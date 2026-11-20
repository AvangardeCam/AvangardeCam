# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The stock of a setup as the machine leaves it at any time of its
playback (model.playback.Timeline), cut by the stock model
(avangardecam.stocklab) as Verify cuts it: the setup's stock box, each
tool's cutting part (model.verify.stock_tool), the moves the machine makes,
in the setup's coordinates, the tool from +Z.

Going on in time cuts only what the tool went along since; a segment the
tool is on is cut up to where it is. Going back starts again from the last
copy of the stock kept before that time: one every SNAPSHOT_SEGMENTS
segments (and at the start), so going back never cuts more than that.

All the moves of one tool are cut at once (stocklab.cut_lines, arcs as
chords as the stock model's simulate makes them), rapid moves too; what
the machine runs into is found on the way (model.crashes: a rapid move
taking material, the tool's shank or neck in material), a move cut on its
own only when material is near it. Crashes keeps them by segment: found
once, kept when going back.

The surface is drawn in pieces (stocklab.mesh.pieces, PIECE_CUBES on each
axis): changed_pieces gives only those whose material changed since it
was last asked, going on or going back (the stock notes the cells each cut
changes, and when going back, the cuts after the time are undone).

Plain Python with numpy, no FreeCAD.
"""

import bisect
import math
import time
from typing import NamedTuple, Optional

import numpy as np

from avangardecam import stocklab
from avangardecam.model import crashes as model_crashes
from avangardecam.model import start_stock
from avangardecam.model.playback import point_on
from avangardecam.model.verify import stock_tool
from avangardecam.stocklab import tools as stock_tools
from avangardecam.stocklab.cut import CHORD
from avangardecam.stocklab.program import segments as stock_segments

# how often a copy of the stock is kept, in segments (on the user's plate:
# going back cuts at most about this many again, 0.15 s at Fine)
SNAPSHOT_SEGMENTS = 2000
# the size of a piece of the stock's surface, in cubes of its lattice on each
# axis (on the user's 27 x 20 x 20 part at Medium 8 x 6 x 6 pieces, a second
# of Adaptive at x10 changes about 12 of them: 16 ms instead of 310)
PIECE_CUBES = 32
# a piece of an arc shorter than this (mm) is cut as a straight line: the
# stock model takes an arc ending where it starts for a whole circle
_ARC_PIECE_MM = 1e-3
_SAME = 1e-9
# cutting against a deadline (Material.cut_to(t, seconds)): at most this
# many chords at once
_MOST_BATCH = 4096


def _piece(segment, a, b):
    """The part of a segment from share a to share b of it."""
    if a <= _SAME and b >= 1.0 - _SAME:
        return segment
    start, end = point_on(segment, a), point_on(segment, b)
    return segment._replace(start=start, end=end)


def _stock_move(segment):
    """A segment as a move of the stock model, or None when it is no move."""
    if segment.centre is None:
        if float(np.linalg.norm(np.subtract(segment.end, segment.start))) <= _SAME:
            return None
        return stocklab.Line(segment.start, segment.end, rapid=segment.rapid)
    cx, cy = segment.centre
    chord = math.dist(segment.start, segment.end)
    whole = math.hypot(segment.start[0] - segment.end[0], segment.start[1] - segment.end[1]) <= _SAME
    if not whole and chord <= _ARC_PIECE_MM:
        return stocklab.Line(segment.start, segment.end, rapid=False)
    return stocklab.Arc(segment.start, segment.end, (cx, cy, 0.0), ccw=not segment.clockwise)


def _chords(move, tolerance):
    """About how many straight pieces the stock model cuts a move as
    (cut.arc_points): what it costs, a line 1."""
    if not isinstance(move, stocklab.Arc):
        return 1
    cx, cy = float(move.center[0]), float(move.center[1])
    x0, y0 = float(move.start[0]) - cx, float(move.start[1]) - cy
    x1, y1 = float(move.end[0]) - cx, float(move.end[1]) - cy
    radius = max(math.hypot(x0, y0), math.hypot(x1, y1))
    if radius <= tolerance:
        return 1
    turn = math.atan2(y1, x1) - math.atan2(y0, x0)
    turn = turn % (2.0 * math.pi) if move.ccw else (-turn) % (2.0 * math.pi)
    if turn < 1e-12:
        turn = 2.0 * math.pi
    step = 2.0 * math.acos(max(1.0 - tolerance / radius, -1.0))
    return max(1, int(math.ceil(turn / step)))


class Material:
    """The stock of a Timeline's setup at a time (cut_to), in the setup's
    coordinates. bounds: model.stock.Bounds of the setup's stock; tools:
    model.tools.Tool by tool number (a tool missing: a flat end mill of
    the program's diameter); resolution: cells on the stock's longest
    edge, as Verify's; start: the material in the stock box
    (model.start_stock.Mesh, None: all of it)."""

    def __init__(self, timeline, bounds, tools, resolution=250, snapshot_segments=SNAPSHOT_SEGMENTS, start=None):
        self.line = timeline
        self.resolution = resolution
        self.stock = start_stock.block(bounds, start, resolution)
        self.stock.watch()  # the copies kept are watched too
        # (from time, to time, the cells changed) of each cut, to know what a
        # going back undoes; the cells changed since changed_pieces, None: all
        self._history = []
        self._changed = None
        self._all = True
        self._shapes = {}
        self._shanks = {}
        for step in timeline.steps:
            number = step.tool.number
            if number not in self._shapes:
                tool = tools.get(number)
                self._shapes[number] = stock_tool(tool) if tool is not None else stock_tools.flat_end_mill(step.tool.diameter_mm, 3.0 * step.tool.diameter_mm)
                self._shanks[number] = model_crashes.shank_tool(tool)
        # what the machine ran into: (kind, segment) -> mm3 taken (the most
        # found: a segment cut in pieces finds it in one of them), in the order found
        self.crashes = {}
        # the tool of each segment
        self._tool_of = [None] * len(timeline.segments)
        for step in timeline.steps:
            for k in range(step.first, step.first + step.count):
                self._tool_of[k] = step.tool.number
        self._every = max(int(snapshot_segments), 1)
        self._kept = {0: self.stock.copy()}  # first segment not cut yet -> the stock then
        self.t = 0.0  # cut up to this time

    @property
    def cell_mm(self):
        return float(self.stock.spacing.max())

    def cut_to(self, t, seconds=None):
        """The stock as it is at time t (cut on from where it was, or
        again from a copy kept before t). seconds: going on, stop cutting
        after about this long, at the end of a segment (a player that
        must not stop for long: it goes on from self.t, the time cut up
        to, next time); None: all the way to t."""
        line = self.line
        t = min(max(t, 0.0), line.total_s)
        back = t < self.t - _SAME
        if back:
            first = int(np.searchsorted(line.starts, t, side="right")) - 1 if line.segments else 0
            kept = max(k for k in self._kept if k <= max(first, 0))
            self.stock = self._kept[kept].copy()
            self.t = float(line.starts[kept]) if kept < len(line.segments) else line.total_s
            # what was cut after t is no more; what is cut again from the copy
            # (up to t) is as it was drawn
            for _t0, t1, cells in self._history:
                if t1 > t + _SAME:
                    self._count_in(cells)
            self._history = [h for h in self._history if h[0] < self.t - _SAME]
        if t > self.t + _SAME:
            deadline = None if seconds is None else time.monotonic() + seconds
            t = self._cut(self.t, t, deadline)
            cells = self.stock.changed_cells()
            if cells is not None:
                self._history.append((self.t, t, cells))
                if not back:
                    self._count_in(cells)
        self.t = t
        return self.stock

    def _count_in(self, cells):
        if self._changed is None:
            self._changed = cells
        else:
            self._changed = (np.minimum(self._changed[0], cells[0]), np.maximum(self._changed[1], cells[1]))

    def changed_pieces(self):
        """The pieces of the stock's surface to draw again (since the last
        call, the first time all): (all, pieces), pieces a dict (i, j, k) ->
        stocklab.Mesh; all: these are all the pieces with a surface, the
        others are gone; else the pieces whose material may have changed
        (one with no surface now is in it, empty)."""
        if self._all:
            self._all, self._changed = False, None
            return True, stocklab.mesh.pieces(self.stock, PIECE_CUBES)
        cells, self._changed = self._changed, None
        if cells is None:
            return False, {}
        return False, stocklab.mesh.pieces(self.stock, PIECE_CUBES, cells)

    def _cut(self, t0, t1, deadline=None):
        """Cut from time t0 to t1; returns the time cut up to: t1, or with
        a deadline (time.monotonic) the end of the segment where it went
        past it. Then the moves are cut a few at a time, as many chords
        (_chords: a helix costs as many lines as it has chords) as the time
        left should take by the last few, the first time one move, never
        more than four times the chords before."""
        line = self.line
        if not line.segments:
            return t1
        i = max(int(np.searchsorted(line.starts, t0, side="right")) - 1, 0)
        pending, tool = [], None  # moves of one tool waiting to be cut, their first segment
        first_pending = i
        batch = 1  # chords
        weight = 0  # the chords of the moves waiting
        tolerance = CHORD * self.stock.spacing.min()
        while i < len(line.segments) and line.starts[i] < t1 - _SAME:
            start, duration = float(line.starts[i]), float(line.durations[i])
            if duration > _SAME:
                a = max((t0 - start) / duration, 0.0)
                b = min((t1 - start) / duration, 1.0)
            else:
                a, b = (0.0, 1.0) if start >= t0 - _SAME else (1.0, 1.0)
            if b > a + _SAME:
                number = self._tool_of[i]
                if number != tool and pending:
                    self._flush(pending, tool, first_pending)
                    pending, weight = [], 0
                if not pending:
                    first_pending = i
                tool = number
                move = _stock_move(_piece(line.segments[i], a, b))
                if move is not None:
                    pending.append((i, move))
                    if deadline is not None:
                        weight += _chords(move, tolerance)
            done = b >= 1.0 - _SAME
            if done and (i + 1) % self._every == 0 and (i + 1) not in self._kept:
                self._flush(pending, tool, first_pending)
                pending, weight = [], 0
                self._kept[i + 1] = self.stock.copy()
            if not done:
                break
            if deadline is not None and pending and weight >= batch:
                began = time.monotonic()
                count = weight
                self._flush(pending, tool, first_pending)
                pending, weight = [], 0
                now = time.monotonic()
                end = float(line.starts[i] + line.durations[i])
                if now >= deadline and end < t1 - _SAME:
                    return end
                each = max((now - began) / count, 1e-6)
                batch = int(min(max((deadline - now) / each / 2.0, 1), 4 * count, _MOST_BATCH))
            i += 1
        self._flush(pending, tool, first_pending)
        return t1

    def _flush(self, pending, tool, first):
        """Cut the moves of one tool waiting, all at once, and keep what
        it ran into."""
        if not pending:
            return
        operation = stocklab.Operation(self._shapes[tool], "+Z", [m for _, m in pending])
        pieces = [(a, b, rapid, pending[number][0]) for a, b, rapid, number in stock_segments(operation, CHORD * self.stock.spacing.min())]
        for c in model_crashes.cut(self.stock, operation.tool, self._shanks[tool], pieces):
            key = (c.kind, c.key)
            self.crashes[key] = max(self.crashes.get(key, 0.0), c.volume_mm3)

    def mesh(self):
        """The stock's surface now (stocklab.Mesh)."""
        return stocklab.surface(self.stock)

    def volume(self):
        return float(self.stock.volume())


class PlayedCrash(NamedTuple):
    """What the machine ran into (model.crashes), on the time line."""

    kind: str  # model.crashes.RAPID or SHANK
    segment: int
    volume_mm3: float
    start_s: float  # of its segment
    end_s: float
    step: int  # its step (Timeline.steps)
    line: Optional[int]  # the program's line of its step


def played_crashes(material):
    """The crashes a Material has found, in time order (PlayedCrash)."""
    line = material.line
    moving = [k for k, s in enumerate(line.steps) if s.count]  # the steps with segments, in order
    firsts = [line.steps[k].first for k in moving]
    result = []
    for (kind, segment), volume in material.crashes.items():
        step = moving[max(bisect.bisect_right(firsts, segment) - 1, 0)]
        start = float(line.starts[segment])
        result.append(PlayedCrash(kind, segment, volume, start, start + float(line.durations[segment]), step, line.steps[step].line))
    return sorted(result, key=lambda c: (c.segment, c.kind))


def fresh_cut(timeline, bounds, tools, t, resolution=250):
    """The stock at time t cut from the start in one go (for tests and to
    compare)."""
    return Material(timeline, bounds, tools, resolution, snapshot_segments=10**9).cut_to(t)


def kept_times(material):
    """The times of the copies of the stock kept (sorted)."""
    line = material.line
    return sorted(float(line.starts[k]) if k < len(line.segments) else line.total_s for k in material._kept)

