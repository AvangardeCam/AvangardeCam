# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The moves the machine makes (model.machine), plain Python with numpy:

    python3 -m unittest avangardecam.tests.test_machine   (from src/Mod/AvangardeCam)
"""

import unittest

import numpy as np

from avangardecam.model import helix, machine, nc
from avangardecam.stocklab.cut import arc_points

NC_6 = nc.Tool(1, "Frees 6mm", 6.0, 8000.0, 200.0, 600.0)
NC_3 = nc.Tool(2, "Frees 3mm", 3.0, 12000.0, 225.0, 300.0)


def points(segments, tolerance=1e-4):
    """Points along the tool's tip moves, arcs as chords within tolerance."""
    result = []
    for s in segments:
        if s.centre is not None:
            centre = (s.centre[0], s.centre[1], 0.0)
            result += arc_points("+Z", s.start, s.end, centre, not s.clockwise, tolerance)
        else:
            result += [np.array(s.start, float), np.array(s.end, float)]
    return np.array(result)


def furthest(a, b):
    """The furthest any point of a is from the polyline through b."""
    p0, p1 = b[:-1], b[1:]
    d = p1 - p0
    length = np.maximum(np.einsum("ij,ij->i", d, d), 1e-24)
    worst = 0.0
    for start in range(0, len(a), 500):
        q = a[start : start + 500, None, :]
        t = np.clip(np.einsum("qij,ij->qi", q - p0, d) / length, 0.0, 1.0)
        gap = np.linalg.norm(q - (p0 + t[..., None] * d), axis=2).min(axis=1)
        worst = max(worst, float(gap.max()))
    return worst


def segments_of(moves, tool=NC_6, radius=None):
    op = nc.Operation(nc.CONTOUR, "Contour", tool, tuple(moves))
    elements = machine.Machine(machine.RETRACT_Z_MM, machine.TOOL_CHANGE_Z_MM).elements(op)
    notes = []
    radius = tool.diameter_mm / 2.0 if radius is None else radius
    return machine.machine_segments(elements, radius, notes), notes


def square(compensation, z=-1.0):
    """A 10 mm square counterclockwise from (0, 0), switched on from
    (-5, -5) and off back to it."""
    feed = 600.0
    moves = [nc.Move(nc.RAPID, -5.0, -5.0, 2.0), nc.Move(nc.LINE, -5.0, -5.0, z, 200.0)]
    moves.append(nc.Move(nc.LINE, 0.0, 0.0, z, feed, compensation=compensation))
    for x, y in ((10, 0), (10, 10), (0, 10), (0, 0)):
        moves.append(nc.Move(nc.LINE, float(x), float(y), z, feed, compensation=compensation))
    moves.append(nc.Move(nc.LINE, -5.0, -5.0, z, feed))
    return moves


