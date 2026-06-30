"""Preview stage labels and helpers for the interactive viewer."""

from __future__ import annotations

from enum import StrEnum

import numpy as np

from film_stockpot.image.pipeline import (
    apply_base_input_transform,
    apply_film_preset,
    apply_pre_neutralize_input_transform,
)
from film_stockpot.image.scanner import apply_scanner_adjustments


class PreviewStage(StrEnum):
    FLAT = "flat"
    BASE = "base"
    FILM = "film"
    FULL = "full"


STAGE_LABELS = {
    PreviewStage.FLAT: "Flat",
    PreviewStage.BASE: "Base graded",
    PreviewStage.FILM: "Film stock",
    PreviewStage.FULL: "Film + adjustments",
}


def compute_base_graded(flat: np.ndarray, base: dict | None) -> np.ndarray:
    """Return the flat scan after the shared base input transform only."""
    return apply_base_input_transform(flat, base)


def compute_pre_neutralize(flat: np.ndarray, base: dict | None) -> np.ndarray:
    """Return the flat scan after base auto-levels, before neutralize/crosstalk."""
    return apply_pre_neutralize_input_transform(flat, base)


def compute_full_graded(film: np.ndarray, adjustments: dict | None) -> np.ndarray:
    """Return the film-stock image with Frontier-style operator adjustments."""
    return apply_scanner_adjustments(film, adjustments)
