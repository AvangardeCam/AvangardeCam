# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Helix milling: CAM > Helix on holes clicked in the model or circles of a
sketch (Shift+click adds the next one; the order is the tool's), its
window, its details and Edit... (model.helix, engine.helix).

The window: the holes, the tool (ui.tool_choice; the one used last for a
helix milling, else the setup's first end mill), the depth (holes of a
model: from the model by default, the end of each hole or out under a
through one; else the user's, from the top of each hole), the pitch (Auto:
the tool's Ø x tan 5°), Finish XY (two passes; 0: one), the XY offset (a
bigger or smaller hole, for a fit), the step over and the diameter drilled
before (widening passes), the passes (helices, or a helix then circles on
Z steps) and the compensation (RL climbs with M3, as the shop's programs; RR is
conventional). Under them the passes in the first hole. The window starts
with the values used last, but the depth from the model (holes of a
model), no XY offset and nothing drilled before: those belong to the
holes, a forgotten one would mill a wrong hole.
"""

import dataclasses

import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.engine import helix as engine_helix
from avangardecam.model import helix as model_helix
from avangardecam.model import nc
from avangardecam.model import operations as model_operations
from avangardecam.ui import details, manual, number_entry, window_fit
from avangardecam.ui.tool_choice import ToolChooser, library_id

DEFAULT_DEPTH_MM = -10.0  # of a sketch's circles, the first time
_LAST = "LastHelixMilling"  # the values, as JSON
LAST_TOOL = "LastHelixTool"  # library id

# what the messages of picking holes say (handlers._picked_holes)
WORDS = {
    "done": QT_TRANSLATE_NOOP("AvangardeCam", "milled"),
    "to": QT_TRANSLATE_NOOP("AvangardeCam", "to mill"),
    "button": QT_TRANSLATE_NOOP("AvangardeCam", "Helix"),
}
_METHODS = (
    (model_helix.HELIX, QT_TRANSLATE_NOOP("AvangardeCam", "Helices")),
    (model_helix.HELIX_CONTOUR, QT_TRANSLATE_NOOP("AvangardeCam", "Helix, then circles")),
)
_SIDES = (
    (nc.LEFT, QT_TRANSLATE_NOOP("AvangardeCam", "RL: climb with M3")),
    (nc.RIGHT, QT_TRANSLATE_NOOP("AvangardeCam", "RR: conventional with M3")),
)
# (field, label, object name, tip) of the length fields
_LENGTHS = (
    ("depth_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Depth"), "Depth", QT_TRANSLATE_NOOP("AvangardeCam", "Z-Depth, negative from the top of each hole")),  # fmt: skip
    ("through_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Out under through holes"), "Through", QT_TRANSLATE_NOOP("AvangardeCam", "With the depth from the model, the tool goes this far under a hole that goes through")),  # fmt: skip
    ("pitch_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Pitch"), "Pitch", QT_TRANSLATE_NOOP("AvangardeCam", "The most the helix goes down in one turn; its half turns are equal")),  # fmt: skip
    ("finish_xy_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Finish XY"), "FinishXY", QT_TRANSLATE_NOOP("AvangardeCam", "The rough passes leave this on the wall, a last pass takes it; 0: one pass")),  # fmt: skip
    ("offset_xy_mm", QT_TRANSLATE_NOOP("AvangardeCam", "XY offset"), "OffsetXY", QT_TRANSLATE_NOOP("AvangardeCam", "The hole this much bigger than its circle (negative: smaller), for a fit")),  # fmt: skip
    ("predrilled_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Drilled Ø"), "Drilled", QT_TRANSLATE_NOOP("AvangardeCam", "Ø of the hole drilled before; 0: the tool mills it from solid")),  # fmt: skip
    ("z_step_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Z step"), "ZStep", QT_TRANSLATE_NOOP("AvangardeCam", "Of the circles after the helix: full steps down from the top, the rest at the depth; 0: at the depth only")),  # fmt: skip
)
_LABELS = {field: label for field, label, _name, _tip in _LENGTHS}
# FreeCAD's length boxes round to the decimals of the user's units (2 by
# default): the pitch (0.2625 for Ø3) and the XY values of a fit need more
_DECIMALS = {"pitch_mm": 4, "finish_xy_mm": 3, "offset_xy_mm": 3}


def _mm_box(value, decimals, minimum, maximum):
    """A number of mm with more decimals than FreeCAD's length boxes; the
    unit stays in the box ("0.2625 mm") and nothing else can be typed."""
    box = QtWidgets.QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(minimum, maximum)
    box.setSuffix(" mm")
    box.setValue(value)
    return number_entry.install(box)


def _value(box):
    return box.value() if isinstance(box, QtWidgets.QDoubleSpinBox) else float(box.property("rawValue"))


def _set_value(box, value):
    if isinstance(box, QtWidgets.QDoubleSpinBox):
        box.setValue(value)
    else:
        box.setProperty("rawValue", value)


def is_helix_tool(tool):
    return tool is not None and tool.shape in engine_helix.HELIX_SHAPES


def last_helix_milling(model):
    """A helix milling with the values used last, else the defaults: the
    depth from the model for holes of a model, else the last one typed; no
    XY offset and nothing drilled."""
    text = params().GetString(_LAST, "")
    try:
        last = model_operations.from_json(text) if text else None
    except (ValueError, TypeError):
        last = None
    if not isinstance(last, model_helix.HelixMilling):
        last = model_helix.HelixMilling()
    depth = None if model else (last.depth_mm if last.depth_mm is not None else DEFAULT_DEPTH_MM)
    return dataclasses.replace(last, depth_mm=depth, offset_xy_mm=0.0, predrilled_mm=0.0)


def feeds_text(tool):
    """The feeds a helix milling takes from a model Tool: Z down to the top of the holes."""
    if tool is None or not (tool.feed_xy_mm_min and tool.feed_z_mm_min):
        return details.NONE
    return tr("Z {:g} (down to the top), XY {:g} mm/min").format(tool.feed_z_mm_min, tool.feed_xy_mm_min)


def passes_text(milling, tool, hole):
    """What the tool does in a hole (model.helix.HelixHole): "2 helices:
    Ø4.3, Ø4.5 (finishing); 61 turns of P0.2625 each"."""
    walls = milling.walls(tool.diameter_mm, hole.diameter_mm)
    pitch = milling.pitch(tool.diameter_mm)
    turns = model_helix.half_turns(hole.top - hole.bottom, pitch) / 2.0
    sizes = ["Ø{:g}".format(round(2.0 * wall, 3)) for wall in walls]
    if milling.finish_xy_mm and len(sizes) > 1:
        sizes[-1] += " " + tr("(finishing)")
    helix_text = tr("{:g} turns of P{:g}").format(turns, round(pitch, 4))
    if len(walls) == 1:
        return tr("1 helix {}, {}").format(sizes[0], helix_text)
    if milling.method == model_helix.HELIX:
        return tr("{} helices: {}; {} each").format(len(walls), ", ".join(sizes), helix_text)
    levels = len(milling.levels(hole.top, hole.bottom))
    on = tr("1 level") if levels == 1 else tr("{} levels").format(levels)
    return tr("Helix {}, {}; then circles {} on {}").format(sizes[0], helix_text, ", ".join(sizes[1:]), on)


def fit_text(milling, tool, targets):
    """What is wrong between the tool (model Tool), the values and the holes (DrillTarget), else ""."""
    if tool is None:
        return ""
    try:
        engine_helix.hole_cuts(milling, tool, targets)
    except cam.ProjectError as exc:
        return str(exc)
    return ""


def _model_depth(targets):
    """The depth from the model of the first hole (negative), shown in the depth field."""
    hole = targets[0].hole if targets else None
    return round(hole.depth_mm, 6) if hole is not None else None


class HelixFields(QtCore.QObject):
    """The values of a helix milling as rows of a form. typed: a value was
    typed or chosen. model: the holes are a model's (they have a depth)."""

    typed = QtCore.Signal()

    def __init__(self, form, milling, model_depth, model, parent=None):
        super().__init__(parent)
        self.boxes = {}
        self.model = model
        self.model_depth = model_depth  # of the first hole, shown with the depth from the model
        self.auto_value = None  # the pitch of the tool, shown while Auto is on
        limit = model_operations.MAX_DEPTH_MM

        def emit(*_args):
            self.typed.emit()

        def length(field, value, minimum=-limit):
            _field, _label, name, tip = next(item for item in _LENGTHS if item[0] == field)
            if field in _DECIMALS:
                box = _mm_box(value, _DECIMALS[field], minimum, limit)
            else:  # any length: a wrong one is refused by the model, not clamped
                box = details.length_box(value, minimum, limit)
            box.setObjectName("AvangardeCamHelix" + name)
            box.setToolTip(tr(tip))
            box.valueChanged.connect(emit)
            self.boxes[field] = box
            return box

        def checked_row(label, box, check):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(box, 1)
            row.addWidget(check)
            form.addRow(tr(label) + ":", row)

        self.from_model = QtWidgets.QCheckBox(tr("From the model"))
        self.from_model.setObjectName("AvangardeCamHelixFromModel")
        self.from_model.setToolTip(tr("Down to the end of each hole, or out under a hole that goes through"))
        depth = milling.depth_mm if milling.depth_mm is not None else model_depth or DEFAULT_DEPTH_MM
        checked_row(_LABELS["depth_mm"], length("depth_mm", depth), self.from_model)
        self.from_model.setChecked(model and milling.depth_mm is None)
        self.from_model.setEnabled(model)
        self.from_model.toggled.connect(self._from_model)
        form.addRow(tr(_LABELS["through_mm"]) + ":", length("through_mm", milling.through_mm, 0.0))
        self.auto_pitch = QtWidgets.QCheckBox(tr("Auto"))
        self.auto_pitch.setObjectName("AvangardeCamHelixAutoPitch")
        self.auto_pitch.setToolTip(tr("The tool's diameter x tan 5°"))
        checked_row(_LABELS["pitch_mm"], length("pitch_mm", milling.pitch_mm or 0.0, 0.0), self.auto_pitch)
        self.auto_pitch.setChecked(milling.pitch_mm is None)
        self.auto_pitch.toggled.connect(self._auto_pitch)
        form.addRow(tr(_LABELS["finish_xy_mm"]) + ":", length("finish_xy_mm", milling.finish_xy_mm, 0.0))
        form.addRow(tr(_LABELS["offset_xy_mm"]) + ":", length("offset_xy_mm", milling.offset_xy_mm))

        self.step_over = QtWidgets.QDoubleSpinBox()
        self.step_over.setObjectName("AvangardeCamHelixStepOver")
        self.step_over.setRange(1.0, 100.0)
        self.step_over.setDecimals(1)
        self.step_over.setSuffix(" %")
        self.step_over.setValue(milling.step_over_percent)
        number_entry.install(self.step_over)
        self.step_over.setToolTip(tr("The most of the tool's diameter a pass widens the hole by; the passes are spread evenly"))  # fmt: skip
        self.step_over.valueChanged.connect(emit)
        self.step_over_mm = QtWidgets.QLabel()
        self.step_over_mm.setObjectName("AvangardeCamHelixStepOverMm")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.step_over, 1)
        row.addWidget(self.step_over_mm)
        form.addRow(tr("Step over") + ":", row)
        form.addRow(tr(_LABELS["predrilled_mm"]) + ":", length("predrilled_mm", milling.predrilled_mm, 0.0))

        self.method = QtWidgets.QComboBox()
        self.method.setObjectName("AvangardeCamHelixMethod")
        for key, text in _METHODS:
            self.method.addItem(tr(text), key)
        self.method.setCurrentIndex(max(0, self.method.findData(milling.method)))
        self.method.setToolTip(tr("Every pass a helix from the top; or the first one a helix, the wider passes and the finishing pass circles on the Z steps"))  # fmt: skip
        self.method.currentIndexChanged.connect(self._method)
        form.addRow(tr("Passes") + ":", self.method)
        form.addRow(tr(_LABELS["z_step_mm"]) + ":", length("z_step_mm", milling.z_step_mm or 0.0, 0.0))

        self.side = QtWidgets.QComboBox()
        self.side.setObjectName("AvangardeCamHelixSide")
        for key, text in _SIDES:
            self.side.addItem(tr(text), key)
        self.side.setCurrentIndex(max(0, self.side.findData(milling.compensation)))
        self.side.setToolTip(tr("The radius compensation, on from the first pass: RL goes round counterclockwise, RR clockwise"))  # fmt: skip
        self.side.currentIndexChanged.connect(emit)
        form.addRow(tr("Compensation") + ":", self.side)
        self._enable()

    def _enable(self):
        from_model = self.from_model.isChecked()
        self.boxes["depth_mm"].setEnabled(not from_model)
        self.boxes["through_mm"].setEnabled(from_model)
        self.boxes["pitch_mm"].setEnabled(not self.auto_pitch.isChecked())
        self.boxes["z_step_mm"].setEnabled(self.method.currentData() == model_helix.HELIX_CONTOUR)

    def _from_model(self, checked):
        if checked and self.model_depth is not None:
            box = self.boxes["depth_mm"]
            box.blockSignals(True)
            box.setProperty("rawValue", self.model_depth)
            box.blockSignals(False)
        self._enable()
        self.typed.emit()

    def _auto_pitch(self, _checked):
        self._enable()
        self.typed.emit()

    def _method(self, *_args):
        self._enable()
        self.typed.emit()

    def show_tool(self, tool):
        """The step over in mm and, while Auto is on, the pitch of a model Tool."""
        if tool is not None and tool.diameter_mm:
            self.step_over_mm.setText("= {:g} mm".format(round(tool.diameter_mm * self.step_over.value() / 100.0, 3)))
        else:
            self.step_over_mm.setText("")
        box = self.boxes["pitch_mm"]
        if self.auto_pitch.isChecked() and tool is not None and tool.diameter_mm and not box.hasFocus():
            box.blockSignals(True)
            _set_value(box, model_helix.auto_pitch(tool.diameter_mm))
            box.blockSignals(False)

    def unreadable(self):
        """Label of the first field that does not hold a length, else ""."""
        for field, box in self.boxes.items():
            if box.isEnabled() and not box.hasAcceptableInput():
                return tr(_LABELS[field])
        return ""

    def milling(self):
        values = {field: _value(box) for field, box in self.boxes.items()}
        values["z_step_mm"] = values["z_step_mm"] or None  # 0: at the depth only
        if self.from_model.isChecked():
            values["depth_mm"] = None
        if self.auto_pitch.isChecked():
            values["pitch_mm"] = None
        return model_helix.HelixMilling(
            step_over_percent=self.step_over.value(),
            method=self.method.currentData(),
            compensation=self.side.currentData(),
            **values,
        )

    def busy(self):
        """True while the user is in a field."""
        return any(w.hasFocus() for w in list(self.boxes.values()) + [self.step_over])

    def show(self, milling, model_depth):
        """Show a helix milling's values, but not in the field being typed in."""
        self.model_depth = model_depth
        shown = dataclasses.asdict(milling)
        shown["depth_mm"] = model_depth if milling.depth_mm is None else milling.depth_mm
        shown["z_step_mm"] = milling.z_step_mm or 0.0
        if milling.pitch_mm is None:
            shown.pop("pitch_mm")  # show_tool fills it in
        for field, box in self.boxes.items():
            if field in shown and shown[field] is not None and not box.hasFocus():
                box.blockSignals(True)
                _set_value(box, shown[field])
                box.blockSignals(False)
        widgets = (
            (self.from_model, lambda w: w.setChecked(milling.depth_mm is None)),
            (self.auto_pitch, lambda w: w.setChecked(milling.pitch_mm is None)),
            (self.step_over, lambda w: w.setValue(milling.step_over_percent) if not w.hasFocus() else None),
            (self.method, lambda w: w.setCurrentIndex(w.findData(milling.method))),
            (self.side, lambda w: w.setCurrentIndex(w.findData(milling.compensation))),
        )
        for widget, set_value in widgets:
            widget.blockSignals(True)
            set_value(widget)
            widget.blockSignals(False)
        self._enable()


