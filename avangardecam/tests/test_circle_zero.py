# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Move 0-Point > Select circle tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_circle_zero   (from the add-on's folder)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import unittest

from avangardecam.model import circle_zero, frame

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

End = circle_zero.End

# a setup on the top of a part, Z0 at 50 mm
TOP = frame.Frame((0.0, 0.0, 50.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# a setup on the front: X to the right, Y up (the part's Z), Z towards the viewer
FRONT = frame.Frame((0.0, -10.0, 6.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))


class TestModel(unittest.TestCase):
    def test_to_point(self):
        self.assertEqual(circle_zero.to_point(TOP, (0.0, -100.0, 0.0)), (0.0, -100.0, -50.0))
        self.assertEqual(circle_zero.to_point(TOP, (0.0, 0.0, 50.0)), (0.0, 0.0, 0.0), "already there")
        # the front setup: its Y is the part's Z, its Z the part's -Y
        self.assertEqual(circle_zero.to_point(FRONT, (5.0, -13.0, 8.0)), (5.0, 2.0, 3.0))
        self.assertEqual(circle_zero.to_point(TOP, (1e-12, 0.0, 50.0)), (0.0, 0.0, 0.0), "no rounding noise")

    def test_mouth_is_a_free_end(self):
        # a blind hole: its floor has the part beyond it
        self.assertEqual(circle_zero.mouth([End(True, 0.0), End(False, 200.0)]), 0)
        self.assertEqual(circle_zero.mouth([End(False, 0.0), End(True, 200.0)]), 1, "however deep")
        self.assertEqual(circle_zero.mouth([End(None, 0.0), End(True, 50.0)]), 1, "not known is not free")
        self.assertIsNone(circle_zero.mouth([End(False, 0.0), End(False, 0.0)]), "inside the part")
        self.assertIsNone(circle_zero.mouth([End(None, 0.0), End(None, 0.0)]))

    def test_mouth_to_the_outside(self):
        # a bore Ø600 from the end of a tube into a hollow inside it: free
        # both ways, but the hollow end has the whole tube around its way out
        self.assertEqual(circle_zero.mouth([End(True, 0.0), End(True, 1720.0, picked=True)], 600.0), 0)
        self.assertEqual(circle_zero.mouth([End(True, 0.0), End(True, 601.0, picked=True)], 600.0), 0)

    def test_mouth_alike(self):
        # a hole through a plate: the end clicked, else the nearer one
        self.assertEqual(circle_zero.mouth([End(True, 0.0, distance=1.0), End(True, 0.0, picked=True, distance=11.0)]), 1)  # fmt: skip
        self.assertEqual(circle_zero.mouth([End(True, 0.0, distance=1.0), End(True, 0.005, distance=11.0)]), 0)
        # a countersink 3 deep on a hole Ø6: no more than its diameter
        self.assertEqual(circle_zero.mouth([End(True, 0.0, distance=9.0), End(True, 3.0, picked=True)], 6.0), 1)
        self.assertEqual(circle_zero.mouth([End(True, 0.0, distance=9.0), End(True, 3.0, distance=1.0)], 6.0), 1)
        self.assertEqual(circle_zero.mouth([End(True, 0.0, distance=9.0), End(True, 7.0, picked=True)], 6.0), 0)
        self.assertEqual(circle_zero.mouth([End(True, 0.0, distance=9.0), End(True, 0.0, distance=3.0)]), 1)
        self.assertEqual(circle_zero.mouth([End(True, 0.0), End(True, 0.0)]), 1, "no click: the upper end")

    def test_side(self):
        self.assertEqual(circle_zero.side(0, 12), circle_zero.OUT, "nothing along the axis")
        self.assertEqual(circle_zero.side(12, 6), circle_zero.IN)
        self.assertEqual(circle_zero.side(12, 12), circle_zero.UNKNOWN)

    def test_along_z(self):
        self.assertTrue(circle_zero.along_z(TOP, (0.0, 0.0, 2.0)))
        self.assertTrue(circle_zero.along_z(TOP, (0.0, 0.0, -1.0)), "either way")
        self.assertFalse(circle_zero.along_z(TOP, (0.0, -1.0, 0.0)))
        self.assertTrue(circle_zero.along_z(FRONT, (0.0, 1.0, 0.0)))
        self.assertFalse(circle_zero.along_z(TOP, (0.0, 0.0, 0.0)))

    def test_diameter_text(self):
        self.assertEqual(circle_zero.diameter_text(300.0), "Ø600")
        self.assertEqual(circle_zero.diameter_text(6.25), "Ø12.5")
        self.assertEqual(circle_zero.diameter_text(2.0000000001), "Ø4")


def _tube():
    """A tube along Y as the test part of a horizontal borer (the Soraluce
    test part, smaller): Ø100 from Y-100 to Y100, hollow inside (Ø70 from
    Y-70 to Y70), a bore Ø40 through both ends into the hollow, four holes
    Ø10 15 deep in the end at Y-100 (on a circle Ø70) and a pin Ø8 standing
    on a flat on its top (Z40, Y40 to Y80; the pin's top at Z46)."""
    import Part

    V = FreeCAD.Vector
    tube = Part.makeCylinder(50, 200, V(0, -100, 0), V(0, 1, 0))
    tube = tube.cut(Part.makeBox(120, 40, 20, V(-60, 40, 40)))
    tube = tube.cut(Part.makeCylinder(35, 140, V(0, -70, 0), V(0, 1, 0)))
    tube = tube.cut(Part.makeCylinder(20, 202, V(0, -101, 0), V(0, 1, 0)))
    for x, z in ((35, 0), (0, 35), (-35, 0), (0, -35)):
        tube = tube.cut(Part.makeCylinder(5, 16, V(x, -101, z), V(0, 1, 0)))
    tube = tube.fuse(Part.makeCylinder(4, 6, V(0, 60, 40), V(0, 0, 1)))
    return tube.removeSplitter()


def _plate():
    """A plate 40 x 20 x 12 (Z0 to Z12): a hole Ø6 through it at X-10 with a
    countersink Ø12 at the top, and a closed hollow Ø4 inside it at X10
    (Z3 to Z6)."""
    import Part

    V = FreeCAD.Vector
    plate = Part.makeBox(40, 20, 12, V(-20, -10, 0))
    plate = plate.cut(Part.makeCylinder(3, 14, V(-10, 0, -1), V(0, 0, 1)))
    plate = plate.cut(Part.makeCone(3, 6, 3, V(-10, 0, 9), V(0, 0, 1)))
    plate = plate.cut(Part.makeCylinder(2, 3, V(10, 0, 3), V(0, 0, 1)))
    return plate.removeSplitter()


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestEngine(unittest.TestCase):
    """The first setup on the tube has its zero point on the top, in the middle."""

    def setUp(self):
        from avangardecam.engine import circle_zero as engine
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry
        from avangardecam.engine import move_zero

        self.cam, self.geometry, self.engine, self.move_zero = cam, geometry, engine, move_zero
        self.doc = FreeCAD.newDocument("AvangardeCamCircleZero")
        self.part = self.doc.addObject("Part::Feature", "Tube")
        self.part.Shape = _tube()
        self.plate = self.doc.addObject("Part::Feature", "Plate")
        self.plate.Shape = _plate()
        self.doc.recompute()
        self.job = cam.ensure_job(self.doc, [self.part])

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def edge(self, radius, centre, obj=None):
        """The round edge of radius about centre."""
        for i, e in enumerate((obj or self.part).Shape.Edges, start=1):
            curve = e.Curve
            if (
                type(curve).__name__ == "Circle"
                and abs(curve.Radius - radius) < 1e-6
                and (curve.Center - FreeCAD.Vector(*centre)).Length < 1e-6
            ):
                return "Edge{}".format(i)
        raise AssertionError("no edge R{} about {}".format(radius, centre))

    def wall(self, radius, at, beside=None, obj=None):
        """The cylinder face of radius whose axis goes through the point at
        (of several, the one reaching beside: a point along the axis)."""
        point = FreeCAD.Vector(*at)
        found = []
        for i, f in enumerate((obj or self.part).Shape.Faces, start=1):
            surface = f.Surface
            if type(surface).__name__ != "Cylinder" or abs(surface.Radius - radius) > 1e-6:
                continue
            off = point - surface.Center
            if (off - surface.Axis * off.dot(surface.Axis)).Length < 1e-6:
                found.append((i, f))
        if beside is not None:
            found = [(i, f) for i, f in found if f.distToShape(Part_vertex(beside))[0] < radius + 1e-6]
        if len(found) != 1:
            raise AssertionError("{} walls R{} through {}".format(len(found), radius, at))
        return "Face{}".format(found[0][0])

    def assertVector(self, actual, expected, msg=None):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=6, msg=msg)

    def assertCircle(self, found, centre, out, radius=None, msg=None):
        self.assertVector(found.centre, centre, msg)
        self.assertVector(found.out, out, msg)
        if radius is not None:
            self.assertAlmostEqual(found.radius, radius, msg=msg)

    def zero(self):
        return self.cam.zero(self.job)

    def test_the_setup(self):
        self.assertVector(self.zero().Base, (0, 0, 50), "on the top, in the middle")
        self.assertVector(self.geometry.tool_axis(self.zero()), (0, 0, 1))

    def test_the_bore_from_its_end(self):
        found = self.engine.circle(self.part, self.edge(20, (0, -100, 0)))
        self.assertCircle(found, (0, -100, 0), (0, -1, 0), 20.0, "out of the end of the tube")
        self.assertEqual(self.engine.shift(self.job, found), (0.0, -100.0, -50.0))
        self.assertEqual(self.engine.turn(self.job, found), (90.0, 0.0, 0.0), "about X: Z onto -Y")
        self.assertFalse(self.engine.along_z(self.job, found))
        # its other end looks the other way
        other = self.engine.circle(self.part, self.edge(20, (0, 100, 0)))
        self.assertCircle(other, (0, 100, 0), (0, 1, 0))
        self.assertEqual(self.engine.turn(self.job, other), (-90.0, 0.0, 0.0))

    def test_the_far_edge_of_the_bore(self):
        """A click into the bore catches its edge where it opens into the
        hollow: the bore's mouth on the end of the tube, Z out of the tube
        (not into the hollow)."""
        found = self.engine.circle(self.part, self.edge(20, (0, -70, 0)))
        self.assertCircle(found, (0, -100, 0), (0, -1, 0), 20.0)
        found = self.engine.circle(self.part, self.edge(20, (0, 70, 0)))
        self.assertCircle(found, (0, 100, 0), (0, 1, 0))

    def test_the_bore_by_its_wall(self):
        wall = self.wall(20, (0, 0, 0), beside=(0, -85, 0))
        for near in ((0, -95, 20), (0, -72, -20), None):
            near = None if near is None else FreeCAD.Vector(*near)
            self.assertCircle(self.engine.circle(self.part, wall, near), (0, -100, 0), (0, -1, 0), 20.0, near)
        far = self.engine.circle(self.part, self.wall(20, (0, 0, 0), beside=(0, 85, 0)), FreeCAD.Vector(0, 72, 0))
        self.assertCircle(far, (0, 100, 0), (0, 1, 0))

    def test_a_blind_hole(self):
        mouth = ((35, -100, 0), (0, -1, 0))
        self.assertCircle(self.engine.circle(self.part, self.edge(5, (35, -100, 0))), *mouth)
        self.assertCircle(self.engine.circle(self.part, self.edge(5, (35, -85, 0))), *mouth, msg="its floor's edge")
        for near in ((30, -86, 0), (30, -99, 0)):
            found = self.engine.circle(self.part, self.wall(5, (35, 0, 0)), FreeCAD.Vector(*near))
            self.assertCircle(found, *mouth, msg="its wall, clicked at {}".format(near))

    def test_a_pin(self):
        top = ((0, 60, 46), (0, 0, 1))
        self.assertCircle(self.engine.circle(self.part, self.edge(4, (0, 60, 46))), *top, radius=4.0)
        self.assertCircle(self.engine.circle(self.part, self.edge(4, (0, 60, 40))), *top, msg="its foot's edge")
        found = self.engine.circle(self.part, self.wall(4, (0, 60, 0)), FreeCAD.Vector(4, 60, 41))
        self.assertCircle(found, *top, msg="its wall, clicked by its foot")
        self.assertTrue(self.engine.along_z(self.job, found))
        self.assertEqual(self.engine.turn(self.job, found), (0.0, 0.0, 0.0), "the tool stands on it already")
        self.assertEqual(self.engine.shift(self.job, found), (0.0, 60.0, -4.0))

    def test_a_hole_through_a_plate(self):
        """Both ends free and alike: the end clicked."""
        top, bottom = ((-10, 0, 9), (0, 0, 1)), ((-10, 0, 0), (0, 0, -1))
        self.assertCircle(self.engine.circle(self.plate, self.edge(3, (-10, 0, 0), self.plate)), *bottom)
        self.assertCircle(self.engine.circle(self.plate, self.edge(3, (-10, 0, 9), self.plate)), *top)
        wall = self.wall(3, (-10, 0, 0), obj=self.plate)
        self.assertCircle(self.engine.circle(self.plate, wall, FreeCAD.Vector(-7, 0, 1)), *bottom)
        self.assertCircle(self.engine.circle(self.plate, wall, FreeCAD.Vector(-7, 0, 8)), *top)

    def test_a_countersink(self):
        """Its edge is a circle of no wall: out the free way."""
        found = self.engine.circle(self.plate, self.edge(6, (-10, 0, 12), self.plate))
        self.assertCircle(found, (-10, 0, 12), (0, 0, 1), 6.0)

    def test_inside_the_part(self):
        """A closed hollow: no end is free; the end clicked, the material
        around it decides."""
        found = self.engine.circle(self.plate, self.edge(2, (10, 0, 6), self.plate))
        self.assertVector(found.centre, (10, 0, 6))
        self.assertVector(found.out, (0, 0, -1), "into the hollow, where there is no material")
        found = self.engine.circle(self.plate, self.wall(2, (10, 0, 0), obj=self.plate), FreeCAD.Vector(12, 0, 3.5))
        self.assertVector(found.centre, (10, 0, 3))
        self.assertVector(found.out, (0, 0, 1))

    def test_not_round(self):
        from avangardecam.engine import ProjectError

        flat = next(
            "Face{}".format(i) for i, f in enumerate(self.part.Shape.Faces, start=1) if f.findPlane() is not None
        )
        line = next(
            "Edge{}".format(i)
            for i, e in enumerate(self.part.Shape.Edges, start=1)
            if type(e.Curve).__name__ == "Line"
        )
        for sub in (flat, line, "Vertex1"):
            self.assertFalse(self.engine.is_round(self.part, sub), sub)
            with self.assertRaisesRegex(ProjectError, "round", msg=sub):
                self.engine.circle(self.part, sub)
        self.assertTrue(self.engine.is_round(self.part, self.edge(20, (0, -100, 0))))
        self.assertTrue(self.engine.is_round(self.part, self.wall(5, (35, 0, 0))))

    def test_move_onto_the_bore_and_drill_the_end(self):
        """The zero point in the middle of the bore's end, Z out of it: the
        holes in the end run along the tool and open towards it."""
        hole = self.wall(5, (0, 0, 35))
        with self.assertRaisesRegex(self.cam.ProjectError, "tool axis"):
            self.cam.model_holes(self.job, self.part, [hole])
        found = self.engine.circle(self.part, self.edge(20, (0, -70, 0)))
        self.move_zero.move(self.job, self.engine.shift(self.job, found), self.engine.turn(self.job, found))
        self.assertVector(self.zero().Base, (0, -100, 0))
        self.assertVector(self.geometry.tool_axis(self.zero()), (0, -1, 0))
        holes = self.cam.model_holes(self.job, self.part, [hole])
        self.assertEqual(len(holes), 1)
        self.assertAlmostEqual(holes[0].depth.depth_mm, -15.0, places=6)
        self.assertFalse(holes[0].depth.through)
        # the zero point is in the middle of the bore: it is a circle there now
        again = self.engine.circle(self.part, self.edge(20, (0, -100, 0)))
        self.assertEqual(self.engine.shift(self.job, again), (0.0, 0.0, 0.0))
        self.assertEqual(self.engine.turn(self.job, again), (0.0, 0.0, 0.0))
        self.assertTrue(self.engine.along_z(self.job, again))

    def test_from_a_turned_zero_point(self):
        """The circle's middle and turn are from the zero point as it stands."""
        self.move_zero.move(self.job, (0.0, 0.0, 0.0), (0.0, 0.0, 90.0))  # X is the part's Y now
        found = self.engine.circle(self.part, self.edge(20, (0, -100, 0)))
        self.assertEqual(self.engine.shift(self.job, found), (-100.0, 0.0, -50.0))
        place = self.move_zero.target(self.job, self.engine.shift(self.job, found), self.engine.turn(self.job, found))
        self.assertVector(place.Base, (0, -100, 0))
        self.assertVector(self.geometry.tool_axis(place), (0, -1, 0))


def Part_vertex(point):
    import Part

    return Part.Vertex(FreeCAD.Vector(*point))


if __name__ == "__main__":
    unittest.main()
