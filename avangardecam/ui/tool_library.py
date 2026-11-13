# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Tool library window: the shop's tools with every material variant.

A T number may appear several times (one variant per workpiece material or
insert). A setup takes one variant per T number; picking another variant
of a number already in the setup offers to replace it. Tools go to the
active setup (the first one is made when there is none).

With pick=True it chooses one tool for an operation instead (Choose tool
in Contour tooling): any row, also the setup's own tools; the caller adds
it to the setup. only=(label, suits) adds a check box showing only the
tools of the operation's kind (Drills only), on as only_on says.

A click on the T or Ø header sorts the table by it, smallest first; a
second click, largest first (an arrow in the header shows which).
"""

import os

import FreeCADGui

from PySide import QtCore, QtGui, QtWidgets

from avangardecam import params, tool_library_path, tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import library
from avangardecam.model import tools as model_tools

ALL = "*"

COLUMNS = (
    "T",
    "Name",
    "Ø mm",
    "Material",
    "Type",
    "Flutes",
    "rpm",
    "Feed XY mm/min",
    "Feed Z mm/min",
)


_TEXT_COLUMNS = (1, 3, 4)  # left aligned
# the columns a header click sorts by: {column: key(entry)}
_SORT_KEYS = {
    0: lambda entry: entry.number,
    2: lambda entry: entry.tool.diameter_mm if entry.tool.diameter_mm is not None else float("inf"),
}


def _g(value):
    return "" if value is None else "{:g}".format(value)


def ask_replace(parent, taken):
    """Ask whether a variant (cam.ToolNumberTaken) replaces the setup's tool
    of its T number."""
    existing, wanted = taken.existing, taken.wanted
    answer = QtWidgets.QMessageBox.question(
        parent,
        tr("Tool library"),
        tr("T{} is already in the project:\n  {} ({})\n\nReplace it by:\n  {} ({})?\n\nOperations using T{} will use the new speeds and feeds.").format(  # fmt: skip
            existing.number,
            existing.tool.name,
            existing.workpiece_material or "?",
            wanted.tool.name,
            wanted.workpiece_material or "?",
            existing.number,
        ),
    )
    return answer == QtWidgets.QMessageBox.Yes


class ToolLibraryDialog(QtWidgets.QDialog):
    def __init__(self, doc, parent=None, pick=False, job=None, only=None, only_on=True):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamToolPicker" if pick else "AvangardeCamToolLibrary")
        self.setWindowTitle(tr("Choose tool") if pick else tr("Tool library"))
        self.doc = doc
        self.pick = pick
        self.job = job  # the setup tools go to; None: the active one
        self.picked = None  # the chosen LibraryTool (pick)
        self.suits = only[1] if only else None  # only=(label, suits(model Tool)): a check box showing only those
        self.entries = []
        self.shown = []  # entries in table order
        self.sort = None  # (column, largest first) of a header click; None: library order
        self.resize(1100, 620)
        # tests replace this to answer the replace question
        self.confirm_replace = self._ask_replace

        layout = QtWidgets.QVBoxLayout(self)

        source = QtWidgets.QHBoxLayout()
        source.addWidget(QtWidgets.QLabel(tr("Library:")))
        self.path_label = QtWidgets.QLabel()
        self.path_label.setObjectName("AvangardeCamLibraryPath")
        self.path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        source.addWidget(self.path_label, 1)
        other = QtWidgets.QPushButton(tr("Open other library..."))
        other.clicked.connect(self._choose_file)
        source.addWidget(other)
        layout.addLayout(source)

        filters = QtWidgets.QHBoxLayout()
        filters.addWidget(QtWidgets.QLabel(tr("Material:")))
        self.material_box = QtWidgets.QComboBox()
        self.material_box.setObjectName("AvangardeCamMaterialFilter")
        self.material_box.currentIndexChanged.connect(self._fill)
        filters.addWidget(self.material_box)
        filters.addSpacing(16)
        filters.addWidget(QtWidgets.QLabel(tr("Search:")))
        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("AvangardeCamToolSearch")
        self.search.setPlaceholderText(tr("name, T number or diameter"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        filters.addWidget(self.search, 1)
        self.only_box = None
        if only:
            filters.addSpacing(16)
            self.only_box = QtWidgets.QCheckBox(tr(only[0]))
            self.only_box.setObjectName("AvangardeCamToolKindFilter")
            self.only_box.setChecked(only_on)
            self.only_box.toggled.connect(self._fill)
            filters.addWidget(self.only_box)
        layout.addLayout(filters)

        self.table = QtWidgets.QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("AvangardeCamToolTable")
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection if pick else QtWidgets.QAbstractItemView.ExtendedSelection
        )
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.table.horizontalHeader().sectionClicked.connect(self.sort_by)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _item: self.use_selected() if pick else self.add_selected())
        layout.addWidget(self.table, 1)

        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamToolLibraryMessage")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)

        buttons = QtWidgets.QDialogButtonBox()
        if pick:
            self.add_button = buttons.addButton(tr("Use this tool"), QtWidgets.QDialogButtonBox.AcceptRole)
            self.add_button.setObjectName("AvangardeCamUseTool")
            self.add_button.clicked.connect(self.use_selected)
        else:
            self.add_button = buttons.addButton(tr("Add to project"), QtWidgets.QDialogButtonBox.AcceptRole)
            self.add_button.setObjectName("AvangardeCamAddTools")
            self.add_button.clicked.connect(self.add_selected)
        close = buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        close.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.load(tool_library_path())

    # -- library file ---------------------------------------------------------

    def load(self, path):
        self.path_label.setText(path)
        try:
            self.entries = library.load(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.entries = []
            self.message.setText(tr("The library could not be read: {}").format(exc))
        self.material_box.blockSignals(True)
        self.material_box.clear()
        self.material_box.addItem(tr("All"), ALL)
        for material in library.materials(self.entries):
            self.material_box.addItem(material, material)
        self.material_box.blockSignals(False)
        self._fill()

    def _choose_file(self):
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            tr("Open tool library"),
            os.path.dirname(tool_library_path()),
            tr("AvangardeCam tool library") + " (*.json)",
        )
        if path:
            params().SetString("ToolLibraryFile", path)
            self.load(path)

    # -- table ------------------------------------------------------------

    def _job(self):
        from avangardecam.ui import scene

        return self.job if self.job is not None else scene.active_setup(self.doc)

    def _project(self):
        """{T number: ProjectTool} of the active setup."""
        return {t.number: t for t in cam.project_tools(self._job())}

    def _matches(self, entry):
        if self.only_box is not None and self.only_box.isChecked() and not self.suits(entry.tool):
            return False
        material = self.material_box.currentData()
        if material not in (None, ALL) and entry.workpiece_material != material:
            return False
        words = self.search.text().lower().split()
        haystack = "t{} {} {} {} ø{:g}".format(
            entry.number,
            entry.tool.name,
            entry.workpiece_material,
            entry.tool.shape,
            entry.tool.diameter_mm,
        ).lower()
        return all(word in haystack for word in words)

    def sort_by(self, column):
        """Sort by the T or Ø column: smallest first, clicked again largest
        first. Other columns do not sort."""
        if column not in _SORT_KEYS:
            return
        largest_first = self.sort == (column, False)
        self.sort = (column, largest_first)
        self._fill()
        self.table.scrollToTop()

    def _headers(self):
        for column, name in enumerate(COLUMNS):
            text = tr(name)
            if self.sort is not None and self.sort[0] == column:
                text += " ▼" if self.sort[1] else " ▲"
            item = QtWidgets.QTableWidgetItem(text)
            if column in _SORT_KEYS:
                item.setToolTip(tr("Click: smallest first; again: largest first"))
            self.table.setHorizontalHeaderItem(column, item)

    def _fill(self, *_args):
        in_project = self._project()
        self.shown = [e for e in self.entries if self._matches(e)]
        if self.sort is not None:
            column, largest_first = self.sort
            self.shown.sort(key=_SORT_KEYS[column], reverse=largest_first)
        self._headers()
        self.table.setRowCount(len(self.shown))
        grey = self.palette().brush(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
        for row, entry in enumerate(self.shown):
            t = entry.tool
            values = (
                "T{}".format(entry.number),
                t.name,
                _g(t.diameter_mm),
                entry.workpiece_material,
                model_tools.describe(t),
                _g(t.flutes),
                _g(t.spindle_rpm),
                _g(t.feed_xy_mm_min),
                _g(t.feed_z_mm_min),
            )
            current = in_project.get(entry.number)
            for column, text in enumerate(values):
                item = QtWidgets.QTableWidgetItem(text)
                if column not in _TEXT_COLUMNS:
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                if current is not None and current.library_id == entry.id:
                    if not self.pick:  # already there; picked, it is used as it is
                        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsSelectable)
                    item.setForeground(grey)
                    item.setToolTip(tr("In the project"))
                elif current is not None:
                    font = item.font()
                    font.setItalic(True)
                    item.setFont(font)
                    item.setToolTip(
                        tr("T{} is in the project as: {}. Adding this one replaces it.").format(
                            entry.number, current.tool.name
                        )
                    )
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.message.setText(
            tr("{} of {} tools. Grey: in the project. Italic: another variant of that T number is in the project.").format(  # fmt: skip
                len(self.shown), len(self.entries)
            )
        )
        self._update_buttons()

    def selected_entries(self):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.shown[row] for row in rows]

    def _update_buttons(self):
        self.add_button.setEnabled(bool(self.selected_entries()))

    def select_ids(self, ids):
        """Select the rows of the given library ids (used by tests)."""
        self.table.clearSelection()
        mode = self.table.selectionMode()
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        for row, entry in enumerate(self.shown):
            if entry.id in ids:
                self.table.selectRow(row)
        self.table.setSelectionMode(mode)

    # -- adding -------------------------------------------------------------

    def _ask_replace(self, taken):
        return ask_replace(self, taken)

    def use_selected(self):
        """Pick: the selected tool, after asking when another variant of its
        T number is in the setup."""
        entries = self.selected_entries()
        if len(entries) != 1:
            self.message.setText(tr("Choose one tool."))
            return
        entry = entries[0]
        current = self._project().get(entry.number)
        if current is not None and current.library_id != entry.id:
            if not self.confirm_replace(cam.ToolNumberTaken(current, entry)):
                return
        self.picked = entry
        self.accept()

    def add_selected(self):
        entries = self.selected_entries()
        if not entries:
            return
        numbers = [e.number for e in entries]
        twice = sorted({n for n in numbers if numbers.count(n) > 1})
        if twice:
            self.message.setText(
                tr("Choose one variant per T number: {}").format(
                    ", ".join("T{}".format(n) for n in twice)
                )
            )
            return
        doc = self.doc
        done, errors = [], []
        # no undo step: FreeCAD cannot undo the making of a tool (in the GUI
        # the undo stops at its tool bit); "Remove from project" takes it out
        try:
            job = self._job() or cam.ensure_job(doc)
            for entry in entries:
                try:
                    cam.add_tool(job, entry)
                    done.append("T{}".format(entry.number))
                except cam.ToolNumberTaken as taken:
                    if self.confirm_replace(taken):
                        cam.replace_tool(job, taken.existing.controller, entry)
                        done.append("T{} ({})".format(entry.number, entry.workpiece_material))
                except cam.ProjectError as exc:
                    errors.append(str(exc))
        except cam.ProjectError as exc:
            errors.append(str(exc))
        self._fill()
        text = tr("In the project now: {}").format(", ".join(done)) if done else ""
        if errors:
            text = (text + "\n" if text else "") + "\n".join(errors)
        self.message.setText(text)
