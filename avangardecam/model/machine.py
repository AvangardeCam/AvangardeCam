# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The moves the machine makes for a setup's NC program (model.nc), in the
setup's coordinates, the tool's tip; not FreeCAD's path. Verify cuts them
out of the stock (model.verify), the cycle time adds them up
(model.cycle_time).

- the program's moves with the radius compensation worked out as the
  control does it with DR0 (Heidenhain TNC): the move that switches RL/RR
  on goes straight to the first contour point, the tool's radius beside it
  square to the contour's first element; elements are offset by the
  radius, an outside corner gets an arc round the corner point, an inside
  corner ends where the offset elements cross; the move that switches it
  off goes straight from the last offset point;
- a drilling cycle (205) as its moves: over the hole at the 2nd set-up
  clearance, down to the set-up clearance, the tip to the depth, back up;
  in full (Machine(full=True)) also its pecks, chip breaking and deepened
  start, as the TNC 620 runs the cycle;
- the way between operations as post.heidenhain writes it: after a tool
  change the tool is at TOOL_CHANGE_Z_MM (in full: it goes up there from
  where it was), after an operation at the retract height, after a
  drilling at the 2nd set-up clearance; the next operation moves in XY at
  that height, then down.
- an operation on another zero point (nc.Operation.zero) has its moves
  counted from that one, the tool along its Z (model.tilted): the tool
  goes high on the preset before the zero point is shifted under it; a
  machine that turns its head (Machine(anew=True)) starts every operation
  high over the operation's own zero point, as post.soraluce writes it.

Each move keeps its feed (mm/min; None on a rapid move, and on a feed move
that keeps the feed before it, as the program writes it), and where in the
operation it comes from (Element.source, the same the postprocessor
numbers its blocks by: post.heidenhain.numbered):
- ("change",): the way up to the tool change height (in full),
- ("approach",): over the operation's first point,
- ("move", i): the operation's move i (op.moves),
- ("retract",): up to the retract height, ("off",): the compensation
  switched off up there,
- ("hole", k): the moves of the drilling cycle in its hole k;
the postprocessor also numbers ("call",): the operation's TOOL CALL.
"""

import math
from typing import NamedTuple, Optional, Tuple

import numpy as np

from avangardecam.model import nc, tilted

RETRACT_Z_MM = 40.0  # after an operation (post.heidenhain: the machine's retract_z_mm)
TOOL_CHANGE_Z_MM = 100.0  # after a tool change (post.heidenhain: L Z100 R0 FMAX)

_SAME = 1e-6  # mm: points this close are the same


class Element(NamedTuple):
    """A programmed move from start to end (both full points)."""

    kind: str  # nc.RAPID, nc.LINE, nc.ARC
    start: tuple
    end: tuple
    centre: Optional[Tuple[float, float]]
    clockwise: bool
    compensation: Optional[str]
    feed: Optional[float] = None  # mm/min
    source: Optional[tuple] = None  # where in the operation it comes from (see the module)


class Segment(NamedTuple):
    """A move of the tool's tip: a line, or an arc (helix) round centre."""

    start: tuple
    end: tuple
    rapid: bool
    centre: Optional[Tuple[float, float]] = None
    clockwise: bool = False
    feed: Optional[float] = None  # mm/min


def _filled(position, move):
    return tuple(position[i] if v is None else v for i, v in enumerate((move.x, move.y, move.z)))


