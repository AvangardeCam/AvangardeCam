# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Playback of a setup: its NC program's moves as the machine makes them
(model.machine in full: the drilling cycle's pecks too, the way up to the
tool change), each when the machine makes it, for a player to show the
tool where it is at any moment.

- the time of each move with the machine's dynamics (model.cycle_time:
  the same as the cycle time, so the whole setup takes as long as its
  cycle time says);
- a step is one move of the program (model.machine.Element: what the
  control runs as one block; a move with the radius compensation may be
  more than one segment of the tool's path, its corner arcs), a tool
  change (TOOL CALL: the tool change time, standing) or a drilling
  cycle's dwell (Q211, at the bottom of each hole, standing, with the
  move down there);
- each step with the line of the program it runs (post.heidenhain.numbered),
  or the line before when it has none of its own (a move that changes
  nothing in the program);
- within a segment the tool moves evenly over its time (the speeding up
  and slowing down only in how long it takes).

Plain Python with numpy, no FreeCAD.
"""

import bisect
import math
from typing import NamedTuple, Optional

import numpy as np

from avangardecam.model import cycle_time, nc
from avangardecam.model.machine import RETRACT_Z_MM, TOOL_CHANGE_Z_MM, Machine, machine_segments
from avangardecam.model.verify import CHAMFER_ANGLE_DEG, DEFAULT_LENGTH, DRILL_ANGLE_DEG

# how fast the player may play, times the machine (user, 2026-10-27: x0.1 to x100)
SPEEDS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 50.0, 100.0)

# an arc is drawn as chords at most this far from it and at most this angle each
CHORD_MM = 0.01
CHORD_ANGLE = math.radians(10.0)

# kinds of a step besides the moves (nc.RAPID, nc.LINE, nc.ARC)
TOOL_CHANGE = "tool change"
DWELL = "dwell"

_SAME = 1e-9


class Step(NamedTuple):
    """One block the machine runs, as the player steps through them."""

    kind: str  # nc.RAPID, nc.LINE, nc.ARC, TOOL_CHANGE or DWELL
    operation: int  # its operation, index in the setup
    tool: nc.Tool  # in the spindle (the old one on the way up to the tool change)
    start_s: float
    duration_s: float
    first: int  # its first segment (Timeline.segments)
    count: int  # its segments (none: standing)
    feed: Optional[float]  # mm/min; None: rapid or standing
    line: Optional[int]  # the program's line it runs (Timeline.lines), None: none yet

    @property
    def end_s(self):
        return self.start_s + self.duration_s


class OperationSpan(NamedTuple):
    label: str
    tool: nc.Tool
    first: int  # its first step
    end: int  # after its last step
    start_s: float
    end_s: float
    notes: tuple  # the radius compensation's (model.machine)

    @property
    def duration_s(self):
        return self.end_s - self.start_s


class Timeline:
    """The steps of a setup over time; the tool's tip at any time."""

    def __init__(self, segments, starts, durations, steps, operations, lines):
        self.segments = segments  # model.machine.Segment, the whole setup in order
        self.starts = np.asarray(starts, dtype=float)  # of each segment, s
        self.durations = np.asarray(durations, dtype=float)
        self.steps = steps
        self.operations = operations
        self.lines = lines  # the program's (all setups'), without line ends
        self.total_s = steps[-1].end_s if steps else 0.0
        self._step_starts = [s.start_s for s in steps]

    def step_at(self, t):
        """The index of the step going on at time t: the last that started
        before t (at the end of a step still that one, as a control
        running block by block shows the block it has just run; at 0 the
        first), not one that takes no time."""
        if not self.steps:
            return None
        i = max(bisect.bisect_left(self._step_starts, t) - 1, 0)
        while i > 0 and self.steps[i].duration_s <= _SAME:
            i -= 1
        return i

    def operation_at(self, t):
        step = self.step_at(t)
        return None if step is None else self.steps[step].operation

    def line_at(self, t):
        """The program's line running at time t, or None."""
        step = self.step_at(t)
        return None if step is None else self.steps[step].line

    def segment_at(self, t):
        """(index of the segment the tool is on at time t, the share of it done)."""
        if not self.segments:
            return None, 0.0
        i = int(np.searchsorted(self.starts, t, side="right")) - 1
        i = min(max(i, 0), len(self.segments) - 1)
        duration = float(self.durations[i])
        if duration <= _SAME:
            return i, 1.0 if t >= self.starts[i] else 0.0
        return i, min(max((t - float(self.starts[i])) / duration, 0.0), 1.0)

    def position(self, t):
        """Where the tool's tip is at time t, (x, y, z)."""
        i, share = self.segment_at(t)
        if i is None:
            return None
        return point_on(self.segments[i], share)

    def next_stop(self, t):
        """The end of the step going on at t, or of the next one when the
        tool is at its end already (steps taking no time are skipped)."""
        for step in self.steps[self.step_at(t) or 0 :]:
            if step.end_s > t + 1e-6:
                return step.end_s
        return self.total_s

    def previous_stop(self, t):
        """The start of the step going on at t, or the start of the one
        before when the tool is at its start already."""
        for step in reversed(self.steps[: (self.step_at(t) or 0) + 1]):
            if step.duration_s > _SAME and step.start_s < t - 1e-6:
                return step.start_s
        return 0.0

    def next_operation(self, t):
        """The start of the next operation, or the end of the setup."""
        for op in self.operations:
            if op.start_s > t + 1e-6:
                return op.start_s
        return self.total_s

    def previous_operation(self, t):
        """The start of the operation going on at t, or of the one before
        when it has just started."""
        for op in reversed(self.operations):
            if op.start_s < t - 1e-6:
                return op.start_s
        return 0.0


