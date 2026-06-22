"""Application theming helpers."""

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


def apply_dark_theme(app: QApplication) -> None:
    """Apply a dark palette and base stylesheet to the application."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, QColor(86, 156, 214))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 122, 204))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    app.setStyleSheet(
        """
        QToolBar {
            background: #2d2d30;
            border: none;
            spacing: 6px;
            padding: 4px;
        }
        QToolButton {
            background: #3e3e42;
            color: #dcdcdc;
            border: 1px solid #555555;
            border-radius: 4px;
            padding: 6px 12px;
        }
        QToolButton:hover {
            background: #4f4f53;
        }
        QToolButton:pressed {
            background: #007acc;
        }

        QDockWidget {
            color: #dcdcdc;
        }
        QDockWidget::title {
            background: #2d2d30;
            padding: 6px 10px;
            border-bottom: 1px solid #3a3a3e;
        }

        QPushButton {
            background: #3a3a3e;
            color: #dcdcdc;
            border: 1px solid #4a4a50;
            border-radius: 5px;
            padding: 6px 12px;
        }
        QPushButton:hover {
            background: #45454a;
        }
        QPushButton:pressed {
            background: #2d6da3;
        }
        QPushButton:disabled {
            color: #6a6a6e;
            background: #303033;
            border-color: #3a3a3e;
        }
        QPushButton#primaryButton {
            background: #0a84d8;
            border: 1px solid #2d8fd8;
            color: #ffffff;
            font-weight: bold;
            padding: 8px 18px;
        }
        QPushButton#primaryButton:hover {
            background: #1a90e0;
        }
        QPushButton#primaryButton:pressed {
            background: #0869ad;
        }

        QListWidget {
            background: #232326;
            border: none;
            outline: none;
        }
        QListWidget::item {
            color: #c8c8cc;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 4px;
            margin: 3px;
        }
        QListWidget::item:hover {
            background: #303034;
        }
        QListWidget::item:selected {
            background: #0a4a78;
            border: 1px solid #2d8fd8;
            color: #ffffff;
        }

        QScrollBar:vertical {
            background: transparent;
            width: 10px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #4a4a50;
            min-height: 30px;
            border-radius: 5px;
        }
        QScrollBar::handle:vertical:hover {
            background: #5a5a62;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: transparent;
        }
        """
    )
