"""Tests for recent-folder persistence."""

from PyQt6.QtCore import QSettings

from film_stockpot.ui.recent_folders import last_folder, load_recent_folders, remember_folder


def _clear_settings() -> None:
    settings = QSettings("Film Stockpot", "FilmStockpot")
    settings.remove("paths/last_folder")
    settings.remove("paths/recent_folders")


def test_remember_folder_tracks_last_and_recents() -> None:
    _clear_settings()
    remember_folder(r"C:\rolls\roll_a")
    remember_folder(r"C:\rolls\roll_b")

    assert last_folder() == r"C:\rolls\roll_b"
    assert load_recent_folders()[:2] == [r"C:\rolls\roll_b", r"C:\rolls\roll_a"]

    remember_folder(r"C:\rolls\roll_a")
    assert load_recent_folders()[0] == r"C:\rolls\roll_a"
    _clear_settings()
