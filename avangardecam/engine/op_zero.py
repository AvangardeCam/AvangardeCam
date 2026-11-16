# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Zero points of operations (experimental), on their own: model.op_zero
has the idea and the sums.

FreeCAD computes a Job on one zero point (its model clones lie where the
zero point puts them), so a setup works on one zero point at a time: the
active one. Its operations are the live ones. An operation of another
zero point is parked: it keeps the zero point it counts from
(AvangardeZero, in the part's coordinates) and its path as it was
computed there, and FreeCAD does not compute it again until its zero
point is active (the guard on Path.Op.Base.ObjectOp.execute below; a
parked operation computed on the active zero point would be another
operation). Nothing of this exists in a setup whose zero point was never
moved away: it works as it always did.

- activate() makes another zero point the active one: the live
  operations are parked, the ones of the new zero point come alive and
  are computed again (they follow the stock and their tools), the stock
  stays the same block.
- The default zero point is the machine's preset (AvangardeDefaultZero);
  set_default() and reset() are CAM > Set 0-Point as default and Reset
  0-Point.
- The stock has a zero point of its own (AvangardeStockZero): the one
  its block is a box on, the default one it was made on. The block is
  kept as that zero point sees it (AvangardeBlock); on another zero point
  FreeCAD's stock is the box around the block (the same block on axes a
  quarter turn away, a larger box at other angles). A stock typed on
  another zero point is the block on the default one, counted from where
  it was typed (stock_changed); at an odd angle its sizes are typed along
  the stock's own axes (stock_edit, set_stock).
- setup_program() is the setup for the NC program: it visits each zero
  point in turn, reads its operations there and comes back, so that
  every operation is read where it is computed.
"""

import contextlib
import itertools
import json
from dataclasses import replace
from typing import NamedTuple

import FreeCAD

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.model import op_zero as model
from avangardecam.model import stock as model_stock

_ZERO = "AvangardeZero"
_PARKED = "AvangardeParked"
_DEFAULT = "AvangardeDefaultZero"
_BLOCK = "AvangardeBlock"  # the stock's bounds on its own zero point
_BOX = "AvangardeDefaultStock"  # its allowances there
_STOCK_ZERO = "AvangardeStockZero"  # the zero point the block is a box on
_GROUP = "AvangardeCam"

_TOLERANCE = 1e-6


# -- FreeCAD leaves parked operations alone ---------------------------------------


def install():
    """Guard FreeCAD's computing of operations: a parked one keeps its path."""
    import Path.Op.Base as PathOp

    current = PathOp.ObjectOp.execute
    if getattr(current, "avangardecam_guard", False):
        return

    def execute(self, obj):
        if getattr(obj, _PARKED, False):
            return None
        return current(self, obj)

    execute.avangardecam_guard = True
    execute.__doc__ = current.__doc__
    PathOp.ObjectOp.execute = execute


def _guarded(op):
    """FreeCAD keeps the methods of an object's proxy from when it got it:
    an operation made or loaded before install() gets them again."""
    proxy = getattr(op, "Proxy", None)
    if proxy is None or getattr(proxy, "avangardecam_guarded", False):
        return
    op.Proxy = proxy
    try:
        proxy.avangardecam_guarded = True
    except AttributeError:
        pass


# -- reading ------------------------------------------------------------------------


def same(a, b):
    """Whether two zero points (placements) are one."""
    return a.isSame(b, _TOLERANCE)


def parked(op):
    """Whether an operation counts from another zero point than the active one."""
    return bool(getattr(op, _PARKED, False))


def zero_of(op):
    """The zero point an operation counts from, in the part's coordinates."""
    if parked(op):
        return getattr(op, _ZERO)
    job = cam.setup_of(op)
    return cam.zero(job) if job is not None else FreeCAD.Placement()


def default_zero(job):
    """The setup's default zero point (the machine's preset): the one it
    had when its zero point was first moved away, or the one set as
    default; else the zero point it has."""
    if hasattr(job, _DEFAULT):
        return getattr(job, _DEFAULT)
    return cam.zero(job)


