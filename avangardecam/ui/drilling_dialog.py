# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Drilling window: the tool and the values of the TNC's universal pecking
cycle (CYCL DEF 205) for picked circles of a sketch or holes of a model.

The main values are on top (depth to the tip or the full diameter, peck,
chip breaking, dwell), the cycle's others under Advanced. The same fields
(DrillingFields) are in the details of a drilling. Labels name the cycle's
Q parameters, as the operators know them from the control.

Holes of a model are by default as deep as the model has them (From the
model); the user may enter one depth for all of them instead.

The tool (ui.tool_choice): a drill of the holes' diameter (the setup's,
else the tool library's in the material of the drill used last or of the
setup's tools), else the one used last for a drilling, else the setup's
first drill. The list and Choose tool... show only drills (Drills only,
which can be switched off). The window starts with the values used last.
"""

import collections
import dataclasses

import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tr
from avangardecam.engine import geometry
from avangardecam.model import operations as model_operations
from avangardecam.model import tools as model_tools
from avangardecam.ui import details, manual, window_fit
from avangardecam.ui.tool_choice import ToolChooser, library_id

DEFAULT_DEPTH_MM = -10.0
_LAST_DRILLING = "LastDrilling"  # the values, as JSON
LAST_TOOL = "LastDrillingTool"  # library id
# the tool lists show only these, unless switched off
DRILLS_ONLY = (QT_TRANSLATE_NOOP("AvangardeCam", "Drills only"), lambda tool: tool.shape == "Drill")

_DEPTH_REFERENCES = (
    (model_operations.TIP, QT_TRANSLATE_NOOP("AvangardeCam", "Tip")),
    (model_operations.FULL_DIAMETER, QT_TRANSLATE_NOOP("AvangardeCam", "Full diameter")),
)

# (field, label, object name) of the length fields; on top, then under Advanced
_MAIN = (
    ("depth_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Depth (Q201)"), "Depth"),
    ("peck_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Peck depth (Q202)"), "Peck"),
    ("chip_break_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Chip break depth (Q257)"), "ChipBreak"),
    ("chip_retract_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Chip break retract (Q256)"), "ChipRetract"),
)
_ADVANCED = (
    ("decrement_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Decrement (Q212)"), "Decrement"),
    ("min_peck_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Min. peck depth (Q205)"), "MinPeck"),
    ("upper_stop_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Upper stop distance (Q258)"), "UpperStop"),
    ("lower_stop_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Lower stop distance (Q259)"), "LowerStop"),
    ("start_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Deepened start (Q379)"), "Start"),
    ("clearance_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Set-up clearance (Q200)"), "Clearance"),
    ("second_clearance_mm", QT_TRANSLATE_NOOP("AvangardeCam", "2nd clearance (Q204)"), "SecondClearance"),
)
# holes of a model only
_THROUGH = ("through_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Out under through holes"), "Through")
_LABELS = {field: text for field, text, _name in _MAIN + _ADVANCED + (_THROUGH,)}

# a drill fits a hole within this, mm
_SAME_DIAMETER_MM = 0.005


def last_drilling():
    """The values used last, else the defaults."""
    text = params().GetString(_LAST_DRILLING, "")
    try:
        drilling = model_operations.from_json(text) if text else None
    except (ValueError, TypeError):
        drilling = None
    if not isinstance(drilling, model_operations.Drilling):
        drilling = model_operations.Drilling(DEFAULT_DEPTH_MM)
    return drilling


def hole_text(diameter, hole=None):
    """"Ø4.5" of a sketch's circle; "Ø4.5 through", "Ø4 5 deep" of a
    model's hole (its HoleDepth)."""
    text = "Ø{:g}".format(round(diameter, 3))
    if hole is not None:
        text += " " + (tr("through") if hole.through else tr("{:g} deep").format(round(-hole.depth_mm, 3)))
    return text


