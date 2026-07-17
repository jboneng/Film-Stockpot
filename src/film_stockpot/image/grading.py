"""Interactive shadow / midtone / highlight color-wheel grading."""

from __future__ import annotations

import colorsys
import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from film_stockpot.image.curves import (
    CURVES_NEUTRAL,
    apply_curves,
    has_curve_adjustments,
    normalize_curves,
)

_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# Grading response strengths. These are shared verbatim with the GPU shader
# (see ``film_stockpot.ui.gpu.grading_backend``) so the CPU and GPU previews
# match. The tint is applied at the full normalized zone weight (no secondary
# attenuation), which is what makes a wheel deflection clearly visible.
_COLOR_OFFSET_STRENGTH = 0.42
_COLOR_GAIN_STRENGTH = 0.55
_LUM_STRENGTH = 0.35

GRADING_NEUTRAL: dict[str, Any] = {
    "shadows": {"hue": 0.0, "sat": 0.0, "lum": 0},
    "midtones": {"hue": 0.0, "sat": 0.0, "lum": 0},
    "highlights": {"hue": 0.0, "sat": 0.0, "lum": 0},
    "blending": 50,
    "balance": 0,
    "curves": CURVES_NEUTRAL,
    "monochrome": False,
    "style_id": None,
}


def normalize_grading(grading: dict | None) -> dict:
    """Return a complete grading dict with defaults filled in."""
    source = grading or {}
    result = {}
    for zone in ("shadows", "midtones", "highlights"):
        zone_in = source.get(zone, {}) or {}
        result[zone] = {
            "hue": float(zone_in.get("hue", 0.0)),
            "sat": float(zone_in.get("sat", 0.0)),
            "lum": int(zone_in.get("lum", 0)),
        }
    result["blending"] = int(source.get("blending", GRADING_NEUTRAL["blending"]))
    result["balance"] = int(source.get("balance", GRADING_NEUTRAL["balance"]))
    result["curves"] = normalize_curves(source.get("curves"))
    result["monochrome"] = bool(source.get("monochrome", False))
    style_id = source.get("style_id")
    result["style_id"] = str(style_id) if style_id else None
    return result


def grading_is_neutral(grading: dict | None) -> bool:
    """Return True when grading settings match the neutral defaults."""
    current = normalize_grading(grading)
    neutral = normalize_grading(GRADING_NEUTRAL)
    current.pop("style_id", None)
    neutral.pop("style_id", None)
    return current == neutral


def grading_mask_key(grading: dict) -> str:
    """Hashable key for cached zone-weight masks (blending/balance only)."""
    normalized = normalize_grading(grading)
    payload = {
        "blending": normalized["blending"],
        "balance": normalized["balance"],
    }
    return json.dumps(payload, sort_keys=True)


def _zones_have_adjustments(grading: dict) -> bool:
    for zone in ("shadows", "midtones", "highlights"):
        values = grading[zone]
        if float(values.get("sat", 0.0)) > 0.0 or int(values.get("lum", 0)) != 0:
            return True
    return False


def has_wheel_adjustments(grading: dict | None) -> bool:
    """True when the color wheels or zone luminance sliders are active."""
    return _zones_have_adjustments(normalize_grading(grading))


def has_grading_adjustments(grading: dict | None) -> bool:
    """True when grading has any visible effect (wheels, luminance, curves, or mono)."""
    normalized = normalize_grading(grading)
    return (
        bool(normalized.get("monochrome"))
        or _zones_have_adjustments(normalized)
        or has_curve_adjustments(normalized.get("curves"))
    )


def _style_is_monochrome(base_style: str | None, settings: dict[str, Any] | None) -> bool:
    if str(base_style or "").lower() == "monochrome":
        return True
    values = settings or {}
    return values.get("saturation") is None and values.get("hue") is None


def camera_style_to_grading(style: Any) -> dict:
    """Map a camera style onto interactive grading settings (L curve + mono flag)."""
    curve_points = getattr(style, "curve_points", None) or []
    points_01 = [[float(x) / 255.0, float(y) / 255.0] for x, y in curve_points]
    grading = normalize_grading(GRADING_NEUTRAL)
    grading["curves"] = normalize_curves({"L": points_01})
    grading["monochrome"] = _style_is_monochrome(
        getattr(style, "base_style", None),
        getattr(style, "settings", None),
    )
    grading["style_id"] = getattr(style, "id", None)
    return grading


def camera_style_scanner_overrides(style: Any) -> dict[str, int]:
    """Return scanner saturation/sharpness overrides for a camera style."""
    settings = getattr(style, "settings", None) or {}
    overrides: dict[str, int] = {}
    saturation = settings.get("saturation")
    if saturation is not None:
        overrides["saturation"] = int(np.clip(int(saturation), -8, 8))
    sharpening = settings.get("sharpening")
    if sharpening is not None:
        overrides["sharpness"] = int(np.clip(int(sharpening), 0, 10))
    return overrides


