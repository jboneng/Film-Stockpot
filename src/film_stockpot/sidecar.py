"""Read, write, and delete per-image edit sidecar files.

A sidecar is a JSON file stored next to the source image (``image.tiff`` ->
``image.tiff.stockpot.json``). It embeds the *full* film-stock preset data, the
full scanner base profile, and the adjustment settings, so an image plus its
sidecar renders identically on another Film Stockpot installation even if the
applied film stock is not installed there.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
_SIDECAR_SUFFIX = ".stockpot.json"


def sidecar_path(image_path: str | Path) -> Path:
    """Return the sidecar path for an image (``image.tiff.stockpot.json``)."""
    source = Path(image_path)
    return source.with_name(source.name + _SIDECAR_SUFFIX)


def has_sidecar(image_path: str | Path) -> bool:
    """Return True if a sidecar file exists for the image."""
    return sidecar_path(image_path).is_file()


def write_sidecar(
    image_path: str | Path,
    *,
    preset: dict | None,
    base: dict | None,
    adjustments: dict,
) -> Path:
    """Write a sidecar capturing the full edit state for an image.

    The whole ``preset`` and ``base`` dicts are embedded verbatim so rendering
    does not depend on the local preset library.
    """
    source = Path(image_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "app": "Film Stockpot",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_image": source.name,
        "film_stock": preset,
        "base_profile": base,
        "adjustments": adjustments,
    }

    target = sidecar_path(source)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def read_sidecar(image_path: str | Path) -> dict | None:
    """Return the parsed sidecar for an image, or None if absent/invalid."""
    target = sidecar_path(image_path)
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_sidecar(image_path: str | Path) -> bool:
    """Delete the sidecar for an image. Returns True if a file was removed."""
    target = sidecar_path(image_path)
    if target.is_file():
        target.unlink()
        return True
    return False
