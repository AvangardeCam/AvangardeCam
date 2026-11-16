# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Moving a setup's zero point (CAM > Move 0-Point), on its own.

The zero point keeps its axes and goes to another place: by a shift along
its own X, Y and Z (as a control's datum shift is typed: X+476.5 puts the
zero 476.5 mm further along X), or to a wall of the part: the shortest
way to the wall's plane, so that the plane goes through the zero point
and the two other coordinates stay as they are.

Plain Python: a zero point is a model.frame.Frame, points and directions
are (x, y, z) tuples in the part's coordinates, a shift is (x, y, z) in
mm along the frame's axes.
"""

import math

from avangardecam.model import frame as model_frame

# no machine in the shop moves further; a typing slip is caught here
MAX_SHIFT_MM = 10000.0
# shifts are kept to the nanometre, as zero points are
_DECIMALS = model_frame.ORIGIN_DECIMALS

NONE = (0.0, 0.0, 0.0)


def _clean(value):
    return round(value, _DECIMALS) + 0.0  # no -0.0


def validate(shift):
    """A shift is three numbers of mm, none further than a machine moves."""
    if len(shift) != 3:
        raise ValueError("A shift of the zero point has an X, a Y and a Z.")
    for axis, value in zip("XYZ", shift):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("The shift along {} must be a number of mm.".format(axis))
        if abs(value) > MAX_SHIFT_MM:
            raise ValueError(
                "The shift along {} is {:g} mm; the zero point moves {:g} mm at most.".format(axis, value, MAX_SHIFT_MM)
            )


def is_none(shift):
    """Whether the shift leaves the zero point where it is."""
    return all(_clean(value) == 0.0 for value in shift)


def moved(frame, shift):
    """The frame with its origin shift further along its own axes."""
    validate(shift)
    origin = frame.to_part(tuple(float(value) for value in shift))
    return model_frame.Frame(tuple(_clean(c) for c in origin), frame.x_axis, frame.y_axis, frame.z_axis)


def added(shift, more):
    """Two shifts one after the other."""
    return tuple(_clean(a + b) for a, b in zip(shift, more))


def to_plane(frame, point, normal):
    """The shift that puts the frame's origin on a plane the shortest way.

    point: any point of the plane; normal: across it, of any length and
    either sense. A wall square to X gives a shift along X only.
    """
    length = math.sqrt(sum(c * c for c in normal))
    if length < 1e-9:
        raise ValueError("The wall has no direction.")
    n = tuple(c / length for c in normal)
    distance = sum((p - o) * c for p, o, c in zip(point, frame.origin, n))
    foot = tuple(o + c * distance for o, c in zip(frame.origin, n))
    return tuple(_clean(value) for value in frame.to_frame(foot))