def _sweep(segment):
    """The angle (radians, signed: negative clockwise) of an arc segment."""
    turn = cycle_time._sweep(segment)
    return -turn if segment.clockwise else turn


def point_on(segment, share):
    """The point a share (0..1) along a segment: along its line, or round
    its arc (the radius and the height evenly between its ends)."""
    s, e = segment.start, segment.end
    if segment.centre is None:
        return tuple(a + (b - a) * share for a, b in zip(s, e))
    cx, cy = segment.centre
    r0 = math.hypot(s[0] - cx, s[1] - cy)
    r1 = math.hypot(e[0] - cx, e[1] - cy)
    a = math.atan2(s[1] - cy, s[0] - cx) + _sweep(segment) * share
    r = r0 + (r1 - r0) * share
    return (cx + r * math.cos(a), cy + r * math.sin(a), s[2] + (e[2] - s[2]) * share)


def _chords(segment):
    """How many chords an arc segment is drawn with (1 for a line)."""
    if segment.centre is None:
        return 1
    cx, cy = segment.centre
    r = max(math.hypot(segment.start[0] - cx, segment.start[1] - cy), math.hypot(segment.end[0] - cx, segment.end[1] - cy))
    step = CHORD_ANGLE
    if r > CHORD_MM:
        step = min(step, 2.0 * math.acos(1.0 - CHORD_MM / r))
    return max(1, int(math.ceil(abs(_sweep(segment)) / step)))


class Polyline(NamedTuple):
    """An operation's path as one line through points (arcs as chords)."""

    points: np.ndarray  # (n, 3)
    rapid: np.ndarray  # (n - 1,) bool, of each piece between two points
    firsts: np.ndarray  # of each segment its first point; one more: the last point

    def done(self, segment, share):
        """How many of the points the tool has passed (the first counted)
        at a share along a segment (index in the operation)."""
        a, b = int(self.firsts[segment]), int(self.firsts[segment + 1])
        return a + 1 + int(math.floor(share * (b - a) + 1e-9))


def polyline(segments):
    """The path of segments one after another as a Polyline."""
    if not segments:
        return Polyline(np.zeros((0, 3)), np.zeros(0, dtype=bool), np.zeros(1, dtype=np.int64))
    points = [segments[0].start]
    rapid, firsts = [], []
    for segment in segments:
        firsts.append(len(points) - 1)
        n = _chords(segment)
        for k in range(1, n + 1):
            points.append(point_on(segment, k / n) if k < n else segment.end)
            rapid.append(segment.rapid)
    firsts.append(len(points) - 1)
    return Polyline(np.array(points, dtype=float), np.array(rapid, dtype=bool), np.array(firsts, dtype=np.int64))


