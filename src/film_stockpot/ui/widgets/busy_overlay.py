"""Semi-transparent overlay with an indeterminate progress indicator."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class BusyOverlay(QWidget):
    """Covers its parent area with a dimmed backdrop and a busy spinner."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background-color: rgba(20, 20, 20, 170);")

        self._label = QLabel("Applying...", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #f0f0f0; font-size: 16px; background: transparent;")

        self._bar = QProgressBar(self)
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedWidth(260)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)
        layout.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._bar, 0, Qt.AlignmentFlag.AlignHCenter)

        self.hide()

    def set_message(self, message: str) -> None:
        self._label.setText(message)
