"""Tests for camera style loading and grading application."""

from __future__ import annotations

import numpy as np

from film_stockpot.image.grading import (
    apply_grading_after_scanner,
    camera_style_scanner_overrides,
    camera_style_to_grading,
    has_grading_adjustments,
    normalize_grading,
)
from film_stockpot.styles.loader import (
    CameraStyle,
    find_camera_styles_dir,
    get_camera_style,
    load_camera_styles,
)


def test_camera_styles_directory_exists() -> None:
    assert find_camera_styles_dir().is_dir()


def test_load_camera_styles_returns_catalog() -> None:
    styles = load_camera_styles()
    assert len(styles) == 166
    assert all(isinstance(style, CameraStyle) for style in styles)
    assert all(style.id for style in styles)
    ids = [style.id for style in styles]
    assert len(ids) == len(set(ids))


def test_get_camera_style_by_id() -> None:
    style = get_camera_style("Agfa Optima::01")
    assert style.name == "Agfa Optima"
    assert style.slot == "01"
    assert style.curve_points


def test_camera_style_to_grading_scales_points() -> None:
    style = get_camera_style("Agfa Optima::01")
    grading = camera_style_to_grading(style)
    points = grading["curves"]["L"]
    assert points[0][0] == 0.0
    assert points[-1][0] == 1.0
    assert all(0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 for x, y in points)
    assert grading["style_id"] == style.id
    assert grading["monochrome"] is False
    assert has_grading_adjustments(grading)


def test_camera_style_scanner_overrides() -> None:
    style = get_camera_style("Agfa Optima::01")
    overrides = camera_style_scanner_overrides(style)
    assert "saturation" in overrides
    assert "sharpness" in overrides
    assert -8 <= overrides["saturation"] <= 8
    assert 0 <= overrides["sharpness"] <= 10


def test_monochrome_style_sets_flag() -> None:
    styles = [style for style in load_camera_styles() if style.base_style == "Monochrome"]
    assert styles
    grading = camera_style_to_grading(styles[0])
    assert grading["monochrome"] is True


def test_apply_grading_monochrome_makes_channels_equal() -> None:
    rgb = np.zeros((8, 8, 3), dtype=np.float32)
    rgb[..., 0] = 0.8
    rgb[..., 1] = 0.4
    rgb[..., 2] = 0.1
    grading = normalize_grading({"monochrome": True})
    out = apply_grading_after_scanner(rgb, {"grading": grading})
    assert np.allclose(out[..., 0], out[..., 1])
    assert np.allclose(out[..., 1], out[..., 2])


def test_apply_grading_curve_only_without_monochrome() -> None:
    rgb = np.full((4, 4, 3), 0.5, dtype=np.float32)
    grading = camera_style_to_grading(get_camera_style("Agfa Optima::01"))
    grading["monochrome"] = False
    out = apply_grading_after_scanner(rgb, {"grading": grading})
    assert out.shape == rgb.shape
    assert not np.allclose(out, rgb)
