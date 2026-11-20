# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Facing: CAM > Facing on a flat face clicked at the top of the model
(Shift+click adds one at the same height), its window, its details and
Edit... (model.facing, engine.facing). For now (the user's choice) only
the top: the tool levels the whole stock down to it.

The window: the face, the tool (ui.tool_choice; the one used last for a
facing, else the setup's first face mill or end mill), Start Z (the top
of the stock unless the user enters one), Z step, step over, the pattern
(zigzag with rounded turns or one way), the direction of the first
pass and the side of the stock it starts on (across the passes: Y- or Y+
for passes along X; at first the one where it climbs); the overrun under Advanced. The offset from walls (model) has no
field while there are no walls. Under them the
Z levels and the passes as they are typed. The window starts with the
values used last, but Start Z. Beside the fields a picture
(ui.field_pictures): the face mill halfway over the top.
"""

import dataclasses

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tr
from avangardecam.engine import facing as engine_facing
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import facing as model_facing
from avangardecam.model import operations as model_operations
from avangardecam.ui import details, field_pictures, manual, window_fit
from avangardecam.ui.tool_choice import ToolChooser, library_id

_LAST_FACING = "LastFacing"  # the values but Start Z, as JSON
LAST_TOOL = "LastFacingTool"  # library id
_SHOWN_LEVELS = 8

_PATTERNS = (
    (model_facing.ZIGZAG, QT_TRANSLATE_NOOP("AvangardeCam", "Zigzag, rounded turns")),
    (model_facing.ONE_WAY, QT_TRANSLATE_NOOP("AvangardeCam", "One way")),
)
_DIRECTIONS = (
    (model_facing.X_PLUS, QT_TRANSLATE_NOOP("AvangardeCam", "X- → X+ (along X)")),
    (model_facing.X_MINUS, QT_TRANSLATE_NOOP("AvangardeCam", "X+ → X- (along X)")),
    (model_facing.Y_PLUS, QT_TRANSLATE_NOOP("AvangardeCam", "Y- → Y+ (along Y)")),
    (model_facing.Y_MINUS, QT_TRANSLATE_NOOP("AvangardeCam", "Y+ → Y- (along Y)")),
)
_SIDES = (model_facing.FROM_MINUS, model_facing.FROM_PLUS)
# (field, label, object name, tip) of the length fields
_LENGTHS = (
    ("z_step_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Z step"), "ZStep", QT_TRANSLATE_NOOP("AvangardeCam", "Full steps down from Start Z, the rest at the face; 0: the whole depth at once")),  # fmt: skip
    ("overrun_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Overrun"), "Overrun", QT_TRANSLATE_NOOP("AvangardeCam", "Over open edges, also on the last pass, the tool's edge goes this far past the stock")),  # fmt: skip
)
_LABELS = {field: label for field, label, _name, _tip in _LENGTHS}
_LABELS["start_z_mm"] = QT_TRANSLATE_NOOP("AvangardeCam", "Start Z")


def is_facing_tool(tool):
    return tool is not None and tool.shape in engine_facing.FACING_SHAPES


def last_facing():
    """A facing with the values used last (Start Z: the top of the stock), else the defaults."""
    text = params().GetString(_LAST_FACING, "")
    try:
        last = model_operations.from_json(text) if text else None
    except (ValueError, TypeError):
        last = None
    if not isinstance(last, model_facing.Facing):
        last = model_facing.Facing()
    return dataclasses.replace(last, start_z_mm=None)


def feeds_text(tool):
    """The feeds a facing takes from a model Tool."""
    if tool is None or not (tool.feed_xy_mm_min and tool.feed_z_mm_min):
        return details.NONE
    return tr("Z {:g}, XY {:g} mm/min").format(tool.feed_z_mm_min, tool.feed_xy_mm_min)


def face_text(model, faces, face_z):
    """"Face12 of Body: Z -2.00" or "2 faces of Body: Z -2.00"."""
    count = faces[0] if len(faces) == 1 else tr("{} faces").format(len(faces))
    return tr("{} of {}: Z {}").format(count, model.Label, "{:+.2f}".format(round(face_z, 2) + 0.0))


def levels_text(levels):
    """"Z +0.00, -1.00, -1.50 (3 levels)", the first ones of many."""
    if not levels:
        return details.NONE
    shown = ", ".join("{:+.2f}".format(round(z, 2) + 0.0) for z in levels[:_SHOWN_LEVELS])
    if len(levels) > _SHOWN_LEVELS:
        shown += ", …"
    count = tr("1 level") if len(levels) == 1 else tr("{} levels").format(len(levels))
    return "Z {} ({})".format(shown, count)


def passes_text(rows, walls):
    """"5 passes, 1 along the walls, on each level"."""
    text = tr("1 pass") if rows == 1 else tr("{} passes").format(rows)
    if walls:
        text += ", " + (tr("1 along the walls") if walls == 1 else tr("{} along the walls").format(walls))
    return text + ", " + tr("on each level")


def entries_text(plan):
    """A warning when the tool comes down into material (a face mill cannot plunge), else ""."""
    closed = plan.closed_entries()
    if not closed:
        return ""
    if closed == 1:
        return tr("The tool comes down into the material once on each level (no open edge to come in from): check it can plunge.")  # fmt: skip
    return tr("The tool comes down into the material {} times on each level (no open edge to come in from): check it can plunge.").format(closed)  # fmt: skip


def fit_text(facing, tool, levels, top, face_z):
    """What is wrong between the tool (model Tool), the values and the Z
    levels, else ""."""
    if tool is None:
        return ""
    if not is_facing_tool(tool):
        return tr("{} is not a face mill or an end mill; facing needs a flat end.").format(tool.name)
    try:
        facing.check(tool.diameter_mm)
    except ValueError as exc:
        return str(exc)
    if not levels:
        return tr("Start Z (Z{:+g}) must be above the face (Z{:+g}).").format(round(top, 3), round(face_z, 3))
    deepest = max(a - b for a, b in zip([top] + levels, levels))
    if tool.cutting_length_mm and deepest > tool.cutting_length_mm + 1e-6:
        return tr("A level cuts {:g} mm deep, more than the cutting length of {} ({:g} mm). Enter a Z step.").format(
            round(deepest, 3), tool.name, tool.cutting_length_mm
        )
    return ""


class FacingFields(QtCore.QObject):
    """The values of a facing as rows of a form; the overrun under
    Advanced. typed: a value was typed or chosen."""

    typed = QtCore.Signal()

    def __init__(self, form, facing, stock_top, parent=None):
        super().__init__(parent)
        self.boxes = {}
        limit = model_operations.MAX_DEPTH_MM
        self.stock_top = stock_top

        def emit(*_args):
            self.typed.emit()

        def length(field, name, tip, value):
            # any length: a wrong one is refused by the model, not clamped
            box = details.length_box(value, -limit, limit)
            box.setObjectName("AvangardeCamFacing" + name)
            box.setToolTip(tr(tip))
            box.valueChanged.connect(emit)
            self.boxes[field] = box
            return box

        self.from_stock = QtWidgets.QCheckBox(tr("Top of the stock"))
        self.from_stock.setObjectName("AvangardeCamFacingFromStock")
        self.from_stock.setToolTip(tr("Start Z follows the top of the stock"))
        start = length(
            "start_z_mm",
            "StartZ",
            QT_TRANSLATE_NOOP("AvangardeCam", "Where the material starts, in the setup's coordinates (the Z of the program)"),  # fmt: skip
            stock_top if facing.start_z_mm is None else facing.start_z_mm,
        )
        row = QtWidgets.QHBoxLayout()
        row.addWidget(start, 1)
        row.addWidget(self.from_stock)
        form.addRow(tr("Start Z") + ":", row)
        self.from_stock.setChecked(facing.start_z_mm is None)
        start.setEnabled(facing.start_z_mm is not None)
        self.from_stock.toggled.connect(self._from_stock)
        field, label, name, tip = _LENGTHS[0]
        form.addRow(tr(label) + ":", length(field, name, tip, facing.z_step_mm or 0.0))

        self.step_over = QtWidgets.QDoubleSpinBox()
        self.step_over.setObjectName("AvangardeCamFacingStepOver")
        self.step_over.setRange(1.0, 100.0)
        self.step_over.setDecimals(1)
        self.step_over.setSuffix(" %")
        self.step_over.setValue(facing.step_over_percent)
        self.step_over.setToolTip(tr("The most of the tool's diameter between passes; the passes are spread evenly"))
        self.step_over.valueChanged.connect(emit)
        self.step_over_mm = QtWidgets.QLabel()
        self.step_over_mm.setObjectName("AvangardeCamFacingStepOverMm")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.step_over, 1)
        row.addWidget(self.step_over_mm)
        form.addRow(tr("Step over") + ":", row)

        self.pattern = self._combo("Pattern", _PATTERNS, facing.pattern)
        self.pattern.setToolTip(tr("Zigzag: back and forth, the passes joined by half circles; one way: up, back, down"))
        form.addRow(tr("Pattern") + ":", self.pattern)
        self.direction = self._combo("Direction", _DIRECTIONS, facing.direction, self._direction_changed)
        self.direction.setToolTip(tr("The way the first pass goes, so the passes run along X or along Y; the first pass climbs"))  # fmt: skip
        form.addRow(tr("First pass") + ":", self.direction)
        self.start_side = QtWidgets.QComboBox()
        self.start_side.setObjectName("AvangardeCamFacingStartSide")
        self.start_side.setToolTip(tr("The side of the stock across the passes the tool starts on and steps over from"))
        self._show_sides(facing.direction, facing.start_side)
        self.start_side.currentIndexChanged.connect(emit)
        form.addRow(tr("Start from") + ":", self.start_side)
        self.offset_xy_mm = facing.offset_xy_mm  # no field: no walls at the top

        self.more = QtWidgets.QToolButton()
        self.more.setObjectName("AvangardeCamFacingAdvanced")
        self.more.setText(tr("Advanced"))
        self.more.setCheckable(True)
        self.more.setArrowType(QtCore.Qt.RightArrow)
        self.more.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.more.setAutoRaise(True)
        form.addRow(self.more)
        self.advanced = QtWidgets.QWidget()
        advanced = QtWidgets.QFormLayout(self.advanced)
        advanced.setContentsMargins(12, 0, 0, 0)
        field, label, name, tip = _LENGTHS[1]
        advanced.addRow(tr(label) + ":", length(field, name, tip, facing.overrun_mm))
        form.addRow(self.advanced)
        self.advanced.setVisible(False)
        self.more.toggled.connect(self._show_advanced)

    def _combo(self, name, items, value, changed=None):
        combo = QtWidgets.QComboBox()
        combo.setObjectName("AvangardeCamFacing" + name)
        for key, text in items:
            combo.addItem(tr(text), key)
        combo.setCurrentIndex(max(0, combo.findData(value)))
        combo.currentIndexChanged.connect(changed or (lambda *_args: self.typed.emit()))
        return combo

    def _show_sides(self, direction, start_side):
        """The start sides across the passes of that direction, start_side
        (None: where the first pass climbs) chosen."""
        axis = "Y" if direction in (model_facing.X_PLUS, model_facing.X_MINUS) else "X"
        chosen = start_side or model_facing.climbing_side(direction)
        self.start_side.blockSignals(True)
        self.start_side.clear()
        for side in _SIDES:
            self.start_side.addItem(axis + side, side)
        self.start_side.setCurrentIndex(self.start_side.findData(chosen))
        self.start_side.blockSignals(False)

    def _direction_changed(self, *_args):
        # another direction starts where its first pass climbs
        self._show_sides(self.direction.currentData(), None)
        self.typed.emit()

    def _from_stock(self, checked):
        box = self.boxes["start_z_mm"]
        box.setEnabled(not checked)
        if checked:
            box.blockSignals(True)
            box.setProperty("rawValue", self.stock_top)
            box.blockSignals(False)
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

    def unreadable(self):
        """Label of the first field that does not hold a length, else ""."""
        for field, box in self.boxes.items():
            if box.isEnabled() and not box.hasAcceptableInput():
                return tr(_LABELS[field])
        return ""

    def facing(self):
        values = {field: float(box.property("rawValue")) for field, box in self.boxes.items()}
        values["z_step_mm"] = values["z_step_mm"] or None  # 0: the whole depth at once
        if self.from_stock.isChecked():
            values["start_z_mm"] = None
        return model_facing.Facing(
            offset_xy_mm=self.offset_xy_mm,
            step_over_percent=self.step_over.value(),
            pattern=self.pattern.currentData(),
            direction=self.direction.currentData(),
            start_side=self._start_side(),
            **values,
        )

    def _start_side(self):
        side = self.start_side.currentData()
        return None if side == model_facing.climbing_side(self.direction.currentData()) else side

    def busy(self):
        """True while the user is in a field."""
        return any(w.hasFocus() for w in list(self.boxes.values()) + [self.step_over])

    def show(self, facing, stock_top):
        """Show a facing's values, but not in the field being typed in."""
        self.stock_top = stock_top
        self.offset_xy_mm = facing.offset_xy_mm
        shown = dataclasses.asdict(facing)
        shown["start_z_mm"] = stock_top if facing.start_z_mm is None else facing.start_z_mm
        shown["z_step_mm"] = facing.z_step_mm or 0.0
        for field, box in self.boxes.items():
            if not box.hasFocus():
                box.blockSignals(True)
                box.setProperty("rawValue", shown[field])
                box.blockSignals(False)
        widgets = (
            (self.from_stock, lambda w: w.setChecked(facing.start_z_mm is None)),
            (self.step_over, lambda w: w.setValue(facing.step_over_percent) if not w.hasFocus() else None),
            (self.pattern, lambda w: w.setCurrentIndex(w.findData(facing.pattern))),
            (self.direction, lambda w: w.setCurrentIndex(w.findData(facing.direction))),
        )
        for widget, set_value in widgets:
            widget.blockSignals(True)
            set_value(widget)
            widget.blockSignals(False)
        self._show_sides(facing.direction, facing.start_side)
        self.boxes["start_z_mm"].setEnabled(facing.start_z_mm is not None)


class FacingDialog(QtWidgets.QDialog):
    """job: the setup; model and faces: the flat faces picked in it
    (names, "Face12", at one height); library: the tool library's
    variants (LibraryTool). To edit a facing: start, its model Facing, and
    tool, its ProjectTool; the values used last are then neither shown
    nor remembered."""

    def __init__(self, job, model, faces, library=(), parent=None, start=None, tool=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamFacingDialog")
        self.setWindowTitle(tr("Facing"))
        self.job = job
        self.editing = start is not None
        self.base, self.face_z = engine_facing.picked_face(job, model, list(faces))
        self.stock_top = cam.stock_bounds(job).z_max

        box = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(tr("Facing: the top of the model level, over the whole stock"))
        heading.setStyleSheet("font-weight: bold;")
        box.addWidget(heading)
        top = QtWidgets.QHBoxLayout()
        box.addLayout(top)
        form = QtWidgets.QFormLayout()
        top.addLayout(form, 1)
        self.pictures = field_pictures.FieldPictures("facing_start.svg")
        top.addWidget(self.pictures, 0, QtCore.Qt.AlignTop)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        face = QtWidgets.QLabel(face_text(model, list(faces), self.face_z))
        face.setObjectName("AvangardeCamFacingFace")
        face.setWordWrap(True)
        form.addRow(tr("Face") + ":", face)
        self.chooser = ToolChooser(job, "AvangardeCamFacing")
        form.addRow(tr("Tool") + ":", self.chooser)
        self.fit = QtWidgets.QLabel()
        self.fit.setObjectName("AvangardeCamFacingFit")
        self.fit.setWordWrap(True)
        self.fit.setStyleSheet("color: #b9770e;")
        form.addRow(self.fit)
        self.feeds = QtWidgets.QLabel()
        self.feeds.setObjectName("AvangardeCamFacingFeeds")
        form.addRow(tr("Feeds") + ":", self.feeds)
        self.chooser.follow(self.feeds, feeds_text)  # the operation's own spindle speed and feeds
        self.fields = FacingFields(form, start if start is not None else last_facing(), self.stock_top, self)
        self.levels = QtWidgets.QLabel()
        self.levels.setObjectName("AvangardeCamFacingLevels")
        self.levels.setWordWrap(True)
        form.addRow(tr("Z levels") + ":", self.levels)
        self.passes = QtWidgets.QLabel()
        self.passes.setObjectName("AvangardeCamFacingPasses")
        self.passes.setWordWrap(True)
        form.addRow(tr("Passes") + ":", self.passes)
        self.entries = QtWidgets.QLabel()
        self.entries.setObjectName("AvangardeCamFacingEntries")
        self.entries.setWordWrap(True)
        self.entries.setStyleSheet("color: #b9770e;")
        form.addRow(self.entries)

        manual_text = tr("The face mill levels the whole stock down to the top face of the model, out past the stock by the overrun. Z steps from Start Z down to the face. Only a face at the very top: nothing of the model above it.")  # fmt: skip
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamFacingMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Facing"), manual_text)
        box.addWidget(buttons)

        for signal in (self.chooser.changed, self.fields.typed):
            signal.connect(self._update)
            signal.connect(lambda: self.message.setText(""))
        if tool is not None:
            self.chooser.choose(tool)
        else:
            self.chooser.start_with(library, params().GetString(LAST_TOOL, ""), is_facing_tool)
        self._update()
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self.fields.step_over.setFocus()

    def use(self, entry):
        self.chooser.use(entry)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        return self.chooser.tool()

    def facing(self):
        return self.fields.facing()

    def _check(self, facing, tool):
        """(levels, what is wrong or "")."""
        top = facing.top_mm(self.stock_top)
        levels = facing.levels(top, self.face_z)
        return levels, fit_text(facing, tool, levels, top, self.face_z)

    def _update(self, *_args):
        choice = self.tool()
        tool = choice.tool if choice is not None else None
        self.feeds.setText(feeds_text(self.chooser.cutting_tool()))
        self.fields.show_step_over(tool)
        try:
            facing = self.facing().validate() if not self.fields.unreadable() else None
        except ValueError:
            facing = None
        self.passes.setText(details.NONE)
        self.entries.setText("")
        if facing is None:
            self.fit.setText("")
            self.levels.setText(details.NONE)
        else:
            levels, wrong = self._check(facing, tool)
            self.levels.setText(levels_text(levels))
            if not wrong and tool is not None and tool.diameter_mm:
                try:
                    plan, rows, walls = engine_facing.plan_for(self.job, facing, self.base, tool.diameter_mm, len(levels))
                    self.passes.setText(passes_text(rows, walls))
                    self.entries.setText(entries_text(plan))
                except cam.ProjectError as exc:
                    wrong = str(exc)
            self.fit.setText(wrong)
        self.fit.setVisible(bool(self.fit.text()))
        self.entries.setVisible(bool(self.entries.text()))

    def accept(self):
        if self.tool() is None:
            self.message.setText(tr("Choose a tool: one of the setup's or with Choose tool... from the tool library."))
            return
        unreadable = self.fields.unreadable()
        if unreadable:
            self.message.setText(tr("{}: enter a length, for example 2 mm.").format(unreadable))
            return
        try:
            facing = self.facing().validate()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        tool = self.tool().tool
        wrong = self._check(facing, tool)[1]
        if not wrong:
            try:
                engine_facing.plan_for(self.job, facing, self.base, tool.diameter_mm)
            except cam.ProjectError as exc:
                wrong = str(exc)
        if wrong:
            self.message.setText(wrong)
            return
        if self.editing:
            return super().accept()
        params().SetString(_LAST_FACING, model_operations.to_json(facing))
        if library_id(self.tool()):
            params().SetString(LAST_TOOL, library_id(self.tool()))
        super().accept()


def _setup(doc, model, faces):
    """The setup of a facing: the active one (the first, made now, when
    there is none) when the faces face its tool, else the first setup whose
    tool they face; else None after saying why."""
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
            engine_facing.picked_face(job, model, faces)
            return job
        except cam.ProjectError as exc:
            refused = refused or exc
    handlers._error(str(refused))
    return None


def make():
    """CAM > Facing: the flat face clicked at the top of the model
    (Shift+click adds one at the same height), in the active setup."""
    from avangardecam import handlers

    doc = FreeCAD.ActiveDocument
    if handlers._models_or_say(doc) is None:
        return
    elements = handlers._model_elements()  # a face of a job's clone is the same face of the original
    faces = [name for _model, name in elements if name.startswith("Face")]
    if len({model.Name for model, _name in elements}) > 1:
        handlers._status(tr("Click the faces of one model only."))
        return
    if not faces:
        handlers._status(tr("Click the flat face at the top of the model (Shift+click adds one at the same height), then click Facing."))  # fmt: skip
        return
    model = elements[0][0]
    job = _setup(doc, model, faces)
    if job is None:
        return
    dialog = FacingDialog(job, model, faces, handlers._library())
    make_op = lambda tc: engine_facing.add_facing(job, dialog.facing(), tc, model, faces)  # noqa: E731
    if handlers._add_operation(doc, job, dialog, make_op, tr("Facing")):
        # FreeCAD leaves the whole model selected (all red)
        FreeCADGui.Selection.clearSelection()


def edit_dialog(op, job, tool, library):
    """(window, its values) to edit a facing (handlers.edit_operation)."""
    model, facing = engine_facing.facing_of(op)
    dialog = FacingDialog(job, model, engine_facing.facing_faces(op), library, start=facing, tool=tool)
    return dialog, dialog.facing


class FacingView(details.DetailsView):
    """Facing: typed values are applied after a pause, chosen ones at once;
    each change is one undo step."""

    APPLY_DELAY_MS = 600

    def __init__(self, op, parent=None):
        from avangardecam import handlers

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.op = op
        self.job = cam.setup_of(op)
        _model, facing = engine_facing.facing_of(op)
        self.add_row(tr("Setup"), self.job.Label if self.job else details.NONE)
        self.face_label = self.add_row(tr("Face"), "")
        self.face_label.setWordWrap(True)
        self.tool_label = self.add_row(tr("Tool"), "")
        self.tool_label.setWordWrap(True)
        self.feeds_label = self.add_row(tr("Feeds"), "")
        self.fields = FacingFields(self.form, facing, self._stock_top(), self)
        self.fields.typed.connect(self._schedule_apply)
        self.levels_label = self.add_row(tr("Z levels"), "")
        self.levels_label.setWordWrap(True)
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("The whole stock levelled down to the top face of the model, from Start Z on the Z levels shown, out past the stock by the overrun. The path in 3D is where the tool centre runs.")  # fmt: skip
        )
        self.add_button(tr("Change tool..."), lambda: handlers.change_tool(self.op), "AvangardeCamChangeTool")
        self.add_button(tr("Remove operation"), self._remove, "AvangardeCamRemoveOperation")
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply)
        self.update_view()

    def _stock_top(self):
        return cam.stock_bounds(self.job).z_max if self.job is not None and self.job.Stock is not None else 0.0

    def _schedule_apply(self, *_args):
        self._timer.start(self.APPLY_DELAY_MS)

    def apply(self, *_args):
        self._timer.stop()
        if self.fields.unreadable():
            return  # still being typed
        try:
            wanted = self.fields.facing().validate()
        except ValueError as exc:
            details._show_error(str(exc))
            return
        if wanted == engine_facing.facing_of(self.op)[1]:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Facing"))
        try:
            engine_facing.set_facing(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            details._show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        model, facing = engine_facing.facing_of(self.op)
        top = self._stock_top()
        try:
            face_z = engine_facing.picked_face(self.job, model, engine_facing.facing_faces(self.op))[1]
            self.face_label.setText(face_text(model, engine_facing.facing_faces(self.op), face_z))
            self.levels_label.setText(levels_text(facing.levels(facing.top_mm(top), face_z)))
        except cam.ProjectError as exc:  # the model changed
            self.face_label.setText(str(exc))
            self.levels_label.setText(details.NONE)
        tc = self.op.ToolController
        tool = next((t.tool for t in cam.project_tools(self.job) if t.controller is tc), None)
        self.tool_label.setText(details.tool_row_text(self.op, self.job))
        self.feeds_label.setText(feeds_text(details.cutting_tool(self.op)))
        self.fields.show_step_over(tool)
        moves, lowest = cam.path_summary(self.op)
        if moves and lowest is not None:
            self.path_label.setText(tr("{} moves, down to Z {:.2f} mm").format(moves, round(lowest, 2) + 0.0))
        else:
            self.path_label.setText(details._no_path(self.op))
        if not self._timer.isActive():
            self.fields.show(facing, top)

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()
