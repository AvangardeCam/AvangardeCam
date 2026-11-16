# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Adaptive clearing window: the end mill, Z-Depth, Z step, step over and
the finishing allowances, the helix and the lift under Advanced, for the
active setup's whole model or the flat floors clicked in it (model
operations.Adaptive).

Z-Depth is in the setup's coordinates (the Z of the program) and starts
at the lowest picked floor, else the lowest floor of the model
(freecad_cam.suggested_adaptive_depth); the window shows the Z levels it
makes (full Z steps and a level on every floor, where only around the
floor is cleared) as they are typed. The
same fields (AdaptiveFields) are in the details of an adaptive clearing.

The tool (ui.tool_choice): the one used last for an adaptive clearing,
else the setup's first end mill. The window starts with the other values
used last.
"""

import dataclasses

import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import operations as model_operations
from avangardecam.ui import details, manual, window_fit
from avangardecam.ui.tool_choice import ToolChooser, library_id

_LAST_ADAPTIVE = "LastAdaptive"  # the values but Start Z and Z-Depth, as JSON
LAST_TOOL = "LastAdaptiveTool"  # library id
MILLS = ("Endmill", "Bullnose", "Ballend")
_SHOWN_LEVELS = 8

# (field, label, object name) of the length fields; on top, then under Advanced
_MAIN = (
    ("z_depth_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Z-Depth"), "Depth"),
    ("z_step_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Z step"), "ZStep"),
    ("finish_xy_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Finish XY"), "FinishXY"),
    ("finish_z_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Finish Z"), "FinishZ"),
)
_ADVANCED = (("lift_mm", QT_TRANSLATE_NOOP("AvangardeCam", "Lift over cleared floor"), "Lift"),)
_LABELS = {field: label for field, label, _name in _MAIN + _ADVANCED}
_LABELS["start_z_mm"] = QT_TRANSLATE_NOOP("AvangardeCam", "Start Z")
_TIPS = {
    "start_z_mm": QT_TRANSLATE_NOOP("AvangardeCam", "The top of the range the Z levels are worked out in (the first level is a Z step under it), in the setup's coordinates; a floor above it is left as it is"),  # fmt: skip
    "z_depth_mm": QT_TRANSLATE_NOOP("AvangardeCam", "Where the clearing ends, its last level, in the setup's coordinates (the Z of the program); the model is never cut, so it may lie below its floors"),  # fmt: skip
    "z_step_mm": QT_TRANSLATE_NOOP("AvangardeCam", "Full steps down from Start Z; on a floor's own level only around that floor, the rest on the next step; 0: no steps, all but the floors at Z-Depth at once"),  # fmt: skip
    "finish_xy_mm": QT_TRANSLATE_NOOP("AvangardeCam", "Left on the walls of the model"),
    "finish_z_mm": QT_TRANSLATE_NOOP("AvangardeCam", "Left on the floors of the model and above Z-Depth: the lowest level is Z-Depth plus this"),
    "lift_mm": QT_TRANSLATE_NOOP("AvangardeCam", "Over floor it cleared, the tool moves rapid this much above the level"),  # fmt: skip
}


CHECK_STYLE = "color: #c0392b; font-weight: bold;"


def check_note():
    """The warning shown with every Adaptive: it is not yet reliable."""
    return tr("Attention: check that Adaptive works well. Look at its path in Play or Verify before cutting: is everything cleared, does the tool go only where it should?")  # fmt: skip


def check_label(parent=None):
    """check_note as a red label."""
    label = QtWidgets.QLabel(check_note(), parent)
    label.setObjectName("AvangardeCamAdaptiveCheck")
    label.setWordWrap(True)
    label.setStyleSheet(CHECK_STYLE)
    return label


def is_mill(tool):
    return tool is not None and tool.shape in MILLS


def last_adaptive(z_depth_mm):
    """An adaptive clearing down to z_depth_mm with the other values used
    last (Start Z: the top of the stock), else the defaults."""
    text = params().GetString(_LAST_ADAPTIVE, "")
    try:
        last = model_operations.from_json(text) if text else None
    except (ValueError, TypeError):
        last = None
    if not isinstance(last, model_operations.Adaptive):
        last = model_operations.Adaptive(z_depth_mm)
    return dataclasses.replace(last, z_depth_mm=z_depth_mm, start_z_mm=None)


def feeds_text(tool):
    """The feeds an adaptive clearing takes from a model Tool."""
    if tool is None or not (tool.feed_xy_mm_min and tool.feed_z_mm_min):
        return details.NONE
    return tr("Z {:g}, XY {:g} mm/min").format(tool.feed_z_mm_min, tool.feed_xy_mm_min)


def area_text(job, model, faces):
    """"Around the whole model" or "2 floors of Body: Z -1.50, +0.00"."""
    if not faces:
        names = ", ".join(m.Label for m in cam.models(job.Document))
        return tr("Around the whole model ({})").format(names) if names else tr("Around the whole model")
    heights = cam.floor_heights(cam.picked_floors(job, model, faces))
    count = tr("1 floor") if len(faces) == 1 else tr("{} floors").format(len(faces))
    shown = ", ".join("{:+.2f}".format(round(z, 2) + 0.0) for z in heights)
    return tr("{} of {}: Z {}").format(count, model.Label, shown)


def levels_text(levels):
    """"Z +0.00, -1.00, -1.50 (3 levels)", the first ones of many."""
    if not levels:
        return details.NONE
    shown = ", ".join("{:+.2f}".format(round(z, 2) + 0.0) for z in levels[:_SHOWN_LEVELS])
    if len(levels) > _SHOWN_LEVELS:
        shown += ", …"
    count = tr("1 level") if len(levels) == 1 else tr("{} levels").format(len(levels))
    return "Z {} ({})".format(shown, count)


def fit_text(adaptive, tool, levels, top):
    """What is wrong between the tool (model Tool), the values and the Z
    levels under the top of the stock, else ""."""
    if tool is None:
        return ""
    if not is_mill(tool):
        return tr("{} is not an end mill; adaptive clearing needs one.").format(tool.name)
    if not levels:
        return tr("Z-Depth ({:g} mm) plus the allowance in Z must be below the top of the stock (Z{:+g} mm).").format(adaptive.z_depth_mm, round(top, 3))  # fmt: skip
    full = adaptive.full_levels(top)  # a floor's own level cuts less than the next of these
    deepest = max(a - b for a, b in zip([top] + full, full))
    if tool.cutting_length_mm and deepest > tool.cutting_length_mm + 1e-6:
        return tr("A level cuts {:g} mm deep, more than the cutting length of {} ({:g} mm). Enter a Z step.").format(
            round(deepest, 3), tool.name, tool.cutting_length_mm
        )
    return ""


class AdaptiveFields(QtCore.QObject):
    """The values of an adaptive clearing as rows of a form: Start Z (the
    top of the stock, stock_top, when ticked), the main ones, the helix,
    the lift and the finishing pass under Advanced. typed: a value was
    typed or chosen."""

    typed = QtCore.Signal()

    def __init__(self, form, adaptive, stock_top, parent=None):
        super().__init__(parent)
        self.boxes = {}
        self.stock_top = stock_top
        limit = model_operations.MAX_DEPTH_MM

        def length(field, name, value):
            # any length: a wrong one is refused by the model, not clamped
            box = details.length_box(value, -limit, limit)
            box.setObjectName("AvangardeCamAdaptive" + name)
            box.setToolTip(tr(_TIPS[field]))
            box.valueChanged.connect(lambda *_args: self.typed.emit())
            self.boxes[field] = box
            return box

        def add(layout, field, label, name):
            layout.addRow(tr(label) + ":", length(field, name, getattr(adaptive, field) or 0.0))

        self.from_stock = QtWidgets.QCheckBox(tr("Top of the stock"))
        self.from_stock.setObjectName("AvangardeCamAdaptiveFromStock")
        self.from_stock.setToolTip(tr("Start Z follows the top of the stock"))
        start = length("start_z_mm", "StartZ", adaptive.top_mm(stock_top))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(start, 1)
        row.addWidget(self.from_stock)
        form.addRow(tr("Start Z") + ":", row)
        self.from_stock.setChecked(adaptive.start_z_mm is None)
        start.setEnabled(adaptive.start_z_mm is not None)
        self.from_stock.toggled.connect(self._from_stock)
        for row in _MAIN[:2]:
            add(form, *row)
        self.step_over = QtWidgets.QDoubleSpinBox()
        self.step_over.setObjectName("AvangardeCamAdaptiveStepOver")
        self.step_over.setRange(1.0, 100.0)
        self.step_over.setDecimals(1)
        self.step_over.setSuffix(" %")
        self.step_over.setValue(adaptive.step_over_percent)
        self.step_over.setToolTip(tr("The most of the tool's diameter it takes sideways"))
        self.step_over.valueChanged.connect(lambda *_args: self.typed.emit())
        self.step_over_mm = QtWidgets.QLabel()
        self.step_over_mm.setObjectName("AvangardeCamAdaptiveStepOverMm")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.step_over, 1)
        row.addWidget(self.step_over_mm)
        form.addRow(tr("Step over") + ":", row)
        for row in _MAIN[2:]:
            add(form, *row)

        self.more = QtWidgets.QToolButton()
        self.more.setObjectName("AvangardeCamAdaptiveAdvanced")
        self.more.setText(tr("Advanced"))
        self.more.setCheckable(True)
        self.more.setArrowType(QtCore.Qt.RightArrow)
        self.more.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.more.setAutoRaise(True)
        form.addRow(self.more)
        self.advanced = QtWidgets.QWidget()
        advanced = QtWidgets.QFormLayout(self.advanced)
        advanced.setContentsMargins(12, 0, 0, 0)
        self.helix = QtWidgets.QDoubleSpinBox()
        self.helix.setObjectName("AvangardeCamAdaptiveHelix")
        self.helix.setRange(0.1, 89.9)
        self.helix.setDecimals(1)
        self.helix.setSuffix(" °")
        self.helix.setValue(adaptive.helix_angle_deg)
        self.helix.setToolTip(tr("Of the helix the tool goes down on into a closed area"))
        self.helix.valueChanged.connect(lambda *_args: self.typed.emit())
        advanced.addRow(tr("Helix angle") + ":", self.helix)
        for row in _ADVANCED:
            add(advanced, *row)
        self.finishing = QtWidgets.QCheckBox(tr("Finishing pass along the walls"))
        self.finishing.setObjectName("AvangardeCamAdaptiveFinishing")
        self.finishing.setChecked(adaptive.finishing_pass)
        self.finishing.toggled.connect(lambda *_args: self.typed.emit())
        advanced.addRow(self.finishing)
        form.addRow(self.advanced)
        self.advanced.setVisible(False)
        self.more.toggled.connect(self._show_advanced)

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

    def adaptive(self):
        values = {field: float(box.property("rawValue")) for field, box in self.boxes.items()}
        values["z_step_mm"] = values["z_step_mm"] or None  # 0: no steps
        if self.from_stock.isChecked():
            values["start_z_mm"] = None
        return model_operations.Adaptive(
            step_over_percent=self.step_over.value(),
            helix_angle_deg=self.helix.value(),
            finishing_pass=self.finishing.isChecked(),
            **values,
        )

    def busy(self):
        """True while the user is in a field."""
        return any(w.hasFocus() for w in list(self.boxes.values()) + [self.step_over, self.helix])

    def show(self, adaptive, stock_top):
        """Show an adaptive clearing's values, but not in the field being typed in."""
        self.stock_top = stock_top
        shown = dataclasses.asdict(adaptive)
        shown["start_z_mm"] = adaptive.top_mm(stock_top)
        for field, box in self.boxes.items():
            if not box.hasFocus():
                box.blockSignals(True)
                box.setProperty("rawValue", shown[field] or 0.0)
                box.blockSignals(False)
        self.from_stock.blockSignals(True)
        self.from_stock.setChecked(adaptive.start_z_mm is None)
        self.from_stock.blockSignals(False)
        self.boxes["start_z_mm"].setEnabled(adaptive.start_z_mm is not None)
        for box, value in ((self.step_over, adaptive.step_over_percent), (self.helix, adaptive.helix_angle_deg)):
            if not box.hasFocus():
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)
        self.finishing.blockSignals(True)
        self.finishing.setChecked(adaptive.finishing_pass)
        self.finishing.blockSignals(False)


