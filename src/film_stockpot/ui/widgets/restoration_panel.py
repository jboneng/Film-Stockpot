"""Restoration tab: dust, hair, and scratch defect detection and removal."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.image.restoration import (
    DEFECT_NEUTRAL,
    INPAINT_NS,
    INPAINT_TELEA,
    DefectParams,
)
from film_stockpot.ui.widgets.collapsible_section import CollapsibleSection


class RestorationPanel(QWidget):
    """Controls for generating, previewing, and removing a defect mask."""

    generate_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    mask_view_toggled = pyqtSignal(bool)
    overlay_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._sliders: dict[str, tuple[QSlider, QLabel, float]] = {}
        self._has_mask = False
        self._has_image = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        section = CollapsibleSection("Defect Removal", self)
        section_layout = section.content_layout()

        section_layout.addWidget(
            self._hint("Detect dust, hair, and scratches on the scan, then inpaint them.")
        )

        detectors = CollapsibleSection("Detectors", self, level="nested")
        detectors_layout = detectors.content_layout()
        self._dust = self._make_detector_checkbox("Dust and specks", DEFECT_NEUTRAL.detect_dust)
        self._hair = self._make_detector_checkbox("Hair and fibers", DEFECT_NEUTRAL.detect_hair)
        self._scratch = self._make_detector_checkbox("Scratches", DEFECT_NEUTRAL.detect_scratch)
        detectors_layout.addWidget(self._dust)
        detectors_layout.addLayout(
            self._make_slider("dust_sensitivity", "Dust sensitivity", DEFECT_NEUTRAL.dust_sensitivity)
        )
        detectors_layout.addWidget(self._hair)
        detectors_layout.addLayout(
            self._make_slider("hair_sensitivity", "Hair sensitivity", DEFECT_NEUTRAL.hair_sensitivity)
        )
        detectors_layout.addWidget(self._scratch)
        detectors_layout.addLayout(
            self._make_slider("scratch_sensitivity", "Scratch sensitivity", DEFECT_NEUTRAL.scratch_sensitivity)
        )
        section_layout.addWidget(detectors)

        mask_shape = CollapsibleSection("Mask", self, level="nested")
        mask_layout = mask_shape.content_layout()
        mask_layout.addLayout(
            self._make_int_slider("min_size", "Min defect size (px)", 1, 40, DEFECT_NEUTRAL.min_size)
        )
        mask_layout.addLayout(
            self._make_int_slider("dilation", "Mask grow (px)", 0, 8, DEFECT_NEUTRAL.dilation)
        )
        mask_layout.addLayout(
            self._make_int_slider("overlay_opacity", "Overlay opacity (%)", 10, 100, 70, on_change=self._on_overlay_changed)
        )
        section_layout.addWidget(mask_shape)

        inpaint = CollapsibleSection("Inpainting", self, level="nested")
        inpaint_layout = inpaint.content_layout()
        method_row = QHBoxLayout()
        method_row.addWidget(QLabel("Method", self))
        method_row.addStretch(1)
        self._method = QComboBox(self)
        self._method.addItem("Telea", INPAINT_TELEA)
        self._method.addItem("Navier-Stokes", INPAINT_NS)
        method_row.addWidget(self._method)
        inpaint_layout.addLayout(method_row)
        inpaint_layout.addLayout(
            self._make_int_slider("inpaint_radius", "Inpaint radius (px)", 1, 15, DEFECT_NEUTRAL.inpaint_radius)
        )
        section_layout.addWidget(inpaint)

        self._generate_button = QPushButton("Generate Mask", self)
        self._generate_button.setToolTip("Detect defects and build a repair mask")
        self._generate_button.clicked.connect(self.generate_requested.emit)
        section_layout.addWidget(self._generate_button)

        buttons_row = QHBoxLayout()
        self._show_button = QPushButton("Show Mask", self)
        self._show_button.setCheckable(True)
        self._show_button.setToolTip("Toggle the preview between the image and the mask overlay")
        self._show_button.toggled.connect(self._on_show_toggled)
        self._clear_button = QPushButton("Clear Mask", self)
        self._clear_button.setToolTip("Discard the mask and restore the original scan")
        self._clear_button.clicked.connect(self.clear_requested.emit)
        buttons_row.addWidget(self._show_button)
        buttons_row.addWidget(self._clear_button)
        section_layout.addLayout(buttons_row)

        self._remove_button = QPushButton("Remove Defects", self)
        self._remove_button.setToolTip("Inpaint the masked defects")
        self._remove_button.clicked.connect(self.remove_requested.emit)
        section_layout.addWidget(self._remove_button)

        self._status = QLabel("No mask generated.", self)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #9a9aa0;")
        section_layout.addWidget(self._status)

        layout.addWidget(section)

        self._update_buttons()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def params(self) -> DefectParams:
        return DefectParams(
            detect_dust=self._dust.isChecked(),
            detect_hair=self._hair.isChecked(),
            detect_scratch=self._scratch.isChecked(),
            dust_sensitivity=self._slider_value("dust_sensitivity"),
            hair_sensitivity=self._slider_value("hair_sensitivity"),
            scratch_sensitivity=self._slider_value("scratch_sensitivity"),
            min_size=int(round(self._slider_value("min_size"))),
            dilation=int(round(self._slider_value("dilation"))),
            inpaint_method=self._method.currentData(),
            inpaint_radius=int(round(self._slider_value("inpaint_radius"))),
        )

    def overlay_opacity(self) -> float:
        return self._slider_value("overlay_opacity") / 100.0

    def set_image_available(self, available: bool) -> None:
        self._has_image = available
        if not available:
            self.set_mask_available(False)
        self._update_buttons()

    def set_mask_available(self, available: bool) -> None:
        self._has_mask = available
        if not available:
            self.set_mask_view(False)
        self._update_buttons()

    def set_mask_view(self, active: bool) -> None:
        if self._show_button.isChecked() == active:
            return
        self._show_button.blockSignals(True)
        self._show_button.setChecked(active)
        self._show_button.blockSignals(False)

    def is_mask_view_active(self) -> bool:
        return self._show_button.isChecked()

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _hint(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setWordWrap(True)
        label.setStyleSheet("color: #9a9aa0;")
        return label

    def _make_detector_checkbox(self, label: str, checked: bool) -> QCheckBox:
        box = QCheckBox(label, self)
        box.setChecked(checked)
        return box

    def _make_slider(self, key: str, label: str, default: float) -> QVBoxLayout:
        """A 0..1 sensitivity slider stored at 0.01 resolution."""
        return self._build_slider(key, label, 0, 100, int(round(default * 100)), scale=0.01)

    def _make_int_slider(
        self,
        key: str,
        label: str,
        low: int,
        high: int,
        default: int,
        *,
        on_change=None,
    ) -> QVBoxLayout:
        return self._build_slider(key, label, low, high, default, scale=1.0, on_change=on_change)

    def _build_slider(
        self,
        key: str,
        label: str,
        low: int,
        high: int,
        default: int,
        *,
        scale: float,
        on_change=None,
    ) -> QVBoxLayout:
        row = QVBoxLayout()
        row.setSpacing(2)
        header = QHBoxLayout()
        header.addWidget(QLabel(label, self))
        header.addStretch(1)
        value_label = QLabel(self._format_value(default, scale), self)
        value_label.setMinimumWidth(36)
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(value_label)
        row.addLayout(header)

        slider = QSlider(Qt.Orientation.Horizontal, self)
        slider.setRange(low, high)
        slider.setValue(default)
        slider.valueChanged.connect(
            lambda value, lbl=value_label, sc=scale, cb=on_change: self._on_slider_changed(value, lbl, sc, cb)
        )
        row.addWidget(slider)
        self._sliders[key] = (slider, value_label, scale)
        return row

    @staticmethod
    def _format_value(value: int, scale: float) -> str:
        if scale == 1.0:
            return str(int(value))
        return f"{value * scale:.2f}"

    def _slider_value(self, key: str) -> float:
        slider, _, scale = self._sliders[key]
        return slider.value() * scale

    def _on_slider_changed(self, value: int, value_label: QLabel, scale: float, callback) -> None:
        value_label.setText(self._format_value(value, scale))
        if callback is not None:
            callback()

    def _on_overlay_changed(self) -> None:
        if self._show_button.isChecked():
            self.overlay_changed.emit()

    def _on_show_toggled(self, checked: bool) -> None:
        self.mask_view_toggled.emit(checked)

    def _update_buttons(self) -> None:
        self._generate_button.setEnabled(self._has_image)
        self._show_button.setEnabled(self._has_mask)
        self._clear_button.setEnabled(self._has_mask)
        self._remove_button.setEnabled(self._has_mask)