def _to_monochrome_luma(image: np.ndarray) -> np.ndarray:
    luma = image @ _LUMA_WEIGHTS
    return np.repeat(luma[:, :, np.newaxis], 3, axis=2)


@dataclass
class GradingMasks:
    shadow_w: np.ndarray
    mid_w: np.ndarray
    highlight_w: np.ndarray


class GradingContext:
    """Caches luma-normalization and zone masks for a fixed film-base frame.

    The normalized luma only depends on the image, while the zone masks also
    depend on blending/balance. They are cached independently so dragging the
    blending or balance sliders never recomputes the (more expensive) luma
    histogram, and dragging a wheel or luminance slider recomputes nothing.
    """

    def __init__(self) -> None:
        # A reference to the exact base array is held (not just ``id(rgb)``): a
        # bare id is unsafe because a freed proxy array can be reallocated at the
        # same address, causing a stale (differently shaped) mask to be reused
        # and a broadcast error. Holding the reference keeps identity stable.
        self._base: np.ndarray | None = None
        self._luma_norm: np.ndarray | None = None
        self._mask_key: str | None = None
        self._masks: GradingMasks | None = None

    def clear(self) -> None:
        self._base = None
        self._luma_norm = None
        self._mask_key = None
        self._masks = None

    def _luma_norm_for(self, rgb: np.ndarray) -> np.ndarray:
        if (
            self._base is rgb
            and self._luma_norm is not None
            and self._base.shape == rgb.shape
        ):
            return self._luma_norm
        luma = np.sum(np.clip(rgb, 0.0, 1.0) * _LUMA_WEIGHTS, axis=-1, keepdims=True)
        self._base = rgb
        self._luma_norm = _normalized_luma(luma)
        self._mask_key = None
        self._masks = None
        return self._luma_norm

    def masks_for(self, rgb: np.ndarray, grading: dict) -> GradingMasks:
        luma_norm = self._luma_norm_for(rgb)
        key = grading_mask_key(grading)
        if self._mask_key == key and self._masks is not None:
            return self._masks

        shadow_w, mid_w, highlight_w = _compute_zone_weights(
            luma_norm,
            blending=int(grading["blending"]),
            balance=int(grading["balance"]),
        )
        self._mask_key = key
        self._masks = GradingMasks(shadow_w=shadow_w, mid_w=mid_w, highlight_w=highlight_w)
        return self._masks


def apply_wheel_grading(
    rgb: np.ndarray,
    settings: dict | None = None,
    *,
    masks: GradingMasks | None = None,
    grading_context: GradingContext | None = None,
) -> np.ndarray:
    """Apply color-wheel grading to a float32 RGB image in 0..1."""
    if not settings:
        return rgb

    grading = normalize_grading(settings.get("grading"))
    if not _zones_have_adjustments(grading):
        return rgb

    if masks is None:
        if grading_context is not None:
            masks = grading_context.masks_for(rgb, grading)
        else:
            luma = np.sum(np.clip(rgb, 0.0, 1.0) * _LUMA_WEIGHTS, axis=-1, keepdims=True)
            luma_norm = _normalized_luma(luma)
            shadow_w, mid_w, highlight_w = _compute_zone_weights(
                luma_norm,
                blending=int(grading["blending"]),
                balance=int(grading["balance"]),
            )
            masks = GradingMasks(shadow_w=shadow_w, mid_w=mid_w, highlight_w=highlight_w)

    # ``np.clip`` always returns a fresh array, so ``base`` is safe to feed into
    # the accumulation below without mutating the caller's buffer.
    base = np.clip(rgb, 0.0, 1.0).astype(np.float32, copy=False)

    # Each zone contributes an affine adjustment of the *original* tones:
    #   out = base * (1 + gain_accum) + offset_accum
    # accumulating multiplicative (gain) and additive (offset + luminance)
    # terms, each localized by its normalized zone weight. Building the two
    # accumulators and combining once is cheaper than mixing per zone and keeps
    # the tint strength tied directly to the zone weight.
    gain_accum: np.ndarray | None = None
    offset_accum: np.ndarray | None = None

    for zone, weight in (
        ("shadows", masks.shadow_w),
        ("midtones", masks.mid_w),
        ("highlights", masks.highlight_w),
    ):
        zone_values = grading[zone]
        sat = float(zone_values.get("sat", 0.0))
        lum = float(zone_values.get("lum", 0.0)) / 100.0

        if sat > 0.0:
            tint = _wheel_to_tint(zone_values)
            offset = (tint - 0.5) * 2.0 * sat * _COLOR_OFFSET_STRENGTH
            gain_minus_one = (tint - 1.0) * sat * _COLOR_GAIN_STRENGTH
            gain_term = weight * gain_minus_one
            offset_term = weight * offset
            gain_accum = gain_term if gain_accum is None else gain_accum + gain_term
            offset_accum = offset_term if offset_accum is None else offset_accum + offset_term

        if lum != 0.0:
            lum_term = weight * (lum * _LUM_STRENGTH)
            offset_accum = lum_term if offset_accum is None else offset_accum + lum_term

    result = base
    if gain_accum is not None:
        result = result + base * gain_accum
    if offset_accum is not None:
        result = result + offset_accum

    if result is base:
        return base.astype(np.float32, copy=False)
    return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)


