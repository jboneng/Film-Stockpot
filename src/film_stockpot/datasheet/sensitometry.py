"""Derive film sensitometry and pipeline parameters from extracted datasheet JSON."""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

PGI_REFERENCE = 37.0
BASE_GRAIN_STRENGTH = 0.35

_CHANNEL_NAMES = ("red_sensitive", "green_sensitive", "blue_sensitive")
_DYE_NAMES = ("cyan_forming", "magenta_forming", "yellow_forming")


def _curve_by_type(curves: list[dict], curve_type: str) -> dict | None:
    for curve in curves or []:
        if curve.get("type") == curve_type:
            return curve
    return None


def _series_points(curve: dict, index: int) -> list[list[float]] | None:
    series = curve.get("series") or []
    if index >= len(series):
        return None
    pts = series[index].get("points")
    return pts if pts and len(pts) >= 4 else None


def _named_series(curve: dict, names: tuple[str, ...]) -> list[list[list[float]]]:
    out: list[list[list[float]]] = []
    by_name = {s.get("name"): s.get("points") for s in (curve.get("series") or [])}
    for name in names:
        pts = by_name.get(name)
        if pts and len(pts) >= 4:
            out.append(pts)
    if len(out) == len(names):
        return out
    ordered = [s.get("points") for s in (curve.get("series") or []) if len(s.get("points") or []) >= 4]
    return ordered[: len(names)]


def _arr(points: list[list[float]]) -> np.ndarray:
    return np.array(points, dtype=np.float64)


def scalar_grain_value(scalars: dict) -> tuple[str | None, float | None]:
    pgi = scalars.get("print_grain_index")
    if isinstance(pgi, list) and pgi:
        val = pgi[0]
        if isinstance(val, int):
            return "PGI", float(val)
        if isinstance(val, str) and val.startswith("<"):
            num = re.search(r"\d+", val)
            if num:
                return "PGI", float(num.group()) - 1.0
    rms = scalars.get("rms_granularity")
    if rms is not None:
        return "RMS", float(rms)
    return None, None


def pgi_to_grain_strength(
    grain_value: float | None,
    *,
    metric: str | None = "PGI",
    reference: float = PGI_REFERENCE,
    base_strength: float = BASE_GRAIN_STRENGTH,
) -> float | None:
    if grain_value is None or grain_value <= 0:
        return None
    if metric == "RMS":
        return round(base_strength * math.sqrt(grain_value / 12.0), 4)
    return round(base_strength * math.sqrt(grain_value / reference), 4)


def derive_sensitometry_from_curves(curves: list[dict]) -> dict[str, Any] | None:
    curve = _curve_by_type(curves, "characteristic_curves")
    if not curve:
        return None

    channel_series = _named_series(curve, _CHANNEL_NAMES)
    if len(channel_series) < 1:
        return None

    d_mins: list[float] = []
    d_maxs: list[float] = []
    gammas: list[float] = []
    latitudes: list[float] = []

    for pts in channel_series:
        arr = _arr(pts)
        xs, ys = arr[:, 0], arr[:, 1]
        d_min_c = float(np.min(ys))
        d_max_c = float(np.max(ys))
        d_mins.append(d_min_c)
        d_maxs.append(d_max_c)

        x_lo, x_hi = float(np.percentile(xs, 15)), float(np.percentile(xs, 85))
        mask = (xs >= x_lo) & (xs <= x_hi)
        if mask.sum() >= 3:
            slope, _ = np.polyfit(xs[mask], ys[mask], 1)
            gammas.append(float(max(0.1, slope)))
        else:
            gammas.append(0.5)

        d_lo = d_min_c + 0.1 * (d_max_c - d_min_c)
        d_hi = d_min_c + 0.9 * (d_max_c - d_min_c)
        try:
            x_at_lo = float(np.interp(d_lo, ys, xs))
            x_at_hi = float(np.interp(d_hi, ys, xs))
            latitudes.append(max(0.0, x_at_hi - x_at_lo))
        except ValueError:
            latitudes.append(float(xs[-1] - xs[0]))

    result: dict[str, Any] = {
        "log_exposure_range": [
            round(float(min(_arr(p)[:, 0].min() for p in channel_series)), 3),
            round(float(max(_arr(p)[:, 0].max() for p in channel_series)), 3),
        ],
        "curve_log_span": round(float(np.mean(latitudes)), 2),
        "d_min": round(float(np.mean(d_mins)), 3),
        "d_max": round(float(np.max(d_maxs)), 3),
        "curve_gamma": round(float(np.mean(gammas)), 3),
    }
    if len(channel_series) >= 3:
        result["d_min_rgb"] = [round(v, 3) for v in d_mins[:3]]
        result["d_max_rgb"] = [round(v, 3) for v in d_maxs[:3]]
        result["gamma_rgb"] = [round(v, 3) for v in gammas[:3]]
    return result


