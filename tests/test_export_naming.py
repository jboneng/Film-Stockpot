"""Tests for export filename templates."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import tifffile

from film_stockpot.export_engine import export_batch, resolve_output_path
from film_stockpot.export_naming import (
    DEFAULT_TEMPLATE,
    ExportNamingContext,
    disambiguate_stem,
    example_export_name,
    render_export_name,
)


def _context(**overrides) -> ExportNamingContext:
    defaults = {
        "source": Path("carnival") / "scan001.tiff",
        "index": 3,
        "total": 36,
        "preset": {"id": "kodak_gold_200", "name": "Kodak Gold 200"},
        "exported_at": datetime(2026, 6, 24, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    return ExportNamingContext(**defaults)


def test_render_default_template() -> None:
    ctx = _context()
    assert render_export_name(DEFAULT_TEMPLATE, ctx) == "scan001_export"


def test_render_original_only() -> None:
    ctx = _context()
    assert render_export_name("{original}", ctx) == "scan001"


def test_render_original_preset() -> None:
    ctx = _context()
    assert render_export_name("{original}_{preset}", ctx) == "scan001_kodak_gold_200"


def test_render_roll_index_padding() -> None:
    ctx = _context()
    assert render_export_name("{roll}_{n:03}_{original}", ctx) == "carnival_003_scan001"


def test_render_date_token() -> None:
    ctx = _context()
    assert render_export_name("{original}_{date}", ctx) == "scan001_20260624"


def test_render_sanitizes_preset_name() -> None:
    ctx = _context(preset={"id": "x", "name": "Stock / 400"})
    assert render_export_name("{preset_name}", ctx) == "Stock_400"


def test_disambiguate_stem_appends_counter() -> None:
    used: set[str] = set()
    assert disambiguate_stem("scan001_export", used) == "scan001_export"
    assert disambiguate_stem("scan001_export", used) == "scan001_export_2"


def test_example_export_name() -> None:
    assert example_export_name("{original}_{preset}").endswith("kodak_gold_200")


def test_resolve_output_path_uses_template(tmp_path: Path) -> None:
    source = Path("scan001.tiff")
    ctx = _context(source=source, index=1, total=1)
    target = resolve_output_path(
        source,
        tmp_path,
        single_input=False,
        name_template="{original}_{preset}",
        naming_context=ctx,
    )
    assert target == tmp_path / "scan001_kodak_gold_200.tif"


def test_export_batch_uses_custom_template(tmp_path: Path) -> None:
    source = tmp_path / "frame.tiff"
    tifffile.imwrite(source, np.full((4, 4, 3), 30000, dtype=np.uint16), photometric="rgb")
    out_dir = tmp_path / "out"
    jobs = [
        {
            "path": str(source),
            "preset": {"id": "kodak_gold_200", "name": "Kodak Gold 200"},
            "base": None,
            "adjustments": None,
        }
    ]

    result = export_batch(
        jobs,
        output=out_dir,
        single_input=False,
        overwrite=True,
        name_template="{original}_{preset}",
    )

    assert result.exported == 1
    assert (out_dir / "frame_kodak_gold_200.tif").is_file()
