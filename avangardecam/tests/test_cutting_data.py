# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The cutting data of an operation (model/engine cutting_data): its own
spindle speed and feeds over the tool's, in the NC program."""

import re
import unittest

import FreeCAD

from avangardecam.model import cutting_data, machine, nc, operations, tools
from avangardecam.post import heidenhain
from avangardecam.tests.test_post import MILL_8, MILL_12, blocks, contour, drill_cycle, drilling, program, setup

OWN = cutting_data.CuttingData(spindle_rpm=2500.0, feed_xy_mm_min=400.0)


class TestModel(unittest.TestCase):
    def test_own_keeps_what_differs(self):
        tool = tools.Tool("Mill", "Endmill", 8.0, spindle_rpm=3000, feed_xy_mm_min=525, feed_z_mm_min=150)
        self.assertEqual(cutting_data.own(tool, (3000, 525.004, 150)), cutting_data.NONE)
        self.assertEqual(cutting_data.own(tool, (2500, 525, None)), cutting_data.CuttingData(spindle_rpm=2500.0))
        self.assertEqual(cutting_data.own(None, (2500, None, 90)).feed_z_mm_min, 90.0)
        with self.assertRaises(ValueError):
            cutting_data.own(tool, (0, 525, 150))

    def test_applied(self):
        tool = cutting_data.applied(MILL_8, OWN)
        self.assertEqual((tool.number, tool.spindle_rpm, tool.feed_xy_mm_min, tool.feed_z_mm_min), (21, 2500, 400, 150))
        self.assertIs(cutting_data.applied(MILL_8, cutting_data.NONE), MILL_8)

    def test_feeds_of_the_moves(self):
        moves = (nc.Move(nc.RAPID, 0, 0, 2), nc.Move(nc.LINE, 0, 0, -1, 150.0), nc.Move(nc.LINE, 10, 0, -1, 525.0),
                 nc.Move(nc.LINE, 10, 5, -1, 300.0))  # fmt: skip
        new = cutting_data.applied(MILL_8, cutting_data.CuttingData(feed_xy_mm_min=400.0, feed_z_mm_min=90.0))
        self.assertEqual([m.feed_mm_min for m in cutting_data.feeds(moves, MILL_8, new)], [None, 90.0, 400.0, 300.0])

    def test_one_feed_for_both(self):
        """A tool with the same XY and Z feed: a move only along Z gets the own Z feed."""
        old = nc.Tool(5, "Mill", 6.0, 8000, feed_z_mm_min=600, feed_xy_mm_min=600)
        new = cutting_data.applied(old, cutting_data.CuttingData(feed_z_mm_min=200.0))
        moves = (nc.Move(nc.RAPID, 0, 0, 2), nc.Move(nc.LINE, None, None, -1, 600.0), nc.Move(nc.LINE, 10, 0, -1, 600.0),
                 nc.Move(nc.LINE, 10, 0, -2, 600.0))  # fmt: skip
        self.assertEqual([m.feed_mm_min for m in cutting_data.feeds(moves, old, new)], [None, 200.0, 600.0, 200.0])

    def test_drilling_cycle(self):
        op = cutting_data.operation(drilling(), cutting_data.CuttingData(feed_xy_mm_min=300.0, feed_z_mm_min=250.0))
        self.assertEqual((op.cycle.feed_mm_min, op.cycle.preposition_feed_mm_min), (300.0, 250.0))
        self.assertEqual(op.tool.spindle_rpm, 2185)

    def test_vc_and_fz(self):
        self.assertAlmostEqual(cutting_data.vc_m_min(8.0, 3000), 75.398, places=3)
        self.assertAlmostEqual(cutting_data.fz_mm(525, 3000, 3), 0.058333, places=6)
        self.assertIsNone(cutting_data.fz_mm(525, 3000, None))


