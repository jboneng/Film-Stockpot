"""Film-stock emulation pipeline.

Applies a single film preset to a flat/log float32 RGB image (values in 0..1).
The pipeline is intentionally stateless: callers always pass the pristine
original image, so applying a different preset never stacks on a prior result.

Beyond the basic grade, the pipeline recovers and re-applies film-specific
characteristics that are latent in a flat scan:

* **Input analysis** (``analyze_input`` / ``input_transform.neutralize``) measures
  per-channel black/white points and removes residual casts so every stock starts
  from a consistent neutral anchor.
* **Tone-zoned color grading** (``color_grading``) tints shadows, midtones, and
  highlights independently -- the core of a film's color-by-tone signature.
* **Per-channel tone curves** (``tone_curves_rgb``) reproduce the R/G/B crossover
  that a single shared curve cannot express.
* **Halation** (``halation``) adds the red/orange highlight bloom characteristic of
  film's anti-halation layer.
* **Grain extraction** (``grain_extraction``) lifts the real grain residual out of
  the scan and re-applies it. No synthetic grain is ever added -- the only grain in
  the output is the grain that was physically on the film.
"""

from __future__ import annotations

import numpy as np

_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_DEFAULT_MONO_MIXER = np.array([0.299, 0.587, 0.114], dtype=np.float32)
_CHANNELS = ("r", "g", "b")


def apply_film_preset(
    rgb: np.ndarray,
    preset: dict,
    base: dict | None = None,
    *,
    crosstalk_strength: float = 0.0,
) -> np.ndarray:
    """Return a new float32 RGB array with the preset's film look applied.

    If ``base`` is provided and defines an ``input_transform``, that de-log /
    scan-normalization stage runs first to expand a flat/log input back to full
    range, preventing the washed-out result that comes from grading a log scan
    directly. The film look is then applied on top.

    ``crosstalk_strength`` (0..1) applies the preset's spectral crosstalk matrix
    after base auto-levels and before neutralize / de-log, so dye-layer unmixing
    runs on the scan's native channel balance.

    ``base`` may also provide ``look_defaults`` (e.g. halation and grain
    extraction) that apply to every stock unless the preset overrides them.

    The input is never modified. Output values are clipped to 0..1.
    """
    image = np.clip(rgb.astype(np.float32, copy=True), 0.0, 1.0)
    # Snapshot the pristine scan luma now (before any mutation) so the grain stage
    # can high-pass it later. Keeping only luma lets every later stage run in
    # place without risk of corrupting the grain source.
    grain_source_luma = image @ _LUMA_WEIGHTS

    transform = base.get("input_transform") if base else None
    if transform:
        image = _apply_input_transform_pre_neutralize(image, transform)

    if crosstalk_strength > 0.0 and not bool(preset.get("monochrome", False)):
        from film_stockpot.image.crosstalk import apply_preset_crosstalk

        image = apply_preset_crosstalk(image, preset, crosstalk_strength)

    if transform:
        image = _apply_input_transform_post_neutralize(image, transform)

    return _apply_film_look(image, preset, base, grain_source_luma)


def apply_film_preset_from_pre_neutralize(
    pre_neutralize_rgb: np.ndarray,
    grain_source_rgb: np.ndarray,
    preset: dict,
    base: dict | None = None,
    *,
    crosstalk_strength: float = 0.0,
) -> np.ndarray:
    """Apply crosstalk, remaining base stages, and the film look.

    ``pre_neutralize_rgb`` is the flat scan after base auto-levels only (before
    neutralize). Crosstalk runs on that buffer, then neutralize / de-log / gamma.
    """
    grain_source_luma = np.clip(grain_source_rgb.astype(np.float32, copy=False), 0.0, 1.0) @ _LUMA_WEIGHTS
    image = np.clip(pre_neutralize_rgb.astype(np.float32, copy=True), 0.0, 1.0)

    if crosstalk_strength > 0.0 and not bool(preset.get("monochrome", False)):
        from film_stockpot.image.crosstalk import apply_preset_crosstalk

        image = apply_preset_crosstalk(image, preset, crosstalk_strength)

    transform = base.get("input_transform") if base else None
    if transform:
        image = _apply_input_transform_post_neutralize(image, transform)

    return _apply_film_look(image, preset, base, grain_source_luma)


