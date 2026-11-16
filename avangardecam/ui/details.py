# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Views of the details area under the project list, one per kind of entry.

A view shows one entry; when the project changes, the panel calls update()
on the current view instead of building a new one, so a field being edited
keeps its focus.
"""

import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.engine import op_zero
from avangardecam.model import frame as model_frame
from avangardecam.model import operations as model_operations
from avangardecam.model import stock as model_stock
from avangardecam.model import tools as model_tools
from avangardecam.ui import next_setup as ui_next_setup

NONE = "—"


def mm(value):
    if value is None:
        return NONE
    # adding 0.0 turns the -0.0 of a rounded tiny negative into 0.0
    return "{:.2f} mm".format(round(value, 2) + 0.0)


def size_text(bounds):
    x, y, z = bounds.size
    return "{:.2f} × {:.2f} × {:.2f} mm".format(x, y, z)


class DetailsView(QtWidgets.QWidget):
    """Title, a form of label/value rows and a note."""

    def __init__(self, title="", note="", parent=None):
        super().__init__(parent)
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        caption = QtWidgets.QLabel(tr("Details"))
        caption.setObjectName("AvangardeCamDetailsCaption")
        box.addWidget(caption)
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("AvangardeCamDetailsTitle")
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        self.form = QtWidgets.QFormLayout()
        self.form.setLabelAlignment(QtCore.Qt.AlignLeft)
        box.addLayout(self.form)
        self.note = QtWidgets.QLabel(note)
        self.note.setObjectName("AvangardeCamDetailsNote")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        self.buttons = QtWidgets.QVBoxLayout()
        box.addLayout(self.buttons)
        box.addStretch(1)

    def add_row(self, label, value):
        field = QtWidgets.QLabel(value)
        field.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.form.addRow(label + ":", field)
        return field

    def add_button(self, text, slot, name=""):
        button = QtWidgets.QPushButton(text)
        if name:
            button.setObjectName(name)
        button.clicked.connect(slot)
        self.buttons.addWidget(button)
        return button

    def rows(self):
        """(label, value) texts of the form, for tests and screen readers."""
        result = []
        for i in range(self.form.rowCount()):
            label_item = self.form.itemAt(i, QtWidgets.QFormLayout.LabelRole)
            if label_item is None:
                continue  # a row across the form (e.g. Advanced)
            label = label_item.widget().text()
            item = self.form.itemAt(i, QtWidgets.QFormLayout.FieldRole)
            field = item.widget()
            if field is None and item.layout() is not None:
                field = item.layout().itemAt(0).widget()  # a field with a check box beside it
            text = field.currentText() if isinstance(field, QtWidgets.QComboBox) else field.text()
            result.append((label.rstrip(":"), text))
        return result

    def update_view(self):
        """Refresh shown values after a project change."""


def _show_error(message):
    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", message)


class ModelView(DetailsView):
    def __init__(self, obj, parent=None):
        super().__init__(obj.Label, parent=parent)
        self.obj = obj
        bounds = cam.bounds(obj)
        x, y, z = bounds.size
        self.add_row(tr("Size X"), mm(x))
        self.add_row(tr("Size Y"), mm(y))
        self.add_row(tr("Size Z"), mm(z))
        self.add_row(tr("Top Z"), mm(bounds.z_max))
        self.add_row(tr("Bottom Z"), mm(bounds.z_min))


def length_box(value, minimum=0.0, maximum=model_stock.BoxStock.MAX_ALLOWANCE_MM):
    """A FreeCAD quantity spin box in mm: it shows the unit and converts what
    the user types ("0.5 in" becomes 12.70 mm), so a number never goes in
    without its unit."""
    box = FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")
    box.setProperty("unit", "mm")
    box.setProperty("minimum", minimum)
    box.setProperty("maximum", maximum)
    box.setProperty("rawValue", value)
    return box


def depth_box(value):
    """Z-Depth. The box takes positive values too, so a wrong sign is refused
    with a message by the model instead of being silently clamped."""
    limit = model_operations.MAX_DEPTH_MM
    return length_box(value, -limit, limit)


def start_z_box(value):
    """A contour's Start Z, from the lines or the zero point (its Relative,
    ui.contour_relative, sets the tool tip): above it or below."""
    box = depth_box(value)
    box.setObjectName("AvangardeCamContourStartZ")
    box.setToolTip(tr("Top of the material, from the sketch plane: the Z steps go down from here to Z-Depth. 0: the sketch plane."))
    return box


# tool compensation of a contour, left and right seen along the arrows
_COMPENSATIONS = (
    (model_operations.OFF, QT_TRANSLATE_NOOP("AvangardeCam", "Off: tool centre on the lines")),
    (model_operations.LEFT, QT_TRANSLATE_NOOP("AvangardeCam", "Left (RL): tool left of the lines")),
    (model_operations.RIGHT, QT_TRANSLATE_NOOP("AvangardeCam", "Right (RR): tool right of the lines")),
)


# how a contour's tool comes onto the lines
_APPROACHES = (
    (model_operations.ARC, QT_TRANSLATE_NOOP("AvangardeCam", "Arc, from beside the lines")),
    (model_operations.NONE, QT_TRANSLATE_NOOP("AvangardeCam", "None: straight down on the lines")),
)


def choice_box(name, choices, value):
    box = QtWidgets.QComboBox()
    box.setObjectName(name)
    for key, text in choices:
        box.addItem(tr(text), key)
    set_choice(box, value)
    return box


def compensation_box(value):
    """Tool compensation of a contour: off, left (RL) or right (RR)."""
    return choice_box("AvangardeCamContourCompensation", _COMPENSATIONS, value)


def approach_box(value):
    """How a contour's tool comes onto the lines: on an arc or straight down."""
    return choice_box("AvangardeCamContourApproach", _APPROACHES, value)


