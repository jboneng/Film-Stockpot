"""Tests for TIFF loading."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from PyQt6.QtGui import QImage

from film_stockpot.image.tiff_loader import load_tiff_image


@pytest.fixture
def grayscale_tiff(tmp_path: Path) -> Path:
    array = np.linspace(0, 65535, 64 * 64, dtype=np.uint16).reshape(64, 64)
    path = tmp_path / "sample.tif"
    Image.fromarray(array).save(path)
    return path


def test_load_grayscale16_tiff(grayscale_tiff: Path) -> None:
    image = load_tiff_image(grayscale_tiff)

    assert isinstance(image, QImage)
    assert not image.isNull()
    assert image.width() == 64
    assert image.height() == 64
    assert image.format() == QImage.Format.Format_Grayscale16


def test_load_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_tiff_image("missing-file.tif")
