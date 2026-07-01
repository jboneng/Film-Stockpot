"""Tests for interactive color-wheel grading."""

import numpy as np

from film_stockpot.image.grading import (
    GRADING_NEUTRAL,
    GradingContext,
    _compute_zone_weights,
    _normalized_luma,
    apply_interactive_adjustments,
    apply_wheel_grading,
    grading_is_neutral,
    has_grading_adjustments,
    normalize_grading,
)
from film_stockpot.image.scanner import NEUTRAL, apply_scanner_adjustments


def _gray_image() -> np.ndarray:
    rgb = np.full((8, 8, 3), 0.5, dtype=np.float32)
    rgb[0:2, :, :] = 0.1
    rgb[6:8, :, :] = 0.9
    return rgb


def _flat_scan_image() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.uniform(0.38, 0.58, (128, 128, 3)).astype(np.float32)


def test_neutral_grading_is_unchanged() -> None:
    rgb = _gray_image()
    assert np.array_equal(apply_wheel_grading(rgb, {"grading": GRADING_NEUTRAL}), rgb)
    assert grading_is_neutral(GRADING_NEUTRAL)


def test_balance_only_does_not_change_image() -> None:
    rgb = _flat_scan_image()
    settings = {"grading": {**GRADING_NEUTRAL, "balance": 100}}
    result = apply_wheel_grading(rgb, settings)
    assert np.allclose(result, rgb)


def test_normalized_luma_spreads_flat_scan_range() -> None:
    rgb = _flat_scan_image()
    luma = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1, keepdims=True)
    luma_norm = _normalized_luma(luma)
    assert float(luma_norm.min()) < 0.05
    assert float(luma_norm.max()) > 0.95


def test_shadow_wheel_affects_flat_scan_darks() -> None:
    rgb = _flat_scan_image()
    luma = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1)
    settings = {
        "grading": {
            **GRADING_NEUTRAL,
            "shadows": {"hue": 0.0, "sat": 1.0, "lum": 0},
        }
    }
    result = apply_wheel_grading(rgb, settings)
    dark_mask = luma < np.percentile(luma, 20)
    bright_mask = luma > np.percentile(luma, 80)
    assert np.mean(np.abs(result[dark_mask] - rgb[dark_mask])) > 0.02
    assert np.mean(np.abs(result[bright_mask] - rgb[bright_mask])) < np.mean(
        np.abs(result[dark_mask] - rgb[dark_mask])
    )


def test_shadow_wheel_adds_color_in_shadows() -> None:
    rgb = _gray_image()
    settings = {
        "grading": {
            **GRADING_NEUTRAL,
            "shadows": {"hue": 0.0, "sat": 1.0, "lum": 0},
        }
    }
    result = apply_wheel_grading(rgb, settings)
    assert float(result[0, 0, 0]) > float(rgb[0, 0, 0])
    assert np.allclose(result[6, 0], rgb[6, 0], atol=0.05)


def test_highlight_luminance_lifts_bright_areas() -> None:
    rgb = _gray_image()
    settings = {
        "grading": {
            **GRADING_NEUTRAL,
            "highlights": {"hue": 0.0, "sat": 0.0, "lum": 50},
        }
    }
    result = apply_wheel_grading(rgb, settings)
    assert float(result[6, 0, 0]) > float(rgb[6, 0, 0])
    assert float(result[0, 0, 0]) == float(rgb[0, 0, 0])


def test_balance_shifts_shadow_weight() -> None:
    rgb = _flat_scan_image()
    luma = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=-1, keepdims=True)
    luma_norm = _normalized_luma(luma)
    low, _, _ = _compute_zone_weights(luma_norm, blending=50, balance=-80)
    high, _, _ = _compute_zone_weights(luma_norm, blending=50, balance=80)
    assert float(np.mean(low)) > float(np.mean(high))


def test_full_sat_produces_visible_change_on_flat_scan() -> None:
    rgb = _flat_scan_image()
    settings = {
        "grading": {
            **GRADING_NEUTRAL,
            "midtones": {"hue": 120.0, "sat": 1.0, "lum": 0},
        }
    }
    result = apply_wheel_grading(rgb, settings)
    assert np.mean(np.abs(result - rgb)) > 0.015


def test_has_grading_adjustments_ignores_blending_and_balance() -> None:
    assert not has_grading_adjustments(GRADING_NEUTRAL)
    assert not has_grading_adjustments({**GRADING_NEUTRAL, "blending": 10, "balance": -40})
    assert has_grading_adjustments(
        {**GRADING_NEUTRAL, "shadows": {"hue": 0.0, "sat": 0.3, "lum": 0}}
    )
    assert has_grading_adjustments(
        {**GRADING_NEUTRAL, "midtones": {"hue": 0.0, "sat": 0.0, "lum": 20}}
    )
    assert has_grading_adjustments(
        {
            **GRADING_NEUTRAL,
            "curves": {
                **GRADING_NEUTRAL["curves"],
                "R": [[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]],
            },
        }
    )


def test_partial_wheel_deflection_is_clearly_visible() -> None:
    # A modest wheel deflection (sat 0.4) must produce an obvious shift; the
    # previous double-attenuated blend made this nearly invisible (~0.015).
    rgb = _flat_scan_image()
    settings = {
        "grading": {
            **GRADING_NEUTRAL,
            "midtones": {"hue": 210.0, "sat": 0.4, "lum": 0},
        }
    }
    result = apply_wheel_grading(rgb, settings)
    assert np.mean(np.abs(result - rgb)) > 0.03


def test_stronger_settings_produce_stronger_change() -> None:
    rgb = _flat_scan_image()

    def shift(sat: float) -> float:
        settings = {
            "grading": {
                **GRADING_NEUTRAL,
                "midtones": {"hue": 300.0, "sat": sat, "lum": 0},
            }
        }
        return float(np.mean(np.abs(apply_wheel_grading(rgb, settings) - rgb)))

    assert shift(0.8) > shift(0.4) > shift(0.1)


def test_shared_context_handles_changing_image_shapes() -> None:
    # A reused context must never apply a cached mask to a differently shaped
    # image. This reproduces the drag-proxy -> full-resolution transition that
    # previously crashed with a broadcast error when array ids were recycled.
    context = GradingContext()
    settings = {
        "grading": {
            **GRADING_NEUTRAL,
            "shadows": {"hue": 210.0, "sat": 0.6, "lum": -8},
        }
    }
    rng = np.random.default_rng(0)
    for shape in ((64, 48, 3), (256, 192, 3), (64, 48, 3), (300, 200, 3)):
        rgb = rng.uniform(0.2, 0.8, shape).astype(np.float32)
        result = apply_wheel_grading(rgb, settings, grading_context=context)
        assert result.shape == shape
        assert result.dtype == np.float32


def test_interactive_adjustments_runs_scanner_then_grading() -> None:
    rgb = _gray_image()
    settings = {
        **NEUTRAL,
        "density": 5,
        "grading": {
            **GRADING_NEUTRAL,
            "midtones": {"hue": 120.0, "sat": 0.8, "lum": 0},
        },
    }
    expected = apply_wheel_grading(apply_scanner_adjustments(rgb, settings), settings)
    result = apply_interactive_adjustments(rgb, settings)
    assert np.allclose(result, expected)