def lead_box(value):
    """Radius of the approach arcs. Takes any length, so a wrong one is
    refused with a message by the model instead of being silently clamped."""
    limit = model_operations.MAX_DEPTH_MM
    box = length_box(value, -limit, limit)
    box.setObjectName("AvangardeCamContourLeadRadius")
    return box


def set_choice(box, value):
    box.blockSignals(True)
    box.setCurrentIndex(max(0, box.findData(value)))
    box.blockSignals(False)


# where the tool comes from, for each direction along the part's axes
_SIDES = {
    "Z+": QT_TRANSLATE_NOOP("AvangardeCam", "from the top"),
    "Z−": QT_TRANSLATE_NOOP("AvangardeCam", "from the bottom"),
    "Y−": QT_TRANSLATE_NOOP("AvangardeCam", "from the front"),
    "Y+": QT_TRANSLATE_NOOP("AvangardeCam", "from the back"),
    "X+": QT_TRANSLATE_NOOP("AvangardeCam", "from the right"),
    "X−": QT_TRANSLATE_NOOP("AvangardeCam", "from the left"),
}


def direction_text(vector):
    """"Z+ (from the top)" for a tool axis in part coordinates."""
    name = model_frame.axis_name(tuple(vector))
    side = _SIDES.get(name)
    return "{} ({})".format(name, tr(side)) if side else name


def point_text(point):
    return "X {:.2f}  Y {:.2f}  Z {:.2f} mm".format(
        *(round(c, 2) + 0.0 for c in (point.x, point.y, point.z))
    )


