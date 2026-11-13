# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Relative of a contour (in the Contour tooling window and in its
details): what Start Z and Z-Depth are measured from (model
Contour.relative, Contour.base_mm).

Checked: from the Z of the lines, each line from its own (the plane of its
sketch from the setup's zero point), so Z-Depth -1 cuts 1 mm below each
line. Unchecked: from the setup's zero point, wherever the lines are, so
Z-Depth -10 cuts at Z-10. The note beside the box says which, and the
tool tips of Start Z and Z-Depth follow it.
"""

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import tr

# beside the box and in the tool tips of the two fields, checked and unchecked
_NOTES = {
    True: QT_TRANSLATE_NOOP("AvangardeCam", "Start Z and Z-Depth from the Z of each line"),
    False: QT_TRANSLATE_NOOP("AvangardeCam", "Start Z and Z-Depth from the zero point"),
}
_TIPS = {
    "start": {
        True: QT_TRANSLATE_NOOP("AvangardeCam", "Top of the material, from the Z of the lines: the Z steps go down from here to Z-Depth. 0: the lines."),
        False: QT_TRANSLATE_NOOP("AvangardeCam", "Top of the material, from the zero point: the Z steps go down from here to Z-Depth, wherever the lines are."),
    },
    "depth": {
        True: QT_TRANSLATE_NOOP("AvangardeCam", "How deep the tool cuts, from the Z of the lines: -1 mm is 1 mm below each line, also when they are at other heights."),
        False: QT_TRANSLATE_NOOP("AvangardeCam", "How deep the tool cuts, from the zero point: -10 mm is Z-10, wherever the lines are."),
    },
}  # fmt: skip
_TIP = QT_TRANSLATE_NOOP(
    "AvangardeCam",
    "Checked: Start Z and Z-Depth are from the Z of the lines (their sketch's plane, seen from the zero point), each line from its own: Z-Depth -1 mm cuts 1 mm below each line. Unchecked: from the zero point, wherever the lines are: Z-Depth -10 mm cuts at Z-10.",
)


class RelativeField(QtCore.QObject):
    """The Relative box in a row of form, with the contour's value.
    describe(start_z, depth) makes the fields' tool tips follow it.
    chosen: the box was checked or unchecked."""

    chosen = QtCore.Signal()

    def __init__(self, form, contour, parent=None):
        super().__init__(parent)
        row = QtWidgets.QWidget()
        line = QtWidgets.QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.check = QtWidgets.QCheckBox(tr("Relative"))
        self.check.setObjectName("AvangardeCamContourRelative")
        self.check.setToolTip(tr(_TIP))
        self.check.setChecked(contour.relative)
        self.note = QtWidgets.QLabel()
        self.note.setObjectName("AvangardeCamContourRelativeNote")
        self.note.setStyleSheet("color: gray;")
        self.note.setWordWrap(True)
        line.addWidget(self.check)
        line.addWidget(self.note, 1)
        form.addRow("", row)
        self._fields = ()
        self.check.toggled.connect(self._toggled)
        self._explain()

    def describe(self, start_z, depth):
        self._fields = (("start", start_z), ("depth", depth))
        self._explain()

    def _toggled(self, *_args):
        self._explain()
        self.chosen.emit()

    def _explain(self):
        relative = self.check.isChecked()
        self.note.setText(tr(_NOTES[relative]))
        for name, box in self._fields:
            box.setToolTip(tr(_TIPS[name][relative]))

    def values(self):
        """The field of model Contour."""
        return {"relative": self.check.isChecked()}

    def show(self, contour):
        """The contour's value."""
        if self.check.isChecked() != contour.relative:
            self.check.blockSignals(True)
            self.check.setChecked(contour.relative)
            self.check.blockSignals(False)
            self._explain()
