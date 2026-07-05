"""H&D print curve logic — ported from NegPy (GPL-3)."""

from __future__ import annotations

from typing import Any

import numpy as np

from film_stockpot.image.print.constants import EXPOSURE_CONSTANTS
from film_stockpot.image.print.normalization import LogNegativeBounds
from film_stockpot.image.print.papers import PaperProfile, effective_constants, resolve_dye_matrix

_LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _softplus(x: np.ndarray) -> np.ndarray:
    return np.where(x > 0.0, x + np.log1p(np.exp(-x)), np.log1p(np.exp(x)))


def _inv_softplus(y: np.ndarray) -> np.ndarray:
    return np.where(y > 20.0, y, np.log(np.expm1(np.maximum(y, 1e-12))))


def _reference_linear_value(d_min: float = 0.0, paper: PaperProfile | None = None) -> float:
    constants = effective_constants(paper)
    target = float(constants["anchor_target_density"])
    d_max = float(constants["d_max"])
    a_hl = float(constants["shoulder_sharpness_base"])
    a_sh = float(constants["toe_sharpness_base"])
    v1 = d_max - _inv_softplus(np.array(a_sh * (d_max - target))) / a_sh
    return float(d_min + _inv_softplus(np.array(a_hl * (float(v1) - d_min))) / a_hl)


def paper_dmin_rgb(d_min: float, paper: PaperProfile | None) -> tuple[float, float, float]:
    if d_min <= 0.0 or paper is None:
        base = max(d_min, 0.0)
        return (base, base, base)
    tint = paper.base_tint_cmy
    return (max(d_min + tint[0], 0.0), max(d_min + tint[1], 0.0), max(d_min + tint[2], 0.0))


def default_grade_range() -> float:
    return float(EXPOSURE_CONSTANTS["auto_grade_target"]) * float(EXPOSURE_CONSTANTS["auto_grade_nominal_ratio"])


def grade_to_slope(grade: float, density_range: float | None) -> float:
    rng_in = default_grade_range() if density_range is None else density_range
    er = min(max(grade, EXPOSURE_CONSTANTS["iso_r_min"]), EXPOSURE_CONSTANTS["iso_r_max"]) / 100.0
    rng = min(max(abs(float(rng_in)), 0.3), 3.5)
    slope = float(EXPOSURE_CONSTANTS["grade_contrast_scale"]) * rng / er
    return float(min(max(slope, EXPOSURE_CONSTANTS["slope_min"]), EXPOSURE_CONSTANTS["slope_max"]))


def grade_coupled_shape(slope_g: float, toe: float, shoulder: float) -> tuple[float, float]:
    slope_norm = (float(slope_g) - float(EXPOSURE_CONSTANTS["slope_min"])) / (
        float(EXPOSURE_CONSTANTS["slope_max"]) - float(EXPOSURE_CONSTANTS["slope_min"])
    )
    slope_norm = min(max(slope_norm, 0.0), 1.0)
    toe_eff = float(toe) + float(EXPOSURE_CONSTANTS["toe_grade_strength"]) * slope_norm
    shoulder_eff = float(shoulder) + float(EXPOSURE_CONSTANTS["shoulder_grade_strength"]) * slope_norm
    return toe_eff, shoulder_eff


def effective_grade_range(
    auto_normalize_contrast: bool,
    floor_ceil_range: float | None,
    textural_range: float | None,
) -> float | None:
    if not auto_normalize_contrast:
        return floor_ceil_range
    if textural_range is None or floor_ceil_range is None:
        return default_grade_range()
    measured = abs(float(textural_range))
    if measured < 1e-6:
        return 3.5
    target = float(EXPOSURE_CONSTANTS["auto_grade_target"])
    nominal = float(EXPOSURE_CONSTANTS["auto_grade_nominal_ratio"])
    strength = float(EXPOSURE_CONSTANTS["auto_grade_strength"])
    ratio = abs(float(floor_ceil_range)) / measured
    return target * (nominal + strength * (ratio - nominal))


def compute_pivot(
    slope: float,
    density: float,
    *,
    d_min: float = 0.0,
    anchor: float | None = None,
    paper: PaperProfile | None = None,
) -> float:
    constants = effective_constants(paper)
    ref = constants["assumed_anchor"] if anchor is None else anchor
    v_star = _reference_linear_value(d_min, paper)
    base = ref - v_star / slope
    return base + (1.0 - density) * constants["density_multiplier"]


def effective_cast_strength(strength: float, auto: bool, confidence: float | None) -> float:
    if auto and confidence is not None:
        return confidence * strength
    return strength


def filtration_offsets(
    wb_cmy: tuple[float, float, float],
    bounds: LogNegativeBounds | None,
) -> tuple[float, float, float]:
    cmy_max = float(EXPOSURE_CONSTANTS["cmy_max_density"])
    out = []
    for ch in range(3):
        density = float(wb_cmy[ch]) * cmy_max
        if bounds is not None:
            density = density / max(abs(bounds.ceils[ch] - bounds.floors[ch]), 1e-6)
        out.append(density)
    return (out[0], out[1], out[2])


