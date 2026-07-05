"""Parameters for the dust / hair / scratch defect removal system."""

from __future__ import annotations

from dataclasses import dataclass, replace

INPAINT_TELEA = "telea"
INPAINT_NS = "ns"
INPAINT_METHODS = (INPAINT_TELEA, INPAINT_NS)


@dataclass(frozen=True)
class DefectParams:
    """Tuning for defect detection and inpainting.

    Sensitivities are 0..1 (higher = more aggressive detection). Sizes are in
    pixels at the resolution the detection runs on (the preview proxy).
    """

    detect_dust: bool = True
    detect_hair: bool = True
    detect_scratch: bool = True

    dust_sensitivity: float = 0.5
    hair_sensitivity: float = 0.5
    scratch_sensitivity: float = 0.5

    min_size: int = 3
    dilation: int = 1

    inpaint_method: str = INPAINT_TELEA
    inpaint_radius: int = 3

    def normalized(self) -> "DefectParams":
        """Return a copy with values clamped to valid ranges."""
        method = self.inpaint_method if self.inpaint_method in INPAINT_METHODS else INPAINT_TELEA
        return replace(
            self,
            dust_sensitivity=_clamp01(self.dust_sensitivity),
            hair_sensitivity=_clamp01(self.hair_sensitivity),
            scratch_sensitivity=_clamp01(self.scratch_sensitivity),
            min_size=max(0, int(self.min_size)),
            dilation=max(0, int(self.dilation)),
            inpaint_method=method,
            inpaint_radius=max(1, int(self.inpaint_radius)),
        )

    def any_detector_enabled(self) -> bool:
        return bool(self.detect_dust or self.detect_hair or self.detect_scratch)


DEFECT_NEUTRAL = DefectParams()


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
