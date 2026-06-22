"""Background workers for off-thread image processing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap

from film_stockpot.image.io import array_to_qimage, load_image_array, save_image_array
from film_stockpot.image.pipeline import apply_film_preset
from film_stockpot.image.scanner import apply_scanner_adjustments


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

    def __init__(self, original_rgb: np.ndarray, preset_data: dict, base_data: dict | None = None) -> None:
        super().__init__()
        self._original_rgb = original_rgb
        self._preset_data = preset_data
        self._base_data = base_data
        self.signals = ApplyPresetSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            processed = apply_film_preset(self._original_rgb, self._preset_data, self._base_data)
        except Exception as error:  # noqa: BLE001 - surfaced to the UI
            self.signals.error.emit(str(error))
            return
        self.signals.finished.emit(processed)


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
            if self._preset is not None:
                rgb = apply_film_preset(rgb, self._preset, self._base)
            rgb = apply_scanner_adjustments(rgb, self._adjustments)
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

    def __init__(self, jobs: list[dict], output_dir: str, bit_depth: int = 16) -> None:
        super().__init__()
        self._jobs = jobs
        self._output_dir = Path(output_dir)
        self._bit_depth = bit_depth
        self._cancelled = False
        self.signals = BatchExportSignals()

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        total = len(self._jobs)
        exported = 0
        failed = 0
        errors: list[str] = []

        for index, job in enumerate(self._jobs):
            if self._cancelled:
                break

            source = Path(job["path"])
            self.signals.progress.emit(index, total, source.name)
            try:
                rgb = load_image_array(job["path"])
                preset = job.get("preset")
                if preset is not None:
                    rgb = apply_film_preset(rgb, preset, job.get("base"))
                rgb = apply_scanner_adjustments(rgb, job.get("adjustments"))

                target = self._output_dir / f"{source.stem}_export.tif"
                save_image_array(target, rgb, bit_depth=self._bit_depth)
                exported += 1
            except Exception as error:  # noqa: BLE001 - reported in summary
                failed += 1
                errors.append(f"{source.name}: {error}")

        self.signals.progress.emit(total, total, "")
        self.signals.finished.emit(exported, failed, self._cancelled, errors)
