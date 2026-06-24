"""Tests for CLI exit codes and JSON reports."""

from pathlib import Path

import json
import numpy as np
import pytest
import tifffile

from film_stockpot.cli import main
from film_stockpot.cli_exit import EXIT_OK, EXIT_RUNTIME, EXIT_USAGE
from film_stockpot.cli_report import build_export_report, compute_export_exit_code
from film_stockpot.export_engine import ExportBatchResult, ExportFileResult


def _write_tiff(path: Path) -> None:
    data = np.full((8, 8, 3), 30000, dtype=np.uint16)
    tifffile.imwrite(path, data, photometric="rgb")


def test_compute_export_exit_code_success() -> None:
    result = ExportBatchResult(exported=2, skipped=1)
    assert compute_export_exit_code(result) == EXIT_OK


def test_compute_export_exit_code_failure() -> None:
    result = ExportBatchResult(failed=1)
    assert compute_export_exit_code(result) == EXIT_RUNTIME


def test_build_export_report_outputs_list(tmp_path: Path) -> None:
    source = tmp_path / "frame.tiff"
    output = tmp_path / "out" / "frame_export.tif"
    result = ExportBatchResult(
        exported=1,
        files=[ExportFileResult(source=source, output=output, status="exported")],
    )
    report = build_export_report(
        result=result,
        input_path=source,
        output_path=tmp_path / "out",
        warnings=[],
        total_jobs=1,
    )
    assert report["status"] == "success"
    assert report["exit_code"] == EXIT_OK
    assert report["outputs"] == [str(output.resolve())]
    assert report["files"][0]["status"] == "exported"


def test_export_json_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    presets_dir = tmp_path / "FilmPresets"
    presets_dir.mkdir()
    (presets_dir / "test_stock.json").write_text(
        '{"id": "test_stock", "name": "Test", "monochrome": false, "pipeline": {}}',
        encoding="utf-8",
    )

    source = tmp_path / "frame.tiff"
    _write_tiff(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    monkeypatch.chdir(tmp_path)
    code = main(
        [
            "export",
            str(source),
            "-o",
            str(out_dir),
            "--stock",
            "test_stock",
            "--presets-dir",
            str(presets_dir),
            "--json",
            "--quiet",
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == EXIT_OK
    assert report["status"] == "success"
    assert report["outputs"] == [str((out_dir / "frame_export.tif").resolve())]
    assert captured.err == ""


def test_export_requires_stock_exit_usage(tmp_path: Path) -> None:
    source = tmp_path / "frame.tiff"
    _write_tiff(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    assert main(["export", str(source), "-o", str(out_dir), "-q"]) == EXIT_USAGE
