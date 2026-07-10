#!/usr/bin/env python3
"""Extract structured datasheet content from manufacturer PDFs.

For each PDF in a folder this script writes sibling artifacts:

  {stem}.extracted.json   machine-readable extraction (text, tables, scalars, figures)
  {stem}.extracted.md     human review summary
  {stem}_assets/          embedded images + full-page renders (graphs, curves, MTF plots)

Usage:
  uv sync --group datasheet
  uv run python scripts/extract_datasheets.py --input-dir "C:/Users/.../FilmDatasheets"
  uv run python scripts/extract_datasheets.py --input-dir ... --pdf e4050.pdf
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - CLI guard
    raise SystemExit(
        "PyMuPDF is required. Install with: uv sync --group datasheet"
    ) from exc

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from datasheet_curves import extract_page_curves  # noqa: E402

SCHEMA_VERSION = "1.1"

SECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("characteristic_curves", re.compile(r"characteristic\s+curves?", re.I)),
    ("spectral_sensitivity", re.compile(r"spectral[\s-]*sensitivity", re.I)),
    ("spectral_dye_density", re.compile(r"spectral[\s-]*dye[\s-]*density", re.I)),
    ("mtf", re.compile(r"\bmtf\b|modulation transfer", re.I)),
    ("print_grain_index", re.compile(r"print grain index", re.I)),
    ("reciprocity", re.compile(r"reciprocity", re.I)),
    ("exposure_rating", re.compile(r"exposure rating|film speed|exposure guide", re.I)),
    ("scanning", re.compile(r"\bscanning\b|sp-?3000|frontier|noritsu", re.I)),
    ("push_processing", re.compile(r"push[\s-]*process|push processing", re.I)),
    ("development", re.compile(r"development time|recommended developers", re.I)),
    ("resolving_power", re.compile(r"resolving power", re.I)),
    ("rms_granularity", re.compile(r"diffuse rms granularity|rms granularity", re.I)),
)

DOC_ID_PATTERN = re.compile(
    r"\b([EF]-\d{4}[A-Z]?|[AF]\d{1,3}-\d{3,4}[A-Z]?|G\d{2}[A-Z]?)\b",
    re.I,
)

PGI_LINE_PATTERN = re.compile(
    r"Print Grain Index\s*"
    r"(?:Less than\s*)?(\d+|less than 25)"
    r"(?:\s+(?:Less than\s*)?(\d+|less than 25))?",
    re.I,
)
PGI_TABLE_PATTERN = re.compile(
    r"Print Grain Index\s+((?:<?\s*\d+\s*){1,6})",
    re.I,
)
RMS_PATTERN = re.compile(
    r"Diffuse RMS Granularity(?: Value)?[^\d]{0,40}(\d+(?:\.\d+)?)",
    re.I,
)
ISO_PATTERN = re.compile(
    r"\b(?:ISO|EI)\s*(?:speed rating of\s*)?(\d{2,4})(?:\s*/\s*(\d{2}))?",
    re.I,
)
LATITUDE_PATTERN = re.compile(
    r"exposure latitude[^\n]{0,120}|underexposure latitude[^\n]{0,120}",
    re.I,
)
RECIPROCITY_PATTERN = re.compile(
    r"reciprocity law failure[^\n]{0,200}",
    re.I,
)
SCANNER_SETTING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("tone_adjustment", re.compile(r"Tone adjustment\s*=\s*([^\n]+)", re.I)),
    ("saturation", re.compile(r"Saturation\s*=\s*([+\-]?\d+)", re.I)),
    ("color_balance_c", re.compile(r"\bC\s*=\s*([+\-]?\d+)", re.I)),
    ("color_balance_m", re.compile(r"\bM\s*=\s*([+\-]?\d+)", re.I)),
    ("color_balance_y", re.compile(r"\bY\s*=\s*([+\-]?\d+)", re.I)),
)


@dataclass
class FigureRecord:
    figure_id: str
    page: int
    kind: str
    relative_path: str
    width: int
    height: int
    sections: list[str] = field(default_factory=list)
    caption_hint: str = ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_sections(page_text: str) -> list[str]:
    found: list[str] = []
    for key, pattern in SECTION_PATTERNS:
        if pattern.search(page_text):
            found.append(key)
    return found


def _parse_pgi_values(text: str) -> list[str | int]:
    values: list[str | int] = []
    for match in PGI_TABLE_PATTERN.finditer(text):
        chunk = match.group(1)
        for token in re.findall(r"<?\s*(\d+)|less than\s*(\d+)", chunk, re.I):
            if token[0]:
                values.append(int(token[0]))
            elif token[1]:
                values.append(f"<{token[1]}")
    if not values:
        for match in PGI_LINE_PATTERN.finditer(text):
            for group in match.groups():
                if not group:
                    continue
                if "less than" in group.lower():
                    num = re.search(r"\d+", group)
                    if num:
                        values.append(f"<{num.group()}")
                else:
                    values.append(int(group))
    return values


def _parse_scalars(full_text: str) -> dict:
    scalars: dict = {}

    doc_ids = DOC_ID_PATTERN.findall(full_text)
    if doc_ids:
        scalars["document_ids"] = sorted(set(doc_ids))

    pgi = _parse_pgi_values(full_text)
    if pgi:
        scalars["print_grain_index"] = pgi

    rms_match = RMS_PATTERN.search(full_text)
    if rms_match:
        scalars["rms_granularity"] = float(rms_match.group(1))

    iso_matches = ISO_PATTERN.findall(full_text)
    if iso_matches:
        scalars["iso_ei_mentions"] = [
            {"iso": int(iso), "din": int(din) if din else None}
            for iso, din in iso_matches[:12]
        ]

    latitude = LATITUDE_PATTERN.search(full_text)
    if latitude:
        scalars["latitude_text"] = " ".join(latitude.group(0).split())

    reciprocity = RECIPROCITY_PATTERN.search(full_text)
    if reciprocity:
        scalars["reciprocity_text"] = " ".join(reciprocity.group(0).split())

    scanner: dict[str, str] = {}
    for key, pattern in SCANNER_SETTING_PATTERNS:
        match = pattern.search(full_text)
        if match:
            scanner[key] = match.group(1).strip()
    if scanner:
        scalars["scanner_settings"] = scanner

    return scalars


def _guess_product_name(full_text: str, pdf_name: str) -> str | None:
    patterns = (
        r"KODAK PROFESSIONAL\s+[A-Z0-9 /+-]+ Film",
        r"KODAK GOLD \d+ Film",
        r"KODAK ULTRA MAX \d+ Film",
        r"FUJICOLOR [A-Z0-9 /+-]+",
        r"FUJIFILM \d+",
        r"ILFORD [A-Z0-9 +]+",
        r"HARMAN Phoenix II",
        r"DELTA 3200 PROFESSIONAL",
        r"HP5 PLUS",
        r"TRI-X \d+",
        r"T-MAX \d+",
    )
    for pattern in patterns:
        match = re.search(pattern, full_text, re.I)
        if match:
            return " ".join(match.group(0).split())
    stem = Path(pdf_name).stem.replace("_", " ")
    return stem if stem else None


def _extract_tables(page: fitz.Page, page_number: int) -> list[dict]:
    tables: list[dict] = []
    try:
        found = page.find_tables()
    except (AttributeError, RuntimeError):
        return tables

    for index, table in enumerate(found.tables):
        try:
            rows = table.extract()
        except (AttributeError, RuntimeError, ValueError):
            continue
        if not rows:
            continue
        cleaned = [
            [("" if cell is None else str(cell).strip()) for cell in row]
            for row in rows
        ]
        if not any(any(cell for cell in row) for row in cleaned):
            continue
        tables.append(
            {
                "table_id": f"p{page_number}_t{index}",
                "page": page_number,
                "rows": cleaned,
            }
        )
    return tables


def _section_hints_for_page(page_text: str, page_sections: list[str]) -> list[str]:
    if page_sections:
        return page_sections
    lowered = page_text.lower()
    if "curve" in lowered or "density" in lowered or "log exposure" in lowered:
        return ["possible_graph_page"]
    return []


def extract_pdf(
    pdf_path: Path,
    *,
    render_pages: bool = True,
    render_scale: float = 2.0,
    min_image_bytes: int = 8_000,
) -> dict:
    """Extract text, tables, scalars, and figures from one PDF."""
    pdf_path = pdf_path.resolve()
    stem = pdf_path.stem
    assets_dir = pdf_path.parent / f"{stem}_assets"
    assets_dir.mkdir(exist_ok=True)

    doc = fitz.open(pdf_path)
    pages_out: list[dict] = []
    figures: list[FigureRecord] = []
    all_tables: list[dict] = []
    all_curves: list[dict] = []
    text_parts: list[str] = []

    for page_index in range(len(doc)):
        page_number = page_index + 1
        page = doc[page_index]
        page_text = _clean_text(page.get_text("text"))
        text_parts.append(page_text)
        page_sections = _detect_sections(page_text)

        page_entry: dict = {
            "page": page_number,
            "text": page_text,
            "sections_detected": page_sections,
            "figure_ids": [],
        }

        for table in _extract_tables(page, page_number):
            all_tables.append(table)
            page_entry.setdefault("table_ids", []).append(table["table_id"])

        section_hints = _section_hints_for_page(page_text, page_sections)

        for image_index, image in enumerate(page.get_images(full=True)):
            xref = image[0]
            try:
                extracted = doc.extract_image(xref)
            except (RuntimeError, ValueError):
                continue
            image_bytes = extracted.get("image")
            if not image_bytes or len(image_bytes) < min_image_bytes:
                continue
            ext = extracted.get("ext", "png")
            if ext == "jpeg":
                ext = "jpg"
            figure_id = f"p{page_number}_img{image_index}"
            filename = f"{figure_id}.{ext}"
            out_path = assets_dir / filename
            out_path.write_bytes(image_bytes)

            width = int(extracted.get("width") or 0)
            height = int(extracted.get("height") or 0)
            figure = FigureRecord(
                figure_id=figure_id,
                page=page_number,
                kind="embedded_image",
                relative_path=f"{stem}_assets/{filename}",
                width=width,
                height=height,
                sections=section_hints,
                caption_hint=" ".join(page_text.split())[:240],
            )
            figures.append(figure)
            page_entry["figure_ids"].append(figure_id)

        render_path: Path | None = None
        render_size: tuple[int, int] | None = None

        if render_pages:
            matrix = fitz.Matrix(render_scale, render_scale)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            figure_id = f"p{page_number}_render"
            filename = f"{figure_id}.png"
            render_path = assets_dir / filename
            pixmap.save(render_path)
            render_size = (pixmap.width, pixmap.height)
            figure = FigureRecord(
                figure_id=figure_id,
                page=page_number,
                kind="page_render",
                relative_path=f"{stem}_assets/{filename}",
                width=pixmap.width,
                height=pixmap.height,
                sections=page_sections or section_hints,
                caption_hint=" ".join(page_text.split())[:240],
            )
            figures.append(figure)
            page_entry["figure_ids"].append(figure_id)

        page_curves = extract_page_curves(
            page,
            page_number,
            page_sections,
            render_path,
            render_size,
            render_scale=render_scale,
        )
        if page_curves:
            page_entry["curve_ids"] = [curve["curve_id"] for curve in page_curves]
            all_curves.extend(page_curves)

        pages_out.append(page_entry)

    full_text = _clean_text("\n\n".join(text_parts))
    sections_summary: dict[str, list[int]] = {}
    for page in pages_out:
        for section in page["sections_detected"]:
            sections_summary.setdefault(section, []).append(page["page"])

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_pdf": pdf_path.name,
        "source_path": str(pdf_path),
        "extracted_at": _utc_now_iso(),
        "page_count": len(doc),
        "product_name_guess": _guess_product_name(full_text, pdf_path.name),
        "sections": sections_summary,
        "scalars": _parse_scalars(full_text),
        "pages": pages_out,
        "tables": all_tables,
        "figures": [
            {
                "figure_id": fig.figure_id,
                "page": fig.page,
                "kind": fig.kind,
                "path": fig.relative_path,
                "width": fig.width,
                "height": fig.height,
                "sections": fig.sections,
                "caption_hint": fig.caption_hint,
            }
            for fig in figures
        ],
        "curves": all_curves,
        "notes": [
            "Graph/curve data are digitized into curves[] when vector paths or page renders allow it.",
            "Verify curve arrays against the PDF before preset export use.",
            "scalars are regex-parsed from text; verify against PDF before preset use.",
        ],
    }
    doc.close()
    return payload


def write_markdown_summary(payload: dict, md_path: Path) -> None:
    lines = [
        f"# Datasheet extraction: {payload['source_pdf']}",
        "",
        f"- Extracted: `{payload['extracted_at']}`",
        f"- Pages: {payload['page_count']}",
        f"- Product guess: {payload.get('product_name_guess') or 'unknown'}",
        "",
        "## Scalars (auto-parsed — verify manually)",
        "",
    ]

    scalars = payload.get("scalars") or {}
    if scalars:
        lines.append("```json")
        lines.append(json.dumps(scalars, indent=2))
        lines.append("```")
    else:
        lines.append("_No scalars detected in text layer._")

    lines.extend(["", "## Sections detected", ""])
    sections = payload.get("sections") or {}
    if sections:
        for name, pages in sorted(sections.items()):
            page_list = ", ".join(str(p) for p in pages)
            lines.append(f"- **{name}**: pages {page_list}")
    else:
        lines.append("_No named sections detected._")

    lines.extend(["", "## Curves", ""])
    curves = payload.get("curves") or []
    if not curves:
        lines.append("_No curves digitized on this PDF._")
    else:
        for curve in curves:
            x_label = curve.get("x_axis", {}).get("label", "x")
            y_label = curve.get("y_axis", {}).get("label", "y")
            series_names = ", ".join(s.get("name", "?") for s in curve.get("series") or [])
            lines.append(
                f"- **{curve.get('curve_id')}** (page {curve.get('page')}, "
                f"{curve.get('type')}, {curve.get('extraction')}): "
                f"{len(curve.get('series') or [])} series [{series_names}] — "
                f"{x_label} vs {y_label}"
            )
        lines.append("")
        lines.append("Full point arrays are in the JSON `curves` field.")

    lines.extend(["", "## Figures", ""])
    for fig in payload.get("figures") or []:
        sections_label = ", ".join(fig.get("sections") or []) or "unlabeled"
        lines.append(
            f"- `{fig['path']}` — page {fig['page']}, {fig['kind']}, "
            f"{fig['width']}×{fig['height']}, sections: {sections_label}"
        )

    lines.extend(["", "## Tables", ""])
    tables = payload.get("tables") or []
    if not tables:
        lines.append("_No tables detected._")
    else:
        for table in tables:
            lines.append(f"### {table['table_id']} (page {table['page']})")
            lines.append("")
            lines.append("| " + " | ".join(f"col{i}" for i in range(len(table["rows"][0]))) + " |")
            lines.append("| " + " | ".join("---" for _ in table["rows"][0]) + " |")
            for row in table["rows"][:20]:
                lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
            if len(table["rows"]) > 20:
                lines.append("")
                lines.append(f"_({len(table['rows']) - 20} more rows omitted)_")
            lines.append("")

    lines.extend(["", "## Page text preview", ""])
    for page in payload.get("pages") or []:
        preview = " ".join((page.get("text") or "").split())[:500]
        lines.append(f"### Page {page['page']}")
        lines.append("")
        lines.append(preview or "_empty text layer_")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")


def write_json(payload: dict, json_path: Path) -> None:
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def process_pdf(pdf_path: Path, *, render_pages: bool, render_scale: float) -> tuple[Path, Path]:
    payload = extract_pdf(
        pdf_path,
        render_pages=render_pages,
        render_scale=render_scale,
    )
    json_path = pdf_path.with_suffix(".extracted.json")
    md_path = pdf_path.with_suffix(".extracted.md")
    write_json(payload, json_path)
    write_markdown_summary(payload, md_path)
    return json_path, md_path


def collect_pdfs(input_dir: Path, pdf_name: str | None) -> list[Path]:
    if pdf_name:
        path = input_dir / pdf_name
        if not path.is_file():
            raise FileNotFoundError(f"PDF not found: {path}")
        return [path]
    return sorted(input_dir.glob("*.pdf"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract datasheet text, tables, scalars, and figure images from PDFs.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(r"C:\Users\jbone\Desktop\FilmDatasheets"),
        help="Folder containing manufacturer PDF datasheets",
    )
    parser.add_argument(
        "--pdf",
        help="Process a single PDF filename inside --input-dir",
    )
    parser.add_argument(
        "--no-page-renders",
        action="store_true",
        help="Skip full-page PNG renders (embedded images only)",
    )
    parser.add_argument(
        "--render-scale",
        type=float,
        default=2.0,
        help="Page render scale factor (default 2.0 ≈ 144 DPI)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    input_dir = args.input_dir.expanduser().resolve()
    if not input_dir.is_dir():
        print(f"Error: input directory not found: {input_dir}", file=sys.stderr)
        return 2

    try:
        pdfs = collect_pdfs(input_dir, args.pdf)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not pdfs:
        print(f"No PDF files found in {input_dir}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for pdf_path in pdfs:
        try:
            json_path, md_path = process_pdf(
                pdf_path,
                render_pages=not args.no_page_renders,
                render_scale=args.render_scale,
            )
            figure_count = len(json.loads(json_path.read_text(encoding="utf-8")).get("figures", []))
            print(f"OK  {pdf_path.name}")
            print(f"    {json_path.name}")
            print(f"    {md_path.name}")
            print(f"    figures: {figure_count}")
        except Exception as exc:  # pragma: no cover - batch resilience
            failures.append(f"{pdf_path.name}: {exc}")
            print(f"FAIL {pdf_path.name}: {exc}", file=sys.stderr)

    if failures:
        print(f"\nCompleted with {len(failures)} failure(s).", file=sys.stderr)
        return 1
    print(f"\nProcessed {len(pdfs)} PDF(s) in {input_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