def apply_film_preset_from_base_graded(
    base_graded_rgb: np.ndarray,
    grain_source_rgb: np.ndarray,
    preset: dict,
    base: dict | None = None,
    *,
    crosstalk_strength: float = 0.0,
) -> np.ndarray:
    """Backward-compatible alias; prefer :func:`apply_film_preset_from_pre_neutralize`."""
    return apply_film_preset_from_pre_neutralize(
        base_graded_rgb,
        grain_source_rgb,
        preset,
        base,
        crosstalk_strength=crosstalk_strength,
    )


def _apply_film_look(
    image: np.ndarray,
    preset: dict,
    base: dict | None,
    grain_source_luma: np.ndarray,
) -> np.ndarray:
    pipeline = preset.get("pipeline", {})
    look = pipeline.get("look", {}) or {}
    scanner = pipeline.get("scanner_adjustments", {}) or {}
    defaults = (base or {}).get("look_defaults", {}) or {}
    monochrome = bool(preset.get("monochrome", False))

    image = _apply_reciprocity_compensation(image, pipeline.get("reciprocity_compensation"))

    ei_adj = pipeline.get("ei_adjustment") or {}

    if monochrome:
        image = _to_monochrome(image, look.get("mono_mixer"))
    else:
        image = _apply_color_matrix(image, look.get("color_matrix"))
        image = _apply_white_balance(image, pipeline.get("white_balance", {}))

    np.clip(image, 0.0, 1.0, out=image)
    image = _apply_tone_curve(image, pipeline.get("tone_curve_8bit"))
    if not monochrome:
        image = _apply_per_channel_curves(image, pipeline.get("tone_curves_rgb"))

    contrast_pct = float(look.get("contrast_pct", 0)) + float(ei_adj.get("contrast_pct_delta", 0))
    lift = float(look.get("lift", 0.0)) + float(ei_adj.get("lift_delta", 0.0))
    gain = float(look.get("gain", 1.0))
    image = _apply_contrast(image, contrast_pct)
    image = _apply_lift_gain(image, lift, gain)

    gamma = float(scanner.get("gamma", 1.0)) + float(ei_adj.get("gamma_delta", 0.0))
    image = _apply_gamma(image, gamma)
    image = _apply_highlights_shadows(
        image,
        scanner.get("highlights", 0),
        scanner.get("shadows", 0),
    )
    np.clip(image, 0.0, 1.0, out=image)

    if not monochrome:
        image = _apply_color_grading(image, pipeline.get("color_grading"))
        np.clip(image, 0.0, 1.0, out=image)
        image = _apply_saturation(image, scanner.get("saturation_pct", 100))
        np.clip(image, 0.0, 1.0, out=image)

    image = _apply_acutance(image, pipeline.get("acutance"), monochrome)
    np.clip(image, 0.0, 1.0, out=image)

    halation = pipeline.get("halation", defaults.get("halation"))
    image = _apply_halation(image, halation, monochrome)
    np.clip(image, 0.0, 1.0, out=image)

    grain_extraction = _resolve_grain_extraction(
        pipeline.get("grain_extraction", defaults.get("grain_extraction")),
        ei_adj,
    )
    image = _apply_extracted_grain(image, grain_source_luma, grain_extraction)

    np.clip(image, 0.0, 1.0, out=image)
    return image.astype(np.float32, copy=False)


# ---------------------------------------------------------------------------
# Input analysis (Feature 1)
# ---------------------------------------------------------------------------


def analyze_input(image: np.ndarray, black_pct: float = 0.1, white_pct: float = 0.1) -> dict:
    """Measure per-channel black/white points and median of a flat scan.

    Returns a dict keyed by ``"r"``, ``"g"``, ``"b"`` (each with ``black``,
    ``white``, ``median``) plus an overall ``luma_median``. The per-channel
    black/white spread encodes the film's color crossover; the medians reveal any
    residual cast left in the flat scan.
    """
    data = np.clip(np.asarray(image, dtype=np.float32), 0.0, 1.0)
    if data.ndim == 2:
        data = np.stack([data] * 3, axis=-1)

    stats: dict = {}
    for index, channel in enumerate(_CHANNELS):
        plane = data[:, :, index]
        stats[channel] = {
            "black": float(np.percentile(plane, black_pct)),
            "white": float(np.percentile(plane, 100.0 - white_pct)),
            "median": float(np.median(plane)),
        }
    luma = np.sum(data * _LUMA_WEIGHTS, axis=-1)
    stats["luma_median"] = float(np.median(luma))
    return stats


