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

# Layout constants used for sizing to fit children
INNER_PAD = 12
OUTER_GAP = 20
BEAT_GAP = 12


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


class BeatBox(BoxBase):
    """Leaf node representing a Beat (great-grandchild)."""
    def __init__(self, x: float, y: float, w: float, h: float, title: str, parent_box: 'StepBox | SequenceBox | ParentBox'):
        super().__init__(x, y, w, h)
        self.parent_box = parent_box
        self.attached_to_parent = True
        self.relative_offset = QPointF(0, 0)  # relative to parent's inner top-left
        self.setBrush(QBrush(CHILD_FILL))
        self.setPen(QPen(CHILD_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(4)

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
        self._dragging = False
        self._press_scene_pos: Optional[QPointF] = None
        self._parent_start_pos: Optional[QPointF] = None
        self._moved_enough = False

    def mousePressEvent(self, event):
        # Start drag; defer toggle decision to release if movement is tiny
        self._dragging = True
        self._moved_enough = False
        self._press_scene_pos = event.scenePos()
        self._parent_start_pos = self.parent_box.pos()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        if self._press_scene_pos is None or self._parent_start_pos is None:
            return
        delta = event.scenePos() - self._press_scene_pos
        # Movement threshold to differentiate click vs drag
        if not self._moved_enough and (abs(delta.x()) > 3 or abs(delta.y()) > 3):
            self._moved_enough = True
        if self._moved_enough:
            self.parent_box.setPos(self._parent_start_pos + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        was_drag = self._moved_enough
        self._dragging = False
        self._press_scene_pos = None
        self._parent_start_pos = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if not was_drag:
            # Treat as click: toggle expand/collapse
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

        self.children: list['SequenceBox'] = []
        self._last_pos = self.pos()

        # Resize handle
        self.resizer = ResizeHandle(self)
        self.expand(True)

    def expand(self, expanded: bool):
        self.expanded = expanded
        self.toggle.expanded = expanded
        self.toggle.update()
        if expanded:
            # Fit tallest child if any
            if self.children:
                max_h = 0
                for c in self.children:
                    max_h = max(max_h, c.rect().height())
                new_h = HEADER_HEIGHT + INNER_PAD + max_h + INNER_PAD
            else:
                new_h = HEADER_HEIGHT + PARENT_EXPANDED_EXTRA
        else:
            new_h = PARENT_COLLAPSED_HEIGHT
        r = self.rect()
        self.setRect(r.x(), r.y(), r.width(), new_h)
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.body.setVisible(expanded)
        # Show/hide attached descendants recursively
        self._setAttachedDescendantsVisible(expanded)
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

    def _setAttachedDescendantsVisible(self, visible: bool):
        if not self.children:
            return
        for c in self.children:
            if not getattr(c, 'attached_to_parent', False):
                continue
            c.setVisible(visible)
            # Recurse for nested containers
            if isinstance(c, SequenceBox) or isinstance(c, StepBox):
                c._setAttachedDescendantsVisible(visible)

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


class SequenceBox(BoxBase):
    """Second level container (Sequence). Collapsible, can hold StepBox children."""
    def __init__(self, x1: float, y1: float, x2: float, parent_box: 'ParentBox'):
        super().__init__(x1, y1, x2 - x1, PARENT_COLLAPSED_HEIGHT)
        self.parent_box = parent_box
        self.setBrush(QBrush(QColor('#a8defc')))
        self.setPen(QPen(PARENT_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self.expanded = True

        self.header = HeaderItem(self, self.rect().x(), self.rect().y(), self.rect().width(), HEADER_HEIGHT)
        self.title = QGraphicsTextItem("SEQ", self)
        self.title.setDefaultTextColor(TEXT_COLOR)
        self.title.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        self.title.setPos(self.rect().x() + 24, self.rect().y() + 9)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditable)

        self.toggle = ToggleTriangle(self)
        self.toggle.setPos(self.rect().x() + 6, self.rect().y() + 11)

        self.body = QGraphicsTextItem("Body...", self)
        self.body.setDefaultTextColor(TEXT_COLOR)
        self.body.setFont(QFont("Helvetica", 10))
        self.body.setTextWidth(self.rect().width() - 24)
        self.body.setPos(self.rect().x() + 12, self.rect().y() + HEADER_HEIGHT + 12)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)

        self.children: list['StepBox'] = []
        self._last_pos = self.pos()

        self.resizer = ResizeHandle(self)
        self.expand(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def expand(self, expanded: bool):
        self.expanded = expanded
        self.toggle.expanded = expanded
        self.toggle.update()
        r = self.rect()
        if expanded:
            # Ensure height fits contained steps
            if self.children:
                max_h = 0
                for s in self.children:
                    max_h = max(max_h, s.rect().height())
                new_h = HEADER_HEIGHT + INNER_PAD + max_h + INNER_PAD
            else:
                new_h = HEADER_HEIGHT + 200
        else:
            new_h = PARENT_COLLAPSED_HEIGHT
        self.setRect(r.x(), r.y(), r.width(), new_h)
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.body.setVisible(expanded)
        self._setAttachedDescendantsVisible(expanded)
        self.onResized()

    def onResized(self):
        r = self.rect()
        self.body.setTextWidth(max(10, r.width() - 24))
        self.resizer.updatePosition()
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.toggle.setPos(r.x() + 6, r.y() + 11)
        self.title.setPos(r.x() + 24, r.y() + 9)
        self.body.setPos(r.x() + 12, r.y() + HEADER_HEIGHT + 12)
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
            delta = self.pos() - self._last_pos
            if not delta.isNull():
                for c in self.children:
                    if c.attached_to_parent:
                        c.setPos(c.pos() + delta)
            self._last_pos = self.pos()
        return super().itemChange(change, value)

    def _setAttachedDescendantsVisible(self, visible: bool):
        if not self.children:
            return
        for c in self.children:
            if not getattr(c, 'attached_to_parent', False):
                continue
            c.setVisible(visible)
            if isinstance(c, StepBox):
                c._setAttachedDescendantsVisible(visible)


class StepBox(BoxBase):
    """Third level container (Step). Collapsible, holds BeatBox children."""
    def __init__(self, x1: float, y1: float, x2: float, parent_box: 'SequenceBox'):
        super().__init__(x1, y1, x2 - x1, PARENT_COLLAPSED_HEIGHT)
        self.parent_box = parent_box
        self.setBrush(QBrush(QColor('#c9ecff')))
        self.setPen(QPen(PARENT_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(2)

        self.expanded = True
        # Remember intended content size to restore after collapse/expand
        self._content_width: float = self.rect().width()
        self._content_height: float = self.rect().height()

        self.header = HeaderItem(self, self.rect().x(), self.rect().y(), self.rect().width(), HEADER_HEIGHT)
        self.title = QGraphicsTextItem("STEP", self)
        self.title.setDefaultTextColor(TEXT_COLOR)
        self.title.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        self.title.setPos(self.rect().x() + 24, self.rect().y() + 9)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditable)

        self.toggle = ToggleTriangle(self)
        self.toggle.setPos(self.rect().x() + 6, self.rect().y() + 11)

        self.body = QGraphicsTextItem("Body...", self)
        self.body.setDefaultTextColor(TEXT_COLOR)
        self.body.setFont(QFont("Helvetica", 10))
        self.body.setTextWidth(self.rect().width() - 24)
        self.body.setPos(self.rect().x() + 12, self.rect().y() + HEADER_HEIGHT + 12)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)

        self.children: list[BeatBox] = []
        self._last_pos = self.pos()

        self.resizer = ResizeHandle(self)
        self.expand(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def expand(self, expanded: bool):
        self.expanded = expanded
        self.toggle.expanded = expanded
        self.toggle.update()
        r = self.rect()
        if expanded:
            # Restore to content size ensuring it fits children
            new_w = max(self._content_width, r.width())
            # Compute height to fit beats if any
            if self.children:
                max_right = 0
                total_h = HEADER_HEIGHT + INNER_PAD
                for c in self.children:
                    max_right = max(max_right, c.rect().width())
                total_h += sum(c.rect().height() for c in self.children) + BEAT_GAP * (len(self.children) - 1) + INNER_PAD
                new_h = max(self._content_height, total_h)
            else:
                new_h = max(self._content_height, HEADER_HEIGHT + 120)
        else:
            new_w = r.width()
            new_h = PARENT_COLLAPSED_HEIGHT
        self.setRect(r.x(), r.y(), new_w, new_h)
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.body.setVisible(expanded)
        self._setAttachedDescendantsVisible(expanded)
        self.onResized()

    def onResized(self):
        r = self.rect()
        self.body.setTextWidth(max(10, r.width() - 24))
        self.resizer.updatePosition()
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.toggle.setPos(r.x() + 6, r.y() + 11)
        self.title.setPos(r.x() + 24, r.y() + 9)
        self.body.setPos(r.x() + 12, r.y() + HEADER_HEIGHT + 12)
        self.repositionAttachedChildren()
        # Persist content size when expanded
        if self.expanded:
            self._content_width = r.width()
            self._content_height = r.height()

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
            delta = self.pos() - self._last_pos
            if not delta.isNull():
                for c in self.children:
                    if c.attached_to_parent:
                        c.setPos(c.pos() + delta)
            self._last_pos = self.pos()
        return super().itemChange(change, value)

    def _setAttachedDescendantsVisible(self, visible: bool):
        if not self.children:
            return
        for c in self.children:
            if not getattr(c, 'attached_to_parent', False):
                continue
            c.setVisible(visible)


class ActBox(ParentBox):
    """Top-level container (Act). Always sits at the back (z-index 0)."""
    def __init__(self, x1: float, y1: float, x2: float):
        super().__init__(x1, y1, x2)
        self.setZValue(0)


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

        # Larger scene to accommodate initial nested layout
        scene = QGraphicsScene(0, 0, 3200, 1200)
        self.setScene(scene)

        # Layout constants for neat nesting
        gap = OUTER_GAP
        inner_pad = INNER_PAD
        # Portrait orientation: narrower steps, taller beats
        step_w = 220
        beat_h = 140
        beat_gap = BEAT_GAP
        beats_per_step = 4
        steps_per_sequence = 4

        # Derived sizes
        total_steps_width = steps_per_sequence * step_w + (steps_per_sequence - 1) * gap
        sequence_w = total_steps_width + inner_pad * 2
        step_body_h = beats_per_step * beat_h + (beats_per_step - 1) * beat_gap
        step_h = HEADER_HEIGHT + inner_pad + step_body_h + inner_pad
        seq_h = HEADER_HEIGHT + inner_pad + step_h + inner_pad

        # Act sized to hold two sequences side-by-side
        total_sequences_width = 2 * sequence_w + gap
        act_w = total_sequences_width + inner_pad * 2
        act_h = HEADER_HEIGHT + inner_pad + seq_h + inner_pad

        # Act (parent)
        self.parent = ActBox(40, 40, 40 + act_w)
        self.parent.resizeTo(act_w, act_h)
        scene.addItem(self.parent)

        # Sequences (children of Act)
        s1 = SequenceBox(0, 0, sequence_w, self.parent)
        s1.title.setPlainText("SEQ 1")
        s1.resizeTo(sequence_w, seq_h)
        s2 = SequenceBox(0, 0, sequence_w, self.parent)
        s2.title.setPlainText("SEQ 2")
        s2.resizeTo(sequence_w, seq_h)
        self.parent.children.extend([s1, s2])
        for s in [s1, s2]:
            scene.addItem(s)
        # Attach sequences neatly inside Act
        for idx, s in enumerate([s1, s2]):
            s.relative_offset = QPointF(inner_pad + idx * (sequence_w + gap), HEADER_HEIGHT + inner_pad)
            s.setPos(self.parent.innerTopLeftScene() + s.relative_offset)
            s.attached_to_parent = True
        self.parent.repositionAttachedChildren()

        # Steps under each sequence (4 side by side)
        def add_steps(seq: SequenceBox):
            seq.children.clear()
            for i in range(steps_per_sequence):
                st = StepBox(0, 0, step_w, seq)
                st.title.setPlainText(f"STEP {i + 1}")
                st.resizeTo(step_w, step_h)
                seq.children.append(st)
                scene.addItem(st)
                st.relative_offset = QPointF(inner_pad + i * (step_w + gap), HEADER_HEIGHT + inner_pad)
                st.setPos(seq.innerTopLeftScene() + st.relative_offset)
                st.attached_to_parent = True
        add_steps(s1)
        add_steps(s2)

        # Beats under every step (4 vertical)
        def add_beats(step: 'StepBox'):
            step.children.clear()
            beat_w = step_w - inner_pad * 2
            for j in range(beats_per_step):
                b = BeatBox(0, 0, beat_w, beat_h, f"BEAT {j + 1}", step)
                step.children.append(b)
                scene.addItem(b)
                b.relative_offset = QPointF(inner_pad, HEADER_HEIGHT + inner_pad + j * (beat_h + beat_gap))
                b.setPos(step.innerTopLeftScene() + b.relative_offset)
                b.attached_to_parent = True
        for seq in [s1, s2]:
            for st in seq.children:
                add_beats(st)

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

# Layout constants used for sizing to fit children
INNER_PAD = 12
OUTER_GAP = 20
BEAT_GAP = 12


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


class BeatBox(BoxBase):
    """Leaf node representing a Beat (great-grandchild)."""
    def __init__(self, x: float, y: float, w: float, h: float, title: str, parent_box: 'StepBox | SequenceBox | ParentBox'):
        super().__init__(x, y, w, h)
        self.parent_box = parent_box
        self.attached_to_parent = True
        self.relative_offset = QPointF(0, 0)  # relative to parent's inner top-left
        self.setBrush(QBrush(CHILD_FILL))
        self.setPen(QPen(CHILD_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(4)

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
        self._dragging = False
        self._press_scene_pos: Optional[QPointF] = None
        self._parent_start_pos: Optional[QPointF] = None
        self._moved_enough = False

    def mousePressEvent(self, event):
        # Start drag; defer toggle decision to release if movement is tiny
        self._dragging = True
        self._moved_enough = False
        self._press_scene_pos = event.scenePos()
        self._parent_start_pos = self.parent_box.pos()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return
        if self._press_scene_pos is None or self._parent_start_pos is None:
            return
        delta = event.scenePos() - self._press_scene_pos
        # Movement threshold to differentiate click vs drag
        if not self._moved_enough and (abs(delta.x()) > 3 or abs(delta.y()) > 3):
            self._moved_enough = True
        if self._moved_enough:
            self.parent_box.setPos(self._parent_start_pos + delta)
        event.accept()

    def mouseReleaseEvent(self, event):
        was_drag = self._moved_enough
        self._dragging = False
        self._press_scene_pos = None
        self._parent_start_pos = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if not was_drag:
            # Treat as click: toggle expand/collapse
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

        self.children: list['SequenceBox'] = []
        self._last_pos = self.pos()

        # Resize handle
        self.resizer = ResizeHandle(self)
        self.expand(True)

    def expand(self, expanded: bool):
        self.expanded = expanded
        self.toggle.expanded = expanded
        self.toggle.update()
        if expanded:
            # Fit tallest child if any
            if self.children:
                max_h = 0
                for c in self.children:
                    max_h = max(max_h, c.rect().height())
                new_h = HEADER_HEIGHT + INNER_PAD + max_h + INNER_PAD
            else:
                new_h = HEADER_HEIGHT + PARENT_EXPANDED_EXTRA
        else:
            new_h = PARENT_COLLAPSED_HEIGHT
        r = self.rect()
        self.setRect(r.x(), r.y(), r.width(), new_h)
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.body.setVisible(expanded)
        # Show/hide attached descendants recursively
        self._setAttachedDescendantsVisible(expanded)
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

    def _setAttachedDescendantsVisible(self, visible: bool):
        if not self.children:
            return
        for c in self.children:
            if not getattr(c, 'attached_to_parent', False):
                continue
            c.setVisible(visible)
            # Recurse for nested containers
            if isinstance(c, SequenceBox) or isinstance(c, StepBox):
                c._setAttachedDescendantsVisible(visible)

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


class SequenceBox(BoxBase):
    """Second level container (Sequence). Collapsible, can hold StepBox children."""
    def __init__(self, x1: float, y1: float, x2: float, parent_box: 'ParentBox'):
        super().__init__(x1, y1, x2 - x1, PARENT_COLLAPSED_HEIGHT)
        self.parent_box = parent_box
        self.setBrush(QBrush(QColor('#a8defc')))
        self.setPen(QPen(PARENT_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)

        self.expanded = True

        self.header = HeaderItem(self, self.rect().x(), self.rect().y(), self.rect().width(), HEADER_HEIGHT)
        self.title = QGraphicsTextItem("SEQ", self)
        self.title.setDefaultTextColor(TEXT_COLOR)
        self.title.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        self.title.setPos(self.rect().x() + 24, self.rect().y() + 9)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditable)

        self.toggle = ToggleTriangle(self)
        self.toggle.setPos(self.rect().x() + 6, self.rect().y() + 11)

        self.body = QGraphicsTextItem("Body...", self)
        self.body.setDefaultTextColor(TEXT_COLOR)
        self.body.setFont(QFont("Helvetica", 10))
        self.body.setTextWidth(self.rect().width() - 24)
        self.body.setPos(self.rect().x() + 12, self.rect().y() + HEADER_HEIGHT + 12)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)

        self.children: list['StepBox'] = []
        self._last_pos = self.pos()

        self.resizer = ResizeHandle(self)
        self.expand(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def expand(self, expanded: bool):
        self.expanded = expanded
        self.toggle.expanded = expanded
        self.toggle.update()
        r = self.rect()
        if expanded:
            # Ensure height fits contained steps
            if self.children:
                max_h = 0
                for s in self.children:
                    max_h = max(max_h, s.rect().height())
                new_h = HEADER_HEIGHT + INNER_PAD + max_h + INNER_PAD
            else:
                new_h = HEADER_HEIGHT + 200
        else:
            new_h = PARENT_COLLAPSED_HEIGHT
        self.setRect(r.x(), r.y(), r.width(), new_h)
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.body.setVisible(expanded)
        self._setAttachedDescendantsVisible(expanded)
        self.onResized()

    def onResized(self):
        r = self.rect()
        self.body.setTextWidth(max(10, r.width() - 24))
        self.resizer.updatePosition()
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.toggle.setPos(r.x() + 6, r.y() + 11)
        self.title.setPos(r.x() + 24, r.y() + 9)
        self.body.setPos(r.x() + 12, r.y() + HEADER_HEIGHT + 12)
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
            delta = self.pos() - self._last_pos
            if not delta.isNull():
                for c in self.children:
                    if c.attached_to_parent:
                        c.setPos(c.pos() + delta)
            self._last_pos = self.pos()
        return super().itemChange(change, value)

    def _setAttachedDescendantsVisible(self, visible: bool):
        if not self.children:
            return
        for c in self.children:
            if not getattr(c, 'attached_to_parent', False):
                continue
            c.setVisible(visible)
            if isinstance(c, StepBox):
                c._setAttachedDescendantsVisible(visible)


class StepBox(BoxBase):
    """Third level container (Step). Collapsible, holds BeatBox children."""
    def __init__(self, x1: float, y1: float, x2: float, parent_box: 'SequenceBox'):
        super().__init__(x1, y1, x2 - x1, PARENT_COLLAPSED_HEIGHT)
        self.parent_box = parent_box
        self.setBrush(QBrush(QColor('#c9ecff')))
        self.setPen(QPen(PARENT_OUTLINE, 2))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(2)

        self.expanded = True
        # Remember intended content size to restore after collapse/expand
        self._content_width: float = self.rect().width()
        self._content_height: float = self.rect().height()

        self.header = HeaderItem(self, self.rect().x(), self.rect().y(), self.rect().width(), HEADER_HEIGHT)
        self.title = QGraphicsTextItem("STEP", self)
        self.title.setDefaultTextColor(TEXT_COLOR)
        self.title.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        self.title.setPos(self.rect().x() + 24, self.rect().y() + 9)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditable)

        self.toggle = ToggleTriangle(self)
        self.toggle.setPos(self.rect().x() + 6, self.rect().y() + 11)

        self.body = QGraphicsTextItem("Body...", self)
        self.body.setDefaultTextColor(TEXT_COLOR)
        self.body.setFont(QFont("Helvetica", 10))
        self.body.setTextWidth(self.rect().width() - 24)
        self.body.setPos(self.rect().x() + 12, self.rect().y() + HEADER_HEIGHT + 12)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)

        self.children: list[BeatBox] = []
        self._last_pos = self.pos()

        self.resizer = ResizeHandle(self)
        self.expand(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

    def expand(self, expanded: bool):
        self.expanded = expanded
        self.toggle.expanded = expanded
        self.toggle.update()
        r = self.rect()
        if expanded:
            # Restore to content size ensuring it fits children
            new_w = max(self._content_width, r.width())
            # Compute height to fit beats if any
            if self.children:
                max_right = 0
                total_h = HEADER_HEIGHT + INNER_PAD
                for c in self.children:
                    max_right = max(max_right, c.rect().width())
                total_h += sum(c.rect().height() for c in self.children) + BEAT_GAP * (len(self.children) - 1) + INNER_PAD
                new_h = max(self._content_height, total_h)
            else:
                new_h = max(self._content_height, HEADER_HEIGHT + 120)
        else:
            new_w = r.width()
            new_h = PARENT_COLLAPSED_HEIGHT
        self.setRect(r.x(), r.y(), new_w, new_h)
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.body.setVisible(expanded)
        self._setAttachedDescendantsVisible(expanded)
        self.onResized()

    def onResized(self):
        r = self.rect()
        self.body.setTextWidth(max(10, r.width() - 24))
        self.resizer.updatePosition()
        self.header.setRect(r.x(), r.y(), r.width(), HEADER_HEIGHT)
        self.toggle.setPos(r.x() + 6, r.y() + 11)
        self.title.setPos(r.x() + 24, r.y() + 9)
        self.body.setPos(r.x() + 12, r.y() + HEADER_HEIGHT + 12)
        self.repositionAttachedChildren()
        # Persist content size when expanded
        if self.expanded:
            self._content_width = r.width()
            self._content_height = r.height()

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
            delta = self.pos() - self._last_pos
            if not delta.isNull():
                for c in self.children:
                    if c.attached_to_parent:
                        c.setPos(c.pos() + delta)
            self._last_pos = self.pos()
        return super().itemChange(change, value)

    def _setAttachedDescendantsVisible(self, visible: bool):
        if not self.children:
            return
        for c in self.children:
            if not getattr(c, 'attached_to_parent', False):
                continue
            c.setVisible(visible)


class ActBox(ParentBox):
    """Top-level container (Act). Always sits at the back (z-index 0)."""
    def __init__(self, x1: float, y1: float, x2: float):
        super().__init__(x1, y1, x2)
        self.setZValue(0)


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

        # Larger scene to accommodate initial nested layout
        scene = QGraphicsScene(0, 0, 3200, 1200)
        self.setScene(scene)

        # Layout constants for neat nesting
        gap = OUTER_GAP
        inner_pad = INNER_PAD
        # Portrait orientation: narrower steps, taller beats
        step_w = 220
        beat_h = 140
        beat_gap = BEAT_GAP
        beats_per_step = 4
        steps_per_sequence = 4

        # Derived sizes
        total_steps_width = steps_per_sequence * step_w + (steps_per_sequence - 1) * gap
        sequence_w = total_steps_width + inner_pad * 2
        step_body_h = beats_per_step * beat_h + (beats_per_step - 1) * beat_gap
        step_h = HEADER_HEIGHT + inner_pad + step_body_h + inner_pad
        seq_h = HEADER_HEIGHT + inner_pad + step_h + inner_pad

        # Act sized to hold two sequences side-by-side
        total_sequences_width = 2 * sequence_w + gap
        act_w = total_sequences_width + inner_pad * 2
        act_h = HEADER_HEIGHT + inner_pad + seq_h + inner_pad

        # Act (parent)
        self.parent = ActBox(40, 40, 40 + act_w)
        self.parent.resizeTo(act_w, act_h)
        scene.addItem(self.parent)

        # Sequences (children of Act)
        s1 = SequenceBox(0, 0, sequence_w, self.parent)
        s1.title.setPlainText("SEQ 1")
        s1.resizeTo(sequence_w, seq_h)
        s2 = SequenceBox(0, 0, sequence_w, self.parent)
        s2.title.setPlainText("SEQ 2")
        s2.resizeTo(sequence_w, seq_h)
        self.parent.children.extend([s1, s2])
        for s in [s1, s2]:
            scene.addItem(s)
        # Attach sequences neatly inside Act
        for idx, s in enumerate([s1, s2]):
            s.relative_offset = QPointF(inner_pad + idx * (sequence_w + gap), HEADER_HEIGHT + inner_pad)
            s.setPos(self.parent.innerTopLeftScene() + s.relative_offset)
            s.attached_to_parent = True
        self.parent.repositionAttachedChildren()

        # Steps under each sequence (4 side by side)
        def add_steps(seq: SequenceBox):
            seq.children.clear()
            for i in range(steps_per_sequence):
                st = StepBox(0, 0, step_w, seq)
                st.title.setPlainText(f"STEP {i + 1}")
                st.resizeTo(step_w, step_h)
                seq.children.append(st)
                scene.addItem(st)
                st.relative_offset = QPointF(inner_pad + i * (step_w + gap), HEADER_HEIGHT + inner_pad)
                st.setPos(seq.innerTopLeftScene() + st.relative_offset)
                st.attached_to_parent = True
        add_steps(s1)
        add_steps(s2)

        # Beats under every step (4 vertical)
        def add_beats(step: 'StepBox'):
            step.children.clear()
            beat_w = step_w - inner_pad * 2
            for j in range(beats_per_step):
                b = BeatBox(0, 0, beat_w, beat_h, f"BEAT {j + 1}", step)
                step.children.append(b)
                scene.addItem(b)
                b.relative_offset = QPointF(inner_pad, HEADER_HEIGHT + inner_pad + j * (beat_h + beat_gap))
                b.setPos(step.innerTopLeftScene() + b.relative_offset)
                b.attached_to_parent = True
        for seq in [s1, s2]:
            for st in seq.children:
                add_beats(st)

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

