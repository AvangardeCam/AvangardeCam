# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Measuring (CAM > Measure), on its own: nothing else in AvangardeCam uses
this module, so a change here cannot change a toolpath. It only reads the
shapes and the setup's zero point (and geometry.model_hole to know a hole
as the drilling knows it).

Elements are (object, "FaceN"/"EdgeN") of models and sketches as the user
sees them, "" for a whole object. Results are in the coordinates of the
setup's zero point (zero: the placement freecad_cam.zero gives).

- from_zero: the extreme coordinates of the elements together.
- local: the size of one element, or what lies between two, as a shop
  measures them: a flat face's sizes in its plane, the distance between
  two faces, a hole's diameter, centre and depth, the distance between the
  centres of two holes, from a face to a hole.
"""

import math
from typing import NamedTuple

import FreeCAD
import Part

from avangardecam.engine import ProjectError, geometry
from avangardecam.model import frame as model_frame

_PARALLEL = 1e-6  # radians
_ROUND = 1e-6  # mm
_AXES = (("X", FreeCAD.Vector(1, 0, 0)), ("Y", FreeCAD.Vector(0, 1, 0)), ("Z", FreeCAD.Vector(0, 0, 1)))


class Row(NamedTuple):
    label: str
    value: object  # a number in unit, or a text
    unit: str = "mm"


class Reading(NamedTuple):
    title: str
    rows: tuple
    note: str = ""  # the axes, when not the setup's


def _shape(obj, name):
    shape = Part.getShape(obj)  # where the user sees it
    if shape is None or shape.isNull():
        return None
    return shape.getElement(name) if name else shape


def _extents(shapes, place):
    """(min, max) along X, Y, Z of shapes together in the coordinates of place.
    The exact geometry: a triangulation (there is one once the shape is shown
    in 3D) makes the box bigger by its deflection."""
    matrix = place.inverse().toMatrix()
    box = None
    for shape in shapes:
        b = shape.transformed(matrix).optimalBoundingBox(False, False)
        box = b if box is None else box.united(b)
    return (box.XMin, box.XMax), (box.YMin, box.YMax), (box.ZMin, box.ZMax)


def from_zero(zero, elements):
    """(x_min, x_max), (y_min, y_max), (z_min, z_max) of elements together,
    the extreme coordinates from the zero point."""
    shapes = [s for s in (_shape(obj, name) for obj, name in elements) if s is not None]
    if not shapes:
        raise ProjectError("Nothing to measure: select faces or edges of the model or lines of a sketch.")
    return _extents(shapes, zero)


# -- local -----------------------------------------------------------------------


class _Plane(NamedTuple):
    face: object
    point: FreeCAD.Vector
    normal: FreeCAD.Vector  # unit, out of the part


class _Circle(NamedTuple):
    centre: FreeCAD.Vector  # a hole's: the middle of its top
    axis: FreeCAD.Vector  # unit
    radius: float
    full: bool  # a whole circle (else an arc: a rounded corner)
    hole: object  # geometry.ModelHole, or None when it is not a hole the tool can reach
    out: FreeCAD.Vector  # unit, along the axis out of the part: Z of the face it is in


class _Line(NamedTuple):
    edge: object
    direction: FreeCAD.Vector


class _Other(NamedTuple):
    shape: object


def _unit(v):
    v = FreeCAD.Vector(v)
    v.normalize()
    return v


def _parallel(a, b):
    return abs(abs(a.dot(b)) - 1.0) < _PARALLEL


def _square(a, b):
    return abs(a.dot(b)) < _PARALLEL


def _round_faces(shape, face):
    """The faces of the same cylinder as face (a STEP file splits one in halves)."""
    s = face.Surface
    return [
        f
        for f in shape.Faces
        if isinstance(f.Surface, Part.Cylinder)
        and abs(f.Surface.Radius - s.Radius) < _ROUND
        and _parallel(f.Surface.Axis, s.Axis)
        and ((f.Surface.Center - s.Center) - s.Axis * (f.Surface.Center - s.Center).dot(s.Axis)).Length < _ROUND
    ]


def _span(face, centre, axis):
    u0, u1, v0, v1 = face.ParameterRange
    heights = [(face.Surface.value(u, v) - centre).dot(axis) for u in (u0, (u0 + u1) / 2.0) for v in (v0, v1)]
    return min(heights), max(heights)


def _outward(obj, shape, element, axis, up):
    """Along the axis of a circle of a model or sketch, out of the part: the
    outward normal of the flat face it is the edge of (a face the tool can
    see first when there are two), the sketch's Z; else the axis turned
    towards the tool."""
    if geometry.is_sketch(obj):
        return _unit(geometry.tool_axis(obj.getGlobalPlacement()))
    rims = [element] if element.ShapeType == "Edge" else [e for e in element.Edges if isinstance(e.Curve, Part.Circle)]
    normals = []
    for rim in rims:
        for f in shape.ancestorsOfType(rim, Part.Face):
            if f.findPlane() is not None and _parallel(f.findPlane().Axis, axis):
                normals.append(_unit(geometry.outward_normal(shape, f)))
    if normals:
        return max(normals, key=lambda n: n.dot(up))
    return axis if axis.dot(up) >= 0 else -axis


def _circle(obj, name, shape, element, up):
    """A round face or edge: the hole it is (geometry.model_hole, as the
    drilling sees it), else the circle or arc it is."""
    hole = None
    if not geometry.is_sketch(obj):
        try:
            hole = geometry.model_hole(obj, name, up)
        except Exception:  # not a hole the setup's tool reaches: only its circle
            hole = None
    if element.ShapeType == "Edge":
        curve = element.Curve
        if hole is not None:
            return _Circle(hole.top, _unit(up), hole.radius, True, hole, _unit(up))
        axis = _unit(curve.Axis)
        out = _outward(obj, shape, element, axis, up)
        return _Circle(curve.Center, axis, curve.Radius, element.isClosed(), None, out)
    surface = element.Surface
    axis = _unit(surface.Axis)
    if hole is not None:
        return _Circle(hole.top, _unit(up), hole.radius, True, hole, _unit(up))
    faces = _round_faces(shape, element)
    turn = sum(f.ParameterRange[1] - f.ParameterRange[0] for f in faces)
    if _parallel(axis, up):
        axis = _unit(up)
    low, high = _span(element, surface.Center, axis)
    out = _outward(obj, shape, element, axis, up)
    return _Circle(surface.Center + axis * high, axis, surface.Radius, turn >= 2.0 * math.pi - 1e-6, None, out)


def _element(obj, name, up):
    if not name:
        raise ProjectError("Measure local measures faces, holes and edges, not all of {}.".format(obj.Label))
    shape = Part.getShape(obj)
    element = shape.getElement(name)
    if element.ShapeType == "Face":
        if element.findPlane() is not None:
            normal = geometry.outward_normal(shape, element) if shape.Solids else element.findPlane().Axis
            return _Plane(element, element.Vertexes[0].Point, _unit(normal))
        if isinstance(element.Surface, Part.Cylinder):
            return _circle(obj, name, shape, element, up)
        return _Other(element)
    if element.ShapeType == "Edge":
        if isinstance(element.Curve, Part.Circle):
            return _circle(obj, name, shape, element, up)
        if isinstance(element.Curve, (Part.Line, Part.LineSegment)):
            return _Line(element, _unit(element.Vertexes[-1].Point - element.Vertexes[0].Point))
        return _Other(element)
    return _Other(element)


class _Setup:
    """Points and directions of the part in the zero point's coordinates."""

    def __init__(self, zero):
        self.zero = zero
        self.inverse = zero.inverse()
        self.up = geometry.tool_axis(zero)

    def point(self, p):
        return self.inverse.multVec(p)

    def direction(self, d):
        return self.inverse.Rotation.multVec(d)

    def axis_of(self, d):
        """"X", "Y" or "Z" when d (part) runs along that axis of the setup, else None."""
        d = self.direction(d)
        return next((name for name, a in _AXES if _parallel(d, a)), None)

    def part(self, d):
        return self.zero.Rotation.multVec(d)


