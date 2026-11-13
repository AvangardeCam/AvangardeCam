# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""CAM > Next setup (user, 2026-10-30): a new setup, the part clamped
again, and the stock it starts from, chosen in a window:

- Stock from Setup N (at first): what that setup's program leaves, cut as
  Verify cuts it at the accuracy chosen (Rough, Medium, Fine) in a thread
  of its own, with a busy window (engine.next_setup.left);
- Standard stock: the model's box with allowances, as every new setup;
- Custom stock: a model of the blank from a file (a casting, STEP or STL)
  lying in the part's coordinates.

The new setup's zero point is on the flat face selected when Next setup
is clicked (as Snap-0-Point puts it); without one it is that of the last
setup, to be put on the new clamping's face with Snap-0-Point (the stock
follows). The setup and its stock are one undo step.

Also here: what the details of such a stock show (describe: Work it out
again), and the stock left drawn instead of its box (show_stock).
"""

import threading

import FreeCADGui

from PySide import QtCore, QtWidgets

from avangardecam import params, tr
from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.engine import next_setup as engine
from avangardecam.ui import verify as ui_verify

_LAST_ACCURACY = "LastNextSetupAccuracy"
_LAST_DIR = "LastBlankDir"
_POLL_MS = 100
FROM_SETUP, STANDARD, CUSTOM = "setup", "standard", "custom"


def last_accuracy():
    value = params().GetInt(_LAST_ACCURACY, ui_verify.DEFAULT_RESOLUTION)
    cells = [r for _name, r in ui_verify.RESOLUTIONS]
    return value if value in cells else ui_verify.DEFAULT_RESOLUTION


class NextSetupDialog(QtWidgets.QDialog):
    """The stock of the next setup; choice() after exec()."""

    def __init__(self, doc, face_picked, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamNextSetupDialog")
        self.setWindowTitle(tr("Next setup"))
        jobs = cam.setups(doc)
        box = QtWidgets.QVBoxLayout(self)
        box.addWidget(QtWidgets.QLabel(tr("Setup {}: the part clamped again. It starts from:").format(len(jobs) + 1)))

        self.group = QtWidgets.QButtonGroup(self)
        self.from_setup = QtWidgets.QRadioButton(tr("Stock from"))
        self.from_setup.setObjectName("AvangardeCamNextSetupFromSetup")
        self.setups = QtWidgets.QComboBox()
        self.setups.setObjectName("AvangardeCamNextSetupSetups")
        for job in jobs:
            self.setups.addItem(job.Label, job.Name)
        self.setups.setCurrentIndex(len(jobs) - 1)
        self.setups.setToolTip(tr("The setup whose program leaves the stock"))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.from_setup)
        row.addWidget(self.setups, 1)
        box.addLayout(row)
        self.accuracy = QtWidgets.QComboBox()
        self.accuracy.setObjectName("AvangardeCamNextSetupAccuracy")
        for name, cells in ui_verify.RESOLUTIONS:
            self.accuracy.addItem("{} ({} {})".format(tr(name), cells, tr("cells")), cells)
        self.accuracy.setCurrentIndex([r for _n, r in ui_verify.RESOLUTIONS].index(last_accuracy()))
        self.accuracy.setToolTip(tr("Cells on the longest edge of the stock, as Verify's: finer takes longer"))
        row = QtWidgets.QHBoxLayout()
        row.addSpacing(24)
        row.addWidget(QtWidgets.QLabel(tr("what its program leaves, worked out at")))
        row.addWidget(self.accuracy, 1)
        box.addLayout(row)

        self.standard = QtWidgets.QRadioButton(tr("Standard stock: the model's box with allowances"))
        self.standard.setObjectName("AvangardeCamNextSetupStandard")
        box.addWidget(self.standard)

        self.custom = QtWidgets.QRadioButton(tr("Custom stock: a model of the blank (a casting)"))
        self.custom.setObjectName("AvangardeCamNextSetupCustom")
        box.addWidget(self.custom)
        row = QtWidgets.QHBoxLayout()
        row.addSpacing(24)
        self.file = QtWidgets.QLineEdit()
        self.file.setObjectName("AvangardeCamNextSetupFile")
        self.file.setPlaceholderText(tr("STEP, IGES, BREP or STL file"))
        row.addWidget(self.file, 1)
        browse = QtWidgets.QPushButton(tr("Browse..."))
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        box.addLayout(row)
        note = QtWidgets.QLabel(tr("The blank must lie where the part lies in the project, as the foundry draws it over the part."))
        note.setWordWrap(True)
        note.setIndent(24)
        box.addWidget(note)

        for k, button in enumerate((self.from_setup, self.standard, self.custom)):
            self.group.addButton(button, k)
        if jobs:
            self.from_setup.setChecked(True)  # user: the stock the setup before leaves, at first
        else:
            self.from_setup.setEnabled(False)
            self.setups.setEnabled(False)
            self.standard.setChecked(True)
        self.group.buttonToggled.connect(lambda *_a: self._enable())
        self.file.textEdited.connect(lambda _t: self.custom.setChecked(True))

        zero = QtWidgets.QLabel(
            tr("Zero point: on the selected face, as Snap-0-Point puts it.") if face_picked else
            tr("Zero point: as in {} for now. Click the face of the new clamping and Snap-0-Point: the stock follows.").format(jobs[-1].Label)
            if jobs else tr("Zero point: on top of the model, in the middle.")
        )  # fmt: skip
        zero.setObjectName("AvangardeCamNextSetupZero")
        zero.setWordWrap(True)
        box.addWidget(zero)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(tr("Make setup"))
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)
        self._enable()

    def _enable(self):
        self.accuracy.setEnabled(self.from_setup.isChecked())

    def _browse(self):
        start = params().GetString(_LAST_DIR, "")
        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self, tr("Model of the blank"), start,
            tr("Models") + " (*.step *.stp *.STEP *.STP *.iges *.igs *.brep *.brp *.stl *.STL *.obj *.ply)",
        )  # fmt: skip
        if path:
            import os

            params().SetString(_LAST_DIR, os.path.dirname(path))
            self.file.setText(path)
            self.custom.setChecked(True)

    def _accept(self):
        if self.custom.isChecked() and not self.file.text().strip():
            QtWidgets.QMessageBox.warning(self, tr("Next setup"), tr("Choose the file of the blank first."))
            return
        if self.from_setup.isChecked():
            params().SetInt(_LAST_ACCURACY, self.accuracy.currentData())
        self.accept()

    def choice(self):
        """(FROM_SETUP, setup Name, cells) / (STANDARD,) / (CUSTOM, path)."""
        if self.from_setup.isChecked():
            return FROM_SETUP, self.setups.currentData(), self.accuracy.currentData()
        if self.custom.isChecked():
            return CUSTOM, self.file.text().strip()
        return (STANDARD,)


def busy(title, work):
    """Run work(progress) in a thread of its own, a busy window up meanwhile;
    its result, or the exception it raised raised here."""
    state = {"step": ""}

    def run():
        try:
            state["result"] = work(lambda text: state.update(step=text))
        except Exception as exc:  # raised again in FreeCAD's thread
            state["error"] = exc
        state["done"] = True

    dialog = QtWidgets.QProgressDialog(FreeCADGui.getMainWindow())
    dialog.setObjectName("AvangardeCamBusy")
    dialog.setWindowTitle(title)
    dialog.setRange(0, 0)
    dialog.setCancelButton(None)
    dialog.setMinimumDuration(0)
    dialog.setWindowModality(QtCore.Qt.ApplicationModal)
    dialog.setLabelText(title)
    dialog.show()
    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer()
    timer.setInterval(_POLL_MS)

    def poll():
        dialog.setLabelText(tr(state["step"]) if state["step"] else title)
        if "done" in state:
            timer.stop()
            loop.quit()

    timer.timeout.connect(poll)
    threading.Thread(target=run, daemon=True).start()
    timer.start()
    loop.exec()
    dialog.close()
    dialog.deleteLater()
    if "error" in state:
        raise state["error"]
    return state["result"]


def work_out_left(previous, cells):
    """What previous's program leaves (a mesh in the part's coordinates),
    worked out with a busy window; ProjectError as engine.next_setup's."""
    doc = previous.Document
    doc.recompute()
    prepared = engine.prepare_left(previous)
    return busy(tr("Stock left by {}").format(previous.Label), lambda progress: engine.left(prepared, cells, progress))


