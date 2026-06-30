"""Tests for spectral crosstalk correction."""

import numpy as np

from film_stockpot.image.crosstalk import (
    CROSSTALK_DEFAULT,
    _limit_positive_rgb_delta,
    apply_preset_crosstalk,
    apply_spectral_crosstalk,
    crosstalk_amount_to_strength,
    crosstalk_slider_to_amount,
    crosstalk_strength_from_adjustments,
    format_crosstalk_amount,
    normalize_crosstalk_amount,
    preset_has_crosstalk,
)


_MATRIX = [
    [1.1, 0.05, 0.02],
    [0.03, 1.08, 0.04],
    [0.01, 0.06, 1.12],
]


def test_strength_zero_is_identity() -> None:
    rgb = np.array([[[0.2, 0.5, 0.8]]], dtype=np.float32)
    out = apply_spectral_crosstalk(rgb, _MATRIX, strength=0.0)
    np.testing.assert_allclose(out, rgb, rtol=1e-5, atol=1e-6)


def test_amount_scale_mapping() -> None:
    assert crosstalk_amount_to_strength(0.0) == 0.0
    assert crosstalk_amount_to_strength(CROSSTALK_DEFAULT) == 0.5
    assert crosstalk_amount_to_strength(1.0) == 1.0
    assert crosstalk_strength_from_adjustments({"crosstalk": 0.5}) == 0.5
    assert crosstalk_strength_from_adjustments({"crosstalk": 0.0}) == 0.0
    assert crosstalk_strength_from_adjustments(None) == 0.0


def test_slider_ticks_use_zero_to_one_range() -> None:
    assert crosstalk_slider_to_amount(0) == 0.0
    assert crosstalk_slider_to_amount(50) == 0.5
    assert crosstalk_slider_to_amount(100) == 1.0
    assert format_crosstalk_amount(0.0) == "0.00"


def test_legacy_sidecars_are_migrated() -> None:
    assert normalize_crosstalk_amount(100) == 1.0
    assert normalize_crosstalk_amount(50) == 0.5
    assert normalize_crosstalk_amount(1.5) == 0.5
    assert normalize_crosstalk_amount(2.0) == 1.0
    assert crosstalk_strength_from_adjustments({"crosstalk": 100}) == 1.0


def test_preset_has_crosstalk() -> None:
    preset = {"pipeline": {"crosstalk": {"matrix": _MATRIX}}}
    assert preset_has_crosstalk(preset)
    assert not preset_has_crosstalk({"pipeline": {}})


def test_gray_is_approximately_invariant() -> None:
    gray = np.full((8, 8, 3), 0.45, dtype=np.float32)
    out = apply_spectral_crosstalk(gray, _MATRIX, strength=1.0)
    channel_means = out.reshape(-1, 3).mean(axis=0)
    assert channel_means.max() - channel_means.min() < 0.02


def test_preset_json_embeds_crosstalk_matrix() -> None:
    from film_stockpot.presets.loader import get_preset

    preset = get_preset("kodak_portra_400")
    matrix = preset.data["pipeline"]["crosstalk"]["matrix"]
    assert len(matrix) == 3
    assert all(len(row) == 3 for row in matrix)
    assert "source" not in preset.data["pipeline"]["crosstalk"]


def test_apply_preset_crosstalk_without_matrix() -> None:
    rgb = np.full((2, 2, 3), 0.4, dtype=np.float32)
    out = apply_preset_crosstalk(rgb, {"pipeline": {}}, strength=1.0)
    np.testing.assert_array_equal(out, rgb)


_FUJI_C200_MATRIX = [
    [1.0, -0.0459, -0.0272],
    [-0.0482, 1.0, -0.0586],
    [-0.0226, -0.1489, 1.0],
]


def test_gamut_fit_avoids_single_channel_hard_clip() -> None:
    grid = np.linspace(0.55, 0.98, 6, dtype=np.float32)
    samples = np.stack(np.meshgrid(grid, grid, grid, indexing="ij"), axis=-1).reshape(-1, 3)
    for strength in (0.1, 0.5, 1.0):
        for triplet in samples[::25]:
            pixel = triplet.reshape(1, 1, 3).astype(np.float32)
            out = apply_spectral_crosstalk(pixel, _FUJI_C200_MATRIX, strength=strength)
            assert float(out.max()) <= 1.0 + 1e-5
            assert float(out.min()) >= -1e-5


