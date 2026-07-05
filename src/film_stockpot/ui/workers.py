"""Background workers for off-thread image processing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap

from film_stockpot.export_engine import export_batch
from film_stockpot.export_naming import DEFAULT_TEMPLATE
from film_stockpot.image.crosstalk import crosstalk_strength_from_adjustments
from film_stockpot.image.io import array_to_qimage, load_image_array, save_image_array
from film_stockpot.image.pipeline import apply_film_preset
from film_stockpot.image.grading import apply_grading_after_scanner, apply_interactive_adjustments
from film_stockpot.image.print import apply_print_stage
from film_stockpot.image.restoration import DefectParams, generate_defect_mask, remove_defects
from film_stockpot.image.scanner import apply_scanner_adjustments
from film_stockpot.presets.loader import resolve_preset_data


class ThumbnailSignals(QObject):
    """Signals emitted by :class:`ThumbnailWorker`."""

    finished = pyqtSignal(str, QPixmap)


class ThumbnailWorker(QRunnable):
    """Load a downscaled thumbnail for the film strip."""

    def __init__(self, path: str, max_size: int) -> None:
        super().__init__()
        self._path = path
        self._max_size = max_size
        self.signals = ThumbnailSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            rgb = load_image_array(self._path)
            height, width = rgb.shape[:2]
            longest = max(height, width)
            if longest > self._max_size:
                step = int(np.ceil(longest / self._max_size))
                rgb = rgb[::step, ::step]
            image = array_to_qimage(rgb)
            pixmap = QPixmap.fromImage(image)
        except Exception:  # noqa: BLE001 - thumbnail failure is non-fatal
            pixmap = QPixmap()
        self.signals.finished.emit(self._path, pixmap)


class ApplyPresetSignals(QObject):
    """Signals emitted by :class:`ApplyPresetWorker`."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)


class ApplyPresetWorker(QRunnable):
    """Apply a film preset to an image on a background thread.

    Always runs against the original image passed in, so repeated applies with
    different presets never stack. Emits the processed float32 RGB array.
    """

    def __init__(
        self,
        original_rgb: np.ndarray,
        preset_data: dict,
        base_data: dict | None = None,
        *,
        crosstalk_strength: float = 0.0,
    ) -> None:
        super().__init__()
        self._original_rgb = original_rgb
        self._preset_data = preset_data
        self._base_data = base_data
        self._crosstalk_strength = crosstalk_strength
        self.signals = ApplyPresetSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            processed = apply_film_preset(
                self._original_rgb,
                self._preset_data,
                self._base_data,
                crosstalk_strength=self._crosstalk_strength,
            )
        except Exception as error:  # noqa: BLE001 - surfaced to the UI
            self.signals.error.emit(str(error))
            return
        self.signals.finished.emit(processed)


class PreviewAdjustSignals(QObject):
    """Signals emitted by :class:`PreviewAdjustWorker`."""

    finished = pyqtSignal(object, int)


class PreviewAdjustWorker(QRunnable):
    """Apply scanner + grading adjustments off the UI thread for live preview."""

    def __init__(
        self,
        film_base: np.ndarray,
        adjustments: dict | None,
        generation: int,
        *,
        preview_fast: bool = False,
    ) -> None:
        super().__init__()
        self._film_base = film_base
        self._adjustments = adjustments
        self._generation = generation
        self._preview_fast = preview_fast
        self.signals = PreviewAdjustSignals()

    @pyqtSlot()
    def run(self) -> None:
        result = apply_interactive_adjustments(
            self._film_base,
            self._adjustments,
            preview_fast=self._preview_fast,
        )
        self.signals.finished.emit(result, self._generation)


class ScannerAdjustSignals(QObject):
    """Signals emitted by :class:`ScannerAdjustWorker`."""

    finished = pyqtSignal(object, object, int)


class ScannerAdjustWorker(QRunnable):
    """Compute only the (heavier) scanner stage off the UI thread.

    Grading is applied separately on the main thread so it can use the GPU and
    the cached scanner output, keeping wheel/luminance edits instantaneous.
    """

    def __init__(
        self,
        film_base: np.ndarray,
        adjustments: dict | None,
        generation: int,
        *,
        preset: dict | None = None,
        flat_scan: np.ndarray | None = None,
        preview_fast: bool = False,
    ) -> None:
        super().__init__()
        self._film_base = film_base
        self._flat_scan = flat_scan
        self._adjustments = adjustments
        self._generation = generation
        self._preset = preset
        self._preview_fast = preview_fast
        self.signals = ScannerAdjustSignals()

    @pyqtSlot()
    def run(self) -> None:
        after_print = apply_print_stage(
            self._film_base,
            self._adjustments,
            self._preset,
            flat_scan=self._flat_scan,
        )
        result = apply_scanner_adjustments(
            after_print,
            self._adjustments,
            preview_fast=self._preview_fast,
        )
        self.signals.finished.emit(result, after_print, self._generation)


class GradingSignals(QObject):
    """Signals emitted by :class:`GradingWorker`."""

    finished = pyqtSignal(object, int)


