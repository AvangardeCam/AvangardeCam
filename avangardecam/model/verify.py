# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Verification of a setup: its NC program cut out of its stock by the
stock model (avangardecam.stocklab), then checked against the part.

Everything is in the setup's coordinates: its stock is a box along them
and the tool comes from +Z, so a zero point turned through any angle
works. An operation on another zero point of the setup (model.tilted) is
cut from where its tool stands there: its moves are turned into the
setup's coordinates, its tool axis is that zero point's Z. The moves are
those the machine makes (model.machine), not
FreeCAD's path: the radius compensation worked out as the TNC does it, a
drilling cycle down at once (its pecks take nothing more), the way
between operations as post.heidenhain writes it.

A thread mill cuts with its teeth only: inside them, within the thread's
minor diameter, its hole must be empty already (drilled, or milled). So
each hole of a thread milling gets a fine stock of its own, the operations
before are cut out of it, then the hole's moves with the thread mill's
body (the tool less its teeth, and less a chord of the arcs, which the
stock model follows as chords: the walls of a hole milled along a helix
stand in by up to that much); material the body takes is a hole not
drilled, or drilled too small or too shallow (HoleCheck).

Plain Python with numpy, no FreeCAD: the engine gives the stock, the part
as triangles and the tools.
"""

import importlib
import math
from typing import NamedTuple, Optional

import numpy as np

from avangardecam import stocklab
from avangardecam.model import crashes, nc, start_stock, tilted
from avangardecam.model.machine import RETRACT_Z_MM, TOOL_CHANGE_Z_MM, Machine, machine_segments
from avangardecam.stocklab import oblique
from avangardecam.stocklab import tools as stock_tools
from avangardecam.stocklab import program as stock_program
from avangardecam.stocklab.cut import CHORD

# stocklab's verify() hides its module of the same name
stock_verify = importlib.import_module("avangardecam.stocklab.verify")

TOLERANCE_MM = 0.01  # deeper into the part than this is too deep
# the material left is darkest blue this many cells over the part: the
# distance up to stocklab's 25 cells takes minutes on a part from a STEP
LEFTOVER_CELLS = 3.0
DEFAULT_LENGTH = 3.0  # cutting length of a tool that has none, in diameters
DRILL_ANGLE_DEG = 118.0  # a drill without its point angle
CHAMFER_ANGLE_DEG = 90.0  # a chamfer mill without its angle

# operations not checked for too deep: a thread is milled outside the hole
# of the part (a model has a threaded hole at its core diameter)
NOT_CHECKED = (nc.THREAD_MILLING,)

# how deep a thread mill's teeth cut: 5/8 of the thread's height H, as an
# ISO thread's minor diameter (FreeCAD's MinorDiameter of M3: 2.45875)
TEETH_OF_HEIGHT = 5.0 / 8.0
THREAD_ANGLE_DEG = 60.0  # a thread mill without its profile angle
BODY_CELLS = 10  # cells of a thread hole's own stock across the thread mill's body radius

_SAME = 1e-6  # mm: points this close are the same


class PlannedHole(NamedTuple):
    """A hole of a thread milling, in the coordinates of the zero point
    its operation counts from (Planned.zero)."""

    centre: tuple  # (x, y, z) of its top
    bottom: float  # z of the tool's tip at the deepest
    reach: float  # the furthest the tool goes from the centre (XY)
    moves: tuple  # the operation's moves in the hole (their indices)


class Planned(NamedTuple):
    """An operation as the stock model cuts it."""

    label: str
    kind: str
    operation: object  # stocklab.Operation
    notes: tuple  # what could not be followed exactly, for the user
    holes: tuple = ()  # PlannedHole: a thread milling's, to check they are there
    teeth_mm: float = 0.0  # a thread milling: how deep the thread mill's teeth cut
    shank: object = None  # the tool's neck and shank (model.crashes.shank_tool), None: not known
    zero: object = None  # the zero point it counts from (nc.Operation.zero), None: the setup's


class Collision(NamedTuple):
    """A rapid move that took material, or a move whose tool's shank or
    neck took material (model.crashes)."""

    operation: str
    start: tuple
    end: tuple
    volume_mm3: float
    kind: str = "rapid"  # model.crashes.RAPID or SHANK


class Gouge(NamedTuple):
    """Where an operation went deepest into the part."""

    operation: str
    depth_mm: float
    point: tuple
    points: int  # how many checked points of the part it went too deep at


class HoleCheck(NamedTuple):
    """A hole of a thread milling, checked for material inside the thread
    mill's teeth (see the module's docstring)."""

    operation: str
    centre: tuple  # (x, y, z) of its top, in the setup's coordinates
    volume_mm3: Optional[float]  # taken by the thread mill's body: 0 when none, None when not checked
    body_mm: float  # the diameter of the body checked with (0: none, the thread mill no wider than its teeth)


class Result(NamedTuple):
    vertices: np.ndarray  # the surface of the stock left, (V, 3)
    triangles: np.ndarray  # (T, 3)
    colors: np.ndarray  # of the vertices (V, 3), 0..1: gray part, blue left over, red too deep or no hole
    collisions: tuple  # Collision
    gouges: tuple  # Gouge, the operations that went too deep
    cell_mm: float  # the size of the stock's cells
    tolerance_mm: float
    notes: tuple
    holes: tuple = ()  # HoleCheck, each hole of the thread millings


# -- tools ---------------------------------------------------------------------


def stock_tool(tool):
    """The cutting part of a tool (model.tools.Tool) as a solid of
    revolution, as long as its cutting length (3 diameters without one).
    A thread mill is a cylinder as wide as its teeth."""
    d = tool.diameter_mm
    r = d / 2.0
    length = tool.cutting_length_mm or tool.length_mm or DEFAULT_LENGTH * d
    shape = tool.shape
    if shape == "Ballend":
        return stock_tools.ball_end_mill(d, max(length, r))
    if shape == "Bullnose" and tool.corner_radius_mm and tool.corner_radius_mm > 0.0:
        corner = min(tool.corner_radius_mm, r)
        return stock_tools.bull_nose_mill(d, corner, max(length, corner))
    if shape == "Drill":
        angle = tool.angle_deg if tool.angle_deg and 0.0 < tool.angle_deg < 180.0 else DRILL_ANGLE_DEG
        tip = r / math.tan(math.radians(angle) / 2.0)
        return stock_tools.drill(d, angle, max(length, tip))
    if shape in ("Chamfer", "VBit"):
        angle = tool.angle_deg if tool.angle_deg and 0.0 < tool.angle_deg < 180.0 else CHAMFER_ANGLE_DEG
        tip_d = tool.tip_diameter_mm if tool.tip_diameter_mm and tool.tip_diameter_mm < d else 0.0
        tip = (d - tip_d) / 2.0 / math.tan(math.radians(angle) / 2.0)
        return stock_tools.chamfer_mill(d, angle, max(length, tip), tip_d)
    return stock_tools.flat_end_mill(d, length)


def teeth_depth(tool):
    """How deep a thread mill's teeth cut (model.tools.Tool): the depth of
    its thread, TEETH_OF_HEIGHT of the height of the thread's profile."""
    angle = tool.angle_deg if tool.angle_deg and 0.0 < tool.angle_deg < 180.0 else THREAD_ANGLE_DEG
    height = (tool.pitch_mm or 0.0) / 2.0 / math.tan(math.radians(angle) / 2.0)
    return TEETH_OF_HEIGHT * height