def _dwell_after(elements, op):
    """The indices of the elements after which a drilling cycle dwells:
    the last one reaching the bottom of each hole."""
    if op.kind != nc.DRILLING or not op.cycle.dwell_s:
        return set()
    lowest = {}
    for i, e in enumerate(elements):
        if e.source and e.source[0] == "hole" and e.kind != nc.RAPID:
            k = e.source[1]
            if k not in lowest or e.end[2] <= elements[lowest[k]].end[2] + 1e-9:
                lowest[k] = i
    return set(lowest.values())


def timeline(setup, setup_index=0, lines=(), lines_of=None, times=cycle_time.BRIDGEPORT_V1000,
             retract_z=RETRACT_Z_MM, change_z=TOOL_CHANGE_Z_MM):  # fmt: skip
    """The Timeline of a setup (nc.Setup), the setup_index-th of its
    program; lines and lines_of from post.heidenhain.numbered of the
    program (none: steps without lines)."""
    lines_of = lines_of or {}
    follower = Machine(retract_z, change_z, full=True)
    segments, starts, durations, steps, operations = [], [], [], [], []
    now = 0.0
    line = None
    previous_tool = None
    for index, op in enumerate(setup.operations):
        elements = follower.elements(op)
        changed = follower.changed
        notes, owners = [], []
        found = machine_segments(elements, op.tool.diameter_mm / 2.0, notes, owners)
        feeds = cycle_time._feeds(found, op.tool.feed_xy_mm_min, op.label)
        took = cycle_time.segment_times(found, feeds, times)
        dwells = _dwell_after(elements, op)
        first_step = len(steps)
        start = now
        by_element = [[] for _ in elements]
        for k, owner in enumerate(owners):
            by_element[owner].append(k)

        def add(kind, tool, duration, first, count, feed, source):
            nonlocal now, line
            if source is not None and (setup_index, index) + source in lines_of:
                line = lines_of[(setup_index, index) + source]
            steps.append(Step(kind, index, tool, now, duration, first, count, feed, line))
            now += duration

        change_pending = changed
        for i, element in enumerate(elements):
            source = element.source
            if change_pending and (source is None or source[0] != "change"):
                add(TOOL_CHANGE, op.tool, times.tool_change_s, len(segments), 0, None, ("call",))
                change_pending = False
            mine = by_element[i]
            first = len(segments)
            moved = now
            for k in mine:
                segments.append(found[k])
                starts.append(moved)
                durations.append(took[k])
                moved += took[k]
            feed = None if element.kind == nc.RAPID else next((feeds[k] for k in mine if feeds[k]), None)
            tool = previous_tool if source == ("change",) and previous_tool is not None else op.tool
            add(element.kind, tool, moved - now, first, len(mine), feed, source)
            if i in dwells:
                add(DWELL, op.tool, op.cycle.dwell_s, len(segments), 0, None, None)
        if change_pending:
            add(TOOL_CHANGE, op.tool, times.tool_change_s, len(segments), 0, None, ("call",))
        operations.append(OperationSpan(op.label, op.tool, first_step, len(steps), start, now, tuple(notes)))
        previous_tool = op.tool
    return Timeline(segments, starts, durations, steps, operations, list(lines))


def operation_polyline(line, operation):
    """The Polyline of an operation (OperationSpan) of a Timeline and the
    index of its first segment."""
    steps = line.steps[operation.first : operation.end]
    if not steps:
        return polyline([]), 0
    first = steps[0].first
    last = steps[-1].first + steps[-1].count
    return polyline(line.segments[first:last]), first


# -- the tool's shape --------------------------------------------------------------


