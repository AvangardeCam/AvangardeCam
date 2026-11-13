# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Slot milling (Dutch: slobgat): a straight slot, two half circles joined
by two parallel walls, as wide as the tool or wider (the user's design,
2026-10-22). The slots are picked in the model (engine.slot), later in a
sketch; slots along an arc come later.

On each Z level, from the top:
- the tool ramps down to the level going to and fro along the slot's
  centre line, between the centres of its ends (reciprocating, as the
  TNC's cycle 253 with Q366=1), no steeper than ramp_angle_deg, and goes
  once more along the whole centre line at the level; or (ramp
  RAMP_CONTOUR, the user, 2026-10-22) round the centre line as the slot's
  outline, no further from it than the tool's radius (no core is left in
  the middle), on straight lines and helical half circles, the same way
  round as the rough passes, and once more round at the level; a slot
  without room for it (ramp_offset) is ramped to and fro;
- rough passes around the centre line (the tool centre, R0), growing by
  no more than the step over, all evenly, out to finish_xy_mm from the
  walls; climbing with RL (the spindle turns clockwise, M3), else the
  other way round.
After all levels the walls are finished with radius compensation RL or
RR (the user: the operator corrects the size with DR), level by level:
the tool goes down in the slot, comes onto the middle of a wall on an
arc, goes once round and leaves on an arc (model.leads, as the contour).

Z levels as the contour's: full Z steps from the top of the slot and
the rest at the end; with finish_z_mm the rough levels stop that much
above the floor and a last level clears the floor.

A slot hardly wider than the tool (SAME_WIDTH_MM) is cut along its centre
only: no rough passes and no finishing pass (the TNC cannot run a radius
compensation inside an arc as small as the tool).

Plain Python: points are (x, y) in the setup's XY, heights its Z.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple, Optional

from avangardecam.model import leads, nc
from avangardecam.model.operations import APPROACH_Z_MM, MAX_CUTS, MAX_DEPTH_MM, SAFETY_MM

SAME_WIDTH_MM = 0.02  # a slot less than this wider than the tool is cut along its centre only
THROUGH_MM = 1.0  # under a through slot, as the drilling
RAMP_ANGLE_DEG = 5.0
MIN_LENGTH_MM = 0.01  # between the centres of the ends: shorter is a round hole, not a slot
# how the tool ramps down to a level
RAMP_TO_AND_FRO = "to_and_fro"
RAMP_CONTOUR = "contour"
RAMPS = (RAMP_TO_AND_FRO, RAMP_CONTOUR)
MIN_RAMP_OFFSET_MM = 0.1  # a ramp along the contour this close to the centre line goes to and fro instead
_EPSILON_MM = 1e-6


def _round(value):
    return round(value, 6) + 0.0


