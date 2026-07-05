"""Tests for the dust / hair / scratch defect detection and removal."""

import numpy as np

from film_stockpot.image.restoration import (
    DEFECT_NEUTRAL,
    INPAINT_NS,
    INPAINT_TELEA,
    DefectParams,
    generate_defect_mask,
    mask_coverage,
    remove_defects,
)


def _flat_scan(value: float = 0.5, size: int = 200) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.float32)


def _scan_with_defects(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    scan = _flat_scan()
    scan += rng.normal(0.0, 0.01, scan.shape).astype(np.float32)  # film-grain-like noise
    scan[50:53, 60:63] = 0.95  # bright dust speck
    scan[120:123, 20:23] = 0.05  # dark dust speck
    scan[90, 30:90] = 0.12  # thin dark scratch
    return np.clip(scan, 0.0, 1.0)


def test_detects_dust_specks() -> None:
    scan = _scan_with_defects()
    mask = generate_defect_mask(scan, DefectParams(detect_hair=False, detect_scratch=False))
    assert mask.dtype == np.bool_
    assert mask.shape == scan.shape[:2]
    assert mask[49:54, 59:64].any()
    assert mask[119:124, 19:24].any()


def test_detects_scratch_line() -> None:
    scan = _scan_with_defects()
    mask = generate_defect_mask(scan, DefectParams(detect_dust=False, detect_hair=False))
    assert mask[88:92, 30:90].sum() > 20


def test_clean_gradient_yields_near_empty_mask() -> None:
    rng = np.random.default_rng(1)
    ramp = np.tile(np.linspace(0.2, 0.8, 200, dtype=np.float32), (200, 1))
    scan = ramp[:, :, None].repeat(3, axis=2) + rng.normal(0.0, 0.01, (200, 200, 3)).astype(np.float32)
    scan = np.clip(scan, 0.0, 1.0)
    mask = generate_defect_mask(scan)
    assert mask_coverage(mask) < 0.01


def test_remove_defects_only_changes_masked_pixels() -> None:
    scan = _scan_with_defects()
    mask = generate_defect_mask(scan)
    assert mask.any()
    cleaned = remove_defects(scan, mask, DEFECT_NEUTRAL)
    assert cleaned.shape == scan.shape
    unmasked = ~mask
    assert np.array_equal(cleaned[unmasked], np.clip(scan, 0.0, 1.0)[unmasked])


def test_remove_defects_reduces_speck_contrast() -> None:
    scan = _scan_with_defects()
    mask = generate_defect_mask(scan, DefectParams(detect_hair=False, detect_scratch=False))
    cleaned = remove_defects(scan, mask, DEFECT_NEUTRAL)
    before = abs(float(scan[51, 61, 0]) - 0.5)
    after = abs(float(cleaned[51, 61, 0]) - 0.5)
    assert after < before


def test_remove_defects_with_empty_mask_is_identity() -> None:
    scan = _scan_with_defects()
    empty = np.zeros(scan.shape[:2], dtype=bool)
    cleaned = remove_defects(scan, empty, DEFECT_NEUTRAL)
    assert np.array_equal(cleaned, np.clip(scan, 0.0, 1.0))


def test_remove_defects_supports_navier_stokes() -> None:
    scan = _scan_with_defects()
    mask = generate_defect_mask(scan)
    cleaned = remove_defects(scan, mask, DefectParams(inpaint_method=INPAINT_NS))
    assert cleaned.shape == scan.shape
    assert cleaned.min() >= 0.0 and cleaned.max() <= 1.0


def test_disabled_detectors_produce_empty_mask() -> None:
    scan = _scan_with_defects()
    params = DefectParams(detect_dust=False, detect_hair=False, detect_scratch=False)
    mask = generate_defect_mask(scan, params)
    assert not mask.any()


def test_params_normalized_clamps_ranges() -> None:
    params = DefectParams(
        dust_sensitivity=5.0,
        hair_sensitivity=-1.0,
        min_size=-3,
        dilation=-1,
        inpaint_method="bogus",
        inpaint_radius=0,
    ).normalized()
    assert params.dust_sensitivity == 1.0
    assert params.hair_sensitivity == 0.0
    assert params.min_size == 0
    assert params.dilation == 0
    assert params.inpaint_method == INPAINT_TELEA
    assert params.inpaint_radius == 1


def test_generate_defect_mask_rejects_non_rgb() -> None:
    import pytest

    with pytest.raises(ValueError):
        generate_defect_mask(np.zeros((10, 10), dtype=np.float32))