class Machine:
    """Follows the program as the machine runs it: where the tool is and
    the programmed moves of each operation, all axes known. full: the
    drilling cycle's pecks too, and the way up to the tool change height
    (they take no material, the cycle time needs them)."""

    def __init__(self, retract_z=RETRACT_Z_MM, change_z=TOOL_CHANGE_Z_MM, full=False, anew=False):
        self.retract_z = retract_z
        self.change_z = change_z
        self.full = full
        self.anew = anew  # a turning head: every operation starts high over its own zero point
        self.position = [None, None, change_z]
        self.zero = None  # the zero point the position is counted from (None: the preset)
        self.tool = None
        self.changed = False  # the last operation called its tool

    def elements(self, op):
        result = []
        self.changed = self.tool is None or self.tool != op.tool.number
        # the zero point the operation counts from (model.tilted): the tool
        # as it sees it, and how high the tool change height is there
        moved = op.zero != self.zero
        self.position, high = tilted.arrive(self, op)
        self.zero = op.zero
        if self.changed:
            self.tool = op.tool.number
            if self.full and self.position[0] is not None and self.position[2] != high:
                self._add(result, nc.Move(nc.RAPID, None, None, high), ("change",))
            self.position = [self.position[0], self.position[1], high]
        elif moved and self.position[2] != high:
            # high on the preset before the zero point changes under the tool
            if self.full and self.position[0] is not None:
                self._add(result, nc.Move(nc.RAPID, None, None, high))
            self.position[2] = high
        if op.kind == nc.DRILLING:
            return result + self._drilling(op)
        moves = list(op.moves)
        lead = 0
        while lead < len(moves) and moves[lead].kind == nc.RAPID:
            lead += 1
        first = next((m for m in moves[:lead] if m.x is not None and m.y is not None), None)
        if first is None or lead == len(moves):
            raise ValueError("{}: the operation does not say where it starts.".format(op.label))
        if self.position[0] is None:
            self.position[:2] = [first.x, first.y]
        # over the first point at the height the tool has, then down
        self._add(result, nc.Move(nc.RAPID, first.x, first.y, None, compensation=first.compensation), ("approach",))
        for i, move in enumerate(moves[:lead]):
            self._add(result, nc.Move(nc.RAPID, None, None, move.z, compensation=first.compensation), ("move", i))
        for i, move in enumerate(moves[lead:], lead):
            self._add(result, move, ("move", i))
        # up to the retract height; the compensation off up there, where the tool is
        side = result[-1].compensation if result else None
        self._add(result, nc.Move(nc.RAPID, None, None, self.retract_z, compensation=side), ("retract",))
        if side is not None:
            self._add(result, nc.Move(nc.RAPID, None, None, None), ("off",))
        return result

    def _add(self, result, move, source=None):
        start = tuple(self.position)
        end = _filled(start, move)
        result.append(Element(move.kind, start, end, move.center, move.clockwise, move.compensation, move.feed_mm_min, source))
        self.position = list(end)

    def _drilling(self, op):
        """Cycle 205 on each hole: over it at the 2nd set-up clearance (up
        to it first when lower), down to the set-up clearance, the tip to
        the depth with the feed, back up. In full, the way down as the
        cycle goes (_drilled); else at once: the pecks and the deepened
        start take nothing more."""
        cycle = op.cycle
        result = []
        for k, hole in enumerate(cycle.holes):
            source = ("hole", k)
            second = hole.surface_z + cycle.second_clearance_mm
            first = hole.surface_z + cycle.clearance_mm
            if self.position[0] is None:
                self.position[:2] = [hole.x, hole.y]
            if self.position[2] < second:
                self._add(result, nc.Move(nc.RAPID, None, None, second), source)
            self._add(result, nc.Move(nc.RAPID, hole.x, hole.y, None), source)
            self._add(result, nc.Move(nc.RAPID, None, None, first), source)
            if self.full:
                for move in _drilled(cycle, hole):
                    self._add(result, move, source)
            else:
                self._add(result, nc.Move(nc.LINE, None, None, hole.surface_z + hole.depth_mm, cycle.feed_mm_min), source)
            self._add(result, nc.Move(nc.RAPID, None, None, max(first, second)), source)
        return result


