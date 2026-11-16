# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Zero points of operations in the interface (experimental), on their
own; engine.op_zero does the work.

- CAM > Set 0-Point as default and CAM > Reset 0-Point,
- "Make 0-Point active" in an operation's menu: the setup's zero point
  goes to the one the operation counts from,
- an operation that counts from another zero point than the active one
  is marked in the list and shows where it counts from instead of its
  values; editing it makes its zero point the active one first,
- the stock's block drawn as it lies where it is no box on the active
  zero point's axes (show_block; ui.scene calls it).
"""

import FreeCAD
import FreeCADGui

from avangardecam import tr
from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import op_zero as engine
from avangardecam.model import op_zero as model
from avangardecam.ui import details

STATUS_TIMEOUT_MS = 4000
_BLOCK_NAME = "AvangardeCamStockBlock"
BLOCK_TRANSPARENCY = 0.85  # as the stock's box (engine.freecad_cam._show_stock)


def _status(message):
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)


def _error(message):
    from PySide import QtWidgets

    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", message)


def parked(op):
    return engine.parked(op)


def zero_text(zero):
    """ "X+20 Y+0 Z-2" of a zero point as the default one sees it, with its
    turn when it is turned; "the default 0-Point" for the default itself."""
    if zero is None:
        return tr("the default 0-Point")
    if model.is_shift(zero):
        return model.shift_text(zero)
    return "{}, {}".format(model.shift_text(zero), model.turn_text(zero))


def _job():
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    job = scene.active_setup(doc) if doc is not None else None
    if job is None:
        _status(tr("The project has no setup yet (CAM > Snap-0-Point)."))
    return job


def _moved(job, select=None):
    """The view and the list follow the zero point."""
    from avangardecam.ui import move_zero, scene
    from avangardecam.ui.layout import LAYOUT

    move_zero.close_dialog()  # its preview stood on the zero point before
    scene.set_active_setup(job)
    scene.apply(job.Document)
    if LAYOUT.panel is not None:
        LAYOUT.panel.refresh()
        LAYOUT.panel.select_entry(*(select or ("setup", job.Name)))


def _change(job, title, change):
    """change() as one undo step; False when it was refused."""
    doc = job.Document
    doc.openTransaction(title)
    try:
        changed = change()
    except (ProjectError, ValueError) as exc:
        doc.abortTransaction()
        _error(tr(str(exc)))
        return None
    if changed:
        doc.commitTransaction()
    else:
        doc.abortTransaction()
    return changed


def set_default():
    """CAM > Set 0-Point as default."""
    job = _job()
    if job is None:
        return False
    if engine.at_default(job):
        _status(tr("{}: the zero point is its default one already.").format(job.Label))
        return False
    if not _change(job, tr("Set 0-Point as default"), lambda: engine.set_default(job)):
        return False
    _moved(job)
    _status(tr("{}: this zero point is the default one now.").format(job.Label))
    return True


def reset():
    """CAM > Reset 0-Point."""
    job = _job()
    if job is None:
        return False
    if engine.at_default(job):
        _status(tr("{}: the zero point is on its default one.").format(job.Label))
        return False
    if not _change(job, tr("Reset 0-Point"), lambda: engine.reset(job)):
        return False
    _moved(job)
    _status(tr("{}: zero point back on its default one.").format(job.Label))
    return True


def make_active(op):
    """The setup's zero point goes to the one the operation counts from."""
    job = cam.setup_of(op)
    if job is None:
        return False
    if not engine.parked(op):
        _status(tr("{} counts from the active zero point already.").format(op.Label))
        return False
    zero = engine.operation_zero(op)
    if not _change(job, tr("Make 0-Point active"), lambda: engine.activate_operation(op)):
        return False
    _moved(job, ("operation", op.Name))
    _status(tr("{}: zero point of {} is the active one ({}).").format(job.Label, op.Label, zero_text(zero)))
    return True


def ready(op):
    """Before an operation is changed: its zero point is the active one
    (made so if it was not). False when that was refused."""
    if not engine.parked(op):
        return True
    return bool(make_active(op))


def add_to_menu(menu, op):
    """Make 0-Point active in the menu of an operation."""
    action = menu.addAction(tr("Make 0-Point active"))
    action.setObjectName("AvangardeCamMakeZeroActive")
    waits = engine.parked(op)
    action.setEnabled(waits)
    action.setToolTip(
        tr("Put the zero point where this operation counts from, to change it or add operations there")
        if waits
        else tr("It counts from the active zero point already")
    )
    action.triggered.connect(lambda: make_active(op))
    return action


class ParkedView(details.DetailsView):
    """An operation that counts from another zero point than the active
    one: where from, and the way to change it."""

    def __init__(self, op, parent=None):
        super().__init__(op.Label, parent=parent)
        self.op = op
        zero = engine.operation_zero(op)
        self.zero_label = self.add_row(tr("Counts from"), zero_text(zero))
        self.part_label = self.add_row(tr("Zero point"), details.point_text(engine.zero_of(op).Base))
        self.note.setText(
            tr("This operation counts from another zero point than the active one and keeps it. Make its zero point active to see and change its values, or to add operations there.")  # fmt: skip
        )
        self.add_button(tr("Make 0-Point active"), lambda: make_active(self.op), "AvangardeCamMakeZeroActiveButton")


# -- the stock's block at an odd angle -------------------------------------------------


def show_block(job, on):
    """Where the stock's block is no box on the active zero point's axes
    (the zero point turned at an odd angle to the stock's own), FreeCAD's
    stock is the larger box around it: draw the block as it lies instead
    (in the setup's node, which ui.scene draws on the zero point)."""
    vo = getattr(job, "ViewObject", None)
    if vo is None:
        return
    root = vo.RootNode
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == _BLOCK_NAME:
            root.removeChild(i)
    seen = engine.block_seen(job) if on else None
    if seen is None:
        return
    from pivy import coin

    bounds, place = seen
    stock_vo = getattr(job.Stock, "ViewObject", None)
    color = tuple(stock_vo.ShapeColor[:3]) if stock_vo is not None and hasattr(stock_vo, "ShapeColor") else (0.8, 0.8, 0.8)
    if stock_vo is not None and stock_vo.Visibility:
        stock_vo.Visibility = False
    node = coin.SoSeparator()
    node.setName(_BLOCK_NAME)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    node.addChild(pick)
    move = coin.SoTransform()
    move.translation.setValue(place.Base.x, place.Base.y, place.Base.z)
    move.rotation.setValue(*place.Rotation.Q)
    node.addChild(move)
    centre = coin.SoTranslation()
    centre.translation.setValue(
        (bounds.x_min + bounds.x_max) / 2.0, (bounds.y_min + bounds.y_max) / 2.0, (bounds.z_min + bounds.z_max) / 2.0
    )
    node.addChild(centre)
    cube = coin.SoCube()
    cube.width, cube.height, cube.depth = bounds.size
    edges = coin.SoSeparator()
    style = coin.SoDrawStyle()
    style.style = coin.SoDrawStyle.LINES
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    black = coin.SoBaseColor()
    black.rgb.setValue(0.0, 0.0, 0.0)
    for child in (style, light, black, cube):
        edges.addChild(child)
    node.addChild(edges)
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*color)
    material.transparency.setValue(BLOCK_TRANSPARENCY)
    node.addChild(material)
    node.addChild(cube)
    root.addChild(node)
