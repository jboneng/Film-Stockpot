"""Tests for the film emulation pipeline."""

import numpy as np

from film_stockpot.image.pipeline import _apply_input_transform, apply_film_preset
from film_stockpot.presets.loader import get_preset, load_base


def _sample_rgb(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.random((16, 16, 3), dtype=np.float32)


def test_apply_preset_preserves_shape_and_range() -> None:
    rgb = _sample_rgb()
    preset = get_preset("kodak_portra_400")

    result = apply_film_preset(rgb, preset.data)

    assert result.shape == rgb.shape
    assert result.dtype == np.float32
    assert result.min() >= 0.0
    assert result.max() <= 1.0


def test_apply_preset_does_not_mutate_input() -> None:
    rgb = _sample_rgb()
    original = rgb.copy()
    preset = get_preset("kodak_ektar_100")

    apply_film_preset(rgb, preset.data)

    assert np.array_equal(rgb, original)


def test_apply_preset_changes_image() -> None:
    rgb = _sample_rgb()
    preset = get_preset("kodak_ektar_100")

    result = apply_film_preset(rgb, preset.data)

    assert not np.allclose(result, rgb)


def test_monochrome_preset_outputs_gray() -> None:
    rgb = _sample_rgb()
    preset = get_preset("ilford_hp5_plus")

    result = apply_film_preset(rgb, preset.data)

    assert np.allclose(result[:, :, 0], result[:, :, 1])
    assert np.allclose(result[:, :, 1], result[:, :, 2])


def test_base_has_input_transform() -> None:
    base = load_base()
    assert base is not None
    assert "input_transform" in base


def test_input_transform_expands_flat_range() -> None:
    flat = np.linspace(0.3, 0.6, 16 * 16 * 3, dtype=np.float32).reshape(16, 16, 3)
    transform = {
        "auto_levels": True,
        "per_channel": False,
        "black_clip_pct": 0.0,
        "white_clip_pct": 0.0,
        "delog_strength": 0.0,
    }

    expanded = _apply_input_transform(flat, transform)

    assert expanded.min() <= 0.01
    assert expanded.max() >= 0.99


def test_base_reduces_washout_on_flat_input() -> None:
    flat = np.linspace(0.35, 0.55, 16 * 16 * 3, dtype=np.float32).reshape(16, 16, 3)
    preset = get_preset("kodak_portra_400")
    base = load_base()

    without_base = apply_film_preset(flat, preset.data)
    with_base = apply_film_preset(flat, preset.data, base)

    assert np.ptp(with_base) > np.ptp(without_base)
