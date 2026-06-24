"""Tests for CLI console progress output."""

import sys

from film_stockpot.console_io import ExportProgress


def test_export_progress_disabled_does_not_crash(capsys) -> None:
    progress = ExportProgress(enabled=False)
    progress.begin(3)
    progress.update(0, 3, "frame.tiff")
    progress.finish(exported=1, skipped=0, failed=0, cancelled=False)


def test_export_progress_finish_stops_spinner(monkeypatch) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    progress = ExportProgress(enabled=True)
    progress.begin(1)
    progress.update(0, 1, "frame.tiff")
    progress.finish(exported=1, skipped=0, failed=0, cancelled=False)
    assert progress._spinner_thread is None
