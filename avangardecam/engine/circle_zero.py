# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Move 0-Point > Select circle, on its own: the middle of a circle of the
part at the mouth of its hole and the way out of the part along its axis
(model.circle_zero chooses the mouth, engine.move_zero moves the zero
point).

A circle is the wall of a round hole or pin (a cylinder face; with the
faces of the same axis and radius that meet it, as STEP files split a
cylinder in halves), or a round edge: the edge of such a wall stands for
the whole wall, so a click that catches the far edge of a hole still
gives its mouth. An edge of no such wall (of a round flat face, of a
cone) is a circle of its own.

The mouth is the end of the wall a tool reaches from outside the part:
beyond it, along the axis, a tool a little thinner than the circle meets
nothing of the part up to the end of the part's box (FreeCAD's Boolean
common of that tool and the part); of two such ends the one with less of
the part around its way out: how far beyond it the part reaches within
twice the circle's radius of the axis (a bore into a hollow inside the
part has the walls of the hollow there). Its Z out of the part points
that way.
When no end is free (a groove inside the part), the material just around
the circle decides: a little along its axis and a little against it,
inside and outside its radius, FreeCAD tells whether the point is in the
part; the side with less material is out.

Everything here is in part coordinates, where the user sees the models.
"""

import math
from typing import NamedTuple

import FreeCAD
import Part

from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.model import circle_zero as model
from avangardecam.model import op_zero as model_zero

# how far from the circle the material is probed, along its axis and across it, in mm
_PROBE_MM = 0.01
# points around the circle that are probed
_PROBES = 6
_INSIDE_TOLERANCE = 1e-7
# faces this close in radius, axis and height belong to one wall
_SAME_MM = 1e-4
_SAME_ANGLE = 1e-6
# the tool that looks beyond an end is this much thinner than the circle (at most a tenth of it)
_CLEARANCE_MM = 0.1
# a common part of the tool and the part this small is nothing (mm³)
_NOTHING_MM3 = 1e-6
# around the way out of an end the part is looked for this many radii from the axis
_AROUND_RADII = 2.0


class Circle(NamedTuple):
    """A circle of the part, in part coordinates."""

    centre: FreeCAD.Vector
    out: FreeCAD.Vector  # unit, along the circle's axis, out of the part
    radius: float


def _element(obj, sub):
    name = sub.split(".")[-1]
    if not name.startswith(("Edge", "Face")):
        raise ProjectError("Click a round edge of the model, or the wall of a round hole or pin.")
    return name, obj.Shape.getElement(name)


def is_round(obj, sub):
    """Whether the edge or face sub of obj gives a circle: a round edge or a
    cylinder face."""
    try:
        _name, element = _element(obj, sub)
    except (ProjectError, Part.OCCError, ValueError):
        return False
    if element.ShapeType == "Edge":
        return isinstance(element.Curve, Part.Circle)
    return isinstance(element.Surface, Part.Cylinder)


def _unit(vector):
    v = FreeCAD.Vector(vector)
    v.normalize()
    return v


# -- the wall of a hole or pin ---------------------------------------------------------


def _coaxial(surface, base, axis, radius):
    if abs(surface.Radius - radius) > _SAME_MM:
        return False
    if abs(abs(_unit(surface.Axis).dot(axis)) - 1.0) > _SAME_ANGLE:
        return False
    offset = surface.Center - base
    return (offset - axis * offset.dot(axis)).Length < _SAME_MM


def _span(face, base, axis):
    """(lowest, highest) of a cylinder face along axis, from base."""
    surface = face.Surface
    u0, _u1, v0, v1 = face.ParameterRange
    heights = [(surface.value(u0, v) - base).dot(axis) for v in (v0, v1)]
    return min(heights), max(heights)


def _wall(shape, element):
    """The cylinder faces of the wall element (a cylinder face or a round
    edge) belongs to, with its axis, a point of it and its radius: (faces,
    base, axis, radius); faces is empty for an edge of no such wall."""
    if element.ShapeType == "Face":
        seeds = [element]
        surface = element.Surface
        base, axis, radius = FreeCAD.Vector(surface.Center), _unit(surface.Axis), float(surface.Radius)
    else:
        curve = element.Curve
        base, axis, radius = FreeCAD.Vector(curve.Center), _unit(curve.Axis), float(curve.Radius)
        seeds = [
            f
            for f in shape.ancestorsOfType(element, Part.Face)
            if isinstance(f.Surface, Part.Cylinder) and _coaxial(f.Surface, base, axis, radius)
        ]
        if not seeds:
            return [], base, axis, radius
    same = [
        f for f in shape.Faces if isinstance(f.Surface, Part.Cylinder) and _coaxial(f.Surface, base, axis, radius)
    ]
    group = [f for f in same if any(f.isSame(s) for s in seeds)] or list(seeds)
    spans = [_span(f, base, axis) for f in group]
    low, high = min(a for a, _b in spans), max(b for _a, b in spans)
    grown = True
    while grown:
        grown = False
        for f in same:
            if any(f.isSame(g) for g in group):
                continue
            a, b = _span(f, base, axis)
            if a <= high + _SAME_MM and b >= low - _SAME_MM:
                group.append(f)
                low, high = min(low, a), max(high, b)
                grown = True
    return group, base, axis, radius


# -- beyond an end ---------------------------------------------------------------------


def _depth(box, start, direction):
    """How far the part's box reaches beyond start along direction (mm, 0 at least)."""
    corners = [
        FreeCAD.Vector(x, y, z)
        for x in (box.XMin, box.XMax)
        for y in (box.YMin, box.YMax)
        for z in (box.ZMin, box.ZMax)
    ]
    return max(0.0, max((corner - start).dot(direction) for corner in corners))


