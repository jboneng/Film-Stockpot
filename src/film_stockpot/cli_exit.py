"""Exit codes for the Film Stockpot CLI (stable for shell pipelines and automation)."""

from __future__ import annotations

EXIT_OK = 0
"""Success: every job exported or skipped; no failures."""

EXIT_RUNTIME = 1
"""Render or I/O failure, or no outputs produced."""

EXIT_USAGE = 2
"""Invalid arguments, missing options, or bad input paths."""

EXIT_NO_INPUT = 3
"""Input path exists but contains no TIFF files."""

EXIT_NAMES = {
    EXIT_OK: "ok",
    EXIT_RUNTIME: "runtime_error",
    EXIT_USAGE: "usage_error",
    EXIT_NO_INPUT: "no_input",
}


def status_for_result(*, exported: int, skipped: int, failed: int) -> str:
    """Return a machine-readable status string for an export run."""
    if failed:
        return "failed"
    if exported == 0 and skipped == 0:
        return "failed"
    if exported == 0 and skipped > 0:
        return "skipped"
    if skipped > 0:
        return "partial"
    return "success"
