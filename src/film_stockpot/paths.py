"""Resolve application paths in development and frozen (PyInstaller) builds."""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent


def is_frozen() -> bool:
    """Return True when running as a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def meipass_root() -> Path | None:
    """Return PyInstaller's temporary extraction directory, if present."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def executable_dir() -> Path:
    """Return the directory containing the running executable."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def repo_root() -> Path:
    """Return the repository root when running from a source checkout."""
    return _PACKAGE_ROOT.parent.parent