def _free(shape, centre, direction, radius):
    """Whether a tool a little thinner than the circle meets nothing of the
    part beyond centre along direction, to the end of the part's box (None:
    not known, the part is no solid)."""
    if not shape.Solids:
        return None
    start = centre + direction * _PROBE_MM
    length = _depth(shape.BoundBox, start, direction) + 1.0
    tool = Part.makeCylinder(radius - min(_CLEARANCE_MM, radius / 10.0), length, start, direction)
    try:
        common = shape.common(tool)
    except Part.OCCError:
        return None
    return common.Volume < _NOTHING_MM3


def _reach(shape, centre, direction, radius):
    """How far beyond centre along direction the part reaches within
    _AROUND_RADII radii of the axis (mm; to the end of the part's box when
    FreeCAD cannot tell)."""
    box = shape.BoundBox
    start = centre + direction * _PROBE_MM
    length = _depth(box, start, direction) + 1.0
    if not shape.Solids:
        return length
    around = Part.makeCylinder(radius * _AROUND_RADII, length, start, direction)
    try:
        common = shape.common(around)
    except Part.OCCError:
        return length
    if common.Volume < _NOTHING_MM3:
        return 0.0
    return min(length, _depth(common.BoundBox, start, direction))


def _end(shape, centre, direction, radius, picked=False, distance=0.0):
    free = _free(shape, centre, direction, radius)
    reach = _reach(shape, centre, direction, radius) if free else 0.0
    return model.End(free, reach, picked, distance)


# -- the material just around the circle -----------------------------------------------


def _material(solids, point):
    return any(s.isInside(point, _INSIDE_TOLERANCE, False) for s in solids)


def _across(axis):
    """Two unit vectors square to axis and to each other."""
    side = axis.cross(FreeCAD.Vector(1, 0, 0))
    if side.Length < 0.5:
        side = axis.cross(FreeCAD.Vector(0, 1, 0))
    side.normalize()
    return side, axis.cross(side)