def _error(message):
    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", message)


def run(doc, models, picked=None, choice=None):
    """CAM > Next setup: ask (choice given: no window, for tests), make the
    setup and its stock; the new setup, or None (cancelled, failed)."""
    if choice is None:
        dialog = NextSetupDialog(doc, picked is not None)
        if not dialog.exec():
            return None
        choice = dialog.choice()
    jobs = cam.setups(doc)
    try:
        if picked is not None:
            place = geometry.zero_on_face(models, *picked)
        elif jobs:
            place = cam.zero(jobs[-1])
        else:
            place = geometry.zero_on_top(models)
        mesh = previous = None
        if choice[0] == FROM_SETUP:
            previous = next(j for j in jobs if j.Name == choice[1])
            mesh = work_out_left(previous, choice[2])
    except ProjectError as exc:
        _error(str(exc))
        return None
    doc.openTransaction(tr("Next setup"))
    try:
        job = cam.new_setup(doc, place)
        if choice[0] == FROM_SETUP:
            engine.set_stock_from_setup(job, previous, mesh, choice[2])
        elif choice[0] == CUSTOM:
            engine.set_custom_stock(job, choice[1])
    except ProjectError as exc:
        doc.abortTransaction()
        _error(str(exc))
        return None
    doc.commitTransaction()
    return job


