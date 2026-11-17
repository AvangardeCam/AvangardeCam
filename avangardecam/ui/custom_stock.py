# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""CAM > Custom stock (user 2026-11-17): the active setup starts from a
model of the blank in a file (a casting, a sawn or pre-machined block:
STEP, IGES, BREP, STL), by default with the middle of its box on the
middle of the model's box (engine.custom_stock). One undo step; a model
sticking out of the blank is said after it is loaded (the blank may lie
another way than the part).

Also opened from the Stock window, the stock's details and its menu (a
right click on it in the list: Move stock... along the setup's axes, Put
in the middle); Next setup has the same choice in its own window
(ui.next_setup).
"""

import os

import FreeCADGui

from PySide import QtWidgets

from avangardecam import params, tr
from avangardecam.engine import ProjectError
from avangardecam.engine import custom_stock as engine
from avangardecam.ui import manual, window_fit

_LAST_DIR = "LastBlankDir"  # as Next setup's
_LAST_MIDDLE = "LastBlankInMiddle"
FILES = "(*.step *.stp *.STEP *.STP *.iges *.igs *.IGES *.IGS *.brep *.brp *.stl *.STL *.obj *.ply)"


def last_middle():
    return params().GetBool(_LAST_MIDDLE, True)


def remember_middle(on):
    params().SetBool(_LAST_MIDDLE, bool(on))


def browse(parent, field):
    """A file dialog for the blank's model; its path put in field."""
    path, _filter = QtWidgets.QFileDialog.getOpenFileName(
        parent, tr("Model of the blank"), params().GetString(_LAST_DIR, ""), tr("Models") + " " + FILES
    )
    if path:
        params().SetString(_LAST_DIR, os.path.dirname(path))
        field.setText(path)
    return path


def middle_box():
    """The check box "middle on the model's middle", as last chosen."""
    box = QtWidgets.QCheckBox(tr("Put the middle of the stock in the middle of the model"))
    box.setToolTip(tr("The file may draw the blank anywhere: its box is moved so that its middle is on the middle of the model's box. A blank the file already draws around the model stays there (its allowances where the foundry put them). Unchecked: the blank always stays where the file draws it, in the part's coordinates."))  # fmt: skip
    box.setChecked(last_middle())
    return box


def out_text(out):
    """What the user is told when the model sticks out of the blank."""
    from avangardecam.ui import details  # it imports ui.next_setup, which imports this

    sides = ", ".join("{} {}".format(s.side, details.mm(s.mm)) for s in out)
    return tr("The model sticks out of the blank: {}. Is the blank large enough, and does it lie the same way as the part?").format(sides)  # fmt: skip


