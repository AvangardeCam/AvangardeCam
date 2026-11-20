# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The cutting data of an operation: the spindle speed and feeds it runs with.

A tool brings its own (the tool library's variant, kept by the setup's tool
controller, shared by every operation with that tool). An operation may set
any of them to its own value; the others follow the tool, also when the
tool's values change later.

The paths are made with the tool's feeds; the NC program (and what runs it:
Simulate, Verify, the cycle time) takes the operation's own: feeds() puts
them on the moves, the tool's XY feed becoming the own XY feed and its Z
feed the own Z feed.

Vc (cutting speed) and fz (feed per tooth) are shown to check the values.
"""

import dataclasses
import math
from dataclasses import dataclass
from typing import Optional

FIELDS = ("spindle_rpm", "feed_xy_mm_min", "feed_z_mm_min")
SAME = 0.01  # rpm or mm/min: the same value (feeds go through mm/s in FreeCAD)


@dataclass(frozen=True)
class CuttingData:
    """An operation's own values; None: the tool's."""

    spindle_rpm: Optional[float] = None
    feed_xy_mm_min: Optional[float] = None
    feed_z_mm_min: Optional[float] = None

    def validate(self):
        for name in FIELDS:
            value = getattr(self, name)
            if value is not None and not value > 0:
                raise ValueError("{} must be > 0".format(name.replace("_", " ")))
        return self

    def empty(self):
        return all(getattr(self, name) is None for name in FIELDS)


NONE = CuttingData()


def own(tool, wanted):
    """CuttingData of the values (rpm, feed XY, feed Z) that differ from the
    tool's: the ones the operation keeps; None for the same value or none."""
    result = {}
    for name, value in zip(FIELDS, wanted):
        mine = getattr(tool, name, None) if tool is not None else None
        same = value is None or (mine is not None and abs(value - mine) < SAME)
        result[name] = None if same else float(value)
    return CuttingData(**result).validate()


def applied(tool, data):
    """The tool (model.tools.Tool or model.nc.Tool) with the operation's own
    values in place of its own."""
    if tool is None or data is None or data.empty():
        return tool
    return dataclasses.replace(tool, **{name: getattr(data, name) for name in FIELDS if getattr(data, name) is not None})


def feeds(moves, old, new):
    """The moves (model.nc.Move) of a path made with tool old's feeds, with
    tool new's: old's XY feed becomes new's XY feed, its Z feed new's Z
    feed. When old has one feed for both, a move only along Z gets the Z
    feed. Other feeds stay."""
    xy = (old.feed_xy_mm_min, new.feed_xy_mm_min)
    z = (old.feed_z_mm_min, new.feed_z_mm_min)
    if xy[0] == xy[1] and z[0] == z[1]:
        return tuple(moves)
    both = xy[0] is not None and z[0] is not None and abs(xy[0] - z[0]) < SAME
    result = []
    position = [None, None, None]
    for move in moves:
        feed = move.feed_mm_min
        if feed is not None:
            is_xy = xy[0] is not None and abs(feed - xy[0]) < SAME
            is_z = z[0] is not None and abs(feed - z[0]) < SAME
            if both and is_xy:
                along_z = all(end is None or start is None or abs(end - start) < 1e-9 for start, end in zip(position[:2], (move.x, move.y)))  # fmt: skip
                feed = z[1] if along_z else xy[1]
            elif is_xy:
                feed = xy[1]
            elif is_z:
                feed = z[1]
            if feed != move.feed_mm_min:
                move = move._replace(feed_mm_min=feed)
        for axis, value in enumerate((move.x, move.y, move.z)):
            if value is not None:
                position[axis] = value
        result.append(move)
    return tuple(result)


def operation(op, data):
    """A model.nc.Operation made with its tool's values, run with the
    operation's own (data): the tool, the moves' feeds and a drilling
    cycle's (Q206 the XY feed, Q253 the Z feed, as the tool's)."""
    if data is None or data.empty():
        return op
    tool = applied(op.tool, data)
    cycle = op.cycle
    if cycle is not None:
        cycle = dataclasses.replace(
            cycle, feed_mm_min=tool.feed_xy_mm_min, preposition_feed_mm_min=tool.feed_z_mm_min
        )
    return dataclasses.replace(op, tool=tool, moves=feeds(op.moves, op.tool, tool), cycle=cycle)


def vc_m_min(diameter_mm, spindle_rpm):
    """Cutting speed at the tool's diameter, m/min; None without both."""
    if not diameter_mm or not spindle_rpm:
        return None
    return math.pi * diameter_mm * spindle_rpm / 1000.0


def fz_mm(feed_mm_min, spindle_rpm, flutes):
    """Feed per tooth, mm; None without all three."""
    if not feed_mm_min or not spindle_rpm or not flutes:
        return None
    return feed_mm_min / (spindle_rpm * flutes)