@dataclass(frozen=True)
class SlotMilling:
    """Slot milling (model.slot).

    depth_mm: of the floor, below the top of each slot (negative); None:
    from the model, the floor of the slot, or through_mm under a through
    slot. z_step_mm: full steps from the top, the rest at the end (None:
    the whole depth at once). step_over_percent: the most of the tool's
    diameter a rough pass grows by. finish_xy_mm and finish_z_mm: the rough
    passes leave this on the walls and the floor. ramp_angle_deg: the
    steepest the tool goes down along the slot. compensation: of the
    finishing pass, nc.LEFT (RL, climbing with M3) or nc.RIGHT (RR).
    lead_radius_mm: of its arcs on and off the wall; None: the tool goes
    down 0.5 mm or the finishing allowance clear of the wall (lead_radius).
    ramp: RAMP_TO_AND_FRO along the centre line or RAMP_CONTOUR round it.
    """

    depth_mm: Optional[float] = None
    through_mm: float = THROUGH_MM
    z_step_mm: Optional[float] = None
    step_over_percent: float = 50.0
    finish_xy_mm: float = 0.0
    finish_z_mm: float = 0.0
    ramp_angle_deg: float = RAMP_ANGLE_DEG
    compensation: str = nc.LEFT
    lead_radius_mm: Optional[float] = None
    ramp: str = RAMP_TO_AND_FRO

    KIND = "slot_milling"

    def validate(self):
        if self.depth_mm is not None and not -MAX_DEPTH_MM <= self.depth_mm < 0.0:
            raise ValueError(
                "The depth must be negative (below the top of the slots) and not deeper "
                "than {:g} mm, got {:g} mm".format(-MAX_DEPTH_MM, self.depth_mm)
            )
        if self.z_step_mm is not None and not 0.0 < self.z_step_mm <= MAX_DEPTH_MM:
            raise ValueError("The Z step must be larger than 0 mm, got {:g} mm".format(self.z_step_mm))
        if not 1.0 <= self.step_over_percent <= 100.0:
            raise ValueError("The step over must be 1 to 100 % of the tool, got {:g} %".format(self.step_over_percent))
        for text, value in (
            ("depth under through slots", self.through_mm),
            ("finishing allowance in XY", self.finish_xy_mm),
            ("finishing allowance in Z", self.finish_z_mm),
        ):
            if not 0.0 <= value <= MAX_DEPTH_MM:
                raise ValueError("The {} must be 0 mm or more, got {:g} mm".format(text, value))
        if not 0.0 < self.ramp_angle_deg <= 45.0:
            raise ValueError("The ramp angle must be more than 0° and at most 45°, got {:g}°".format(self.ramp_angle_deg))
        if self.compensation not in (nc.LEFT, nc.RIGHT):
            raise ValueError("unknown compensation of the finishing pass: {!r}".format(self.compensation))
        if self.lead_radius_mm is not None and not 0.0 < self.lead_radius_mm <= MAX_DEPTH_MM:
            raise ValueError("The approach radius must be larger than 0 mm, got {:g} mm".format(self.lead_radius_mm))
        if self.ramp not in RAMPS:
            raise ValueError("unknown ramp: {!r}".format(self.ramp))
        return self

    def lead_radius(self, tool_diameter_mm, width_mm):
        """Radius of the finishing pass's arcs on and off the wall: the
        user's, or the tool goes down 0.5 mm clear of the wall, or the
        finishing allowance when it is more (it does not cut into it), at
        most to the middle of the slot."""
        if self.lead_radius_mm is not None:
            return self.lead_radius_mm
        radius = tool_diameter_mm / 2.0
        return min(radius + max(leads.LEAD_CLEARANCE_MM, self.finish_xy_mm), width_mm / 2.0)

    def check(self, tool_diameter_mm, slot, depth_mm):
        """ValueError when a tool of that diameter cannot mill the slot
        (Slot) that deep (mm below its top, positive)."""
        width = slot.width_mm
        if tool_diameter_mm > width + _EPSILON_MM:
            raise ValueError("The tool (Ø{:g}) is wider than the slot ({:g} mm)".format(tool_diameter_mm, round(width, 3)))
        if self.finish_z_mm and self.finish_z_mm >= depth_mm - _EPSILON_MM:
            raise ValueError(
                "The finishing allowance in Z ({:g} mm) must be less than the depth of the slot ({:g} mm)".format(
                    self.finish_z_mm, round(depth_mm, 3)
                )
            )
        if as_wide_as_tool(tool_diameter_mm, width):
            if self.finish_xy_mm:
                raise ValueError(
                    "The slot ({:g} mm) is as wide as the tool (Ø{:g}): it is cut along its centre, "
                    "with no finishing allowance in XY".format(round(width, 3), tool_diameter_mm)
                )
            return self
        if self.finish_xy_mm > (width - tool_diameter_mm) / 2.0 + _EPSILON_MM:
            raise ValueError(
                "The finishing allowance in XY ({:g} mm) is more than the tool (Ø{:g}) leaves on the walls "
                "of the slot ({:g} mm) going along its centre".format(self.finish_xy_mm, tool_diameter_mm, round(width, 3))
            )
        lead = self.lead_radius(tool_diameter_mm, width)
        if not tool_diameter_mm / 2.0 + _EPSILON_MM < lead <= width / 2.0 + _EPSILON_MM:
            raise ValueError(
                "The approach radius ({:g} mm) must be more than the tool's radius ({:g} mm) and at most "
                "half the slot ({:g} mm)".format(lead, tool_diameter_mm / 2.0, round(width / 2.0, 3))
            )
        return self

    def levels(self, top_mm, floor_mm):
        """Z levels of the rough passes, from the top: full Z steps down
        from top_mm, the floor raised by finish_z_mm, and with it the floor
        itself (a last level that clears the floor)."""
        bottom = _round(floor_mm + self.finish_z_mm)
        found = [bottom]
        if self.z_step_mm is not None:
            k = 1
            while top_mm - k * self.z_step_mm > bottom + _EPSILON_MM:
                found.insert(-1, _round(top_mm - k * self.z_step_mm))
                k += 1
        if self.finish_z_mm:
            found.append(_round(floor_mm))
        return found

    def wall_levels(self, top_mm, floor_mm):
        """Z levels of the finishing pass: those of the rough passes, the
        floor instead of the level above it."""
        found = self.levels(top_mm, floor_mm)
        return found[:-2] + found[-1:] if self.finish_z_mm else found

    def step_mm(self, tool_diameter_mm):
        return tool_diameter_mm * self.step_over_percent / 100.0

    def rough_offsets(self, tool_diameter_mm, width_mm):
        """Distances of the rough passes' tool centre from the centre line,
        growing evenly by no more than the step over, out to finish_xy_mm
        from the walls. Without an allowance the last one is the finishing
        pass's, so it is left to it."""
        if as_wide_as_tool(tool_diameter_mm, width_mm):
            return []
        widest = (width_mm - tool_diameter_mm) / 2.0 - self.finish_xy_mm
        if widest <= _EPSILON_MM:
            return []
        count = max(1, int(math.ceil(widest / self.step_mm(tool_diameter_mm) - 1e-9)))
        found = [widest * k / count for k in range(1, count + 1)]
        return found if self.finish_xy_mm else found[:-1]


    def ramp_offset(self, tool_diameter_mm, width_mm):
        """Distance of the tool centre from the centre line on a ramp along
        the contour: the tool's radius (no core is left in the middle), less
        where it would cut into the finishing allowance. None: the ramp goes
        to and fro (chosen so, or less than MIN_RAMP_OFFSET_MM of room)."""
        if self.ramp != RAMP_CONTOUR or as_wide_as_tool(tool_diameter_mm, width_mm):
            return None
        offset = min(tool_diameter_mm / 2.0, (width_mm - tool_diameter_mm) / 2.0 - self.finish_xy_mm)
        return offset if offset > MIN_RAMP_OFFSET_MM - _EPSILON_MM else None


    def passes(self, tool_diameter_mm, width_mm):
        """(ramp_offset, the rough offsets beyond it): a ramp along the
        contour cuts the passes inside its last turn."""
        ramp = self.ramp_offset(tool_diameter_mm, width_mm)
        offsets = self.rough_offsets(tool_diameter_mm, width_mm)
        if ramp is not None:
            offsets = [offset for offset in offsets if offset > ramp + _EPSILON_MM]
        return ramp, offsets


