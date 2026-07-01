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
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from film_stockpot import __version__
from film_stockpot.export_naming import ExportNamingContext, render_export_name
from film_stockpot.image.folder import list_tiff_files
from film_stockpot.image.io import PreviewImageBuffer, compute_histograms, compute_luma_histogram, load_image_array
from film_stockpot.image.grading import (
    GRADING_NEUTRAL,
    grading_is_neutral,
    has_grading_adjustments,
)
from film_stockpot.image.crosstalk import (
    CROSSTALK_DEFAULT,
    CROSSTALK_MAX,
    CROSSTALK_MIN,
    CROSSTALK_PRECISION,
    crosstalk_amount_to_slider,
    crosstalk_slider_to_amount,
    format_crosstalk_amount,
    normalize_crosstalk_amount,
    preset_has_crosstalk,
)
from film_stockpot.image.pipeline import apply_film_preset, apply_film_preset_from_pre_neutralize
from film_stockpot.image.scanner import NEUTRAL
from film_stockpot.presets.loader import load_base, load_grouped_presets, resolve_preset_data
from film_stockpot.sidecar import (
    delete_sidecar,
    has_sidecar,
    read_sidecar,
    write_sidecar,
)
from film_stockpot.ui.preview_stages import PreviewStage
from film_stockpot.ui.gpu import GpuGradingBackend
from film_stockpot.ui.preview_engine import PreviewEngine, downscale_for_preview
from film_stockpot.ui.preview_settings import (
    drag_preview_max_long_edge,
    gpu_acceleration_enabled,
    live_histogram_enabled,
    preview_max_long_edge,
    set_gpu_acceleration,
    show_perf_overlay,
)
from film_stockpot.ui.recent_folders import last_folder, load_recent_folders, remember_folder
from film_stockpot.ui.icons import load_icon
from film_stockpot.ui.widgets.busy_overlay import BusyOverlay
from film_stockpot.ui.widgets.export_panel import FORMAT_TIFF_16BIT, ExportPanel
from film_stockpot.ui.widgets.film_strip import FilmStripPanel
from film_stockpot.ui.widgets.histogram import HistogramWidget
from film_stockpot.ui.widgets.image_viewer import ImageViewer
from film_stockpot.ui.widgets.preview_mode_bar import PreviewModeBar
from film_stockpot.ui.widgets.grading_panel import GradingPanel
from film_stockpot.ui.widgets.scanner_panel import ScannerPanel
from film_stockpot.ui.workers import (
    ApplyPresetWorker,
    BatchExportWorker,
    ExportOneWorker,
    GradingWorker,
    ScannerAdjustWorker,
)


