"""Tests for color-wheel hue and saturation mapping."""

import math

from PyQt6.QtCore import QPointF

from film_stockpot.ui.widgets.color_wheel import ColorWheelWidget


def test_position_to_hue_places_red_at_top() -> None:
    assert ColorWheelWidget._position_to_hue(0.0, -1.0) == 0.0


def test_position_to_hue_places_green_at_lower_right() -> None:
    hue = ColorWheelWidget._position_to_hue(1.0, 1.0)
    assert 100.0 <= hue <= 140.0


def test_distance_to_saturation_is_quadratic() -> None:
    assert ColorWheelWidget._distance_to_saturation(0.0, 50.0) == 0.0
    assert math.isclose(ColorWheelWidget._distance_to_saturation(25.0, 50.0), 0.25)
    assert math.isclose(ColorWheelWidget._distance_to_saturation(50.0, 50.0), 1.0)


def test_saturation_to_distance_inverts_quadratic() -> None:
    outer = 50.0
    for sat in (0.0, 0.04, 0.25, 0.64, 1.0):
        dist = ColorWheelWidget._saturation_to_distance(sat, outer)
        assert math.isclose(ColorWheelWidget._distance_to_saturation(dist, outer), sat)


def test_edge_coverage_antialiases_outer_boundary() -> None:
    assert ColorWheelWidget._edge_coverage(50.0, 50.0) == 0.5
    assert math.isclose(ColorWheelWidget._edge_coverage(50.4, 50.0), 0.1)
    assert ColorWheelWidget._edge_coverage(50.6, 50.0) == 0.0
    assert ColorWheelWidget._edge_coverage(49.0, 50.0) == 1.0


def test_pos_to_values_resets_in_dead_zone(qapp) -> None:
    wheel = ColorWheelWidget()
    center = wheel._center()
    hue, sat = wheel._pos_to_values(center)
    assert hue == 0.0
    assert sat == 0.0


def test_pos_to_values_reaches_full_saturation_at_edge(qapp) -> None:
    wheel = ColorWheelWidget()
    center = wheel._center()
    outer = wheel._outer_radius()
    hue, sat = wheel._pos_to_values(center + QPointF(0.0, -outer))
    assert math.isclose(sat, 1.0)
    assert math.isclose(hue, 0.0, abs_tol=0.5)
