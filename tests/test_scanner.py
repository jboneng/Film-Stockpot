"""Tests for the interactive scanner adjustments."""

import numpy as np

from film_stockpot.image.scanner import NEUTRAL, apply_scanner_adjustments


def _sample_rgb(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((16, 16, 3), dtype=np.float32)


def test_neutral_settings_are_identity() -> None:
    rgb = _sample_rgb()
    result = apply_scanner_adjustments(rgb, dict(NEUTRAL))
    assert np.allclose(result, rgb, atol=1e-6)


def test_no_settings_is_identity() -> None:
    rgb = _sample_rgb()
    result = apply_scanner_adjustments(rgb, None)
    assert np.allclose(result, rgb, atol=1e-6)


def test_positive_density_darkens() -> None:
    rgb = np.full((8, 8, 3), 0.5, dtype=np.float32)
    result = apply_scanner_adjustments(rgb, {"density": 10})
    assert result.mean() < 0.5


def test_positive_gamma_brightens_midtones() -> None:
    rgb = np.full((8, 8, 3), 0.5, dtype=np.float32)
    result = apply_scanner_adjustments(rgb, {"gamma": 10})
    assert result.mean() > 0.5


def test_cyan_slider_moves_toward_labeled_colors() -> None:
    rgb = np.full((8, 8, 3), 0.5, dtype=np.float32)
    toward_cyan = apply_scanner_adjustments(rgb, {"cyan": -10})
    toward_red = apply_scanner_adjustments(rgb, {"cyan": 10})
    assert toward_cyan[:, :, 0].mean() < 0.5
    assert toward_red[:, :, 0].mean() > 0.5
    assert np.allclose(toward_cyan[:, :, 1], 0.5)
    assert np.allclose(toward_red[:, :, 1], 0.5)


def test_magenta_slider_moves_toward_labeled_colors() -> None:
    rgb = np.full((8, 8, 3), 0.5, dtype=np.float32)
    toward_magenta = apply_scanner_adjustments(rgb, {"magenta": -10})
    toward_green = apply_scanner_adjustments(rgb, {"magenta": 10})
    assert toward_magenta[:, :, 1].mean() < 0.5
    assert toward_green[:, :, 1].mean() > 0.5


def test_yellow_slider_moves_toward_labeled_colors() -> None:
    rgb = np.full((8, 8, 3), 0.5, dtype=np.float32)
    toward_yellow = apply_scanner_adjustments(rgb, {"yellow": -10})
    toward_blue = apply_scanner_adjustments(rgb, {"yellow": 10})
    assert toward_yellow[:, :, 2].mean() < 0.5
    assert toward_blue[:, :, 2].mean() > 0.5


def test_does_not_mutate_input() -> None:
    rgb = _sample_rgb()
    original = rgb.copy()
    apply_scanner_adjustments(rgb, {"density": 5, "saturation": 4, "tone": "Hard"})
    assert np.array_equal(rgb, original)


def test_combined_settings_stay_in_range() -> None:
    rgb = _sample_rgb()
    settings = {
        "density": -8,
        "cyan": 6,
        "magenta": -4,
        "yellow": 3,
        "highlight": 10,
        "shadow": -6,
        "saturation": 8,
        "sharpness": 6,
        "tone": "All Hard",
    }
    result = apply_scanner_adjustments(rgb, settings)
    assert result.shape == rgb.shape
    assert result.min() >= 0.0
    assert result.max() <= 1.0
