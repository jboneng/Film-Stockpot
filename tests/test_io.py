"""Tests for image IO helpers."""

from pathlib import Path

import numpy as np
import pytest
import tifffile

from film_stockpot.image.io import load_image_array, save_image_array


def test_save_and_load_16bit_tiff(tmp_path: Path) -> None:
    rgb = np.linspace(0.0, 1.0, 32 * 32 * 3, dtype=np.float32).reshape(32, 32, 3)
    path = tmp_path / "export.tif"

    save_image_array(path, rgb, bit_depth=16)
    loaded = load_image_array(path)

    assert loaded.shape == rgb.shape
    assert np.allclose(loaded, rgb, atol=1.0 / 65535.0)


def test_save_invalid_bit_depth_raises(tmp_path: Path) -> None:
    rgb = np.zeros((4, 4, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        save_image_array(tmp_path / "bad.tif", rgb, bit_depth=12)


def test_saved_tiff_is_uint16(tmp_path: Path) -> None:
    rgb = np.full((8, 8, 3), 0.5, dtype=np.float32)
    path = tmp_path / "half.tif"
    save_image_array(path, rgb, bit_depth=16)

    data = tifffile.imread(path)
    assert data.dtype == np.uint16
