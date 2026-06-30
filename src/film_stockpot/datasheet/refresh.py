"""Refresh FilmPresets JSON from extracted datasheet files."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from film_stockpot.datasheet.sensitometry import (
    BASE_GRAIN_STRENGTH,
    blend_color_matrices,
    derive_acutance_from_curves,
    derive_color_matrix_from_dye_density,
    derive_ei_variants_from_curves,
    derive_reciprocity_compensation,
    derive_sensitometry_from_curves,
    derive_tone_curves_from_characteristic,
    is_valid_tone_curve,
    is_valid_tone_curves_rgb,
    pgi_to_grain_strength,
    scalar_grain_value,
)

PRESET_SCHEMA_VERSION = "1.1"


def load_manifest(presets_dir: Path) -> dict:
    path = presets_dir / "_datasheet_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing datasheet manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_extraction(extracted_dir: Path, stem: str) -> dict | None:
    path = extracted_dir / f"{stem}.extracted.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _full_text(extraction: dict) -> str:
    return "\n".join(page.get("text") or "" for page in extraction.get("pages") or [])


def refresh_preset_from_extraction(
    preset: dict,
    extraction: dict,
    *,
    apply_pipeline: bool = True,
    blend_color_matrix: float = 0.35,
    preserve_color_grading: bool = True,
) -> tuple[dict, dict[str, Any]]:
    """Return updated preset copy and a change report."""
    out = deepcopy(preset)
    report: dict[str, Any] = {"preset_id": out.get("id"), "changes": []}

    def _log(field: str, old: Any, new: Any) -> None:
        if old != new:
            report["changes"].append({"field": field, "old": old, "new": new})

    out["schema_version"] = PRESET_SCHEMA_VERSION
    scalars = extraction.get("scalars") or {}
    curves = extraction.get("curves") or []
    film = out.setdefault("film", {})
    pipeline = out.setdefault("pipeline", {})
    look = pipeline.setdefault("look", {})
    confidence = out.setdefault("confidence", {})

    doc_ids = scalars.get("document_ids") or []
    film["datasheet"] = {
        "source_pdf": extraction.get("source_pdf"),
        "extracted_at": extraction.get("extracted_at"),
        "document_id": doc_ids[0] if doc_ids else None,
        "schema_version": extraction.get("schema_version"),
        "curve_types": sorted({c.get("type") for c in curves if c.get("type")}),
    }
    out["source"] = extraction.get("source_pdf") or out.get("source")

    iso_mentions = scalars.get("iso_ei_mentions") or []
    if iso_mentions and iso_mentions[0].get("iso"):
        iso = int(iso_mentions[0]["iso"])
        _log("film.base_iso", film.get("base_iso"), iso)
        film["base_iso"] = iso
        confidence["base_iso"] = "specified"

    metric, grain_val = scalar_grain_value(scalars)
    if grain_val is not None:
        old_grain = film.get("grain")
        new_grain = {"metric": metric, "value": int(grain_val) if grain_val == int(grain_val) else grain_val}
        _log("film.grain", old_grain, new_grain)
        film["grain"] = new_grain
        pipeline["grain"] = new_grain
        confidence["grain"] = "specified"

        strength = pgi_to_grain_strength(grain_val, metric=metric)
        if strength is not None:
            grain_cfg = {"strength": strength, "radius": 1}
            _log("pipeline.grain_extraction", pipeline.get("grain_extraction"), grain_cfg)
            pipeline["grain_extraction"] = grain_cfg

    sens = derive_sensitometry_from_curves(curves)
    if sens:
        film["sensitometry"] = sens
        for key in ("d_min", "d_max", "curve_gamma"):
            if key in sens:
                _log(f"film.{key}", film.get(key), sens[key])
                film[key] = sens[key]
                confidence[key] = "specified" if sens.get("gamma_rgb") else "estimated"

    reciprocity = derive_reciprocity_compensation(scalars, _full_text(extraction))
    if reciprocity:
        old = film.get("reciprocity") or {}
        merged = {**old, **reciprocity}
        if old.get("note") and not reciprocity.get("note"):
            merged["note"] = old["note"]
        _log("film.reciprocity", old, merged)
        film["reciprocity"] = merged
        pipeline["reciprocity_compensation"] = reciprocity
        confidence["reciprocity"] = "specified"

    scanner = scalars.get("scanner_settings")
    if scanner:
        out["native_scanner_profile"] = {
            "scanner": "Fuji SP-3000",
            "tone_adjustment": scanner.get("tone_adjustment"),
            "saturation": scanner.get("saturation"),
            "color_balance": {
                "c": scanner.get("color_balance_c"),
                "m": scanner.get("color_balance_m"),
                "y": scanner.get("color_balance_y"),
            },
        }
        confidence["native_scanner_profile"] = "specified"

    if apply_pipeline:
        master, rgb = derive_tone_curves_from_characteristic(curves)
        if master and is_valid_tone_curve(master):
            pipeline["datasheet_tone_curve_8bit"] = master
            if not preset.get("pipeline", {}).get("tone_curve_8bit"):
                pipeline["tone_curve_8bit"] = master
                confidence["tone_curve_8bit"] = "specified"
        if rgb and is_valid_tone_curves_rgb(rgb) and not out.get("monochrome"):
            pipeline["datasheet_tone_curves_rgb"] = rgb
            if not preset.get("pipeline", {}).get("tone_curves_rgb"):
                pipeline["tone_curves_rgb"] = rgb
                confidence["tone_curves_rgb"] = "specified"

        acutance = derive_acutance_from_curves(curves)
        if acutance:
            pipeline["acutance"] = acutance
            confidence["acutance"] = "specified"

        dye_matrix = derive_color_matrix_from_dye_density(curves)
        if dye_matrix and not out.get("monochrome"):
            existing = look.get("color_matrix")
            blended = blend_color_matrices(existing, dye_matrix, blend_color_matrix)
            look["color_matrix"] = blended
            pipeline["dye_density_matrix"] = dye_matrix
            confidence["color_matrix"] = "specified"

        base_iso = int(film.get("base_iso") or 400)
        ei_variants = derive_ei_variants_from_curves(curves, base_iso)
        if ei_variants:
            pipeline["ei_variants"] = ei_variants

        recommended = film.get("recommended_ei")
        ei_adj: dict[str, Any] | None = None
        if ei_variants and recommended and str(recommended) in ei_variants.get("variants", {}):
            ei_adj = ei_variants["variants"][str(recommended)]
        elif recommended and base_iso and recommended != base_iso:
            ratio = float(recommended) / float(base_iso)
            ei_adj = {
                "contrast_pct_delta": round((1.0 - ratio) * 4.0, 1),
                "gamma_delta": round((1.0 - ratio) * 0.025, 3),
                "grain_strength_mult": round(ratio**0.5, 3),
                "lift_delta": round(0.006 * (1.0 - ratio), 4),
            }
        if ei_adj:
            pipeline["ei_adjustment"] = ei_adj

    if preserve_color_grading and preset.get("pipeline", {}).get("color_grading"):
        pipeline["color_grading"] = preset["pipeline"]["color_grading"]

    return out, report


def refresh_all_presets(
    presets_dir: Path,
    extracted_dir: Path,
    *,
    apply_pipeline: bool = True,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    manifest = load_manifest(presets_dir)
    reports: list[dict[str, Any]] = []

    for preset_path in sorted(presets_dir.glob("*.json")):
        if preset_path.name.startswith("_"):
            continue
        preset = json.loads(preset_path.read_text(encoding="utf-8"))
        preset_id = preset.get("id", preset_path.stem)
        entry = (manifest.get("entries") or {}).get(preset_id)
        if not entry:
            reports.append({"preset_id": preset_id, "status": "skipped", "reason": "no manifest entry"})
            continue

        stem = entry.get("extracted_stem", preset_id)
        extraction = load_extraction(extracted_dir, stem)
        if extraction is None:
            reports.append({"preset_id": preset_id, "status": "skipped", "reason": f"missing {stem}.extracted.json"})
            continue

        updated, report = refresh_preset_from_extraction(
            preset,
            extraction,
            apply_pipeline=apply_pipeline,
        )
        report["status"] = "updated"
        reports.append(report)

        if not dry_run:
            preset_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return reports