class GradingWorker(QRunnable):
    """Apply wheel grading to a cached scanner result off the UI thread.

    Used as the CPU fallback when the GPU backend is unavailable. The shared
    ``grading_context`` caches the zone masks between frames; the main window
    serializes these workers so the context has a single owner at a time.
    """

    def __init__(
        self,
        scanner_result: np.ndarray,
        adjustments: dict | None,
        generation: int,
        *,
        grading_context: object | None = None,
    ) -> None:
        super().__init__()
        self._scanner_result = scanner_result
        self._adjustments = adjustments
        self._generation = generation
        self._grading_context = grading_context
        self.signals = GradingSignals()

    @pyqtSlot()
    def run(self) -> None:
        result = apply_grading_after_scanner(
            self._scanner_result,
            self._adjustments,
            grading_context=self._grading_context,
        )
        self.signals.finished.emit(result, self._generation)


class DefectMaskSignals(QObject):
    """Signals emitted by :class:`DefectMaskWorker`."""

    finished = pyqtSignal(object, int)
    error = pyqtSignal(str, int)


class DefectMaskWorker(QRunnable):
    """Detect dust / hair / scratch defects on a scan off the UI thread."""

    def __init__(self, rgb: np.ndarray, params: DefectParams, generation: int) -> None:
        super().__init__()
        self._rgb = rgb
        self._params = params
        self._generation = generation
        self.signals = DefectMaskSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            mask = generate_defect_mask(self._rgb, self._params)
        except Exception as error:  # noqa: BLE001 - surfaced to the UI
            self.signals.error.emit(str(error), self._generation)
            return
        self.signals.finished.emit(mask, self._generation)


class DefectRemoveSignals(QObject):
    """Signals emitted by :class:`DefectRemoveWorker`."""

    finished = pyqtSignal(object, int)
    error = pyqtSignal(str, int)


class DefectRemoveWorker(QRunnable):
    """Inpaint masked defects on a scan off the UI thread."""

    def __init__(
        self,
        rgb: np.ndarray,
        mask: np.ndarray,
        params: DefectParams,
        generation: int,
    ) -> None:
        super().__init__()
        self._rgb = rgb
        self._mask = mask
        self._params = params
        self._generation = generation
        self.signals = DefectRemoveSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            cleaned = remove_defects(self._rgb, self._mask, self._params)
        except Exception as error:  # noqa: BLE001 - surfaced to the UI
            self.signals.error.emit(str(error), self._generation)
            return
        self.signals.finished.emit(cleaned, self._generation)


class ExportOneSignals(QObject):
    """Signals emitted by :class:`ExportOneWorker`."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)


class ExportOneWorker(QRunnable):
    """Render one image at full resolution and save it on a background thread.

    The preview is rendered from a downscaled proxy for speed; export recomputes
    the full-resolution result here so the saved file is at native resolution.
    """

    def __init__(
        self,
        original_rgb: np.ndarray,
        preset: dict | None,
        base: dict | None,
        adjustments: dict | None,
        path: str,
        bit_depth: int = 16,
    ) -> None:
        super().__init__()
        self._original_rgb = original_rgb
        self._preset = preset
        self._base = base
        self._adjustments = adjustments
        self._path = path
        self._bit_depth = bit_depth
        self.signals = ExportOneSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            rgb = self._original_rgb
            preset = resolve_preset_data(self._preset)
            if preset is not None:
                rgb = apply_film_preset(
                    rgb,
                    preset,
                    self._base,
                    crosstalk_strength=crosstalk_strength_from_adjustments(self._adjustments),
                )
            rgb = apply_print_stage(rgb, self._adjustments, preset, flat_scan=self._original_rgb)
            rgb = apply_interactive_adjustments(
                rgb,
                self._adjustments,
                preset=preset,
                skip_print_stage=True,
            )
            save_image_array(self._path, rgb, bit_depth=self._bit_depth)
        except Exception as error:  # noqa: BLE001 - surfaced to the UI
            self.signals.error.emit(str(error))
            return
        self.signals.finished.emit(self._path)


class BatchExportSignals(QObject):
    """Signals emitted by :class:`BatchExportWorker`."""

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, int, bool, list)


class BatchExportWorker(QRunnable):
    """Render and save every job in a batch on a background thread.

    Each job is a dict with ``path``, ``preset``, ``base``, and ``adjustments``.
    The film preset (if any) and the scanner adjustments are applied before the
    image is written into ``output_dir`` as a 16-bit TIFF. Cancellation is
    cooperative: :meth:`cancel` is checked between jobs.
    """

    def __init__(
        self,
        jobs: list[dict],
        output_dir: str,
        *,
        bit_depth: int = 16,
        name_template: str | None = None,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._output_dir = Path(output_dir)
        self._bit_depth = bit_depth
        self._name_template = name_template
        self._cancelled = False
        self.signals = BatchExportSignals()

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        result = export_batch(
            self._jobs,
            output=self._output_dir,
            single_input=False,
            bit_depth=self._bit_depth,
            overwrite=True,
            name_template=self._name_template or DEFAULT_TEMPLATE,
            on_progress=lambda done, total, name: self.signals.progress.emit(done, total, name),
            is_cancelled=lambda: self._cancelled,
        )
        self.signals.finished.emit(result.exported, result.failed, result.cancelled, result.errors)
