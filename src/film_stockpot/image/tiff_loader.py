"""Load 16-bit TIFF images into QImage objects."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PyQt6.QtGui import QImage

_GRAYSCALE_16_MODES = frozenset({"I;16", "I;16B", "I;16L", "I;16N"})


def load_tiff_image(path: str | Path) -> QImage:
    """Load a TIFF file and return a display-ready QImage."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Image not found: {file_path}")

    with Image.open(file_path) as image:
        image.load()
        mode = image.mode
        array = np.array(image)

    if mode in _GRAYSCALE_16_MODES or (array.ndim == 2 and array.dtype == np.uint16):
        return _grayscale16_to_qimage(array)

    if array.ndim == 3 and array.shape[2] in (3, 4) and array.dtype == np.uint16:
        return _rgb16_to_qimage(array)

    if array.ndim == 2:
        return _grayscale16_to_qimage(array.astype(np.uint16))

    if array.ndim == 3 and array.shape[2] == 3:
        return _rgb8_to_qimage(array.astype(np.uint8))

    if array.ndim == 3 and array.shape[2] == 4:
        return _rgba8_to_qimage(array.astype(np.uint8))

    raise ValueError(f"Unsupported TIFF layout: mode={mode}, shape={array.shape}, dtype={array.dtype}")


def _grayscale16_to_qimage(array: np.ndarray) -> QImage:
    if array.ndim != 2:
        raise ValueError("Expected a 2D grayscale array")

    data = np.ascontiguousarray(array, dtype=np.uint16)
    height, width = data.shape
    bytes_per_line = width * 2
    image = QImage(
        data.data,
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_Grayscale16,
    )
    return image.copy()


def _rgb16_to_qimage(array: np.ndarray) -> QImage:
    rgb = array[:, :, :3]
    scaled = _scale_to_uint8(rgb)
    return _rgb8_to_qimage(scaled)


def _rgb8_to_qimage(array: np.ndarray) -> QImage:
    data = np.ascontiguousarray(array)
    height, width, _ = data.shape
    bytes_per_line = width * 3
    image = QImage(
        data.data,
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_RGB888,
    )
    return image.copy()


def _rgba8_to_qimage(array: np.ndarray) -> QImage:
    data = np.ascontiguousarray(array)
    height, width, _ = data.shape
    bytes_per_line = width * 4
    image = QImage(
        data.data,
        width,
        height,
        bytes_per_line,
        QImage.Format.Format_RGBA8888,
    )
    return image.copy()


def _scale_to_uint8(array: np.ndarray) -> np.ndarray:
    source = array.astype(np.float32)
    minimum = float(source.min())
    maximum = float(source.max())
    if maximum <= minimum:
        return np.zeros(source.shape, dtype=np.uint8)
    scaled = (source - minimum) / (maximum - minimum) * 255.0
    return scaled.astype(np.uint8)
