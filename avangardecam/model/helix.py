# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Helix milling of round holes (the user, 2026-10-26): an end mill goes
down a helix and mills the hole without drilling it, or makes a hole
drilled too small bigger. The shop likes it for toleranced holes: the
radius compensation is on from the start (the operator corrects the size
with DR) and the tool leaves no mark where it comes onto the wall.

As the shop's programs mill a hole (a real program of the shop: a
Ø4.5 hole 16 deep with a Ø3 end mill): over the hole, down to its top
with the Z feed, straight out from the centre with RL to a point the
tool's radius and LEAD_START_MM from the centre, a half circle onto the
wall touching it (the tool centre comes from LEAD_START_MM beside the
hole's centre), down a helix in equal half turns counterclockwise
(CC + CP IPA+180. IZ-0.131 DR+), no deeper than half the pitch each,
once round at the depth (two half circles), a half circle off the wall
back across the hole and back to the centre (R0); 10 mm above the top
to the next hole.

The passes (the user's choices):
- the rough passes leave finish_xy_mm on the wall and a last pass takes
  it: two helices; one without the allowance;
- offset_xy_mm: the hole that much bigger (negative: smaller), for a fit;
- a hole the tool cannot clear in one helix, or one drilled before
  (predrilled_mm), is widened in passes growing evenly by no more than
  the step over; the first leaves no core in the middle;
- method HELIX: every pass a helix from the top; HELIX_CONTOUR: the first
  pass a helix, the others (widening, finishing) circles at Z-Depth or on
  Z steps from the top, on and off the wall on the same half circles;
- down to Z-Depth: the user's below the top of each hole, or from the
  model (a through hole: through_mm under it).

Plain Python: points are (x, y) in the setup's XY, heights its Z.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple, Optional

from avangardecam.model import nc
from avangardecam.model.operations import APPROACH_Z_MM, MAX_CUTS, MAX_DEPTH_MM, SAFETY_MM

THROUGH_MM = 1.0  # under a through hole, as the drilling
BETWEEN_MM = 10.0  # above the holes' top, from one hole to the next (the shop's programs)
LEAD_START_MM = 0.1  # the tool centre this far beside the hole's centre where it comes onto the wall (the shop's programs)
# the pitch by default: the tool's diameter x tan 5°, 0.2625 for Ø3 (the shop's
# program goes 16 mm down a Ø4.5 hole in 61 turns), to 4 decimals as shown
PITCH_ANGLE_DEG = 5.0
MIN_ROOM_MM = 0.01  # the wall at least this outside the tool: the TNC cannot compensate a circle as small as the tool
HELIX = "helix"  # every pass a helix
HELIX_CONTOUR = "helix_contour"  # a helix, then circles
METHODS = (HELIX, HELIX_CONTOUR)
_EPSILON_MM = 1e-6


def _round(value):
    return round(value, 6) + 0.0


@dataclass(frozen=True)
class HelixMilling:
    """Helix milling of holes (model.helix).

    depth_mm: Z-Depth below the top of each hole (negative); None: from the
    model, the end of the hole, or through_mm under a through hole.
    pitch_mm: the most the helix goes down in a turn; None: auto_pitch of
    the tool. finish_xy_mm: the rough passes leave this on the wall, a last
    pass takes it (0: no finishing pass). offset_xy_mm: the hole this much
    bigger than its circle (negative: smaller). step_over_percent: the most
    of the tool's diameter a pass grows by. predrilled_mm: Ø of a hole
    drilled before (0: none, the tool mills it from solid). method: HELIX
    or HELIX_CONTOUR. z_step_mm: of the circles of HELIX_CONTOUR, full
    steps from the top, the rest at Z-Depth (None: at Z-Depth only).
    compensation: nc.LEFT (RL, counterclockwise: climbing with M3, as
    the shop's programs) or nc.RIGHT (RR, clockwise).
    """

    depth_mm: Optional[float] = None
    through_mm: float = THROUGH_MM
    pitch_mm: Optional[float] = None
    finish_xy_mm: float = 0.1
    offset_xy_mm: float = 0.0
    step_over_percent: float = 50.0
    predrilled_mm: float = 0.0
    method: str = HELIX
    z_step_mm: Optional[float] = None
    compensation: str = nc.LEFT

    KIND = "helix_milling"

    def validate(self):
        if self.depth_mm is not None and not -MAX_DEPTH_MM <= self.depth_mm < 0.0:
            raise ValueError(
                "The depth must be negative (below the top of the holes) and not deeper "
                "than {:g} mm, got {:g} mm".format(-MAX_DEPTH_MM, self.depth_mm)
            )
        if self.pitch_mm is not None and not 0.0 < self.pitch_mm <= MAX_DEPTH_MM:
            raise ValueError("The pitch must be larger than 0 mm, got {:g} mm".format(self.pitch_mm))
        if self.z_step_mm is not None and not 0.0 < self.z_step_mm <= MAX_DEPTH_MM:
            raise ValueError("The Z step must be larger than 0 mm, got {:g} mm".format(self.z_step_mm))
        for text, value in (
            ("depth under through holes", self.through_mm),
            ("finishing allowance in XY", self.finish_xy_mm),
            ("drilled diameter", self.predrilled_mm),
        ):
            if not 0.0 <= value <= MAX_DEPTH_MM:
                raise ValueError("The {} must be 0 mm or more, got {:g} mm".format(text, value))
        if not -MAX_DEPTH_MM <= self.offset_xy_mm <= MAX_DEPTH_MM:
            raise ValueError("The XY offset must be within {:g} mm, got {:g} mm".format(MAX_DEPTH_MM, self.offset_xy_mm))
        if not 1.0 <= self.step_over_percent <= 100.0:
            raise ValueError("The step over must be 1 to 100 % of the tool, got {:g} %".format(self.step_over_percent))
        if self.method not in METHODS:
            raise ValueError("unknown way of the passes: {!r}".format(self.method))
        if self.compensation not in (nc.LEFT, nc.RIGHT):
            raise ValueError("unknown compensation: {!r}".format(self.compensation))
        return self

    def pitch(self, tool_diameter_mm):
        """The most the helix goes down in a turn: the user's, else auto_pitch."""
        return self.pitch_mm if self.pitch_mm is not None else auto_pitch(tool_diameter_mm)

    def wall_mm(self, hole_diameter_mm):
        """Radius of the finished hole, with the XY offset: the program's circle."""
        return hole_diameter_mm / 2.0 + self.offset_xy_mm

    def walls(self, tool_diameter_mm, hole_diameter_mm):
        """Radii of the passes' circles, where the tool's edge cuts (the
        program's; the tool centre runs its radius inside), from the first:
        the rough passes out to finish_xy_mm from the wall, growing evenly
        by no more than the step over from the drilled hole (or from the
        tool's own radius: the tool in the middle), the first one leaving
        no core in the middle; then the wall."""
        radius = tool_diameter_mm / 2.0
        wall = self.wall_mm(hole_diameter_mm)
        rough = wall - self.finish_xy_mm
        drilled = self.predrilled_mm / 2.0
        start = max(drilled, radius)
        step = tool_diameter_mm * self.step_over_percent / 100.0
        if drilled < radius:
            step = min(step, radius + drilled)  # it cuts out to rough - D: nothing left inside
        found = []
        if rough > start + _EPSILON_MM:
            count = int(math.ceil((rough - start) / step - 1e-9))
            found = [_round(start + (rough - start) * k / count) for k in range(1, count + 1)]
        if self.finish_xy_mm or not found:
            found.append(_round(wall))
        return found

    def check(self, tool_diameter_mm, hole_diameter_mm, depth_mm, cutting_length_mm=None):
        """ValueError when a tool of that diameter (and cutting length, when
        known) cannot mill a hole of that diameter that deep (mm below its
        top, positive)."""
        radius = tool_diameter_mm / 2.0
        wall = self.wall_mm(hole_diameter_mm)
        size = "Ø{:g}".format(round(2.0 * wall, 3))
        if wall < radius + MIN_ROOM_MM:
            raise ValueError("The tool (Ø{:g}) is too big for a {} hole".format(tool_diameter_mm, size))
        if self.predrilled_mm >= 2.0 * wall - _EPSILON_MM:
            raise ValueError("The hole is drilled Ø{:g} already, not smaller than {}".format(self.predrilled_mm, size))
        rough = wall - self.finish_xy_mm
        if self.finish_xy_mm and rough < radius + MIN_ROOM_MM and self.predrilled_mm / 2.0 < rough - _EPSILON_MM:
            raise ValueError(
                "The finishing allowance in XY ({:g} mm) leaves no room for a rough pass of the tool (Ø{:g}) "
                "in a {} hole: at most {:g} mm".format(
                    self.finish_xy_mm, tool_diameter_mm, size, max(0.0, round(wall - radius - MIN_ROOM_MM, 3))
                )
            )
        if depth_mm <= _EPSILON_MM:
            raise ValueError("The hole must go down from its top, got {:g} mm".format(depth_mm))
        pitch = self.pitch(tool_diameter_mm)
        if cutting_length_mm and pitch > cutting_length_mm + _EPSILON_MM:
            raise ValueError(
                "The pitch ({:g} mm) is more than the tool's cutting length ({:g} mm)".format(round(pitch, 4), cutting_length_mm)  # fmt: skip
            )
        walls = self.walls(tool_diameter_mm, hole_diameter_mm)
        helices = len(walls) if self.method == HELIX else 1
        if helices * half_turns(depth_mm, pitch) > MAX_CUTS:
            raise ValueError("The helix needs too many turns (at most {} half turns); take a larger pitch".format(MAX_CUTS))  # fmt: skip
        if self.method == HELIX_CONTOUR:
            levels = self.levels(0.0, -depth_mm)
            if (len(walls) - 1) * len(levels) > MAX_CUTS:
                raise ValueError("The hole has too many circles; take a larger step over or Z step")
            deepest = max(a - b for a, b in zip([0.0] + levels, levels))
            if len(walls) > 1 and cutting_length_mm and deepest > cutting_length_mm + _EPSILON_MM:
                raise ValueError(
                    "A circle cuts {:g} mm deep, more than the tool's cutting length ({:g} mm); enter a Z step".format(
                        round(deepest, 3), cutting_length_mm
                    )
                )
        return self

    def levels(self, top_mm, bottom_mm):
        """Z levels of the circles of HELIX_CONTOUR, from the top: full Z
        steps down from top_mm and the rest at bottom_mm (Z-Depth)."""
        found = [_round(bottom_mm)]
        if self.z_step_mm is not None:
            k = 1
            while top_mm - k * self.z_step_mm > bottom_mm + _EPSILON_MM:
                found.insert(-1, _round(top_mm - k * self.z_step_mm))
                k += 1
        return found


def auto_pitch(tool_diameter_mm):
    """The pitch of a helix by default: the tool's diameter x tan 5°, to 4 decimals."""
    return round(tool_diameter_mm * math.tan(math.radians(PITCH_ANGLE_DEG)), 4)


def half_turns(depth_mm, pitch_mm):
    """How many equal half turns take the helix depth_mm down, none deeper
    than half the pitch."""
    return max(1, int(math.ceil(depth_mm / (pitch_mm / 2.0) - 1e-9)))


class HelixHole(NamedTuple):
    """A hole to mill, in the setup's coordinates: the centre of its top,
    Z-Depth and its diameter (without the XY offset)."""

    x: float
    y: float
    top: float
    bottom: float
    diameter_mm: float


def moves(milling, holes, tool_diameter_mm, feed_z_mm_min, feed_xy_mm_min, approach_z=None, program=True):
    """The tool's moves (nc.Move) of a helix milling (HelixMilling) of the
    holes (HelixHole) in their order.

    program: the circles where the tool's edge cuts, with the radius
    compensation (the program); else where the tool centre goes, its
    radius inside (FreeCAD's path)."""
    radius = tool_diameter_mm / 2.0
    pitch = milling.pitch(tool_diameter_mm)
    clockwise = milling.compensation == nc.RIGHT
    side = milling.compensation if program else None
    approach = APPROACH_Z_MM if approach_z is None else approach_z
    result = []
    position = [None, None, None]

    def add(kind, x, y, z, feed=None, centre=None, compensation=None):
        result.append(nc.Move(kind, x, y, z, feed, centre, clockwise, compensation))
        position[:] = [x, y, z]

    def onto_wall(hole, wall, start, z):
        """Out from the centre with the compensation on and a half circle onto
        the wall at +X; the centre of the half circle."""
        lead = (hole.x + (wall - start) / 2.0, hole.y)
        add(nc.LINE, hole.x - start, hole.y, z, feed_xy_mm_min, compensation=side)
        add(nc.ARC, hole.x + wall, hole.y, z, feed_xy_mm_min, lead, side)

    def round_and_off(hole, wall, start, at_plus, z):
        """Once round on the wall (two half circles) from where the tool is
        (at_plus: +X, else -X), a half circle off it back across the hole,
        back to the centre with the compensation off."""
        here, there = (hole.x + wall, hole.x - wall) if at_plus else (hole.x - wall, hole.x + wall)
        add(nc.ARC, there, hole.y, z, feed_xy_mm_min, (hole.x, hole.y), side)
        add(nc.ARC, here, hole.y, z, feed_xy_mm_min, (hole.x, hole.y), side)
        away = hole.x - start if at_plus else hole.x + start
        add(nc.ARC, away, hole.y, z, feed_xy_mm_min, ((here + away) / 2.0, hole.y), side)
        add(nc.LINE, hole.x, hole.y, z, feed_xy_mm_min)

    def helix(hole, wall, start):
        onto_wall(hole, wall, start, hole.top)
        count = half_turns(hole.top - hole.bottom, pitch)
        for k in range(1, count + 1):
            x = hole.x - wall if k % 2 else hole.x + wall
            add(nc.ARC, x, hole.y, hole.top - (hole.top - hole.bottom) * k / count, feed_xy_mm_min, (hole.x, hole.y), side)  # fmt: skip
        round_and_off(hole, wall, start, count % 2 == 0, hole.bottom)

    def circles(hole, wall, start):
        for level in milling.levels(hole.top, hole.bottom):
            if level > position[2] + _EPSILON_MM:
                add(nc.RAPID, hole.x, hole.y, level)  # up in the hole cut already
            elif level < position[2] - _EPSILON_MM:
                if level + SAFETY_MM < position[2]:
                    add(nc.RAPID, hole.x, hole.y, level + SAFETY_MM)
                add(nc.LINE, hole.x, hole.y, level, feed_z_mm_min)
            onto_wall(hole, wall, start, level)
            round_and_off(hole, wall, start, True, level)

    previous = None
    for hole in holes:
        if previous is None:
            add(nc.RAPID, hole.x, hole.y, max(approach, hole.top + SAFETY_MM))
        else:
            add(nc.RAPID, hole.x, hole.y, max(previous, hole.top) + BETWEEN_MM)
        add(nc.RAPID, hole.x, hole.y, hole.top + SAFETY_MM)
        add(nc.LINE, hole.x, hole.y, hole.top, feed_z_mm_min)
        start = radius + LEAD_START_MM if program else LEAD_START_MM
        for k, wall in enumerate(milling.walls(tool_diameter_mm, hole.diameter_mm)):
            wall = wall if program else wall - radius
            if k == 0 or milling.method == HELIX:
                if k:
                    add(nc.RAPID, hole.x, hole.y, hole.top)  # up in the hole cut already
                helix(hole, wall, start)
            else:
                circles(hole, wall, start)
        add(nc.RAPID, hole.x, hole.y, hole.top + BETWEEN_MM)
        previous = hole.top
    return tuple(result)
