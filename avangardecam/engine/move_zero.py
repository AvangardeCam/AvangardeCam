# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Move 0-Point (CAM > Move 0-Point), on its own: the setup's zero point
goes to another place (model.move_zero has the sums) and, with 5 axes,
turns (model.op_zero).

The operations do not follow: each one counts from the zero point it was
made on and keeps it (engine.op_zero, experimental). The stock stays the
same block. New operations count from where the zero point was left; the
NC program gives each operation's zero point from the setup's default
one, the machine's preset.
"""

import FreeCAD

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.engine import op_zero
from avangardecam.model import move_zero as model
from avangardecam.model import op_zero as model_zero

NO_TURN = model_zero.NO_TURN


def _frame(job, shift=model.NONE):
    """The setup's zero point, shift further along its axes."""
    return model.moved(geometry.frame_of(cam.zero(job)), shift)


def wall_shift(job, obj, sub, shift=model.NONE):
    """The shift that puts the setup's zero point on the flat face sub of
    the model obj the shortest way (its plane through the zero point).

    shift: a shift already chosen; the result takes the zero point from
    there, so a second wall keeps what the first one gave (a corner).
    """
    face = geometry.flat_face(obj, sub)
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    point = face.Vertexes[0].Point
    more = model.to_plane(_frame(job, shift), tuple(point), tuple(normal))
    return model.added(shift, more)


def wall_turn(job, obj, sub):
    """The turn (degrees about the zero point's X, Y and Z) that brings its
    Z out of the flat face sub of the model obj, square to it, the
    shortest way: the tool then stands on that wall."""
    face = geometry.flat_face(obj, sub)
    normal = geometry.outward_normal(obj.Shape, face)
    return model_zero.turn_onto(geometry.frame_of(cam.zero(job)), tuple(normal))


def target(job, shift, turn=NO_TURN):
    """Where the zero point would be after the shift along its axes and
    then the turn about them: a placement in part coordinates."""
    return geometry.placement(model_zero.turned(_frame(job, shift), turn))


def move(job, shift, turn=NO_TURN):
    """Move the setup's active zero point by shift (mm along its own X, Y,
    Z) and then turn it (degrees about its own X, Y, Z). The operations
    keep the zero points they count from; the stock stays the same block.
    Returns the new zero point."""
    place = target(job, shift, turn)  # validates the shift and the turn
    op_zero.activate(job, place)
    return place
