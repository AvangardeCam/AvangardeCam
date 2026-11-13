# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Slot milling (model.slot) on FreeCAD: slots picked in the model, the
operation and its path.

A slot is picked by any of its faces (a wall, a round end, the floor) or
edges, in the Job's clone of the model, so it is read in the setup's
coordinates and follows the zero point. A slot is two round ends of one
radius, standing along the tool axis, joined by two straight walls: the
round ends are found from the picked element (directly, through the
walls next to it, or the floor's round edges), and the shape is checked
by probing the material (the walls and beyond the ends material, the
slot and above it none), as the drilling probes a hole. It goes through
when nothing is right under it; else its floor ends it.

The operation is FreeCAD's Slot (ObjectSlot) with this proxy, so expert
mode shows a slot; its Base is the picked elements of the clone. Its path
is where the tool centre goes; the NC program gets the finishing pass
with the radius compensation instead (program_moves), as the thread
milling. The 3D view draws the program (path_drawing): the ramps and
rough passes the tool centre, the finishing pass the walls, as a contour
with compensation.
"""

import math
from typing import NamedTuple

import FreeCAD
import Part
import Path
import Path.Op.Slot as PathSlot

from avangardecam.engine import freecad_cam as cam
from avangardecam.model import nc
from avangardecam.model import operations as model_operations
from avangardecam.model import slot as model_slot

_SAME_MM = 1e-4  # radii and centres of a slot's round ends are matched to this
_PROBE_MM = 0.01  # the material is probed this far beside the walls
_END_PROBE_MM = 1e-3  # under the floor

# tools that cut a floor with their end and go down on a ramp
SLOT_SHAPES = ("Endmill", "Bullnose", "Ballend")

_G = {nc.RAPID: "G0", nc.LINE: "G1"}


class SlotMilling(PathSlot.ObjectSlot):
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
        if slot_milling_of(obj) is None:  # not one of AvangardeCam's
            return super().opExecute(obj)
        try:
            moves = slot_moves(obj, program=False)
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


def slot_milling_of(op):
    """(model, model SlotMilling) of a slot milling made by AvangardeCam, else None."""
    return cam._operation_of(op, model_slot.SlotMilling)


# -- slots of a model ------------------------------------------------------------


class ModelSlot(NamedTuple):
    """A slot of a model, in the setup's coordinates."""

    name: str  # the element the user picked ("Face12", "Edge7")
    slot: model_slot.Slot
    top: float  # Z of the top of its walls
    bottom: float  # Z of the bottom of its walls: the floor, or the underside of the part
    through: bool

    def depth_mm(self):
        return self.top - self.bottom


def _vertical_cylinder(face):
    surface = getattr(face, "Surface", None)
    return isinstance(surface, Part.Cylinder) and abs(abs(surface.Axis.z) - 1.0) < 1e-9


def _vertical_plane(face):
    plane = face.findPlane() if face.ShapeType == "Face" else None
    return plane is not None and abs(plane.Axis.z) < 1e-9


def _faces_beside(shape, face):
    """Faces of the shape that share an edge with face."""
    found = []
    for edge in face.Edges:
        for f in shape.ancestorsOfType(edge, Part.Face):
            if not f.isSame(face) and not any(f.isSame(g) for g in found):
                found.append(f)
    return found


def _round_faces(shape, element):
    """Round walls standing along the tool axis that belong to the slot of a
    picked element: the element itself, those beside a straight wall or a
    floor, those on a round edge."""
    if element.ShapeType == "Face":
        if _vertical_cylinder(element):
            return [element]
        return [f for f in _faces_beside(shape, element) if _vertical_cylinder(f)]
    if element.ShapeType == "Edge":
        faces = shape.ancestorsOfType(element, Part.Face)
        found = [f for f in faces if _vertical_cylinder(f)]
        for face in faces:
            if not found and face.findPlane() is not None:
                found = [f for f in _faces_beside(shape, face) if _vertical_cylinder(f)]
        return found
    return []


def _key(face):
    s = face.Surface
    return (s.Center.x, s.Center.y, s.Radius)


def _same_end(a, b):
    return abs(a[0] - b[0]) < _SAME_MM and abs(a[1] - b[1]) < _SAME_MM and abs(a[2] - b[2]) < _SAME_MM


def _ends(shape, faces):
    """(x, y, radius) of each round end the faces belong to, each once; when
    only one, the other end through the straight walls beside it."""
    ends = []
    for face in faces:
        if not any(_same_end(_key(face), e) for e in ends):
            ends.append(_key(face))
    if len(ends) == 1:
        for face in faces:
            for wall in _faces_beside(shape, face):
                if not _vertical_plane(wall):
                    continue
                for other in _faces_beside(shape, wall):
                    key = _key(other) if _vertical_cylinder(other) else None
                    if key and abs(key[2] - ends[0][2]) < _SAME_MM and not any(_same_end(key, e) for e in ends):
                        ends.append(key)
    return ends


def _span(shape, end):
    """(lowest, highest) Z of the round walls of an end (STEP may split them)."""
    faces = [f for f in shape.Faces if _vertical_cylinder(f) and _same_end(_key(f), end)]
    return min(f.BoundBox.ZMin for f in faces), max(f.BoundBox.ZMax for f in faces)


def _sweep(shape, end):
    """The angle the round walls of an end go round, radians (a round hole: 2π)."""
    faces = [f for f in shape.Faces if _vertical_cylinder(f) and _same_end(_key(f), end)]
    levels = {}
    for f in faces:  # STEP may split them in height too: the widest level
        key = (round(f.BoundBox.ZMin, 4), round(f.BoundBox.ZMax, 4))
        u0, u1, _v0, _v1 = f.ParameterRange
        levels[key] = levels.get(key, 0.0) + (u1 - u0)
    return max(levels.values(), default=0.0)


def _inside(solid, x, y, z):
    return solid.isInside(FreeCAD.Vector(x, y, z), 1e-7, False)


def slot_in_model(clone, name, label):
    """The slot of a model (its Job's clone, in the setup's coordinates) the
    user picked by an element (name). ProjectError when it is not a slot
    of two round ends along the tool axis, open towards the tool."""
    shape = clone.Shape
    try:
        element = shape.getElement(name)
    except Exception:
        element = None
    faces = _round_faces(shape, element) if element is not None else []
    ends = _ends(shape, faces)
    if len(ends) == 1 and _sweep(shape, ends[0]) > 2.0 * math.pi - 1e-6:
        raise cam.ProjectError(
            "{} of {} is a round hole, not a slot. Use Drilling or Thread milling for it.".format(name, label)
        )
    if len(ends) == 1:
        raise cam.ProjectError(
            "{} of {} is not a closed slot: it has one round end (a slot running out of the part?).".format(name, label)
        )
    if len(ends) != 2:
        raise cam.ProjectError(
            "{} of {} is not part of a slot with two round ends along the tool axis. Click a wall, "
            "a round end or the floor of a slot.".format(name, label)
        )
    (x1, y1, r1), (x2, y2, r2) = ends
    if abs(r1 - r2) > _SAME_MM:
        raise cam.ProjectError("The round ends of the slot of {} ({}) are not the same size.".format(label, name))
    # the end with the lower X first (then Y): the tool starts there
    if (round(x2, 4), round(y2, 4)) < (round(x1, 4), round(y1, 4)):
        (x1, y1), (x2, y2) = (x2, y2), (x1, y1)
    try:
        slot = model_slot.Slot((_round(x1), _round(y1)), (_round(x2), _round(y2)), _round(2.0 * r1))
        u, n = slot.axes()
    except ValueError as exc:
        raise cam.ProjectError("{} of {}: {}.".format(name, label, exc)) from exc
    low1, high1 = _span(shape, ends[0])
    low2, high2 = _span(shape, ends[1])
    if abs(low1 - low2) > 1e-3:
        raise cam.ProjectError(
            "The round ends of the slot of {} ({}) end at different depths (Z{:+.3f}, Z{:+.3f}).".format(label, name, low1, low2)  # fmt: skip
        )
    top, bottom = max(high1, high2), min(low1, low2)
    solid = next((s for s in shape.Solids if any(f.isSame(faces[0]) for f in s.Faces)), None)
    if solid is None:
        raise cam.ProjectError("{} is not a solid; its slots cannot be milled.".format(label))
    r = r1
    middle = slot.middle()
    z = (top + bottom) / 2.0
    centre_line = (slot.start, middle, slot.end)
    if any(_inside(solid, x, y, z) for x, y in centre_line):
        raise cam.ProjectError("{} of {} is not a slot (there is material inside it).".format(name, label))
    walls = [
        (middle[0] + n[0] * k * (r + _PROBE_MM), middle[1] + n[1] * k * (r + _PROBE_MM)) for k in (1, -1)
    ] + [
        (slot.start[0] - u[0] * (r + _PROBE_MM), slot.start[1] - u[1] * (r + _PROBE_MM)),
        (slot.end[0] + u[0] * (r + _PROBE_MM), slot.end[1] + u[1] * (r + _PROBE_MM)),
    ]
    if not all(_inside(solid, x, y, z) for x, y in walls):
        raise cam.ProjectError(
            "{} of {} is not a closed slot: its walls are open (a slot running out of the part?).".format(name, label)
        )
    if any(_inside(solid, x, y, top + _PROBE_MM) for x, y in centre_line):
        raise cam.ProjectError(
            "The slot of {} ({}) is closed at the top; the tool of this setup cannot reach it.".format(label, name)
        )
    under = list(centre_line) + [
        (middle[0] + n[0] * k * (r - 10.0 * _END_PROBE_MM), middle[1] + n[1] * k * (r - 10.0 * _END_PROBE_MM))
        for k in (1, -1)
    ]
    through = not any(_inside(solid, x, y, bottom - _END_PROBE_MM) for x, y in under)
    return ModelSlot(name, slot, _round(top), _round(bottom), through)


def _round(value):
    return round(value, 6) + 0.0


def model_slots(clone, names, label):
    """The slots of a model the user picked, each once, in the order they
    were picked (several elements of one slot: its first)."""
    found = []
    for name in names:
        slot = slot_in_model(clone, name, label)
        if not any(
            math.hypot(s.slot.start[0] - slot.slot.start[0], s.slot.start[1] - slot.slot.start[1]) < _SAME_MM
            and math.hypot(s.slot.end[0] - slot.slot.end[0], s.slot.end[1] - slot.slot.end[1]) < _SAME_MM
            and abs(s.top - slot.top) < _SAME_MM
            for s in found
        ):
            found.append(slot)
    return found


def picked_slots(job, model, elements):
    """(FreeCAD Base [(clone, names)], [ModelSlot]) for elements picked in a
    model ("Face12", "Edge3"), each element once, in the Job's clone."""
    names = list(dict.fromkeys(elements))
    if not names:
        raise cam.ProjectError("Click a wall, a round end or the floor of a slot in the model.")
    clone = cam._clone(job, model)
    return [(clone, tuple(names))], model_slots(clone, names, model.Label)


def _slots(base):
    return [s for clone, names in base for s in model_slots(clone, list(names), cam._original(clone).Label)]


def floor_of(milling, found):
    """Z of the floor the tool goes down to in a slot (ModelSlot): from the
    model (the floor, or through_mm under a through slot), else the user's
    depth below its top."""
    if milling.depth_mm is None:
        return _round(found.bottom - (milling.through_mm if found.through else 0.0))
    return _round(found.top + milling.depth_mm)


def check(job, milling, tc, base):
    """([model.slot.SlotCut], tool) of a slot milling; ProjectError when the
    tool cannot mill the slots."""
    try:
        milling.validate()
    except ValueError as exc:
        raise cam.ProjectError(str(exc)) from exc
    cam._check_tool(job, tc)
    if getattr(tc, "Tool", None) is None:
        raise cam.ProjectError("{} has no tool.".format(tc.Label))
    tool = cam._tool_from_controller(tc)
    return slot_cuts(milling, tool, _slots(base)), tool


def slot_cuts(milling, tool, found):
    """[model.slot.SlotCut] of the slots (ModelSlot) milled with a tool
    (model Tool); ProjectError when it cannot mill them."""
    if tool.shape not in SLOT_SHAPES:
        raise cam.ProjectError("{} is not an end mill; slot milling needs one.".format(tool.name))
    if not found:
        raise cam.ProjectError("Click a wall, a round end or the floor of a slot in the model.")
    cuts = []
    for s in found:
        floor = floor_of(milling, s)
        if not s.through and floor < s.bottom - 1e-6:
            raise cam.ProjectError(
                "The slot at X{:+.3f} Y{:+.3f} is {:g} mm deep; {:g} mm goes through its floor.".format(
                    s.slot.middle()[0], s.slot.middle()[1], round(s.depth_mm(), 3), round(s.top - floor, 3)
                )
            )
        try:
            milling.check(tool.diameter_mm, s.slot, s.top - floor)
        except ValueError as exc:
            raise cam.ProjectError("{}.".format(exc)) from exc
        levels = milling.levels(s.top, floor)
        if len(levels) > model_operations.MAX_CUTS:
            raise cam.ProjectError("{} Z levels are too many (at most {}); take a larger Z step.".format(len(levels), model_operations.MAX_CUTS))  # fmt: skip
        deepest = max(a - b for a, b in zip([s.top] + levels, levels))
        if tool.cutting_length_mm and deepest > tool.cutting_length_mm + 1e-6:
            raise cam.ProjectError(
                "A level cuts {:g} mm deep, more than the cutting length of {} ({:g} mm). Enter a Z step.".format(
                    round(deepest, 3), tool.name, tool.cutting_length_mm
                )
            )
        cuts.append(model_slot.SlotCut(s.slot, s.top, floor))
    return cuts


def slot_moves(op, program=True):
    """The tool moves (nc.Move) of a slot milling in the setup's
    coordinates: the finishing pass with the radius compensation along the
    walls (program), else where the tool centre goes (FreeCAD's path)."""
    job = cam.setup_of(op)
    _model, milling = slot_milling_of(op)
    cuts, tool = check(job, milling, op.ToolController, op.Base)
    try:
        return model_slot.moves(
            milling,
            cuts,
            tool.diameter_mm,
            tool.feed_z_mm_min,
            tool.feed_xy_mm_min,
            cam._value(op.SafeHeight, "mm"),
            cam._value(op.ClearanceHeight, "mm"),
            program,
        )
    except ValueError as exc:
        raise cam.ProjectError(str(exc)) from exc


def program_moves(op):
    """The moves of a slot milling for the NC program."""
    return slot_moves(op, program=True)


def _arc_points(start, move):
    """Points of an arc move (nc.ARC) from start, no further than
    cam._DRAW_DEFLECTION_MM from it; down evenly on a helix."""
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
    down = move.z - start.z  # a helix on a ramp along the contour
    return [
        FreeCAD.Vector(cx + radius * math.cos(first + sweep * k / count), cy + radius * math.sin(first + sweep * k / count), start.z + down * k / count)  # fmt: skip
        for k in range(1, count)
    ] + [FreeCAD.Vector(move.x, move.y, move.z)]


def path_drawing(op):
    """How the 3D view draws a slot milling (cam.path_drawing): the
    program's moves, the ramps and rough passes where the tool centre goes,
    the finishing pass along the walls, where the edge cuts with the radius
    compensation; None while it has no path."""
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


def _attach_view(op):
    import Path.Op.Gui.Base as PathOpGui
    import Path.Op.Gui.Slot as PathSlotGui

    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, PathSlotGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False


def add_slot_milling(job, milling, tc, model, elements):
    """Slot milling (model SlotMilling) of the slots picked in a model by
    their elements ("Face12", "Edge3"), in the order picked."""
    base, _found = picked_slots(job, model, elements)
    check(job, milling, tc, base)
    doc = job.Document
    op = doc.addObject("Path::FeaturePython", "SlotMilling")
    op.Proxy = SlotMilling(op, "SlotMilling", job, tc)
    if FreeCAD.GuiUp:
        _attach_view(op)
    op.Label = cam._next_label(doc, "Slot milling")
    op.Base = base
    op.ToolController = tc
    for name in ("StartDepth", "FinalDepth", "StepDown"):
        op.setExpression(name, None)  # depths come from the slots and the user's values
    cam._user_values(op, model, milling, "Model with the slots", cam._MODEL_PROPERTY)
    sync(job, op)
    doc.recompute()
    return op


def set_slot_milling(op, milling):
    """Change the user's values of a slot milling."""
    job = cam.setup_of(op)
    check(job, milling, op.ToolController, op.Base)
    setattr(op, cam._OPERATION_PROPERTY, model_operations.to_json(milling))
    sync(job, op)
    op.Document.recompute()


def slot_elements(op):
    """Names of the elements the slots of a slot milling were picked by ("Face12")."""
    return [name for _obj, names in getattr(op, "Base", []) for name in names]


def slots(op):
    """The slots of a slot milling (ModelSlot), in the order the tool mills them."""
    return _slots(op.Base)


def sync(job, op):
    """FreeCAD's own values of a slot milling from the user's and the
    slots, so expert mode shows them; heights as the shop's programs have them."""
    _model, milling = slot_milling_of(op)
    try:
        found = _slots(op.Base)
    except cam.ProjectError:
        found = []
    top = max((s.top for s in found), default=0.0)
    floor = min((floor_of(milling, s) for s in found), default=top)
    op.StartDepth = cam._quantity(top, "mm")
    op.FinalDepth = cam._quantity(floor, "mm")
    op.StepDown = cam._quantity(milling.z_step_mm or max(top - floor, 0.0), "mm")
    cam._set_heights(job, op, top)
