# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""CAM > Move 0-Point, on its own (engine.move_zero moves the zero point).

A window that does not block the 3D view: the shift of the active setup's
zero point along its own X, Y and Z is typed, or taken from a wall of the
part: Select wall, then a click on a flat face, puts the face's plane
through the zero point (the shift the shortest way to it; another wall
after it adds to the first, so two or three walls give a corner). A face
selected before the window opens is taken at once, as Snap-0-Point does.

With "5 axes" ticked (shown only when edition.FIVE_AXES) the zero point also turns: by angles typed about
its own X, Y and Z (in this order, about the axes as they stand before
the turn), and Select wall turns its Z out of the wall, square to it
("Z out of the wall"), so that the tool stands on that wall.

While the window is open the view shows where the zero point would be:
a cross of the three axes (X red, Y green, Z blue) and a yellow line to it
from the present zero point. OK moves the zero point in one undo step.
The operations made so far keep the zero points they count from
(engine.op_zero); new ones count from where the zero point is left.
"""

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

from avangardecam import edition, tr
from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import move_zero as engine
from avangardecam.model import move_zero as model
from avangardecam.model import op_zero as model_zero
from avangardecam.ui import details

STATUS_TIMEOUT_MS = 4000
# the selection is read this long after a click: after FreeCAD's own
# notification and after picking.py has moved a click to a sketch line
_READ_MS = 50
_PREVIEW_NAME = "AvangardeCamMoveZeroPreview"
_AXIS_COLORS = ((1.0, 0.0, 0.0), (0.0, 0.7, 0.0), (0.0, 0.3, 1.0))
_LINK_COLOR = (1.0, 1.0, 0.0)
# the cross's arms, as a share of the stock's largest size
_ARM_SHARE = 0.15
_ARM_MIN_MM = 5.0
# the window opens this far inside the 3D view's top left corner
_MARGIN_PX = 24

_dialog = None


def _status(message):
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)


def selected_face():
    """(model, "FaceN") of the one face selected in 3D, else None."""
    faces = []
    for selection in FreeCADGui.Selection.getSelectionEx("", 0):
        for sub in selection.SubElementNames:
            if sub.split(".")[-1].startswith("Face"):
                faces.append(cam.model_element(selection.Object, sub))
    if len(faces) != 1:
        return None
    return faces[0]  # a face of a job's clone is the same face of the original


def turn_text(turn):
    """ "X+0 Y+90 Z+0": the angles about the zero point's axes."""
    return " ".join("{}{:+g}".format(axis, round(value, 3) + 0.0) for axis, value in zip("XYZ", turn))


def shift_text(shift):
    """"X+476.5 Y+0 Z-1.75" as a datum shift reads in a program."""
    return " ".join("{}{:+.3f}".format(axis, value + 0.0).rstrip("0").rstrip(".") for axis, value in zip("XYZ", shift))


# -- the preview in 3D -----------------------------------------------------------


