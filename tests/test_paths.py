"""Tests for frozen/runtime path resolution."""

from film_stockpot import paths


def test_repo_root_contains_film_presets() -> None:
    presets = paths.repo_root() / "FilmPresets"
    assert presets.is_dir()
    assert (presets / "_index.json").is_file()