def as_wide_as_tool(tool_diameter_mm, width_mm):
    """The slot is cut along its centre only."""
    return width_mm - tool_diameter_mm < SAME_WIDTH_MM - _EPSILON_MM


class Slot(NamedTuple):
    """A straight slot in the setup's XY: the centres of its two ends and its width."""

    start: tuple
    end: tuple
    width_mm: float

    def length_mm(self):
        """Between the centres of the ends."""
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    def axes(self):
        """(u along the slot from start to end, n on its left)."""
        length = self.length_mm()
        if length < MIN_LENGTH_MM:
            raise ValueError("The ends of the slot are {:g} mm apart; that is a round hole".format(round(length, 4)))
        u = ((self.end[0] - self.start[0]) / length, (self.end[1] - self.start[1]) / length)
        return u, (-u[1], u[0])

    def middle(self):
        return ((self.start[0] + self.end[0]) / 2.0, (self.start[1] + self.end[1]) / 2.0)


class SlotCut(NamedTuple):
    """A slot to mill and its heights in the setup's Z: the top of its
    walls and the floor the tool goes down to."""

    slot: Slot
    top: float
    floor: float


def _plus(p, v, k):
    return (p[0] + v[0] * k, p[1] + v[1] * k)


def ring(slot, offset_mm, at_end, clockwise):
    """(start, moves) of the tool once round the centre line at offset_mm
    from it, from beside the end where the tool is (at_end: the slot's
    end, else its start), counterclockwise (climbing with M3) or clockwise.
    Moves: ("line", point) or ("arc", point, centre, clockwise)."""
    u, n = slot.axes()
    side = -1.0 if not clockwise else 1.0  # counterclockwise: along +u on the right of the centre line
    a, b = slot.start, slot.end
    # once round from beside the start, along +u
    start = _plus(a, n, side * offset_mm)
    loop = [
        ("line", _plus(b, n, side * offset_mm)),
        ("arc", _plus(b, n, -side * offset_mm), b, clockwise),
        ("line", _plus(a, n, -side * offset_mm)),
        ("arc", start, a, clockwise),
    ]
    if at_end:
        start, loop = loop[0][1], loop[1:] + loop[:1]
    return start, loop


