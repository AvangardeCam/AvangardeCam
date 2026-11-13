# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Facing (model.facing) on FreeCAD: the operation, its area and its path.

For now (the user's choice, 2026-10-21) a facing levels the top of the
model only: the picked face must have nothing of the setup's models above
it (_check_top), and the tool faces the whole stock down to it. The area
below works for faces with walls too (steps, floors), for later; only
plan_for reaches it for such faces now (the tests).

The area of a picked flat face is worked out in the setup's XY, from
the Job's clones of the models and its stock:
- keep-out: the models above the face seen from the tool, grown by the
  tool's radius and the user's offset (the tool measured at its widest,
  as the shop measures every tool), so the tool's edge stays that far
  from the walls going up from the face;
- the stock grown by the tool's radius and the overrun: over open edges
  (nothing above, or a step down) the tool goes out past the stock until
  it leaves the material;
- the area: that grown stock less the keep-out, the pieces under the
  picked face. A face with nothing above it is faced over the whole stock.
The links between passes may go a tool's diameter further out than the
passes (the half circles beside the stock).

The operation is FreeCAD's Mill Facing (MillFace) with this proxy, so
expert mode shows FreeCAD's values; its Base is the picked face of the
Job's clone of the model, which moves with the zero point. Its path is
where the tool centre goes, and the NC program reads it
(freecad_cam.nc_moves).
"""

import FreeCAD
import Part
import Path
import Path.Op.Adaptive as PathAdaptive
import Path.Op.MillFace as PathMillFace

from avangardecam.engine import freecad_cam as cam
from avangardecam.model import facing as model_facing
from avangardecam.model import nc
from avangardecam.model import operations as model_operations

EPSILON_MM = 1e-3  # the models are sliced this much above the face
_INSIDE_MM = 1e-3  # a link this close to the edge of the area is inside

# tools that cut a flat floor with their end: a drill, a ball end or a chamfer does not
FACING_SHAPES = ("Endmill", "Bullnose")

_G = {nc.RAPID: "G0", nc.LINE: "G1"}


class Facing(PathMillFace.ObjectFace):
    def __init__(self, obj, name, parentJob, tc=None):
        # FreeCAD takes the tool of the operation before it in the setup, else
        # the only one it supports; with more it asks (FreeCADCmd: it fails)
        self._tool = tc
        try:
            super().__init__(obj, name, parentJob)
        finally:
            self._tool = None

    def isToolSupported(self, obj, tool):
        if getattr(self, "_tool", None) is not None:
            return tool is self._tool.Tool
        return super().isToolSupported(obj, tool)

    def opExecute(self, obj):
        if facing_of(obj) is None:  # not one of AvangardeCam's
            return super().opExecute(obj)
        try:
            moves = facing_moves(obj)
        except cam.ProjectError as exc:  # e.g. another tool chosen in expert mode
            Path.Log.error("{}: {}".format(obj.Label, exc))
            return
        if len(moves) > 1 and moves[-1].kind == nc.RAPID and (moves[-1].x, moves[-1].y) == (moves[-2].x, moves[-2].y):
            moves = moves[:-1]  # up at the end: FreeCAD adds the clearance height, the program its retract
        position = [None, None, None]
        for move in moves:
            p = {axis: value for axis, value in zip("XYZ", (move.x, move.y, move.z)) if value is not None}
            if move.kind == nc.ARC:
                p["I"] = move.center[0] - position[0]
                p["J"] = move.center[1] - position[1]
                name = "G2" if move.clockwise else "G3"
            else:
                name = _G[move.kind]
            if move.feed_mm_min is not None:
                p["F"] = move.feed_mm_min / 60.0  # FreeCAD keeps feeds in mm/s
            self.commandlist.append(Path.Command(name, p))
            position = [move.x, move.y, move.z]


def facing_of(op):
    """(model, model Facing) of a facing made by AvangardeCam, else None."""
    return cam._operation_of(op, model_facing.Facing)


def picked_face(job, model, faces):
    """(FreeCAD Base [(clone, names)], Z of the face) for flat faces picked in
    a model ("Face12"), facing the setup's tool, all at one height, at the
    top of the setup's models (_check_top)."""
    if not faces:
        raise cam.ProjectError("Click a flat face at the top of the model to face.")
    base = cam.picked_floors(job, model, faces)
    heights = cam.floor_heights(base)
    if max(heights) - min(heights) > 1e-6:
        raise cam.ProjectError(
            "The faces are at different heights (Z {}). Face one height at a time.".format(
                ", ".join("{:+.3f}".format(z) for z in sorted(set(round(h, 3) for h in heights), reverse=True))
            )
        )
    face_z = round(min(heights), 6) + 0.0
    _check_top(job, base, face_z)
    return base, face_z


def material_top(job, z):
    """Z of the top of the setup's models above z, or None when nothing of
    them is above it."""
    shapes = [clone.Shape for clone in job.Model.Group]
    found = []
    for shape in shapes:
        box = shape.BoundBox
        if box.ZMax <= z + EPSILON_MM:
            continue
        cut = Part.makeBox(box.XLength + 2, box.YLength + 2, box.ZMax - z, FreeCAD.Vector(box.XMin - 1, box.YMin - 1, z + EPSILON_MM))
        above = shape.common(cut)
        if above.Solids and above.Volume > 1e-9:
            found.append(above.optimalBoundingBox(False, False).ZMax)
    return max(found) if found else None


def _check_top(job, base, face_z):
    """ProjectError unless the face is at the top of the models: for now
    (the user's choice, 2026-10-21) facing levels the top only, over the
    whole stock."""
    top = material_top(job, face_z)
    if top is not None:
        names = ", ".join(name for _obj, names in base for name in names)
        raise cam.ProjectError(
            "Facing is for the top of the model: {} (Z{:+.3f}) has material above it, up to Z{:+.3f}. "
            "Click a face at the very top.".format(names, face_z, top)
        )


def _face_z(op):
    return round(min(cam.floor_heights(op.Base)), 6) + 0.0


def check(job, facing, tc, base):
    """(levels, Z of the face, tool) of a facing; ProjectError when the tool cannot face it."""
    try:
        facing.validate()
    except ValueError as exc:
        raise cam.ProjectError(str(exc)) from exc
    cam._check_tool(job, tc)
    if getattr(tc, "Tool", None) is None:
        raise cam.ProjectError("{} has no tool.".format(tc.Label))
    tool = cam._tool_from_controller(tc)
    if tool.shape not in FACING_SHAPES:
        raise cam.ProjectError("{} is not a face mill or an end mill; facing needs a flat end.".format(tc.Label))
    try:
        facing.check(tool.diameter_mm)
    except ValueError as exc:
        raise cam.ProjectError(str(exc)) from exc
    if job.Stock is None:
        raise cam.ProjectError("{} has no stock to face.".format(job.Label))
    if not base:
        raise cam.ProjectError("Click a flat face at the top of the model to face.")
    face_z = round(min(cam.floor_heights(base)), 6) + 0.0
    _check_top(job, base, face_z)
    top = facing.top_mm(cam.stock_bounds(job).z_max)
    levels = facing.levels(top, face_z)
    if not levels:
        raise cam.ProjectError(
            "Start Z (Z{:+g}) must be above the face (Z{:+g}).".format(round(top, 3), round(face_z, 3))
        )
    if len(levels) > model_operations.MAX_CUTS:
        raise cam.ProjectError("{} Z levels are too many (at most {}); take a larger Z step.".format(len(levels), model_operations.MAX_CUTS))  # fmt: skip
    deepest = max(a - b for a, b in zip([top] + levels, levels))
    if tool.cutting_length_mm and deepest > tool.cutting_length_mm + 1e-6:
        raise cam.ProjectError(
            "A level cuts {:g} mm deep, more than the cutting length of {} ({:g} mm). Enter a Z step.".format(
                round(deepest, 3), tc.Label, tool.cutting_length_mm
            )
        )
    return levels, face_z, tool


def _rectangle(bounds, grow):
    points = [
        FreeCAD.Vector(bounds.x_min - grow, bounds.y_min - grow, 0),
        FreeCAD.Vector(bounds.x_max + grow, bounds.y_min - grow, 0),
        FreeCAD.Vector(bounds.x_max + grow, bounds.y_max + grow, 0),
        FreeCAD.Vector(bounds.x_min - grow, bounds.y_max + grow, 0),
    ]
    return Part.Face(Part.makePolygon(points + points[:1]))


def _fused(faces):
    if not faces:
        return None
    return faces[0].fuse(faces[1:]).removeSplitter() if len(faces) > 1 else faces[0]


class Area:
    """Where the tool centre of a facing may go, at Z0 of the setup's XY."""

    def __init__(self, job, base, facing, diameter_mm):
        radius = diameter_mm / 2.0
        self.bounds = cam.stock_bounds(job)
        self.radius = radius
        face_z = round(min(cam.floor_heights(base)), 6) + 0.0
        shapes = [clone.Shape for clone in job.Model.Group]
        models = shapes[0].fuse(shapes[1:]) if len(shapes) > 1 else shapes[0]
        above = PathAdaptive._getSolidProjection(models, face_z + EPSILON_MM)
        keep_out = None
        if above.Faces:
            keep_out = _fused([f.makeOffset2D(radius + facing.offset_xy_mm, join=0) for f in above.Faces])
        self.limit = radius + facing.overrun_mm
        passes = _rectangle(self.bounds, self.limit)
        links = _rectangle(self.bounds, radius + facing.overrun_mm + diameter_mm)
        if keep_out is not None:
            passes, links = passes.cut(keep_out), links.cut(keep_out)
        picked = PathAdaptive.projectFacesToXY([obj.Shape.getElement(n) for obj, names in base for n in names])
        self.faces = [f for f in passes.Faces if any(f.common(p).Area > 1e-6 for p in picked.Faces)]
        if not self.faces:
            raise cam.ProjectError(
                "The tool (Ø{:g}) does not fit on the face beside its walls (offset {:g} mm).".format(
                    diameter_mm, facing.offset_xy_mm
                )
            )
        self.links = links.Faces

    def _on_limit(self, point):
        """The point lies on the edge of the grown stock (an open side)."""
        b, g, t = self.bounds, self.limit, 1e-6
        x0, x1, y0, y1 = b.x_min - g, b.x_max + g, b.y_min - g, b.y_max + g
        on_x = (abs(point.x - x0) < t or abs(point.x - x1) < t) and y0 - t <= point.y <= y1 + t
        on_y = (abs(point.y - y0) < t or abs(point.y - y1) < t) and x0 - t <= point.x <= x1 + t
        return on_x or on_y

    def walls(self):
        """[(start, moves)] of the tool centre along the walls going up from
        the face (the edges of the area that are not open sides), climbing:
        the wall on the tool's left (the spindle turns clockwise, M3). Open
        ones start and end out past the stock."""
        edges = [
            e
            for f in self.faces
            for e in f.Edges
            if not all(self._on_limit(p) for p in (e.Vertexes[0].Point, e.Vertexes[-1].Point, e.valueAt(_middle(e))))
        ]
        result = []
        for chain in Part.sortEdges(edges) if edges else []:
            start, moves = _chain_moves(chain)
            if self._region_on_left(start, moves[0]):
                start, moves = model_facing.reversed_moves(start, moves)
            result.append((start, moves))
        return result

    def _region_on_left(self, start, move):
        """The area lies on the left of the first move of a run."""
        if move[0] == "arc":  # just after its start, along its tangent
            rx, ry = start[0] - move[2][0], start[1] - move[2][1]
            dx, dy = (ry, -rx) if move[3] else (-ry, rx)
            length = (dx * dx + dy * dy) ** 0.5
            px, py = start[0] + dx / length * 0.01, start[1] + dy / length * 0.01
        else:
            dx, dy = move[1][0] - start[0], move[1][1] - start[1]
            length = (dx * dx + dy * dy) ** 0.5
            px, py = (start[0] + move[1][0]) / 2.0, (start[1] + move[1][1]) / 2.0
        left = FreeCAD.Vector(px - dy / length * 0.01, py + dx / length * 0.01, 0)
        return any(f.isInside(left, 1e-6, True) for f in self.faces)

    def fits(self, points):
        return all(any(f.isInside(FreeCAD.Vector(x, y, 0), _INSIDE_MM, True) for f in self.links) for x, y in points)

    def outside(self, x, y):
        """The tool at (x, y) is clear of the stock."""
        b = self.bounds
        dx = max(b.x_min - x, 0.0, x - b.x_max)
        dy = max(b.y_min - y, 0.0, y - b.y_max)
        return (dx * dx + dy * dy) ** 0.5 >= self.radius - _INSIDE_MM

    def rows(self, facing, step_mm, diameter_mm):
        """[(v, ((u0, u1), ...))] of the pass lines across the area, in the
        order the tool steps over (model.facing.plan)."""
        (u_axis, _u_way), (v_axis, v_way) = facing.axes()
        box = _fused(self.faces).BoundBox
        low_high = ((box.XMin, box.XMax), (box.YMin, box.YMax))
        stock = ((self.bounds.x_min, self.bounds.x_max), (self.bounds.y_min, self.bounds.y_max))
        # the material the tool cuts: its edge around the area, in the stock
        low = max(low_high[v_axis][0] - self.radius, stock[v_axis][0])
        high = min(low_high[v_axis][1] + self.radius, stock[v_axis][1])
        u_low, u_high = low_high[u_axis][0] - 1.0, low_high[u_axis][1] + 1.0
        # the last pass goes the overrun past the far end when it is the stock's (an open side)
        far = high if v_way > 0 else low
        overrun = facing.overrun_mm if far in stock[v_axis] else 0.0
        result = []
        for v in model_facing.rows_at(low, high, diameter_mm, step_mm, v_way > 0, overrun):
            a, b = (FreeCAD.Vector(u_low, v, 0), FreeCAD.Vector(u_high, v, 0))
            if u_axis == 1:
                a, b = FreeCAD.Vector(v, u_low, 0), FreeCAD.Vector(v, u_high, 0)
            line = Part.LineSegment(a, b).toShape()
            spans = []
            for face in self.faces:
                for edge in line.common(face).Edges:
                    ends = sorted(p.Point[u_axis] for p in edge.Vertexes)
                    if ends[-1] - ends[0] > 1e-6:
                        spans.append((ends[0], ends[-1]))
            spans.sort()
            merged = []
            for span in spans:  # pieces of one face split by OCCT meet again
                if merged and span[0] <= merged[-1][1] + 1e-6:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], span[1]))
                else:
                    merged.append(span)
            if merged:
                result.append((v, tuple(merged)))
        return sorted(result, key=lambda row: row[0] * v_way)


