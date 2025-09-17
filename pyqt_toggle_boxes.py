from __future__ import annotations

import sys
from typing import Optional, Tuple

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QBrush, QColor, QPen, QFont, QPainter, QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QStyleOptionGraphicsItem,
    QWidget,
    QGraphicsProxyWidget,
    QTextEdit,
    QLineEdit,
)


CANVAS_BG = QColor("#f6f6f6")
PARENT_FILL = QColor("#7ec3ff")
PARENT_OUTLINE = QColor("#1c7ed6")
HEADER_FILL = QColor("#5aa9e6")
TEXT_COLOR = QColor("#0b2e4e")
CHILD_FILL = QColor("#b2e3ff")
CHILD_OUTLINE = QColor("#1c7ed6")
HEADER_HEIGHT = 36
PARENT_COLLAPSED_HEIGHT = HEADER_HEIGHT + 8
PARENT_EXPANDED_EXTRA = 220


class ToggleTriangle(QGraphicsItem):
    def __init__(self, parent: QGraphicsItem):
        super().__init__(parent)
        self.expanded = True
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, 14, 14)

    def paint(self, painter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        painter.setBrush(QBrush(TEXT_COLOR))
        painter.setPen(Qt.PenStyle.NoPen)
        if self.expanded:
            # Down triangle
            points = [QPointF(1, 3), QPointF(13, 3), QPointF(7, 12)]
        else:
            # Right triangle
            points = [QPointF(3, 1), QPointF(3, 13), QPointF(12, 7)]
        painter.drawPolygon(*points)

    def mousePressEvent(self, event):
        event.accept()
        # Let parent box toggle
        parent = self.parentItem()
        if hasattr(parent, 'expand'):
            parent.expand(not parent.expanded)
            if hasattr(parent, 'repositionAttachedChildren'):
                parent.repositionAttachedChildren()


class ResizeHandle(QGraphicsRectItem):
    def __init__(self, owner: 'BoxBase'):
        super().__init__(-6, -6, 12, 12, owner)
        self.owner = owner
        self.setBrush(QBrush(QColor('#333333')))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setZValue(10)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self._dragging = False

    def updatePosition(self):
        r = self.owner.rect()
        self.setPos(r.x() + r.width(), r.y() + r.height())

    def mousePressEvent(self, event):
        self._dragging = True
        self._start = event.scenePos()
        self._start_rect = QRectF(self.owner.rect())
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        delta = event.scenePos() - self._start
        new_w = max(120, self._start_rect.width() + delta.x())
        new_h = max(80, self._start_rect.height() + delta.y())
        self.owner.resizeTo(new_w, new_h)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()


class BoxBase(QGraphicsRectItem):
    def resizeTo(self, w: float, h: float):
        r = self.rect()
        self.setRect(r.x(), r.y(), w, h)
        if hasattr(self, 'onResized'):
            self.onResized()


class ChildBox(BoxBase):
    def __init__(self, x: float, y: float, w: float, h: float, title: str, parent_box: 'ParentBox'):
        super().__init__(x, y, w, h)
        self.parent_box = parent_box
        self.attached_to_parent = True
        self.relative_offset = QPointF(0, 0)  # relative to parent's inner top-left
        self.setBrush(QBrush(CHILD_FILL))
        self.setPen(QPen(CHILD_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(2)

        # Title
        self.title = QGraphicsTextItem(title, self)
        self.title.setDefaultTextColor(TEXT_COLOR)
        self.title.setFont(QFont("Helvetica", 11, QFont.Weight.Bold))
        self.title.setPos(10, 8)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditable)

        # Body
        self.body = QGraphicsTextItem("Body...", self)
        self.body.setDefaultTextColor(TEXT_COLOR)
        self.body.setFont(QFont("Helvetica", 10))
        self.body.setTextWidth(w - 20)
        self.body.setPos(10, 32)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)

        # Resize handle
        self.resizer = ResizeHandle(self)
        self.onResized()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Attach/detach based on center point inside parent's inner rect
        center = self.mapToScene(self.rect().center())
        if self.parent_box.isPointInsideBody(center):
            self.attached_to_parent = True
            # store relative offset
            self.relative_offset = self.scenePos() - self.parent_box.innerTopLeftScene()
        else:
            self.attached_to_parent = False

    def onResized(self):
        # Keep text widths within rect
        r = self.rect()
        self.body.setTextWidth(max(10, r.width() - 20))
        self.resizer.updatePosition()


class HeaderItem(QGraphicsRectItem):
    def __init__(self, parent: 'ParentBox', x: float, y: float, w: float, h: float):
        super().__init__(x, y, w, h, parent)
        self.parent_box = parent
        self.setBrush(QBrush(HEADER_FILL))
        self.setPen(QPen(PARENT_OUTLINE, 2))
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event):
        # Toggle on single click anywhere in header
        self.parent_box.expand(not self.parent_box.expanded)
        self.parent_box.repositionAttachedChildren()
        event.accept()


