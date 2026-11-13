# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Measuring tests (engine.measure). Run inside FreeCADCmd, see
avangardecam/tests/run.py."""

import unittest

import FreeCAD

from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.engine import measure


class TestMeasure(unittest.TestCase):
    def setUp(self):
        """A block 60 × 30 × 20 (0..60, 0..30, 0..20) with a Ø6 hole through it
        at X10 Y15 and a Ø8 hole 5 deep at X40 Y15; the setup's zero in the
        middle of its top (X30 Y15 Z20)."""
        self.doc = FreeCAD.newDocument("AvangardeCamMeasure")
        box = self.doc.addObject("Part::Box", "Block")
        box.Length, box.Width, box.Height = 60, 30, 20
        through = self.doc.addObject("Part::Cylinder", "Through")
        through.Radius, through.Height = 3, 30
        through.Placement.Base = FreeCAD.Vector(10, 15, -5)
        blind = self.doc.addObject("Part::Cylinder", "Blind")
        blind.Radius, blind.Height = 4, 10
        blind.Placement.Base = FreeCAD.Vector(40, 15, 15)
        holes = self.doc.addObject("Part::MultiFuse", "Holes")
        holes.Shapes = [through, blind]
        part = self.doc.addObject("Part::Cut", "Part")
        part.Base, part.Tool = box, holes
        self.doc.recompute()
        self.part = part
        self.job = cam.ensure_job(self.doc)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def face(self, normal):
        """The flat face of the part whose outward normal is normal."""
        shape = self.part.Shape
        for i, f in enumerate(shape.Faces, start=1):
            if f.findPlane() is not None and geometry.outward_normal(shape, f).getAngle(FreeCAD.Vector(*normal)) < 1e-9:
                return "Face{}".format(i)
        raise AssertionError("no face with normal {}".format(normal))

    def wall(self, radius):
        return next(
            "Face{}".format(i)
            for i, f in enumerate(self.part.Shape.Faces, start=1)
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - radius) < 1e-9
        )

    def rim(self, radius, z):
        return next(
            "Edge{}".format(i)
            for i, e in enumerate(self.part.Shape.Edges, start=1)
            if e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Radius - radius) < 1e-9 and abs(e.Curve.Center.z - z) < 1e-9
        )

    def edge_along_x(self, y, z):
        return next(
            "Edge{}".format(i)
            for i, e in enumerate(self.part.Shape.Edges, start=1)
            if e.Curve.TypeId == "Part::GeomLine"
            and abs(e.Vertexes[0].Point.y - y) < 1e-9
            and abs(e.Vertexes[0].Point.z - z) < 1e-9
            and abs(e.Vertexes[1].Point.y - y) < 1e-9
            and abs(e.Vertexes[1].Point.z - z) < 1e-9
        )

    def local(self, *names):
        reading = measure.local(cam.zero(self.job), [(self.part, n) if isinstance(n, str) else n for n in names])
        rows = {r.label: (round(r.value, 9) + 0.0 if not isinstance(r.value, str) else r.value) for r in reading.rows}
        return reading.title, rows

    def test_from_zero(self):
        def extents(*elements):
            return [tuple(round(v, 9) + 0.0 for v in axis) for axis in measure.from_zero(cam.zero(self.job), elements)]

        top, front = self.face((0, 0, 1)), self.face((0, -1, 0))
        self.assertEqual(extents((self.part, top)), [(-30, 30), (-15, 15), (0, 0)])
        self.assertEqual(extents((self.part, top), (self.part, front)), [(-30, 30), (-15, 15), (-20, 0)], "together")
        self.assertEqual(extents((self.part, "")), [(-30, 30), (-15, 15), (-20, 0)], "the whole model")
        # the hole's wall to its outermost points, not to the box of a triangulation
        self.assertEqual(extents((self.part, self.wall(3))), [(-23, -17), (-3, 3), (-20, 0)])
        cam.rotate_zero(self.job, 90)  # the new X is the old Y
        self.assertEqual(extents((self.part, self.wall(3))), [(-3, 3), (17, 23), (-20, 0)])
        with self.assertRaises(ProjectError):
            measure.from_zero(cam.zero(self.job), [])

    def test_one_face(self):
        self.assertEqual(self.local(self.face((0, 0, 1))), ("Flat face", {"Along X": 60, "Along Y": 30, "At Z": 0}))
        self.assertEqual(self.local(self.face((0, -1, 0))), ("Flat face", {"Along X": 60, "Along Z": 20, "At Y": -15}))
        self.assertEqual(self.local(self.face((1, 0, 0))), ("Flat face", {"Along Y": 30, "Along Z": 20, "At X": 30}))
        cam.rotate_zero(self.job, 90)
        self.assertEqual(self.local(self.face((0, 0, 1))), ("Flat face", {"Along X": 30, "Along Y": 60, "At Z": 0}))

    def test_one_hole(self):
        through = {"Diameter Ø": 6, "Centre X": -20, "Centre Y": 0, "Centre Z": 0, "Depth": 20, "Through": "yes"}
        self.assertEqual(self.local(self.wall(3)), ("Hole", through))
        self.assertEqual(self.local(self.rim(3, 20)), ("Hole", through), "by its round edge")
        blind = {"Diameter Ø": 8, "Centre X": 10, "Centre Y": 0, "Centre Z": 0, "Depth": 5, "Through": "no"}
        self.assertEqual(self.local(self.rim(4, 15)), ("Hole", blind), "by the edge of its floor")

    def test_two_holes(self):
        title, rows = self.local(self.wall(3), self.rim(4, 20))
        self.assertEqual(title, "Two holes")
        self.assertEqual(rows, {"Centre distance": 30, "Between nearest points": 23, "Nearest points along X": 23, "Nearest points along Y": "overlap", "ΔX": 30, "ΔY": 0, "ΔZ": 0, "Ø 1": 6, "Ø 2": 8})
        self.assertEqual(self.local(self.wall(4), self.wall(3))[1]["ΔX"], -30, "from the first clicked")

    def side_holes(self):
        """A second block 60 × 30 × 20 at X200 with two holes along Y through
        its front (Y0) and back: Ø4 at X210 Z12 and Ø6 at X240 Z4."""
        block = self.doc.addObject("Part::Box", "SideBlock")
        block.Length, block.Width, block.Height = 60, 30, 20
        block.Placement.Base = FreeCAD.Vector(200, 0, 0)
        cut = block
        for x, z, r in ((210, 12, 2), (240, 4, 3)):
            hole = self.doc.addObject("Part::Cylinder", "SideHole")
            hole.Radius, hole.Height = r, 40
            hole.Placement = FreeCAD.Placement(FreeCAD.Vector(x, -5, z), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90))
            cut = self.doc.addObject("Part::Cut", "Side")
            cut.Base, cut.Tool = block, hole
            block = cut
        self.doc.recompute()
        return cut

    def side_rim(self, obj, radius, y):
        return next(
            "Edge{}".format(i)
            for i, e in enumerate(obj.Shape.Edges, start=1)
            if e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Radius - radius) < 1e-9 and abs(e.Curve.Center.y - y) < 1e-9
        )

    def test_two_holes_in_a_side_face(self):
        side = self.side_holes()
        reading = measure.local(cam.zero(self.job), [(side, self.side_rim(side, 2, 0)), (side, self.side_rim(side, 3, 0))])
        rows = {r.label: round(r.value, 9) + 0.0 for r in reading.rows}
        self.assertEqual(reading.note, measure._FACE_AXES, "in the front face's own axes")
        across = round((30**2 + 8**2) ** 0.5, 9)
        self.assertEqual(rows, {
            "Centre distance": across, "Between nearest points": round(across - 5, 9),
            "Nearest points along X": 25, "Nearest points along Y": 3,  # the face's Y is the part's Z
            "ΔX": 30, "ΔY": -8, "ΔZ": 0, "Ø 1": 4, "Ø 2": 6,
        })  # fmt: skip
        back = measure.local(cam.zero(self.job), [(side, self.side_rim(side, 2, 30)), (side, self.side_rim(side, 3, 30))])
        self.assertEqual(round(back.rows[4].value, 9), -30, "seen from the back X runs the other way")

    def test_two_circles_not_parallel(self):
        side = self.side_holes()
        title, rows = self.local(self.wall(3), (side, self.side_rim(side, 2, 0)))
        self.assertEqual(title, "Two circles")
        self.assertNotIn("Between nearest points", rows)
        # the side circle (Ø4 at X210 Y0 Z12, axis Y) and the top of the Ø6 hole (X10 Y15 Z20, axis Z)
        side_circle = FreeCAD.Vector(210, 0, 12)
        nearest_on_top = FreeCAD.Vector(13, 15, 20)  # towards the side circle along X
        self.assertLess(rows["Shortest distance in space"], (side_circle - nearest_on_top).Length)
        self.assertGreater(rows["Shortest distance in space"], 190)
        # in the setup's axes (the first is a hole of its top): Ø6 at X10 Y15, the side circle at X210 Y0
        self.assertEqual((rows["Nearest points along X"], rows["Nearest points along Y"]), (195, 12))

    def test_two_faces(self):
        top, bottom, front = self.face((0, 0, 1)), self.face((0, 0, -1)), self.face((0, -1, 0))
        self.assertEqual(self.local(top, bottom), ("Two parallel faces", {"Distance along Z": 20}))
        self.assertEqual(self.local(front, top), ("Two faces", {"Angle": 90, "Shortest distance": 0}))
        floor = next(
            "Face{}".format(i)
            for i, f in enumerate(self.part.Shape.Faces, start=1)
            if f.findPlane() is not None and abs(f.BoundBox.ZMax - 15) < 1e-9 and f.BoundBox.ZLength < 1e-9
        )
        self.assertEqual(self.local(top, floor), ("Two parallel faces", {"Distance along Z": 5}), "the blind hole's floor")

    def test_face_and_hole(self):
        left = self.face((-1, 0, 0))
        rows = {"Face to centre along X": 10, "Face to nearest side along X": 7, "Face to far side along X": 13, "Diameter Ø": 6}
        self.assertEqual(self.local(left, self.wall(3)), ("Face and hole", rows))
        self.assertEqual(self.local(self.wall(3), left), ("Face and hole", rows), "either order")
        back = self.face((0, 1, 0))
        self.assertEqual(self.local(back, self.rim(4, 20))[1]["Face to centre along Y"], 15)
        self.assertEqual(
            self.local(self.face((0, 0, -1)), self.wall(4)),
            ("Face and hole", {"Face to centre along the axis (Z)": 20, "Diameter Ø": 8}),
            "the bottom to the blind hole's top",
        )

    def test_edges(self):
        self.assertEqual(self.local(self.edge_along_x(0, 20)), ("Straight edge", {"Length": 60, "Along": "X"}))
        self.assertEqual(self.local(self.edge_along_x(0, 20), self.edge_along_x(30, 20))[1], {"Shortest distance": 30})

    def test_sketch_circle(self):
        top = self.face((0, 0, 1))
        sketch = geometry.extract_boundary(self.doc, [self.part], self.part, top)
        circle = next(
            "Edge{}".format(i)
            for i, e in enumerate(sketch.Shape.Edges, start=1)
            if e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Radius - 3) < 1e-9
        )
        self.assertEqual(
            self.local((sketch, circle)),
            ("Circle", {"Diameter Ø": 6, "Centre X": -20, "Centre Y": 0, "Centre Z": 0, "Axis": "Z"}),
        )

    def test_refuses(self):
        top = self.face((0, 0, 1))
        with self.assertRaises(ProjectError):
            self.local(top, top, top)
        with self.assertRaises(ProjectError):
            self.local("")  # the whole model
        with self.assertRaises(ProjectError):
            measure.local(cam.zero(self.job), [])
