"""Manual preview pipeline benchmark (run with ``python -m tests.bench_preview``)."""

from __future__ import annotations

import time

import numpy as np

from film_stockpot.ui.preview_engine import PreviewEngine


def _bench(label: str, fn, *, repeats: int = 5) -> None:
    fn()
    start = time.perf_counter()
    for _ in range(repeats):
        fn()
    elapsed_ms = (time.perf_counter() - start) * 1000.0 / repeats
    print(f"{label}: {elapsed_ms:.1f} ms")


def main() -> None:
    film = np.random.default_rng(0).random((1800, 1200, 3), dtype=np.float32)
    settings = {
        "density": 2,
        "gamma": -1,
        "cyan": 3,
        "grading": {
            "shadows": {"hue": 210.0, "sat": 0.4, "lum": -5},
            "midtones": {"hue": 35.0, "sat": 0.2, "lum": 0},
            "highlights": {"hue": 45.0, "sat": 0.3, "lum": 8},
            "blending": 55,
            "balance": 10,
        },
    }
    engine = PreviewEngine(preview_max=1800, drag_preview_max=1200)
    engine.set_film_base(film, None)

    _bench("first full render", lambda: engine.render_full(settings))
    _bench("cached full render", lambda: engine.render_full(settings))
    _bench("fast drag render", lambda: engine.render_full(settings, preview_fast=True))


if __name__ == "__main__":
    main()