def _around(shape, centre, axis, radius):
    """axis or its opposite: the side of the circle with less material just
    around it (the circle's own axis when it cannot be told)."""
    side, other = _across(axis)
    solids = shape.Solids
    above = below = 0
    for k in range(_PROBES):
        a = 2.0 * math.pi * (k + 0.5) / _PROBES
        across = side * math.cos(a) + other * math.sin(a)
        for d in (-_PROBE_MM, _PROBE_MM):
            ring = centre + across * (radius + d)
            above += _material(solids, ring + axis * _PROBE_MM)
            below += _material(solids, ring - axis * _PROBE_MM)
    return -axis if model.side(above, below) == model.IN else axis


# -- the circle ------------------------------------------------------------------------


def _of_wall(shape, faces, base, axis, radius, near, edge):
    spans = [_span(f, base, axis) for f in faces]
    heights = (min(a for a, _b in spans), max(b for _a, b in spans))
    at = None if near is None else (FreeCAD.Vector(near) - base).dot(axis)
    picked = None if edge is None else (FreeCAD.Vector(edge.Curve.Center) - base).dot(axis)
    ends = []
    for height, direction in zip(heights, (-axis, axis)):
        centre = base + axis * height
        clicked = picked is not None and abs(picked - height) < _SAME_MM * 10
        distance = 0.0 if at is None else abs(at - height)
        ends.append((centre, direction, _end(shape, centre, direction, radius, clicked, distance)))
    i = model.mouth([end for _c, _d, end in ends], 2.0 * radius)
    if i is not None:
        return Circle(ends[i][0], ends[i][1], radius)
    # no end is free: the end clicked (else the nearer one), the material around it
    i = next((k for k, (_c, _d, end) in enumerate(ends) if end.picked), None)
    if i is None:
        i = min(range(2), key=lambda k: (ends[k][2].distance, -k))
    centre = ends[i][0]
    return Circle(centre, _around(shape, centre, axis, radius), radius)


def _of_edge(shape, centre, axis, radius):
    """A round edge of no wall: of its axis's two ways the free one (of two,
    the one with less of the part's box beyond it), else the material
    around it."""
    ends = [_end(shape, centre, direction, radius) for direction in (axis, -axis)]
    decided = ends[0].free != ends[1].free or (
        ends[0].free and abs(ends[0].depth - ends[1].depth) > max(model.SAME_DEPTH_MM, 2.0 * radius)
    )
    i = model.mouth(ends, 2.0 * radius) if decided else None
    if i is None:
        return Circle(centre, _around(shape, centre, axis, radius), radius)
    return Circle(centre, axis if i == 0 else -axis, radius)


def circle(obj, sub, near=None):
    """The circle of the round edge or cylinder face sub ("Edge18") of the
    model obj, at the mouth of its hole (the top of its pin), with the way
    out of the part along its axis; near: where the user clicked (a point
    in part coordinates), which decides between two mouths alike (a hole
    through a plate). ProjectError when sub is not round."""
    name, element = _element(obj, sub)
    shape = obj.Shape
    edge = element.ShapeType == "Edge" and isinstance(element.Curve, Part.Circle)
    face = element.ShapeType == "Face" and isinstance(element.Surface, Part.Cylinder)
    if not (edge or face):
        raise ProjectError(
            "{} of {} is not round. Click a round edge of the model, or the wall of a round hole or pin.".format(name, obj.Label)  # fmt: skip
        )
    faces, base, axis, radius = _wall(shape, element)
    if not faces:
        return _of_edge(shape, base, axis, radius)
    return _of_wall(shape, faces, base, axis, radius, near, element if edge else None)


def _zero(job):
    return geometry.frame_of(cam.zero(job))


def shift(job, found):
    """The shift along the setup's zero point's axes that puts it in the
    middle of the circle found (circle())."""
    return model.to_point(_zero(job), tuple(found.centre))


def turn(job, found):
    """The turn (degrees about the zero point's X, Y and Z) that brings its
    Z out of the part along the axis of the circle found, the shortest way:
    the tool then stands on the circle."""
    return model_zero.turn_onto(_zero(job), tuple(found.out))


def along_z(job, found):
    """Whether the tool already stands along the circle's axis (either way)."""
    return model.along_z(_zero(job), tuple(found.out))