def finishing(slot, offset_mm, lead_mm, side):
    """(lead centre, moves) of the finishing pass, the tool at offset_mm
    from the centre line (the wall for the program, else where its centre
    runs) and arcs of lead_mm on and off it: from the lead centre straight
    to the arc, onto the middle of a wall, once round, off on an arc and
    back to the lead centre. side: of the tool seen along its way, nc.LEFT
    (RL: counterclockwise, the wall on its right) or nc.RIGHT."""
    u, n = slot.axes()
    clockwise = side == nc.RIGHT
    _start, loop = ring(slot, offset_mm, False, clockwise)
    # the middle of the first wall: the loop's first line split in two
    point = _plus(slot.middle(), n, (1.0 if clockwise else -1.0) * offset_mm)
    centre, arc_start = leads.lead_in(point, u, side, lead_mm)
    _centre, arc_end = leads.lead_out(point, u, side, lead_mm)
    turn = leads.clockwise(side)
    moves = [("line", arc_start), ("arc", point, centre, turn)]
    moves += [loop[0]] + loop[1:] + [("line", point)]
    moves += [("arc", arc_end, centre, turn), ("line", centre)]
    return centre, moves


def ramp(slot, at_end, top_mm, level_mm, angle_deg):
    """(moves, at_end) of the tool ramping down from top_mm to level_mm
    to and fro along the centre line, no steeper than angle_deg, from the
    end where it is, then once more along the centre line at the level.
    Moves: ("line", (x, y), z); at_end: where it ends."""
    length = slot.length_mm()
    drop = top_mm - level_mm
    strokes = max(1, int(math.ceil(drop / (length * math.tan(math.radians(angle_deg))) - 1e-9)))
    if strokes > MAX_CUTS:
        raise ValueError("The ramp needs {} strokes along the slot (at most {}); take a smaller Z step or a steeper ramp".format(strokes, MAX_CUTS))  # fmt: skip
    moves = []
    for k in range(1, strokes + 2):  # the last one at the level
        at_end = not at_end
        z = level_mm if k > strokes else top_mm - drop * k / strokes
        moves.append(("line", slot.end if at_end else slot.start, _round(z)))
    return moves, at_end


def contour_ramp(slot, offset_mm, at_end, clockwise, top_mm, level_mm, angle_deg):
    """(start, moves) of the tool ramping down from top_mm to level_mm
    going round the centre line at offset_mm (ring), from beside the end
    where it is, no steeper than angle_deg, whole turns alike, then once
    more round at the level. Moves: ("line", point, z) or ("arc", point,
    centre, clockwise, z); an arc going down is a helix."""
    start, loop = ring(slot, offset_mm, at_end, clockwise)
    lengths = []
    point = start
    for move in loop:
        lengths.append(math.pi * offset_mm if move[0] == "arc" else math.hypot(move[1][0] - point[0], move[1][1] - point[1]))  # fmt: skip
        point = move[1]
    turn = sum(lengths)
    drop = top_mm - level_mm
    turns = max(1, int(math.ceil(drop / (turn * math.tan(math.radians(angle_deg))) - 1e-9)))
    if turns * len(loop) > MAX_CUTS:
        raise ValueError("The ramp needs {} turns round the slot; take a smaller Z step or a steeper ramp".format(turns))  # fmt: skip
    moves = []
    done = 0.0
    for k in range(turns):
        for move, length in zip(loop, lengths):
            done += length
            z = level_mm if k == turns - 1 and move is loop[-1] else top_mm - drop * done / (turn * turns)
            moves.append(move + (_round(z),))
    moves += [move + (level_mm,) for move in loop]
    return start, moves


