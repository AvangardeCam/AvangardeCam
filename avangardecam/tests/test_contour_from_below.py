# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Contours on a sketch facing away from the tool: a face of the part's
bottom used in a setup from the top. The sketch has no zero point of its
own; its lines are where they are, seen from the tool's side. Run inside
FreeCADCmd (avangardecam/tests/run.py)."""

import unittest

import FreeCAD

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.model import library, nc, operations
from avangardecam.tests import test_engine
from avangardecam.tests.test_model import LIBRARY


def _area(points):
    """Signed area of a closed polygon in XY: positive counter-clockwise
    seen from +Z (from the tool)."""
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))


class TestContourFromBelow(unittest.TestCase):
    """The part 40 x 20 x 12 (Z 0..12), the setup's zero on its top: the
    bottom at Z-12, its outline the same as the top's."""

    def setUp(self):
        self.doc = FreeCAD.newDocument("AvangardeCamFromBelow")
        box = self.doc.addObject("Part::Box", "Part")
        box.Length, box.Width, box.Height = 40, 20, 12
        box.Placement.Base = FreeCAD.Vector(-20, -10, 0)
        self.doc.recompute()
        self.part = box
        self.job = cam.ensure_job(self.doc, [box])
        variant = next(e for e in library.load(LIBRARY) if e.number == 21 and e.workpiece_material == "RVS")
        self.tc = cam.add_tool(self.job, variant)
        self.top = geometry.extract_boundary(self.doc, [box], box, self.face((0, 0, 1)))
        self.bottom = geometry.extract_boundary(self.doc, [box], box, self.face((0, 0, -1)))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def face(self, normal):
        return test_engine.TestEngine.face(self, self.part, normal)

    def cutting(self, op):
        """(x, y, z) of the cutting moves of the path."""
        moves = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3") and "X" in c.Parameters]
        return [(c.Parameters["X"], c.Parameters["Y"], c.Parameters.get("Z")) for c in moves]

    def test_bottom_fits_contours_only(self):
        self.assertFalse(cam.sketch_fits(self.job, self.bottom), "drilling still needs a sketch facing the tool")
        self.assertTrue(cam.sketch_faces_away(self.job, self.bottom))
        self.assertTrue(cam.contour_fits(self.job, self.bottom))
        self.assertEqual(cam.setups_for_contour(self.doc, self.bottom), [self.job])
        side = geometry.extract_boundary(self.doc, [self.part], self.part, self.face((0, -1, 0)))
        self.assertFalse(cam.contour_fits(self.job, side), "a side face's lines are not across the tool")
        with self.assertRaises(cam.ProjectError):
            cam.add_contour(self.job, side, operations.Contour(-1.0), self.tc)

    def test_bottom_from_the_top(self):
        op = cam.add_contour(self.job, self.bottom, operations.Contour(-1.0), self.tc)
        self.assertEqual([round(z, 6) for z in cam.contour_planes(op)], [-12.0], "the bottom's lines at Z-12")
        self.assertEqual(cam.contour_depths(op), (-12.0, -13.0), "relative: 1 mm below them")
        cuts = self.cutting(op)
        self.assertEqual({round(z, 6) for _x, _y, z in cuts}, {-13.0})
        self.assertAlmostEqual(max(abs(x) for x, _y, _z in cuts), 20.0, msg="tool centre on the outline")
        self.assertAlmostEqual(max(abs(y) for _x, y, _z in cuts), 10.0)
        fixed = cam.add_contour(self.job, self.bottom, operations.Contour(-12.5, relative=False), self.tc)
        self.assertEqual({round(z, 6) for _x, _y, z in self.cutting(fixed)}, {-12.5}, "from the zero point")

    def test_compensation_seen_from_the_tool(self):
        """RL keeps the tool left of the lines seen from the tool, also on
        the bottom's lines: inside the outline when they run counter-
        clockwise seen from the top, outside when clockwise."""
        for sketch in (self.top, self.bottom):
            op = cam.add_contour(self.job, sketch, operations.Contour(-1.0, operations.LEFT, operations.NONE), self.tc)
            centre = [(x, y) for x, y, _z in self.cutting(op)]
            inside = max(abs(x) for x, _y in centre) < 20.0 - 1e-6
            self.assertEqual(inside, _area(centre) > 0.0, "{}: left of the lines seen from the tool".format(sketch.Label))
            program = [(m.x, m.y) for m in cam.nc_moves(op) if m.kind == nc.LINE and m.compensation == nc.LEFT]
            self.assertAlmostEqual(max(abs(x) for x, _y in program), 20.0, msg="the program has the lines with RL")
            self.assertEqual(_area(program) > 0.0, _area(centre) > 0.0, "the program runs as the tool centre")

    def test_arcs_seen_from_the_tool(self):
        """The approach arc on the left of the lines is on their left seen
        from the top, on the top's and on the bottom's lines: it turns the
        same way onto them, and its centre (where the tool goes down) is
        left of the first line."""
        turns = []
        for sketch in (self.top, self.bottom):
            op = cam.add_contour(self.job, sketch, operations.Contour(-1.0, operations.OFF, operations.ARC, 4.5), self.tc)
            moves = [m for m in cam.nc_moves(op) if m.kind in (nc.LINE, nc.ARC)]
            first = next(i for i, m in enumerate(moves) if m.kind == nc.ARC)
            arc, line = moves[first], moves[first + 1]  # onto the lines, then along the first one
            turns.append(arc.clockwise)
            along = (line.x - arc.x, line.y - arc.y)
            to_centre = (arc.center[0] - arc.x, arc.center[1] - arc.y)
            self.assertGreater(along[0] * to_centre[1] - along[1] * to_centre[0], 0.0, "{}: the arc on the left".format(sketch.Label))  # fmt: skip
        self.assertEqual(turns[0], turns[1])

    def test_turning_the_setup_round(self):
        """A setup with a contour on the top's lines can turn round onto the
        bottom: the top's sketch then faces away from its tool."""
        op = cam.add_contour(self.job, self.top, operations.Contour(-1.0), self.tc)
        cam.set_zero(self.job, geometry.zero_on_face([self.part], self.part, self.face((0, 0, -1))))
        helper = cam.helper_objects(op)[0]
        self.assertTrue(helper.Flipped)
        self.assertEqual([round(z, 6) for z in cam.contour_planes(op)], [-12.0])
        cuts = self.cutting(op)
        self.assertAlmostEqual(max(abs(x) for x, _y, _z in cuts), 20.0)
        cam.set_zero(self.job, geometry.zero_on_face([self.part], self.part, self.face((0, 0, 1))))
        self.assertFalse(cam.helper_objects(op)[0].Flipped, "facing its tool again")
        with self.assertRaises(cam.ProjectError):
            cam.set_zero(self.job, geometry.zero_on_face([self.part], self.part, self.face((0, -1, 0))))


if __name__ == "__main__":
    unittest.main()
