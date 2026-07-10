"""Print-stage orchestration for Film Stockpot."""

from __future__ import annotations

from typing import Any

import numpy as np

from film_stockpot.image.print.constants import EXPOSURE_CONSTANTS
from film_stockpot.image.print.logic import (
    apply_characteristic_curve,
    effective_cast_strength,
    filtration_offsets,
    get_luminance,
    grade_coupled_shape,
    per_channel_curve_params,
)
from film_stockpot.image.print.normalization import (
    default_log_bounds,
    display_to_normalized_log,
    graded_display_to_normalized_log,
    luminance_density_range,
    measure_anchor_from_normalized,
    measure_neutral_axis,
    measure_shadow_log_refs,
    measure_textural_range_from_normalized,
    flat_scan_to_normalized_log,
    norm_log_to_transmittance,
    normalized_neutral_axis,
    normalized_shadow_refs,
)
from film_stockpot.image.print.papers import (
    PROCESS_BW,
    default_paper_profile,
    effective_paper_profile,
    process_mode_for_preset,
)

PRINT_NEUTRAL: dict[str, Any] = {
    "enabled": False,
    "paper_profile": "kodak_endura",
    "grade": 115.0,
    "density": 0.75,
    "cyan": 0.0,
    "magenta": 0.0,
    "yellow": 0.0,
    "shadow_cyan": 0.0,
    "shadow_magenta": 0.0,
    "shadow_yellow": 0.0,
    "highlight_cyan": 0.0,
    "highlight_magenta": 0.0,
    "highlight_yellow": 0.0,
    "toe": 0.0,
    "toe_width": 2.5,
    "shoulder": 0.0,
    "shoulder_width": 2.5,
    "paper_dmin": True,
    "flare": False,
    "auto_exposure": True,
    "auto_normalize_contrast": False,
    "auto_cast_removal": True,
    "cast_removal_strength": 0.5,
}


def _coerce_grade(value: Any) -> float:
    grade = float(value)
    if grade <= 5.0:
        return 150.0 - 20.0 * grade
    return grade


def normalize_print_settings(settings: dict | None, preset: dict | None = None) -> dict:
    """Merge user print settings with defaults."""
    source = settings or {}
    merged = dict(PRINT_NEUTRAL)
    merged.update({key: source[key] for key in PRINT_NEUTRAL if key in source})
    merged["enabled"] = bool(merged.get("enabled", False))
    merged["grade"] = _coerce_grade(merged.get("grade", PRINT_NEUTRAL["grade"]))
    if preset is not None and "paper_profile" not in source:
        merged["paper_profile"] = default_paper_profile(preset)
    return merged


def print_settings_from_adjustments(adjustments: dict | None, preset: dict | None = None) -> dict:
    block = (adjustments or {}).get("print")
    if not isinstance(block, dict):
        return normalize_print_settings(None, preset)
    return normalize_print_settings(block, preset)


def print_enabled(adjustments: dict | None) -> bool:
    block = (adjustments or {}).get("print")
    if not isinstance(block, dict):
        return False
    return bool(block.get("enabled", False))