def _apply_input_transform(image: np.ndarray, transform: dict | None) -> np.ndarray:
    """Expand a flat/log input to full range before the film look is applied."""
    if not transform:
        return image

    result = _apply_input_transform_pre_neutralize(image, transform)
    return _apply_input_transform_post_neutralize(result, transform)


def _apply_input_transform_pre_neutralize(image: np.ndarray, transform: dict | None) -> np.ndarray:
    """Auto-level a flat scan before crosstalk and neutralize."""
    if not transform:
        return image

    result = image
    if transform.get("auto_levels", False):
        result = _auto_levels(
            result,
            float(transform.get("black_clip_pct", 0.0) or 0.0),
            float(transform.get("white_clip_pct", 0.0) or 0.0),
            bool(transform.get("per_channel", False)),
        )
    return np.clip(result, 0.0, 1.0)


def _apply_input_transform_post_neutralize(image: np.ndarray, transform: dict | None) -> np.ndarray:
    """Neutralize, de-log, and gamma-correct after crosstalk."""
    if not transform:
        return image

    result = image
    if transform.get("neutralize", False):
        result = _neutralize(result, float(transform.get("neutralize_strength", 1.0) or 0.0))

    strength = float(transform.get("delog_strength", 0.0) or 0.0)
    if strength > 0.0:
        result = _apply_delog(result, strength)

    gamma = float(transform.get("gamma", 1.0) or 1.0)
    if gamma > 0.0 and gamma != 1.0:
        result = np.clip(result, 0.0, 1.0) ** (1.0 / gamma)

    return np.clip(result, 0.0, 1.0)


def apply_base_input_transform(rgb: np.ndarray, base: dict | None) -> np.ndarray:
    """Apply the full shared base ``input_transform`` stage (no film-stock look)."""
    image = np.clip(rgb.astype(np.float32, copy=True), 0.0, 1.0)
    if base:
        image = _apply_input_transform(image, base.get("input_transform"))
    return image.astype(np.float32, copy=False)


def apply_pre_neutralize_input_transform(rgb: np.ndarray, base: dict | None) -> np.ndarray:
    """Apply base auto-levels only (the buffer crosstalk runs on)."""
    image = np.clip(rgb.astype(np.float32, copy=True), 0.0, 1.0)
    if base:
        image = _apply_input_transform_pre_neutralize(image, base.get("input_transform"))
    return image.astype(np.float32, copy=False)


def _neutralize(image: np.ndarray, strength: float) -> np.ndarray:
    """Align per-channel medians toward a common gray, removing residual cast."""
    if strength <= 0.0 or image.ndim != 3 or image.shape[2] < 3:
        return image
    clipped = np.clip(image, 0.0, 1.0)
    medians = np.array(
        [np.median(clipped[:, :, channel]) for channel in range(3)],
        dtype=np.float32,
    )
    target = float(np.mean(medians))
    safe = np.where(medians > 1e-4, medians, 1.0)
    gains = target / safe
    gains = 1.0 * (1.0 - strength) + gains * strength
    return np.clip(image * gains.astype(np.float32), 0.0, 1.0)


def _auto_levels(image: np.ndarray, black_clip_pct: float, white_clip_pct: float, per_channel: bool) -> np.ndarray:
    if per_channel:
        out = np.empty_like(image)
        for channel in range(image.shape[2]):
            data = image[:, :, channel]
            low = np.percentile(data, black_clip_pct)
            high = np.percentile(data, 100.0 - white_clip_pct)
            out[:, :, channel] = _stretch(data, float(low), float(high))
        return out

    luma = np.sum(image * _LUMA_WEIGHTS, axis=-1)
    low = float(np.percentile(luma, black_clip_pct))
    high = float(np.percentile(luma, 100.0 - white_clip_pct))
    return _stretch(image, low, high)


def _stretch(data: np.ndarray, low: float, high: float) -> np.ndarray:
    if high <= low:
        return data
    return (data - low) / (high - low)


