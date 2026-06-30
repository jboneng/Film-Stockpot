"""Interactive Fuji Frontier-style operator adjustments.

These are cheap, elementwise operations meant to run in realtime on a preview
image. They are applied on top of the film-preset result, mirroring how a
Frontier operator fine-tunes a scan after the base look is set.
"""

from __future__ import annotations

import numpy as np

from film_stockpot.image.crosstalk import CROSSTALK_DEFAULT

_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

TONE_FACTORS = {
    "Soft": 0.85,
    "Standard": 1.0,
    "Hard": 1.15,
    "All Hard": 1.30,
}

NEUTRAL: dict = {
    "density": 0,
    "gamma": 0,
    "cyan": 0,
    "magenta": 0,
    "yellow": 0,
    "highlight": 0,
    "shadow": 0,
    "saturation": 0,
    "sharpness": 0,
    "tone": "Standard",
    "crosstalk": CROSSTALK_DEFAULT,
}


def apply_scanner_adjustments(rgb: np.ndarray, settings: dict | None = None) -> np.ndarray:
    """Apply Frontier-style operator adjustments to a float32 RGB image (0..1).

    Neutral settings return the input unchanged. The input is never modified.
    """
    values = {**NEUTRAL, **(settings or {})}
    image = np.clip(rgb.astype(np.float32, copy=True), 0.0, 1.0)

    density = float(values["density"])
    if density != 0.0:
        image = np.clip(image * (2.0 ** (-density * 0.05)), 0.0, 1.0)

    gamma_steps = float(values["gamma"])
    if gamma_steps != 0.0:
        gamma = 1.0 + gamma_steps * 0.04
        image = np.clip(image, 0.0, 1.0) ** (1.0 / gamma)

    cyan = float(values["cyan"])
    magenta = float(values["magenta"])
    yellow = float(values["yellow"])
    if cyan or magenta or yellow:
        step = 0.012
        # Negative slider values add the named cast (cyan/magenta/yellow); positive
        # values add the complementary color (red/green/blue), matching the
        # left-to-right labels on the Frontier-style controls.
        gains = np.array([1.0 + cyan * step, 1.0 + magenta * step, 1.0 + yellow * step], dtype=np.float32)
        image = np.clip(image * gains, 0.0, 1.0)

    tone_factor = TONE_FACTORS.get(values["tone"], 1.0)
    if tone_factor != 1.0:
        image = (image - 0.5) * tone_factor + 0.5

    shadow = float(values["shadow"]) / 100.0
    highlight = float(values["highlight"]) / 100.0
    if shadow != 0.0:
        image = image + shadow * (1.0 - image) * 0.5
    if highlight != 0.0:
        image = image + highlight * image * 0.5
    image = np.clip(image, 0.0, 1.0)

    saturation = float(values["saturation"])
    if saturation != 0.0:
        factor = 1.0 + saturation * 0.08
        luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)
        image = np.clip(luma + (image - luma) * factor, 0.0, 1.0)

    sharpness = float(values["sharpness"])
    if sharpness > 0.0:
        image = _unsharp_mask(image, sharpness * 0.12)

    return np.clip(image, 0.0, 1.0).astype(np.float32)


def _unsharp_mask(image: np.ndarray, amount: float) -> np.ndarray:
    blurred = _blur(image)
    return np.clip(image + (image - blurred) * amount, 0.0, 1.0)


def _blur(image: np.ndarray) -> np.ndarray:
    padded = np.pad(image, ((1, 1), (1, 1), (0, 0)), mode="edge")
    return (
        4.0 * padded[1:-1, 1:-1]
        + padded[:-2, 1:-1]
        + padded[2:, 1:-1]
        + padded[1:-1, :-2]
        + padded[1:-1, 2:]
    ) / 8.0
