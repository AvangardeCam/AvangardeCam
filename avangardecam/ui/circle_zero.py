# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Move 0-Point > Select circle, on its own: what the click picked
(engine.circle_zero finds the circle; the window is ui.move_zero).

Select circle, then a click on a round edge of the model or on the wall
of a round hole or pin, puts the zero point in the middle of the circle
at the mouth of the hole, where a tool comes in from outside the part
(engine.circle_zero). With 5 axes and "Z out of the model" the zero
point's Z also turns along the circle's axis, out of the part.
"""

import FreeCAD
import FreeCADGui

from avangardecam import edition, tr
from avangardecam.engine import circle_zero as engine
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import circle_zero as model


def _to_part(point):
    """A point picked in the 3D view, in part coordinates: the view draws
    the part moved to the active setup's zero point (ui.scene)."""
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    if doc is None:
        return FreeCAD.Vector(point)
    return scene.view_placement(doc).inverse().multVec(FreeCAD.Vector(point))


def selected_round():
    """(model, "EdgeN" or "FaceN", the clicked point in part coordinates)
    of the one edge or face selected in 3D, else None. Whether it is round
    is is_round()'s to say (a flat face is a wall)."""
    found = []
    for selection in FreeCADGui.Selection.getSelectionEx("", 0):
        points = list(getattr(selection, "PickedPoints", ()))
        for i, sub in enumerate(selection.SubElementNames):
            element = cam.model_element(selection.Object, sub)
            if element is None:
                continue
            point = points[i] if i < len(points) else FreeCAD.Vector()
            found.append((element[0], element[1], _to_part(point)))
    return found[0] if len(found) == 1 else None


def is_round(picked):
    """Whether what selected_round() gave is a round edge or a cylinder face."""
    return engine.is_round(picked[0], picked[1])


def hint():
    return tr("Click a round edge of the model, or the wall of a round hole or pin.")


def picked_text(obj, sub, found):
    """What the window says of the circle picked."""
    return tr("{} of {}: the middle of {}").format(sub, obj.Label, model.diameter_text(found.radius))


def tilt_hint():
    """Said after picked_text when the circle's axis is not along Z and the
    zero point does not turn (no 5 axes)."""
    if not edition.FIVE_AXES:
        return tr("Its axis is not along Z: the zero point moves to its middle, Z stays as it is.")
    return tr("Its axis is not along Z: tick 5 axes to turn Z out of the part along it.")


def circle(job, picked):
    """(shift, turn, text, along) for the circle picked ((model, sub, near)
    from selected_round): the zero point's shift to its middle, the turn of
    its Z out of the part along its axis (for 5 axes), what the window says
    of it and whether its axis is along Z already. ProjectError when it is
    not round."""
    obj, sub, near = picked
    found = engine.circle(obj, sub, near)
    return engine.shift(job, found), engine.turn(job, found), picked_text(obj, sub, found), engine.along_z(job, found)