def _apply_delog(image: np.ndarray, strength: float) -> np.ndarray:
    clipped = np.clip(image, 0.0, 1.0)
    s_curve = clipped * clipped * (3.0 - 2.0 * clipped)
    return clipped * (1.0 - strength) + s_curve * strength


# ---------------------------------------------------------------------------
# Color / tone look
# ---------------------------------------------------------------------------


def _to_monochrome(image: np.ndarray, mixer: list | None) -> np.ndarray:
    weights = np.array(mixer, dtype=np.float32) if mixer else _DEFAULT_MONO_MIXER
    luma = image @ weights
    return np.repeat(luma[:, :, np.newaxis], 3, axis=2)


def _apply_color_matrix(image: np.ndarray, matrix: list | None) -> np.ndarray:
    if not matrix:
        return image
    mat = np.array(matrix, dtype=np.float32)
    return image @ mat.T


def _apply_white_balance(image: np.ndarray, white_balance: dict) -> np.ndarray:
    gains = (white_balance or {}).get("rgb_gains")
    if not gains:
        return image
    return image * np.array(gains, dtype=np.float32)


def _apply_tone_curve(image: np.ndarray, curve: list | None) -> np.ndarray:
    if not curve or not _curve_is_monotonic(curve):
        return image
    xs = np.array([point[0] for point in curve], dtype=np.float32) / 255.0
    ys = np.array([point[1] for point in curve], dtype=np.float32) / 255.0
    order = np.argsort(xs)
    return np.interp(image, xs[order], ys[order]).astype(np.float32)


def _apply_per_channel_curves(image: np.ndarray, curves: dict | None) -> np.ndarray:
    """Apply independent R/G/B tone curves to reproduce film color crossover.

    ``curves`` maps ``"r"``/``"g"``/``"b"`` to a list of ``[x, y]`` points in
    0..255 space. Missing channels are left untouched.
    """
    if not curves or image.ndim != 3 or image.shape[2] < 3:
        return image
    if not _rgb_curves_are_valid(curves):
        return image

    result = image.copy()
    touched = False
    for index, channel in enumerate(_CHANNELS):
        curve = curves.get(channel)
        if not curve:
            continue
        xs = np.array([point[0] for point in curve], dtype=np.float32) / 255.0
        ys = np.array([point[1] for point in curve], dtype=np.float32) / 255.0
        order = np.argsort(xs)
        result[:, :, index] = np.interp(image[:, :, index], xs[order], ys[order])
        touched = True

    return result.astype(np.float32) if touched else image


def _curve_is_monotonic(curve: list) -> bool:
    if len(curve) < 2:
        return False
    ordered = sorted(curve, key=lambda p: float(p[0]))
    ys = [float(p[1]) for p in ordered]
    return all(ys[i] <= ys[i + 1] + 1e-6 for i in range(len(ys) - 1))


def _rgb_curves_are_valid(curves: dict) -> bool:
    if set(curves.keys()) != {"r", "g", "b"}:
        return False
    return all(_curve_is_monotonic(curves[ch]) for ch in _CHANNELS)


def _apply_color_grading(image: np.ndarray, grading: dict | None) -> np.ndarray:
    """Tint shadows, midtones, and highlights independently (split-tone).

    Each zone is an additive ``[r, g, b]`` offset. Zone membership is derived from
    luma with overlapping triangular weights, so the result is smooth.
    """
    if not grading:
        return image

    shadows = np.array(grading.get("shadows", (0.0, 0.0, 0.0)), dtype=np.float32)
    midtones = np.array(grading.get("midtones", (0.0, 0.0, 0.0)), dtype=np.float32)
    highlights = np.array(grading.get("highlights", (0.0, 0.0, 0.0)), dtype=np.float32)
    if not (np.any(shadows) or np.any(midtones) or np.any(highlights)):
        return image

    luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)
    shadow_w = np.clip(1.0 - luma * 2.0, 0.0, 1.0)
    highlight_w = np.clip(luma * 2.0 - 1.0, 0.0, 1.0)
    mid_w = 1.0 - shadow_w - highlight_w

    result = image + shadow_w * shadows + mid_w * midtones + highlight_w * highlights
    return result.astype(np.float32)