def _stock_moves(segments):
    moves = []
    for s in segments:
        if s.centre is not None:
            moves.append(stocklab.Arc(s.start, s.end, (s.centre[0], s.centre[1], 0.0), ccw=not s.clockwise))
        elif float(np.linalg.norm(np.subtract(s.end, s.start))) > _SAME:
            moves.append(stocklab.Line(s.start, s.end, rapid=s.rapid))
    return moves


def _thread_holes(moves, radius):
    """The holes of a thread milling's moves (stocklab), the tool's radius
    given: one round the centre of each helix; a feed line goes with the
    hole nearest to its middle, rapid moves with none."""
    centres, inside = [], []
    for i, move in enumerate(moves):
        if isinstance(move, stocklab.Arc):
            c = move.center[:2]
            k = next((k for k, other in enumerate(centres) if float(np.hypot(*(other - c))) <= _SAME), None)
            if k is None:
                centres.append(np.array(c, dtype=float))
                inside.append([])
                k = -1
            inside[k].append(i)
    if not centres:
        return ()
    for i, move in enumerate(moves):
        if isinstance(move, stocklab.Line) and not move.rapid:
            middle = (move.start[:2] + move.end[:2]) / 2.0
            inside[int(np.argmin([np.hypot(*(middle - c)) for c in centres]))].append(i)
    result = []
    for c, indices in zip(centres, inside):
        indices = sorted(indices)
        ends = np.array([p for i in indices for p in (moves[i].start, moves[i].end)])
        top = max(float(moves[i].start[2]) for i in indices if isinstance(moves[i], stocklab.Arc))
        # an arc's points are no further from its centre than its ends
        reach = float(np.hypot(*(ends[:, :2] - c).T).max()) + radius
        result.append(PlannedHole((float(c[0]), float(c[1]), top), float(ends[:, 2].min()), reach, tuple(indices)))
    return tuple(result)


