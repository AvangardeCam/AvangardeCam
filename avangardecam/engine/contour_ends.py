# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Start contour and End contour: the lines of an open chain made longer
or shorter at their start and end (model Contour.start_extend_mm,
end_extend_mm), before the XY passes, compensation and approach arcs are
made from them (geometry.contour_runs).

Longer: a straight line on from the first line's start (back against the
tool's direction) or from the last line's end, along their tangent, e.g.
to take the stock off past the part's corner. Shorter: the lines start or
end that far along them, measured along the lines (a chamfer mill leaves
before a wall standing up at the end). The program has the new lines, so
compensation and the approach arcs follow them.
"""

import FreeCAD
import Part

# lines shorter than this are not left
_MIN_MM = 1e-3


class EndsError(ValueError):
    """The lines cannot be made that much shorter."""


def _start(edge):
    return edge.valueAt(edge.FirstParameter)


def _end(edge):
    return edge.valueAt(edge.LastParameter)


def _direction(edge, at_end):
    t = edge.tangentAt(edge.LastParameter if at_end else edge.FirstParameter)
    t = FreeCAD.Vector(t.x, t.y, 0.0)
    t.normalize()
    return t


def _piece(edge, u0, u1):
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


def _cut_start(lines, length):
    """The lines without their first length mm."""
    lines = list(lines)
    while lines and lines[0].Length <= length + _MIN_MM:
        length -= lines.pop(0).Length
    if not lines:
        return []
    edge = lines[0]
    if length > 0.0:
        lines[0] = _piece(edge, edge.getParameterByLength(length), edge.LastParameter)
    return lines


def _cut_end(lines, length):
    """The lines without their last length mm."""
    lines = list(lines)
    while lines and lines[-1].Length <= length + _MIN_MM:
        length -= lines.pop().Length
    if not lines:
        return []
    edge = lines[-1]
    if length > 0.0:
        lines[-1] = _piece(edge, edge.FirstParameter, edge.getParameterByLength(edge.Length - length))
    return lines


def changed(lines, start_mm, end_mm, label=""):
    """The directed edges of an open chain, longer (positive) or shorter
    (negative) by start_mm at the start and end_mm at the end. Raises
    EndsError when nothing is left of them."""
    total = sum(e.Length for e in lines)
    cut = max(-start_mm, 0.0) + max(-end_mm, 0.0)
    if cut >= total - _MIN_MM:
        raise EndsError(
            "{}Start contour and End contour ({:g} and {:g} mm) shorten the lines ({:g} mm long) to "
            "nothing.".format(label + ": " if label else "", start_mm, end_mm, round(total, 3))
        )
    result = list(lines)
    if start_mm < 0.0:
        result = _cut_start(result, -start_mm)
    if end_mm < 0.0:
        result = _cut_end(result, -end_mm)
    if start_mm > 0.0:
        first = _start(result[0])
        before = first - _direction(result[0], False) * start_mm
        if _straight(result[0]):  # one line in the program, not two
            result[0] = Part.LineSegment(before, _end(result[0])).toShape()
        else:
            result.insert(0, Part.LineSegment(before, first).toShape())
    if end_mm > 0.0:
        last = _end(result[-1])
        after = last + _direction(result[-1], True) * end_mm
        if _straight(result[-1]):
            result[-1] = Part.LineSegment(_start(result[-1]), after).toShape()
        else:
            result.append(Part.LineSegment(last, after).toShape())
    return result


def _straight(edge):
    return isinstance(edge.Curve, (Part.Line, Part.LineSegment))