def _density_to_byte(d: float, d_min: float, d_max: float) -> int:
    if d_max <= d_min:
        return 128
    t = (d - d_min) / (d_max - d_min)
    return int(round(np.clip(t, 0.0, 1.0) * 255.0))


def _log_h_to_byte(x: float, x_min: float, x_max: float) -> int:
    if x_max <= x_min:
        return 128
    t = (x - x_min) / (x_max - x_min)
    return int(round(np.clip(t, 0.0, 1.0) * 255.0))


def is_valid_tone_curve(points: list[list[float | int]]) -> bool:
    if len(points) < 2:
        return False
    ordered = sorted(points, key=lambda p: float(p[0]))
    ys = [float(p[1]) for p in ordered]
    return all(ys[i] <= ys[i + 1] + 1e-6 for i in range(len(ys) - 1))


def is_valid_tone_curves_rgb(curves: dict[str, list[list[float | int]]] | None) -> bool:
    if not curves or set(curves.keys()) != {"r", "g", "b"}:
        return False
    return all(is_valid_tone_curve(curves[ch]) for ch in ("r", "g", "b"))


def _enforce_monotonic_curve(points: list[list[int]]) -> list[list[int]] | None:
    ordered = sorted([[int(p[0]), int(p[1])] for p in points], key=lambda p: p[0])
    if not is_valid_tone_curve(ordered):
        return None
    return ordered


def derive_tone_curves_from_characteristic(
    curves: list[dict],
    *,
    point_count: int = 7,
) -> tuple[list[list[int]] | None, dict[str, list[list[int]]] | None]:
    curve = _curve_by_type(curves, "characteristic_curves")
    if not curve:
        return None, None

    channel_series = _named_series(curve, _CHANNEL_NAMES)
    if len(channel_series) < 3:
        return None, None

    x_min = min(float(_arr(p)[:, 0].min()) for p in channel_series)
    x_max = max(float(_arr(p)[:, 0].max()) for p in channel_series)
    pad = (x_max - x_min) * 0.02
    x_min -= pad
    x_max += pad

    all_ys = np.concatenate([_arr(p)[:, 1] for p in channel_series[:3]])
    y_global_min = float(np.min(all_ys))
    y_global_max = float(np.max(all_ys))

    rgb_curves: dict[str, list[list[int]]] = {}
    channel_keys = ("r", "g", "b")
    all_byte_curves: list[list[list[int]]] = []

    for key, pts in zip(channel_keys, channel_series[:3]):
        arr = _arr(pts)
        xs, ys = arr[:, 0], arr[:, 1]
        sample_x = np.linspace(x_min, x_max, num=point_count)
        sample_y = np.interp(sample_x, xs, ys)
        byte_pts = [
            [
                _log_h_to_byte(float(x), x_min, x_max),
                _density_to_byte(float(y), y_global_min, y_global_max),
            ]
            for x, y in zip(sample_x, sample_y)
        ]
        cleaned = _enforce_monotonic_curve(byte_pts)
        if cleaned is None:
            return None, None
        rgb_curves[key] = cleaned
        all_byte_curves.append(cleaned)

    master: list[list[int]] = []
    for i in range(point_count):
        in_v = int(round(np.mean([c[i][0] for c in all_byte_curves])))
        out_v = int(round(np.mean([c[i][1] for c in all_byte_curves])))
        master.append([in_v, out_v])
    master_clean = _enforce_monotonic_curve(master)
    if master_clean is None or not is_valid_tone_curves_rgb(rgb_curves):
        return None, None
    return master_clean, rgb_curves


def derive_acutance_from_curves(curves: list[dict]) -> dict[str, Any] | None:
    curve = _curve_by_type(curves, "mtf")
    if not curve:
        return None

    best_mtf50: float | None = None
    for series in curve.get("series") or []:
        pts = series.get("points")
        if not pts or len(pts) < 4:
            continue
        arr = _arr(pts)
        freqs, resp = arr[:, 0], arr[:, 1]
        if np.max(freqs) < 5:
            continue
        peak = float(np.max(resp))
        if peak <= 0:
            continue
        target = peak * 0.5
        above = np.where(resp >= target)[0]
        if above.size == 0:
            continue
        idx = int(above[-1])
        if idx >= len(freqs) - 1:
            mtf50 = float(freqs[idx])
        else:
            mtf50 = float(np.interp(target, resp[idx : idx + 2], freqs[idx : idx + 2]))
        if best_mtf50 is None or mtf50 > best_mtf50:
            best_mtf50 = mtf50

    if best_mtf50 is None:
        return None

    # Subtle acutance only — datasheet MTF maps to a gentle micro-contrast boost.
    strength = float(np.clip((best_mtf50 - 20.0) / 600.0, 0.04, 0.10))
    return {
        "mtf50_cycles_per_mm": round(best_mtf50, 1),
        "strength": round(strength, 3),
        "radius": 1.0,
        "amount": round(strength * 0.75, 3),
    }


