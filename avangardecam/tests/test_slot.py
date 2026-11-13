# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Slot milling tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_slot   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import datetime
import json
import math
import unittest

from avangardecam.model import nc, operations, slot
from avangardecam.post import heidenhain

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

# a slot 20 x 10 along X (its ends 10 apart), 5 deep, milled with Ø8
SLOT = slot.Slot((-5.0, 0.0), (5.0, 0.0), 10.0)
CUT = slot.SlotCut(SLOT, 0.0, -5.0)


def _points(moves):
    return [(round(m.x, 3), round(m.y, 3), round(m.z, 3)) for m in moves]


class TestSlotModel(unittest.TestCase):
    def test_values(self):
        values = slot.SlotMilling()
        self.assertIs(values.validate(), values)
        self.assertEqual(
            (values.depth_mm, values.through_mm, values.z_step_mm, values.step_over_percent),
            (None, 1.0, None, 50.0),
        )
        self.assertEqual(
            (values.finish_xy_mm, values.finish_z_mm, values.ramp_angle_deg, values.compensation, values.lead_radius_mm),
            (0.0, 0.0, 5.0, nc.LEFT, None),
        )
        self.assertEqual(values.ramp, slot.RAMP_TO_AND_FRO)
        every = slot.SlotMilling(-4.0, 0.5, 1.5, 40.0, 0.2, 0.1, 3.0, nc.RIGHT, 4.5, slot.RAMP_CONTOUR)
        self.assertEqual(operations.from_json(operations.to_json(every)), every)
        self.assertEqual(json.loads(operations.to_json(every))["kind"], "slot_milling")
        for bad in (
            slot.SlotMilling(depth_mm=0.0),
            slot.SlotMilling(depth_mm=2.0),
            slot.SlotMilling(through_mm=-1.0),
            slot.SlotMilling(z_step_mm=0.0),
            slot.SlotMilling(step_over_percent=0.5),
            slot.SlotMilling(step_over_percent=101.0),
            slot.SlotMilling(finish_xy_mm=-0.1),
            slot.SlotMilling(finish_z_mm=-0.1),
            slot.SlotMilling(ramp_angle_deg=0.0),
            slot.SlotMilling(ramp_angle_deg=60.0),
            slot.SlotMilling(compensation="off"),
            slot.SlotMilling(lead_radius_mm=0.0),
            slot.SlotMilling(ramp="spiral"),
        ):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()

    def test_levels(self):
        """Full Z steps from the top and the rest at the floor (as the
        contour); with an allowance in Z the rough passes stop above the
        floor and a last level clears it; the walls are finished on the
        same steps and the floor."""
        self.assertEqual(slot.SlotMilling().levels(0.0, -5.0), [-5.0])
        self.assertEqual(slot.SlotMilling(z_step_mm=2.0).levels(0.0, -5.0), [-2.0, -4.0, -5.0])
        self.assertEqual(slot.SlotMilling(z_step_mm=2.5).levels(0.0, -5.0), [-2.5, -5.0])
        with_z = slot.SlotMilling(z_step_mm=2.5, finish_z_mm=0.1)
        self.assertEqual(with_z.levels(0.0, -5.0), [-2.5, -4.9, -5.0])
        self.assertEqual(with_z.wall_levels(0.0, -5.0), [-2.5, -5.0])
        self.assertEqual(slot.SlotMilling(finish_z_mm=0.1).wall_levels(1.0, -5.0), [-5.0])

    def test_rough_offsets(self):
        """Evenly out to the allowance; without one the last pass is the
        finishing pass's; a slot as wide as the tool has none."""
        self.assertEqual(slot.SlotMilling(finish_xy_mm=0.2).rough_offsets(8.0, 10.0), [0.8])
        self.assertEqual(slot.SlotMilling().rough_offsets(8.0, 10.0), [], "the finishing pass takes the 1 mm")
        self.assertEqual([round(o, 6) for o in slot.SlotMilling().rough_offsets(6.0, 20.0)], [2.333333, 4.666667])
        found = slot.SlotMilling(finish_xy_mm=0.1).rough_offsets(6.0, 20.0)
        self.assertEqual(len(found), 3)
        self.assertAlmostEqual(found[-1], 6.9)
        self.assertLessEqual(found[0], 3.0)
        self.assertEqual(slot.SlotMilling().rough_offsets(8.0, 8.01), [])
        self.assertTrue(slot.as_wide_as_tool(8.0, 8.01))
        self.assertFalse(slot.as_wide_as_tool(8.0, 8.02))

    def test_check(self):
        values = slot.SlotMilling()
        self.assertIs(values.check(8.0, SLOT, 5.0), values)
        self.assertIs(values.check(10.0, SLOT, 5.0), values, "as wide as the tool: along the centre")
        with self.assertRaisesRegex(ValueError, "wider than the slot"):
            values.check(10.5, SLOT, 5.0)
        with self.assertRaisesRegex(ValueError, "as wide as the tool"):
            slot.SlotMilling(finish_xy_mm=0.1).check(10.0, SLOT, 5.0)
        with self.assertRaisesRegex(ValueError, "more than the tool"):
            slot.SlotMilling(finish_xy_mm=1.5).check(8.0, SLOT, 5.0)
        with self.assertRaisesRegex(ValueError, "less than the depth"):
            slot.SlotMilling(finish_z_mm=5.0).check(8.0, SLOT, 5.0)
        with self.assertRaisesRegex(ValueError, "approach radius"):
            slot.SlotMilling(lead_radius_mm=4.0).check(8.0, SLOT, 5.0)
        with self.assertRaisesRegex(ValueError, "approach radius"):
            slot.SlotMilling(lead_radius_mm=5.5).check(8.0, SLOT, 5.0)
        self.assertEqual(values.lead_radius(8.0, 10.0), 4.5, "0.5 mm clear of the wall")
        self.assertEqual(slot.SlotMilling(finish_xy_mm=0.8).lead_radius(8.0, 10.0), 4.8, "clear of the allowance")
        self.assertEqual(values.lead_radius(9.6, 10.0), 5.0, "at most half the slot")
        with self.assertRaisesRegex(ValueError, "round hole"):
            slot.Slot((1.0, 1.0), (1.0, 1.0), 10.0).axes()

    def test_ring(self):
        """Once round the centre line, from beside the end where the tool
        is: counterclockwise along +u on the right of it, or clockwise."""
        start, loop = slot.ring(SLOT, 1.0, False, False)
        self.assertEqual(start, (-5.0, -1.0))
        self.assertEqual([m[1] for m in loop], [(5.0, -1.0), (5.0, 1.0), (-5.0, 1.0), (-5.0, -1.0)])
        self.assertEqual([m[3] for m in loop if m[0] == "arc"], [False, False])
        start, loop = slot.ring(SLOT, 1.0, True, False)
        self.assertEqual(start, (5.0, -1.0))
        self.assertEqual(loop[-1][1], start)
        start, loop = slot.ring(SLOT, 1.0, False, True)
        self.assertEqual(start, (-5.0, 1.0))
        self.assertEqual(loop[1], ("arc", (5.0, -1.0), (5.0, 0.0), True))
        # a slot at an angle: the same, turned
        turned = slot.Slot((0.0, 0.0), (0.0, 10.0), 6.0)
        start, loop = slot.ring(turned, 2.0, False, False)
        self.assertEqual(start, (2.0, 0.0), "going +Y, the right is +X")

    def test_ramp(self):
        """To and fro along the centre line, no steeper than the angle,
        evenly, then once more at the level."""
        found, at_end = slot.ramp(SLOT, False, 0.0, -2.5, 5.0)
        self.assertEqual([m[2] for m in found], [-0.833333, -1.666667, -2.5, -2.5])
        self.assertEqual([m[1] for m in found], [SLOT.end, SLOT.start, SLOT.end, SLOT.start])
        self.assertFalse(at_end)
        drop = 2.5 / 3
        self.assertLessEqual(math.degrees(math.atan(drop / 10.0)), 5.0)
        found, at_end = slot.ramp(SLOT, True, -2.5, -2.6, 5.0)
        self.assertEqual(found, [("line", SLOT.start, -2.6), ("line", SLOT.end, -2.6)])
        self.assertTrue(at_end)
        with self.assertRaisesRegex(ValueError, "strokes"):
            slot.ramp(slot.Slot((0.0, 0.0), (0.02, 0.0), 6.0), False, 0.0, -100.0, 1.0)

    def test_moves(self):
        """Over the start, down to the top, ramps and rough passes level by
        level, then the walls with RL: from the lead centre onto the middle
        of the wall and once round, back with R0."""
        values = slot.SlotMilling(z_step_mm=2.5, finish_xy_mm=0.2, finish_z_mm=0.1)
        moves = slot.moves(values, [CUT], 8.0, 300.0, 1000.0, 3.0)
        self.assertEqual(moves[0], nc.Move(nc.RAPID, -5.0, 0.0, 20.0))
        self.assertEqual(moves[1], nc.Move(nc.RAPID, -5.0, 0.0, 2.0))
        self.assertEqual(moves[2], nc.Move(nc.LINE, -5.0, 0.0, 0.0, 300.0))
        cutting = [m for m in moves if m.kind != nc.RAPID]
        self.assertAlmostEqual(min(m.z for m in cutting), -5.0)
        # the rough passes stay the allowance off the walls, R0
        rough = [m for m in moves if m.compensation is None and m.kind != nc.RAPID]
        for m in rough:
            inside = max(abs(m.y), math.hypot(abs(m.x) - 5.0, m.y) if abs(m.x) > 5.0 else 0.0)
            self.assertLessEqual(inside, 5.0 - 4.0 - 0.2 + 1e-6, m)
        # the walls with RL, at -2.5 and -5
        compensated = [m for m in moves if m.compensation == nc.LEFT]
        self.assertEqual(sorted(set(round(m.z, 3) for m in compensated)), [-5.0, -2.5])
        self.assertEqual(len(compensated), 2 * 8)
        first = compensated[0]
        self.assertEqual((first.kind, round(first.x, 3), round(first.y, 3)), (nc.LINE, -3.182, -3.682))
        self.assertEqual((compensated[1].kind, compensated[1].center, compensated[1].clockwise), (nc.ARC, (0.0, -0.5), False))
        self.assertEqual((round(compensated[1].x, 6), compensated[1].y), (0.0, -5.0), "onto the middle of the wall")
        walls = [m for m in compensated if m.kind == nc.ARC and m.center != (0.0, -0.5)]
        self.assertEqual([(m.center, m.x, m.y) for m in walls[:2]], [((5.0, 0.0), 5.0, 5.0), ((-5.0, 0.0), -5.0, -5.0)])
        after = moves[moves.index(compensated[7]) + 1]
        self.assertEqual((after.kind, after.x, after.y, after.compensation), (nc.LINE, 0.0, -0.5, None), "R0 back to the lead centre")
        self.assertEqual(moves[-1], nc.Move(nc.RAPID, 0.0, -0.5, 3.0))

    def test_ramp_offset(self):
        """Along the contour the tool's radius from the centre line, less
        where it would cut into the finishing allowance; else to and fro."""
        contour = slot.SlotMilling(ramp=slot.RAMP_CONTOUR)
        self.assertEqual(contour.ramp_offset(4.0, 10.0), 2.0)
        self.assertEqual(contour.ramp_offset(8.0, 10.0), 1.0)
        self.assertAlmostEqual(slot.SlotMilling(finish_xy_mm=0.2, ramp=slot.RAMP_CONTOUR).ramp_offset(8.0, 10.0), 0.8)
        self.assertIsNone(slot.SlotMilling().ramp_offset(4.0, 10.0), "to and fro chosen")
        self.assertIsNone(contour.ramp_offset(10.0, 10.0), "as wide as the tool")
        self.assertIsNone(contour.ramp_offset(9.9, 10.0), "less than 0.1 mm of room")
        values = slot.SlotMilling(finish_xy_mm=0.2, ramp=slot.RAMP_CONTOUR)
        self.assertEqual(values.passes(4.0, 10.0), (2.0, [2.8]), "the pass at 1.4 inside the ramp's turn")
        self.assertEqual(slot.SlotMilling(finish_xy_mm=0.2).passes(4.0, 10.0), (None, [1.4, 2.8]))

    def test_contour_ramp(self):
        """Ø4 round the centre line 2 mm from it (no core left), the same
        way round as the passes, down on lines and helical half circles no
        steeper than the ramp angle, once round at the level; then the pass
        at 2.8 (the one at 1.4 is inside the ramp's), no centre line."""
        values = slot.SlotMilling(z_step_mm=2.5, finish_xy_mm=0.2, ramp=slot.RAMP_CONTOUR)
        moves = slot.moves(values, [CUT], 4.0, 300.0, 1000.0, 3.0)
        self.assertEqual(moves[:3], (nc.Move(nc.RAPID, -5.0, -2.0, 20.0), nc.Move(nc.RAPID, -5.0, -2.0, 2.0), nc.Move(nc.LINE, -5.0, -2.0, 0.0, 300.0)))  # fmt: skip
        rough = [m for m in moves if m.compensation is None and m.kind != nc.RAPID]
        self.assertEqual({round(abs(m.y), 3) for m in rough if m.kind == nc.LINE} - {2.5}, {2.0, 2.8}, "no centre line (2.5: the lead centre)")
        self.assertTrue(all(not m.clockwise for m in rough if m.kind == nc.ARC), "counterclockwise: climbing with RL")
        tan = math.tan(math.radians(5.0)) + 1e-6
        before = moves[2]
        ramps = []
        for m in moves[3:]:
            if m.kind == nc.RAPID or m.compensation:
                break
            if m.z < before.z - 1e-9:
                along = math.pi * 2.0 if m.kind == nc.ARC else math.hypot(m.x - before.x, m.y - before.y)
                self.assertLessEqual((before.z - m.z) / along, tan, m)
                self.assertEqual(m.feed_mm_min, 300.0)
                ramps.append(m)
            before = m
        self.assertEqual(len([m for m in ramps if m.kind == nc.ARC]), 4, "two half circles a level, down as helices")
        self.assertEqual(sorted({m.z for m in ramps})[:1], [-5.0])
        flat = [m for m in rough if m.feed_mm_min == 1000.0 and m.kind == nc.ARC and abs(m.y) == 2.0]
        self.assertEqual(len(flat), 4, "once round at -2.5 and -5")
        lines = self.program_lines(moves)
        self.assertEqual(lines.count("CP IPA+180. IZ-0.482 DR+"), 4, "the helices")
        self.assertIn("L X+5. Z-0.768", lines)
        self.assertEqual(lines[lines.index("L X+5. Z-0.768") - 1], "L Z+0. R0 FQ30", "down beside the start, then round")

    def program_lines(self, moves):
        tool = nc.Tool(21, "VHM 4mm", 4.0, 8000.0, 300.0, 1000.0)
        operation = nc.Operation(nc.SLOT_MILLING, "Slot milling", tool, moves)
        program = nc.Program("SLOT", "", datetime.date(2026, 10, 22), (nc.Setup(1, "Setup 1", None, (operation,)),))
        return [line.split(" ", 1)[1] for line in heidenhain.write(program).split("\r\n") if line]

    def test_contour_ramp_too_narrow(self):
        """No room beside the centre line: to and fro after all."""
        values = slot.SlotMilling(ramp=slot.RAMP_CONTOUR)
        self.assertEqual(slot.moves(values, [CUT], 9.95, 300.0, 1000.0, 3.0), slot.moves(slot.SlotMilling(), [CUT], 9.95, 300.0, 1000.0, 3.0))  # fmt: skip

    def test_tool_centre(self):
        """FreeCAD's path: the finishing pass a radius in from the walls,
        the lead arc a radius smaller around the same centre, no compensation."""
        values = slot.SlotMilling(finish_xy_mm=0.2)
        centre = slot.moves(values, [CUT], 8.0, 300.0, 1000.0, 3.0, program=False)
        program = slot.moves(values, [CUT], 8.0, 300.0, 1000.0, 3.0)
        self.assertEqual(len(centre), len(program))
        self.assertTrue(all(m.compensation is None for m in centre))
        arcs = [m for m in centre if m.kind == nc.ARC and m.center == (0.0, -0.5)]
        self.assertEqual(len(arcs), 2)
        self.assertAlmostEqual(arcs[0].y, -1.0)
        walls = [m for m in centre if m.kind == nc.ARC and m.center == (5.0, 0.0)]
        self.assertEqual((walls[-1].x, walls[-1].y), (5.0, 1.0))

    def test_conventional(self):
        """RR: the passes go clockwise, the finishing pass on the +Y wall."""
        values = slot.SlotMilling(finish_xy_mm=0.2, compensation=nc.RIGHT)
        moves = slot.moves(values, [CUT], 8.0, 300.0, 1000.0, 3.0)
        compensated = [m for m in moves if m.compensation == nc.RIGHT]
        self.assertTrue(compensated)
        self.assertTrue(all(m.clockwise for m in compensated if m.kind == nc.ARC))
        self.assertEqual((round(compensated[1].x, 6), compensated[1].y), (0.0, 5.0))
        self.assertTrue(all(m.clockwise for m in moves if m.kind == nc.ARC and m.compensation is None))

    def test_as_wide_as_tool(self):
        """Along the centre line only: the ramps and once more at each level."""
        moves = slot.moves(slot.SlotMilling(z_step_mm=2.5), [CUT], 10.0, 300.0, 1000.0, 3.0)
        self.assertFalse([m for m in moves if m.kind == nc.ARC or m.compensation])
        self.assertTrue(all(m.y == 0.0 for m in moves))
        self.assertEqual(min(m.z for m in moves), -5.0)

    def test_slots_in_order(self):
        """From slot to slot over the safe height, each from its own top."""
        other = slot.SlotCut(slot.Slot((20.0, 0.0), (20.0, 10.0), 10.0), -2.0, -4.0)
        moves = slot.moves(slot.SlotMilling(), [CUT, other], 8.0, 300.0, 1000.0, 3.0)
        index = next(i for i, m in enumerate(moves) if m.x == 20.0 and m.y == 0.0)
        self.assertEqual(moves[index], nc.Move(nc.RAPID, 20.0, 0.0, 3.0))
        self.assertEqual(moves[index + 1], nc.Move(nc.RAPID, 20.0, 0.0, 0.0))
        self.assertEqual(moves[index + 2], nc.Move(nc.LINE, 20.0, 0.0, -2.0, 300.0))
        self.assertAlmostEqual(min(m.z for m in moves[index:]), -4.0)

    def test_program(self):
        """The postprocessor writes it with L, CC and C: RL onto the wall, R0 off it."""
        values = slot.SlotMilling(z_step_mm=2.5, finish_xy_mm=0.2, finish_z_mm=0.1)
        moves = slot.moves(values, [CUT], 8.0, 300.0, 1000.0, 3.0)
        tool = nc.Tool(21, "VHM 8mm", 8.0, 8000.0, 300.0, 1000.0)
        operation = nc.Operation(nc.SLOT_MILLING, "Slot milling", tool, moves)
        program = nc.Program("SLOT", "", datetime.date(2026, 10, 22), (nc.Setup(1, "Setup 1", None, (operation,)),))
        lines = [line.split(" ", 1)[1] for line in heidenhain.write(program).split("\r\n") if line]
        self.assertIn("*- Slot Milling", lines)
        self.assertIn("L X+5. Z-0.833", lines, "the ramp")
        self.assertEqual(lines.count("L X-3.182 Y-3.682 RL FQ31"), 2)
        self.assertEqual(lines.count("L X+0. Y-0.5 R0"), 2)
        self.assertEqual(lines.count("C X+0. Y-5. DR+"), 2)
        self.assertEqual(lines[lines.index("L Z+40. R0 FMAX") - 1], "L X+0. Y-0.5 R0", "up from the lead centre")


