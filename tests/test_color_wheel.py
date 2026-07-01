"""Tests for color-wheel hue mapping."""

import math

from film_stockpot.ui.widgets.color_wheel import ColorWheelWidget


def test_position_to_hue_places_red_at_top() -> None:
    assert ColorWheelWidget._position_to_hue(0.0, -1.0) == 0.0


def test_position_to_hue_places_green_at_lower_right() -> None:
    hue = ColorWheelWidget._position_to_hue(1.0, 1.0)
    assert 100.0 <= hue <= 140.0


def test_gradient_stop_hue_compensates_qt_offset() -> None:
    # At the top of the wheel the picker reads red (0°) so the gradient stop
    # there must use the Qt-compensated hue, not 0.
    assert ColorWheelWidget._gradient_stop_hue(0.0) == 90.0
    assert ColorWheelWidget._gradient_stop_hue(90.0) == 0.0


def test_gradient_stop_matches_picker_at_cardinal_angles() -> None:
    for angle in (0.0, 90.0, 180.0, 270.0):
        rad = math.radians(angle)
        dx = math.sin(rad)
        dy = -math.cos(rad)
        picker_hue = ColorWheelWidget._position_to_hue(dx, dy)
        stop_hue = ColorWheelWidget._gradient_stop_hue(angle)
        assert math.isclose((90.0 - stop_hue) % 360.0, picker_hue, abs_tol=1e-6)