class AdaptiveDialog(QtWidgets.QDialog):
    """job: the setup; model and faces: the flat floors picked in the model
    (names, "Face23"), none for the whole model; library: the tool library's
    variants (LibraryTool). To edit an adaptive clearing: start, its model
    Adaptive, and tool, its ProjectTool; the values used last are then
    neither shown nor remembered."""

    def __init__(self, job, model, faces=(), library=(), parent=None, start=None, tool=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamAdaptiveDialog")
        self.setWindowTitle(tr("Adaptive"))
        self.job = job
        self.editing = start is not None
        self.faces = list(faces)
        self.base = cam.picked_floors(job, model, self.faces) if self.faces else []
        self.top = cam.stock_bounds(job).z_max

        box = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(tr("Adaptive clearing: an even load on the tool, from Start Z down"))
        heading.setStyleSheet("font-weight: bold;")
        box.addWidget(heading)
        box.addWidget(check_label(self))
        form = QtWidgets.QFormLayout()
        box.addLayout(form)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        area = QtWidgets.QLabel(area_text(job, model, self.faces))
        area.setObjectName("AvangardeCamAdaptiveArea")
        area.setWordWrap(True)
        form.addRow(tr("Area") + ":", area)
        self.chooser = ToolChooser(job, "AvangardeCamAdaptive")
        form.addRow(tr("Tool") + ":", self.chooser)
        self.fit = QtWidgets.QLabel()
        self.fit.setObjectName("AvangardeCamAdaptiveFit")
        self.fit.setWordWrap(True)
        self.fit.setStyleSheet("color: #b9770e;")
        form.addRow(self.fit)
        self.feeds = QtWidgets.QLabel()
        self.feeds.setObjectName("AvangardeCamAdaptiveFeeds")
        form.addRow(tr("Feeds") + ":", self.feeds)
        if start is None:
            start = last_adaptive(cam.suggested_adaptive_depth(job, model, self.faces))
        self.fields = AdaptiveFields(form, start, self.top, self)
        self.levels = QtWidgets.QLabel()
        self.levels.setObjectName("AvangardeCamAdaptiveLevels")
        self.levels.setWordWrap(True)
        form.addRow(tr("Z levels") + ":", self.levels)

        manual_text = tr("Clears the stock from Start Z (the top of the stock when ticked) down to Z-Depth, its last level (the Z of the program), with an even load: a small step over, deep cuts. The Z steps go down from Start Z; a level on each flat floor of the model from Start Z down, where only around that floor is cleared (the rest on the next Z step), a floor above Start Z left as it is; the model is never cut. Picked floors: only their area, the tool centre up to their edges. Into a closed area on a helix, else in from beside the stock; over cleared floor rapid just above the level.")  # fmt: skip
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamAdaptiveMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Adaptive clearing"), manual_text)
        box.addWidget(buttons)

        for signal in (self.chooser.changed, self.fields.typed):
            signal.connect(self._update)
            signal.connect(lambda: self.message.setText(""))
        if tool is not None:
            self.chooser.choose(tool)
        else:
            self.chooser.start_with(library, params().GetString(LAST_TOOL, ""), is_mill)
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self.fields.boxes["z_depth_mm"].setFocus()
        self.fields.boxes["z_depth_mm"].selectAll()

    def use(self, entry):
        self.chooser.use(entry)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        return self.chooser.tool()

    def adaptive(self):
        return self.fields.adaptive()

    def _levels(self, adaptive):
        return cam.adaptive_levels(self.job, adaptive, self.base)

    def _update(self, *_args):
        choice = self.tool()
        tool = choice.tool if choice is not None else None
        self.feeds.setText(feeds_text(tool))
        self.fields.show_step_over(tool)
        try:
            adaptive = self.adaptive().validate() if not self.fields.unreadable() else None
        except ValueError:
            adaptive = None
        if adaptive is None:
            self.fit.setText("")
            self.levels.setText(details.NONE)
        else:
            levels = self._levels(adaptive)
            self.levels.setText(levels_text(levels))
            self.fit.setText(fit_text(adaptive, tool, levels, self.top))
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
            adaptive = self.adaptive().validate()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        wrong = fit_text(adaptive, self.tool().tool, self._levels(adaptive), self.top)
        if wrong:
            self.message.setText(wrong)
            return
        if self.editing:
            return super().accept()
        params().SetString(_LAST_ADAPTIVE, model_operations.to_json(adaptive))
        if library_id(self.tool()):
            params().SetString(LAST_TOOL, library_id(self.tool()))
        super().accept()
