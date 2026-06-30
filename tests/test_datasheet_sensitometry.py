"""Tests for datasheet sensitometry derivation."""

from __future__ import annotations

from film_stockpot.datasheet.sensitometry import (
    derive_reciprocity_compensation,
    derive_sensitometry_from_curves,
    derive_tone_curves_from_characteristic,
    pgi_to_grain_strength,
    scalar_grain_value,
)

_SAMPLE_CHAR_CURVE = [
    {
        "type": "characteristic_curves",
        "series": [
            {
                "name": "red_sensitive",
                "points": [[-2.0, 0.2], [-1.0, 0.8], [0.0, 1.8], [1.0, 2.8]],
            },
            {
                "name": "green_sensitive",
                "points": [[-2.0, 0.15], [-1.0, 0.7], [0.0, 1.6], [1.0, 2.5]],
            },
            {
                "name": "blue_sensitive",
                "points": [[-2.0, 0.1], [-1.0, 0.5], [0.0, 1.2], [1.0, 2.0]],
            },
        ],
    }
]

_SAMPLE_MTF = [
    {
        "type": "mtf",
        "series": [
            {
                "name": "series_1",
                "points": [[0, 100], [20, 90], [40, 70], [60, 45], [100, 20]],
            }
        ],
    }
]


def test_scalar_grain_pgi() -> None:
    metric, val = scalar_grain_value({"print_grain_index": [37, 59]})
    assert metric == "PGI"
    assert val == 37.0


def test_pgi_to_grain_strength() -> None:
    assert pgi_to_grain_strength(37) == 0.35
    assert pgi_to_grain_strength(148) == 0.7


def test_derive_sensitometry() -> None:
    sens = derive_sensitometry_from_curves(_SAMPLE_CHAR_CURVE)
    assert sens is not None
    assert sens["d_min"] > 0
    assert sens["d_max"] > sens["d_min"]
    assert sens["curve_gamma"] > 0
    assert sens["curve_log_span"] > 0


def test_derive_tone_curves() -> None:
    master, rgb = derive_tone_curves_from_characteristic(_SAMPLE_CHAR_CURVE)
    assert master is not None
    assert rgb is not None
    assert "r" in rgb and "g" in rgb and "b" in rgb
    assert master[0][0] == 0
    assert master[-1][0] == 255


def test_reciprocity_no_correction_range() -> None:
    comp = derive_reciprocity_compensation(
        {"reciprocity_text": "no filter correction or exposure compensation required for exposures from 1/10,000 second to 1 second"}
    )
    assert comp is not None
    assert comp["no_correction_range_s"][1] == 1.0


def test_acutance_from_mtf() -> None:
    from film_stockpot.datasheet.sensitometry import derive_acutance_from_curves

    acu = derive_acutance_from_curves(_SAMPLE_MTF)
    assert acu is not None
    assert acu["mtf50_cycles_per_mm"] > 0
    assert acu["strength"] <= 0.10


def test_rejects_non_monotonic_rgb_curves() -> None:
    from film_stockpot.datasheet.sensitometry import is_valid_tone_curves_rgb

    assert not is_valid_tone_curves_rgb(
        {"r": [[0, 139], [128, 24], [255, 0]], "g": [[0, 0], [255, 255]], "b": [[0, 0], [255, 255]]}
    )