class StockView(DetailsView):
    """Stock allowances, applied to the FreeCAD stock as they are typed."""

    ALLOWANCES = (
        ("x_neg_mm", "Allowance X−"),
        ("x_pos_mm", "Allowance X+"),
        ("y_neg_mm", "Allowance Y−"),
        ("y_pos_mm", "Allowance Y+"),
        ("z_neg_mm", "Allowance bottom (Z−)"),
        ("z_pos_mm", "Allowance top (Z+)"),
    )
    APPLY_DELAY_MS = 400
    LIVE = True  # updated in place, the allowance boxes keep their focus

    def __init__(self, job, parent=None):
        super().__init__(tr("Stock"), parent=parent)
        self.job = job
        self.boxes = {}
        self.size_label = self.add_row(tr("Size"), "")
        self.top_label = self.add_row(tr("Top Z"), "")
        self.bottom_label = self.add_row(tr("Bottom Z"), "")
        edit = op_zero.stock_edit(job)  # on the active zero point's axes, or on the stock's own
        current = edit.box
        if current is None and ui_next_setup.describe(self, job):
            pass  # a stock left by another setup, a blank's model
        elif current is None:
            # one literal per text, so lupdate finds it
            self.note.setText(
                tr("This stock was made in FreeCAD with a fixed size. Replace it by a box around the model to set allowances here.")  # fmt: skip
            )
            self.add_button(tr("Replace by box with allowances"), self._replace)
        else:
            for name, label in self.ALLOWANCES:
                box = length_box(getattr(current, name))
                box.setObjectName("AvangardeCamStock_" + name)
                box.valueChanged.connect(self._schedule_apply)
                self.form.addRow(tr(label) + ":", box)
                self.boxes[name] = box
        self.add_button(tr("Stock size..."), self._ask_size, "AvangardeCamStockSizeButton")
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply)
        self.update_view()

    def _schedule_apply(self, *_args):
        self._timer.start(self.APPLY_DELAY_MS)

    def wanted(self):
        values = {name: float(box.property("rawValue")) for name, box in self.boxes.items()}
        return model_stock.BoxStock(**values)

    def apply(self):
        """Write the allowances to the FreeCAD stock (one undo step)."""
        self._timer.stop()
        try:
            wanted = self.wanted().validate()
        except ValueError as exc:
            _show_error(str(exc))
            return
        if wanted == op_zero.stock_edit(self.job).box:
            return
        doc = self.job.Document
        doc.openTransaction(tr("Stock allowance"))
        try:
            op_zero.set_stock(self.job, wanted)
        finally:
            doc.commitTransaction()

    def _ask_size(self):
        """X, Y, Z of the block typed, the model put in its middle (ui.stock_size)."""
        from avangardecam.ui import stock_size

        if self._timer.isActive():
            self.apply()  # an allowance still being typed goes in first
        stock_size.ask(self.job)

    def _replace(self):
        doc = self.job.Document
        doc.openTransaction(tr("Stock allowance"))
        try:
            cam.set_stock(self.job, model_stock.BoxStock())
        finally:
            doc.commitTransaction()

    def update_view(self):
        edit = op_zero.stock_edit(self.job)
        bounds = edit.bounds
        self.size_label.setText(size_text(bounds))
        self.top_label.setText(mm(bounds.z_max))
        self.bottom_label.setText(mm(bounds.z_min))
        current = edit.box
        if current is None or not self.boxes:
            return
        note = tr("The stock is the model's box plus these allowances.")
        if edit.own:  # whose axes: it changes as the zero point is moved
            from avangardecam.ui import stock_dialog

            note += " " + stock_dialog.OWN_ZERO_NOTE()
        self.note.setText(note)
        for name, box in self.boxes.items():
            if not box.hasFocus() and not self._timer.isActive():
                box.blockSignals(True)
                box.setProperty("rawValue", getattr(current, name))
                box.blockSignals(False)


class ToolView(DetailsView):
    def __init__(self, job, project_tool, parent=None):
        t = project_tool.tool
        super().__init__("T{}  {}".format(project_tool.number, t.name), parent=parent)
        self.job = job
        self.controller = project_tool.controller

        def number(value, unit):
            return NONE if value is None else "{:g} {}".format(value, unit)

        self.add_row(tr("Tool number"), "T{}".format(project_tool.number))
        self.add_row(tr("Material"), project_tool.workpiece_material or NONE)
        self.add_row(tr("Type"), model_tools.describe(t))
        self.add_row(tr("Diameter"), mm(t.diameter_mm))
        if t.corner_radius_mm:
            self.add_row(tr("Corner radius"), mm(t.corner_radius_mm))
        if t.angle_deg:
            self.add_row(tr("Angle"), number(t.angle_deg, "°"))
        self.add_row(tr("Flutes"), NONE if t.flutes is None else str(t.flutes))
        self.add_row(tr("Cutting length"), mm(t.cutting_length_mm))
        self.add_row(tr("Total length"), mm(t.length_mm))
        self.add_row(tr("Spindle speed"), number(t.spindle_rpm, "rpm"))
        self.add_row(tr("Feed XY"), number(t.feed_xy_mm_min, "mm/min"))
        self.add_row(tr("Feed Z"), number(t.feed_z_mm_min, "mm/min"))
        if not project_tool.library_id:
            self.note.setText(tr("This tool was not made from the tool library."))
        self.add_button(tr("Remove from project"), self._remove, "AvangardeCamRemoveTool")

    def _remove(self):
        doc = self.job.Document
        doc.openTransaction(tr("Remove tool"))
        try:
            cam.remove_tool(self.job, self.controller)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            _show_error(str(exc))
            return
        doc.commitTransaction()