def picked_text(holes):
    """"3: Ø4.5 through → Ø4 5 deep → Ø4.5" of holes (diameter, HoleDepth
    or None) in the tool's order."""
    shown = [hole_text(d, h) for d, h in holes]
    if len(shown) > 4:
        shown = shown[:2] + ["…", shown[-1]]
    return "{}: {}".format(len(holes), " → ".join(shown))


def holes_text(sketch, circles):
    """"2: Ø4.5 → Ø4.5" of picked circles in the tool's order, "all 3: Ø6,
    Ø4" for all the sketch's circles."""
    names = list(circles) or geometry.sketch_circles(sketch)
    diameters = [sketch.Shape.getElement(n).Curve.Radius * 2.0 for n in names]
    if circles:
        return picked_text([(d, None) for d in diameters])
    shown = sorted({round(d, 3) for d in diameters})
    return tr("all {}: {}").format(len(names), ", ".join("Ø{:g}".format(d) for d in shown))


def suggested_drill(tools, library, diameter, last_id=""):
    """A drill for holes of diameter: the setup's (ProjectTool) of that
    diameter, the one used last first; else a library variant (LibraryTool)
    of it in the material of the drill used last (last_id) or of the
    setup's tools, or the only one there is. None when there is none or
    the material is not clear: variants differ in speeds and feeds."""

    def fits(choice):
        return choice.tool.shape == "Drill" and abs(choice.tool.diameter_mm - diameter) < _SAME_DIAMETER_MM

    mine = [t for t in tools if fits(t)]
    if mine:
        return next((t for t in mine if t.library_id == last_id), mine[0])
    found = [e for e in library if fits(e)]
    if len(found) <= 1:
        return found[0] if found else None
    last = next((e for e in library if e.id == last_id), None) if last_id else None
    materials = ([last.workpiece_material] if last is not None else []) + [t.workpiece_material for t in tools]
    for material in materials:
        match = [e for e in found if e.workpiece_material == material]
        if match:
            return match[0]
    return None


def main_diameter(holes):
    """The diameter most of the holes (diameter, ...) have, None without holes."""
    count = collections.Counter(round(d, 3) for d, _h in holes)
    return count.most_common(1)[0][0] if count else None


def fit_text(holes, tool):
    """What does not fit between the holes and a drill (model Tool), else ""."""
    if tool is None or not holes:
        return ""
    wrong = sorted({round(d, 3) for d, _h in holes if abs(d - tool.diameter_mm) >= _SAME_DIAMETER_MM})
    if not wrong:
        return ""
    return tr("The drill is Ø{:g}; holes of {} are not its size.").format(
        tool.diameter_mm, ", ".join("Ø{:g}".format(d) for d in wrong)
    )


FEEDS_TIP = QT_TRANSLATE_NOOP(
    "AvangardeCam", "Q206: down into the hole, the tool's feed. Q253: pre-positioning, the tool's plunge feed."
)


def feeds_text(tool):
    """The feeds the cycle takes from a model Tool (FEEDS_TIP)."""
    if tool is None or not (tool.feed_xy_mm_min and tool.feed_z_mm_min):
        return details.NONE
    return tr("Q206 {:g}, Q253 {:g} mm/min").format(tool.feed_xy_mm_min, tool.feed_z_mm_min)


def tip_text(drilling, tool, holes=()):
    """How deep the drill's tip goes, from the top of the holes; from the
    model: in the deepest of the holes (diameter, HoleDepth)."""
    tip = model_tools.tip_length_mm(tool) if tool is not None else 0.0
    if drilling.depth_mm is None:
        depths = [h for _d, h in holes if h is not None]
        if not depths:
            return details.NONE
        deepest = max(-drilling.final_depth_mm(tip, h) for h in depths)
        text = tr("{:.3f} mm deep in the deepest hole").format(deepest + 0.0)
    else:
        text = tr("{:.3f} mm deep").format(-drilling.final_depth_mm(tip) + 0.0)
    if drilling.depth_to == model_operations.FULL_DIAMETER or drilling.depth_mm is None:
        text += " " + tr("(point {:.3f} mm)").format(tip)
    return text