class CompensationTest(unittest.TestCase):
    def test_outside_corners_are_rounded(self):
        segments, notes = segments_of(square(nc.RIGHT))
        self.assertEqual(notes, [])
        cut = [s for s in segments if s.start[2] == -1.0 and s.end[2] == -1.0]
        # switched on: from (-5, -5) square to the first line, 3 right of it
        self.assertEqual(cut[0].start[:2], (-5.0, -5.0))
        np.testing.assert_allclose(cut[0].end[:2], (0.0, -3.0))
        np.testing.assert_allclose((cut[1].start[:2], cut[1].end[:2]), ((0.0, -3.0), (10.0, -3.0)))
        corner = cut[2]  # round (10, 0), counterclockwise as the square
        self.assertEqual((corner.centre, corner.clockwise), ((10.0, 0.0), False))
        np.testing.assert_allclose(corner.end[:2], (13.0, 0.0))
        self.assertEqual(sum(1 for s in cut if s.centre is not None), 3)  # not at the last point
        # off: from beside the last line straight back
        np.testing.assert_allclose(cut[-1].start[:2], (-3.0, 0.0))
        self.assertEqual(cut[-1].end[:2], (-5.0, -5.0))

    def test_inside_corners_meet(self):
        segments, notes = segments_of(square(nc.LEFT))
        self.assertEqual(notes, [])
        cut = [s for s in segments if s.start[2] == -1.0 and s.end[2] == -1.0]
        self.assertTrue(all(s.centre is None for s in cut))
        corners = [tuple(float(v) for v in np.round(s.end[:2], 9)) for s in cut[1:-1]]
        self.assertEqual(corners, [(7.0, 3.0), (7.0, 7.0), (3.0, 7.0), (3.0, 0.0)])  # the last not trimmed: off after it
        np.testing.assert_allclose(cut[0].end[:2], (0.0, 3.0))  # on: square to the first line

    def test_too_small_inside(self):
        _segments, notes = segments_of(square(nc.LEFT), radius=6.0)
        self.assertTrue(notes)

    def test_helix_as_the_tool_centre(self):
        """The program of a helix milling (RL), compensated as the control
        does it, is the tool centre's path FreeCAD gets (program=False)."""
        for method in (helix.HELIX, helix.HELIX_CONTOUR):
            for side in (nc.LEFT, nc.RIGHT):
                milling = helix.HelixMilling(method=method, compensation=side, finish_xy_mm=0.2, predrilled_mm=0.0)
                holes = [helix.HelixHole(5.0, 2.0, 0.0, -1.5, 8.0)]
                program = helix.moves(milling, holes, 3.0, 225.0, 300.0)
                centre = helix.moves(milling, holes, 3.0, 225.0, 300.0, program=False)
                machine, notes = segments_of(program, NC_3)
                followed, _ = segments_of(centre, NC_3, radius=0.0)
                self.assertEqual(notes, [])
                # points of one path no further than 0.001 from the chords (0.0001) of the other
                self.assertLess(furthest(points(machine, 0.01), points(followed)), 1e-3, (method, side))
                self.assertLess(furthest(points(followed, 0.01), points(machine)), 1e-3, (method, side))


class MachineTest(unittest.TestCase):
    def test_way_between_operations(self):
        first = nc.Operation(nc.CONTOUR, "A", NC_6, (nc.Move(nc.RAPID, 0.0, 0.0, 2.0), nc.Move(nc.LINE, 5.0, 0.0, -1.0, 600.0)))
        second = nc.Operation(nc.CONTOUR, "B", NC_6, (nc.Move(nc.RAPID, 20.0, 0.0, 2.0), nc.Move(nc.LINE, 25.0, 0.0, -1.0, 600.0)))
        follower = machine.Machine(40.0, 100.0)
        a = follower.elements(first)
        self.assertEqual(a[0].start, (0.0, 0.0, 100.0))  # after the tool change
        self.assertEqual(a[-1].end, (5.0, 0.0, 40.0))
        b = follower.elements(second)
        self.assertEqual((b[0].start, b[0].end), ((5.0, 0.0, 40.0), (20.0, 0.0, 40.0)))  # over, then down
        self.assertEqual(b[1].end, (20.0, 0.0, 2.0))

    def test_drilling(self):
        cycle = nc.DrillCycle(
            peck_mm=2.0, feed_mm_min=100.0, clearance_mm=2.0, second_clearance_mm=10.0, decrement_mm=0.0,
            min_peck_mm=0.0, upper_stop_mm=0.0, lower_stop_mm=0.0, chip_break_mm=0.0, chip_retract_mm=0.0,
            dwell_s=0.0, start_mm=0.0, preposition_feed_mm_min=0.0,
            holes=(nc.DrillHole(10.0, 0.0, 0.0, -8.0), nc.DrillHole(20.0, 0.0, -2.0, -5.0)),
        )  # fmt: skip
        op = nc.Operation(nc.DRILLING, "Drilling", NC_3, (), cycle)
        elements = machine.Machine(40.0, 100.0).elements(op)
        ends = [e.end for e in elements]
        self.assertEqual(ends[:4], [(10.0, 0.0, 100.0), (10.0, 0.0, 2.0), (10.0, 0.0, -8.0), (10.0, 0.0, 10.0)])
        self.assertEqual(ends[4:], [(20.0, 0.0, 10.0), (20.0, 0.0, 0.0), (20.0, 0.0, -7.0), (20.0, 0.0, 8.0)])
        self.assertEqual(elements[2].kind, nc.LINE)


if __name__ == "__main__":
    unittest.main()
