"""Tests for preview stage helpers."""

import numpy as np

from film_stockpot.ui.preview_stages import PreviewStage, STAGE_LABELS, compute_base_graded, compute_full_graded


def test_stage_labels_cover_all_stages() -> None:
    assert set(STAGE_LABELS) == set(PreviewStage)


def test_compute_base_graded_returns_array() -> None:
    flat = np.full((4, 4, 3), 1000, dtype=np.uint16)
    result = compute_base_graded(flat, None)
    assert result.shape == flat.shape


def test_compute_full_graded_returns_array() -> None:
    film = np.full((4, 4, 3), 1000, dtype=np.uint16)
    result = compute_full_graded(film, None)
    assert result.shape == film.shape
