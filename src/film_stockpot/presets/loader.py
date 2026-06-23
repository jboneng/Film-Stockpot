"""Load film presets from the FilmPresets folder."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from film_stockpot import paths

_PRESETS_DIR_NAME = "FilmPresets"
_INDEX_FILE = "_index.json"
_BASE_FILE = "_frontier_base.json"


@dataclass(frozen=True)
class Preset:
    """A single film-stock preset."""

    id: str
    name: str
    path: Path
    data: dict


@dataclass(frozen=True)
class PresetGroup:
    """A named group of presets, as listed in the index."""

    family: str
    label: str
    presets: list[Preset] = field(default_factory=list)


def find_presets_dir() -> Path:
    """Locate the FilmPresets directory in frozen builds and source checkouts."""
    candidates: list[Path] = []
    if paths.is_frozen():
        candidates.append(paths.executable_dir() / _PRESETS_DIR_NAME)
        bundle = paths.meipass_root()
        if bundle is not None:
            candidates.append(bundle / _PRESETS_DIR_NAME)
    candidates.append(Path.cwd() / _PRESETS_DIR_NAME)
    candidates.append(paths.repo_root() / _PRESETS_DIR_NAME)
    candidates.extend(parent / _PRESETS_DIR_NAME for parent in Path(__file__).resolve().parents)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"Could not locate a '{_PRESETS_DIR_NAME}' directory near {Path.cwd()} or {__file__}."
    )


def _load_preset_file(path: Path) -> Preset:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Preset(id=data.get("id", path.stem), name=data.get("name", path.stem), path=path, data=data)


def load_grouped_presets(presets_dir: Path | None = None) -> list[PresetGroup]:
    """Load presets organized into groups using the index manifest.

    Falls back to a single group of all non-underscore JSON files if the index
    is missing.
    """
    directory = presets_dir or find_presets_dir()
    index_path = directory / _INDEX_FILE

    if not index_path.is_file():
        presets = [
            _load_preset_file(path)
            for path in sorted(directory.glob("*.json"))
            if not path.name.startswith("_")
        ]
        return [PresetGroup(family="all", label="Film stocks", presets=presets)]

    index = json.loads(index_path.read_text(encoding="utf-8"))
    groups: list[PresetGroup] = []
    for group in index.get("groups", []):
        presets = []
        for entry in group.get("presets", []):
            preset_path = directory / entry["file"]
            if preset_path.is_file():
                presets.append(_load_preset_file(preset_path))
        if presets:
            groups.append(PresetGroup(family=group["family"], label=group["label"], presets=presets))
    return groups


def load_base(presets_dir: Path | None = None) -> dict | None:
    """Load the shared Frontier base profile (de-log + scanner layer), if present."""
    directory = presets_dir or find_presets_dir()
    base_path = directory / _BASE_FILE
    if base_path.is_file():
        return json.loads(base_path.read_text(encoding="utf-8"))
    return None


def get_preset(preset_id: str, presets_dir: Path | None = None) -> Preset:
    """Return a single preset by its id."""
    for group in load_grouped_presets(presets_dir):
        for preset in group.presets:
            if preset.id == preset_id:
                return preset
    raise KeyError(f"No preset with id '{preset_id}'.")