class SetupView(DetailsView):
    """One clamping of the part: where its zero point is and where the tool
    comes from."""

    LIVE = True

    def __init__(self, job, parent=None):
        super().__init__(job.Label, parent=parent)
        self.job = job
        self.axis_label = self.add_row(tr("Tool axis"), "")
        self.zero_label = self.add_row(tr("Zero point"), "")
        self.default_label = self.add_row(tr("From the default 0-Point"), "")
        self.rotation_label = self.add_row(tr("Rotation about Z"), "")
        self.fixture_label = self.add_row(tr("Fixture"), "")
        self.stock_label = self.add_row(tr("Stock"), "")
        self.operations_label = self.add_row(tr("Operations"), "")
        self.note.setText(
            tr("Snap-0-Point puts the zero point in the middle of the part, in the plane of the selected flat face; it is given in the model's coordinates. It is the setup's default zero point: the machine's preset. CAM > Move 0-Point moves it away (onto a wall, by a distance; with 5 axes it turns): operations keep the zero point they were made on and the program gives it from the default one. CAM > Reset 0-Point puts it back, Set 0-Point as default makes the present one the default. Rotate 0-Point turns the whole setup about Z.")  # fmt: skip
        )
        self.update_view()

    def update_view(self):
        from avangardecam.engine import op_zero as engine_op_zero
        from avangardecam.ui import op_zero as ui_op_zero

        place = cam.zero(self.job)
        self.axis_label.setText(direction_text(geometry.tool_axis(place)))
        self.zero_label.setText(point_text(place.Base))
        self.default_label.setText(ui_op_zero.zero_text(engine_op_zero.from_default(self.job)))
        self.rotation_label.setText("{:g}°".format(round(cam.zero_rotation(self.job), 3)))
        self.fixture_label.setText(", ".join(self.job.Fixtures) or NONE)
        self.stock_label.setText(size_text(cam.stock_bounds(self.job)))
        self.operations_label.setText(str(len(cam.operations(self.job))))


def lines_text(sketch, lines):
    """"all (5)" or the picked lines in the tool's order."""
    if not lines:
        return tr("all ({})").format(len(sketch.Shape.Edges))
    shown = list(lines) if len(lines) <= 4 else [lines[0], lines[1], "…", lines[-1]]
    return "{}: {}".format(len(lines), " → ".join(shown))


def sketches_text(picks):
    """(sketches, lines) as a contour's rows show them; picks: (sketch,
    its lines) of each sketch, in the tool's order."""
    if len(picks) == 1:
        return picks[0][0].Label, lines_text(*picks[0])
    sketches = ", ".join(sketch.Label for sketch, _lines in picks)
    return sketches, "\n".join("{}: {}".format(sketch.Label, lines_text(sketch, lines)) for sketch, lines in picks)


class SketchView(DetailsView):
    def __init__(self, sketch, parent=None):
        super().__init__(sketch.Label, parent=parent)
        self.sketch = sketch
        local = sketch.Shape.transformed(sketch.Placement.inverse().toMatrix()).BoundBox
        fits = cam.setups_for_contour(sketch.Document, sketch)  # facing the tool or away from it
        self.add_row(tr("Faces the tool"), direction_text(geometry.tool_axis(sketch.Placement)))
        self.add_row(tr("Size"), "{:.2f} × {:.2f} mm".format(local.XLength, local.YLength))
        self.add_row(tr("Elements"), str(sketch.GeometryCount))
        away = tr("from the other side: contours only")
        self.add_row(
            tr("Setups"),
            "\n".join(j.Label + (" ({})".format(away) if cam.sketch_faces_away(j, sketch) else "") for j in fits) or NONE,
        )
        if fits:
            # its plane from each setup's zero point: the Z of its lines in the program
            planes = ["{}: Z {:.2f} mm".format(j.Label, round(cam.zero(j).inverse().multiply(sketch.Placement).Base.z, 2) + 0.0) for j in fits]  # fmt: skip
            self.add_row(tr("Lines at"), "\n".join(planes))
            self.note.setText(tr("The sketch has no zero point of its own: the program takes its lines where they are, seen from the setup's zero point (Lines at: their Z), also from the other side (a face of the part's bottom contoured from the top; left and right as the tool sees them). Click its lines in 3D in the order the tool follows them: Shift+click adds a line, Ctrl+click the shortest way to a line, Alt+click a whole loop. Selected lines are red; their arrows show the tool's direction, a click on an arrow turns it round. For Drilling, Thread milling and Helix click the circles in the order the tool works them (Shift+click adds one)."))  # fmt: skip
        else:
            self.note.setText(
                tr("No setup has its tool facing this sketch yet: select the face it was taken from and click CAM > Snap-0-Point.")  # fmt: skip
            )
        from avangardecam import handlers

        self.add_button(
            tr("Contour tooling..."),
            lambda: handlers.contour_tooling(self.sketch),
            "AvangardeCamContourTooling",
        )
        self.add_button(tr("Deburring..."), lambda: handlers.deburring(self.sketch), "AvangardeCamDeburring")
        self.add_button(tr("Drilling..."), lambda: handlers.drilling(self.sketch), "AvangardeCamDrilling")
        self.add_button(
            tr("Thread milling..."), lambda: handlers.thread_milling(self.sketch), "AvangardeCamThreadMilling"
        )
        self.add_button(tr("Helix milling..."), lambda: handlers.helix_milling(self.sketch), "AvangardeCamHelixMilling")


