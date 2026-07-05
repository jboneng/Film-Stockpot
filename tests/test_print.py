"""Tests for NegPy-style print emulation."""

import numpy as np

from film_stockpot.image.print.logic import grade_to_slope, paper_dmin_rgb
from film_stockpot.image.print.papers import (
    PAPER_PROFILES,
    default_paper_profile,
    effective_paper_profile,
    process_mode_for_preset,
    profiles_for_mode,
    resolve_paper,
)
from film_stockpot.image.print.stage import PRINT_NEUTRAL, apply_print_stage, normalize_print_settings, print_enabled


def test_print_disabled_is_identity() -> None:
    rgb = np.linspace(0.1, 0.9, 12, dtype=np.float32).reshape(2, 2, 3)
    out = apply_print_stage(rgb, {"print": {"enabled": False}})
    np.testing.assert_allclose(out, rgb)


def test_print_enabled_changes_image() -> None:
    rgb = np.linspace(0.15, 0.85, 12, dtype=np.float32).reshape(2, 2, 3)
    settings = {
        "print": {
            **PRINT_NEUTRAL,
            "enabled": True,
            "paper_profile": "kodak_endura",
        }
    }
    out = apply_print_stage(rgb, settings, {"monochrome": False})
    assert out.shape == rgb.shape
    assert not np.allclose(out, rgb)


def test_default_paper_profile_by_stock_type() -> None:
    assert default_paper_profile({"monochrome": False}) == "kodak_endura"
    assert default_paper_profile({"monochrome": True}) == "ilford_mg_rc"


def test_profiles_for_mode_filters_stock_types() -> None:
    color_keys = {key for key, _ in profiles_for_mode("c41")}
    bw_keys = {key for key, _ in profiles_for_mode("bw")}
    assert "kodak_endura" in color_keys
    assert "ilford_mg_rc" in bw_keys
    assert "kodak_endura" not in bw_keys


def test_effective_paper_profile_rejects_cross_mode() -> None:
    paper = effective_paper_profile("kodak_endura", "bw")
    assert paper.kind == "default"


def test_normalize_print_settings_defaults_off() -> None:
    merged = normalize_print_settings(None, {"monochrome": False})
    assert merged["enabled"] is False
    assert merged["paper_profile"] == "kodak_endura"


def test_print_enabled_reads_nested_block() -> None:
    assert print_enabled({"print": {"enabled": True}}) is True
    assert print_enabled({}) is False


def test_grade_to_slope_clamps_iso_r() -> None:
    soft = grade_to_slope(180.0, 1.0)
    hard = grade_to_slope(50.0, 1.0)
    assert hard > soft


def test_endura_dye_matrix_is_row_normalized() -> None:
    paper = resolve_paper("kodak_endura")
    rows = np.array(paper.dye_matrix, dtype=np.float64)
    sums = rows.sum(axis=1)
    np.testing.assert_allclose(sums, np.ones(3), rtol=0, atol=1e-6)


def test_paper_dmin_rgb_includes_tint() -> None:
    paper = resolve_paper("fuji_crystal")
    rgb = paper_dmin_rgb(0.06, paper)
    assert rgb[1] < 0.06
    assert rgb[2] < 0.06


def test_print_bridge_avoids_black_crush_on_flat_scan() -> None:
    rng = np.random.default_rng(0)
    flat = np.clip(rng.normal(0.45, 0.12, (128, 192, 3)), 0.05, 0.95).astype(np.float32)
    settings = {
        "print": {
            **PRINT_NEUTRAL,
            "enabled": True,
            "paper_profile": "kodak_endura",
        }
    }
    out = apply_print_stage(flat, settings, None, flat_scan=flat)
    assert out.mean() > 0.05
    assert (out < 0.01).mean() < 0.25
    corr = float(np.corrcoef(flat[:, :, 0].ravel(), out[:, :, 0].ravel())[0, 1])
    assert corr > 0.5


def test_print_keeps_positive_polarity_on_flat_scan() -> None:
    x = np.linspace(0.0, 1.0, 192, dtype=np.float32)
    grad = np.stack([np.tile(x, (128, 1))] * 3, axis=-1)
    settings = {
        "print": {
            **PRINT_NEUTRAL,
            "enabled": True,
            "paper_profile": "fuji_crystal",
        }
    }
    out = apply_print_stage(grad, settings, None, flat_scan=grad)
    corr = float(np.corrcoef(grad[:, :, 0].ravel(), out[:, :, 0].ravel())[0, 1])
    assert corr > 0.5


def test_print_lift_matches_flat_scan_median() -> None:
    from film_stockpot.image.print.logic import get_luminance

    rng = np.random.default_rng(2)
    flat = np.clip(rng.normal(0.45, 0.12, (128, 192, 3)), 0.05, 0.95).astype(np.float32)
    settings = {
        "print": {
            **PRINT_NEUTRAL,
            "enabled": True,
            "paper_profile": "kodak_endura",
        }
    }
    out = apply_print_stage(flat, settings, None, flat_scan=flat)
    ref_mid = float(np.percentile(get_luminance(flat), 50.0))
    out_mid = float(np.percentile(get_luminance(out), 50.0))
    assert out_mid >= ref_mid * 0.85


def test_print_display_path_handles_graded_input() -> None:
    import json
    from pathlib import Path

    from film_stockpot.image.pipeline import apply_base_input_transform

    base = json.loads(Path("FilmPresets/_frontier_base.json").read_text())
    rng = np.random.default_rng(1)
    flat = np.clip(rng.normal(0.45, 0.12, (128, 192, 3)), 0.05, 0.95).astype(np.float32)
    graded = apply_base_input_transform(flat, base)
    settings = {
        "print": {
            **PRINT_NEUTRAL,
            "enabled": True,
            "paper_profile": "kodak_endura",
        }
    }
    out = apply_print_stage(graded, settings, {"monochrome": False})
    assert out.mean() > 0.05
    assert (out < 0.01).mean() < 0.25
