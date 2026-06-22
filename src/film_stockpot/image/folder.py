"""Helpers for discovering image files in folders."""

from __future__ import annotations

from pathlib import Path

_TIFF_EXTENSIONS = {".tif", ".tiff"}


def list_tiff_files(directory: str | Path) -> list[Path]:
    """Return TIFF files in a folder, sorted by filename."""
    folder = Path(directory)
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder}")

    return sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in _TIFF_EXTENSIONS),
        key=lambda path: path.name.lower(),
    )