def plan(setup, tools, retract_z=RETRACT_Z_MM, change_z=TOOL_CHANGE_Z_MM, anew=False):
    """The operations of a setup (nc.Setup) as the stock model cuts them
    (Planned); tools: model.tools.Tool by tool number; anew: a machine
    that turns its head (model.machine.Machine)."""
    machine = Machine(retract_z, change_z, anew=anew)
    result = []
    for op in setup.operations:
        tool = tools.get(op.tool.number)
        if tool is None:
            raise ValueError("{}: T{} is not in the project.".format(op.label, op.tool.number))
        notes = []
        elements = machine.elements(op)
        segments = machine_segments(elements, tool.diameter_mm / 2.0, notes)
        moves = _stock_moves(segments)  # counted from the operation's zero point
        operation = stocklab.Operation(
            stock_tool(tool), tilted.axis(op.zero), [tilted.stock_move(op.zero, m) for m in moves], op.label
        )
        planned = Planned(
            op.label, op.kind, operation, tuple(dict.fromkeys(notes)), shank=crashes.shank_tool(tool), zero=op.zero
        )
        if op.kind == nc.THREAD_MILLING:
            planned = planned._replace(holes=_thread_holes(moves, tool.diameter_mm / 2.0), teeth_mm=teeth_depth(tool))
        result.append(planned)
    return result


# -- the check -------------------------------------------------------------------


def _move_boxes(operation):
    """The box each move's tool sweeps through: (low, high), (n, 3); an
    arc's of its whole circle (round its axis: the tool's)."""
    d = oblique.unit(operation.axis)
    across = np.sqrt(np.clip(1.0 - d * d, 0.0, None))  # how far a circle round d reaches along each axis
    low, high = [], []
    for move in operation.moves:
        a, b = move.start, move.end
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        if isinstance(move, stocklab.Arc):
            # the points of the arc's axis as high as its ends
            ca = move.center + float((a - move.center) @ d) * d
            cb = move.center + float((b - move.center) @ d) * d
            r = max(float(np.linalg.norm(a - ca)), float(np.linalg.norm(b - cb)))
            lo = np.minimum(lo, np.minimum(ca, cb) - r * across)
            hi = np.maximum(hi, np.maximum(ca, cb) + r * across)
        low.append(lo)
        high.append(hi)
    reach = operation.tool.radius * across
    up = operation.tool.length * d
    return (np.array(low).reshape(-1, 3) - reach + np.minimum(up, 0.0),
            np.array(high).reshape(-1, 3) + reach + np.maximum(up, 0.0))  # fmt: skip


def _hole_box(stock, hole, zero):
    """The box of the stock (Bounds) a thread hole's own stock fills, in
    the setup's coordinates: round the hole, from the tip's deepest out
    to where the stock ends on the tool's side; (lower, upper)."""
    x, y, _top = hole.centre
    low = np.array((stock.x_min, stock.y_min, stock.z_min))
    high = np.array((stock.x_max, stock.y_max, stock.z_max))
    if zero is None:
        return (np.maximum((x - hole.reach, y - hole.reach, hole.bottom), low),
                np.minimum((x + hole.reach, y + hole.reach, stock.z_max), high))  # fmt: skip
    corners = np.array([(cx, cy, cz) for cx in (low[0], high[0]) for cy in (low[1], high[1]) for cz in (low[2], high[2])])
    out = float(tilted.seen(zero, corners)[:, 2].max())  # the stock's end as the zero point sees it
    box = tilted.points(zero, [
        (cx, cy, cz) for cx in (x - hole.reach, x + hole.reach) for cy in (y - hole.reach, y + hole.reach)
        for cz in (hole.bottom, max(out, hole.bottom))
    ])  # fmt: skip
    return np.maximum(box.min(axis=0), low), np.minimum(box.max(axis=0), high)


def _hole_checks(stock, planned, index, start=None):
    """Each hole of the thread milling planned[index] (HoleCheck): a stock
    of its own around the hole, from the tip's deepest up to the top of the
    stock, BODY_CELLS cells across the thread mill's body (as fine whatever
    the accuracy chosen: a hole of M3 is two cells of a Rough stock; of
    the setup's start mesh when it has one: a hole drilled in the setup
    before is there), the operations before cut out of it, then the hole's
    feed moves with the body (see the module's docstring)."""
    p = planned[index]
    tool = p.operation.tool
    inside = tool.radius - p.teeth_mm
    if inside <= 0.0:
        return [HoleCheck(p.label, tilted.point(p.zero, h.centre), None, 0.0) for h in p.holes]
    cell = inside / BODY_CELLS
    body = stock_tools.flat_end_mill(2.0 * (inside - CHORD * cell), tool.length)
    before = [(q.operation, _move_boxes(q.operation)) for q in planned[:index]]
    result = []
    for hole in p.holes:
        lower, upper = _hole_box(stock, hole, p.zero)
        centre = tilted.point(p.zero, hole.centre)
        if np.any(upper - lower < cell):  # out of the stock
            result.append(HoleCheck(p.label, centre, 0.0, body.radius * 2.0))
            continue
        local = start_stock.block(stock, start, max(1, int(math.ceil(float((upper - lower).max()) / cell))), lower, upper)
        # only the moves that reach the hole's stock: the others take nothing
        for operation, (low, high) in before:
            near = np.flatnonzero(np.all(low <= upper, axis=1) & np.all(high >= lower, axis=1))
            if near.size:
                moves = [operation.moves[i] for i in near]
                stocklab.simulate(local, [stocklab.Operation(operation.tool, operation.axis, moves, operation.name)])
        mine = set(hole.moves)
        feed = [(a, b) for a, b, rapid, number in stock_program.segments(p.operation, CHORD * cell) if number in mine and not rapid]
        taken = stocklab.cut_lines(local, body, p.operation.axis, [a for a, _ in feed], [b for _, b in feed]) if feed else 0.0
        touch = stock_program.TOUCH * float(np.prod(local.spacing))
        result.append(HoleCheck(p.label, centre, taken if taken > touch else 0.0, body.radius * 2.0))
    return result


