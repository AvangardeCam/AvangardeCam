# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""CAM > Cycle time (the stopwatch): how long each operation and setup of
the document takes on the machine (engine.cycle_time), worked out only when
the user asks (user, 2026-10-27: worked out at every look, a program of many
moves would make the program slow). The button opens a window with a table
of every setup and its operations; Recalculate works them out again.

The details of a setup and of an operation have a Time row at the top: the
time worked out last, else a link that works it out. The times of a
document are kept until anything in it changes (hiding an operation
aside); then the row and the window say they are out of date.
"""

import html

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

from avangardecam import tr
from avangardecam.engine import cycle_time as engine_cycle_time
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import cycle_time
from avangardecam.ui import postprocessors

LABEL = QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Time")
_COLUMNS = (QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Operation"), QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Tool"),
            QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Time"), QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Feed"),
            QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Rapid"), QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Dwell"),
            QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Tool change"))  # fmt: skip
_PARTS = ("feed_s", "rapid_s", "dwell_s", "tool_change_s")  # the columns after Time
_IGNORED = ("Visibility", "_GroupTouched")  # hiding an operation (FreeCAD touches its group) changes no time
_MARGIN_PX = 24
_TOP_PX = 190  # below the ribbon

_times = {}  # document name: the times of its setups (SetupTime), or the error
_changed = set()  # documents whose times were forgotten after a change
_rows = []  # (QLabel, document object) of the Time rows shown
_observer = None
_window = None


class _Observer:
    """Forgets the times of a document when anything in it changes."""

    def _forget(self, doc):
        name = getattr(doc, "Name", None)
        if name in _times:
            del _times[name]
            _changed.add(name)
            QtCore.QTimer.singleShot(0, _refresh)  # not in the middle of the change

    def slotChangedObject(self, obj, prop):
        if prop not in _IGNORED:
            self._forget(getattr(obj, "Document", None))

    def slotCreatedObject(self, obj):
        self._forget(getattr(obj, "Document", None))

    slotDeletedObject = slotCreatedObject

    def slotUndoDocument(self, doc):
        self._forget(doc)

    slotRedoDocument = slotUndoDocument

    def slotDeletedDocument(self, doc):
        _times.pop(doc.Name, None)
        _changed.discard(doc.Name)


def _watch():
    global _observer
    if _observer is None:
        _observer = _Observer()
        FreeCAD.addDocumentObserver(_observer)


def stored(doc):
    """The times worked out last for the document (a list of
    model.cycle_time.SetupTime), the error met instead, or None: not worked
    out since it was opened or last changed."""
    return _times.get(doc.Name)


def calculate(doc):
    """Recompute the document, work out the times of its setups and keep
    them until it changes; returns them, or the error met."""
    _watch()
    doc.recompute()
    try:
        found = engine_cycle_time.program_times(doc, post=postprocessors.last())
    except Exception as exc:  # ProjectError, ValueError and what FreeCAD raises: shown as the time
        found = exc
    _times[doc.Name] = found
    _changed.discard(doc.Name)
    _refresh()
    return found


def work_out(doc):
    """calculate() with the wait cursor (the link of a Time row)."""
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        return calculate(doc)
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()


def breakdown(t):
    """"feed 52 s, rapid 11 s, tool change 1.5 s" of an OperationTime or a SetupTime."""
    parts = [(tr("feed"), _part(t, "feed_s")), (tr("rapid"), _part(t, "rapid_s")), (tr("dwell"), _part(t, "dwell_s")), (tr("tool change"), _part(t, "tool_change_s"))]  # fmt: skip
    return ", ".join("{} {}".format(name, cycle_time.duration_text(s)) for name, s in parts if s > 0.0)


def _part(t, name):
    return getattr(t, name) if isinstance(t, cycle_time.OperationTime) else t.part(name)


def _of(found, obj):
    """The SetupTime of a setup (Job) or the OperationTime of an operation;
    None for an operation the program leaves out (switched off)."""
    jobs = cam.setups(obj.Document)
    if obj in jobs:
        return found[jobs.index(obj)]
    job = cam.setup_of(obj)
    if job not in jobs:
        raise LookupError(obj.Label)
    return next((op for op in found[jobs.index(job)].operations if op.label == obj.Label), None)


def text(obj):
    """The Time row's text for a setup (Job) or an operation, once worked
    out (stored); None when it is not."""
    found = stored(obj.Document)
    if found is None:
        return None
    if isinstance(found, Exception):
        return tr("not known: {}").format(found)
    try:
        t = _of(found, obj)
    except LookupError:
        return tr("not known")
    if t is None:
        return tr("none: switched off")
    if isinstance(t, cycle_time.SetupTime) and not t.operations:
        return "0 s"
    return "{} ({})".format(cycle_time.duration_text(t.total_s), breakdown(t))


def _assumptions():
    times = cycle_time.BRIDGEPORT_V1000
    return tr("Worked out from the NC program with the machine's dynamics, fitted to the TNC's simulation: acceleration {:g} m/s2, jerk {:g} m/s3 on feed moves, corners within {:g} mm; rapid moves X/Y {:g} and Z {:g} mm/min, tool change {:g} s.").format(times.acceleration_mm_s2 / 1000.0, times.jerk_mm_s3 / 1000.0, times.corner_tolerance_mm, times.rapid_xy_mm_min, times.rapid_z_mm_min, times.tool_change_s)  # fmt: skip


def _fill(row, obj):
    found = text(obj)
    if found is not None:
        row.setTextFormat(QtCore.Qt.PlainText)
        row.setText(found)
        return
    missing = tr("changed since it was worked out:") if obj.Document.Name in _changed else tr("not worked out yet:")
    row.setTextFormat(QtCore.Qt.RichText)
    row.setText('{} <a href="work">{}</a>'.format(html.escape(missing), html.escape(tr("Work it out"))))


def _alive(row):
    try:
        row.objectName()
        return True
    except RuntimeError:  # the view showing it is gone
        return False


def attach(view, obj):
    """Add the Time row of a setup (Job) or an operation to the top of its
    details view; it works nothing out until its link is clicked."""
    _watch()
    _rows[:] = [(r, o) for r, o in _rows if _alive(r)]
    doc = obj.Document
    row = QtWidgets.QLabel()
    row.setWordWrap(True)
    row.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse)
    row.setToolTip(_assumptions())
    row.linkActivated.connect(lambda _link: work_out(doc))
    view.form.insertRow(0, tr(LABEL) + ":", row)
    _rows.append((row, obj))
    _fill(row, obj)
    refresh = view.update_view

    def update_view():
        refresh()
        _fill(row, obj)

    view.update_view = update_view
    return row


def _refresh():
    """Show the times kept now in the Time rows and the window."""
    for row, obj in list(_rows):
        try:
            _fill(row, obj)
        except (RuntimeError, ReferenceError):  # the view is gone, or the object
            _rows.remove((row, obj))
    if window() is not None:
        _window.fill()


# -- the window --------------------------------------------------------------------


def window():
    """The open Cycle time window, or None."""
    return _window if _window is not None and _window.isVisible() else None


def show_window(doc):
    """Open the window for a document (one at a time) and work its times out."""
    global _window
    if window() is not None:
        _window.close()
    main = FreeCADGui.getMainWindow()
    _window = CycleTimeWindow(doc, main)
    _window.show()
    # in the top right corner, under the ribbon: the part stays in sight
    frame = main.frameGeometry()
    _window.move(frame.right() - _window.frameGeometry().width() - _MARGIN_PX, frame.top() + _TOP_PX)
    _window.recalculate()
    return _window


class CycleTimeWindow(QtWidgets.QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle(tr("Cycle time - {}").format(doc.Label))
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        layout = QtWidgets.QVBoxLayout(self)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.table = QtWidgets.QTreeWidget()
        self.table.setHeaderLabels([tr(c) for c in _COLUMNS])
        self.table.setMinimumSize(620, 220)
        self.table.setAlternatingRowColors(True)
        for column in range(2, len(_COLUMNS)):
            self.table.headerItem().setTextAlignment(column, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(self.table, 1)
        note = QtWidgets.QLabel(_assumptions())
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        self.recalculate_button = buttons.addButton(tr("Recalculate"), QtWidgets.QDialogButtonBox.ActionRole)
        self.recalculate_button.setToolTip(tr("Work the times out again from the program as it is now"))
        self.recalculate_button.clicked.connect(self.recalculate)
        self.copy_button = buttons.addButton(tr("Copy"), QtWidgets.QDialogButtonBox.ActionRole)
        self.copy_button.setToolTip(tr("Copy the table, to paste it into a spreadsheet or a message"))
        self.copy_button.clicked.connect(self.copy)
        layout.addWidget(buttons)

    def recalculate(self):
        """Say so, then work the times out (_work): the window shows the
        words before FreeCAD's thread is busy."""
        self.status.setText(tr("Working out the times..."))
        self.recalculate_button.setEnabled(False)
        QtCore.QTimer.singleShot(50, self._work)

    def _work(self):
        self.recalculate_button.setEnabled(True)
        if self.doc.Name not in FreeCAD.listDocuments():
            self.status.setText(tr("The document is closed."))
            return
        work_out(self.doc)  # fills the window

    def fill(self):
        """The table of the times kept (stored), or what keeps them out."""
        if self.doc.Name not in FreeCAD.listDocuments():
            return
        found = stored(self.doc)
        if found is None:
            # the old times stay, grayed, until Recalculate
            self.table.setEnabled(False)
            if self.doc.Name in _changed:
                self.status.setText(tr("The project changed since: press Recalculate."))
            return
        self.table.setEnabled(True)
        self.table.clear()
        if isinstance(found, Exception):
            self.status.setText(tr("The times could not be worked out: {}").format(found))
            return
        total = sum(t.total_s for t in found)
        self.status.setText(tr("All setups: {}").format(cycle_time.duration_text(total)))
        for job, t in zip(cam.setups(self.doc), found):
            self._add_setup(job, t)
        for column in range(len(_COLUMNS)):
            self.table.resizeColumnToContents(column)

    def _add_setup(self, job, t):
        item = self._item(self.table, [job.Label, "", _seconds(t.total_s)] + [_seconds(t.part(p)) for p in _PARTS])
        font = item.font(0)
        font.setBold(True)
        for column in range(len(_COLUMNS)):
            item.setFont(column, font)
        by_label = {op.label: op for op in t.operations}
        for op in job.Operations.Group:
            found = by_label.get(op.Label)
            if found is None:
                off = self._item(item, [op.Label, "", tr("switched off") if not getattr(op, "Active", True) else "-"])
                for column in range(len(_COLUMNS)):
                    off.setForeground(column, QtGui.QBrush(QtCore.Qt.gray))
                continue
            values = [_seconds(found.total_s)] + [_seconds(getattr(found, p)) for p in _PARTS]
            self._item(item, [op.Label, found.tool] + values)
        item.setExpanded(True)

    @staticmethod
    def _item(parent, texts):
        item = QtWidgets.QTreeWidgetItem(parent, texts)
        for column in range(2, len(_COLUMNS)):
            item.setTextAlignment(column, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        return item

    def rows(self):
        """The table's texts, row by row (a setup's operations after it), for Copy and tests."""
        result = [[tr(c) for c in _COLUMNS]]
        for i in range(self.table.topLevelItemCount()):
            setup = self.table.topLevelItem(i)
            result.append([setup.text(c) for c in range(len(_COLUMNS))])
            for k in range(setup.childCount()):
                result.append([setup.child(k).text(c) for c in range(len(_COLUMNS))])
        return result

    def copy(self):
        """The status line and the table to the clipboard, tab separated."""
        lines = [self.status.text()] + ["\t".join(row) for row in self.rows()]
        QtWidgets.QApplication.clipboard().setText("\n".join(lines) + "\n")


def _seconds(s):
    return cycle_time.duration_text(s) if s > 0.0 else ""