def work_out_again(job):
    """The stock left by the setup a FROM_SETUP stock comes from, worked out
    again at the same accuracy (one undo step); True when it was."""
    previous = engine.from_setup(job)
    if previous is None:
        _error(tr("The setup this stock was worked out from is gone."))
        return False
    cells = getattr(job.Stock, engine.ACCURACY_PROPERTY, 0) or last_accuracy()
    try:
        mesh = work_out_left(previous, cells)
    except ProjectError as exc:
        _error(str(exc))
        return False
    doc = job.Document
    doc.openTransaction(tr("Stock from {}").format(previous.Label))
    try:
        engine.update_from_setup(job, mesh, cells)
    finally:
        doc.commitTransaction()
    return True


def kind_text(job):
    """How the project list names a setup's stock: Box, From Setup 1, Blank."""
    kind = engine.kind(job)
    if kind == engine.FROM_SETUP:
        previous = engine.from_setup(job)
        return tr("From {}").format(previous.Label) if previous is not None else tr("From a removed setup")
    if kind == engine.CUSTOM:
        return tr("Blank")
    return tr("Box")


def describe(view, job):
    """Fill the stock's details (ui.details.StockView) for a stock left by
    another setup or a blank's model; False for a stock of another kind."""
    kind = engine.kind(job)
    if kind not in (engine.FROM_SETUP, engine.CUSTOM):
        return False
    if kind == engine.FROM_SETUP:
        previous = engine.from_setup(job)
        view.add_row(tr("From"), previous.Label if previous is not None else tr("a removed setup"))
        view.add_row(tr("Worked out"), getattr(job.Stock, engine.MADE_PROPERTY, ""))
        view.add_row(tr("Accuracy"), "{} {}".format(getattr(job.Stock, engine.ACCURACY_PROPERTY, 0), tr("cells")))
        view.note.setText(tr("What the program of the setup before leaves. After a change in that setup, work it out again."))
        view.add_button(tr("Work it out again"), lambda: work_out_again(job), "AvangardeCamStockWorkOutAgain")
    else:
        view.add_row(tr("Blank"), getattr(job.Stock, engine.FILE_PROPERTY, ""))
        view.note.setText(tr("A model of the blank, lying where the part lies in the project."))
    view.add_button(tr("Replace by box with allowances"), view._replace)
    return True


def show_stock(job, on):
    """Draw a stock left by another setup itself (its mesh, in the part's
    coordinates as the view is) instead of its box (ui.scene.apply)."""
    if engine.kind(job) != engine.FROM_SETUP:
        return
    src = engine.source(job)
    for obj, visible in ((src, on), (job.Stock, False)):
        vo = getattr(obj, "ViewObject", None) if obj is not None else None
        if vo is not None and vo.Visibility != visible:
            vo.Visibility = visible
