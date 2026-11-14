# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Engine tests: model <-> FreeCAD CAM translation. Run inside FreeCADCmd,
see avangardecam/tests/run.py."""

import math
import unittest

import FreeCAD

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.model import library, operations, stock
from avangardecam.tests.test_model import LIBRARY


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("AvangardeCamTest")
        box = self.doc.addObject("Part::Box", "Part")
        box.Length, box.Width, box.Height = 40, 20, 12
        box.Placement.Base = FreeCAD.Vector(-20, -10, 0)
        self.doc.recompute()
        self.part = box
        self.library = library.load(LIBRARY)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def variant(self, number, material):
        return next(
            e for e in self.library if e.number == number and e.workpiece_material == material
        )

    def assertBounds(self, actual, expected, msg=None):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=6, msg=msg)

    def assertVector(self, actual, expected):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=9)

    def assertPlacement(self, place, origin, tool_axis):
        self.assertVector(place.Base, origin)
        self.assertVector(geometry.tool_axis(place), tool_axis)

    def face(self, obj, normal):
        """Name of the flat face of obj whose outward normal is normal."""
        normal = FreeCAD.Vector(*normal)
        for i, f in enumerate(obj.Shape.Faces, start=1):
            if f.findPlane() is not None and geometry.outward_normal(obj.Shape, f).getAngle(normal) < 1e-9:
                return "Face{}".format(i)
        raise AssertionError("no face with normal {}".format(normal))

    def holed_part(self):
        """The part with a 6 mm hole through it, at x = -10, y = 0."""
        hole = self.doc.addObject("Part::Cylinder", "Hole")
        hole.Radius, hole.Height = 3, 30
        hole.Placement.Base = FreeCAD.Vector(-10, 0, -5)
        cut = self.doc.addObject("Part::Cut", "Body")
        cut.Base, cut.Tool = self.part, hole
        self.doc.recompute()
        return cut

    def test_models_without_job(self):
        self.assertEqual(cam.models(self.doc), [self.part])
        self.assertIsNone(cam.find_job(self.doc))

    def leftovers(self):
        """Objects that belong to nothing: not a model, not in a job."""
        return [o.Name for o in self.doc.Objects if o.TypeId.startswith(("PartDesign::", "Sketcher::"))]

    def test_job_has_default_stock_and_no_tools(self):
        job = cam.ensure_job(self.doc)
        self.assertEqual(self.leftovers(), [], "FreeCAD's default end mill leaves no shape body")
        self.assertIs(cam.ensure_job(self.doc), job, "one job per project")
        self.assertEqual(cam.models(self.doc), [self.part], "originals, not the job's clones")
        self.assertEqual(cam.project_tools(job), [], "FreeCAD's default end mill is removed")
        self.assertEqual(cam.stock(job), stock.BoxStock())
        # zero point on top of the part, in the middle: the job's coordinates
        self.assertEqual(job.Label, "Setup 1")
        self.assertPlacement(cam.zero(job), (0, 0, 12), (0, 0, 1))
        self.assertBounds(cam.stock_bounds(job), (-21, -11, -12, 21, 11, 1))

    def test_stock_allowance_round_trip(self):
        job = cam.ensure_job(self.doc)
        wanted = stock.BoxStock(0, 0, 0, 0, 0, 0.1)
        cam.set_stock(job, wanted)
        self.assertEqual(cam.stock(job), wanted)
        self.assertBounds(cam.stock_bounds(job), (-20, -10, -12, 20, 10, 0.1))
        with self.assertRaises(ValueError):
            cam.set_stock(job, stock.BoxStock(z_pos_mm=-1))
        self.assertEqual(cam.stock(job), wanted, "a refused stock changes nothing")

    def test_library_tool(self):
        job = cam.ensure_job(self.doc)
        t5 = self.variant(5, "Aluminium")
        tc = cam.add_tool(job, t5)
        (entry,) = cam.project_tools(job)
        self.assertIs(entry.controller, tc)
        self.assertEqual((entry.number, entry.library_id, entry.workpiece_material), (5, t5.id, "Aluminium"))
        t = entry.tool
        self.assertEqual((t.shape, t.diameter_mm, t.corner_radius_mm, t.flutes), ("Bullnose", 6, 0.2, 3))
        self.assertAlmostEqual(t.spindle_rpm, 12000)
        self.assertAlmostEqual(t.feed_xy_mm_min, 1250)
        self.assertAlmostEqual(t.feed_z_mm_min, 937)
        self.assertEqual(tc.Label, "T5: VHM ALU Frees 6mm")
        # FreeCAD keeps feeds in mm/s: 1250 mm/min must be 20.83 mm/s, not 1250
        self.assertAlmostEqual(cam._value(tc.HorizFeed, "mm/s"), 1250 / 60)

        cam.add_tool(job, self.variant(29, "RVS"))
        t29 = cam.tool_with_number(job, 29).tool
        self.assertEqual((t29.shape, t29.angle_deg, t29.spindle_rpm), ("Chamfer", 90, 10000))

    def test_thread_mill(self):
        job = cam.ensure_job(self.doc)
        m6 = self.variant(221, "RVS")
        tc = cam.add_tool(job, m6)
        self.assertEqual(tc.Tool.ShapeType, "ThreadMill")
        self.assertAlmostEqual(tc.Tool.Diameter.Value, 4.8)
        t = cam.tool_with_number(job, 221).tool
        self.assertEqual(t.shape, "ThreadMill")
        for field in ("diameter_mm", "pitch_mm", "angle_deg", "neck_diameter_mm", "neck_length_mm", "length_mm"):
            self.assertAlmostEqual(getattr(t, field), getattr(m6.tool, field), msg=field)

    def test_one_variant_per_number(self):
        job = cam.ensure_job(self.doc)
        tc = cam.add_tool(job, self.variant(40, "Aluminium"))
        with self.assertRaises(cam.ToolNumberTaken) as caught:
            cam.add_tool(job, self.variant(40, "RVS"))
        self.assertEqual(caught.exception.existing.workpiece_material, "Aluminium")
        self.assertEqual(len(cam.project_tools(job)), 1)

        old_bit = tc.Tool.Name
        rvs = self.variant(40, "RVS")
        cam.replace_tool(job, tc, rvs)
        (entry,) = cam.project_tools(job)
        self.assertIs(entry.controller, tc, "same tool controller, operations stay linked")
        self.assertEqual((entry.library_id, entry.workpiece_material), (rvs.id, "RVS"))
        self.assertAlmostEqual(entry.tool.spindle_rpm, 562)
        self.assertAlmostEqual(entry.tool.feed_xy_mm_min, 50)
        self.assertAlmostEqual(entry.tool.feed_z_mm_min, 37.5)
        self.assertEqual(entry.tool.angle_deg, 118)
        self.assertIsNone(self.doc.getObject(old_bit), "the old tool bit is gone")
        with self.assertRaises(cam.ProjectError):
            cam.replace_tool(job, tc, self.variant(19, "RVS"))

        cam.remove_tool(job, tc)
        self.assertEqual(cam.project_tools(job), [])
        self.assertEqual(self.leftovers(), [], "removed tools leave no shape bodies")

    def test_owner(self):
        job = cam.ensure_job(self.doc)
        tc = cam.add_tool(job, self.variant(5, "Aluminium"))
        clone = job.Model.Group[0]
        self.assertEqual(cam.owner(clone), ("model", self.part))
        self.assertEqual(cam.owner(self.part), ("model", self.part))
        self.assertEqual(cam.owner(job.Stock), ("stock", job.Stock))
        self.assertEqual(cam.owner(tc.Tool), ("tool", tc))
        self.assertEqual(cam.owner(job), ("setup", job))

    def test_element_of_a_model_made_of_objects(self):
        import Part

        # as a STEP file is imported: an App::Part with a shape inside, both placed
        assembly = self.doc.addObject("App::Part", "Assembly")
        assembly.Placement.Base = FreeCAD.Vector(100, 0, 0)
        inner = self.doc.addObject("Part::Feature", "Inner")
        inner.Shape = Part.makeBox(10, 10, 5)
        inner.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 50, 0), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 180))
        assembly.addObject(inner)
        self.doc.recompute()
        self.assertEqual(cam.models(self.doc), [self.part, assembly])
        sub = next("Face{}".format(i) for i, f in enumerate(inner.Shape.Faces, start=1) if f.CenterOfMass.z > 4.9)
        found = cam.model_element(assembly, "Inner." + sub)  # a click in 3D
        self.assertIsNotNone(found)
        model, name = found
        self.assertIs(model, assembly)
        self.assertEqual(cam.model_element(inner, sub), found, "as selection observers name it")
        self.assertEqual(cam.model_element(assembly, "Inner.;#a:1;:G;XTR;:H1,F." + sub), found, "with topological names")
        place = geometry.zero_on_face(cam.models(self.doc), model, name)
        # the inner box at x 90..100, y 40..50 (turned round, moved by both placements), z 0..5;
        # X0 Y0 in the middle of both models
        self.assertPlacement(place, (40, 20, 5), (0, 0, 1))
        self.assertAlmostEqual(assembly.Shape.getElement(name).CenterOfMass.z, 5)
        self.assertEqual(cam.model_element(self.part, "Face6"), (self.part, "Face6"))
        self.assertIsNone(cam.model_element(assembly, "Inner.Vertex1"))
        self.assertIsNone(cam.model_element(assembly.Origin, "Face1"), "not a shape")

    def test_add_second_model(self):
        job = cam.ensure_job(self.doc)
        second = self.doc.addObject("Part::Box", "Second")
        second.Placement.Base = FreeCAD.Vector(30, 0, 0)  # 10 mm cube from x=30
        self.doc.recompute()
        cam.add_model(self.doc, second)
        cam.add_model(self.doc, second)  # twice is once
        self.assertEqual(cam.models(self.doc), [self.part, second])
        self.assertAlmostEqual(cam.stock_bounds(job).x_max, 41)


    def test_zero_on_a_side_face(self):
        front = self.face(self.part, (0, -1, 0))
        place = geometry.zero_on_face([self.part], self.part, front)
        # middle of the part's width and height, on the front face; Y is up
        self.assertPlacement(place, (0, -10, 6), (0, -1, 0))
        self.assertVector(place.Rotation.multVec(FreeCAD.Vector(1, 0, 0)), (1, 0, 0))
        self.assertVector(place.Rotation.multVec(FreeCAD.Vector(0, 1, 0)), (0, 0, 1))

        first = cam.ensure_job(self.doc)
        second = cam.new_setup(self.doc, place)
        self.assertEqual([j.Label for j in cam.setups(self.doc)], ["Setup 1", "Setup 2"])
        self.assertIs(cam.setup_of(second.Stock), second)
        self.assertEqual(cam.owner(second.Model.Group[0]), ("model", self.part))
        # in setup 2 the part is 40 wide, 12 high and 20 deep below the face
        self.assertBounds(cam.stock_bounds(second), (-21, -7, -20, 21, 7, 1))
        self.assertBounds(cam.stock_bounds(first), (-21, -11, -12, 21, 11, 1), "setup 1 unchanged")

    def test_set_zero(self):
        job = cam.ensure_job(self.doc)
        corner = FreeCAD.Placement(FreeCAD.Vector(-20, -10, 12), FreeCAD.Rotation())
        cam.set_zero(job, corner)
        self.assertPlacement(cam.zero(job), (-20, -10, 12), (0, 0, 1))
        self.assertBounds(cam.stock_bounds(job), (-1, -1, -12, 41, 21, 1), "stock follows")

    def test_rotate_zero(self):
        job = cam.ensure_job(self.doc)
        self.assertEqual(cam.zero_rotation(job), 0.0)
        cam.rotate_zero(job, 90)
        self.assertPlacement(cam.zero(job), (0, 0, 12), (0, 0, 1))
        self.assertVector(cam.zero(job).Rotation.multVec(FreeCAD.Vector(1, 0, 0)), (0, 1, 0))
        self.assertEqual(cam.zero_rotation(job), 90.0)
        # the part lies across the machine now: 20 along X, 40 along Y
        self.assertBounds(cam.stock_bounds(job), (-11, -21, -12, 11, 21, 1), "stock follows")
        cam.rotate_zero(job, 180)
        self.assertEqual(cam.zero_rotation(job), -90.0)
        cam.rotate_zero(job, 90)
        self.assertEqual(cam.zero_rotation(job), 0.0)
        self.assertBounds(cam.stock_bounds(job), (-21, -11, -12, 21, 11, 1))
        cam.rotate_zero(job, 12.5)
        self.assertAlmostEqual(cam.zero_rotation(job), 12.5)
        self.assertPlacement(cam.zero(job), (0, 0, 12), (0, 0, 1))

    def test_rotate_zero_keeps_the_block(self):
        """Test plate A: allowances 1.5 in X, 1.75 in Y; a quarter
        turn must not make 303 x 96 into 303.5 x 95.5."""
        job = cam.ensure_job(self.doc)
        cam.set_stock(job, stock.BoxStock(1, 2, 3, 4, 5, 6))
        self.assertBounds(cam.stock_bounds(job), (-21, -13, -17, 22, 14, 6))

        def in_world():
            box = job.Stock.Shape.transformed(cam.zero(job).toMatrix()).BoundBox
            return (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)

        block = in_world()
        for degrees in (90, 90, 180, -90, 270, 180):
            cam.rotate_zero(job, degrees)
            self.assertBounds(in_world(), block, "the block stays after {}°".format(degrees))
        self.assertEqual(cam.zero_rotation(job), 0.0)
        self.assertEqual(cam.stock(job), stock.BoxStock(1, 2, 3, 4, 5, 6))
        cam.rotate_zero(job, 90)
        # across the machine: 27 along X, 43 along Y
        self.assertBounds(cam.stock_bounds(job), (-13, -22, -17, 14, 21, 6))

    def test_rotate_zero_moves_the_operations(self):
        body, job, tc, sketch = self.contour_setup()
        op = cam.add_contour(job, sketch, operations.Contour(-3.0), tc)

        def extents():
            cutting = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]
            xs = [c.Parameters["X"] for c in cutting if "X" in c.Parameters]
            ys = [c.Parameters["Y"] for c in cutting if "Y" in c.Parameters]
            return min(xs), max(xs), min(ys), max(ys)

        self.assertBounds(extents(), (-20, 20, -10, 10))
        cam.rotate_zero(job, 90)
        self.assertBounds(extents(), (-10, 10, -20, 20))
        self.assertEqual(cam.contour_depths(op), (0.0, -3.0), "Z unchanged")

    def test_extract_boundary(self):
        body = self.holed_part()
        top = self.face(body, (0, 0, 1))
        sketch = geometry.extract_boundary(self.doc, [body], body, top)
        self.assertEqual(cam.owner(sketch), ("sketch", sketch))
        self.assertNotIn(sketch, cam.models(self.doc), "a sketch is not a model")
        self.assertPlacement(sketch.Placement, (0, 0, 12), (0, 0, 1))
        self.assertEqual(sketch.GeometryCount, 5, "4 lines and the hole")
        self.assertEqual(sorted(len(w.Edges) for w in sketch.Shape.Wires), [1, 4])
        self.assertTrue(all(w.isClosed() for w in sketch.Shape.Wires))
        b = sketch.Shape.BoundBox
        self.assertBounds((b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax), (-20, -10, 12, 20, 10, 12))
        circle = [g for g in sketch.Geometry if type(g).__name__ == "Circle"][0]
        self.assertVector(circle.Center, (-10, 0, 0))  # sketch coordinates = G-code coordinates
        self.assertAlmostEqual(circle.Radius, 3)

    def test_arcs_keep_their_side(self):
        """A rounded corner must stay the short arc, whichever way OCCT runs it."""
        rounded = self.doc.addObject("Part::Fillet", "Rounded")
        rounded.Base = self.part
        edges = [(i, 4.0, 4.0) for i, e in enumerate(self.part.Shape.Edges, start=1)
                 if abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-9
                 and abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-9]
        rounded.Edges = edges
        self.doc.recompute()
        top = self.face(rounded, (0, 0, 1))
        sketch = geometry.extract_boundary(self.doc, [rounded], rounded, top)
        arcs = [g for g in sketch.Geometry if type(g).__name__ == "ArcOfCircle"]
        self.assertEqual(len(arcs), 4)
        for arc in arcs:
            self.assertAlmostEqual(arc.LastParameter - arc.FirstParameter, 1.5707963267948966)
        self.assertAlmostEqual(sketch.Shape.Wires[0].Length, rounded.Shape.getElement(top).OuterWire.Length)

    def contour_setup(self):
        body = self.holed_part()
        job = cam.ensure_job(self.doc, [body])
        tc = cam.add_tool(job, self.variant(21, "RVS"))
        sketch = geometry.extract_boundary(self.doc, [body], body, self.face(body, (0, 0, 1)))
        return body, job, tc, sketch

    def test_contour_on_top(self):
        body, job, tc, sketch = self.contour_setup()
        op = cam.add_contour(job, sketch, operations.Contour(-3.0), tc)
        self.assertEqual(op.Label, "Contour 1")
        self.assertIs(cam.setup_of(op), job)
        self.assertEqual(cam.contour_of(op), (sketch, operations.Contour(-3.0)))
        self.assertEqual(cam.contour_depths(op), (0.0, -3.0))
        moves, lowest = cam.path_summary(op)
        self.assertGreater(moves, 8)
        self.assertAlmostEqual(lowest, -3.0)
        cutting = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]
        xs = [c.Parameters["X"] for c in cutting if "X" in c.Parameters]
        self.assertAlmostEqual(min(xs), -20.0)  # no compensation: the tool centre is on the edge
        self.assertAlmostEqual(max(xs), 20.0)
        self.assertEqual(cam.owner(op.BaseShapes[0]), ("operation", op))
        self.assertNotIn(op.BaseShapes[0], cam.models(self.doc))

        cam.set_contour(op, operations.Contour(-5.0))
        self.assertAlmostEqual(cam.path_summary(op)[1], -5.0)

        # zero 2 mm above the part: the sketch plane is at Z-2 now
        above = FreeCAD.Placement(FreeCAD.Vector(0, 0, 14), FreeCAD.Rotation())
        cam.set_zero(job, above)
        self.assertEqual(cam.contour_depths(op), (-2.0, -7.0))
        self.assertAlmostEqual(cam.path_summary(op)[1], -7.0)

        side = geometry.zero_on_face([body], body, self.face(body, (0, -1, 0)))
        with self.assertRaises(cam.ProjectError):
            cam.set_zero(job, side)
        self.assertPlacement(cam.zero(job), (0, 0, 14), (0, 0, 1))

        with self.assertRaises(ValueError):
            cam.set_contour(op, operations.Contour(1.0))

        helper = op.BaseShapes[0].Name
        cam.remove_operation(op)
        self.assertEqual(cam.operations(job), [])
        self.assertIsNone(self.doc.getObject(helper))

    def line(self, sketch, x=None, y=None):
        """Name of the sketch's straight line at x = ... or y = ... (sketch coordinates)."""
        for i, e in enumerate(sketch.Shape.Edges, start=1):
            mid = sketch.Placement.inverse().multVec(e.valueAt((e.FirstParameter + e.LastParameter) / 2))
            if e.Curve.TypeId == "Part::GeomLine" and (
                (x is not None and abs(mid.x - x) < 1e-9) or (y is not None and abs(mid.y - y) < 1e-9)
            ):
                return "Edge{}".format(i)
        raise AssertionError("no line at x={} y={}".format(x, y))

    def cutting_xy(self, op):
        """(x, y) of the cutting moves (the plunge first) of a contour."""
        moves = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3") and "X" in c.Parameters]
        return [(round(c.Parameters["X"], 6), round(c.Parameters["Y"], 6)) for c in moves]

    def test_contour_on_several_sketches(self):
        """Lines of two Extract boundary edges at different heights in one
        contour: sketch after sketch, each cut from its own plane."""
        import Part

        V = FreeCAD.Vector
        shape = Part.makeBox(40, 20, 10, V(-20, -10, 0)).fuse(Part.makeBox(10, 10, 4, V(-15, -5, 10))).removeSplitter()
        stepped = self.doc.addObject("Part::Feature", "Stepped")
        stepped.Shape = shape
        self.doc.recompute()
        job = cam.ensure_job(self.doc, [stepped])
        tc = cam.add_tool(job, self.variant(21, "RVS"))
        tops = sorted(
            ("Face{}".format(i) for i, f in enumerate(shape.Faces, start=1)
             if f.findPlane() is not None and geometry.outward_normal(shape, f).getAngle(V(0, 0, 1)) < 1e-9),
            key=lambda name: -shape.getElement(name).BoundBox.ZMax,
        )  # fmt: skip
        island = geometry.extract_boundary(self.doc, [stepped], stepped, tops[0])  # Z 14
        plate = geometry.extract_boundary(self.doc, [stepped], stepped, tops[1])  # Z 10, around the island too
        cam.set_zero(job, geometry.zero_on_face([stepped], stepped, tops[0]))
        right = self.line(plate, x=20)
        op = cam.add_contour_sketches(job, [(island, [], ()), (plate, [right], ())], operations.Contour(-1.0), tc)
        self.assertEqual(cam.contour_sketches(op), [(island, []), (plate, [right])])
        self.assertEqual(cam.contour_of(op)[0], island, "linked to the first sketch")
        self.assertEqual([round(z, 6) for z in cam.contour_planes(op)], [0.0, -4.0])
        self.assertEqual(cam.contour_depths(op), (0.0, -5.0), "from the highest plane down to the deepest cut")
        cutting = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3") and "Z" in c.Parameters]
        depths = [round(c.Parameters["Z"], 6) for c in cutting]
        self.assertEqual(sorted(set(depths)), [-5.0, -1.0], "each sketch 1 mm below its own plane")
        self.assertEqual(depths[0], -1.0, "the island first, as picked")
        self.assertEqual(depths[-1], -5.0)
        ys = {round(c.Parameters["Y"], 6) for c in cutting if round(c.Parameters["Z"], 6) == -5.0 and "Y" in c.Parameters}
        self.assertEqual(ys, {10.0, -10.0}, "on the plate only its picked line")

        cam.set_contour(op, operations.Contour(-2.0))
        self.assertEqual(cam.contour_depths(op), (0.0, -6.0))
        helpers = [h.Name for h in cam.helper_objects(op)]
        cam.remove_operation(op)
        self.assertTrue(all(self.doc.getObject(name) is None for name in helpers))

    def test_contour_follows_picked_lines(self):
        body, job, tc, sketch = self.contour_setup()
        right, bottom = self.line(sketch, x=20), self.line(sketch, y=-10)
        op = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [right, bottom])
        self.assertEqual(cam.contour_lines(op), [right, bottom])
        # starts on the first picked line and runs towards the second
        self.assertEqual(self.cutting_xy(op), [(20, 10), (20, -10), (-20, -10)])
        self.assertAlmostEqual(cam.path_summary(op)[1], -1.0)

        op2 = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [bottom, right])
        self.assertEqual(op2.Label, "Contour 2")
        self.assertEqual(self.cutting_xy(op2), [(-20, -10), (20, -10), (20, 10)])

    def test_contour_lines_that_do_not_meet(self):
        body, job, tc, sketch = self.contour_setup()
        top = self.line(sketch, y=10)
        circle = next(
            "Edge{}".format(i) for i, e in enumerate(sketch.Shape.Edges, start=1) if e.Curve.TypeId == "Part::GeomCircle"
        )
        op = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [top, circle])
        self.assertEqual(len(cam.helper_objects(op)), 2, "one chain per helper keeps the order")
        xy = self.cutting_xy(op)
        self.assertEqual(xy[:2], [(-20, 10), (20, 10)], "the first picked line first: " + str(xy))
        self.assertAlmostEqual(abs(complex(*xy[-1]) - complex(-10, 0)), 3.0, msg="then the hole")
        with self.assertRaises(cam.ProjectError):
            cam.add_contour(job, sketch, operations.Contour(-1.0), tc, ["Edge99"])

        helpers = [h.Name for h in cam.helper_objects(op)]
        cam.remove_operation(op)
        self.assertEqual([self.doc.getObject(n) for n in helpers], [None, None])

    def test_loop_and_path(self):
        body, job, tc, sketch = self.contour_setup()
        top, right = self.line(sketch, y=10), self.line(sketch, x=20)
        bottom, left = self.line(sketch, y=-10), self.line(sketch, x=-20)
        loop = geometry.line_loop(sketch, right)
        self.assertEqual(loop[0], right)
        self.assertEqual(sorted(loop), sorted([top, right, bottom, left]))
        circle = next(
            "Edge{}".format(i) for i, e in enumerate(sketch.Shape.Edges, start=1) if e.Curve.TypeId == "Part::GeomCircle"
        )
        self.assertEqual(geometry.line_loop(sketch, circle), [circle])
        # from top to bottom: through right or left, both 20 mm; adjacent lines: nothing between
        self.assertIn(geometry.line_path(sketch, [top], bottom), ([right], [left]))
        self.assertEqual(geometry.line_path(sketch, [top], right), [])
        # the chain top -> right runs on from the right line's free end
        self.assertEqual(geometry.line_path(sketch, [top, right], left), [bottom])
        self.assertEqual(geometry.line_path(sketch, [top], circle), [], "no way to the hole")

    def test_chain_order(self):
        import Part

        V = FreeCAD.Vector
        a = Part.LineSegment(V(0, 0, 0), V(10, 0, 0)).toShape()
        b = Part.LineSegment(V(10, 10, 0), V(10, 0, 0)).toShape()  # drawn the other way
        c = Part.LineSegment(V(10, 10, 0), V(0, 10, 0)).toShape()
        far = Part.LineSegment(V(50, 0, 0), V(60, 0, 0)).toShape()
        self.assertEqual(geometry.chain_order([a, b, c]), [[(0, False), (1, True), (2, False)]])
        self.assertEqual(geometry.chain_order([c, b, a]), [[(0, True), (1, False), (2, True)]])
        self.assertEqual(geometry.chain_order([b, far, a]), [[(0, False)], [(1, False)], [(2, False)]])

    def test_chain_order_backwards(self):
        import Part

        V = FreeCAD.Vector
        a = Part.LineSegment(V(0, 0, 0), V(10, 0, 0)).toShape()
        b = Part.LineSegment(V(10, 10, 0), V(10, 0, 0)).toShape()
        far = Part.LineSegment(V(50, 0, 0), V(60, 0, 0)).toShape()
        # any line of a chain turns the whole chain round
        self.assertEqual(geometry.chain_order([a, b, far], backwards=[1]), [[(1, False), (0, True)], [(2, False)]])
        self.assertEqual(geometry.chain_order([a, b, far], backwards=[2]), [[(0, False), (1, True)], [(2, True)]])

    def test_contour_backwards(self):
        body, job, tc, sketch = self.contour_setup()
        right, bottom = self.line(sketch, x=20), self.line(sketch, y=-10)
        op = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [right, bottom], backwards=[bottom])
        self.assertEqual(cam.contour_lines(op), [bottom, right], "the tool's order")
        self.assertEqual(self.cutting_xy(op), [(-20, -10), (20, -10), (20, 10)])
        self.assertEqual(geometry.line_chains(sketch, [right, bottom]), [[right, bottom]])

        # a single line has no other line to show its direction
        one = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [right])
        self.assertEqual(self.cutting_xy(one)[0], (20, -10), "the line as it was drawn")
        one = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [right], backwards=[right])
        self.assertEqual(self.cutting_xy(one), [(20, 10), (20, -10)])

        # a hole: the other way round from the same point
        circle = next(
            "Edge{}".format(i) for i, e in enumerate(sketch.Shape.Edges, start=1) if e.Curve.TypeId == "Part::GeomCircle"
        )
        arcs = []
        for backwards in ((), [circle]):
            hole = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [circle], backwards=backwards)
            cuts = [c for c in hole.Path.Commands if c.Name in ("G2", "G3")]
            arcs.append(({c.Name for c in cuts}, self.cutting_xy(hole)[0]))
        self.assertEqual(len(arcs[0][0]), 1)
        self.assertNotEqual(arcs[0][0], arcs[1][0], "G2 <-> G3: " + str(arcs))
        self.assertEqual(arcs[0][1], arcs[1][1], "starts at the same point")

        # all lines with one chain turned: each chain keeps its own direction
        whole = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, backwards=[circle])
        helpers = cam.helper_objects(whole)
        self.assertEqual(len(helpers), 2)
        self.assertEqual([h.Reversed for h in helpers if circle in h.Edges], [True])
        self.assertEqual([h.Reversed for h in helpers if circle not in h.Edges], [False])

    def test_line_arrows(self):
        body, job, tc, sketch = self.contour_setup()
        right, bottom = self.line(sketch, x=20), self.line(sketch, y=-10)
        arrows = {name: (tuple(round(c, 6) for c in p), tuple(round(c, 6) for c in d))
                  for name, p, d in geometry.line_arrows(sketch, [right, bottom])}  # fmt: skip
        self.assertEqual(arrows[right], ((20, 0, 0), (0, -1, 0)), "in the middle, towards the second line")
        self.assertEqual(arrows[bottom], ((0, -10, 0), (-1, 0, 0)))
        turned = {name: tuple(round(c, 6) for c in d) for name, _p, d in geometry.line_arrows(sketch, [right, bottom], [right])}
        self.assertEqual(turned, {right: (0, 1, 0), bottom: (1, 0, 0)})
        self.assertEqual(len(geometry.line_arrows(sketch)), len(sketch.Shape.Edges), "all lines")

    def test_nc_program(self):
        from avangardecam.post import heidenhain

        body, job, tc, sketch = self.contour_setup()
        right, bottom = self.line(sketch, x=20), self.line(sketch, y=-10)
        op = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [right, bottom])
        # as the shop's programs: down to Z+20 over the start, then 2 mm above the stock (top at Z+1)
        self.assertAlmostEqual(op.ClearanceHeight.Value, 20.0)
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0)
        cam.set_stock(job, stock.BoxStock(z_pos_mm=4.0))
        self.assertAlmostEqual(op.SafeHeight.Value, 6.0, msg="the heights follow the stock")
        cam.set_stock(job, stock.BoxStock())

        front = self.face(body, (0, -1, 0))
        side = geometry.extract_boundary(self.doc, [body], body, front)
        second = cam.new_setup(self.doc, geometry.zero_on_face([body], body, front))
        cam.add_contour(second, side, operations.Contour(-2.0), cam.add_tool(second, self.variant(21, "RVS")))

        program = cam.nc_program(self.doc, "TEST")
        self.assertEqual([(s.preset, len(s.operations)) for s in program.setups], [(1, 1), (2, 1)])
        blocks = [line.split(" ", 1)[1] for line in heidenhain.write(program).split("\r\n") if line]
        tool = cam.tool_with_number(job, 21).tool
        self.assertIn("TOOL CALL 21 Z S{} DL0 DR0;{}".format(heidenhain.plain(tool.spindle_rpm), tool.name), blocks)
        self.assertEqual(blocks.count("TOOL CALL 21 Z S{} DL0 DR0;{}".format(heidenhain.plain(tool.spindle_rpm), tool.name)), 1)
        self.assertIn("FN0: Q30={} ;voeding Z".format(heidenhain.plain(tool.feed_z_mm_min)), blocks)
        self.assertIn("FN0: Q31={} ;voeding XY".format(heidenhain.plain(tool.feed_xy_mm_min)), blocks)
        start = blocks.index("L X+20. Y+10. R0 FMAX")
        # feeds read back in mm/min: FreeCAD's plunge and cut feeds are the tool's Q30 and Q31
        self.assertEqual(
            blocks[start : start + 7],
            ["L X+20. Y+10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30", "L Y-10. FQ31",
             "L X-20.", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        self.assertEqual([b for b in blocks if "Q339" in b], ["   Q339=+1    ;REF.PUNT-NUMMER", "   Q339=+2    ;REF.PUNT-NUMMER"])  # fmt: skip
        self.assertIn("BLK FORM 0.1 Z X-21. Y-11. Z-12.", blocks)
        self.assertIn("BLK FORM 0.2 X+21. Y+11. Z+1.", blocks)

        op.Active = False
        self.doc.recompute()
        self.assertEqual(len(cam.nc_program(self.doc, "TEST").setups[0].operations), 0, "inactive operations stay out")

    def nc_blocks(self, op):
        """The contour's blocks of the .H program, from over its start to the end of its tool."""
        from avangardecam.post import heidenhain

        text = heidenhain.write(cam.nc_program(self.doc, "TEST"))
        blocks = [line.split(" ", 1)[1] for line in text.split("\r\n") if line]
        start = next(i for i, b in enumerate(blocks) if b.startswith("FN0: Q31=")) + 1
        return blocks[start : blocks.index("L Z100 R0 FMAX", start)]

    def centre_xy(self, op):
        """(x, y) of all the cutting moves' ends of the FreeCAD path."""
        return [(c.Parameters["X"], c.Parameters["Y"]) for c in op.Path.Commands
                if c.Name in ("G1", "G2", "G3") and "X" in c.Parameters]  # fmt: skip

    def square(self, sketch):
        """The outline clockwise from the top line, like the shop's square program."""
        return [self.line(sketch, y=10), self.line(sketch, x=20), self.line(sketch, y=-10), self.line(sketch, x=-20)]

    def test_compensation_left_outside(self):
        body, job, tc, sketch = self.contour_setup()
        # RL keeps the 8 mm tool outside; by default it goes down 0.5 mm clear (arc radius 4.5)
        arc = operations.Contour(-1.0, operations.LEFT, operations.ARC)
        op = cam.add_contour(job, sketch, arc, tc, self.square(sketch))
        self.assertEqual(cam.contour_of(op)[1], arc)
        self.assertAlmostEqual(cam.lead_radius(op), 4.5)
        self.assertEqual(
            self.nc_blocks(op),
            ["L X+0. Y+14.5 R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30",
             "L X-3.182 Y+11.318 RL FQ31", "CC X+0. Y+14.5", "C X+0. Y+10. DR+", "L X+20.", "L Y-10.", "L X-20.",
             "L Y+10.", "L X+0.", "CC X+0. Y+14.5", "C X+3.182 Y+11.318 DR+", "L X+0. Y+14.5 R0", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        # FreeCAD's path is the tool centre: 4 mm outside, round the corners
        xy = self.centre_xy(op)
        self.assertEqual(tuple(round(c, 6) for c in xy[0]), (0, 14.5), "down in the centre of the lead arc")
        self.assertAlmostEqual(max(y for _x, y in xy), 14.5)
        self.assertAlmostEqual(max(x for x, _y in xy), 24.0)
        self.assertAlmostEqual(min(x for x, _y in xy), -24.0)
        self.assertAlmostEqual(min(y for _x, y in xy), -14.0)
        arcs = [c for c in op.Path.Commands if c.Name in ("G2", "G3")]
        self.assertEqual(len(arcs), 6, "four corners and the two lead arcs")
        self.assertAlmostEqual(cam.path_summary(op)[1], -1.0)

        # the user's radius, the shop's programs' 1.1 x the tool radius
        cam.set_contour(op, operations.Contour(-1.0, operations.LEFT, operations.ARC, 4.4))
        self.assertEqual(self.nc_blocks(op)[4], "L X-3.111 Y+11.289 RL FQ31")
        with self.assertRaises(cam.ProjectError, msg="with compensation the arc must be wider than the tool"):
            cam.set_contour(op, operations.Contour(-1.0, operations.LEFT, operations.ARC, 4.0))
        self.assertAlmostEqual(cam.lead_radius(op), 4.4, msg="nothing changed")

        # the other side: inside, the corners cut short
        cam.set_contour(op, operations.Contour(-1.0, operations.RIGHT, operations.ARC))
        xy = self.centre_xy(op)
        self.assertAlmostEqual(max(x for x, _y in xy), 16.0)
        self.assertAlmostEqual(min(y for _x, y in xy), -6.0)
        self.assertEqual(len([c for c in op.Path.Commands if c.Name in ("G2", "G3")]), 2, "only the lead arcs")
        blocks = self.nc_blocks(op)
        self.assertEqual(blocks[0], "L X+0. Y+5.5 R0 FMAX")
        self.assertIn("L X-3.182 Y+8.682 RR FQ31", blocks)
        self.assertIn("C X+0. Y+10. DR-", blocks)

        # off again: the centre on the lines, from the start of the first one
        cam.set_contour(op, operations.Contour(-1.0))
        self.assertEqual(self.nc_blocks(op)[:5], ["L X-20. Y+10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX",
                                                 "L Z-1. R0 FQ30", "L X+20. FQ31"])  # fmt: skip
        self.assertFalse([b for b in self.nc_blocks(op) if " RL" in b or " RR" in b])

    def test_compensation_without_approach(self):
        body, job, tc, sketch = self.contour_setup()
        # RL switched on over the start above the part, straight down, off above the part again
        op = cam.add_contour(job, sketch, operations.Contour(-1.0, operations.LEFT), tc, self.square(sketch))
        self.assertEqual(
            self.nc_blocks(op),
            ["L X+0. Y+10. RL FMAX", "L Z+20. FMAX M3 M8", "L Z+3. FMAX", "L Z-1. FQ30", "L X+20. FQ31", "L Y-10.",
             "L X-20.", "L Y+10.", "L X+0.", "L Z+40. FMAX", "L X+0. Y+10. R0 FMAX"],
        )  # fmt: skip
        xy = self.centre_xy(op)
        self.assertEqual(tuple(round(c, 6) for c in xy[0]), (0, 14), "the tool centre goes down beside the line")
        self.assertEqual(len([c for c in op.Path.Commands if c.Name in ("G2", "G3")]), 4, "round the corners only")

        # two chains: off above the part before the tool moves to the second start
        right, left = self.line(sketch, x=20), self.line(sketch, x=-20)
        cam.remove_operation(op)
        op = cam.add_contour(job, sketch, operations.Contour(-1.0, operations.LEFT), tc, [right, left])
        blocks = self.nc_blocks(op)
        on = [i for i, b in enumerate(blocks) if b.endswith(" RL FMAX")]
        off = [i for i, b in enumerate(blocks) if b.endswith(" R0 FMAX") and b.startswith("L X")]
        self.assertEqual((len(on), len(off)), (2, 2), blocks)
        self.assertEqual(off[0] + 1, on[1], "off, then on again over the second start: {}".format(blocks))
        self.assertTrue(blocks[off[0] - 1].startswith("L Z+") and blocks[off[0] - 1].endswith(" FMAX"), "up first")
        self.assertEqual(off[1], len(blocks) - 1, "off again above the part at the end")
        self.assertEqual(blocks[-2], "L Z+40. FMAX")

    def test_approach_without_compensation(self):
        body, job, tc, sketch = self.contour_setup()
        # the tool centre comes in on the arc from the left, going down 0.5 mm clear of the line
        op = cam.add_contour(job, sketch, operations.Contour(-1.0, operations.OFF, operations.ARC), tc, self.square(sketch))
        self.assertEqual(
            self.nc_blocks(op),
            ["L X+0. Y+14.5 R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30",
             "L X-3.182 Y+11.318 FQ31", "CC X+0. Y+14.5", "C X+0. Y+10. DR+", "L X+20.", "L Y-10.", "L X-20.",
             "L Y+10.", "L X+0.", "CC X+0. Y+14.5", "C X+3.182 Y+11.318 DR+", "L X+0. Y+14.5", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        xy = self.centre_xy(op)
        self.assertAlmostEqual(max(x for x, _y in xy), 20.0, msg="the centre on the lines")
        # a smaller radius: the user's choice, down on the line
        cam.set_contour(op, operations.Contour(-1.0, operations.OFF, operations.ARC, 2.0))
        self.assertEqual(self.nc_blocks(op)[0], "L X+0. Y+12. R0 FMAX")
        # Off with arc on the right of the lines (Advanced): inside the square, the arcs clockwise
        right = operations.Contour(-1.0, operations.OFF, operations.ARC, arc_side=operations.RIGHT)
        cam.set_contour(op, right)
        self.assertEqual(cam.contour_of(op)[1], right)
        self.assertEqual(
            self.nc_blocks(op),
            ["L X+0. Y+5.5 R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30",
             "L X-3.182 Y+8.682 FQ31", "CC X+0. Y+5.5", "C X+0. Y+10. DR-", "L X+20.", "L Y-10.", "L X-20.",
             "L Y+10.", "L X+0.", "CC X+0. Y+5.5", "C X+3.182 Y+8.682 DR-", "L X+0. Y+5.5", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        self.assertEqual([h.ArcSide for h in cam.helper_objects(op)], [operations.RIGHT])
        self.assertAlmostEqual(max(x for x, _y in self.centre_xy(op)), 20.0, msg="the centre still on the lines")

    def test_offset_without_compensation(self):
        body, job, tc, sketch = self.contour_setup()
        # a chamfer mill's centre 0.5 mm inside the lines (right of them), straight down; a closed
        # loop then starts in the middle of its first line
        inside = operations.Contour(-1.0, offset_xy_mm=0.5, arc_side=operations.RIGHT)
        op = cam.add_contour(job, sketch, inside, tc, self.square(sketch))
        self.assertEqual(cam.contour_of(op)[1], inside)
        self.assertEqual(
            self.nc_blocks(op),
            ["L X+0. Y+9.5 R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30", "L X+19.5 FQ31",
             "L Y-9.5", "L X-19.5", "L Y+9.5", "L X+0.", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        # outside (left), round the corners; negative: to the other side
        cam.set_contour(op, operations.Contour(-1.0, offset_xy_mm=0.5))
        xy = self.centre_xy(op)
        self.assertAlmostEqual(max(x for x, _y in xy), 20.5)
        self.assertEqual(len([c for c in op.Path.Commands if c.Name in ("G2", "G3")]), 4, "round the four corners")
        cam.set_contour(op, operations.Contour(-1.0, offset_xy_mm=-0.5))
        self.assertAlmostEqual(max(x for x, _y in self.centre_xy(op)), 19.5)
        # with the arcs too: they come onto the moved lines
        cam.set_contour(op, operations.Contour(-1.0, operations.OFF, operations.ARC, offset_xy_mm=0.5, arc_side=operations.RIGHT))  # fmt: skip
        blocks = self.nc_blocks(op)
        self.assertEqual(blocks[0], "L X+0. Y+5. R0 FMAX", "the arc's centre 4.5 mm inside the moved line")
        self.assertIn("C X+0. Y+9.5 DR-", blocks)
        self.assertAlmostEqual(max(x for x, _y in self.centre_xy(op)), 19.5)

    def test_start_and_end_contour(self):
        body, job, tc, sketch = self.contour_setup()
        top, right = self.line(sketch, y=10), self.line(sketch, x=20)
        op = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, [top, right])
        self.assertEqual(self.nc_blocks(op)[0], "L X-20. Y+10. R0 FMAX")
        # longer: straight on before the first line and after the last one, along them
        longer = operations.Contour(-1.0, start_extend_mm=5.0, end_extend_mm=3.0)
        cam.set_contour(op, longer)
        self.assertEqual(cam.contour_of(op)[1], longer)
        self.assertEqual(
            self.nc_blocks(op),
            ["L X-25. Y+10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30", "L X+20. FQ31",
             "L Y-13.", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        # shorter: starts in the middle of the top line (40 mm), leaves 2 mm before the end
        cam.set_contour(op, operations.Contour(-1.0, start_extend_mm=-20.0, end_extend_mm=-2.0))
        self.assertEqual(
            self.nc_blocks(op),
            ["L X+0. Y+10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30", "L X+20. FQ31",
             "L Y-8.", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        # the program has the new lines: with RL the arcs come onto and leave them there
        cam.set_contour(op, operations.Contour(-1.0, operations.LEFT, operations.ARC, start_extend_mm=5.0, end_extend_mm=-2.0))  # fmt: skip
        self.assertEqual(
            self.nc_blocks(op)[4:12],
            ["L X-28.182 Y+11.318 RL FQ31", "CC X-25. Y+14.5", "C X-25. Y+10. DR+", "L X+20.", "L Y-8.",
             "CC X+24.5 Y-8.", "C X+21.318 Y-11.182 DR+", "L X+24.5 Y-8. R0"],
        )  # fmt: skip
        # nothing left, and closed loops
        with self.assertRaises(cam.ProjectError):
            cam.set_contour(op, operations.Contour(-1.0, start_extend_mm=-40.0, end_extend_mm=-20.0))
        with self.assertRaises(cam.ProjectError):
            cam.add_contour(job, sketch, operations.Contour(-1.0, end_extend_mm=2.0), tc, self.square(sketch))
        with self.assertRaises(ValueError):
            operations.Contour(-1.0, start_extend_mm=2000.0).validate()

    def test_path_drawing(self):
        body, job, tc, sketch = self.contour_setup()

        def xyz(p):
            return tuple(round(c, 6) for c in p)

        # without compensation the view draws FreeCAD's path: the tool centre on the lines
        op = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, self.square(sketch))
        self.assertIsNone(cam.path_drawing(op))

        # RL without the approach arcs: down with the centre 4 mm beside the line, across to the line, where
        # the edge cuts, back to the centre at the end
        cam.set_contour(op, operations.Contour(-1.0, operations.LEFT))
        pieces = cam.path_drawing(op)
        kinds = [k for k, _p in pieces]
        down = kinds.index(cam.DRAW_LINK) - 1
        self.assertEqual(kinds[down : down + 4], [cam.DRAW_FEED, cam.DRAW_LINK, cam.DRAW_FEED, cam.DRAW_LINK])
        self.assertEqual(kinds[down - 1], cam.DRAW_RAPID)
        self.assertEqual(kinds[-1], cam.DRAW_RAPID, "up again")
        plunge, link_in, lines, link_out = (pieces[down + k][1] for k in range(4))
        self.assertEqual(xyz(plunge[0])[:2], (0, 14))
        self.assertEqual([xyz(p) for p in link_in], [(0, 14, -1), (0, 10, -1)])
        self.assertEqual({xyz(p)[2] for p in lines}, {-1})
        self.assertAlmostEqual(max(p.x for p in lines), 20.0)
        self.assertAlmostEqual(min(p.y for p in lines), -10.0)
        self.assertEqual([xyz(p) for p in link_out], [(0, 10, -1), (0, 14, -1)])

        # with the approach arcs the program starts and ends in their centre, where the tool goes down
        cam.set_contour(op, operations.Contour(-1.0, operations.LEFT, operations.ARC))
        pieces = cam.path_drawing(op)
        self.assertNotIn(cam.DRAW_LINK, [k for k, _p in pieces])
        plunge, lines = [p for k, p in pieces if k == cam.DRAW_FEED]
        self.assertEqual(xyz(plunge[-1]), (0, 14.5, -1))
        self.assertEqual((xyz(lines[0]), xyz(lines[-1])), ((0, 14.5, -1), (0, 14.5, -1)))
        self.assertAlmostEqual(max(p.x for p in lines), 20.0)

        # each XY pass and Z level: its own lines
        cam.set_contour(op, operations.Contour(-3.0, operations.LEFT, z_step_mm=2.0, xy_width_mm=6.0, xy_step_mm=4.0))
        lines = [p for k, p in cam.path_drawing(op) if k == cam.DRAW_FEED and len(p) > 2]
        self.assertEqual(sorted(round(max(p.x for p in pts), 3) for pts in lines), [20, 20, 23, 23])

    def test_contour_z_steps(self):
        body, job, tc, sketch = self.contour_setup()
        op = cam.add_contour(job, sketch, operations.Contour(-5.0, z_step_mm=2.0), tc, self.square(sketch))
        # full steps, the last one what is left; down again fast to 2 mm above the level cut before
        self.assertEqual(
            self.nc_blocks(op),
            ["L X-20. Y+10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-2. R0 FQ30", "L X+20. FQ31",
             "L Y-10.", "L X-20.", "L Y+10.", "L Z+3. R0 FMAX", "L Z+0. R0 FMAX", "L Z-4. R0 FQ30", "L X+20. FQ31",
             "L Y-10.", "L X-20.", "L Y+10.", "L Z+3. R0 FMAX", "L Z-2. R0 FMAX", "L Z-5. R0 FQ30", "L X+20. FQ31",
             "L Y-10.", "L X-20.", "L Y+10.", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        self.assertAlmostEqual(op.StepDown.Value, 2.0)
        self.assertAlmostEqual(cam.path_summary(op)[1], -5.0)

    def test_contour_above_the_zero(self):
        body, job, tc, sketch = self.contour_setup()
        # the sketch on the top at Z0, the material up to Z+5 (above the stock's top at Z+1): Z+3, then Z+1
        contour = operations.Contour(1.0, start_z_mm=5.0, z_step_mm=2.0)
        op = cam.add_contour(job, sketch, contour, tc, self.square(sketch))
        self.assertEqual(cam.contour_depths(op), (5.0, 1.0))
        self.assertAlmostEqual(op.SafeHeight.Value, 7.0)  # 2 mm above Start Z, higher than the stock
        self.assertAlmostEqual(op.ClearanceHeight.Value, 20.0)
        self.assertEqual(
            self.nc_blocks(op),
            ["L X-20. Y+10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+7. R0 FMAX", "L Z+3. R0 FQ30", "L X+20. FQ31",
             "L Y-10.", "L X-20.", "L Y+10.", "L Z+7. R0 FMAX", "L Z+5. R0 FMAX", "L Z+1. R0 FQ30", "L X+20. FQ31",
             "L Y-10.", "L X-20.", "L Y+10.", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        self.assertAlmostEqual(cam.path_summary(op)[1], 1.0)
        # Start Z at the sketch plane again: 2 mm above the stock's top as before
        cam.set_contour(op, operations.Contour(-1.0))
        self.assertEqual(cam.contour_depths(op), (0.0, -1.0))
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0)
        # and lower than the plane (material already cut away there)
        cam.set_contour(op, operations.Contour(-4.0, start_z_mm=-2.0))
        self.assertEqual(cam.contour_depths(op), (-2.0, -4.0))
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0)
        self.assertEqual(self.plunges(self.nc_blocks(op)), ["Z-4."])
        # Z-Depth the same as Start Z: one pass at that height, on Z0 or above it
        for z in (0.0, 2.0):
            cam.set_contour(op, operations.Contour(z, start_z_mm=z, z_step_mm=1.0))
            self.assertEqual(cam.contour_depths(op), (z, z))
            self.assertEqual(self.plunges(self.nc_blocks(op)), ["Z{:+g}.".format(z)])
            self.assertAlmostEqual(cam.path_summary(op)[1], z)

    def plunges(self, blocks):
        return [b.split()[1] for b in blocks if b.endswith(" FQ30")]

    def test_contour_xy_passes(self):
        body, job, tc, sketch = self.contour_setup()
        # 6 mm beside the square, steps up to 4 mm, 0.1 mm left for a finishing pass: passes 3.05, 0.1 and 0
        # mm outside the lines, each of them by Z steps, from the outside in
        contour = operations.Contour(-3.0, operations.LEFT, operations.ARC, z_step_mm=2.0, xy_width_mm=6.0,
                                     xy_step_mm=4.0, finish_xy_mm=0.1)  # fmt: skip
        op = cam.add_contour(job, sketch, contour, tc, self.square(sketch))
        blocks = self.nc_blocks(op)
        self.assertEqual(self.plunges(blocks), ["Z-2.", "Z-3."] * 3)
        # the program has the lines moved by each pass, round the outside corners; the control adds the radius
        first, second, last = (blocks.index(b) for b in ("C X+23.05 Y+10. DR-", "C X+20.1 Y+10. DR-", "L X+20."))
        self.assertLess(first, second)
        self.assertEqual(blocks.count("C X+23.05 Y+10. DR-"), 2)
        self.assertEqual(blocks.count("C X+20.1 Y+10. DR-"), 2)
        self.assertEqual(blocks[0], "L X+0. Y+17.55 R0 FMAX", "down in the centre of the arc of the outer pass")
        self.assertIn("L Y+14.6 R0 FMAX", blocks)
        self.assertEqual(blocks.count("L Z+0. R0 FMAX"), 3, "fast down to just above each pass's first level")
        tail = blocks[blocks.index("L Y+14.5 R0 FMAX"):]
        self.assertFalse([b for b in tail if b.startswith("C X+2")], "the finishing pass on the lines, corners sharp")
        self.assertEqual(blocks[-1], "L Z+40. R0 FMAX")
        # FreeCAD's path is the tool centre: 4 mm outside the outer pass
        self.assertAlmostEqual(max(x for x, _y in self.centre_xy(op)), 27.05)
        self.assertAlmostEqual(cam.path_summary(op)[1], -3.0)

        # by Z levels: all XY passes on a level, then the next one
        cam.set_contour(op, operations.Contour(-3.0, operations.LEFT, z_step_mm=2.0, xy_width_mm=6.0, xy_step_mm=4.0,
                                               order=operations.BY_LEVEL))  # fmt: skip
        blocks = self.nc_blocks(op)
        self.assertEqual(self.plunges(blocks), ["Z-2.", "Z-2.", "Z-3.", "Z-3."])
        corners = [i for i, b in enumerate(blocks) if b == "C X+23. Y+10. DR-"]
        sharp = [i for i, b in enumerate(blocks) if b == "L X+0." and blocks[i - 1] == "L Y+10."]
        self.assertEqual(len(corners), 2)
        self.assertTrue(corners[0] < sharp[0] < corners[1] < sharp[1], blocks)

        # the tool must take each step
        with self.assertRaises(cam.ProjectError, msg="9 mm steps leave material between the passes of an 8 mm tool"):
            cam.set_contour(op, operations.Contour(-3.0, operations.LEFT, xy_width_mm=9.0, xy_step_mm=9.0))
        self.assertEqual(cam.contour_of(op)[1].order, operations.BY_LEVEL, "nothing changed")

    def test_contour_past_the_lines(self):
        body, job, tc, sketch = self.contour_setup()
        right = self.line(sketch, x=20)
        # a toleranced fit: the last pass 0.02 mm past the line, into the part
        contour = operations.Contour(-3.0, operations.LEFT, operations.ARC, xy_width_mm=6.0, xy_step_mm=4.0,
                                     offset_xy_mm=-0.02)  # fmt: skip
        op = cam.add_contour(job, sketch, contour, tc, [right])
        blocks = self.nc_blocks(op)
        self.assertEqual(self.plunges(blocks), ["Z-3.", "Z-3."])
        self.assertIn("C X+17.01 Y-10. DR+", blocks)  # 2.99 mm beside the line: two equal steps of 3.01
        self.assertIn("C X+20.02 Y-10. DR+", blocks)
        self.assertEqual(blocks[blocks.index("C X+20.02 Y-10. DR+") + 1], "L Y+10.")
        self.assertAlmostEqual(max(x for x, _y in self.centre_xy(op)), 16.02)
        # an open line: back to its start above the stock
        back = blocks.index("L X+15.52 Y-10. R0 FMAX")
        self.assertEqual(blocks[back - 1], "L Z+3. R0 FMAX")

    def test_contour_of_an_older_document(self):
        import Path.Op.Engrave as PathEngrave

        body, job, tc, sketch = self.contour_setup()
        op = cam.add_contour(job, sketch, operations.Contour(-3.0), tc, self.square(sketch))
        op.Proxy.__class__ = PathEngrave.ObjectEngrave  # as contours made before the passes
        cam.set_contour(op, operations.Contour(-3.0, z_step_mm=1.0))
        self.assertEqual(type(op.Proxy).__name__, "Contour")
        self.assertEqual(self.plunges(self.nc_blocks(op)), ["Z-1.", "Z-2.", "Z-3."])

    def test_compensation_open_lines(self):
        body, job, tc, sketch = self.contour_setup()
        right, bottom = self.line(sketch, x=20), self.line(sketch, y=-10)
        op = cam.add_contour(job, sketch, operations.Contour(-1.0, operations.LEFT, operations.ARC), tc, [right, bottom])
        self.assertEqual(
            self.nc_blocks(op),
            ["L X+24.5 Y+10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX", "L Z-1. R0 FQ30",
             "L X+21.318 Y+13.182 RL FQ31", "CC X+24.5 Y+10.", "C X+20. Y+10. DR+", "L Y-10.", "L X-20.",
             "CC X-20. Y-14.5", "C X-23.182 Y-11.318 DR+", "L X-20. Y-14.5 R0", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        xy = self.centre_xy(op)
        self.assertAlmostEqual(max(x for x, _y in xy), 24.5)
        self.assertAlmostEqual(min(y for _x, y in xy), -14.5)
        # round the outside corner: one arc there and the two lead arcs
        self.assertEqual(len([c for c in op.Path.Commands if c.Name in ("G2", "G3")]), 3)

    def test_compensation_one_line_or_arc(self):
        import Part

        body, job, tc, sketch = self.contour_setup()
        top = self.line(sketch, y=10)
        arc = operations.ARC
        # one straight line has no plane for OCCT's offset: moved by hand
        for side, backwards, y in ((operations.LEFT, [], 14.0), (operations.RIGHT, [], 6.0), (operations.LEFT, [top], 6.0)):
            op = cam.add_contour(job, sketch, operations.Contour(-1.0, side, arc), tc, [top], backwards)
            cuts = self.centre_xy(op)[2:-2]  # without the lead lines
            self.assertTrue(cuts and all(abs(cy - y) < 1e-6 for _x, cy in cuts[1:-1]), (side, backwards, cuts))
            self.assertEqual(sum(" RL " in b or " RR " in b for b in self.nc_blocks(op)), 1)
            cam.remove_operation(op)
        # one arc: the same centre, the radius smaller on its inside
        arcs = self.doc.addObject("Sketcher::SketchObject", "Arcs")
        arcs.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 12), FreeCAD.Rotation())
        circle = Part.Circle(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 8)
        arcs.addGeometry(Part.ArcOfCircle(circle, 0.0, 1.5))  # counter-clockwise
        arcs.addGeometry(Part.ArcOfCircle(Part.Circle(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 3), 0.0, 1.5))
        self.doc.recompute()
        for side, radius in ((operations.LEFT, 4.0), (operations.RIGHT, 12.0)):
            op = cam.add_contour(job, arcs, operations.Contour(-1.0, side, arc), tc, ["Edge1"])
            cuts = self.centre_xy(op)[2:-2]
            self.assertAlmostEqual(abs(complex(*cuts[0])), radius, msg=side)
            self.assertIn("CC X+0. Y+0.", self.nc_blocks(op))
        with self.assertRaises(cam.ProjectError, msg="the 8 mm tool inside a 3 mm arc"):
            cam.add_contour(job, arcs, operations.Contour(-1.0, operations.LEFT), tc, ["Edge2"])

    def test_compensation_tool_too_big(self):
        body, job, tc, sketch = self.contour_setup()
        circle = next(
            "Edge{}".format(i) for i, e in enumerate(sketch.Shape.Edges, start=1) if e.Curve.TypeId == "Part::GeomCircle"
        )
        # the 8 mm tool does not fit in the 6 mm hole; outside of it, it does
        results = []
        for side in (operations.LEFT, operations.RIGHT):
            try:
                op = cam.add_contour(job, sketch, operations.Contour(-1.0, side, operations.ARC), tc, [circle])
            except cam.ProjectError:
                results.append(None)
                continue
            results.append(op)
            self.assertIn(" RL" if side == operations.LEFT else " RR", " ".join(self.nc_blocks(op)))
            dist = [abs(complex(x, y) - complex(-10, 0)) for x, y in self.centre_xy(op)]
            self.assertAlmostEqual(min(dist[2:-2]), 7.0, msg="4 mm outside the hole")
        self.assertEqual(len([r for r in results if r is None]), 1, results)
        op = next(r for r in results if r is not None)
        inside = operations.RIGHT if op is results[0] else operations.LEFT
        with self.assertRaises(cam.ProjectError):
            cam.set_contour(op, operations.Contour(-1.0, inside, operations.ARC))
        self.assertNotEqual(cam.contour_of(op)[1].compensation, inside, "nothing changed")

    def test_library_tool_for_an_operation(self):
        body, job, tc, sketch = self.contour_setup()  # T21 RVS
        self.assertIs(cam.library_tool(job, self.variant(21, "RVS")), tc, "the setup's own")
        mill = cam.library_tool(job, self.variant(8, "Aluminium"))
        self.assertEqual(int(mill.ToolNumber), 8)
        self.assertEqual([t.number for t in cam.project_tools(job)], [8, 21])
        with self.assertRaises(cam.ToolNumberTaken):
            cam.library_tool(job, self.variant(21, "Staal"))
        self.assertIs(cam.library_tool(job, self.variant(21, "Staal"), replace=True), tc)
        self.assertEqual(tc.AvangardeMaterial, "Staal")

    def test_contour_tool(self):
        body, job, tc, sketch = self.contour_setup()
        op = cam.add_contour(job, sketch, operations.Contour(-1.0, operations.LEFT, operations.ARC), tc, self.square(sketch))
        mill = cam.add_tool(job, self.variant(8, "Aluminium"))  # 12 mm
        cam.set_contour_tool(op, mill)
        self.assertIs(op.ToolController, mill)
        self.assertAlmostEqual(cam.lead_radius(op), 6.5, msg="the default radius follows the tool")
        xy = self.centre_xy(op)
        self.assertAlmostEqual(max(x for x, _y in xy), 26.0, msg="6 mm outside now")
        blocks = self.nc_blocks(op)
        self.assertEqual(blocks[0], "L X+0. Y+16.5 R0 FMAX")
        from avangardecam.post import heidenhain

        text = heidenhain.write(cam.nc_program(self.doc, "TEST"))
        self.assertIn(" TOOL CALL 8 Z ", text)
        self.assertNotIn(" TOOL CALL 21 Z ", text, "T21 stays in the setup, unused")

        # the user's radius stays: too small for the bigger tool with compensation
        cam.set_contour_tool(op, tc)
        cam.set_contour(op, operations.Contour(-1.0, operations.LEFT, operations.ARC, 5.0))
        with self.assertRaises(cam.ProjectError):
            cam.set_contour_tool(op, mill)
        self.assertIs(op.ToolController, tc, "nothing changed")

        other = cam.new_setup(self.doc, cam.zero(job))
        with self.assertRaises(cam.ProjectError, msg="a tool of another setup"):
            cam.set_contour_tool(op, cam.add_tool(other, self.variant(21, "RVS")))

    def test_change_operation(self):
        body, job, tc, sketch = self.contour_setup()
        op = cam.add_contour(job, sketch, operations.Contour(-1.0, operations.LEFT, operations.ARC, 5.0), tc, self.square(sketch))
        mill = cam.add_tool(job, self.variant(8, "Aluminium"))  # 12 mm: the radius 5 is too small for it
        cam.change_operation(op, operations.Contour(-2.0, operations.LEFT, operations.ARC, 7.0), mill)
        self.assertIs(op.ToolController, mill)
        self.assertEqual(cam.contour_of(op)[1], operations.Contour(-2.0, operations.LEFT, operations.ARC, 7.0))
        self.assertAlmostEqual(cam.path_summary(op)[1], -2.0)
        with self.assertRaises(cam.ProjectError):
            cam.change_operation(op, operations.Contour(-3.0, operations.LEFT, operations.ARC, 5.0), mill)
        with self.assertRaises(ValueError):
            cam.change_operation(op, operations.Contour(3.0), tc)
        self.assertIs(op.ToolController, mill, "nothing changed")
        self.assertEqual(cam.contour_of(op)[1].z_depth_mm, -2.0)

    def test_operation_off(self):
        from avangardecam.post import heidenhain

        body, job, tc, sketch = self.contour_setup()
        op = cam.add_contour(job, sketch, operations.Contour(-1.0), tc, self.square(sketch))
        cam.set_active(op, False)
        self.assertEqual(cam.path_summary(op), (0, None))
        self.assertNotIn(" TOOL CALL 21 Z ", heidenhain.write(cam.nc_program(self.doc, "TEST")))
        cam.set_active(op, True)
        self.assertAlmostEqual(cam.path_summary(op)[1], -1.0)
        self.assertIn(" TOOL CALL 21 Z ", heidenhain.write(cam.nc_program(self.doc, "TEST")))

    def test_contour_needs_a_facing_setup(self):
        body, job, tc, _top = self.contour_setup()
        front = self.face(body, (0, -1, 0))
        sketch = geometry.extract_boundary(self.doc, [body], body, front)
        with self.assertRaises(cam.ProjectError):
            cam.add_contour(job, sketch, operations.Contour(-2.0), tc)
        self.assertEqual(cam.setups_for_sketch(self.doc, sketch), [])

        second = cam.new_setup(self.doc, geometry.zero_on_face([body], body, front))
        self.assertEqual(cam.setups_for_sketch(self.doc, sketch), [second])
        tc2 = cam.add_tool(second, self.variant(21, "RVS"))
        # the same tool in two setups keeps its name; FreeCAD's labels stay unique
        self.assertEqual(cam.tool_with_number(second, 21).tool.name, "Iscar Vingerfrees 8mm RVS")
        self.assertEqual(tc2.Label, "T21: Iscar Vingerfrees 8mm RVS (Setup 2)")
        self.assertEqual(tc2.Tool.Label, "Iscar Vingerfrees 8mm RVS (Setup 2)")
        op = cam.add_contour(second, sketch, operations.Contour(-2.0), tc2)
        self.assertAlmostEqual(cam.path_summary(op)[1], -2.0)
        cutting = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]
        ys = [c.Parameters["Y"] for c in cutting if "Y" in c.Parameters]
        self.assertAlmostEqual(min(ys), -6.0)  # the front face is 12 high, zero in the middle
        self.assertAlmostEqual(max(ys), 6.0)

    # -- drilling ----------------------------------------------------------------

    def drilling_setup(self):
        """The part with three holes through it (Ø6 at x -10, Ø4 at x 10,
        Ø3 at y 5), T40 (6.8 mm, 118°) and the sketch of its top."""
        body = self.part
        for i, (x, y, r) in enumerate(((-10, 0, 3), (10, 0, 2), (0, 5, 1.5))):
            hole = self.doc.addObject("Part::Cylinder", "Hole{}".format(i))
            hole.Radius, hole.Height = r, 30
            hole.Placement.Base = FreeCAD.Vector(x, y, -5)
            cut = self.doc.addObject("Part::Cut", "Cut{}".format(i))
            cut.Base, cut.Tool = body, hole
            body = cut
        self.doc.recompute()
        job = cam.ensure_job(self.doc, [body])
        tc = cam.add_tool(job, self.variant(40, "Aluminium"))
        sketch = geometry.extract_boundary(self.doc, [body], body, self.face(body, (0, 0, 1)))
        return body, job, tc, sketch

    def circle(self, sketch, x, y):
        """Name of the sketch's circle around (x, y), sketch coordinates."""
        for name in geometry.sketch_circles(sketch):
            centre = sketch.Placement.inverse().multVec(sketch.Shape.getElement(name).Curve.Center)
            if abs(centre.x - x) < 1e-9 and abs(centre.y - y) < 1e-9:
                return name
        raise AssertionError("no circle at ({}, {})".format(x, y))

    def drill_cycles(self, op):
        return [(c.Name, {k: round(v, 4) for k, v in c.Parameters.items()}) for c in op.Path.Commands
                if c.Name in ("G73", "G81", "G82", "G83")]  # fmt: skip

    def test_drilling_in_picked_order(self):
        body, job, tc, sketch = self.drilling_setup()
        self.assertEqual(len(geometry.sketch_circles(sketch)), 3)
        picked = [self.circle(sketch, 10, 0), self.circle(sketch, -10, 0), self.circle(sketch, 0, 5)]
        op = cam.add_drilling(job, sketch, operations.Drilling(-8.0), tc, picked)
        self.assertEqual(op.Label, "Drilling 1")
        self.assertIs(cam.setup_of(op), job)
        self.assertEqual(cam.drilling_of(op), (sketch, operations.Drilling(-8.0)))
        self.assertIsNone(cam.contour_of(op))
        self.assertEqual(cam.drilling_circles(op), picked)
        self.assertEqual(cam.drilling_holes(op), [(10, 0, 4), (-10, 0, 6), (0, 5, 3)], "the order of the clicks")
        # down to the tip from the sketch plane (Z0), 2 mm above it the cycle starts,
        # pecking 1 mm by default
        cycles = self.drill_cycles(op)
        self.assertEqual({(c[0], c[1]["Q"]) for c in cycles}, {("G83", 1.0)})
        self.assertEqual({(c[1]["Z"], c[1]["R"]) for c in cycles}, {(-8.0, 2.0)})
        # from hole to hole at the 2nd set-up clearance (Q204, 50 as the shop's programs)
        self.assertAlmostEqual(op.SafeHeight.Value, 50.0)
        self.assertAlmostEqual(op.ClearanceHeight.Value, 50.0)
        helper = cam.helper_objects(op)[0]
        self.assertEqual(cam.owner(helper), ("operation", op))
        self.assertNotIn(helper, cam.models(self.doc))

        # the full diameter 8 mm deep: the tip of the 118° drill goes 2.043 deeper
        cam.set_drilling(op, operations.Drilling(-8.0, operations.FULL_DIAMETER))
        self.assertEqual({c[1]["Z"] for c in self.drill_cycles(op)}, {-10.0429})
        # a flat drill has no point
        flat = cam.add_tool(job, self.variant(6, "Aluminium"))
        cam.set_tool(op, flat)
        self.assertIs(op.ToolController, flat)
        self.assertEqual({c[1]["Z"] for c in self.drill_cycles(op)}, {-8.0})
        cam.set_tool(op, tc)

        # zero 2 mm above the part: the holes start at Z-2
        cam.set_zero(job, FreeCAD.Placement(FreeCAD.Vector(0, 0, 14), FreeCAD.Rotation()))
        self.assertEqual({(c[1]["Z"], c[1]["R"]) for c in self.drill_cycles(op)}, {(-12.0429, 0.0)})
        self.assertEqual([h[:2] for h in cam.drilling_holes(op)], [(10, 0), (-10, 0), (0, 5)])

        with self.assertRaises(ValueError):
            cam.set_drilling(op, operations.Drilling(3.0))
        helper = helper.Name
        cam.remove_operation(op)
        self.assertEqual(cam.operations(job), [])
        self.assertIsNone(self.doc.getObject(helper))

    def test_drilling_a_hole_of_arcs(self):
        """A sketch of a STEP model's face has its holes as two half arcs:
        either of them is the hole, drilled once; a lone half is no hole."""
        import Part

        _body, job, tc, sketch = self.drilling_setup()
        z = FreeCAD.Vector(0, 0, 1)
        halves = Part.Circle(FreeCAD.Vector(0, -6, 0), z, 1.25)
        sketch.addGeometry(Part.ArcOfCircle(halves, 0.0, math.pi))
        sketch.addGeometry(Part.ArcOfCircle(halves, math.pi, 2.0 * math.pi))
        sketch.addGeometry(Part.ArcOfCircle(Part.Circle(FreeCAD.Vector(0, -10, 0), z, 1.0), 0.0, math.pi))
        self.doc.recompute()
        self.assertEqual(len(geometry.sketch_circles(sketch)), 4)
        hole = self.circle(sketch, 0, -6)
        lines = geometry.hole_lines(sketch, hole)
        self.assertEqual(len(lines), 2)
        self.assertEqual([geometry.hole_name(sketch, line) for line in lines], [hole, hole])
        lone = [n for n in ("Edge{}".format(i) for i in range(1, len(sketch.Shape.Edges) + 1))
                if isinstance(sketch.Shape.getElement(n).Curve, Part.Circle) and geometry.hole_name(sketch, n) is None]  # fmt: skip
        self.assertEqual(len(lone), 1)
        with self.assertRaises(cam.ProjectError):
            geometry.hole_circles(sketch, lone)
        with self.assertRaises(cam.ProjectError):
            geometry.hole_circles(sketch, [lines[1]])  # a hole goes by its first line

        op = cam.add_drilling(job, sketch, operations.Drilling(-1.5), tc, [hole, self.circle(sketch, 10, 0)])
        self.assertEqual(cam.drilling_holes(op), [(0, -6, 2.5), (10, 0, 4)])
        self.assertEqual({(c[1]["X"], c[1]["Y"], c[1]["Z"]) for c in self.drill_cycles(op)}, {(0, -6, -1.5), (10, 0, -1.5)})  # fmt: skip
        everything = cam.add_drilling(job, sketch, operations.Drilling(-1.5), tc)
        self.assertEqual(len(cam.drilling_holes(everything)), 4)

    def test_drilling_cycles(self):
        _body, job, tc, sketch = self.drilling_setup()
        op = cam.add_drilling(job, sketch, operations.Drilling(-8.0, peck_mm=3.0), tc)
        self.assertEqual(len(cam.drilling_holes(op)), 3, "no circles picked: all of them")
        self.assertEqual({(c[0], c[1]["Q"]) for c in self.drill_cycles(op)}, {("G83", 3.0)})
        cases = (
            (operations.Drilling(-8.0, peck_mm=8.0, chip_break_mm=0.0), "G81"),  # one peck is the whole hole
            (operations.Drilling(-8.0, peck_mm=8.0), "G73"),  # breaking the chip every 4 mm
            (operations.Drilling(-8.0, peck_mm=None, chip_break_mm=2.0), "G73"),
            (operations.Drilling(-8.0, peck_mm=None, chip_break_mm=0.0, dwell_s=0.5), "G82"),
            # FreeCAD cannot peck and dwell in one hole: it pecks (and drills every hole)
            (operations.Drilling(-8.0, peck_mm=3.0, chip_break_mm=1.0, dwell_s=0.5), "G83"),
        )
        for drilling, name in cases:
            cam.set_drilling(op, drilling)
            cycles = self.drill_cycles(op)
            self.assertEqual(len(cycles), 3, drilling)
            self.assertEqual({c[0] for c in cycles}, {name}, drilling)
        cam.set_drilling(op, operations.Drilling(-8.0, peck_mm=None, chip_break_mm=0.0, dwell_s=0.5))
        self.assertEqual({c[1]["P"] for c in self.drill_cycles(op)}, {0.5})

    def test_drilling_nc_program(self):
        from avangardecam.post import heidenhain

        _body, job, tc, sketch = self.drilling_setup()
        picked = [self.circle(sketch, -10, 0), self.circle(sketch, 10, 0)]
        drilling = operations.Drilling(-8.0, operations.FULL_DIAMETER, peck_mm=3.0, chip_break_mm=1.5, dwell_s=0.5)
        cam.add_drilling(job, sketch, drilling, tc, picked)
        cam.set_zero(job, FreeCAD.Placement(FreeCAD.Vector(0, 0, 14), FreeCAD.Rotation()))  # holes start at Z-2
        text = heidenhain.write(cam.nc_program(self.doc, "TEST"))
        lines = text.split("\r\n")
        q = {line.split("=")[0].strip(): line.split(";")[0].strip() for line in lines if line.startswith("    Q")}
        tool = cam.tool_with_number(job, 40).tool
        self.assertEqual(
            [q[n] for n in ("Q200", "Q201", "Q206", "Q202", "Q203", "Q204", "Q257", "Q211", "Q253")],
            ["Q200=2", "Q201=-10.043", "Q206={}".format(heidenhain.plain(tool.feed_xy_mm_min)), "Q202=+3.",
             "Q203=0", "Q204=50", "Q257=1.5", "Q211=0.5", "Q253={}".format(heidenhain.plain(tool.feed_z_mm_min))],
        )  # fmt: skip
        blocks = [line.split(" ", 1)[1] for line in lines if line and not line.startswith(" ")]
        self.assertIn("  * -TOOL#: 40 Diameter: Ø+6.8 -- {}".format(tool.name), blocks)
        calls = [b for b in blocks if b.startswith("CYCL CALL POS")]
        self.assertEqual(calls, ["CYCL CALL POS X-10. Y+0. Z-2 FMAX M3 M8", "CYCL CALL POS X+10. Y+0. Z-2 FMAX"])
        self.assertEqual(blocks[blocks.index(calls[-1]) + 1], "L Z100 R0 FMAX", "the cycle ends high: no Z+40")

    def test_drilling_refuses(self):
        body, job, tc, sketch = self.drilling_setup()
        with self.assertRaises(cam.ProjectError):
            cam.add_drilling(job, sketch, operations.Drilling(-8.0), tc, [self.line(sketch, x=20)])
        front = self.face(body, (0, -1, 0))
        side = geometry.extract_boundary(self.doc, [body], body, front)
        with self.assertRaises(cam.ProjectError):
            cam.add_drilling(job, side, operations.Drilling(-8.0), tc)  # does not face the tool
        second = cam.new_setup(self.doc, geometry.zero_on_face([body], body, front))
        with self.assertRaises(cam.ProjectError):
            cam.add_drilling(second, side, operations.Drilling(-8.0), cam.add_tool(second, self.variant(40, "RVS")))  # no circles  # fmt: skip
        self.assertEqual(cam.operations(job) + cam.operations(second), [])

    def test_drilling_in_a_file(self):
        import os
        import tempfile

        _body, job, tc, sketch = self.drilling_setup()
        picked = [self.circle(sketch, 0, 5), self.circle(sketch, -10, 0)]
        cam.add_drilling(job, sketch, operations.Drilling(-5.0, peck_mm=2.0), tc, picked)
        path = os.path.join(tempfile.mkdtemp(), "drilling.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        op = cam.operations(cam.find_job(self.doc))[0]
        self.assertEqual(cam.drilling_of(op)[1], operations.Drilling(-5.0, peck_mm=2.0))
        op.touch()
        self.doc.recompute()
        self.assertEqual([h[:2] for h in cam.drilling_holes(op)], [(0, 5), (-10, 0)], "the order stays")


    # -- drilling holes picked in the model -----------------------------------------

    def model_with_holes(self):
        """The part (top at Z12) with holes from the top: A Ø6 through at x -15
        (its wall in two halves, as STEP has it), B Ø4 5 mm deep with a flat
        floor at x -5, C Ø5 6 mm deep with a drill point at x 3, D Ø10 3 mm
        deep (a counterbore) over Ø5 through at x 12; E Ø4 from the bottom up
        to Z6 at (0, 6), F Ø4 across the part along Y at x -9.5, Z 4, and G a
        quarter of Ø6 cut off its corner at (-20, -10), not a hole."""
        import Part

        V = FreeCAD.Vector
        shape = Part.makeBox(40, 20, 12, V(-20, -10, 0))
        for angle in (0, 180):  # A in halves
            half = Part.makeCylinder(3, 30, V(-15, 0, -5), V(0, 0, 1), 180)
            half.rotate(V(-15, 0, 0), V(0, 0, 1), angle)
            shape = shape.cut(half)
        shape = shape.cut(Part.makeCylinder(2, 10, V(-5, 0, 7)))  # B
        tip = 2.5 / math.tan(math.radians(59))
        shape = shape.cut(Part.makeCylinder(2.5, 10, V(3, 0, 6)).fuse(Part.makeCone(2.5, 0, tip, V(3, 0, 6), V(0, 0, -1))))  # C  # fmt: skip
        shape = shape.cut(Part.makeCylinder(5, 10, V(12, 0, 9))).cut(Part.makeCylinder(2.5, 30, V(12, 0, -5)))  # D
        shape = shape.cut(Part.makeCylinder(2, 6, V(0, 6, 0)))  # E
        shape = shape.cut(Part.makeCylinder(2, 30, V(-9.5, -15, 4), V(0, 1, 0)))  # F
        shape = shape.cut(Part.makeCylinder(3, 30, V(-20, -10, -5)))  # G: a quarter round at a corner
        obj = self.doc.addObject("Part::Feature", "Holes")
        obj.Shape = shape
        self.doc.removeObject(self.part.Name)
        self.part = obj
        self.doc.recompute()
        return obj

    def wall(self, obj, x, y, radius):
        """Names of the cylinder faces of radius around the axis (x, y, any z)."""
        import Part

        found = []
        for i, f in enumerate(obj.Shape.Faces, start=1):
            if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - radius) < 1e-9:
                c = f.Surface.Center
                if abs(c.x - x) < 1e-9 and abs(c.y - y) < 1e-9 and abs(abs(f.Surface.Axis.z) - 1) < 1e-9:
                    found.append("Face{}".format(i))
        self.assertTrue(found, "no wall at ({}, {}) R{}".format(x, y, radius))
        return found

    def top_edge(self, obj, x, y, z):
        """Name of a circle edge (or arc: A's are halves) centred at (x, y, z)."""
        for i, e in enumerate(obj.Shape.Edges, start=1):
            if hasattr(e.Curve, "Center") and (e.Curve.Center - FreeCAD.Vector(x, y, z)).Length < 1e-9:
                return "Edge{}".format(i)
        raise AssertionError("no circle at ({}, {}, {})".format(x, y, z))

    def test_model_holes(self):
        obj = self.model_with_holes()
        up = FreeCAD.Vector(0, 0, 1)
        halves = self.wall(obj, -15, 0, 3)
        self.assertEqual(len(halves), 2, "STEP-like: the wall in halves")
        for name in (halves[0], halves[1], self.top_edge(obj, -15, 0, 12)):
            hole = geometry.model_hole(obj, name, up)
            self.assertVector(hole.top, (-15, 0, 12))
            self.assertAlmostEqual(hole.radius, 3.0)
            self.assertAlmostEqual(hole.depth.depth_mm, -12.0)
            self.assertTrue(hole.depth.through, name)
            self.assertEqual(sorted(hole.faces), sorted(halves))
        cases = (
            (self.wall(obj, -5, 0, 2)[0], (-5, 0, 12), -5.0, False),  # flat floor
            (self.wall(obj, 3, 0, 2.5)[0], (3, 0, 12), -6.0, False),  # a drill point under the cylinder
            (self.wall(obj, 12, 0, 5)[0], (12, 0, 12), -3.0, False),  # the counterbore: its floor
            (self.wall(obj, 12, 0, 2.5)[0], (12, 0, 9), -9.0, True),  # under it, from its floor
        )
        for name, top, depth, through in cases:
            hole = geometry.model_hole(obj, name, up)
            self.assertVector(hole.top, top)
            self.assertAlmostEqual(hole.depth.depth_mm, depth, msg=top)
            self.assertEqual(hole.depth.through, through, top)
        # from below, the counterbore's hole is 9 deep from the bottom and goes through into it
        hole = geometry.model_hole(obj, self.wall(obj, 12, 0, 2.5)[0], -up)
        self.assertVector(hole.top, (12, 0, 0))
        self.assertEqual(hole.depth, operations.HoleDepth(-9.0, True))
        refused = (
            (self.wall(obj, 0, 6, 2)[0], up),  # E is closed at the top
            (self.wall(obj, -5, 0, 2)[0], -up),  # B seen from below
            (self.face(obj, (0, 0, 1)), up),  # not a hole
            (self.wall(obj, -20, -10, 3)[0], up),  # G: its wall is open
            (self.top_edge(obj, -15, 0, 12), FreeCAD.Vector(1, 0, 0)),  # A across the tool axis
        )
        for name, direction in refused:
            with self.assertRaises(cam.ProjectError, msg=(name, direction)):
                geometry.model_hole(obj, name, direction)
        import Part

        f = next(
            "Face{}".format(i) for i, face in enumerate(obj.Shape.Faces, start=1)
            if isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Axis.y) > 0.5
        )  # fmt: skip
        with self.assertRaises(cam.ProjectError):
            geometry.model_hole(obj, f, up)  # F runs along Y
        # each hole once, in the order picked
        picked = [self.wall(obj, -5, 0, 2)[0], halves[1], halves[0], self.top_edge(obj, -5, 0, 12)]
        self.assertEqual([h.name for h in geometry.model_holes(obj, picked, up)], picked[:2])

    def test_model_hole_remembered(self):
        """A hole is recognised once per shape, element and tool axis; a
        changed model is recognised again, refusals are not remembered."""
        body = self.holed_part()
        up = FreeCAD.Vector(0, 0, 1)
        wall = self.wall(body, -10, 0, 3)[0]
        calls = []
        recognise = geometry._recognise_hole

        def counted(*args):
            calls.append(args[2])
            return recognise(*args)

        geometry._recognise_hole = counted
        try:
            first = geometry.model_hole(body, wall, up)
            again = geometry.model_hole(body, wall, FreeCAD.Vector(0, 0, 1))
            self.assertEqual(calls, [wall], "the same hole is not recognised twice")
            self.assertEqual(again, first)
            again.top.x = 99.0
            self.assertVector(geometry.model_hole(body, wall, up).top, (-10, 0, 12))  # a caller cannot change it
            with self.assertRaises(cam.ProjectError):
                geometry.model_hole(body, wall, FreeCAD.Vector(1, 0, 0))
            with self.assertRaises(cam.ProjectError):
                geometry.model_hole(body, wall, FreeCAD.Vector(1, 0, 0))
            self.assertEqual(len(calls), 3, "a refused hole is checked again")
            # the model changes: the hole is 8 mm now
            body.Tool.Radius = 4
            self.doc.recompute()
            wall = self.wall(body, -10, 0, 4)[0]
            self.assertAlmostEqual(geometry.model_hole(body, wall, up).radius, 4.0)
            self.assertEqual(len(calls), 4)
        finally:
            geometry._recognise_hole = recognise

    def model_drilling(self, drilling):
        obj = self.model_with_holes()
        job = cam.ensure_job(self.doc, [obj])
        tc = cam.add_tool(job, self.variant(40, "Aluminium"))
        picked = [self.wall(obj, -15, 0, 3)[0], self.top_edge(obj, -5, 0, 12), self.wall(obj, 12, 0, 2.5)[0]]
        return obj, job, tc, cam.add_model_drilling(job, obj, drilling, tc, picked), picked

    def test_model_drilling(self):
        from avangardecam.post import heidenhain

        obj, job, tc, op, picked = self.model_drilling(operations.Drilling(None))
        self.assertEqual(cam.drilling_of(op), (obj, operations.Drilling(None)))
        self.assertEqual(cam.drilling_circles(op), picked)
        self.assertEqual(cam.owner(cam.helper_objects(op)[0]), ("operation", op))
        self.assertEqual(cam.models(self.doc), [obj])
        # zero on top of the part (Z12): A and B start at Z0, the hole under the counterbore at Z-3
        self.assertEqual([h[:2] for h in cam.drilling_holes(op)], [(-15, 0), (-5, 0), (12, 0)], "the order picked")
        self.assertEqual([round(t.top, 6) for t in cam.drill_targets(op)], [0, 0, -3])
        tip = 3.4 / math.tan(math.radians(59))  # T40: 6.8 mm, 118°
        cycles = self.drill_cycles(op)
        expected = [(-13 - tip, 2), (-5 - tip, 2), (-13 - tip, -1)]  # through: 1 mm out under the part
        self.assertEqual([(c[1]["Z"], c[1]["R"]) for c in cycles], [(round(z, 4), r) for z, r in expected])
        self.assertAlmostEqual(op.StartDepth.Value, 0.0)
        self.assertAlmostEqual(op.FinalDepth.Value, -13 - tip)
        self.assertAlmostEqual(op.SafeHeight.Value, 50.0)
        # each depth its own cycle, each hole its own top
        lines = heidenhain.write(cam.nc_program(self.doc, "TEST")).split("\r\n")
        q201 = [line.split(";")[0].strip() for line in lines if line.strip().startswith("Q201")]
        self.assertEqual(q201, ["Q201=-15.043", "Q201=-7.043", "Q201=-12.043"])
        calls = [line.split(" ", 1)[1] for line in lines if "CYCL CALL POS" in line]
        self.assertEqual(calls, ["CYCL CALL POS X-15. Y+0. Z0 FMAX M3 M8", "CYCL CALL POS X-5. Y+0. Z0 FMAX", "CYCL CALL POS X+12. Y+0. Z-3 FMAX"])  # fmt: skip

        # the user's depth: the same for every hole, from its top
        cam.set_drilling(op, operations.Drilling(-4.0))
        self.assertEqual([(c[1]["Z"], c[1]["R"]) for c in self.drill_cycles(op)], [(-4.0, 2.0), (-4.0, 2.0), (-7.0, -1.0)])  # fmt: skip
        lines = heidenhain.write(cam.nc_program(self.doc, "TEST")).split("\r\n")
        self.assertEqual(sum(1 for line in lines if "CYCL DEF 205" in line), 1)
        # less under a through hole
        cam.set_drilling(op, operations.Drilling(None, through_mm=0.5))
        self.assertAlmostEqual(self.drill_cycles(op)[0][1]["Z"], round(-12.5 - tip, 4))
        with self.assertRaises(cam.ProjectError):
            cam.set_drilling(op, operations.Drilling(None, start_mm=9.0))  # below the bottom of B
        # the zero 2 mm lower: everything 2 mm higher
        cam.set_zero(job, FreeCAD.Placement(FreeCAD.Vector(0, 0, 10), FreeCAD.Rotation()))
        self.assertEqual([round(t.top, 6) for t in cam.drill_targets(op)], [2, 2, -1])
        helper = cam.helper_objects(op)[0].Name
        cam.remove_operation(op)
        self.assertIsNone(self.doc.getObject(helper))
        self.assertIn(obj, cam.models(self.doc))

    def test_model_drilling_refuses(self):
        obj = self.model_with_holes()
        job = cam.ensure_job(self.doc, [obj])
        tc = cam.add_tool(job, self.variant(40, "Aluminium"))
        for picked in ([], [self.wall(obj, 0, 6, 2)[0]], [self.face(obj, (0, 0, 1))]):
            with self.assertRaises(cam.ProjectError, msg=picked):
                cam.add_model_drilling(job, obj, operations.Drilling(None), tc, picked)
        # the circles of a sketch have no depth of their own
        sketch = geometry.extract_boundary(self.doc, [obj], obj, self.face(obj, (0, 0, 1)))
        with self.assertRaises(cam.ProjectError):
            cam.add_drilling(job, sketch, operations.Drilling(None), tc)
        self.assertEqual(cam.operations(job), [])

    def test_model_drilling_in_a_file(self):
        import os
        import tempfile

        _obj, _job, _tc, op, picked = self.model_drilling(operations.Drilling(None, peck_mm=2.0))
        path = os.path.join(tempfile.mkdtemp(), "model_drilling.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        op = cam.operations(cam.find_job(self.doc))[0]
        self.assertEqual(cam.drilling_of(op)[1], operations.Drilling(None, peck_mm=2.0))
        self.assertEqual(cam.drilling_circles(op), picked)
        op.touch()
        self.doc.recompute()
        self.assertEqual([h[:2] for h in cam.drilling_holes(op)], [(-15, 0), (-5, 0), (12, 0)], "the order stays")

    # -- thread milling ----------------------------------------------------------------

    def thread_setup(self):
        """The part with two Ø2.5 holes through it (at x -10 and 10) and a Ø2
        one at (0, 5), T216 (M3 thread mill, Ø2.4, P0.5) and the sketch of its top."""
        body = self.part
        for i, (x, y, r) in enumerate(((-10, 0, 1.25), (10, 0, 1.25), (0, 5, 1.0))):
            hole = self.doc.addObject("Part::Cylinder", "Hole{}".format(i))
            hole.Radius, hole.Height = r, 30
            hole.Placement.Base = FreeCAD.Vector(x, y, -5)
            cut = self.doc.addObject("Part::Cut", "Cut{}".format(i))
            cut.Base, cut.Tool = body, hole
            body = cut
        self.doc.recompute()
        job = cam.ensure_job(self.doc, [body])
        tc = cam.add_tool(job, self.variant(216, "Aluminium"))
        sketch = geometry.extract_boundary(self.doc, [body], body, self.face(body, (0, 0, 1)))
        return body, job, tc, sketch

    def helices(self, op):
        return [c for c in op.Path.Commands if c.Name in ("G2", "G3")]

    def test_thread_milling(self):
        from avangardecam.post import heidenhain

        _body, job, tc, sketch = self.thread_setup()
        picked = [self.circle(sketch, 10, 0), self.circle(sketch, -10, 0)]
        thread = operations.ThreadMilling(3.0, -6.5)
        op = cam.add_thread_milling(job, sketch, thread, tc, picked)
        self.assertEqual(op.Label, "Thread milling 1")
        self.assertEqual(cam.thread_milling_of(op), (sketch, thread))
        self.assertIsNone(cam.drilling_of(op))
        self.assertEqual(cam.drilling_circles(op), picked)
        self.assertEqual([(t.x, t.y, t.top) for t in cam.drill_targets(op)], [(10, 0, 0), (-10, 0, 0)])
        # the tool centre: 0.3 from the hole's centre (1.5 - 1.2), clockwise, 26 half turns a pass, 2 passes
        helices = self.helices(op)
        self.assertEqual(len(helices), 2 * 2 * 26)
        self.assertEqual({c.Name for c in helices}, {"G2"})
        first = helices[0].Parameters
        self.assertAlmostEqual(first["X"], 9.7)
        self.assertAlmostEqual(first["I"], -0.3)
        self.assertAlmostEqual(first["Z"], -0.25)
        self.assertAlmostEqual(cam.path_summary(op)[1], -6.5)
        self.assertEqual((op.MajorDiameter.Value, op.Pitch.Value, op.Passes, op.ThreadName), (3.0, 0.5, 2, "M3"))
        self.assertEqual((op.Direction, op.ThreadOrientation), ("Conventional", "RightHand"))
        self.assertAlmostEqual(op.StartDepth.Value, 0.0)
        self.assertAlmostEqual(op.FinalDepth.Value, -6.5)
        self.assertAlmostEqual(op.SafeHeight.Value, 10.0, msg="from hole to hole")

        blocks = [line.split(" ", 1)[1] for line in heidenhain.write(cam.nc_program(self.doc, "TEST")).split("\r\n") if line]  # fmt: skip
        self.assertIn("*- Thread Milling", blocks)
        self.assertIn("TOOL CALL 216 Z S12000 DL0 DR0;Draadfrees M3 P=0.5 Alu", blocks)
        self.assertEqual(blocks.count("CP IPA-180. IZ-0.25 DR-"), 104)
        self.assertEqual([b for b in blocks if " RR " in b], ["L X+11.5 RR FQ31"] * 2 + ["L X-8.5 RR FQ31"] * 2)

        cam.set_thread_milling(op, operations.ThreadMilling(3.0, -4.0, passes=1))
        self.assertEqual(len(self.helices(op)), 2 * 16)
        # the zero 2 mm above the part: the threads start at Z-2
        cam.set_zero(job, FreeCAD.Placement(FreeCAD.Vector(0, 0, 14), FreeCAD.Rotation()))
        self.assertAlmostEqual(cam.path_summary(op)[1], -6.0)
        self.assertAlmostEqual(op.SafeHeight.Value, 8.0)

        with self.assertRaises(cam.ProjectError):
            cam.set_tool(op, cam.add_tool(job, self.variant(40, "Aluminium")))  # a drill
        with self.assertRaises(cam.ProjectError):
            cam.set_thread_milling(op, operations.ThreadMilling(2.4, -4.0))  # as big as the tool
        self.assertIs(op.ToolController, tc)
        helper = cam.helper_objects(op)[0].Name
        cam.remove_operation(op)
        self.assertIsNone(self.doc.getObject(helper))

    def test_thread_milling_refuses(self):
        _body, job, tc, sketch = self.thread_setup()
        thread = operations.ThreadMilling(3.0, -6.5)
        with self.assertRaises(cam.ProjectError):
            cam.add_thread_milling(job, sketch, thread, tc)  # all circles: the Ø2 one is too small for Ø2.4
        drill = cam.add_tool(job, self.variant(40, "Aluminium"))
        with self.assertRaises(cam.ProjectError):
            cam.add_thread_milling(job, sketch, thread, drill, [self.circle(sketch, 10, 0)])
        self.assertEqual(cam.operations(job), [])
        self.assertEqual([o for o in self.doc.Objects if o.Name.startswith("HoleCircles")], [], "nothing left over")

    def test_model_thread_milling(self):
        obj = self.model_with_holes()
        job = cam.ensure_job(self.doc, [obj])
        tc = cam.add_tool(job, self.variant(218, "Staal"))  # M5 thread mill, Ø4, P0.8
        a, c = self.wall(obj, -15, 0, 3)[0], self.wall(obj, 3, 0, 2.5)[0]
        thread = operations.ThreadMilling(6.0, -5.0, passes=1)
        op = cam.add_model_thread_milling(job, obj, thread, tc, [c, a])
        self.assertEqual(cam.thread_milling_of(op), (obj, thread))
        self.assertEqual([(t.x, t.y) for t in cam.drill_targets(op)], [(3, 0), (-15, 0)], "the order picked")
        self.assertAlmostEqual(cam.path_summary(op)[1], -5.0)
        # C is 6 deep: a thread of 6.5 does not fit, A goes through
        with self.assertRaises(cam.ProjectError):
            cam.set_thread_milling(op, operations.ThreadMilling(6.0, -6.5))
        with self.assertRaises(cam.ProjectError):
            cam.add_model_thread_milling(job, obj, thread, tc, [self.wall(obj, -5, 0, 2)[0]])  # B Ø4: the tool is Ø4
        deep = cam.add_model_thread_milling(job, obj, operations.ThreadMilling(6.0, -20.0, passes=1), tc, [a])
        self.assertAlmostEqual(cam.path_summary(deep)[1], -20.0)

    def test_first_operation_among_tools(self):
        """The first operation of a setup with several tools takes the one
        chosen: FreeCAD would ask which (in FreeCADCmd it failed)."""
        _body, job, t40, sketch = self.drilling_setup()
        t6 = cam.add_tool(job, self.variant(6, "Aluminium"))
        contour = cam.add_contour(job, sketch, operations.Contour(-1.0), t6)
        self.assertIs(contour.ToolController, t6)
        cam.remove_operation(contour)
        drilling = cam.add_drilling(job, sketch, operations.Drilling(-1.5), t40, [self.circle(sketch, 10, 0)])
        self.assertIs(drilling.ToolController, t40)

    def test_first_thread_milling_among_tools(self):
        _body, job, tc, sketch = self.thread_setup()
        cam.add_tool(job, self.variant(40, "Aluminium"))
        op = cam.add_thread_milling(job, sketch, operations.ThreadMilling(3.0, -3.0, passes=1), tc, [self.circle(sketch, 10, 0)])  # fmt: skip
        self.assertIs(op.ToolController, tc)

    def test_first_adaptive_among_tools(self):
        _plate, job, tc = self.adaptive_setup()
        cam.add_tool(job, self.variant(40, "Aluminium"))
        op = cam.add_adaptive(job, operations.Adaptive(-5.0, z_step_mm=1.5), tc)
        self.assertIs(op.ToolController, tc)

    def test_thread_milling_in_a_file(self):
        import os
        import tempfile

        _body, job, tc, sketch = self.thread_setup()
        picked = [self.circle(sketch, -10, 0), self.circle(sketch, 10, 0)]
        cam.add_thread_milling(job, sketch, operations.ThreadMilling(3.0, -3.0, passes=1), tc, picked)
        path = os.path.join(tempfile.mkdtemp(), "thread_milling.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        op = cam.operations(cam.find_job(self.doc))[0]
        self.assertEqual(cam.thread_milling_of(op)[1], operations.ThreadMilling(3.0, -3.0, passes=1))
        op.touch()
        self.doc.recompute()
        self.assertEqual(len(self.helices(op)), 2 * 12)
        self.assertAlmostEqual(self.helices(op)[0].Parameters["X"], -10.3, msg="the order stays")

    # -- adaptive clearing ---------------------------------------------------------------

    def adaptive_setup(self):
        """A plate 40 x 20 with its top at Z-2 of the setup (zero on top of the
        part), a boss 10 x 6 on its left edge up to Z0 and a pocket 14 x 10
        down to Z-5 at x 0..14; the stock 1 mm around and on top (Z+1); T5
        (Ø6, Aluminium)."""
        import Part

        shape = Part.makeBox(40, 20, 10, FreeCAD.Vector(-20, -10, 0))
        shape = shape.fuse(Part.makeBox(10, 6, 2, FreeCAD.Vector(-20, -3, 10)))
        shape = shape.cut(Part.makeBox(14, 10, 3, FreeCAD.Vector(0, -5, 7))).removeSplitter()
        plate = self.doc.addObject("Part::Feature", "Plate")
        plate.Shape = shape
        self.doc.recompute()
        job = cam.ensure_job(self.doc, [plate])
        tc = cam.add_tool(job, self.variant(5, "Aluminium"))
        return plate, job, tc

    def floor(self, obj, z, x=None):
        """Name of the flat face of obj (part coordinates) facing up at z (and over x)."""
        for i, f in enumerate(obj.Shape.Faces, start=1):
            if f.findPlane() is None or abs(f.BoundBox.ZMin - z) > 1e-9 or f.BoundBox.ZLength > 1e-9:
                continue
            if geometry.outward_normal(obj.Shape, f).z > 0.5 and (x is None or f.BoundBox.XMin - 1e-9 <= x <= f.BoundBox.XMax + 1e-9):  # fmt: skip
                return "Face{}".format(i)
        raise AssertionError("no floor at {}".format(z))

    def cuts(self, op):
        """{Z: [((x0, y0), (x1, y1)), ...]} of the cutting moves of a path in
        the plane (arcs as chords of 16 parts)."""
        found = {}
        at = None
        for c in op.Path.Commands:
            if c.Name not in ("G0", "G1", "G2", "G3"):
                continue
            p = c.Parameters
            to = tuple(p.get(a, at[i] if at else 0.0) for i, a in enumerate("XYZ"))
            if at is not None and c.Name != "G0" and abs(to[2] - at[2]) < 1e-9 and to[:2] != at[:2]:
                points = [at[:2], to[:2]]
                if c.Name in ("G2", "G3"):
                    centre = (at[0] + p.get("I", 0.0), at[1] + p.get("J", 0.0))
                    r = math.hypot(at[0] - centre[0], at[1] - centre[1])
                    a0 = math.atan2(at[1] - centre[1], at[0] - centre[0])
                    a1 = math.atan2(to[1] - centre[1], to[0] - centre[0])
                    sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
                    if c.Name == "G2":
                        sweep -= 2 * math.pi
                    points = [(centre[0] + r * math.cos(a0 + sweep * k / 16), centre[1] + r * math.sin(a0 + sweep * k / 16)) for k in range(17)]  # fmt: skip
                level = found.setdefault(round(to[2], 6), [])
                level.extend(zip(points, points[1:]))
            at = to
        return found

    @staticmethod
    def segment_distance(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
        return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)

    @staticmethod
    def box_distance(p, x0, y0, x1, y1):
        """Distance of p from the rectangle, 0 inside."""
        return math.hypot(max(x0 - p[0], 0.0, p[0] - x1), max(y0 - p[1], 0.0, p[1] - y1))

    def assertCleared(self, segments, points, reach, msg):
        """Every point is within reach of a cutting move: the tool went over it."""
        left = [p for p in points if not any(self.segment_distance(p, a, b) <= reach for a, b in segments)]
        self.assertEqual(left, [], msg)

    @staticmethod
    def taken_off(segments, rect, radius, cell=0.2):
        """(conventional, climb): cells of a stock (rect: x0, y0, x1, y1) on
        one level the tool (radius) takes off going along segments in their
        order, on its left (conventional milling, the spindle turning
        clockwise) and on its right (climb milling)."""
        import numpy as np

        x0, y0, x1, y1 = rect
        X, Y = np.meshgrid(np.arange(x0 + cell / 2, x1, cell), np.arange(y0 + cell / 2, y1, cell), indexing="ij")
        material = np.ones(X.shape, bool)
        reach = int(radius / cell) + 2
        left = right = 0
        for a, b in segments:
            length = math.dist(a, b)
            if length == 0.0:
                continue
            way = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            steps = max(1, int(length / (2 * cell)))
            before = a
            for k in range(1, steps + 1):
                c = (a[0] + (b[0] - a[0]) * k / steps, a[1] + (b[1] - a[1]) * k / steps)
                i, j = int((c[0] - x0) / cell), int((c[1] - y0) / cell)
                window = (slice(max(0, i - reach), max(0, i + reach + 1)), slice(max(0, j - reach), max(0, j + reach + 1)))
                x, y, m = X[window], Y[window], material[window]
                hit = m & ((x - c[0]) ** 2 + (y - c[1]) ** 2 <= radius * radius)
                if hit.any():
                    side = way[0] * (y[hit] - before[1]) - way[1] * (x[hit] - before[0])
                    left += int((side > 0).sum())
                    right += int((side <= 0).sum())
                    m[hit] = False
                before = c
        return left, right

    def outside_model(self, p, level):
        """How far p is from the material of the test model above level, seen from the tool."""
        if level >= 0.0:
            return math.inf  # the top of the boss: nothing above
        boss = self.box_distance(p, -20, -3, -10, 3)
        if level >= -2.0:
            return boss
        if 0 <= p[0] <= 14 and -5 <= p[1] <= 5:  # in the pocket, its walls
            return min(p[0], 14 - p[0], p[1] + 5, 5 - p[1])
        return self.box_distance(p, -20, -10, 20, 10)

    def test_adaptive_around_the_model(self):
        """Around the whole model from the top of the stock: a level on every
        floor (the top of the boss and of the plate are cut, FreeCAD's own
        Adaptive left the plate's top uncut; on the boss's own level only
        around it), the model never cut, the pocket entered on a helix,
        around the part down to Z-Depth."""
        plate, job, tc = self.adaptive_setup()
        self.assertEqual(cam.suggested_adaptive_depth(job), -5.0, "the lowest floor")
        adaptive = operations.Adaptive(-5.0, z_step_mm=1.5)
        op = cam.add_adaptive(job, adaptive, tc)
        self.assertEqual(cam.adaptive_of(op), (plate, adaptive))
        self.assertEqual(op.Label, "Adaptive 1")
        self.assertEqual(cam.adaptive_levels(job, adaptive), [0.0, -0.5, -2.0, -3.5, -5.0])
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [0.0, -0.5, -2.0, -3.5, -5.0])
        for level, segments in cuts.items():
            near = min(self.outside_model(p, level) for segment in segments for p in segment)
            self.assertGreater(near, 3.0 - 0.02, "the tool keeps out of the model at Z{}".format(level))
        grid = [(x * 1.0, y * 1.0) for x in range(-21, 22) for y in range(-11, 12)]
        boss = [(x * 1.0, y * 1.0) for x in range(-20, -9) for y in range(-3, 4)]
        self.assertCleared(cuts[0.0], boss, 3.1, "the stock over the top of the boss")
        # over the stock (21 x 11): beside it the tool may move in the air, the area
        # around the boss grown out of the stock for it to come in from there, so at
        # the stock's edge its centre goes up to the edge of that area (1.5 x Ø)
        over = [b for _a, b in cuts[0.0] if self.box_distance(b, -21, -11, 21, 11) == 0.0]
        far = max(self.box_distance(b, -20, -3, -10, 3) for b in over)  # not where it came in from
        self.assertLess(far, 1.5 * 6.0 + 0.1, "on the boss's own level only around it")
        plate_top = [p for p in grid if self.box_distance(p, -20, -3, -10, 3) > 0.1]
        self.assertCleared(cuts[-0.5], plate_top, 3.1, "the rest of the stock on the next Z step")
        self.assertCleared(cuts[-2.0], plate_top, 3.1, "the top of the plate, to the boss")
        pocket = [(x * 1.0, y * 1.0) for x in range(1, 14) for y in range(-4, 5)]  # a round tool leaves the corners
        self.assertCleared(cuts[-5.0], pocket, 3.1, "the pocket's floor")
        outside = [p for p in grid if self.box_distance(p, -20, -10, 20, 10) > 0.1]
        self.assertCleared(cuts[-5.0], outside, 3.1, "the stock around the part, down to Z-Depth")
        helices = [c for c in op.Path.Commands if c.Name in ("G2", "G3") and "Z" in c.Parameters]
        self.assertTrue(helices, "into the pocket on a helix")
        # FreeCAD's own values follow the user's, for expert mode
        self.assertEqual((op.ModelAwareExperiment, op.UseHelixArcs, op.StepOver), (True, True, 20))
        self.assertAlmostEqual(op.FinalDepth.Value, -5.0)
        self.assertAlmostEqual(op.StartDepth.Value, 1.0)
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0)
        self.assertAlmostEqual(op.ClearanceHeight.Value, 20.0)

    def test_adaptive_floor_between_steps(self):
        """The user's plate: on a level only a floor has (a counterbore 6
        deep between the Z steps of 8) the tool cleared all round the part;
        now only around that floor, the rest on the next Z step. An area of
        such a level open to the edge of the stock: in from outside it,
        going down clear of the stock, never all round it."""
        _plate, job, tc = self.adaptive_setup()
        adaptive = operations.Adaptive(-8.0, z_step_mm=4.0)
        op = cam.add_adaptive(job, adaptive, tc)
        self.assertEqual(adaptive.full_levels(1.0), [-3.0, -7.0, -8.0])
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [0.0, -2.0, -3.0, -5.0, -7.0, -8.0])
        # over the stock (21 x 11) only in the pocket; beside the stock the tool takes
        # the stock's 1 mm beside the plate as far as the area around the pocket's floor goes
        in_pocket = [p for segment in cuts[-5.0] for p in segment if self.box_distance(p, -21, -11, 21, 11) == 0.0]
        self.assertEqual([p for p in in_pocket if not (3.0 - 0.02 <= p[0] <= 11.0 + 0.02 and abs(p[1]) <= 2.0 + 0.02)], [], "only in the pocket")  # fmt: skip
        beside = [p for segment in cuts[-5.0] for p in segment if self.box_distance(p, -21, -11, 21, 11) > 0.0]
        reach = 1.5 * 6.0 + 6.0 + 1.0  # around the floor, grown out of the stock by Ø and 1 mm
        self.assertTrue(all(self.box_distance(p, 0, -5, 14, 5) <= reach + 1e-6 for p in beside), "never all round the part")
        pocket = [(x * 1.0, y * 1.0) for x in range(1, 14) for y in range(-4, 5)]
        self.assertCleared(cuts[-5.0], pocket, 3.1, "the pocket's floor")
        grid = [(x * 1.0, y * 1.0) for x in range(-21, 22) for y in range(-11, 12)]
        outside = [p for p in grid if self.box_distance(p, -20, -10, 20, 10) > 0.1]
        for level in (-3.0, -7.0, -8.0):
            self.assertCleared(cuts[level], outside, 3.1, "round the part on the Z step Z{}".format(level))
        for level, segments in cuts.items():
            near = min(self.outside_model(p, level) for segment in segments for p in segment)
            self.assertGreater(near, 3.0 - 0.02, "the tool keeps out of the model at Z{}".format(level))
        # the tool goes down beside the stock (21 x 11) 1 mm clear of it, never overlapping it
        # (not the 0.5 mm down after a way over cleared floor)
        at, beside = None, []
        for c in op.Path.Commands:
            if c.Name not in ("G0", "G1", "G2", "G3"):
                continue
            to = tuple(c.Parameters.get(a, at[i] if at else 0.0) for i, a in enumerate("XYZ"))
            if at is not None and c.Name == "G1" and to[:2] == at[:2] and to[2] < at[2] - 1.0:
                if self.box_distance(to, -21, -11, 21, 11) > 0.0:
                    beside.append(to)
            at = to
        self.assertTrue(beside, "in from beside the stock")
        for to in beside:
            self.assertGreater(self.box_distance(to, -21, -11, 21, 11), 3.0 + 1.0 - 0.01, "down at {}".format(to))
        # no Z step: all but the floors at Z-Depth at once, its depth for the cutting length
        short = cam.add_tool(job, self.variant(2, "Aluminium"))  # Ø3, cuts 4 mm
        with self.assertRaises(cam.ProjectError) as caught:
            cam.add_adaptive(job, operations.Adaptive(-5.0), short)  # +1 to -5 at once, the floors between no steps
        self.assertIn("cutting length", str(caught.exception))

    def test_adaptive_floor_level_near_the_stock_edge(self):
        """The user's plate (70 x 40, the stock 2.1 mm wider each side, 5.1
        longer, 2.6 on top; a Ø6 tool, step over 10 %): the area around the
        top of the plate, cleared on its own level, went 4.1 mm out of the
        stock on the long sides. libarea came in from outside on the short
        ends only, took the rest for cleared, and in the user's file its
        finishing pass took 2 mm off the long sides with the material on
        the left of the tool (conventional milling: 85 % of all it took
        off); the top kept its 2.5 mm. Now all the stock over the plate
        goes, climb milling."""
        import Part

        plate = self.doc.addObject("Part::Feature", "Plate")
        plate.Shape = Part.makeBox(70, 40, 10, FreeCAD.Vector(-35, -20, -10))
        self.doc.recompute()
        job = cam.ensure_job(self.doc, [plate])
        cam.set_stock(job, stock.BoxStock(2.1, 2.1, 5.1, 5.1, 0.0, 2.6))
        tc = cam.add_tool(job, self.variant(5, "Aluminium"))
        adaptive = operations.Adaptive(-2.0, step_over_percent=10.0, finish_xy_mm=0.2, finish_z_mm=0.1)
        op = cam.add_adaptive(job, adaptive, tc)
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [0.1, -1.9])
        b = cam.stock_bounds(job)
        self.assertBounds(b, (-37.1, -25.1, -10.0, 37.1, 25.1, 2.6))
        grid = [(x * 1.0, y * 1.0) for x in range(-37, 38, 2) for y in range(-25, 26, 2)]
        self.assertCleared(cuts[0.1], grid, 3.1, "the stock over the plate")
        conventional, climb = self.taken_off(cuts[0.1], (b.x_min, b.y_min, b.x_max, b.y_max), 3.0)
        self.assertLess(conventional, 0.01 * (conventional + climb), "climb milling")

    def test_adaptive_floor_level_arcs_meeting_in_the_stock(self):
        """A demo plate: two pockets 3.5 deep
        open to the end of the plate, their floors' corners there 15.5
        apart, the stock 5 mm longer; a Ø6 tool. Around the floors (grown
        by 1.5 x Ø and Finish XY on their own level) the arcs met 0.04 mm
        in the stock: the area out of the stock fell apart, FreeCAD's
        fusion kept two faces and libarea got the area as it was. It
        cleared nothing and gave its finishing pass only, starting 70 mm
        from where the tool went down: the tool fed straight across the rib
        between the pockets, 3.4 mm into the top of the part. Now the
        pockets are cleared, climb milling, the tool never in the part."""
        import Part

        shape = Part.makeBox(40, 60, 10, FreeCAD.Vector(-20, -30, -10))
        for y in (7.75, -25.0):
            shape = shape.cut(Part.makeBox(20, 17.25, 3.5, FreeCAD.Vector(-20, y, -3.5)))
        plate = self.doc.addObject("Part::Feature", "Plate")
        plate.Shape = shape.removeSplitter()
        self.doc.recompute()
        job = cam.ensure_job(self.doc, [plate])
        cam.set_stock(job, stock.BoxStock(5.0, 1.0, 1.0, 1.0, 0.0, 0.0))
        tc = cam.add_tool(job, self.variant(5, "Aluminium"))
        adaptive = operations.Adaptive(-8.0, step_over_percent=10.0, finish_xy_mm=0.2, finish_z_mm=0.1)
        op = cam.add_adaptive(job, adaptive, tc)
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [-3.4, -7.9])
        # the model over the pockets' level: the rib between them, their side walls, the plate's other end
        walls = [(-20, -7.75, 20, 7.75), (-20, 25, 20, 30), (-20, -30, 20, -25), (0, -30, 20, 30)]
        closest = min(
            min(self.box_distance(p, *w) for w in walls)
            for a, b in cuts[-3.4]
            for k in range(int(math.dist(a, b) / 0.25) + 2)
            for p in [(a[0] + (b[0] - a[0]) * min(1.0, k * 0.25 / max(math.dist(a, b), 1e-9)),
                       a[1] + (b[1] - a[1]) * min(1.0, k * 0.25 / max(math.dist(a, b), 1e-9)))]
        )  # fmt: skip
        self.assertGreater(closest, 3.0 - 0.02, "the tool keeps out of the model, also between two points")
        floors = [(x + 0.5, sign * (y + 0.5)) for x in range(-20, -3) for y in range(8, 24) for sign in (1, -1)]
        self.assertCleared(cuts[-3.4], floors, 3.1, "the pockets' floors")
        b = cam.stock_bounds(job)
        conventional, climb = self.taken_off(cuts[-3.4], (b.x_min, b.y_min, b.x_max, b.y_max), 3.0)
        self.assertLess(conventional, 0.01 * (conventional + climb), "climb milling")

    def test_adaptive_cut_apart_from_the_tool(self):
        """A cut of libarea not starting where the tool is (its finishing
        pass, when it cleared nothing): the tool goes over the safe height
        to it, not straight through what is between; libarea's small gaps
        (0.03 mm, 0.1 after a way over cleared floor) stay."""
        from types import SimpleNamespace

        from avangardecam.engine import adaptive as engine_adaptive
        from avangardecam.model import clearing, nc

        paths = (
            (clearing.CUT, ((0.0, 0.0), (5.0, 0.0))),
            (clearing.LINK, ((5.03, 0.0), (9.0, 0.0))),
            (clearing.CUT, ((9.1, 0.0), (12.0, 0.0))),
            (clearing.CUT, ((60.0, 40.0), (61.0, 40.0))),
        )
        joined = engine_adaptive._joined(SimpleNamespace(Label="Adaptive 1"), (0.0, 0.0), paths, 1.0)
        self.assertEqual(joined, paths[:3] + ((clearing.UP, ((60.0, 40.0),)),) + paths[3:])
        moves = clearing.moves([clearing.Piece((-3.4,), 0.0, None, (0.0, 0.0), joined)], 2.0, 0.5, 5.0, 300.0, 1250.0)
        at = moves[0]
        for move in moves[1:]:
            if move.kind != nc.RAPID and abs(move.z - at.z) < 1e-9:
                self.assertLess(math.dist((at.x, at.y), (move.x, move.y)), 10.0, "no long cut at the level")
            at = move

    def test_adaptive_sliver_holes(self):
        """A hole smaller than 1 mm² in an area to clear (where two arcs
        came into the stock) goes, unless the model is in it."""
        import Part

        from avangardecam.engine import adaptive as engine_adaptive

        plane = Part.makePlane(10, 10)
        sliver = Part.makePlane(0.1, 0.05, FreeCAD.Vector(5, 5, 0))
        face = plane.cut(sliver).Faces[0]
        self.assertEqual(len(face.Wires), 2)
        self.assertEqual(len(engine_adaptive._without_slivers(face, Part.Shape()).Wires), 1, "the sliver goes")
        self.assertAlmostEqual(engine_adaptive._without_slivers(face, Part.Shape()).Area, 100.0)
        self.assertEqual(len(engine_adaptive._without_slivers(face, sliver).Wires), 2, "the model in it: stays")
        bigger = plane.cut(Part.makePlane(2, 2, FreeCAD.Vector(4, 4, 0))).Faces[0]
        self.assertEqual(len(engine_adaptive._without_slivers(bigger, Part.Shape()).Wires), 2, "4 mm²: stays")

    def test_adaptive_tight_counterbore(self):
        """A counterbore Ø8 for a Ø6 tool with Finish XY 0.2 (the user's
        plate): libarea's helix ¼ of the diameter does not go in there (0.05
        mm to spare, missed by where its polygon's points fall), ⅛ does, and
        neither the helix nor the clearing comes into Finish XY."""
        import types

        import area
        import Part
        import Path.Op.Adaptive as PathAdaptive

        from avangardecam.engine import adaptive as engine_adaptive

        obj = types.SimpleNamespace(KeepToolDownRatio=3.0, Tolerance=0.1, Label="Adaptive")
        adaptive = operations.Adaptive(-10.0, step_over_percent=10.0, finish_xy_mm=0.2)
        centre = (-20.0, 16.2)  # one of the places libarea misses it at
        circle = Part.Face(Part.Wire(Part.makeCircle(4.0, FreeCAD.Vector(centre[0], centre[1], 0))))
        path2d = PathAdaptive.convertTo2d(engine_adaptive._discretized(circle))
        stock2d = [[(-50.0, -50.0), (50.0, -50.0), (50.0, 50.0), (-50.0, 50.0)]]
        inside = area.AdaptiveOperationType.ClearingInside
        self.assertEqual(engine_adaptive._clear(obj, adaptive, 6.0, 1.5, inside, stock2d, path2d), [], "libarea: no way in on ¼")
        cleared = engine_adaptive._clear_area(obj, adaptive, 6.0, inside, stock2d, path2d)
        self.assertEqual(len(cleared), 1, "in on ⅛")
        helix, start, paths = cleared[0]
        self.assertIsNotNone(helix)
        self.assertLessEqual(math.dist(helix, start), 0.375 + 1e-6, "a helix Ø0.75")
        # the tool's centre within 4 - 0.2 - 3 of the counterbore's (and libarea's tolerance)
        far = max(math.dist(p, centre) for _kind, points in paths for p in points + (start,))
        self.assertLessEqual(far, 0.8 + 0.1, "Finish XY left on the wall")

    def test_adaptive_start_z(self):
        """Start Z: the top of the range of the levels (the user's): on the
        top of the boss with Z-Depth there, only the stock over it; under
        it, the boss's top left as it is and the levels from Start Z down."""
        _plate, job, tc = self.adaptive_setup()
        top_only = operations.Adaptive(0.0, start_z_mm=0.0)
        op = cam.add_adaptive(job, top_only, tc)
        self.assertEqual(sorted(self.cuts(op), reverse=True), [0.0], "the stock over the boss")
        self.assertAlmostEqual(op.StartDepth.Value, 0.0)
        under = operations.Adaptive(-5.0, z_step_mm=2.0, start_z_mm=-0.1)
        self.assertEqual(cam.adaptive_levels(job, under), [-2.0, -2.1, -4.1, -5.0], "no level on the boss's top")
        cam.set_adaptive(op, under)
        self.doc.recompute()
        self.assertEqual(sorted(self.cuts(op), reverse=True), [-2.0, -2.1, -4.1, -5.0])
        self.assertAlmostEqual(op.StartDepth.Value, -0.1)
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0, msg="above the stock still")
        with self.assertRaises(cam.ProjectError):
            cam.set_adaptive(op, operations.Adaptive(0.0, start_z_mm=-1.0))

    def side_hole_plate(self):
        """A plate 40 x 20 x 10 (zero on its top) with a drilled hole Ø5 into
        its side, along Y, 12 deep with a 118° point, its axis at Z-5 (the
        test plate A has three such holes)."""
        import Part

        plate = Part.makeBox(40, 20, 10, FreeCAD.Vector(-20, -10, 0))
        drill = Part.makeCylinder(2.5, 12, FreeCAD.Vector(0, 10, 5), FreeCAD.Vector(0, -1, 0))
        tip = Part.makeCone(2.5, 0, 2.5 / math.tan(math.radians(59)), FreeCAD.Vector(0, -2, 5), FreeCAD.Vector(0, -1, 0))
        return plate.cut(drill.fuse(tip)).removeSplitter()

    def test_solid_projection_beside_a_side_hole(self):
        """Sliced through the top of a side hole, FreeCAD's projection of the
        plate above came out empty (on the user's plate 11 mm² instead of
        24775: the clearing went through it); AvangardeCam's sees the whole plate."""
        from avangardecam.engine import adaptive as engine_adaptive

        shape = self.side_hole_plate()
        shape.translate(FreeCAD.Vector(0, 0, -10))
        for z in (-2.95, -2.75, -2.6, -4.0, -9.0):
            seen = engine_adaptive.solid_projection(shape, z)
            self.assertAlmostEqual(seen.Area, 800.0, delta=0.5, msg="the whole plate above Z{}".format(z))
        self.assertTrue(engine_adaptive.solid_projection(shape, 0.5).isNull(), "nothing above the plate")

    def test_adaptive_beside_a_side_hole(self):
        """A level through the top of a side hole: the tool stays out of the plate."""
        plate = self.doc.addObject("Part::Feature", "SideHole")
        plate.Shape = self.side_hole_plate()
        self.doc.recompute()
        job = cam.ensure_job(self.doc, [plate])
        tc = cam.add_tool(job, self.variant(5, "Aluminium"))
        op = cam.add_adaptive(job, operations.Adaptive(-2.75, start_z_mm=-0.1), tc)
        cuts = self.cuts(op)
        self.assertEqual(list(cuts), [-2.75])
        near = min(self.box_distance(p, -20, -10, 20, 10) for segment in cuts[-2.75] for p in segment)
        self.assertGreater(near, 3.0 - 0.02, "around the plate only")

    def test_adaptive_finishing_allowances(self):
        """The allowances stay on the model's walls and floors, and above
        Z-Depth beside the part too (the user's file: Z-Depth -1.5 on the
        plate's floor with 0.1 left on it, the tool went down to -1.5 around
        the part's edge)."""
        _plate, job, tc = self.adaptive_setup()
        adaptive = operations.Adaptive(-2.0, finish_xy_mm=0.2, finish_z_mm=0.2)
        op = cam.add_adaptive(job, adaptive, tc)
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [0.2, -1.8])
        self.assertAlmostEqual(cam.path_summary(op)[1], -1.8, msg="nothing below Z-Depth + 0.2")
        self.assertGreater(min(self.outside_model(p, -1.0) for s in cuts[-1.8] for p in s), 3.2 - 0.02, "0.2 off the boss")  # fmt: skip
        self.assertCleared(cuts[-1.8], [(5.0, 7.0), (18.0, -8.0), (20.5, 0.0), (0.0, -10.5)], 3.1, "the plate and the stock beside it")  # fmt: skip
        # picked floor, as in the user's file
        plate = cam.models(self.doc)[0]
        op = cam.add_adaptive(job, operations.Adaptive(-2.0, finish_xy_mm=0.2, finish_z_mm=0.1), tc, plate, [self.floor(plate, 10.0, x=18.0)])  # fmt: skip
        self.assertEqual(sorted(self.cuts(op), reverse=True), [-1.9])
        self.assertAlmostEqual(cam.path_summary(op)[1], -1.9)

    def test_adaptive_picked_floors(self):
        """Picked floors: the tool clears their area (its centre up to their
        edges) and comes in from outside where it reaches the stock's edge."""
        plate, job, tc = self.adaptive_setup()
        boss = self.floor(plate, 12.0)
        self.assertEqual(cam.suggested_adaptive_depth(job, plate, [boss]), 0.0)
        op = cam.add_adaptive(job, operations.Adaptive(0.0), tc, plate, [boss])
        self.assertEqual(cam.adaptive_floors(op), [boss])
        cuts = self.cuts(op)
        self.assertEqual(list(cuts), [0.0])
        self.assertCleared(cuts[0.0], [(-19.5, 2.5), (-10.5, -2.5), (-15.0, 0.0)], 3.1, "the top of the boss")
        # where the tool is in the stock, it is no farther than its radius from the boss
        for a, b in cuts[0.0]:
            for p in (a, b):
                for k in range(16):
                    edge = (p[0] + 2.9 * math.cos(k * math.pi / 8), p[1] + 2.9 * math.sin(k * math.pi / 8))
                    if self.box_distance(edge, -21, -11, 21, 11) == 0.0:
                        self.assertLess(self.box_distance(edge, -20, -3, -10, 3), 3.0 + 0.1, p)
        # the plate's top: all of it around the boss and beside it, in from outside
        top = self.floor(plate, 10.0, x=18.0)
        self.assertEqual(cam.suggested_adaptive_depth(job, plate, [top]), -2.0, "the pocket is not under it")
        op = cam.add_adaptive(job, operations.Adaptive(-2.0, z_step_mm=1.5), tc, plate, [top])
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [-0.5, -2.0])
        self.assertGreater(min(self.box_distance(p, -20, -3, -10, 3) for s in cuts[-2.0] for p in s), 3.0 - 0.02)
        beside = [(x * 1.0, y) for x in range(-20, -9) for y in (5.0, 8.0, -5.0, -8.0)]
        self.assertCleared(cuts[-2.0], beside + [(19.0, 9.0), (5.0, 0.0)], 3.1, "beside the boss and the far end")
        for bad in ([self.face(plate, (1, 0, 0))], [self.face(plate, (0, 0, -1))]):  # a wall, the bottom
            with self.assertRaises(cam.ProjectError, msg=bad):
                cam.add_adaptive(job, operations.Adaptive(-2.0), tc, plate, bad)

    def test_adaptive_refuses(self):
        plate, job, tc = self.adaptive_setup()
        with self.assertRaises(cam.ProjectError):
            cam.add_adaptive(job, operations.Adaptive(1.0), tc)  # not below the top of the stock
        with self.assertRaises(cam.ProjectError):
            cam.add_adaptive(job, operations.Adaptive(-2.0), cam.add_tool(job, self.variant(40, "RVS")))  # a drill
        short = cam.add_tool(job, self.variant(2, "Aluminium"))  # Ø3, cuts 4 mm
        with self.assertRaises(cam.ProjectError) as caught:
            cam.add_adaptive(job, operations.Adaptive(-12.0), short)  # -5 to -12 at once
        self.assertIn("cutting length", str(caught.exception))
        self.assertEqual(cam.operations(job), [], "nothing made")

    def test_adaptive_nc_program(self):
        from avangardecam.post import heidenhain

        _plate, job, tc = self.adaptive_setup()
        op = cam.add_adaptive(job, operations.Adaptive(-5.0, z_step_mm=1.5), tc)
        text = heidenhain.write(cam.nc_program(self.doc, "ADAPTIVE"))
        lines = [line.split(" ", 1)[1] for line in text.split("\r\n") if line]
        self.assertIn("*- Adaptive Clearing", lines)
        start = next(i for i, line in enumerate(lines) if line.startswith("FN0: Q31="))
        self.assertTrue(lines[start + 1].endswith(" R0 FMAX") and lines[start + 1].startswith("L X"))
        self.assertEqual(lines[start + 2 : start + 4], ["L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX"])
        self.assertTrue(any(line.startswith("CP IPA-180. IZ-") for line in lines), "the helix into the pocket")
        self.assertIn("L Z-1.5 R0 FMAX", lines, "0.5 mm over the cleared floor of Z-2")
        self.assertEqual(lines[-8], "L Z+40. R0 FMAX")
        self.assertFalse(lines[-9].startswith("L Z"), "from the last cut straight up to Z+40: {}".format(lines[-9]))

    def test_adaptive_changes_and_file(self):
        import os
        import tempfile

        plate, job, tc = self.adaptive_setup()
        op = cam.add_adaptive(job, operations.Adaptive(-2.0), tc, plate, [self.floor(plate, 10.0, x=18.0)])
        cam.set_adaptive(op, operations.Adaptive(-2.0, z_step_mm=1.5))
        self.assertEqual(sorted(self.cuts(op), reverse=True), [-0.5, -2.0])
        with self.assertRaises(cam.ProjectError):
            cam.set_adaptive(op, operations.Adaptive(3.0))
        self.assertEqual(cam.adaptive_of(op)[1], operations.Adaptive(-2.0, z_step_mm=1.5), "a refused change")
        t7 = cam.add_tool(job, self.variant(7, "Aluminium"))  # Ø10
        cam.set_tool(op, t7)
        near = min(self.box_distance(p, -20, -3, -10, 3) for s in self.cuts(op)[-2.0] for p in s)
        self.assertGreater(near, 5.0 - 0.02, "Ø10 keeps 5 mm off the boss")
        with self.assertRaises(cam.ProjectError):
            cam.set_tool(op, cam.add_tool(job, self.variant(40, "RVS")))
        path = os.path.join(tempfile.mkdtemp(), "adaptive.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        job = cam.find_job(self.doc)
        op = cam.operations(job)[0]
        self.assertEqual(cam.adaptive_of(op)[1], operations.Adaptive(-2.0, z_step_mm=1.5))
        self.assertEqual(type(op.Proxy).__module__, "avangardecam.engine.adaptive")
        count = len(op.Path.Commands)
        op.touch()
        self.doc.recompute()
        # the part read back from the file differs in the last digits, libarea's path a little
        self.assertAlmostEqual(len(op.Path.Commands) / count, 1.0, delta=0.1)
        self.assertEqual(sorted(self.cuts(op), reverse=True), [-0.5, -2.0])
        # the zero point turned: the floor and the levels go with it
        cam.rotate_zero(job, 90.0)
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [-0.5, -2.0])
        # new X = old Y: the boss (old x -20..-10, y -3..3) is now at x -3..3, y 10..20
        self.assertGreater(min(self.box_distance(p, -3, 10, 3, 20) for s in cuts[-2.0] for p in s), 5.0 - 0.02)


if __name__ == "__main__":
    unittest.main()