def test_crosstalk_runs_before_film_look_in_pipeline() -> None:
    from film_stockpot.image.pipeline import apply_film_preset
    from film_stockpot.presets.loader import get_preset

    preset = get_preset("fuji_c200").data
    flat = np.array([[[0.72, 0.78, 0.96]]], dtype=np.float32)
    with_crosstalk = apply_film_preset(flat, preset, base=None, crosstalk_strength=0.5)
    without_crosstalk = apply_film_preset(flat, preset, base=None, crosstalk_strength=0.0)
    assert not np.allclose(with_crosstalk, without_crosstalk)


def test_resolve_preset_data_prefers_local_library() -> None:
    from film_stockpot.presets.loader import get_preset, resolve_preset_data

    local = get_preset("fuji_c200").data
    sidecar = dict(local)
    sidecar["pipeline"] = {k: v for k, v in local["pipeline"].items() if k != "crosstalk"}
    resolved = resolve_preset_data(sidecar)
    assert preset_has_crosstalk(resolved)


def test_headroom_limiter_preserves_channel_decreases() -> None:
    reference = np.array([[[0.72, 0.78, 0.96]]], dtype=np.float32)
    corrected = np.array([[[0.75, 0.74, 0.90]]], dtype=np.float32)
    out = _limit_positive_rgb_delta(reference, corrected)
    assert float(out[0, 0, 2]) < float(reference[0, 0, 2])


def test_fast_path_matches_full_pipeline() -> None:
    from film_stockpot.image.pipeline import (
        apply_film_preset,
        apply_film_preset_from_pre_neutralize,
        apply_pre_neutralize_input_transform,
    )
    from film_stockpot.presets.loader import get_preset, load_base

    preset = get_preset("fuji_c200").data
    base = load_base()
    flat = np.random.default_rng(7).random((64, 64, 3), dtype=np.float32) * 0.5 + 0.25
    pre_neutralize = apply_pre_neutralize_input_transform(flat, base)
    for strength in (0.0, 0.5, 1.0):
        full = apply_film_preset(flat, preset, base, crosstalk_strength=strength)
        fast = apply_film_preset_from_pre_neutralize(
            pre_neutralize,
            flat,
            preset,
            base,
            crosstalk_strength=strength,
        )
        np.testing.assert_allclose(fast, full, rtol=0, atol=1e-5)


def test_crosstalk_runs_before_neutralize() -> None:
    from film_stockpot.image.pipeline import (
        _apply_input_transform_post_neutralize,
        _apply_input_transform_pre_neutralize,
    )
    from film_stockpot.presets.loader import get_preset, load_base

    preset = get_preset("fuji_c200").data
    base = load_base()
    flat = np.full((16, 16, 3), [0.72, 0.78, 0.96], dtype=np.float32)
    transform = base.get("input_transform")
    pre = _apply_input_transform_pre_neutralize(flat, transform)
    after_ct = apply_preset_crosstalk(pre, preset, 1.0)
    post = _apply_input_transform_post_neutralize(after_ct, transform)
    after_neut_only = _apply_input_transform_post_neutralize(pre, transform)
    ct_after_neut = apply_preset_crosstalk(after_neut_only, preset, 1.0)
    assert not np.allclose(post, ct_after_neut)


def test_zero_and_full_crosstalk_differ_on_bright_scan() -> None:
    from film_stockpot.image.pipeline import apply_base_input_transform, apply_film_preset
    from film_stockpot.presets.loader import get_preset, load_base

    preset = get_preset("fuji_c200").data
    base = load_base()
    flat = np.full((32, 32, 3), [0.72, 0.78, 0.96], dtype=np.float32)
    if base is not None:
        flat = apply_base_input_transform(flat, base.get("input_transform"))
    out0 = apply_film_preset(flat, preset, base=None, crosstalk_strength=0.0)
    out1 = apply_film_preset(flat, preset, base=None, crosstalk_strength=1.0)
    assert float(np.abs(out1 - out0).mean()) > 0.001
