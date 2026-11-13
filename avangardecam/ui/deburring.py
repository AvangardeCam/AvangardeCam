# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Deburring: CAM > Deburring on picked sketch lines (as Contour tooling:
click order, arrows, lines of several sketches), its window, its details
and Edit... (model.deburring, engine.deburring).

The window: the tool (ui.tool_choice; the one used last for a deburring,
else the setup's first chamfer mill; "Chamfer mills only"), the chamfer,
Tip below chamfer, the side of the lines (left by default: with M3
climbing), the approach (straight down by default, or on an arc with its
radius) and Advanced: Z-Depth and XY offset of the user's own, Start
contour and End contour. Under them a line saying where the tool runs
(without Advanced: worked out of the chamfer; with it: the chamfer that
makes). The window starts with the values used last. Beside the fields a
picture (ui.field_pictures): the chamfer mill on the edge.
"""

import dataclasses
import json

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tr
from avangardecam.engine import deburring as engine_deburring
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import deburring as model_deburring
from avangardecam.model import leads as model_leads
from avangardecam.model import operations as model_operations
from avangardecam.ui import details, field_pictures, manual, window_fit
from avangardecam.ui.tool_choice import ToolChooser, library_id

_LAST = "LastDeburring"  # the values as JSON
LAST_TOOL = "LastDeburringTool"  # library id
CHAMFER_MILLS_ONLY = (
    QT_TRANSLATE_NOOP("AvangardeCam", "Chamfer mills only"),
    lambda tool: tool.shape in model_deburring.SHAPES,
)

_SIDES = (
    (model_operations.LEFT, QT_TRANSLATE_NOOP("AvangardeCam", "Left of the lines (climb with M3)")),
    (model_operations.RIGHT, QT_TRANSLATE_NOOP("AvangardeCam", "Right of the lines (conventional with M3)")),
)
_APPROACHES = (
    (model_operations.NONE, QT_TRANSLATE_NOOP("AvangardeCam", "None: straight down beside the lines")),
    (model_operations.ARC, QT_TRANSLATE_NOOP("AvangardeCam", "Arc, from beside the lines")),
)
# (field, label, object name, tip, minimum) of the length fields, the first two always shown
_LENGTHS = (
    ("chamfer_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Chamfer"), "Chamfer",
     QT_TRANSLATE_NOOP("AvangardeCam", "Width of the chamfer on the face of the lines (with a 90° tool both of its sides)"), 0.0),  # fmt: skip
    ("tip_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Tip below chamfer"), "TipBelow",
     QT_TRANSLATE_NOOP("AvangardeCam", "How far the tool's tip goes below the chamfer; its edge stays as far clear of the wall under it (90° tool)"), 0.0),  # fmt: skip
)
_ADVANCED = (
    ("z_depth_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Z-Depth"), "Depth",
     QT_TRANSLATE_NOOP("AvangardeCam", "The tool's tip, from the lines (negative: below them)"), None),  # fmt: skip
    ("offset_xy_mm", QT_TRANSLATE_NOOP("AvangardeCam", "XY offset"), "OffsetXY",
     QT_TRANSLATE_NOOP("AvangardeCam", "The tool centre this far beside the lines, on the side chosen"), None),  # fmt: skip
    ("start_extend_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Start contour"), "StartContour",
     QT_TRANSLATE_NOOP("AvangardeCam", "The cut this much longer before the first line, straight on along it. Negative: it starts this far along the lines. Open lines only."), None),  # fmt: skip
    ("end_extend_mm", QT_TRANSLATE_NOOP("AvangardeCam", "End contour"), "EndContour",
     QT_TRANSLATE_NOOP("AvangardeCam", "The cut this much longer after the last line. Negative: the tool leaves the lines this far before their end (before a wall standing up). Open lines only."), None),  # fmt: skip
)

_MANUAL = (
    "Deburring runs a chamfer mill along the lines picked, as Contour tooling does: in the order clicked, the way the arrows show, lines of several sketches each from its own plane. The compensation is off: the program has where the tool centre goes.\n\nBy default enter only the chamfer and how far the tool's tip goes below it (Tip below chamfer). The depth and how far the tool centre runs beside the lines follow from the tool's cone: with a 90° tool the tip goes chamfer + tip below the lines and the centre runs the tip's radius + Tip below chamfer beside them, so a larger chamfer is the same line, deeper. The line under the fields says where the tool runs.\n\nSide: the tool runs left or right of the lines, seen along the arrows. Left climbs with M3 (as RL), right is conventional (as RR). Extract boundary edges gives an outline whose left is outside and holes whose left is inside, so all lines of such a sketch are deburred on the left.\n\nApproach: straight down beside the lines (fits small holes), or on an arc on the tool's side (no mark where the tool goes down; a closed loop starts in the middle of its first line).\n\nAdvanced: enter Z-Depth (the tip, from the lines) and the XY offset (the tool centre beside them) yourself, as in Contour tooling; the line under the fields says what chamfer that makes. Start contour and End contour make open lines longer or, negative, shorter (the tool leaves before a wall standing up)."
)  # fmt: skip


def is_chamfer_mill(tool):
    return CHAMFER_MILLS_ONLY[1](tool)


def last_deburring():
    """The values used last, else the defaults."""
    start = model_deburring.Deburring()
    try:
        values = json.loads(params().GetString(_LAST, "") or "{}")
        fields = {f.name for f in dataclasses.fields(start)}
        return dataclasses.replace(start, **{k: v for k, v in values.items() if k in fields}).validate()
    except (ValueError, TypeError):
        return start


def cut_text(deburring, tool):
    """Where the tool runs, or why it cannot, as the line under the fields shows it."""
    if tool is None:
        return ""
    try:
        model_deburring.check(deburring, tool)
        depth, offset = model_deburring.cut(deburring, tool)
        chamfer, tip = model_deburring.chamfer_of(depth, offset, tool)
    except ValueError as exc:
        return str(exc)
    if deburring.advanced:
        return tr("The tip {:.2f} mm below the lines makes a chamfer of {:.2f} mm, the tip {:.2f} mm below it.").format(
            depth, chamfer, tip
        )
    return tr("The tip {:.2f} mm below the lines (Z-Depth {:.2f} mm), the tool centre {:.2f} mm beside them.").format(
        depth, -depth, offset
    )


class DeburringFields(QtCore.QObject):
    """The fields of a deburring at the end of form. typed: a length was
    typed; chosen: a box or Advanced was chosen."""

    typed = QtCore.Signal()
    chosen = QtCore.Signal()

    def __init__(self, form, deburring, parent=None):
        super().__init__(parent)
        limit = model_operations.MAX_DEPTH_MM
        self.boxes = {}
        self.labels = {}

        def length(rows, field, label, name, tip, minimum):
            box = details.length_box(getattr(deburring, field), -limit if minimum is None else minimum, limit)
            box.setObjectName("AvangardeCamDeburring" + name)
            box.setToolTip(tr(tip))
            box.valueChanged.connect(lambda *_args: self.typed.emit())
            self.boxes[field] = box
            self.labels[field] = tr(label)
            rows.addRow(tr(label) + ":", box)
            return box

        for row in _LENGTHS:
            length(form, *row)
        self.side = details.choice_box("AvangardeCamDeburringSide", _SIDES, deburring.side)
        self.side.setToolTip(tr("The tool's side of the lines, seen along the arrows: with M3 left climbs, right is conventional."))  # fmt: skip
        self.side.currentIndexChanged.connect(lambda *_args: self.chosen.emit())
        form.addRow(tr("Side") + ":", self.side)
        self.approach = details.choice_box("AvangardeCamDeburringApproach", _APPROACHES, deburring.approach)
        self.approach.currentIndexChanged.connect(self._approach_chosen)
        form.addRow(tr("Approach") + ":", self.approach)
        self.lead = details.lead_box(deburring.lead_radius_mm or model_leads.default_radius(0.0))
        self.lead.setObjectName("AvangardeCamDeburringLeadRadius")
        self.lead.valueChanged.connect(self._lead_typed)
        form.addRow(tr("Approach radius") + ":", self.lead)
        self.lead_own = deburring.lead_radius_mm is not None  # else the default, following the tool
        self.tool_radius = 0.0

        self.check = QtWidgets.QCheckBox(tr("Advanced"))
        self.check.setObjectName("AvangardeCamDeburringAdvanced")
        self.check.setChecked(deburring.advanced)
        form.addRow(self.check)
        self.more = QtWidgets.QWidget()
        rows = QtWidgets.QFormLayout(self.more)
        rows.setContentsMargins(12, 0, 0, 0)
        for row in _ADVANCED:
            length(rows, *row)
        form.addRow(self.more)
        self.check.toggled.connect(self._advanced_toggled)
        self.cut = QtWidgets.QLabel()
        self.cut.setObjectName("AvangardeCamDeburringCut")
        self.cut.setWordWrap(True)
        self.cut.setStyleSheet("color: #555555;")
        form.addRow(self.cut)
        self.tool = None  # model Tool the line under the fields is for
        self._show_state()

    # -- state -----------------------------------------------------------------

    def _show_state(self):
        advanced = self.check.isChecked()
        self.more.setVisible(advanced)
        for field in ("chamfer_mm", "tip_mm"):
            self.boxes[field].setEnabled(not advanced)
        self.lead.setEnabled(self.approach.currentData() == model_operations.ARC)

    def _approach_chosen(self, *_args):
        self._show_state()
        self.chosen.emit()

    def _lead_typed(self, *_args):
        self.lead_own = True
        self.typed.emit()

    def _advanced_toggled(self, checked):
        """Checked: the own values start where the chamfer puts the tool."""
        if checked and self.tool is not None:
            try:
                plain = dataclasses.replace(self.deburring(), advanced=False)
                depth, offset = model_deburring.cut(model_deburring.check(plain, self.tool), self.tool)
                self._set("z_depth_mm", -depth)
                self._set("offset_xy_mm", offset)
            except ValueError:
                pass  # what was there stays
        self._show_state()
        self.chosen.emit()

    def _set(self, field, value):
        box = self.boxes[field]
        box.blockSignals(True)
        box.setProperty("rawValue", value)
        box.blockSignals(False)

    def use_tool(self, tool):
        """The model Tool chosen (None: none): the default approach radius
        and the line under the fields follow it."""
        self.tool = tool
        self.tool_radius = tool.diameter_mm / 2.0 if tool is not None else 0.0
        if not self.lead_own:
            self.lead.blockSignals(True)
            self.lead.setProperty("rawValue", model_leads.default_radius(self.tool_radius))
            self.lead.blockSignals(False)
        self.refresh()

    def refresh(self):
        self.cut.setText(cut_text(self.deburring(), self.tool) if not self.unreadable() else "—")

    # -- values ----------------------------------------------------------------

    def unreadable(self):
        """Label of the first field in use that does not hold a length, else ""."""
        used = [f for f, _l, _n, _t, _m in _LENGTHS] + ([f for f, _l, _n, _t, _m in _ADVANCED] if self.check.isChecked() else [])  # fmt: skip
        for field in used:
            if not self.boxes[field].hasAcceptableInput():
                return self.labels[field]
        if self.lead.isEnabled() and not self.lead.hasAcceptableInput():
            return tr("Approach radius")
        return ""

    def deburring(self):
        arc = self.approach.currentData() == model_operations.ARC
        return model_deburring.Deburring(
            side=self.side.currentData(),
            approach=self.approach.currentData(),
            lead_radius_mm=float(self.lead.property("rawValue")) if arc and self.lead_own else None,
            advanced=self.check.isChecked(),
            **{field: float(box.property("rawValue")) for field, box in self.boxes.items()},
        )

    def busy(self):
        return any(box.hasFocus() for box in self.boxes.values()) or self.lead.hasFocus()

    def show(self, deburring, lead_mm):
        """A deburring's values, but not in a field the user is in; lead_mm:
        the approach radius the tool runs."""
        for field, box in self.boxes.items():
            if not box.hasFocus():
                self._set(field, getattr(deburring, field))
        details.set_choice(self.side, deburring.side)
        details.set_choice(self.approach, deburring.approach)
        self.lead_own = deburring.lead_radius_mm is not None
        if not self.lead.hasFocus():
            self.lead.blockSignals(True)
            self.lead.setProperty("rawValue", lead_mm)
            self.lead.blockSignals(False)
        self.check.blockSignals(True)
        self.check.setChecked(deburring.advanced)
        self.check.blockSignals(False)
        self._show_state()
        self.refresh()


def warning_text(job, picks, deburring, tool):
    """What to warn about before deburring picks ((sketch, lines,
    backwards)): loops the tool runs on the material of, approach arcs
    that do not fit; "" for nothing."""
    from avangardecam.engine import lead_check

    texts = []
    try:
        texts.append(on_material_text(engine_deburring.on_material(job, picks, deburring, tool)))
        texts.append(lead_check.text(engine_deburring.leads_too_close(job, picks, deburring, tool), tr))
    except (cam.ProjectError, ValueError, ArithmeticError) as exc:
        FreeCAD.Console.PrintLog("AvangardeCam deburring check: {}\n".format(exc))  # the operation says what is wrong
    return "\n\n".join(t for t in texts if t)


def on_material_text(found):
    """The warning for closed loops the tool would run on the material of
    (engine.deburring.on_material), "" for none."""
    if not found:
        return ""
    return tr("On these loops the tool centre runs on the material of the face (an outline inside, a hole outside): it would cut a groove into the part. Turn the loop's arrows round (click an arrow) or choose the other side.") + "\n" + "\n".join(found)  # fmt: skip


class DeburringDialog(QtWidgets.QDialog):
    """picks: (sketch, its lines in the tool's order) of each sketch, as
    Contour tooling. To edit a deburring: start, its model Deburring, and
    tool, its ProjectTool; the values used last are then neither shown nor
    remembered. warn(model Deburring, model Tool): what to warn about
    (warning_text), asked on OK (the user may deburr anyway)."""

    def __init__(self, job, picks, library=(), parent=None, start=None, tool=None, warn=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.warn = warn
        self.setObjectName("AvangardeCamDeburringDialog")
        self.setWindowTitle(tr("Deburring"))
        self.job = job
        self.editing = start is not None
        start = start if start is not None else last_deburring()

        box = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        box.addLayout(top)
        form = QtWidgets.QFormLayout()
        top.addLayout(form, 1)
        self.pictures = field_pictures.FieldPictures("deburring_start.svg")
        top.addWidget(self.pictures, 0, QtCore.Qt.AlignTop)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        sketches, lines_text = details.sketches_text(picks)
        form.addRow(tr("Sketch") + ":", QtWidgets.QLabel(sketches))
        lines_label = QtWidgets.QLabel(lines_text)
        lines_label.setObjectName("AvangardeCamDeburringLines")
        form.addRow(tr("Lines") + ":", lines_label)
        self.chooser = ToolChooser(job, "AvangardeCamDeburring", only=CHAMFER_MILLS_ONLY)
        form.addRow(tr("Tool") + ":", self.chooser)
        self.fields = DeburringFields(form, start, self)
        for signal in (self.fields.typed, self.fields.chosen):
            signal.connect(self.fields.refresh)
        self.chooser.changed.connect(self._tool_changed)
        if tool is not None:
            self.chooser.choose(tool)
        else:
            self.chooser.start_with(library, params().GetString(LAST_TOOL, ""), is_chamfer_mill)
        self._tool_changed()

        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamDeburringMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)
        self.chooser.changed.connect(lambda: self.message.setText(""))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Deburring"), tr(_MANUAL))
        box.addWidget(buttons)
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self.fields.boxes["chamfer_mm"].setFocus()
        self.fields.boxes["chamfer_mm"].selectAll()

    def use(self, entry):
        self.chooser.use(entry)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        return self.chooser.tool()

    def _tool_changed(self, *_args):
        choice = self.tool()
        self.fields.use_tool(choice.tool if choice is not None else None)

    def deburring(self):
        return self.fields.deburring()

    def accept(self):
        choice = self.tool()
        if choice is None:
            self.message.setText(tr("Choose a chamfer mill: one of the setup's or with Choose tool... from the tool library."))  # fmt: skip
            return
        unreadable = self.fields.unreadable()
        if unreadable:
            self.message.setText(tr("{}: enter a length, for example 0.5 mm.").format(unreadable))
            return
        try:
            deburring = model_deburring.check(self.deburring(), choice.tool)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        if deburring.approach == model_operations.ARC and deburring.lead_radius_mm is not None:
            if deburring.lead_radius_mm <= 0.0:
                self.message.setText(tr("Approach radius: enter a length larger than 0 mm."))
                return
        warning = self.warn(deburring, choice.tool) if self.warn is not None else ""
        if warning:
            answer = QtWidgets.QMessageBox.warning(
                self, tr("Deburring"), warning + "\n\n" + tr("Deburr anyway?"),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No,
            )  # fmt: skip
            if answer != QtWidgets.QMessageBox.Yes:
                self.message.setText(warning)
                return
        if self.editing:
            return super().accept()
        params().SetString(_LAST, model_deburring.to_json(dataclasses.replace(deburring, lead_radius_mm=None)))
        if library_id(choice):
            params().SetString(LAST_TOOL, library_id(choice))
        super().accept()


# -- making one ------------------------------------------------------------------


def make(sketch=None):
    """CAM > Deburring on the selected sketch lines (as Contour tooling: in
    the order clicked, the arrows, lines of several sketches)."""
    from avangardecam import handlers
    from avangardecam.engine import geometry
    from avangardecam.ui import direction, picking, scene

    doc = FreeCAD.ActiveDocument
    if handlers._models_or_say(doc) is None:
        return
    picks = picking.selections()
    if not picks or (sketch is not None and all(s is not sketch for s, _lines in picks)):
        handlers._status(tr("Click the edges to deburr: lines of a sketch from Extract boundary edges (Shift+click adds a line, Alt+click a loop), then click Deburring."))  # fmt: skip
        return
    jobs = None
    for one, _lines in picks:
        fits = cam.setups_for_contour(doc, one)
        if not fits:
            handlers._error(
                tr("No setup has its tool across the lines of {}.\n\nSelect the face the sketch was taken from and click Snap-0-Point first.").format(one.Label)  # fmt: skip
            )
            return
        jobs = [job for job in (jobs if jobs is not None else fits) if job in fits]
    if not jobs:
        handlers._error(tr("The sketches face the tools of different setups: one deburring is made in one setup."))
        return
    active = scene.active_setup(doc)
    job = active if active in jobs else jobs[0]
    turned = [direction.backwards(one) for one, _lines in picks]
    tool_order = [
        (one, [name for chain in geometry.line_runs(one, lines, back) for name, _r in chain] if lines else [])
        for (one, lines), back in zip(picks, turned)
    ]
    runs = [(one, lines, back) for (one, lines), back in zip(picks, turned)]
    warn = lambda values, tool: warning_text(job, runs, values, tool)  # noqa: E731
    dialog = DeburringDialog(job, tool_order, handlers._library(), warn=warn)
    make_op = lambda tc: engine_deburring.add_deburring(job, runs, dialog.deburring(), tc)  # noqa: E731
    handlers._add_operation(doc, job, dialog, make_op, tr("Deburring"))


def edit_dialog(op, job, tool, library):
    """(window, its values) to edit a deburring (handlers.edit_operation)."""
    sketch, deburring = engine_deburring.deburring_of(op)
    warn = lambda values, model_tool: warning_text(job, engine_deburring.op_picks(op), values, model_tool)  # noqa: E731
    dialog = DeburringDialog(job, cam.contour_sketches(op) or [(sketch, [])], library, start=deburring, tool=tool, warn=warn)  # fmt: skip
    return dialog, dialog.deburring


# -- details ---------------------------------------------------------------------


class DeburringView(details.DetailsView):
    """Deburring: typed values are applied after a pause, chosen ones at
    once; each change is one undo step."""

    APPLY_DELAY_MS = 600

    def __init__(self, op, parent=None):
        from avangardecam import handlers

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.op = op
        self.job = cam.setup_of(op)
        sketch, deburring = engine_deburring.deburring_of(op)
        sketches, lines = details.sketches_text(cam.contour_sketches(op) or [(sketch, [])])
        self.add_row(tr("Setup"), self.job.Label if self.job else details.NONE)
        self.add_row(tr("Sketch"), sketches)
        self.add_row(tr("Lines"), lines)
        self.tool_label = self.add_row(tr("Tool"), "")
        self.tool_label.setWordWrap(True)
        self.planes_label = self.add_row(tr("Lines at"), "")
        self.warning = QtWidgets.QLabel()  # loops the tool runs on the material of, at the top: seen at once
        self.warning.setObjectName("AvangardeCamDeburringWarning")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #c0392b;")
        self.form.addRow(self.warning)
        self.fields = DeburringFields(self.form, deburring, self)
        self.fields.typed.connect(self._schedule_apply)
        self.fields.chosen.connect(self.apply)
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("A chamfer mill along the lines in the order shown under Lines, the way the arrows show, on the side chosen; the compensation is off. Without Advanced the depth and the tool centre beside the lines follow from the chamfer and the tool's cone, with it they are your own. The path in 3D is where the tool centre goes.")  # fmt: skip
        )
        self.add_button(tr("Change tool..."), lambda: handlers.change_tool(self.op), "AvangardeCamChangeTool")
        self.add_button(tr("Remove operation"), self._remove, "AvangardeCamRemoveOperation")
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply)
        self.update_view()

    def _schedule_apply(self, *_args):
        self._timer.start(self.APPLY_DELAY_MS)

    def apply(self, *_args):
        self._timer.stop()
        if self.fields.unreadable():
            return  # still being typed
        try:
            wanted = self.fields.deburring().validate()
        except ValueError as exc:
            details._show_error(str(exc))
            return
        if wanted == engine_deburring.deburring_of(self.op)[1]:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Deburring"))
        try:
            engine_deburring.set_deburring(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            details._show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        _sketch, deburring = engine_deburring.deburring_of(self.op)
        tc = self.op.ToolController
        tool = next((t.tool for t in cam.project_tools(self.job) if t.controller is tc), None)
        self.tool_label.setText(details.tool_row_text(self.op, self.job))
        planes = cam.contour_planes(self.op)
        self.planes_label.setText("Z {} mm".format(", ".join("{:.2f}".format(round(z, 2) + 0.0) for z in planes)) if planes else details.NONE)  # fmt: skip
        moves, lowest = cam.path_summary(self.op)
        if moves and lowest is not None:
            self.path_label.setText(tr("{} moves, deepest Z {:.2f} mm").format(moves, round(lowest, 2) + 0.0))
        else:
            self.path_label.setText(details._no_path(self.op))
        self.fields.tool = tool
        self.fields.tool_radius = tool.diameter_mm / 2.0 if tool is not None else 0.0
        warning = ""
        if tool is not None and self.job is not None:
            warning = warning_text(self.job, engine_deburring.op_picks(self.op), deburring, tool)
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        if not self._timer.isActive():
            self.fields.show(deburring, cam.lead_radius(self.op))

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()
