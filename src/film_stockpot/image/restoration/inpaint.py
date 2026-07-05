"""Inpaint masked defects using OpenCV, preserving unmasked pixels exactly."""

from __future__ import annotations

import cv2
import numpy as np

from film_stockpot.image.restoration.params import (
    DEFECT_NEUTRAL,
    INPAINT_TELEA,
    DefectParams,
)


def remove_defects(rgb: np.ndarray, mask: np.ndarray | None, params: DefectParams = DEFECT_NEUTRAL) -> np.ndarray:
    """Return a copy of ``rgb`` with masked defects inpainted.

    Inpainting runs on an 8-bit copy (OpenCV's inpaint only supports 8-bit), but
    only the masked pixels are composited back over the original float image, so
    every unmasked pixel is preserved bit-for-bit at full precision.
    """
    params = params.normalized()
    result = np.clip(rgb.astype(np.float32, copy=True), 0.0, 1.0)
    if mask is None:
        return result
    mask = np.ascontiguousarray(mask.astype(bool))
    if mask.shape != result.shape[:2] or not mask.any():
        return result

    source8 = (result * 255.0 + 0.5).astype(np.uint8)
    bgr = cv2.cvtColor(source8, cv2.COLOR_RGB2BGR)
    mask8 = np.ascontiguousarray((mask.astype(np.uint8)) * 255)
    flag = cv2.INPAINT_TELEA if params.inpaint_method == INPAINT_TELEA else cv2.INPAINT_NS

    painted = cv2.inpaint(bgr, mask8, float(params.inpaint_radius), flag)
    painted_rgb = cv2.cvtColor(painted, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0

    result[mask] = painted_rgb[mask]
    return result.astype(np.float32, copy=False)