def _apply_contrast(image: np.ndarray, contrast_pct: float) -> np.ndarray:
    factor = float(contrast_pct) / 100.0
    if factor == 0.0:
        return image
    return (image - 0.5) * (1.0 + factor) + 0.5


def _apply_lift_gain(image: np.ndarray, lift: float, gain: float) -> np.ndarray:
    lift = float(lift)
    gain = float(gain)
    if lift == 0.0 and gain == 1.0:
        return image
    return image * gain + lift


def _apply_gamma(image: np.ndarray, gamma: float) -> np.ndarray:
    gamma = float(gamma)
    if gamma <= 0.0 or gamma == 1.0:
        return image
    return np.clip(image, 0.0, 1.0) ** (1.0 / gamma)


def _apply_highlights_shadows(image: np.ndarray, highlights: float, shadows: float) -> np.ndarray:
    highlights = float(highlights) / 100.0
    shadows = float(shadows) / 100.0
    if highlights == 0.0 and shadows == 0.0:
        return image
    result = image
    if shadows != 0.0:
        result = result + shadows * (1.0 - result) * 0.5
    if highlights != 0.0:
        result = result + highlights * result * 0.5
    return result


def _apply_saturation(image: np.ndarray, saturation_pct: float) -> np.ndarray:
    factor = float(saturation_pct) / 100.0
    if factor == 1.0:
        return image
    luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)
    return luma + (image - luma) * factor


def _resolve_grain_extraction(config: dict | None, ei_adj: dict) -> dict | None:
    if not config:
        return config
    mult = float(ei_adj.get("grain_strength_mult", 1.0) or 1.0)
    if mult == 1.0:
        return config
    out = dict(config)
    out["strength"] = float(config.get("strength", 0.0) or 0.0) * mult
    return out


def _apply_reciprocity_compensation(image: np.ndarray, config: dict | None) -> np.ndarray:
    """Compensate reciprocity failure for long exposures (toe lift in shadows)."""
    if not config or image.ndim != 3:
        return image

    assumed = float(config.get("assumed_exposure_s", 0.008) or 0.008)
    no_corr = config.get("no_correction_range_s")
    if isinstance(no_corr, (list, tuple)) and len(no_corr) >= 2:
        if float(no_corr[0]) <= assumed <= float(no_corr[1]):
            return image

    exponent = float(config.get("correction_exponent", 1.0) or 1.0)
    threshold = float(config.get("correction_start_s", 1.0) or 1.0)
    if assumed <= threshold:
        return image

    base_toe = float(config.get("toe_lift", 0.0) or 0.0)
    if exponent != 1.0:
        metered = assumed
        corrected = metered**exponent
        factor = max(0.0, (corrected - metered) / max(metered, 1e-6))
        toe = base_toe + factor * 0.04
    else:
        toe = base_toe

    if abs(toe) < 1e-6:
        return image

    luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)
    shadow_w = np.clip(1.0 - luma * 2.5, 0.0, 1.0)
    return (image + shadow_w * toe).astype(np.float32)