def _stadium(start, end, width, z0, z1):
    """A slot-shaped solid from z0 to z1 (part coordinates)."""
    import Part

    a, b = FreeCAD.Vector(start[0], start[1], z0), FreeCAD.Vector(end[0], end[1], z0)
    u = b - a
    u.normalize()
    n = FreeCAD.Vector(-u.y, u.x, 0) * (width / 2.0)
    wire = Part.Wire(
        [
            Part.LineSegment(a - n, b - n).toShape(),
            Part.Arc(b - n, b + u * (width / 2.0), b + n).toShape(),
            Part.LineSegment(b + n, a + n).toShape(),
            Part.Arc(a + n, a - u * (width / 2.0), a - n).toShape(),
        ]
    )
    return Part.Face(wire).extrude(FreeCAD.Vector(0, 0, z1 - z0))


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestSlotEngine(unittest.TestCase):
    """A plate 60 x 40 x 20, the zero on the middle of its top (Z+20 of the
    part): a blind slot 30 x 10 along X, 6 deep, its ends at (-15, 8) and
    (5, 8); a through slot 18 x 8 along Y, ends at (20, -12) and (20, -2);
    a slot 6 wide at an angle, 4 deep, ends at (-20, -12) and (-12, -6); a
    round hole Ø6 at (5, -12); a slot 6 wide running out of the right edge
    at Y+15; the stock 1 mm around and on top. T5 (Ø6, Aluminium)."""

    def setUp(self):
        import Part

        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import slot as engine_slot
        from avangardecam.model import library
        from avangardecam.tests.test_engine import TestEngine
        from avangardecam.tests.test_model import LIBRARY

        self.cam, self.engine = cam, engine_slot
        self.helpers = TestEngine("setUp")
        self.doc = FreeCAD.newDocument("AvangardeCamSlot")
        self.helpers.doc = self.doc
        self.helpers.library = library.load(LIBRARY)
        shape = Part.makeBox(60, 40, 20, FreeCAD.Vector(-30, -20, 0))
        for cut in (
            _stadium((-15, 8), (5, 8), 10.0, 14.0, 21.0),
            _stadium((20, -12), (20, -2), 8.0, -1.0, 21.0),
            _stadium((-20, -12), (-12, -6), 6.0, 16.0, 21.0),
            Part.makeCylinder(3.0, 30.0, FreeCAD.Vector(5, -12, -5)),
            _stadium((25, 15), (40, 15), 6.0, 15.0, 21.0),
        ):
            shape = shape.cut(cut)
        self.plate = self.doc.addObject("Part::Feature", "Plate")
        self.plate.Shape = shape.removeSplitter()
        self.doc.recompute()
        self.job = cam.ensure_job(self.doc, [self.plate])
        self.tc = cam.add_tool(self.job, self.helpers.variant(5, "Aluminium"))

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def face(self, test):
        for i, f in enumerate(self.plate.Shape.Faces, start=1):
            if test(f):
                return "Face{}".format(i)
        raise AssertionError("no such face")

    def round_end(self, x, y):
        return self.face(lambda f: hasattr(f.Surface, "Radius") and abs(f.Surface.Center.x - x) < 1e-6 and abs(f.Surface.Center.y - y) < 1e-6)  # fmt: skip

    def floor(self, z, x, y):
        return self.face(
            lambda f: f.findPlane() is not None
            and f.BoundBox.ZLength < 1e-9
            and abs(f.BoundBox.ZMin - z) < 1e-9
            and f.isInside(FreeCAD.Vector(x, y, z), 1e-6, True)
        )

    def wall(self, y):
        return self.face(lambda f: f.findPlane() is not None and f.BoundBox.YLength < 1e-9 and abs(f.BoundBox.YMin - y) < 1e-9 and f.BoundBox.ZLength < 7)  # fmt: skip

    def slot_of(self, name):
        clone = self.cam._clone(self.job, self.plate)
        return self.engine.slot_in_model(clone, name, self.plate.Label)

    def test_picked_by_any_face_or_edge(self):
        """A round end, a wall, the floor or a round edge: the same slot, in
        the setup's coordinates (the zero on the middle of the top)."""
        expected = (slot.Slot((-15.0, 8.0), (5.0, 8.0), 10.0), 0.0, -6.0, False)
        end = self.round_end(5, 8)
        edge = next(
            "Edge{}".format(i)
            for i, e in enumerate(self.plate.Shape.Edges, start=1)
            if hasattr(e.Curve, "Radius") and abs(e.Curve.Center.x + 15) < 1e-6 and abs(e.Curve.Center.y - 8) < 1e-6 and abs(e.Curve.Center.z - 20) < 1e-6  # fmt: skip
        )
        for name in (end, self.wall(3.0), self.wall(13.0), self.floor(14.0, -5, 8), edge):
            found = self.slot_of(name)
            self.assertEqual((found.slot, found.top, found.bottom, found.through), expected, name)
        through = self.slot_of(self.round_end(20, -12))
        self.assertEqual((through.slot, through.top, through.bottom, through.through), (slot.Slot((20.0, -12.0), (20.0, -2.0), 8.0), 0.0, -20.0, True))  # fmt: skip
        turned = self.slot_of(self.round_end(-12, -6))
        self.assertEqual((turned.slot.start, turned.slot.end, turned.bottom), ((-20.0, -12.0), (-12.0, -6.0), -4.0))
        self.assertAlmostEqual(turned.slot.width_mm, 6.0)

    def test_not_a_slot(self):
        for name, text in (
            (self.round_end(5, -12), "a round hole, not a slot"),
            (self.round_end(25, 15), "not a closed slot"),
            (self.floor(20.0, 0, -18), "not part of a slot"),
        ):
            with self.assertRaises(self.cam.ProjectError) as caught:
                self.slot_of(name)
            self.assertIn(text, str(caught.exception), name)

    def test_slot_milling(self):
        """Ø6 in the blind slot: down to its floor, the tool centre 2 mm from
        the walls; the program finishes them with RL."""
        values = slot.SlotMilling(z_step_mm=3.0, finish_xy_mm=0.2)
        op = self.engine.add_slot_milling(self.job, values, self.tc, self.plate, [self.wall(3.0)])
        self.assertEqual(self.engine.slot_milling_of(op), (self.plate, values))
        self.assertEqual(op.Label, "Slot milling 1")
        self.assertEqual(type(op.Proxy).__module__, "avangardecam.engine.slot")
        points = [c.Placement.Base for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]
        self.assertAlmostEqual(min(p.z for p in points), -6.0)
        self.assertAlmostEqual(min(p.y for p in points), 6.0, msg="the tool centre a radius from the wall at Y+3")
        self.assertAlmostEqual(max(p.y for p in points), 10.0)
        self.assertAlmostEqual(min(p.x for p in points), -15.0)
        self.assertAlmostEqual(op.StartDepth.Value, 0.0)
        self.assertAlmostEqual(op.FinalDepth.Value, -6.0)
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0)
        self.assertAlmostEqual(op.ClearanceHeight.Value, 20.0)
        from avangardecam.post import heidenhain

        text = heidenhain.write(self.cam.nc_program(self.doc, "SLOT"))
        lines = [line.split(" ", 1)[1] for line in text.split("\r\n") if line]
        self.assertIn("*- Slot Milling", lines)
        self.assertEqual(sum(1 for line in lines if " RL " in line), 2, "onto the wall at Z-3 and Z-6")
        self.assertIn("C X-5. Y+3. DR+", lines, "onto the middle of the wall with RL")
        start = next(i for i, line in enumerate(lines) if line.startswith("FN0: Q31="))
        self.assertEqual(lines[start + 1 : start + 5], ["L X-15. Y+8. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+2. R0 FMAX", "L Z+0. R0 FQ30"])  # fmt: skip

    def test_path_drawing(self):
        """The view draws the ramps and rough passes where the tool centre
        goes, the finishing pass along the walls (Y+3 and Y+13), where the
        edge cuts with RL; FreeCAD's path keeps the tool centre."""
        values = slot.SlotMilling(z_step_mm=3.0, finish_xy_mm=0.2)
        op = self.engine.add_slot_milling(self.job, values, self.tc, self.plate, [self.wall(3.0)])
        pieces = self.cam.path_drawing(op)
        self.assertEqual(pieces, self.engine.path_drawing(op))
        feeds = [points for kind, points in pieces if kind == self.cam.DRAW_FEED]
        self.assertEqual({kind for kind, _p in pieces}, {self.cam.DRAW_RAPID, self.cam.DRAW_FEED})
        walls = [points for points in feeds if min(p.y for p in points) < 6.0 - 1e-6]
        self.assertEqual(len(walls), 2, "the finishing pass at Z-3 and Z-6")
        for points in walls:
            self.assertAlmostEqual(min(p.y for p in points), 3.0)
            self.assertAlmostEqual(max(p.y for p in points), 13.0)
            self.assertEqual(len({round(p.z, 6) for p in points[1:]}), 1, "down at the lead centre, then flat")
            self.assertTrue(all(abs(p.y - 8.0) <= 5.0 + 1e-6 for p in points), "nothing past the walls")
        rough = [points for points in feeds if points not in walls]
        self.assertAlmostEqual(min(p.y for points in rough for p in points), 6.0 + 0.2)
        self.assertAlmostEqual(min(p.z for points in rough for p in points), -6.0)
        self.assertAlmostEqual(min(c.Placement.Base.y for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")), 6.0)

    def test_contour_ramp(self):
        """Ramping along the contour in the blind slot (Ø6, 10 wide, 0.2 on
        the walls): round the centre line 1.8 mm from it, helices on FreeCAD's
        path (G2/G3 going down) and in the drawing, which goes down evenly."""
        values = slot.SlotMilling(z_step_mm=3.0, finish_xy_mm=0.2, ramp=slot.RAMP_CONTOUR)
        op = self.engine.add_slot_milling(self.job, values, self.tc, self.plate, [self.wall(3.0)])
        z = None
        helices = 0
        for c in op.Path.Commands:
            if c.Name in ("G2", "G3") and z is not None and c.Placement.Base.z < z - 1e-6:
                helices += 1
            if c.Name in ("G0", "G1", "G2", "G3"):
                z = c.Placement.Base.z
        self.assertEqual(helices, 4, "two half circles on each of the two levels")
        cutting = [c.Placement.Base for c in op.Path.Commands if c.Name in ("G1", "G2", "G3")]
        self.assertAlmostEqual(min(p.y for p in cutting), 6.0)
        self.assertNotIn(8.0, {round(p.y, 6) for p in cutting if p.z < -1e-6}, "not along the centre line")
        feeds = [points for kind, points in self.cam.path_drawing(op) if kind == self.cam.DRAW_FEED]
        ramp = feeds[0]
        steps = [round(a.z - b.z, 9) for a, b in zip(ramp, ramp[1:])]
        self.assertTrue(all(step >= 0.0 for step in steps[: len(steps) // 3]), "down, never up, on the first turn")
        self.assertGreater(len({round(p.z, 3) for p in ramp if abs(p.x - 5.0) < 1.8 + 1e-6 and p.x > 5.0}), 10, "the helix drawn going down")  # fmt: skip

    def test_depths(self):
        """Through: through_mm under the part; the user's depth from the top;
        not through the floor of a blind slot."""
        through = [self.round_end(20, -2)]
        op = self.engine.add_slot_milling(self.job, slot.SlotMilling(z_step_mm=10.0), self.tc, self.plate, through)
        self.assertAlmostEqual(op.FinalDepth.Value, -21.0)
        self.cam.change_operation(op, slot.SlotMilling(depth_mm=-3.0), self.tc)
        self.assertAlmostEqual(min(c.Placement.Base.z for c in op.Path.Commands if c.Name == "G1"), -3.0)
        with self.assertRaises(self.cam.ProjectError) as caught:
            self.engine.add_slot_milling(self.job, slot.SlotMilling(depth_mm=-7.0), self.tc, self.plate, [self.wall(3.0)])
        self.assertIn("goes through its floor", str(caught.exception))

    def test_tools(self):
        """Ø10 in the slot 10 wide: along its centre only; too wide for the 8 mm one."""
        t7 = self.cam.add_tool(self.job, self.helpers.variant(7, "Aluminium"))  # Ø10
        op = self.engine.add_slot_milling(self.job, slot.SlotMilling(), t7, self.plate, [self.wall(3.0)])
        self.assertFalse([c for c in op.Path.Commands if c.Name in ("G2", "G3")])
        self.assertEqual({round(c.Placement.Base.y, 6) for c in op.Path.Commands if c.Name == "G1"}, {8.0})
        with self.assertRaises(self.cam.ProjectError) as caught:
            self.engine.add_slot_milling(self.job, slot.SlotMilling(), t7, self.plate, [self.round_end(20, -2)])
        self.assertIn("wider than the slot", str(caught.exception))
        with self.assertRaises(self.cam.ProjectError):
            self.cam.set_tool(op, self.cam.add_tool(self.job, self.helpers.variant(40, "RVS")))

    def test_slots_in_order_and_file(self):
        """Two slots in the order picked (one slot picked twice: once); kept
        in the file; the zero point turned: new X = old Y."""
        import os
        import tempfile

        picked = [self.round_end(-12, -6), self.wall(3.0), self.floor(14.0, -5, 8)]
        op = self.engine.add_slot_milling(self.job, slot.SlotMilling(), self.tc, self.plate, picked)
        self.assertEqual([s.slot.start for s in self.engine.slots(op)], [(-20.0, -12.0), (-15.0, 8.0)])
        self.assertEqual(self.engine.slot_elements(op), picked)
        path = os.path.join(tempfile.mkdtemp(), "slot.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        job = self.cam.find_job(self.doc)
        op = self.cam.operations(job)[0]
        self.assertEqual(type(op.Proxy).__module__, "avangardecam.engine.slot")
        op.touch()
        self.doc.recompute()
        self.assertAlmostEqual(min(c.Placement.Base.z for c in op.Path.Commands if c.Name == "G1"), -6.0)
        self.cam.rotate_zero(job, 90.0)
        found = self.engine.slots(op)
        self.assertEqual([(round(s.slot.start[0], 6), round(s.slot.start[1], 6)) for s in found], [(-12.0, 20.0), (8.0, -5.0)])  # fmt: skip


if __name__ == "__main__":
    unittest.main()
