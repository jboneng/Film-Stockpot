"""Build machine-readable CLI reports for automation and tool chains."""

from __future__ import annotations

from pathlib import Path

from film_stockpot import __version__
from film_stockpot.cli_exit import EXIT_NAMES, EXIT_OK, EXIT_RUNTIME, status_for_result
from film_stockpot.export_engine import ExportBatchResult


def compute_export_exit_code(result: ExportBatchResult) -> int:
    """Return the process exit code for an export run."""
    if result.cancelled:
        return EXIT_RUNTIME
    if result.failed:
        return EXIT_RUNTIME
    if result.exported == 0 and result.skipped == 0:
        return EXIT_RUNTIME
    return EXIT_OK


def build_export_report(
    *,
    result: ExportBatchResult,
    input_path: Path,
    output_path: Path,
    warnings: list[str],
    total_jobs: int,
) -> dict:
    """Return a JSON-serializable export summary for downstream tools."""
    exit_code = compute_export_exit_code(result)
    status = status_for_result(
        exported=result.exported,
        skipped=result.skipped,
        failed=result.failed,
    )
    if result.cancelled:
        status = "cancelled"

    return {
        "tool": "film-stockpot",
        "command": "export",
        "version": __version__,
        "status": status,
        "exit_code": exit_code,
        "exit_name": EXIT_NAMES.get(exit_code, "unknown"),
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "counts": {
            "total": total_jobs,
            "exported": result.exported,
            "skipped": result.skipped,
            "failed": result.failed,
        },
        "outputs": [
            str(file_result.output.resolve())
            for file_result in result.files
            if file_result.status in {"exported", "skipped"}
        ],
        "files": [
            {
                "source": str(file_result.source.resolve()),
                "output": str(file_result.output.resolve()),
                "status": file_result.status,
                **({"error": file_result.error} if file_result.error else {}),
            }
            for file_result in result.files
        ],
        "errors": list(result.errors),
        "warnings": list(warnings),
        "cancelled": result.cancelled,
    }
