"""Hue/saturation color wheel widget for tonal grading."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QConicalGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class ColorWheelWidget(QWidget):
    """Circular hue/saturation picker with a neutral center."""

    value_changed = pyqtSignal()
    dragging_changed = pyqtSignal(bool)

    def __init__(self, diameter: int = 112, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._hue = 0.0
        self._sat = 0.0
        self._dragging = False
        self.setFixedSize(diameter, diameter)
        self.setMouseTracking(True)

    def hue(self) -> float:
        return self._hue

    def saturation(self) -> float:
        return self._sat

    def set_values(self, hue: float, sat: float) -> None:
        self._hue = float(hue) % 360.0
        self._sat = max(0.0, min(1.0, float(sat)))
        self.update()

    def values(self) -> tuple[float, float]:
        return self._hue, self._sat

    def _outer_radius(self) -> float:
        return self._diameter / 2.0 - 6.0

    def _inner_radius(self) -> float:
        return self._outer_radius() * 0.28

    def _center(self) -> QPointF:
        return QPointF(self.width() / 2.0, self.height() / 2.0)

    @staticmethod
    def _position_to_hue(dx: float, dy: float) -> float:
        """Clockwise hue in degrees from the wheel center (0 = red at top)."""
        return (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0

    @staticmethod
    def _gradient_stop_hue(clockwise_angle_from_top: float) -> float:
        """Hue fed to ``QConicalGradient`` so the painted color matches ``_position_to_hue``.

        Qt's conical gradient applies a +90 degree offset between stop angle and
        displayed hue. Without this compensation red appears at the right and
        green at the top while the picker still stores red-at-top, which makes
        wheel picks look inverted (red <-> green) in the preview.
        """
        return (90.0 - clockwise_angle_from_top) % 360.0

    def _pos_to_values(self, pos: QPointF) -> tuple[float, float]:
        center = self._center()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        dist = math.hypot(dx, dy)
        inner = self._inner_radius()
        outer = self._outer_radius()
        if dist <= inner:
            return 0.0, 0.0
        sat = min(1.0, (dist - inner) / max(outer - inner, 1.0))
        return self._position_to_hue(dx, dy), sat

    def _handle_position(self) -> QPointF:
        center = self._center()
        if self._sat <= 0.0:
            return center
        inner = self._inner_radius()
        outer = self._outer_radius()
        dist = inner + self._sat * (outer - inner)
        angle = math.radians(self._hue - 90.0)
        return QPointF(center.x() + dist * math.cos(angle), center.y() + dist * math.sin(angle))

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = self._center()
        outer = self._outer_radius()
        inner = self._inner_radius()

        gradient = QConicalGradient(center, 0.0)
        for step in range(13):
            stop_pos = step / 12.0
            stop_angle = stop_pos * 360.0
            hue = self._gradient_stop_hue(stop_angle)
            gradient.setColorAt(stop_pos, QColor.fromHsvF(hue / 360.0, 1.0, 1.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(center, outer, outer)

        painter.setBrush(QColor(48, 48, 52))
        painter.drawEllipse(center, inner, inner)

        handle = self._handle_position()
        painter.setPen(QPen(QColor(20, 20, 22), 1.5))
        painter.setBrush(QColor(240, 240, 240))
        painter.drawEllipse(handle, 5.5, 5.5)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.dragging_changed.emit(True)
            self._apply_position(event.position())
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging:
            self._apply_position(event.position())
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.dragging_changed.emit(False)
            self._apply_position(event.position())
            event.accept()

    def _apply_position(self, pos: QPointF) -> None:
        hue, sat = self._pos_to_values(pos)
        if math.isclose(hue, self._hue, abs_tol=0.5) and math.isclose(sat, self._sat, abs_tol=0.001):
            return
        self._hue = hue
        self._sat = sat
        self.update()
        self.value_changed.emit()
