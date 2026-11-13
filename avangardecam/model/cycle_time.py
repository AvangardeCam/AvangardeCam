# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Cycle time: how long the machine takes for each operation of a setup's
NC program (model.nc) and for the whole setup, from the moves the machine
makes (model.machine in full: the drilling cycle's pecks too).

- a feed move: its length (a helix along it) at its feed; the path of the
  tool centre, the radius compensation worked out, as the TNC keeps the
  feed of the tool centre;
- a rapid move (FMAX): each axis at most its rapid traverse, the move as
  long as its slowest axis needs;
- the dwell of a drilling cycle (Q211) at the bottom of each hole;
- a tool change (TOOL CALL) as long as the machine's tool change, the way
  up to the tool change height before it and down after it as rapid moves.

With the machine's dynamics (_dynamic_times): each move speeds up and
slows down at most at the acceleration, a change of speed on a feed move
takes longer by the jerk (an S-curve), a corner between two moves is taken at the speed
that keeps the tool within the corner tolerance of it (as a circle through
the corner would at that acceleration), an arc at most at the speed its
radius allows; the tool stops where it turns back and at the start and end
of an operation. The control looks ahead over the whole operation. The
machine's values are fitted to the TNC 620's own simulation of a plate's
program (user, 2026-10-27), see BRIDGEPORT_V1000. Without an acceleration
(0) the times are those at full speed.

The operation that calls a tool has its change; the end of the program
(spindle off, the table out) is in none.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from avangardecam.model import nc
from avangardecam.model.machine import RETRACT_Z_MM, TOOL_CHANGE_Z_MM, Machine, machine_segments


@dataclass(frozen=True)
class MachineTimes:
    name: str
    rapid_xy_mm_min: float  # FMAX of X and of Y
    rapid_z_mm_min: float
    tool_change_s: float
    acceleration_mm_s2: float = 0.0  # 0: full speed at once (no dynamics)
    jerk_mm_s3: float = 0.0  # on feed moves; 0: the acceleration at once
    corner_tolerance_mm: float = 0.0
    rapid_jerk_mm_s3: float = 0.0  # on rapid moves; 0: the acceleration at once


# rapid traverse: the user (2026-10-27; the data sheet has 48 m/min in XY);
# tool change: the data sheet (tool to tool). The dynamics fitted to the
# TNC's simulation (user, 2026-10-27) of
# - rapid moves back and forth in the air: 500 x 2 mm in Z 0:31, 300 x
#   10 mm 0:41, 100 x 100 mm 0:45, 500 x 2 mm in X 0:31, 100 x 300 mm
#   1:17: Z as X, no jerk to be seen, 2.1 m/s2;
# - the user's plate, one program per operation: facing 1:14, drilling
#   (pecks of 1 mm) 0:41, adaptive (42 000 moves, F1250) 21:23, thread
#   milling 0:26, all 23:43 (the real run 23:52); at full speed these were
#   1:08, 0:18, 17:58, 0:22, all 19:47. The feed moves need the jerk and
#   the corners as well.
# With these (and 1.5 s for each tool change) the plate's operations take
# 1:13, 0:43, 21:32, 0:24, all 23:53; the rapid moves above within 3 %. The
# thread milling stays 3 s short.
BRIDGEPORT_V1000 = MachineTimes("BRIDGEPORT V1000", 43000.0, 36000.0, 1.5, 2100.0, 100000.0, 0.002)


class OperationTime(NamedTuple):
    label: str
    feed_s: float
    rapid_s: float
    dwell_s: float
    tool_change_s: float
    tool: str = ""  # "T21 Frees 6mm"

    @property
    def total_s(self):
        return self.feed_s + self.rapid_s + self.dwell_s + self.tool_change_s


class SetupTime(NamedTuple):
    label: str
    operations: tuple  # OperationTime, in the program's order

    @property
    def total_s(self):
        return sum(op.total_s for op in self.operations)

    def part(self, field):
        """The sum of one part of the operations' times (feed_s, rapid_s, ...)."""
        return sum(getattr(op, field) for op in self.operations)


def _sweep(segment):
    """The angle (radians, positive) an arc segment turns through: a whole
    turn when it ends where it starts."""
    cx, cy = segment.centre
    a0 = math.atan2(segment.start[1] - cy, segment.start[0] - cx)
    a1 = math.atan2(segment.end[1] - cy, segment.end[0] - cx)
    turn = ((a0 - a1) if segment.clockwise else (a1 - a0)) % (2.0 * math.pi)
    return turn if turn > 1e-9 else 2.0 * math.pi


def length(segment):
    """The length of the tool's path along a segment (model.machine.Segment), mm."""
    dz = segment.end[2] - segment.start[2]
    if segment.centre is None:
        return math.dist(segment.start, segment.end)
    cx, cy = segment.centre
    r0 = math.hypot(segment.start[0] - cx, segment.start[1] - cy)
    r1 = math.hypot(segment.end[0] - cx, segment.end[1] - cy)
    return math.hypot(_sweep(segment) * (r0 + r1) / 2.0, dz)


def rapid_s(segment, times):
    """How long a rapid move takes: as long as its slowest axis."""
    dx, dy, dz = (abs(b - a) for a, b in zip(segment.start, segment.end))
    return 60.0 * max(dx / times.rapid_xy_mm_min, dy / times.rapid_xy_mm_min, dz / times.rapid_z_mm_min)


def _feeds(segments, feed, label):
    """The feed (mm/min) of each segment, None on a rapid move; a move
    without one keeps the feed before it, the first the tool's feed."""
    result = []
    for segment in segments:
        if segment.rapid:
            result.append(None)
            continue
        feed = segment.feed if segment.feed is not None else feed
        if not feed or feed <= 0.0:
            raise ValueError("{}: a cutting move without a feed.".format(label))
        result.append(feed)
    return result


def operation_time(op, follower, times=BRIDGEPORT_V1000):
    """The time of an operation (nc.Operation) where the machine
    (model.machine.Machine, full) is after the operations before it."""
    elements = follower.elements(op)
    segments = machine_segments(elements, op.tool.diameter_mm / 2.0, [])
    feeds = _feeds(segments, op.tool.feed_xy_mm_min, op.label)
    if times.acceleration_mm_s2 > 0.0:
        feed_s, rapid = _dynamic_times(segments, feeds, times)
    else:
        feed_s = sum(60.0 * length(s) / f for s, f in zip(segments, feeds) if f is not None)
        rapid = sum(rapid_s(s, times) for s in segments if s.rapid)
    dwell = op.cycle.dwell_s * len(op.cycle.holes) if op.kind == nc.DRILLING else 0.0
    change = times.tool_change_s if follower.changed else 0.0
    return OperationTime(op.label, feed_s, rapid, dwell, change, "T{} {}".format(op.tool.number, op.tool.name))


# -- dynamics --------------------------------------------------------------------

_ARC_STEP = math.radians(5.0)  # an arc is planned as chords of this angle, smooth between them


def _pieces(segments, feeds, times):
    """The straight pieces the segments are planned as: (unit vector,
    length mm, top speed mm/s, arc radius or 0, rapid, smooth with the
    piece before: inside an arc, the segment's index). On an arc the top
    speed is at most the one its radius allows at the acceleration."""
    rapid_xy, rapid_z = times.rapid_xy_mm_min / 60.0, times.rapid_z_mm_min / 60.0
    result = []
    for index, (segment, feed) in enumerate(zip(segments, feeds)):
        if segment.centre is None:
            points, radius = [segment.start, segment.end], 0.0
        else:
            cx, cy = segment.centre
            a0 = math.atan2(segment.start[1] - cy, segment.start[0] - cx)
            sweep = _sweep(segment) * (-1.0 if segment.clockwise else 1.0)
            r0 = math.hypot(segment.start[0] - cx, segment.start[1] - cy)
            r1 = math.hypot(segment.end[0] - cx, segment.end[1] - cy)
            n = max(1, int(math.ceil(abs(sweep) / _ARC_STEP)))
            points = []
            for k in range(n + 1):
                f = k / n
                r = r0 + (r1 - r0) * f
                z = segment.start[2] + (segment.end[2] - segment.start[2]) * f
                points.append((cx + r * math.cos(a0 + sweep * f), cy + r * math.sin(a0 + sweep * f), z))
            radius = (r0 + r1) / 2.0
        smooth = False
        for p, q in zip(points, points[1:]):
            d = (q[0] - p[0], q[1] - p[1], q[2] - p[2])
            size = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
            if size < 1e-9:
                continue
            u = (d[0] / size, d[1] / size, d[2] / size)
            if feed is None:  # the slowest axis at its rapid traverse
                top = 1.0 / max(abs(u[0]) / rapid_xy, abs(u[1]) / rapid_xy, abs(u[2]) / rapid_z)
            else:
                top = feed / 60.0
            if radius > 0.0:
                top = min(top, math.sqrt(times.acceleration_mm_s2 * radius))
            result.append((u, size, top, radius, feed is None, smooth, index))
            smooth = True
    return result


def _corner_speeds(pieces, times):
    """The most speed (mm/s) at the start of each piece and at the end of
    the last: 0 at both ends; at a corner the speed of a circle through it
    that stays within the corner tolerance at the acceleration; 0 where the
    tool turns back; none inside an arc."""
    a, tolerance = times.acceleration_mm_s2, times.corner_tolerance_mm
    n = len(pieces)
    limit = np.zeros(n + 1)
    if n > 1:
        u = np.array([p[0] for p in pieces])
        top = np.array([p[2] for p in pieces])
        cos = np.clip(-np.einsum("ij,ij->i", u[:-1], u[1:]), -1.0, 1.0)
        half = np.sqrt(0.5 * (1.0 - cos))  # sin of half the angle between the pieces
        with np.errstate(divide="ignore", invalid="ignore"):
            speed = np.sqrt(a * tolerance * half / np.maximum(1.0 - half, 1e-12))
        speed = np.where(half > 1.0 - 1e-6, np.inf, speed)  # straight on
        speed = np.where(cos > 1.0 - 1e-6, 0.0, speed)  # turning back
        speed = np.where(np.array([p[5] for p in pieces[1:]]), np.inf, speed)
        limit[1:-1] = np.minimum(speed, np.minimum(top[:-1], top[1:]))
    return limit.tolist()


def _change_s(dv, a, jerk):
    """How much longer a change of speed by dv takes with the jerk than at
    the acceleration a at once (an S-curve)."""
    if jerk <= 0.0 or dv <= 1e-9:
        return 0.0
    if dv >= a * a / jerk:
        return a / jerk
    return 2.0 * math.sqrt(dv / jerk) - dv / a


def _piece_times(pieces, times):
    """The time (s) of each piece (_pieces) with the machine's dynamics,
    and the jerk's time of each: each piece at most at its top speed, the
    corners at most at _corner_speeds, the speeds planned back from the
    end and on from the start so that every change keeps within the
    acceleration; each speeding up and each slowing down (over as many
    pieces of a kind as it takes) longer by the jerk of its kind
    (_change_s: rapid moves have their own), on the piece where it ends."""
    a = times.acceleration_mm_s2
    jerks = [times.rapid_jerk_mm_s3 if p[4] else times.jerk_mm_s3 for p in pieces]
    v = _corner_speeds(pieces, times)
    top = [p[2] for p in pieces]
    lengths = [p[1] for p in pieces]
    for i in range(len(pieces) - 1, -1, -1):
        v[i] = min(v[i], math.sqrt(v[i + 1] ** 2 + 2.0 * a * lengths[i]))
    for i in range(len(pieces)):
        v[i + 1] = min(v[i + 1], math.sqrt(v[i] ** 2 + 2.0 * a * lengths[i]))
    took = [0.0] * len(pieces)
    change = [0, 0.0, None]  # the speed change going on: +1 up, -1 down, 0 none; its size; its piece
    extra = [0.0] * len(pieces)  # the jerk's time, on the piece where each change ends

    def turn(sign, dv, i):
        if change[0] and (sign != change[0] or dv is None or pieces[i][4] != pieces[change[2]][4]):
            k = change[2]
            extra[k] += _change_s(change[1], a, jerks[k])
            change[:] = [0, 0.0, None]
        if dv:
            change[:] = [sign, change[1] + dv, i]

    for i in range(len(pieces)):
        v0, v1, most, size = v[i], v[i + 1], top[i], lengths[i]
        up, down = (most * most - v0 * v0) / (2.0 * a), (most * most - v1 * v1) / (2.0 * a)
        flat = up + down <= size
        if not flat:  # no time at the top speed
            most = math.sqrt(max((2.0 * a * size + v0 * v0 + v1 * v1) / 2.0, 0.0))
            t = (most - v0) / a + (most - v1) / a
        else:
            t = (most - v0) / a + (most - v1) / a + (size - up - down) / most
        if most - v0 > 1e-9:
            turn(+1, most - v0, i)
        if flat or (most - v0 <= 1e-9 and most - v1 <= 1e-9):
            turn(0, None, i)  # at a steady speed
        if most - v1 > 1e-9:
            turn(-1, most - v1, i)
        took[i] = t
    turn(0, None, len(pieces) - 1)
    return took, extra


def _dynamic_times(segments, feeds, times):
    """(feed s, rapid s) of an operation's segments with the machine's
    dynamics (_piece_times)."""
    pieces = _pieces(segments, feeds, times)
    took, extra = _piece_times(pieces, times)
    feed_s = rapid = 0.0
    for piece, t in zip(pieces, took):
        if piece[4]:
            rapid += t
        else:
            feed_s += t
    for piece, t in zip(pieces, extra):
        if piece[4]:
            rapid += t
        else:
            feed_s += t
    return feed_s, rapid


def segment_times(segments, feeds, times=BRIDGEPORT_V1000):
    """The time (s) of each segment of an operation (feeds: _feeds), as
    operation_time adds them up: with the machine's dynamics the time of
    its pieces and the jerk's time ending on them, without at full speed."""
    if times.acceleration_mm_s2 <= 0.0:
        return [60.0 * length(s) / f if f is not None else rapid_s(s, times) for s, f in zip(segments, feeds)]
    pieces = _pieces(segments, feeds, times)
    took, extra = _piece_times(pieces, times)
    result = [0.0] * len(segments)
    for piece, t, e in zip(pieces, took, extra):
        result[piece[6]] += t + e
    return result


def setup_time(setup, times=BRIDGEPORT_V1000, retract_z=RETRACT_Z_MM, change_z=TOOL_CHANGE_Z_MM):
    """The time of a setup (nc.Setup) and of each of its operations (SetupTime)."""
    follower = Machine(retract_z, change_z, full=True)
    return SetupTime(setup.label, tuple(operation_time(op, follower, times) for op in setup.operations))


def program_time(program, times=BRIDGEPORT_V1000, retract_z=RETRACT_Z_MM):
    """The times of a program's setups (SetupTime), in their order: each
    starts with its first tool called (the operator changes the setup)."""
    return [setup_time(setup, times, retract_z) for setup in program.setups]


def duration_text(seconds):
    """45 s, 1 min 05 s, 1 h 02 min: as exact as it is worth."""
    seconds = max(seconds, 0.0)
    if seconds < 10.0:
        return "{:.1f} s".format(seconds)
    whole = int(round(seconds))
    if whole < 60:
        return "{} s".format(whole)
    if whole < 3600:
        return "{} min {:02d} s".format(whole // 60, whole % 60)
    minutes = int(round(seconds / 60.0))
    return "{} h {:02d} min".format(minutes // 60, minutes % 60)
