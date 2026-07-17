"""Shadow / midtone / highlight color-wheel grading controls."""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.image.grading import (
    GRADING_NEUTRAL,
    camera_style_scanner_overrides,
    camera_style_to_grading,
    normalize_grading,
)
from film_stockpot.styles.loader import CameraStyle, load_camera_styles
from film_stockpot.ui.widgets.color_wheel import ColorWheelWidget
from film_stockpot.ui.widgets.curve_editor import CurveEditorWidget


class _ZoneControl(QWidget):
    """One color wheel plus a luminance slider."""

    changed = pyqtSignal()
    interaction_changed = pyqtSignal(bool)

    def __init__(self, label: str, wheel_size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._wheel = ColorWheelWidget(wheel_size, self)
        self._wheel.value_changed.connect(self.changed.emit)
        self._wheel.dragging_changed.connect(self.interaction_changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel(label, self)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._wheel, 0, Qt.AlignmentFlag.AlignHCenter)

        lum_row = QHBoxLayout()
        lum_row.setSpacing(6)
        lum_icon = QLabel("\u2600", self)
        lum_icon.setToolTip("Luminance")
        lum_row.addWidget(lum_icon)
        self._lum = QSlider(Qt.Orientation.Horizontal, self)
        self._lum.setRange(-100, 100)
        self._lum.setValue(0)
        self._lum.valueChanged.connect(self._on_lum_changed)
        self._lum.sliderPressed.connect(lambda: self.interaction_changed.emit(True))
        self._lum.sliderReleased.connect(lambda: self.interaction_changed.emit(False))
        lum_row.addWidget(self._lum, 1)
        self._lum_value = QLabel("0", self)
        self._lum_value.setMinimumWidth(28)
        self._lum_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lum_row.addWidget(self._lum_value)
        layout.addLayout(lum_row)

    def _on_lum_changed(self, value: int) -> None:
        self._lum_value.setText(str(value))
        self.changed.emit()

    def zone_values(self) -> dict:
        hue, sat = self._wheel.values()
        return {"hue": hue, "sat": sat, "lum": self._lum.value()}

    def set_zone_values(self, values: dict) -> None:
        self._wheel.blockSignals(True)
        self._wheel.set_values(float(values.get("hue", 0.0)), float(values.get("sat", 0.0)))
        self._wheel.blockSignals(False)
        lum = int(values.get("lum", 0))
        self._lum.blockSignals(True)
        self._lum.setValue(lum)
        self._lum.blockSignals(False)
        self._lum_value.setText(str(lum))


class GradingPanel(QWidget):
    """Color wheels for shadow, midtone, and highlight grading."""

    changed = pyqtSignal()
    interaction_changed = pyqtSignal(bool)
    scanner_overrides = pyqtSignal(dict)

    _STYLE_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._interaction_depth = 0
        self._style_id: str | None = None
        self._monochrome = False
        self._applying_style = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style", self))
        self._style_combo = QComboBox(self)
        self._style_combo.setMaxVisibleItems(20)
        self._populate_styles()
        self._style_combo.currentIndexChanged.connect(self._on_style_changed)
        style_row.addWidget(self._style_combo, 1)
        layout.addLayout(style_row)

        self._midtones = _ZoneControl("Midtones", 128, self)
        self._midtones.changed.connect(self.changed.emit)
        self._midtones.interaction_changed.connect(self._on_zone_interaction)
        layout.addWidget(self._midtones, 0, Qt.AlignmentFlag.AlignHCenter)

        wheels_row = QHBoxLayout()
        wheels_row.setSpacing(16)
        self._shadows = _ZoneControl("Shadows", 104, self)
        self._highlights = _ZoneControl("Highlights", 104, self)
        self._shadows.changed.connect(self.changed.emit)
        self._highlights.changed.connect(self.changed.emit)
        self._shadows.interaction_changed.connect(self._on_zone_interaction)
        self._highlights.interaction_changed.connect(self._on_zone_interaction)
        wheels_row.addWidget(self._shadows)
        wheels_row.addWidget(self._highlights)
        layout.addLayout(wheels_row)

        layout.addLayout(self._make_global_slider("blending", "Blending", 0, 100, 50))
        layout.addLayout(self._make_global_slider("balance", "Balance", -100, 100, 0))
        self._blending_slider.sliderPressed.connect(self._begin_interaction)
        self._blending_slider.sliderReleased.connect(self._end_interaction)
        self._balance_slider.sliderPressed.connect(self._begin_interaction)
        self._balance_slider.sliderReleased.connect(self._end_interaction)

        self._curve_editor = CurveEditorWidget(self)
        self._curve_editor.changed.connect(self.changed.emit)
        self._curve_editor.interaction_changed.connect(self._on_zone_interaction)
        layout.addWidget(self._curve_editor)

        self._reset_button = QPushButton("Reset Grading", self)
        self._reset_button.clicked.connect(self.reset)
        layout.addWidget(self._reset_button)
        layout.addStretch(1)

    def _populate_styles(self) -> None:
        model = QStandardItemModel(self._style_combo)
        none_item = QStandardItem("None")
        none_item.setData(None, self._STYLE_ROLE)
        model.appendRow(none_item)

        try:
            styles = load_camera_styles()
        except FileNotFoundError:
            styles = []

        name_counts: dict[str, int] = {}
        for style in styles:
            name_counts[style.name] = name_counts.get(style.name, 0) + 1

        for style in styles:
            text = style.name
            if name_counts.get(style.name, 0) > 1 and style.slot:
                text = f"{style.name} ({style.slot})"
            item = QStandardItem(text)
            item.setData(style, self._STYLE_ROLE)
            model.appendRow(item)

        self._style_combo.setModel(model)

    def _on_style_changed(self, index: int) -> None:
        if self._applying_style:
            return
        style = self._style_combo.itemData(index, self._STYLE_ROLE)
        if style is None:
            grading = normalize_grading(GRADING_NEUTRAL)
            self.set_settings(grading)
            self.changed.emit()
            return

        assert isinstance(style, CameraStyle)
        grading = camera_style_to_grading(style)
        self.set_settings(grading)
        overrides = camera_style_scanner_overrides(style)
        if overrides:
            self.scanner_overrides.emit(overrides)
        self.changed.emit()

    def _make_global_slider(self, key: str, label: str, low: int, high: int, default: int) -> QVBoxLayout:
        row = QVBoxLayout()
        row.setSpacing(2)
        header = QHBoxLayout()
        header.addWidget(QLabel(label, self))
        header.addStretch(1)
        value_label = QLabel(str(default), self)
        value_label.setMinimumWidth(28)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(value_label)
        row.addLayout(header)

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(low, high)
        slider.setValue(default)
        slider.valueChanged.connect(lambda value, lbl=value_label: self._on_global_changed(value, lbl))
        row.addWidget(slider)

        setattr(self, f"_{key}_slider", slider)
        setattr(self, f"_{key}_value", value_label)
        return row

    def _on_global_changed(self, value: int, value_label: QLabel) -> None:
        value_label.setText(str(value))
        self.changed.emit()

    def _on_zone_interaction(self, active: bool) -> None:
        if active:
            self._begin_interaction()
        else:
            self._end_interaction()

    def _begin_interaction(self) -> None:
        if self._interaction_depth == 0:
            self.interaction_changed.emit(True)
        self._interaction_depth += 1

    def _end_interaction(self) -> None:
        self._interaction_depth = max(0, self._interaction_depth - 1)
        if self._interaction_depth == 0:
            self.interaction_changed.emit(False)

    def _select_style_id(self, style_id: str | None) -> None:
        self._applying_style = True
        try:
            if not style_id:
                self._style_combo.setCurrentIndex(0)
                return
            for row in range(self._style_combo.count()):
                style = self._style_combo.itemData(row, self._STYLE_ROLE)
                if isinstance(style, CameraStyle) and style.id == style_id:
                    self._style_combo.setCurrentIndex(row)
                    return
            self._style_combo.setCurrentIndex(0)
        finally:
            self._applying_style = False

    def settings(self) -> dict:
        return {
            "grading": {
                "shadows": self._shadows.zone_values(),
                "midtones": self._midtones.zone_values(),
                "highlights": self._highlights.zone_values(),
                "blending": self._blending_slider.value(),
                "balance": self._balance_slider.value(),
                "curves": self._curve_editor.curves(),
                "monochrome": self._monochrome,
                "style_id": self._style_id,
            }
        }

    def set_settings(self, grading: dict | None) -> None:
        values = normalize_grading(grading)
        self._style_id = values.get("style_id")
        self._monochrome = bool(values.get("monochrome"))
        self._select_style_id(self._style_id)

        self._shadows.set_zone_values(values["shadows"])
        self._midtones.set_zone_values(values["midtones"])
        self._highlights.set_zone_values(values["highlights"])

        self._blending_slider.blockSignals(True)
        self._blending_slider.setValue(int(values["blending"]))
        self._blending_slider.blockSignals(False)
        self._blending_value.setText(str(values["blending"]))

        self._balance_slider.blockSignals(True)
        self._balance_slider.setValue(int(values["balance"]))
        self._balance_slider.blockSignals(False)
        self._balance_value.setText(str(values["balance"]))

        self._curve_editor.set_curves(values.get("curves"))

    def set_luma_histogram(self, hist: np.ndarray | None) -> None:
        self._curve_editor.set_luma_histogram(hist)

    def reset(self) -> None:
        self.set_settings(GRADING_NEUTRAL)
        self.changed.emit()
