"""Print-stage constants ported from NegPy (GPL-3)."""

from __future__ import annotations

from typing import Any

EXPOSURE_CONSTANTS: dict[str, Any] = {
    "cmy_max_density": 0.2,
    "density_multiplier": 0.2,
    "anchor_target_density": 0.74,
    "assumed_anchor": 0.46,
    "iso_r_min": 50.0,
    "iso_r_max": 180.0,
    "slope_min": 2.0,
    "slope_max": 10.0,
    "d_max": 2.3,
    "d_min": 0.06,
    "toe_shoulder_strength": 0.85,
    "toe_sharpness_base": 4.0,
    "shoulder_sharpness_base": 3.0,
    "toeshoulder_width_ref": 2.5,
    "toe_height": 0.35,
    "shoulder_height": 0.35,
    "grade_contrast_scale": 2.9,
    "analysis_grid": 1024,
    "base_luma_clip": 0.01,
    "base_color_clip": 1.0,
    "shadow_neutral_percentile": 98.0,
    "scan_clip_level": 0.99,
    "scan_clip_warn": 0.01,
    "cast_removal_max_offset": 0.1,
    "neutral_axis_highlight_band": (0.10, 0.30),
    "neutral_axis_mid_band": (0.40, 0.60),
    "neutral_axis_shadow_band": (0.72, 0.92),
    "neutral_axis_chroma_quantile": 0.30,
    "neutral_axis_chroma_cap": 0.35,
    "neutral_axis_min_pixels": 64,
    "midtone_cast_max_offset": 0.2,
    "neutral_axis_curv_max_ratio": 0.45,
    "anchor_meter_percentile": 50.0,
    "anchor_meter_band": 0.12,
    "anchor_meter_strength": 0.2,
    "toe_grade_strength": 0.15,
    "shoulder_grade_strength": 0.12,
    "auto_grade_target": 0.5,
    "auto_grade_strength": 0.4,
    "auto_grade_nominal_ratio": 2.0,
    "target_system_gamma": 1.10,
    "textural_range_clip": 10.0,
    "flare_fraction": 0.005,
    "flat_log_gain": 0.65,
    "flat_log_lift": 0.10,
    "paper_midtone_gamma": 0.15,
    "paper_gamma_width": 0.6,
}

LUMA_R = 0.2126
LUMA_G = 0.7152
LUMA_B = 0.0722
