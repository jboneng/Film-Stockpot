"""Interactive L/R/G/B curve editor for the grading panel."""

from __future__ import annotations

import copy

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.image.curves import (
    CURVES_NEUTRAL,
    evaluate_curve,
    normalize_curve_points,
    normalize_curves,
)

_CHANNELS = ("L", "R", "G", "B")
_CHANNEL_COLORS = {
    "L": QColor(220, 220, 228),
    "R": QColor(255, 80, 80),
    "G": QColor(80, 220, 120),
    "B": QColor(90, 150, 255),
}
_MARGIN = 24
_HIT_RADIUS = 8.0
_MIN_POINTS = 3

_TOGGLE_STYLE = """
QToolButton {
    background: #3a3a3e;
    color: #b8b8be;
    border: 1px solid #4a4a50;
    padding: 2px 10px;
    font-size: 11px;
}
QToolButton:checked {
    background: #0a84d8;
    color: #ffffff;
    border-color: #2d8fd8;
}
QToolButton#curveToggleLeft {
    border-top-left-radius: 4px;
    border-bottom-left-radius: 4px;
    border-right: none;
}
QToolButton#curveToggleRight {
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}
"""


class _CurveCanvas(QWidget):
    """Editable curve plot for one channel."""

    changed = pyqtSignal()
    interaction_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._channel = "L"
        self._points: list[list[float]] = [point[:] for point in CURVES_NEUTRAL["L"]]
        self._drag_index: int | None = None
        self._hover_index: int | None = None
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def set_channel(self, channel: str) -> None:
        self._channel = channel if channel in _CHANNEL_COLORS else "L"
        self.update()

    def set_points(self, points: list[list[float]]) -> None:
        self._points = normalize_curve_points(points)
        self._drag_index = None
        self._hover_index = None
        self.update()

    def points(self) -> list[list[float]]:
        return copy.deepcopy(self._points)

    def _plot_rect(self):
        return (
            _MARGIN,
            _MARGIN,
            max(1, self.width() - 2 * _MARGIN),
            max(1, self.height() - 2 * _MARGIN),
        )

    def _to_widget(self, x: float, y: float) -> QPointF:
        left, top, width, height = self._plot_rect()
        return QPointF(left + x * width, top + (1.0 - y) * height)

    def _from_widget(self, pos: QPointF) -> tuple[float, float]:
        left, top, width, height = self._plot_rect()
        x = (pos.x() - left) / width
        y = 1.0 - (pos.y() - top) / height
        return float(max(0.0, min(1.0, x))), float(max(0.0, min(1.0, y)))

    def _point_index_at(self, pos: QPointF) -> int | None:
        best_index: int | None = None
        best_dist = _HIT_RADIUS**2
        for index, (x, y) in enumerate(self._points):
            handle = self._to_widget(x, y)
            dx = pos.x() - handle.x()
            dy = pos.y() - handle.y()
            dist = dx * dx + dy * dy
            if dist <= best_dist:
                best_dist = dist
                best_index = index
        return best_index

    def _insert_point(self, x: float, y: float) -> None:
        x = float(max(0.0, min(1.0, x)))
        y = float(max(0.0, min(1.0, y)))
        for existing_x, _ in self._points:
            if abs(existing_x - x) < 0.02:
                return
        self._points.append([x, y])
        self._points = normalize_curve_points(self._points)
        self.changed.emit()

    def _delete_point(self, index: int) -> None:
        if index <= 0 or index >= len(self._points) - 1:
            return
        if len(self._points) <= _MIN_POINTS:
            return
        del self._points[index]
        self._points = normalize_curve_points(self._points)
        self.changed.emit()

    def _move_point(self, index: int, x: float, y: float) -> None:
        if index == 0:
            self._points[0] = [0.0, float(max(0.0, min(1.0, y)))]
        elif index == len(self._points) - 1:
            self._points[-1] = [1.0, float(max(0.0, min(1.0, y)))]
        else:
            prev_x = self._points[index - 1][0]
            next_x = self._points[index + 1][0]
            x = float(max(prev_x + 0.01, min(next_x - 0.01, x)))
            y = float(max(0.0, min(1.0, y)))
            self._points[index] = [x, y]
        self._points = normalize_curve_points(self._points)
        self.changed.emit()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        left, top, width, height = self._plot_rect()
        rect_color = QColor(24, 24, 27)
        border_color = QColor(58, 58, 64)
        grid_color = QColor(52, 52, 58)
        guide_color = QColor(90, 90, 98)
        curve_color = _CHANNEL_COLORS[self._channel]

        painter.fillRect(self.rect(), rect_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawRect(left, top, width, height)

        for step in (0.25, 0.5, 0.75):
            gx = left + step * width
            gy = top + step * height
            painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DotLine))
            painter.drawLine(int(gx), top, int(gx), top + height)
            painter.drawLine(left, int(gy), left + width, int(gy))

        guide_start = self._to_widget(0.0, 0.0)
        guide_end = self._to_widget(1.0, 1.0)
        painter.setPen(QPen(guide_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(guide_start, guide_end)

        path = QPainterPath()
        samples = 128
        for sample in range(samples + 1):
            x = sample / samples
            y = evaluate_curve(self._points, x)
            point = self._to_widget(x, y)
            if sample == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        painter.setPen(QPen(curve_color, 2.0))
        painter.drawPath(path)

        for index, (x, y) in enumerate(self._points):
            center = self._to_widget(x, y)
            radius = 5.0 if index in (self._drag_index, self._hover_index) else 4.0
            painter.setPen(QPen(QColor(20, 20, 22), 1.5))
            painter.setBrush(QColor(240, 240, 240))
            painter.drawEllipse(center, radius, radius)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if event.button() == Qt.MouseButton.RightButton:
            index = self._point_index_at(pos)
            if index is not None:
                self._delete_point(index)
            event.accept()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        index = self._point_index_at(pos)
        if index is not None:
            self._drag_index = index
            self.interaction_changed.emit(True)
            event.accept()
            return

        left, top, width, height = self._plot_rect()
        if not (left <= pos.x() <= left + width and top <= pos.y() <= top + height):
            return

        x, y = self._from_widget(pos)
        curve_y = evaluate_curve(self._points, x)
        self._insert_point(x, curve_y)
        self._drag_index = self._point_index_at(self._to_widget(x, curve_y))
        self.interaction_changed.emit(True)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag_index is not None:
            x, y = self._from_widget(pos)
            self._move_point(self._drag_index, x, y)
            event.accept()
            return

        self._hover_index = self._point_index_at(pos)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_index is not None:
            self._drag_index = None
            self.interaction_changed.emit(False)
            event.accept()


class CurveEditorWidget(QWidget):
    """L/R/G/B curve controls with shared editing canvas."""

    changed = pyqtSignal()
    interaction_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._curves = normalize_curves(CURVES_NEUTRAL)
        self._channel = "L"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Curves", self)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch(1)

        self._buttons: dict[str, QToolButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(0)
        for index, channel in enumerate(_CHANNELS):
            button = QToolButton(self)
            button.setText(channel)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            if index == 0:
                button.setObjectName("curveToggleLeft")
            elif index == len(_CHANNELS) - 1:
                button.setObjectName("curveToggleRight")
            button.toggled.connect(lambda checked, ch=channel: self._on_channel_toggled(ch, checked))
            group.addButton(button)
            self._buttons[channel] = button
            toggle_row.addWidget(button)
        header.addLayout(toggle_row)
        layout.addLayout(header)

        self._canvas = _CurveCanvas(self)
        self._canvas.changed.connect(self._on_canvas_changed)
        self._canvas.interaction_changed.connect(self.interaction_changed.emit)
        layout.addWidget(self._canvas)

        hint = QLabel("Click the curve to add a point. Right-click a point to remove it.", self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9a9aa0; font-size: 11px;")
        layout.addWidget(hint)

        self.setStyleSheet(_TOGGLE_STYLE)
        self._buttons["L"].setChecked(True)
        self._canvas.set_channel("L")
        self._canvas.set_points(self._curves["L"])

    def _on_channel_toggled(self, channel: str, checked: bool) -> None:
        if not checked:
            return
        self._curves[self._channel] = self._canvas.points()
        self._channel = channel
        self._canvas.set_channel(channel)
        self._canvas.set_points(self._curves[channel])

    def _on_canvas_changed(self) -> None:
        self._curves[self._channel] = self._canvas.points()
        self.changed.emit()

    def curves(self) -> dict[str, list[list[float]]]:
        self._curves[self._channel] = self._canvas.points()
        return normalize_curves(self._curves)

    def set_curves(self, curves: dict | None) -> None:
        self._curves = normalize_curves(curves)
        self._canvas.set_points(self._curves[self._channel])

    def reset(self) -> None:
        self.set_curves(CURVES_NEUTRAL)
