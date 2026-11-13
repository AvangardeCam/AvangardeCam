# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""What the machine runs into, found while the stock is cut (Play, Verify):

- RAPID: a rapid move (FMAX, G0) taking material;
- SHANK: the tool's shank or neck taking material: the part of the tool
  above its cutting length, which does not cut (a thread mill going
  deeper than its neck is long: its shank, wider than the thread, in the
  hole; an end mill deeper than its flutes).

The shank and the neck are as the simulation draws them
(model.playback.tool_profile): the neck as wide and as long as the tool
says, the shank from there up to the tool's length (two diameters more
without one), as wide as the shank (as the tool without one); only for a
tool whose cutting length is known (otherwise the whole tool may cut).

The moves are cut in order as one batch (stocklab.cut_lines), as fast as
the cutting alone; a move is cut on its own, to know what it took, only
when material is near enough to it to be in the way: on the rays along Z
of the stock within the tool part's radius from the move (as seen from
above: the rays it cuts), between the lowest and the highest the part
goes. Mostly nothing is (a rapid move above the stock, up and down in a
hole the tool has cut, a shank above the material), so there is nothing
to cut on its own. (With a cell's half diagonal more round it the walls of
such a hole were in the way: on the user's plate 2837 of 2965 rapid moves,
cut on their own 4 s more.) What it misses is less than a cell, between
the rays along Z. Where the tool is at the start of a move is the move
before's (it took it, or ran into it), so a move straight up or down
looks only where it goes: above the tool, below its tip. The moves cut
together wait (they only take material), so a move in the way of what is
there now is looked at again once they are cut, and is cut on its own
only when it still is (up and down in the hole of a helix cut just
before).

