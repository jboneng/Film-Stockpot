"""Export tab for saving processed images."""

from PyQt6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

FORMAT_TIFF_16BIT = "TIFF 16-bit"


class ExportPanel(QWidget):
    """Export format selection and save action."""

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

        self._export_button = QPushButton("Export Image", self)
        self._export_button.clicked.connect(self._on_export_clicked)
        layout.addWidget(self._export_button)

        self._export_all_button = QPushButton("Export All", self)
        self._export_all_button.setObjectName("primaryButton")
        self._export_all_button.clicked.connect(self._on_export_all_clicked)
        layout.addWidget(self._export_all_button)

        layout.addStretch(1)

        self._export_callback = None
        self._export_all_callback = None

    def set_export_callback(self, callback) -> None:
        self._export_callback = callback

    def set_export_all_callback(self, callback) -> None:
        self._export_all_callback = callback

    def selected_format(self) -> str:
        return self._format.currentText()

    def set_enabled(self, enabled: bool) -> None:
        self._format.setEnabled(enabled)
        self._export_button.setEnabled(enabled)
        self._export_all_button.setEnabled(enabled)

    def _on_export_clicked(self) -> None:
        if self._export_callback is not None:
            self._export_callback()

    def _on_export_all_clicked(self) -> None:
        if self._export_all_callback is not None:
            self._export_all_callback()
