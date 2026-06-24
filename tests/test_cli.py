"""Tests for the command-line interface."""

from pathlib import Path

import numpy as np
import pytest
import tifffile

from film_stockpot.cli import main
from film_stockpot.cli_exit import EXIT_OK, EXIT_USAGE
from film_stockpot.main import is_cli_invocation


def _write_tiff(path: Path) -> None:
    data = np.full((8, 8, 3), 30000, dtype=np.uint16)
    tifffile.imwrite(path, data, photometric="rgb")


def test_is_cli_invocation() -> None:
    assert is_cli_invocation([]) is False
    assert is_cli_invocation(["export", "scan.tiff"]) is True
    assert is_cli_invocation(["presets", "list"]) is True
    assert is_cli_invocation(["--version"]) is True


def test_presets_list_runs() -> None:
    assert main(["presets", "list"]) == 0


def test_export_requires_stock_without_sidecar_mode(tmp_path: Path) -> None:
    source = tmp_path / "frame.tiff"
    _write_tiff(source)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    assert main(["export", str(source), "-o", str(out_dir), "-q"]) == EXIT_USAGE


def test_export_with_stock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    presets_dir = tmp_path / "FilmPresets"
    presets_dir.mkdir()
    preset_file = presets_dir / "test_stock.json"
    preset_file.write_text(
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
            "-q",
        ]
    )
    assert code == EXIT_OK
    assert (out_dir / "frame_export.tif").is_file()
