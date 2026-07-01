"""Tests for L/R/G/B curve adjustments."""

import numpy as np

from film_stockpot.image.curves import (
    CURVES_NEUTRAL,
    apply_curves,
    bezier_segments,
    build_curve_lut,
    curves_is_neutral,
    evaluate_curve,
    has_curve_adjustments,
    normalize_curve_points,
    normalize_curves,
)
from film_stockpot.image.io import compute_luma_histogram
from film_stockpot.image.grading import (
    GRADING_NEUTRAL,
    apply_grading_after_scanner,
    apply_interactive_adjustments,
    grading_is_neutral,
    has_grading_adjustments,
    normalize_grading,
)
from film_stockpot.image.scanner import NEUTRAL, apply_scanner_adjustments


def _gray_ramp() -> np.ndarray:
    ramp = np.linspace(0.1, 0.9, 8, dtype=np.float32)
    yy, xx = np.meshgrid(ramp, ramp, indexing="xy")
    gray = (xx + yy) * 0.5
    return np.stack([gray, gray, gray], axis=-1).astype(np.float32)


def test_default_curve_points_are_endpoints_and_midpoint() -> None:
    points = normalize_curve_points(None)
    assert points == [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]]


def test_neutral_curves_leave_image_unchanged() -> None:
    rgb = _gray_ramp()
    assert np.allclose(apply_curves(rgb, CURVES_NEUTRAL), rgb)
    assert curves_is_neutral(CURVES_NEUTRAL)
    assert not has_curve_adjustments(CURVES_NEUTRAL)


def test_red_curve_lifts_red_channel() -> None:
    rgb = np.full((4, 4, 3), 0.5, dtype=np.float32)
    curves = normalize_curves(CURVES_NEUTRAL)
    curves["R"] = [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]
    result = apply_curves(rgb, curves)
    assert float(result[0, 0, 0]) > float(rgb[0, 0, 0])
    assert np.allclose(result[..., 1], rgb[..., 1])
    assert np.allclose(result[..., 2], rgb[..., 2])


def test_luma_curve_preserves_neutral_grey() -> None:
    rgb = np.full((4, 4, 3), 0.4, dtype=np.float32)
    curves = normalize_curves(CURVES_NEUTRAL)
    curves["L"] = [[0.0, 0.0], [0.5, 0.65], [1.0, 1.0]]
    result = apply_curves(rgb, curves)
    assert np.allclose(result[..., 0], result[..., 1])
    assert np.allclose(result[..., 1], result[..., 2])
    assert float(result[0, 0, 0]) > float(rgb[0, 0, 0])


def test_build_curve_lut_is_monotonic_for_monotonic_points() -> None:
    lut = build_curve_lut([[0.0, 0.0], [0.5, 0.4], [1.0, 1.0]])
    assert np.all(np.diff(lut) >= -1e-6)


def test_evaluate_curve_interpolates_between_points() -> None:
    points = [[0.0, 0.0], [1.0, 1.0]]
    assert abs(evaluate_curve(points, 0.25) - 0.25) < 0.02


def test_bezier_curve_bends_toward_middle_point() -> None:
    points = [[0.0, 0.0], [0.5, 0.8], [1.0, 1.0]]
    assert evaluate_curve(points, 0.25) > 0.25
    assert abs(evaluate_curve(points, 0.5) - 0.8) < 0.05


def test_bezier_segments_returns_one_segment_per_span() -> None:
    points = [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]]
    assert len(bezier_segments(points)) == 2


def test_compute_luma_histogram_from_gray_image() -> None:
    rgb = np.full((4, 4, 3), 0.5, dtype=np.float32)
    hist = compute_luma_histogram(rgb)
    assert hist is not None
    assert hist.shape == (256,)
    assert float(hist.sum()) == 16.0


def test_grading_neutral_includes_curves() -> None:
    assert grading_is_neutral(GRADING_NEUTRAL)
    assert normalize_grading(GRADING_NEUTRAL)["curves"] == normalize_curves(CURVES_NEUTRAL)


def test_has_grading_adjustments_detects_curves_only() -> None:
    grading = {**GRADING_NEUTRAL, "curves": normalize_curves(CURVES_NEUTRAL)}
    grading["curves"]["G"] = [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]]
    assert has_grading_adjustments(grading)
    assert not grading_is_neutral(grading)


def test_apply_interactive_adjustments_runs_scanner_curves_then_wheels() -> None:
    rgb = _gray_ramp()
    settings = {
        **NEUTRAL,
        "grading": {
            **GRADING_NEUTRAL,
            "curves": {
                **CURVES_NEUTRAL,
                "B": [[0.0, 0.0], [0.5, 0.65], [1.0, 1.0]],
            },
            "midtones": {"hue": 120.0, "sat": 0.8, "lum": 0},
        },
    }
    after_scanner = apply_scanner_adjustments(rgb, settings)
    expected = apply_grading_after_scanner(after_scanner, settings)
    result = apply_interactive_adjustments(rgb, settings)
    assert np.allclose(result, expected)
    assert not np.allclose(result, after_scanner)
