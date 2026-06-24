"""Export tab for saving processed images."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.export_naming import (
    DEFAULT_TEMPLATE,
    NAME_PRESET_LABELS,
    NAME_PRESETS,
    OUTPUT_EXTENSION,
    example_export_name,
)
from film_stockpot.ui.export_settings import load_name_template, save_name_template

FORMAT_TIFF_16BIT = "TIFF 16-bit"
_CUSTOM_PRESET = "__custom__"


class ExportPanel(QWidget):
    """Export format selection and save action."""

    name_template_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        format_group = QGroupBox("Format", self)
        format_layout = QVBoxLayout(format_group)

        format_row = QHBoxLayout()
        self._format = QComboBox(self)
        self._format.addItem(FORMAT_TIFF_16BIT)
        format_row.addWidget(self._format, 1)
        format_layout.addLayout(format_row)

        layout.addWidget(format_group)

        naming_group = QGroupBox("Naming", self)
        naming_layout = QVBoxLayout(naming_group)

        preset_row = QHBoxLayout()
        self._name_preset = QComboBox(self)
        for key, label in NAME_PRESET_LABELS.items():
            self._name_preset.addItem(label, key)
        self._name_preset.addItem("Custom", _CUSTOM_PRESET)
        preset_row.addWidget(self._name_preset, 1)
        naming_layout.addLayout(preset_row)

        self._name_template = QLineEdit(self)
        self._name_template.setPlaceholderText(DEFAULT_TEMPLATE)
        self._name_template.setToolTip(
            "Tokens: {original}, {preset}, {preset_name}, {roll}, {n}, {n:03}, {date}"
        )
        naming_layout.addWidget(self._name_template)

        self._name_preview = QLabel(self)
        self._name_preview.setStyleSheet("color: #9a9aa0; font-size: 11px;")
        self._name_preview.setWordWrap(True)
        naming_layout.addWidget(self._name_preview)

        layout.addWidget(naming_group)

        self._export_button = QPushButton("Export Image", self)
        self._export_button.clicked.connect(self._on_export_clicked)
        layout.addWidget(self._export_button)

        self._export_all_button = QPushButton("Export All", self)
        self._export_all_button.setObjectName("primaryButton")
        self._export_all_button.clicked.connect(self._on_export_all_clicked)
        layout.addWidget(self._export_all_button)

        roll_group = QGroupBox("Roll", self)
        roll_layout = QVBoxLayout(roll_group)
        self._copy_all_button = QPushButton("Copy Settings to All", self)
        self._copy_all_button.setToolTip("Write the current film stock and adjustments to every image")
        self._copy_all_button.clicked.connect(self._on_copy_all_clicked)
        roll_layout.addWidget(self._copy_all_button)
        self._copy_unedited_button = QPushButton("Copy to Unedited Only", self)
        self._copy_unedited_button.setToolTip("Apply current settings only to images without a sidecar file")
        self._copy_unedited_button.clicked.connect(self._on_copy_unedited_clicked)
        roll_layout.addWidget(self._copy_unedited_button)
        layout.addWidget(roll_group)

        layout.addStretch(1)

        self._export_callback = None
        self._export_all_callback = None
        self._copy_all_callback = None
        self._copy_unedited_callback = None

        self._name_preset.currentIndexChanged.connect(self._on_name_preset_changed)
        self._name_template.textChanged.connect(self._on_name_template_changed)

        saved_template = load_name_template()
        self._set_template(saved_template, select_matching_preset=True)

    def set_export_callback(self, callback) -> None:
        self._export_callback = callback

    def set_export_all_callback(self, callback) -> None:
        self._export_all_callback = callback

    def set_copy_all_callback(self, callback) -> None:
        self._copy_all_callback = callback

    def set_copy_unedited_callback(self, callback) -> None:
        self._copy_unedited_callback = callback

    def selected_format(self) -> str:
        return self._format.currentText()

    def name_template(self) -> str:
        text = self._name_template.text().strip()
        return text or DEFAULT_TEMPLATE

    def set_name_preview(self, example_stem: str) -> None:
        self._name_preview.setText(f"Example: {example_stem}{OUTPUT_EXTENSION}")

    def refresh_builtin_preview(self) -> None:
        self.set_name_preview(example_export_name(self.name_template()))

    def set_enabled(self, enabled: bool) -> None:
        self._format.setEnabled(enabled)
        self._name_preset.setEnabled(enabled)
        self._name_template.setEnabled(enabled)
        self._export_button.setEnabled(enabled)
        self._export_all_button.setEnabled(enabled)
        self._copy_all_button.setEnabled(enabled)
        self._copy_unedited_button.setEnabled(enabled)

    def _set_template(self, template: str, *, select_matching_preset: bool = False) -> None:
        blocked = self._name_template.blockSignals(True)
        self._name_template.setText(template)
        self._name_template.blockSignals(blocked)
        if select_matching_preset:
            self._select_matching_preset(template)
        self.refresh_builtin_preview()

    def _select_matching_preset(self, template: str) -> None:
        blocked = self._name_preset.blockSignals(True)
        for index in range(self._name_preset.count()):
            key = self._name_preset.itemData(index)
            if key == _CUSTOM_PRESET:
                continue
            if NAME_PRESETS.get(key) == template:
                self._name_preset.setCurrentIndex(index)
                self._name_preset.blockSignals(blocked)
                return
        self._name_preset.setCurrentIndex(self._name_preset.count() - 1)
        self._name_preset.blockSignals(blocked)

    def _on_name_preset_changed(self) -> None:
        key = self._name_preset.currentData()
        if key == _CUSTOM_PRESET:
            return
        template = NAME_PRESETS.get(key, DEFAULT_TEMPLATE)
        self._set_template(template)
        save_name_template(template)
        self.name_template_changed.emit(template)

    def _on_name_template_changed(self) -> None:
        template = self.name_template()
        save_name_template(template)
        self._select_matching_preset(template)
        self.refresh_builtin_preview()
        self.name_template_changed.emit(template)

    def _on_export_clicked(self) -> None:
        if self._export_callback is not None:
            self._export_callback()

    def _on_export_all_clicked(self) -> None:
        if self._export_all_callback is not None:
            self._export_all_callback()

    def _on_copy_all_clicked(self) -> None:
        if self._copy_all_callback is not None:
            self._copy_all_callback()

    def _on_copy_unedited_clicked(self) -> None:
        if self._copy_unedited_callback is not None:
            self._copy_unedited_callback()
