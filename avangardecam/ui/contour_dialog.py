# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Contour tooling window: the tool, Start Z and Z-Depth (Relative to the
lines or from the zero point, ui.contour_relative), the tool compensation,
the approach, the passes (ui.contour_passes) and Advanced
(ui.contour_advanced) for picked sketch lines.

The tool (ui.tool_choice): the one used last for a contour, else the
setup's first tool that is not a drill. Beside the fields a picture of
what the field in use does (ui.field_pictures): the contour as a whole,
for Z step and Order the order of the passes chosen. How it all works:
the Manual button (ui.manual).
"""

import dataclasses
import json

import FreeCADGui

from PySide import QtCore, QtWidgets

from avangardecam import params, tr
from avangardecam.model import leads as model_leads
from avangardecam.model import operations as model_operations
from avangardecam.ui import (
    contour_advanced, contour_ends, contour_passes, contour_relative, details, field_pictures, manual, window_fit,
)  # fmt: skip
from avangardecam.ui.tool_choice import ToolChooser, library_id

DEFAULT_DEPTH_MM = -1.0
_LAST_DEPTH = "LastContourDepth"
_LAST_START = "LastContourStartZ"
_LAST_RELATIVE = "LastContourRelative"  # what the two above are from
_LAST_COMPENSATION = "LastContourCompensation"  # as the box shows it (also Off with arc)
_LAST_APPROACH = "LastContourApproach"  # for RL/RR
_LAST_ADVANCED = "LastContourAdvanced"
_LAST_ARC_SIDE = "LastContourArcSide"
_LAST_PASSES = "LastContourPasses"  # JSON of the passes' fields
LAST_TOOL = "LastContourTool"  # library id

# how the contour works, behind the Manual button
_MANUAL = (
    "The sketch has no zero point of its own: its lines are where they are on the part, seen from the setup's zero point, also in Z.\n\nRelative checked: Start Z and Z-Depth are from the Z of the lines, each line from its own: Z-Depth -1 mm cuts 1 mm below each line, so lines at other heights are cut at other Z. Unchecked: from the zero point, wherever the lines are: Z-Depth -10 mm cuts at Z-10 for all of them. Z-Depth +5 mm ends 5 mm above. Start Z is the top of the material (relative 0: the lines); the Z steps go down from it to Z-Depth, both the same: one pass at that height. Lines at other heights are cut one after the other, the tool going up between them.\n\nThe tool follows the lines the way the arrows on the lines show, by Z steps (0: the whole depth at once); with compensation also in XY passes from the outside in, beside the lines on the tool's side, a finishing pass last.\n\nCompensation off: the tool centre is on the lines; Off with arc (under Advanced) the same, with the approach on an arc on the contour side chosen there; with Advanced the XY offset moves the tool centre to that side (a chamfer mill).\n\nStart contour and End contour (under Advanced) make open lines longer at their start and end, straight on along them, or negative shorter (the tool starts or leaves that far along them).\n\nThe contour side with compensation is RL or RR. Left (RL) or right (RR), seen along the arrows: the program has the lines and the control keeps the tool beside them by its radius from the tool table.\n\nApproach on an arc: the tool goes down in the centre of an arc touching the lines (by default 0.5 mm clear of them) on the side of the compensation, and comes onto them on that arc; a closed loop starts in the middle of its first line.\n\nWithout an approach the tool goes down on the start of the lines, the compensation switched on above the part."
)  # fmt: skip

# the passes numbered in the order they are cut: XY passes side by side, Z levels below each other
_ORDER_PICTURES = {
    model_operations.BY_PASS: "contour_order_by_pass.svg",
    model_operations.BY_LEVEL: "contour_order_by_level.svg",
}


class ContourDialog(QtWidgets.QDialog):
    """lines: the picked lines in the tool's order ([] all of them); lines
    of several sketches: sketch is a list of (sketch, lines) and lines ();
    library: the tool library's variants (LibraryTool), to start with the
    tool used last when the setup does not have it. To edit a contour:
    start, its model Contour, and tool, its ProjectTool; the values used
    last are then neither shown nor remembered."""

    def __init__(self, job, sketch, lines, library=(), parent=None, start=None, tool=None, warn=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.warn = warn  # (model Contour, tool radius) -> what to ask about on OK (ui.lead_warning)
        self.setObjectName("AvangardeCamContourDialog")
        self.setWindowTitle(tr("Contour tooling"))
        self.job = job
        self.editing = start is not None
        # an edited contour's approach radius that follows its tool (None) keeps following it
        self._following = self.editing and start.lead_radius_mm is None
        advanced, approach_lr = False, None
        if start is None:
            advanced = params().GetBool(_LAST_ADVANCED, False)
            approach_lr = params().GetString(_LAST_APPROACH, model_operations.ARC)
            start = dataclasses.replace(
                _last_passes(params().GetString(_LAST_COMPENSATION, model_operations.OFF), advanced, approach_lr),
                z_depth_mm=params().GetFloat(_LAST_DEPTH, DEFAULT_DEPTH_MM),
                start_z_mm=params().GetFloat(_LAST_START, 0.0),
                relative=params().GetBool(_LAST_RELATIVE, True),
                arc_side=params().GetString(_LAST_ARC_SIDE, model_operations.LEFT),
            )

        box = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        box.addLayout(top)
        form = QtWidgets.QFormLayout()
        top.addLayout(form, 1)
        self.pictures = field_pictures.FieldPictures("contour_start.svg")
        top.addWidget(self.pictures, 0, QtCore.Qt.AlignTop)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        sketches, lines_text = details.sketches_text(sketch if isinstance(sketch, list) else [(sketch, lines)])
        form.addRow(tr("Sketch") + ":", QtWidgets.QLabel(sketches))
        lines_label = QtWidgets.QLabel(lines_text)
        lines_label.setObjectName("AvangardeCamContourLines")
        form.addRow(tr("Lines") + ":", lines_label)

        self.chooser = ToolChooser(job, "AvangardeCamContour")
        form.addRow(tr("Tool") + ":", self.chooser)

        self.start_z = details.start_z_box(start.start_z_mm)
        form.addRow(tr("Start Z") + ":", self.start_z)
        self.depth = details.depth_box(start.z_depth_mm)
        self.depth.setObjectName("AvangardeCamContourDepth")
        form.addRow(tr("Z-Depth") + ":", self.depth)
        self.relative = contour_relative.RelativeField(form, start, self)
        self.relative.describe(self.start_z, self.depth)
        self.compensation = details.compensation_box(start.compensation)
        form.addRow(tr("Compensation") + ":", self.compensation)
        self.approach = details.approach_box(start.approach)
        form.addRow(tr("Approach") + ":", self.approach)
        self.lead = details.lead_box(start.lead_radius_mm or model_leads.default_radius(0.0))
        self.lead_edited = False
        self.lead.valueChanged.connect(self._lead_edited)
        form.addRow(tr("Approach radius") + ":", self.lead)
        self.passes = contour_passes.PassesFields(form, start, self)
        for field in (self.passes.boxes["z_step_mm"], self.passes.order):
            self.pictures.add(field, self._order_picture)
        self.passes.chosen.connect(self.pictures.refresh)
        self.advanced = contour_advanced.AdvancedFields(
            form, start, self.compensation, self.approach, advanced, approach_lr, self
        )
        self.ends = contour_ends.EndsFields(self.advanced.rows, start, self)
        self.advanced.chosen.connect(self._approach_changed)
        self.advanced.chosen.connect(self._compensation_changed)
        for signal in (self.passes.typed, self.passes.chosen, self.depth.valueChanged, self.start_z.valueChanged):
            signal.connect(self._show_passes)
        self.chooser.changed.connect(self._tool_changed)
        self._approach_changed()
        self._compensation_changed()
        if tool is not None:
            # a radius of the user's own stays with another tool
            own = start.lead_radius_mm
            self.lead_edited = own is not None and abs(own - model_leads.default_radius(_radius(tool))) > 1e-6
            self.chooser.choose(tool)
        else:
            self.chooser.start_with(library, params().GetString(LAST_TOOL, ""), lambda tool: tool.shape != "Drill")

        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamContourMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)
        self.chooser.changed.connect(lambda: self.message.setText(""))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Contour"), tr(_MANUAL))
        box.addWidget(buttons)
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self.depth.setFocus()
        self.depth.selectAll()

    def _order_picture(self):
        return _ORDER_PICTURES[self.passes.order.currentData()]

    # -- tool ------------------------------------------------------------------

    def use(self, entry):
        self.chooser.use(entry)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        return self.chooser.tool()

    def _tool_radius(self):
        return _radius(self.tool())

    def _lead_edited(self, *_args):
        self.lead_edited = True

    def _tool_changed(self, *_args):
        """The default approach radius follows the tool's diameter."""
        if not self.lead_edited:
            self.lead.blockSignals(True)
            self.lead.setProperty("rawValue", model_leads.default_radius(self._tool_radius()))
            self.lead.blockSignals(False)

    # -- values ----------------------------------------------------------------

    def _approach_changed(self, *_args):
        self.lead.setEnabled(self.advanced.values()["approach"] == model_operations.ARC)

    def _compensation_changed(self, *_args):
        compensated = self.advanced.values()["compensation"] != model_operations.OFF
        self.passes.compensated(compensated, self.advanced.offset_open())
        self._show_passes()

    def _show_passes(self, *_args):
        self.passes.summary.setText(contour_passes.passes_text(self.contour()) if not self._unreadable() else "—")

    def contour(self):
        chosen = self.advanced.values()
        lead = float(self.lead.property("rawValue")) if chosen["approach"] == model_operations.ARC else None
        if self._following and not self.lead_edited:
            lead = None
        return model_operations.Contour(
            float(self.depth.property("rawValue")), lead_radius_mm=lead,
            start_z_mm=float(self.start_z.property("rawValue")), **chosen, **self.passes.values(),
            **self.ends.values(self.advanced.check.isChecked()), **self.relative.values(),
        )  # fmt: skip

    def _unreadable(self):
        """Label of the first field that does not hold a length, else ""."""
        if not self.start_z.hasAcceptableInput():
            return tr("Start Z")
        if not self.depth.hasAcceptableInput():
            return tr("Z-Depth")
        if self.lead.isEnabled() and not self.lead.hasAcceptableInput():
            return tr("Approach radius")
        return self.passes.unreadable() or self.ends.unreadable(self.advanced.check.isChecked())

    def accept(self):
        if self.tool() is None:
            self.message.setText(tr("Choose a tool: one of the setup's or with Choose tool... from the tool library."))
            return
        if not self.start_z.hasAcceptableInput():
            self.message.setText(tr("Start Z: enter a length, for example 0 mm."))
            return
        if not self.depth.hasAcceptableInput():
            self.message.setText(tr("Z-Depth: enter a length, for example -3 mm."))
            return
        if self.lead.isEnabled() and not self.lead.hasAcceptableInput():
            self.message.setText(tr("Approach radius: enter a length, for example 4.5 mm."))
            return
        unreadable = self.passes.unreadable() or self.ends.unreadable(self.advanced.check.isChecked())
        if unreadable:
            self.message.setText(tr("{}: enter a length, for example 0.1 mm.").format(unreadable))
            return
        try:
            contour = self.contour().validate()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        if contour.compensation != model_operations.OFF and contour.lead_radius_mm is not None:
            if contour.lead_radius_mm <= self._tool_radius():
                self.message.setText(
                    tr("With compensation the approach radius must be larger than the tool radius ({:g} mm).").format(self._tool_radius())  # fmt: skip
                )
                return
        from avangardecam.ui import lead_warning

        if not lead_warning.go_on(self, self.message, tr("Contour tooling"), self.warn, contour, self._tool_radius()):
            return
        if self.editing:
            return super().accept()
        params().SetFloat(_LAST_DEPTH, contour.z_depth_mm)
        params().SetFloat(_LAST_START, contour.start_z_mm)
        params().SetBool(_LAST_RELATIVE, contour.relative)
        shown, approach_lr, advanced = self.advanced.remembered()
        params().SetString(_LAST_COMPENSATION, shown)
        params().SetString(_LAST_APPROACH, approach_lr)
        params().SetBool(_LAST_ADVANCED, advanced)
        params().SetString(_LAST_ARC_SIDE, contour.arc_side)
        params().SetString(_LAST_PASSES, json.dumps(self.passes.values()))
        if library_id(self.tool()):
            params().SetString(LAST_TOOL, library_id(self.tool()))
        super().accept()


def _radius(choice):
    """Radius of a ProjectTool or LibraryTool, 0 for None, mm."""
    return (choice.tool.diameter_mm or 0.0) / 2.0 if choice is not None else 0.0


def _last_passes(shown, advanced, approach_lr):
    """A contour with the compensation (as the box showed it) and the
    passes used last (none at first); Off with arc only with Advanced."""
    if shown == contour_advanced.OFF_ARC and advanced:
        compensation, approach = model_operations.OFF, model_operations.ARC
    elif shown in (model_operations.LEFT, model_operations.RIGHT):
        compensation, approach = shown, approach_lr
    else:
        compensation, approach = model_operations.OFF, model_operations.NONE
    contour = model_operations.Contour(DEFAULT_DEPTH_MM, compensation, approach)
    try:
        values = json.loads(params().GetString(_LAST_PASSES, "") or "{}")
        fields = {f.name for f in dataclasses.fields(contour)}
        return dataclasses.replace(contour, **{k: v for k, v in values.items() if k in fields})
    except (ValueError, TypeError):
        return contour
