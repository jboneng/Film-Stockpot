"""Load bundled SVG icons for the UI."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"
_DEFAULT_COLOR = QColor(220, 220, 220)


def icon_path(name: str) -> Path:
    """Return the path to a bundled icon file."""
    return _ICONS_DIR / name


def load_pixmap(name: str, size: int, *, color: QColor | None = _DEFAULT_COLOR) -> QPixmap:
    """Render an SVG icon to a pixmap at ``size`` × ``size`` pixels."""
    path = icon_path(name)
    svg_data = path.read_text(encoding="utf-8")
    if color is not None:
        svg_data = svg_data.replace("currentColor", color.name())

    renderer = QSvgRenderer(svg_data.encode("utf-8"))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def load_icon(name: str, size: int = 24, *, color: QColor | None = _DEFAULT_COLOR) -> QIcon:
    """Return a :class:`QIcon` rendered from a bundled SVG."""
    return QIcon(load_pixmap(name, size, color=color))
