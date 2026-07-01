"""Persist preview performance preferences between sessions."""

from __future__ import annotations

from PyQt6.QtCore import QSettings

_ORG = "Film Stockpot"
_APP = "FilmStockpot"

_KEY_GPU = "preview/gpu_acceleration"
_KEY_PREVIEW_MAX = "preview/max_long_edge"
_KEY_DRAG_MAX = "preview/drag_max_long_edge"
_KEY_LIVE_HISTOGRAM = "preview/live_histogram"
_KEY_SHOW_PERF = "preview/show_perf_overlay"

DEFAULT_PREVIEW_MAX = 1800
DEFAULT_DRAG_MAX = 1200


def _settings() -> QSettings:
    return QSettings(_ORG, _APP)


def set_show_perf_overlay(enabled: bool) -> None:
    _settings().setValue(_KEY_SHOW_PERF, bool(enabled))


def gpu_acceleration_enabled() -> bool:
    value = _settings().value(_KEY_GPU, True)
    if isinstance(value, bool):
        return value
    return str(value).lower() not in {"0", "false", "no", "off"}


def set_gpu_acceleration(enabled: bool) -> None:
    _settings().setValue(_KEY_GPU, bool(enabled))


def preview_max_long_edge() -> int:
    return max(640, int(_settings().value(_KEY_PREVIEW_MAX, DEFAULT_PREVIEW_MAX)))


def drag_preview_max_long_edge() -> int:
    return max(480, int(_settings().value(_KEY_DRAG_MAX, DEFAULT_DRAG_MAX)))


def live_histogram_enabled() -> bool:
    value = _settings().value(_KEY_LIVE_HISTOGRAM, True)
    if isinstance(value, bool):
        return value
    return str(value).lower() not in {"0", "false", "no", "off"}


def show_perf_overlay() -> bool:
    value = _settings().value(_KEY_SHOW_PERF, False)
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}