def derive_color_matrix_from_dye_density(curves: list[dict]) -> list[list[float]] | None:
    curve = _curve_by_type(curves, "spectral_dye_density")
    if not curve:
        return None

    dye_series = _named_series(curve, _DYE_NAMES)
    if len(dye_series) < 3:
        series_list = [s.get("points") for s in (curve.get("series") or []) if len(s.get("points") or []) >= 4]
        dye_series = series_list[:3]
    if len(dye_series) < 3:
        return None

    bands = (650.0, 550.0, 450.0)
    matrix: list[list[float]] = []
    for pts in dye_series[:3]:
        arr = _arr(pts)
        xs, ys = arr[:, 0], arr[:, 1]
        row = [float(max(0.0, np.interp(w, xs, ys))) for w in bands]
        total = sum(row) or 1.0
        matrix.append([round(v / total, 4) for v in row])

    return matrix


def _parse_reciprocity_range(text: str) -> tuple[float | None, float | None]:
    text = text.lower()
    # "1/10,000 second to 1 second"
    match = re.search(
        r"(\d+(?:\.\d+)?(?:\s*[/\u2044]\s*\d+(?:,\d{3})*)?)\s*(?:second|sec)\s+to\s+"
        r"(\d+(?:\.\d+)?(?:\s*[/\u2044]\s*\d+(?:,\d{3})*)?)\s*(?:second|sec)",
        text,
    )
    if not match:
        return None, None

    def _to_seconds(token: str) -> float:
        token = token.replace(",", "").replace("\u2044", "/").strip()
        if "/" in token:
            parts = token.split("/", 1)
            return float(parts[0]) / float(parts[1].replace(" ", ""))
        return float(token)

    try:
        return _to_seconds(match.group(1)), _to_seconds(match.group(2))
    except ValueError:
        return None, None


def derive_reciprocity_compensation(
    scalars: dict,
    full_text: str = "",
) -> dict[str, Any] | None:
    note = scalars.get("reciprocity_text") or ""
    text = f"{note} {full_text}".lower()

    lo, hi = _parse_reciprocity_range(text)
    formula = None
    formula_match = re.search(r"ta\s*=\s*tm\s*\^?\s*([\d.]+)", text, re.I)
    if formula_match:
        formula = f"Ta = Tm^{formula_match.group(1)}"

    if lo is not None and hi is not None:
        return {
            "no_correction_range_s": [round(lo, 6), round(hi, 6)],
            "assumed_exposure_s": 0.008,
            "toe_lift": 0.0,
            "formula": formula,
            "note": note[:240] if note else None,
        }

    if "no filter correction or exposure compensation" in text or "no correction" in text:
        return {
            "no_correction_range_s": [0.0001, 1.0],
            "assumed_exposure_s": 0.008,
            "toe_lift": 0.0,
            "formula": formula,
        }

    if formula:
        exp = float(formula_match.group(1)) if formula_match else 1.31
        return {
            "assumed_exposure_s": 1.0,
            "correction_exponent": exp,
            "toe_lift": 0.025,
            "formula": formula,
        }
    return None


def derive_ei_variants_from_curves(curves: list[dict], base_iso: int) -> dict[str, Any] | None:
    char = _curve_by_type(curves, "characteristic_curves")
    if not char:
        return None

    series = char.get("series") or []
    if len(series) <= 3:
        return None

    variants: dict[str, dict[str, float]] = {}
    for extra in series[3:]:
        name = (extra.get("name") or "").lower()
        ei_match = re.search(r"(\d{3,4})", name)
        if not ei_match:
            continue
        ei = int(ei_match.group(1))
        if ei == base_iso:
            continue
        ratio = ei / max(1, base_iso)
        variants[str(ei)] = {
            "contrast_pct_delta": round(min(18.0, (ratio - 1.0) * 12.0), 1),
            "gamma_delta": round(min(0.12, (ratio - 1.0) * 0.08), 3),
            "grain_strength_mult": round(math.sqrt(ratio), 3),
            "lift_delta": round(-0.01 * (ratio - 1.0), 4),
        }

    if not variants:
        return None
    return {"base_iso": base_iso, "variants": variants}


def blend_color_matrices(
    existing: list[list[float]] | None,
    derived: list[list[float]],
    blend: float = 0.35,
) -> list[list[float]]:
    identity = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    base = np.array(existing or identity, dtype=np.float64)
    target = np.array(derived, dtype=np.float64)
    out = base * (1.0 - blend) + target * blend
    return [[round(float(v), 4) for v in row] for row in out.tolist()]
