#!/usr/bin/env python3
"""Refresh FilmPresets from extracted datasheet JSON files.

Usage:
  uv run python scripts/refresh_presets_from_datasheets.py
  uv run python scripts/refresh_presets_from_datasheets.py --dry-run
  uv run python scripts/refresh_presets_from_datasheets.py --extracted-dir "C:/Users/.../FilmDatasheets"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from film_stockpot.datasheet.refresh import load_manifest, refresh_all_presets  # noqa: E402
from film_stockpot.presets.loader import find_presets_dir  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Refresh FilmPresets from extracted datasheet JSON.")
    parser.add_argument(
        "--extracted-dir",
        type=Path,
        default=None,
        help="Folder containing *.extracted.json files (default: manifest default_extracted_dir)",
    )
    parser.add_argument(
        "--presets-dir",
        type=Path,
        default=None,
        help="FilmPresets directory (default: auto-detect)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without writing preset files",
    )
    parser.add_argument(
        "--no-pipeline",
        action="store_true",
        help="Update metadata only; skip tone curves, acutance, color matrix",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write JSON change report to this path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    presets_dir = args.presets_dir or find_presets_dir()
    manifest = load_manifest(presets_dir)
    extracted_dir = args.extracted_dir
    if extracted_dir is None:
        extracted_dir = Path(manifest.get("default_extracted_dir", ""))
    extracted_dir = extracted_dir.expanduser().resolve()

    if not extracted_dir.is_dir():
        print(f"Error: extracted dir not found: {extracted_dir}", file=sys.stderr)
        return 2

    reports = refresh_all_presets(
        presets_dir,
        extracted_dir,
        apply_pipeline=not args.no_pipeline,
        dry_run=args.dry_run,
    )

    updated = sum(1 for r in reports if r.get("status") == "updated")
    skipped = sum(1 for r in reports if r.get("status") == "skipped")
    print(f"Presets dir: {presets_dir}")
    print(f"Extracted dir: {extracted_dir}")
    print(f"Updated: {updated}, skipped: {skipped}, dry_run: {args.dry_run}")

    for report in reports:
        pid = report.get("preset_id", "?")
        status = report.get("status", "?")
        if status == "skipped":
            print(f"  SKIP {pid}: {report.get('reason')}")
            continue
        n = len(report.get("changes") or [])
        print(f"  OK   {pid}: {n} field(s) changed")

    if args.report:
        args.report.write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
