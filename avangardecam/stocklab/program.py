# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""A program: operations, each a tool on a tool axis and its moves, in the
part's frame (the bridge in AvangardeCam turns a setup's path into it).
"""

from typing import NamedTuple

import numpy as np

from .cut import CHORD, arc_points, cut_line, cut_lines

# A rapid move taking less than this part of a cell is only touching.
TOUCH = 0.01

# The most feed moves cut at once.
BATCH = 5000


class Line:
    """Straight from `start` to `end` (the tool's tip); rapid: G0."""

    def __init__(self, start, end, rapid=False):
        self.start = np.asarray(start, dtype=float)
        self.end = np.asarray(end, dtype=float)
        self.rapid = rapid


class Arc:
    """An arc or a helix (G2 / G3) around `center`, see cut.arc_points."""

    rapid = False

    def __init__(self, start, end, center, ccw=True):
        self.start = np.asarray(start, dtype=float)
        self.end = np.asarray(end, dtype=float)
        self.center = np.asarray(center, dtype=float)
        self.ccw = ccw


class Operation:
    def __init__(self, tool, axis, moves, name=""):
        self.tool = tool
        self.axis = axis
        self.moves = list(moves)
        self.name = name


class Collision(NamedTuple):
    """A rapid move that took material."""

    operation: int
    move: int
    volume: float


def segments(operation, chord):
    """The straight pieces of the operation's moves: (start, end, rapid,
    number of the move); arcs as chords no further than `chord` from them."""
    for number, move in enumerate(operation.moves):
        if isinstance(move, Arc):
            points = arc_points(operation.axis, move.start, move.end, move.center, move.ccw, chord)
            for a, b in zip(points, points[1:]):
                yield a, b, False, number
        else:
            yield move.start, move.end, move.rapid, number


def simulate(stock, operations):
    """Cut the operations in turn; returns the rapid moves that took
    material (Collision). The feed moves between two rapid moves are cut
    at once; a rapid move on its own, for its volume."""
    chord = CHORD * stock.spacing.min()
    touch = TOUCH * float(np.prod(stock.spacing))
    collisions = []
    for index, operation in enumerate(operations):
        rapid_taken = {}
        feed = []
        for a, b, rapid, number in segments(operation, chord):
            if not rapid:
                feed.append((a, b))
                if len(feed) == BATCH:
                    _cut_feed(stock, operation, feed)
                continue
            _cut_feed(stock, operation, feed)
            taken = cut_line(stock, operation.tool, operation.axis, a, b)
            if taken > touch:
                rapid_taken[number] = rapid_taken.get(number, 0.0) + taken
        _cut_feed(stock, operation, feed)
        collisions += [Collision(index, number, volume) for number, volume in sorted(rapid_taken.items())]
    return collisions


def _cut_feed(stock, operation, feed):
    """Cut the feed moves waiting in `feed` and empty it."""
    if feed:
        cut_lines(stock, operation.tool, operation.axis, [a for a, _ in feed], [b for _, b in feed])
        feed.clear()