def _holes_red(colors, vertices, planned, holes, cell):
    """The stock's surface red in and around the holes with material in them."""
    found = {(h.operation, h.centre) for h in holes if h.volume_mm3}
    for p in planned:
        for hole in p.holes:
            if (p.label, tilted.point(p.zero, hole.centre)) not in found:
                continue
            x, y, top = hole.centre
            seen = tilted.seen(p.zero, vertices)  # as the hole's zero point sees them
            near = (np.hypot(seen[:, 0] - x, seen[:, 1] - y) <= hole.reach + 1.5 * cell) & (
                seen[:, 2] >= hole.bottom - 1.5 * cell) & (seen[:, 2] <= top + 1.5 * cell)  # fmt: skip
            colors[near] = stock_verify.RED
    return colors


def verify(stock, vertices, triangles, planned, resolution=stocklab.DEFAULT_RESOLUTION,
           tolerance=TOLERANCE_MM, progress=None, start=None):  # fmt: skip
    """Cut the planned operations out of the stock (model.stock.Bounds;
    start: the material in it, a model.start_stock.Mesh, None: all of it)
    and check them against the part (closed mesh of triangles), all in the
    setup's coordinates. progress(text) is told each step."""

    def say(text):
        if progress is not None:
            progress(text)

    say("Cutting the stock")
    block = start_stock.block(stock, start, resolution)
    part = stocklab.Model(vertices, triangles)
    operations = [p.operation for p in planned]
    found = crashes.simulate(block, operations, [p.shank for p in planned])
    collisions = []
    for c in found:
        move = operations[c.operation].moves[c.move]
        collisions.append(Collision(planned[c.operation].label, tuple(move.start), tuple(move.end), c.volume, c.kind))
    say("Checking the threads' holes")
    holes = [h for index, p in enumerate(planned) if p.holes for h in _hole_checks(stock, planned, index, start)]
    say("Checking for too deep")
    checked = [p for p in planned if p.kind not in NOT_CHECKED]
    # the part's points half as dense as the stock's cells (stocklab's default)
    g = stock_verify.gouges(part, [p.operation for p in checked], tolerance, max(resolution // 2, 1))
    deep = g.too_deep()
    gouges = []
    for index, p in enumerate(checked):
        mine = deep & (g.operation == index)
        if mine.any():
            worst = int(np.argmax(np.where(mine, g.depth, -1.0)))
            gouges.append(Gouge(p.label, float(g.depth[worst]), tuple(g.points[worst]), int(mine.sum())))
    say("Material left")
    left = stock_verify.leftover(block, part, LEFTOVER_CELLS * float(block.spacing.min()))
    report = stock_verify.Report(block, [], g, left)
    colors = _holes_red(stock_verify.colors(report), left.mesh.vertices, planned, holes, float(block.spacing.min()))
    notes = ["{}: {}".format(p.label, n) for p in planned for n in p.notes]
    return Result(
        left.mesh.vertices, left.mesh.triangles, colors, tuple(collisions), tuple(gouges),
        float(block.spacing.min()), tolerance, tuple(notes), tuple(holes),
    )  # fmt: skip


def export(result, path):
    """Save the stock left: .ply with the colours of the check (Blender,
    MeshLab), .stl the bare shape (any CAD/CAM program)."""
    from avangardecam.stocklab import mesh

    kind = path.lower().rsplit(".", 1)[-1]
    if kind == "ply":
        mesh.save_ply(path, result.vertices, result.triangles, result.colors)
    elif kind == "stl":
        mesh.Mesh(result.vertices, result.triangles).save_stl(path)
    else:
        raise ValueError("The stock left can be saved as .ply or .stl, not {}.".format(path))
