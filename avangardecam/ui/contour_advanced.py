# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Advanced of a contour, in the Contour tooling window and in its details:
a check box that shows the side of the lines (Contour side), offers
"Off with arc" in the compensation box and opens the XY offset without
compensation.

The compensation box as the user sees it:
- Off: the tool centre on the lines, straight down onto them;
- Off with arc (Advanced only): the tool centre on the lines, coming onto
  them and leaving them on arcs on the contour side (left or right, seen
  along the arrows);
- Left (RL) / Right (RR): the approach box tells how it comes onto them.

The contour side is the tool's side of the lines, seen along the arrows:
with compensation the same as RL/RR (choosing one sets the other; with M3
left climbs, right is conventional), without it the side of the arcs and
of the XY offset (a chamfer mill's centre beside the edge). Without
compensation the XY offset is open with Advanced only, where its side is.

The model keeps compensation, approach and arc side apart (model Contour):
Off is OFF + NONE, Off with arc OFF + ARC + arc_side. The approach box
shows that for the two Offs and is open for RL/RR only, where it keeps the
user's choice.
"""

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import tr
from avangardecam.model import operations as model_operations
from avangardecam.ui import details

OFF_ARC = "off_arc"  # only in the compensation box, not in the model
_OFF_ARC_TEXT = QT_TRANSLATE_NOOP("AvangardeCam", "Off with arc: tool centre on the lines, arcs on the contour side")

_SIDES = (
    (model_operations.LEFT, QT_TRANSLATE_NOOP("AvangardeCam", "Left of the lines (RL: climb with M3)")),
    (model_operations.RIGHT, QT_TRANSLATE_NOOP("AvangardeCam", "Right of the lines (RR: conventional with M3)")),
)
_COMPENSATED = (model_operations.LEFT, model_operations.RIGHT)


def needs_advanced(contour):
    """True for a contour only Advanced shows: Off with arc, Off with an XY
    offset, or Start/End contour (ui.contour_ends)."""
    off = contour.compensation == model_operations.OFF and (
        contour.approach == model_operations.ARC or bool(contour.offset_xy_mm)
    )
    return off or bool(contour.start_extend_mm or contour.end_extend_mm)


def shown_compensation(contour):
    """What the compensation box shows for a model Contour."""
    if contour.compensation == model_operations.OFF and contour.approach == model_operations.ARC:
        return OFF_ARC
    return contour.compensation


class AdvancedFields(QtCore.QObject):
    """Rows Advanced and, under it, Contour side, at the end of form;
    compensation and approach: the boxes of details.compensation_box and
    details.approach_box above them. advanced: Advanced checked at first
    (also when the contour needs it, needs_advanced); approach_lr: the
    approach for RL/RR while the contour is Off (None: the contour's own).
    chosen: compensation, approach, side or Advanced chosen, after the
    boxes show it."""

    chosen = QtCore.Signal()

    def __init__(self, form, contour, compensation, approach, advanced=False, approach_lr=None, parent=None):
        super().__init__(parent)
        self.compensation = compensation
        self.approach = approach
        if contour.compensation != model_operations.OFF or approach_lr is None:
            approach_lr = contour.approach
        self._approach_lr = approach_lr

        self.check = QtWidgets.QCheckBox(tr("Advanced"))
        self.check.setObjectName("AvangardeCamContourAdvanced")
        form.addRow(self.check)
        self.more = QtWidgets.QWidget()
        self.rows = rows = QtWidgets.QFormLayout(self.more)  # more rows go at its end (ui.contour_ends)
        rows.setContentsMargins(12, 0, 0, 0)
        self.side = details.choice_box("AvangardeCamContourArcSide", _SIDES, _side(contour))
        self.side.setToolTip(tr("The tool's side of the lines, seen along the arrows. With compensation it is RL or RR (with M3 left climbs, right is conventional); without it the side of the approach arcs and of the XY offset."))  # fmt: skip
        rows.addRow(tr("Contour side") + ":", self.side)
        form.addRow(self.more)

        self.check.setChecked(advanced or needs_advanced(contour))
        self._offer_off_arc()
        details.set_choice(self.compensation, shown_compensation(contour))
        self._show_state()
        self.check.toggled.connect(self._advanced_toggled)
        self.compensation.currentIndexChanged.connect(self._compensation_chosen)
        self.approach.currentIndexChanged.connect(self._approach_chosen)
        self.side.currentIndexChanged.connect(self._side_chosen)

    # -- the boxes -------------------------------------------------------------

    def _offer_off_arc(self):
        """Off with arc in the compensation box after Off, with Advanced only."""
        index = self.compensation.findData(OFF_ARC)
        self.compensation.blockSignals(True)
        if self.check.isChecked() and index < 0:
            self.compensation.insertItem(self.compensation.findData(model_operations.OFF) + 1, tr(_OFF_ARC_TEXT), OFF_ARC)  # fmt: skip
        elif not self.check.isChecked() and index >= 0:
            if self.compensation.currentIndex() == index:
                self.compensation.setCurrentIndex(self.compensation.findData(model_operations.OFF))
            self.compensation.removeItem(index)
        self.compensation.blockSignals(False)

    def _fixed_approach(self):
        """The approach of an Off (straight down) or Off with arc, else None."""
        shown = self.compensation.currentData()
        return {model_operations.OFF: model_operations.NONE, OFF_ARC: model_operations.ARC}.get(shown)

    def _show_state(self):
        """The approach box for the compensation shown, the rows under Advanced."""
        self.more.setVisible(self.check.isChecked())
        if self.compensation.currentData() in _COMPENSATED:
            details.set_choice(self.side, self.compensation.currentData())
        approach = self._fixed_approach()
        self.approach.setEnabled(approach is None)
        details.set_choice(self.approach, approach or self._approach_lr)

    def _advanced_toggled(self, *_args):
        self._offer_off_arc()  # unchecked while Off with arc: Off
        self._show_state()
        self.chosen.emit()

    def _compensation_chosen(self, *_args):
        self._show_state()
        self.chosen.emit()

    def _side_chosen(self, *_args):
        """With compensation the side is RL or RR."""
        if self.compensation.currentData() in _COMPENSATED:
            details.set_choice(self.compensation, self.side.currentData())
            self._show_state()
        self.chosen.emit()

    def _approach_chosen(self, *_args):
        if self.approach.isEnabled():
            self._approach_lr = self.approach.currentData()
        self.chosen.emit()

    # -- values ----------------------------------------------------------------

    def values(self):
        """compensation, approach and arc_side of model Contour."""
        shown = self.compensation.currentData()
        compensation = model_operations.OFF if shown == OFF_ARC else shown
        return {
            "compensation": compensation,
            "approach": self._fixed_approach() or self.approach.currentData(),
            "arc_side": self.side.currentData(),
        }

    def offset_open(self):
        """True when the XY offset can be typed: with compensation, or with
        Advanced, where its side is."""
        return self.compensation.currentData() in _COMPENSATED or self.check.isChecked()

    def remembered(self):
        """(compensation as shown, approach for RL/RR, Advanced) to start the next contour with."""
        return self.compensation.currentData(), self._approach_lr, self.check.isChecked()

    def show(self, contour):
        """A contour's values; Advanced stays checked once it is."""
        if contour.compensation != model_operations.OFF:
            self._approach_lr = contour.approach
        if needs_advanced(contour):
            self.check.blockSignals(True)
            self.check.setChecked(True)
            self.check.blockSignals(False)
        self._offer_off_arc()
        details.set_choice(self.compensation, shown_compensation(contour))
        details.set_choice(self.side, _side(contour))
        self._show_state()


def _side(contour):
    """The contour side shown: with compensation its RL/RR."""
    return contour.compensation if contour.compensation in _COMPENSATED else contour.arc_side
