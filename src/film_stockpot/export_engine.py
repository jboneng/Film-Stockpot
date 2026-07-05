"""Headless image export — shared by the GUI batch worker and the CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from film_stockpot.image.crosstalk import crosstalk_strength_from_adjustments
from film_stockpot.image.io import load_image_array, save_image_array
from film_stockpot.image.pipeline import apply_film_preset
from film_stockpot.image.print import apply_print_stage
from film_stockpot.image.grading import apply_interactive_adjustments
from film_stockpot.image.scanner import NEUTRAL
from film_stockpot.presets.loader import resolve_preset_data
from film_stockpot.export_naming import (
    DEFAULT_TEMPLATE,
    OUTPUT_EXTENSION,
    ExportNamingContext,
    disambiguate_stem,
    render_export_name,
)
from film_stockpot.sidecar import read_sidecar

ExportJob = dict


@dataclass(frozen=True)
class ExportFileResult:
    """Outcome for one source image in a batch export."""

    source: Path
    output: Path
    status: str  # exported, skipped, failed
    error: str | None = None


@dataclass
class ExportBatchResult:
    """Summary of a batch export run."""

    exported: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    files: list[ExportFileResult] = field(default_factory=list)


def load_adjustments_file(path: Path) -> dict:
    """Load Frontier-style adjustments from a JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Adjustments file must contain a JSON object: {path}")
    return {**NEUTRAL, **data}


def load_sidecar_recipe(path: Path) -> dict:
    """Load a sidecar JSON file used as a shared recipe template."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Sidecar file must contain a JSON object: {path}")
    return data


def build_export_jobs(
    paths: list[str | Path],
    *,
    fallback_preset: dict | None,
    fallback_base: dict | None,
    fallback_adjustments: dict | None,
    sidecar_default_base: dict | None = None,
    require_sidecars: bool = False,
    ignore_sidecars: bool = False,
) -> tuple[list[ExportJob], list[str]]:
    """Build per-image render jobs.

    When ``require_sidecars`` is True, every image must have a sidecar file.
    When ``ignore_sidecars`` is True, per-image sidecars are never read.
    Otherwise (prefer sidecars), an existing sidecar overrides the fallback
    settings for that image.
    """
    if require_sidecars and ignore_sidecars:
        raise ValueError("require_sidecars and ignore_sidecars are mutually exclusive.")

    adjustments = {**NEUTRAL, **(fallback_adjustments or {})}
    jobs: list[ExportJob] = []
    warnings: list[str] = []

    for raw_path in paths:
        path = Path(raw_path)
        sidecar = None if ignore_sidecars else read_sidecar(path)

        if require_sidecars and sidecar is None:
            raise FileNotFoundError(f"Missing sidecar for {path.name}")

        if sidecar is not None:
            jobs.append(
                {
                    "path": str(path),
                    "preset": sidecar.get("film_stock"),
                    "base": sidecar.get("base_profile") or sidecar_default_base or fallback_base,
                    "adjustments": {**NEUTRAL, **(sidecar.get("adjustments") or {})},
                }
            )
            continue

        if fallback_preset is None and not require_sidecars:
            warnings.append(f"No sidecar and no fallback preset for {path.name}")

        jobs.append(
            {
                "path": str(path),
                "preset": fallback_preset,
                "base": fallback_base,
                "adjustments": adjustments,
            }
        )

    return jobs, warnings


def resolve_output_path(
    source: Path,
    output: Path,
    *,
    single_input: bool,
    name_template: str = DEFAULT_TEMPLATE,
    naming_context: ExportNamingContext | None = None,
    used_names: set[str] | None = None,
) -> Path:
    """Return the destination path for one exported TIFF."""
    if single_input and output.suffix.lower() in {".tif", ".tiff"}:
        return output
    if output.suffix.lower() in {".tif", ".tiff"}:
        return output

    context = naming_context or ExportNamingContext.from_job(
        {"path": str(source), "preset": None},
        index=1,
        total=1,
    )
    stem = render_export_name(name_template, context)
    if used_names is not None:
        stem = disambiguate_stem(stem, used_names)
    return output / f"{stem}{OUTPUT_EXTENSION}"


def render_job_to_path(job: ExportJob, target: Path, *, bit_depth: int = 16) -> None:
    """Load, render, and save one export job."""
    rgb = load_image_array(job["path"])
    flat_scan = rgb
    preset = resolve_preset_data(job.get("preset"))
    if preset is not None:
        rgb = apply_film_preset(
            rgb,
            preset,
            job.get("base"),
            crosstalk_strength=crosstalk_strength_from_adjustments(job.get("adjustments")),
        )
    rgb = apply_print_stage(rgb, job.get("adjustments"), preset, flat_scan=flat_scan)
    rgb = apply_interactive_adjustments(rgb, job.get("adjustments"), preset=preset, skip_print_stage=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    save_image_array(target, rgb, bit_depth=bit_depth)


def export_batch(
    jobs: list[ExportJob],
    *,
    output: Path,
    single_input: bool,
    bit_depth: int = 16,
    overwrite: bool = False,
    name_template: str = DEFAULT_TEMPLATE,
    on_progress: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> ExportBatchResult:
    """Render and save every job. Skips existing outputs unless ``overwrite``."""
    result = ExportBatchResult()
    total = len(jobs)
    cancelled = is_cancelled or (lambda: False)
    used_names: set[str] = set()
    exported_at = datetime.now(timezone.utc)

    for index, job in enumerate(jobs):
        if cancelled():
            result.cancelled = True
            break

        source = Path(job["path"])
        if on_progress is not None:
            on_progress(index, total, source.name)

        target = resolve_output_path(
            source,
            output,
            single_input=single_input,
            name_template=name_template,
            naming_context=ExportNamingContext.from_job(
                job,
                index=index + 1,
                total=total,
                exported_at=exported_at,
            ),
            used_names=used_names,
        )
        if target.is_file() and not overwrite:
            result.skipped += 1
            result.files.append(
                ExportFileResult(source=source, output=target, status="skipped")
            )
            continue

        try:
            render_job_to_path(job, target, bit_depth=bit_depth)
            result.exported += 1
            result.files.append(
                ExportFileResult(source=source, output=target, status="exported")
            )
        except Exception as error:  # noqa: BLE001 - reported in summary
            result.failed += 1
            message = f"{source.name}: {error}"
            result.errors.append(message)
            result.files.append(
                ExportFileResult(
                    source=source,
                    output=target,
                    status="failed",
                    error=str(error),
                )
            )

    if on_progress is not None:
        on_progress(total, total, "")

    return result
