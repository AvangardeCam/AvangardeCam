# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The tool moves of an adaptive clearing (model.operations.Adaptive).

FreeCAD's Adaptive (libarea's Adaptive2d, engine.adaptive) works out how
the tool clears each area; an area is the same on several Z levels and
is worked out once (a Piece). The moves between are the shop's:
- the tool comes down over its first start to Z+20 (the spindle starts
  there), rapid to 2 mm above the stock, then with the Z feed;
- each Z level in turn, from the top, each area cut on it: rapid down to
  2 mm above where the tool cut the area before (or where its material
  starts), with the Z feed to there, then into a closed area on a helix
  in half turns (one more turn at the level clears its middle), or
  straight down beside the stock into an open one;
- over cleared floor rapid, lift_mm above the level; over uncut material
  up to the safe height; after each area up to the safe height.
"""

import math
from typing import NamedTuple, Optional, Tuple

from avangardecam.model import nc
from avangardecam.model.operations import APPROACH_Z_MM, SAFETY_MM

# how the tool goes along a path of a piece (FreeCAD: AdaptiveMotionType)
CUT = "cut"  # cutting, at the level
LINK = "link"  # over cleared floor, lift_mm above the level
UP = "up"  # over uncut material, at the safe height

_SAME_MM = 1e-6
_HELIX_MM = 0.01  # FreeCAD: no helix this small; the helix runs this much inside its start


class Piece(NamedTuple):
    """An area the tool clears, the same way on each of its levels."""

    levels: tuple  # Z, from the top
    top: float  # Z where its material starts above its first level
    helix: Optional[Tuple[float, float]]  # centre of the helix into it; None: in beside the stock
    start: Tuple[float, float]  # where its clearing starts
    paths: tuple  # (CUT, LINK or UP, ((x, y), ...)), in order


def helix_radius(piece):
    """Radius of a piece's helix, mm; 0 when it has none (FreeCAD's rule)."""
    if piece.helix is None:
        return 0.0
    radius = math.hypot(piece.start[0] - piece.helix[0], piece.start[1] - piece.helix[1])
    return radius - _HELIX_MM if radius > _HELIX_MM else 0.0


def half_turns(depth_mm, radius_mm, angle_deg):
    """(sweep in degrees, depth mm) of each arc of a helix going depth_mm down
    at angle_deg on radius_mm, in half turns; the last one shorter."""
    half = math.pi * radius_mm * math.tan(math.radians(angle_deg))
    full = int(math.floor(depth_mm / half + 1e-9))
    arcs = [(180.0, half)] * full
    rest = depth_mm - full * half
    if rest > 1e-6:
        arcs.append((180.0 * rest / half, rest))
    return arcs


class _Moves:
    def __init__(self, safe_z, approach_z, lift_mm, feed_z, feed_xy):
        self.safe_z, self.approach_z, self.lift_mm = safe_z, approach_z, lift_mm
        self.feed_z, self.feed_xy = feed_z, feed_xy
        self.result = []
        self.x = self.y = self.z = None

    def rapid(self, x=None, y=None, z=None):
        x = self.x if x is None else x
        y = self.y if y is None else y
        z = self.z if z is None else z
        if self._at(x, y, z):
            return
        self.result.append(nc.Move(nc.RAPID, x, y, z))
        self.x, self.y, self.z = x, y, z

    def line(self, x, y, z, feed):
        if self._at(x, y, z):
            return
        self.result.append(nc.Move(nc.LINE, x, y, z, feed))
        self.x, self.y, self.z = x, y, z

    def arc(self, centre, sweep, radius, z, feed):
        """Clockwise by sweep degrees around centre from where the tool is."""
        angle = math.atan2(self.y - centre[1], self.x - centre[0]) - math.radians(sweep)
        x, y = centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)
        self.result.append(nc.Move(nc.ARC, x, y, z, feed, centre, True))
        self.x, self.y, self.z = x, y, z

    def _at(self, x, y, z):
        return (
            self.x is not None
            and abs(self.x - x) < _SAME_MM
            and abs(self.y - y) < _SAME_MM
            and self.z is not None
            and abs(self.z - z) < _SAME_MM
        )

    def over(self, x, y, above):
        """Rapid over (x, y), then down to 2 mm over above (no higher than
        the safe height): the tool came first, else from the safe height."""
        if self.z is None:
            self.result.append(nc.Move(nc.RAPID, x, y, self.approach_z))
            self.x, self.y, self.z = x, y, self.approach_z
        else:
            self.rapid(z=max(self.z, self.safe_z))
            self.rapid(x, y)
        self.rapid(z=min(self.safe_z, above + SAFETY_MM, self.z))

    def piece(self, piece, level, above, helix_angle_deg):
        radius = helix_radius(piece)
        if radius > 0.0:
            centre = piece.helix
            self.over(centre[0] + radius, centre[1], above)
            self.line(self.x, self.y, above, self.feed_z)
            z = above
            for sweep, down in half_turns(above - level, radius, helix_angle_deg):
                z -= down
                self.arc(centre, sweep, radius, z, self.feed_z)
            for _half in range(2):  # a whole turn on the level clears the middle
                self.arc(centre, 180.0, radius, level, self.feed_xy)
        else:
            self.over(piece.start[0], piece.start[1], above)
            self.line(self.x, self.y, level, self.feed_z)
        for kind, points in piece.paths:
            if kind == CUT:
                if self.z > level + _SAME_MM:
                    if self.z > self.safe_z - _SAME_MM:  # after a way over uncut material
                        self.rapid(z=min(self.safe_z, above + SAFETY_MM))
                    self.line(self.x, self.y, level, self.feed_z)
                for x, y in points:
                    self.line(x, y, level, self.feed_xy)
            else:
                z = level + self.lift_mm if kind == LINK else self.safe_z
                self.rapid(z=max(z, self.z))
                for x, y in points:
                    self.rapid(x, y)
        self.rapid(z=self.safe_z)


def moves(pieces, safe_z, lift_mm, helix_angle_deg, feed_z_mm_min, feed_xy_mm_min, approach_z=None):
    """The tool's moves of an adaptive clearing (nc.Move): each Z level of
    the pieces from the top, each piece cut on it in their order.

    safe_z: 2 mm above the stock; approach_z: where the tool comes down to
    over its first start (Z+20, or the safe height when higher)."""
    approach = max(APPROACH_Z_MM if approach_z is None else approach_z, safe_z)
    tool = _Moves(safe_z, approach, lift_mm, feed_z_mm_min, feed_xy_mm_min)
    levels = sorted({z for piece in pieces for z in piece.levels}, reverse=True)
    for level in levels:
        for piece in pieces:
            if level not in piece.levels:
                continue
            i = piece.levels.index(level)
            above = piece.top if i == 0 else piece.levels[i - 1]
            tool.piece(piece, level, above, helix_angle_deg)
    return tuple(tool.result)
