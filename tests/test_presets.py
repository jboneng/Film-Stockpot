"""Tests for preset discovery and loading."""

from film_stockpot.presets.loader import find_presets_dir, get_preset, load_grouped_presets


def test_presets_directory_exists() -> None:
    assert find_presets_dir().is_dir()


def test_load_grouped_presets_returns_all_stocks() -> None:
    groups = load_grouped_presets()
    total = sum(len(group.presets) for group in groups)

    assert len(groups) >= 1
    assert total == 20


def test_every_preset_has_a_pipeline() -> None:
    for group in load_grouped_presets():
        for preset in group.presets:
            assert "pipeline" in preset.data, f"{preset.id} missing pipeline"


def test_get_preset_by_id() -> None:
    preset = get_preset("kodak_portra_400")
    assert preset.name == "Kodak Portra 400"


def test_get_ilford_delta_3200() -> None:
    preset = get_preset("ilford_delta_3200")
    assert preset.name == "Ilford Delta 3200"
    assert preset.data["monochrome"] is True
    assert preset.data["film"]["base_iso"] == 1000
    assert preset.data["film"]["recommended_ei"] == 3200
