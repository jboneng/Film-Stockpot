"""Log-density analysis helpers for the print stage (GPL-3)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from film_stockpot.image.print.constants import EXPOSURE_CONSTANTS, LUMA_B, LUMA_G, LUMA_R
from film_stockpot.image.print.papers import PROCESS_E6

_EPSILON = 1e-6
_PRINT_DENSITY_LO = -0.92
_PRINT_DENSITY_HI = -0.10


@dataclass(frozen=True)
class LogNegativeBounds:
    floors: tuple[float, float, float]
    ceils: tuple[float, float, float]


def linear_to_log(rgb: np.ndarray) -> np.ndarray:
    safe = np.clip(np.nan_to_num(rgb, nan=_EPSILON, posinf=1.0, neginf=_EPSILON), _EPSILON, 1.0)
    return np.log10(safe).astype(np.float32, copy=False)


def normalize_log_image(img_log: np.ndarray, bounds: LogNegativeBounds) -> np.ndarray:
    floors = np.asarray(bounds.floors, dtype=np.float32)
    ceils = np.asarray(bounds.ceils, dtype=np.float32)
    delta = ceils - floors
    delta = np.where(np.abs(delta) < _EPSILON, np.where(delta >= 0, _EPSILON, -_EPSILON), delta)
    return ((img_log - floors) / delta).astype(np.float32, copy=False)


def _block_median_grid(img_log: np.ndarray) -> np.ndarray:
    height, width = img_log.shape[:2]
    grid = int(EXPOSURE_CONSTANTS["analysis_grid"])
    block = int(np.ceil(max(height, width) / grid))
    if block <= 1 or height < block or width < block:
        return img_log
    hb, wb = (height // block) * block, (width // block) * block
    arr = img_log[:hb, :wb]
    channels = arr.shape[2]
    reshaped = arr.reshape(hb // block, block, wb // block, block, channels)
    return np.median(reshaped, axis=(1, 3))


def _sample_log_bounds(
    img_log: np.ndarray,
    percentile_clip: float,
    base: float,
    process_mode: str,
) -> tuple[list[float], list[float]]:
    if percentile_clip >= 0:
        clip = max(0.00001, min(50.0, percentile_clip + base))
        margin = 0.0
    else:
        clip = base
        margin = -percentile_clip
    p_low, p_high = float(clip), float(100.0 - clip)
    fixed_range = -3.0 if process_mode == PROCESS_E6 else 3.0
    if process_mode == PROCESS_E6:
        p_low, p_high = p_high, p_low

    floors = [float(np.percentile(img_log[:, :, ch], p_low)) for ch in range(3)]
    ceils = []
    for ch in range(3):
        data = img_log[:, :, ch]
        if process_mode != PROCESS_E6:
            ceils.append(float(np.percentile(data, p_high)))
        else:
            ceils.append(float(floors[ch] + fixed_range))

    if margin > 0.0:
        for ch in range(3):
            if ceils[ch] >= floors[ch]:
                floors[ch] -= margin
                ceils[ch] += margin
            else:
                floors[ch] += margin
                ceils[ch] -= margin
    return floors, ceils


def analyze_log_exposure_bounds(
    rgb: np.ndarray,
    *,
    process_mode: str = "c41",
    percentile_clip: float = 0.0,
    color_clip: float = 0.0,
) -> LogNegativeBounds:
    img_log = _block_median_grid(linear_to_log(rgb))
    base_luma = float(EXPOSURE_CONSTANTS["base_luma_clip"])
    floors, ceils = _sample_log_bounds(img_log, percentile_clip, base_luma, process_mode)
    color_floors, color_ceils = _sample_log_bounds(img_log, color_clip, 0.0, process_mode)
    mean_lf, mean_lc = sum(floors) / 3.0, sum(ceils) / 3.0
    mean_cf, mean_cc = sorted(color_floors)[1], sorted(color_ceils)[1]
    floors = [mean_lf + (color_floors[ch] - mean_cf) for ch in range(3)]
    ceils = [mean_lc + (color_ceils[ch] - mean_cc) for ch in range(3)]
    return LogNegativeBounds((floors[0], floors[1], floors[2]), (ceils[0], ceils[1], ceils[2]))


def luminance_density_range(bounds: LogNegativeBounds) -> float:
    rr = abs(bounds.ceils[0] - bounds.floors[0])
    rg = abs(bounds.ceils[1] - bounds.floors[1])
    rb = abs(bounds.ceils[2] - bounds.floors[2])
    return float(LUMA_R * rr + LUMA_G * rg + LUMA_B * rb)


def measure_anchor_from_log(img_log: np.ndarray, bounds: LogNegativeBounds) -> float:
    img_log = _block_median_grid(img_log)
    norm = normalize_log_image(img_log, bounds)
    lum = LUMA_R * norm[:, :, 0] + LUMA_G * norm[:, :, 1] + LUMA_B * norm[:, :, 2]
    measured = float(np.percentile(lum, float(EXPOSURE_CONSTANTS["anchor_meter_percentile"])))
    assumed = float(EXPOSURE_CONSTANTS["assumed_anchor"])
    strength = float(EXPOSURE_CONSTANTS["anchor_meter_strength"])
    band = float(EXPOSURE_CONSTANTS["anchor_meter_band"])
    anchor = assumed + strength * (measured - assumed)
    return float(min(max(anchor, assumed - band), assumed + band))


def measure_anchor(rgb: np.ndarray, bounds: LogNegativeBounds) -> float:
    return measure_anchor_from_log(linear_to_log(rgb), bounds)


def measure_textural_range_from_log(img_log: np.ndarray) -> float:
    img_log = _block_median_grid(img_log)
    lum = LUMA_R * img_log[:, :, 0] + LUMA_G * img_log[:, :, 1] + LUMA_B * img_log[:, :, 2]
    clip = float(EXPOSURE_CONSTANTS["textural_range_clip"])
    lo, hi = np.percentile(lum, [clip, 100.0 - clip])
    return float(abs(hi - lo))


def measure_textural_range(rgb: np.ndarray) -> float:
    return measure_textural_range_from_log(linear_to_log(rgb))


def measure_shadow_log_refs(rgb: np.ndarray) -> tuple[float, float, float]:
    img_log = _block_median_grid(linear_to_log(rgb))
    percentile = float(EXPOSURE_CONSTANTS["shadow_neutral_percentile"])
    return (
        float(np.percentile(img_log[:, :, 0], percentile)),
        float(np.percentile(img_log[:, :, 1], percentile)),
        float(np.percentile(img_log[:, :, 2], percentile)),
    )


def measure_neutral_axis(rgb: np.ndarray, bounds: LogNegativeBounds) -> tuple | None:
    img_log = _block_median_grid(linear_to_log(rgb))
    norm = normalize_log_image(img_log, bounds)
    luma = LUMA_R * norm[:, :, 0] + LUMA_G * norm[:, :, 1] + LUMA_B * norm[:, :, 2]
    chroma = norm.max(axis=2) - norm.min(axis=2)
    flat_log = img_log.reshape(-1, 3)
    luma_f = luma.reshape(-1)
    chroma_f = chroma.reshape(-1)
    constants = EXPOSURE_CONSTANTS
    quantile = float(constants["neutral_axis_chroma_quantile"])
    cap = float(constants["neutral_axis_chroma_cap"])
    min_pixels = int(constants["neutral_axis_min_pixels"])

    def _band_refs(lo: float, hi: float) -> tuple[tuple[float, float, float], float] | None:
        band = (luma_f >= lo) & (luma_f <= hi)
        if int(band.sum()) < min_pixels:
            return None
        band_chroma = chroma_f[band]
        threshold = float(np.quantile(band_chroma, quantile))
        idx = np.nonzero(band)[0][band_chroma <= threshold]
        near_neutral = float(np.median(chroma_f[idx])) if idx.size else cap
        if idx.size < min_pixels or near_neutral > cap:
            return None
        refs = (
            float(np.median(flat_log[idx, 0])),
            float(np.median(flat_log[idx, 1])),
            float(np.median(flat_log[idx, 2])),
        )
        return refs, near_neutral

    mid = _band_refs(float(constants["neutral_axis_mid_band"][0]), float(constants["neutral_axis_mid_band"][1]))
    shadow = _band_refs(float(constants["neutral_axis_shadow_band"][0]), float(constants["neutral_axis_shadow_band"][1]))
    if mid is None or shadow is None:
        return None
    highlight = _band_refs(
        float(constants["neutral_axis_highlight_band"][0]),
        float(constants["neutral_axis_highlight_band"][1]),
    )
    confidence = float(np.clip(1.0 - mid[1] / cap, 0.0, 1.0))
    return (mid[0], shadow[0], highlight[0] if highlight is not None else None, confidence)


def normalize_refs(
    refs: tuple[float, float, float],
    floors: tuple[float, float, float],
    ceils: tuple[float, float, float],
) -> tuple[float, float, float]:
    out = []
    for ch in range(3):
        denom = ceils[ch] - floors[ch]
        if abs(denom) < _EPSILON:
            denom = _EPSILON if denom >= 0 else -_EPSILON
        out.append((refs[ch] - floors[ch]) / denom)
    return (out[0], out[1], out[2])


def normalized_shadow_refs(
    bounds: LogNegativeBounds,
    refs: tuple[float, float, float] | None,
) -> tuple[float, float, float] | None:
    if refs is None:
        return None
    return normalize_refs(refs, bounds.floors, bounds.ceils)


def normalized_neutral_axis(
    bounds: LogNegativeBounds,
    refs: tuple | None,
) -> tuple | None:
    if refs is None:
        return None
    mid, shadow, highlight = refs[0], refs[1], refs[2]

    def _norm(channel_refs: tuple[float, float, float] | None) -> tuple[float, float, float] | None:
        return normalize_refs(channel_refs, bounds.floors, bounds.ceils) if channel_refs is not None else None

    return (_norm(mid), _norm(shadow), _norm(highlight))


def default_log_bounds(*, process_mode: str = "c41") -> LogNegativeBounds:
    """Fixed C-41 bounds for display-referred print input."""
    if process_mode == PROCESS_E6:
        return LogNegativeBounds((0.10, 0.10, 0.10), (0.92, 0.92, 0.92))
    return LogNegativeBounds(
        (_PRINT_DENSITY_LO, _PRINT_DENSITY_LO, _PRINT_DENSITY_LO),
        (_PRINT_DENSITY_HI, _PRINT_DENSITY_HI, _PRINT_DENSITY_HI),
    )


def is_display_referred(rgb: np.ndarray) -> bool:
    """True when ``rgb`` looks like a display-linear film-grade buffer."""
    img = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    return float(img.min()) < 0.015 and float(img.max()) > 0.985


def flat_scan_to_normalized_log(flat: np.ndarray) -> np.ndarray:
    """Decode a flat/log TIFF scan back to normalized negative log."""
    gain = float(EXPOSURE_CONSTANTS["flat_log_gain"])
    lift = float(EXPOSURE_CONSTANTS["flat_log_lift"])
    img = np.clip(np.asarray(flat, dtype=np.float32), 0.0, 1.0)
    return np.clip(1.0 - (img - lift) / gain, 0.0, 1.0).astype(np.float32, copy=False)


def norm_log_to_transmittance(norm_log: np.ndarray) -> np.ndarray:
    """Rebuild linear negative transmittance from normalized log (for analysis helpers)."""
    scaled = _PRINT_DENSITY_LO + np.clip(norm_log, 0.0, 1.0) * (_PRINT_DENSITY_HI - _PRINT_DENSITY_LO)
    return np.clip(np.power(10.0, scaled), _EPSILON, 1.0).astype(np.float32, copy=False)


def bridge_scan_to_print_linear(rgb: np.ndarray) -> np.ndarray:
    """Legacy remap for flat sources without flat-master encoding."""
    return norm_log_to_transmittance(flat_scan_to_normalized_log(rgb))


def display_to_normalized_log(rgb: np.ndarray) -> np.ndarray:
    """Approximate normalized negative log from a display-linear film image."""
    img = np.clip(np.asarray(rgb, dtype=np.float32), 0.0, 1.0)
    anchor = float(EXPOSURE_CONSTANTS["assumed_anchor"])
    span_scale = 0.35
    out = np.empty_like(img)
    for ch in range(3):
        plane = img[:, :, ch]
        lo, hi = np.percentile(plane, [2.0, 98.0])
        mid = 0.5 * (float(lo) + float(hi))
        span = max(float(hi) - float(lo), 0.05)
        # Bright display values are low negative density (high print transmittance).
        out[:, :, ch] = np.clip(anchor - (plane - mid) / span * span_scale, 0.0, 1.0)
    return out.astype(np.float32, copy=False)


def measure_anchor_from_normalized(norm_log: np.ndarray) -> float:
    lum = LUMA_R * norm_log[:, :, 0] + LUMA_G * norm_log[:, :, 1] + LUMA_B * norm_log[:, :, 2]
    measured = float(np.percentile(lum, float(EXPOSURE_CONSTANTS["anchor_meter_percentile"])))
    assumed = float(EXPOSURE_CONSTANTS["assumed_anchor"])
    strength = float(EXPOSURE_CONSTANTS["anchor_meter_strength"])
    band = float(EXPOSURE_CONSTANTS["anchor_meter_band"])
    anchor = assumed + strength * (measured - assumed)
    return float(min(max(anchor, assumed - band), assumed + band))


def measure_textural_range_from_normalized(norm_log: np.ndarray) -> float:
    lum = LUMA_R * norm_log[:, :, 0] + LUMA_G * norm_log[:, :, 1] + LUMA_B * norm_log[:, :, 2]
    clip = float(EXPOSURE_CONSTANTS["textural_range_clip"])
    lo, hi = np.percentile(lum, [clip, 100.0 - clip])
    return float(abs(hi - lo))


def rgb_to_normalized_log(rgb: np.ndarray, *, process_mode: str = "c41") -> tuple[np.ndarray, LogNegativeBounds]:
    bounds = analyze_log_exposure_bounds(rgb, process_mode=process_mode)
    img_log = linear_to_log(rgb)
    return normalize_log_image(img_log, bounds), bounds