class CustomStockDialog(QtWidgets.QDialog):
    """The file of the blank and where it goes; path() and middle() after exec()."""

    def __init__(self, job, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamCustomStockDialog")
        self.setWindowTitle(tr("Custom stock"))
        box = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        box.addLayout(form)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        row = QtWidgets.QHBoxLayout()
        self.file = QtWidgets.QLineEdit()
        self.file.setObjectName("AvangardeCamCustomStockFile")
        self.file.setPlaceholderText(tr("STEP, IGES, BREP or STL file"))
        row.addWidget(self.file, 1)
        button = QtWidgets.QPushButton(tr("Browse..."))
        button.setObjectName("AvangardeCamCustomStockBrowse")
        button.clicked.connect(lambda: browse(self, self.file))
        row.addWidget(button)
        form.addRow(tr("Blank") + ":", row)
        self.middle = middle_box()
        self.middle.setObjectName("AvangardeCamCustomStockMiddle")
        box.addWidget(self.middle)
        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamCustomStockMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        box.addWidget(self.message)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(tr("Load stock"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        manual.add_button(
            buttons, tr("Custom stock"),
            tr("The setup starts from a model of the blank in a file (a casting, a sawn or pre-machined block) instead of a box with allowances. By default the middle of the blank's box is put on the middle of the model's box, as the file may draw it anywhere; a blank the file already draws around the model stays there. It is only moved, never turned; a right click on the stock in the list moves it along X, Y and Z. Play and Verify start from this material. A box with allowances again: Replace by box with allowances in the stock's details."),  # fmt: skip
        )
        box.addWidget(buttons)
        self.setMinimumWidth(560)
        window_fit.fit_contents(self)

    def _accept(self):
        if not self.path():
            self.message.setText(tr("Choose the file of the blank first."))
            return
        remember_middle(self.middle.isChecked())
        self.accept()

    def path(self):
        return self.file.text().strip()


def _warn(text):
    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), tr("Custom stock"), text)


def load(job, path, middle):
    """Load the blank (one undo step); the engine's Loaded, or None after
    an error was said. A model sticking out of the blank is said too."""
    doc = job.Document
    doc.openTransaction(tr("Custom stock"))
    try:
        loaded = engine.load(job, path, middle)
    except ProjectError as exc:
        doc.abortTransaction()
        _warn(str(exc))
        return None
    doc.commitTransaction()
    from avangardecam import handlers

    handlers._select("stock", job.Stock.Name)  # a new stock object: its details shown
    if loaded.out:
        _warn(out_text(loaded.out))
    return loaded


def ask(job, path=None, middle=None):
    """CAM > Custom stock: the window (path given: none, for tests), then
    the blank loaded; True when it was."""
    if path is None:
        dialog = CustomStockDialog(job)
        if not dialog.exec():
            return False
        path, middle = dialog.path(), dialog.middle.isChecked()
    if middle is None:
        middle = last_middle()
    return load(job, path, middle) is not None


def centre(job):
    """Details: the blank moved with its middle on the model's middle (one undo step)."""
    doc = job.Document
    doc.openTransaction(tr("Stock in the middle"))
    try:
        engine.centre(job)
    except ProjectError as exc:
        doc.abortTransaction()
        _warn(str(exc))
        return False
    doc.commitTransaction()
    out = engine.sticking_out(job)
    if out:
        _warn(out_text(out))
    return True


def middle_text(job):
    """Details: where the blank's middle is."""
    from avangardecam.ui import details

    try:
        if engine.is_on_middle(job):
            return tr("on the model's middle")
        dx, dy, dz = engine.off_middle(job)
    except ProjectError:
        return details.NONE
    return tr("X {:+.2f}  Y {:+.2f}  Z {:+.2f} mm off the model's").format(*(round(-d, 2) + 0.0 for d in (dx, dy, dz)))  # no "-0.00"


# -- moving it by hand (a right click on the stock) ---------------------------------


class MoveStockDialog(QtWidgets.QDialog):
    """How far to move the blank along the setup's X, Y and Z; shift() after exec()."""

    LIMIT_MM = 10000.0

    def __init__(self, job, parent=None):
        from avangardecam.ui import details

        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamMoveStockDialog")
        self.setWindowTitle(tr("Move stock"))
        box = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        box.addLayout(form)
        form.addRow(tr("Setup") + ":", QtWidgets.QLabel(job.Label))
        form.addRow(tr("Middle") + ":", QtWidgets.QLabel(middle_text(job)))
        self.fields = []
        for axis in "XYZ":
            field = details.length_box(0.0, -self.LIMIT_MM, self.LIMIT_MM)
            field.setObjectName("AvangardeCamMoveStock" + axis)
            field.setToolTip(tr("How far the blank moves along the setup's {} axis; minus: the other way").format(axis))
            form.addRow(tr("Move {}").format(axis) + ":", field)
            self.fields.append(field)
        note = QtWidgets.QLabel(tr("Along the axes of the setup's zero point, as the view shows them. The blank keeps where it is moved when the zero point moves."))  # fmt: skip
        note.setWordWrap(True)
        box.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(tr("Move"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self.setMinimumWidth(420)
        window_fit.fit_contents(self)
        self.fields[0].setFocus()
        self.fields[0].selectAll()

    def shift(self):
        return tuple(float(f.property("rawValue")) for f in self.fields)


def move(job, shift=None):
    """Move the blank along the setup's axes (the window unless shift is
    given, for tests); one undo step. True when it moved."""
    if shift is None:
        dialog = MoveStockDialog(job)
        if not dialog.exec():
            return False
        shift = dialog.shift()
    if not any(abs(d) > 1e-9 for d in shift):
        return False
    doc = job.Document
    doc.openTransaction(tr("Move stock"))
    try:
        engine.move(job, shift)
    except ProjectError as exc:
        doc.abortTransaction()
        _warn(str(exc))
        return False
    doc.commitTransaction()
    out = engine.sticking_out(job)
    if out:
        _warn(out_text(out))
    return True


def stock_menu(job, panel=None):
    """The menu of a right click on a setup's stock in the list: a custom
    stock moved along the axes or put in the middle; another stock from a
    file; the Stock window."""
    from avangardecam.engine import next_setup

    result = QtWidgets.QMenu(panel)
    result.setObjectName("AvangardeCamStockMenu")
    result.setToolTipsVisible(True)
    custom = next_setup.kind(job) == next_setup.CUSTOM
    if custom:
        action = result.addAction(tr("Move stock..."))
        action.setObjectName("AvangardeCamMoveStock")
        action.setToolTip(tr("Move the blank along X, Y and Z of the setup"))
        action.triggered.connect(lambda: move(job))
        action = result.addAction(tr("Put in the middle"))
        action.setObjectName("AvangardeCamStockMenuMiddle")
        action.setToolTip(tr("The middle of the blank's box on the middle of the model's box"))
        action.triggered.connect(lambda: centre(job))
        result.addSeparator()
    action = result.addAction(tr("Custom stock..."))
    action.setObjectName("AvangardeCamStockMenuCustom")
    action.setToolTip(tr("A model of the blank from a file (a casting, a sawn block)"))
    action.triggered.connect(lambda: ask(job))
    action = result.addAction(tr("Stock..."))
    action.setObjectName("AvangardeCamStockMenuWindow")
    action.setToolTip(tr("The Stock window: a box with allowances"))
    action.triggered.connect(lambda: _stock_window(job))
    return result


def _stock_window(job):
    from avangardecam.ui import stock_dialog

    stock_dialog.ask(job)
