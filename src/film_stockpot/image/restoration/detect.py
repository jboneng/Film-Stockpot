"""Classical-CV defect detection for film scans.

Detects dust specks, hair/fibers, and scratches on a scan and fuses them into a
single binary repair mask. The design goal (per the project handover) is to flag
as few pixels as possible while preserving film grain, texture, and real edges --
the mask quality matters more than the inpainting that follows.

All detectors operate on the scan luma and are polarity-agnostic (they respond to
both bright and dark defects), so they work on positives and negatives alike.
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage.filters import sato
from skimage.measure import label, regionprops
from skimage.morphology import closing, dilation, disk

from film_stockpot.image.restoration.params import DEFECT_NEUTRAL, DefectParams

_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def generate_defect_mask(rgb: np.ndarray, params: DefectParams = DEFECT_NEUTRAL) -> np.ndarray:
    """Return a boolean ``(H, W)`` repair mask for a float32 RGB scan (0..1)."""
    params = params.normalized()
    if rgb is None or rgb.ndim != 3 or rgb.shape[2] < 3:
        raise ValueError("generate_defect_mask expects an (H, W, 3) RGB array")

    luma8, luma = _to_luma(rgb)
    height, width = luma.shape
    mask = np.zeros((height, width), dtype=bool)

    if params.detect_dust:
        mask |= _detect_dust(luma8, params.dust_sensitivity)
    if params.detect_hair:
        mask |= _detect_hair(luma, params.hair_sensitivity)
    if params.detect_scratch:
        mask |= _detect_scratch(luma8, params.scratch_sensitivity)

    return _refine(mask, params.min_size, params.dilation)


def mask_coverage(mask: np.ndarray | None) -> float:
    """Fraction of pixels flagged in ``mask`` (0..1)."""
    if mask is None or mask.size == 0:
        return 0.0
    return float(np.count_nonzero(mask)) / float(mask.size)


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------


def _to_luma(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    luma = np.clip(rgb.astype(np.float32), 0.0, 1.0) @ _LUMA_WEIGHTS
    luma8 = (luma * 255.0 + 0.5).astype(np.uint8)
    return luma8, luma.astype(np.float32)


# ---------------------------------------------------------------------------
# Dust: small isolated particles via white/black top-hat morphology.
# Top-hat responds only to features smaller than the structuring element, so
# large real structures (edges, subjects) are inherently rejected.
# ---------------------------------------------------------------------------


def _detect_dust(luma8: np.ndarray, sensitivity: float) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    white = cv2.morphologyEx(luma8, cv2.MORPH_TOPHAT, kernel)
    black = cv2.morphologyEx(luma8, cv2.MORPH_BLACKHAT, kernel)
    response = np.maximum(white, black).astype(np.float32)
    threshold = _adaptive_threshold(response, sensitivity, floor=8.0)
    return response > threshold


# ---------------------------------------------------------------------------
# Hair / fibers: thin curved ridges via the Sato line filter.
# ---------------------------------------------------------------------------


def _detect_hair(luma: np.ndarray, sensitivity: float) -> np.ndarray:
    sigmas = range(1, 4)
    bright = sato(luma, sigmas=sigmas, black_ridges=False)
    dark = sato(luma, sigmas=sigmas, black_ridges=True)
    response = _suppress_border(np.maximum(bright, dark).astype(np.float32))
    # The Sato response scales with local contrast; a sensitivity-driven absolute
    # floor keeps flat/low-texture inputs from tripping on ridge-filter noise.
    floor = 0.01 + 0.09 * (1.0 - float(sensitivity))
    threshold = _adaptive_threshold(response, sensitivity, floor=floor)
    mask = response > threshold
    return _keep_elongated(mask, min_major=8.0, min_ratio=2.5)


# ---------------------------------------------------------------------------
# Scratches: long straight lines via orientation-selective morphology.
# ---------------------------------------------------------------------------


def _detect_scratch(luma8: np.ndarray, sensitivity: float) -> np.ndarray:
    length = _odd(max(9, int(round(max(luma8.shape) / 120.0))))
    bright = _line_response(luma8, length)
    dark = _line_response(255 - luma8, length)
    response = _suppress_border(np.maximum(bright, dark))
    threshold = _adaptive_threshold(response, sensitivity, floor=10.0)
    mask = response > threshold
    return _keep_elongated(mask, min_major=float(length), min_ratio=3.0)


def _line_response(img: np.ndarray, length: int) -> np.ndarray:
    """Orientation-selective bright-line response.

    A thin line aligned with an orientation survives an opening along that
    orientation but is removed by the perpendicular opening, so the difference
    between the two openings isolates thin aligned structures.
    """
    opens = {angle: cv2.morphologyEx(img, cv2.MORPH_OPEN, _line_kernel(length, angle)) for angle in (0, 45, 90, 135)}
    response = np.zeros(img.shape, dtype=np.float32)
    for angle_a, angle_b in ((0, 90), (45, 135)):
        diff = opens[angle_a].astype(np.float32) - opens[angle_b].astype(np.float32)
        response = np.maximum(response, np.abs(diff))
    return np.clip(response, 0.0, 255.0)


def _line_kernel(length: int, angle: int) -> np.ndarray:
    kernel = np.zeros((length, length), dtype=np.uint8)
    center = length // 2
    if angle == 0:
        kernel[center, :] = 1
    elif angle == 90:
        kernel[:, center] = 1
    elif angle == 135:
        np.fill_diagonal(kernel, 1)
    else:  # 45 degrees
        np.fill_diagonal(np.fliplr(kernel), 1)
    return kernel


# ---------------------------------------------------------------------------
# Component filtering and refinement
# ---------------------------------------------------------------------------


def _keep_elongated(mask: np.ndarray, *, min_major: float, min_ratio: float) -> np.ndarray:
    """Keep only line-like connected components (reject compact blobs)."""
    if not mask.any():
        return mask
    labelled = label(mask)
    out = np.zeros_like(mask)
    for region in regionprops(labelled):
        major = float(region.axis_major_length)
        minor = max(float(region.axis_minor_length), 1e-6)
        if major >= min_major and (major / minor) >= min_ratio:
            coords = region.coords
            out[coords[:, 0], coords[:, 1]] = True
    return out


def _remove_small(mask: np.ndarray, min_size: int) -> np.ndarray:
    """Drop connected components with fewer than ``min_size`` pixels."""
    if min_size <= 1 or not mask.any():
        return mask
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    for index in range(1, count):
        keep[index] = stats[index, cv2.CC_STAT_AREA] >= min_size
    return keep[labels]


def _refine(mask: np.ndarray, min_size: int, dilation_size: int) -> np.ndarray:
    if not mask.any():
        return mask
    mask = _remove_small(mask, min_size)
    mask = closing(mask, disk(1))
    if dilation_size > 0:
        mask = dilation(mask, disk(dilation_size))
    return mask.astype(bool)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adaptive_threshold(response: np.ndarray, sensitivity: float, *, floor: float) -> float:
    mean = float(response.mean())
    std = float(response.std())
    scale = 4.5 - 4.0 * float(sensitivity)
    return max(mean + scale * std, floor)


def _suppress_border(response: np.ndarray, margin_fraction: float = 0.01) -> np.ndarray:
    """Zero a thin border ring so film-frame edges do not read as defects."""
    height, width = response.shape[:2]
    margin = max(2, int(round(min(height, width) * margin_fraction)))
    if margin * 2 >= min(height, width):
        return response
    out = response.copy()
    out[:margin, :] = 0.0
    out[-margin:, :] = 0.0
    out[:, :margin] = 0.0
    out[:, -margin:] = 0.0
    return out


def _odd(value: int) -> int:
    value = int(value)
    return value if value % 2 == 1 else value + 1
