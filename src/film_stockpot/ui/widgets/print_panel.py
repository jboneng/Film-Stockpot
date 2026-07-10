"""Darkroom print controls for exposure and paper emulation."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.image.print import (
    PRINT_NEUTRAL,
    default_paper_profile,
    normalize_print_settings,
    process_mode_for_preset,
    profiles_for_mode,
)
from film_stockpot.ui.widgets.collapsible_section import CollapsibleSection


class PrintPanel(QWidget):
    """Darkroom print emulation controls."""

    changed = pyqtSignal()
    interaction_changed = pyqtSignal(bool)
    enabled_changed = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._interaction_depth = 0
        self._process_mode = "c41"
        self._building = False
        self._sliders: dict[str, tuple[QSlider, QLabel, float]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        section = CollapsibleSection("Print Emulation", self)
        section_layout = section.content_layout()

        self._enabled = QCheckBox("Enable print emulation", self)
        self._enabled.setToolTip(
            "Simulate RA-4 / darkroom paper printing before Frontier scanner controls."
        )
        self._enabled.toggled.connect(self._on_enabled_toggled)
        section_layout.addWidget(self._enabled)

        paper_row = QHBoxLayout()
        paper_row.addWidget(QLabel("Paper", self))
        self._paper = QComboBox(self)
        paper_row.addWidget(self._paper, 1)
        section_layout.addLayout(paper_row)

        auto_row = QHBoxLayout()
        self._auto_exposure = QCheckBox("Auto density", self)
        self._auto_exposure.setChecked(True)
        self._auto_grade = QCheckBox("Auto grade", self)
        self._auto_grade.setChecked(False)
        auto_row.addWidget(self._auto_exposure)
        auto_row.addWidget(self._auto_grade)
        section_layout.addLayout(auto_row)

        exposure = CollapsibleSection("Exposure", self, level="nested")
        exposure_layout = exposure.content_layout()
        exposure_layout.addLayout(self._make_slider("density", "Density", 0, 200, scale=0.01, default=75))
        exposure_layout.addLayout(self._make_slider("grade", "ISO-R grade", 50, 180, scale=1.0, default=115))
        section_layout.addWidget(exposure)

        color = CollapsibleSection("Filtration (CMY)", self, level="nested")
        color_layout = color.content_layout()
        color_layout.addLayout(self._make_slider("cyan", "Cyan", -100, 100, scale=0.01))
        color_layout.addLayout(self._make_slider("magenta", "Magenta", -100, 100, scale=0.01))
        color_layout.addLayout(self._make_slider("yellow", "Yellow", -100, 100, scale=0.01))
        section_layout.addWidget(color)

        shape = CollapsibleSection("Paper curve", self, level="nested")
        shape_layout = shape.content_layout()
        shape_layout.addLayout(self._make_slider("toe", "Toe", -100, 100, scale=0.01))
        shape_layout.addLayout(self._make_slider("toe_width", "Toe width", 1, 500, scale=0.01, default=250))
        shape_layout.addLayout(self._make_slider("shoulder", "Shoulder", -100, 100, scale=0.01))
        shape_layout.addLayout(self._make_slider("shoulder_width", "Shoulder width", 1, 500, scale=0.01, default=250))
        section_layout.addWidget(shape)

        toggles = QHBoxLayout()
        self._paper_dmin = QCheckBox("Paper white", self)
        self._paper_dmin.setChecked(True)
        self._auto_cast = QCheckBox("Auto cast removal", self)
        self._auto_cast.setChecked(True)
        toggles.addWidget(self._paper_dmin)
        toggles.addWidget(self._auto_cast)
        section_layout.addLayout(toggles)

        self._reset_button = QPushButton("Reset Print", self)
        self._reset_button.clicked.connect(self.reset)
        section_layout.addWidget(self._reset_button)

        layout.addWidget(section)

        self._populate_paper_combo()
        self._set_controls_enabled(False)
        self._paper.currentIndexChanged.connect(self._on_child_changed)
        self._auto_exposure.toggled.connect(self._on_child_changed)
        self._auto_grade.toggled.connect(self._on_child_changed)
        self._paper_dmin.toggled.connect(self._on_child_changed)
        self._auto_cast.toggled.connect(self._on_child_changed)

    def _on_child_changed(self, *_args) -> None:
        if not self._building:
            self.changed.emit()

    def _make_slider(
        self,
        key: str,
        label: str,
        low: int,
        high: int,
        *,
        scale: float,
        default: int = 0,
    ) -> QVBoxLayout:
        row = QVBoxLayout()
        row.setSpacing(2)
        header = QHBoxLayout()
        header.addWidget(QLabel(label, self))
        header.addStretch(1)
        value_label = QLabel(self._format_slider_value(default, scale), self)
        value_label.setMinimumWidth(36)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(value_label)
        row.addLayout(header)

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(low, high)
        slider.setValue(default)
        slider.valueChanged.connect(
            lambda value, lbl=value_label, sc=scale: self._on_slider_changed(value, lbl, sc)
        )
        slider.sliderPressed.connect(self._begin_interaction)
        slider.sliderReleased.connect(self._end_interaction)
        row.addWidget(slider)
        self._sliders[key] = (slider, value_label, scale)
        return row

    @staticmethod
    def _format_slider_value(value: int, scale: float) -> str:
        if scale == 1.0:
            return str(value)
        return f"{value * scale:.2f}"

    def _slider_value(self, key: str) -> float:
        slider, _, scale = self._sliders[key]
        return slider.value() * scale

    def _set_slider_value(self, key: str, value: float) -> None:
        slider, label, scale = self._sliders[key]
        slider.blockSignals(True)
        slider.setValue(int(round(value / scale)))
        slider.blockSignals(False)
        label.setText(self._format_slider_value(slider.value(), scale))

    def _on_slider_changed(self, value: int, value_label: QLabel, scale: float) -> None:
        value_label.setText(self._format_slider_value(value, scale))
        if not self._building:
            self.changed.emit()

    def _on_enabled_toggled(self, enabled: bool) -> None:
        self._set_controls_enabled(enabled)
        self.enabled_changed.emit(enabled)
        if not self._building:
            self.changed.emit()

    def _set_controls_enabled(self, enabled: bool) -> None:
        """Disable only controls that need an active print; auto toggles stay editable."""
        for widget in (self._paper, self._reset_button):
            widget.setEnabled(enabled)
        for widget in (self._auto_exposure, self._auto_grade, self._paper_dmin, self._auto_cast):
            widget.setEnabled(True)
        for slider, label, _scale in self._sliders.values():
            slider.setEnabled(enabled)
            label.setEnabled(enabled)

    def _begin_interaction(self) -> None:
        if self._interaction_depth == 0:
            self.interaction_changed.emit(True)
        self._interaction_depth += 1

    def _end_interaction(self) -> None:
        self._interaction_depth = max(0, self._interaction_depth - 1)
        if self._interaction_depth == 0:
            self.interaction_changed.emit(False)

    def _populate_paper_combo(self) -> None:
        entries = [(profile.label, key) for key, profile in profiles_for_mode(self._process_mode)]
        current = [(self._paper.itemText(i), self._paper.itemData(i)) for i in range(self._paper.count())]
        if entries == current:
            return
        selected = self._paper.currentData()
        self._paper.blockSignals(True)
        self._paper.clear()
        for label, key in entries:
            self._paper.addItem(label, key)
        index = self._paper.findData(selected)
        if index >= 0:
            self._paper.setCurrentIndex(index)
        self._paper.blockSignals(False)

    def sync_for_preset(self, preset: dict | None) -> None:
        mode = process_mode_for_preset(preset)
        if mode == self._process_mode:
            return
        self._process_mode = mode
        self._populate_paper_combo()
        if self._enabled.isChecked():
            self._paper.blockSignals(True)
            index = self._paper.findData(default_paper_profile(preset))
            if index >= 0:
                self._paper.setCurrentIndex(index)
            self._paper.blockSignals(False)

    def settings(self) -> dict:
        values = {
            "enabled": self._enabled.isChecked(),
            "paper_profile": self._paper.currentData() or PRINT_NEUTRAL["paper_profile"],
            "auto_exposure": self._auto_exposure.isChecked(),
            "auto_normalize_contrast": self._auto_grade.isChecked(),
            "auto_cast_removal": self._auto_cast.isChecked(),
            "paper_dmin": self._paper_dmin.isChecked(),
            "cast_removal_strength": PRINT_NEUTRAL["cast_removal_strength"],
        }
        for key in self._sliders:
            values[key] = self._slider_value(key)
        return values

    def set_settings(self, settings: dict | None, preset: dict | None = None) -> None:
        merged = normalize_print_settings(settings, preset)
        self._building = True
        self.sync_for_preset(preset)
        self._enabled.blockSignals(True)
        self._enabled.setChecked(bool(merged["enabled"]))
        self._enabled.blockSignals(False)
        self._set_controls_enabled(bool(merged["enabled"]))

        index = self._paper.findData(merged["paper_profile"])
        if index >= 0:
            self._paper.setCurrentIndex(index)

        self._auto_exposure.setChecked(bool(merged["auto_exposure"]))
        self._auto_grade.setChecked(bool(merged["auto_normalize_contrast"]))
        self._auto_cast.setChecked(bool(merged["auto_cast_removal"]))
        self._paper_dmin.setChecked(bool(merged["paper_dmin"]))

        self._set_slider_value("density", float(merged["density"]))
        self._set_slider_value("grade", float(merged["grade"]))
        self._set_slider_value("cyan", float(merged["cyan"]))
        self._set_slider_value("magenta", float(merged["magenta"]))
        self._set_slider_value("yellow", float(merged["yellow"]))
        self._set_slider_value("toe", float(merged["toe"]))
        self._set_slider_value("toe_width", float(merged["toe_width"]))
        self._set_slider_value("shoulder", float(merged["shoulder"]))
        self._set_slider_value("shoulder_width", float(merged["shoulder_width"]))
        self._building = False

    def reset(self) -> None:
        preset = None
        merged = normalize_print_settings(PRINT_NEUTRAL, preset)
        self.set_settings(merged, preset)
        self.changed.emit()

    def is_enabled(self) -> bool:
        return self._enabled.isChecked()
