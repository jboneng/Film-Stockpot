"""Cached preview pipeline for interactive adjustment and display."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import numpy as np

from film_stockpot.image.grading import (
    GradingContext,
    apply_grading_after_scanner,
    apply_interactive_adjustments,
    has_grading_adjustments,
    has_wheel_adjustments,
)
from film_stockpot.image.io import compute_histograms
from film_stockpot.image.print import apply_print_stage, print_cache_key, print_enabled
from film_stockpot.image.scanner import apply_scanner_adjustments
from film_stockpot.ui.preview_stages import PreviewStage, compute_base_graded, compute_pre_neutralize


def downscale_for_preview(rgb: np.ndarray, max_long_edge: int) -> np.ndarray:
    """Return a contiguous preview proxy no larger than ``max_long_edge``."""
    height, width = rgb.shape[:2]
    longest = max(height, width)
    if longest <= max_long_edge:
        return rgb if rgb.flags.c_contiguous else np.ascontiguousarray(rgb)
    step = int(np.ceil(longest / max_long_edge))
    return np.ascontiguousarray(rgb[::step, ::step])


def _scanner_key(settings: dict | None, *, preview_fast: bool) -> str:
    """Key for the scanner stage (everything except grading)."""
    payload = {k: v for k, v in (settings or {}).items() if k != "grading"}
    payload["_preview_fast"] = preview_fast
    return json.dumps(payload, sort_keys=True, default=str)


def _full_key(settings: dict | None, *, preview_fast: bool) -> str:
    """Key for the fully rendered result (scanner *and* grading).

    The full cache must include grading; otherwise a grading-only change would
    return the previously rendered frame and the edit would never appear.
    """
    payload = dict(settings or {})
    payload["_preview_fast"] = preview_fast
    return json.dumps(payload, sort_keys=True, default=str)


@dataclass
class PreviewTimings:
    scanner_ms: float = 0.0
    grading_ms: float = 0.0
    total_ms: float = 0.0
    used_gpu: bool = False


@dataclass
class PreviewEngine:
    """Owns preview proxies, cached layers, and timing stats."""

    preview_max: int = 1800
    drag_preview_max: int = 1200
    gpu_backend: object | None = None
    _flat: np.ndarray | None = field(default=None, init=False)
    _base_graded: np.ndarray | None = field(default=None, init=False)
    _pre_neutralize: np.ndarray | None = field(default=None, init=False)
    _film_base: np.ndarray | None = field(default=None, init=False)
    _film_base_full: np.ndarray | None = field(default=None, init=False)
    _render_preset: dict | None = field(default=None, init=False)
    _base_profile: dict | None = field(default=None, init=False)
    _print_key: str | None = field(default=None, init=False)
    _print_result: np.ndarray | None = field(default=None, init=False)
    _scanner_key: str | None = field(default=None, init=False)
    _scanner_result: np.ndarray | None = field(default=None, init=False)
    _full_key: str | None = field(default=None, init=False)
    _full_result: np.ndarray | None = field(default=None, init=False)
    _grading_context: GradingContext = field(default_factory=GradingContext, init=False)
    last_timings: PreviewTimings = field(default_factory=PreviewTimings, init=False)

    def clear(self) -> None:
        self._flat = None
        self._base_graded = None
        self._pre_neutralize = None
        self._film_base = None
        self._film_base_full = None
        self._render_preset = None
        self._base_profile = None
        self._print_key = None
        self._print_result = None
        self._scanner_key = None
        self._scanner_result = None
        self._full_key = None
        self._full_result = None
        self._grading_context.clear()

    def set_flat_original(self, rgb: np.ndarray | None, base_profile: dict | None) -> None:
        self._flat = downscale_for_preview(rgb, self.preview_max) if rgb is not None else None
        self._base_profile = base_profile
        if self._flat is None:
            self._base_graded = None
            self._pre_neutralize = None
            return
        self._pre_neutralize = compute_pre_neutralize(self._flat, base_profile)
        self._base_graded = compute_base_graded(self._flat, base_profile)

    def set_film_base(self, rgb: np.ndarray | None, base_profile: dict | None, preset: dict | None = None) -> None:
        """Set the film-stock preview base and invalidate adjustment caches."""
        self._film_base_full = rgb
        self._base_profile = base_profile
        self._render_preset = preset
        self._film_base = downscale_for_preview(rgb, self.preview_max) if rgb is not None else None
        self._print_key = None
        self._print_result = None
        self._scanner_key = None
        self._scanner_result = None
        self._full_key = None
        self._full_result = None
        self._grading_context.clear()
        if self._flat is None and rgb is not None:
            self.set_flat_original(rgb, base_profile)

    def rebuild_flat_cache(self, base_profile: dict | None) -> None:
        self._base_profile = base_profile
        if self._flat is None:
            return
        self._pre_neutralize = compute_pre_neutralize(self._flat, base_profile)
        self._base_graded = compute_base_graded(self._flat, base_profile)

    @property
    def flat_original(self) -> np.ndarray | None:
        return self._flat

    @property
    def pre_neutralize(self) -> np.ndarray | None:
        return self._pre_neutralize

    @property
    def film_base(self) -> np.ndarray | None:
        return self._film_base

    def effective_film_base(self, *, preview_fast: bool = False) -> np.ndarray | None:
        base = self._film_base
        if base is None:
            return None
        if preview_fast:
            return downscale_for_preview(base, self.drag_preview_max)
        return base

    def effective_flat_scan(self, *, preview_fast: bool = False) -> np.ndarray | None:
        flat = self._flat
        if flat is None:
            return None
        if preview_fast:
            return downscale_for_preview(flat, self.drag_preview_max)
        return flat

    def cache_hit(self, adjustments: dict | None, *, preview_fast: bool = False) -> bool:
        if self._film_base is None:
            return False
        key = _full_key(adjustments, preview_fast=preview_fast)
        return self._full_key == key and self._full_result is not None

    def scanner_cached(self, adjustments: dict | None, *, preview_fast: bool = False) -> bool:
        """True when the scanner stage for ``adjustments`` is already computed.

        Because the scanner key excludes grading, this is the signal that a
        change was *grading only* (wheels / luminance / blending / balance) and
        the cached scanner output can be re-graded without recomputing it.
        """
        if self._film_base is None:
            return False
        key = _scanner_key(adjustments, preview_fast=preview_fast)
        return self._scanner_key == key and self._scanner_result is not None

    def scanner_result(self) -> np.ndarray | None:
        return self._scanner_result

    def grading_context(self) -> GradingContext:
        return self._grading_context

    def store_scanner_result(
        self,
        adjustments: dict | None,
        result: np.ndarray,
        *,
        preview_fast: bool = False,
    ) -> None:
        """Cache the scanner-stage output (grading applied separately)."""
        key = _scanner_key(adjustments, preview_fast=preview_fast)
        self._scanner_key = key
        self._scanner_result = result
        self._full_key = None
        self._full_result = None

    def store_print_result(
        self,
        adjustments: dict | None,
        result: np.ndarray,
        *,
        preview_fast: bool = False,
    ) -> None:
        key = print_cache_key(adjustments, self._render_preset)
        if preview_fast:
            key = f"{key}:fast"
        self._print_key = key
        self._print_result = result

    def store_rendered_full(
        self,
        adjustments: dict | None,
        result: np.ndarray,
        *,
        preview_fast: bool = False,
    ) -> None:
        key = _full_key(adjustments, preview_fast=preview_fast)
        self._full_key = key
        self._full_result = result

    def invalidate_adjustment_cache(self) -> None:
        self._print_key = None
        self._print_result = None
        self._scanner_key = None
        self._scanner_result = None
        self._full_key = None
        self._full_result = None

    def _render_print_stage(
        self,
        film_base: np.ndarray,
        adjustments: dict | None,
        *,
        preview_fast: bool = False,
        compute_if_missing: bool = True,
    ) -> np.ndarray:
        if not print_enabled(adjustments):
            return film_base

        key = print_cache_key(adjustments, self._render_preset)
        if preview_fast:
            key = f"{key}:fast"
        if self._print_key == key and self._print_result is not None:
            return self._print_result
        if not compute_if_missing:
            return self._print_result if self._print_result is not None else film_base

        prior_key = self._print_key
        result = apply_print_stage(
            film_base,
            adjustments,
            self._render_preset,
            flat_scan=self.effective_flat_scan(preview_fast=preview_fast),
        )
        self._print_key = key
        self._print_result = result
        if prior_key != key:
            self._scanner_key = None
            self._scanner_result = None
            self._full_key = None
            self._full_result = None
        return result

    def stage_array(
        self,
        stage: PreviewStage,
        adjustments: dict | None,
        *,
        preview_fast: bool = False,
    ) -> np.ndarray | None:
        if stage is PreviewStage.FLAT:
            return self._flat
        if stage is PreviewStage.BASE:
            return self._base_graded
        if stage is PreviewStage.FILM:
            return self._film_base
        if stage is PreviewStage.PRINT:
            film_base = self.effective_film_base(preview_fast=preview_fast)
            if film_base is None:
                return None
            return self._render_print_stage(
                film_base,
                adjustments,
                preview_fast=preview_fast,
                compute_if_missing=False,
            )
        if stage is PreviewStage.FULL:
            return self.render_full(adjustments, preview_fast=preview_fast)
        return None

    def render_full(self, adjustments: dict | None, *, preview_fast: bool = False) -> np.ndarray | None:
        film_base = self.effective_film_base(preview_fast=preview_fast)
        if film_base is None:
            return None
        full_key = _full_key(adjustments, preview_fast=preview_fast)
        if self._full_key == full_key and self._full_result is not None:
            return self._full_result

        scanner_key = _scanner_key(adjustments, preview_fast=preview_fast)
        started = time.perf_counter()
        if self._scanner_key == scanner_key and self._scanner_result is not None:
            after_scanner = self._scanner_result
            scanner_ms = 0.0
        else:
            scanner_started = time.perf_counter()
            if print_enabled(adjustments):
                print_key = print_cache_key(adjustments, self._render_preset)
                if preview_fast:
                    print_key = f"{print_key}:fast"
                if self._print_key == print_key and self._print_result is not None:
                    after_print = self._print_result
                elif self._full_result is not None:
                    # Print stage runs off-thread; keep the last frame until the worker finishes.
                    return self._full_result
                else:
                    after_print = film_base
            else:
                after_print = film_base

            after_scanner = apply_scanner_adjustments(
                after_print,
                adjustments,
                preview_fast=preview_fast,
            )
            self._scanner_key = scanner_key
            self._scanner_result = after_scanner
            scanner_ms = (time.perf_counter() - scanner_started) * 1000.0

        grading_started = time.perf_counter()
        used_gpu = False
        grading = (adjustments or {}).get("grading")
        if not has_grading_adjustments(grading):
            full = after_scanner
            grading_ms = 0.0
            self._full_key = full_key
            self._full_result = full
            self.last_timings = PreviewTimings(
                scanner_ms=scanner_ms,
                grading_ms=grading_ms,
                total_ms=(time.perf_counter() - started) * 1000.0,
                used_gpu=False,
            )
            return full
        gpu = self.gpu_backend
        full = apply_grading_after_scanner(
            after_scanner,
            adjustments,
            grading_context=self._grading_context,
            gpu_backend=gpu if gpu is not None and getattr(gpu, "enabled", False) else None,
        )
        used_gpu = bool(
            gpu is not None and getattr(gpu, "enabled", False) and has_wheel_adjustments(grading)
        )
        grading_ms = (time.perf_counter() - grading_started) * 1000.0

        self._full_key = full_key
        self._full_result = full
        self.last_timings = PreviewTimings(
            scanner_ms=scanner_ms,
            grading_ms=grading_ms,
            total_ms=(time.perf_counter() - started) * 1000.0,
            used_gpu=used_gpu,
        )
        return full

    def histogram_for_full(self, adjustments: dict | None, *, preview_fast: bool = False) -> np.ndarray | None:
        full = self.render_full(adjustments, preview_fast=preview_fast)
        return compute_histograms(full) if full is not None else None

    def render_full_cpu(
        self,
        adjustments: dict | None,
        *,
        preview_fast: bool = False,
    ) -> np.ndarray | None:
        """Render without touching caches (for background workers)."""
        if self._film_base is None:
            return None
        return apply_interactive_adjustments(
            self._film_base,
            adjustments,
            preset=self._render_preset,
            flat_scan=self._flat,
            preview_fast=preview_fast,
            grading_context=self._grading_context,
            gpu_backend=self.gpu_backend if getattr(self.gpu_backend, "enabled", False) else None,
        )
