# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Start contour and End contour of a contour, under its Advanced (in the
Contour tooling window and in its details): the cut longer or shorter at
the start and end of open lines (model Contour.start_extend_mm,
end_extend_mm; engine.contour_ends).

The rows sit in the rows Advanced opens (ui.contour_advanced); with
Advanced unchecked they are hidden and the contour runs the whole lines.
"""

from PySide import QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import tr
from avangardecam.model import operations as model_operations
from avangardecam.ui import details

# field of model Contour, label, object name, tool tip
_ROWS = (
    ("start_extend_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Start contour"), "StartContour",
     QT_TRANSLATE_NOOP("AvangardeCam", "The cut this much longer before the first line, straight on along it (e.g. to take the stock off past a corner). Negative: it starts this far along the lines (-20 mm on a 40 mm line: in its middle). Open lines only.")),  # fmt: skip
    ("end_extend_mm", QT_TRANSLATE_NOOP("AvangardeCam", "End contour"), "EndContour",
     QT_TRANSLATE_NOOP("AvangardeCam", "The cut this much longer after the last line, straight on along it. Negative: the tool leaves the lines this far before their end (a chamfer mill before a wall standing up). Open lines only.")),  # fmt: skip
)


def changed(contour):
    """True for a contour whose lines are made longer or shorter."""
    return bool(contour.start_extend_mm or contour.end_extend_mm)


class EndsFields(QtCore.QObject):
    """The two rows at the end of rows (the form Advanced opens), with the
    contour's values. typed: a value was typed."""

    typed = QtCore.Signal()

    def __init__(self, rows, contour, parent=None):
        super().__init__(parent)
        limit = model_operations.MAX_DEPTH_MM
        self.boxes = {}
        self.labels = {}
        for field, label, name, tip in _ROWS:
            box = details.length_box(getattr(contour, field), -limit, limit)
            box.setObjectName("AvangardeCam" + name)
            box.setToolTip(tr(tip))
            box.valueChanged.connect(lambda *_args: self.typed.emit())
            self.boxes[field] = box
            self.labels[field] = tr(label)
            rows.addRow(tr(label) + ":", box)

    def unreadable(self, advanced):
        """Label of the first field that does not hold a length, else ""
        (none with Advanced unchecked: the fields are not used)."""
        for field, box in self.boxes.items():
            if advanced and not box.hasAcceptableInput():
                return self.labels[field]
        return ""

    def values(self, advanced):
        """The fields of model Contour; 0 with Advanced unchecked."""
        return {field: float(box.property("rawValue")) if advanced else 0.0 for field, box in self.boxes.items()}

    def show(self, contour):
        """The contour's values, but not in a field the user is in."""
        for field, box in self.boxes.items():
            if not box.hasFocus():
                box.blockSignals(True)
                box.setProperty("rawValue", getattr(contour, field))
                box.blockSignals(False)

    def busy(self):
        return any(box.hasFocus() for box in self.boxes.values())
