"""Export filename templates for single and batch rendering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TEMPLATE = "{original}_export"
OUTPUT_EXTENSION = ".tif"

NAME_PRESETS: dict[str, str] = {
    "original_export": "{original}_export",
    "original_only": "{original}",
    "original_preset": "{original}_{preset}",
    "roll_index": "{roll}_{n:03}_{original}",
}

NAME_PRESET_LABELS: dict[str, str] = {
    "original_export": "{original}_export",
    "original_only": "{original}",
    "original_preset": "{original}_{preset}",
    "roll_index": "{roll}_{n:03}_{original}",
}

_TOKEN_PATTERN = re.compile(r"\{([^}:]+)(?::([^}]+))?\}")
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class ExportNamingContext:
    """Values available to export filename templates."""

    source: Path
    index: int
    total: int
    preset: dict | None
    exported_at: datetime

    @classmethod
    def from_job(
        cls,
        job: dict,
        *,
        index: int,
        total: int,
        exported_at: datetime | None = None,
    ) -> ExportNamingContext:
        return cls(
            source=Path(job["path"]),
            index=index,
            total=total,
            preset=job.get("preset"),
            exported_at=exported_at or datetime.now(timezone.utc),
        )

    @property
    def roll_name(self) -> str:
        return self.source.parent.name or "roll"

    @property
    def preset_id(self) -> str:
        if not self.preset:
            return "none"
        return str(self.preset.get("id") or "none")

    @property
    def preset_display_name(self) -> str:
        if not self.preset:
            return "none"
        return str(self.preset.get("name") or self.preset_id)


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe filename stem."""
    cleaned = _INVALID_CHARS.sub("_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._ ")
    return cleaned or "export"


def _sanitize_token(value: str) -> str:
    cleaned = value.strip().replace(" ", "_")
    return sanitize_filename(cleaned)


def _format_index(index: int, fmt: str | None) -> str:
    if fmt is None:
        return str(index)
    try:
        width = int(fmt)
    except ValueError:
        return str(index)
    return f"{index:0{width}d}"


def _resolve_token(key: str, fmt: str | None, ctx: ExportNamingContext) -> str:
    if key == "original":
        return _sanitize_token(ctx.source.stem)
    if key == "preset":
        return _sanitize_token(ctx.preset_id)
    if key == "preset_name":
        return _sanitize_token(ctx.preset_display_name)
    if key == "roll":
        return _sanitize_token(ctx.roll_name)
    if key == "n":
        return _format_index(ctx.index, fmt)
    if key == "date":
        return ctx.exported_at.strftime("%Y%m%d")
    if key == "suffix":
        return fmt or "_export"
    return ""


def render_export_name(template: str, ctx: ExportNamingContext) -> str:
    """Render a template into a filename stem (no extension)."""

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        fmt = match.group(2)
        return _resolve_token(key, fmt, ctx)

    rendered = _TOKEN_PATTERN.sub(replace, template)
    return sanitize_filename(rendered)


def disambiguate_stem(stem: str, used: set[str]) -> str:
    """Ensure ``stem`` is unique within ``used``, mutating the set."""
    if stem not in used:
        used.add(stem)
        return stem

    counter = 2
    while True:
        candidate = f"{stem}_{counter}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def example_export_name(template: str) -> str:
    """Return a sample rendered name for UI previews."""
    sample = ExportNamingContext(
        source=Path("roll") / "scan001.tiff",
        index=3,
        total=36,
        preset={"id": "kodak_gold_200", "name": "Kodak Gold 200"},
        exported_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
    )
    return render_export_name(template, sample)
