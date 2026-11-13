# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""FreeCAD's Adaptive operation, clearing on AvangardeCam's Z levels with
the shop's moves.

FreeCAD's Adaptive with its model awareness (ModelAwareExperiment) cuts
on its Z steps only: a flat floor between two steps keeps up to a step of
material. Worse, it slices the model exactly at each step, so a floor
lying on a step counts as material above the tool and is not cut at all
(on the user's test part the top of the plate kept 0.5 mm). AvangardeCam
puts a level on every floor (model.operations.Adaptive.levels) and slices
the model EPSILON_MM above each level.

The areas of each level come from FreeCAD's own helpers (the stock's
outline less the model's above the level), or for picked floors their
outline grown by the tool's radius less the model above (_picked_regions), and
FreeCAD's Adaptive2d (libarea) clears each one; an area the same on
several levels is worked out once. The moves between
are model.clearing's. This proxy is FreeCAD's own Adaptive (properties,
task panel in expert mode); its path is where the tool centre goes, and
the NC program reads it (freecad_cam.nc_moves).

In a setup starting from the stock another setup left (CAM > Next setup,
engine.next_setup.material) libarea clears on each level what there is
of that stock from the level up to the level over it (_stocks): no paths
where the setup before took the material away.
"""

import contextlib
import math
from typing import NamedTuple

import DraftGeomUtils
import Part
import Path
import Path.Op.Adaptive as PathAdaptive

from avangardecam.model import clearing
from avangardecam.model import nc
from avangardecam.model import start_stock

EPSILON_MM = 1e-3  # the model is sliced this much above a level
FLOOR_REACH = 1.5  # tool diameters (and Finish XY) around a floor cleared on its own level
OUTSIDE_GAP_MM = 1.0  # the tool going down beside the stock keeps this off it (_in_from_outside)
SLIVER_MM2 = 1.0  # a face seen from the tool smaller than this counts as its bounding rectangle
# material of a stock left (_stocks) less than this under the level cleared
# before is the floor cut there (the stock left keeps it a few µm lower:
# 1.4 µm in test_start_stock), not material for the next level
FLOOR_MM = 0.01
# a cut of libarea starting further than this from where the tool is (or
# twice libarea's tolerance) is gone to over the safe height (_joined)
JUMP_MM = 1.0
# the helices libarea comes into a closed area on, tried in turn (_clear_area),
# as parts of the tool's diameter (0: libarea's own, as wide as the tool):
# libarea leaves the area out without a word when its helix does not fit (a
# pocket 10 mm wide for a Ø6 tool). In the user's counterbores Ø8 (Ø6 tool,
# Finish XY 0.2) a helix Ø1.5 had 0.05 mm to spare and went in or not by
# where the points of libarea's polygons fell (the plate turned 90°: all
# five cleared, else none); ⅛ has 0.43 mm. The helix keeps inside Finish XY
# whichever it is (libarea takes the allowance off the area first).
HELICES = (0.0, 0.5, 0.25, 0.125)

_G = {nc.RAPID: "G0", nc.LINE: "G1"}


class Adaptive(PathAdaptive.PathAdaptive):
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

    def opExecute(self, obj):
        from avangardecam.engine import freecad_cam

        if freecad_cam.adaptive_of(obj) is None:  # not one of AvangardeCam's
            return super().opExecute(obj)
        try:
            moves = freecad_cam.adaptive_moves(obj, self)
        except freecad_cam.ProjectError as exc:  # e.g. another tool chosen in expert mode
            Path.Log.error("{}: {}".format(obj.Label, exc))
            return
        last, before = moves[-1] if moves else None, moves[-2] if len(moves) > 1 else None
        if before is not None and last.kind == nc.RAPID and (last.x, last.y) == (before.x, before.y):
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


def floor_faces(shapes):
    """The flat faces of shapes (setup coordinates) facing the tool: the
    floors the clearing puts a level on."""
    from avangardecam.engine import geometry

    result = []
    for shape in shapes:
        for face in shape.Faces:
            if face.findPlane() is not None and face.BoundBox.ZLength <= 1e-6:
                if geometry.outward_normal(shape, face).z >= 1.0 - 1e-9:
                    result.append(face)
    return result


def _flat(face):
    """A level face moved down to Z0."""
    import FreeCAD

    moved = face.copy()
    moved.translate(FreeCAD.Vector(0, 0, -face.BoundBox.ZMin))
    return moved


def under(faces, areas):
    """The level faces under one of areas (level faces at any height): seen
    from the tool, their outlines overlap."""
    flats = [_flat(a) for a in areas]
    return [f for f in faces if any(_flat(f).common(a).Area > 1e-6 for a in flats)]


def solid_projection(shape, z):
    """What the tool sees of shape above z, flat on Z0: FreeCAD's
    _getSolidProjection made safe.

    FreeCAD projects each face and fuses them all at once; on the user's
    plate (test plate A, side holes with drill points) a slice through a
    point left a cone 0.04 mm² big, and the fusion with it gave 11 mm²
    instead of the whole plate (24775 mm²): the clearing on that level went
    through the model. Here a face seen that small counts as its bounding
    rectangle (a little more model, never less), and a projection smaller
    than its largest face is refused (ProjectError) rather than cut."""
    import FreeCAD

    bb = shape.BoundBox
    box = Part.makeBox(bb.XLength, bb.YLength, max(bb.ZLength, bb.ZLength - z), FreeCAD.Vector(bb.XMin, bb.YMin, z))
    seen = []
    for solid in shape.common(box).Solids:
        for face in solid.Faces:
            flat = PathAdaptive.projectFacesToXY([face])
            if flat.isNull() or not flat.Faces:
                continue  # a wall
            if flat.Area < SLIVER_MM2:
                fb = face.BoundBox
                if fb.XLength < 1e-6 or fb.YLength < 1e-6:
                    continue
                flat = Part.makePlane(fb.XLength, fb.YLength, FreeCAD.Vector(fb.XMin, fb.YMin, 0))
            seen.append(flat)
    if not seen:
        return Part.Shape()
    fused = seen[0].fuse(seen[1:]) if len(seen) > 1 else seen[0]
    result = DraftGeomUtils.concatenate(fused.removeSplitter())
    if result.isNull() or not result.isValid() or result.Area < max(f.Area for f in seen) - 1e-6:
        from avangardecam.engine import freecad_cam

        raise freecad_cam.ProjectError(
            "The model seen from the tool above Z{:+.3f} mm could not be worked out; "
            "take another Z-Depth, Z step or Finish Z.".format(z)
        )
    return result


@contextlib.contextmanager
def _safe_projections():
    """FreeCAD's helpers (its roughing areas) with solid_projection."""
    original = PathAdaptive._getSolidProjection
    PathAdaptive._getSolidProjection = solid_projection
    try:
        yield
    finally:
        PathAdaptive._getSolidProjection = original


def _discretized(shape):
    return [[PathAdaptive.discretize(w)] for w in shape.Wires]


def _models(proxy):
    shapes = [obj.Shape for obj in proxy.model]
    return shapes[0].fuse(shapes[1:]) if len(shapes) > 1 else shapes[0]


def _add_region(regions, region, depth, area):
    """FreeCAD's region list: the depth goes to the region clearing the same
    area, else a new region."""
    for r in regions:
        if not r["area"].cut(area).Wires and not area.cut(r["area"]).Wires:
            r["depths"].append(depth)
            return
    regions.append({"region": region, "area": area, "depths": [depth]})


def _outline(faces, reach_mm):
    """The outlines of level faces (at any height) seen from the tool, flat
    on Z0, holes in them left out (they go down), grown by reach_mm."""
    seen = PathAdaptive.projectFacesToXY(faces)
    outlines = [Part.Face(face.OuterWire).makeOffset2D(reach_mm) for face in seen.Faces]
    return outlines[0].fuse(outlines[1:]).removeSplitter() if len(outlines) > 1 else outlines[0]


def _picked_regions(proxy, obj, depths, reach_mm, material=None):
    """(inside, outside) regions as FreeCAD's ({"region", "depths"}) for
    picked floors (obj.Base). The area to clear on each depth: the floors'
    outlines seen from the tool (holes in them left out: they go down)
    grown by reach_mm (_outline), in the stock, less the models above the
    depth (and the Z allowance): _regions.

    FreeCAD keeps the whole tool inside the picked faces: on the user's
    test part (a Ø6 tool, the plate's floor 5.75 mm wide beside its holes)
    it cleared only the middle of the plate. Grown by the tool's radius the
    tool centre goes up to the floors' edges, as Fusion's "tool outside
    boundary", so it clears the floor up to its edges and the stock beside
    them; the models' walls above still bound it.

    An area reaching the edge of the stock is cleared as FreeCAD clears
    around a whole model (outside): all the rest of the stock is kept out,
    and the tool comes in from outside the stock and may move there (a
    strip beside a wall as wide as the tool gets cleared). Cleared inside
    instead, an area reaching out of the stock by about the tool's
    diameter made libarea come in from outside and then cut almost
    nothing. A closed area (a pocket) is cleared inside, on a helix."""
    return _regions(proxy, obj, depths, _outline(_picked(obj), reach_mm), material)


def _picked(obj):
    return [base.Shape.getElement(sub) for base, subs in obj.Base for sub in subs]


def _regions(proxy, obj, depths, outline, material=None):
    """(inside, outside) regions as FreeCAD's for the area outline (flat on
    Z0) on each depth (from the top): in the stock, less the models above
    the depth (and the Z allowance); open to the edge of the stock outside,
    else inside (_picked_regions). The stock: the Job's above the depth,
    or what there is of material above it (its depths: _stocks)."""
    models = _models(proxy)
    top = proxy.stock.Shape.BoundBox.ZMax
    allowance = obj.ZStockToLeave.Value
    inside, outside = [], []
    for depth in depths:
        if depth >= top:
            continue
        if material is None:
            stock = solid_projection(proxy.stock.Shape, depth - allowance)
        else:
            found = start_stock.area(material, depth - allowance, top)
            if found is None:
                continue
            stock = _material_stock(found).face
        above = solid_projection(models, depth - allowance)
        left = outline.common(stock)
        if above.Wires:
            left = left.cut(above)
        edges = [face.OuterWire for face in stock.Faces]
        open_ = []
        for face in left.Faces:
            if min(face.distToShape(edge)[0] for edge in edges) < 1e-3:
                open_.append(face)
            else:
                _add_region(inside, face, depth, face)
        if open_:
            area = open_[0].fuse(open_[1:]).removeSplitter() if len(open_) > 1 else open_[0]
            _add_region(outside, stock.cut(area), depth, area)  # the region kept out
    return inside, outside


def _floor_regions(proxy, obj, level, floors, reach_mm, within=None):
    """Regions as FreeCAD's ({"region", "depths"}), all cleared inside, on
    a level only floors have: around the floors lying there (their outlines
    grown by reach_mm, in the area within when given: flat on Z0) less the
    models above the level (and the Z allowance); none without such floors.

    Out of the stock too: where the tool can stand there, libarea comes in
    from outside it (pieces grows such an area out of the stock far enough
    for that: _out_of_stock; models: the models above the level). Cut to
    the stock, an area open to its edge came in on a helix and left the
    corners of a floor at the edge; cleared outside (_regions), libarea's
    finishing pass went all round the stock (on the user's plate 950 mm at
    the level of its steps)."""
    if not floors:
        return []
    outline = _outline(floors, reach_mm)
    if within is not None:
        outline = outline.common(within)
    depth = level + EPSILON_MM
    above = solid_projection(_models(proxy), depth - obj.ZStockToLeave.Value)
    left = outline.cut(above) if above.Wires else outline
    return [{"region": face, "area": face, "depths": [depth], "models": above} for face in left.Faces]


def pieces(proxy, obj, levels, top, tool_diameter_mm, adaptive):
    """The areas (model.clearing.Piece) the tool clears on the levels, for
    the operation obj (FreeCAD's Adaptive, its Base: the picked floors)
    with its proxy (model and stock of its Job); top: of the stock.

    On the full levels (adaptive.full_levels: the Z steps and the lowest)
    the whole area: around the whole model FreeCAD's (its roughing helper),
    for picked floors AvangardeCam's (_picked_regions). On a level only a
    floor has, the area around the floors lying there only: their
    outlines grown by FLOOR_REACH tool diameters and Finish XY
    (_floor_regions; where that goes out of the stock, grown out of it
    for the tool to come in from beside it: _out_of_stock), the rest is
    cleared on the next full level (the user: down into a counterbore,
    not all round the part again). All of
    them slice the model and the stock above each level less the Z
    allowance (obj.ZStockToLeave), which leaves it on the floors.

    The tool comes down over an area from 2 mm above the full level over
    it (or the top of the stock): the levels between cleared only around
    their floors.

    In a setup starting from a mesh (engine.next_setup.material) the stock
    of each level is what there is of the mesh from the level up to where
    the region's material starts (_stocks); a level with nothing worth a
    pass in a region is left out."""
    import area

    if not levels:
        return []
    from avangardecam.engine import next_setup

    material = next_setup.material(proxy.job)
    full = [z for z in levels if z in adaptive.full_levels(top)]
    shifted = [z + EPSILON_MM for z in full]
    if obj.Base:
        inside, outside = _picked_regions(proxy, obj, shifted, tool_diameter_mm / 2.0, material)
    else:
        with _safe_projections():
            inside, outside = PathAdaptive._workingEdgeHelperRoughing(proxy, obj, shifted)
    found = [(inside, outside)]
    floors = floor_faces([o.Shape for o in proxy.model])
    within = None
    if obj.Base:
        floors = under(floors, _picked(obj))
        within = _outline(_picked(obj), tool_diameter_mm / 2.0)  # as _picked_regions
    reach = FLOOR_REACH * tool_diameter_mm + adaptive.finish_xy_mm
    for level in levels:
        if level not in full:  # as model.operations.Adaptive.levels puts a level on a floor
            lying = [f for f in floors if abs(round(round(f.BoundBox.ZMin, 6) + adaptive.finish_z_mm, 6) - level) < 1e-6]  # fmt: skip
            found.append((_floor_regions(proxy, obj, level, lying, reach, within), []))
    regions = []  # (region, kind), of each the outside ones first
    for inside, outside in found:
        regions += [(region, area.AdaptiveOperationType.ClearingOutside) for region in outside]
        regions += [(region, area.AdaptiveOperationType.ClearingInside) for region in inside]
    allowance = obj.ZStockToLeave.Value
    result = []
    out = tool_diameter_mm + adaptive.finish_xy_mm + OUTSIDE_GAP_MM
    for region, kind in regions:
        is_inside = kind == area.AdaptiveOperationType.ClearingInside
        depths = sorted(region["depths"], reverse=True)
        for group, stock, above in _stocks(proxy, material, region["region"], is_inside, depths, full, top, allowance, adaptive.finish_xy_mm):
            own = tuple(round(d - EPSILON_MM, 6) + 0.0 for d in group)
            shape = region["region"]
            if "models" in region:  # a floor's (_floor_regions)
                shape = _out_of_stock(shape, stock.face, region["models"], out)
            path2d = PathAdaptive.convertTo2d(_discretized(shape))
            cleared = _clear_area(obj, adaptive, tool_diameter_mm, kind, stock.paths, path2d)
            for helix, start, paths in cleared:
                if helix is None:
                    start, paths = _in_from_outside(stock.face, start, paths, tool_diameter_mm / 2.0)
                result.append(clearing.Piece(own, above, helix, start, paths))
    return result


def _out_of_stock(region, stock, models, reach_mm):
    """An area cleared inside (region, flat on Z0) going out of the stock
    (flat on Z0), grown out of it where it goes out to reach_mm off it,
    less the models (above its level, flat on Z0). libarea comes into an
    area from outside the stock only where the tool's centre can stand
    clear of the stock (pieces: reach_mm is the tool's diameter, Finish XY
    and OUTSIDE_GAP_MM).

    On the user's plate (70 x 40 under a stock 2.1 mm wider each side, 5.1
    longer; a Ø6 tool) the area around its top went 4.1 mm out of the
    stock on the long sides: libarea came in on the short ends only, took
    the rest for cleared (too near the area's edge to be left) and its
    finishing pass took 2 mm off the long sides with the material on the
    wrong side of the tool (conventional milling); the top kept its stock.

    The two go together as one face (_joining), else the area stays as it
    was: libarea then has no room to come in beside the stock. On the
    mounting plate D (two pockets 3.5 deep open to the
    end of the plate, 5 mm of stock beyond it, a Ø6 tool) it cleared
    nothing in them and gave its finishing pass only, 70 mm away from
    where the tool went down, across the rib between them (_joined)."""
    try:
        outside = region.cut(stock)
        if not outside.Faces or outside.Area < 1e-6:
            return region  # in the stock: on a helix
        grown = [_offset(face, reach_mm) for face in region.common(stock).Faces]
        near = [_offset(face, reach_mm) for face in outside.Faces]
        if not grown:
            return region
        more = _fused(grown).common(_fused(near)).cut(stock)
        if models.Wires:
            more = more.cut(models)
        if not more.Faces:
            return region
        faces = _joining(region, more, models)
        if faces is None:
            return region  # not one face where they touch: as it is
    except Part.OCCError:
        return region  # as it is
    return faces[0] if len(faces) == 1 else Part.makeCompound(faces)


def _joining(region, more, models):
    """The faces of region and more (flat on Z0) together that take in
    region (not a strip beside the stock across a wall of it), none of
    them touching another; None when they cannot be put together so.
    Holes smaller than SLIVER_MM2 with none of models (flat on Z0) in
    them are left out.

    libarea takes two faces touching each other for nothing to clear, so
    first FreeCAD's fusion: it keeps the stock's outline as an edge
    between two faces, joined again by DraftGeomUtils.concatenate. On the
    mounting plate D, the arcs around two floors met
    0.04 mm in the stock and two faces stayed: then libarea's own
    (Path.Area, Clipper: 1.6 µm off the faces at its accuracy) puts them
    together, with a hole 0.06 x 0.04 mm where each arc came in; the tool
    would have kept its radius off it."""
    fused = DraftGeomUtils.concatenate(region.fuse(more).removeSplitter())
    faces = _taking_in(fused, region)
    if faces is None:
        joined = Path.Area(Accuracy=0.001)
        joined.add(region, op=0)
        joined.add(more, op=0)
        faces = _taking_in(joined.getShape(), region)
    if faces is None:
        return None
    return [_without_slivers(face, models) for face in faces]


def _taking_in(shape, region):
    """The faces of shape taking in some of region, None when none or two of them touch."""
    faces = [face for face in shape.Faces if face.common(region).Area > 1e-6]
    if not faces or any(a.distToShape(b)[0] < 1e-6 for i, a in enumerate(faces) for b in faces[i + 1 :]):
        return None
    return faces


def _without_slivers(face, models):
    """face (flat on Z0) without its holes smaller than SLIVER_MM2 with
    none of models in them."""
    holes = [wire for wire in face.Wires if not wire.isSame(face.OuterWire)]
    kept = []
    for wire in holes:
        hole = Part.Face(wire)
        if abs(hole.Area) < SLIVER_MM2 and not (models.Wires and models.common(hole).Area > 1e-9):
            continue
        kept.append(wire)
    if len(kept) == len(holes):
        return face
    return Part.makeFace([face.OuterWire] + kept, "Part::FaceMakerBullseye")


def _fused(faces):
    return faces[0].fuse(faces[1:]).removeSplitter() if len(faces) > 1 else faces[0]


def _over(full, level, top):
    """The full level over a level, else the top of the stock."""
    return next((z for z in reversed(full) if z > level + 1e-9), top)


def _nothing_left(material, region, inside, stock, finish_xy_mm):
    """No material worth a pass for libarea in a region (FreeCAD's: inside,
    the area to clear; outside, the area kept out) on a stock of material
    (_stocks, flat on Z0): none further from the region's edges than
    Finish XY and two diagonals of a cell, or less than a cell of it.

    Where the setup before cut along a wall already, the stock still has
    some beside it, and libarea would go round the wall in the air on every
    level: start_stock.area takes up to the diagonal of a cell more than
    the material (never less), and the stock left has its floors rounded
    down where they meet a wall, by up to half a cell within a cell of it
    (its surface's corners; 75 µm 0.13 mm off the wall in test_start_stock)."""
    cell = float(max(material.spacing[0], material.spacing[1]))
    band = finish_xy_mm + 2.0 * math.sqrt(2.0) * cell + EPSILON_MM
    pieces = []
    for face in region.Faces:
        try:
            pieces += _offset(face, -band if inside else band).Faces
        except Part.OCCError:
            if not inside:
                return False  # cannot tell: cleared as it is
            # shrunk to nothing: no material beyond the band
    if inside:
        left = stock.common(Part.makeCompound(pieces)) if pieces else Part.Shape()
    else:
        left = stock.cut(Part.makeCompound(pieces)) if pieces else stock
    return not left.Faces or left.Area < cell * cell


def _offset(face, distance):
    """A face flat on Z0 grown by distance (negative: shrunk). FreeCAD's
    offset goes the other way on a face turned over (a hole's region)."""
    moved = face.makeOffset2D(distance)
    if (moved.Area - face.Area) * distance < 0.0:
        moved = face.makeOffset2D(-distance)
    return moved


class _Stock(NamedTuple):
    """The stock libarea clears an area in: flat on Z0 (Part), and as
    libarea's paths (the outline first, then the holes in it)."""

    face: object
    paths: list


def _stocks(proxy, material, region, inside, depths, full, top, allowance, finish_xy_mm):
    """[(depths, _Stock, top)] libarea clears a region (FreeCAD's, inside
    or outside) on (depths: FreeCAD's, EPSILON_MM above their levels, from
    the top); top: where the material of the first of them starts.

    The Job's stock (a box, a casting) above the first depth less the Z
    allowance, for all of them; its material starts at the full level over
    the first. A setup starting from a mesh (material: its stock model)
    has on each depth what there is of it from the depth less the Z
    allowance up to where it starts: the region's depth before (less
    FLOOR_MM), as the tool cleared the region there; the top of the stock
    on its first depth (start_stock.area: never less than the material).
    So the tool takes no air under a stock left with steps. A depth with
    nothing worth a pass in the region (_nothing_left) is left out; what
    it has stays, so on the depths under it the material starts where it
    started on that depth: no rapid move over it. The depths after each
    other with the same stock go together."""
    if material is None:
        face = solid_projection(proxy.stock.Shape, depths[0] - allowance)
        paths = PathAdaptive.convertTo2d([e for f in face.Faces for e in _discretized(f)])
        return [(depths, _Stock(face, paths), _over(full, round(depths[0] - EPSILON_MM, 6), top))]
    groups = []
    starts = top  # where the material of the next depth starts
    before = None  # the stock of the depth before, when it is cleared
    for depth in depths:
        level = round(depth - EPSILON_MM, 6)
        found = start_stock.area(material, depth - allowance, starts - FLOOR_MM if starts < top else top)
        if found is None:
            before = None
            continue
        if before is not None and _same(before, found):
            groups[-1][0].append(depth)
            starts = level
            continue
        stock = _material_stock(found)
        if _nothing_left(material, region, inside, stock.face, finish_xy_mm):
            before = None
            continue  # its material stays: the next depth starts where it did
        groups.append(([depth], stock, starts))
        before = found
        starts = level
    return groups


def _same(a, b):
    """Two start_stock.area results are the same (None: none)."""
    if a is None or b is None:
        return a is b
    return [a[0].tolist()] + [h.tolist() for h in a[1]] == [b[0].tolist()] + [h.tolist() for h in b[1]]


def _material_stock(found):
    """The _Stock of start_stock.area's (outline, holes)."""
    import FreeCAD

    outline, holes = found
    loops = [outline] + list(holes)
    wires = []
    for loop in loops:
        points = [FreeCAD.Vector(float(x), float(y), 0.0) for x, y in loop]
        wires.append(Part.makePolygon(points + points[:1]))
    face = Part.makeFace(wires, "Part::FaceMakerBullseye")
    return _Stock(face, [loop.tolist() for loop in loops])


def _in_from_outside(stock, start, paths, radius_mm):
    """(start, paths) of a piece the tool comes into from beside the stock
    (stock: flat on Z0). libarea starts it overlapping the stock (by its
    step over, on an area of a floor's own level open to the edge of the
    stock more: 1.2 mm on the user's plate): going down there the tool
    cuts the stock's edge with its side all the way down (the user: in
    stainless steel that breaks the tool). So the tool goes down
    OUTSIDE_GAP_MM clear of the stock straight out from the start and in
    to it at the level."""
    import FreeCAD

    distance, pairs, _info = stock.distToShape(Part.Vertex(FreeCAD.Vector(start[0], start[1], 0.0)))
    clear = radius_mm + OUTSIDE_GAP_MM
    if distance < 1e-6 or distance >= clear - 1e-3:
        return start, paths  # in the stock (no way out to take), or clear of it already
    edge = pairs[0][0]
    out = ((start[0] - edge.x) / distance, (start[1] - edge.y) / distance)
    down = (edge.x + out[0] * clear, edge.y + out[1] * clear)
    if stock.distToShape(Part.Vertex(FreeCAD.Vector(down[0], down[1], 0.0)))[0] < clear - 1e-3:
        return start, paths  # a stock not convex there
    return down, ((clearing.CUT, (start,)),) + tuple(paths)


def _clear_area(obj, adaptive, tool_diameter_mm, kind, stock2d, path2d):
    """_clear of an area, a closed one (ClearingInside) come into on a
    smaller helix (HELICES) while libarea leaves it out."""
    import area

    for part in HELICES:
        cleared = _clear(obj, adaptive, tool_diameter_mm, part * tool_diameter_mm, kind, stock2d, path2d)
        if cleared or kind != area.AdaptiveOperationType.ClearingInside:
            break
    return cleared


def _clear(obj, adaptive, tool_diameter_mm, helix_mm, kind, stock2d, path2d):
    """[(helix centre or None, start, paths)] of libarea's Adaptive2d clearing an area."""
    import area

    kinds = {
        area.AdaptiveMotionType.Cutting: clearing.CUT,
        area.AdaptiveMotionType.LinkClear: clearing.LINK,
        area.AdaptiveMotionType.LinkNotClear: clearing.UP,
    }
    a2d = area.Adaptive2d()
    a2d.stepOverFactor = 0.01 * adaptive.step_over_percent
    a2d.toolDiameter = tool_diameter_mm
    a2d.helixRampDiameter = helix_mm  # 0: the tool's diameter
    a2d.keepToolDownDistRatio = float(obj.KeepToolDownRatio)
    a2d.stockToLeave = adaptive.finish_xy_mm
    a2d.tolerance = max(0.001, float(obj.Tolerance))
    a2d.forceInsideOut = False
    a2d.finishingProfile = adaptive.finishing_pass
    a2d.opType = kind
    result = []
    for found in a2d.Execute(stock2d, path2d, lambda _paths: False):
        paths = tuple(
            (kinds[motion], tuple((float(x), float(y)) for x, y in points))
            for motion, points in found.AdaptivePaths
            if points
        )
        if not paths:
            continue
        helix = tuple(found.HelixCenterPoint)[:2]
        start = tuple(found.StartPoint)[:2]
        paths = _joined(obj, start, paths, max(JUMP_MM, 2.0 * a2d.tolerance))
        result.append((None if math.dist(helix, start) <= 1e-9 else helix, start, paths))
    return result


def _joined(obj, start, paths, jump_mm):
    """libarea's paths of a piece starting at start, a way over the uncut
    material (UP) to a cut starting further than jump_mm from where the
    tool is: the tool goes up, over and down into it, not straight through
    whatever is between (obj: the operation, for its warning).

    libarea's cuts go on where the path before ends (0.03 mm off it on the
    user's plate, 0.1 after a way over cleared floor), and FreeCAD's own
    Adaptive feeds straight to each one. But when libarea clears nothing
    in an area it gives the finishing pass only, wherever that starts: on
    the mounting plate D 70 mm from where the tool
    went down, across the rib between two pockets, 3.4 mm into the top of
    the part."""
    result = []
    at = start
    for kind, points in paths:
        if kind == clearing.CUT and math.dist(at, points[0]) > jump_mm:
            Path.Log.warning(
                "{}: a cut does not start where the tool is ({:.1f} mm off it); "
                "the tool goes over the safe height to it.".format(obj.Label, math.dist(at, points[0]))
            )
            result.append((clearing.UP, (points[0],)))
        result.append((kind, points))
        at = points[-1]
    return tuple(result)