Plain Python with numpy, no FreeCAD.
"""

from typing import NamedTuple

import numpy as np

from avangardecam import stocklab
from avangardecam.model import verify as model_verify  # it imports this module
from avangardecam.stocklab import program as stock_program
from avangardecam.stocklab import tools as stock_tools
from avangardecam.stocklab.cut import CHORD

RAPID = "rapid"
SHANK = "shank"

# a shank as long as the tool without its length: two diameters over the
# cutting length (as model.playback.tool_profile draws it)
SHANK_DIAMETERS = 2.0
# what the shank takes is measured with it this many cells narrower (it
# cuts as wide as it is): a shank as wide as the cutting part going along
# after it takes what the chords of the arcs leave, and is in nothing
SHANK_SLACK_CELLS = 0.1

_SAME = 1e-9


class Crash(NamedTuple):
    kind: str  # RAPID or SHANK
    key: object  # the move's (as given to cut)
    volume_mm3: float


def shank_tool(tool):
    """The parts of a tool (model.tools.Tool) above its cutting length,
    its neck and its shank, as a stocklab tool (from the tip as the
    cutting part), or None: no tool, or no cutting length known."""
    if tool is None or not tool.cutting_length_mm or not tool.diameter_mm:
        return None
    d = tool.diameter_mm
    cutting = model_verify.stock_tool(tool).length
    length = tool.length_mm if tool.length_mm and tool.length_mm > cutting else cutting + SHANK_DIAMETERS * d
    parts, up = [], cutting
    neck_end = tool.neck_length_mm
    if tool.neck_diameter_mm and neck_end and cutting < neck_end < length:
        parts.append(stock_tools.Part([stock_tools.Line(cutting, neck_end, tool.neck_diameter_mm / 2.0)]))
        up = neck_end
    shank = tool.shank_diameter_mm or d
    parts.append(stock_tools.Part([stock_tools.Line(up, length, shank / 2.0)]))
    return stock_tools.Tool(parts, "shank")


def _top(stock):
    """The highest material of the stock (on its rays along Z), -inf: none."""
    return float(stock.rays[2].hi.max(initial=-np.inf))


def _in_the_way(stock, tool, a, b):
    """Is there material on the stock's rays along Z within the tool's
    radius (from the tip a to b, the tool from +Z) between the lowest and
    the highest it goes (more than a sliver above the lowest)?"""
    spacing = stock.spacing
    reach = tool.radius
    low = np.minimum(a, b) - reach
    high = np.maximum(a, b) + reach
    block = stock.block(2, low, high)
    if block is None:
        return False
    if abs(a[0] - b[0]) <= _SAME and abs(a[1] - b[1]) <= _SAME and a[2] != b[2]:
        # straight up: above the tool where it is; down: below it
        if b[2] > a[2]:
            bottom, top = a[2] + min(part.h1 for part in tool.parts), b[2] + tool.length
        else:
            bottom, top = b[2] + min(part.h0 for part in tool.parts), a[2] + max(part.h0 for part in tool.parts)
    else:
        bottom, top = min(a[2], b[2]) + min(part.h0 for part in tool.parts), max(a[2], b[2]) + tool.length
    bottom += stock.sliver
    lo = stock.rays[2].lo[block]
    hi = stock.rays[2].hi[block]
    has = np.any((lo < top) & (hi > bottom), axis=-1)
    if not has.any():
        return False
    # within the reach of the line from a to b, seen from above
    x = stock.lower[0] + (np.arange(block[0].start, block[0].stop) + 0.5) * spacing[0]
    y = stock.lower[1] + (np.arange(block[1].start, block[1].stop) + 0.5) * spacing[1]
    px, py = np.meshgrid(x - a[0], y - a[1], indexing="ij")
    dx, dy = b[0] - a[0], b[1] - a[1]
    along = dx * dx + dy * dy
    share = np.clip((px * dx + py * dy) / along, 0.0, 1.0) if along > _SAME else 0.0
    near = np.hypot(px - share * dx, py - share * dy) <= reach
    return bool(np.any(has & near))


def cut(stock, tool, shank, pieces):
    """Cut straight pieces of moves, in order, with the tool (from +Z) and
    its shank (shank_tool; None: none). pieces: (start, end, rapid, key),
    the pieces of one move one after another with its key. Returns the
    Crash found, one for each kind and move, in the order found."""
    touch = stock_program.TOUCH * float(np.prod(stock.spacing))
    top = _top(stock)  # material only goes: higher it never is
    narrow = None
    if shank is not None:
        slack = SHANK_SLACK_CELLS * float(stock.spacing.min())
        parts = [stock_tools.Part([stock_tools.Line(p.h0, p.h1, p.rmax - slack)]) for p in shank.parts if p.rmax > slack]
        narrow = stock_tools.Tool(parts, shank.name) if parts else None
    shank_low = min(part.h0 for part in shank.parts) if shank is not None else None
    found = {}
    starts, ends = [], []

    def flush():
        if starts:
            stocklab.cut_lines(stock, tool, "+Z", starts, ends)
            starts.clear()
            ends.clear()

    def in_the_way(part, a, b):
        """Material in the way of the part, the moves waiting cut first when it is."""
        if not _in_the_way(stock, part, a, b):
            return False
        if not starts:
            return True
        flush()
        return _in_the_way(stock, part, a, b)

    def crash(kind, key, taken):
        if taken > touch:
            found[(kind, key)] = found.get((kind, key), 0.0) + taken

    move, key = [], None
    for piece in list(pieces) + [None]:
        if move and (piece is None or piece[3] != key):
            # the shank after the move's cutting, all the move's pieces at once
            if shank is not None:
                near = [(a, b) for a, b in move if min(a[2], b[2]) + shank_low < top and in_the_way(shank, a, b)]
                if near:
                    flush()
                    a, b = [a for a, _ in near], [b for _, b in near]
                    if narrow is not None:
                        crash(SHANK, key, stocklab.cut_lines(stock, narrow, "+Z", a, b))
                    stocklab.cut_lines(stock, shank, "+Z", a, b)
            move = []
        if piece is None:
            break
        a, b, rapid, key = piece
        a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        move.append((a, b))
        if rapid and min(a[2], b[2]) < top and in_the_way(tool, a, b):
            flush()
            crash(RAPID, key, stocklab.cut_line(stock, tool, "+Z", a, b))
            continue
        starts.append(a)
        ends.append(b)
        if len(starts) >= stock_program.BATCH:
            flush()
    flush()
    return [Crash(kind, key, volume) for (kind, key), volume in found.items()]


class Found(NamedTuple):
    """A crash of an operation's move (Verify)."""

    kind: str
    operation: int  # index of the operation
    move: int  # index of its move
    volume: float


def simulate(stock, operations, shanks):
    """Cut the operations (stocklab.Operation, the tool from +Z) in turn,
    shanks[i] the shank of operations[i]'s tool (or None), as
    stocklab.simulate does; returns what they ran into (Found)."""
    chord = CHORD * stock.spacing.min()
    result = []
    for index, (operation, shank) in enumerate(zip(operations, shanks)):
        pieces = ((a, b, rapid, number) for a, b, rapid, number in stock_program.segments(operation, chord))
        for c in cut(stock, operation.tool, shank, pieces):
            result.append(Found(c.kind, index, c.key, c.volume_mm3))
    return result
