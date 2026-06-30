"""Tests for the film emulation pipeline."""

import numpy as np

from film_stockpot.image.pipeline import (
    _apply_acutance,
    _apply_color_grading,
    _apply_extracted_grain,
    _apply_halation,
    _apply_input_transform,
    _apply_per_channel_curves,
    _apply_reciprocity_compensation,
    _neutralize,
    analyze_input,
    apply_film_preset,
)
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


# --- Feature 1: input analysis / neutralization -------------------------------


def test_analyze_input_reports_per_channel_stats() -> None:
    rgb = _sample_rgb()

    stats = analyze_input(rgb)

    for channel in ("r", "g", "b"):
        assert {"black", "white", "median"} <= set(stats[channel])
        assert stats[channel]["black"] <= stats[channel]["white"]
    assert "luma_median" in stats


def test_neutralize_removes_channel_cast() -> None:
    cast = np.empty((8, 8, 3), dtype=np.float32)
    cast[:, :, 0] = 0.6
    cast[:, :, 1] = 0.4
    cast[:, :, 2] = 0.4

    neutral = _neutralize(cast, 1.0)
    medians = [float(np.median(neutral[:, :, c])) for c in range(3)]

    assert max(medians) - min(medians) < 0.02


def test_neutralize_strength_zero_is_noop() -> None:
    rgb = _sample_rgb()
    assert np.allclose(_neutralize(rgb, 0.0), rgb)


# --- Feature 2: tone-zoned color grading --------------------------------------


def test_color_grading_tints_shadows() -> None:
    shadow = np.full((8, 8, 3), 0.1, dtype=np.float32)

    graded = _apply_color_grading(shadow, {"shadows": [0.1, 0.0, 0.0]})

    assert graded[:, :, 0].mean() > shadow[:, :, 0].mean()
    assert np.allclose(graded[:, :, 1], shadow[:, :, 1])


def test_color_grading_none_is_noop() -> None:
    rgb = _sample_rgb()
    assert np.allclose(_apply_color_grading(rgb, None), rgb)


# --- Feature 3: halation ------------------------------------------------------


def test_halation_adds_light_with_red_bias() -> None:
    image = np.zeros((48, 48, 3), dtype=np.float32)
    image[20:28, 20:28, :] = 1.0
    halation = {"intensity": 0.6, "threshold": 0.5, "radius": 40, "color": [1.0, 0.3, 0.1]}

    out = _apply_halation(image, halation)

    assert out.sum() > image.sum()
    assert out[:, :, 0].sum() > out[:, :, 2].sum()


def test_halation_keeps_monochrome_gray() -> None:
    image = np.zeros((48, 48, 3), dtype=np.float32)
    image[20:28, 20:28, :] = 1.0
    halation = {"intensity": 0.6, "threshold": 0.5, "radius": 40, "color": [1.0, 0.3, 0.1]}

    out = _apply_halation(image, halation, monochrome=True)

    assert np.allclose(out[:, :, 0], out[:, :, 1])
    assert np.allclose(out[:, :, 1], out[:, :, 2])


# --- Feature 4: per-channel tone curves ---------------------------------------


def test_per_channel_curves_affect_only_named_channel() -> None:
    image = np.full((4, 4, 3), 0.5, dtype=np.float32)
    curves = {
        "r": [[0, 0], [128, 200], [255, 255]],
        "g": [[0, 0], [128, 128], [255, 255]],
        "b": [[0, 0], [128, 128], [255, 255]],
    }

    out = _apply_per_channel_curves(image, curves)

    assert out[:, :, 0].mean() > 0.5
    assert np.allclose(out[:, :, 1], 0.5)
    assert np.allclose(out[:, :, 2], 0.5)


# --- Feature 5: grain extraction ----------------------------------------------


def test_extracted_grain_adds_variation() -> None:
    rng = np.random.default_rng(1)
    source = np.clip(0.5 + rng.normal(0.0, 0.05, (16, 16, 3)), 0.0, 1.0).astype(np.float32)
    flat = np.full((16, 16, 3), 0.5, dtype=np.float32)

    out = _apply_extracted_grain(flat, source, {"strength": 1.0, "radius": 1})

    assert out.std() > flat.std()


def test_extracted_grain_none_is_noop() -> None:
    rgb = _sample_rgb()
    assert np.allclose(_apply_extracted_grain(rgb, rgb, None), rgb)


# --- Integration: monochrome stays gray with base effects ---------------------


def test_monochrome_with_base_effects_stays_gray() -> None:
    rgb = _sample_rgb()
    preset = get_preset("ilford_hp5_plus")
    base = load_base()

    result = apply_film_preset(rgb, preset.data, base)

    assert np.allclose(result[:, :, 0], result[:, :, 1])
    assert np.allclose(result[:, :, 1], result[:, :, 2])


def test_reciprocity_compensation_lifts_shadows_for_long_exposure() -> None:
    image = np.linspace(0.0, 1.0, 16 * 16 * 3, dtype=np.float32).reshape(16, 16, 3) * 0.4
    config = {"assumed_exposure_s": 2.0, "correction_exponent": 1.31, "toe_lift": 0.02}
    out = _apply_reciprocity_compensation(image, config)
    assert float(out.mean()) > float(image.mean())


def test_acutance_increases_local_contrast() -> None:
    image = np.zeros((32, 32, 3), dtype=np.float32)
    image[8:24, 8:24] = 0.8
    config = {"amount": 0.2, "radius": 1.2}
    out = _apply_acutance(image, config)
    assert not np.allclose(out, image)


def test_invalid_rgb_curves_are_skipped() -> None:
    image = _sample_rgb()
    bad = {
        "r": [[0, 200], [128, 50], [255, 255]],
        "g": [[0, 0], [255, 255]],
        "b": [[0, 0], [255, 255]],
    }
    out = _apply_per_channel_curves(image, bad)
    assert np.allclose(out, image)
