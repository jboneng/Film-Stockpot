"""Tests for folder TIFF discovery."""

from pathlib import Path

import pytest

from film_stockpot.image.folder import list_tiff_files


def test_list_tiff_files_finds_tifs(tmp_path: Path) -> None:
    (tmp_path / "b.tif").write_bytes(b"")
    (tmp_path / "a.TIFF").write_bytes(b"")
    (tmp_path / "note.txt").write_bytes(b"")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.tif").write_bytes(b"")

    files = list_tiff_files(tmp_path)

    assert [path.name for path in files] == ["a.TIFF", "b.tif"]


def test_list_tiff_files_missing_directory_raises() -> None:
    with pytest.raises(NotADirectoryError):
        list_tiff_files("missing-folder")