def at_default(job):
    return same(cam.zero(job), default_zero(job))


def parked_operations(job):
    return [op for op in job.Operations.Group if parked(op)]


def from_default(job, place=None):
    """A zero point (None: the active one) as the default one sees it: a
    model.frame.Frame, None for the default itself."""
    place = cam.zero(job) if place is None else place
    return model.relative(geometry.frame_of(default_zero(job)), geometry.frame_of(place))


def operation_zero(op):
    """An operation's zero point as the default one sees it (None: on it)."""
    return from_default(cam.setup_of(op), zero_of(op))


def drawn_at(obj, place):
    """Where the 3D view draws an object of a setup whose zero point is
    place: a parked operation's path lies on its own zero point."""
    if not parked(obj):
        return place
    _guarded(obj)  # one of a file opened before the guard was there
    return getattr(obj, _ZERO)


# -- parking ------------------------------------------------------------------------


def _property(obj, kind, name, tip):
    if not hasattr(obj, name):
        obj.addProperty(kind, name, _GROUP, tip)
        obj.setEditorMode(name, 1)  # read-only in FreeCAD's property editor


def _park(op, zero):
    _property(op, "App::PropertyPlacement", _ZERO, "Zero point the operation counts from, in the part's coordinates")
    _property(op, "App::PropertyBool", _PARKED, "The operation waits for its zero point to be the active one")
    setattr(op, _ZERO, zero)
    setattr(op, _PARKED, True)
    _guarded(op)


def _arm(job):
    """The guard is there, also for the parked operations of an opened file."""
    install()
    for op in job.Operations.Group:
        if parked(op):
            _guarded(op)


def _unpark(op):
    setattr(op, _PARKED, False)
    op.touch()  # computed again: its tool or the stock may have changed while it waited


# -- the block of stock ---------------------------------------------------------------


def _json(job, name):
    try:
        return json.loads(getattr(job, name, "") or "null")
    except ValueError:
        return None


def stock_zero(job):
    """The stock's own zero point: the one its block is a box on. The
    default zero point, unless another one was set as default at an odd
    angle to it (the block stays the block it is)."""
    if hasattr(job, _STOCK_ZERO) and _json(job, _BLOCK):
        return getattr(job, _STOCK_ZERO)
    return default_zero(job)


def _along(place, other):
    """Whether the axes of a zero point go along another one's (quarter
    turns apart at most): a box on one is a box on the other."""
    return model.along_axes(model.relative(geometry.frame_of(other), geometry.frame_of(place)))


def _moved(bounds, place):
    """The box around bounds (x_min, ..., z_max) moved by place."""
    corners = [
        place.multVec(FreeCAD.Vector(x, y, z))
        for x, y, z in itertools.product((bounds[0], bounds[3]), (bounds[1], bounds[4]), (bounds[2], bounds[5]))
    ]
    low = [min(getattr(c, axis) for c in corners) for axis in "xyz"]
    high = [max(getattr(c, axis) for c in corners) for axis in "xyz"]
    return model_stock.Bounds(*low, *high)