def _degrees(a, b):
    return math.degrees(a.getAngle(b))


def _between_planes(a, b):
    """The angle between two planes (by their normals), 0 to 90°."""
    angle = _degrees(a, b)
    return min(angle, 180.0 - angle)


def _face_sizes(setup, plane):
    rows = []
    n = setup.direction(plane.normal)
    in_plane = [(name, a) for name, a in _AXES if _square(n, a)]
    if len(in_plane) >= 2:
        (nu, u), (nv, v) = in_plane[:2]
        labels = ("Along " + nu, "Along " + nv)
        u, v = setup.part(u), setup.part(v)
    elif len(in_plane) == 1:
        nu, u = in_plane[0]
        u = setup.part(u)
        v = _unit(plane.normal.cross(u))
        labels = ("Along " + nu, "Across")
    else:
        straight = [e for e in plane.face.Edges if isinstance(e.Curve, (Part.Line, Part.LineSegment))]
        if straight:
            longest = max(straight, key=lambda e: e.Length)
            u = longest.Vertexes[-1].Point - longest.Vertexes[0].Point
            u = _unit(u - plane.normal * u.dot(plane.normal))
        else:
            u = plane.normal.cross(FreeCAD.Vector(1, 0, 0))
            if u.Length < 0.5:
                u = plane.normal.cross(FreeCAD.Vector(0, 1, 0))
            u = _unit(u)
        v = _unit(plane.normal.cross(u))
        labels = ("Length", "Width")
    frame = FreeCAD.Placement(
        FreeCAD.Matrix(u.x, v.x, plane.normal.x, 0, u.y, v.y, plane.normal.y, 0, u.z, v.z, plane.normal.z, 0, 0, 0, 0, 1)
    )
    (u0, u1), (v0, v1), _w = _extents([plane.face], frame)
    sizes = [u1 - u0, v1 - v0]
    if labels[0] == "Length" and sizes[1] > sizes[0]:
        sizes.reverse()
    rows.append(Row(labels[0], sizes[0]))
    rows.append(Row(labels[1], sizes[1]))
    level = setup.axis_of(plane.normal)
    if level is not None:
        rows.append(Row("At " + level, setup.point(plane.point)[("X", "Y", "Z").index(level)]))
    else:
        rows.append(Row("Angle to the XY plane", _between_planes(setup.direction(plane.normal), FreeCAD.Vector(0, 0, 1)), "°"))
    return Reading("Flat face", tuple(rows))


