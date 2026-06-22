"""Right-hand panel of Fuji Frontier-style operator controls."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.image.scanner import NEUTRAL


class ScannerPanel(QWidget):
    """Frontier-familiar controls that emit ``changed`` on every adjustment."""

    changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Frontier Controls", self)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title.setFont(title_font)
        layout.addWidget(title)

        density = QGroupBox("Density", self)
        density_layout = QVBoxLayout(density)
        density_layout.addLayout(self._make_slider("density", "Density (+ darker)", -15, 15))
        density_layout.addLayout(self._make_slider("gamma", "Gamma (+ brighter)", -15, 15))
        layout.addWidget(density)

        color_balance = QGroupBox("Color Balance", self)
        color_layout = QVBoxLayout(color_balance)
        color_layout.addLayout(self._make_slider("cyan", "Cyan \u2194 Red", -15, 15))
        color_layout.addLayout(self._make_slider("magenta", "Magenta \u2194 Green", -15, 15))
        color_layout.addLayout(self._make_slider("yellow", "Yellow \u2194 Blue", -15, 15))
        layout.addWidget(color_balance)

        tone = QGroupBox("Tone", self)
        tone_layout = QVBoxLayout(tone)
        tone_row = QHBoxLayout()
        tone_row.addWidget(QLabel("Tone", self))
        tone_row.addStretch(1)
        self._tone = QComboBox(self)
        self._tone.addItems(["Soft", "Standard", "Hard", "All Hard"])
        self._tone.setCurrentText("Standard")
        self._tone.currentTextChanged.connect(lambda _: self.changed.emit())
        tone_row.addWidget(self._tone)
        tone_layout.addLayout(tone_row)
        tone_layout.addLayout(self._make_slider("highlight", "Highlight", -15, 15))
        tone_layout.addLayout(self._make_slider("shadow", "Shadow", -15, 15))
        layout.addWidget(tone)

        color = QGroupBox("Color", self)
        color_only_layout = QVBoxLayout(color)
        color_only_layout.addLayout(self._make_slider("saturation", "Saturation", -8, 8))
        layout.addWidget(color)

        detail = QGroupBox("Detail", self)
        detail_layout = QVBoxLayout(detail)
        detail_layout.addLayout(self._make_slider("sharpness", "Sharpness", 0, 10))
        layout.addWidget(detail)

        self._reset_button = QPushButton("Reset Controls", self)
        self._reset_button.clicked.connect(self.reset)
        layout.addWidget(self._reset_button)

        layout.addStretch(1)

    def _make_slider(self, key: str, label: str, low: int, high: int) -> QVBoxLayout:
        row = QVBoxLayout()
        row.setSpacing(2)

        header = QHBoxLayout()
        header.addWidget(QLabel(label, self))
        header.addStretch(1)
        value_label = QLabel("0", self)
        value_label.setMinimumWidth(28)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(value_label)
        row.addLayout(header)

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(low, high)
        slider.setValue(0)
        slider.valueChanged.connect(lambda value, lbl=value_label: self._on_slider_changed(value, lbl))
        row.addWidget(slider)

        self._sliders[key] = slider
        self._value_labels[key] = value_label
        return row

    def _on_slider_changed(self, value: int, value_label: QLabel) -> None:
        value_label.setText(str(value))
        self.changed.emit()

    def settings(self) -> dict:
        values = {key: slider.value() for key, slider in self._sliders.items()}
        values["tone"] = self._tone.currentText()
        return values

    def set_settings(self, settings: dict) -> None:
        """Restore control values without emitting ``changed`` for each tweak."""
        for key, slider in self._sliders.items():
            if key not in settings:
                continue
            value = int(settings[key])
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
            self._value_labels[key].setText(str(value))

        if "tone" in settings:
            self._tone.blockSignals(True)
            self._tone.setCurrentText(str(settings["tone"]))
            self._tone.blockSignals(False)

    def reset(self) -> None:
        for key, slider in self._sliders.items():
            slider.blockSignals(True)
            slider.setValue(0)
            slider.blockSignals(False)
            self._value_labels[key].setText("0")
        self._tone.blockSignals(True)
        self._tone.setCurrentText(NEUTRAL["tone"])
        self._tone.blockSignals(False)
        self.changed.emit()