def pecks(cycle, depth):
    """The depths (positive, below the start of the drilling) cycle 205
    drills to one after another in a hole `depth` deep (positive): Q202,
    then less by Q212 each time, not less than Q205; the whole depth at
    once without Q202."""
    if cycle.peck_mm is None or abs(cycle.peck_mm) <= _SAME:
        return [depth]
    result = []
    reached, k = 0.0, 0
    smallest = abs(cycle.min_peck_mm) if cycle.min_peck_mm else _SAME
    while reached < depth - _SAME:
        step = max(abs(cycle.peck_mm) - k * abs(cycle.decrement_mm), smallest)
        reached = min(reached + step, depth)
        result.append(reached)
        k += 1
    return result


def _drilled(cycle, hole):
    """The moves of cycle 205 in a hole from its set-up clearance down and
    up to it again, as the TNC 620 runs it: with a deepened start (Q379)
    down to the set-up clearance over it at the pre-positioning feed
    (Q253); each peck at the feed (Q206), with chip breaking (Q257: up by
    Q256 and down again, rapid) every Q257; after a peck rapid up to the
    set-up clearance and down to the advanced stop distance over the depth
    reached (Q258 at the first, Q259 at the last, evenly between); the
    dwell (Q211) is no move."""
    top = hole.surface_z
    clearance = top + cycle.clearance_mm
    start = top - abs(cycle.start_mm or 0.0)
    result = []
    if start < top - _SAME:
        result.append(nc.Move(nc.LINE, None, None, start + cycle.clearance_mm, cycle.preposition_feed_mm_min))
    depths = pecks(cycle, max(-hole.depth_mm - (top - start), 0.0))
    breaks = abs(cycle.chip_break_mm or 0.0)
    for k, depth in enumerate(depths):
        bottom = start - depth
        if breaks > _SAME:
            reached = start - (depths[k - 1] if k else 0.0)
            while reached - breaks > bottom + _SAME:
                reached -= breaks
                result.append(nc.Move(nc.LINE, None, None, reached, cycle.feed_mm_min))
                result.append(nc.Move(nc.RAPID, None, None, reached + abs(cycle.chip_retract_mm)))
                result.append(nc.Move(nc.RAPID, None, None, reached))
        result.append(nc.Move(nc.LINE, None, None, bottom, cycle.feed_mm_min))
        if k + 1 < len(depths):
            share = k / (len(depths) - 2) if len(depths) > 2 else 0.0
            stop = cycle.upper_stop_mm + (cycle.lower_stop_mm - cycle.upper_stop_mm) * share
            result.append(nc.Move(nc.RAPID, None, None, clearance))
            result.append(nc.Move(nc.RAPID, None, None, bottom + stop))
    return result


def _xy(p):
    return np.array(p[:2], dtype=float)


def _moves_in_xy(element):
    return element.kind == nc.ARC or float(np.hypot(*(_xy(element.end) - _xy(element.start)))) > _SAME


def _tangents(element):
    """Unit tangents in XY at the start and at the end of an element."""
    if element.kind == nc.ARC:
        c = np.array(element.centre, dtype=float)
        result = []
        for p in (element.start, element.end):
            radial = _xy(p) - c
            t = np.array((-radial[1], radial[0])) / max(np.hypot(*radial), 1e-12)
            result.append(-t if element.clockwise else t)
        return result
    d = _xy(element.end) - _xy(element.start)
    d /= np.hypot(*d)
    return [d, d]


