# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Dragging an operation in the project list to change the order its
setup runs them in.

Press an operation and move the mouse: a line shows where it goes, between
the operations of its own setup (an operation uses its setup's tools, so
not into another one). Releasing moves it there in one undo step
(handlers.move_operation); Escape, or releasing away from the operations
or where it already is, changes nothing. A plain click still only selects
it. The list is not changed here: the document is, and the list is built
again from it.
"""

from PySide import QtCore, QtWidgets

from avangardecam.engine.operation_order import moved


def _pos(event):
    pos = event.position() if hasattr(event, "position") else event.pos()
    return QtCore.QPoint(int(pos.x()), int(pos.y()))


class OperationDrag(QtCore.QObject):
    """Watches the mouse on the list; operation_of(item) is the operation
    of a list entry, or None for other entries."""

    def __init__(self, tree, operation_of):
        super().__init__(tree)
        self.setObjectName("AvangardeCamOperationDrag")
        self.tree = tree
        self.operation_of = operation_of
        self.line = QtWidgets.QFrame(tree.viewport())
        self.line.setObjectName("AvangardeCamDropLine")
        self.line.setStyleSheet("background: palette(highlight);")
        self.line.hide()
        self._pressed = None  # (operation, where the mouse was pressed)
        self.dragging = False
        self.target = None  # index in the setup's operations it goes before, None: nowhere
        tree.viewport().installEventFilter(self)
        tree.installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self.tree:
            if kind == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape and self.dragging:
                self.cancel()
                return True
            return False
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self.cancel()
            item = self.tree.itemAt(_pos(event))
            op = self.operation_of(item) if item is not None else None
            if op is not None:
                self._pressed = (op, _pos(event))
            return False
        if kind == QtCore.QEvent.MouseMove and self._pressed is not None:
            if not event.buttons() & QtCore.Qt.LeftButton:
                self.cancel()
                return False
            pos = _pos(event)
            if not self.dragging:
                distance = (pos - self._pressed[1]).manhattanLength()
                if distance < QtWidgets.QApplication.startDragDistance():
                    return True  # not the list's own drag-selecting
                self.dragging = True
            self._follow(pos)
            return True
        if kind == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            if self.dragging:
                op, target = self._pressed[0], self.target
                self.cancel()
                if target is not None:
                    # later: the list is built again, not under its own mouse event
                    QtCore.QTimer.singleShot(0, lambda: _move(op, target))
            self._pressed = None
        return False

    def cancel(self):
        self._pressed = None
        self.dragging = False
        self.target = None
        self.line.hide()
        self.tree.viewport().unsetCursor()

    def _entries(self):
        """The list entries of the operations of the dragged one's setup
        (looked up each time: the list may have been built again)."""
        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            if getattr(self.operation_of(item), "Name", None) == self._pressed[0].Name:
                group = item.parent()
                return [group.child(i) for i in range(group.childCount())]
            iterator += 1
        return []

    def target_at(self, pos):
        """Index the dragged operation goes before with the mouse at pos,
        None: away from the operations of its setup or where it is."""
        entries = self._entries()
        rects = [self.tree.visualItemRect(e) for e in entries]
        if not rects or any(not r.isValid() for r in rects):
            return None
        top = self.tree.visualItemRect(entries[0].parent()).top()
        bottom = rects[-1].bottom() + rects[-1].height()
        if not top <= pos.y() <= bottom:
            return None
        index = sum(1 for r in rects if r.center().y() < pos.y())
        names = [self.operation_of(e).Name for e in entries]
        return None if moved(names, self._pressed[0].Name, index) == names else index

    def _follow(self, pos):
        self.target = self.target_at(pos)
        viewport = self.tree.viewport()
        if self.target is None:
            self.line.hide()
            viewport.setCursor(QtCore.Qt.ForbiddenCursor)
            return
        viewport.setCursor(QtCore.Qt.ClosedHandCursor)
        rects = [self.tree.visualItemRect(e) for e in self._entries()]
        y = rects[self.target].top() if self.target < len(rects) else rects[-1].bottom() + 1
        left = rects[0].left()
        self.line.setGeometry(left, y - 1, viewport.width() - left, 2)
        self.line.show()
        self.line.raise_()


def _move(op, index):
    from avangardecam import handlers

    try:
        op.Name
    except Exception:  # gone meanwhile
        return
    handlers.move_operation(op, index)


def install(tree, operation_of):
    """Let the operations of the list be dragged into another order."""
    return OperationDrag(tree, operation_of)