def _middle(edge):
    return (edge.FirstParameter + edge.LastParameter) / 2.0


def _chain_moves(edges):
    """(start, moves) along connected edges (Part.sortEdges), each edge the
    way the chain goes: lines, arcs, other curves as short lines."""
    if len(edges) > 1:
        first, second = edges[0], edges[1]
        ends = [v.Point for v in second.Vertexes]
        a, b = first.Vertexes[0].Point, first.Vertexes[-1].Point
        start = b if min((a - e).Length for e in ends) < min((b - e).Length for e in ends) else a
    else:
        start = edges[0].Vertexes[0].Point
    here = start
    moves = []
    for edge in edges:
        forward = (edge.Vertexes[0].Point - here).Length <= (edge.Vertexes[-1].Point - here).Length
        p0, p1 = edge.FirstParameter, edge.LastParameter
        if not forward:
            p0, p1 = p1, p0
        if isinstance(edge.Curve, (Part.Line, Part.LineSegment)):
            here = edge.valueAt(p1)
            moves.append(("line", (here.x, here.y)))
        elif isinstance(edge.Curve, Part.Circle):
            centre = (edge.Curve.Center.x, edge.Curve.Center.y)
            halves = 2 if edge.isClosed() else 1
            for k in range(halves):
                a = p0 + (p1 - p0) * k / halves
                b = p0 + (p1 - p0) * (k + 1) / halves
                begin, mid, end = edge.valueAt(a), edge.valueAt((a + b) / 2.0), edge.valueAt(b)
                clockwise = model_facing._clockwise((begin.x, begin.y), (mid.x, mid.y), centre)
                moves.append(("arc", (end.x, end.y), centre, clockwise))
            here = edge.valueAt(p1)
        else:
            points = edge.discretize(Deflection=0.005)
            if not forward:
                points.reverse()
            moves.extend(("line", (p.x, p.y)) for p in points[1:])
            here = points[-1]
    return (start.x, start.y), tuple(moves)