def _lift_print_to_reference(positive: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Raise print midtones toward the flat scan so the stage does not crush density."""
    ref = np.clip(reference.astype(np.float32, copy=False), 0.0, 1.0)
    out = np.clip(positive.astype(np.float32, copy=False), 0.0, 1.0)
    ref_mid = float(np.percentile(get_luminance(ref), 50.0))
    out_mid = float(np.percentile(get_luminance(out), 50.0))
    if out_mid < 1e-5 or ref_mid <= out_mid:
        return out
    gain = min(ref_mid / out_mid, 2.5)
    return np.clip(out * gain, 0.0, 1.0).astype(np.float32, copy=False)


def apply_print_stage(
    rgb: np.ndarray,
    settings: dict | None,
    preset: dict | None = None,
    *,
    flat_scan: np.ndarray | None = None,
) -> np.ndarray:
    """Apply darkroom print emulation when enabled."""
    print_settings = print_settings_from_adjustments(settings, preset)
    if not print_settings["enabled"]:
        return rgb

    process_mode = process_mode_for_preset(preset)
    paper = effective_paper_profile(str(print_settings["paper_profile"]), process_mode)
    d_min = paper.d_min if bool(print_settings["paper_dmin"]) else 0.0

    image = np.clip(rgb.astype(np.float32, copy=True), 0.0, 1.0)
    scan_source = flat_scan if flat_scan is not None else image
    # A selected film stock has already expanded the scan to display space — emulate
    # printing that grade instead of re-decoding the raw flat log encoding.
    film_graded = preset is not None
    use_flat_log = flat_scan is not None and not film_graded
    bounds = default_log_bounds(process_mode=process_mode)
    if use_flat_log:
        log_image = flat_scan_to_normalized_log(scan_source)
        working = norm_log_to_transmittance(log_image)
        metered_anchor = measure_anchor_from_normalized(log_image) if print_settings["auto_exposure"] else None
        textural_range = measure_textural_range_from_normalized(log_image)
        shadow_refs = measure_shadow_log_refs(working)
        shadow_refs_norm = normalized_shadow_refs(bounds, shadow_refs)
        neutral_axis_refs = measure_neutral_axis(working, bounds)
        neutral_axis_norm = normalized_neutral_axis(bounds, neutral_axis_refs)
        confidence = neutral_axis_refs[3] if neutral_axis_refs is not None else None
    elif flat_scan is not None:
        log_image = graded_display_to_normalized_log(image, flat_scan)
        working = norm_log_to_transmittance(flat_scan_to_normalized_log(flat_scan))
        metered_anchor = measure_anchor_from_normalized(log_image) if print_settings["auto_exposure"] else None
        textural_range = measure_textural_range_from_normalized(log_image)
        shadow_refs = measure_shadow_log_refs(working)
        shadow_refs_norm = normalized_shadow_refs(bounds, shadow_refs)
        neutral_axis_refs = measure_neutral_axis(working, bounds)
        neutral_axis_norm = normalized_neutral_axis(bounds, neutral_axis_refs)
        confidence = neutral_axis_refs[3] if neutral_axis_refs is not None else None
    else:
        log_image = display_to_normalized_log(image)
        metered_anchor = (
            measure_anchor_from_normalized(log_image) if print_settings["auto_exposure"] else None
        )
        textural_range = measure_textural_range_from_normalized(log_image)
        shadow_refs = None
        shadow_refs_norm = None
        neutral_axis_norm = None
        confidence = None

    anchor = metered_anchor if print_settings["auto_exposure"] else None
    lum_range = luminance_density_range(bounds)
    cast_strength = effective_cast_strength(
        float(print_settings["cast_removal_strength"]),
        bool(print_settings["auto_cast_removal"]),
        confidence,
    )

    slopes, pivots, curvatures = per_channel_curve_params(
        float(print_settings["grade"]),
        float(print_settings["density"]),
        bool(print_settings["auto_normalize_contrast"]),
        cast_strength,
        lum_range,
        shadow_refs_norm,
        textural_range,
        d_min=d_min,
        anchor=anchor,
        paper=paper,
        neutral_axis_norm=neutral_axis_norm,
    )

    cmy_max = float(EXPOSURE_CONSTANTS["cmy_max_density"])
    cmy_offsets = filtration_offsets(
        (
            float(print_settings["cyan"]),
            float(print_settings["magenta"]),
            float(print_settings["yellow"]),
        ),
        bounds,
    )
    shadow_cmy = (
        float(print_settings["shadow_cyan"]) * cmy_max,
        float(print_settings["shadow_magenta"]) * cmy_max,
        float(print_settings["shadow_yellow"]) * cmy_max,
    )
    highlight_cmy = (
        float(print_settings["highlight_cyan"]) * cmy_max,
        float(print_settings["highlight_magenta"]) * cmy_max,
        float(print_settings["highlight_yellow"]) * cmy_max,
    )
    toe_eff, shoulder_eff = grade_coupled_shape(slopes[1], float(print_settings["toe"]), float(print_settings["shoulder"]))

    working = log_image
    if process_mode == PROCESS_BW:
        lum = get_luminance(working)
        working = np.stack([lum, lum, lum], axis=-1)

    positive = apply_characteristic_curve(
        working,
        (pivots[0], slopes[0]),
        (pivots[1], slopes[1]),
        (pivots[2], slopes[2]),
        toe=toe_eff,
        toe_width=float(print_settings["toe_width"]),
        shoulder=shoulder_eff,
        shoulder_width=float(print_settings["shoulder_width"]),
        shadow_cmy=shadow_cmy,
        highlight_cmy=highlight_cmy,
        cmy_offsets=cmy_offsets,
        d_min=d_min,
        flare=float(EXPOSURE_CONSTANTS["flare_fraction"]) if print_settings["flare"] else 0.0,
        surround_gamma=1.0,
        curvatures=curvatures,
        paper=paper,
    )

    if process_mode == PROCESS_BW:
        lum = get_luminance(positive)
        positive = np.stack([lum, lum, lum], axis=-1)

    reference = scan_source if use_flat_log else image
    positive = _lift_print_to_reference(positive, reference)

    return positive.astype(np.float32, copy=False)


def print_cache_key(settings: dict | None, preset: dict | None = None) -> str:
    import json

    payload = print_settings_from_adjustments(settings, preset)
    return json.dumps(payload, sort_keys=True, default=str)