class DrillingFields(QtCore.QObject):
    """The values of a drilling as rows of a form: the main ones, then the
    cycle's others under Advanced. typed: a value was typed; chosen: the
    depth reference or From the model was chosen.

    model: the holes are a model's; they may be as deep as the model has
    them (From the model), and get the depth under through holes."""

    typed = QtCore.Signal()
    chosen = QtCore.Signal()

    def __init__(self, form, drilling, parent=None, model=False):
        super().__init__(parent)
        limit = model_operations.MAX_DEPTH_MM
        self.boxes = {}
        self.from_model = None

        def add(layout, field, label, name, beside=None):
            # any length: a wrong one is refused by the model, not clamped
            box = details.length_box(_shown(drilling, field), -limit, limit)
            box.setObjectName("AvangardeCamDrilling" + name)
            box.valueChanged.connect(lambda *_args: self.typed.emit())
            self.boxes[field] = box
            if beside is None:
                layout.addRow(tr(label) + ":", box)
            else:
                row = QtWidgets.QHBoxLayout()
                row.addWidget(box, 1)
                row.addWidget(beside)
                layout.addRow(tr(label) + ":", row)

        if model:
            self.from_model = QtWidgets.QCheckBox(tr("From the model"))
            self.from_model.setObjectName("AvangardeCamDrillingFromModel")
            self.from_model.setToolTip(
                tr("Each hole as deep as the model has it: the drill's full diameter to the end of the hole, and out under a through hole.")  # fmt: skip
            )
            self.from_model.setChecked(drilling.depth_mm is None)
            self.from_model.toggled.connect(self._from_model_toggled)
        add(form, *_MAIN[0], beside=self.from_model)
        self.depth_to = details.choice_box("AvangardeCamDrillingDepthTo", _DEPTH_REFERENCES, drilling.depth_to)
        self.depth_to.currentIndexChanged.connect(lambda *_args: self.chosen.emit())
        form.addRow(tr("Depth to") + ":", self.depth_to)
        if model:
            add(form, *_THROUGH)
            self.boxes["through_mm"].setToolTip(tr("The drill's full diameter comes out under a through hole this far."))
        for row in _MAIN[1:]:
            add(form, *row)
        self.boxes["peck_mm"].setToolTip(tr("0: the whole depth at once"))
        self.boxes["chip_break_mm"].setToolTip(tr("0: no chip breaking"))
        self.dwell = QtWidgets.QDoubleSpinBox()
        self.dwell.setObjectName("AvangardeCamDrillingDwell")
        self.dwell.setRange(0.0, 3600.0)
        self.dwell.setDecimals(2)
        self.dwell.setSingleStep(0.1)
        self.dwell.setSuffix(" s")
        self.dwell.setValue(drilling.dwell_s)
        self.dwell.valueChanged.connect(lambda *_args: self.typed.emit())
        form.addRow(tr("Dwell at bottom (Q211)") + ":", self.dwell)

        self.more = QtWidgets.QToolButton()
        self.more.setObjectName("AvangardeCamDrillingAdvanced")
        self.more.setText(tr("Advanced"))
        self.more.setCheckable(True)
        self.more.setArrowType(QtCore.Qt.RightArrow)
        self.more.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.more.setAutoRaise(True)
        form.addRow(self.more)
        self.advanced = QtWidgets.QWidget()
        advanced = QtWidgets.QFormLayout(self.advanced)
        advanced.setContentsMargins(12, 0, 0, 0)
        for row in _ADVANCED:
            add(advanced, *row)
        form.addRow(self.advanced)
        self.advanced.setVisible(False)
        self.more.toggled.connect(self._show_advanced)
        self._depth_to_chosen = drilling.depth_to
        self._show_from_model()

    def _from_model_toggled(self, checked):
        if checked:
            self._depth_to_chosen = self.depth_to.currentData()
        self._show_from_model()
        self.chosen.emit()

    def _show_from_model(self):
        """From the model: the depth comes from the holes, to the full diameter."""
        checked = self.from_model is not None and self.from_model.isChecked()
        self.boxes["depth_mm"].setEnabled(not checked)
        self.depth_to.setEnabled(not checked)
        details.set_choice(self.depth_to, model_operations.FULL_DIAMETER if checked else self._depth_to_chosen)
        if "through_mm" in self.boxes:
            self.boxes["through_mm"].setEnabled(checked)

    def _from_the_model(self):
        return self.from_model is not None and self.from_model.isChecked()

    def _show_advanced(self, shown):
        self.advanced.setVisible(shown)
        self.more.setArrowType(QtCore.Qt.DownArrow if shown else QtCore.Qt.RightArrow)

    def unreadable(self):
        """Label of the first field that does not hold a length, else ""."""
        for field, box in self.boxes.items():
            if not box.isEnabled():
                continue
            if not box.hasAcceptableInput():
                return tr(_LABELS[field])
        return ""

    def drilling(self):
        values = {field: float(box.property("rawValue")) for field, box in self.boxes.items()}
        values["peck_mm"] = values["peck_mm"] or None  # 0: the whole depth at once
        depth_to = self.depth_to.currentData()
        if self._from_the_model():
            values["depth_mm"] = None
            depth_to = self._depth_to_chosen  # the user's choice for a depth of their own
        return model_operations.Drilling(depth_to=depth_to, dwell_s=self.dwell.value(), **values)

    def busy(self):
        """True while the user is in a field."""
        return any(box.hasFocus() for box in self.boxes.values()) or self.dwell.hasFocus()

    def show(self, drilling):
        """Show a drilling's values, but not in the field being typed in."""
        for field, box in self.boxes.items():
            if field == "depth_mm" and drilling.depth_mm is None:
                continue  # keeps the depth typed last
            if not box.hasFocus():
                box.blockSignals(True)
                box.setProperty("rawValue", _shown(drilling, field))
                box.blockSignals(False)
        if not self.dwell.hasFocus():
            self.dwell.blockSignals(True)
            self.dwell.setValue(drilling.dwell_s)
            self.dwell.blockSignals(False)
        self._depth_to_chosen = drilling.depth_to
        if self.from_model is not None:
            self.from_model.blockSignals(True)
            self.from_model.setChecked(drilling.depth_mm is None)
            self.from_model.blockSignals(False)
        self._show_from_model()


