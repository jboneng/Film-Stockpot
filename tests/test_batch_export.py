"""Tests for the batch export worker."""

from pathlib import Path

import numpy as np
import tifffile
from PyQt6.QtWidgets import QApplication

from film_stockpot.ui.workers import BatchExportWorker


def _write_tiff(path: Path, value: int = 30000) -> None:
    data = np.full((8, 8, 3), value, dtype=np.uint16)
    tifffile.imwrite(path, data, photometric="rgb")


def _jobs(paths: list[Path]) -> list[dict]:
    return [
        {"path": str(p), "preset": None, "base": None, "adjustments": None}
        for p in paths
    ]


def test_batch_export_writes_all_images(qapp: QApplication, tmp_path: Path) -> None:
    sources = []
    for index in range(3):
        src = tmp_path / f"frame_{index}.tiff"
        _write_tiff(src)
        sources.append(src)

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    results: dict = {}
    worker = BatchExportWorker(_jobs(sources), str(out_dir))
    worker.signals.finished.connect(
        lambda exported, failed, cancelled, errors: results.update(
            exported=exported, failed=failed, cancelled=cancelled, errors=errors
        )
    )
    worker.run()

    assert results["exported"] == 3
    assert results["failed"] == 0
    assert results["cancelled"] is False
    for index in range(3):
        assert (out_dir / f"frame_{index}_export.tif").is_file()


def test_batch_export_emits_progress(qapp: QApplication, tmp_path: Path) -> None:
    src = tmp_path / "frame.tiff"
    _write_tiff(src)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    progress: list[tuple] = []
    worker = BatchExportWorker(_jobs([src]), str(out_dir))
    worker.signals.progress.connect(lambda done, total, name: progress.append((done, total, name)))
    worker.run()

    assert progress[0] == (0, 1, "frame.tiff")
    assert progress[-1] == (1, 1, "")


def test_batch_export_cancel_stops_processing(qapp: QApplication, tmp_path: Path) -> None:
    sources = []
    for index in range(3):
        src = tmp_path / f"frame_{index}.tiff"
        _write_tiff(src)
        sources.append(src)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    worker = BatchExportWorker(_jobs(sources), str(out_dir))
    worker.cancel()
    results: dict = {}
    worker.signals.finished.connect(
        lambda exported, failed, cancelled, errors: results.update(
            exported=exported, cancelled=cancelled
        )
    )
    worker.run()

    assert results["cancelled"] is True
    assert results["exported"] == 0


def test_batch_export_reports_failures(qapp: QApplication, tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.tiff"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    results: dict = {}
    worker = BatchExportWorker(_jobs([missing]), str(out_dir))
    worker.signals.finished.connect(
        lambda exported, failed, cancelled, errors: results.update(
            exported=exported, failed=failed, errors=errors
        )
    )
    worker.run()

    assert results["failed"] == 1
    assert results["exported"] == 0
    assert len(results["errors"]) == 1
