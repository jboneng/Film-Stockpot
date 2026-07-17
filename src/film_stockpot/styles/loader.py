"""Load camera styles from the CameraStyles catalog."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from film_stockpot import paths

_STYLES_DIR_NAME = "CameraStyles"
_CATALOG_FILE = "catalog.json"


@dataclass(frozen=True)
class CameraStyle:
    """A single camera look from the style catalog."""

    id: str
    name: str
    label: str
    slot: str | None
    base_style: str | None
    settings: dict[str, Any]
    curve_points: list[list[float]]


_cached_styles: list[CameraStyle] | None = None
_cached_dir: Path | None = None


def find_camera_styles_dir() -> Path:
    """Locate the CameraStyles directory in frozen builds and source checkouts."""
    candidates: list[Path] = []
    if paths.is_frozen():
        candidates.append(paths.executable_dir() / _STYLES_DIR_NAME)
        bundle = paths.meipass_root()
        if bundle is not None:
            candidates.append(bundle / _STYLES_DIR_NAME)
    candidates.append(Path.cwd() / _STYLES_DIR_NAME)
    candidates.append(paths.repo_root() / _STYLES_DIR_NAME)
    candidates.extend(parent / _STYLES_DIR_NAME for parent in Path(__file__).resolve().parents)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"Could not locate a '{_STYLES_DIR_NAME}' directory near {Path.cwd()} or {__file__}."
    )


def _style_id(name: str, slot: str | None) -> str:
    return f"{name}::{slot or ''}"


def _profile_to_style(profile: dict[str, Any]) -> CameraStyle:
    name = str(profile.get("name") or profile.get("label") or "Untitled")
    label = str(profile.get("label") or name)
    slot = profile.get("slot")
    slot_text = str(slot) if slot is not None else None
    curve = profile.get("curve") or {}
    points = curve.get("points") or []
    curve_points: list[list[float]] = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        curve_points.append([float(point[0]), float(point[1])])
    settings = dict(profile.get("settings") or {})
    base_style = profile.get("base_style")
    return CameraStyle(
        id=_style_id(name, slot_text),
        name=name,
        label=label,
        slot=slot_text,
        base_style=str(base_style) if base_style not in (None, False) else None,
        settings=settings,
        curve_points=curve_points,
    )


def load_camera_styles(styles_dir: Path | None = None) -> list[CameraStyle]:
    """Load all camera styles from catalog.json, sorted by name."""
    global _cached_styles, _cached_dir

    directory = styles_dir or find_camera_styles_dir()
    if styles_dir is None and _cached_styles is not None and _cached_dir == directory:
        return list(_cached_styles)

    catalog_path = directory / _CATALOG_FILE
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Camera style catalog not found: {catalog_path}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    styles = [_profile_to_style(profile) for profile in catalog.get("profiles", [])]
    styles.sort(key=lambda style: (style.name.lower(), style.slot or "", style.id))

    if styles_dir is None:
        _cached_styles = list(styles)
        _cached_dir = directory
    return styles


def get_camera_style(style_id: str, styles_dir: Path | None = None) -> CameraStyle:
    """Return a single camera style by its id."""
    for style in load_camera_styles(styles_dir):
        if style.id == style_id:
            return style
    raise KeyError(f"No camera style with id '{style_id}'.")