class _Offset:
    """An element offset by the tool's radius to one side (XY), its z kept."""

    def __init__(self, element, radius, side, notes):
        self.element = element
        self.rapid = element.kind == nc.RAPID
        self.z0, self.z1 = element.start[2], element.end[2]
        self.t0, self.t1 = _tangents(element)
        left = side == nc.LEFT
        if element.kind == nc.ARC:
            self.centre = np.array(element.centre, dtype=float)
            r0 = float(np.hypot(*(_xy(element.start) - self.centre)))
            r1 = float(np.hypot(*(_xy(element.end) - self.centre)))
            # the left of a counterclockwise arc is towards its centre
            sign = -1.0 if left != element.clockwise else 1.0
            self.radius = max(r0 + sign * radius, 0.0)
            if r0 + sign * radius <= _SAME:
                notes.append("an arc of R{:g} is too small for the tool's radius {:g}".format(round(r0, 3), radius))
            self.p0 = self.centre + (_xy(element.start) - self.centre) * (self.radius / max(r0, 1e-12))
            self.p1 = self.centre + (_xy(element.end) - self.centre) * (self.radius / max(r1, 1e-12))
        else:
            self.centre = None
            n = np.array((-self.t0[1], self.t0[0])) * (1.0 if left else -1.0)
            self.p0 = _xy(element.start) + radius * n
            self.p1 = _xy(element.end) + radius * n

    def segment(self):
        start = (self.p0[0], self.p0[1], self.z0)
        end = (self.p1[0], self.p1[1], self.z1)
        feed = self.element.feed
        if self.centre is None:
            return Segment(start, end, self.rapid, feed=feed)
        return Segment(start, end, self.rapid, tuple(self.centre), self.element.clockwise, feed)

    def crossings(self, other):
        """Where the full line or circle of this offset element crosses the other's."""
        if self.centre is None and other.centre is None:
            d, e = self.p1 - self.p0, other.p1 - other.p0
            den = d[0] * e[1] - d[1] * e[0]
            if abs(den) < 1e-12 * float(np.hypot(*d) * np.hypot(*e)):
                return []
            w = other.p0 - self.p0
            s = (w[0] * e[1] - w[1] * e[0]) / den
            return [self.p0 + s * d]
        if self.centre is None or other.centre is None:
            line, circle = (self, other) if self.centre is None else (other, self)
            return _line_circle(line.p0, line.p1, circle.centre, circle.radius)
        return _circle_circle(self.centre, self.radius, other.centre, other.radius)


def _line_circle(p0, p1, c, r):
    d = p1 - p0
    f = p0 - c
    a = float(np.dot(d, d))
    b = 2.0 * float(np.dot(f, d))
    k = float(np.dot(f, f)) - r * r
    disc = b * b - 4.0 * a * k
    if a < 1e-24 or disc < 0.0:
        return []
    root = math.sqrt(disc)
    return [p0 + ((-b + s * root) / (2.0 * a)) * d for s in (-1.0, 1.0)]


def _circle_circle(c0, r0, c1, r1):
    d = float(np.hypot(*(c1 - c0)))
    if d < 1e-12 or d > r0 + r1 or d < abs(r0 - r1):
        return []
    a = (r0 * r0 - r1 * r1 + d * d) / (2.0 * d)
    h = math.sqrt(max(r0 * r0 - a * a, 0.0))
    u = (c1 - c0) / d
    m = c0 + a * u
    n = np.array((-u[1], u[0]))
    return [m + h * n, m - h * n]


