"""Tests for the cached preview engine."""

import numpy as np

from film_stockpot.image.grading import GRADING_NEUTRAL
from film_stockpot.ui.preview_engine import PreviewEngine, downscale_for_preview


def test_downscale_for_preview_keeps_small_images() -> None:
    rgb = np.zeros((800, 600, 3), dtype=np.float32)
    result = downscale_for_preview(rgb, 1800)
    assert result.shape == rgb.shape


def test_downscale_for_preview_reduces_large_images() -> None:
    rgb = np.zeros((4000, 3000, 3), dtype=np.float32)
    result = downscale_for_preview(rgb, 1800)
    assert max(result.shape[:2]) <= 1800


def test_preview_engine_cache_hit_after_render() -> None:
    engine = PreviewEngine(preview_max=512, drag_preview_max=256)
    film = np.full((64, 64, 3), 0.5, dtype=np.float32)
    engine.set_film_base(film, None)
    settings = {
        "grading": {
            **GRADING_NEUTRAL,
            "shadows": {"hue": 0.0, "sat": 0.5, "lum": 0},
        }
    }

    assert engine.cache_hit(settings) is False
    first = engine.render_full(settings)
    assert first is not None
    assert engine.cache_hit(settings) is True
    second = engine.render_full(settings)
    assert second is first


def test_scanner_cached_tracks_grading_only_changes() -> None:
    engine = PreviewEngine(preview_max=256, drag_preview_max=128)
    film = np.full((32, 32, 3), 0.5, dtype=np.float32)
    engine.set_film_base(film, None)

    settings = {
        "density": 4,
        "grading": {**GRADING_NEUTRAL, "shadows": {"hue": 0.0, "sat": 0.5, "lum": 0}},
    }
    assert engine.scanner_cached(settings) is False
    engine.render_full(settings)
    assert engine.scanner_cached(settings) is True

    # Changing only grading keeps the scanner stage cached (so it is reused).
    grading_only = {
        "density": 4,
        "grading": {**GRADING_NEUTRAL, "shadows": {"hue": 120.0, "sat": 0.8, "lum": 10}},
    }
    assert engine.scanner_cached(grading_only) is True

    # Changing a scanner control invalidates the scanner stage.
    scanner_changed = {**grading_only, "density": 5}
    assert engine.scanner_cached(scanner_changed) is False


def test_store_scanner_result_enables_grading_reuse() -> None:
    engine = PreviewEngine(preview_max=256, drag_preview_max=128)
    film = np.full((16, 16, 3), 0.4, dtype=np.float32)
    engine.set_film_base(film, None)

    settings = {"grading": {**GRADING_NEUTRAL, "midtones": {"hue": 40.0, "sat": 0.6, "lum": 0}}}
    scanner_result = engine.effective_film_base()
    assert scanner_result is not None

    engine.store_scanner_result(settings, scanner_result)
    assert engine.scanner_cached(settings) is True
    assert engine.scanner_result() is scanner_result

    full = engine.render_full(settings)
    assert full is not None
    assert engine.last_timings.scanner_ms == 0.0


def test_neutral_grading_skips_grading_stage() -> None:
    engine = PreviewEngine(preview_max=256, drag_preview_max=128)
    film = np.full((16, 16, 3), 0.5, dtype=np.float32)
    engine.set_film_base(film, None)

    full = engine.render_full({"grading": GRADING_NEUTRAL})
    assert full is not None
    assert engine.last_timings.grading_ms == 0.0


def test_preview_engine_drag_proxy_is_smaller() -> None:
    engine = PreviewEngine(preview_max=800, drag_preview_max=200)
    film = np.zeros((800, 800, 3), dtype=np.float32)
    engine.set_film_base(film, None)
    full_base = engine.effective_film_base(preview_fast=False)
    drag_base = engine.effective_film_base(preview_fast=True)
    assert full_base is not None and drag_base is not None
    assert max(drag_base.shape[:2]) <= 200
    assert max(full_base.shape[:2]) <= 800