def _no_path(op):
    if not op.Active:
        return tr("off: not in the program or the simulation")
    return tr("no path; see the report view in expert mode")


class ContourView(DetailsView):
    """Contour tooling: Z-Depth and the passes are applied as they are
    typed, the tool compensation, approach and order as they are chosen."""

    APPLY_DELAY_MS = 600
    LIVE = True

    def __init__(self, op, parent=None):
        from avangardecam.ui import contour_advanced, contour_ends, contour_passes, contour_relative

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.op = op
        self.job = cam.setup_of(op)
        sketch, contour = cam.contour_of(op)
        sketches, lines = sketches_text(cam.contour_sketches(op) or [(sketch, [])])
        self.add_row(tr("Setup"), self.job.Label if self.job else NONE)
        self.add_row(tr("Sketch"), sketches)
        self.add_row(tr("Lines"), lines)
        self.tool_label = self.add_row(tr("Tool"), "")
        self.start_label = self.add_row(tr("Lines at"), "")
        self.lead_warning = QtWidgets.QLabel()  # approach arcs that do not fit (engine.lead_check)
        self.lead_warning.setObjectName("AvangardeCamContourLeadWarning")
        self.lead_warning.setWordWrap(True)
        self.lead_warning.setStyleSheet("color: #c0392b;")
        self.form.addRow(self.lead_warning)
        self.start_z = start_z_box(contour.start_z_mm)
        self.start_z.valueChanged.connect(self._schedule_apply)
        self.form.addRow(tr("Start Z") + ":", self.start_z)
        self.depth = depth_box(contour.z_depth_mm)
        self.depth.setObjectName("AvangardeCamContourDepth")
        self.depth.valueChanged.connect(self._schedule_apply)
        self.form.addRow(tr("Z-Depth") + ":", self.depth)
        self.relative = contour_relative.RelativeField(self.form, contour, self)
        self.relative.describe(self.start_z, self.depth)
        self.relative.chosen.connect(self.apply)
        self.compensation = compensation_box(contour.compensation)
        self.form.addRow(tr("Compensation") + ":", self.compensation)
        self.approach = approach_box(contour.approach)
        self.form.addRow(tr("Approach") + ":", self.approach)
        self.lead = lead_box(cam.lead_radius(op))
        self.lead.valueChanged.connect(self._schedule_apply)
        self.form.addRow(tr("Approach radius") + ":", self.lead)
        self.passes = contour_passes.PassesFields(self.form, contour, self)
        self.passes.typed.connect(self._schedule_apply)
        self.passes.chosen.connect(self.apply)
        self.advanced = contour_advanced.AdvancedFields(self.form, contour, self.compensation, self.approach, parent=self)
        self.advanced.chosen.connect(self.apply)
        self.ends = contour_ends.EndsFields(self.advanced.rows, contour, self)
        self.ends.typed.connect(self._schedule_apply)
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("The tool follows the lines from Start Z down to Z-Depth, both from the Z of the lines (Lines at, from the zero point) with Relative, else from the zero point (negative below), in the order shown under Lines, by Z steps and with compensation in XY passes from the outside in. Compensation left (RL) or right (RR) is seen along the arrows, as the contour side of Off with arc (under Advanced). On an arc the tool goes down in its centre, the approach radius from the lines. The path in 3D is where the tool centre goes.")  # fmt: skip
        )
        from avangardecam import handlers

        self.add_button(tr("Change tool..."), lambda: handlers.change_tool(self.op), "AvangardeCamChangeTool")
        self.add_button(tr("Remove operation"), self._remove, "AvangardeCamRemoveOperation")
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply)
        self.update_view()

    def _schedule_apply(self, *_args):
        self._timer.start(self.APPLY_DELAY_MS)

    def wanted(self):
        current = cam.contour_of(self.op)[1]
        chosen = self.advanced.values()
        lead = current.lead_radius_mm
        if chosen["approach"] == model_operations.ARC:
            lead = float(self.lead.property("rawValue"))
            if current.lead_radius_mm is None and abs(lead - cam.lead_radius(self.op)) < 1e-9:
                lead = None  # still the default, which follows the tool
        self.passes.compensated(chosen["compensation"] != model_operations.OFF, self.advanced.offset_open())
        return model_operations.Contour(
            float(self.depth.property("rawValue")), lead_radius_mm=lead,
            start_z_mm=float(self.start_z.property("rawValue")), **chosen, **self.passes.values(),
            **self.ends.values(self.advanced.check.isChecked()), **self.relative.values(),
        )  # fmt: skip

    def apply(self, *_args):
        self._timer.stop()
        if self.ends.unreadable(self.advanced.check.isChecked()):
            return  # still being typed
        if self.passes.unreadable() or not (self.depth.hasAcceptableInput() and self.start_z.hasAcceptableInput()):
            return  # still being typed
        try:
            wanted = self.wanted().validate()
        except ValueError as exc:
            _show_error(str(exc))
            self.depth.setFocus()
            return
        current = cam.contour_of(self.op)[1]
        if wanted == current:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Contour tooling"))
        try:
            cam.set_contour(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            _show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        tc = self.op.ToolController
        tool = next((t for t in cam.project_tools(self.job) if t.controller is tc), None)
        if tool is None:
            self.tool_label.setText(tc.Label if tc is not None else NONE)
        else:
            from avangardecam.ui.tool_choice import tool_text

            self.tool_label.setText(tool_text(tool))
        sketch = cam.contour_of(self.op)[0]
        # older contours have no helpers: the plane of their sketch from the zero point
        planes = cam.contour_planes(self.op) or [cam.zero(self.job).inverse().multiply(sketch.Placement).Base.z]
        self.start_label.setText("Z {} mm".format(", ".join("{:.2f}".format(round(z, 2) + 0.0) for z in planes)))
        moves, lowest = cam.path_summary(self.op)
        if moves and lowest is not None:
            self.path_label.setText(tr("{} moves, deepest Z {:.2f} mm").format(moves, round(lowest, 2) + 0.0))
        else:
            self.path_label.setText(_no_path(self.op))
        _sketch, contour = cam.contour_of(self.op)
        for box, value in (
            (self.start_z, contour.start_z_mm), (self.depth, contour.z_depth_mm), (self.lead, cam.lead_radius(self.op)),
        ):  # fmt: skip
            if not box.hasFocus() and not self._timer.isActive():
                box.blockSignals(True)
                box.setProperty("rawValue", value)
                box.blockSignals(False)
        from avangardecam.engine import lead_check

        try:
            warning = lead_check.text(lead_check.for_op(self.op, contour), tr) if self.job is not None else ""
        except (cam.ProjectError, ValueError, ArithmeticError):
            warning = ""  # the path says what is wrong
        self.lead_warning.setText(warning)
        self.lead_warning.setVisible(bool(warning))
        self.advanced.show(contour)
        self.relative.show(contour)
        self.lead.setEnabled(contour.approach == model_operations.ARC)
        if not self._timer.isActive():
            self.passes.show(contour, self.advanced.offset_open())
            self.ends.show(contour)

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()


def tool_row_text(op, job):
    """The tool of an operation as the tool list shows it."""
    from avangardecam.ui.tool_choice import tool_text

    tc = op.ToolController
    tool = next((t for t in cam.project_tools(job) if t.controller is tc), None) if job else None
    if tool is None:
        return tc.Label if tc is not None else NONE
    return tool_text(tool)


class DrillingView(DetailsView):
    """Drilling: typed values are applied after a pause, the depth
    reference as it is chosen; each change is one undo step."""

    APPLY_DELAY_MS = 600

    def __init__(self, op, parent=None):
        from avangardecam import handlers
        from avangardecam.ui import drilling_dialog

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.op = op
        self.job = cam.setup_of(op)
        source, drilling = cam.drilling_of(op)
        self.model = not geometry.is_sketch(source)
        self.add_row(tr("Setup"), self.job.Label if self.job else NONE)
        self.add_row(tr("Model") if self.model else tr("Sketch"), source.Label)
        if self.model:
            self.holes_label = self.add_row(tr("Holes"), "")
            self.holes_label.setWordWrap(True)
        else:
            self.holes_label = None
            self.add_row(tr("Holes"), drilling_dialog.holes_text(source, cam.drilling_circles(op)))
        self.tool_label = self.add_row(tr("Tool"), "")
        self.tool_label.setWordWrap(True)
        self.feeds_label = self.add_row(tr("Feeds"), "")
        self.feeds_label.setWordWrap(True)
        self.feeds_label.setToolTip(tr(drilling_dialog.FEEDS_TIP))
        self.top_label = self.add_row(tr("Holes' top"), "")
        self.fields = drilling_dialog.DrillingFields(self.form, drilling, self, model=self.model)
        self.fields.typed.connect(self._schedule_apply)
        self.fields.chosen.connect(self.apply)
        self.tip_label = self.add_row(tr("The tip goes"), "")
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("Cycle 205 on each hole, in the order shown under Holes. The depth is negative, from the top of the holes (From the model: each hole as deep as the model has it); 0 as the peck depth drills the whole depth at once, 0 as the chip breaking depth breaks no chips. The path in 3D shows FreeCAD's drilling cycle; the NC program has cycle 205 with all its values.")  # fmt: skip
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
        unreadable = self.fields.unreadable()
        if unreadable:
            return  # still being typed
        try:
            wanted = self.fields.drilling().validate()
        except ValueError as exc:
            _show_error(str(exc))
            return
        if wanted == cam.drilling_of(self.op)[1]:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Drilling"))
        try:
            cam.set_drilling(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            _show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        from avangardecam.ui import drilling_dialog

        _source, drilling = cam.drilling_of(self.op)
        tc = self.op.ToolController
        tool = next((t.tool for t in cam.project_tools(self.job) if t.controller is tc), None)
        self.tool_label.setText(tool_row_text(self.op, self.job))
        self.feeds_label.setText(drilling_dialog.feeds_text(tool))
        top, tip = cam.contour_depths(self.op)
        try:
            targets = cam.drill_targets(self.op)
        except cam.ProjectError as exc:  # the model changed
            targets = []
            if self.holes_label is not None:
                self.holes_label.setText(str(exc))
        holes = [(t.diameter, t.hole) for t in targets]
        if self.holes_label is not None and targets:
            self.holes_label.setText(drilling_dialog.picked_text(holes))
        tops = sorted({round(t.top, 2) + 0.0 for t in targets})
        if len(tops) > 1:
            self.top_label.setText("Z {:.2f} … {:.2f} mm".format(tops[-1], tops[0]))
        else:
            self.top_label.setText("Z {:.2f} mm".format(round(top, 2) + 0.0))
        self.tip_label.setText(drilling_dialog.tip_text(drilling, tool, holes))
        holes = cam.drilling_holes(self.op)
        if holes:
            self.path_label.setText(tr("{} holes, tip at Z {:.2f} mm").format(len(holes), round(tip, 2) + 0.0))
        else:
            self.path_label.setText(_no_path(self.op))
        if not self._timer.isActive():
            self.fields.show(drilling)

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()


class ThreadMillingView(DetailsView):
    """Thread milling: typed values are applied after a pause; each change
    is one undo step."""

    APPLY_DELAY_MS = 600

    def __init__(self, op, parent=None):
        from avangardecam import handlers
        from avangardecam.ui import thread_dialog

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.op = op
        self.job = cam.setup_of(op)
        source, thread = cam.thread_milling_of(op)
        self.add_row(tr("Setup"), self.job.Label if self.job else NONE)
        self.add_row(tr("Model") if not geometry.is_sketch(source) else tr("Sketch"), source.Label)
        self.holes_label = self.add_row(tr("Holes"), "")
        self.holes_label.setWordWrap(True)
        self.tool_label = self.add_row(tr("Tool"), "")
        self.tool_label.setWordWrap(True)
        self.feeds_label = self.add_row(tr("Feeds"), "")
        self.top_label = self.add_row(tr("Holes' top"), "")
        self.fields = thread_dialog.ThreadFields(self.form, thread, self)
        self.fields.typed.connect(self._schedule_apply)
        self.helix_label = self.add_row(tr("Helix"), "")
        self.helix_label.setWordWrap(True)
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("An internal right-hand thread in each hole, in the order shown under Holes: down to the top of the hole, out to the major diameter with radius compensation right (RR), down a helix clockwise to the depth (negative, from the top of each hole), the same helix again for each pass. The path in 3D is where the tool centre runs; the NC program has the thread with RR.")  # fmt: skip
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
            wanted = self.fields.thread().validate()
        except ValueError as exc:
            _show_error(str(exc))
            return
        if wanted == cam.thread_milling_of(self.op)[1]:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Thread milling"))
        try:
            cam.set_thread_milling(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            _show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        from avangardecam.ui import drilling_dialog, thread_dialog

        source, thread = cam.thread_milling_of(self.op)
        tc = self.op.ToolController
        tool = next((t.tool for t in cam.project_tools(self.job) if t.controller is tc), None)
        self.tool_label.setText(tool_row_text(self.op, self.job))
        self.feeds_label.setText(thread_dialog.feeds_text(tool))
        top, bottom = cam.contour_depths(self.op)
        try:
            targets = cam.drill_targets(self.op)
        except cam.ProjectError as exc:  # the model changed
            targets = []
            self.holes_label.setText(str(exc))
        if targets:
            if geometry.is_sketch(source):
                self.holes_label.setText(drilling_dialog.holes_text(source, cam.drilling_circles(self.op)))
            else:
                self.holes_label.setText(drilling_dialog.picked_text([(t.diameter, t.hole) for t in targets]))
        tops = sorted({round(t.top, 2) + 0.0 for t in targets})
        if len(tops) > 1:
            self.top_label.setText("Z {:.2f} … {:.2f} mm".format(tops[-1], tops[0]))
        else:
            self.top_label.setText("Z {:.2f} mm".format(round(top, 2) + 0.0))
        self.helix_label.setText(thread_dialog.helix_text(thread, tool))
        self.fields.show_name(tool.pitch_mm if thread_dialog.is_thread_mill(tool) else None)
        moves, lowest = cam.path_summary(self.op)
        if moves and lowest is not None:
            self.path_label.setText(tr("{} holes, down to Z {:.2f} mm").format(len(targets), round(lowest, 2) + 0.0))
        else:
            self.path_label.setText(_no_path(self.op))
        if not self._timer.isActive():
            self.fields.show(thread)

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()


class AdaptiveView(DetailsView):
    """Adaptive clearing: typed values are applied after a pause; each
    change is one undo step."""

    APPLY_DELAY_MS = 600

    def __init__(self, op, parent=None):
        from avangardecam import handlers
        from avangardecam.ui import adaptive_dialog

        super().__init__(op.Label, parent=parent)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)  # the panel is narrow
        self.layout().insertWidget(self.layout().indexOf(self.form), adaptive_dialog.check_label(self))
        self.op = op
        self.job = cam.setup_of(op)
        model, adaptive = cam.adaptive_of(op)
        self.add_row(tr("Setup"), self.job.Label if self.job else NONE)
        self.area_label = self.add_row(tr("Area"), "")
        self.area_label.setWordWrap(True)
        self.tool_label = self.add_row(tr("Tool"), "")
        self.tool_label.setWordWrap(True)
        self.feeds_label = self.add_row(tr("Feeds"), "")
        self.fields = adaptive_dialog.AdaptiveFields(self.form, adaptive, self._stock_top(), self)
        self.fields.typed.connect(self._schedule_apply)
        self.levels_label = self.add_row(tr("Z levels"), "")
        self.levels_label.setWordWrap(True)
        self.path_label = self.add_row(tr("Path"), "")
        self.note.setText(
            tr("From Start Z down to Z-Depth (the Z of the program) with an even load, on the Z levels shown: the Z steps and a level on each flat floor of the model from Start Z down, where only around that floor is cleared (the rest on the next Z step). The model is never cut. The path in 3D is where the tool centre runs.")  # fmt: skip
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
            wanted = self.fields.adaptive().validate()
        except ValueError as exc:
            _show_error(str(exc))
            return
        if wanted == cam.adaptive_of(self.op)[1]:
            return
        doc = self.op.Document
        doc.openTransaction(tr("Adaptive"))
        try:
            cam.set_adaptive(self.op, wanted)
        except cam.ProjectError as exc:
            doc.abortTransaction()
            self.update_view()
            _show_error(str(exc))
            return
        doc.commitTransaction()

    def update_view(self):
        from avangardecam.ui import adaptive_dialog

        model, adaptive = cam.adaptive_of(self.op)
        faces = cam.adaptive_floors(self.op)
        try:
            self.area_label.setText(adaptive_dialog.area_text(self.job, model, faces))
            levels = cam.adaptive_levels(self.job, adaptive, self.op.Base)
            self.levels_label.setText(adaptive_dialog.levels_text(levels))
        except cam.ProjectError as exc:  # the model changed
            self.area_label.setText(str(exc))
            self.levels_label.setText(NONE)
        tc = self.op.ToolController
        tool = next((t.tool for t in cam.project_tools(self.job) if t.controller is tc), None)
        self.tool_label.setText(tool_row_text(self.op, self.job))
        self.feeds_label.setText(adaptive_dialog.feeds_text(tool))
        self.fields.show_step_over(tool)
        moves, lowest = cam.path_summary(self.op)
        if moves and lowest is not None:
            self.path_label.setText(tr("{} moves, down to Z {:.2f} mm").format(moves, round(lowest, 2) + 0.0))
        else:
            self.path_label.setText(_no_path(self.op))
        if not self._timer.isActive():
            self.fields.show(adaptive, self._stock_top())

    def _remove(self):
        doc = self.op.Document
        doc.openTransaction(tr("Remove operation"))
        try:
            cam.remove_operation(self.op)
        finally:
            doc.commitTransaction()
