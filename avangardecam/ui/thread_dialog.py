# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Thread milling window: the thread mill, the thread's major diameter,
its depth and the passes, for picked circles of a sketch or holes of a
model (model.threads: the way the shop's programs mill threads).

The major diameter is suggested from the holes and the thread mill's
pitch (threads.suggested_major: Ø2.5 with P0.5 is M3) until the user types
one. The same fields (ThreadFields) are in the details of a thread milling.

The tool (ui.tool_choice): a thread mill for the holes (the setup's, else
the tool library's in the material of the tool used last or of the setup's
tools): it fits into them and its pitch makes a standard thread of them;
else the one used last for a thread milling, else the setup's first thread
mill. The list and Choose tool... show only thread mills (Thread mills
only, which can be switched off). The window starts with the depth and
passes used last.
"""

import collections
import dataclasses

import FreeCADGui

from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tr
from avangardecam.model import operations as model_operations
from avangardecam.model import threads as model_threads
from avangardecam.ui import details, manual, window_fit
from avangardecam.ui.tool_choice import ToolChooser, library_id

DEFAULT_DEPTH_MM = -10.0
_LAST_THREAD = "LastThreadMilling"  # depth and passes, as JSON
LAST_TOOL = "LastThreadTool"  # library id

_LABELS = {
    "major_diameter_mm": QT_TRANSLATE_NOOP("AvangardeCam", "Major diameter"),
    "depth_mm": QT_TRANSLATE_NOOP("AvangardeCam", "Depth"),
}


def is_thread_mill(tool):
    return tool is not None and tool.shape == "ThreadMill" and bool(tool.pitch_mm)


# the tool lists show only these, unless switched off
THREAD_MILLS_ONLY = (QT_TRANSLATE_NOOP("AvangardeCam", "Thread mills only"), is_thread_mill)


def last_thread(major_mm):
    """A thread milling of major_mm with the depth and passes used last,
    else the defaults."""
    text = params().GetString(_LAST_THREAD, "")
    try:
        last = model_operations.from_json(text) if text else None
    except (ValueError, TypeError):
        last = None
    if not isinstance(last, model_operations.ThreadMilling):
        last = model_operations.ThreadMilling(major_mm, DEFAULT_DEPTH_MM)
    return dataclasses.replace(last, major_diameter_mm=major_mm)


def main_diameter(holes):
    """The diameter most of the holes (diameter, ...) have, None without holes."""
    count = collections.Counter(round(d, 3) for d, _h in holes)
    return count.most_common(1)[0][0] if count else None


def _fits(tool, holes):
    """True when a thread mill goes into all the holes and its pitch makes
    a standard thread of the main one."""
    if not is_thread_mill(tool) or not holes:
        return False
    if any(tool.diameter_mm >= d - 1e-6 for d, _h in holes):
        return False
    major = model_threads.suggested_major(main_diameter(holes), tool.pitch_mm)
    return model_threads.standard(major, tool.pitch_mm) is not None


def suggested_mill(tools, library, holes, last_id=""):
    """A thread mill for the holes (see _fits): the setup's (ProjectTool),
    the one used last first; else a library variant (LibraryTool) in the
    material of the tool used last (last_id) or of the setup's tools, or
    the only one there is. None when there is none or the material is not
    clear: variants differ in speeds and feeds."""
    mine = [t for t in tools if _fits(t.tool, holes)]
    if mine:
        return next((t for t in mine if t.library_id == last_id), mine[0])
    found = [e for e in library if _fits(e.tool, holes)]
    if len(found) <= 1:
        return found[0] if found else None
    last = next((e for e in library if e.id == last_id), None) if last_id else None
    materials = ([last.workpiece_material] if last is not None else []) + [t.workpiece_material for t in tools]
    for material in materials:
        match = [e for e in found if e.workpiece_material == material]
        if match:
            return match[0]
    return None


def feeds_text(tool):
    """The feeds a thread milling takes from a model Tool."""
    if tool is None or not (tool.feed_xy_mm_min and tool.feed_z_mm_min):
        return details.NONE
    return tr("Z {:g}, XY {:g} mm/min").format(tool.feed_z_mm_min, tool.feed_xy_mm_min)


def helix_text(thread, tool):
    """"13 turns of P0.5, 2 passes" or "13 turns + 72° of P0.5, 1 pass"."""
    if not is_thread_mill(tool):
        return details.NONE
    full, rest = model_threads.turns(thread, tool.pitch_mm)
    text = tr("{:g} turns").format(full / 2.0)
    if rest:
        text += " + {:g}°".format(round(360.0 * rest / tool.pitch_mm, 1))
    passes = tr("1 pass") if thread.passes == 1 else tr("{} passes").format(thread.passes)
    return "{} {}, {}".format(text, tr("of P{:g}").format(tool.pitch_mm), passes)


def fit_text(thread, tool, holes):
    """What is wrong between the thread mill (model Tool), the thread and the
    holes (diameter, HoleDepth or None), else ""."""
    if tool is None:
        return ""
    if not is_thread_mill(tool):
        return tr("{} is not a thread mill; choose one (Draadfrees).").format(tool.name)
    try:
        thread.check(tool.diameter_mm, tool.pitch_mm)
    except ValueError as exc:
        return str(exc)
    small = sorted({round(d, 3) for d, _h in holes if tool.diameter_mm >= d - 1e-6})
    if small:
        return tr("The thread mill (Ø{:g}) does not fit into holes of {}.").format(
            tool.diameter_mm, ", ".join("Ø{:g}".format(d) for d in small)
        )
    shallow = [h for _d, h in holes if h is not None and not h.through and thread.depth_mm < h.depth_mm - 1e-6]
    if shallow:
        deepest = max(-h.depth_mm for h in shallow)
        return tr("The thread is deeper than a hole of the model ({:g} mm).").format(round(deepest, 3))
    return ""


class ThreadFields(QtCore.QObject):
    """The values of a thread milling as rows of a form. typed: a value was
    typed; the major diameter says major_edited first."""

    typed = QtCore.Signal()
    major_edited = QtCore.Signal()

    def __init__(self, form, thread, parent=None):
        super().__init__(parent)
        limit = model_operations.MAX_DEPTH_MM
        self.boxes = {}
        # any length: a wrong one is refused by the model, not clamped
        self.major = details.length_box(thread.major_diameter_mm, -limit, limit)
        self.major.setObjectName("AvangardeCamThreadMajor")
        self.major.valueChanged.connect(self._major_changed)
        self.boxes["major_diameter_mm"] = self.major
        self.name = QtWidgets.QLabel()
        self.name.setObjectName("AvangardeCamThreadName")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.major, 1)
        row.addWidget(self.name)
        form.addRow(tr(_LABELS["major_diameter_mm"]) + ":", row)
        self.depth = details.length_box(thread.depth_mm, -limit, limit)
        self.depth.setObjectName("AvangardeCamThreadDepth")
        self.depth.setToolTip(tr("Negative, from the top of the holes: where the helix ends"))
        self.depth.valueChanged.connect(lambda *_args: self.typed.emit())
        self.boxes["depth_mm"] = self.depth
        form.addRow(tr(_LABELS["depth_mm"]) + ":", self.depth)
        self.passes = QtWidgets.QSpinBox()
        self.passes.setObjectName("AvangardeCamThreadPasses")
        self.passes.setRange(1, model_operations.MAX_PASSES)
        self.passes.setValue(thread.passes)
        self.passes.setToolTip(tr("How many times the tool runs the same helix"))
        self.passes.valueChanged.connect(lambda *_args: self.typed.emit())
        form.addRow(tr("Passes") + ":", self.passes)

    def _major_changed(self, *_args):
        self.major_edited.emit()
        self.typed.emit()

    def unreadable(self):
        """Label of the first field that does not hold a length, else ""."""
        for field, box in self.boxes.items():
            if not box.hasAcceptableInput():
                return tr(_LABELS[field])
        return ""

    def thread(self):
        return model_operations.ThreadMilling(
            float(self.major.property("rawValue")), float(self.depth.property("rawValue")), self.passes.value()
        )

    def set_major(self, major_mm):
        """Show a major diameter without it counting as typed."""
        self.major.blockSignals(True)
        self.major.setProperty("rawValue", major_mm)
        self.major.blockSignals(False)

    def show_name(self, pitch_mm):
        """The thread's name beside the major diameter ("M3"), for a pitch."""
        if pitch_mm and not self.unreadable():
            self.name.setText(model_threads.name(float(self.major.property("rawValue")), pitch_mm))
        else:
            self.name.setText("")

    def busy(self):
        """True while the user is in a field."""
        return any(box.hasFocus() for box in self.boxes.values()) or self.passes.hasFocus()

    def show(self, thread):
        """Show a thread milling's values, but not in the field being typed in."""
        for field, box in self.boxes.items():
            if not box.hasFocus():
                box.blockSignals(True)
                box.setProperty("rawValue", getattr(thread, field))
                box.blockSignals(False)
        if not self.passes.hasFocus():
            self.passes.blockSignals(True)
            self.passes.setValue(thread.passes)
            self.passes.blockSignals(False)


class ThreadMillingDialog(QtWidgets.QDialog):
    """source: the sketch or the model of the holes; text: the holes as the
    window shows them; holes: (diameter, HoleDepth) of each, HoleDepth None
    for a sketch's circles; ignored: how many other lines were selected;
    library: the tool library's variants (LibraryTool). To edit a thread
    milling: start, its model ThreadMilling, and tool, its ProjectTool; the
    values used last are then neither shown nor remembered."""

    def __init__(self, job, source, text, holes, library=(), ignored=0, parent=None, start=None, tool=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamThreadDialog")
        self.setWindowTitle(tr("Thread milling"))
        self.job = job
        self.editing = start is not None
        self.holes = list(holes)
        self.major_typed = self.editing  # an edited thread keeps its diameter
        model = any(h is not None for _d, h in self.holes)

        box = QtWidgets.QVBoxLayout(self)
        heading = QtWidgets.QLabel(tr("Thread milling: internal, right-hand, from the top down"))
        heading.setStyleSheet("font-weight: bold;")
        box.addWidget(heading)
        form = QtWidgets.QFormLayout()
        box.addLayout(form)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        form.addRow((tr("Model") if model else tr("Sketch")) + ":", QtWidgets.QLabel(source.Label))
        if ignored:
            text += "  " + tr("({} other lines are left out)").format(ignored)
        holes_label = QtWidgets.QLabel(text)
        holes_label.setObjectName("AvangardeCamThreadHoles")
        form.addRow(tr("Holes") + ":", holes_label)
        self.chooser = ToolChooser(job, "AvangardeCamThread", only=THREAD_MILLS_ONLY)
        form.addRow(tr("Tool") + ":", self.chooser)
        self.fit = QtWidgets.QLabel()
        self.fit.setObjectName("AvangardeCamThreadFit")
        self.fit.setWordWrap(True)
        self.fit.setStyleSheet("color: #b9770e;")
        form.addRow(self.fit)
        self.feeds = QtWidgets.QLabel()
        self.feeds.setObjectName("AvangardeCamThreadFeeds")
        form.addRow(tr("Feeds") + ":", self.feeds)
        self.chooser.follow(self.feeds, feeds_text)  # the operation's own spindle speed and feeds
        if start is None:
            start = last_thread(main_diameter(self.holes) or 1.0)
        self.fields = ThreadFields(form, start, self)
        self.helix = QtWidgets.QLabel()
        self.helix.setObjectName("AvangardeCamThreadHelix")
        form.addRow(tr("Helix") + ":", self.helix)

        manual_text = tr("The major diameter is the thread's nominal one (M3: 3 mm); the pitch is the thread mill's. The depth is negative, from the top of each hole: the tool goes down to the top, out to the thread with radius compensation right (RR) and down a helix clockwise, back to the centre; each further pass runs the same helix again. The holes are threaded in the order they were clicked.")  # fmt: skip
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamThreadMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(buttons, tr("Thread milling"), manual_text)
        box.addWidget(buttons)

        self.fields.major_edited.connect(self._major_typed)
        for signal in (self.chooser.changed, self.fields.typed):
            signal.connect(self._update)
            signal.connect(lambda: self.message.setText(""))
        last_id = params().GetString(LAST_TOOL, "")
        mill = suggested_mill(self.chooser.tools, library, self.holes, last_id)
        if tool is not None:
            self.chooser.choose(tool)
        elif mill is not None:
            self.chooser.choose(mill)
        else:
            self.chooser.start_with(library, last_id, is_thread_mill)
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)
        self.fields.depth.setFocus()
        self.fields.depth.selectAll()

    def use(self, entry):
        self.chooser.use(entry)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        return self.chooser.tool()

    def thread(self):
        return self.fields.thread()

    def _major_typed(self, *_args):
        self.major_typed = True

    def _update(self, *_args):
        choice = self.tool()
        tool = choice.tool if choice is not None else None
        if not self.major_typed and is_thread_mill(tool) and self.holes:
            self.fields.set_major(model_threads.suggested_major(main_diameter(self.holes), tool.pitch_mm))
        self.fields.show_name(tool.pitch_mm if is_thread_mill(tool) else None)
        self.feeds.setText(feeds_text(self.chooser.cutting_tool()))
        if self.fields.unreadable():
            self.fit.setText("")
            self.helix.setText(details.NONE)
        else:
            thread = self.thread()
            self.fit.setText(fit_text(thread, tool, self.holes))
            self.helix.setText(helix_text(thread, tool))
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
            thread = self.thread().validate()
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        wrong = fit_text(thread, self.tool().tool, self.holes)
        if wrong:
            self.message.setText(wrong)
            return
        if self.editing:
            return super().accept()
        params().SetString(_LAST_THREAD, model_operations.to_json(thread))
        if library_id(self.tool()):
            params().SetString(LAST_TOOL, library_id(self.tool()))
        super().accept()
