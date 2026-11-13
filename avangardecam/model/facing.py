# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Facing: a flat face of the model cut level with a face mill, in
straight passes (the user's design, 2026-10-21). For now the user keeps it
to the top of the model, faced over the whole stock (engine.facing); the
walls and offset_xy_mm below are for faces lower down, later.

The user clicks a flat face facing the tool. The tool clears its plane
everywhere the model is not above it: up to the walls going up from it
(kept offset_xy_mm away from them, the tool measured at its widest), and
over open edges (nothing above, or a step down) out to the stock and
overrun_mm beyond, so it leaves the material entirely. A face with nothing
above it is faced over the whole stock. engine.facing works out that
area; this module lays the passes over it and makes the moves.

The passes start on one side of the stock across them (the user's, by
default where the first one climbs) and step over to the other, the first
coming in over the edge (the user, 2026-10-22: a face mill does not start
near the middle).

Plain Python: the area comes in as rows (the stretches of each pass line
inside it) and a test whether a link between passes stays inside.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple, Optional

from avangardecam.model import nc
from avangardecam.model.operations import APPROACH_Z_MM, MAX_CUTS, MAX_DEPTH_MM, SAFETY_MM

# how the tool goes from one pass to the next
ZIGZAG = "zigzag"  # back the other way, the passes joined by half circles at depth
ONE_WAY = "one_way"  # always the same way: up, rapid back, down
PATTERNS = (ZIGZAG, ONE_WAY)

# the direction of the first pass, which also says along which axis the passes go
X_PLUS = "x+"
X_MINUS = "x-"
Y_PLUS = "y+"
Y_MINUS = "y-"
DIRECTIONS = (X_PLUS, X_MINUS, Y_PLUS, Y_MINUS)

# the side of the stock across the passes the tool starts on: of Y for passes
# along X, of X for passes along Y (None: the side where the first pass climbs)
FROM_MINUS = "-"
FROM_PLUS = "+"
START_SIDES = (None, FROM_MINUS, FROM_PLUS)

# (u, v) of each direction with the first pass climbing (Facing.axes)
_CLIMBING = {
    X_PLUS: ((0, 1), (1, 1)),
    X_MINUS: ((0, -1), (1, -1)),
    Y_PLUS: ((1, 1), (0, -1)),
    Y_MINUS: ((1, -1), (0, 1)),
}

OVERRUN_MM = 2.0  # past open edges the tool leaves the material by this much
_EPSILON_MM = 1e-6
_LEVEL_GAP_MM = 1e-3  # a level closer than this under Start Z cuts nothing


def _round(value):
    return round(value, 6) + 0.0


@dataclass(frozen=True)
class Facing:
    """Facing of a flat face (model.facing).

    start_z_mm: the top of the material, in the setup's coordinates (the Z
    of the program); None: the top of the stock. The Z levels go from it
    down to the face: full steps of z_step_mm and the rest at the end (as
    the contour; None: the whole depth at once).
    step_over_percent: the most of the tool's diameter between passes; the
    passes are spread evenly.
    pattern ZIGZAG or ONE_WAY; direction: of the first pass (X_PLUS: from
    X- to X+), so the passes go along X or Y.
    start_side: FROM_MINUS or FROM_PLUS, the side of the stock across the
    passes the first one is on (Y- or Y+ for passes along X); None: the side
    where it climbs.
    offset_xy_mm: the tool's edge stays this far from the walls going up
    from the face (negative: into them).
    overrun_mm: past open edges the tool's edge goes this far beyond the
    stock.
    """

    start_z_mm: Optional[float] = None
    z_step_mm: Optional[float] = None
    step_over_percent: float = 70.0
    pattern: str = ZIGZAG
    direction: str = X_PLUS
    offset_xy_mm: float = 0.0
    overrun_mm: float = OVERRUN_MM
    start_side: Optional[str] = None

    KIND = "facing"

    def validate(self):
        if self.start_z_mm is not None and not -MAX_DEPTH_MM <= self.start_z_mm <= MAX_DEPTH_MM:
            raise ValueError("Start Z must be within {:g} mm of the zero point, got {:g} mm".format(MAX_DEPTH_MM, self.start_z_mm))  # fmt: skip
        if self.z_step_mm is not None and not 0.0 < self.z_step_mm <= MAX_DEPTH_MM:
            raise ValueError("The Z step must be larger than 0 mm, got {:g} mm".format(self.z_step_mm))
        if not 1.0 <= self.step_over_percent <= 100.0:
            raise ValueError("The step over must be 1 to 100 % of the tool, got {:g} %".format(self.step_over_percent))
        if self.pattern not in PATTERNS:
            raise ValueError("Unknown pattern: {}".format(self.pattern))
        if self.direction not in DIRECTIONS:
            raise ValueError("Unknown direction: {}".format(self.direction))
        if self.start_side not in START_SIDES:
            raise ValueError("Unknown start side: {}".format(self.start_side))
        if not -MAX_DEPTH_MM <= self.offset_xy_mm <= MAX_DEPTH_MM:
            raise ValueError("The offset must be within {:g} mm, got {:g} mm".format(MAX_DEPTH_MM, self.offset_xy_mm))
        if not 0.0 <= self.overrun_mm <= MAX_DEPTH_MM:
            raise ValueError("The overrun must be 0 mm or more, got {:g} mm".format(self.overrun_mm))
        return self

    def check(self, tool_diameter_mm):
        """ValueError when a tool of that diameter cannot face with these values."""
        if self.offset_xy_mm <= -tool_diameter_mm / 2.0 + _EPSILON_MM:
            raise ValueError(
                "An offset of {:g} mm puts the tool's centre into the walls (Ø{:g})".format(self.offset_xy_mm, tool_diameter_mm)
            )
        return self

    def top_mm(self, stock_top_mm):
        """Z where the material starts: Start Z, else the top of the stock."""
        return stock_top_mm if self.start_z_mm is None else self.start_z_mm

    def levels(self, top_mm, face_z_mm):
        """Z levels in the setup's coordinates, from the top: full Z steps
        down from top_mm and the face itself; none at top_mm or above."""
        found = [_round(face_z_mm)]
        if self.z_step_mm is not None:
            k = 1
            while top_mm - k * self.z_step_mm > face_z_mm + _EPSILON_MM:
                found.insert(-1, _round(top_mm - k * self.z_step_mm))
                k += 1
        return [z for z in found if z < top_mm - _LEVEL_GAP_MM]

    def step_mm(self, tool_diameter_mm):
        return tool_diameter_mm * self.step_over_percent / 100.0

    def axes(self):
        """(u, v) of the passes: u along them (0: X, 1: Y), +1/-1 the way the
        first one goes; v the axis and way the tool steps over: from the
        start side to the other one.

        Without a start side the tool steps over so the first pass climbs
        (the spindle turns clockwise, M3): the uncut material on its left."""
        u, (v_axis, v_way) = _CLIMBING[self.direction]
        if self.start_side is not None:
            v_way = 1 if self.start_side == FROM_MINUS else -1
        return u, (v_axis, v_way)


def climbing_side(direction):
    """The start side (FROM_MINUS or FROM_PLUS) where the first pass of that direction climbs."""
    return FROM_MINUS if _CLIMBING[direction][1][1] > 0 else FROM_PLUS


def rows_at(low_mm, high_mm, diameter_mm, step_mm, from_low=True, overrun_mm=0.0):
    """Positions of the pass lines across material from low_mm to high_mm
    (along the step-over axis), in the order the tool steps over: from the
    low end (from_low) or the high one. Each pass cuts no more than step_mm
    of fresh material, all evenly: the first one comes in over the start
    end, the tool out past it, and the last one has the tool's edge
    overrun_mm past the other end (the user, 2026-10-22)."""
    width = max(high_mm - low_mm, 0.0) + overrun_mm
    count = max(1, int(math.ceil(width / step_mm - 1e-9)))
    radius = diameter_mm / 2.0
    if from_low:
        return [low_mm - radius + width * i / count for i in range(1, count + 1)]
    return [high_mm + radius - width * i / count for i in range(1, count + 1)]


class Run(NamedTuple):
    """Passes the tool cuts without lifting, in the setup's XY."""

    start: tuple  # (x, y) where it comes down
    moves: tuple  # ("line", (x, y)) or ("arc", (x, y) end, (cx, cy) centre, clockwise)
    open_entry: bool  # it comes down clear of the stock (to a wall: where the passes cut)
    direct: bool  # from the run before at the level (inside the area), else over the safe height


class Plan(NamedTuple):
    runs: tuple

    def closed_entries(self):
        """How many times the tool comes down into material."""
        return sum(1 for run in self.runs if not run.open_entry)


_ARC_POINTS = 12  # a link's half circle is checked at this many points


def plan(rows, facing, fits, outside):
    """The runs of a facing (Plan).

    rows: [(v, ((u0, u1), ...))] in the order the tool steps over (Facing.axes),
    each with the stretches of its pass line the tool centre may run along,
    u0 < u1. fits(points): True when the tool centre may go through these
    (x, y) points at depth (inside the area, links included). outside(x, y):
    True when the tool there is clear of the stock (it may come down).

    ZIGZAG: each pass goes back the other way; the next pass starts on the
    same side, joined by a half circle of its distance, or by a straight
    line when the half circle does not fit (a wall there); when neither
    fits, a new run. A new run starts the way the first pass goes, or the
    other way when only that end is outside the stock.
    ONE_WAY: every pass the way of the first, each a run."""
    (u_axis, u_way), _v = facing.axes()

    def xy(u, v):
        return (u, v) if u_axis == 0 else (v, u)

    left = [[True] * len(spans) for _v, spans in rows]
    found = []  # (start, moves)
    for i, (row_v, spans) in enumerate(rows):
        for j, (u0, u1) in enumerate(spans):
            if not left[i][j]:
                continue
            left[i][j] = False
            way = u_way
            if facing.pattern == ZIGZAG:
                first, other = (u0, u1) if way > 0 else (u1, u0)
                if not outside(*xy(first, row_v)) and outside(*xy(other, row_v)):
                    way = -way
            start, end = (u0, u1) if way > 0 else (u1, u0)
            moves = [("line", xy(end, row_v))]
            k, v, here = i, row_v, end
            while facing.pattern == ZIGZAG and k + 1 < len(rows):
                next_v, next_spans = rows[k + 1]
                # the stretch of the next line beside this one, its end nearest to where the tool is
                beside = [
                    n for n, (a, b) in enumerate(next_spans) if left[k + 1][n] and a <= max(u0, u1) and min(u0, u1) <= b
                ]
                if not beside:
                    break
                n = min(beside, key=lambda n: abs((next_spans[n][1] if way > 0 else next_spans[n][0]) - here))
                a, b = next_spans[n]
                next_start, next_end = (b, a) if way > 0 else (a, b)
                link = _link(here, v, next_start, next_v, way, xy, fits)
                if link is None:
                    break
                left[k + 1][n] = False
                moves.extend(link)
                moves.append(("line", xy(next_end, next_v)))
                k, v, here, way, u0, u1 = k + 1, next_v, next_end, -way, a, b
            found.append((xy(start, row_v), tuple(moves)))
    return _plan(found, fits, outside)


def with_walls(the_plan, walls, fits, outside, radius_mm):
    """The plan and then, on each level, the tool along the walls going up
    from the face (walls: [(start, moves)], at the user's offset): the
    passes lie evenly across the material, so beside a wall along them
    they leave a strip. The tool comes down to a wall clear of the stock
    or within radius_mm of a pass, on floor the passes have cut."""
    passes = [(run.start, run.moves) for run in the_plan.runs]
    lines = []
    for start, moves in passes:
        for move in moves:
            if move[0] == "line":
                lines.append((start, move[1]))
            start = move[1]

    def beside(x, y):
        return any(_distance((x, y), a, b) <= radius_mm + _EPSILON_MM for a, b in lines)

    runs = _plan(passes + list(walls), fits, outside).runs
    return Plan(runs[: len(passes)] + tuple(run._replace(open_entry=run.open_entry or beside(*run.start)) for run in runs[len(passes) :]))  # fmt: skip


def _distance(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length == 0.0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _plan(found, fits, outside):
    runs = []
    for n, (start, moves) in enumerate(found):
        before = found[n - 1][1][-1][1]  # the first run: from the end of the last one, a level higher
        runs.append(Run(start, moves, outside(*start), fits(_segment(before, start))))
    return Plan(tuple(runs))


def reversed_moves(start, moves):
    """(start, moves) of a run gone the other way."""
    points = [start] + [move[1] for move in moves]
    result = []
    for i in range(len(moves) - 1, -1, -1):
        move = moves[i]
        if move[0] == "line":
            result.append(("line", points[i]))
        else:
            result.append(("arc", points[i], move[2], not move[3]))
    return points[-1], tuple(result)


def _segment(a, b, count=_ARC_POINTS):
    return [(a[0] + (b[0] - a[0]) * t / count, a[1] + (b[1] - a[1]) * t / count) for t in range(count + 1)]


def _link(u, v, next_u, next_v, way, xy, fits):
    """Moves from the end of a pass (u, v) to the start of the next one
    (next_u, next_v) on the same side, at depth; None when nothing fits.

    A half circle beyond the farther of the two ends (the nearer pass
    goes on straight up to there), else a straight line."""
    turn = max(u, next_u) if way > 0 else min(u, next_u)
    middle = (v + next_v) / 2.0
    radius = abs(next_v - v) / 2.0
    points = [xy(*p) for p in _segment((u, v), (turn, v), 4)]
    for t in range(_ARC_POINTS + 1):
        angle = math.pi * t / _ARC_POINTS
        points.append(xy(turn + way * radius * math.sin(angle), middle + (v - middle) * math.cos(angle)))
    points.extend(xy(*p) for p in _segment((turn, next_v), (next_u, next_v), 4))
    if fits(points):
        moves = []
        if abs(turn - u) > _EPSILON_MM:
            moves.append(("line", xy(turn, v)))
        centre = xy(turn, middle)
        moves.append(("arc", xy(turn, next_v), centre, _clockwise(xy(turn, v), xy(turn + way * radius, middle), centre)))
        if abs(turn - next_u) > _EPSILON_MM:
            moves.append(("line", xy(next_u, next_v)))
        return moves
    if fits(_segment(xy(u, v), xy(next_u, next_v))):
        return [("line", xy(next_u, next_v))]
    return None


def _clockwise(start, mid, centre):
    """True when an arc from start through mid around centre turns clockwise (seen from +Z)."""
    ax, ay = start[0] - centre[0], start[1] - centre[1]
    bx, by = mid[0] - centre[0], mid[1] - centre[1]
    return ax * by - ay * bx < 0.0


def moves(the_plan, levels, top_mm, safe_z, feed_z_mm_min, feed_xy_mm_min, approach_z=None):
    """The tool's moves of a facing (nc.Move): each Z level from the top,
    all the runs of the plan on it.

    Over the first start to Z+20 (the spindle starts there), rapid down to
    2 mm above where the material starts (top_mm, then the level above),
    with the Z feed to the level; the runs at the XY feed. Between runs
    the tool goes up 2 mm over the level above and across, when the way
    stays inside the area (Run.direct), else over the safe height."""
    approach = max(APPROACH_Z_MM if approach_z is None else approach_z, safe_z)
    result = []
    position = [None, None, None]

    def add(kind, x, y, z, feed=None, centre=None, clockwise=False):
        if kind != nc.ARC and position == [x, y, z]:
            return
        result.append(nc.Move(kind, x, y, z, feed, centre, clockwise))
        position[:] = [x, y, z]

    if len(levels) * sum(len(run.moves) for run in the_plan.runs) > MAX_CUTS * 10:
        raise ValueError("The facing has too many moves; take a larger step over or Z step.")
    above = top_mm
    for level in levels:
        over = min(safe_z, above + SAFETY_MM)
        for run in the_plan.runs:
            x, y = run.start
            if position[2] is None:
                add(nc.RAPID, x, y, approach)
            elif run.direct:  # the tool is over material it cut already
                add(nc.RAPID, x, y, position[2])
            else:
                add(nc.RAPID, position[0], position[1], max(safe_z, position[2]))
                add(nc.RAPID, x, y, position[2])
            add(nc.RAPID, x, y, over)
            add(nc.LINE, x, y, level, feed_z_mm_min)
            for move in run.moves:
                if move[0] == "line":
                    add(nc.LINE, move[1][0], move[1][1], level, feed_xy_mm_min)
                else:
                    _kind, end, centre, clockwise = move
                    add(nc.ARC, end[0], end[1], level, feed_xy_mm_min, centre, clockwise)
            add(nc.RAPID, position[0], position[1], over)
        above = level
    if position[2] is not None:
        add(nc.RAPID, position[0], position[1], safe_z)
    return tuple(result)