def per_channel_curve_params(
    grade: float,
    density: float,
    auto_normalize_contrast: bool,
    strength: float,
    lum_range: float | None,
    shadow_refs_norm: tuple[float, float, float] | None,
    textural_range: float | None,
    *,
    d_min: float = 0.0,
    anchor: float | None = None,
    paper: PaperProfile | None = None,
    neutral_axis_norm: Any = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    constants = effective_constants(paper)
    channel_gamma = paper.channel_gamma if paper is not None else (1.0, 1.0, 1.0)
    slope_min = float(constants["slope_min"])
    slope_max = float(constants["slope_max"])
    effective_range = effective_grade_range(auto_normalize_contrast, lum_range, textural_range)
    base_slope = grade_to_slope(grade, effective_range)
    epsilon = 1e-6

    if strength > 0.0 and neutral_axis_norm is not None:
        mid_norm, sh_norm, hl_norm = neutral_axis_norm
        limit = float(constants["midtone_cast_max_offset"])
        curv_lim = float(constants["neutral_axis_curv_max_ratio"])
        m_g, s_g = float(mid_norm[1]), float(sh_norm[1])
        slope_g = min(max(base_slope * channel_gamma[1], slope_min), slope_max)
        pivot_g = compute_pivot(slope_g, density, d_min=d_min, anchor=anchor, paper=paper)
        target = lambda g: slope_g * (g - pivot_g)  # noqa: E731
        t_m, t_s = target(m_g), target(s_g)
        h_g = float(hl_norm[1]) if hl_norm is not None else None
        clamp_dev = lambda g, v: g + min(max(strength * (v - g), -limit), limit)  # noqa: E731

        slopes, pivots, curvs = [], [], []
        for ch in range(3):
            if ch == 1:
                slopes.append(slope_g)
                pivots.append(pivot_g)
                curvs.append(0.0)
                continue
            u_m = clamp_dev(m_g, float(mid_norm[ch]))
            u_s = clamp_dev(s_g, float(sh_norm[ch]))
            curv = 0.0
            if h_g is not None and hl_norm is not None:
                u_h = clamp_dev(h_g, float(hl_norm[ch]))
                matrix = np.array(
                    [[1.0, u_h, u_h * u_h], [1.0, u_m, u_m * u_m], [1.0, u_s, u_s * u_s]],
                    dtype=np.float64,
                )
                try:
                    curv = float(np.linalg.solve(matrix, np.array([target(h_g), t_m, t_s]))[2])
                except np.linalg.LinAlgError:
                    curv = 0.0
                curv = min(max(curv, -curv_lim * slope_g), curv_lim * slope_g)
            du = u_m - u_s
            slope_ch = slope_g if abs(du) < epsilon else ((t_m - t_s) - curv * (u_m * u_m - u_s * u_s)) / du
            slope_ch = min(max(slope_ch * channel_gamma[ch], slope_min), slope_max)
            curv_ch = curv * channel_gamma[ch]
            pivot_ch = u_m - (t_m - curv_ch * u_m * u_m) / slope_ch if abs(slope_ch) > epsilon else pivot_g
            slopes.append(slope_ch)
            pivots.append(pivot_ch)
            curvs.append(curv_ch)
        return (slopes[0], slopes[1], slopes[2]), (pivots[0], pivots[1], pivots[2]), (curvs[0], curvs[1], curvs[2])

    if strength > 0.0 and shadow_refs_norm is not None:
        anchor_val = float(constants["assumed_anchor"]) if anchor is None else float(anchor)
        limit = float(constants["cast_removal_max_offset"])
        r_green = float(shadow_refs_norm[1])
        numer = anchor_val - r_green
        slopes = []
        pivots = []
        for ch in range(3):
            cast = min(max(strength * (r_green - float(shadow_refs_norm[ch])), -limit), limit)
            denom = anchor_val - (r_green - cast)
            if ch == 1 or abs(denom) < epsilon:
                slope_ch = base_slope
            else:
                slope_ch = base_slope * numer / denom
                slope_ch = min(max(slope_ch, slope_min), slope_max)
            slope_ch = min(max(slope_ch * channel_gamma[ch], slope_min), slope_max)
            slopes.append(slope_ch)
            pivots.append(compute_pivot(slope_ch, density, d_min=d_min, anchor=anchor, paper=paper))
        return (slopes[0], slopes[1], slopes[2]), (pivots[0], pivots[1], pivots[2]), (0.0, 0.0, 0.0)

    s0 = min(max(base_slope * channel_gamma[0], slope_min), slope_max)
    s1 = min(max(base_slope * channel_gamma[1], slope_min), slope_max)
    s2 = min(max(base_slope * channel_gamma[2], slope_min), slope_max)
    p0 = compute_pivot(s0, density, d_min=d_min, anchor=anchor, paper=paper)
    p1 = compute_pivot(s1, density, d_min=d_min, anchor=anchor, paper=paper)
    p2 = compute_pivot(s2, density, d_min=d_min, anchor=anchor, paper=paper)
    return (s0, s1, s2), (p0, p1, p2), (0.0, 0.0, 0.0)


def apply_characteristic_curve(
    img: np.ndarray,
    params_r: tuple[float, float],
    params_g: tuple[float, float],
    params_b: tuple[float, float],
    *,
    toe: float = 0.0,
    toe_width: float = 2.5,
    shoulder: float = 0.0,
    shoulder_width: float = 2.5,
    shadow_cmy: tuple[float, float, float] = (0.0, 0.0, 0.0),
    highlight_cmy: tuple[float, float, float] = (0.0, 0.0, 0.0),
    cmy_offsets: tuple[float, float, float] = (0.0, 0.0, 0.0),
    d_min: float = 0.0,
    flare: float = 0.0,
    surround_gamma: float = 1.0,
    midtone_gamma: float | None = None,
    curvatures: tuple[float, float, float] = (0.0, 0.0, 0.0),
    paper: PaperProfile | None = None,
) -> np.ndarray:
    constants = effective_constants(paper)
    toe_shoulder_strength = float(constants["toe_shoulder_strength"])
    if midtone_gamma is None:
        midtone_gamma = float(constants["paper_midtone_gamma"])
    v_star = _reference_linear_value(d_min, paper)
    pivots = np.asarray([params_r[0], params_g[0], params_b[0]], dtype=np.float32)
    slopes = np.asarray([params_r[1], params_g[1], params_b[1]], dtype=np.float32)
    curvs = np.asarray(curvatures, dtype=np.float32)
    offsets = np.asarray(cmy_offsets, dtype=np.float32)
    shadow = np.asarray(shadow_cmy, dtype=np.float32)
    highlight = np.asarray(highlight_cmy, dtype=np.float32)
    d_min_rgb = np.asarray(paper_dmin_rgb(d_min, paper), dtype=np.float64)
    dye = resolve_dye_matrix(paper)
    dye_mix = np.eye(3, dtype=np.float64) if dye is None else dye

    eps = 1e-6
    toe_eff = float(toe * toe_shoulder_strength)
    shoulder_eff = float(shoulder * toe_shoulder_strength)
    d_max = float(constants["d_max"])
    width_ref = float(constants["toeshoulder_width_ref"])
    a_hl = float(constants["shoulder_sharpness_base"]) * width_ref / max(shoulder_width, eps)
    a_sh_base = float(constants["toe_sharpness_base"]) * width_ref / max(toe_width, eps)
    if toe_eff >= 0.0:
        d_max_base = d_max - toe_eff * float(constants["toe_height"])
        a_sh = a_sh_base
    else:
        d_max_base = d_max
        a_sh = a_sh_base * (1.0 - toe_eff * 4.0)

    d_min_eff = np.maximum(0.0, d_min_rgb + shoulder_eff * float(constants["shoulder_height"]))
    d_max_eff = np.full(3, d_max_base, dtype=np.float64)
    d_max_eff = np.maximum(d_max_eff, d_min_eff + 0.1)
    flare_white = 10.0 ** (-d_min_rgb)

    source = np.ascontiguousarray(img.astype(np.float32))
    val = source + offsets.reshape(1, 1, 3)
    v = slopes.reshape(1, 1, 3) * (val - pivots.reshape(1, 1, 3)) + curvs.reshape(1, 1, 3) * val * val
    if midtone_gamma != 0.0:
        gamma_width = float(constants["paper_gamma_width"])
        v = v + midtone_gamma * gamma_width * np.tanh((v - v_star) / gamma_width)
    zone_center = float(constants["anchor_target_density"])
    w_sh = 1.0 / (1.0 + np.exp(-3.0 * (v - zone_center)))
    w_hi = 1.0 - w_sh
    v = v + shadow.reshape(1, 1, 3) * w_sh + highlight.reshape(1, 1, 3) * w_hi
    v1 = d_min_eff.reshape(1, 1, 3) + _softplus(a_hl * (v - d_min_eff.reshape(1, 1, 3))) / a_hl
    dens = d_max_eff.reshape(1, 1, 3) - _softplus(a_sh * (d_max_eff.reshape(1, 1, 3) - v1)) / a_sh

    if dye is not None:
        excess = dens - d_min_rgb.reshape(1, 1, 3)
        dens = d_min_rgb.reshape(1, 1, 3) + np.matmul(excess, dye_mix.T)

    if surround_gamma != 1.0:
        dens = d_min_rgb.reshape(1, 1, 3) + surround_gamma * (dens - d_min_rgb.reshape(1, 1, 3))

    transmittance = 10.0 ** (-dens)
    if flare != 0.0:
        transmittance = (transmittance + flare * flare_white.reshape(1, 1, 3)) / (1.0 + flare)
    return np.clip(transmittance, 0.0, 1.0).astype(np.float32)


def get_luminance(rgb: np.ndarray) -> np.ndarray:
    return np.sum(rgb * _LUMA, axis=-1)