def _centre_rows(setup, circle, prefix="Centre"):
    c = setup.point(circle.centre)
    return [Row("{} {}".format(prefix, name), c[i]) for i, name in enumerate(("X", "Y", "Z"))]


def _round_size(circle):
    return Row("Diameter Ø", 2.0 * circle.radius) if circle.full else Row("Radius R", circle.radius)


def _circle_reading(setup, circle):
    rows = [_round_size(circle)] + _centre_rows(setup, circle)
    if circle.hole is not None:
        depth = circle.hole.depth
        rows.append(Row("Depth", -depth.depth_mm))
        rows.append(Row("Through", "yes" if depth.through else "no", ""))
        return Reading("Hole", tuple(rows))
    along = setup.axis_of(circle.axis)
    rows.append(Row("Axis", along, "") if along else Row("Axis angle from Z", _between_planes(setup.direction(circle.axis), FreeCAD.Vector(0, 0, 1)), "°"))  # fmt: skip
    return Reading("Circle" if circle.full else "Arc", tuple(rows))


def _one(setup, item):
    if isinstance(item, _Plane):
        return _face_sizes(setup, item)
    if isinstance(item, _Circle):
        return _circle_reading(setup, item)
    if isinstance(item, _Line):
        rows = [Row("Length", item.edge.Length)]
        along = setup.axis_of(item.direction)
        rows.append(Row("Along", along, "") if along else Row("Angle from Z", _between_planes(setup.direction(item.direction), FreeCAD.Vector(0, 0, 1)), "°"))  # fmt: skip
        return Reading("Straight edge", tuple(rows))
    if item.shape.ShapeType == "Edge":
        return Reading("Edge", (Row("Length", item.shape.Length),))
    raise ProjectError("Measure local measures flat faces, round holes and edges; this face is curved.")


def _shortest(a, b):
    return Row("Shortest distance", a.distToShape(b)[0])


def _two_planes(setup, a, b):
    if _parallel(a.normal, b.normal):
        distance = abs((b.point - a.point).dot(a.normal))
        along = setup.axis_of(a.normal)
        return Reading("Two parallel faces", (Row("Distance" + (" along " + along if along else ""), distance),))
    return Reading("Two faces", (Row("Angle", _between_planes(a.normal, b.normal), "°"), _shortest(a.face, b.face)))


_FACE_AXES = "In the face's own axes: Z out of the part, X and Y as Snap-0-Point puts them there"


def _face_axes(setup, out):
    """(x, y, z) in part coordinates of the face a circle is in, Z out of the
    part: the setup's axes when its tool looks at the face, else the axes
    Snap-0-Point would give it; and whether they are the setup's."""
    if out.getAngle(setup.up) < _PARALLEL:
        return setup.part(_AXES[0][1]), setup.part(_AXES[1][1]), out, True
    x, y, z = (FreeCAD.Vector(*v) for v in model_frame.axes_for_normal(tuple(out)))
    return x, y, z, False


