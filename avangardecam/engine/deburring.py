# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Deburring (model.deburring) on FreeCAD: a contour of a chamfer mill.

The operation is a contour (freecad_cam.add_contour_sketches, "Deburring
1") on the picked sketch lines, so its path, the program, Verify, Play and
the cycle time are the contour's. Its model Contour (AvangardeOperation)
is worked out of the user's model Deburring, kept beside it in
AvangardeDeburring: the depth and the offset of the tool centre come from
the tool's cone, so they are worked out again with another tool
(set_deburring_tool) or another variant of it (follow_tool, from
freecad_cam._sync_operations).
"""

import Path

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.model import deburring as model_deburring
from avangardecam.model import leads as model_leads
from avangardecam.model import operations as model_operations

PROPERTY = "AvangardeDeburring"


def deburring_of(op):
    """(sketch, model Deburring) of a deburring made by AvangardeCam, else None."""
    text = getattr(op, PROPERTY, "")
    found = cam.contour_of(op) if text else None
    if found is None:
        return None
    return found[0], model_deburring.from_json(text)


def tool_of(tc):
    """The model Tool of a tool controller; ProjectError without one."""
    if tc is None or getattr(tc, "Tool", None) is None:
        raise cam.ProjectError("The deburring has no tool.")
    return cam._tool_from_controller(tc)


def contour_for(deburring, tc):
    """The model Contour of a deburring with the tool of tc; ProjectError
    when the tool cannot make it."""
    try:
        tool = tool_of(tc)
        return model_deburring.to_contour(model_deburring.check(deburring, tool), tool)
    except ValueError as exc:
        raise cam.ProjectError(str(exc))


def on_material(job, picks, deburring, tool):
    """Closed loops of picks ((sketch, lines, backwards) as add_deburring;
    lines [] for all) where the tool centre would run on the material of
    the sketch's face (an outline run inside, a hole outside: a groove in
    the part), as "Sketch: Edge1, Edge2, ..." texts. The face is the one
    the closed loops of the sketch make (Extract boundary edges: the
    outline and its holes); lines that do not close are not checked.
    tool: the model Tool. The user may deburr anyway (the arrows and the
    side are theirs)."""
    contour = model_deburring.to_contour(deburring, tool)
    radius = tool.diameter_mm / 2.0
    lead = contour.lead_radius_mm if contour.lead_radius_mm is not None else model_leads.default_radius(radius)
    found = []
    for sketch, lines, backwards in picks:
        flipped = cam.sketch_faces_away(job, sketch)
        face = _face(sketch, geometry.facing_tool(sketch.Placement, flipped))
        if face is None:
            continue
        names = list(lines) or geometry.all_lines(sketch)
        chains = geometry.line_chains(sketch, names)
        runs = geometry.contour_runs(
            sketch, names, set(backwards), contour.compensation, contour.approach, lead, radius,
            contour.xy_offsets(), contour.arc_side, contour.start_extend_mm, contour.end_extend_mm, flipped,
        )  # fmt: skip
        for run in runs:
            if _closed(run.program) and _on(face, run.centre):
                found.append("{}: {}".format(sketch.Label, ", ".join(chains[run.chain]) if run.chain < len(chains) else ""))
    return found


def leads_too_close(job, picks, deburring, tool):
    """engine.lead_check.TooClose of the chains of picks (as on_material)
    whose approach arc does not fit (a small hole)."""
    from avangardecam.engine import lead_check

    return lead_check.for_picks(job, picks, model_deburring.to_contour(deburring, tool), tool.diameter_mm / 2.0)


def _face(sketch, place):
    """The face the closed wires of a sketch make (holes cut out), in the
    coordinates of its runs (place: where they are); None without one."""
    import Part

    try:
        shape = sketch.Shape.transformed(place.inverse().toMatrix())
        wires = [w for w in shape.Wires if w.isClosed()]
        return Part.makeFace(wires, "Part::FaceMakerBullseye") if wires else None
    except Exception:  # FreeCAD's CADKernelError or OCCError: nothing to check against
        return None


def _closed(edges):
    return bool(edges) and edges[0].Vertexes[0].Point.isEqual(edges[-1].Vertexes[-1].Point, 1e-6)


def _on(face, edges):
    """True when most of the length of edges (their middles) is on the face."""
    on = total = 0.0
    for edge in edges:
        middle = edge.valueAt(edge.getParameterByLength(edge.Length / 2.0))
        middle.z = face.BoundBox.ZMin
        total += edge.Length
        if face.isInside(middle, 1e-6, True):
            on += edge.Length
    return total > 0.0 and on > total / 2.0


def add_deburring(job, picks, deburring, tc):
    """Deburring on lines of sketches: picks as freecad_cam.add_contour_sketches,
    (sketch, lines, backwards) in the tool's order."""
    if tc not in job.Tools.Group:
        raise cam.ProjectError("{} is not a tool of {}.".format(tc.Label, job.Label))
    op = cam.add_contour_sketches(job, picks, contour_for(deburring, tc), tc, name="Deburring")
    _store(op, deburring)
    return op


def set_deburring(op, deburring):
    """Change the user's values of a deburring."""
    cam.set_contour(op, contour_for(deburring, op.ToolController))
    _store(op, deburring)


def set_deburring_tool(op, tc):
    """Another tool of its setup for a deburring: its depth and offset
    follow the new cone."""
    _sketch, deburring = deburring_of(op)
    contour = contour_for(deburring, tc)
    old = op.ToolController
    op.ToolController = tc
    try:
        cam.set_contour(op, contour)
    except (cam.ProjectError, ValueError):
        op.ToolController = old
        raise


def op_picks(op):
    """(sketch, lines, backwards) of each helper of a deburring, as add_deburring takes them."""
    from avangardecam.engine import lead_check

    return lead_check.op_picks(op)


def follow_tool(op):
    """The contour of a deburring again from its tool (another variant of
    its T number, freecad_cam.replace_tool); a tool that cannot make it
    leaves the contour as it was, saying why."""
    _sketch, deburring = deburring_of(op)
    try:
        contour = contour_for(deburring, op.ToolController)
    except cam.ProjectError as exc:
        Path.Log.error("{}: {}".format(op.Label, exc))
        return
    if cam.contour_of(op)[1] != contour:
        setattr(op, cam._OPERATION_PROPERTY, model_operations.to_json(contour))


def _store(op, deburring):
    cam._add_property(op, "App::PropertyString", PROPERTY, "The deburring as the user set it up in AvangardeCam")
    setattr(op, PROPERTY, model_deburring.to_json(deburring))