def plan_for(job, facing, base, diameter_mm, levels=1):
    """(model.facing.Plan, number of pass lines, number of runs along the
    walls) of a facing of the picked face (base) with a tool of that
    diameter, on that many levels."""
    area = Area(job, base, facing, diameter_mm)
    rows = area.rows(facing, facing.step_mm(diameter_mm), diameter_mm)
    if len(rows) * levels > model_operations.MAX_CUTS:
        raise cam.ProjectError("{} passes are too many (at most {}); take a larger step over or Z step.".format(len(rows) * levels, model_operations.MAX_CUTS))  # fmt: skip
    the_plan = model_facing.plan(rows, facing, area.fits, area.outside)
    walls = area.walls()
    return model_facing.with_walls(the_plan, walls, area.fits, area.outside, diameter_mm / 2.0), len(rows), len(walls)


def facing_plan(job, facing, tc, base):
    """(model.facing.Plan, levels, Z of the face, tool) of a facing in the setup."""
    levels, face_z, tool = check(job, facing, tc, base)
    the_plan, _rows, _walls = plan_for(job, facing, base, tool.diameter_mm, len(levels))
    return the_plan, levels, face_z, tool


def facing_moves(op):
    """The tool moves (nc.Move) of a facing in the setup's coordinates, where the tool centre goes."""
    job = cam.setup_of(op)
    _model, facing = facing_of(op)
    the_plan, levels, _face_z, tool = facing_plan(job, facing, op.ToolController, op.Base)
    try:
        return model_facing.moves(
            the_plan,
            levels,
            facing.top_mm(cam.stock_bounds(job).z_max),
            cam._value(op.SafeHeight, "mm"),
            tool.feed_z_mm_min,
            tool.feed_xy_mm_min,
            cam._value(op.ClearanceHeight, "mm"),
        )
    except ValueError as exc:
        raise cam.ProjectError(str(exc)) from exc