def _arc(cr, ch, radius, a0, a1, n=8):
    """Points (r, h) of a quarter-ish arc of the profile round (cr, ch),
    angles from the axis' downward direction (0: straight down)."""
    return [(cr + radius * math.sin(a0 + (a1 - a0) * k / n), ch - radius * math.cos(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def tool_profile(tool, diameter):
    """The tool's outline from its tip up as (cutting, body): each a list
    of (radius, height) from the axis round to the axis again, the tip at
    height 0. tool: model.tools.Tool (None: a flat end mill of the
    diameter). The cutting part as long as its cutting length (3 diameters
    without one) like Verify's; the body (neck, shank) up to the tool's
    length, else two diameters more."""
    d = tool.diameter_mm if tool is not None and tool.diameter_mm else diameter
    r = d / 2.0
    shape = tool.shape if tool is not None else "Endmill"
    cutting_length = (tool.cutting_length_mm if tool is not None else None) or DEFAULT_LENGTH * d
    if shape == "Ballend":
        outline = _arc(0.0, r, r, 0.0, math.pi / 2.0)
        cutting_length = max(cutting_length, r)
    elif shape == "Bullnose" and tool.corner_radius_mm and tool.corner_radius_mm > 0.0:
        c = min(tool.corner_radius_mm, r)
        outline = [(0.0, 0.0)] + _arc(r - c, c, c, 0.0, math.pi / 2.0)
        cutting_length = max(cutting_length, c)
    elif shape in ("Drill", "Chamfer", "VBit"):
        default = DRILL_ANGLE_DEG if shape == "Drill" else CHAMFER_ANGLE_DEG
        angle = tool.angle_deg if tool.angle_deg and 0.0 < tool.angle_deg < 180.0 else default
        tip_r = tool.tip_diameter_mm / 2.0 if shape != "Drill" and tool.tip_diameter_mm and tool.tip_diameter_mm < d else 0.0
        tip = (r - tip_r) / math.tan(math.radians(angle) / 2.0)
        outline = [(0.0, 0.0)] + ([(tip_r, 0.0)] if tip_r > 0.0 else []) + [(r, tip)]
        cutting_length = max(cutting_length, tip)
    else:
        outline = [(0.0, 0.0), (r, 0.0)]
    cutting = outline + [(r, cutting_length), (0.0, cutting_length)]
    shank_r = (tool.shank_diameter_mm / 2.0 if tool is not None and tool.shank_diameter_mm else r)
    length = tool.length_mm if tool is not None and tool.length_mm else None
    if not length or length <= cutting_length:
        length = cutting_length + 2.0 * d
    body = [(0.0, cutting_length)]
    neck_r = tool.neck_diameter_mm / 2.0 if tool is not None and tool.neck_diameter_mm else None
    neck_end = tool.neck_length_mm if tool is not None and tool.neck_length_mm else None
    up = cutting_length
    if neck_r and neck_end and cutting_length < neck_end < length:
        body += [(neck_r, cutting_length), (neck_r, neck_end)]
        up = neck_end
    body += [(shank_r, up), (shank_r, length), (0.0, length)]
    return cutting, body


def revolve(profile, sides=32):
    """A profile (radius, height) turned round the Z axis: (vertices
    (n, 3), triangles (m, 3)); points on the axis once."""
    vertices, rings = [], []
    for r, h in profile:
        if r <= 1e-12:
            rings.append([len(vertices)] * sides)
            vertices.append((0.0, 0.0, h))
            continue
        rings.append(list(range(len(vertices), len(vertices) + sides)))
        for k in range(sides):
            a = 2.0 * math.pi * k / sides
            vertices.append((r * math.cos(a), r * math.sin(a), h))
    triangles = []
    for below, above in zip(rings, rings[1:]):
        for k in range(sides):
            a, b = below[k], below[(k + 1) % sides]
            c, d = above[k], above[(k + 1) % sides]
            if a != b:
                triangles.append((a, b, d))
            if c != d:
                triangles.append((a, d, c))
    return np.array(vertices, dtype=float), np.array(triangles, dtype=np.int64).reshape(-1, 3)


# -- texts ---------------------------------------------------------------------------


def clock_text(seconds):
    """3:07, 1:02:05: the time on the player's clock."""
    whole = int(max(seconds, 0.0))
    if whole >= 3600:
        return "{}:{:02d}:{:02d}".format(whole // 3600, whole % 3600 // 60, whole % 60)
    return "{}:{:02d}".format(whole // 60, whole % 60)


def speed_text(speed):
    """x0.1, x1, x25."""
    return "×{:g}".format(speed)
