"""Primary application window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import Qt, QThreadPool, QTimer
from PyQt6.QtGui import QAction, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QGroupBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from film_stockpot import __version__
from film_stockpot.image.folder import list_tiff_files
from film_stockpot.image.io import array_to_qimage, load_image_array
from film_stockpot.image.scanner import NEUTRAL, apply_scanner_adjustments
from film_stockpot.presets.loader import load_base, load_grouped_presets
from film_stockpot.sidecar import (
    delete_sidecar,
    has_sidecar,
    read_sidecar,
    write_sidecar,
)
from film_stockpot.ui.icons import load_icon
from film_stockpot.ui.widgets.busy_overlay import BusyOverlay
from film_stockpot.ui.widgets.export_panel import FORMAT_TIFF_16BIT, ExportPanel
from film_stockpot.ui.widgets.film_strip import FilmStripPanel
from film_stockpot.ui.widgets.histogram import HistogramWidget
from film_stockpot.ui.widgets.image_viewer import ImageViewer
from film_stockpot.ui.widgets.scanner_panel import ScannerPanel
from film_stockpot.ui.workers import ApplyPresetWorker, BatchExportWorker, ExportOneWorker


class MainWindow(QMainWindow):
    """Top-level window for the Film Stockpot application."""

    _SAVE_TIFF_FILTER = "TIFF Images (*.tif *.tiff)"
    _PRESET_ROLE = Qt.ItemDataRole.UserRole
    _PREVIEW_MAX = 1800
    _LIVE_DEBOUNCE_MS = 15
    _PRESET_DEBOUNCE_MS = 200
    _SIDECAR_DEBOUNCE_MS = 500

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Film Stockpot {__version__}")

        self._original_rgb: np.ndarray | None = None
        self._preview_original: np.ndarray | None = None
        self._current_path: str | None = None
        self._adjust_base: np.ndarray | None = None
        self._preview_base: np.ndarray | None = None
        self._exporting_single = False
        self._apply_generation = 0
        self._active_base: dict | None = None
        self._external_preset_active = False
        self._restoring = False
        self._batch_worker: BatchExportWorker | None = None
        self._threadpool = QThreadPool.globalInstance()

        try:
            self._base = load_base()
        except (OSError, ValueError):
            self._base = None

        self._viewer = ImageViewer(self)
        self.setCentralWidget(self._viewer)

        self._busy = BusyOverlay(self)

        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._update_live)

        self._preset_timer = QTimer(self)
        self._preset_timer.setSingleShot(True)
        self._preset_timer.timeout.connect(self._apply_selected_preset)

        self._sidecar_timer = QTimer(self)
        self._sidecar_timer.setSingleShot(True)
        self._sidecar_timer.timeout.connect(self._save_sidecar)

        self._build_toolbar()
        self._build_film_strip()
        self._build_panel()
        self._populate_presets()
        self._update_actions_enabled()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        open_icon = load_icon("folder.svg", 20)
        self._open_action = QAction(open_icon, "Open Folder", self)
        self._open_action.setToolTip("Open a folder of TIFF images")
        self._open_action.triggered.connect(self._open_folder)
        toolbar.addAction(self._open_action)

        toolbar.addSeparator()

        self._folder_label = QLabel("No folder open", self)
        self._folder_label.setStyleSheet("color: #9a9aa0; padding-left: 4px;")
        toolbar.addWidget(self._folder_label)

    def _build_film_strip(self) -> None:
        self._film_strip = FilmStripPanel(self)
        self._film_strip.image_selected.connect(self._load_image_from_path)
        self._film_strip.open_folder_requested.connect(self._open_folder)
        self._film_strip.clear_sidecar_requested.connect(self._clear_sidecar)

        dock = QDockWidget("Film Strip", self)
        dock.setObjectName("film_strip_dock")
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(self._film_strip)
        dock.setMinimumWidth(210)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_panel(self) -> None:
        self._panel = ScannerPanel(self)
        self._panel.changed.connect(self._schedule_live_update)

        self._combo = QComboBox(self)

        film_group = QGroupBox("Film Stock", self)
        film_layout = QVBoxLayout(film_group)
        film_layout.addWidget(self._combo)

        self._reset_film_button = QPushButton("Reset Film Stock", self)
        self._reset_film_button.clicked.connect(self._reset_film_stock)
        film_layout.addWidget(self._reset_film_button)

        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)
        container_layout.addWidget(film_group)
        container_layout.addWidget(self._panel)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setMinimumWidth(280)

        self._export_panel = ExportPanel(self)
        self._export_panel.set_export_callback(self._export_image)
        self._export_panel.set_export_all_callback(self._export_all)

        tabs = QTabWidget(self)
        tabs.setMinimumWidth(280)
        tabs.addTab(scroll, "Adjustment")
        tabs.addTab(self._export_panel, "Export")

        self._histogram = HistogramWidget(self)

        panel_container = QWidget(self)
        panel_layout = QVBoxLayout(panel_container)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        panel_layout.addWidget(self._histogram)
        panel_layout.addWidget(tabs, 1)

        dock = QDockWidget("Panel", self)
        dock.setObjectName("panel_dock")
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        dock.setWidget(panel_container)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self._combo.currentIndexChanged.connect(self._schedule_preset_apply)

    def _populate_presets(self) -> None:
        model = QStandardItemModel(self)

        none_item = QStandardItem("None")
        none_item.setData(None, self._PRESET_ROLE)
        model.appendRow(none_item)

        try:
            groups = load_grouped_presets()
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Presets Unavailable", f"Could not load film presets.\n\n{error}")
            self._combo.blockSignals(True)
            self._combo.setModel(model)
            self._combo.setCurrentIndex(0)
            self._combo.blockSignals(False)
            return

        for group in groups:
            header = QStandardItem(group.label)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header_font = header.font()
            header_font.setBold(True)
            header_font.setItalic(True)
            header.setFont(header_font)
            model.appendRow(header)

            for preset in group.presets:
                item = QStandardItem(f"   {preset.name}")
                item.setData(preset.data, self._PRESET_ROLE)
                model.appendRow(item)

        self._combo.blockSignals(True)
        self._combo.setModel(model)
        self._combo.setCurrentIndex(0)
        self._combo.blockSignals(False)
        self._external_preset_active = False

    def _current_preset(self) -> dict | None:
        return self._combo.currentData(self._PRESET_ROLE)

    def _find_preset_row(self, preset_id: str) -> int | None:
        model = self._combo.model()
        for row in range(model.rowCount()):
            data = model.item(row).data(self._PRESET_ROLE)
            if isinstance(data, dict) and data.get("id") == preset_id:
                return row
        return None

    def _remove_external_item(self) -> None:
        if self._external_preset_active:
            self._combo.model().removeRow(1)
            self._external_preset_active = False

    def _select_preset_in_combo(self, preset: dict | None) -> None:
        """Point the combo at ``preset``, embedding it as an external item if
        the stock is not installed locally. Signals are blocked."""
        self._combo.blockSignals(True)
        self._remove_external_item()

        if preset is None:
            self._combo.setCurrentIndex(0)
        else:
            row = self._find_preset_row(preset.get("id"))
            if row is None:
                name = preset.get("name", "Film stock")
                item = QStandardItem(f"   {name}  (from sidecar)")
                item.setData(preset, self._PRESET_ROLE)
                self._combo.model().insertRow(1, item)
                self._external_preset_active = True
                row = 1
            self._combo.setCurrentIndex(row)

        self._combo.blockSignals(False)

    def _open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open Folder")
        if not folder:
            return

        try:
            paths = list_tiff_files(folder)
        except OSError as error:
            QMessageBox.critical(self, "Unable to Open Folder", f"Could not read the folder.\n\n{error}")
            return

        folder_path = Path(folder)
        self._folder_label.setText(folder_path.name or str(folder_path))
        self._folder_label.setToolTip(str(folder_path))
        self._film_strip.set_files(paths, folder=folder_path)
        for image_path in paths:
            if has_sidecar(image_path):
                self._film_strip.set_edited(str(image_path), True)

        if not paths:
            QMessageBox.information(
                self,
                "No Images Found",
                "No TIFF images were found in the selected folder.",
            )

    def _load_image_from_path(self, path: str) -> None:
        # Persist any pending edits for the image we are leaving, otherwise the
        # debounced save is cancelled below and those edits are lost.
        self._flush_pending_sidecar()

        try:
            self._original_rgb = load_image_array(path)
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self,
                "Unable to Open Image",
                f"Could not load the selected TIFF file.\n\n{error}",
            )
            return

        # The film pipeline is expensive at full resolution, so the interactive
        # preview is rendered from a downscaled proxy. Export recomputes from the
        # full-resolution original, so the saved file is unaffected.
        self._preview_original = self._downscale_for_preview(self._original_rgb)
        self._current_path = path
        self._preset_timer.stop()
        self._sidecar_timer.stop()

        sidecar = read_sidecar(path)
        if sidecar:
            self._restore_from_sidecar(sidecar)
        else:
            self._restore_defaults()
        self._update_actions_enabled()

    def _flush_pending_sidecar(self) -> None:
        """Immediately save a queued sidecar for the current image, if any.

        Called before switching images so a debounced edit is never dropped.
        """
        preset_pending = self._preset_timer.isActive()
        sidecar_pending = self._sidecar_timer.isActive()
        self._preset_timer.stop()
        self._sidecar_timer.stop()

        if self._current_path is None or not (preset_pending or sidecar_pending):
            return
        if preset_pending:
            self._active_base = self._base
        self._save_sidecar()

    def _restore_from_sidecar(self, sidecar: dict) -> None:
        preset = sidecar.get("film_stock")
        base = sidecar.get("base_profile") or self._base
        adjustments = sidecar.get("adjustments") or {}

        self._restoring = True
        self._select_preset_in_combo(preset)
        self._panel.set_settings({**NEUTRAL, **adjustments})
        self._restoring = False

        self._active_base = base
        self._render_preset(preset, base)

    def _restore_defaults(self) -> None:
        self._restoring = True
        self._select_preset_in_combo(None)
        self._panel.set_settings(dict(NEUTRAL))
        self._restoring = False

        self._active_base = self._base
        self._render_preset(None, self._base)

    def _schedule_preset_apply(self) -> None:
        self._preset_timer.start(self._PRESET_DEBOUNCE_MS)

    def _apply_selected_preset(self) -> None:
        if self._original_rgb is None:
            return
        self._active_base = self._base
        self._render_preset(self._current_preset(), self._base)
        self._schedule_sidecar_save()

    def _downscale_for_preview(self, rgb: np.ndarray) -> np.ndarray:
        """Return a copy no larger than ``_PREVIEW_MAX`` on its longest edge."""
        height, width = rgb.shape[:2]
        longest = max(height, width)
        if longest <= self._PREVIEW_MAX:
            return rgb
        step = int(np.ceil(longest / self._PREVIEW_MAX))
        return np.ascontiguousarray(rgb[::step, ::step])

    def _render_preset(self, preset: dict | None, base: dict | None) -> None:
        if self._preview_original is None:
            return

        self._apply_generation += 1
        generation = self._apply_generation

        if preset is None:
            self._set_base(self._preview_original)
            return

        self._set_busy(True, f"Applying {preset.get('name', 'preset')}...")
        worker = ApplyPresetWorker(self._preview_original, preset, base)
        worker.signals.finished.connect(
            lambda processed, gen=generation: self._on_apply_finished(processed, gen)
        )
        worker.signals.error.connect(
            lambda message, gen=generation: self._on_apply_error(message, gen)
        )
        self._threadpool.start(worker)

    def _on_apply_finished(self, processed: np.ndarray, generation: int) -> None:
        if generation != self._apply_generation:
            return
        self._set_base(processed)
        self._set_busy(False)

    def _on_apply_error(self, message: str, generation: int) -> None:
        if generation != self._apply_generation:
            return
        self._set_busy(False)
        QMessageBox.critical(self, "Unable to Apply Preset", f"Processing failed.\n\n{message}")

    def _reset_film_stock(self) -> None:
        if self._original_rgb is None:
            return
        if self._combo.currentIndex() == 0 and not self._external_preset_active:
            return
        self._select_preset_in_combo(None)
        self._apply_selected_preset()

    def _is_default_state(self) -> bool:
        if self._current_preset() is not None:
            return False
        settings = self._panel.settings()
        return all(settings.get(key) == value for key, value in NEUTRAL.items())

    def _schedule_sidecar_save(self) -> None:
        if self._restoring or self._current_path is None:
            return
        self._sidecar_timer.start(self._SIDECAR_DEBOUNCE_MS)

    def _save_sidecar(self) -> None:
        if self._current_path is None:
            return

        if self._is_default_state():
            if delete_sidecar(self._current_path):
                self._film_strip.set_edited(self._current_path, False)
            return

        try:
            write_sidecar(
                self._current_path,
                preset=self._current_preset(),
                base=self._active_base,
                adjustments=self._panel.settings(),
            )
        except OSError as error:
            QMessageBox.warning(self, "Unable to Save Sidecar", f"Could not write the sidecar file.\n\n{error}")
            return

        self._film_strip.set_edited(self._current_path, True)

    def _clear_sidecar(self, path: str) -> None:
        delete_sidecar(path)
        self._film_strip.set_edited(path, False)

        if path == self._current_path:
            self._sidecar_timer.stop()
            self._restore_defaults()

    def _set_base(self, image: np.ndarray) -> None:
        """Set the image the live adjustments operate on and refresh the preview."""
        self._adjust_base = image
        self._build_preview()
        self._update_live()

    def _build_preview(self) -> None:
        if self._adjust_base is None:
            self._preview_base = None
            return
        height, width = self._adjust_base.shape[:2]
        longest = max(height, width)
        if longest > self._PREVIEW_MAX:
            step = int(np.ceil(longest / self._PREVIEW_MAX))
            self._preview_base = np.ascontiguousarray(self._adjust_base[::step, ::step])
        else:
            self._preview_base = self._adjust_base

    def _schedule_live_update(self) -> None:
        self._live_timer.start(self._LIVE_DEBOUNCE_MS)
        self._schedule_sidecar_save()

    def _update_live(self) -> None:
        if self._preview_base is None:
            self._histogram.clear()
            return
        adjusted = apply_scanner_adjustments(self._preview_base, self._panel.settings())
        self._viewer.set_image(array_to_qimage(adjusted))
        self._histogram.set_image(adjusted)

    def _export_image(self) -> None:
        if self._original_rgb is None or self._exporting_single:
            return

        export_format = self._export_panel.selected_format()
        if export_format != FORMAT_TIFF_16BIT:
            QMessageBox.warning(self, "Unsupported Format", f"Export format not supported: {export_format}")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Image",
            self._default_export_name(),
            self._SAVE_TIFF_FILTER,
        )
        if not path:
            return

        if not path.lower().endswith((".tif", ".tiff")):
            path = f"{path}.tif"

        # Recompute at full resolution (the preview uses a downscaled proxy) on a
        # background thread so the saved file is native-resolution and the UI
        # stays responsive.
        base = self._active_base if self._active_base is not None else self._base
        worker = ExportOneWorker(
            self._original_rgb,
            self._current_preset(),
            base,
            self._panel.settings(),
            path,
        )
        worker.signals.finished.connect(self._on_export_one_finished)
        worker.signals.error.connect(self._on_export_one_error)
        self._exporting_single = True
        self._set_busy(True, "Exporting image...")
        self._threadpool.start(worker)

    def _on_export_one_finished(self, path: str) -> None:
        self._exporting_single = False
        self._set_busy(False)
        QMessageBox.information(self, "Export Complete", f"Image saved to:\n{path}")

    def _on_export_one_error(self, message: str) -> None:
        self._exporting_single = False
        self._set_busy(False)
        QMessageBox.critical(self, "Unable to Export Image", f"Could not save the image.\n\n{message}")

    def _default_export_name(self) -> str:
        if self._current_path:
            source = Path(self._current_path)
            return f"{source.stem}_export.tif"
        return "export.tif"

    def _export_all(self) -> None:
        if self._batch_worker is not None:
            return

        excluded = self._film_strip.excluded_paths()
        paths = [path for path in self._film_strip.paths() if path not in excluded]
        if not paths:
            if excluded:
                QMessageBox.information(
                    self,
                    "Nothing to Export",
                    "Every image in the film strip is excluded from batch export.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Nothing to Export",
                    "Open a folder with TIFF images before exporting.",
                )
            return

        export_format = self._export_panel.selected_format()
        if export_format != FORMAT_TIFF_16BIT:
            QMessageBox.warning(self, "Unsupported Format", f"Export format not supported: {export_format}")
            return

        output_dir = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not output_dir:
            return

        jobs = self._build_export_jobs(paths)
        total = len(jobs)

        dialog = QProgressDialog("Preparing export...", "Cancel", 0, total, self)
        dialog.setWindowTitle("Exporting Images")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)

        worker = BatchExportWorker(jobs, output_dir)
        self._batch_worker = worker
        dialog.canceled.connect(worker.cancel)
        worker.signals.progress.connect(
            lambda done, count, name: self._on_batch_progress(dialog, done, count, name)
        )
        worker.signals.finished.connect(
            lambda exported, failed, cancelled, errors: self._on_batch_finished(
                dialog, output_dir, exported, failed, cancelled, errors
            )
        )
        self._threadpool.start(worker)

    def _build_export_jobs(self, paths: list[str]) -> list[dict]:
        """Build per-image render jobs.

        Images with a sidecar use its embedded preset/base/adjustments; images
        without one inherit the current preview's film stock and adjustments.
        """
        current_preset = self._current_preset()
        current_base = self._active_base if self._active_base is not None else self._base
        current_adjustments = self._panel.settings()

        jobs: list[dict] = []
        for path in paths:
            sidecar = read_sidecar(path)
            if sidecar:
                jobs.append(
                    {
                        "path": path,
                        "preset": sidecar.get("film_stock"),
                        "base": sidecar.get("base_profile") or self._base,
                        "adjustments": sidecar.get("adjustments") or dict(NEUTRAL),
                    }
                )
            else:
                jobs.append(
                    {
                        "path": path,
                        "preset": current_preset,
                        "base": current_base,
                        "adjustments": current_adjustments,
                    }
                )
        return jobs

    def _on_batch_progress(self, dialog: QProgressDialog, done: int, total: int, name: str) -> None:
        dialog.setMaximum(total)
        dialog.setValue(done)
        if name:
            dialog.setLabelText(f"Exporting {done + 1} of {total}\n{name}")

    def _on_batch_finished(
        self,
        dialog: QProgressDialog,
        output_dir: str,
        exported: int,
        failed: int,
        cancelled: bool,
        errors: list,
    ) -> None:
        self._batch_worker = None
        dialog.reset()
        dialog.close()

        if cancelled:
            QMessageBox.information(
                self,
                "Export Cancelled",
                f"Export cancelled.\n\n{exported} image(s) were exported before cancelling.",
            )
            return

        if failed:
            detail = "\n".join(errors[:10])
            if len(errors) > 10:
                detail += f"\n... and {len(errors) - 10} more."
            QMessageBox.warning(
                self,
                "Export Finished With Errors",
                f"{exported} image(s) exported, {failed} failed.\n\n{detail}",
            )
            return

        QMessageBox.information(
            self,
            "Export Complete",
            f"{exported} image(s) exported to:\n{output_dir}",
        )

    def _set_busy(self, busy: bool, message: str = "") -> None:
        if busy:
            self._busy.set_message(message)
            self._busy.setGeometry(self.centralWidget().geometry())
            self._busy.show()
            self._busy.raise_()
        else:
            self._busy.hide()
        self._update_actions_enabled(busy)

    def _update_actions_enabled(self, busy: bool = False) -> None:
        has_image = self._original_rgb is not None
        self._open_action.setEnabled(not busy)
        self._film_strip.set_enabled(not busy)
        self._combo.setEnabled(not busy)
        self._reset_film_button.setEnabled(has_image and not busy)
        self._panel.setEnabled(has_image and not busy)
        self._export_panel.set_enabled(has_image and not busy)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._busy.isVisible():
            self._busy.setGeometry(self.centralWidget().geometry())

    def closeEvent(self, event) -> None:  # noqa: N802
        self._flush_pending_sidecar()
        super().closeEvent(event)