def _normalized_luma(luma: np.ndarray) -> np.ndarray:
    """Stretch image luma to 0..1 using a histogram approximation."""
    flat = luma.ravel()
    hist, edges = np.histogram(flat, bins=256, range=(0.0, 1.0))
    total = float(flat.size)
    if total <= 0.0:
        return luma

    low_count = total * 0.01
    high_count = total * 0.99
    cumulative = np.cumsum(hist)
    lo_idx = int(np.searchsorted(cumulative, low_count, side="left"))
    hi_idx = int(np.searchsorted(cumulative, high_count, side="left"))
    lo = float(edges[lo_idx])
    hi = float(edges[min(hi_idx + 1, len(edges) - 1)])
    span = max(hi - lo, 1e-4)
    return np.clip((luma - lo) / span, 0.0, 1.0)


def _compute_zone_weights(
    luma_norm: np.ndarray,
    *,
    blending: int,
    balance: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return shadow, midtone, and highlight masks on normalized luma."""
    balance_shift = float(balance) / 100.0 * 0.30
    luma_eff = np.clip(luma_norm + balance_shift, 0.0, 1.0)

    raw_shadow = np.clip(1.0 - luma_eff * 2.0, 0.0, 1.0)
    raw_highlight = np.clip(luma_eff * 2.0 - 1.0, 0.0, 1.0)
    raw_mid = np.clip(1.0 - raw_shadow - raw_highlight, 0.0, 1.0)

    blend = float(blending) / 100.0
    power = 2.0 - blend * 1.5

    shadow_w = raw_shadow**power
    highlight_w = raw_highlight**power
    mid_w = raw_mid**power

    total = shadow_w + mid_w + highlight_w
    total = np.maximum(total, 1e-6)
    return shadow_w / total, mid_w / total, highlight_w / total


def _wheel_to_tint(zone: dict) -> np.ndarray:
    hue = float(zone.get("hue", 0.0)) % 360.0
    red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, 1.0, 1.0)
    return np.array([red, green, blue], dtype=np.float32)


def apply_grading_after_scanner(
    rgb: np.ndarray,
    settings: dict | None = None,
    *,
    grading_context: GradingContext | None = None,
    gpu_backend: object | None = None,
) -> np.ndarray:
    """Apply curves and color-wheel grading to a scanner-adjusted image."""
    grading = normalize_grading((settings or {}).get("grading"))
    if not has_grading_adjustments(grading):
        return rgb

    image = apply_curves(rgb, grading.get("curves"))
    if _zones_have_adjustments(grading):
        if gpu_backend is not None and getattr(gpu_backend, "enabled", False):
            gpu_result = gpu_backend.apply_grading(image, grading, grading_context=grading_context)
            if gpu_result is not None:
                image = gpu_result
            else:
                image = apply_wheel_grading(
                    image,
                    {"grading": grading},
                    grading_context=grading_context,
                )
        else:
            image = apply_wheel_grading(
                image,
                {"grading": grading},
                grading_context=grading_context,
            )

    if grading.get("monochrome"):
        image = _to_monochrome_luma(image)
    return image


def apply_interactive_adjustments(
    rgb: np.ndarray,
    settings: dict | None = None,
    *,
    preset: dict | None = None,
    flat_scan: np.ndarray | None = None,
    preview_fast: bool = False,
    grading_context: GradingContext | None = None,
    gpu_backend: object | None = None,
    skip_print_stage: bool = False,
) -> np.ndarray:
    """Apply print emulation, Frontier scanner controls, then curves and wheel grading."""
    from film_stockpot.image.print import apply_print_stage
    from film_stockpot.image.scanner import apply_scanner_adjustments

    image = rgb
    if not skip_print_stage:
        image = apply_print_stage(image, settings, preset, flat_scan=flat_scan)
    image = apply_scanner_adjustments(image, settings, preview_fast=preview_fast)
    return apply_grading_after_scanner(
        image,
        settings,
        grading_context=grading_context,
        gpu_backend=gpu_backend,
    )
