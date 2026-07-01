"""RGB + luma curve adjustments for interactive grading."""

from __future__ import annotations

from typing import Any

import numpy as np

_LUT_SIZE = 256
_LUT_INPUT = np.linspace(0.0, 1.0, _LUT_SIZE, dtype=np.float32)
_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_CHANNELS = ("L", "R", "G", "B")
_DEFAULT_POINTS: list[list[float]] = [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]]

CURVES_NEUTRAL: dict[str, list[list[float]]] = {
    channel: [point[:] for point in _DEFAULT_POINTS] for channel in _CHANNELS
}


def normalize_curves(curves: dict | None) -> dict[str, list[list[float]]]:
    """Return complete curve control points for every channel."""
    source = curves or {}
    return {channel: normalize_curve_points(source.get(channel)) for channel in _CHANNELS}


def normalize_curve_points(points: list | None) -> list[list[float]]:
    """Sanitize one channel's control points."""
    if not points:
        return [point[:] for point in _DEFAULT_POINTS]

    cleaned: list[list[float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x = float(np.clip(point[0], 0.0, 1.0))
        y = float(np.clip(point[1], 0.0, 1.0))
        cleaned.append([x, y])

    if not cleaned:
        return [point[:] for point in _DEFAULT_POINTS]

    cleaned.sort(key=lambda item: item[0])
    merged: list[list[float]] = []
    for x, y in cleaned:
        if merged and abs(x - merged[-1][0]) < 1e-4:
            merged[-1][1] = y
        else:
            merged.append([x, y])

    if merged[0][0] > 0.0:
        merged.insert(0, [0.0, merged[0][1]])
    else:
        merged[0][0] = 0.0

    if merged[-1][0] < 1.0:
        merged.append([1.0, merged[-1][1]])
    else:
        merged[-1][0] = 1.0

    return merged


def curves_is_neutral(curves: dict | None) -> bool:
    """True when every channel is the default identity curve."""
    normalized = normalize_curves(curves)
    return normalized == normalize_curves(CURVES_NEUTRAL)


def has_curve_adjustments(curves: dict | None) -> bool:
    """True when any channel deviates from the identity curve."""
    return not curves_is_neutral(curves)


def build_curve_lut(points: list[list[float]]) -> np.ndarray:
    """Build a 256-entry lookup table from sorted control points."""
    normalized = normalize_curve_points(points)
    xs = np.array([point[0] for point in normalized], dtype=np.float32)
    ys = np.array([point[1] for point in normalized], dtype=np.float32)
    return np.interp(_LUT_INPUT, xs, ys).astype(np.float32, copy=False)


def evaluate_curve(points: list[list[float]], x: float) -> float:
    """Evaluate the curve at a single input value."""
    normalized = normalize_curve_points(points)
    xs = [point[0] for point in normalized]
    ys = [point[1] for point in normalized]
    return float(np.interp(float(x), xs, ys))


def apply_lut(values: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Map float values in 0..1 through a precomputed LUT."""
    return np.interp(values, _LUT_INPUT, lut).astype(np.float32, copy=False)


def apply_curves(rgb: np.ndarray, curves: dict | None) -> np.ndarray:
    """Apply L/R/G/B curves to a float32 RGB image in 0..1."""
    normalized = normalize_curves(curves)
    if curves_is_neutral(normalized):
        return rgb

    image = np.clip(rgb, 0.0, 1.0).astype(np.float32, copy=False)
    l_lut = build_curve_lut(normalized["L"])
    r_lut = build_curve_lut(normalized["R"])
    g_lut = build_curve_lut(normalized["G"])
    b_lut = build_curve_lut(normalized["B"])

    if not np.allclose(l_lut, _LUT_INPUT):
        luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)
        new_luma = apply_lut(luma, l_lut)
        scale = np.ones_like(luma, dtype=np.float32)
        np.divide(new_luma, luma, out=scale, where=luma > 1e-6)
        image = np.clip(image * scale, 0.0, 1.0)

    if not np.allclose(r_lut, _LUT_INPUT):
        image[..., 0] = apply_lut(image[..., 0], r_lut)
    if not np.allclose(g_lut, _LUT_INPUT):
        image[..., 1] = apply_lut(image[..., 1], g_lut)
    if not np.allclose(b_lut, _LUT_INPUT):
        image[..., 2] = apply_lut(image[..., 2], b_lut)

    return np.clip(image, 0.0, 1.0).astype(np.float32, copy=False)
