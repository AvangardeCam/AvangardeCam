# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Deburring tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_deburring   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import json
import math
import unittest

from avangardecam.model import deburring, operations, tools

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

# the shop's chamfer mills as the tool library has them
T29 = tools.Tool("Afbraamfrees 6mm Alu", "Chamfer", 6.0, angle_deg=90.0, tip_diameter_mm=0.0)
T162 = tools.Tool("Afbraamfrees 10mm RVS", "Chamfer", 10.0, angle_deg=90.0, tip_diameter_mm=2.5)
V60 = tools.Tool("V 60", "VBit", 10.0, angle_deg=60.0, tip_diameter_mm=0.0)
MILL = tools.Tool("VHM Frees 6mm", "Endmill", 6.0)


class TestModel(unittest.TestCase):
    def test_cut_from_the_chamfer(self):
        # the tip 0.5 below a 0.5 chamfer: 1 mm deep, the sharp tip's centre 0.5 beside the edge
        self.assertEqual(deburring.cut(deburring.Deburring(), T29), (1.0, 0.5))
        # the user's own deburring with T29 (Contour tooling, XY offset 0.85, Z-Depth -1): a 0.15 chamfer
        self.assertEqual(deburring.chamfer_of(1.0, 0.85, T29), (0.15, 0.85))
        self.assertEqual(deburring.cut(deburring.Deburring(0.15, 0.85), T29), (1.0, 0.85))
        # a tip of 2.5 mm: the centre its radius further out, the depth the same
        self.assertEqual(deburring.cut(deburring.Deburring(0.5, 0.5), T162), (1.0, 1.75))
        # a 60° cone is steeper: deeper for the same chamfer
        depth, offset = deburring.cut(deburring.Deburring(0.5, 0.5), V60)
        slope = math.tan(math.radians(30))
        self.assertAlmostEqual(depth, 0.5 / slope + 0.5, places=6)
        self.assertAlmostEqual(offset, 0.5 * slope, places=6)
        self.assertEqual(deburring.chamfer_of(depth, offset, V60), (0.5, 0.5))

    def test_advanced_own_values(self):
        own = deburring.Deburring(advanced=True, z_depth_mm=-1.2, offset_xy_mm=0.7)
        self.assertEqual(deburring.cut(own, T29), (1.2, 0.7))
        self.assertEqual(deburring.chamfer_of(1.2, 0.7, T29), (0.5, 0.7))
        with self.assertRaisesRegex(ValueError, "below the lines"):
            deburring.Deburring(advanced=True, z_depth_mm=0.5).validate()

    def test_contour(self):
        contour = deburring.to_contour(deburring.check(deburring.Deburring(0.15, 0.85), T29), T29)
        self.assertEqual(
            contour,
            operations.Contour(-1.0, operations.OFF, operations.NONE, offset_xy_mm=0.85, start_z_mm=0.0, relative=True),
        )
        self.assertEqual(contour.levels(), [-1.0], "one pass")
        right_arc = deburring.Deburring(side=operations.RIGHT, approach=operations.ARC, lead_radius_mm=2.0)
        contour = deburring.to_contour(right_arc, T29)
        self.assertEqual((contour.arc_side, contour.approach, contour.lead_radius_mm), (operations.RIGHT, operations.ARC, 2.0))  # fmt: skip
        # Start / End contour only with Advanced
        ends = deburring.Deburring(start_extend_mm=-2.0, end_extend_mm=3.0)
        self.assertEqual((deburring.to_contour(ends, T29).start_extend_mm, deburring.to_contour(ends, T29).end_extend_mm), (0.0, 0.0))  # fmt: skip
        own = deburring.Deburring(advanced=True, z_depth_mm=-1.0, offset_xy_mm=0.6, start_extend_mm=-2.0, end_extend_mm=3.0)
        self.assertEqual((deburring.to_contour(own, T29).start_extend_mm, deburring.to_contour(own, T29).end_extend_mm), (-2.0, 3.0))  # fmt: skip

    def test_check(self):
        with self.assertRaisesRegex(ValueError, "not a chamfer mill"):
            deburring.check(deburring.Deburring(), MILL)
        # the cone reaches Ø6 at the face: chamfer + tip at most 3 mm with T29
        deburring.check(deburring.Deburring(2.5, 0.5), T29)
        with self.assertRaisesRegex(ValueError, "at most 2.5 mm"):
            deburring.check(deburring.Deburring(2.6, 0.5), T29)
        with self.assertRaisesRegex(ValueError, "cut into the wall"):
            deburring.check(deburring.Deburring(advanced=True, z_depth_mm=-1.0, offset_xy_mm=1.0), T162)
        with self.assertRaisesRegex(ValueError, "makes none"):
            deburring.check(deburring.Deburring(advanced=True, z_depth_mm=-1.0, offset_xy_mm=1.0), T29)
        for bad in (deburring.Deburring(0.0), deburring.Deburring(tip_mm=-0.1), deburring.Deburring(side="up")):
            with self.assertRaises(ValueError):
                bad.validate()

    def test_json(self):
        own = deburring.Deburring(0.3, 0.6, operations.RIGHT, operations.ARC, 3.0, True, -1.5, 0.7, -1.0, 2.0)
        text = deburring.to_json(own)
        self.assertEqual(json.loads(text)["kind"], "deburring")
        self.assertEqual(deburring.from_json(text), own)


