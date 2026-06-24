"""Controls for preview stage selection and split comparison."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from film_stockpot.ui.preview_stages import STAGE_LABELS, PreviewStage


class PreviewModeBar(QWidget):
    """Toolbar for choosing preview stages and split compare mode."""

    changed = pyqtSignal()
    fit_requested = pyqtSignal()
    actual_size_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._view_stage = QComboBox(self)
        self._before_stage = QComboBox(self)
        self._after_stage = QComboBox(self)
        for combo in (self._view_stage, self._before_stage, self._after_stage):
            for stage in PreviewStage:
                combo.addItem(STAGE_LABELS[stage], stage)

        self._set_combo_stage(self._view_stage, PreviewStage.FULL)
        self._set_combo_stage(self._before_stage, PreviewStage.FLAT)
        self._set_combo_stage(self._after_stage, PreviewStage.FULL)

        self._split_toggle = QCheckBox("Split compare", self)
        self._split_toggle.setToolTip("Drag the divider in the preview to compare two stages")

        self._split_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._split_slider.setRange(5, 95)
        self._split_slider.setValue(50)
        self._split_slider.setEnabled(False)
        self._split_slider.setFixedWidth(120)

        self._fit_button = QPushButton("Fit", self)
        self._fit_button.setToolTip("Fit image to window (double-click preview)")
        self._actual_button = QPushButton("100%", self)
        self._actual_button.setToolTip("Show pixels at 1:1")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        layout.addWidget(QLabel("View:", self))
        layout.addWidget(self._view_stage, 1)
        layout.addWidget(self._split_toggle)
        layout.addWidget(QLabel("Before:", self))
        layout.addWidget(self._before_stage)
        layout.addWidget(QLabel("After:", self))
        layout.addWidget(self._after_stage)
        layout.addWidget(self._split_slider)
        layout.addWidget(self._fit_button)
        layout.addWidget(self._actual_button)

        self._view_stage.currentIndexChanged.connect(self._emit_changed)
        self._before_stage.currentIndexChanged.connect(self._emit_changed)
        self._after_stage.currentIndexChanged.connect(self._emit_changed)
        self._split_toggle.toggled.connect(self._on_split_toggled)
        self._split_slider.valueChanged.connect(self._emit_changed)
        self._fit_button.clicked.connect(self.fit_requested.emit)
        self._actual_button.clicked.connect(self.actual_size_requested.emit)

        self._update_split_controls_enabled()

    def view_stage(self) -> PreviewStage:
        return PreviewStage(self._view_stage.currentData())

    def before_stage(self) -> PreviewStage:
        return PreviewStage(self._before_stage.currentData())

    def after_stage(self) -> PreviewStage:
        return PreviewStage(self._after_stage.currentData())

    def split_enabled(self) -> bool:
        return self._split_toggle.isChecked()

    def split_ratio(self) -> float:
        return self._split_slider.value() / 100.0

    def set_split_ratio(self, ratio: float) -> None:
        value = int(max(0.05, min(0.95, ratio)) * 100)
        blocked = self._split_slider.blockSignals(True)
        self._split_slider.setValue(value)
        self._split_slider.blockSignals(blocked)

    def _on_split_toggled(self, enabled: bool) -> None:
        self._update_split_controls_enabled()
        self._emit_changed()

    def _update_split_controls_enabled(self) -> None:
        split_on = self._split_toggle.isChecked()
        self._view_stage.setEnabled(not split_on)
        self._before_stage.setEnabled(split_on)
        self._after_stage.setEnabled(split_on)
        self._split_slider.setEnabled(split_on)

    def _emit_changed(self) -> None:
        self.changed.emit()

    @staticmethod
    def _set_combo_stage(combo: QComboBox, stage: PreviewStage) -> None:
        index = combo.findData(stage)
        if index >= 0:
            combo.setCurrentIndex(index)
