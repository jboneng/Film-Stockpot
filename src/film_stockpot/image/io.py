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