def _attach_view(op):
    import Path.Op.Gui.Base as PathOpGui
    import Path.Op.Gui.MillFace as PathMillFaceGui

    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, PathMillFaceGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False


def add_facing(job, facing, tc, model, faces):
    """Facing (model Facing) of flat faces picked in a model ("Face12", all
    at one height) in the setup: from Start Z (the top of the stock) down
    to the face."""
    base, _z = picked_face(job, model, faces)
    facing_plan(job, facing, tc, base)  # the tool fits the face
    doc = job.Document
    op = doc.addObject("Path::FeaturePython", "Facing")
    op.Proxy = Facing(op, "Facing", job, tc)
    if FreeCAD.GuiUp:
        _attach_view(op)
    op.Label = cam._next_label(doc, "Facing")
    op.Base = base
    op.ToolController = tc
    for name in ("StartDepth", "FinalDepth", "StepDown"):
        op.setExpression(name, None)  # depths come from the stock and the user's values
    cam._user_values(op, model, facing, "Model of the face", cam._MODEL_PROPERTY)
    sync(job, op)
    doc.recompute()
    return op


def set_facing(op, facing):
    """Change the user's values of a facing."""
    job = cam.setup_of(op)
    facing_plan(job, facing, op.ToolController, op.Base)
    setattr(op, cam._OPERATION_PROPERTY, model_operations.to_json(facing))
    sync(job, op)
    op.Document.recompute()


def facing_faces(op):
    """Names of the faces of a facing ("Face12")."""
    return [name for _obj, names in getattr(op, "Base", []) for name in names]


def sync(job, op):
    """FreeCAD's own values of a facing from the user's, the stock and the
    setup, so expert mode shows them; heights as the shop's programs have them."""
    _model, facing = facing_of(op)
    stock_top = cam.stock_bounds(job).z_max if job.Stock is not None else 0.0
    top = facing.top_mm(stock_top)
    face_z = _face_z(op)
    op.StartDepth = cam._quantity(top, "mm")
    op.FinalDepth = cam._quantity(face_z, "mm")
    op.StepDown = cam._quantity(facing.z_step_mm or max(top - face_z, 0.0), "mm")
    cam._set_heights(job, op, top)
    op.BoundaryShape = "Stock"
    op.ClearingPattern = "ZigZag" if facing.pattern == model_facing.ZIGZAG else "Line"
    op.ZigZagAngle = 0.0 if facing.axes()[0][0] == 0 else 90.0
    op.StepOver = int(round(facing.step_over_percent))
    op.ExcludeRaisedAreas = True
    op.CutMode = "Climb"