def _compensated(position, chain, radius, notes):
    """The tool's moves along a chain of elements with the same
    compensation, from where the tool is (see the module's docstring),
    the tool's position after them and the index in the chain of the
    element each move belongs to (a corner to the element after it)."""
    side = chain[0].compensation
    on, rest = chain[0], chain[1:]
    offsets = [_Offset(e, radius, side, notes) if _moves_in_xy(e) else None for e in rest]
    contour = [o for o in offsets if o is not None]
    if not contour:
        # nothing to follow: beside the end of the switching move, square to it
        end = _xy(on.end)
        if _moves_in_xy(on):
            t = _tangents(on)[1]
            end = end + radius * np.array((-t[1], t[0])) * (1.0 if side == nc.LEFT else -1.0)
        target = (end[0], end[1], on.end[2])
        segments = [Segment(position, target, on.kind == nc.RAPID, feed=on.feed)]
        here = target
        for e in rest:
            segments.append(Segment(here, (here[0], here[1], e.end[2]), e.kind == nc.RAPID, feed=e.feed))
            here = segments[-1].end
        return segments, here, list(range(len(segments)))
    # the corners between the offset elements
    corners = {}  # index in contour of the element after the corner: an arc (centre, clockwise)
    for k in range(1, len(contour)):
        a, b = contour[k - 1], contour[k]
        if float(np.hypot(*(a.p1 - b.p0))) <= _SAME:
            continue
        cross = a.t1[0] * b.t0[1] - a.t1[1] * b.t0[0]
        dot = float(np.dot(a.t1, b.t0))
        turning_right = cross < 0.0 or (abs(cross) < 1e-9 and dot < 0.0)
        corner = _xy(a.element.end)
        if turning_right == (side == nc.LEFT):
            # outside: round the corner point; the tool on the left turns right (clockwise)
            corners[k] = (tuple(corner), side == nc.LEFT)
            continue
        found = a.crossings(b)
        if not found:
            notes.append("an inside corner at X{:.3f} Y{:.3f} the tool cannot reach".format(*corner))
            corners[k] = None
            continue
        x = min(found, key=lambda p: float(np.hypot(*(p - corner))))
        a.p1 = x
        b.p0 = np.array(x)
    for offset in contour:
        if offset.centre is None and float(np.dot(offset.p1 - offset.p0, offset.t0)) < -_SAME:
            # the offset line runs backwards: the control stops, the contour is too small
            notes.append("a line at X{:.3f} Y{:.3f} too short for the tool's radius {:g}".format(*_xy(offset.element.start), radius))
    segments = []
    first = contour[0]
    start = (first.p0[0], first.p0[1], on.end[2])
    segments.append(Segment(position, start, on.kind == nc.RAPID, feed=on.feed))
    owners = [0]
    here = start
    k = 0
    for index, (e, offset) in enumerate(zip(rest, offsets), 1):
        owners += [index - 1] * (len(segments) - len(owners))  # those of the element before
        if offset is None:  # along the tool axis where the tool is
            segments.append(Segment(here, (here[0], here[1], e.end[2]), e.kind == nc.RAPID, feed=e.feed))
            here = segments[-1].end
            continue
        begin = (offset.p0[0], offset.p0[1], offset.z0)
        # a corner goes at the feed of the element after it
        feed = e.feed
        if k in corners:
            arc = corners[k]
            if arc is None:
                segments.append(Segment(here, begin, offset.rapid, feed=feed))
            else:
                segments.append(Segment(here, (begin[0], begin[1], here[2]), offset.rapid, arc[0], arc[1], feed))
        elif float(np.hypot(*(np.array(here[:2]) - offset.p0))) > _SAME:
            segments.append(Segment(here, (begin[0], begin[1], here[2]), offset.rapid, feed=feed))
        segment = offset.segment()
        segments.append(segment._replace(start=segments[-1].end))
        here = segment.end
        k += 1
    owners += [len(chain) - 1] * (len(segments) - len(owners))
    return segments, here, owners


def machine_segments(elements, radius, notes, owners=None):
    """The tool's tip moves (Segment) of programmed elements (Element),
    the radius compensation worked out. owners (a list): gets the index
    of the element each segment belongs to."""
    if not elements:
        return []
    segments = []
    position = elements[0].start
    i = 0
    while i < len(elements):
        e = elements[i]
        if e.compensation is None:
            if e.kind == nc.ARC:
                segments.append(Segment(position, e.end, False, e.centre, e.clockwise, e.feed))
            else:
                segments.append(Segment(position, e.end, e.kind == nc.RAPID, feed=e.feed))
            if owners is not None:
                owners.append(i)
            position = e.end
            i += 1
            continue
        j = i
        while j < len(elements) and elements[j].compensation == e.compensation:
            j += 1
        found, position, chain = _compensated(position, elements[i:j], radius, notes)
        segments += found
        if owners is not None:
            owners += [i + k for k in chain]
        i = j
    return segments
