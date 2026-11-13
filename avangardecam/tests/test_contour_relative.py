# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Relative of a contour: Start Z and Z-Depth from the Z of each line, or
from the setup's zero point. The model tests are plain Python:

    python3 -m unittest avangardecam.tests.test_contour_relative   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import json
import unittest

from avangardecam.model import operations

try:
    import FreeCAD
except ImportError:
    FreeCAD = None


class TestModel(unittest.TestCase):
    def test_relative_at_first(self):
        self.assertTrue(operations.Contour(-1.0).relative)
        old = operations.from_json('{"kind": "contour", "z_depth_mm": -1.0}')
        self.assertTrue(old.relative, "files from before Relative: from the lines, as they were")

    def test_base(self):
        relative = operations.Contour(-1.0)
        self.assertEqual(relative.base_mm(-4.0), -4.0, "from the lines")
        fixed = operations.Contour(-10.0, relative=False)
        self.assertEqual(fixed.base_mm(-4.0), 0.0, "from the zero point, wherever the lines are")
        self.assertEqual(fixed.levels(), [-10.0], "levels from base_mm")

    def test_json(self):
        fixed = operations.Contour(-10.0, start_z_mm=-2.0, z_step_mm=4.0, relative=False)
        text = operations.to_json(fixed)
        self.assertIs(json.loads(text)["relative"], False)
        self.assertEqual(operations.from_json(text), fixed)

    def test_validate(self):
        with self.assertRaises(ValueError):
            operations.Contour(-1.0, relative=1).validate()
        with self.assertRaisesRegex(ValueError, "zero point"):
            operations.Contour(-2000.0, relative=False).validate()
        with self.assertRaisesRegex(ValueError, "the lines"):
            operations.Contour(-2000.0).validate()
        with self.assertRaises(ValueError):
            operations.Contour(-1.0, start_z_mm=-2.0, relative=False).validate()  # Z-Depth above Start Z


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestEngine(unittest.TestCase):
    """A block 40 x 20 x 10 with an island 10 x 10 x 4 on it; the zero
    point on the island's top, so the plate's top is at Z-4."""

    def setUp(self):
        import Part

        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry
        from avangardecam.model import library
        from avangardecam.tests import test_engine
        from avangardecam.tests.test_model import LIBRARY

        self.cam = cam
        self.doc = FreeCAD.newDocument("AvangardeCamRelative")
        V = FreeCAD.Vector
        shape = Part.makeBox(40, 20, 10, V(-20, -10, 0)).fuse(Part.makeBox(10, 10, 4, V(-15, -5, 10))).removeSplitter()
        stepped = self.doc.addObject("Part::Feature", "Stepped")
        stepped.Shape = shape
        self.doc.recompute()
        self.job = cam.ensure_job(self.doc, [stepped])
        variant = next(e for e in library.load(LIBRARY) if e.number == 21 and e.workpiece_material == "RVS")
        self.tc = cam.add_tool(self.job, variant)
        tops = sorted(
            ("Face{}".format(i) for i, f in enumerate(shape.Faces, start=1)
             if f.findPlane() is not None and geometry.outward_normal(shape, f).getAngle(V(0, 0, 1)) < 1e-9),
            key=lambda name: -shape.getElement(name).BoundBox.ZMax,
        )  # fmt: skip
        self.island = geometry.extract_boundary(self.doc, [stepped], stepped, tops[0])  # Z 14
        self.plate = geometry.extract_boundary(self.doc, [stepped], stepped, tops[1])  # Z 10
        cam.set_zero(self.job, geometry.zero_on_face([stepped], stepped, tops[0]))
        self.right = test_engine.TestEngine.line(self, self.plate, x=20)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def contour(self, contour):
        picks = [(self.island, [], ()), (self.plate, [self.right], ())]
        return self.cam.add_contour_sketches(self.job, picks, contour, self.tc)

    def cutting_z(self, op):
        """Z of the cutting moves, in the order of the path."""
        moves = [c for c in op.Path.Commands if c.Name in ("G1", "G2", "G3") and "Z" in c.Parameters]
        return [round(c.Parameters["Z"], 6) for c in moves]

    def test_relative_from_each_line(self):
        op = self.contour(operations.Contour(-1.0))
        self.assertEqual(sorted(set(self.cutting_z(op))), [-5.0, -1.0], "1 mm below each line")
        self.assertEqual(self.cam.contour_depths(op), (0.0, -5.0))

    def test_not_relative_from_the_zero_point(self):
        op = self.contour(operations.Contour(-10.0, relative=False))
        self.assertEqual(set(self.cutting_z(op)), {-10.0}, "Z-10 for the island and the plate")
        self.assertEqual(self.cam.contour_depths(op), (0.0, -10.0))
        self.assertAlmostEqual(self.cam.path_summary(op)[1], -10.0)
        self.assertGreaterEqual(op.SafeHeight.Value, 2.0, "2 mm above the stock's top")

    def test_not_relative_by_z_steps(self):
        op = self.contour(operations.Contour(-6.0, z_step_mm=4.0, relative=False))
        runs = [z for i, z in enumerate(self.cutting_z(op)) if i == 0 or z != self.cutting_z(op)[i - 1]]
        self.assertEqual(runs, [-4.0, -6.0, -4.0, -6.0], "the island, then the plate, each by the same steps")

    def test_lines_one_after_the_other(self):
        """Lines at other heights: the tool goes up between them."""
        op = self.contour(operations.Contour(-1.0))
        commands = list(op.Path.Commands)
        last_island = max(i for i, c in enumerate(commands) if c.Name == "G1" and round(c.Parameters.get("Z", 1), 6) == -1.0)  # fmt: skip
        first_plate = min(i for i, c in enumerate(commands) if c.Name == "G1" and round(c.Parameters.get("Z", 1), 6) == -5.0)  # fmt: skip
        between = [c.Parameters["Z"] for c in commands[last_island:first_plate] if c.Name == "G0" and "Z" in c.Parameters]
        self.assertTrue(between and max(between) >= op.ClearanceHeight.Value - 1e-6, "up to the clearance height")

    def test_switched(self):
        op = self.contour(operations.Contour(-1.0))
        self.cam.set_contour(op, operations.Contour(-1.0, relative=False))
        self.assertEqual(set(self.cutting_z(op)), {-1.0}, "unchecked: Z-1 for both")
        self.cam.set_contour(op, operations.Contour(-3.0, start_z_mm=-3.0, relative=False))
        self.assertEqual(set(self.cutting_z(op)), {-3.0}, "above the plate: one pass at Z-3")
        self.cam.set_contour(op, operations.Contour(-1.0))
        self.assertEqual(sorted(set(self.cutting_z(op))), [-5.0, -1.0], "checked again")

    def test_zero_point_moved(self):
        """Not relative, Z-Depth stays where it is from the zero point;
        relative, it stays where it is on the part."""
        fixed = self.contour(operations.Contour(-10.0, relative=False))
        relative = self.contour(operations.Contour(-1.0))
        above = self.cam.zero(self.job)
        above.Base.z += 2.0
        self.cam.set_zero(self.job, above)
        self.doc.recompute()
        self.assertEqual(set(self.cutting_z(fixed)), {-10.0})
        self.assertEqual(sorted(set(self.cutting_z(relative))), [-7.0, -3.0])

    def test_old_files(self):
        """A contour saved before Relative (no field in its JSON) cuts as before."""
        op = self.contour(operations.Contour(-1.0))
        data = json.loads(op.AvangardeOperation)
        del data["relative"]
        op.AvangardeOperation = json.dumps(data)
        self.cam.set_contour(op, self.cam.contour_of(op)[1])
        self.assertEqual(sorted(set(self.cutting_z(op))), [-5.0, -1.0])


if __name__ == "__main__":
    unittest.main()
