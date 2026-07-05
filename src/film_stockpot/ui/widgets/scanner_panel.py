"""Right-hand panel of Fuji Frontier-style operator controls."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.image.scanner import NEUTRAL
from film_stockpot.ui.widgets.collapsible_section import CollapsibleSection


class ScannerPanel(QWidget):
    """Frontier-familiar controls that emit ``changed`` on every adjustment."""

    changed = pyqtSignal()
    interaction_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}
        self._interaction_depth = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        frontier = CollapsibleSection("Frontier Controls", self)
        frontier_layout = frontier.content_layout()

        density = CollapsibleSection("Density", self, level="nested")
        density_layout = density.content_layout()
        density_layout.addLayout(self._make_slider("density", "Density (+ darker)", -15, 15))
        density_layout.addLayout(self._make_slider("gamma", "Gamma (+ brighter)", -15, 15))
        frontier_layout.addWidget(density)
        self._density_group = density

        color_balance = CollapsibleSection("Color Balance", self, level="nested")
        color_layout = color_balance.content_layout()
        color_layout.addLayout(self._make_slider("cyan", "Cyan \u2194 Red", -15, 15))
        color_layout.addLayout(self._make_slider("magenta", "Magenta \u2194 Green", -15, 15))
        color_layout.addLayout(self._make_slider("yellow", "Yellow \u2194 Blue", -15, 15))
        frontier_layout.addWidget(color_balance)
        self._color_group = color_balance
        self._print_overlap_keys = ("density", "cyan", "magenta", "yellow")

        tone = CollapsibleSection("Tone", self, level="nested")
        tone_layout = tone.content_layout()
        tone_row = QHBoxLayout()
        tone_row.addWidget(QLabel("Tone curve", self))
        tone_row.addStretch(1)
        self._tone = QComboBox(self)
        self._tone.addItems(["Soft", "Standard", "Hard", "All Hard"])
        self._tone.setCurrentText("Standard")
        self._tone.currentTextChanged.connect(lambda _: self.changed.emit())
        tone_row.addWidget(self._tone)
        tone_layout.addLayout(tone_row)
        tone_layout.addLayout(self._make_slider("highlight", "Highlight", -15, 15))
        tone_layout.addLayout(self._make_slider("shadow", "Shadow", -15, 15))
        frontier_layout.addWidget(tone)

        color = CollapsibleSection("Color", self, level="nested")
        color_only_layout = color.content_layout()
        color_only_layout.addLayout(self._make_slider("saturation", "Saturation", -8, 8))
        frontier_layout.addWidget(color)

        detail = CollapsibleSection("Detail", self, level="nested")
        detail_layout = detail.content_layout()
        detail_layout.addLayout(self._make_slider("sharpness", "Sharpness", 0, 10))
        frontier_layout.addWidget(detail)

        self._reset_button = QPushButton("Reset Controls", self)
        self._reset_button.clicked.connect(self.reset)
        frontier_layout.addWidget(self._reset_button)

        layout.addWidget(frontier)

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
        slider.sliderPressed.connect(self._begin_interaction)
        slider.sliderReleased.connect(self._end_interaction)
        row.addWidget(slider)

        self._sliders[key] = slider
        self._value_labels[key] = value_label
        return row

    def _on_slider_changed(self, value: int, value_label: QLabel) -> None:
        value_label.setText(str(value))
        self.changed.emit()

    def _begin_interaction(self) -> None:
        if self._interaction_depth == 0:
            self.interaction_changed.emit(True)
        self._interaction_depth += 1

    def _end_interaction(self) -> None:
        self._interaction_depth = max(0, self._interaction_depth - 1)
        if self._interaction_depth == 0:
            self.interaction_changed.emit(False)

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

    def set_print_controls_active(self, active: bool) -> None:
        """Disable Frontier density/CMY that overlap print; keep gamma for post-print tone."""
        tooltip = (
            "Controlled by Print emulation when print is enabled."
            if active
            else ""
        )
        self._density_group.setEnabled(True)
        self._density_group.setToolTip("")
        self._color_group.setEnabled(not active)
        self._color_group.setToolTip(tooltip)
        self._sliders["gamma"].setEnabled(True)
        self._sliders["gamma"].setToolTip("")
        for key in self._print_overlap_keys:
            slider = self._sliders[key]
            slider.setEnabled(not active)
            slider.setToolTip(tooltip if active else "")
