# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Operations on other zero points in what runs a setup's program (Play,
Verify, the cycle time, the stock a setup leaves), on its own.

An operation's moves are counted from its zero point (nc.Operation.zero:
a model.frame.Frame as the setup's preset sees it, None: the preset),
the tool along that zero point's Z. The stock, the part and what is drawn
are in the preset's coordinates. Here is what turns one into the other:

- axis: the tool axis of a zero point for the stock model: "+Z" while the
  tool stands as on the preset (a zero point only shifted, or turned
  about Z), else the direction of its Z (along another axis of the stock
  or along none: stocklab cuts both);
- point, points, seen: a point (or an array of them) of a zero point in
  the preset's coordinates, and back;
- stock_move: a move of the stock model (stocklab.Line, stocklab.Arc)
  in the preset's coordinates;
- arrive: where the machine's tool is when the zero point changes
  (model.machine.Machine calls it).

Plain Python with numpy, no FreeCAD.
"""

import numpy as np

from avangardecam import stocklab
from avangardecam.model import op_zero

UP = (0.0, 0.0, 1.0)


def axis(zero):
    """The tool axis of a zero point, as stocklab takes it."""
    return "+Z" if op_zero.is_level(zero) else tuple(zero.z_axis)


def direction(zero):
    """The tool axis of a zero point as a vector in the preset's coordinates."""
    return UP if zero is None else tuple(zero.z_axis)


def _matrix(zero):
    """The zero point's axes as the columns of a matrix."""
    return np.array((zero.x_axis, zero.y_axis, zero.z_axis), dtype=float).T


def point(zero, p):
    """A point of the zero point in the preset's coordinates."""
    return tuple(p) if zero is None else zero.to_part(p)


def points(zero, array):
    """Points (n, 3) of the zero point in the preset's coordinates."""
    array = np.asarray(array, dtype=float)
    if zero is None:
        return array
    return array @ _matrix(zero).T + np.array(zero.origin, dtype=float)


def seen(zero, array):
    """Points (n, 3) of the preset as the zero point sees them."""
    array = np.asarray(array, dtype=float)
    if zero is None:
        return array
    return (array - np.array(zero.origin, dtype=float)) @ _matrix(zero)


def stock_move(zero, move):
    """A move of the stock model counted from the zero point, in the
    preset's coordinates; an arc's centre becomes a point of its axis."""
    if zero is None:
        return move
    start, end = point(zero, move.start), point(zero, move.end)
    if isinstance(move, stocklab.Arc):
        return stocklab.Arc(start, end, point(zero, move.center), ccw=move.ccw)
    return stocklab.Line(start, end, rapid=move.rapid)


def rotation(zero):
    """The zero point's turn as a quaternion (x, y, z, w), for what draws
    the tool along its Z; None: not turned."""
    if zero is None or op_zero.is_shift(zero):
        return None
    m = _matrix(zero)
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0.0:
        s = 2.0 * np.sqrt(trace + 1.0)
        q = ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        q = (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        q = ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    else:
        s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        q = ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)
    return tuple(float(c) for c in q)


def turned(setup):
    """Whether an operation of the setup (nc.Setup) counts from a turned
    zero point: its program needs a machine that tilts."""
    return any(not op_zero.is_shift(op.zero) for op in setup.operations)


# -- the machine ---------------------------------------------------------------------


def arrive(machine, op):
    """Where the machine's tool (model.machine.Machine: position, zero,
    change_z, anew) is as the operation's zero point sees it, before the
    operation calls its tool: (position, the height the tool is high at).

    A machine that turns its head (anew) starts every operation high over
    the operation's own zero point, wherever it was. Another machine only
    shifts the zero point: the tool is where it was, and high is the tool
    change height of the preset. (A turned zero point on such a machine:
    as with a turning head.)"""
    zero = op.zero
    before = machine.zero
    if machine.anew or not (op_zero.is_shift(zero) and op_zero.is_shift(before)):
        return [None, None, machine.change_z], machine.change_z
    old = (0.0, 0.0, 0.0) if before is None else before.origin
    new = (0.0, 0.0, 0.0) if zero is None else zero.origin
    position = [None if c is None else c + old[i] - new[i] for i, c in enumerate(machine.position)]
    return position, machine.change_z - new[2]
