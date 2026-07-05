"""Hue/saturation color wheel widget for tonal grading."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class ColorWheelWidget(QWidget):
    """Circular hue/saturation picker with a white neutral center."""

    value_changed = pyqtSignal()
    dragging_changed = pyqtSignal(bool)

    _DEAD_ZONE_RADIUS = 3.0
    _RENDER_SCALE = 3

    def __init__(self, diameter: int = 112, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._hue = 0.0
        self._sat = 0.0
        self._dragging = False
        self._wheel_cache: QImage | None = None
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

    def _center(self) -> QPointF:
        return QPointF(self.width() / 2.0, self.height() / 2.0)

    @staticmethod
    def _position_to_hue(dx: float, dy: float) -> float:
        """Clockwise hue in degrees from the wheel center (0 = red at top)."""
        return (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0

    @staticmethod
    def _distance_to_saturation(dist: float, outer: float) -> float:
        """Map radial distance to saturation with a quadratic curve."""
        if outer <= 0.0:
            return 0.0
        ratio = min(1.0, dist / outer)
        return ratio * ratio

    @staticmethod
    def _saturation_to_distance(sat: float, outer: float) -> float:
        """Inverse of ``_distance_to_saturation`` for handle placement."""
        clamped = max(0.0, min(1.0, sat))
        return outer * math.sqrt(clamped)

    @staticmethod
    def _edge_coverage(dist: float, outer: float) -> float:
        """Anti-alias weight for the outer circular boundary."""
        return min(1.0, max(0.0, outer + 0.5 - dist))

    def _pos_to_values(self, pos: QPointF) -> tuple[float, float]:
        center = self._center()
        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        dist = math.hypot(dx, dy)
        if dist <= self._DEAD_ZONE_RADIUS:
            return 0.0, 0.0

        outer = self._outer_radius()
        if dist > outer:
            scale = outer / dist
            dx *= scale
            dy *= scale
            dist = outer

        return self._position_to_hue(dx, dy), self._distance_to_saturation(dist, outer)

    def _handle_position(self) -> QPointF:
        center = self._center()
        if self._sat <= 0.0:
            return center
        dist = self._saturation_to_distance(self._sat, self._outer_radius())
        angle = math.radians(self._hue - 90.0)
        return QPointF(center.x() + dist * math.cos(angle), center.y() + dist * math.sin(angle))

    def _picked_color(self) -> QColor:
        if self._sat <= 0.0:
            return QColor(255, 255, 255)
        return QColor.fromHsvF(self._hue / 360.0, self._sat, 1.0)

    def _build_wheel_image(self) -> QImage:
        scale = self._RENDER_SCALE
        size = self._diameter * scale
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)

        center = size / 2.0
        outer = self._outer_radius() * scale

        for y in range(size):
            for x in range(size):
                dx = x + 0.5 - center
                dy = y + 0.5 - center
                dist = math.hypot(dx, dy)
                coverage = self._edge_coverage(dist, outer)
                if coverage <= 0.0:
                    continue

                hue = self._position_to_hue(dx, dy)
                sat = self._distance_to_saturation(dist, outer)
                color = QColor.fromHsvF(hue / 360.0, sat, 1.0)
                alpha = int(round(coverage * 255.0))
                color.setAlpha(alpha)
                image.setPixelColor(x, y, color)

        return image

    def _wheel_image(self) -> QImage:
        if self._wheel_cache is None:
            self._wheel_cache = self._build_wheel_image()
        return self._wheel_cache

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self._wheel_image())

        handle = self._handle_position()
        painter.setPen(QPen(QColor(20, 20, 22), 1.5))
        painter.setBrush(self._picked_color())
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
