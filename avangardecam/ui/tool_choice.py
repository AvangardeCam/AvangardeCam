# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The tool of a new operation: one of the setup's tools or any variant of
the shop's tool library (Choose tool...).

A variant that is not in the setup yet is added when the operation is
made; one whose T number the setup has as another variant replaces it
(the picker asks first). The window starts with the tool used last for
that kind of operation; with none, with the setup's first tool that suits
it, else the user chooses: variants differ in speeds and feeds, so the
program does not pick one from the library by itself.

Under the tool: its spindle speed and feeds, changeable for this
operation (ui.cutting_data; own() of them, cutting_changed when one
changes).

An operation may show only its kind of tools (only=(label, suits), e.g.
Drills only for a drilling): a check box, on at the start, hides the others
in the list and in Choose tool...; off, everything is shown. A chosen tool
of another kind turns it off, so the chosen tool is always in the list.
"""

from PySide import QtCore, QtWidgets

from avangardecam import tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.ui.cutting_data import CuttingDataFields


def tool_text(choice):
    """"T21  Iscar Vingerfrees 8mm RVS (RVS)  Ø8" of a ProjectTool or LibraryTool."""
    material = choice.workpiece_material
    diameter = choice.tool.diameter_mm
    return "T{}  {}{}{}".format(
        choice.number,
        choice.tool.name,
        " ({})".format(material) if material else "",
        "  Ø{:g}".format(diameter) if diameter else "",
    )


def library_id(choice):
    return choice.library_id if isinstance(choice, cam.ProjectTool) else choice.id


class ToolChooser(QtWidgets.QWidget):
    """A list of tools with Choose tool... and a hint under it saying what
    the chosen tool means for the setup. prefix names its widgets
    (prefix + "Tool", prefix + "ToolHint", prefix + "ToolFilter").
    only=(label, suits(model Tool)) adds the check box showing only the
    tools that suit."""

    changed = QtCore.Signal()
    cutting_changed = QtCore.Signal()  # a spindle speed or feed changed (also with another tool)

    def __init__(self, job, prefix, parent=None, only=None):
        super().__init__(parent)
        self.job = job
        self.tools = cam.project_tools(job)
        self.choices = []  # ProjectTool or LibraryTool, the setup's first
        self.texts = []  # their texts in the box
        self.rows = []  # indices into choices of the box's rows
        self.only = only
        self.suits = only[1] if only else None
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        row = QtWidgets.QHBoxLayout()
        self.box = QtWidgets.QComboBox()
        self.box.setObjectName(prefix + "Tool")
        self.box.setPlaceholderText(tr("Choose a tool"))
        self.box.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        row.addWidget(self.box, 1)
        choose = QtWidgets.QPushButton(tr("Choose tool..."))
        choose.setObjectName("AvangardeCamChooseTool")
        choose.clicked.connect(self._choose_tool)
        row.addWidget(choose)
        box.addLayout(row)
        self.filter = None
        if only:
            self.filter = QtWidgets.QCheckBox(tr(only[0]))
            self.filter.setObjectName(prefix + "ToolFilter")
            self.filter.setChecked(True)
            self.filter.toggled.connect(self._refill)
            box.addWidget(self.filter)
        self.hint = QtWidgets.QLabel()
        self.hint.setObjectName(prefix + "ToolHint")
        self.hint.setWordWrap(True)
        box.addWidget(self.hint)
        self.cutting = CuttingDataFields(prefix)
        self.cutting.changed.connect(self.cutting_changed)
        box.addWidget(self.cutting)
        for tool in self.tools:
            self._add_choice(tool)
        self.box.setCurrentIndex(-1)
        self.box.currentIndexChanged.connect(self._changed)

    def filtering(self):
        """Whether only the tools that suit are shown."""
        return self.filter is not None and self.filter.isChecked()

    def _refill(self, *_args):
        """The box again with the choices the filter lets through, the
        chosen one staying chosen."""
        chosen = self._chosen_index()
        self.rows = [i for i, c in enumerate(self.choices) if not self.filtering() or self.suits(c.tool)]
        self.box.blockSignals(True)
        self.box.clear()
        for i in self.rows:
            self.box.addItem(self.texts[i])
        self.box.setCurrentIndex(self.rows.index(chosen) if chosen in self.rows else -1)
        self.box.blockSignals(False)
        if chosen is not None and chosen not in self.rows:
            self._changed()

    def _select(self, index):
        """Choose choices[index], showing all tools when the filter hides it."""
        if self.filtering() and not self.suits(self.choices[index].tool):
            self.filter.setChecked(False)
        self.box.setCurrentIndex(self.rows.index(index))

    def _chosen_index(self):
        row = self.box.currentIndex()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def start_with(self, library, last_id, suits):
        """The tool used last (its library id), else the setup's first tool
        for which suits(model Tool) is true."""
        entry = next((e for e in library if e.id == last_id), None) if last_id else None
        if entry is not None:
            self.use(entry)
        else:
            first = next((i for i, t in enumerate(self.tools) if suits(t.tool)), None)
            if first is not None:
                self._select(first)
        self._changed()

    def _add_choice(self, choice):
        text = tool_text(choice)
        if not isinstance(choice, cam.ProjectTool):
            if any(t.number == choice.number for t in self.tools):
                text += "  " + tr("(replaces T{} in {})").format(choice.number, self.job.Label)
            else:
                text += "  " + tr("(new in {})").format(self.job.Label)
        self.choices.append(choice)
        self.texts.append(text)
        self._refill()
        return len(self.choices) - 1

    def choose(self, choice):
        """Choose one of the setup's tools (ProjectTool) or a library variant."""
        if isinstance(choice, cam.ProjectTool):
            mine = (i for i, c in enumerate(self.choices) if isinstance(c, cam.ProjectTool) and c.controller is choice.controller)  # fmt: skip
            self._select(next(mine))
        else:
            self.use(choice)
        self._changed()

    def use(self, entry):
        """Choose a library variant: the setup's tool made from it, else
        the variant itself (added on OK, replacing another variant of its
        T number)."""
        index = next((i for i, c in enumerate(self.choices) if library_id(c) == entry.id), None)
        if index is None:
            index = self._add_choice(entry)
        self._select(index)

    def tool(self):
        """The chosen ProjectTool or LibraryTool, or None."""
        index = self._chosen_index()
        return self.choices[index] if index is not None else None

    def _choose_tool(self):
        from avangardecam.ui.tool_library import ToolLibraryDialog

        picker = ToolLibraryDialog(self.job.Document, self, pick=True, job=self.job, only=self.only, only_on=self.filtering())
        if picker.exec() and picker.picked is not None:
            self.use(picker.picked)

    def cutting_tool(self):
        """The chosen tool's model Tool with the spindle speed and feeds of
        the fields, or None."""
        return self.cutting.cutting_tool()

    def follow(self, label, text):
        """label shows text(cutting_tool()) as the tool and its values change."""
        self.cutting_changed.connect(lambda: label.setText(text(self.cutting_tool())))
        label.setText(text(self.cutting_tool()))

    def _changed(self, *_args):
        choice = self.tool()
        self.cutting.set_tool(choice.tool if choice is not None else None)
        if choice is None:
            self.hint.setText(tr("Choose one of the setup's tools or one from the tool library."))
        elif isinstance(choice, cam.ProjectTool):
            self.hint.setText("")
        else:
            existing = next((t for t in self.tools if t.number == choice.number), None)
            if existing is None:
                self.hint.setText(tr("T{} is not in {} yet; it is added with this variant.").format(choice.number, self.job.Label))  # fmt: skip
            else:
                self.hint.setText(
                    tr("{} has T{} as {}; it is replaced by this variant, and operations using T{} get its speeds and feeds.").format(  # fmt: skip
                        self.job.Label, choice.number, tool_text(existing), choice.number
                    )
                )
        self.changed.emit()
