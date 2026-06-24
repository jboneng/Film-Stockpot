"""Persist export preferences between sessions."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from film_stockpot.export_naming import DEFAULT_TEMPLATE

_ORG = "Film Stockpot"
_APP = "FilmStockpot"
_KEY_NAME_TEMPLATE = "export/name_template"


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def load_name_template() -> str:
    value = _settings().value(_KEY_NAME_TEMPLATE, DEFAULT_TEMPLATE)
    return str(value) if value else DEFAULT_TEMPLATE


def save_name_template(template: str) -> None:
    _settings().setValue(_KEY_NAME_TEMPLATE, template.strip() or DEFAULT_TEMPLATE)
