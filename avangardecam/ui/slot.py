# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Slot milling: CAM > Slot on slots clicked in the model (a wall, a round
end, the floor or an edge; Shift+click adds the next slot), its window,
its details and Edit... (model.slot, engine.slot).

The window: the slots, the tool (ui.tool_choice; the one used last for a
slot milling, else the setup's first end mill), the depth (from the
model by default: the floor, or out under a through slot; else the
user's, from the top of each slot), Z step, step over, the finishing
allowances in XY and Z, the side of the finishing pass (RL climbs with
M3, RR is conventional); the ramp (to and fro or along the contour),
its angle and the approach radius under Advanced. Under them the Z levels of the first slot and the passes as
they are typed. The window starts with the values used last, but the
user's depth.
"""

import dataclasses

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import slot as engine_slot
from avangardecam.model import nc
from avangardecam.model import operations as model_operations
from avangardecam.model import slot as model_slot
from avangardecam.ui import details, manual, window_fit
from avangardecam.ui.tool_choice import ToolChooser, library_id

_LAST_SLOT = "LastSlotMilling"  # the values but the depth, as JSON
LAST_TOOL = "LastSlotTool"  # library id
_SHOWN_LEVELS = 8

_SIDES = (
    (nc.LEFT, QT_TRANSLATE_NOOP("AvangardeCam", "RL: climb with M3")),
    (nc.RIGHT, QT_TRANSLATE_NOOP("AvangardeCam", "RR: conventional with M3")),
)
_RAMPS = (
    (model_slot.RAMP_TO_AND_FRO, QT_TRANSLATE_NOOP("AvangardeCam", "To and fro along the centre line")),
    (model_slot.RAMP_CONTOUR, QT_TRANSLATE_NOOP("AvangardeCam", "Along the contour")),
)
# (field, label, object name, tip) of the length fields
_LENGTHS = (
    ("depth_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Depth"), "Depth", QT_TRANSLATE_NOOP("AvangardeCam", "Of the floor, below the top of each slot (negative)")),  # fmt: skip
    ("through_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Out under through slots"), "Through", QT_TRANSLATE_NOOP("AvangardeCam", "With the depth from the model, the tool goes this far under a slot that goes through")),  # fmt: skip
    ("z_step_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Z step"), "ZStep", QT_TRANSLATE_NOOP("AvangardeCam", "Full steps down from the top of the slot, the rest at the floor; 0: the whole depth at once")),  # fmt: skip
    ("finish_xy_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Finish XY"), "FinishXY", QT_TRANSLATE_NOOP("AvangardeCam", "The rough passes leave this on the walls; the finishing pass with RL/RR takes it")),  # fmt: skip
    ("finish_z_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Finish Z"), "FinishZ", QT_TRANSLATE_NOOP("AvangardeCam", "The rough passes leave this on the floor; a last level clears it")),  # fmt: skip
    ("lead_radius_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Approach radius"), "LeadRadius", QT_TRANSLATE_NOOP("AvangardeCam", "Of the arcs of the finishing pass on and off the wall: more than the tool's radius, at most half the slot")),  # fmt: skip
)
_LABELS = {field: label for field, label, _name, _tip in _LENGTHS}


def is_slot_tool(tool):
    return tool is not None and tool.shape in engine_slot.SLOT_SHAPES


def last_slot_milling():
    """A slot milling with the values used last (the depth from the model), else the defaults."""
    text = params().GetString(_LAST_SLOT, "")
    try:
        last = model_operations.from_json(text) if text else None
    except (ValueError, TypeError):
        last = None
    if not isinstance(last, model_slot.SlotMilling):
        last = model_slot.SlotMilling()
    return dataclasses.replace(last, depth_mm=None)


def feeds_text(tool):
    """The feeds a slot milling takes from a model Tool: Z for the ramps."""
    if tool is None or not (tool.feed_xy_mm_min and tool.feed_z_mm_min):
        return details.NONE
    return tr("Z {:g} (ramps), XY {:g} mm/min").format(tool.feed_z_mm_min, tool.feed_xy_mm_min)


def _size(found):
    """"20 x 10, 6 deep" or "16 x 8, through" of a slot (ModelSlot)."""
    s = found.slot
    size = "{:g} × {:g}".format(round(s.length_mm() + s.width_mm, 3), round(s.width_mm, 3))
    if found.through:
        return tr("{}, through").format(size)
    return tr("{}, {:g} deep").format(size, round(found.depth_mm(), 3))


def slots_text(model, found):
    """"Slot 20 × 10, 6 deep in Body" or "2 slots in Body: 20 × 10, 6 deep; 16 × 8, through"."""
    if len(found) == 1:
        return tr("Slot {} in {}").format(_size(found[0]), model.Label)
    return tr("{} slots in {}: {}").format(len(found), model.Label, "; ".join(_size(f) for f in found))


def levels_text(levels):
    """"Z -3.00, -6.00 (2 levels)", the first ones of many."""
    if not levels:
        return details.NONE
    shown = ", ".join("{:+.2f}".format(round(z, 2) + 0.0) for z in levels[:_SHOWN_LEVELS])
    if len(levels) > _SHOWN_LEVELS:
        shown += ", …"
    count = tr("1 level") if len(levels) == 1 else tr("{} levels").format(len(levels))
    return "Z {} ({})".format(shown, count)


def passes_text(milling, tool, cut):
    """What the tool does in a slot (model.slot.SlotCut) on each level."""
    if model_slot.as_wide_as_tool(tool.diameter_mm, cut.slot.width_mm):
        return tr("Ramp to and fro, then once along the centre line (the slot is as wide as the tool, no finishing pass)")  # fmt: skip
    round_ramp, rough = milling.passes(tool.diameter_mm, cut.slot.width_mm)
    if round_ramp is None:
        text = tr("Ramp to and fro, along the centre line")
        if milling.ramp == model_slot.RAMP_CONTOUR:
            text += " " + tr("(no room for the ramp along the contour)")
    else:
        text = tr("Ramp along the contour {:g} mm from the centre line, once round").format(round(round_ramp, 3))
    rough = len(rough)
    if rough:
        text += ", " + (tr("1 pass around it") if rough == 1 else tr("{} passes around it").format(rough))
    side = "RL" if milling.compensation == nc.LEFT else "RR"
    walls = len(milling.wall_levels(cut.top, cut.floor))
    text += "; " + tr("the walls finished with {} on {}").format(side, tr("1 level") if walls == 1 else tr("{} levels").format(walls))  # fmt: skip
    return text


def fit_text(milling, tool, found):
    """What is wrong between the tool (model Tool), the values and the slots, else ""."""
    if tool is None:
        return ""
    try:
        engine_slot.slot_cuts(milling, tool, found)
    except cam.ProjectError as exc:
        return str(exc)
    return ""


class SlotFields(QtCore.QObject):
    """The values of a slot milling as rows of a form; the ramp angle and
    the approach radius under Advanced. typed: a value was typed or chosen."""

    typed = QtCore.Signal()

    def __init__(self, form, milling, model_depth, parent=None):
        super().__init__(parent)
        self.boxes = {}
        limit = model_operations.MAX_DEPTH_MM
        self.model_depth = model_depth  # of the first slot, shown with the depth from the model

        def emit(*_args):
            self.typed.emit()

        def length(field, value, minimum=-limit):
            _field, _label, name, tip = next(item for item in _LENGTHS if item[0] == field)
            # any length: a wrong one is refused by the model, not clamped
            box = details.length_box(value, minimum, limit)
            box.setObjectName("AvangardeCamSlot" + name)
            box.setToolTip(tr(tip))
            box.valueChanged.connect(emit)
            self.boxes[field] = box
            return box

        self.from_model = QtWidgets.QCheckBox(tr("From the model"))
        self.from_model.setObjectName("AvangardeCamSlotFromModel")
        self.from_model.setToolTip(tr("Down to the floor of each slot, or out under a slot that goes through"))
        depth = length("depth_mm", model_depth if milling.depth_mm is None else milling.depth_mm)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(depth, 1)
        row.addWidget(self.from_model)
        form.addRow(tr("Depth") + ":", row)
        self.from_model.setChecked(milling.depth_mm is None)
        self.from_model.toggled.connect(self._from_model)
        form.addRow(tr(_LABELS["through_mm"]) + ":", length("through_mm", milling.through_mm))
        form.addRow(tr(_LABELS["z_step_mm"]) + ":", length("z_step_mm", milling.z_step_mm or 0.0))

        self.step_over = QtWidgets.QDoubleSpinBox()
        self.step_over.setObjectName("AvangardeCamSlotStepOver")
        self.step_over.setRange(1.0, 100.0)
        self.step_over.setDecimals(1)
        self.step_over.setSuffix(" %")
        self.step_over.setValue(milling.step_over_percent)
        self.step_over.setToolTip(tr("The most of the tool's diameter a rough pass grows by; the passes are spread evenly"))  # fmt: skip
        self.step_over.valueChanged.connect(emit)
        self.step_over_mm = QtWidgets.QLabel()
        self.step_over_mm.setObjectName("AvangardeCamSlotStepOverMm")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.step_over, 1)
        row.addWidget(self.step_over_mm)
        form.addRow(tr("Step over") + ":", row)
        form.addRow(tr(_LABELS["finish_xy_mm"]) + ":", length("finish_xy_mm", milling.finish_xy_mm))
        form.addRow(tr(_LABELS["finish_z_mm"]) + ":", length("finish_z_mm", milling.finish_z_mm))

        self.side = QtWidgets.QComboBox()
        self.side.setObjectName("AvangardeCamSlotSide")
        for key, text in _SIDES:
            self.side.addItem(tr(text), key)
        self.side.setCurrentIndex(max(0, self.side.findData(milling.compensation)))
        self.side.setToolTip(tr("The radius compensation of the finishing pass along the walls; the rough passes go the same way round"))  # fmt: skip
        self.side.currentIndexChanged.connect(emit)
        form.addRow(tr("Finishing") + ":", self.side)

        self.more = QtWidgets.QToolButton()
        self.more.setObjectName("AvangardeCamSlotAdvanced")
        self.more.setText(tr("Advanced"))
        self.more.setCheckable(True)
        self.more.setArrowType(QtCore.Qt.RightArrow)
        self.more.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.more.setAutoRaise(True)
        form.addRow(self.more)
        self.advanced = QtWidgets.QWidget()
        advanced = QtWidgets.QFormLayout(self.advanced)
        advanced.setContentsMargins(12, 0, 0, 0)
        self.ramp = QtWidgets.QDoubleSpinBox()
        self.ramp.setObjectName("AvangardeCamSlotRampAngle")
        self.ramp.setRange(0.1, 45.0)
        self.ramp.setDecimals(1)
        self.ramp.setSuffix(" °")
        self.ramp.setValue(milling.ramp_angle_deg)
        self.ramp.setToolTip(tr("The steepest the tool goes down along the slot"))
        self.ramp.valueChanged.connect(emit)
        self.ramp_kind = QtWidgets.QComboBox()
        self.ramp_kind.setObjectName("AvangardeCamSlotRamp")
        for key, text in _RAMPS:
            self.ramp_kind.addItem(tr(text), key)
        self.ramp_kind.setCurrentIndex(max(0, self.ramp_kind.findData(milling.ramp)))
        self.ramp_kind.setToolTip(tr("Along the contour: round the centre line, the tool's radius from it at most, on lines and helices, the same way round as the passes; a slot without room for it is ramped to and fro"))  # fmt: skip
        self.ramp_kind.currentIndexChanged.connect(emit)
        advanced.addRow(tr("Ramp") + ":", self.ramp_kind)
        advanced.addRow(tr("Ramp angle") + ":", self.ramp)
        self.auto_lead = QtWidgets.QCheckBox(tr("Auto"))
        self.auto_lead.setObjectName("AvangardeCamSlotAutoLead")
        self.auto_lead.setToolTip(tr("The tool goes down 0.5 mm, or the finishing allowance, clear of the wall"))
        lead = length("lead_radius_mm", milling.lead_radius_mm or 0.0, 0.0)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(lead, 1)
        row.addWidget(self.auto_lead)
        advanced.addRow(tr(_LABELS["lead_radius_mm"]) + ":", row)
        self.auto_lead.setChecked(milling.lead_radius_mm is None)
        lead.setEnabled(milling.lead_radius_mm is not None)
        self.auto_lead.toggled.connect(self._auto_lead)
        form.addRow(self.advanced)
        self.advanced.setVisible(False)
        self.more.toggled.connect(self._show_advanced)
        self._enable()

    def _enable(self):
        from_model = self.from_model.isChecked()
        self.boxes["depth_mm"].setEnabled(not from_model)
        self.boxes["through_mm"].setEnabled(from_model)
        self.boxes["lead_radius_mm"].setEnabled(not self.auto_lead.isChecked())

    def _from_model(self, checked):
        if checked and self.model_depth is not None:
            box = self.boxes["depth_mm"]
            box.blockSignals(True)
            box.setProperty("rawValue", self.model_depth)
            box.blockSignals(False)
        self._enable()
        self.typed.emit()

    def _auto_lead(self, _checked):
        self._enable()
        self.typed.emit()

    def _show_advanced(self, shown):
        self.advanced.setVisible(shown)
        self.more.setArrowType(QtCore.Qt.DownArrow if shown else QtCore.Qt.RightArrow)

    def show_step_over(self, tool):
        """The step over in mm of a model Tool beside its percentage."""
        if tool is not None and tool.diameter_mm:
            self.step_over_mm.setText("= {:g} mm".format(round(tool.diameter_mm * self.step_over.value() / 100.0, 3)))
        else:
            self.step_over_mm.setText("")

    def show_lead(self, milling, tool, width_mm):
        """The automatic approach radius of a tool in the field while Auto is on."""
        box = self.boxes["lead_radius_mm"]
        if self.auto_lead.isChecked() and tool is not None and tool.diameter_mm and width_mm and not box.hasFocus():
            box.blockSignals(True)
            box.setProperty("rawValue", round(milling.lead_radius(tool.diameter_mm, width_mm), 6))
            box.blockSignals(False)

    def unreadable(self):
        """Label of the first field that does not hold a length, else ""."""
        for field, box in self.boxes.items():
            if box.isEnabled() and not box.hasAcceptableInput():
                return tr(_LABELS[field])
        return ""

    def milling(self):
        values = {field: float(box.property("rawValue")) for field, box in self.boxes.items()}
        values["z_step_mm"] = values["z_step_mm"] or None  # 0: the whole depth at once
        if self.from_model.isChecked():
            values["depth_mm"] = None
        if self.auto_lead.isChecked():
            values["lead_radius_mm"] = None
        return model_slot.SlotMilling(
            step_over_percent=self.step_over.value(),
            ramp_angle_deg=self.ramp.value(),
            compensation=self.side.currentData(),
            ramp=self.ramp_kind.currentData(),
            **values,
        )

    def busy(self):
        """True while the user is in a field."""
        return any(w.hasFocus() for w in list(self.boxes.values()) + [self.step_over, self.ramp])

    def show(self, milling, model_depth):
        """Show a slot milling's values, but not in the field being typed in."""
        self.model_depth = model_depth
        shown = dataclasses.asdict(milling)
        shown["depth_mm"] = model_depth if milling.depth_mm is None else milling.depth_mm
        shown["z_step_mm"] = milling.z_step_mm or 0.0
        if milling.lead_radius_mm is None:
            shown.pop("lead_radius_mm")  # show_lead fills it in
        for field, box in self.boxes.items():
            if field in shown and shown[field] is not None and not box.hasFocus():
                box.blockSignals(True)
                box.setProperty("rawValue", shown[field])
                box.blockSignals(False)
        widgets = (
            (self.from_model, lambda w: w.setChecked(milling.depth_mm is None)),
            (self.auto_lead, lambda w: w.setChecked(milling.lead_radius_mm is None)),
            (self.step_over, lambda w: w.setValue(milling.step_over_percent) if not w.hasFocus() else None),
            (self.ramp, lambda w: w.setValue(milling.ramp_angle_deg) if not w.hasFocus() else None),
            (self.side, lambda w: w.setCurrentIndex(w.findData(milling.compensation))),
            (self.ramp_kind, lambda w: w.setCurrentIndex(w.findData(milling.ramp))),
        )
        for widget, set_value in widgets:
            widget.blockSignals(True)
            set_value(widget)
            widget.blockSignals(False)
        self._enable()


def _model_depth(found):
    """The depth from the model of the first slot (negative), shown in the depth field."""
    return round(-found[0].depth_mm(), 6) if found else None


class SlotDialog(QtWidgets.QDialog):
    """job: the setup; model and elements: what was picked of its slots
    (names, "Face12", "Edge3"); library: the tool library's variants
    (LibraryTool). To edit a slot milling: start, its model SlotMilling,
    and tool, its ProjectTool; the values used last are then neither shown
    nor remembered."""

    def __init__(self, job, model, elements, library=(), parent=None, start=None, tool=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamSlotDialog")
        self.setWindowTitle(tr("Slot milling"))
        self.job = job
        self.editing = start is not None
        _base, self.found = engine_slot.picked_slots(job, model, list(elements))

        box = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(tr("Slot milling: ramping down along the slot, finishing the walls with RL/RR"))
        heading.setStyleSheet("font-weight: bold;")
        box.addWidget(heading)
        form = QtWidgets.QFormLayout()
        box.addLayout(form)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        slots = QtWidgets.QLabel(slots_text(model, self.found))
        slots.setObjectName("AvangardeCamSlotSlots")
        slots.setWordWrap(True)
        form.addRow(tr("Slots") + ":", slots)
        self.chooser = ToolChooser(job, "AvangardeCamSlot")
        form.addRow(tr("Tool") + ":", self.chooser)
        self.fit = QtWidgets.QLabel()
        self.fit.setObjectName("AvangardeCamSlotFit")
        self.fit.setWordWrap(True)
        self.fit.setStyleSheet("color: #b9770e;")
        form.addRow(self.fit)
        self.feeds = QtWidgets.QLabel()
        self.feeds.setObjectName("AvangardeCamSlotFeeds")
        form.addRow(tr("Feeds") + ":", self.feeds)
        first = start if start is not None else last_slot_milling()
        self.fields = SlotFields(form, first, _model_depth(self.found), self)
        self.levels = QtWidgets.QLabel()
        self.levels.setObjectName("AvangardeCamSlotLevels")
        self.levels.setWordWrap(True)
        form.addRow(tr("Z levels") + ":", self.levels)
        self.passes = QtWidgets.QLabel()
        self.passes.setObjectName("AvangardeCamSlotPasses")
        self.passes.setWordWrap(True)
        form.addRow(tr("Passes") + ":", self.passes)

        manual_text = tr("On each Z level the tool ramps down going to and fro along the slot's centre line (or round it, under Advanced), then clears out to the finishing allowance. Then the walls are finished level by level with the radius compensation, coming on and off on an arc in the middle of a wall, so the size can be corrected with DR on the machine.")  # fmt: skip
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamSlotMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Slot milling"), manual_text)
        box.addWidget(buttons)

        for signal in (self.chooser.changed, self.fields.typed):
            signal.connect(self._update)
            signal.connect(lambda: self.message.setText(""))
        if tool is not None:
            self.chooser.choose(tool)
        else:
            self.chooser.start_with(library, params().GetString(LAST_TOOL, ""), is_slot_tool)
        self._update()
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self.fields.step_over.setFocus()

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
        self.feeds.setText(feeds_text(tool))
        self.fields.show_step_over(tool)
        try:
            milling = self.milling().validate() if not self.fields.unreadable() else None
        except ValueError:
            milling = None
        self.passes.setText(details.NONE)
        if milling is None or not self.found:
            self.fit.setText("")
            self.levels.setText(details.NONE)
        else:
            self.fields.show_lead(milling, tool, self.found[0].slot.width_mm)
            first = self.found[0]
            floor = engine_slot.floor_of(milling, first)
            self.levels.setText(levels_text(milling.levels(first.top, floor)) if floor < first.top else details.NONE)
            wrong = fit_text(milling, tool, self.found)
            if not wrong and tool is not None:
                cut = model_slot.SlotCut(first.slot, first.top, floor)
                self.passes.setText(passes_text(milling, tool, cut))
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
        wrong = fit_text(milling, self.tool().tool, self.found)
        if wrong:
            self.message.setText(wrong)
            return
        if self.editing:
            return super().accept()
        params().SetString(_LAST_SLOT, model_operations.to_json(milling))
        if library_id(self.tool()):
            params().SetString(LAST_TOOL, library_id(self.tool()))
        super().accept()


def _setup(doc, model, elements):
    """The setup of a slot milling: the active one (the first, made now,
    when there is none) when the slots stand along its tool, else the first
    setup whose tool they stand along; else None after saying why."""
    from avangardecam import handlers
    from avangardecam.ui import scene

    if not cam.setups(doc):
        doc.openTransaction(tr("Create setup"))
        try:
            cam.ensure_job(doc)
        finally:
            doc.commitTransaction()
    active = scene.active_setup(doc)
    jobs = cam.setups(doc)
    if active in jobs:
        jobs.remove(active)
        jobs.insert(0, active)
    refused = None
    for job in jobs:
        try:
            engine_slot.picked_slots(job, model, elements)
            return job
        except cam.ProjectError as exc:
            refused = refused or exc
    handlers._error(str(refused))
    return None


def make():
    """CAM > Slot: the slots clicked in the model (a wall, a round end, the
    floor or an edge of each; Shift+click adds), in the active setup."""
    from avangardecam import handlers

    doc = FreeCAD.ActiveDocument
    if handlers._models_or_say(doc) is None:
        return
    elements = handlers._model_elements()  # an element of a job's clone is the same of the original
    if len({model.Name for model, _name in elements}) > 1:
        handlers._status(tr("Click the slots of one model only."))
        return
    if not elements:
        handlers._status(tr("Click a wall, a round end or the floor of a slot in the model (Shift+click adds the next slot), then click Slot."))  # fmt: skip
        return
    model = elements[0][0]
    names = [name for _model, name in elements]
    job = _setup(doc, model, names)
    if job is None:
        return
    dialog = SlotDialog(job, model, names, handlers._library())
    make_op = lambda tc: engine_slot.add_slot_milling(job, dialog.milling(), tc, model, names)  # noqa: E731
    if handlers._add_operation(doc, job, dialog, make_op, tr("Slot milling")):
        # FreeCAD leaves the whole model selected (all red)
        FreeCADGui.Selection.clearSelection()


def edit_dialog(op, job, tool, library):
    """(window, its values) to edit a slot milling (handlers.edit_operation)."""
    model, milling = engine_slot.slot_milling_of(op)
    dialog = SlotDialog(job, model, engine_slot.slot_elements(op), library, start=milling, tool=tool)
    return dialog, dialog.milling


class SlotView(details.DetailsView):
    """Slot milling: typed values are applied after a pause, chosen ones at
    once; each change is one undo step."""

    APPLY_DELAY_MS = 600

    def __init__(self, op, parent=None):
        from avangardecam import handlers

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.op = op
        self.job = cam.setup_of(op)
        _model, milling = engine_slot.slot_milling_of(op)
        self.add_row(tr("Setup"), self.job.Label if self.job else details.NONE)
        self.slots_label = self.add_row(tr("Slots"), "")
        self.slots_label.setWordWrap(True)
        self.tool_label = self.add_row(tr("Tool"), "")
        self.tool_label.setWordWrap(True)
        self.feeds_label = self.add_row(tr("Feeds"), "")
        self.fields = SlotFields(self.form, milling, self._model_depth(), self)
        self.fields.typed.connect(self._schedule_apply)
        self.levels_label = self.add_row(tr("Z levels"), "")
        self.levels_label.setWordWrap(True)
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("Ramps along the slot and rough passes on the Z levels shown, then the walls finished with the radius compensation. In 3D the ramps and rough passes are where the tool centre runs, the finishing pass where its edge cuts.")  # fmt: skip
        )
        self.add_button(tr("Change tool..."), lambda: handlers.change_tool(self.op), "AvangardeCamChangeTool")
        self.add_button(tr("Remove operation"), self._remove, "AvangardeCamRemoveOperation")
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply)
        self.update_view()

    def _found(self):
        try:
            return engine_slot.slots(self.op)
        except cam.ProjectError:  # the model changed
            return []

    def _model_depth(self):
        return _model_depth(self._found())

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
        if wanted == engine_slot.slot_milling_of(self.op)[1]:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Slot milling"))
        try:
            engine_slot.set_slot_milling(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            details._show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        model, milling = engine_slot.slot_milling_of(self.op)
        try:
            found = engine_slot.slots(self.op)
            self.slots_label.setText(slots_text(model, found))
        except cam.ProjectError as exc:  # the model changed
            found = []
            self.slots_label.setText(str(exc))
        if found:
            floor = engine_slot.floor_of(milling, found[0])
            self.levels_label.setText(levels_text(milling.levels(found[0].top, floor)))
        else:
            self.levels_label.setText(details.NONE)
        tc = self.op.ToolController
        tool = next((t.tool for t in cam.project_tools(self.job) if t.controller is tc), None)
        self.tool_label.setText(details.tool_row_text(self.op, self.job))
        self.feeds_label.setText(feeds_text(tool))
        self.fields.show_step_over(tool)
        moves, lowest = cam.path_summary(self.op)
        if moves and lowest is not None:
            self.path_label.setText(tr("{} moves, down to Z {:.2f} mm").format(moves, round(lowest, 2) + 0.0))
        else:
            self.path_label.setText(details._no_path(self.op))
        if not self._timer.isActive():
            self.fields.show(milling, _model_depth(found))
            if found:
                self.fields.show_lead(milling, tool, found[0].slot.width_mm)

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()
