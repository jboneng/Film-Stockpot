"""Tests for datasheet PDF extraction helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "extract_datasheets.py"


def _load_module():
    name = "extract_datasheets"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_pgi_from_kodak_text() -> None:
    mod = _load_module()
    text = "Print Grain Index 37 59 89\nPrint Grain Index Less than 25 Less than 25 36"
    values = mod._parse_pgi_values(text)
    assert values[:3] == [37, 59, 89]


def test_parse_scalars_includes_scanner_settings() -> None:
    mod = _load_module()
    text = """
    Tone adjustment = All Hard
    Saturation = +2
    C= -2, M= 0, Y= 0
    Print Grain Index 44 64
    """
    scalars = mod._parse_scalars(text)
    assert scalars["print_grain_index"]
    assert scalars["scanner_settings"]["tone_adjustment"] == "All Hard"
    assert scalars["scanner_settings"]["saturation"] == "+2"


def test_detect_sections() -> None:
    mod = _load_module()
    text = "CURVES Characteristic Curves Spectral-Dye-Density Curves MTF"
    sections = mod._detect_sections(text)
    assert "characteristic_curves" in sections
    assert "spectral_dye_density" in sections
    assert "mtf" in sections


def test_guess_product_name_portra() -> None:
    mod = _load_module()
    text = "KODAK PROFESSIONAL PORTRA 400 Film is the world's finest grain"
    assert mod._guess_product_name(text, "e4050.pdf") == "KODAK PROFESSIONAL PORTRA 400 Film"


def _load_curves_module():
    path = ROOT / "scripts" / "datasheet_curves.py"
    name = "datasheet_curves"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_classify_axis_wavelength() -> None:
    mod = _load_curves_module()
    ticks = [
        mod.TickLabel(value=400, x=100, y=500),
        mod.TickLabel(value=500, x=150, y=500),
        mod.TickLabel(value=600, x=200, y=500),
        mod.TickLabel(value=700, x=250, y=500),
    ]
    assert mod._classify_axis_ticks(ticks) == "spectral_dye_density"


def test_classify_axis_mtf() -> None:
    mod = _load_curves_module()
    ticks = [
        mod.TickLabel(value=0, x=100, y=500),
        mod.TickLabel(value=10, x=150, y=500),
        mod.TickLabel(value=50, x=200, y=500),
        mod.TickLabel(value=100, x=250, y=500),
    ]
    assert mod._classify_axis_ticks(ticks) == "mtf"


def test_series_matches_type_mtf_rejects_negative_x() -> None:
    mod = _load_curves_module()
    points = [(-1.5, 0.5), (0.0, 0.8), (50.0, 0.4)]
    assert not mod._series_matches_type(points, "mtf")
    assert mod._series_matches_type([(0.0, 0.8), (50.0, 0.4), (100.0, 0.2)], "mtf")