def _apply_acutance(image: np.ndarray, acutance: dict | None, monochrome: bool = False) -> np.ndarray:
    """Edge enhancement derived from datasheet MTF (micro-contrast / acutance)."""
    if not acutance or image.ndim != 3 or image.shape[2] < 3:
        return image

    amount = float(acutance.get("amount", acutance.get("strength", 0.0)) or 0.0)
    if amount <= 0.0:
        return image

    radius = float(acutance.get("radius", 1.2))
    longest = max(image.shape[0], image.shape[1])
    px = max(1, int(round(radius * longest / 1500.0)))

    if monochrome:
        luma = image[:, :, 0:1]
    else:
        luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)

    blurred = _gaussian_blur(luma, px)
    detail = luma - blurred
    boosted = luma + detail * amount
    if monochrome:
        return np.clip(boosted.repeat(3, axis=2), 0.0, 1.0).astype(np.float32)

    return np.clip(image + detail * amount, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Halation (Feature 3)
# ---------------------------------------------------------------------------


def _apply_halation(image: np.ndarray, halation: dict | None, monochrome: bool = False) -> np.ndarray:
    """Add a blurred highlight bloom, screen-blended over the image.

    ``halation`` keys: ``intensity`` (strength), ``threshold`` (highlight luma
    cutoff), ``radius`` (blur size, resolution-independent), and ``color`` (tint,
    forced neutral for monochrome stocks).
    """
    if not halation or image.ndim != 3 or image.shape[2] < 3:
        return image

    intensity = float(halation.get("intensity", 0.0) or 0.0)
    if intensity <= 0.0:
        return image

    threshold = float(halation.get("threshold", 0.65))
    radius = float(halation.get("radius", 12.0))
    color = [1.0, 1.0, 1.0] if monochrome else halation.get("color", [1.0, 0.35, 0.12])
    tint = np.array(color, dtype=np.float32)

    luma = np.sum(image * _LUMA_WEIGHTS, axis=-1, keepdims=True)
    mask = _smoothstep(threshold, min(1.0, threshold + 0.3), luma)
    source = mask * image

    longest = max(image.shape[0], image.shape[1])
    px = max(1, int(round(radius * longest / 1500.0)))
    glow = _gaussian_blur(source, px)

    halo = np.clip(glow * tint * intensity, 0.0, 1.0)
    return 1.0 - (1.0 - image) * (1.0 - halo)


def _smoothstep(edge0: float, edge1: float, values: np.ndarray) -> np.ndarray:
    if edge1 <= edge0:
        return (values >= edge1).astype(np.float32)
    t = np.clip((values - edge0) / (edge1 - edge0), 0.0, 1.0)
    return (t * t * (3.0 - 2.0 * t)).astype(np.float32)


def _gaussian_blur(image: np.ndarray, radius: int) -> np.ndarray:
    """Approximate a Gaussian blur with three separable box-blur passes.

    Works on 2D (luma) or 3D (RGB) float32 arrays.
    """
    radius = int(radius)
    if radius < 1:
        return image
    box = max(1, radius // 3)
    result = image
    for _ in range(3):
        result = _box_blur_axis(result, box, 0)
        result = _box_blur_axis(result, box, 1)
    return result


def _box_blur_axis(image: np.ndarray, radius: int, axis: int) -> np.ndarray:
    """Box-blur along one axis via a running sum (no per-pass dtype copy).

    Operates on the array's native layout (no transpose), so each ``cumsum`` runs
    over contiguous-friendly memory.
    """
    length = image.shape[axis]
    if length <= 1:
        return image
    kernel = 2 * radius + 1
    pad_width = [(0, 0)] * image.ndim
    pad_width[axis] = (radius + 1, radius)
    padded = np.pad(image, pad_width, mode="edge")
    cumulative = np.cumsum(padded, axis=axis)

    upper = [slice(None)] * image.ndim
    lower = [slice(None)] * image.ndim
    upper[axis] = slice(kernel, kernel + length)
    lower[axis] = slice(0, length)
    return (cumulative[tuple(upper)] - cumulative[tuple(lower)]) / kernel


# ---------------------------------------------------------------------------
# Grain extraction (Feature 5)
# ---------------------------------------------------------------------------


def _apply_extracted_grain(image: np.ndarray, source_luma: np.ndarray, config: dict | None) -> np.ndarray:
    """Lift the scan's real high-frequency grain and re-apply it, midtone-weighted.

    ``source_luma`` is the pristine scan's luma (``H, W``). Because the box blur and
    the luma projection are both linear, high-passing the luma is identical to
    high-passing each channel and projecting to luma -- but a third of the work.

    ``config`` keys: ``strength`` (amount) and ``radius`` (high-pass size). The
    residual is monochromatic so grain never tints the image.
    """
    if not config or source_luma is None:
        return image
    strength = float(config.get("strength", 0.0) or 0.0)
    if strength <= 0.0:
        return image
    if source_luma.shape[:2] != image.shape[:2]:
        return image

    radius = max(1, int(config.get("radius", 1) or 1))
    luma = np.clip(source_luma, 0.0, 1.0)
    luma_residual = (luma - _gaussian_blur(luma, radius))[:, :, np.newaxis]

    image_luma = np.mean(image, axis=-1, keepdims=True)
    midtone_mask = 1.0 - np.abs(image_luma - 0.5)
    return image + luma_residual * strength * midtone_mask
