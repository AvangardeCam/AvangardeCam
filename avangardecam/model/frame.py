# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Zero point of a setup: where G-code X0 Y0 Z0 lies on the part and which
way its axes point, in the part's own coordinates (mm).

The tool always moves along the setup's Z axis. Snapping the zero point to
a flat face of the part makes Z the face's outward normal (the side the
spindle comes from), puts Z0 in the face's plane and X0 Y0 in the middle
of the part's extents along the new X and Y axes. The zero point can then
be turned about its Z axis (by 90°, 180° or any angle).

Vectors are plain (x, y, z) tuples; the engine converts them to FreeCAD.
"""

import math
from typing import NamedTuple

# A face whose normal is closer than 45° to the part's Z axis is a top or a
# bottom face; any other face is a side face.
_UP_DOWN = math.sqrt(0.5)
# components this small are rounding noise of a rotation; snapping them to
# zero keeps axes along the part's axes exact (clean G-code coordinates)
_NOISE = 1e-12
# zero points are kept to the nanometre
ORIGIN_DECIMALS = 6


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(*vectors):
    return tuple(sum(v[i] for v in vectors) for i in range(3))


def _unit(a):
    length = math.sqrt(_dot(a, a))
    if length < 1e-9:
        raise ValueError("direction has no length")
    clean = tuple(0.0 if abs(c / length) < _NOISE else c / length for c in a)
    length = math.sqrt(_dot(clean, clean))
    return tuple(c / length + 0.0 for c in clean)


def _in_plane(a, normal):
    """a without its component along normal (a unit vector)."""
    return _sub(a, _scale(normal, _dot(a, normal)))


class Frame(NamedTuple):
    """A right-handed zero point: origin and unit axes in part coordinates."""

    origin: tuple
    x_axis: tuple
    y_axis: tuple
    z_axis: tuple

    def to_frame(self, point):
        """Coordinates of a part point as the machine sees them in this setup."""
        d = _sub(point, self.origin)
        return (_dot(d, self.x_axis), _dot(d, self.y_axis), _dot(d, self.z_axis))

    def to_part(self, point):
        """Part coordinates of a point given in this frame."""
        return _add(
            self.origin,
            _scale(self.x_axis, point[0]),
            _scale(self.y_axis, point[1]),
            _scale(self.z_axis, point[2]),
        )


def axes_for_normal(normal):
    """(x, y, z) axes of a setup whose tool comes from the side normal points to.

    Top and bottom faces keep X along the part's X (a bottom face turns the
    part over around X). Side faces keep "up" up: Y follows the part's Z, so
    looking at the face, X runs to the right and Y upwards.
    """
    z = _unit(normal)
    if abs(z[2]) > _UP_DOWN:
        x = _unit(_in_plane((1.0, 0.0, 0.0), z))
        y = _unit(_cross(z, x))
    else:
        y = _unit(_in_plane((0.0, 0.0, 1.0), z))
        x = _unit(_cross(y, z))
    return x, y, z


def rotated_about_z(frame, degrees):
    """The frame turned about its own Z axis through its origin.

    Positive degrees turn the axes counter-clockwise seen from the tool
    (as the control's ROT): at 90° the new X is the old Y. Quarter turns
    are exact, so axes along the part's axes stay clean.
    """
    quarters = degrees / 90.0
    if abs(quarters - round(quarters)) < 1e-12:
        cos, sin = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(round(quarters)) % 4]
    else:
        cos, sin = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    x = _unit(_add(_scale(frame.x_axis, cos), _scale(frame.y_axis, sin)))
    z = _unit(frame.z_axis)
    y = _unit(_cross(z, x))
    return Frame(frame.origin, x, y, z)


def rotation_about_z(frame):
    """How far the frame is turned about Z from the axes Snap-0-Point gives
    its tool axis, in degrees, -180 < angle <= 180 (sense of rotated_about_z)."""
    x0 = axes_for_normal(frame.z_axis)[0]
    angle = math.degrees(math.atan2(_dot(_cross(x0, frame.x_axis), frame.z_axis), _dot(x0, frame.x_axis)))
    angle = round(angle, 6) + 0.0
    return 180.0 if angle == -180.0 else angle


def centered_on_face(axes, x_range, y_range, face_level):
    """Zero point in the middle of the part's extents and in the face's plane.

    axes: (x, y, z) from axes_for_normal; x_range, y_range: (min, max) of the
    part along x and y; face_level: the face plane's distance from the part
    origin along z. All in mm.
    """
    x, y, z = axes
    cx = (x_range[0] + x_range[1]) / 2.0
    cy = (y_range[0] + y_range[1]) / 2.0
    origin = _add(_scale(x, cx), _scale(y, cy), _scale(z, face_level))
    # rounding noise of the geometry kernel is not part of a zero point
    return Frame(tuple(round(c, ORIGIN_DECIMALS) + 0.0 for c in origin), x, y, z)


_AXIS_NAMES = (
    ((1.0, 0.0, 0.0), "X+"),
    ((-1.0, 0.0, 0.0), "X−"),
    ((0.0, 1.0, 0.0), "Y+"),
    ((0.0, -1.0, 0.0), "Y−"),
    ((0.0, 0.0, 1.0), "Z+"),
    ((0.0, 0.0, -1.0), "Z−"),
)


def axis_name(direction):
    """"Z+" for a direction along one of the part's axes, else the vector."""
    d = _unit(direction)
    for axis, name in _AXIS_NAMES:
        if _dot(d, axis) > 1.0 - 1e-9:
            return name
    return "({:.3f}, {:.3f}, {:.3f})".format(*d)
