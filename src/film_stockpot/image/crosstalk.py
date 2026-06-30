"""Spectral crosstalk correction (NegPy-compatible density unmixing).

Matrices are stored in each film preset JSON under ``pipeline.crosstalk.matrix``.
Film Stockpot does not read NegPy TOML files at runtime.

The UI slider runs 0.00..1.00 where 0 is off, 0.5 is the default, and 1 applies
the full calibrated matrix.
"""

from __future__ import annotations

import numpy as np

_EPSILON = 1e-6

CROSSTALK_MIN = 0.0
CROSSTALK_MAX = 1.0
CROSSTALK_DEFAULT = 0.5
CROSSTALK_PRECISION = 100


def normalize_crosstalk_amount(value: float) -> float:
    """Return a 0..1 crosstalk amount, migrating older sidecar scales."""
    if value > 2.0 + 1e-6:
        return float(np.clip(value / 100.0, CROSSTALK_MIN, CROSSTALK_MAX))
    if value > 1.0 + 1e-6:
        return float(np.clip(value - 1.0, CROSSTALK_MIN, CROSSTALK_MAX))
    return float(np.clip(value, CROSSTALK_MIN, CROSSTALK_MAX))


def crosstalk_amount_to_strength(amount: float) -> float:
    return normalize_crosstalk_amount(amount)


def crosstalk_amount_to_slider(amount: float) -> int:
    return int(round(normalize_crosstalk_amount(amount) * CROSSTALK_PRECISION))


def crosstalk_slider_to_amount(slider_value: int) -> float:
    return normalize_crosstalk_amount(slider_value / CROSSTALK_PRECISION)


def format_crosstalk_amount(amount: float) -> str:
    return f"{normalize_crosstalk_amount(amount):.2f}"


# Backward-compatible aliases for older call sites/tests.
normalize_crosstalk_separation = normalize_crosstalk_amount
crosstalk_separation_to_strength = crosstalk_amount_to_strength
crosstalk_separation_to_slider = crosstalk_amount_to_slider
crosstalk_slider_to_separation = crosstalk_slider_to_amount
format_crosstalk_separation = format_crosstalk_amount


def preset_crosstalk_matrix(preset: dict | None) -> list[list[float]] | None:
    if not preset:
        return None
    block = (preset.get("pipeline") or {}).get("crosstalk") or {}
    matrix = block.get("matrix")
    if not matrix or len(matrix) != 3:
        return None
    if any(len(row) != 3 for row in matrix):
        return None
    return matrix


def preset_has_crosstalk(preset: dict | None) -> bool:
    return preset_crosstalk_matrix(preset) is not None


def _limit_positive_rgb_delta(reference: np.ndarray, corrected: np.ndarray) -> np.ndarray:
    """Limit channel increases to available headroom without attenuating decreases."""
    delta = corrected - reference
    positive = np.maximum(delta, 0.0)
    negative = np.minimum(delta, 0.0)
    headroom = np.maximum(1.0 - reference, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.where(positive > 1e-8, headroom / positive, np.inf)
    scale = np.min(ratios, axis=-1, keepdims=True)
    scale = np.where(np.isfinite(scale), np.minimum(scale, 1.0), 1.0)
    return np.clip(reference + positive * scale.astype(np.float32) + negative, 0.0, 1.0)


def apply_spectral_crosstalk(
    rgb: np.ndarray,
    matrix: list[list[float]] | None,
    strength: float,
) -> np.ndarray:
    """Unmix dye-layer crosstalk in density space (matches NegPy Lab logic).

    ``strength`` is 0..1 where 0 is identity and 1 applies the full calibrated
    matrix (after row normalization). Results are anchored and gamut-mapped to
    avoid single-channel clipping in downstream film stages.
    """
    if matrix is None or strength <= 0.0 or rgb.ndim != 3 or rgb.shape[2] < 3:
        return rgb

    strength = float(np.clip(strength, 0.0, 1.0))
    cal = np.array(matrix, dtype=np.float64)
    identity = np.eye(3, dtype=np.float64)
    applied = identity * (1.0 - strength) + cal * strength
    row_sums = np.sum(applied, axis=1, keepdims=True)
    applied = applied / np.maximum(row_sums, 1e-6)

    clipped = np.clip(rgb.astype(np.float32, copy=False), _EPSILON, 1.0)
    density = -np.log10(clipped)
    mixed = np.einsum("hwc,kc->hwk", density, applied.astype(np.float32))
    mixed = np.maximum(mixed, 0.0)
    out = np.power(10.0, -mixed, dtype=np.float32)
    return _limit_positive_rgb_delta(clipped, out)


def apply_preset_crosstalk(
    rgb: np.ndarray,
    preset: dict | None,
    strength: float,
) -> np.ndarray:
    return apply_spectral_crosstalk(rgb, preset_crosstalk_matrix(preset), strength)


def crosstalk_strength_from_adjustments(adjustments: dict | None) -> float:
    if not adjustments:
        return 0.0
    return crosstalk_amount_to_strength(float(adjustments.get("crosstalk", CROSSTALK_DEFAULT)))
