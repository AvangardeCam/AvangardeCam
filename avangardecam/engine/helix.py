# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Helix milling (model.helix) on FreeCAD: the holes, the operation and
its path.

The holes are picked as for the drilling and the thread milling: circles
of a sketch or holes of a model, in the order clicked, on the same helper
objects (freecad_cam._circles_helper, _model_holes_helper: their circles
in the setup's coordinates, following the zero point), each milled from
its own top.

The operation is FreeCAD's Helix (ObjectHelix) with this proxy, so expert
mode shows a helix with the user's values; its path is where the tool
centre goes (helix_moves(..., program=False)), for the simulation. The NC
program has the passes with the radius compensation (program_moves), as
the thread and slot milling. The 3D view draws the program
(path_drawing): the circles where the tool's edge cuts.
"""

import math

import FreeCAD
import Path
import Path.Op.Helix as PathHelix

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.model import helix as model_helix
from avangardecam.model import nc
from avangardecam.model import operations as model_operations

# tools that cut a hole's floor with their end and go down on a helix
HELIX_SHAPES = ("Endmill", "Bullnose", "Ballend")

_G = {nc.RAPID: "G0", nc.LINE: "G1"}


class HelixMilling(PathHelix.ObjectHelix):
    def __init__(self, obj, name, parentJob, tc=None):
        # FreeCAD takes the tool of the operation before it in the setup, else
        # the only one it supports; with more it asks: tc is the only one
        self._tool = tc
        try:
            super().__init__(obj, name, parentJob)
        finally:
            self._tool = None

    def isToolSupported(self, obj, tool):
        if getattr(self, "_tool", None) is not None:
            return tool is self._tool.Tool
        return super().isToolSupported(obj, tool)

    def circularHoleExecute(self, obj, holes):
        if helix_milling_of(obj) is None:  # not one of AvangardeCam's
            return super().circularHoleExecute(obj, holes)
        try:
            moves = helix_moves(obj, program=False)
        except cam.ProjectError as exc:  # e.g. another tool chosen in expert mode
            Path.Log.error("{}: {}".format(obj.Label, exc))
            return
        if len(moves) > 1 and moves[-1].kind == nc.RAPID and (moves[-1].x, moves[-1].y) == (moves[-2].x, moves[-2].y):
            moves = moves[:-1]  # up at the end: FreeCAD adds the clearance height, the program its retract
        self.commandlist.append(Path.Command("(Begin Helix Milling)"))
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


def helix_milling_of(op):
    """(sketch or model, model HelixMilling) of a helix milling made by AvangardeCam, else None."""
    return cam._operation_of(op, model_helix.HelixMilling)


# -- the holes -------------------------------------------------------------------


def bottom_of(milling, target):
    """Z-Depth in a hole (freecad_cam.DrillTarget): from the model (the end of
    the hole, or through_mm under a through hole), else the user's depth
    below its top. ProjectError for a sketch's circle without a depth."""
    if milling.depth_mm is not None:
        return _round(target.top + milling.depth_mm)
    if target.hole is None:
        raise cam.ProjectError("The circles of a sketch have no depth of their own; enter the depth.")
    return _round(target.top + target.hole.depth_mm - (milling.through_mm if target.hole.through else 0.0))


def _round(value):
    return round(value, 6) + 0.0


def helix_holes(milling, targets):
    """The holes (model.helix.HelixHole) of the targets (DrillTarget) in their order."""
    return [model_helix.HelixHole(t.x, t.y, t.top, bottom_of(milling, t), t.diameter) for t in targets]


def hole_cuts(milling, tool, targets):
    """[model.helix.HelixHole] of the holes (DrillTarget) milled with a tool
    (model Tool); ProjectError when it cannot mill them."""
    if tool.shape not in HELIX_SHAPES:
        raise cam.ProjectError("{} is not an end mill; helix milling needs one.".format(tool.name))
    if not targets:
        raise cam.ProjectError("Click the holes to mill in the model or the circles of a sketch.")
    found = helix_holes(milling, targets)
    for target, hole in zip(targets, found):
        where = "The hole at X{:+.3f} Y{:+.3f}".format(hole.x, hole.y)
        if target.hole is not None and not target.hole.through and hole.bottom < hole.top + target.hole.depth_mm - 1e-6:
            raise cam.ProjectError(
                "{} is {:g} mm deep; {:g} mm goes through its floor.".format(
                    where, round(-target.hole.depth_mm, 3), round(hole.top - hole.bottom, 3)
                )
            )
        try:
            milling.check(tool.diameter_mm, hole.diameter_mm, hole.top - hole.bottom, tool.cutting_length_mm)
        except ValueError as exc:
            raise cam.ProjectError("{}: {}.".format(where, exc)) from exc
    return found


def check(job, milling, tc, targets):
    """([model.helix.HelixHole], tool) of a helix milling of the holes
    (DrillTarget); ProjectError when the tool cannot mill them."""
    try:
        milling.validate()
    except ValueError as exc:
        raise cam.ProjectError(str(exc)) from exc
    cam._check_tool(job, tc)
    if getattr(tc, "Tool", None) is None:
        raise cam.ProjectError("{} has no tool.".format(tc.Label))
    tool = cam._tool_from_controller(tc)
    return hole_cuts(milling, tool, targets), tool


def _sketch_targets(job, sketch, names):
    """DrillTargets of a sketch's circles before there is an operation."""
    place = cam.zero(job).inverse().multiply(sketch.Placement)
    targets = []
    for edge in geometry.hole_circles(sketch, names):
        centre = place.multVec(edge.Curve.Center)
        targets.append(cam.DrillTarget(centre.x, centre.y, centre.z, edge.Curve.Radius * 2.0, None))
    return targets


def _model_targets(job, picked):
    """DrillTargets of a model's holes (geometry.ModelHole) before there is an operation."""
    place = cam.zero(job).inverse()
    targets = []
    for hole in picked:
        top = place.multVec(hole.top)
        targets.append(cam.DrillTarget(top.x, top.y, top.z, hole.radius * 2.0, hole.depth))
    return targets


def sketch_holes(job, sketch, circles=()):
    """(names, DrillTargets) of a sketch's circles to mill (all of them in
    FreeCAD's order without circles)."""
    names = cam._sketch_circles(job, sketch, circles, "mill")
    return names, _sketch_targets(job, sketch, names)


def model_holes(job, model, holes):
    """(geometry.ModelHole, DrillTargets) of the holes picked in a model, each once in the order picked."""
    names = list(dict.fromkeys(holes))
    if not names:
        raise cam.ProjectError("Click the holes to mill in the model.")
    picked = cam.model_holes(job, model, names)
    return picked, _model_targets(job, picked)


# -- the operation -----------------------------------------------------------------


def _attach_view(op):
    import Path.Op.Gui.Base as PathOpGui
    import Path.Op.Gui.Helix as PathHelixGui

    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, PathHelixGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False


def add_helix_milling(job, sketch, milling, tc, circles=()):
    """Helix milling (model HelixMilling) of circles of a sketch, from the
    sketch plane down; circles as for freecad_cam.add_drilling (None: all
    of them). The circles have no depth of their own: the user's."""
    if milling.depth_mm is None:
        raise cam.ProjectError("The circles of a sketch have no depth of their own; enter the depth.")
    names, targets = sketch_holes(job, sketch, circles)
    check(job, milling, tc, targets)
    label = cam._next_label(job.Document, "Helix milling")
    helper = cam._circles_helper(job, sketch, names, label)
    return _helix_op(job, helper, len(names), label, milling, tc, sketch, cam._SKETCH_PROPERTY, "Sketch with the circles of the holes")  # fmt: skip


def add_model_helix_milling(job, model, milling, tc, holes):
    """Helix milling of holes picked in a model (as freecad_cam.add_model_drilling),
    each from its own top; without the user's depth as deep as the model has it."""
    picked, targets = model_holes(job, model, holes)
    check(job, milling, tc, targets)
    label = cam._next_label(job.Document, "Helix milling")
    helper = cam._model_holes_helper(job, model, picked, label)
    return _helix_op(job, helper, len(picked), label, milling, tc, model, cam._MODEL_PROPERTY, "Model with the holes")  # fmt: skip


def _helix_op(job, helper, count, label, milling, tc, source, link, tip):
    doc = job.Document
    op = doc.addObject("Path::FeaturePython", "HelixMilling")
    op.Proxy = HelixMilling(op, "HelixMilling", job, tc)
    if FreeCAD.GuiUp:
        _attach_view(op)
    op.Label = label
    op.Base = [(helper, tuple("Edge{}".format(i) for i in range(1, count + 1)))]
    op.ToolController = tc
    for name in ("StartDepth", "FinalDepth", "StepDown"):
        op.setExpression(name, None)  # depths come from the holes and the user's values
    cam._user_values(op, source, milling, tip, link)
    sync(job, op)
    doc.recompute()
    return op


def set_helix_milling(op, milling):
    """Change the user's values of a helix milling."""
    source, _old = helix_milling_of(op)
    if milling.depth_mm is None and geometry.is_sketch(source):
        raise cam.ProjectError("The circles of a sketch have no depth of their own; enter the depth.")
    check(cam.setup_of(op), milling, op.ToolController, cam.drill_targets(op))
    setattr(op, cam._OPERATION_PROPERTY, model_operations.to_json(milling))
    sync(cam.setup_of(op), op)
    op.Document.recompute()


def holes(op):
    """The holes of a helix milling (model.helix.HelixHole), in the order the tool mills them."""
    _source, milling = helix_milling_of(op)
    return helix_holes(milling, cam.drill_targets(op))


def sync(job, op):
    """Holes and heights of a helix milling from its sketch or model and the
    setup's zero point; FreeCAD's own helix values from the user's, so
    expert mode shows them; heights as the shop's programs have them."""
    source, milling = helix_milling_of(op)
    place = cam._place_holes(job, op, source)
    try:
        found = holes(op)
    except cam.ProjectError:
        found = []  # the model changed, or no depth yet: recomputing says what is wrong
    top = max((h.top for h in found), default=place.Base.z)
    bottom = min((h.bottom for h in found), default=top - 1.0)
    op.StartDepth = cam._quantity(top, "mm")
    op.FinalDepth = cam._quantity(bottom, "mm")
    heights = (
        ("SafeHeight", top + model_helix.BETWEEN_MM),
        ("ClearanceHeight", max(model_operations.APPROACH_Z_MM, top + model_operations.SAFETY_MM)),
    )
    for name, value in heights:
        op.setExpression(name, None)
        setattr(op, name, cam._quantity(value, "mm"))
    diameter = 2.0 * cam._tool_radius(op.ToolController)
    if diameter:
        op.StepDown = cam._quantity(milling.pitch(diameter), "mm")
    op.StepOver = int(round(milling.step_over_percent))
    op.StartRadius = cam._quantity(milling.predrilled_mm / 2.0, "mm")
    op.OffsetExtra = cam._quantity(-milling.offset_xy_mm, "mm")  # FreeCAD stays this far inside the hole
    op.StartSide = "Inside"
    op.CutMode = "Climb" if milling.compensation == nc.LEFT else "Conventional"


def helix_moves(op, program=True):
    """The tool moves (nc.Move) of a helix milling in the setup's
    coordinates: the circles with the radius compensation where the tool's
    edge cuts (program), else where the tool centre goes (FreeCAD's path)."""
    job = cam.setup_of(op)
    _source, milling = helix_milling_of(op)
    found, tool = check(job, milling, op.ToolController, cam.drill_targets(op))
    return model_helix.moves(
        milling,
        found,
        tool.diameter_mm,
        tool.feed_z_mm_min,
        tool.feed_xy_mm_min,
        cam._value(op.ClearanceHeight, "mm"),
        program,
    )


def program_moves(op):
    """The moves of a helix milling for the NC program."""
    return helix_moves(op, program=True)


# -- drawing -------------------------------------------------------------------------


def _arc_points(start, move):
    """Points of an arc move (nc.ARC) from start, no further than
    freecad_cam._DRAW_DEFLECTION_MM from it; down evenly on a helix."""
    cx, cy = move.center
    radius = math.hypot(start.x - cx, start.y - cy)
    first = math.atan2(start.y - cy, start.x - cx)
    sweep = math.atan2(move.y - cy, move.x - cx) - first
    if move.clockwise:
        while sweep >= 0.0:
            sweep -= 2.0 * math.pi
    else:
        while sweep <= 0.0:
            sweep += 2.0 * math.pi
    step = 2.0 * math.acos(1.0 - cam._DRAW_DEFLECTION_MM / radius) if radius > cam._DRAW_DEFLECTION_MM else math.pi
    count = max(2, int(math.ceil(abs(sweep) / step)))
    down = move.z - start.z
    return [
        FreeCAD.Vector(cx + radius * math.cos(first + sweep * k / count), cy + radius * math.sin(first + sweep * k / count), start.z + down * k / count)  # fmt: skip
        for k in range(1, count)
    ] + [FreeCAD.Vector(move.x, move.y, move.z)]


def path_drawing(op):
    """How the 3D view draws a helix milling (freecad_cam.path_drawing): the
    program's moves, the circles and helices on the wall, where the edge
    cuts with the radius compensation; None while it has no path."""
    if op.Path is None or not op.Path.Commands:
        return None
    pieces = []
    position = None
    for move in program_moves(op):
        end = FreeCAD.Vector(move.x, move.y, move.z)
        if position is not None and not position.isEqual(end, 1e-9):
            kind = cam.DRAW_RAPID if move.kind == nc.RAPID else cam.DRAW_FEED
            points = _arc_points(position, move) if move.kind == nc.ARC else [end]
            if pieces and pieces[-1][0] == kind == cam.DRAW_FEED:
                pieces[-1][1].extend(points)  # one line along the cut
            else:
                pieces.append((kind, [position] + points))
        position = end
    return pieces
