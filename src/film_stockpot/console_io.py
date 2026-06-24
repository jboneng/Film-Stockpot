"""Console helpers for CLI export (progress display and Windows stdio)."""

from __future__ import annotations

import sys
import threading
import time

_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def ensure_stdio_console() -> None:
    """Attach stdout/stderr to a console on Windows GUI builds when run from a terminal."""
    if sys.platform != "win32":
        return
    if sys.stdout is not None and sys.stdout.isatty():
        return

    import ctypes

    kernel32 = ctypes.windll.kernel32
    if kernel32.GetConsoleWindow():
        return
    if not kernel32.AttachConsole(-1):
        return

    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
    sys.stderr = open("CONERR$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115


class ExportProgress:
    """Render a multi-line progress display with a busy spinner for batch export."""

    def __init__(self, *, enabled: bool = True, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._enabled = enabled and self._stream is not None
        self._is_tty = bool(self._enabled and hasattr(self._stream, "isatty") and self._stream.isatty())
        self._started = time.monotonic()
        self._last_lines = 0
        self._spinner_stop = threading.Event()
        self._spinner_thread: threading.Thread | None = None
        self._spinner_message = ""

    def begin(self, total: int) -> None:
        if not self._enabled:
            return
        self._started = time.monotonic()
        self._write_block(
            [
                "",
                "  Film Stockpot export",
                "  " + "─" * 44,
                self._bar_line(0, total, ""),
                self._status_line(0, total, "", 0.0),
                self._busy_line(_SPINNER_FRAMES[0], "Preparing…"),
                "",
            ]
        )
        self._start_spinner("Preparing…")

    def update(self, done: int, total: int, name: str) -> None:
        self._stop_spinner()
        if not self._enabled or not name:
            return
        elapsed = time.monotonic() - self._started
        self._write_block(
            [
                "",
                "  Film Stockpot export",
                "  " + "─" * 44,
                self._bar_line(done, total, name),
                self._status_line(done, total, name, elapsed),
                self._busy_line(_SPINNER_FRAMES[0], f"Processing {name}…"),
                "",
            ]
        )
        self._start_spinner(f"Processing {name}…")

    def finish(self, *, exported: int, skipped: int, failed: int, cancelled: bool) -> None:
        self._stop_spinner()
        if not self._enabled:
            return
        elapsed = time.monotonic() - self._started
        status = "cancelled" if cancelled else "complete"
        parts = [f"{exported} exported"]
        if skipped:
            parts.append(f"{skipped} skipped")
        if failed:
            parts.append(f"{failed} failed")
        summary = ", ".join(parts)
        self._write_block(
            [
                "",
                "  Film Stockpot export",
                "  " + "─" * 44,
                f"  {status.capitalize()} — {summary} ({elapsed:.1f}s)",
                "",
            ]
        )

    def _bar_line(self, done: int, total: int, name: str) -> str:
        width = 32
        if total <= 0:
            filled = 0
        else:
            filled = min(width, int(width * (done + 1) / total))
        bar = "█" * filled + "░" * (width - filled)
        label = name if name else "…"
        if len(label) > 28:
            label = label[:25] + "..."
        return f"  [{bar}]  {label}"

    def _status_line(self, done: int, total: int, name: str, elapsed: float) -> str:
        if not name:
            return "  …"
        return f"  {done + 1}/{total}  {name}  ({elapsed:.1f}s)"

    def _busy_line(self, frame: str, message: str) -> str:
        return f"  {frame} {message}"

    def _start_spinner(self, message: str) -> None:
        if not self._is_tty:
            return
        self._spinner_message = message
        self._spinner_stop.clear()
        self._spinner_thread = threading.Thread(target=self._spinner_loop, daemon=True)
        self._spinner_thread.start()

    def _stop_spinner(self) -> None:
        self._spinner_stop.set()
        if self._spinner_thread is not None:
            self._spinner_thread.join(timeout=0.5)
            self._spinner_thread = None

    def _spinner_loop(self) -> None:
        frame_idx = 0
        while not self._spinner_stop.wait(0.08):
            frame = _SPINNER_FRAMES[frame_idx % len(_SPINNER_FRAMES)]
            frame_idx += 1
            self._write_spinner_line(self._busy_line(frame, self._spinner_message))

    def _write_spinner_line(self, line: str) -> None:
        if self._stream is None or self._last_lines < 2:
            return
        # Spinner sits two lines above the cursor (busy line + trailing blank).
        self._stream.write("\x1b[2A")
        self._stream.write("\x1b[2K" + line + "\n\n")
        self._stream.flush()

    def _write_block(self, lines: list[str]) -> None:
        if self._stream is None:
            return
        if self._last_lines:
            self._stream.write(f"\x1b[{self._last_lines}A")
        for line in lines:
            self._stream.write("\x1b[2K" + line + "\n")
        self._stream.flush()
        self._last_lines = len(lines)
