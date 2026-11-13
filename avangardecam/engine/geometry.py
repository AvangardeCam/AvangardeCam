# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The part's geometry as the user picks it: flat faces, their outward
normals, zero points on them and sketches made from their edges.

Everything here is in part coordinates, where the user sees the models.
Turning that into a setup's machine coordinates is freecad_cam's job.
"""

import collections
import heapq
import math
from typing import NamedTuple

import FreeCAD
import Part

from avangardecam.engine import ProjectError
from avangardecam.model import frame as model_frame
from avangardecam.model import leads as model_leads
from avangardecam.model import nc as model_nc
from avangardecam.model import operations as model_operations

# how far outside a face a point is probed to tell its outer side, in mm
_PROBE_MM = 0.01


def vector(values):
    return FreeCAD.Vector(*values)


def placement(frame):
    """FreeCAD placement of a model Frame: maps frame coordinates to the part."""
    x, y, z = frame.x_axis, frame.y_axis, frame.z_axis
    matrix = FreeCAD.Matrix(
        x[0], y[0], z[0], frame.origin[0],
        x[1], y[1], z[1], frame.origin[1],
        x[2], y[2], z[2], frame.origin[2],
        0.0, 0.0, 0.0, 1.0,
    )  # fmt: skip
    return FreeCAD.Placement(matrix)


def frame_of(place):
    """Model Frame of a FreeCAD placement."""
    rotation = place.Rotation

    def axis(v):
        return tuple(float(c) for c in rotation.multVec(FreeCAD.Vector(*v)))

    return model_frame.Frame(
        tuple(float(c) for c in place.Base),
        axis((1, 0, 0)),
        axis((0, 1, 0)),
        axis((0, 0, 1)),
    )


def tool_axis(place):
    """The direction the tool comes from in a setup or sketch placement."""
    return place.Rotation.multVec(FreeCAD.Vector(0, 0, 1))


def same_direction(a, b):
    return a.getAngle(b) < 1e-6


def opposite_direction(a, b):
    return same_direction(a, -b)


# a sketch seen from its other side: its X stays, Y and Z turn round
FLIP = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 180)


def facing_tool(place, flipped):
    """Placement of a sketch's lines as the tool sees them: the sketch's
    own, or turned over about its X when it faces away from the tool
    (flipped, e.g. a face of the part's bottom used from the top)."""
    return place.multiply(FreeCAD.Placement(FreeCAD.Vector(), FLIP)) if flipped else place


# -- faces ---------------------------------------------------------------------


def flat_face(obj, sub):
    """The face sub ("Face12") of obj in part coordinates; it must be flat."""
    name = sub.split(".")[-1]
    if not name.startswith("Face"):
        raise ProjectError("Select a flat face of the model (selected: {}).".format(name or obj.Label))
    face = obj.Shape.getElement(name)
    if face.findPlane() is None:
        raise ProjectError("{} of {} is not flat.".format(name, obj.Label))
    return face


def _point_on(face):
    """A point inside the face (its centre of mass may lie in a hole)."""
    point = face.CenterOfMass
    if face.isInside(point, 1e-6, True):
        return point
    points, triangles = face.tessellate(0.1)
    a, b, c = (points[i] for i in triangles[0])
    return (a + b + c) * (1.0 / 3.0)


def outward_normal(shape, face):
    """Unit normal of a flat face pointing out of the part.

    FreeCAD 1.1 already turns normalAt() to the outside for reversed faces;
    the probe makes sure of it whatever the version or the face's history.
    """
    u0, u1, v0, v1 = face.ParameterRange
    normal = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    normal.normalize()
    if shape.Solids:
        point = _point_on(face)
        outside = point + normal * _PROBE_MM
        inside = point - normal * _PROBE_MM
        if any(s.isInside(outside, 1e-7, False) for s in shape.Solids) and not any(
            s.isInside(inside, 1e-7, False) for s in shape.Solids
        ):
            normal = -normal
    return normal


def _extents(shapes, rotation_only):
    """(x_min, x_max), (y_min, y_max), (z_min, z_max) of shapes along the axes
    of a placement without translation."""
    matrix = rotation_only.inverse().toMatrix()
    box = None
    for shape in shapes:
        local = shape.transformed(matrix)
        # exact geometry: a triangulation (there is one once the shape is
        # shown in 3D) makes the box bigger by its deflection
        b = local.optimalBoundingBox(False, False)
        if box is None:
            box = b
        else:
            box.add(b)
    if box is None:
        raise ProjectError("The project has no model.")
    return (box.XMin, box.XMax), (box.YMin, box.YMax), (box.ZMin, box.ZMax)


def _shapes(models):
    return [Part.getShape(m) for m in models]


def zero_on_face(models, obj, sub):
    """Zero point snapped to a flat face: Z out of the face, Z0 in its plane,
    X0 Y0 in the middle of the models' extents."""
    face = flat_face(obj, sub)
    normal = outward_normal(obj.Shape, face)
    axes = model_frame.axes_for_normal(tuple(normal))
    rotation_only = placement(model_frame.Frame((0.0, 0.0, 0.0), *axes))
    x_range, y_range, _z = _extents(_shapes(models), rotation_only)
    level = face.Vertexes[0].Point.dot(vector(axes[2]))
    return placement(model_frame.centered_on_face(axes, x_range, y_range, level))


def zero_on_top(models):
    """Default zero point: on top of the models, in the middle."""
    axes = model_frame.axes_for_normal((0.0, 0.0, 1.0))
    rotation_only = placement(model_frame.Frame((0.0, 0.0, 0.0), *axes))
    x_range, y_range, z_range = _extents(_shapes(models), rotation_only)
    return placement(model_frame.centered_on_face(axes, x_range, y_range, z_range[1]))


# -- sketches ------------------------------------------------------------------


def _flat(point):
    return FreeCAD.Vector(point.x, point.y, 0.0)


def _sketch_geometry(edge):
    """Sketcher geometry of an edge already moved into the sketch plane."""
    curve = edge.Curve
    first, last = edge.FirstParameter, edge.LastParameter
    if isinstance(curve, (Part.Line, Part.LineSegment)):
        return Part.LineSegment(_flat(edge.valueAt(first)), _flat(edge.valueAt(last)))
    if isinstance(curve, Part.Circle):
        circle = Part.Circle(_flat(curve.Center), FreeCAD.Vector(0, 0, 1), curve.Radius)
        if edge.isClosed():
            return circle
        # sketcher arcs run counter-clockwise seen from +Z; an edge on a
        # clockwise circle covers the arc from its end to its start
        start, end = edge.valueAt(first), edge.valueAt(last)
        if curve.Axis.z < 0:
            start, end = end, start
        a1 = circle.parameter(_flat(start))
        a2 = circle.parameter(_flat(end))
        while a2 <= a1:
            a2 += 2.0 * math.pi
        return Part.ArcOfCircle(circle, a1, a2)
    spline = curve.toBSpline(first, last)
    for i, pole in enumerate(spline.getPoles(), start=1):
        spline.setPole(i, _flat(pole))
    return spline


def extract_boundary(doc, models, obj, sub):
    """A sketch of the boundary edges of a flat face (outer edge and holes).

    The sketch is a copy, not linked to the face, so it survives changes of
    the model. It lies in the face's plane with the same axes and origin
    Snap-0-Point would give that face: sketch coordinates are the G-code
    coordinates of a setup snapped to it.
    """
    face = flat_face(obj, sub)
    place = zero_on_face(models, obj, sub)
    to_sketch = place.inverse().toMatrix()
    sketch = doc.addObject("Sketcher::SketchObject", "Sketch")
    sketch.Placement = place
    sketch.Label = "Sketch {} {}".format(obj.Label, sub.split(".")[-1])
    for wire in face.Wires:
        for edge in wire.Edges:
            sketch.addGeometry(_sketch_geometry(edge.transformed(to_sketch)))
    sketch.detectMissingPointOnPointConstraints(1e-6)
    sketch.makeMissingPointOnPointCoincident(False)
    doc.recompute()
    return sketch


def is_sketch(obj):
    return obj is not None and obj.isDerivedFrom("Sketcher::SketchObject")


# -- contour lines ------------------------------------------------------------

# line ends closer than this meet, mm
_MEET_MM = 1e-4


def _ends(edge):
    return edge.valueAt(edge.FirstParameter), edge.valueAt(edge.LastParameter)


def _meet(a, b):
    return a.distanceToPoint(b) < _MEET_MM


def _directed(edge, reverse, start_at=None):
    """A new edge running from the edge's start to its end (or back).

    Built fresh, so its first vertex is where it starts: FreeCAD's Engrave
    begins a wire at the first vertex of its first edge. start_at, the end
    of the previous edge, closes gaps below _MEET_MM exactly.
    """
    curve = edge.Curve
    first, last = edge.FirstParameter, edge.LastParameter
    start, end = _ends(edge)
    if reverse:
        start, end = end, start
    if start_at is not None:
        start = start_at
    if isinstance(curve, (Part.Line, Part.LineSegment)):
        return Part.LineSegment(start, end).toShape()
    if edge.isClosed():
        return _turned_round(edge) if reverse else edge.copy()
    if isinstance(curve, Part.Circle):
        return Part.Arc(start, edge.valueAt((first + last) / 2.0), end).toShape()
    spline = curve.toBSpline(first, last)
    if reverse:
        spline.reverse()
    if start_at is not None:
        spline.setPole(1, start_at)  # a clamped spline starts at its first pole
    return spline.toShape()


def _turned_round(edge):
    """A closed edge run the other way round, from the same start."""
    curve = edge.Curve
    start = edge.valueAt(edge.FirstParameter)
    if isinstance(curve, Part.Circle):
        circle = Part.Circle(curve.Center, -curve.Axis, curve.Radius)
        circle.XAxis = start - curve.Center
        return circle.toShape(0.0, 2.0 * math.pi)
    spline = curve.toBSpline(edge.FirstParameter, edge.LastParameter)
    spline.reverse()
    return spline.toShape()


def chain_order(edges, backwards=()):
    """How the tool runs along edges given in the order they were picked.

    Returns chains, each a list of (index, reversed): consecutive edges that
    meet are run one after the other, the first one towards the second.
    An edge that does not meet the previous one starts a new chain.
    backwards: indices of edges whose chain is run the other way round,
    from its last edge to its first.
    """
    chains = []
    end = None
    for i, edge in enumerate(edges):
        a, b = _ends(edge)
        if chains and end is not None and _meet(end, a):
            reverse = False
        elif chains and end is not None and _meet(end, b):
            reverse = True
        else:
            chains.append([])
            reverse = False
            following = edges[i + 1] if i + 1 < len(edges) else None
            if following is not None and not edge.isClosed():
                na, nb = _ends(following)
                if not (_meet(b, na) or _meet(b, nb)) and (_meet(a, na) or _meet(a, nb)):
                    reverse = True
        chains[-1].append((i, reverse))
        end = a if reverse else b
    backwards = set(backwards)
    return [
        [(i, not reverse) for i, reverse in reversed(chain)] if any(i in backwards for i, _r in chain) else chain
        for chain in chains
    ]


def sketch_edges(sketch, names=()):
    """Edges of a sketch in its own coordinates (z = 0), by name ("Edge3")
    in the given order; all of them, in the sketch's order, without names."""
    to_sketch = sketch.Placement.inverse().toMatrix()
    shape = sketch.Shape
    if names:
        missing = [n for n in names if not n.startswith("Edge") or int(n[4:]) > len(shape.Edges)]
        if missing:
            raise ProjectError("{} has no line {}.".format(sketch.Label, ", ".join(missing)))
        edges = [shape.getElement(n) for n in names]
    else:
        edges = list(shape.Edges)
    return [e.transformed(to_sketch) for e in edges]


def is_circle(edge):
    """True for a full circle, the edge of a hole."""
    return isinstance(edge.Curve, Part.Circle) and edge.isClosed()


def _sketch_holes(sketch):
    """The holes of a sketch: {name: [names of its lines]}, in the sketch's
    order. A hole is a full circle, or arcs of one circle closing it all
    round (a model's hole edges are halves, so are those of a sketch of
    its face); it is named after its first line."""
    holes = {}
    arcs = []  # [[names], centre, radius, angle covered]
    for i, edge in enumerate(sketch.Shape.Edges, start=1):
        name = "Edge{}".format(i)
        if is_circle(edge):
            holes[name] = [name]
        elif isinstance(edge.Curve, Part.Circle):
            centre, radius = edge.Curve.Center, edge.Curve.Radius
            angle = edge.LastParameter - edge.FirstParameter
            for arc in arcs:
                if _meet(arc[1], centre) and abs(arc[2] - radius) < _MEET_MM:
                    arc[0].append(name)
                    arc[3] += angle
                    break
            else:
                arcs.append([[name], centre, radius, angle])
    for names, _centre, _radius, angle in arcs:
        if len(names) > 1 and abs(angle - 2.0 * math.pi) < 1e-6:
            holes[names[0]] = names
    return dict(sorted(holes.items(), key=lambda hole: int(hole[0][4:])))


def sketch_circles(sketch):
    """Names of the sketch's holes (_sketch_holes), in the sketch's order."""
    return list(_sketch_holes(sketch))


def hole_name(sketch, line):
    """Name of the sketch's hole a line ("Edge3") belongs to, else None."""
    for name, lines in _sketch_holes(sketch).items():
        if line in lines:
            return name
    return None


def hole_lines(sketch, name):
    """The lines of a sketch's hole by its name (_sketch_holes)."""
    return _sketch_holes(sketch).get(name, [name])


def hole_circles(sketch, names):
    """Circles of a sketch's holes by name, in its own coordinates: a hole
    of arcs gives their full circle. ProjectError when one of them is not
    a hole."""
    holes = _sketch_holes(sketch)
    edges = [
        e.Curve.toShape() if name in holes and not is_circle(e) else e
        for name, e in zip(names, sketch_edges(sketch, names))
    ]
    wrong = [name for name, edge in zip(names, edges) if not is_circle(edge)]
    if wrong:
        raise ProjectError(
            "{}: {} {} not a circle; only full circles can be drilled.".format(
                sketch.Label, ", ".join(wrong), "is" if len(wrong) == 1 else "are"
            )
        )
    return edges


def _middle(edge):
    return edge.valueAt(edge.getParameterByLength(edge.Length / 2.0))


def all_lines(sketch):
    """Names of all the sketch's lines, in connected chains."""
    edges = list(sketch.Shape.Edges)
    names = []
    # sortEdges returns copies (some of them turned round): found by their middle
    for chain in Part.sortEdges(edges):
        for edge in chain:
            middle = _middle(edge)
            index = min(range(len(edges)), key=lambda i: _middle(edges[i]).distanceToPoint(middle))
            names.append("Edge{}".format(index + 1))
    return names


def line_runs(sketch, names=(), backwards=()):
    """How the tool runs along the lines (all of them without names): chains
    of (name, reversed) in the tool's order. backwards: names of lines whose
    chain is run the other way round."""
    names = list(names) or all_lines(sketch)
    edges = sketch_edges(sketch, names)
    backwards = set(backwards)
    flipped = [i for i, name in enumerate(names) if name in backwards]
    return [[(names[i], reverse) for i, reverse in chain] for chain in chain_order(edges, flipped)]


def contour_chains(sketch, names=(), backwards=(), flipped=False):
    """Edges the tool follows, chain by chain, in sketch coordinates; each
    edge is built fresh in the tool's direction.

    With names: the picked lines in the order they were picked, each chain
    starting at its first line (at its last one when the chain is run
    backwards). Without: all lines, in connected chains. flipped: in the
    coordinates of facing_tool (the sketch turned over to face the tool),
    so left and right are as the tool sees them.
    """
    turn = FreeCAD.Placement(FreeCAD.Vector(), FLIP).toMatrix()  # its own inverse
    chains = []
    for chain in line_runs(sketch, names, backwards):
        edges = sketch_edges(sketch, [name for name, _reverse in chain])
        built = []
        for edge, (_name, reverse) in zip(edges, chain):
            built.append(_directed(edge, reverse, _end(built[-1]) if built else None))
        chains.append([e.transformed(turn) for e in built] if flipped else built)
    return chains


def contour_wires(sketch, names=(), backwards=()):
    """Wires the tool follows, in sketch coordinates (see contour_chains)."""
    return [Part.Wire(chain) for chain in contour_chains(sketch, names, backwards)]


def line_chains(sketch, names):
    """The picked lines split into chains the tool runs without lifting,
    each in the order the lines were picked."""
    edges = sketch_edges(sketch, names)
    return [[names[i] for i in sorted(i for i, _reverse in chain)] for chain in chain_order(edges)]


def line_arrows(sketch, names=(), backwards=()):
    """Where the tool's direction is shown: (name, point, direction) for
    each line, in the middle of its length, in sketch coordinates."""
    arrows = []
    for chain in line_runs(sketch, names, backwards):
        edges = sketch_edges(sketch, [name for name, _reverse in chain])
        for edge, (name, reverse) in zip(edges, chain):
            at = edge.getParameterByLength(edge.Length / 2.0)
            direction = edge.tangentAt(at)
            arrows.append((name, edge.valueAt(at), -direction if reverse else direction))
    return arrows


# -- radius compensation ----------------------------------------------------------
#
# With RL/RR the program has the lines themselves and the control keeps the
# tool beside them by its radius (from the tool table); the tool comes in
# and leaves on arcs (model.leads). FreeCAD's path is where the tool
# centre really goes, so the 3D view and the simulation show the cut.

# how close an offset has to come to where it should start and end, mm
_OFFSET_MM = 1e-3


def _start(edge):
    return edge.valueAt(edge.FirstParameter)


def _end(edge):
    return edge.valueAt(edge.LastParameter)


def _xy(point):
    return (point.x, point.y)


def _point(xy):
    return FreeCAD.Vector(xy[0], xy[1], 0.0)


def _tangent(edge, at_end=False):
    """Unit direction of a directed edge at its start (or end), in its plane."""
    t = edge.tangentAt(edge.LastParameter if at_end else edge.FirstParameter)
    length = math.hypot(t.x, t.y)
    return (t.x / length, t.y / length)


def _line(a, b):
    return Part.LineSegment(_point(a), _point(b)).toShape()


def _arc(centre, a, b):
    """The arc around centre from a to b, shorter than half a turn."""
    c, a, b = _point(centre), _point(a), _point(b)
    middle = (a + b) * 0.5 - c
    middle.normalize()
    return Part.Arc(a, c + middle * (a - c).Length, b).toShape()


def _part(edge, u0, u1):
    """The piece of a directed edge between two of its parameters."""
    a, b = edge.valueAt(u0), edge.valueAt(u1)
    curve = edge.Curve
    if isinstance(curve, (Part.Line, Part.LineSegment)):
        return Part.LineSegment(a, b).toShape()
    if isinstance(curve, Part.Circle):
        return Part.Arc(a, edge.valueAt((u0 + u1) / 2.0), b).toShape()
    spline = curve.toBSpline(edge.FirstParameter, edge.LastParameter)
    spline.segment(u0, u1)
    return spline.toShape()


def _walk(edges):
    """The edges of a wire built fresh in the order they are walked."""
    built = []
    for i, edge in enumerate(edges):
        a, b = _ends(edge)
        if built:
            reverse = not _meet(_end(built[-1]), a)
        else:
            following = edges[i + 1] if i + 1 < len(edges) else None
            reverse = following is not None and not edge.isClosed() and not any(_meet(b, p) for p in _ends(following))
        built.append(_directed(edge, reverse, _end(built[-1]) if built else None))
    return built


def _turned(edges):
    """A walk of edges the other way round."""
    built = []
    for edge in reversed(edges):
        built.append(_directed(edge, True, _end(built[-1]) if built else None))
    return built


class Run(NamedTuple):
    """How the tool runs one chain of lines in one XY pass, in sketch coordinates."""

    program: list  # edges as the program has them
    centre: list  # edges the tool centre follows (the program's without compensation)
    side: object  # LEFT/RIGHT: the control keeps the tool there (RL/RR); None: R0
    lead: bool  # comes in and leaves on arcs; else straight down on the lines
    chain: int = 0  # which chain of the lines, from 0
    offset: float = 0.0  # the program's lines this far beside the sketch's, mm (negative: the other side)


def _from_middle(chain):
    """(edges, closed): a closed chain starts and ends in the middle of its
    first line, so the tool does not go down or come in at a corner."""
    closed = _meet(_start(chain[0]), _end(chain[-1]))
    if not closed:
        return chain, False
    edge = chain[0]
    middle = edge.getParameterByLength(edge.Length / 2.0)
    return [_part(edge, middle, edge.LastParameter)] + chain[1:] + [_part(edge, edge.FirstParameter, middle)], True


def _beside(lines, side, distance):
    """(first, last) point of the lines moved by distance to a side."""
    nx, ny = model_leads.side_normal(_tangent(lines[0]), side)
    first = FreeCAD.Vector(nx, ny, 0.0) * distance + _start(lines[0])
    nx, ny = model_leads.side_normal(_tangent(lines[-1], True), side)
    return first, FreeCAD.Vector(nx, ny, 0.0) * distance + _end(lines[-1])


def contour_runs(
    sketch, names, backwards, compensation, approach, lead_radius, tool_radius, offsets=(0.0,), arc_side=model_nc.LEFT,
    start_extend=0.0, end_extend=0.0, flipped=False,
):  # fmt: skip
    """How the tool runs the lines, chain by chain and in each chain pass by
    pass (Run), in sketch coordinates (flipped: of facing_tool, for a
    sketch facing away from the tool).

    compensation LEFT/RIGHT: the program has the lines and the control keeps
    the tool beside them; the tool centre goes along them moved by the tool
    radius, round the outside corners on arcs and cut short at the inside
    ones. Else its centre is on the lines.
    approach ARC: a line from the centre of an arc of lead_radius to the
    arc, the arc onto the lines, the lines, the arc off them and a line back
    to its centre (model.leads); with compensation the tool centre runs the
    arcs smaller by its radius, without it they are on arc_side of the
    lines. NONE: the lines only.
    offsets: one pass for each, its program the lines moved that far to the
    tool's side (negative: to the other side); with compensation the tool
    centre goes beside these, as the control runs them. Without it only
    one, to arc_side, and the tool centre runs it (e.g. a chamfer mill's
    centre beside the edge); a closed chain then starts in the middle of
    its first line too.
    start_extend, end_extend: an open chain's lines longer (positive) or
    shorter (negative) at its start and end (engine.contour_ends), before
    all that.
    """
    side = compensation if compensation in (model_nc.LEFT, model_nc.RIGHT) and tool_radius > 0.0 else None
    lead = approach == model_operations.ARC
    if lead and side is not None and lead_radius <= tool_radius:
        raise ProjectError(
            "{}: with compensation the approach radius ({:g} mm) must be larger than the tool radius "
            "({:g} mm).".format(sketch.Label, lead_radius, tool_radius)
        )
    if side is None and len(offsets) > 1:
        raise ProjectError("{}: XY passes need tool compensation left or right.".format(sketch.Label))
    runs = []
    ends = bool(start_extend or end_extend)
    for index, chain in enumerate(contour_chains(sketch, names, backwards, flipped)):
        if side is None and not lead and not any(offsets) and not ends:
            runs.append(Run(chain, chain, None, False, index))
            continue
        lines, closed = _from_middle(chain)
        if ends:
            from avangardecam.engine import contour_ends

            if closed:
                raise ProjectError(
                    "{}: Start contour and End contour are for open lines, not a closed loop.".format(sketch.Label)
                )
            try:
                lines = contour_ends.changed(lines, start_extend, end_extend, sketch.Label)
            except contour_ends.EndsError as exc:
                raise ProjectError(str(exc)) from None
        for offset in offsets:
            program = lines
            if offset:
                there = side or arc_side
                there = there if offset > 0.0 else model_leads.other_side(there)
                first, last = _beside(lines, there, abs(offset))
                try:
                    program = _offset(sketch, lines, closed, first, last, _tangent(lines[0]), abs(offset))
                except ProjectError:
                    raise ProjectError(
                        "{}: there is no room for the pass {:g} mm beside these lines.".format(sketch.Label, offset)
                    ) from None
            run = _run(sketch, program, closed, side, lead, lead_radius, tool_radius, arc_side)
            runs.append(run._replace(chain=index, offset=offset))
    return runs


def _run(sketch, lines, closed, side, lead, lead_radius, tool_radius, arc_side):
    """The Run of lines that start where the tool comes onto them."""
    first, last = _start(lines[0]), _end(lines[-1])
    program = lines
    if lead:
        # without compensation the arcs come from arc_side of the lines
        arc_side = side or arc_side
        c_in, p_in = model_leads.lead_in(_xy(first), _tangent(lines[0]), arc_side, lead_radius)
        c_out, p_out = model_leads.lead_out(_xy(last), _tangent(lines[-1], True), arc_side, lead_radius)
        program = [_line(c_in, p_in), _arc(c_in, p_in, _xy(first))] + lines + [_arc(c_out, _xy(last), p_out), _line(p_out, c_out)]  # fmt: skip
    if side is None:
        return Run(program, program, None, lead)
    moved_first, moved_last = _beside(lines, side, tool_radius)
    centre = _offset(sketch, lines, closed, moved_first, moved_last, _tangent(lines[0]), tool_radius)
    if lead:
        scale = (lead_radius - tool_radius) / lead_radius

        def inner(c, p):
            return (c[0] + scale * (p[0] - c[0]), c[1] + scale * (p[1] - c[1]))

        q_in, q_out = inner(c_in, p_in), inner(c_out, p_out)
        centre = (
            [_line(c_in, q_in), _arc(c_in, q_in, _xy(moved_first))]
            + centre
            + [_arc(c_out, _xy(moved_last), q_out), _line(q_out, c_out)]
        )
    return Run(program, centre, side, lead)


def _offset(sketch, lines, closed, first, last, tangent, distance):
    """The lines moved by distance to the tool's side, walked from first to
    last: OCCT's 2D offset, arcs round the outside corners. OCCT needs the
    lines' plane, so lines on one straight line and a single arc (no plane,
    or no corners) are moved here."""
    if not closed and len(lines) == 1 and isinstance(lines[0].Curve, Part.Circle):
        run = [_moved(lines[0], first - _start(lines[0]), last - _end(lines[0]), sketch, distance)]
    elif not closed and _straight(lines):
        shift = first - _start(lines[0])
        run = [Part.LineSegment(_start(e) + shift, _end(e) + shift).toShape() for e in lines]
    else:
        run = _occt_offset(sketch, lines, closed, first, tangent, distance)
    if _start(run[0]).distanceToPoint(first) > _OFFSET_MM or _end(run[-1]).distanceToPoint(last) > _OFFSET_MM:
        raise ProjectError(_no_room(sketch, distance))
    return run


def _no_room(sketch, distance):
    return "{}: the tool ({:g} mm radius) does not fit along these lines with radius compensation.".format(
        sketch.Label, distance
    )


def _straight(lines):
    """True when all the lines lie on one straight line."""
    if not all(isinstance(e.Curve, (Part.Line, Part.LineSegment)) for e in lines):
        return False
    a = _start(lines[0])
    d = _end(lines[0]) - a
    d.normalize()
    return all(abs((p - a).x * d.y - (p - a).y * d.x) < 1e-9 for e in lines for p in _ends(e))


def _moved(arc, shift_start, shift_end, sketch, distance):
    """An arc moved to the tool's side: the same centre, its radius larger
    or smaller by distance."""
    centre = arc.Curve.Center
    radius = (_start(arc) + shift_start - centre).Length
    if radius < _OFFSET_MM or abs(abs(radius - arc.Curve.Radius) - distance) > _OFFSET_MM:
        raise ProjectError(_no_room(sketch, distance))
    middle = arc.valueAt((arc.FirstParameter + arc.LastParameter) / 2.0) - centre
    middle.normalize()
    return Part.Arc(_start(arc) + shift_start, centre + middle * radius, _end(arc) + shift_end).toShape()


def _occt_offset(sketch, lines, closed, first, tangent, distance):
    wire = Part.Wire(lines)
    start = Part.Vertex(first)
    for d in (distance, -distance):  # which sign is which side depends on the wire
        try:
            shape = wire.makeOffset2D(d, 0, False, not closed, False)
        except (Part.OCCError, FreeCAD.Base.FreeCADError):  # "offset result has no wires": no room
            continue
        if len(shape.Wires) == 1 and shape.distToShape(start)[0] < _OFFSET_MM:
            break
    else:
        raise ProjectError(_no_room(sketch, distance))
    run = _walk(shape.Wires[0].OrderedEdges)
    if not closed:
        return _turned(run) if _start(run[0]).distanceToPoint(first) > _OFFSET_MM else run
    # start at the first point, in the tool's direction
    i = min(range(len(run)), key=lambda k: run[k].distToShape(start)[0])
    edge = run[i]
    if _start(edge).distanceToPoint(first) < _OFFSET_MM:
        run = run[i:] + run[:i]
    elif _end(edge).distanceToPoint(first) < _OFFSET_MM:
        run = run[i + 1 :] + run[: i + 1]
    else:
        u = edge.Curve.parameter(first)
        run = [_part(edge, u, edge.LastParameter)] + run[i + 1 :] + run[:i] + [_part(edge, edge.FirstParameter, u)]
    t = _tangent(run[0])
    return _turned(run) if t[0] * tangent[0] + t[1] * tangent[1] < 0.0 else run


def helper_lines(obj):
    """(names, backwards) of a ContourLines object, as contour_chains takes them."""
    edges = list(obj.Edges)
    # older documents have no Reversed
    backwards = (edges or all_lines(obj.Sketch)) if getattr(obj, "Reversed", False) else ()
    return edges, backwards


# -- picking lines like in Blender ------------------------------------------------

# line ends are matched to the micrometre fraction when walking a sketch
_KEY_DECIMALS = 6


def _key(point):
    return tuple(round(c, _KEY_DECIMALS) + 0.0 for c in point)


def _line_graph(sketch):
    """{name: (start key, end key, length)} of a sketch's lines."""
    graph = {}
    for i, edge in enumerate(sketch.Shape.Edges, start=1):
        a, b = _ends(edge)
        graph["Edge{}".format(i)] = (_key(a), _key(b), edge.Length)
    return graph


def line_loop(sketch, name):
    """The lines of the sketch's wire that holds the line, starting with it
    and following the wire (Alt+click)."""
    edges = sketch.Shape.Edges
    target = sketch.Shape.getElement(name)
    for wire in sketch.Shape.Wires:
        ordered = list(wire.OrderedEdges)
        at = next((k for k, e in enumerate(ordered) if e.isSame(target)), None)
        if at is None:
            continue
        ordered = ordered[at:] + ordered[:at]
        names = []
        for e in ordered:
            index = next(i for i, x in enumerate(edges, start=1) if x.isSame(e))
            names.append("Edge{}".format(index))
        return names
    return [name]


def line_path(sketch, picked, name):
    """Lines leading from the end of the picked lines (in click order) to
    the line name, by the shortest way along the sketch (Ctrl+click).
    Neither the last picked line nor name are part of the result."""
    if not picked:
        return []
    graph = _line_graph(sketch)
    last = graph[picked[-1]]
    starts = {last[0], last[1]}
    if len(picked) > 1:
        before = graph[picked[-2]]
        shared = starts & {before[0], before[1]}
        if len(shared) == 1 and len(starts) == 2:
            starts -= shared  # the chain runs on from the free end
    goals = {graph[name][0], graph[name][1]}
    if starts & goals:
        return []
    skip = {picked[-1], name}
    queue = [(0.0, i, point, ()) for i, point in enumerate(sorted(starts))]
    heapq.heapify(queue)
    done = set()
    counter = len(queue)
    while queue:
        dist, _n, point, path = heapq.heappop(queue)
        if point in goals:
            return list(path)
        if point in done:
            continue
        done.add(point)
        for line, (a, b, length) in graph.items():
            if line in skip or point not in (a, b):
                continue
            other = b if point == a else a
            if other not in done:
                counter += 1
                heapq.heappush(queue, (dist + length, counter, other, path + (line,)))
    return []


def add_compensation(obj):
    """Compensation and approach properties of a ContourLines object (also
    for ones from older documents)."""
    for kind, name, tip in (
        ("App::PropertyString", "Compensation", "Side the control keeps the tool on: left (RL), right (RR); else the tool centre is on the lines"),  # fmt: skip
        ("App::PropertyLength", "ToolRadius", "Radius of the tool, for its centre's path"),
        ("App::PropertyString", "Approach", "How the tool comes onto the lines: arc, or none (straight down)"),
        ("App::PropertyLength", "LeadRadius", "Radius of the approach arcs"),
        ("App::PropertyString", "ArcSide", "Without compensation: side of the lines the approach arcs are on, left or right"),  # fmt: skip
        ("App::PropertyDistance", "StartExtend", "Start contour: the lines this much longer at their start (negative: shorter)"),  # fmt: skip
        ("App::PropertyDistance", "EndExtend", "End contour: the lines this much longer at their end (negative: shorter)"),  # fmt: skip
        ("App::PropertyBool", "Flipped", "The sketch faces away from the tool (e.g. the part's bottom used from the top): its lines are seen from the tool's side"),  # fmt: skip
    ):
        if not hasattr(obj, name):
            obj.addProperty(kind, name, "AvangardeCam", tip)


class ContourLines:
    """Proxy of a contour's geometry: lines of a sketch in the order the
    tool follows them, in the sketch's coordinates (Flipped: turned over to
    face the tool, facing_tool). Follows changes of the sketch. Its
    Placement puts it into the setup's coordinates."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "Sketch", "AvangardeCam", "Sketch the lines belong to")
        obj.addProperty(
            "App::PropertyStringList", "Edges", "AvangardeCam", "Lines in the order the tool follows them; empty: all"
        )
        obj.addProperty(
            "App::PropertyBool", "Reversed", "AvangardeCam", "The tool runs the lines the other way round, from the last"
        )
        add_compensation(obj)
        obj.Proxy = self

    def execute(self, obj):
        if obj.Sketch is None:
            return
        edges, backwards = helper_lines(obj)
        # older documents have no compensation nor approach
        runs = contour_runs(
            obj.Sketch,
            edges,
            backwards,
            getattr(obj, "Compensation", ""),
            getattr(obj, "Approach", ""),
            obj.LeadRadius.Value if hasattr(obj, "LeadRadius") else 0.0,
            obj.ToolRadius.Value if hasattr(obj, "ToolRadius") else 0.0,
            arc_side=getattr(obj, "ArcSide", "") or model_nc.LEFT,
            start_extend=obj.StartExtend.Value if hasattr(obj, "StartExtend") else 0.0,
            end_extend=obj.EndExtend.Value if hasattr(obj, "EndExtend") else 0.0,
            flipped=getattr(obj, "Flipped", False),
        )
        shape = Part.makeCompound([Part.Wire(run.centre) for run in runs])
        shape.Placement = obj.Placement
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None


class HoleCircles:
    """Proxy of a drilling's holes: circles of a sketch in the order the
    tool drills them, in the sketch's coordinates. Follows changes of the
    sketch. Its Placement puts it into the setup's coordinates."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "Sketch", "AvangardeCam", "Sketch the circles belong to")
        obj.addProperty("App::PropertyStringList", "Edges", "AvangardeCam", "Circles in the order the tool drills them")
        obj.Proxy = self

    def execute(self, obj):
        if obj.Sketch is None:
            return
        shape = Part.makeCompound(hole_circles(obj.Sketch, list(obj.Edges)))
        shape.Placement = obj.Placement
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None


# -- holes of a model --------------------------------------------------------------

# radii and axes of a hole's faces are matched to this, mm
_SAME_MM = 1e-4
# probes for the end of a hole lie this far beyond it, mm: closer than any
# drill point's slope gets to the wall in that distance
_END_PROBE_MM = 1e-3
# a hole's wall is probed for material all round at this many points
_AROUND = 24


class ModelHole(NamedTuple):
    """A round hole of a model, in part coordinates, seen from the tool
    (up: the tool axis, towards the tool). top: the centre of its top on
    its axis; depth: how far its cylinder goes down from there (negative)
    and whether it comes out the other side of the part."""

    name: str  # the element the user picked ("Face12", "Edge7")
    top: FreeCAD.Vector
    radius: float
    depth: model_operations.HoleDepth
    faces: tuple  # names of the faces of its cylinder


def _coaxial(surface, centre, axis):
    """True when a cylinder or cone has the axis through centre along axis."""
    if abs(abs(surface.Axis.dot(axis)) - 1.0) > 1e-9:
        return False
    offset = surface.Center - centre if hasattr(surface, "Center") else surface.Apex - centre
    return (offset - axis * offset.dot(axis)).Length < _SAME_MM


def _span(face, centre, up):
    """(lowest, highest) of a cylinder or cone face along up, from centre."""
    u0, u1, v0, v1 = face.ParameterRange
    heights = [(face.Surface.value(u, v) - centre).dot(up) for u in (u0, (u0 + u1) / 2.0) for v in (v0, v1)]
    return min(heights), max(heights)


def _solid_with(shape, face):
    return next((s for s in shape.Solids if any(f.isSame(face) for f in s.Faces)), None)


def _cylinders(shape, element):
    """Cylinder faces of the hole a picked face or circle edge belongs to."""
    if element.ShapeType == "Face":
        return [element] if isinstance(element.Surface, Part.Cylinder) else []
    if element.ShapeType == "Edge" and isinstance(element.Curve, Part.Circle):
        circle = element.Curve
        return [
            f
            for f in shape.ancestorsOfType(element, Part.Face)
            if isinstance(f.Surface, Part.Cylinder)
            and abs(f.Surface.Radius - circle.Radius) < _SAME_MM
            and _coaxial(f.Surface, circle.Center, circle.Axis)
        ]
    return []


def _inside(solid, point):
    return solid.isInside(point, 1e-7, False)


def _across(up):
    """Two unit vectors across up."""
    side = up.cross(FreeCAD.Vector(1, 0, 0))
    if side.Length < 0.5:
        side = up.cross(FreeCAD.Vector(0, 1, 0))
    side.normalize()
    return side, up.cross(side)


# holes recognised: picking, the operation, its helper and every recompute
# ask for the same holes again, and each costs ~30 point-in-solid tests
# (Shape.isInside, ~6 ms each on a part of 150 faces: 5 holes took 6 s).
# An entry keeps its shape, so no other shape can take its hash code.
_HOLES_KNOWN = collections.OrderedDict()
_HOLES_KNOWN_MAX = 512


def model_hole(obj, name, up):
    """The hole of a model the user picked by one of its faces or its circle
    edge (name), seen from a tool coming along up (part coordinates):
    _recognise_hole, remembered for the same shape, element and tool axis."""
    shape = obj.Shape
    key = (shape.hashCode(), name, tuple(round(c, 12) + 0.0 for c in up))
    known = _HOLES_KNOWN.get(key)
    if known is not None and known[0].isSame(shape):
        _HOLES_KNOWN.move_to_end(key)
        hole = known[1]
        return hole._replace(top=FreeCAD.Vector(hole.top))
    hole = _recognise_hole(obj, shape, name, up)
    _HOLES_KNOWN[key] = (shape, hole._replace(top=FreeCAD.Vector(hole.top)))
    while len(_HOLES_KNOWN) > _HOLES_KNOWN_MAX:
        _HOLES_KNOWN.popitem(last=False)
    return hole


def _recognise_hole(obj, shape, name, up):
    """The hole of a model the user picked by one of its faces or its circle
    edge (name), seen from a tool coming along up (part coordinates).

    The hole is the whole cylinder: its faces with the same axis and radius
    that meet (STEP often splits a cylinder in halves). Its top must be
    open towards the tool. It goes through when nothing of the part is
    right under its cylinder (else a floor, a drill point or a smaller
    hole ends it). ProjectError when the element is not a hole's, or the
    hole does not run along up or opens away from the tool."""
    element = shape.getElement(name)
    cylinders = _cylinders(shape, element)
    if not cylinders:
        raise ProjectError(
            "{} of {} is not the wall or the edge of a round hole. Click the inside of a hole or its round edge.".format(name, obj.Label)  # fmt: skip
        )
    face = cylinders[0]
    surface = face.Surface
    radius = surface.Radius
    centre = surface.Center
    solid = _solid_with(shape, face)
    if solid is None:
        raise ProjectError("{} is not a solid; its holes cannot be drilled.".format(obj.Label))
    # a hole has the material outside its cylinder, a pin or a round inside
    u0, u1, v0, v1 = face.ParameterRange
    point = face.Surface.value((u0 + u1) / 2.0, (v0 + v1) / 2.0)
    radial = point - centre - surface.Axis * (point - centre).dot(surface.Axis)
    radial.normalize()
    if not _inside(solid, point + radial * _PROBE_MM) or _inside(solid, point - radial * _PROBE_MM):
        raise ProjectError("{} of {} is not a hole (the material is inside it).".format(name, obj.Label))
    # material all round: not a rounded inner corner, an arch or the end of a slot
    level = surface.Axis * (point - centre).dot(surface.Axis)
    side, other = _across(surface.Axis)
    for k in range(_AROUND):
        a = 2.0 * math.pi * k / _AROUND
        if not _inside(solid, centre + level + (side * math.cos(a) + other * math.sin(a)) * (radius + _PROBE_MM)):
            raise ProjectError(
                "{} of {} is not a round hole: its wall is open (a rounded corner or the end of a slot?).".format(name, obj.Label)  # fmt: skip
            )
    up = FreeCAD.Vector(up)
    up.normalize()
    if abs(abs(surface.Axis.dot(up)) - 1.0) > 1e-6:
        raise ProjectError(
            "The hole of {} ({}) does not run along the tool axis of the setup. Use Snap-0-Point on a face square to the hole first.".format(obj.Label, name)  # fmt: skip
        )

    # the whole cylinder: faces with its axis and radius that meet it
    same = [
        (i, f)
        for i, f in enumerate(solid.Faces)
        if isinstance(f.Surface, Part.Cylinder)
        and abs(f.Surface.Radius - radius) < _SAME_MM
        and _coaxial(f.Surface, centre, up)
    ]
    low, high = _span(face, centre, up)
    group = [f for _i, f in same if f.isSame(face)]
    grown = True
    while grown:
        grown = False
        for _i, f in same:
            if any(f.isSame(g) for g in group):
                continue
            a, b = _span(f, centre, up)
            if a <= high + _SAME_MM and b >= low - _SAME_MM:
                group.append(f)
                low, high = min(low, a), max(high, b)
                grown = True
    names = tuple(
        "Face{}".format(i) for i, f in enumerate(shape.Faces, start=1) if any(f.isSame(g) for g in group)
    )

    top = centre + up * high
    if _inside(solid, top + up * _PROBE_MM):
        raise ProjectError(
            "The hole of {} ({}) is closed at the top; the tool of this setup cannot reach it.".format(obj.Label, name)
        )
    # ends: a floor or a step to a smaller hole under its wall, or a drill point
    bottom = centre + up * low
    side, other = _across(up)
    ring = [bottom - up * _END_PROBE_MM + d * (radius - 10.0 * _END_PROBE_MM) for d in (side, -side, other, -other)]
    blind = any(_inside(solid, p) for p in ring + [bottom - up * _END_PROBE_MM])
    if not blind:
        for f in solid.Faces:
            if isinstance(f.Surface, Part.Cone) and _coaxial(f.Surface, centre, up):
                a, b = _span(f, centre, up)
                apex = (f.Surface.Apex - centre).dot(up)
                if abs(b - low) < _SAME_MM and apex < low:
                    blind = True  # narrowing under the cylinder: a drill point
                    break
    return ModelHole(name, top, radius, model_operations.HoleDepth(low - high, not blind), names)


def model_holes(obj, names, up):
    """The holes of a model the user picked, each once, in the order they
    were picked (several elements of one hole: its first)."""
    holes = []
    for name in names:
        hole = model_hole(obj, name, up)
        if not any((h.top - hole.top).Length < _SAME_MM for h in holes):
            holes.append(hole)
    return holes


def setup_up(place):
    """The tool axis, in part coordinates, of a helper placed by a setup
    (its Placement: part -> setup coordinates)."""
    return place.Rotation.inverted().multVec(FreeCAD.Vector(0, 0, 1))


class ModelHoles:
    """Proxy of a drilling's holes picked in a model: one element of each
    hole (its wall or its round edge) in the order the tool drills them.
    Its shape is the circle of each hole's top, in the same order; its
    Placement puts the part into the setup's coordinates, so the tool axis
    is the setup's. Follows changes of the model."""

    def __init__(self, obj):
        obj.addProperty("App::PropertyLink", "Model", "AvangardeCam", "Model the holes belong to")
        obj.addProperty("App::PropertyStringList", "Holes", "AvangardeCam", "An element of each hole, in the order the tool drills them")  # fmt: skip
        obj.Proxy = self

    def execute(self, obj):
        if obj.Model is None:
            return
        up = setup_up(obj.Placement)
        circles = [Part.makeCircle(h.radius, h.top, up) for h in model_holes(obj.Model, list(obj.Holes), up)]
        shape = Part.makeCompound(circles)
        shape.Placement = obj.Placement
        obj.Shape = shape

    def dumps(self):
        return None

    def loads(self, state):
        return None