def _lines(points, color, width):
    from pivy import coin

    group = coin.SoSeparator()
    rgb = coin.SoBaseColor()
    rgb.rgb.setValue(*color)
    group.addChild(rgb)
    draw = coin.SoDrawStyle()
    draw.lineWidth = width
    group.addChild(draw)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, points)
    group.addChild(coords)
    lines = coin.SoLineSet()
    lines.numVertices.setValues(0, [2] * (len(points) // 2))
    group.addChild(lines)
    return group


def _preview_node(shift, arm, turn=model_zero.NO_TURN):
    """The cross of the zero point after the shift and the turn, and the
    way to it, in the setup's coordinates; seen through the part, not
    pickable."""
    from pivy import coin

    group = coin.SoSeparator()
    group.setName(_PREVIEW_NAME)
    style = coin.SoPickStyle()
    style.style = coin.SoPickStyle.UNPICKABLE
    group.addChild(style)
    depth = coin.SoDepthBuffer()
    depth.test = False
    group.addChild(depth)
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    group.addChild(light)
    at = tuple(shift)
    group.addChild(_lines([(0.0, 0.0, 0.0), at], _LINK_COLOR, 2.0))
    for axis, color in zip(model_zero.axes_of(turn), _AXIS_COLORS):
        end = tuple(c + arm * d for c, d in zip(at, axis))
        group.addChild(_lines([at, end], color, 4.0))
    return group


def _job_root(job):
    """The Job's own node of the 3D scene: ui.scene draws it at the zero point."""
    try:
        view = job.ViewObject
    except (ReferenceError, RuntimeError, AttributeError):
        return None
    return view.RootNode if view is not None else None


def clear_preview(job):
    root = _job_root(job)
    if root is None:
        return
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == _PREVIEW_NAME:
            root.removeChild(i)


def show_preview(job, shift, turn=model_zero.NO_TURN):
    """Draw where the zero point would be (nothing when it stays as it is)."""
    clear_preview(job)
    root = _job_root(job)
    if root is None or (model.is_none(shift) and model_zero.no_turn(turn)):
        return
    arm = max(_ARM_MIN_MM, _ARM_SHARE * max(cam.stock_bounds(job).size))
    root.addChild(_preview_node(shift, arm, turn))


def preview_shown(job):
    root = _job_root(job)
    return root is not None and any(
        root.getChild(i).getName() == _PREVIEW_NAME for i in range(root.getNumChildren())
    )


# -- the window ------------------------------------------------------------------


class _Selection:
    """FreeCAD's selection observer: tells the dialog that a click selected something."""

    def __init__(self, dialog):
        self.dialog = dialog

    def addSelection(self, doc_name, obj_name, sub, pnt):
        self.dialog.selection_changed()

    def setSelection(self, doc_name):
        self.dialog.selection_changed()


class MoveZeroDialog(QtWidgets.QDialog):
    """The shift of a setup's zero point, typed or from a wall; with 5
    axes its turn as well."""

    def __init__(self, job, parent=None):
        super().__init__(parent or FreeCADGui.getMainWindow())
        self.setObjectName("AvangardeCamMoveZero")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setWindowTitle(tr("Move 0-Point"))
        self.job = job
        self._filling = False
        layout = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QLabel("<b>{}</b>".format(tr("Zero point of {}").format(job.Label)))
        layout.addWidget(head)

        self.wall_button = QtWidgets.QPushButton(tr("Select wall"))
        self.wall_button.setObjectName("AvangardeCamMoveZeroWall")
        self.wall_button.setCheckable(True)
        self.wall_button.setAutoDefault(False)
        self.wall_button.setToolTip(
            tr("Click it, then a flat face of the model: the zero point moves the shortest way onto the face's plane")
        )
        self.wall_button.toggled.connect(self._wall_toggled)
        self.wall_label = QtWidgets.QLabel()
        self.wall_label.setObjectName("AvangardeCamMoveZeroWallText")
        self.wall_label.setWordWrap(True)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.wall_button)
        row.addWidget(self.wall_label, 1)
        layout.addLayout(row)

        form = QtWidgets.QFormLayout()
        self.boxes = []
        for axis in "XYZ":
            box = details.length_box(0.0, -model.MAX_SHIFT_MM, model.MAX_SHIFT_MM)
            box.setObjectName("AvangardeCamMoveZero" + axis)
            box.setToolTip(tr("How far the zero point moves along the setup's {} (negative: the other way)").format(axis))
            box.valueChanged.connect(self._typed)
            form.addRow(tr("Move {}").format(axis) + ":", box)
            self.boxes.append(box)
        layout.addLayout(form)

        self.five_axes = QtWidgets.QCheckBox(tr("5 axes"))
        self.five_axes.setObjectName("AvangardeCamMoveZero5X")
        self.five_axes.setToolTip(
            tr("Turn the zero point as well: for a machine that tilts its head or table (its own postprocessor)")
        )
        layout.addWidget(self.five_axes)
        self.five_axes.setVisible(edition.FIVE_AXES)  # unticked when hidden: no turn
        self.turn_group = QtWidgets.QWidget()
        self.turn_group.setObjectName("AvangardeCamMoveZeroTurn")
        turn_layout = QtWidgets.QVBoxLayout(self.turn_group)
        turn_layout.setContentsMargins(0, 0, 0, 0)
        self.z_out = QtWidgets.QCheckBox(tr("Z out of the wall"))
        self.z_out.setObjectName("AvangardeCamMoveZeroZOut")
        self.z_out.setChecked(True)
        self.z_out.setToolTip(
            tr("Select wall also turns the zero point's Z out of the wall, square to it: the tool stands on that wall")
        )
        turn_layout.addWidget(self.z_out)
        turn_form = QtWidgets.QFormLayout()
        self.turn_boxes = []
        for axis in "XYZ":
            box = QtWidgets.QDoubleSpinBox()
            box.setObjectName("AvangardeCamMoveZeroTurn" + axis)
            box.setRange(-model_zero.MAX_TURN_DEG, model_zero.MAX_TURN_DEG)
            box.setDecimals(3)
            box.setSuffix(" °")
            box.setKeyboardTracking(False)
            box.setToolTip(
                tr("Angle the zero point turns about its own {} (positive: counter-clockwise seen against the axis); X first, then Y, then Z, about the axes as they stand before the turn").format(axis)  # fmt: skip
            )
            box.valueChanged.connect(self._typed)
            turn_form.addRow(tr("Turn about {}").format(axis) + ":", box)
            self.turn_boxes.append(box)
        turn_layout.addLayout(turn_form)
        layout.addWidget(self.turn_group)
        self.turn_group.setVisible(False)
        self.five_axes.toggled.connect(self._five_axes_toggled)

        note = QtWidgets.QLabel(
            tr("The operations made so far keep the zero point they count from. New operations count from where the zero point is left; the NC program gives it from the default zero point of {}.").format(job.Label)  # fmt: skip
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._observer = _Selection(self)
        FreeCADGui.Selection.addObserver(self._observer)
        picked = selected_face()
        if picked is not None:  # selected first, as for Snap-0-Point
            self._use_wall(picked)

    # -- values ------------------------------------------------------------------

    def shift(self):
        return tuple(float(box.property("rawValue")) for box in self.boxes)

    def set_shift(self, shift):
        self._filling = True
        try:
            for box, value in zip(self.boxes, shift):
                box.setProperty("rawValue", float(value))
        finally:
            self._filling = False
        self._preview()

    def turn(self):
        """The angles about X, Y and Z; none without 5 axes."""
        if not self.five_axes.isChecked():
            return model_zero.NO_TURN
        return tuple(float(box.value()) for box in self.turn_boxes)

    def set_turn(self, turn):
        self._filling = True
        try:
            for box, value in zip(self.turn_boxes, turn):
                box.setValue(float(value))
        finally:
            self._filling = False
        self._preview()

    def _five_axes_toggled(self, on):
        self.turn_group.setVisible(on)
        self.adjustSize()
        self._preview()

    def _typed(self, *_args):
        if not self._filling:
            self._preview()

    def _preview(self):
        try:
            show_preview(self.job, self.shift(), self.turn())
        except (ReferenceError, RuntimeError, ValueError):
            pass  # the setup is gone or a value is out of range: OK says so

    # -- the wall ----------------------------------------------------------------

    def _wall_toggled(self, on):
        if not on:
            return
        picked = selected_face()
        if picked is not None:
            self._use_wall(picked)
        else:
            self.wall_label.setText(tr("Click a flat face of the model."))

    def selection_changed(self):
        """A click selected something: read it once FreeCAD is done with it."""
        if self.wall_button.isChecked():
            QtCore.QTimer.singleShot(_READ_MS, self._read_selection)

    def _read_selection(self):
        if not self.wall_button.isChecked():
            return
        picked = selected_face()
        if picked is not None:
            self._use_wall(picked)

    def _use_wall(self, picked):
        """Put the wall's plane through the zero point and, with 5 axes and
        "Z out of the wall", turn its Z out of the wall; a face that is not
        flat is refused and the button waits for another."""
        obj, sub = picked
        turn = None
        try:
            shift = engine.wall_shift(self.job, obj, sub, self.shift())
            if self.five_axes.isChecked() and self.z_out.isChecked():
                turn = engine.wall_turn(self.job, obj, sub)
        except (ProjectError, ValueError) as exc:
            self.wall_label.setText(tr(str(exc)))
            return False
        if turn is not None:
            self.set_turn(turn)
        self.set_shift(shift)
        self.wall_label.setText(tr("{} of {}").format(sub, obj.Label))
        self.wall_button.setChecked(False)
        FreeCADGui.Selection.clearSelection()
        return True

    # -- closing -----------------------------------------------------------------

    def accept(self):
        """Move the zero point (one undo step); a refused shift keeps the window open."""
        from avangardecam.ui import scene
        from avangardecam.ui.layout import LAYOUT

        job = self.job
        try:
            doc = job.Document
            gone = job not in cam.setups(doc)
        except (ReferenceError, RuntimeError):
            gone = True
        if gone:
            QtWidgets.QMessageBox.warning(self, "AvangardeCam", tr("The setup is not in the project any more."))
            super().reject()
            return
        shift, turn = self.shift(), self.turn()
        if model.is_none(shift) and model_zero.no_turn(turn):
            super().accept()
            return
        clear_preview(job)
        doc.openTransaction(tr("Move 0-Point"))
        try:
            engine.move(job, shift, turn)
        except (ValueError, ProjectError) as exc:
            doc.abortTransaction()
            self._preview()
            QtWidgets.QMessageBox.warning(self, "AvangardeCam", tr(str(exc)))
            return
        doc.commitTransaction()
        scene.set_active_setup(job)
        scene.apply(doc)
        if LAYOUT.panel is not None:
            LAYOUT.panel.select_entry("setup", job.Name)
        if model_zero.no_turn(turn):
            _status(tr("{}: zero point moved {}").format(job.Label, shift_text(shift)))
        else:
            _status(
                tr("{}: zero point moved {}, turned {}").format(job.Label, shift_text(shift), turn_text(turn))
            )
        super().accept()

    def done(self, result):
        global _dialog
        if self._observer is not None:
            FreeCADGui.Selection.removeObserver(self._observer)
            self._observer = None
        clear_preview(self.job)
        if _dialog is self:
            _dialog = None
        super().done(result)


def _place(dialog):
    """In the top left corner of the 3D view: the part in the middle stays in sight."""
    area = FreeCADGui.getMainWindow().centralWidget()
    if area is not None:
        dialog.move(area.mapToGlobal(QtCore.QPoint(_MARGIN_PX, _MARGIN_PX)))


def close_dialog():
    """Close the window (the zero point it showed is another one now)."""
    if _dialog is not None:
        try:
            _dialog.reject()
        except RuntimeError:
            pass  # Qt has deleted it already


def open_dialog(job):
    """The window for a setup; one at a time."""
    global _dialog
    if _dialog is not None:
        try:
            _dialog.reject()
        except RuntimeError:
            pass  # Qt has deleted it already (its document's windows closed)
    _dialog = MoveZeroDialog(job)
    _place(_dialog)
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def run():
    """CAM > Move 0-Point: the window for the active setup (the first setup
    is made if there is none yet)."""
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    if doc is None or not cam.models(doc):
        _status(tr("Import a model first (File > Import model)."))
        return None
    job = scene.active_setup(doc)
    if job is None:
        doc.openTransaction(tr("Create setup"))
        try:
            job = cam.ensure_job(doc)
        except ProjectError as exc:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", str(exc))
            return None
        doc.commitTransaction()
        scene.set_active_setup(job)
    return open_dialog(job)
