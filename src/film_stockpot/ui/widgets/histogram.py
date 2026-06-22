"""RGB histogram with a linear / logarithmic display toggle.

The widget renders the per-channel distribution of the currently previewed image.
Histograms are computed from the same float32 RGB preview that drives the viewer,
so the curve always matches what is on screen.
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_BINS = 256

_TOGGLE_STYLE = """
QToolButton {
    background: #3a3a3e;
    color: #b8b8be;
    border: 1px solid #4a4a50;
    padding: 2px 12px;
    font-size: 11px;
}
QToolButton:checked {
    background: #0a84d8;
    color: #ffffff;
    border-color: #2d8fd8;
}
QToolButton#histToggleLeft {
    border-top-left-radius: 4px;
    border-bottom-left-radius: 4px;
    border-right: none;
}
QToolButton#histToggleRight {
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}
"""


class _HistogramCanvas(QWidget):
    """Paints precomputed per-channel histograms with additive blending."""

    _BG = QColor(24, 24, 27)
    _BORDER = QColor(58, 58, 64)
    _GRID = QColor(52, 52, 58)
    _CHANNEL_COLORS = (
        QColor(255, 80, 80),
        QColor(80, 220, 120),
        QColor(90, 150, 255),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hist: np.ndarray | None = None
        self._log = False
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_histograms(self, hist: np.ndarray | None) -> None:
        self._hist = hist
        self.update()

    def set_log(self, log: bool) -> None:
        if log != self._log:
            self._log = log
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        painter.fillRect(rect, self._BG)
        self._draw_grid(painter, rect)

        if self._hist is not None:
            self._draw_histogram(painter, rect)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setPen(QPen(self._BORDER, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.end()

    def _draw_grid(self, painter: QPainter, rect) -> None:
        painter.setPen(QPen(self._GRID, 1, Qt.PenStyle.DotLine))
        for fraction in (0.25, 0.5, 0.75):
            x = int(rect.width() * fraction)
            painter.drawLine(x, rect.top(), x, rect.bottom())

    def _draw_histogram(self, painter: QPainter, rect) -> None:
        data = self._hist.astype(np.float64)
        if self._log:
            data = np.log1p(data)
        peak = float(data.max())
        if peak <= 0.0:
            return
        data = data / peak

        width = rect.width()
        height = rect.height()
        bins = data.shape[1]

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setPen(Qt.PenStyle.NoPen)

        for channel in range(data.shape[0]):
            color = QColor(self._CHANNEL_COLORS[channel])
            color.setAlpha(150)
            path = QPainterPath()
            path.moveTo(0.0, float(height))
            for i in range(bins):
                x = width * i / (bins - 1)
                y = height - data[channel, i] * height
                path.lineTo(float(x), float(y))
            path.lineTo(float(width), float(height))
            path.closeSubpath()
            painter.fillPath(path, color)


class HistogramWidget(QWidget):
    """RGB histogram panel with a linear/logarithmic toggle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Histogram", self)
        title_font = title.font()
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch(1)

        self._lin_button = self._make_toggle_button("Lin", "histToggleLeft")
        self._log_button = self._make_toggle_button("Log", "histToggleRight")
        self._lin_button.setChecked(True)
        self._lin_button.setToolTip("Linear histogram")
        self._log_button.setToolTip("Logarithmic histogram")

        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self._lin_button)
        group.addButton(self._log_button)
        self._log_button.toggled.connect(self._canvas_set_log)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(0)
        toggle_row.addWidget(self._lin_button)
        toggle_row.addWidget(self._log_button)
        header.addLayout(toggle_row)

        layout.addLayout(header)

        self._canvas = _HistogramCanvas(self)
        layout.addWidget(self._canvas)

        self.setStyleSheet(_TOGGLE_STYLE)

    def _make_toggle_button(self, text: str, object_name: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(object_name)
        button.setText(text)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _canvas_set_log(self, checked: bool) -> None:
        self._canvas.set_log(checked)

    def set_image(self, rgb: np.ndarray | None) -> None:
        """Compute and display histograms for a float32 RGB image (0..1)."""
        if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3:
            self._canvas.set_histograms(None)
            return

        data = np.clip(rgb, 0.0, 1.0)
        hist = np.empty((3, _BINS), dtype=np.float64)
        for channel in range(3):
            counts, _ = np.histogram(data[:, :, channel], bins=_BINS, range=(0.0, 1.0))
            hist[channel] = counts
        self._canvas.set_histograms(hist)

    def clear(self) -> None:
        self._canvas.set_histograms(None)
