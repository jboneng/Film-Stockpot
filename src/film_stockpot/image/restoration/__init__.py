"""Dust / hair / scratch defect detection and removal."""

from __future__ import annotations

from film_stockpot.image.restoration.detect import generate_defect_mask, mask_coverage
from film_stockpot.image.restoration.inpaint import remove_defects
from film_stockpot.image.restoration.params import (
    DEFECT_NEUTRAL,
    INPAINT_METHODS,
    INPAINT_NS,
    INPAINT_TELEA,
    DefectParams,
)

__all__ = [
    "DEFECT_NEUTRAL",
    "DefectParams",
    "INPAINT_METHODS",
    "INPAINT_NS",
    "INPAINT_TELEA",
    "generate_defect_mask",
    "mask_coverage",
    "remove_defects",
]
