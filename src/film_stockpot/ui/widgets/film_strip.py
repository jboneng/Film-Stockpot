"""Vertical film-strip browser for TIFF files in a folder."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from film_stockpot.sidecar import has_sidecar
from film_stockpot.ui.icons import load_icon, load_pixmap
from film_stockpot.ui.workers import ThumbnailWorker


class FilmStripPanel(QWidget):
    """Scrollable vertical strip of TIFF thumbnails with an empty state."""

    image_selected = pyqtSignal(str)
    open_folder_requested = pyqtSignal()
    clear_sidecar_requested = pyqtSignal(str)
    exclude_changed = pyqtSignal(str, bool)

    _THUMB_SIZE = 160
    _PATH_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._threadpool = QThreadPool.globalInstance()
        self._thumb_generation = 0
        self._folder_name = ""
        self._edited: set[str] = set()
        self._excluded: set[str] = set()
        self._base_pixmaps: dict[str, QPixmap] = {}

        self._placeholder = self._make_placeholder()
        self._placeholder_icon = QIcon(self._placeholder)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._build_empty_page())
        self._stack.addWidget(self._build_content_page())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

        self._stack.setCurrentIndex(0)

    def _build_empty_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 24, 16, 24)
        layout.setSpacing(12)
        layout.addStretch(1)

        icon = QLabel(page)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setPixmap(load_pixmap("film.svg", 56))
        layout.addWidget(icon)

        message = QLabel("No folder open.\nChoose a folder of TIFF images to begin.", page)
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("color: #9a9aa0;")
        layout.addWidget(message)

        open_button = QPushButton("Open Folder", page)
        open_button.setObjectName("primaryButton")
        open_button.setIcon(load_icon("folder.svg", 18))
        open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        open_button.clicked.connect(self.open_folder_requested.emit)
        layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addStretch(2)
        return page

    def _build_content_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._folder_label = QLabel("", page)
        self._folder_label.setStyleSheet("font-weight: bold; color: #e8e8ea;")
        layout.addWidget(self._folder_label)

        self._count_label = QLabel("", page)
        self._count_label.setStyleSheet("color: #9a9aa0; font-size: 11px;")
        layout.addWidget(self._count_label)

        divider = QFrame(page)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #3a3a3e;")
        layout.addWidget(divider)

        self._list = QListWidget(page)
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QSize(self._THUMB_SIZE, self._THUMB_SIZE))
        self._list.setGridSize(QSize(self._THUMB_SIZE + 22, self._THUMB_SIZE + 40))
        self._list.setUniformItemSizes(True)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setFlow(QListWidget.Flow.TopToBottom)
        self._list.setWrapping(False)
        self._list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._list, 1)

        return page

    def set_files(self, paths: list[Path], folder: Path | None = None) -> None:
        self._thumb_generation += 1
        generation = self._thumb_generation
        self._list.clear()
        self._edited.clear()
        self._excluded.clear()
        self._base_pixmaps.clear()

        self._folder_name = folder.name if folder else ""

        if not paths:
            self._folder_label.setText(self._folder_name or "Folder")
            self._folder_label.setToolTip(str(folder) if folder else "")
            self._count_label.setText("No TIFF images found")
            self._stack.setCurrentIndex(1)
            self._update_header_elide()
            return

        self._count_label.setText(f"{len(paths)} image{'s' if len(paths) != 1 else ''}")
        self._folder_label.setToolTip(str(folder) if folder else "")

        for path in paths:
            key = str(path)
            item = QListWidgetItem(path.name)
            item.setData(self._PATH_ROLE, key)
            item.setToolTip(path.name)
            item.setIcon(self._placeholder_icon)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._base_pixmaps[key] = self._placeholder
            self._list.addItem(item)
            self._load_thumbnail(item, generation)

        self._stack.setCurrentIndex(1)
        self._update_header_elide()
        self._list.setCurrentRow(0)

    def clear(self) -> None:
        self._thumb_generation += 1
        self._list.clear()
        self._edited.clear()
        self._excluded.clear()
        self._base_pixmaps.clear()
        self._folder_name = ""
        self._stack.setCurrentIndex(0)

    def set_enabled(self, enabled: bool) -> None:
        self._list.setEnabled(enabled)

    def paths(self) -> list[str]:
        """Return every image path currently shown, in display order."""
        return [
            self._list.item(index).data(self._PATH_ROLE)
            for index in range(self._list.count())
        ]

    def current_index(self) -> int:
        """Return the 1-based index of the selected frame, or 1 if none."""
        row = self._list.currentRow()
        return row + 1 if row >= 0 else 1

    def set_edited(self, path: str, edited: bool) -> None:
        """Toggle the 'edited' badge for the item matching ``path``."""
        if edited:
            self._edited.add(path)
        else:
            self._edited.discard(path)
        item = self._find_item(path)
        if item is not None:
            self._refresh_item_icon(item)

    def set_excluded(self, path: str, excluded: bool) -> None:
        """Toggle whether ``path`` is excluded from batch export."""
        if excluded:
            self._excluded.add(path)
        else:
            self._excluded.discard(path)
        item = self._find_item(path)
        if item is not None:
            self._refresh_item_icon(item)

    def excluded_paths(self) -> set[str]:
        """Return paths the user has excluded from batch export."""
        return set(self._excluded)

    def _find_item(self, path: str) -> QListWidgetItem | None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(self._PATH_ROLE) == path:
                return item
        return None

    def _on_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        path = item.data(self._PATH_ROLE)
        excluded = path in self._excluded

        menu = QMenu(self)
        clear_action = menu.addAction("Clear sidecar file")
        clear_action.setEnabled(has_sidecar(path) or path in self._edited)
        menu.addSeparator()
        if excluded:
            exclude_action = menu.addAction("Include in batch export")
        else:
            exclude_action = menu.addAction("Exclude from batch export")

        chosen = menu.exec(self._list.viewport().mapToGlobal(pos))
        if chosen is clear_action:
            self.clear_sidecar_requested.emit(path)
        elif chosen is exclude_action:
            self.set_excluded(path, not excluded)
            self.exclude_changed.emit(path, not excluded)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_header_elide()

    def _update_header_elide(self) -> None:
        if not self._folder_name:
            self._folder_label.setText("")
            return
        metrics = QFontMetrics(self._folder_label.font())
        available = max(40, self._folder_label.width())
        elided = metrics.elidedText(self._folder_name, Qt.TextElideMode.ElideMiddle, available)
        self._folder_label.setText(elided)

    def _make_placeholder(self) -> QPixmap:
        size = self._THUMB_SIZE
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(52, 52, 56))
        painter.setPen(QPen(QColor(74, 74, 80), 1))
        painter.drawRoundedRect(2, 2, size - 4, size - 4, 6, 6)
        painter.end()
        return pixmap

    def _load_thumbnail(self, item: QListWidgetItem, generation: int) -> None:
        path = item.data(self._PATH_ROLE)
        worker = ThumbnailWorker(path, self._THUMB_SIZE)
        worker.signals.finished.connect(
            lambda image_path, pixmap, gen=generation: self._on_thumbnail_ready(item, image_path, pixmap, gen)
        )
        self._threadpool.start(worker)

    def _on_thumbnail_ready(
        self,
        item: QListWidgetItem,
        path: str,
        pixmap: QPixmap,
        generation: int,
    ) -> None:
        if generation != self._thumb_generation:
            return
        if item.data(self._PATH_ROLE) != path:
            return
        if pixmap.isNull():
            return
        self._base_pixmaps[path] = pixmap
        self._refresh_item_icon(item)

    def _refresh_item_icon(self, item: QListWidgetItem) -> None:
        path = item.data(self._PATH_ROLE)
        base = self._base_pixmaps.get(path, self._placeholder)
        item.setIcon(
            self._compose_icon(base, path in self._edited, path in self._excluded)
        )

    def _compose_icon(self, pixmap: QPixmap, edited: bool, excluded: bool) -> QIcon:
        if not edited and not excluded:
            return QIcon(pixmap)

        badged = QPixmap(pixmap)
        painter = QPainter(badged)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        diameter = 18
        if edited:
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setBrush(QColor(10, 132, 216))
            painter.drawEllipse(6, 6, diameter, diameter)

        if excluded:
            x = badged.width() - diameter - 6
            y = 6
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setBrush(QColor(220, 40, 40))
            painter.drawEllipse(x, y, diameter, diameter)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            inset = 5
            painter.drawLine(x + inset, y + inset, x + diameter - inset, y + diameter - inset)
            painter.drawLine(x + diameter - inset, y + inset, x + inset, y + diameter - inset)

        painter.end()
        return QIcon(badged)

    def _on_current_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        path = current.data(self._PATH_ROLE)
        if path:
            self.image_selected.emit(path)
