"""Film-stock emulation pipeline.

Applies a single film preset to a flat/log float32 RGB image (values in 0..1).
The pipeline is intentionally stateless: callers always pass the pristine
original image, so applying a different preset never stacks on a prior result.
"""

from __future__ import annotations

import numpy as np

_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_DEFAULT_MONO_MIXER = np.array([0.299, 0.587, 0.114], dtype=np.float32)
_GRAIN_MAX_SIGMA = 0.035


def apply_film_preset(rgb: np.ndarray, preset: dict, base: dict | None = None) -> np.ndarray:
    """Return a new float32 RGB array with the preset's film look applied.

    If ``base`` is provided and defines an ``input_transform``, that de-log /
    scan-normalization stage runs first to expand a flat/log input back to full
    range, preventing the washed-out result that comes from grading a log scan
    directly. The film look is then applied on top.

    The input is never modified. Output values are clipped to 0..1.
    """
    image = np.clip(rgb.astype(np.float32, copy=True), 0.0, 1.0)

    if base:
        image = _apply_input_transform(image, base.get("input_transform"))

    pipeline = preset.get("pipeline", {})
    look = pipeline.get("look", {}) or {}
    scanner = pipeline.get("scanner_adjustments", {}) or {}
    monochrome = bool(preset.get("monochrome", False))

    if monochrome:
        image = _to_monochrome(image, look.get("mono_mixer"))
    else:
        image = _apply_color_matrix(image, look.get("color_matrix"))
        image = _apply_white_balance(image, pipeline.get("white_balance", {}))

    image = np.clip(image, 0.0, 1.0)
    image = _apply_tone_curve(image, pipeline.get("tone_curve_8bit"))
    image = _apply_contrast(image, look.get("contrast_pct", 0))
    image = _apply_lift_gain(image, look.get("lift", 0.0), look.get("gain", 1.0))
    image = _apply_gamma(image, scanner.get("gamma", 1.0))
    image = _apply_highlights_shadows(
        image,
        scanner.get("highlights", 0),
        scanner.get("shadows", 0),
    )
    image = np.clip(image, 0.0, 1.0)

    if not monochrome:
        image = _apply_saturation(image, scanner.get("saturation_pct", 100))
        image = np.clip(image, 0.0, 1.0)

    grain = pipeline.get("grain", {}) or {}
    image = _apply_grain(image, grain.get("intensity", 0.0) or 0.0)

    return np.clip(image, 0.0, 1.0).astype(np.float32)


def _apply_input_transform(image: np.ndarray, transform: dict | None) -> np.ndarray:
    """Expand a flat/log input to full range before the film look is applied."""
    if not transform:
        return image

    result = image
    if transform.get("auto_levels", False):
        result = _auto_levels(
            result,
            float(transform.get("black_clip_pct", 0.0) or 0.0),
            float(transform.get("white_clip_pct", 0.0) or 0.0),
            bool(transform.get("per_channel", False)),
        )

    strength = float(transform.get("delog_strength", 0.0) or 0.0)
    if strength > 0.0:
        result = _apply_delog(result, strength)

    gamma = float(transform.get("gamma", 1.0) or 1.0)
    if gamma > 0.0 and gamma != 1.0:
        result = np.clip(result, 0.0, 1.0) ** (1.0 / gamma)

    return np.clip(result, 0.0, 1.0)


def _auto_levels(image: np.ndarray, black_clip_pct: float, white_clip_pct: float, per_channel: bool) -> np.ndarray:
    if per_channel:
        out = np.empty_like(image)
        for channel in range(image.shape[2]):
            data = image[:, :, channel]
            low = np.percentile(data, black_clip_pct)
            high = np.percentile(data, 100.0 - white_clip_pct)
            out[:, :, channel] = _stretch(data, float(low), float(high))
        return out

    luma = np.sum(image * _LUMA_WEIGHTS, axis=-1)
    low = float(np.percentile(luma, black_clip_pct))
    high = float(np.percentile(luma, 100.0 - white_clip_pct))
    return _stretch(image, low, high)


def _stretch(data: np.ndarray, low: float, high: float) -> np.ndarray:
    if high <= low:
        return data
    return (data - low) / (high - low)


def _apply_delog(image: np.ndarray, strength: float) -> np.ndarray:
    clipped = np.clip(image, 0.0, 1.0)
    s_curve = clipped * clipped * (3.0 - 2.0 * clipped)
    return clipped * (1.0 - strength) + s_curve * strength


def _to_monochrome(image: np.ndarray, mixer: list | None) -> np.ndarray:
    weights = np.array(mixer, dtype=np.float32) if mixer else _DEFAULT_MONO_MIXER
    luma = image @ weights
    return np.repeat(luma[:, :, np.newaxis], 3, axis=2)


def _apply_color_matrix(image: np.ndarray, matrix: list | None) -> np.ndarray:
    if not matrix:
        return image
    mat = np.array(matrix, dtype=np.float32)
    return image @ mat.T


def _apply_white_balance(image: np.ndarray, white_balance: dict) -> np.ndarray:
    gains = (white_balance or {}).get("rgb_gains")
    if not gains:
        return image
    return image * np.array(gains, dtype=np.float32)


def _apply_tone_curve(image: np.ndarray, curve: list | None) -> np.ndarray:
    if not curve:
        return image
    xs = np.array([point[0] for point in curve], dtype=np.float32) / 255.0
    ys = np.array([point[1] for point in curve], dtype=np.float32) / 255.0
    order = np.argsort(xs)
    return np.interp(image, xs[order], ys[order]).astype(np.float32)


def _apply_contrast(image: np.ndarray, contrast_pct: float) -> np.ndarray:
    factor = float(contrast_pct) / 100.0
    if factor == 0.0:
        return image
    return (image - 0.5) * (1.0 + factor) + 0.5


def _apply_lift_gain(image: np.ndarray, lift: float, gain: float) -> np.ndarray:
    lift = float(lift)
    gain = float(gain)
    if lift == 0.0 and gain == 1.0:
        return image
    return image * gain + lift


def _apply_gamma(image: np.ndarray, gamma: float) -> np.ndarray:
    gamma = float(gamma)
    if gamma <= 0.0 or gamma == 1.0:
        return image
    return np.clip(image, 0.0, 1.0) ** (1.0 / gamma)


def _apply_highlights_shadows(image: np.ndarray, highlights: float, shadows: float) -> np.ndarray:
    highlights = float(highlights) / 100.0
    shadows = float(shadows) / 100.0
    if highlights == 0.0 and shadows == 0.0:
        return image
    result = image
    if shadows != 0.0:
        result = result + shadows * (1.0 - result) * 0.5
    if highlights != 0.0:
        result = result + highlights * result * 0.5
    return result


def _apply_saturation(image: np.ndarray, saturation_pct: float) -> np.ndarray:
    factor = float(saturation_pct) / 100.0
    if factor == 1.0:
        return image
    luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)
    return luma + (image - luma) * factor


def _apply_grain(image: np.ndarray, intensity: float) -> np.ndarray:
    intensity = float(intensity)
    if intensity <= 0.0:
        return image
    sigma = _GRAIN_MAX_SIGMA * intensity
    height, width = image.shape[:2]
    noise = np.random.normal(0.0, sigma, (height, width, 1)).astype(np.float32)
    luma = np.mean(image, axis=-1, keepdims=True)
    midtone_mask = 1.0 - np.abs(luma - 0.5)
    return image + noise * midtone_mask
