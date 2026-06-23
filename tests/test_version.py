"""Tests for version metadata and the bump helper."""

import importlib.util
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_INIT = _ROOT / "src" / "film_stockpot" / "__init__.py"


def _load_bump_module():
    spec = importlib.util.spec_from_file_location("bump_version", _ROOT / "scripts" / "bump_version.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_version_files_match() -> None:
    pyproject_version = re.search(r'^version = "(\d+\.\d+\.\d+)"$', _PYPROJECT.read_text(), re.M).group(1)
    init_version = re.search(r'^__version__ = "(\d+\.\d+\.\d+)"$', _INIT.read_text(), re.M).group(1)
    assert pyproject_version == init_version


def test_verify_version_sync() -> None:
    bump = _load_bump_module()
    assert bump.verify_version_sync() == bump._format_version(*bump._read_pyproject_version())


def test_bump_build_increments_third_component(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bump = _load_bump_module()
    pyproject = tmp_path / "pyproject.toml"
    init_file = tmp_path / "src" / "film_stockpot" / "__init__.py"
    init_file.parent.mkdir(parents=True)
    pyproject.write_text('version = "0.1.3"\n', encoding="utf-8")
    init_file.write_text('__version__ = "0.1.3"\n', encoding="utf-8")
    monkeypatch.setattr(bump, "_PYPROJECT", pyproject)
    monkeypatch.setattr(bump, "_INIT", init_file)
    assert bump._write_version(0, 1, 4) == "0.1.4"


def test_bump_minor_increments_second_and_resets_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bump = _load_bump_module()
    pyproject = tmp_path / "pyproject.toml"
    init_file = tmp_path / "src" / "film_stockpot" / "__init__.py"
    init_file.parent.mkdir(parents=True)
    pyproject.write_text('version = "0.1.3"\n', encoding="utf-8")
    init_file.write_text('__version__ = "0.1.3"\n', encoding="utf-8")
    monkeypatch.setattr(bump, "_PYPROJECT", pyproject)
    monkeypatch.setattr(bump, "_INIT", init_file)
    assert bump._write_version(0, 2, 1) == "0.2.1"


def test_write_version_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bump = _load_bump_module()
    pyproject = tmp_path / "pyproject.toml"
    init_file = tmp_path / "src" / "film_stockpot" / "__init__.py"
    init_file.parent.mkdir(parents=True)
    pyproject.write_text('version = "1.2.3"\n', encoding="utf-8")
    init_file.write_text('__version__ = "1.2.3"\n', encoding="utf-8")

    monkeypatch.setattr(bump, "_PYPROJECT", pyproject)
    monkeypatch.setattr(bump, "_INIT", init_file)

    assert bump._write_version(4, 5, 6) == "4.5.6"
    assert 'version = "4.5.6"' in pyproject.read_text(encoding="utf-8")
    assert '__version__ = "4.5.6"' in init_file.read_text(encoding="utf-8")
