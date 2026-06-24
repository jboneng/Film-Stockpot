"""Tests for the headless export engine."""

from pathlib import Path

import numpy as np
import tifffile

from film_stockpot.export_engine import build_export_jobs, export_batch, resolve_output_path
from film_stockpot.sidecar import write_sidecar


def _write_tiff(path: Path, value: int = 30000) -> None:
    data = np.full((8, 8, 3), value, dtype=np.uint16)
    tifffile.imwrite(path, data, photometric="rgb")


def test_build_export_jobs_prefers_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "frame.tiff"
    _write_tiff(source)
    write_sidecar(
        source,
        preset={"id": "from_sidecar", "pipeline": {}},
        base={"input_transform": {}},
        adjustments={"density": 2},
    )

    jobs, warnings = build_export_jobs(
        [source],
        fallback_preset={"id": "fallback"},
        fallback_base=None,
        fallback_adjustments={"density": 0},
    )

    assert warnings == []
    assert jobs[0]["preset"]["id"] == "from_sidecar"
    assert jobs[0]["adjustments"]["density"] == 2


def test_build_export_jobs_uses_stock_fallback(tmp_path: Path) -> None:
    source = tmp_path / "frame.tiff"
    _write_tiff(source)

    jobs, warnings = build_export_jobs(
        [source],
        fallback_preset={"id": "kodak_gold_200"},
        fallback_base={"input_transform": {}},
        fallback_adjustments={"gamma": 1},
    )

    assert warnings == []
    assert jobs[0]["preset"]["id"] == "kodak_gold_200"


def test_export_batch_writes_and_skips_existing(tmp_path: Path) -> None:
    source = tmp_path / "frame.tiff"
    _write_tiff(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    jobs = [{"path": str(source), "preset": None, "base": None, "adjustments": None}]

    first = export_batch(jobs, output=out_dir, single_input=False, overwrite=False)
    assert first.exported == 1
    assert first.skipped == 0
    assert (out_dir / "frame_export.tif").is_file()

    second = export_batch(jobs, output=out_dir, single_input=False, overwrite=False)
    assert second.exported == 0
    assert second.skipped == 1

    third = export_batch(jobs, output=out_dir, single_input=False, overwrite=True)
    assert third.exported == 1
    assert third.skipped == 0


def test_resolve_output_path_single_file() -> None:
    source = Path("scan.tiff")
    assert resolve_output_path(source, Path("out.tif"), single_input=True) == Path("out.tif")
    assert resolve_output_path(source, Path("out"), single_input=True) == Path("out/scan_export.tif")


def test_export_batch_cancelled(tmp_path: Path) -> None:
    sources = []
    for index in range(3):
        src = tmp_path / f"frame_{index}.tiff"
        _write_tiff(src)
        sources.append(src)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    jobs = [{"path": str(p), "preset": None, "base": None, "adjustments": None} for p in sources]

    result = export_batch(
        jobs,
        output=out_dir,
        single_input=False,
        is_cancelled=lambda: True,
    )
    assert result.cancelled is True
    assert result.exported == 0
