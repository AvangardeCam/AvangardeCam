# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""A zero point in the middle of a circle (CAM > Move 0-Point > Select
circle), on its own.

The user clicks a round edge of the part, or the wall of a round hole or
pin: the zero point goes to the middle of the circle at the mouth of the
hole (the top of the pin) and, with 5 axes, its Z turns along the
circle's axis, out of the part, so that the tool stands on it: the holes
in the end of a tube and the bore in its middle, from the end.

The mouth is the end of the hole a tool reaches from outside the part:
nothing of the part beyond it along the axis (a blind hole's floor has
the part beyond it), and of two such ends the one with less of the part
around its way out (a bore that opens into a hollow inside the part has
the whole part around it beyond its inner end; it opens to the outside at
the end of the part). When the two differ by no more than the circle's
diameter (a hole through a plate, a countersink on one end) the end the
user clicked is taken. What lies beyond an end is found by the engine
(engine.circle_zero asks FreeCAD); the choice is here.

Plain Python: points and directions are (x, y, z) tuples in the part's
coordinates, a zero point is a model.frame.Frame, a shift is (x, y, z) in
mm along the frame's own axes.
"""

from avangardecam.model import frame as model_frame

_DECIMALS = model_frame.ORIGIN_DECIMALS
# a direction this close to the zero point's Z goes along it
_ALONG = 1e-9

# ends with this much less of the part around them are no better (and at
# least the circle's diameter, see mouth())
SAME_DEPTH_MM = 0.01

OUT = 1  # the circle's axis points out of the part
IN = -1  # its opposite does
UNKNOWN = 0  # the same material on both sides: it cannot be told


def to_point(frame, point):
    """The shift along the frame's own axes that puts its origin on point."""
    return tuple(round(value, _DECIMALS) + 0.0 for value in frame.to_frame(point))


class End:
    """An end of a hole or pin (or a sense of a circle's axis), as the
    engine found it: free (nothing of the part beyond it along the axis;
    None: not known), depth (how far beyond it the part reaches around its
    way out, mm), picked (the user clicked its very circle), distance (mm
    from the click)."""

    def __init__(self, free, depth, picked=False, distance=0.0):
        self.free, self.depth, self.picked, self.distance = free, depth, picked, distance

    def __repr__(self):
        return "End(free={}, depth={:g}, picked={}, distance={:g})".format(
            self.free, self.depth, self.picked, self.distance
        )


def mouth(ends, diameter=0.0):
    """The index of the end a tool comes in from outside the part: a free
    one; of free ones the one with less of the part around its way out;
    when they differ by no more than the circle's diameter, the one
    clicked, else the one nearer to the click. None when no end is free
    (the circle is inside the part): then the material just around it
    decides (side())."""
    free = [i for i, end in enumerate(ends) if end.free]
    if not free:
        return None
    least = min(ends[i].depth for i in free)
    alike = [i for i in free if ends[i].depth - least <= max(SAME_DEPTH_MM, diameter)]
    picked = [i for i in alike if ends[i].picked]
    if len(picked) == 1:
        return picked[0]
    return min(alike, key=lambda i: (ends[i].distance, -i))


def side(above, below):
    """Which way the circle's axis points out of the part: above and below
    count the probes around the circle that are in material just along the
    axis and just against it. The side with less material is out."""
    if above == below:
        return UNKNOWN
    return OUT if above < below else IN


def along_z(frame, direction):
    """Whether direction goes along the frame's Z (either way): the tool
    already stands along the circle's axis."""
    length = sum(c * c for c in direction) ** 0.5
    if length == 0.0:
        return False
    cos = sum(a * b for a, b in zip(direction, frame.z_axis)) / length
    return abs(abs(cos) - 1.0) < _ALONG


def diameter_text(radius):
    """ "Ø600" or "Ø12.5": the circle's diameter in mm."""
    return "Ø{:g}".format(round(2.0 * radius, 3) + 0.0)
