"""Digitize curves from film datasheet PDF pages (vector paths + image fallback)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import numpy as np

# PDF user-space y grows downward; data y grows upward.
NUMERIC_TICK = re.compile(r"^-?\d+(?:\.\d+)?$")

CURVE_SECTIONS = frozenset(
    {
        "characteristic_curves",
        "spectral_sensitivity",
        "spectral_dye_density",
        "mtf",
    }
)

# Typical axis ranges used to classify plot type when labels are sparse.
PLOT_SIGNATURES: tuple[tuple[str, tuple[float, float], tuple[float, float]], ...] = (
    ("characteristic_curves", (-4.5, 1.5), (0.0, 4.5)),
    ("spectral_sensitivity", (-4.5, 1.5), (0.0, 2.5)),
    ("spectral_dye_density", (350.0, 750.0), (0.0, 3.0)),
    ("mtf", (0.0, 120.0), (0.0, 1.2)),
)

# BGR-ish curve colors on rendered pages (OpenCV order in numpy RGB actually RGB).
IMAGE_CURVE_COLORS: tuple[tuple[str, tuple[int, int, int], int], ...] = (
    ("red", (200, 40, 40), 55),
    ("green", (40, 140, 60), 55),
    ("blue", (40, 80, 200), 55),
    ("cyan", (40, 160, 180), 55),
    ("magenta", (180, 40, 140), 55),
    ("yellow", (200, 180, 40), 55),
    ("black", (30, 30, 30), 40),
)


@dataclass
class TickLabel:
    value: float
    x: float
    y: float


@dataclass
class PlotRegion:
    plot_id: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    x_ticks: list[TickLabel] = field(default_factory=list)
    y_ticks: list[TickLabel] = field(default_factory=list)
    guess_type: str = "unknown"


@dataclass
class Polyline:
    points: list[tuple[float, float]]
    color: tuple[float, float, float] | None
    width: float


def _parse_numeric(text: str) -> float | None:
    text = text.strip()
    if not NUMERIC_TICK.match(text):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def extract_tick_labels(page: fitz.Page) -> list[TickLabel]:
    labels: list[TickLabel] = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                value = _parse_numeric(span.get("text", ""))
                if value is None:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                labels.append(TickLabel(value=value, x=(x0 + x1) / 2, y=(y0 + y1) / 2))
    return labels


def _is_monotonic(values: list[float], *, allow_dups: bool = True) -> bool:
    if len(values) < 3:
        return False
    if allow_dups:
        values = [values[0]] + [v for i, v in enumerate(values[1:]) if abs(v - values[i]) > 1e-6]
    if len(values) < 3:
        return False
    diffs = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    return pos >= len(diffs) - 1 or neg >= len(diffs) - 1


def _trim_axis_segment(segment: list[TickLabel]) -> list[TickLabel]:
    """Drop trailing tick labels that break monotonicity (legend/key bleed)."""
    segment = sorted(segment, key=lambda lbl: lbl.x)
    for end in range(len(segment), 3, -1):
        sub = segment[:end]
        if _is_monotonic([lbl.value for lbl in sub]):
            return sub
    return segment


def _trim_leading_outliers(segment: list[TickLabel], max_step: float = 50.0) -> list[TickLabel]:
    segment = sorted(segment, key=lambda lbl: lbl.x)
    while len(segment) > 4:
        values = [lbl.value for lbl in segment]
        gaps = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
        if gaps and max(gaps) > max_step:
            worst = gaps.index(max(gaps))
            if worst == 0:
                segment = segment[1:]
                continue
        break
    return segment


def _clean_horizontal_axis(segment: list[TickLabel]) -> list[TickLabel]:
    segment = sorted(segment, key=lambda lbl: lbl.x)
    for start in range(len(segment)):
        sub = segment[start:]
        if len(sub) >= 4 and _is_monotonic([lbl.value for lbl in sub]):
            return _dedupe_axis_ticks(sub)
    return _dedupe_axis_ticks(_trim_leading_outliers(_trim_axis_segment(segment)))


def _dedupe_axis_ticks(segment: list[TickLabel]) -> list[TickLabel]:
    out: list[TickLabel] = []
    for lbl in sorted(segment, key=lambda lbl: lbl.x):
        if out and abs(lbl.x - out[-1].x) < 8 and abs(lbl.value - out[-1].value) < 1e-6:
            continue
        out.append(lbl)
    return out


def _classify_axis_ticks(ticks: list[TickLabel]) -> str:
    if len(ticks) < 4:
        return "unknown"
    vals = [t.value for t in ticks]
    wavelength = sum(1 for v in vals if v >= 300)
    if wavelength >= 3:
        return "spectral_dye_density"
    if max(vals) >= 10 and min(vals) >= 0 and any(v in (10, 20, 50, 100, 200) for v in vals):
        return "mtf"
    if min(vals) < 0 or (min(vals) <= 0 and max(vals) <= 1.5):
        return "characteristic_curves"
    if min(vals) <= 0 and max(vals) <= 3.5:
        return "spectral_sensitivity"
    return "unknown"


def _split_row_by_x_gaps(row: list[TickLabel], gap_px: float = 75.0) -> list[list[TickLabel]]:
    """Split a tick row into separate axes when labels cluster in disjoint x bands."""
    if not row:
        return []
    row = sorted(row, key=lambda lbl: lbl.x)
    segments: list[list[TickLabel]] = [[row[0]]]
    for lbl in row[1:]:
        if lbl.x - segments[-1][-1].x > gap_px:
            segments.append([lbl])
        else:
            segments[-1].append(lbl)
    return segments


def _find_horizontal_axes(labels: list[TickLabel], y_tol: float = 4.0) -> list[list[TickLabel]]:
    """Group tick labels that sit on a shared horizontal baseline (x-axis)."""
    if not labels:
        return []
    sorted_labels = sorted(labels, key=lambda lbl: lbl.y)
    rows: list[list[TickLabel]] = []
    current: list[TickLabel] = [sorted_labels[0]]
    for lbl in sorted_labels[1:]:
        if abs(lbl.y - current[-1].y) <= y_tol:
            current.append(lbl)
        else:
            rows.append(current)
            current = [lbl]
    rows.append(current)

    axes: list[list[TickLabel]] = []
    for row in rows:
        for segment in _split_row_by_x_gaps(row):
            segment = _clean_horizontal_axis(segment)
            if len(segment) < 4:
                continue
            x_span = segment[-1].x - segment[0].x
            if x_span < 70:
                continue
            if not _is_monotonic([lbl.value for lbl in segment]):
                continue
            axes.append(segment)
    return axes


def _find_vertical_axis(
    labels: list[TickLabel],
    x_left: float,
    x_right: float,
    y_top: float,
    y_bottom: float,
    x_tol: float = 45.0,
) -> list[TickLabel]:
    """Find y-axis ticks on the left or right edge of a plot band."""
    candidates = [
        lbl
        for lbl in labels
        if y_top <= lbl.y <= y_bottom and (lbl.x <= x_left + x_tol or lbl.x >= x_right - x_tol)
    ]
    if len(candidates) < 3:
        return []
    candidates.sort(key=lambda lbl: lbl.y)
    if not _is_monotonic([lbl.value for lbl in candidates]):
        return []
    if candidates[-1].y - candidates[0].y < 40:
        return []
    return candidates


def _fit_linear(pixels: list[float], values: list[float]) -> tuple[float, float] | None:
    if len(pixels) < 2 or len(values) < 2:
        return None
    px = np.array(pixels, dtype=np.float64)
    vy = np.array(values, dtype=np.float64)
    if np.allclose(px.std(), 0):
        return None
    slope, intercept = np.polyfit(px, vy, 1)
    return float(slope), float(intercept)


def _guess_plot_type(x_range: tuple[float, float], y_range: tuple[float, float]) -> str:
    best = "unknown"
    best_score = float("inf")
    for name, x_sig, y_sig in PLOT_SIGNATURES:
        score = abs(x_range[0] - x_sig[0]) + abs(x_range[1] - x_sig[1])
        score += abs(y_range[0] - y_sig[0]) + abs(y_range[1] - y_sig[1])
        if score < best_score:
            best_score = score
            best = name
    return best if best_score < 8.0 else "unknown"


def find_plot_regions(page: fitz.Page, sections: list[str]) -> list[PlotRegion]:
    labels = extract_tick_labels(page)
    if len(labels) < 6:
        return []

    horizontal_axes = _find_horizontal_axes(labels)
    if not horizontal_axes:
        return []

    horizontal_axes.sort(key=lambda row: row[0].y)

    regions: list[PlotRegion] = []
    for index, h_ticks in enumerate(horizontal_axes):
        x_px = [t.x for t in h_ticks]
        x_vals = [t.value for t in h_ticks]
        x_fit = _fit_linear(x_px, x_vals)
        if not x_fit:
            continue

        axis_y = float(np.mean([t.y for t in h_ticks]))
        y_max_px = axis_y - 8
        y_min_px = max(40.0, axis_y - 195)

        x_left_px = min(x_px)
        x_right_px = max(x_px)
        v_ticks = _find_vertical_axis(labels, x_left_px, x_right_px, y_min_px, y_max_px)
        y_px = [t.y for t in v_ticks] if v_ticks else []
        y_fit = _fit_linear(y_px, [t.value for t in v_ticks]) if v_ticks else None

        x_min_val = x_fit[0] * x_left_px + x_fit[1]
        x_max_val = x_fit[0] * x_right_px + x_fit[1]
        if x_min_val > x_max_val:
            x_min_val, x_max_val = x_max_val, x_min_val

        guess = _classify_axis_ticks(h_ticks)

        regions.append(
            PlotRegion(
                plot_id=f"plot_{index + 1}_{guess}",
                x_min=x_left_px,
                x_max=x_right_px,
                y_min=y_min_px,
                y_max=y_max_px,
                x_ticks=h_ticks,
                y_ticks=v_ticks,
                guess_type=guess,
            )
        )

    _assign_log_exposure_types(regions, sections)
    _add_spectral_sensitivity_band(regions, sections)
    _expand_regions_from_frame_boxes(regions, _drawing_polylines(page))
    return _dedupe_regions_by_type(regions)


def _dedupe_regions_by_type(regions: list[PlotRegion]) -> list[PlotRegion]:
    """Keep the strongest region per plot type (most axis ticks × plot area)."""
    best: dict[str, PlotRegion] = {}
    extras: list[PlotRegion] = []
    for region in regions:
        if region.guess_type == "unknown":
            continue
        if region.plot_id == "plot_spectral_sensitivity_band":
            extras.append(region)
            continue
        existing = best.get(region.guess_type)
        if region.guess_type == "spectral_dye_density" and existing:
            if region.x_ticks[0].y < existing.x_ticks[0].y:
                best[region.guess_type] = region
            continue
        score = len(region.x_ticks) * max(1.0, region.y_max - region.y_min)
        if existing is None or score > len(existing.x_ticks) * max(1.0, existing.y_max - existing.y_min):
            best[region.guess_type] = region
    return list(best.values()) + extras


def _assign_log_exposure_types(regions: list[PlotRegion], sections: list[str]) -> None:
    """Disambiguate stacked log-exposure plots (characteristic vs spectral sensitivity)."""

    def _is_log_exposure_axis(ticks: list[TickLabel]) -> bool:
        if len(ticks) < 4:
            return False
        vals = [t.value for t in ticks]
        if any(v >= 100 for v in vals):
            return False
        return min(vals) <= 0 and max(vals) <= 2.0

    ambiguous = [
        r
        for r in regions
        if _is_log_exposure_axis(r.x_ticks)
        and r.guess_type in ("characteristic_curves", "spectral_sensitivity", "unknown")
    ]
    if len(ambiguous) < 2:
        return
    ambiguous.sort(key=lambda r: r.x_ticks[0].y)
    type_order: list[str] = []
    if "characteristic_curves" in sections:
        type_order.append("characteristic_curves")
    if "spectral_sensitivity" in sections:
        type_order.append("spectral_sensitivity")
    if not type_order:
        type_order = ["characteristic_curves", "spectral_sensitivity"]
    for idx, region in enumerate(ambiguous):
        if idx < len(type_order):
            region.guess_type = type_order[idx]
            base = region.plot_id.rsplit("_", 1)[0]
            region.plot_id = f"{base}_{region.guess_type}"


def _add_spectral_sensitivity_band(regions: list[PlotRegion], sections: list[str]) -> None:
    if "spectral_sensitivity" not in sections:
        return
    if any(r.guess_type == "spectral_sensitivity" for r in regions):
        return
    char = next((r for r in regions if r.guess_type == "characteristic_curves"), None)
    if not char:
        return
    y_top = char.y_max + 3
    y_bottom = char.y_max + 90
    if y_bottom - y_top < 40:
        return
    regions.append(
        PlotRegion(
            plot_id="plot_spectral_sensitivity_band",
            x_min=char.x_min,
            x_max=char.x_max,
            y_min=y_top,
            y_max=y_bottom,
            x_ticks=char.x_ticks,
            y_ticks=char.y_ticks,
            guess_type="spectral_sensitivity",
        )
    )


def _expand_regions_from_frame_boxes(regions: list[PlotRegion], polylines: list[Polyline]) -> None:
    for region in regions:
        for poly in polylines:
            if not _is_box_path(poly.points):
                continue
            xs = [p[0] for p in poly.points]
            ys = [p[1] for p in poly.points]
            x_overlap = min(xs) <= region.x_max and max(xs) >= region.x_min
            if not x_overlap:
                continue
            region.y_min = min(region.y_min, min(ys))
            region.y_max = max(region.y_max, max(ys))


def _is_box_path(points: list[tuple[float, float]]) -> bool:
    xs = {round(p[0]) for p in points}
    ys = {round(p[1]) for p in points}
    return len(xs) <= 4 and len(ys) <= 4


def _series_matches_type(points: list[tuple[float, float]], plot_type: str) -> bool:
    xs = [p[0] for p in points]
    mn, mx = min(xs), max(xs)
    if plot_type == "characteristic_curves":
        return mn >= -5.5 and mx <= 4.5
    if plot_type == "spectral_dye_density":
        return mn >= 300 and mx <= 820
    if plot_type == "spectral_sensitivity":
        return mn >= -5.5 and mx <= 4.5
    if plot_type == "mtf":
        return mn >= 0 and mx <= 150
    return True


def _looks_like_grid(points: list[tuple[float, float]]) -> bool:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    if span_x < 30 and span_y < 30:
        return True
    if span_y < 2.5 and span_x > 20:
        return True
    if span_x < 2.5 and span_y > 20:
        return True
    return False


def _drawing_polylines(page: fitz.Page, min_width: float = 0.5) -> list[Polyline]:
    polylines: list[Polyline] = []
    for drawing in page.get_drawings():
        color = drawing.get("color")
        width = float(drawing.get("width") or 0)
        if color is None or width < min_width:
            continue
        points: list[tuple[float, float]] = []
        for item in drawing.get("items", []):
            op = item[0]
            if op == "l" and len(item) >= 3:
                points.append((float(item[1].x), float(item[1].y)))
                points.append((float(item[2].x), float(item[2].y)))
            elif op == "c" and len(item) >= 6:
                points.append((float(item[4].x), float(item[4].y)))
                points.append((float(item[5].x), float(item[5].y)))
        if len(points) < 12:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if max(xs) - min(xs) < 70 or max(ys) - min(ys) < 12:
            continue
        if _looks_like_grid(points):
            continue
        polylines.append(Polyline(points=points, color=color, width=width))
    return polylines


def _merge_polyline_points(points: list[tuple[float, float]], tol: float = 1.5) -> list[tuple[float, float]]:
    if not points:
        return []
    # dedupe consecutive
    merged = [points[0]]
    for pt in points[1:]:
        if math.hypot(pt[0] - merged[-1][0], pt[1] - merged[-1][1]) > 0.3:
            merged.append(pt)
    return merged


def _polyline_in_region(poly: Polyline, region: PlotRegion) -> bool:
    if not poly.points:
        return False
    xs = [p[0] for p in poly.points]
    ys = [p[1] for p in poly.points]
    if max(xs) < region.x_min or min(xs) > region.x_max:
        return False
    if max(ys) < region.y_min or min(ys) > region.y_max:
        return False
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    return region.x_min <= cx <= region.x_max and region.y_min <= cy <= region.y_max


def _pixel_to_data(
    x_px: float,
    y_px: float,
    region: PlotRegion,
) -> tuple[float, float] | None:
    x_ticks = region.x_ticks
    x_px_vals = [t.x for t in x_ticks]
    x_data_vals = [t.value for t in x_ticks]

    if region.guess_type == "mtf" and max(x_data_vals) >= 10:
        log_vals = [math.log10(max(v, 0.01)) for v in x_data_vals]
        log_fit = _fit_linear(x_px_vals, log_vals)
        if not log_fit:
            return None
        x_val = 10 ** (log_fit[0] * x_px + log_fit[1])
    else:
        x_fit = _fit_linear(x_px_vals, x_data_vals)
        if not x_fit:
            return None
        x_val = x_fit[0] * x_px + x_fit[1]

    if region.y_ticks:
        y_fit = _fit_linear([t.y for t in region.y_ticks], [t.value for t in region.y_ticks])
        if not y_fit:
            return None
    else:
        # Fallback: map plot pixel height to a sensible default range by plot type.
        defaults = {
            "characteristic_curves": (4.0, 0.0),
            "spectral_sensitivity": (2.0, 0.0),
            "spectral_dye_density": (3.0, 0.0),
            "mtf": (1.0, 0.0),
        }
        y_top_val, y_bottom_val = defaults.get(region.guess_type, (1.0, 0.0))
        t = (y_px - region.y_min) / max(1.0, region.y_max - region.y_min)
        y_val = y_top_val + t * (y_bottom_val - y_top_val)
        return round(float(x_val), 4), round(y_val, 4)

    y_val = y_fit[0] * y_px + y_fit[1]
    return round(float(x_val), 4), round(y_val, 4)


def _resample_series(points: list[list[float]], target_count: int = 64) -> list[list[float]]:
    if len(points) < 2:
        return points
    arr = np.array(points, dtype=np.float64)
    order = np.argsort(arr[:, 0])
    arr = arr[order]
    # drop duplicate x
    keep = [0]
    for i in range(1, len(arr)):
        if arr[i, 0] > arr[keep[-1], 0] + 1e-6:
            keep.append(i)
    arr = arr[keep]
    if len(arr) < 2:
        return arr.tolist()
    xs = np.linspace(arr[0, 0], arr[-1, 0], num=min(target_count, max(16, len(arr))))
    ys = np.interp(xs, arr[:, 0], arr[:, 1])
    return [[round(float(x), 4), round(float(y), 4)] for x, y in zip(xs, ys)]


def _cluster_polylines_into_series(polys: list[Polyline], region: PlotRegion) -> list[list[tuple[float, float]]]:
    """Convert each vector path in the plot region to one resampled data series."""
    series_points: list[list[tuple[float, float]]] = []
    for poly in polys:
        if _is_box_path(poly.points):
            continue
        merged = _merge_polyline_points(poly.points)
        data_pts: list[tuple[float, float]] = []
        for x_px, y_px in merged:
            converted = _pixel_to_data(x_px, y_px, region)
            if converted:
                data_pts.append(converted)
        if len(data_pts) >= 4:
            series_points.append(data_pts)

    if not series_points:
        return []

    # Drop near-duplicate series (PDF sometimes emits the same path twice).
    unique: list[list[tuple[float, float]]] = []
    for pts in series_points:
        arr = np.array(pts)
        mid_x = float(np.median(arr[:, 0]))
        mid_y = float(np.median(arr[:, 1]))
        duplicate = False
        for existing in unique:
            ex = np.array(existing)
            if abs(float(np.median(ex[:, 0])) - mid_x) < 0.15 and abs(float(np.median(ex[:, 1])) - mid_y) < 0.15:
                duplicate = True
                break
        if not duplicate and _series_matches_type(pts, region.guess_type):
            unique.append(pts)
    return unique


def _axis_metadata(plot_type: str) -> tuple[dict, dict]:
    if plot_type == "spectral_dye_density":
        return (
            {"label": "wavelength", "unit": "nm"},
            {"label": "density", "unit": "status_m"},
        )
    if plot_type == "mtf":
        return (
            {"label": "spatial_frequency", "unit": "cycles_per_mm"},
            {"label": "response", "unit": "relative"},
        )
    if plot_type == "spectral_sensitivity":
        return (
            {"label": "log_exposure", "unit": "relative"},
            {"label": "sensitivity", "unit": "relative"},
        )
    return (
        {"label": "log_exposure", "unit": "relative"},
        {"label": "density", "unit": "status_m"},
    )


def _series_name(plot_type: str, index: int, count: int) -> str:
    if plot_type == "spectral_dye_density" and count == 3:
        return ("cyan_forming", "magenta_forming", "yellow_forming")[index]
    if plot_type in ("characteristic_curves", "spectral_sensitivity") and count == 3:
        return ("red_sensitive", "green_sensitive", "blue_sensitive")[index]
    return f"series_{index + 1}"


def _image_trace_region(
    rgb: np.ndarray,
    region: PlotRegion,
    pdf_to_px: float,
) -> list[list[tuple[float, float]]]:
    x0 = max(0, int(region.x_min * pdf_to_px))
    y0 = max(0, int(region.y_min * pdf_to_px))
    x1 = min(rgb.shape[1], int(region.x_max * pdf_to_px))
    y1 = min(rgb.shape[0], int(region.y_max * pdf_to_px))
    if x1 - x0 < 40 or y1 - y0 < 40:
        return []

    bbox = (x0, y0, x1, y1)
    all_series: list[list[tuple[float, float]]] = []
    for color_name, target_rgb, tol in IMAGE_CURVE_COLORS:
        traced = _trace_curve_from_image(rgb, bbox, color_name, target_rgb, tol)
        if not traced:
            continue
        data_pts: list[tuple[float, float]] = []
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        for x_norm, y_norm in traced:
            x_px = (x0 + x_norm * width) / pdf_to_px
            y_px = (y0 + (1.0 - y_norm) * height) / pdf_to_px
            converted = _pixel_to_data(x_px, y_px, region)
            if converted:
                data_pts.append(converted)
        if len(data_pts) >= 8 and _series_matches_type(data_pts, region.guess_type):
            all_series.append(data_pts)
    return all_series


def extract_curves_vector(page: fitz.Page, page_number: int, sections: list[str]) -> list[dict]:
    if not any(section in CURVE_SECTIONS for section in sections):
        # also try if page mentions curves in text
        text = page.get_text("text").lower()
        if not any(k in text for k in ("characteristic curve", "spectral", "mtf", "dye density")):
            return []

    regions = find_plot_regions(page, sections)
    if not regions:
        return []

    polylines = _drawing_polylines(page)
    curves_out: list[dict] = []

    for region in regions:
        in_region = [p for p in polylines if _polyline_in_region(p, region)]
        series_data = _cluster_polylines_into_series(in_region, region)
        if not series_data:
            continue

        x_axis, y_axis = _axis_metadata(region.guess_type)
        series_list: list[dict] = []
        for idx, pts in enumerate(series_data):
            resampled = _resample_series([[x, y] for x, y in pts])
            if len(resampled) < 4:
                continue
            series_list.append(
                {
                    "name": _series_name(region.guess_type, idx, len(series_data)),
                    "points": resampled,
                    "point_count": len(resampled),
                }
            )

        if not series_list:
            continue

        curves_out.append(
            {
                "curve_id": region.plot_id,
                "page": page_number,
                "type": region.guess_type,
                "extraction": "vector",
                "x_axis": x_axis,
                "y_axis": y_axis,
                "series": series_list,
            }
        )
    return curves_out


def _trace_curve_from_image(
    rgb: np.ndarray,
    plot_bbox: tuple[int, int, int, int],
    color_name: str,
    target_rgb: tuple[int, int, int],
    tolerance: int,
) -> list[list[float]] | None:
    x0, y0, x1, y1 = plot_bbox
    crop = rgb[y0:y1, x0:x1].astype(np.int16)
    if crop.size == 0:
        return None
    tr, tg, tb = target_rgb
    dist = np.abs(crop[:, :, 0] - tr) + np.abs(crop[:, :, 1] - tg) + np.abs(crop[:, :, 2] - tb)
    mask = dist < tolerance
    if mask.sum() < 80:
        return None

    height, width = mask.shape
    points: list[list[float]] = []
    for col in range(0, width, max(1, width // 80)):
        rows = np.where(mask[:, col])[0]
        if rows.size == 0:
            continue
        row = int(np.median(rows))
        x_norm = col / max(1, width - 1)
        y_norm = 1.0 - row / max(1, height - 1)
        points.append([round(x_norm, 4), round(y_norm, 4)])

    if len(points) < 10:
        return None
    return _resample_series(points, target_count=48)


def extract_curves_image(
    render_path: Path,
    page_number: int,
    sections: list[str],
    width: int,
    height: int,
) -> list[dict]:
    if not render_path.is_file():
        return []
    from PIL import Image

    img = np.array(Image.open(render_path).convert("RGB"))
    h, w = img.shape[:2]

    # Heuristic plot bands for stacked datasheet layouts (top -> bottom).
    bands = [
        (0.08, 0.38, "characteristic_curves"),
        (0.36, 0.58, "spectral_sensitivity"),
        (0.56, 0.78, "spectral_dye_density"),
        (0.76, 0.96, "mtf"),
    ]

    curves: list[dict] = []
    for band_index, (y0_frac, y1_frac, plot_type) in enumerate(bands):
        if sections and plot_type not in sections and not any(s in CURVE_SECTIONS for s in sections):
            continue
        y0 = int(y0_frac * h)
        y1 = int(y1_frac * h)
        x0 = int(0.08 * w)
        x1 = int(0.92 * w)
        bbox = (x0, y0, x1, y1)

        series_list: list[dict] = []
        for color_name, rgb, tol in IMAGE_CURVE_COLORS:
            traced = _trace_curve_from_image(img, bbox, color_name, rgb, tol)
            if traced:
                series_list.append(
                    {
                        "name": color_name,
                        "points": traced,
                        "point_count": len(traced),
                        "note": "normalized_image_coordinates_0_to_1",
                    }
                )

        if not series_list:
            continue

        x_axis, y_axis = _axis_metadata(plot_type)
        curves.append(
            {
                "curve_id": f"p{page_number}_band{band_index + 1}_{plot_type}",
                "page": page_number,
                "type": plot_type,
                "extraction": "image_trace",
                "x_axis": x_axis,
                "y_axis": y_axis,
                "series": series_list[:6],
                "plot_bbox_px": {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "render_width": width, "render_height": height},
            }
        )
    return curves


def extract_page_curves(
    page: fitz.Page,
    page_number: int,
    sections: list[str],
    render_path: Path | None,
    render_size: tuple[int, int] | None,
    render_scale: float = 2.0,
) -> list[dict]:
    if not any(section in CURVE_SECTIONS for section in sections):
        text = page.get_text("text").lower()
        if not any(k in text for k in ("characteristic curve", "spectral", "mtf", "dye density")):
            return []

    regions = find_plot_regions(page, sections)
    if not regions:
        return []

    polylines = _drawing_polylines(page)
    rgb: np.ndarray | None = None
    if render_path and render_path.is_file():
        from PIL import Image

        rgb = np.array(Image.open(render_path).convert("RGB"))

    curves_out: list[dict] = []
    seen_types: set[str] = set()

    for region in regions:
        if region.guess_type in seen_types or region.guess_type == "unknown":
            continue

        in_region = [
            p for p in polylines if _polyline_in_region(p, region) and not _is_box_path(p.points)
        ]
        series_data = _cluster_polylines_into_series(in_region, region)
        extraction = "vector"

        if not series_data and rgb is not None:
            series_data = _image_trace_region(rgb, region, render_scale)
            extraction = "image_trace"

        if not series_data:
            continue

        seen_types.add(region.guess_type)
        x_axis, y_axis = _axis_metadata(region.guess_type)
        series_list: list[dict] = []
        for idx, pts in enumerate(series_data):
            resampled = _resample_series([[x, y] for x, y in pts])
            if len(resampled) < 4:
                continue
            series_list.append(
                {
                    "name": _series_name(region.guess_type, idx, len(series_data)),
                    "points": resampled,
                    "point_count": len(resampled),
                }
            )

        if not series_list:
            continue

        curves_out.append(
            {
                "curve_id": region.plot_id,
                "page": page_number,
                "type": region.guess_type,
                "extraction": extraction,
                "x_axis": x_axis,
                "y_axis": y_axis,
                "series": series_list,
            }
        )

    return curves_out


def derive_leakage_from_dye_density(curve: dict) -> dict[str, Any] | None:
    """Build a 3x3 dye leakage matrix from spectral_dye_density series (sampled at 550/550/550 nm bands)."""
    if curve.get("type") != "spectral_dye_density":
        return None
    if curve.get("extraction") != "vector":
        return None
    series = curve.get("series") or []
    if len(series) < 3:
        return None

    # Map series names to rows; sample density at representative wavelengths per dye column heuristic.
    # Rows = R/G/B measurement bands, cols = C/M/Y dyes.
    def sample(series_points: list[list[float]], wavelength: float) -> float:
        arr = np.array(series_points, dtype=np.float64)
        if len(arr) < 2:
            return 1.0
        return float(np.interp(wavelength, arr[:, 0], arr[:, 1]))

    # Use series order cyan/magenta/yellow as columns
    cols: list[list[float]] = []
    for s in series[:3]:
        pts = s.get("points") or []
        cols.append(
            [
                max(0.0, sample(pts, 650)),  # red band
                max(0.0, sample(pts, 550)),  # green band
                max(0.0, sample(pts, 450)),  # blue band
            ]
        )
    # columns are dyes; build matrix A[i][j] = band i reading for dye j alone -> use diagonal normalization later
    matrix = [
        [cols[0][0], cols[1][0], cols[2][0]],
        [cols[0][1], cols[1][1], cols[2][1]],
        [cols[0][2], cols[1][2], cols[2][2]],
    ]
    return {
        "leakage_matrix": matrix,
        "note": "Heuristic sampling from dye-density curves; verify before preset export.",
    }
