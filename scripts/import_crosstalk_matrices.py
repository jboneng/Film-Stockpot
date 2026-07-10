#!/usr/bin/env python3
"""One-shot dev tool: copy crosstalk matrices from TOML into FilmPresets JSON.

The application reads ``pipeline.crosstalk.matrix`` from each preset JSON at
runtime. External TOML files are never loaded by Film Stockpot itself.

Usage:
  uv run python scripts/import_crosstalk_matrices.py
  uv run python scripts/import_crosstalk_matrices.py --crosstalk-dir "C:/path/to/crosstalk"
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESETS_DIR = ROOT / "FilmPresets"
MANIFEST_PATH = Path(__file__).resolve().with_name("crosstalk_import_manifest.json")


def _parse_toml_matrix(path: Path) -> list[list[float]] | None:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    rows = data.get("matrix")
    if not isinstance(rows, list) or len(rows) != 3:
        return None
    matrix: list[list[float]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 3:
            return None
        matrix.append([float(v) for v in row])
    return matrix


def import_matrices(crosstalk_dir: Path) -> list[str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries: dict[str, str] = manifest.get("entries") or {}
    updated: list[str] = []

    for preset_id, toml_name in entries.items():
        toml_path = crosstalk_dir / toml_name
        preset_path = PRESETS_DIR / f"{preset_id}.json"
        if not toml_path.is_file():
            print(f"SKIP {preset_id}: missing {toml_path.name}")
            continue
        if not preset_path.is_file():
            print(f"SKIP {preset_id}: missing preset JSON")
            continue

        matrix = _parse_toml_matrix(toml_path)
        if matrix is None:
            print(f"SKIP {preset_id}: invalid {toml_name}")
            continue

        preset = json.loads(preset_path.read_text(encoding="utf-8"))
        pipeline = preset.setdefault("pipeline", {})
        pipeline["crosstalk"] = {"matrix": matrix}
        preset_path.write_text(json.dumps(preset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        updated.append(preset_id)
        print(f"OK   {preset_id} <- {toml_name}")

    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy crosstalk matrices from TOML into FilmPresets JSON (dev import only).",
    )
    parser.add_argument(
        "--crosstalk-dir",
        type=Path,
        default=None,
        help="Folder of crosstalk TOML files (default: manifest default_crosstalk_dir)",
    )
    args = parser.parse_args(argv)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    crosstalk_dir = args.crosstalk_dir
    if crosstalk_dir is None:
        crosstalk_dir = Path(manifest.get("default_crosstalk_dir", ""))
    crosstalk_dir = crosstalk_dir.expanduser().resolve()

    if not crosstalk_dir.is_dir():
        print(f"Error: crosstalk dir not found: {crosstalk_dir}", file=sys.stderr)
        return 2

    count = len(import_matrices(crosstalk_dir))
    print(f"\nUpdated {count} preset(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
