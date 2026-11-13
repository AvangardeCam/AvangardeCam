# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""How a contour's tool comes onto it on an arc and leaves it, as the shop's
programs for its TNC do it:

- the tool goes down in the centre of an arc that touches the contour
  where it starts, on the tool's side (with radius compensation the side
  the control keeps it on, else the left of the contour);
- a straight line takes it to the start of the arc (with RL/RR the
  control switches the compensation on there), and LEAD_ANGLE_DEG of the
  arc bring it onto the contour, tangent to it;
- at the end the same backwards: an arc off the contour, then a straight
  line to its centre (with R0: the compensation off).

The arc's radius is the user's; by default (default_radius) the tool goes
down LEAD_CLEARANCE_MM clear of the contour. The shop's programs take 1.1 x
the tool radius. A closed contour starts and ends in the middle of its first
line, so the arcs stay away from its corners.

Points are (x, y) in the plane of the contour, tangents are unit vectors
in the tool's direction.
"""

import math

from avangardecam.model.nc import LEFT, RIGHT

LEAD_CLEARANCE_MM = 0.5
LEAD_ANGLE_DEG = 45.0


def default_radius(tool_radius_mm):
    """Radius of the lead arcs for a tool: it goes down LEAD_CLEARANCE_MM
    clear of the contour."""
    return tool_radius_mm + LEAD_CLEARANCE_MM


def side_normal(tangent, side):
    """Unit vector from the contour to the tool's side."""
    tx, ty = tangent
    if side == LEFT:
        return (-ty, tx)
    if side == RIGHT:
        return (ty, -tx)
    raise ValueError("no side of the contour: {!r}".format(side))


def other_side(side):
    return RIGHT if side == LEFT else LEFT


def clockwise(side):
    """Direction of the lead arcs, seen from +Z: they turn towards the
    tool's side."""
    return side == RIGHT


def _arc_point(point, tangent, side, r, turn):
    """(centre, point on the arc turn of the lead angle away from point)."""
    nx, ny = side_normal(tangent, side)
    centre = (point[0] + r * nx, point[1] + r * ny)
    angle = math.radians(LEAD_ANGLE_DEG) * turn * (-1.0 if clockwise(side) else 1.0)
    c, s = math.cos(angle), math.sin(angle)
    # from the centre to the contour is -normal; turned by angle
    x, y = -nx * c + ny * s, -nx * s - ny * c
    return centre, (centre[0] + r * x, centre[1] + r * y)


def lead_in(point, tangent, side, r):
    """(centre, start) of the arc that ends on the contour at point."""
    return _arc_point(point, tangent, side, r, -1.0)


def lead_out(point, tangent, side, r):
    """(centre, end) of the arc that leaves the contour at point."""
    return _arc_point(point, tangent, side, r, 1.0)
