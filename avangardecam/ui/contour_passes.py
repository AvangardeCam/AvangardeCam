# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The passes of a contour as rows of a form, in the Contour tooling window
and in its details: Z steps, XY passes beside the lines, the finishing
allowances, the XY offset and the order of the passes (model Contour).

The XY rows need tool compensation (it tells which side of the lines the
material is on), so they are off without it; the XY offset also with the
contour side of Advanced (ui.contour_advanced).
"""

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import tr
from avangardecam.model import operations as model_operations
from avangardecam.ui import details

# field of model Contour, label, object name, tool tip; None in a step field: 0 in the box
_Z_ROWS = (
    ("z_step_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Z step"), "ZStep",
     QT_TRANSLATE_NOOP("AvangardeCam", "How deep each Z level goes, full steps and the rest last. 0: the whole depth at once.")),  # fmt: skip
    ("finish_z_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Finish Z"), "FinishZ",
     QT_TRANSLATE_NOOP("AvangardeCam", "Finishing allowance on the floor: the rough levels stop this much above Z-Depth, a last level takes it.")),  # fmt: skip
)
_XY_ROWS = (
    ("xy_width_mm", QT_TRANSLATE_NOOP("AvangardeCam", "XY width"), "XYWidth",
     QT_TRANSLATE_NOOP("AvangardeCam", "Material beside the lines, on the tool's side, cut away in passes. 0: one pass.")),  # fmt: skip
    ("xy_step_mm", QT_TRANSLATE_NOOP("AvangardeCam", "XY step"), "XYStep",
     QT_TRANSLATE_NOOP("AvangardeCam", "The widest XY pass; the XY width is split into equal passes no wider than this.")),  # fmt: skip
    ("finish_xy_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Finish XY"), "FinishXY",
     QT_TRANSLATE_NOOP("AvangardeCam", "Finishing allowance on the wall: the rough passes leave this much, a last pass takes it, by the same Z steps.")),  # fmt: skip
    ("offset_xy_mm", QT_TRANSLATE_NOOP("AvangardeCam", "XY offset"), "XYOffset",
     QT_TRANSLATE_NOOP("AvangardeCam", "The last pass this far beside the lines. Negative: past the lines, into the part (a toleranced fit). Without compensation (Advanced): the tool centre this far beside the lines on the contour side, e.g. a chamfer mill's.")),  # fmt: skip
)
_STEPS = ("z_step_mm", "xy_step_mm")

_ORDERS = (
    (model_operations.BY_PASS, QT_TRANSLATE_NOOP("AvangardeCam", "By XY pass: each one all the way down")),
    (model_operations.BY_LEVEL, QT_TRANSLATE_NOOP("AvangardeCam", "By Z level: all XY passes on each")),
)


class PassesFields(QtCore.QObject):
    """typed: a value was typed; chosen: the order was chosen."""

    typed = QtCore.Signal()
    chosen = QtCore.Signal()

    def __init__(self, form, contour, parent=None):
        super().__init__(parent)
        limit = model_operations.MAX_DEPTH_MM
        self.boxes = {}
        self.labels = {}
        for field, label, name, tip in _Z_ROWS + _XY_ROWS:
            # any length: a wrong one is refused by the model, not clamped
            box = details.length_box(getattr(contour, field) or 0.0, -limit, limit)
            box.setObjectName("AvangardeCamContour" + name)
            box.setToolTip(tr(tip))
            box.valueChanged.connect(lambda *_args: self.typed.emit())
            self.boxes[field] = box
            self.labels[field] = tr(label)
            form.addRow(tr(label) + ":", box)
        self.order = details.choice_box("AvangardeCamContourOrder", _ORDERS, contour.order)
        self.order.setToolTip(tr("Order of the rough passes; the finishing pass comes last."))
        self.order.currentIndexChanged.connect(lambda *_args: self.chosen.emit())
        form.addRow(tr("Order") + ":", self.order)
        self.summary = QtWidgets.QLabel()
        self.summary.setObjectName("AvangardeCamContourPasses")
        form.addRow(tr("Passes") + ":", self.summary)
        self.compensated(contour.compensation != model_operations.OFF)

    def compensated(self, on, offset=None):
        """XY passes need the compensation's side of the lines; the XY
        offset a side (offset; None: as the passes)."""
        for field, *_rest in _XY_ROWS:
            self.boxes[field].setEnabled(on)
        self.boxes["offset_xy_mm"].setEnabled(on if offset is None else offset)

    def unreadable(self):
        """Label of the first field that does not hold a length, else ""."""
        for field, box in self.boxes.items():
            if box.isEnabled() and not box.hasAcceptableInput():
                return self.labels[field]
        return ""

    def values(self):
        """The fields of model Contour; without compensation no XY passes."""
        values = {field: float(box.property("rawValue")) for field, box in self.boxes.items()}
        for field in _STEPS:
            values[field] = values[field] or None  # 0: none
        if not self.boxes["xy_width_mm"].isEnabled():
            values.update(xy_width_mm=0.0, finish_xy_mm=0.0)
        if not self.boxes["offset_xy_mm"].isEnabled():
            values.update(offset_xy_mm=0.0)
        values["order"] = self.order.currentData()
        return values

    def show(self, contour, offset=None):
        """The contour's values, but not in a field the user is in; offset:
        the XY offset open (None: as the passes)."""
        for field, box in self.boxes.items():
            if not box.hasFocus():
                box.blockSignals(True)
                box.setProperty("rawValue", getattr(contour, field) or 0.0)
                box.blockSignals(False)
        details.set_choice(self.order, contour.order)
        self.compensated(contour.compensation != model_operations.OFF, offset)
        self.show_summary(contour)

    def show_summary(self, contour):
        self.summary.setText(passes_text(contour))

    def busy(self):
        """True while the user is in a field."""
        return any(box.hasFocus() for box in self.boxes.values())


def passes_text(contour):
    """How many cuts a contour makes: "3 XY × 2 Z = 6 cuts, the last XY one finishing"."""
    try:
        contour.validate()
    except ValueError:
        return "—"
    xy, z = len(contour.xy_offsets()), len(contour.levels())
    if xy * z == 1:
        return tr("one")
    text = tr("{} XY × {} Z = {} cuts").format(xy, z, xy * z)
    if contour.finish_xy_mm:
        text += tr(", the last XY one finishing")
    return text
