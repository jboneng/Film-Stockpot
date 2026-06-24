"""Interactive image viewer with zoom, pan, and optional split compare."""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QLabel, QWidget


class _SplitOverlay(QGraphicsItem):
    """Divider line, drag handle, and Before/After labels in scene coordinates."""

    _HANDLE_RADIUS = 22
    _HIT_PAD = 28

    def __init__(self) -> None:
        super().__init__()
        self._ratio = 0.5
        self._image_width = 1
        self._image_height = 1
        self.setZValue(100)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)

    def set_geometry(self, width: int, height: int, ratio: float) -> None:
        self.prepareGeometryChange()
        self._image_width = max(1, width)
        self._image_height = max(1, height)
        self._ratio = max(0.05, min(0.95, ratio))
        self.update()

    def split_x(self) -> float:
        return self._ratio * self._image_width

    def boundingRect(self) -> QRectF:  # noqa: N802
        x = self.split_x()
        return QRectF(x - self._HIT_PAD, 0, self._HIT_PAD * 2, self._image_height)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:  # noqa: N802
        width = self._image_width
        height = self._image_height
        x = self.split_x()
        center_y = height / 2

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawLine(int(x), 0, int(x), int(height))

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawEllipse(QPointF(x, center_y), self._HANDLE_RADIUS, self._HANDLE_RADIUS)

        arrow_half = 7
        arrow_y = 4
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPolygon(
            [
                QPointF(x - arrow_half - 4, center_y),
                QPointF(x - 4, center_y - arrow_y),
                QPointF(x - 4, center_y + arrow_y),
            ]
        )
        painter.drawPolygon(
            [
                QPointF(x + arrow_half + 4, center_y),
                QPointF(x + 4, center_y - arrow_y),
                QPointF(x + 4, center_y + arrow_y),
            ]
        )

        self._draw_label(painter, "Before", 12, 12)
        after_width = 52
        self._draw_label(painter, "After", width - after_width - 12, 12, width=after_width)

    def _draw_label(
        self,
        painter: QPainter,
        text: str,
        x: float,
        y: float,
        *,
        width: float = 58,
    ) -> None:
        height = 24
        rect = QRectF(x, y, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setPen(QColor(255, 255, 255))
        font = QFont(painter.font())
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class ImageViewer(QGraphicsView):
    """Pan/zoom image view with optional before/after split comparison."""

    split_ratio_changed = pyqtSignal(float)

    _MIN_ZOOM = 0.05
    _MAX_ZOOM = 16.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._before_item = QGraphicsPixmapItem()
        self._after_item = QGraphicsPixmapItem()
        self._split_overlay = _SplitOverlay()
        self._scene.addItem(self._before_item)
        self._scene.addItem(self._after_item)
        self._scene.addItem(self._split_overlay)
        self._split_overlay.hide()

        self._empty_label = QLabel("Open a folder to begin.", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)

        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(Qt.GlobalColor.black)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMouseTracking(True)

        self._before_pixmap = QPixmap()
        self._after_pixmap = QPixmap()
        self._split_enabled = False
        self._split_ratio = 0.5
        self._dragging_split = False
        self._panning = False
        self._pan_start = QPoint()
        self._has_image = False
        self._user_zoomed = False

    def set_single_image(self, image: QImage | None) -> None:
        """Show one image across the full viewport."""
        self._split_enabled = False
        self._split_overlay.hide()
        if image is None or image.isNull():
            self._clear_images()
            return
        pixmap = QPixmap.fromImage(image)
        self._before_pixmap = pixmap
        self._after_pixmap = pixmap
        self._apply_pixmaps()
        self._has_image = True
        self._empty_label.hide()
        if not self._user_zoomed:
            self.fit_in_view()

    def set_split_images(
        self,
        before: QImage | None,
        after: QImage | None,
        *,
        ratio: float | None = None,
    ) -> None:
        """Show a draggable before/after split between two images."""
        self._split_enabled = True
        if before is None or after is None or before.isNull() or after.isNull():
            self._clear_images()
            return
        self._before_pixmap = QPixmap.fromImage(before)
        self._after_pixmap = QPixmap.fromImage(after)
        if ratio is not None:
            self._split_ratio = max(0.05, min(0.95, ratio))
        self._apply_pixmaps()
        self._split_overlay.show()
        self._has_image = True
        self._empty_label.hide()
        if not self._user_zoomed:
            self.fit_in_view()

    def split_ratio(self) -> float:
        return self._split_ratio

    def set_split_ratio(self, ratio: float) -> None:
        ratio = max(0.05, min(0.95, ratio))
        if abs(ratio - self._split_ratio) < 1e-4:
            return
        self._split_ratio = ratio
        if self._split_enabled and self._has_image:
            self._apply_pixmaps()

    def clear_image(self) -> None:
        self._clear_images()

    def fit_in_view(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            return
        self._user_zoomed = False
        self.resetTransform()
        self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_to_actual_size(self) -> None:
        if not self._has_image:
            return
        self._user_zoomed = True
        self.resetTransform()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._empty_label.setGeometry(self.viewport().geometry())
        if self._has_image and not self._user_zoomed:
            self.fit_in_view()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._has_image:
            super().wheelEvent(event)
            return
        self._user_zoomed = True
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current = self.transform().m11()
        new_scale = max(self._MIN_ZOOM, min(self._MAX_ZOOM, current * factor))
        self.setTransform(self.transform().scale(new_scale / current, new_scale / current))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._has_image:
            super().mousePressEvent(event)
            return

        if self._split_enabled and event.button() == Qt.MouseButton.LeftButton:
            if self._near_split(event.position()):
                self._dragging_split = True
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                event.accept()
                return

        if event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton} or (
            event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._dragging_split and self._split_enabled:
            ratio = self._ratio_from_viewport(event.position())
            self.set_split_ratio(ratio)
            self.split_ratio_changed.emit(self._split_ratio)
            event.accept()
            return

        if self._panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        if self._split_enabled and self._near_split(event.position()):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging_split = False
        if self._panning:
            self._panning = False
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._has_image:
            self.fit_in_view()
        super().mouseDoubleClickEvent(event)

    def _clear_images(self) -> None:
        self._before_pixmap = QPixmap()
        self._after_pixmap = QPixmap()
        self._before_item.setPixmap(QPixmap())
        self._after_item.setPixmap(QPixmap())
        self._split_overlay.hide()
        self._has_image = False
        self._user_zoomed = False
        self._dragging_split = False
        self.resetTransform()
        self._empty_label.show()
        self._empty_label.raise_()

    def _apply_pixmaps(self) -> None:
        if self._before_pixmap.isNull() or self._after_pixmap.isNull():
            return

        width = self._before_pixmap.width()
        height = self._before_pixmap.height()
        self._before_item.setVisible(True)

        if self._split_enabled:
            split_x = max(1, min(width - 1, int(round(width * self._split_ratio))))
            self._split_ratio = split_x / width
            self._before_item.setPixmap(self._before_pixmap.copy(0, 0, split_x, height))
            self._before_item.setPos(0, 0)
            self._after_item.setPixmap(self._after_pixmap.copy(split_x, 0, width - split_x, height))
            self._after_item.setPos(split_x, 0)
            self._after_item.setVisible(True)
            self._split_overlay.set_geometry(width, height, self._split_ratio)
            self._scene.setSceneRect(0, 0, width, height)
            return

        self._after_item.setVisible(False)
        self._before_item.setPixmap(self._before_pixmap)
        self._before_item.setPos(0, 0)
        self._scene.setSceneRect(0, 0, width, height)

    def _ratio_from_viewport(self, viewport_pos: QPointF) -> float:
        scene_pos = self.mapToScene(viewport_pos.toPoint())
        width = max(1, self._before_pixmap.width())
        return max(0.05, min(0.95, scene_pos.x() / width))

    def _near_split(self, viewport_pos: QPointF) -> bool:
        scene_pos = self.mapToScene(viewport_pos.toPoint())
        split_x = self._split_ratio * max(1, self._before_pixmap.width())
        tolerance = self._viewport_to_scene_distance(24)
        return abs(scene_pos.x() - split_x) <= tolerance

    def _viewport_to_scene_distance(self, pixels: float) -> float:
        origin = self.mapToScene(QPoint(0, 0))
        offset = self.mapToScene(QPoint(int(pixels), 0))
        return abs(offset.x() - origin.x())
