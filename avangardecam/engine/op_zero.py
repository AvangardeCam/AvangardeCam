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
  0-Point. The block of stock is kept as the default zero point sees it;
  on another zero point the stock is the box around that block (the same
  block on axes a quarter turn away, a larger box at other angles).
- setup_program() is the setup for the NC program: it visits each zero
  point in turn, reads its operations there and comes back, so that
  every operation is read where it is computed.
"""

import contextlib
import itertools
import json
from dataclasses import replace

import FreeCAD

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.model import op_zero as model
from avangardecam.model import stock as model_stock

_ZERO = "AvangardeZero"
_PARKED = "AvangardeParked"
_DEFAULT = "AvangardeDefaultZero"
_BLOCK = "AvangardeBlock"  # the stock's bounds on the default zero point
_BOX = "AvangardeDefaultStock"  # its allowances there
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


def _remember_block(job):
    """The stock as the default zero point (the active one) has it."""
    _property(job, "App::PropertyString", _BLOCK, "Stock bounds on the default zero point")
    _property(job, "App::PropertyString", _BOX, "Stock allowances on the default zero point")
    box = cam.stock(job)
    if box is None:  # another kind of stock: it is not a box around the model
        setattr(job, _BLOCK, "")
        setattr(job, _BOX, "")
        return
    setattr(job, _BLOCK, json.dumps(list(cam.stock_bounds(job))))
    setattr(job, _BOX, json.dumps([box.x_neg_mm, box.x_pos_mm, box.y_neg_mm, box.y_pos_mm, box.z_neg_mm, box.z_pos_mm]))


def _fit_stock(job, place):
    """The allowances of the stock on the zero point place (the clones are
    there already): the block's own on the default zero point, else the
    box around the block."""
    import Path.Main.Stock as PathStock

    block, box = _json(job, _BLOCK), _json(job, _BOX)
    if cam.stock(job) is None or not block or not box or not job.Model.Group:
        return
    default = default_zero(job)
    if same(place, default):
        allowances = box
    else:
        seen = place.inverse().multiply(default)
        corners = [
            seen.multVec(FreeCAD.Vector(x, y, z))
            for x, y, z in itertools.product((block[0], block[3]), (block[1], block[4]), (block[2], block[5]))
        ]
        part = PathStock.shapeBoundBox(job.Model.Group)
        low = [min(getattr(c, axis) for c in corners) for axis in "xyz"]
        high = [max(getattr(c, axis) for c in corners) for axis in "xyz"]
        allowances = [
            part.XMin - low[0], high[0] - part.XMax,
            part.YMin - low[1], high[1] - part.YMax,
            part.ZMin - low[2], high[2] - part.ZMax,
        ]  # fmt: skip
    stock = job.Stock
    for name, value in zip(("ExtXneg", "ExtXpos", "ExtYneg", "ExtYpos", "ExtZneg", "ExtZpos"), allowances):
        setattr(stock, name, cam._quantity(max(0.0, round(value, 6)), "mm"))


def _preset_stock(job):
    """The stock's bounds on the default zero point, None when only going
    there tells."""
    if at_default(job):
        return cam.stock_bounds(job)
    block = _json(job, _BLOCK)
    if block and cam.stock(job) is not None:
        return model_stock.Bounds(*block)
    return None


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
    if same(old, getattr(job, _DEFAULT)):
        _remember_block(job)
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
    _remember_block(job)  # the stock as it is seen from here
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
    """The default zero point went with the setup."""
    if hasattr(job, _DEFAULT):
        setattr(job, _DEFAULT, cam.zero(job))


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


def on_presets(program):
    """(the program with every operation in its preset's coordinates, the
    labels of the operations left out: a tilted tool cannot be shown on
    the preset). For the simulation, Verify and the cycle time."""
    setups, left_out = [], []
    for setup in program.setups:
        flat, labels = model.setup_on_preset(setup)
        setups.append(flat)
        left_out.extend(labels)
    return replace(program, setups=tuple(setups)), tuple(left_out)


try:
    install()
except ImportError:  # FreeCAD without its CAM workbench
    pass
