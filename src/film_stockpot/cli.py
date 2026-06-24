"""Command-line interface for headless batch export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from film_stockpot import __version__
from film_stockpot.cli_exit import EXIT_NO_INPUT, EXIT_USAGE
from film_stockpot.cli_report import build_export_report, compute_export_exit_code
from film_stockpot.console_io import ExportProgress, ensure_stdio_console
from film_stockpot.export_engine import (
    build_export_jobs,
    export_batch,
    load_adjustments_file,
    load_sidecar_recipe,
)
from film_stockpot.export_naming import DEFAULT_TEMPLATE
from film_stockpot.image.folder import list_tiff_files
from film_stockpot.image.scanner import NEUTRAL
from film_stockpot.presets.loader import find_presets_dir, get_preset, load_base, load_grouped_presets


def _collect_inputs(input_path: Path) -> tuple[list[Path], bool]:
    if input_path.is_file():
        return [input_path], True
    if input_path.is_dir():
        return list_tiff_files(input_path), False
    raise FileNotFoundError(f"Input not found: {input_path}")


def _resolve_fallback(
    *,
    stock_id: str | None,
    sidecar_template: Path | None,
    adjustments_path: Path | None,
    presets_dir: Path | None,
) -> tuple[dict | None, dict | None, dict]:
    preset = None
    base = load_base(presets_dir)

    if sidecar_template is not None:
        recipe = load_sidecar_recipe(sidecar_template)
        preset = recipe.get("film_stock")
        if recipe.get("base_profile") is not None:
            base = recipe.get("base_profile")
        adjustments = {**NEUTRAL, **(recipe.get("adjustments") or {})}
    else:
        adjustments = dict(NEUTRAL)
        if stock_id is not None:
            preset = get_preset(stock_id, presets_dir).data

    if adjustments_path is not None:
        adjustments = load_adjustments_file(adjustments_path)

    return preset, base, adjustments


def _cmd_export(args: argparse.Namespace) -> int:
    ensure_stdio_console()

    input_path = Path(args.input)
    output_path = Path(args.output)
    presets_dir = Path(args.presets_dir) if args.presets_dir else None

    try:
        paths, single_input = _collect_inputs(input_path)
    except (FileNotFoundError, NotADirectoryError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if not paths:
        print(f"Error: no TIFF files found in {input_path}", file=sys.stderr)
        return EXIT_NO_INPUT

    if single_input:
        if output_path.suffix.lower() not in {".tif", ".tiff"} and output_path.exists() and not output_path.is_dir():
            print(f"Error: output must be a directory or .tif file: {output_path}", file=sys.stderr)
            return EXIT_USAGE
    elif output_path.suffix.lower() in {".tif", ".tiff"}:
        print("Error: folder input requires a directory as --output", file=sys.stderr)
        return EXIT_USAGE

    require_sidecars = args.use_sidecars
    ignore_sidecars = args.ignore_sidecars

    if args.sidecar_template and (require_sidecars or ignore_sidecars):
        print("Error: --sidecar cannot be combined with --use-sidecars or --ignore-sidecars", file=sys.stderr)
        return EXIT_USAGE

    stock_id = args.stock
    sidecar_template = Path(args.sidecar_template) if args.sidecar_template else None

    if require_sidecars:
        stock_id = None
    elif sidecar_template is None and stock_id is None:
        print("Error: --stock is required unless --use-sidecars or --sidecar is set", file=sys.stderr)
        return EXIT_USAGE

    try:
        fallback_preset, fallback_base, fallback_adjustments = _resolve_fallback(
            stock_id=stock_id,
            sidecar_template=sidecar_template,
            adjustments_path=Path(args.adjustments) if args.adjustments else None,
            presets_dir=presets_dir,
        )
    except (FileNotFoundError, KeyError, ValueError, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if sidecar_template is None and fallback_preset is None and not require_sidecars:
        print("Error: fallback preset is required (set --stock or --sidecar)", file=sys.stderr)
        return EXIT_USAGE

    try:
        jobs, warnings = build_export_jobs(
            paths,
            fallback_preset=fallback_preset,
            fallback_base=fallback_base,
            fallback_adjustments=fallback_adjustments,
            require_sidecars=require_sidecars,
            ignore_sidecars=ignore_sidecars,
        )
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if args.strict and warnings:
        for message in warnings:
            print(f"Error: {message}", file=sys.stderr)
        return EXIT_USAGE

    progress_stream = sys.stderr if args.json else sys.stdout
    if not args.quiet:
        for message in warnings:
            print(f"Warning: {message}", file=sys.stderr)

    progress = ExportProgress(enabled=not args.quiet, stream=progress_stream)
    progress.begin(len(jobs))

    def on_progress(done: int, total: int, name: str) -> None:
        if name:
            progress.update(done, total, name)

    result = export_batch(
        jobs,
        output=output_path,
        single_input=single_input,
        overwrite=args.overwrite,
        name_template=args.name,
        on_progress=on_progress,
    )

    progress.finish(
        exported=result.exported,
        skipped=result.skipped,
        failed=result.failed,
        cancelled=result.cancelled,
    )

    report = build_export_report(
        result=result,
        input_path=input_path,
        output_path=output_path,
        warnings=warnings,
        total_jobs=len(jobs),
    )
    exit_code = compute_export_exit_code(result)

    if args.json:
        print(json.dumps(report, indent=2))
    elif not args.quiet and result.errors:
        print("Errors:", file=sys.stderr)
        for message in result.errors:
            print(f"  {message}", file=sys.stderr)

    return exit_code


def _cmd_presets_list(args: argparse.Namespace) -> int:
    ensure_stdio_console()
    presets_dir = Path(args.presets_dir) if args.presets_dir else None
    try:
        groups = load_grouped_presets(presets_dir)
    except FileNotFoundError as error:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        import json

        payload = [
            {"id": preset.id, "name": preset.name, "group": group.label}
            for group in groups
            for preset in group.presets
        ]
        print(json.dumps(payload, indent=2))
        return 0

    try:
        directory = presets_dir or find_presets_dir()
    except FileNotFoundError:
        directory = None

    if directory is not None:
        print(f"Presets directory: {directory}\n")
    for group in groups:
        print(f"[{group.label}]")
        for preset in group.presets:
            print(f"  {preset.id:<24} {preset.name}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="film-stockpot",
        description="Film Stockpot — film-stock grading for NegPy flat TIFF exports.",
    )
    parser.add_argument("--version", action="version", version=f"Film Stockpot {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    export_parser = subparsers.add_parser(
        "export",
        help="Export TIFF images with film-stock presets and Frontier-style adjustments",
    )
    export_parser.add_argument(
        "input",
        help="A TIFF file or a folder containing TIFF files",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .tif file (single input) or output directory (folder input)",
    )
    export_parser.add_argument(
        "--stock",
        metavar="ID",
        help="Film-stock preset id for images without a sidecar (required unless --use-sidecars or --sidecar)",
    )
    export_parser.add_argument(
        "--adjustments",
        metavar="FILE",
        help="JSON file with Frontier-style operator adjustments",
    )
    export_parser.add_argument(
        "--sidecar",
        dest="sidecar_template",
        metavar="FILE",
        help="Use preset/base/adjustments from a sidecar JSON as the fallback recipe for all images",
    )
    export_parser.add_argument(
        "--use-sidecars",
        action="store_true",
        help="Require a per-image .stockpot.json sidecar for every input TIFF",
    )
    export_parser.add_argument(
        "--ignore-sidecars",
        action="store_true",
        help="Ignore existing per-image sidecars; use --stock / --sidecar fallback only",
    )
    export_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output files (default: skip existing)",
    )
    export_parser.add_argument(
        "--name",
        metavar="TEMPLATE",
        default=DEFAULT_TEMPLATE,
        help=(
            'Output filename template for folder exports (default: "{original}_export"). '
            "Tokens: {original}, {preset}, {preset_name}, {roll}, {n}, {n:03}, {date}"
        ),
    )
    export_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any image lacks a sidecar when using fallback preset mode",
    )
    export_parser.add_argument(
        "--presets-dir",
        metavar="DIR",
        help="Override the FilmPresets directory",
    )
    export_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )
    export_parser.add_argument(
        "--json",
        action="store_true",
        help="Write a machine-readable JSON report to stdout (progress goes to stderr)",
    )
    export_parser.set_defaults(func=_cmd_export)

    presets_parser = subparsers.add_parser("presets", help="Inspect installed film-stock presets")
    presets_sub = presets_parser.add_subparsers(dest="presets_command", required=True)

    list_parser = presets_sub.add_parser("list", help="List preset ids and display names")
    list_parser.add_argument("--json", action="store_true", help="Print JSON")
    list_parser.add_argument("--presets-dir", metavar="DIR", help="Override the FilmPresets directory")
    list_parser.set_defaults(func=_cmd_presets_list)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_USAGE
    if args.command == "presets" and args.presets_command is None:
        parser.parse_args([*(argv or []), "presets", "--help"])
        return EXIT_USAGE
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