class MainWindow(QMainWindow):
    """Top-level window for the Film Stockpot application."""

    _SAVE_TIFF_FILTER = "TIFF Images (*.tif *.tiff)"
    _PRESET_ROLE = Qt.ItemDataRole.UserRole
    _LIVE_DEBOUNCE_MS = 15
    _WHEEL_DEBOUNCE_MS = 8
    _HIST_DEFER_MS = 150
    _PRESET_DEBOUNCE_MS = 200
    _CROSSTALK_DEBOUNCE_MS = 80
    _SIDECAR_DEBOUNCE_MS = 500

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Film Stockpot {__version__}")

        self._original_rgb: np.ndarray | None = None
        self._current_path: str | None = None
        self._adjust_base: np.ndarray | None = None
        self._exporting_single = False
        self._apply_generation = 0
        self._preview_generation = 0
        self._preview_interacting = False
        self._preview_interaction_depth = 0
        self._grading_worker_busy = False
        self._grading_worker_pending = False
        self._pending_hist_rgb: np.ndarray | None = None
        self._preview_engine = PreviewEngine(
            preview_max=preview_max_long_edge(),
            drag_preview_max=drag_preview_max_long_edge(),
            gpu_backend=GpuGradingBackend(),
        )
        self._preview_image = PreviewImageBuffer()
        self._active_base: dict | None = None
        self._external_preset_active = False
        self._restoring = False
        self._reset_crosstalk_on_apply = True
        self._batch_worker: BatchExportWorker | None = None
        self._threadpool = QThreadPool.globalInstance()

        try:
            self._base = load_base()
        except (OSError, ValueError):
            self._base = None

        self._viewer = ImageViewer(self)
        self._preview_bar = PreviewModeBar(self)
        self._preview_bar.changed.connect(self._refresh_preview_view)
        self._preview_bar.fit_requested.connect(self._viewer.fit_in_view)
        self._preview_bar.actual_size_requested.connect(self._viewer.zoom_to_actual_size)
        self._viewer.split_ratio_changed.connect(self._preview_bar.set_split_ratio)

        preview_container = QWidget(self)
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        preview_layout.addWidget(self._preview_bar)
        preview_layout.addWidget(self._viewer, 1)
        self.setCentralWidget(preview_container)

        self._busy = BusyOverlay(self)

        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.timeout.connect(self._update_live)

        self._preset_timer = QTimer(self)
        self._preset_timer.setSingleShot(True)
        self._preset_timer.timeout.connect(self._apply_selected_preset)

        self._crosstalk_timer = QTimer(self)
        self._crosstalk_timer.setSingleShot(True)
        self._crosstalk_timer.timeout.connect(self._apply_crosstalk_only)

        self._hist_timer = QTimer(self)
        self._hist_timer.setSingleShot(True)
        self._hist_timer.timeout.connect(self._apply_deferred_histogram)

        self._sidecar_timer = QTimer(self)
        self._sidecar_timer.setSingleShot(True)
        self._sidecar_timer.timeout.connect(self._save_sidecar)

        self._build_menu()
        self._build_toolbar()
        self._build_film_strip()
        self._build_panel()
        self._populate_presets()
        self._update_actions_enabled()
        self._try_restore_last_folder()

        self._perf_label = QLabel("", self)
        self.statusBar().addPermanentWidget(self._perf_label)
        self._update_perf_overlay()

    def _build_menu(self) -> None:
        view_menu = self.menuBar().addMenu("View")

        self._gpu_action = QAction("GPU acceleration", self)
        self._gpu_action.setCheckable(True)
        self._gpu_action.setChecked(gpu_acceleration_enabled())
        self._gpu_action.setToolTip("Use OpenGL for live wheel grading when available")
        self._gpu_action.triggered.connect(self._toggle_gpu_acceleration)
        view_menu.addAction(self._gpu_action)

        self._perf_action = QAction("Show preview timing", self)
        self._perf_action.setCheckable(True)
        self._perf_action.setChecked(show_perf_overlay())
        self._perf_action.triggered.connect(self._toggle_perf_overlay)
        view_menu.addAction(self._perf_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        open_icon = load_icon("folder.svg", 20)
        self._open_action = QAction(open_icon, "Open Folder", self)
        self._open_action.setToolTip("Open a folder of TIFF images")
        self._open_menu = QMenu(self)
        browse_action = self._open_menu.addAction("Browse for folder...")
        browse_action.triggered.connect(self._open_folder)
        self._open_menu.addSeparator()
        self._recent_menu = self._open_menu.addMenu("Recent folders")
        self._open_action.setMenu(self._open_menu)
        self._open_action.triggered.connect(self._open_folder)
        toolbar.addAction(self._open_action)
        self._refresh_recent_menu()

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
        self._panel.interaction_changed.connect(self._on_preview_interaction)

        self._combo = QComboBox(self)

        film_group = QGroupBox("Film Stock", self)
        film_layout = QVBoxLayout(film_group)
        film_layout.addWidget(self._combo)

        crosstalk_row = QVBoxLayout()
        crosstalk_row.setSpacing(2)
        crosstalk_header = QHBoxLayout()
        crosstalk_header.addWidget(QLabel("Crosstalk", self))
        crosstalk_header.addStretch(1)
        self._crosstalk_value = QLabel(format_crosstalk_amount(CROSSTALK_DEFAULT), self)
        self._crosstalk_value.setMinimumWidth(36)
        self._crosstalk_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        crosstalk_header.addWidget(self._crosstalk_value)
        crosstalk_row.addLayout(crosstalk_header)

        self._crosstalk_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._crosstalk_slider.setRange(
            int(CROSSTALK_MIN * CROSSTALK_PRECISION),
            int(CROSSTALK_MAX * CROSSTALK_PRECISION),
        )
        self._crosstalk_slider.setValue(crosstalk_amount_to_slider(CROSSTALK_DEFAULT))
        self._crosstalk_slider.setEnabled(False)
        self._crosstalk_slider.setToolTip(
            "Spectral crosstalk correction: 0 = off, 0.5 = default, 1 = full matrix"
        )
        self._crosstalk_slider.valueChanged.connect(self._on_crosstalk_changed)
        self._crosstalk_slider.sliderPressed.connect(self._begin_preview_interaction)
        self._crosstalk_slider.sliderReleased.connect(self._end_preview_interaction)
        crosstalk_row.addWidget(self._crosstalk_slider)
        film_layout.addLayout(crosstalk_row)

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
        self._export_panel.set_copy_all_callback(lambda: self._copy_settings_to_roll(only_unedited=False))
        self._export_panel.set_copy_unedited_callback(lambda: self._copy_settings_to_roll(only_unedited=True))
        self._export_panel.name_template_changed.connect(self._update_export_name_preview)

        self._grading_panel = GradingPanel(self)
        self._grading_panel.changed.connect(self._schedule_live_update)
        self._grading_panel.interaction_changed.connect(self._on_preview_interaction)

        grading_scroll = QScrollArea(self)
        grading_scroll.setWidgetResizable(True)
        grading_scroll.setWidget(self._grading_panel)
        grading_scroll.setMinimumWidth(280)

        tabs = QTabWidget(self)
        tabs.setMinimumWidth(280)
        tabs.addTab(scroll, "Adjustment")
        tabs.addTab(grading_scroll, "Grading")
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
        self._sync_crosstalk_controls()

    def _adjustment_settings(self) -> dict:
        return {
            **self._panel.settings(),
            **self._grading_panel.settings(),
            "crosstalk": crosstalk_slider_to_amount(self._crosstalk_slider.value()),
        }

    def _set_crosstalk_value(self, value: float) -> None:
        amount = normalize_crosstalk_amount(value)
        slider_value = crosstalk_amount_to_slider(amount)
        self._crosstalk_slider.blockSignals(True)
        self._crosstalk_slider.setValue(slider_value)
        self._crosstalk_slider.blockSignals(False)
        self._crosstalk_value.setText(format_crosstalk_amount(amount))

    def _sync_crosstalk_controls(self) -> None:
        preset = self._render_preset_data()
        enabled = preset is not None and preset_has_crosstalk(preset)
        self._crosstalk_slider.setEnabled(enabled)

    def _on_crosstalk_changed(self, value: int) -> None:
        self._crosstalk_value.setText(format_crosstalk_amount(crosstalk_slider_to_amount(value)))
        if self._current_preset() is not None:
            self._crosstalk_timer.start(self._CROSSTALK_DEBOUNCE_MS)
        self._schedule_sidecar_save()

    def _apply_crosstalk_only(self) -> None:
        if self._current_preset() is None or self._preview_engine.flat_original is None:
            return
        preset = self._render_preset_data()
        if preset is None or not preset_has_crosstalk(preset):
            return

        # Crosstalk edits must win over any in-flight preset worker.
        self._preset_timer.stop()
        self._apply_generation += 1

        base = self._active_base if self._active_base is not None else self._base
        strength = crosstalk_slider_to_amount(self._crosstalk_slider.value())
        self._refresh_base_graded_cache()
        flat = self._preview_engine.flat_original
        try:
            if self._preview_engine.pre_neutralize is not None:
                processed = apply_film_preset_from_pre_neutralize(
                    self._preview_engine.pre_neutralize,
                    flat,
                    preset,
                    base,
                    crosstalk_strength=strength,
                )
            else:
                processed = apply_film_preset(
                    flat,
                    preset,
                    base,
                    crosstalk_strength=strength,
                )
        except (OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Unable to Apply Crosstalk",
                f"Could not update the preview.\n\n{error}",
            )
            return
        self._set_base(processed)

    def _render_preset_data(self) -> dict | None:
        return resolve_preset_data(self._current_preset())

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
        start_dir = last_folder() or ""
        folder = QFileDialog.getExistingDirectory(self, "Open Folder", start_dir)
        if not folder:
            return
        self._open_folder_at(folder)

    def _open_folder_at(self, folder: str) -> None:
        try:
            paths = list_tiff_files(folder)
        except OSError as error:
            QMessageBox.critical(self, "Unable to Open Folder", f"Could not read the folder.\n\n{error}")
            return

        remember_folder(folder)
        self._refresh_recent_menu()

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

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = load_recent_folders()
        if not recent:
            empty = self._recent_menu.addAction("(none)")
            empty.setEnabled(False)
            return
        for folder in recent:
            path = Path(folder)
            label = path.name or str(path)
            action = self._recent_menu.addAction(label)
            action.setToolTip(folder)
            action.triggered.connect(lambda _checked=False, target=folder: self._open_folder_at(target))

    def _try_restore_last_folder(self) -> None:
        folder = last_folder()
        if folder and Path(folder).is_dir():
            self._open_folder_at(folder)

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
        flat = downscale_for_preview(self._original_rgb, preview_max_long_edge())
        self._preview_engine.clear()
        self._preview_engine.preview_max = preview_max_long_edge()
        self._preview_engine.drag_preview_max = drag_preview_max_long_edge()
        self._preview_engine.set_flat_original(flat, self._base)
        self._current_path = path
        self._adjust_base = None
        self._preview_generation += 1
        self._preset_timer.stop()
        self._crosstalk_timer.stop()
        self._sidecar_timer.stop()

        sidecar = read_sidecar(path)
        if sidecar:
            self._restore_from_sidecar(sidecar)
        else:
            self._restore_defaults()
        self._update_actions_enabled()
        self._update_export_name_preview()

    def _update_export_name_preview(self, _template: str | None = None) -> None:
        if self._current_path is None:
            self._export_panel.refresh_builtin_preview()
            return
        context = ExportNamingContext.from_job(
            {"path": self._current_path, "preset": self._current_preset()},
            index=self._film_strip.current_index(),
            total=max(1, len(self._film_strip.paths())),
        )
        stem = render_export_name(self._export_panel.name_template(), context)
        self._export_panel.set_name_preview(stem)

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
        self._grading_panel.set_settings(adjustments.get("grading"))
        self._set_crosstalk_value(adjustments.get("crosstalk", NEUTRAL["crosstalk"]))
        self._restoring = False
        self._sync_crosstalk_controls()

        self._active_base = base
        self._refresh_base_graded_cache()
        self._render_preset(
            preset,
            base,
            crosstalk_strength=crosstalk_slider_to_amount(self._crosstalk_slider.value()),
        )
        self._update_export_name_preview()

    def _restore_defaults(self) -> None:
        self._restoring = True
        self._select_preset_in_combo(None)
        self._panel.set_settings(dict(NEUTRAL))
        self._grading_panel.set_settings(GRADING_NEUTRAL)
        self._set_crosstalk_value(NEUTRAL["crosstalk"])
        self._restoring = False
        self._sync_crosstalk_controls()

        self._active_base = self._base
        self._render_preset(None, self._base)
        self._update_export_name_preview()

    def _schedule_preset_apply(self, *, reset_crosstalk: bool = True) -> None:
        self._reset_crosstalk_on_apply = reset_crosstalk
        self._preset_timer.start(self._PRESET_DEBOUNCE_MS)

    def _apply_selected_preset(self) -> None:
        if self._original_rgb is None:
            return
        self._crosstalk_timer.stop()
        reset_crosstalk = self._reset_crosstalk_on_apply
        self._reset_crosstalk_on_apply = True
        if reset_crosstalk and not self._restoring:
            self._set_crosstalk_value(NEUTRAL["crosstalk"])
        self._sync_crosstalk_controls()
        self._active_base = self._base
        self._refresh_base_graded_cache()
        self._render_preset(
            self._current_preset(),
            self._base,
            show_busy=reset_crosstalk,
            crosstalk_strength=crosstalk_slider_to_amount(self._crosstalk_slider.value()),
        )
        self._schedule_sidecar_save()
        self._update_export_name_preview()

    def _downscale_for_preview(self, rgb: np.ndarray) -> np.ndarray:
        """Return a copy no larger than the configured preview max on its longest edge."""
        return downscale_for_preview(rgb, preview_max_long_edge())

    def _render_preset(
        self,
        preset: dict | None,
        base: dict | None,
        *,
        show_busy: bool = True,
        crosstalk_strength: float | None = None,
    ) -> None:
        if self._preview_engine.flat_original is None:
            return

        resolved = resolve_preset_data(preset)
        self._apply_generation += 1
        generation = self._apply_generation

        if resolved is None:
            self._set_base(self._preview_engine.flat_original)
            return

        if show_busy:
            self._set_busy(True, f"Applying {resolved.get('name', 'preset')}...")
        strength = (
            crosstalk_strength
            if crosstalk_strength is not None
            else crosstalk_slider_to_amount(self._crosstalk_slider.value())
        )
        worker = ApplyPresetWorker(
            self._preview_engine.flat_original,
            resolved,
            base,
            crosstalk_strength=strength,
        )
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
        if self._busy.isVisible():
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
        settings = self._adjustment_settings()
        scanner_defaults = all(
            abs(float(settings.get(key, 0)) - float(value)) < 1e-6 if key == "crosstalk" else settings.get(key) == value
            for key, value in NEUTRAL.items()
        )
        return scanner_defaults and grading_is_neutral(settings.get("grading"))

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
                adjustments=self._adjustment_settings(),
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
        base = self._active_base if self._active_base is not None else self._base
        self._preview_engine.set_film_base(image, base)
        self._schedule_live_update(immediate=True)

    def _refresh_base_graded_cache(self) -> None:
        base = self._active_base if self._active_base is not None else self._base
        self._preview_engine.rebuild_flat_cache(base)

    def _stage_array(self, stage: PreviewStage, *, preview_fast: bool = False) -> np.ndarray | None:
        return self._preview_engine.stage_array(
            stage,
            self._adjustment_settings(),
            preview_fast=preview_fast,
        )

    def _refresh_preview_view(self) -> None:
        preview_fast = self._preview_interacting
        if self._preview_bar.split_enabled():
            before = self._stage_array(self._preview_bar.before_stage(), preview_fast=preview_fast)
            after = self._stage_array(self._preview_bar.after_stage(), preview_fast=preview_fast)
            if before is None or after is None:
                self._viewer.clear_image()
                return
            self._viewer.set_split_images(
                self._preview_image.to_qimage(before),
                self._preview_image.to_qimage(after),
                ratio=self._preview_bar.split_ratio(),
            )
            return

        image = self._stage_array(self._preview_bar.view_stage(), preview_fast=preview_fast)
        if image is None:
            self._viewer.clear_image()
            return
        self._viewer.set_single_image(self._preview_image.to_qimage(image))

    def _live_debounce_ms(self) -> int:
        return self._WHEEL_DEBOUNCE_MS if self._preview_interacting else self._LIVE_DEBOUNCE_MS

    def _schedule_live_update(self, *, immediate: bool = False) -> None:
        if immediate:
            self._live_timer.stop()
            self._update_live()
        else:
            self._live_timer.start(self._live_debounce_ms())
        self._schedule_sidecar_save()

    def _begin_preview_interaction(self) -> None:
        if self._preview_interaction_depth == 0:
            self._preview_interacting = True
        self._preview_interaction_depth += 1

    def _end_preview_interaction(self) -> None:
        self._preview_interaction_depth = max(0, self._preview_interaction_depth - 1)
        if self._preview_interaction_depth == 0 and self._preview_interacting:
            self._preview_interacting = False
            self._grading_worker_pending = False
            self._preview_engine.invalidate_adjustment_cache()
            self._hist_timer.stop()
            self._schedule_live_update(immediate=True)

    def _on_preview_interaction(self, active: bool) -> None:
        if active:
            self._begin_preview_interaction()
        else:
            self._end_preview_interaction()

    def _update_live(self) -> None:
        """Refresh the live preview using a two-stage pipeline.

        The heavy scanner stage runs on a background thread and is cached, so
        it is only recomputed when a scanner control actually changes. The
        grading stage (the color wheels, luminance, blending and balance) is
        applied on top of that cached result -- on the GPU when available, which
        makes wheel edits feel instantaneous, or on a serialized background
        worker as a CPU fallback.
        """
        if self._preview_engine.film_base is None:
            self._histogram.clear()
            self._refresh_preview_view()
            self._update_perf_overlay()
            return

        settings = self._adjustment_settings()
        preview_fast = self._preview_interacting
        engine = self._preview_engine

        if engine.cache_hit(settings, preview_fast=preview_fast):
            self._on_preview_ready(engine.render_full(settings, preview_fast=preview_fast))
            return

        if engine.scanner_cached(settings, preview_fast=preview_fast):
            self._render_grading_stage(settings, preview_fast)
            return

        # Scanner settings changed: recompute that (expensive) stage off-thread.
        self._preview_generation += 1
        generation = self._preview_generation
        film_base = engine.effective_film_base(preview_fast=preview_fast)
        if film_base is None:
            return
        worker = ScannerAdjustWorker(
            film_base,
            settings,
            generation,
            preview_fast=preview_fast,
        )
        worker.signals.finished.connect(
            lambda result, gen=generation: self._on_scanner_ready(
                result,
                gen,
                settings,
                preview_fast,
            )
        )
        self._threadpool.start(worker)

    def _on_scanner_ready(
        self,
        scanner_result: np.ndarray,
        generation: int,
        settings: dict,
        preview_fast: bool,
    ) -> None:
        if generation != self._preview_generation:
            return
        self._preview_engine.store_scanner_result(settings, scanner_result, preview_fast=preview_fast)
        self._render_grading_stage(settings, preview_fast)

    def _gpu_ready(self) -> bool:
        gpu = self._preview_engine.gpu_backend
        return gpu is not None and getattr(gpu, "enabled", False)

    def _render_grading_stage(self, settings: dict, preview_fast: bool) -> None:
        """Apply grading on top of the cached scanner result and display it."""
        engine = self._preview_engine

        if self._gpu_ready() or not has_grading_adjustments(settings.get("grading")):
            # GPU grading (or a no-op) is fast enough to run synchronously and
            # give immediate feedback.
            self._on_preview_ready(engine.render_full(settings, preview_fast=preview_fast))
            return

        # CPU fallback: grade off-thread, but serialize so the shared grading
        # context (mask cache) only has one owner at a time. Newer requests
        # coalesce into a single pending render that re-reads current state.
        if self._grading_worker_busy:
            self._grading_worker_pending = True
            return

        scanner_result = engine.scanner_result()
        if scanner_result is None:
            self._on_preview_ready(engine.render_full(settings, preview_fast=preview_fast))
            return

        self._grading_worker_busy = True
        self._preview_generation += 1
        generation = self._preview_generation
        worker = GradingWorker(
            scanner_result,
            settings,
            generation,
            grading_context=engine.grading_context(),
        )
        worker.signals.finished.connect(
            lambda result, gen=generation: self._on_grading_ready(
                result,
                gen,
                settings,
                preview_fast,
            )
        )
        self._threadpool.start(worker)

    def _on_grading_ready(
        self,
        result: np.ndarray,
        generation: int,
        settings: dict,
        preview_fast: bool,
    ) -> None:
        self._grading_worker_busy = False
        if generation == self._preview_generation:
            self._preview_engine.store_rendered_full(settings, result, preview_fast=preview_fast)
            self._on_preview_ready(result)

        if self._grading_worker_pending:
            self._grading_worker_pending = False
            self._update_live()

    def _on_preview_ready(self, full: np.ndarray | None) -> None:
        if full is None:
            self._histogram.clear()
            self._grading_panel.set_luma_histogram(None)
        else:
            self._schedule_histogram(full)
            self._grading_panel.set_luma_histogram(compute_luma_histogram(full))
        self._refresh_preview_view()
        self._update_perf_overlay()

    def _schedule_histogram(self, full: np.ndarray) -> None:
        if not live_histogram_enabled():
            return
        self._pending_hist_rgb = full
        if self._preview_interacting:
            self._hist_timer.start(self._HIST_DEFER_MS)
            return
        self._apply_deferred_histogram()

    def _apply_deferred_histogram(self) -> None:
        if self._pending_hist_rgb is None:
            return
        hist = compute_histograms(self._pending_hist_rgb)
        self._histogram.set_histograms(hist)

    def _toggle_gpu_acceleration(self, checked: bool) -> None:
        set_gpu_acceleration(checked)
        self._preview_engine.invalidate_adjustment_cache()
        self._schedule_live_update(immediate=True)

    def _toggle_perf_overlay(self, checked: bool) -> None:
        from film_stockpot.ui.preview_settings import set_show_perf_overlay

        set_show_perf_overlay(checked)
        self._update_perf_overlay()

    def _update_perf_overlay(self) -> None:
        if not show_perf_overlay():
            self._perf_label.clear()
            return
        timings = self._preview_engine.last_timings
        gpu = "GPU" if timings.used_gpu else "CPU"
        self._perf_label.setText(
            f"Preview {timings.total_ms:.0f} ms "
            f"(scanner {timings.scanner_ms:.0f}, grading {timings.grading_ms:.0f}, {gpu})"
        )

    def _copy_settings_to_roll(self, *, only_unedited: bool) -> None:
        paths = self._film_strip.paths()
        if not paths or self._original_rgb is None:
            QMessageBox.information(
                self,
                "Nothing to Copy",
                "Open a folder and select settings before copying to the roll.",
            )
            return

        preset = self._current_preset()
        base = self._active_base if self._active_base is not None else self._base
        adjustments = self._adjustment_settings()
        targets = [path for path in paths if not only_unedited or not has_sidecar(path)]
        if not targets:
            QMessageBox.information(
                self,
                "Nothing to Copy",
                "Every image in the roll already has a sidecar file.",
            )
            return

        copied = 0
        errors: list[str] = []
        for path in targets:
            try:
                write_sidecar(path, preset=preset, base=base, adjustments=adjustments)
                self._film_strip.set_edited(path, True)
                copied += 1
            except OSError as error:
                errors.append(f"{Path(path).name}: {error}")

        if errors:
            detail = "\n".join(errors[:10])
            if len(errors) > 10:
                detail += f"\n... and {len(errors) - 10} more."
            QMessageBox.warning(
                self,
                "Copy Finished With Errors",
                f"Copied settings to {copied} image(s), {len(errors)} failed.\n\n{detail}",
            )
            return

        scope = "unedited image(s)" if only_unedited else "image(s)"
        QMessageBox.information(
            self,
            "Settings Copied",
            f"Current settings copied to {copied} {scope} in the roll.",
        )

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
            self._adjustment_settings(),
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
        if not self._current_path:
            return "export.tif"
        context = ExportNamingContext.from_job(
            {"path": self._current_path, "preset": self._current_preset()},
            index=self._film_strip.current_index(),
            total=max(1, len(self._film_strip.paths())),
        )
        stem = render_export_name(self._export_panel.name_template(), context)
        return f"{stem}.tif"

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

        worker = BatchExportWorker(
            jobs,
            output_dir,
            name_template=self._export_panel.name_template(),
        )
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
        from film_stockpot.export_engine import build_export_jobs

        jobs, _warnings = build_export_jobs(
            paths,
            fallback_preset=self._current_preset(),
            fallback_base=self._active_base if self._active_base is not None else self._base,
            fallback_adjustments=self._adjustment_settings(),
            sidecar_default_base=self._base,
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
        self._preview_bar.setEnabled(not busy)

    def _update_actions_enabled(self, busy: bool = False) -> None:
        has_image = self._original_rgb is not None
        self._open_action.setEnabled(not busy)
        self._film_strip.set_enabled(not busy)
        self._combo.setEnabled(not busy)
        preset = self._render_preset_data()
        crosstalk_enabled = (
            has_image
            and not busy
            and preset is not None
            and preset_has_crosstalk(preset)
        )
        self._crosstalk_slider.setEnabled(crosstalk_enabled)
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
