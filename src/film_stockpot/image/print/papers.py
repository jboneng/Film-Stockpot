"""Darkroom paper profiles (GPL-3).

Values were loosely mapped from published datasheets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from film_stockpot.image.print.constants import EXPOSURE_CONSTANTS

DEFAULT_PROFILE_KEY = "neutral"
PROCESS_C41 = "c41"
PROCESS_BW = "bw"
PROCESS_E6 = "e6"

DyeMatrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]

_IDENTITY_DYE: DyeMatrix = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

_TONAL_KEYS = (
    "d_max",
    "d_min",
    "toe_sharpness_base",
    "shoulder_sharpness_base",
    "toe_height",
    "shoulder_height",
    "paper_midtone_gamma",
    "paper_gamma_width",
)


@dataclass(frozen=True)
class PaperProfile:
    label: str
    kind: str = "ra4"
    d_max: float = EXPOSURE_CONSTANTS["d_max"]
    d_min: float = EXPOSURE_CONSTANTS["d_min"]
    toe_sharpness_base: float = EXPOSURE_CONSTANTS["toe_sharpness_base"]
    shoulder_sharpness_base: float = EXPOSURE_CONSTANTS["shoulder_sharpness_base"]
    toe_height: float = EXPOSURE_CONSTANTS["toe_height"]
    shoulder_height: float = EXPOSURE_CONSTANTS["shoulder_height"]
    paper_midtone_gamma: float = EXPOSURE_CONSTANTS["paper_midtone_gamma"]
    paper_gamma_width: float = EXPOSURE_CONSTANTS["paper_gamma_width"]
    channel_gamma: tuple[float, float, float] = (1.0, 1.0, 1.0)
    base_tint_cmy: tuple[float, float, float] = (0.0, 0.0, 0.0)
    dye_matrix: DyeMatrix = _IDENTITY_DYE


PAPER_PROFILES: dict[str, PaperProfile] = {
    DEFAULT_PROFILE_KEY: PaperProfile(label="Neutral (default)", kind="default"),
    "ilford_mg_rc": PaperProfile(
        label="Ilford Multigrade RC",
        kind="bw",
        d_max=2.10,
        d_min=0.04,
        paper_midtone_gamma=0.15,
    ),
    "ilford_fb_classic": PaperProfile(
        label="Ilford Multigrade FB Classic",
        kind="bw",
        d_max=2.15,
        d_min=0.04,
        toe_sharpness_base=5.0,
        paper_midtone_gamma=0.15,
    ),
    "foma_fomatone": PaperProfile(
        label="Foma Fomatone MG Classic",
        kind="bw",
        d_max=2.0,
        d_min=0.05,
        toe_sharpness_base=3.5,
        paper_midtone_gamma=0.10,
    ),
    "foma_fomabrom": PaperProfile(
        label="Foma Fomabrom Variant",
        kind="bw",
        d_max=2.0,
        d_min=0.04,
        paper_midtone_gamma=0.15,
    ),
    "kodak_endura": PaperProfile(
        label="Kodak Endura Premier",
        kind="ra4",
        d_max=2.55,
        d_min=0.06,
        toe_sharpness_base=3.5,
        paper_midtone_gamma=0.22,
        channel_gamma=(1.04, 1.0, 0.98),
        dye_matrix=(
            (0.95, 0.04, 0.01),
            (0.08, 0.88, 0.04),
            (0.04, 0.14, 0.82),
        ),
    ),
    "fuji_crystal": PaperProfile(
        label="Fujicolor Crystal Archive",
        kind="ra4",
        d_max=2.35,
        d_min=0.03,
        paper_midtone_gamma=0.15,
        channel_gamma=(1.0, 1.03, 1.05),
        base_tint_cmy=(0.0, -0.01, -0.015),
        dye_matrix=(
            (0.96, 0.03, 0.01),
            (0.06, 0.91, 0.03),
            (0.03, 0.11, 0.86),
        ),
    ),
}

_MODE_KIND: dict[str, str] = {PROCESS_C41: "ra4", PROCESS_BW: "bw"}


def resolve_paper(key: str) -> PaperProfile:
    return PAPER_PROFILES.get(key, PAPER_PROFILES[DEFAULT_PROFILE_KEY])


def resolve_dye_matrix(paper: PaperProfile | None) -> np.ndarray | None:
    if paper is None or paper.dye_matrix == _IDENTITY_DYE:
        return None
    matrix = np.array(paper.dye_matrix, dtype=np.float64)
    return matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1e-6)


def profiles_for_mode(process_mode: str) -> list[tuple[str, PaperProfile]]:
    allowed = _MODE_KIND.get(process_mode)
    out = [(DEFAULT_PROFILE_KEY, PAPER_PROFILES[DEFAULT_PROFILE_KEY])]
    if allowed is not None:
        out += [(key, profile) for key, profile in PAPER_PROFILES.items() if profile.kind == allowed]
    return out


def effective_paper_profile(key: str, process_mode: str | None) -> PaperProfile:
    paper = resolve_paper(key)
    if paper.kind == "default":
        return paper
    if process_mode is not None and _MODE_KIND.get(process_mode) == paper.kind:
        return paper
    return PAPER_PROFILES[DEFAULT_PROFILE_KEY]


def effective_constants(paper: PaperProfile | None) -> dict[str, Any]:
    if paper is None or paper.kind == "default":
        return EXPOSURE_CONSTANTS
    merged = dict(EXPOSURE_CONSTANTS)
    for key in _TONAL_KEYS:
        merged[key] = getattr(paper, key)
    return merged


def process_mode_for_preset(preset: dict | None) -> str:
    if preset is None:
        return PROCESS_C41
    if bool(preset.get("monochrome", False)):
        return PROCESS_BW
    process = str(preset.get("process", PROCESS_C41)).lower()
    if process in (PROCESS_E6, "e-6"):
        return PROCESS_E6
    return PROCESS_C41


def default_paper_profile(preset: dict | None) -> str:
    mode = process_mode_for_preset(preset)
    if mode == PROCESS_BW:
        return "ilford_mg_rc"
    return "kodak_endura"