def _model_bounds(job, place):
    """The box of the setup's models as the zero point place sees them."""
    import Path.Main.Stock as PathStock

    if same(place, cam.zero(job)):
        box = PathStock.shapeBoundBox(job.Model.Group)
    else:
        box = FreeCAD.BoundBox()
        inverse = place.inverse()
        for clone in job.Model.Group:
            original = cam._original(clone)
            shape = original.Shape.copy()
            shape.Placement = inverse.multiply(original.Placement)
            box.add(shape.BoundBox)
    return model_stock.Bounds(box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def _allowances(block, model_box):
    """How far a block reaches past the models' box on each side."""
    values = [
        model_box.x_min - block[0], block[3] - model_box.x_max,
        model_box.y_min - block[1], block[4] - model_box.y_max,
        model_box.z_min - block[2], block[5] - model_box.z_max,
    ]  # fmt: skip
    return [max(0.0, round(value, 6)) for value in values]


def _keep_block(job, zero, block, allowances):
    _property(job, "App::PropertyString", _BLOCK, "Stock bounds on the stock's own zero point")
    _property(job, "App::PropertyString", _BOX, "Stock allowances on the stock's own zero point")
    _property(job, "App::PropertyPlacement", _STOCK_ZERO, "Zero point of the stock: its block is a box on it")
    setattr(job, _STOCK_ZERO, zero)
    setattr(job, _BLOCK, json.dumps([float(c) for c in block]) if block is not None else "")
    setattr(job, _BOX, json.dumps([float(c) for c in allowances]) if allowances is not None else "")


def _remember_block(job):
    """The stock as the active zero point has it is the setup's block: a
    box on this zero point, its own from now on."""
    box = cam.stock(job)
    if box is None:  # another kind of stock: it is not a box around the model
        _keep_block(job, cam.zero(job), None, None)
        return
    _keep_block(
        job, cam.zero(job), cam.stock_bounds(job),
        [box.x_neg_mm, box.x_pos_mm, box.y_neg_mm, box.y_pos_mm, box.z_neg_mm, box.z_pos_mm],
    )  # fmt: skip


def _fit_stock(job, place):
    """The allowances of FreeCAD's stock on the zero point place (the
    clones are there already): the block's own on its own zero point,
    else the box around the block."""
    block, box = _json(job, _BLOCK), _json(job, _BOX)
    if cam.stock(job) is None or not block or not box or not job.Model.Group:
        return
    own = stock_zero(job)
    if same(place, own):
        allowances = box
    else:
        allowances = _allowances(_moved(block, place.inverse().multiply(own)), _model_bounds(job, place))
    stock = job.Stock
    for name, value in zip(("ExtXneg", "ExtXpos", "ExtYneg", "ExtYpos", "ExtZneg", "ExtZpos"), allowances):
        setattr(stock, name, cam._quantity(max(0.0, round(value, 6)), "mm"))


def _preset_stock(job):
    """The stock's bounds on the default zero point (the box around the
    block when its own zero point is at an odd angle to it), None when
    only going there tells."""
    if at_default(job):
        return cam.stock_bounds(job)
    block = _json(job, _BLOCK)
    if block and cam.stock(job) is not None:
        own, default = stock_zero(job), default_zero(job)
        return model_stock.Bounds(*block) if same(own, default) else _moved(block, default.inverse().multiply(own))
    return None


def stock_changed(job):
    """freecad_cam.set_stock: the stock typed on the active zero point is
    the setup's block from now on. Typed on another zero point than the
    default one, it is the block on the default one, counted from where
    it was typed; at an odd angle to it (no box there) it is a box on the
    zero point it was typed on."""
    if not hasattr(job, _BLOCK):
        return  # a setup on one zero point keeps nothing
    here, default = cam.zero(job), default_zero(job)
    if cam.stock(job) is None or same(here, default) or not _along(here, default):
        _remember_block(job)
        return
    block = _moved(cam.stock_bounds(job), default.inverse().multiply(here))
    _keep_block(job, default, block, _allowances(block, _model_bounds(job, default)))


class StockEdit(NamedTuple):
    """What the stock's windows show and take (stock_edit, set_stock)."""

    own: bool  # along the stock's own zero point: the active one is at an odd angle to it
    model: object  # model.stock.Bounds: the models' box the allowances are counted from
    box: object  # model.stock.BoxStock, None: a stock of another kind
    bounds: object  # model.stock.Bounds of the stock


def stock_edit(job):
    """The stock as it is typed: on the active zero point's axes, or, when
    those are at an odd angle to the stock's own zero point (the block is
    no box on them), on the stock's own."""
    own = stock_zero(job)
    block, box = _json(job, _BLOCK), _json(job, _BOX)
    if block and box and cam.stock(job) is not None and job.Model.Group and not _along(cam.zero(job), own):
        return StockEdit(True, _model_bounds(job, own), model_stock.BoxStock(*box), model_stock.Bounds(*block))
    from avangardecam.engine import stock_size

    return StockEdit(False, stock_size.models_bounds(job), cam.stock(job), cam.stock_bounds(job))


def set_stock(job, box):
    """Make the stock the models' box plus the allowances of box, as
    stock_edit gave them."""
    edit = stock_edit(job)
    if not edit.own:
        cam.set_stock(job, box)
        return
    box.validate()
    allowances = [box.x_neg_mm, box.x_pos_mm, box.y_neg_mm, box.y_pos_mm, box.z_neg_mm, box.z_pos_mm]
    _keep_block(job, stock_zero(job), box.bounds(edit.model), allowances)
    _fit_stock(job, cam.zero(job))
    cam._place_stock(job)
    cam._sync_operations(job)
    job.Document.recompute()


def block_seen(job):
    """The stock's block where it is no box on the active zero point's
    axes, to draw it as it lies: (its bounds on its own zero point, that
    zero point as the active one sees it: a placement); else None."""
    own = stock_zero(job)
    block = _json(job, _BLOCK)
    if not block or cam.stock(job) is None or _along(cam.zero(job), own):
        return None
    return model_stock.Bounds(*block), cam.zero(job).inverse().multiply(own)


# -- moving the active zero point ---------------------------------------------------


def activate(job, place):
    """Make place (a placement in the part's coordinates) the setup's
    active zero point. The operations stay on the zero points they count
    from: the live ones are parked, those of place come alive. Returns
    whether the zero point changed."""
    _arm(job)
    old = cam.zero(job)
    if same(old, place):
        return False
    if not hasattr(job, _DEFAULT):
        # until now the setup had one zero point: its preset
        _property(job, "App::PropertyPlacement", _DEFAULT, "Default zero point of the setup (the machine's preset)")
        setattr(job, _DEFAULT, old)
    if not hasattr(job, _BLOCK) or same(old, stock_zero(job)):
        _remember_block(job)  # the stock as its own zero point has it now
    for op in job.Operations.Group:
        if not parked(op):
            _park(op, old)
    for op in job.Operations.Group:
        if same(getattr(op, _ZERO), place):
            _unpark(op)
    cam._move_clones(job, place)
    _fit_stock(job, place)
    cam._place_stock(job)
    cam._sync_operations(job)
    job.Document.recompute()
    return True


def activate_operation(op):
    """Make the zero point an operation counts from the active one."""
    return activate(cam.setup_of(op), zero_of(op))


def set_default(job):
    """The active zero point is the setup's default from now on (the
    machine's preset; the program's datum shifts are counted from it).
    Returns whether it changed."""
    if at_default(job):
        return False
    _property(job, "App::PropertyPlacement", _DEFAULT, "Default zero point of the setup (the machine's preset)")
    setattr(job, _DEFAULT, cam.zero(job))
    if _along(cam.zero(job), stock_zero(job)):
        _remember_block(job)  # the same block, on this zero point's axes from now on
    return True


def reset(job):
    """Back to the default zero point; returns whether the zero point moved."""
    return activate(job, default_zero(job))


# -- freecad_cam.set_zero: the setup's own zero point moves -----------------------------


def before_setup_move(job):
    """Snap-0-Point and Rotate 0-Point move the setup: its default zero
    point with all that counts from it. They start from the default one."""
    if not at_default(job):
        raise cam.ProjectError(
            "The zero point of {} is not its default one. Reset 0-Point first, or move and turn this one with "
            "Move 0-Point; Set 0-Point as default makes it the default.".format(job.Label)
        )


def after_setup_move(job):
    """The default zero point went with the setup, the stock with it."""
    if hasattr(job, _DEFAULT):
        setattr(job, _DEFAULT, cam.zero(job))
    if hasattr(job, _BLOCK):
        _remember_block(job)


# -- the NC program -------------------------------------------------------------------


@contextlib.contextmanager
def _visit(job):
    """Go round the setup's zero points and leave the document as it was:
    with undo on, the visit is a transaction that is dropped."""
    doc = job.Document
    start = cam.zero(job)
    dropped = bool(doc.UndoMode) and not getattr(doc, "HasPendingTransaction", False)
    touched = {obj.Name for obj in doc.Objects if "Touched" in obj.State}
    if dropped:
        doc.openTransaction("Read the zero points")
    try:
        yield
    finally:
        if dropped:
            doc.abortTransaction()
            for obj in doc.Objects:  # all is as it was computed before
                if "Touched" in obj.State and obj.Name not in touched:
                    obj.purgeTouched()
        if not same(cam.zero(job), start):
            activate(job, start)


def one_zero(job):
    """Whether the setup's program needs no visit: its zero point is the
    default one and every operation in the program counts from it."""
    return at_default(job) and not any(parked(op) for op in job.Operations.Group if getattr(op, "Active", True))


def setup_program(job):
    """(the stock's bounds on the default zero point, the setup's switched
    on operations in their order as model.nc.Operation, each with the zero
    point it counts from as the default one sees it)."""
    ops = [op for op in job.Operations.Group if getattr(op, "Active", True)]
    if one_zero(job):
        return cam.stock_bounds(job), [cam.nc_operation(op) for op in ops]
    _arm(job)
    stock = _preset_stock(job)
    made = {}
    zeros = []
    for op in sorted(ops, key=parked):  # the active zero point first: no way to go
        zero = zero_of(op)
        if not any(same(zero, known) for known in zeros):
            zeros.append(zero)
    with _visit(job):
        for zero in zeros:
            activate(job, zero)
            seen = from_default(job, zero)
            for op in ops:
                if not parked(op):
                    made[op.Name] = replace(cam.nc_operation(op), zero=seen)
        if stock is None:
            activate(job, default_zero(job))
            stock = cam.stock_bounds(job)
    return stock, [made[op.Name] for op in ops]


# -- what runs the program (Play, Verify, the stock a setup leaves) -----------------------
#
# The program, its stock and what they show are in the default zero
# point's coordinates; FreeCAD has the setup's part and stock in the
# active one's.


def to_default(job):
    """The placement that takes the Job's coordinates (the active zero
    point's) to the default zero point's; None when they are the same."""
    if at_default(job):
        return None
    return default_zero(job).inverse().multiply(cam.zero(job))


def from_default_placement(job):
    """The placement that takes the default zero point's coordinates to
    the Job's (the active zero point's); None when they are the same."""
    place = to_default(job)
    return None if place is None else place.inverse()


def on_default(job, vertices):
    """Points (n, 3) of the Job's coordinates in the default zero point's."""
    place = to_default(job)
    if place is None:
        return vertices
    import numpy as np

    m = np.array(place.toMatrix().A, float).reshape(4, 4)
    return np.asarray(vertices, float) @ m[:3, :3].T + m[:3, 3]


def start_mesh(job):
    """The material the setup starts from (engine.next_setup.start_mesh),
    in the default zero point's coordinates."""
    from avangardecam.engine import next_setup

    mesh = next_setup.start_mesh(job)
    if mesh is None:
        return _tilted_block(job)
    if at_default(job):
        return mesh
    return mesh._replace(vertices=on_default(job, mesh.vertices))


def _tilted_block(job):
    """The block as a mesh in the default zero point's coordinates when it
    is no box there (its own zero point at an odd angle to the default
    one: the program's stock is the box around it); else None."""
    import numpy as np

    from avangardecam.model import start_stock

    block = _json(job, _BLOCK)
    own, default = stock_zero(job), default_zero(job)
    if not block or cam.stock(job) is None or _along(own, default):
        return None
    (x0, y0, z0, x1, y1, z1), seen = block, default.inverse().multiply(own)
    corners = [seen.multVec(FreeCAD.Vector(x, y, z)) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    triangles = [
        (0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 4), (1, 5, 4),
        (2, 6, 3), (3, 6, 7), (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5),
    ]  # fmt: skip
    return start_stock.Mesh(np.array([(c.x, c.y, c.z) for c in corners], float), np.array(triangles, np.int64))


try:
    install()
except ImportError:  # FreeCAD without its CAM workbench
    pass
