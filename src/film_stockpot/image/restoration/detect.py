"""Classical-CV defect detection for film scans.

Detects dust specks, hair/fibers, and scratches on a scan and fuses them into a
single binary repair mask. The design goal (per the project handover) is to flag
as few pixels as possible while preserving film grain, texture, and -- crucially --
real image structure such as window frames, building edges, and the film rebate.

Every detector is built on operators that respond to *thin* features (top-hat
morphology, ridge filtering) and therefore inherently reject wide region
boundaries / step edges. Detections are then cleaned up by rejecting texture-dense
regions (siding, foliage, text) and long structural contours, so only isolated
defects survive. All detectors are polarity-agnostic (bright and dark defects),
so they work on positives and negatives alike.
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

    if not mask.any():
        return mask

    # Real image structure and texture are the dominant false positives. First
    # drop detections inside dense repetitive texture (siding, foliage, text),
    # then drop detections on long structural boundaries (frames, building edges)
    # while protecting thin ridge pixels so genuine long scratches/hairs survive.
    mask = _reject_dense_texture(mask)
    if mask.any():
        structure = _structure_edges(luma8) & ~dilation(_ridge_pixels(luma8), disk(2))
        mask &= ~structure
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
# large real structures (edges, subjects, frames) are inherently rejected.
# ---------------------------------------------------------------------------


def _detect_dust(luma8: np.ndarray, sensitivity: float) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    white = cv2.morphologyEx(luma8, cv2.MORPH_TOPHAT, kernel)
    black = cv2.morphologyEx(luma8, cv2.MORPH_BLACKHAT, kernel)
    response = _suppress_border(np.maximum(white, black).astype(np.float32))
    threshold = _busy_scene_threshold(response, sensitivity, floor=12.0)
    mask = response >= threshold
    # Dust is compact; reject anything strongly elongated (that is a line, handled
    # by the scratch/hair detectors) so texture stripes are not doubled up here.
    return _reject_by_shape(mask, max_major=None, max_area=400)


# ---------------------------------------------------------------------------
# Hair / fibers: thin curved ridges via the Sato line filter (Hessian-based,
# which suppresses step edges by construction).
# ---------------------------------------------------------------------------


def _detect_hair(luma: np.ndarray, sensitivity: float) -> np.ndarray:
    bright = sato(luma, sigmas=(1, 2), black_ridges=False)
    dark = sato(luma, sigmas=(1, 2), black_ridges=True)
    response = _suppress_border(np.maximum(bright, dark).astype(np.float32))
    floor = 0.02 + 0.10 * (1.0 - float(sensitivity))
    threshold = _adaptive_threshold(response, sensitivity, floor=floor)
    mask = response >= threshold
    return _keep_elongated(mask, min_major=12.0, min_ratio=3.0)


# ---------------------------------------------------------------------------
# Scratches: long thin lines via top-hat morphology (rejects step edges) with
# strict elongation so only long, straight, thin structures survive.
# ---------------------------------------------------------------------------


def _detect_scratch(luma8: np.ndarray, sensitivity: float) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    white = cv2.morphologyEx(luma8, cv2.MORPH_TOPHAT, kernel)
    black = cv2.morphologyEx(luma8, cv2.MORPH_BLACKHAT, kernel)
    response = _suppress_border(np.maximum(white, black).astype(np.float32))
    # A fixed floor avoids global percentile inflation from siding/textured regions,
    # which was hiding real scratches on otherwise flat areas of the scan.
    threshold = 8.0 + (1.0 - float(sensitivity)) * 12.0
    mask = response >= threshold
    length = max(14.0, max(luma8.shape) / 80.0)
    return _keep_elongated(mask, min_major=length, min_ratio=4.0)


# ---------------------------------------------------------------------------
# Structure / texture rejection
# ---------------------------------------------------------------------------


def _structure_edges(luma8: np.ndarray) -> np.ndarray:
    """Mask of long structural contours (frames, building/horizon edges, siding).

    Thresholds the gradient magnitude at a high percentile (which adapts to
    low-contrast edges that fixed Canny thresholds miss) and keeps only long
    connected contours. Real region boundaries are therefore excluded from the
    defect mask, while short isolated defects and scattered grain are left alone.
    """
    luma = luma8.astype(np.float32)
    grad_x = cv2.Sobel(luma, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(luma, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    threshold = float(np.percentile(magnitude, 90.0))
    if threshold <= 0.0:
        return np.zeros(luma8.shape, dtype=bool)
    edges = (magnitude > threshold).astype(np.uint8)
    min_length = max(60, int(0.22 * max(luma8.shape)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = np.zeros(count, dtype=bool)
    for index in range(1, count):
        bbox_diag = max(stats[index, cv2.CC_STAT_WIDTH], stats[index, cv2.CC_STAT_HEIGHT])
        keep[index] = bbox_diag >= min_length
    long_edges = keep[labels]
    return dilation(long_edges, disk(3))


def _ridge_pixels(luma8: np.ndarray) -> np.ndarray:
    """Strong thin-ridge (line/speck) response used to shield real defects.

    A step edge (region boundary) produces almost no top-hat response, whereas a
    thin line does, so protecting these pixels lets genuine scratches and hairs
    survive structural-edge rejection even when they are long.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    white = cv2.morphologyEx(luma8, cv2.MORPH_TOPHAT, kernel)
    black = cv2.morphologyEx(luma8, cv2.MORPH_BLACKHAT, kernel)
    response = np.maximum(white, black).astype(np.float32)
    threshold = max(float(np.percentile(response, 99.0)), 10.0)
    return response > threshold


def _reject_dense_texture(mask: np.ndarray, fraction: float = 0.10) -> np.ndarray:
    """Drop detections inside locally dense regions (siding, foliage, text).

    Isolated defects (dust, a lone scratch/hair) occupy a small fraction of any
    local window; repetitive texture saturates it, so a local-density threshold
    separates the two.
    """
    if not mask.any():
        return mask
    height, width = mask.shape
    window = _odd(max(25, int(round(min(height, width) * 0.08))))
    density = cv2.boxFilter(mask.astype(np.float32), -1, (window, window), normalize=True)
    return mask & (density < fraction)


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


def _reject_by_shape(mask: np.ndarray, *, max_major: float | None, max_area: int | None) -> np.ndarray:
    """Drop components that are too large or (optionally) too elongated for dust."""
    if not mask.any():
        return mask
    labelled = label(mask)
    out = np.zeros_like(mask)
    for region in regionprops(labelled):
        if max_area is not None and region.area > max_area:
            continue
        if max_major is not None and region.axis_major_length > max_major:
            continue
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
    """Return mean+std threshold for sparse responses (dust, hair)."""
    mean = float(response.mean())
    std = float(response.std())
    scale = 4.5 - 4.0 * float(sensitivity)
    return max(floor, mean + scale * std)


def _busy_scene_threshold(response: np.ndarray, sensitivity: float, *, floor: float) -> float:
    """High-percentile threshold for responses polluted by repetitive texture."""
    percentile = min(99.95, 98.5 + (1.0 - float(sensitivity)) * 1.2)
    active = response[response > floor * 0.5]
    if active.size <= response.size * 0.002:
        return _adaptive_threshold(response, sensitivity, floor=floor)
    return max(floor, float(np.percentile(active, percentile)))


def _suppress_border(response: np.ndarray, margin_fraction: float = 0.02) -> np.ndarray:
    """Zero a border ring so the film frame / rebate does not read as defects."""
    height, width = response.shape[:2]
    margin = max(3, int(round(min(height, width) * margin_fraction)))
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
