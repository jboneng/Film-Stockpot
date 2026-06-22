"""Tests for the per-image edit sidecar files."""

from pathlib import Path

from film_stockpot.sidecar import (
    delete_sidecar,
    has_sidecar,
    read_sidecar,
    sidecar_path,
    write_sidecar,
)

_PRESET = {"id": "kodak_portra_400", "name": "Portra 400", "pipeline": {"saturation": 1.1}}
_BASE = {"input_transform": {"gamma": 1.25}}
_ADJUSTMENTS = {"density": 5, "cyan": -3, "tone": "Hard"}


def _image(tmp_path: Path) -> Path:
    image = tmp_path / "frame_01.tiff"
    image.write_bytes(b"not-a-real-tiff")
    return image


def test_sidecar_path_appends_suffix(tmp_path: Path) -> None:
    image = tmp_path / "frame.tiff"
    assert sidecar_path(image) == tmp_path / "frame.tiff.stockpot.json"


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    image = _image(tmp_path)
    write_sidecar(image, preset=_PRESET, base=_BASE, adjustments=_ADJUSTMENTS)

    assert has_sidecar(image)
    data = read_sidecar(image)
    assert data is not None
    assert data["film_stock"] == _PRESET
    assert data["base_profile"] == _BASE
    assert data["adjustments"] == _ADJUSTMENTS
    assert data["source_image"] == "frame_01.tiff"
    assert data["schema_version"]


def test_write_embeds_full_preset_for_portability(tmp_path: Path) -> None:
    image = _image(tmp_path)
    write_sidecar(image, preset=_PRESET, base=_BASE, adjustments=_ADJUSTMENTS)
    data = read_sidecar(image)
    # The whole preset (not just an id) must be embedded so it renders on a
    # machine that lacks the film stock.
    assert data["film_stock"]["pipeline"] == _PRESET["pipeline"]


def test_no_preset_is_allowed(tmp_path: Path) -> None:
    image = _image(tmp_path)
    write_sidecar(image, preset=None, base=None, adjustments=_ADJUSTMENTS)
    data = read_sidecar(image)
    assert data["film_stock"] is None
    assert data["base_profile"] is None


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert read_sidecar(tmp_path / "missing.tiff") is None
    assert not has_sidecar(tmp_path / "missing.tiff")


def test_read_invalid_json_returns_none(tmp_path: Path) -> None:
    image = _image(tmp_path)
    sidecar_path(image).write_text("{ not json", encoding="utf-8")
    assert read_sidecar(image) is None


def test_delete_removes_file(tmp_path: Path) -> None:
    image = _image(tmp_path)
    write_sidecar(image, preset=_PRESET, base=_BASE, adjustments=_ADJUSTMENTS)
    assert delete_sidecar(image) is True
    assert not has_sidecar(image)
    assert delete_sidecar(image) is False
