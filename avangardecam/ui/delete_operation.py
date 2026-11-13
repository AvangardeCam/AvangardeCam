# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Deleting an unwanted operation, on its own: Delete in the menu of an
operation in the project list, or the Delete key on the operation selected
there (also one made in FreeCAD).

The operation goes with the objects AvangardeCam made for it (its sketch
lines or circles, cam.remove_operation) in one undo step: Undo brings it
back. The tools of the setup stay (a tool's details remove one). The next
operation of the setup is selected then, or the one before it, or the
setup's Operations group when it was the only one.
"""

import FreeCADGui

from PySide import QtCore, QtGui

from avangardecam import tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.ui import scene

STATUS_TIMEOUT_MS = 4000


def _status(message):
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)


def _entry_after(op):
    """(kind, name) of the list entry to select once op is deleted."""
    job = cam.setup_of(op)
    ops = cam.operations(job)
    if op not in ops:
        return None
    i = ops.index(op)
    rest = ops[i + 1 :] + ops[:i][::-1]
    if rest:
        return "operation", rest[0].Name
    return "group", "operations:{}".format(job.Name)


def delete(op, panel=None):
    """Delete an operation (see the module), one undo step."""
    doc = op.Document
    label = op.Label
    after = _entry_after(op)
    scene.set_hidden(op, False)  # a new operation may get its name
    doc.openTransaction(tr("Delete operation"))
    try:
        cam.remove_operation(op)
    finally:
        doc.commitTransaction()
    if panel is not None and after is not None:
        panel.select_entry(*after)
    _status(tr("{} deleted. Undo brings it back.").format(label))


def add_to_menu(menu, op, panel=None):
    """Delete in the menu of an operation."""
    action = menu.addAction(tr("Delete"))
    action.setObjectName("AvangardeCamDeleteOperation")
    action.setShortcut(QtGui.QKeySequence(QtCore.Qt.Key_Delete))
    action.setToolTip(tr("Out of the setup and the program; Undo brings it back"))
    action.triggered.connect(lambda: delete(op, panel))
    return action


class _DeleteKey(QtCore.QObject):
    """The Delete key on the list deletes the selected operation; on other
    entries FreeCAD's own Delete does what it did."""

    def __init__(self, tree, operation_of, panel):
        super().__init__(tree)
        self.setObjectName("AvangardeCamDeleteKey")
        self.tree = tree
        self.operation_of = operation_of
        self.panel = panel
        tree.installEventFilter(self)

    def _operation(self, event):
        if event.key() != QtCore.Qt.Key_Delete:
            return None
        if event.modifiers() not in (QtCore.Qt.NoModifier, QtCore.Qt.KeypadModifier):
            return None
        return self.operation_of(self.tree.currentItem())

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.ShortcutOverride and self._operation(event) is not None:
            event.accept()  # the key comes here, not to FreeCAD's Delete
            return True
        if kind == QtCore.QEvent.KeyPress:
            op = self._operation(event)
            if op is not None:
                delete(op, self.panel)
                return True
        return False


def install(tree, operation_of, panel):
    """operation_of(item): the operation of a list entry, or None."""
    return _DeleteKey(tree, operation_of, panel)