def _shown(drilling, field):
    """A drilling's value in its field (no depth: the default one)."""
    value = getattr(drilling, field)
    if value is None:
        return DEFAULT_DEPTH_MM if field == "depth_mm" else 0.0
    return value


class DrillingDialog(QtWidgets.QDialog):
    """source: the sketch or the model of the holes; text: the holes as the
    window shows them; holes: (diameter, HoleDepth) of each, HoleDepth None
    for a sketch's circles; ignored: how many other lines were selected
    (they are not drilled); library: the tool library's variants
    (LibraryTool), for a drill of the holes' size or the tool used last.
    To edit a drilling: start, its model Drilling, and tool, its
    ProjectTool; the values used last are then neither shown nor
    remembered."""

    def __init__(self, job, source, text, holes, library=(), ignored=0, parent=None, start=None, tool=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamDrillingDialog")
        self.setWindowTitle(tr("Drilling"))
        self.job = job
        self.editing = start is not None
        self.holes = list(holes)
        model = any(h is not None for _d, h in self.holes)

        box = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(tr("Deep drilling with chip breaking (cycle 205)"))
        heading.setStyleSheet("font-weight: bold;")
        box.addWidget(heading)
        form = QtWidgets.QFormLayout()
        box.addLayout(form)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        form.addRow((tr("Model") if model else tr("Sketch")) + ":", QtWidgets.QLabel(source.Label))
        if ignored:
            text += "  " + tr("({} other lines are not drilled)").format(ignored)
        holes_label = QtWidgets.QLabel(text)
        holes_label.setObjectName("AvangardeCamDrillingHoles")
        form.addRow(tr("Holes") + ":", holes_label)
        self.chooser = ToolChooser(job, "AvangardeCamDrilling", only=DRILLS_ONLY)
        form.addRow(tr("Tool") + ":", self.chooser)
        self.fit = QtWidgets.QLabel()
        self.fit.setObjectName("AvangardeCamDrillingFit")
        self.fit.setWordWrap(True)
        self.fit.setStyleSheet("color: #b9770e;")
        form.addRow(self.fit)
        self.feeds = QtWidgets.QLabel()
        self.feeds.setObjectName("AvangardeCamDrillingFeeds")
        self.feeds.setToolTip(tr(FEEDS_TIP))
        form.addRow(tr("Feeds") + ":", self.feeds)
        if start is None:
            start = last_drilling()
            if model:
                start = dataclasses.replace(start, depth_mm=None)  # the user's choice: as deep as the model has them
            elif start.depth_mm is None:
                start = dataclasses.replace(start, depth_mm=DEFAULT_DEPTH_MM)
        self.fields = DrillingFields(form, start, self, model=model)
        self.tip = QtWidgets.QLabel()
        self.tip.setObjectName("AvangardeCamDrillingTip")
        form.addRow(tr("The tip goes") + ":", self.tip)

        if model:
            text = tr("From the model, each hole is as deep as the model has it: the drill's full diameter reaches the end of the hole, and comes out under a through hole by the value above. Else the depth is negative, from the top of each hole: -10 mm drills 10 mm deep.")  # fmt: skip
        else:
            text = tr("The depth is negative, from the top of the holes (the sketch plane): -10 mm drills 10 mm deep.")
        manual_text = text + " " + tr("To the full diameter, the tip goes deeper by the drill's point. The drill comes out of the hole every peck depth (0: the whole depth at once) and backs off by the retraction every chip breaking depth (0: none). The holes are drilled in the order they were clicked; from hole to hole the drill goes at the 2nd set-up clearance.")  # fmt: skip
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamDrillingMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Drilling"), manual_text)
        box.addWidget(buttons)

        self.chooser.changed.connect(self._update)
        for signal in (self.chooser.changed, self.fields.typed, self.fields.chosen):
            signal.connect(self._update)
            signal.connect(lambda: self.message.setText(""))
        last_id = params().GetString(LAST_TOOL, "")
        diameter = main_diameter(self.holes)
        drill = suggested_drill(self.chooser.tools, library, diameter, last_id) if diameter else None
        if tool is not None:
            self.chooser.choose(tool)
        elif drill is not None:
            self.chooser.choose(drill)
        else:
            self.chooser.start_with(library, last_id, DRILLS_ONLY[1])
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        depth = self.fields.boxes["depth_mm"]
        if depth.isEnabled():
            depth.setFocus()
            depth.selectAll()

    def use(self, entry):
        self.chooser.use(entry)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        return self.chooser.tool()

    def drilling(self):
        return self.fields.drilling()

    def _update(self, *_args):
        choice = self.tool()
        tool = choice.tool if choice is not None else None
        self.feeds.setText(feeds_text(tool))
        self.fit.setText(fit_text(self.holes, tool))
        self.fit.setVisible(bool(self.fit.text()))
        if self.fields.unreadable():
            self.tip.setText(details.NONE)
        else:
            self.tip.setText(tip_text(self.drilling(), tool, self.holes))

    def accept(self):
        if self.tool() is None:
            self.message.setText(tr("Choose a tool: one of the setup's or with Choose tool... from the tool library."))
            return
        unreadable = self.fields.unreadable()
        if unreadable:
            self.message.setText(tr("{}: enter a length, for example 2 mm.").format(unreadable))
            return
        try:
            drilling = self.drilling().validate()
            tip = model_tools.tip_length_mm(self.tool().tool)
            for _diameter, hole in self.holes:
                drilling.check(tip, hole if drilling.depth_mm is None else None)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        if self.editing:
            return super().accept()
        params().SetString(_LAST_DRILLING, model_operations.to_json(drilling))
        if library_id(self.tool()):
            params().SetString(LAST_TOOL, library_id(self.tool()))
        super().accept()
