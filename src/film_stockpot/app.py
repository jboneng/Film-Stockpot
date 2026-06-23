"""Application entry point."""

import sys

from PyQt6.QtWidgets import QApplication

from film_stockpot import __version__
from film_stockpot.ui.main_window import MainWindow
from film_stockpot.ui.theme import apply_dark_theme


def main() -> int:
    """Create the application and run the event loop."""
    app = QApplication(sys.argv)
    app.setApplicationName("Film Stockpot")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Film Stockpot")
    apply_dark_theme(app)

    window = MainWindow()
    window.showMaximized()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
