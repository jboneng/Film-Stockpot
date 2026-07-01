"""Image IO helpers bridging files, NumPy arrays, and QImage."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage
import tifffile


def _read_file_array(file_path: Path) -> np.ndarray:
    """Read raw pixel data from an image file."""
    suffix = file_path.suffix.lower()
    if suffix in (".tif", ".tiff"):
        try:
            return tifffile.imread(file_path)
        except (ImportError, OSError, RuntimeError, ValueError):
            with Image.open(file_path) as image:
                image.load()
                return np.array(image)

    with Image.open(file_path) as image:
        image.load()
        return np.array(image)


def load_image_array(path: str | Path) -> np.ndarray:
    """Load an image as a contiguous float32 RGB array normalized to 0..1.

    Grayscale images are expanded to three channels and alpha is dropped so the
    processing pipeline always receives an ``(H, W, 3)`` array.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Image not found: {file_path}")

    array = _read_file_array(file_path)

    if array.dtype == np.uint16:
        data = array.astype(np.float32) / 65535.0
    elif array.dtype == np.uint8:
        data = array.astype(np.float32) / 255.0
    else:
        data = array.astype(np.float32)
        maximum = float(data.max()) if data.size else 0.0
        if maximum > 0.0:
            data = data / maximum

    if data.ndim == 2:
        data = np.stack([data] * 3, axis=-1)
    elif data.ndim == 3 and data.shape[2] >= 3:
        data = data[:, :, :3]
    else:
        raise ValueError(f"Unsupported image layout: shape={array.shape}, dtype={array.dtype}")

    return np.ascontiguousarray(data, dtype=np.float32)


def compute_histograms(rgb: np.ndarray, *, bins: int = 256) -> np.ndarray | None:
    """Return per-channel histogram counts for a float32 RGB image."""
    if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3:
        return None
    data = np.clip(rgb, 0.0, 1.0)
    hist = np.empty((3, bins), dtype=np.float64)
    for channel in range(3):
        counts, _ = np.histogram(data[:, :, channel], bins=bins, range=(0.0, 1.0))
        hist[channel] = counts
    return hist


def compute_luma_histogram(rgb: np.ndarray, *, bins: int = 256) -> np.ndarray | None:
    """Return a luminance histogram for a float32 RGB image."""
    if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3:
        return None
    weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    luma = np.sum(np.clip(rgb, 0.0, 1.0) * weights, axis=-1)
    counts, _ = np.histogram(luma.ravel(), bins=bins, range=(0.0, 1.0))
    return counts.astype(np.float64)


class PreviewImageBuffer:
    """Reusable uint8 buffer for preview display conversion."""

    __slots__ = ("_rgb", "_uint8", "_image")

    def __init__(self) -> None:
        self._rgb: np.ndarray | None = None
        self._uint8: np.ndarray | None = None
        self._image: QImage | None = None

    def to_qimage(self, rgb: np.ndarray) -> QImage:
        clipped = np.clip(rgb, 0.0, 1.0)
        height, width = clipped.shape[:2]
        if self._uint8 is None or self._uint8.shape != clipped.shape:
            self._uint8 = np.empty((height, width, 3), dtype=np.uint8)
        np.copyto(self._uint8, (clipped * 255.0 + 0.5).astype(np.uint8))
        return QImage(
            self._uint8.data,
            width,
            height,
            width * 3,
            QImage.Format.Format_RGB888,
        ).copy()


def array_to_qimage(rgb: np.ndarray) -> QImage:
    """Convert a float32 RGB array (0..1) to an 8-bit RGB888 QImage for display."""
    clipped = np.clip(rgb, 0.0, 1.0)
    as_uint8 = np.ascontiguousarray((clipped * 255.0 + 0.5).astype(np.uint8))
    height, width, _ = as_uint8.shape
    image = QImage(
        as_uint8.data,
        width,
        height,
        width * 3,
        QImage.Format.Format_RGB888,
    )
    return image.copy()


def save_image_array(path: str | Path, rgb: np.ndarray, *, bit_depth: int = 16) -> None:
    """Save a float32 RGB array (0..1) to disk."""
    file_path = Path(path)
    clipped = np.clip(rgb, 0.0, 1.0)

    if bit_depth == 16:
        data = np.ascontiguousarray((clipped * 65535.0 + 0.5).astype(np.uint16))
        tifffile.imwrite(file_path, data, photometric="rgb")
        return
    if bit_depth == 8:
        data = np.ascontiguousarray((clipped * 255.0 + 0.5).astype(np.uint8))
    else:
        raise ValueError(f"Unsupported bit depth: {bit_depth}")

    Image.fromarray(data).save(file_path, format="TIFF")
