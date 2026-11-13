# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""CAM > Measure, on its own (engine.measure does the geometry): what is
selected, and the windows that show the measures.

- Measure from 0-Point: the extreme coordinates of the selected elements
  together (smallest and largest X, Y and Z) from the active setup's zero.
- Measure local: one element (a flat face's sizes, a hole's diameter,
  centre and depth, an edge's length) or two (the distance between two
  faces, between the centres of two holes, from a face to a hole).

The windows do not block the program: the user can select other elements
and click the measure again, the same window then shows the new values.
"""

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

from avangardecam import tr
from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.engine import measure as engine

_AXES = ("X", "Y", "Z")
STATUS_TIMEOUT_MS = 4000
_windows = {}


def mm(value):
    """A coordinate as the machine shows it: 3 decimals, never -0.000."""
    return "{:.3f}".format(round(value, 3) + 0.0)


def _status(message):
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)


def selected():
    """(object, "FaceN"/"EdgeN" or "" for all of it) of the selected faces and
    edges of models, lines of sketches, whole models and sketches, in the
    order they were clicked."""
    found = []
    for selection in FreeCADGui.Selection.getSelectionEx("", 0):
        obj = selection.Object
        entry = cam.owner(obj)
        if geometry.is_sketch(obj) and entry == ("sketch", obj):
            lines = [n.split(".")[-1] for n in map(cam.plain_sub, selection.SubElementNames)]
            lines = [n for n in lines if n.startswith("Edge")]
            if lines:
                found.extend((obj, n) for n in lines)
            elif not selection.SubElementNames:
                found.append((obj, ""))
            continue
        if not selection.SubElementNames:
            if entry is not None and entry[0] == "model":
                found.append((entry[1], ""))
            continue
        for sub in selection.SubElementNames:
            element = cam.model_element(obj, sub)  # a face of a job's clone is the same face of the original
            if element is not None:
                found.append(element)
    return found


def _setup():
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    if doc is None or not cam.models(doc):
        _status(tr("Import a model first (File > Import model)."))
        return None
    job = scene.active_setup(doc)
    if job is None:
        _status(tr("Make a setup first (CAM > Snap-0-Point)."))
    return job


def _error(message):
    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", message)


def _window(kind):
    window = _windows.get(kind)
    if window is None:
        window = kind(FreeCADGui.getMainWindow())
        _windows[kind] = window
    return window


def _show(window):
    window.show()
    window.raise_()
    window.activateWindow()
    return window


# -- Measure from 0-Point --------------------------------------------------------


class MeasureDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCam_MeasureDialog")
        self.setWindowTitle(tr("Measure from 0-Point"))
        self.origin = QtWidgets.QLabel()
        self.count = QtWidgets.QLabel()
        grid = QtWidgets.QGridLayout()
        for column, text in enumerate((tr("Min"), tr("Max"), tr("Size")), start=1):
            head = QtWidgets.QLabel("<b>{}</b>".format(text))
            head.setAlignment(QtCore.Qt.AlignRight)
            grid.addWidget(head, 0, column)
        self.values = {}  # ("X", "min" / "max" / "size") -> QLabel
        for row, axis in enumerate(_AXES, start=1):
            grid.addWidget(QtWidgets.QLabel("<b>{}</b>".format(axis)), row, 0)
            for column, kind in enumerate(("min", "max", "size"), start=1):
                label = QtWidgets.QLabel()
                label.setObjectName("AvangardeCam_Measure_{}_{}".format(axis, kind))
                label.setAlignment(QtCore.Qt.AlignRight)
                label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                label.setMinimumWidth(label.fontMetrics().horizontalAdvance("-0000.000") + 12)
                grid.addWidget(label, row, column)
                self.values[axis, kind] = label
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.origin)
        layout.addWidget(self.count)
        layout.addLayout(grid)
        layout.addWidget(buttons)

    def show_extents(self, job, extents, count):
        """extents: (min, max) along X, Y and Z (engine.measure.from_zero)."""
        self.origin.setText(tr("From the 0-Point of {} (Z towards the tool), mm").format(job.Label))
        self.count.setText(tr("Selected elements: {}").format(count))
        for axis, (low, high) in zip(_AXES, extents):
            self.values[axis, "min"].setText(mm(low))
            self.values[axis, "max"].setText(mm(high))
            self.values[axis, "size"].setText(mm(high - low))

    def text(self, axis, kind):
        return self.values[axis, kind].text()


def from_zero():
    """CAM > Measure from 0-Point; returns the window or None."""
    job = _setup()
    if job is None:
        return None
    elements = selected()
    if not elements:
        _status(tr("Select faces or edges of the model or lines of a sketch (Shift+click adds one), then click Measure from 0-Point."))  # fmt: skip
        return None
    try:
        extents = engine.from_zero(cam.zero(job), elements)
    except ProjectError as exc:
        _error(str(exc))
        return None
    window = _window(MeasureDialog)
    window.show_extents(job, extents, len(elements))
    return _show(window)


# -- Measure local ---------------------------------------------------------------


def value_text(row):
    """A row's value as the window shows it: mm and degrees with 3 decimals."""
    if isinstance(row.value, str):
        return tr(row.value)
    return mm(row.value) + (" °" if row.unit == "°" else "")


class LocalDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCam_MeasureLocalDialog")
        self.setWindowTitle(tr("Measure local"))
        self.title = QtWidgets.QLabel()
        self.note = QtWidgets.QLabel()
        self.grid = QtWidgets.QGridLayout()
        self.rows = []  # (label, value) as shown
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.note)
        layout.addLayout(self.grid)
        layout.addWidget(buttons)

    def show_reading(self, job, reading):
        self.title.setText("<b>{}</b>".format(tr(reading.title)))
        note = tr(reading.note) if reading.note else tr("In the axes of {} (Z towards the tool)").format(job.Label)
        self.note.setText(note + ", mm")
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.rows = []
        for i, row in enumerate(reading.rows):
            label, value = tr(row.label), value_text(row)
            name = QtWidgets.QLabel(label)
            shown = QtWidgets.QLabel(value)
            shown.setAlignment(QtCore.Qt.AlignRight)
            shown.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            shown.setMinimumWidth(shown.fontMetrics().horizontalAdvance("-0000.000 °") + 12)
            self.grid.addWidget(name, i, 0)
            self.grid.addWidget(shown, i, 1)
            self.rows.append((label, value))
        self.adjustSize()


def local():
    """CAM > Measure local; returns the window or None."""
    job = _setup()
    if job is None:
        return None
    elements = selected()
    if not elements:
        _status(tr("Click a face, a hole or an edge (Shift+click a second one), then click Measure local."))
        return None
    try:
        reading = engine.local(cam.zero(job), elements)
    except ProjectError as exc:
        _error(str(exc))
        return None
    window = _window(LocalDialog)
    window.show_reading(job, reading)
    return _show(window)