class HelixDialog(QtWidgets.QDialog):
    """job: the setup; source: the sketch or the model of the holes; text:
    the holes as the window shows them; targets: the holes
    (freecad_cam.DrillTarget), in the tool's order; ignored: how many other
    lines were selected; library: the tool library's variants
    (LibraryTool). To edit a helix milling: start, its model HelixMilling,
    and tool, its ProjectTool; the values used last are then neither shown
    nor remembered."""

    def __init__(self, job, source, text, targets, library=(), ignored=0, parent=None, start=None, tool=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamHelixDialog")
        self.setWindowTitle(tr("Helix milling"))
        self.job = job
        self.editing = start is not None
        self.targets = list(targets)
        model = not geometry.is_sketch(source)

        box = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(tr("Helix milling: down a helix with RL/RR from the start, no mark on the wall"))
        heading.setStyleSheet("font-weight: bold;")
        box.addWidget(heading)
        form = QtWidgets.QFormLayout()
        box.addLayout(form)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        form.addRow((tr("Model") if model else tr("Sketch")) + ":", QtWidgets.QLabel(source.Label))
        if ignored:
            text += "  " + tr("({} other lines are left out)").format(ignored)
        holes = QtWidgets.QLabel(text)
        holes.setObjectName("AvangardeCamHelixHoles")
        form.addRow(tr("Holes") + ":", holes)
        self.chooser = ToolChooser(job, "AvangardeCamHelix")
        form.addRow(tr("Tool") + ":", self.chooser)
        self.fit = QtWidgets.QLabel()
        self.fit.setObjectName("AvangardeCamHelixFit")
        self.fit.setWordWrap(True)
        self.fit.setStyleSheet("color: #b9770e;")
        form.addRow(self.fit)
        self.feeds = QtWidgets.QLabel()
        self.feeds.setObjectName("AvangardeCamHelixFeeds")
        form.addRow(tr("Feeds") + ":", self.feeds)
        self.chooser.follow(self.feeds, feeds_text)  # the operation's own spindle speed and feeds
        first = start if start is not None else last_helix_milling(model)
        self.fields = HelixFields(form, first, _model_depth(self.targets), model, self)
        self.passes = QtWidgets.QLabel()
        self.passes.setObjectName("AvangardeCamHelixPasses")
        self.passes.setWordWrap(True)
        form.addRow(tr("Passes") + ":", self.passes)

        manual_text = tr("The tool goes down to the top of each hole, out from its centre with the radius compensation on, onto the wall on a half circle and down a helix in equal half turns to the depth, once round there and off the wall on a half circle: no mark where it comes in, and the size is corrected with DR on the machine. With Finish XY a rough pass leaves it and a last pass takes it. A hole wider than the tool clears at once, or one drilled before (Drilled Ø), is widened in passes no wider than the step over: helices, or after the first helix circles on the Z steps. The holes are milled in the order they were clicked.")  # fmt: skip
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamHelixMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Helix milling"), manual_text)
        box.addWidget(buttons)

        for signal in (self.chooser.changed, self.fields.typed):
            signal.connect(self._update)
            signal.connect(lambda: self.message.setText(""))
        if tool is not None:
            self.chooser.choose(tool)
        else:
            self.chooser.start_with(library, params().GetString(LAST_TOOL, ""), is_helix_tool)
        self._update()
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self.fields.boxes["finish_xy_mm"].setFocus()

    def use(self, entry):
        self.chooser.use(entry)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        return self.chooser.tool()

    def milling(self):
        return self.fields.milling()

    def _update(self, *_args):
        choice = self.tool()
        tool = choice.tool if choice is not None else None
        self.feeds.setText(feeds_text(self.chooser.cutting_tool()))
        self.fields.show_tool(tool)
        try:
            milling = self.milling().validate() if not self.fields.unreadable() else None
        except ValueError:
            milling = None
        self.passes.setText(details.NONE)
        if milling is None or not self.targets:
            self.fit.setText("")
        else:
            wrong = fit_text(milling, tool, self.targets)
            if not wrong and tool is not None:
                first = engine_helix.helix_holes(milling, self.targets[:1])[0]
                self.passes.setText(passes_text(milling, tool, first))
            self.fit.setText(wrong)
        self.fit.setVisible(bool(self.fit.text()))

    def accept(self):
        if self.tool() is None:
            self.message.setText(tr("Choose a tool: one of the setup's or with Choose tool... from the tool library."))
            return
        unreadable = self.fields.unreadable()
        if unreadable:
            self.message.setText(tr("{}: enter a length, for example 2 mm.").format(unreadable))
            return
        try:
            milling = self.milling().validate()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        wrong = fit_text(milling, self.tool().tool, self.targets)
        if wrong:
            self.message.setText(wrong)
            return
        if self.editing:
            return super().accept()
        params().SetString(_LAST, model_operations.to_json(milling))
        if library_id(self.tool()):
            params().SetString(LAST_TOOL, library_id(self.tool()))
        super().accept()


def _targets(job, source, names):
    """DrillTargets of the holes picked (handlers._picked_holes)."""
    if geometry.is_sketch(source):
        return engine_helix.sketch_holes(job, source, names)[1]
    return engine_helix.model_holes(job, source, names)[1]


def make(sketch=None):
    """CAM > Helix (or Helix milling... of a sketch): the holes clicked in
    the model or the circles of a sketch, in the order they were clicked."""
    from avangardecam import handlers

    picked = handlers._picked_holes(sketch, WORDS)
    if picked is None:
        return
    job, source, names = picked.job, picked.source, picked.names
    try:
        targets = _targets(job, source, names)
    except cam.ProjectError as exc:
        handlers._error(str(exc))
        return
    dialog = HelixDialog(job, source, picked.text, targets, handlers._library(), picked.ignored)
    if picked.model:
        make_op = lambda tc: engine_helix.add_model_helix_milling(job, source, dialog.milling(), tc, names)  # noqa: E731
    else:
        make_op = lambda tc: engine_helix.add_helix_milling(job, source, dialog.milling(), tc, names)  # noqa: E731
    if handlers._add_operation(source.Document, job, dialog, make_op, tr("Helix milling")) and picked.model:
        # FreeCAD leaves the whole model selected (all red); its holes are the operation's now
        FreeCADGui.Selection.clearSelection()


def holes_text(op):
    """The holes of a helix milling as the windows show them."""
    from avangardecam.ui.drilling_dialog import holes_text as circles_text
    from avangardecam.ui.drilling_dialog import picked_text

    source, _milling = engine_helix.helix_milling_of(op)
    if geometry.is_sketch(source):
        return circles_text(source, cam.drilling_circles(op))
    return picked_text([(t.diameter, t.hole) for t in cam.drill_targets(op)])


def edit_dialog(op, job, tool, library):
    """(window, its values) to edit a helix milling (handlers.edit_operation)."""
    source, milling = engine_helix.helix_milling_of(op)
    dialog = HelixDialog(job, source, holes_text(op), cam.drill_targets(op), library, start=milling, tool=tool)
    return dialog, dialog.milling


class HelixView(details.DetailsView):
    """Helix milling: typed values are applied after a pause, chosen ones at
    once; each change is one undo step."""

    APPLY_DELAY_MS = 600

    def __init__(self, op, parent=None):
        from avangardecam import handlers

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.op = op
        self.job = cam.setup_of(op)
        source, milling = engine_helix.helix_milling_of(op)
        model = not geometry.is_sketch(source)
        self.add_row(tr("Setup"), self.job.Label if self.job else details.NONE)
        self.add_row(tr("Model") if model else tr("Sketch"), source.Label)
        self.holes_label = self.add_row(tr("Holes"), "")
        self.holes_label.setWordWrap(True)
        self.tool_label = self.add_row(tr("Tool"), "")
        self.tool_label.setWordWrap(True)
        self.feeds_label = self.add_row(tr("Feeds"), "")
        self.top_label = self.add_row(tr("Holes' top"), "")
        self.fields = HelixFields(self.form, milling, _model_depth(self._targets()), model, self)
        self.fields.typed.connect(self._schedule_apply)
        self.passes_label = self.add_row(tr("Passes"), "")
        self.passes_label.setWordWrap(True)
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("Each hole in the order shown under Holes: onto the wall on a half circle with the radius compensation, down a helix, once round at the depth and off the wall. In 3D the passes are where the tool's edge cuts, as the program has them; the simulation runs the tool centre.")  # fmt: skip
        )
        self.add_button(tr("Change tool..."), lambda: handlers.change_tool(self.op), "AvangardeCamChangeTool")
        self.add_button(tr("Remove operation"), self._remove, "AvangardeCamRemoveOperation")
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply)
        self.update_view()

    def _targets(self):
        try:
            return cam.drill_targets(self.op)
        except cam.ProjectError:  # the model changed
            return []

    def _schedule_apply(self, *_args):
        self._timer.start(self.APPLY_DELAY_MS)

    def apply(self, *_args):
        self._timer.stop()
        if self.fields.unreadable():
            return  # still being typed
        try:
            wanted = self.fields.milling().validate()
        except ValueError as exc:
            details._show_error(str(exc))
            return
        if wanted == engine_helix.helix_milling_of(self.op)[1]:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Helix milling"))
        try:
            engine_helix.set_helix_milling(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            details._show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        _source, milling = engine_helix.helix_milling_of(self.op)
        try:
            targets = cam.drill_targets(self.op)
            self.holes_label.setText(holes_text(self.op))
        except cam.ProjectError as exc:  # the model changed
            targets = []
            self.holes_label.setText(str(exc))
        tc = self.op.ToolController
        tool = next((t.tool for t in cam.project_tools(self.job) if t.controller is tc), None)
        self.tool_label.setText(details.tool_row_text(self.op, self.job))
        self.feeds_label.setText(feeds_text(details.cutting_tool(self.op)))
        self.fields.show_tool(tool)
        tops = sorted({round(t.top, 2) + 0.0 for t in targets})
        if len(tops) > 1:
            self.top_label.setText("Z {:.2f} … {:.2f} mm".format(tops[-1], tops[0]))
        else:
            self.top_label.setText("Z {:.2f} mm".format(tops[0] if tops else round(cam.contour_depths(self.op)[0], 2) + 0.0))  # fmt: skip
        self.passes_label.setText(details.NONE)
        if targets and tool is not None and not fit_text(milling, tool, targets):
            self.passes_label.setText(passes_text(milling, tool, engine_helix.helix_holes(milling, targets[:1])[0]))
        moves, lowest = cam.path_summary(self.op)
        if moves and lowest is not None:
            self.path_label.setText(tr("{} holes, down to Z {:.2f} mm").format(len(targets), round(lowest, 2) + 0.0))
        else:
            self.path_label.setText(details._no_path(self.op))
        if not self._timer.isActive():
            self.fields.show(milling, _model_depth(targets))
            self.fields.show_tool(tool)

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()
