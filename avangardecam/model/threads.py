# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Threads: the standard sizes, and the helix a thread mill runs.

The shop mills internal right-hand threads as its programs have them
(a real program of the shop, M3 with T216): over the hole, down to its top
with the Z feed, straight out from the centre to the thread's major
radius with the radius compensation right (RR), then down a helix in
half turns clockwise (CP IPA-180. IZ-P/2 DR-), back to the centre (R0),
and the same helix again for each further pass. From hole to hole 10 mm
above the top.
"""

import math
from typing import NamedTuple

from avangardecam.model import nc
from avangardecam.model.operations import APPROACH_Z_MM, SAFETY_MM

BETWEEN_MM = 10.0  # above the holes' top, from one hole to the next (the shop's programs)

# ISO metric coarse and the usual fine threads, and pipe threads (G, BSP):
# name, major diameter, pitch
STANDARD = (
    ("M1", 1.0, 0.25), ("M1.2", 1.2, 0.25), ("M1.4", 1.4, 0.3), ("M1.6", 1.6, 0.35),
    ("M2", 2.0, 0.4), ("M2.5", 2.5, 0.45), ("M3", 3.0, 0.5), ("M3.5", 3.5, 0.6),
    ("M4", 4.0, 0.7), ("M5", 5.0, 0.8), ("M6", 6.0, 1.0), ("M8", 8.0, 1.25),
    ("M8x1", 8.0, 1.0), ("M10", 10.0, 1.5), ("M10x1.25", 10.0, 1.25), ("M10x1", 10.0, 1.0),
    ("M12", 12.0, 1.75), ("M12x1.5", 12.0, 1.5), ("M12x1.25", 12.0, 1.25), ("M14", 14.0, 2.0),
    ("M14x1.5", 14.0, 1.5), ("M16", 16.0, 2.0), ("M16x1.5", 16.0, 1.5), ("M18", 18.0, 2.5),
    ("M18x1.5", 18.0, 1.5), ("M20", 20.0, 2.5), ("M20x1.5", 20.0, 1.5), ("M22", 22.0, 2.5),
    ("M24", 24.0, 3.0), ("M24x2", 24.0, 2.0), ("M27", 27.0, 3.0), ("M30", 30.0, 3.5),
    ("M30x2", 30.0, 2.0), ("M33", 33.0, 3.5), ("M36", 36.0, 4.0),
    ("G1/8", 9.728, 25.4 / 28), ("G1/4", 13.157, 25.4 / 19), ("G3/8", 16.662, 25.4 / 19),
    ("G1/2", 20.955, 25.4 / 14), ("G3/4", 26.441, 25.4 / 14), ("G1", 33.249, 25.4 / 11),
)  # fmt: skip

# a hole drilled for a thread is about its major diameter less the pitch
# (M12: 10.2 for 10.25); pipe threads are drilled a little bigger
_SAME_MM = 0.1
_SAME_PITCH = 0.01


def standard(major_mm, pitch_mm):
    """Name of the standard thread of that size ("M3", "M10x1", "G1/4"),
    None when it is not one."""
    for name, major, pitch in STANDARD:
        if abs(major - major_mm) < 0.005 and abs(pitch - pitch_mm) < _SAME_PITCH:
            return name
    return None


def name(major_mm, pitch_mm):
    """"M3", or "Ø3.2 P0.5" for a thread that is not a standard one."""
    return standard(major_mm, pitch_mm) or "Ø{:g} P{:g}".format(round(major_mm, 3), round(pitch_mm, 4))


def _nearest(diameter_mm, pitch_mm):
    found = [
        (abs(major - diameter_mm), major)
        for _name, major, pitch in STANDARD
        if abs(pitch - pitch_mm) < _SAME_PITCH and abs(major - diameter_mm) < _SAME_MM
    ]
    return min(found)[1] if found else None


def suggested_major(hole_diameter_mm, pitch_mm):
    """The major diameter of the thread for a hole of a model or a sketch's
    circle (the user's choice): the hole drilled for the thread is its
    major diameter less the pitch (Ø2.5 with P0.5: M3); a hole as big as a
    standard thread of that pitch already is its major diameter (a sketch's
    circle drawn at M3); else the hole plus the pitch."""
    major = _nearest(hole_diameter_mm + pitch_mm, pitch_mm)
    if major is None:
        major = _nearest(hole_diameter_mm, pitch_mm)
    return major if major is not None else round(hole_diameter_mm + pitch_mm, 6)


class ThreadHole(NamedTuple):
    """A hole to mill a thread in, in the setup's coordinates: the centre of its top."""

    x: float
    y: float
    top: float


def turns(thread, pitch_mm):
    """(full half turns, the depth left after them, mm) of the helix of a
    thread: the last arc is shorter (the user's choice), the pitch stays."""
    half = pitch_mm / 2.0
    depth = -thread.depth_mm
    full = int(math.floor(depth / half + 1e-9))
    rest = depth - full * half
    return full, (rest if rest > 1e-6 else 0.0)


def moves(thread, holes, pitch_mm, radius_mm, feed_z_mm_min, feed_xy_mm_min, compensation=None):
    """The tool's moves of a thread milling (model.operations.ThreadMilling)
    in the holes (ThreadHole) in their order, as nc.Move.

    radius_mm: of the helix; the major radius with compensation RIGHT (the
    program: the control keeps the tool inside by its radius), the major
    radius less the tool's without (where the tool centre runs, FreeCAD's
    path)."""
    full, rest = turns(thread, pitch_mm)
    half = pitch_mm / 2.0
    result = []
    previous = None
    for x, y, top in holes:
        if previous is None:
            result.append(nc.Move(nc.RAPID, x, y, max(APPROACH_Z_MM, top + SAFETY_MM)))
        else:
            result.append(nc.Move(nc.RAPID, x, y, max(previous, top) + BETWEEN_MM))
        result.append(nc.Move(nc.RAPID, x, y, top + SAFETY_MM))
        for k in range(thread.passes):
            if k == 0:
                result.append(nc.Move(nc.LINE, x, y, top, feed_z_mm_min))
            else:
                result.append(nc.Move(nc.RAPID, x, y, top))
            result.append(nc.Move(nc.LINE, x + radius_mm, y, top, feed_xy_mm_min, compensation=compensation))
            angle = 0.0  # degrees, clockwise is negative
            z = top
            arcs = [(180.0, half)] * full + ([(360.0 * rest / pitch_mm, rest)] if rest else [])
            for sweep, down in arcs:
                angle -= sweep
                z -= down
                a = math.radians(angle)
                end_x, end_y = x + radius_mm * math.cos(a), y + radius_mm * math.sin(a)
                result.append(nc.Move(nc.ARC, end_x, end_y, z, feed_xy_mm_min, (x, y), True, compensation))
            result.append(nc.Move(nc.LINE, x, y, top + thread.depth_mm, feed_xy_mm_min))
        result.append(nc.Move(nc.RAPID, x, y, top + BETWEEN_MM))
        previous = top
    return tuple(result)