def moves(milling, cuts, tool_diameter_mm, feed_z_mm_min, feed_xy_mm_min, safe_z, approach_z=None, program=True):
    """The tool's moves (nc.Move) of a slot milling (SlotMilling) of the
    slots (SlotCut) in their order.

    program: the finishing pass along the walls with the radius
    compensation (the program); else where the tool centre goes, a radius
    in from them (FreeCAD's path). The rest is the tool centre either way."""
    radius = tool_diameter_mm / 2.0
    approach = max(APPROACH_Z_MM if approach_z is None else approach_z, safe_z)
    result = []
    position = [None, None, None]

    def add(kind, x, y, z, feed=None, centre=None, clockwise=False, compensation=None):
        if kind != nc.ARC and position == [x, y, z] and compensation is None:
            return
        result.append(nc.Move(kind, x, y, z, feed, centre, clockwise, compensation))
        position[:] = [x, y, z]

    def go(found, z, feed, compensation=None):
        for move in found:
            if move[0] == "line":
                add(nc.LINE, move[1][0], move[1][1], z, feed, compensation=compensation)
            else:
                _kind, end, centre, clockwise = move
                add(nc.ARC, end[0], end[1], z, feed, centre, clockwise, compensation)

    def down(x, y, z):
        """Rapid to 2 mm over z where the tool is (in the slot cut already), then the Z feed."""
        if z + SAFETY_MM < position[2]:
            add(nc.RAPID, x, y, z + SAFETY_MM)
        add(nc.LINE, x, y, z, feed_z_mm_min)

    for cut in cuts:
        slot = cut.slot
        clockwise = milling.compensation == nc.RIGHT
        levels = milling.levels(cut.top, cut.floor)
        round_ramp, offsets = milling.passes(tool_diameter_mm, slot.width_mm)
        if len(levels) * (len(offsets) + 2) > MAX_CUTS:
            raise ValueError("The slot has too many passes; take a larger step over or Z step.")
        x, y = slot.start if round_ramp is None else ring(slot, round_ramp, False, clockwise)[0]
        if position[2] is None:
            add(nc.RAPID, x, y, approach)
        else:
            add(nc.RAPID, position[0], position[1], max(safe_z, position[2]))
            add(nc.RAPID, x, y, position[2])
        add(nc.RAPID, x, y, cut.top + SAFETY_MM)
        add(nc.LINE, x, y, cut.top, feed_z_mm_min)
        above, at_end = cut.top, False
        for level in levels:
            if round_ramp is None:
                found, at_end = ramp(slot, at_end, above, level, milling.ramp_angle_deg)
                for _kind, (x, y), z in found[:-1]:
                    add(nc.LINE, x, y, z, feed_z_mm_min)
                add(nc.LINE, found[-1][1][0], found[-1][1][1], level, feed_xy_mm_min)
            else:
                start, found = contour_ramp(slot, round_ramp, at_end, clockwise, above, level, milling.ramp_angle_deg)
                add(nc.LINE, start[0], start[1], above, feed_xy_mm_min)  # out from where it is, in what is cut
                for k, move in enumerate(found):
                    feed = feed_xy_mm_min if k >= len(found) - 4 else feed_z_mm_min  # the last turn at the level
                    if move[0] == "line":
                        add(nc.LINE, move[1][0], move[1][1], move[2], feed)
                    else:
                        add(nc.ARC, move[1][0], move[1][1], move[4], feed, move[2], move[3])
            for offset in offsets:
                start, loop = ring(slot, offset, at_end, clockwise)
                add(nc.LINE, start[0], start[1], level, feed_xy_mm_min)
                go(loop, level, feed_xy_mm_min)
            if round_ramp is None:
                end = slot.end if at_end else slot.start
                add(nc.LINE, end[0], end[1], level, feed_xy_mm_min)  # back on the centre line, in what is cut
            above = level
        if not as_wide_as_tool(tool_diameter_mm, slot.width_mm):
            lead = milling.lead_radius(tool_diameter_mm, slot.width_mm)
            compensation = milling.compensation if program else None
            wall = slot.width_mm / 2.0 if program else slot.width_mm / 2.0 - radius
            centre, found = finishing(slot, wall, lead if program else lead - radius, milling.compensation)
            add(nc.RAPID, position[0], position[1], cut.top + SAFETY_MM)
            add(nc.RAPID, centre[0], centre[1], cut.top + SAFETY_MM)
            for level in milling.wall_levels(cut.top, cut.floor):
                down(centre[0], centre[1], level)
                go(found[:-1], level, feed_xy_mm_min, compensation)
                go(found[-1:], level, feed_xy_mm_min)  # back to the lead centre: R0
        add(nc.RAPID, position[0], position[1], max(safe_z, cut.top + SAFETY_MM))
    return tuple(result)
