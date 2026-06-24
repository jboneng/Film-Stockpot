"""Persist recently opened folders between sessions."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

_ORG = "Film Stockpot"
_APP = "FilmStockpot"
_KEY_LAST = "paths/last_folder"
_KEY_RECENT = "paths/recent_folders"
_MAX_RECENT = 10


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def last_folder() -> str | None:
    value = _settings().value(_KEY_LAST, "")
    if not value:
        return None
    return str(value)


def remember_folder(path: str) -> None:
    normalized = str(path)
    store = _settings()
    store.setValue(_KEY_LAST, normalized)

    recent = load_recent_folders()
    recent = [entry for entry in recent if entry != normalized]
    recent.insert(0, normalized)
    store.setValue(_KEY_RECENT, recent[:_MAX_RECENT])


def load_recent_folders() -> list[str]:
    value = _settings().value(_KEY_RECENT, [])
    if not value:
        return []
    if isinstance(value, list):
        return [str(entry) for entry in value if entry]
    return [str(value)]