class ParentBox(BoxBase):
    def __init__(self, x1: float, y1: float, x2: float):
        super().__init__(x1, y1, x2 - x1, PARENT_COLLAPSED_HEIGHT)
        self.setBrush(QBrush(PARENT_FILL))
        self.setPen(QPen(PARENT_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self.expanded = True

        # Header rect (visual + toggler)
        self.header = HeaderItem(self, self.rect().x(), self.rect().y(), self.rect().width(), HEADER_HEIGHT)

        # Title
        self.title = QGraphicsTextItem("TEXT BOX WITH TOGGLE STATE", self)
        self.title.setDefaultTextColor(TEXT_COLOR)
        self.title.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        self.title.setPos(self.rect().x() + 24, self.rect().y() + 9)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditable)

        # Toggle triangle
        self.toggle = ToggleTriangle(self)
        self.toggle.setPos(self.rect().x() + 6, self.rect().y() + 11)

        # Body text area
        self.body = QGraphicsTextItem("Body...", self)
        self.body.setDefaultTextColor(TEXT_COLOR)
        self.body.setFont(QFont("Helvetica", 10))
        self.body.setTextWidth(self.rect().width() - 24)
        self.body.setPos(self.rect().x() + 12, self.rect().y() + HEADER_HEIGHT + 12)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)

        self.children: list[ChildBox] = []
        self._last_pos = self.pos()

        # Resize handle
        self.resizer = ResizeHandle(self)
        self.expand(True)

    def expand(self, expanded: bool):
        self.expanded = expanded
        self.toggle.expanded = expanded
        self.toggle.update()
        if expanded:
            new_h = HEADER_HEIGHT + PARENT_EXPANDED_EXTRA
        else:
            new_h = PARENT_COLLAPSED_HEIGHT
        r = self.rect()
        self.setRect(r.x(), r.y(), r.width(), new_h)
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.body.setVisible(expanded)
        # Only hide attached children when collapsed; detached remain visible
        for c in self.children:
            if c.attached_to_parent:
                c.setVisible(expanded)
        self.onResized()

    def onResized(self):
        r = self.rect()
        self.body.setTextWidth(max(10, r.width() - 24))
        self.resizer.updatePosition()
        # Keep header width aligned
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        # Keep toggle/title anchored
        self.toggle.setPos(r.x() + 6, r.y() + 11)
        self.title.setPos(r.x() + 24, r.y() + 9)
        self.body.setPos(r.x() + 12, r.y() + HEADER_HEIGHT + 12)
        # Reposition attached children to their relative offsets
        self.repositionAttachedChildren()

    def isPointInsideBody(self, scene_point: QPointF) -> bool:
        if not self.expanded:
            return False
        r = self.rect()
        inner = QRectF(r.x() + 6, r.y() + HEADER_HEIGHT + 6, r.width() - 12, r.height() - HEADER_HEIGHT - 12)
        return inner.contains(self.mapFromScene(scene_point))

    def innerTopLeftScene(self) -> QPointF:
        r = self.rect()
        p_local = QPointF(r.x() + 12, r.y() + HEADER_HEIGHT + 12)
        return self.mapToScene(p_local)

    def repositionAttachedChildren(self):
        if not self.children:
            return
        base = self.innerTopLeftScene()
        for c in self.children:
            if c.attached_to_parent:
                c.setPos(base + c.relative_offset)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # Move attached children by same delta
            delta = self.pos() - self._last_pos
            if not delta.isNull():
                for c in self.children:
                    if c.attached_to_parent:
                        c.setPos(c.pos() + delta)
            self._last_pos = self.pos()
        return super().itemChange(change, value)


class View(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setRenderHints(
            self.renderHints()
            | QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setBackgroundBrush(QBrush(CANVAS_BG))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)

        scene = QGraphicsScene(0, 0, 1200, 700)
        self.setScene(scene)

        # Parent
        self.parent = ParentBox(40, 40, 1140)
        scene.addItem(self.parent)

        # Children
        c1 = ChildBox(0, 0, 440, 120, "SEQ 1", self.parent)
        c2 = ChildBox(0, 0, 440, 120, "SEQ 2", self.parent)
        self.parent.children.extend([c1, c2])
        scene.addItem(c1)
        scene.addItem(c2)
        # Initial child placement uses relative offsets of zero; set them and reposition
        for c in [c1, c2]:
            c.relative_offset = c.scenePos() - self.parent.innerTopLeftScene()
        self.parent.repositionAttachedChildren()

        # Allow clicking outside text to end editing
        self.setInteractive(True)

    # Copy/Paste support and bookkeeping
    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_C) and (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)):
            items = self.scene().selectedItems()
            self._clipboard = None
            if items:
                it = items[0]
                if isinstance(it, ChildBox):
                    self._clipboard = ('child', {
                        'w': it.rect().width(), 'h': it.rect().height(),
                        'title': it.title.toPlainText(), 'body': it.body.toPlainText()
                    })
                elif isinstance(it, ParentBox):
                    self._clipboard = ('parent', {
                        'w': it.rect().width(), 'h': it.rect().height(),
                        'title': it.title.toPlainText(), 'body': it.body.toPlainText()
                    })
            event.accept()
            return
        if (event.key() == Qt.Key.Key_V) and (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)):
            if hasattr(self, '_clipboard') and self._clipboard:
                kind, data = self._clipboard
                pos = self.mapToScene(self.mapFromGlobal(QCursor.pos()))
                pos += QPointF(20, 20)
                if kind == 'child':
                    c = ChildBox(pos.x(), pos.y(), data['w'], data['h'], data['title'], self.parent)
                    c.body.setPlainText(data['body'])
                    c.attached_to_parent = False
                    self.scene().addItem(c)
                elif kind == 'parent':
                    p = ParentBox(pos.x(), pos.y(), pos.x() + data['w'])
                    p.resizeTo(data['w'], data['h'])
                    p.title.setPlainText(data['title'])
                    p.body.setPlainText(data['body'])
                    self.scene().addItem(p)
            event.accept()
            return
        super().keyPressEvent(event)

    # Click outside any text to end editing and remember last click for paste
    def mousePressEvent(self, event):
        focused = self.scene().focusItem()
        if isinstance(focused, QGraphicsTextItem):
            focused.clearFocus()
        self._last_click = self.mapToScene(event.position().toPoint())
        super().mousePressEvent(event)


def main():
    app = QApplication(sys.argv)
    view = View()
    view.setWindowTitle("PyQt6: Toggleable Parent and Draggable Children")
    view.resize(1200, 700)
    view.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