def _gap(a, b, u):
    """Between the nearest points of two circles along u (nothing between
    them along u when they overlap there)."""

    def span(c):
        half = c.radius * math.sqrt(max(0.0, 1.0 - c.axis.dot(u) ** 2))
        return c.centre.dot(u) - half, c.centre.dot(u) + half

    (a0, a1), (b0, b1) = span(a), span(b)
    gap = max(b0 - a1, a0 - b1)
    return gap if gap >= -_ROUND else "overlap"


def _two_circles(setup, a, b):
    """The centres of two circles and the wall between them, in the axes of
    the face the first one is in."""
    title = "Two holes" if a.hole is not None and b.hole is not None else "Two circles"
    x, y, z, own = _face_axes(setup, a.out)
    v = b.centre - a.centre
    rows = []
    if _parallel(a.axis, b.axis):
        across = (v - a.axis * v.dot(a.axis)).Length
        rows.append(Row("Centre distance", across))
        # across the axes, as a caliper measures the wall between two holes
        if across >= a.radius + b.radius:
            nearest = across - a.radius - b.radius
        elif across <= abs(a.radius - b.radius):  # one inside the other
            nearest = abs(a.radius - b.radius) - across
        else:  # they cross
            nearest = 0.0
        rows.append(Row("Between nearest points", nearest))
    else:
        rows.append(Row("Centre distance", v.Length))
        # only here: circles that are not parallel have no wall across their axes
        circles = [Part.makeCircle(c.radius, c.centre, c.axis) for c in (a, b)]
        rows.append(Row("Shortest distance in space", circles[0].distToShape(circles[1])[0]))
    rows.append(Row("Nearest points along X", _gap(a, b, x)))
    rows.append(Row("Nearest points along Y", _gap(a, b, y)))
    rows += [Row("Δ" + name, v.dot(u)) for name, u in (("X", x), ("Y", y), ("Z", z))]
    rows += [Row("Ø 1" if a.full else "R 1", 2 * a.radius if a.full else a.radius)]
    rows += [Row("Ø 2" if b.full else "R 2", 2 * b.radius if b.full else b.radius)]
    return Reading(title, tuple(rows), "" if own else _FACE_AXES)


def _plane_circle(setup, plane, circle, circle_shape):
    title = "Face and hole" if circle.hole is not None else "Face and circle"
    if _square(plane.normal, circle.axis):  # the axis along the face: across to it
        d = abs((circle.centre - plane.point).dot(plane.normal))
        along = setup.axis_of(plane.normal)
        suffix = " along " + along if along else ""
        rows = (
            Row("Face to centre" + suffix, d),
            Row("Face to nearest side" + suffix, d - circle.radius),
            Row("Face to far side" + suffix, d + circle.radius),
            _round_size(circle),
        )
        return Reading(title, rows)
    if _parallel(plane.normal, circle.axis):  # the face square to the axis: along it
        d = (circle.centre - plane.point).dot(plane.normal)
        along = setup.axis_of(plane.normal)
        return Reading(
            title,
            (Row("Face to centre along the axis" + (" (" + along + ")" if along else ""), abs(d)), _round_size(circle)),
        )
    return Reading(
        title,
        (Row("Axis to face angle", 90.0 - _between_planes(plane.normal, circle.axis), "°"), _shortest(plane.face, circle_shape)),
    )


def local(zero, elements):
    """Reading of one element or of two (in the order they were picked)."""
    if not elements:
        raise ProjectError("Nothing to measure: click a face, a hole or an edge (Shift+click a second one).")
    if len(elements) > 2:
        raise ProjectError("Measure local takes one element or two (selected: {}).".format(len(elements)))
    setup = _Setup(zero)
    items = [_element(obj, name, setup.up) for obj, name in elements]
    shapes = [_shape(obj, name) for obj, name in elements]
    if len(items) == 1:
        return _one(setup, items[0])
    a, b = items
    if isinstance(a, _Plane) and isinstance(b, _Plane):
        return _two_planes(setup, a, b)
    if isinstance(a, _Circle) and isinstance(b, _Circle):
        return _two_circles(setup, a, b)
    if isinstance(a, _Plane) and isinstance(b, _Circle):
        return _plane_circle(setup, a, b, shapes[1])
    if isinstance(a, _Circle) and isinstance(b, _Plane):
        return _plane_circle(setup, b, a, shapes[0])
    if isinstance(a, _Line) and isinstance(b, _Line) and not _parallel(a.direction, b.direction):
        return Reading("Two edges", (Row("Angle", _between_planes(a.direction, b.direction), "°"), _shortest(*shapes)))
    return Reading("Two elements", (_shortest(*shapes),))
