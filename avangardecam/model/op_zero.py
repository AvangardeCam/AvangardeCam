# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Zero points of operations (experimental), on their own.

A setup has a default zero point: the machine's preset. The zero point
the user works on can be moved and turned away from it (CAM > Move
0-Point); each operation counts from the zero point it was made on and
keeps it. In the NC program an operation's zero point is given from the
preset: where its origin lies and which way its axes point, in the
preset's coordinates (a control's datum shift and tilted working plane).

Plain Python. Zero points are model.frame.Frame; angles are degrees. A
turn is three angles (a, b, c) about X, Y and Z, as a control's spatial
angles: the axes turn first about the fixed X by a, then about the fixed
Y by b, then about the fixed Z by c (the same as: about Z by c, about
the new Y by b, about the new X by a).
"""

import math

from avangardecam.model import frame as model_frame

# axes and angles this close are the same (rounding noise of rotations)
_NOISE = 1e-9
_ANGLE_DECIMALS = 6
_DECIMALS = model_frame.ORIGIN_DECIMALS

NO_TURN = (0.0, 0.0, 0.0)
MAX_TURN_DEG = 360.0

_X = (1.0, 0.0, 0.0)
_Y = (0.0, 1.0, 0.0)
_Z = (0.0, 0.0, 1.0)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _clean(value):
    """A component of a unit vector without the noise of a rotation."""
    for exact in (0.0, 1.0, -1.0):
        if abs(value - exact) < _NOISE:
            return exact
    return value


def _unit(a):
    length = math.sqrt(_dot(a, a))
    if length < 1e-12:
        raise ValueError("direction has no length")
    return tuple(_clean(c / length) for c in a)


def _angle(value):
    value = round(value, _ANGLE_DECIMALS) + 0.0
    return 180.0 if value == -180.0 else value


def _sin_cos(degrees):
    quarters = degrees / 90.0
    if abs(quarters - round(quarters)) < 1e-12:  # exact, so axes along the part's axes stay clean
        return ((0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0))[int(round(quarters)) % 4]
    return math.sin(math.radians(degrees)), math.cos(math.radians(degrees))


def validate_turn(turn):
    """A turn is three angles in degrees, none more than a whole turn."""
    if len(turn) != 3:
        raise ValueError("A turn of the zero point has an angle about X, Y and Z.")
    for axis, value in zip("XYZ", turn):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("The turn about {} must be a number of degrees.".format(axis))
        if abs(value) > MAX_TURN_DEG:
            raise ValueError("The turn about {} is {:g}°; a whole turn is {:g}°.".format(axis, value, MAX_TURN_DEG))


def no_turn(turn):
    return all(_angle(value) % 360.0 == 0.0 for value in turn)


def axes_of(turn):
    """The (x, y, z) axes after a turn, in the coordinates they turn in."""
    validate_turn(turn)
    (sa, ca), (sb, cb), (sc, cc) = (_sin_cos(value) for value in turn)
    # the columns of Rz(c) * Ry(b) * Rx(a)
    x = (cc * cb, sc * cb, -sb)
    y = (cc * sb * sa - sc * ca, sc * sb * sa + cc * ca, cb * sa)
    z = (cc * sb * ca + sc * sa, sc * sb * ca - cc * sa, cb * ca)
    return _unit(x), _unit(y), _unit(z)


def turn_of(axes):
    """The turn (a, b, c) that gives the (x, y, z) axes: a control's spatial
    angles. With the tool axis level (b = ±90°) a and c turn about the same
    line; a is 0 then."""
    x, y, z = (_unit(axis) for axis in axes)
    if abs(x[2]) > 1.0 - _NOISE:
        b = -90.0 if x[2] > 0.0 else 90.0
        sign = 1.0 if b > 0.0 else -1.0
        return (0.0, b, _angle(math.degrees(math.atan2(sign * z[1], sign * z[0]))))
    a = math.degrees(math.atan2(y[2], z[2]))
    b = math.degrees(math.asin(max(-1.0, min(1.0, -x[2]))))
    c = math.degrees(math.atan2(x[1], x[0]))
    return (_angle(a), _angle(b), _angle(c))


def turned(frame, turn):
    """The frame with its axes turned about themselves, through its origin."""
    validate_turn(turn)
    if no_turn(turn):
        return frame
    own = (frame.x_axis, frame.y_axis, frame.z_axis)

    def to_part(direction):
        return _unit(tuple(sum(own[k][i] * direction[k] for k in range(3)) for i in range(3)))

    x, y, z = (to_part(axis) for axis in axes_of(turn))
    return model_frame.Frame(frame.origin, x, y, z)


def turn_onto(frame, normal):
    """The turn that brings the frame's Z onto normal (a direction in the
    part's coordinates) the shortest way: a tool that stood along Z then
    stands square to the wall normal looks out of. Onto the opposite
    direction the frame turns over about its X."""
    n = _unit((_dot(normal, frame.x_axis), _dot(normal, frame.y_axis), _dot(normal, frame.z_axis)))
    if n[2] > 1.0 - _NOISE:
        return NO_TURN
    if n[2] < -1.0 + _NOISE:
        return (180.0, 0.0, 0.0)
    axis = _unit(_cross(_Z, n))
    sin, cos = math.sqrt(max(0.0, 1.0 - n[2] * n[2])), n[2]

    def rotate(v):  # Rodrigues
        k = axis
        kv = _cross(k, v)
        kd = _dot(k, v) * (1.0 - cos)
        return tuple(v[i] * cos + kv[i] * sin + k[i] * kd for i in range(3))

    return turn_of((rotate(_X), rotate(_Y), rotate(_Z)))


def relative(default, zero):
    """zero as the preset default sees it: its origin and axes in the
    default's coordinates; None when they are the same zero point."""

    def direction(axis):
        return _unit((_dot(axis, default.x_axis), _dot(axis, default.y_axis), _dot(axis, default.z_axis)))

    origin = tuple(round(c, _DECIMALS) + 0.0 for c in default.to_frame(zero.origin))
    found = model_frame.Frame(origin, direction(zero.x_axis), direction(zero.y_axis), direction(zero.z_axis))
    return None if is_preset(found) else found


def is_shift(zero):
    """Whether a zero point (from the preset) only lies elsewhere: its axes
    are the preset's."""
    return zero is None or (zero.x_axis, zero.y_axis, zero.z_axis) == (_X, _Y, _Z)


def is_preset(zero):
    return zero is None or (is_shift(zero) and zero.origin == (0.0, 0.0, 0.0))


def along_axes(zero):
    """Whether a zero point's axes go along the preset's (turned by
    quarter turns at most): a box on one is a box on the other."""
    return zero is None or all(max(abs(c) for c in axis) == 1.0 for axis in (zero.x_axis, zero.y_axis, zero.z_axis))


def is_level(zero):
    """Whether the tool stands as on the preset (the zero point is shifted
    and turned about Z at most)."""
    return zero is None or zero.z_axis == _Z


def shift_text(zero):
    """ "X+476.5 Y+0 Z-1.75" of a zero point from the preset."""
    origin = (0.0, 0.0, 0.0) if zero is None else zero.origin
    return " ".join("{}{:+g}".format(axis, round(value, 3) + 0.0) for axis, value in zip("XYZ", origin))


def turn_text(zero):
    """ "A+0 B+90 C+0" of a zero point from the preset."""
    turn = NO_TURN if zero is None else turn_of((zero.x_axis, zero.y_axis, zero.z_axis))
    return " ".join("{}{:+g}".format(axis, round(value, 3) + 0.0) for axis, value in zip("ABC", turn))