class TestProgram(unittest.TestCase):
    def test_own_feeds(self):
        """Q30/Q31 of the operation's own feeds, the moves on them."""
        op = cutting_data.operation(contour(MILL_8), cutting_data.CuttingData(feed_xy_mm_min=400.0, feed_z_mm_min=90.0))
        text = blocks(heidenhain.write(program(setup(1, op))))
        self.assertIn("FN0: Q30=90 ;voeding Z", text)
        self.assertIn("FN0: Q31=400 ;voeding XY", text)
        self.assertNotIn("FN0: Q31=525 ;voeding XY", text)
        self.assertFalse([b for b in text if re.search(r" F\d", b)], "no feed written out")

    def test_another_speed_calls_the_tool_again(self):
        """The same T with another spindle speed: a whole TOOL CALL with its
        number; the same speed: none. TOOL DEF names the next other tool."""
        first, same = contour(MILL_8), contour(MILL_8)
        slower = cutting_data.operation(contour(MILL_8), OWN)
        text = blocks(heidenhain.write(program(setup(1, first, same, slower, contour(MILL_12)))))
        calls = [b for b in text if b.startswith("TOOL CALL")]
        self.assertEqual(
            calls,
            ["TOOL CALL 21 Z S3000 DL0 DR0;Iscar Vingerfrees 8mm RVS", "TOOL CALL 21 Z S2500 DL0 DR0;Iscar Vingerfrees 8mm RVS",
             "TOOL CALL 8 Z S12000 DL0 DR0;VHM ALU Frees 12mm"],
        )  # fmt: skip
        defs = [b for b in text if b.startswith("TOOL DEF")]
        self.assertEqual(defs, ["TOOL DEF 8", "TOOL DEF 8", "TOOL DEF 21"])
        second = text.index(calls[1])
        self.assertIn("M01", text[second - 6 : second], "as a tool change")
        self.assertTrue(any("M3 M8" in b for b in text[second:]), "the spindle on again")

    def test_machine_calls_the_tool_again(self):
        """Simulate and the cycle time go up to the tool change height for it too."""
        follower = machine.Machine(40.0, 100.0)
        follower.elements(contour(MILL_8))
        follower.elements(contour(MILL_8))
        self.assertFalse(follower.changed)
        follower.elements(cutting_data.operation(contour(MILL_8), OWN))
        self.assertTrue(follower.changed)


class TestEngine(unittest.TestCase):
    def setUp(self):
        from avangardecam import tool_library_path
        from avangardecam.model import library

        self.doc = FreeCAD.newDocument("AvangardeCamCuttingData")
        box = self.doc.addObject("Part::Box", "Part")
        box.Length, box.Width, box.Height = 40, 20, 12
        box.Placement.Base = FreeCAD.Vector(-20, -10, 0)
        self.doc.recompute()
        self.part = box
        self.library = library.load(tool_library_path())

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def contour(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry

        job = cam.ensure_job(self.doc, [self.part])
        entry = next(e for e in self.library if e.number == 21 and e.workpiece_material == "RVS")
        tc = cam.add_tool(job, entry)
        top = next(i for i, f in enumerate(self.part.Shape.Faces, 1) if f.normalAt(0, 0).z > 0.99)
        sketch = geometry.extract_boundary(self.doc, [self.part], self.part, "Face{}".format(top))
        return job, cam.add_contour(job, sketch, operations.Contour(-1.0), tc)

    def test_kept_on_the_operation(self):
        from avangardecam.engine import cutting_data as engine
        from avangardecam.engine import freecad_cam as cam

        job, op = self.contour()
        tool = cam.tool_with_number(job, 21).tool
        self.assertEqual(engine.own(op), cutting_data.NONE)
        before = cam.nc_operation(op)
        self.assertEqual(before.tool.feed_xy_mm_min, tool.feed_xy_mm_min)
        engine.set_own(op, cutting_data.CuttingData(spindle_rpm=2000.0, feed_xy_mm_min=300.0))
        self.assertEqual(engine.own(op), cutting_data.CuttingData(spindle_rpm=2000.0, feed_xy_mm_min=300.0))
        self.assertEqual(engine.tool(op).feed_xy_mm_min, 300.0)
        self.assertEqual(engine.tool(op).feed_z_mm_min, tool.feed_z_mm_min)
        after = cam.nc_operation(op)
        self.assertEqual((after.tool.spindle_rpm, after.tool.feed_xy_mm_min), (2000.0, 300.0))
        self.assertEqual(
            [m.feed_mm_min for m in after.moves if m.feed_mm_min is not None],
            [300.0 if abs(f - tool.feed_xy_mm_min) < 0.01 else f for f in (m.feed_mm_min for m in before.moves if m.feed_mm_min is not None)],  # fmt: skip
        )
        self.assertIn(tool.feed_z_mm_min, [m.feed_mm_min for m in after.moves], "the Z feed stays the tool's")
        self.assertAlmostEqual(cam._value(op.ToolController.HorizFeed, "mm/min"), tool.feed_xy_mm_min, msg="the tool keeps its own")  # fmt: skip
        engine.set_own(op, cutting_data.NONE)
        self.assertEqual(cam.nc_operation(op).tool.feed_xy_mm_min, tool.feed_xy_mm_min, "back to the tool's")


if __name__ == "__main__":
    unittest.main()
