"""Smoke tests for the UI layer."""

from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from pathlib import Path

from film_stockpot import __version__
from film_stockpot.image.scanner import NEUTRAL
from film_stockpot.ui.main_window import MainWindow
from film_stockpot.ui.widgets.film_strip import FilmStripPanel
from film_stockpot.ui.widgets.image_viewer import ImageViewer
from film_stockpot.ui.widgets.scanner_panel import ScannerPanel


def test_main_window_creates(qapp: QApplication) -> None:
    window = MainWindow()
    assert window.windowTitle() == f"Film Stockpot {__version__}"
    assert isinstance(window.centralWidget(), ImageViewer)


def test_scanner_panel_set_settings_round_trips(qapp: QApplication) -> None:
    panel = ScannerPanel()
    settings = {**NEUTRAL, "density": 7, "cyan": -4, "tone": "Hard"}
    panel.set_settings(settings)
    result = panel.settings()
    assert result["density"] == 7
    assert result["cyan"] == -4
    assert result["tone"] == "Hard"


def test_scanner_panel_set_settings_does_not_emit_changed(qapp: QApplication) -> None:
    panel = ScannerPanel()
    fired = []
    panel.changed.connect(lambda: fired.append(True))
    panel.set_settings({**NEUTRAL, "density": 3})
    assert fired == []


def test_film_strip_exclude_tracks_paths(qapp: QApplication, tmp_path: Path) -> None:
    strip = FilmStripPanel()
    paths = [tmp_path / f"frame_{i}.tiff" for i in range(3)]
    strip.set_files(paths, folder=tmp_path)

    assert strip.excluded_paths() == set()

    strip.set_excluded(str(paths[1]), True)
    assert strip.excluded_paths() == {str(paths[1])}

    strip.set_excluded(str(paths[1]), False)
    assert strip.excluded_paths() == set()


def test_film_strip_set_files_resets_exclusions(qapp: QApplication, tmp_path: Path) -> None:
    strip = FilmStripPanel()
    paths = [tmp_path / "frame_0.tiff"]
    strip.set_files(paths, folder=tmp_path)
    strip.set_excluded(str(paths[0]), True)

    strip.set_files(paths, folder=tmp_path)
    assert strip.excluded_paths() == set()


def test_image_viewer_scales_image(qapp: QApplication) -> None:
    viewer = ImageViewer()
    viewer.resize(400, 300)

    image = QImage(200, 100, QImage.Format.Format_Grayscale16)
    image.fill(32768)
    viewer.set_image(image)

    pixmap = viewer._label.pixmap()
    assert pixmap is not None
    assert not pixmap.isNull()
    assert pixmap.width() <= 400
    assert pixmap.height() <= 300