@unittest.skipIf(FreeCAD is None, "needs FreeCAD")
class TestEngine(unittest.TestCase):
    def setUp(self):
        from avangardecam.model import library
        from avangardecam.tests.test_model import LIBRARY

        self.doc = FreeCAD.newDocument("AvangardeCamDeburringTest")
        box = self.doc.addObject("Part::Box", "Part")
        box.Length, box.Width, box.Height = 40, 20, 12
        box.Placement.Base = FreeCAD.Vector(-20, -10, 0)
        hole = self.doc.addObject("Part::Cylinder", "Hole")
        hole.Radius, hole.Height = 3, 30
        hole.Placement.Base = FreeCAD.Vector(-10, 0, -5)
        self.body = self.doc.addObject("Part::Cut", "Body")
        self.body.Base, self.body.Tool = box, hole
        self.doc.recompute()
        self.library = {e.id: e for e in library.load(LIBRARY)}

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def setup(self, tool_id="t29-aluminium-afbraamfrees-6mm-alu"):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry

        job = cam.ensure_job(self.doc, [self.body])
        tc = cam.add_tool(job, self.library[tool_id])
        up = FreeCAD.Vector(0, 0, 1)
        faces = self.body.Shape.Faces
        number = next(i for i, f in enumerate(faces, start=1) if f.findPlane() is not None and geometry.outward_normal(self.body.Shape, f).getAngle(up) < 1e-9)  # fmt: skip
        name = "Face{}".format(number)
        sketch = geometry.extract_boundary(self.doc, [self.body], self.body, name)
        return job, tc, sketch

    def rings(self, op):
        """Distance of the cutting moves' ends from the hole's centre and
        the largest |x| (the outline), the lowest Z."""
        ends = [c.Parameters for c in op.Path.Commands if c.Name in ("G1", "G2", "G3") and "X" in c.Parameters]
        near = [math.hypot(p["X"] + 10, p["Y"]) for p in ends if abs(p["X"] + 10) < 5 and abs(p["Y"]) < 5]
        return round(max(near), 6), round(max(abs(p["X"]) for p in ends), 6), round(min(p["Z"] for p in ends), 6)

    def test_all_lines_of_the_top(self):
        """All lines of an extracted face, as the user's Contour 1: the
        outline deburred outside, the hole inside, on the left."""
        from avangardecam.engine import deburring as engine
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry

        job, tc, sketch = self.setup()
        values = deburring.Deburring(0.15, 0.85)
        op = engine.add_deburring(job, [(sketch, [], [])], values, tc)
        self.assertEqual(op.Label, "Deburring 1")
        self.assertEqual(engine.deburring_of(op), (sketch, values))
        self.assertEqual(cam.contour_of(op)[1].offset_xy_mm, 0.85)
        self.assertEqual(self.rings(op), (2.15, 20.85, -1.0))
        # a plain contour is no deburring
        plain = cam.add_contour(job, sketch, operations.Contour(-1.0), tc)
        self.assertEqual(plain.Label, "Contour 1")
        self.assertIsNone(engine.deburring_of(plain))

        # new values: one change, the contour follows
        cam.change_operation(op, deburring.Deburring(0.5, 0.5), tc)
        self.assertEqual(engine.deburring_of(op)[1], deburring.Deburring(0.5, 0.5))
        self.assertEqual(self.rings(op), (2.5, 20.5, -1.0))
        tool = cam._tool_from_controller(tc)
        self.assertEqual(engine.on_material(job, engine.op_picks(op), engine.deburring_of(op)[1], tool), [])
        # the right side: the outline inside, the hole outside, both on the material: said, but made
        right = deburring.Deburring(0.5, 0.5, operations.RIGHT)
        found = engine.on_material(job, [(sketch, [], [])], right, tool)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(all(text.startswith(sketch.Label + ": Edge") for text in found), found)
        cam.change_operation(op, right, tc)
        self.assertEqual(self.rings(op)[:2], (3.5, 19.5))
        self.assertEqual(len(engine.on_material(job, engine.op_picks(op), right, tool)), 2)
        # the hole turned round (its arrows): only the outline left
        hole = next(name for name in geometry.all_lines(sketch) if sketch.Shape.Edges[int(name[4:]) - 1].Curve.TypeId == "Part::GeomCircle")  # fmt: skip
        self.assertEqual(len(engine.on_material(job, [(sketch, [], [hole])], right, tool)), 1)

    def test_tool_follows(self):
        from avangardecam.engine import deburring as engine
        from avangardecam.engine import freecad_cam as cam

        job, tc, sketch = self.setup("t162-rvs-afbraamfrees-8mm-rvs")
        op = engine.add_deburring(job, [(sketch, [], [])], deburring.Deburring(0.5, 0.5), tc)
        self.assertEqual(cam.contour_of(op)[1].offset_xy_mm, 1.5, "the Ø2 tip's radius + 0.5")
        # another variant of T162 (Ø2.5 tip): worked out again
        cam.replace_tool(job, tc, self.library["t162-staal-afbraamfrees-10mm-staal"])
        self.assertEqual(cam.contour_of(op)[1].offset_xy_mm, 1.75)
        self.assertEqual(self.rings(op)[:2], (1.25, 21.75))
        # another tool: T29, sharp
        t29 = cam.add_tool(job, self.library["t29-aluminium-afbraamfrees-6mm-alu"])
        cam.set_tool(op, t29)
        self.assertIs(op.ToolController, t29)
        self.assertEqual(cam.contour_of(op)[1].offset_xy_mm, 0.5)
        # an end mill cannot deburr: refused, nothing changed
        mill = cam.add_tool(job, self.library["t5-aluminium-vhm-alu-frees-6mm"])
        with self.assertRaisesRegex(cam.ProjectError, "not a chamfer mill"):
            cam.set_tool(op, mill)
        self.assertIs(op.ToolController, t29)
        with self.assertRaisesRegex(cam.ProjectError, "too small"):
            cam.change_operation(op, deburring.Deburring(2.8, 0.5), t29)
        self.assertEqual(engine.deburring_of(op)[1], deburring.Deburring(0.5, 0.5))

    def test_advanced_and_arc(self):
        from avangardecam.engine import deburring as engine
        from avangardecam.engine import freecad_cam as cam

        job, tc, sketch = self.setup()
        own = deburring.Deburring(advanced=True, z_depth_mm=-1.2, offset_xy_mm=0.7)
        op = engine.add_deburring(job, [(sketch, [], [])], own, tc)
        self.assertEqual(self.rings(op), (2.3, 20.7, -1.2))
        # on an arc of 1 mm: the tool goes down 1 mm beside the lines, inside the hole, outside the outline
        arc = deburring.Deburring(approach=operations.ARC, lead_radius_mm=1.0)
        cam.change_operation(op, arc, tc)
        self.assertEqual(engine.deburring_of(op)[1], arc)
        self.assertEqual(cam.lead_radius(op), 1.0)
        downs = [c.Parameters for c in op.Path.Commands if c.Name == "G1" and "Z" in c.Parameters and c.Parameters["Z"] < -0.5]
        plunges = [p for p in downs if "X" in p]
        self.assertTrue(plunges)
        ring = [round(math.hypot(p["X"] + 10, p["Y"]), 6) for p in plunges if abs(p["X"] + 10) < 5 and abs(p["Y"]) < 5]
        self.assertIn(1.5, ring, "the hole: 1 mm inside the ring of 2.5 mm")

    def test_approach_arc_that_does_not_fit(self):
        """In the 6 mm hole the default arc (3.5 mm) bends round past the
        line the tool runs 0.5 mm beside: said, for the hole only."""
        from avangardecam.engine import deburring as engine
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import lead_check

        job, tc, sketch = self.setup()
        tool = cam._tool_from_controller(tc)
        arc = deburring.Deburring(approach=operations.ARC)
        found = engine.leads_too_close(job, [(sketch, [], [])], arc, tool)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(len(found[0].lines), 1, "the hole's circle")
        self.assertLess(found[0].closest_mm, 0.5)
        self.assertEqual(found[0].offset_mm, 0.5)
        self.assertIn("does not fit", lead_check.text(found))
        # a radius of 1 mm fits; straight down is not checked
        self.assertEqual(engine.leads_too_close(job, [(sketch, [], [])], deburring.Deburring(approach=operations.ARC, lead_radius_mm=1.0), tool), [])  # fmt: skip
        self.assertEqual(engine.leads_too_close(job, [(sketch, [], [])], deburring.Deburring(), tool), [])
        # Contour tooling the same: Off with arc and an XY offset (a chamfer mill by hand); made anyway
        contour = operations.Contour(-1.0, operations.OFF, operations.ARC, offset_xy_mm=0.5)
        op = cam.add_contour(job, sketch, contour, tc)
        self.assertEqual(len(lead_check.for_op(op)), 1)
        self.assertEqual(lead_check.for_op(op, operations.Contour(-1.0, operations.OFF, operations.ARC)), [], "no offset: not checked")  # fmt: skip
        self.assertEqual(lead_check.for_op(op, operations.Contour(-1.0, operations.LEFT, operations.ARC)), [], "RL: not checked")  # fmt: skip

    def test_program_title(self):
        from avangardecam.engine import deburring as engine
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.model import nc
        from avangardecam.post import heidenhain

        job, tc, sketch = self.setup()
        engine.add_deburring(job, [(sketch, [], [])], deburring.Deburring(), tc)
        cam.add_contour(job, sketch, operations.Contour(-1.0), tc)
        program = cam.nc_program(self.doc, "TEST")
        self.assertEqual([op.kind for op in program.setups[0].operations], [nc.DEBURRING, nc.CONTOUR])
        text = heidenhain.write(program)
        self.assertIn("*- Deburring\r\n", text)
        self.assertIn("*- Contourbewerking\r\n", text)
