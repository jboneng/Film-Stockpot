"""Collapsible panel section with a full-width header bar."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

_MAX_WIDGET_HEIGHT = 16777215


class _SectionHeader(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, *, level: str = "primary") -> None:
        super().__init__(parent)
        self.setObjectName("collapsibleHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_PRIMARY_HEADER_STYLE if level == "primary" else _NESTED_HEADER_STYLE)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


_PRIMARY_HEADER_STYLE = """
QFrame#collapsibleHeader {
    background: #2d2d30;
    border: none;
    border-top: 1px solid #3a3a3e;
    border-bottom: 1px solid #3a3a3e;
    min-height: 32px;
    max-height: 32px;
}
QFrame#collapsibleHeader:hover {
    background: #333337;
}
QLabel#collapsibleTitle {
    color: #e8e8ea;
    font-weight: 600;
    font-size: 12px;
    background: transparent;
    border: none;
    padding: 0;
}
QLabel#collapsibleChevron {
    color: #9a9aa0;
    font-size: 11px;
    background: transparent;
    border: none;
    min-width: 14px;
    max-width: 14px;
}
"""

_NESTED_HEADER_STYLE = """
QFrame#collapsibleHeader {
    background: transparent;
    border: none;
    min-height: 26px;
    max-height: 26px;
}
QFrame#collapsibleHeader:hover QLabel#collapsibleTitle {
    color: #f0f0f2;
}
QLabel#collapsibleTitle {
    color: #c8c8cc;
    font-weight: 500;
    font-size: 11px;
    background: transparent;
    border: none;
    padding: 0;
}
QLabel#collapsibleChevron {
    color: #7a7a82;
    font-size: 10px;
    background: transparent;
    border: none;
    min-width: 14px;
    max-width: 14px;
}
"""


class CollapsibleSection(QWidget):
    """Section header that expands/collapses a content area."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        expanded: bool = True,
        level: str = "primary",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")
        self._level = level
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._expanded = expanded
        self._header = _SectionHeader(self, level=level)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10 if level == "primary" else 4, 0, 10, 0)
        header_layout.setSpacing(6)

        self._chevron = QLabel(self._chevron_text(expanded), self._header)
        self._chevron.setObjectName("collapsibleChevron")
        self._chevron.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title = QLabel(title, self._header)
        self._title.setObjectName("collapsibleTitle")
        self._title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        header_layout.addWidget(self._chevron)
        header_layout.addWidget(self._title, 1)
        self._header.clicked.connect(self._toggle)

        self._body = QWidget(self)
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._body_layout = QVBoxLayout(self._body)
        body_margins = (10, 8, 10, 10) if level == "primary" else (18, 2, 4, 6)
        self._body_layout.setContentsMargins(*body_margins)
        self._body_layout.setSpacing(8)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header)
        outer.addWidget(self._body)

        self._apply_expanded(expanded)

    def content_layout(self) -> QVBoxLayout:
        return self._body_layout

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._apply_expanded(expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)

    @staticmethod
    def _chevron_text(expanded: bool) -> str:
        return "\u25be" if expanded else "\u25b8"

    def _apply_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._body.setVisible(expanded)
        self._body.setMaximumHeight(_MAX_WIDGET_HEIGHT if expanded else 0)
        self._chevron.setText(self._chevron_text(expanded))
        self.updateGeometry()
        widget = self.parentWidget()
        while widget is not None:
            widget.updateGeometry()
            widget = widget.parentWidget()
