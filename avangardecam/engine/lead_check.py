# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Approach arcs that do not fit, without compensation (the user's choice
2026-11-02: a warning that may be passed over, not a refusal).

Without compensation the tool centre runs the lead line and arc
themselves (geometry.contour_runs), beside the lines by the XY offset (a
chamfer mill's centre beside the edge). In a small hole the default arc
does not fit: it bends round past the lines' side and the tool centre
comes closer to the edge than the offset, so the chamfer gets larger
there, or across the lines, into the part. too_close finds the chains
where that happens: the closest the tool centre comes on the lead to
any line of the sketch, against the offset it runs the lines at.
"""

from typing import NamedTuple

from avangardecam.engine import geometry
from avangardecam.model import operations as model_operations

SAMPLES = 24  # points on each lead line and arc
TOLERANCE_MM = 0.01


class TooClose(NamedTuple):
    sketch: object
    lines: list  # names of the chain's lines
    closest_mm: float  # how close the tool centre comes to the lines on the lead
    offset_mm: float  # how far beside them it runs the lines


def checked(contour):
    """True for a contour whose approach arcs too_close checks: arcs, no
    compensation, the tool centre beside the lines."""
    return (
        contour.compensation == model_operations.OFF
        and contour.approach == model_operations.ARC
        and contour.offset_xy_mm > TOLERANCE_MM
    )


def too_close(sketch, names, backwards, contour, lead_radius, tool_radius, flipped=False):
    """TooClose of each chain of the lines (names, [] for all of them;
    backwards as geometry.contour_runs) whose approach or leaving arc
    brings the tool centre closer to a line of the sketch than the
    contour's XY offset; [] when none does or the contour is not checked."""
    import Part

    if not checked(contour):
        return []
    names = list(names) or geometry.all_lines(sketch)
    chains = geometry.line_chains(sketch, names)
    runs = geometry.contour_runs(
        sketch, names, set(backwards), contour.compensation, contour.approach, lead_radius, tool_radius,
        contour.xy_offsets(), contour.arc_side, contour.start_extend_mm, contour.end_extend_mm, flipped,
    )  # fmt: skip
    place = geometry.facing_tool(sketch.Placement, flipped)
    lines = sketch.Shape.transformed(place.inverse().toMatrix())  # in the runs' coordinates
    found = []
    for run in runs:
        if not run.lead or len(run.centre) < 4:
            continue
        closest = None
        for edge in run.centre[:2] + run.centre[-2:]:  # line and arc in, arc and line out
            for k in range(SAMPLES + 1):
                point = edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * k / SAMPLES)
                point.z = lines.BoundBox.ZMin
                distance = Part.Vertex(point).distToShape(lines)[0]
                closest = distance if closest is None else min(closest, distance)
        if closest is not None and closest < contour.offset_xy_mm - TOLERANCE_MM:
            chain = chains[run.chain] if run.chain < len(chains) else []
            found.append(TooClose(sketch, chain, round(closest, 3) + 0.0, contour.offset_xy_mm))
    return found


HEADER = "The approach arc does not fit here: on it the tool centre comes closer to the lines than on them, so the chamfer gets larger there (at 0 mm the tool runs across the lines, into the part). Enter a smaller approach radius or go straight down."  # fmt: skip
ROW = "{}: {} - {:g} mm from the lines on the arc, {:g} mm beside them on the lines"


def text(found, translate=lambda s: s):
    """The warning for the chains of too_close, "" for none; translate:
    the GUI's tr for its sentences."""
    if not found:
        return ""
    rows = [translate(ROW).format(f.sketch.Label, ", ".join(f.lines), f.closest_mm, f.offset_mm) for f in found]
    return translate(HEADER) + "\n" + "\n".join(rows)


def for_picks(job, picks, contour, tool_radius):
    """too_close for picks ((sketch, lines, backwards) as
    freecad_cam.add_contour_sketches) of a contour in job."""
    from avangardecam.engine import freecad_cam as cam
    from avangardecam.model import leads as model_leads

    if not checked(contour):
        return []
    lead = contour.lead_radius_mm if contour.lead_radius_mm is not None else model_leads.default_radius(tool_radius)
    found = []
    for sketch, lines, backwards in picks:
        found += too_close(sketch, lines, backwards, contour, lead, tool_radius, cam.sketch_faces_away(job, sketch))
    return found


def op_picks(op):
    """(sketch, lines, backwards) of each helper of a contour, as for_picks takes them."""
    from avangardecam.engine import freecad_cam as cam

    picks = []
    for helper in cam.helper_objects(op):
        names, backwards = geometry.helper_lines(helper)
        picks.append((helper.Sketch, list(names), list(backwards)))
    return picks


def for_op(op, contour=None):
    """too_close of a contour operation (its own values, or contour)."""
    from avangardecam.engine import freecad_cam as cam

    contour = contour if contour is not None else cam.contour_of(op)[1]
    return for_picks(cam.setup_of(op), op_picks(op), contour, cam._tool_radius(op.ToolController))
