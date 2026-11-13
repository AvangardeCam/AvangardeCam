# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Facing tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_facing   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import json
import unittest

from avangardecam.model import facing, nc, operations

try:
    import FreeCAD
except ImportError:
    FreeCAD = None


def _always(*_args):
    return True


class TestFacingModel(unittest.TestCase):
    def test_values(self):
        values = facing.Facing()
        self.assertIs(values.validate(), values)
        self.assertEqual(
            (values.start_z_mm, values.z_step_mm, values.step_over_percent, values.pattern, values.direction),
            (None, None, 70.0, facing.ZIGZAG, facing.X_PLUS),
        )
        self.assertEqual((values.offset_xy_mm, values.overrun_mm), (0.0, 2.0))
        every = facing.Facing(-1.0, 2.0, 50.0, facing.ONE_WAY, facing.Y_MINUS, 0.5, 3.0)
        self.assertEqual(operations.from_json(operations.to_json(every)), every)
        self.assertEqual(json.loads(operations.to_json(every))["kind"], "facing")
        for bad in (
            facing.Facing(z_step_mm=0.0),
            facing.Facing(step_over_percent=0.5),
            facing.Facing(step_over_percent=101.0),
            facing.Facing(pattern="spiral"),
            facing.Facing(direction="z+"),
            facing.Facing(start_side="y-"),
            facing.Facing(overrun_mm=-1.0),
            facing.Facing(start_z_mm=1001.0),
        ):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()
        self.assertEqual(facing.Facing(offset_xy_mm=-2.0).check(6.0).offset_xy_mm, -2.0, "into the walls, the centre outside")
        with self.assertRaises(ValueError):
            facing.Facing(offset_xy_mm=-3.0).check(6.0)

    def test_levels(self):
        """Full Z steps from the top of the material and the rest at the
        face (as the contour and the TNC); nothing at the top or above."""
        self.assertEqual(facing.Facing().levels(1.0, -5.0), [-5.0])
        self.assertEqual(facing.Facing(z_step_mm=2.0).levels(1.0, -5.0), [-1.0, -3.0, -5.0])
        self.assertEqual(facing.Facing(z_step_mm=2.0).levels(1.0, -4.0), [-1.0, -3.0, -4.0])
        self.assertEqual(facing.Facing(z_step_mm=0.3).levels(1.0, 0.0), [0.7, 0.4, 0.1, 0.0])
        self.assertEqual(facing.Facing().levels(0.0, 0.0), [], "Start Z on the face")
        self.assertEqual(facing.Facing(start_z_mm=-1.0).top_mm(1.0), -1.0)
        self.assertEqual(facing.Facing().top_mm(1.0), 1.0, "the top of the stock")

    def test_rows(self):
        """From the start end: each pass evenly no more than the step of fresh
        material, the first one in over that end, the last one with the
        tool's edge on the other end (the user: not near the middle)."""
        rows = facing.rows_at(-11.0, 11.0, 6.0, 4.2)
        for got, wanted in zip(rows, [-14.0 + 22.0 * i / 6 for i in range(1, 7)]):
            self.assertAlmostEqual(got, wanted)
        self.assertEqual(len(rows), 6)
        self.assertAlmostEqual(rows[-1], 8.0, msg="the tool's edge on the far end")
        self.assertEqual(facing.rows_at(0.0, 100.0, 50.0, 20.0), [-5.0, 15.0, 35.0, 55.0, 75.0], "Ø50, 40 %: in from the edge")  # fmt: skip
        self.assertEqual(facing.rows_at(0.0, 100.0, 50.0, 20.0, False), [105.0, 85.0, 65.0, 45.0, 25.0], "from the high end")  # fmt: skip
        self.assertEqual(facing.rows_at(0.0, 5.0, 6.0, 4.2), [-0.5, 2.0], "narrower than the tool: still in from the edge")
        self.assertEqual([round(v, 6) for v in facing.rows_at(0.0, 100.0, 50.0, 20.0, True, 2.0)], [-8.0, 9.0, 26.0, 43.0, 60.0, 77.0], "the last one 2 mm past the far end")  # fmt: skip
        self.assertEqual([round(v, 6) for v in facing.rows_at(0.0, 100.0, 50.0, 20.0, False, 5.0)], [107.5, 90.0, 72.5, 55.0, 37.5, 20.0], "from the high end, 5 mm past the low one")  # fmt: skip

    def test_axes(self):
        """The first pass climbs (M3): the uncut material on its left."""
        self.assertEqual(facing.Facing(direction=facing.X_PLUS).axes(), ((0, 1), (1, 1)))
        self.assertEqual(facing.Facing(direction=facing.X_MINUS).axes(), ((0, -1), (1, -1)))
        self.assertEqual(facing.Facing(direction=facing.Y_PLUS).axes(), ((1, 1), (0, -1)))
        self.assertEqual(facing.Facing(direction=facing.Y_MINUS).axes(), ((1, -1), (0, 1)))

    def test_start_side(self):
        """The user's side across the passes, else the climbing one."""
        self.assertEqual(facing.Facing(start_side=facing.FROM_PLUS).axes(), ((0, 1), (1, -1)), "X+ from Y+")
        self.assertEqual(facing.Facing(start_side=facing.FROM_MINUS).axes(), ((0, 1), (1, 1)), "X+ from Y-: climbing")
        self.assertEqual(facing.Facing(direction=facing.Y_PLUS, start_side=facing.FROM_MINUS).axes(), ((1, 1), (0, 1)))
        self.assertEqual(facing.Facing(direction=facing.Y_MINUS, start_side=facing.FROM_PLUS).axes(), ((1, -1), (0, -1)))
        sides = [facing.climbing_side(d) for d in facing.DIRECTIONS]
        self.assertEqual(sides, [facing.FROM_MINUS, facing.FROM_PLUS, facing.FROM_PLUS, facing.FROM_MINUS])
        every = facing.Facing(direction=facing.Y_PLUS, start_side=facing.FROM_MINUS)
        self.assertEqual(operations.from_json(operations.to_json(every)), every)
        old = operations.to_json(facing.Facing()).replace(', "start_side": null', "")
        self.assertNotIn("start_side", old)
        self.assertEqual(operations.from_json(old), facing.Facing(), "saved before the start side")

    def rectangle(self, values, rows=(-4.0, 0.0, 4.0)):
        return facing.plan([(v, ((-10.0, 10.0),)) for v in rows], values, _always, _always)

    def test_zigzag(self):
        """One run: back and forth, joined by half circles beyond the ends."""
        plan = self.rectangle(facing.Facing())
        self.assertEqual(len(plan.runs), 1)
        run = plan.runs[0]
        self.assertEqual(run.start, (-10.0, -4.0))
        self.assertEqual(
            run.moves,
            (
                ("line", (10.0, -4.0)),
                ("arc", (10.0, 0.0), (10.0, -2.0), False),
                ("line", (-10.0, 0.0)),
                ("arc", (-10.0, 4.0), (-10.0, 2.0), True),
                ("line", (10.0, 4.0)),
            ),
        )
        self.assertEqual(plan.closed_entries(), 0)

    def test_zigzag_along_y(self):
        """Y+: the passes go along Y, the first one up, stepping to -X."""
        plan = self.rectangle(facing.Facing(direction=facing.Y_PLUS), rows=(4.0, 0.0))
        run = plan.runs[0]
        self.assertEqual(run.start, (4.0, -10.0))
        self.assertEqual(run.moves, (("line", (4.0, 10.0)), ("arc", (0.0, 10.0), (2.0, 10.0), False), ("line", (0.0, -10.0))))  # fmt: skip

    def test_one_way(self):
        """Every pass the same way, each a run; the tool goes back over the
        area at the level, 2 mm over the material."""
        plan = self.rectangle(facing.Facing(pattern=facing.ONE_WAY))
        self.assertEqual([run.start for run in plan.runs], [(-10.0, -4.0), (-10.0, 0.0), (-10.0, 4.0)])
        self.assertEqual([run.moves for run in plan.runs], [(("line", (10.0, v)),) for v in (-4.0, 0.0, 4.0)])
        self.assertTrue(all(run.direct for run in plan.runs))

    def test_wall_at_the_end(self):
        """A wall where the passes end: no half circle into it, a straight
        line along it."""

        def fits(points):
            return all(x <= 10.0 + 1e-9 for x, _y in points)

        plan = facing.plan([(v, ((-10.0, 10.0),)) for v in (-4.0, 0.0)], facing.Facing(), fits, _always)
        self.assertEqual(plan.runs[0].moves[1], ("line", (10.0, 0.0)))

    def test_new_run_when_nothing_fits(self):
        """No way along the walls to the next pass: the tool lifts; a run
        starts at its end outside the stock (the other way than the user's
        when only that one is)."""

        def fits(points):
            return all(not (-1.0 < y < 1.0) or x < -20.0 for x, y in points)

        def outside(x, _y):
            return x > 9.0

        rows = [(-4.0, ((-10.0, 10.0),)), (4.0, ((-10.0, 10.0),))]
        plan = facing.plan(rows, facing.Facing(), fits, outside)
        self.assertEqual([run.start for run in plan.runs], [(10.0, -4.0), (10.0, 4.0)])
        self.assertEqual(plan.closed_entries(), 0)
        self.assertFalse(plan.runs[1].direct)
        plan = facing.plan(rows, facing.Facing(), fits, lambda x, y: False)
        self.assertEqual([run.start for run in plan.runs], [(-10.0, -4.0), (-10.0, 4.0)], "the user's way")
        self.assertEqual(plan.closed_entries(), 2, "down into the material")

    def test_around_an_island(self):
        """Two stretches on a line: the zigzag goes on with the one on the
        side where the tool is; the other one later."""

        def fits(points):
            return all(not (-3.0 < x < 3.0 and -3.0 < y < 3.0) for x, y in points)

        rows = [(-4.0, ((-10.0, 10.0),)), (0.0, ((-10.0, -3.0), (3.0, 10.0))), (4.0, ((-10.0, 10.0),))]
        plan = facing.plan(rows, facing.Facing(), fits, _always)
        self.assertEqual(plan.runs[0].moves[:3], (("line", (10.0, -4.0)), ("arc", (10.0, 0.0), (10.0, -2.0), False), ("line", (3.0, 0.0))))  # fmt: skip
        self.assertEqual(len(plan.runs), 3)
        self.assertEqual(plan.runs[1].start, (-10.0, 0.0), "the left stretch, from outside")

    def test_walls(self):
        """The walls after the passes; the tool comes down to them where the
        passes cut (within the tool's radius), else it counts as into the
        material."""
        plan = self.rectangle(facing.Facing(pattern=facing.ONE_WAY), rows=(0.0,))
        wall = ((0.0, 2.0), (("line", (5.0, 2.0)),))
        far = ((0.0, 9.0), (("line", (5.0, 9.0)),))
        both = facing.with_walls(plan, [wall, far], _always, lambda x, y: False, 3.0)
        self.assertEqual([run.open_entry for run in both.runs], [False, True, False])
        start, moves = facing.reversed_moves((0.0, 0.0), (("line", (1.0, 0.0)), ("arc", (2.0, 1.0), (2.0, 0.0), False)))
        self.assertEqual((start, moves), ((2.0, 1.0), (("arc", (1.0, 0.0), (2.0, 0.0), True), ("line", (0.0, 0.0)))))

    def test_moves(self):
        """Down to Z+20 over the first start, rapid 2 mm over the material,
        with the Z feed to the level; after a run up 2 mm over the level
        above and across (inside the area), up at the end."""
        plan = self.rectangle(facing.Facing(), rows=(0.0,))
        moves = facing.moves(plan, [-1.0, -2.0], 1.0, 3.0, 300.0, 900.0)
        expected = [
            nc.Move(nc.RAPID, -10.0, 0.0, 20.0),
            nc.Move(nc.RAPID, -10.0, 0.0, 3.0),
            nc.Move(nc.LINE, -10.0, 0.0, -1.0, 300.0),
            nc.Move(nc.LINE, 10.0, 0.0, -1.0, 900.0),
            nc.Move(nc.RAPID, 10.0, 0.0, 3.0),
            nc.Move(nc.RAPID, -10.0, 0.0, 3.0),
            nc.Move(nc.RAPID, -10.0, 0.0, 1.0),
            nc.Move(nc.LINE, -10.0, 0.0, -2.0, 300.0),
            nc.Move(nc.LINE, 10.0, 0.0, -2.0, 900.0),
            nc.Move(nc.RAPID, 10.0, 0.0, 1.0),
            nc.Move(nc.RAPID, 10.0, 0.0, 3.0),
        ]
        self.assertEqual(list(moves), expected)
        arcs = [m for m in facing.moves(self.rectangle(facing.Facing()), [0.0], 1.0, 3.0, 300.0, 900.0) if m.kind == nc.ARC]
        self.assertEqual([(m.center, m.clockwise, m.z, m.feed_mm_min) for m in arcs], [((10.0, -2.0), False, 0.0, 900.0), ((-10.0, 2.0), True, 0.0, 900.0)])  # fmt: skip


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestFacingEngine(unittest.TestCase):
    """The plate of the adaptive tests: 40 x 20, its top at Z-2 of the setup,
    a boss 10 x 6 on its left edge up to Z0, a pocket 14 x 10 down to Z-5;
    the stock 1 mm around and on top (Z+1); T5 (Ø6, Aluminium)."""

    def setUp(self):
        from avangardecam.engine import facing as engine_facing
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.model import library
        from avangardecam.tests.test_engine import TestEngine
        from avangardecam.tests.test_model import LIBRARY

        self.cam, self.engine = cam, engine_facing
        self.helpers = TestEngine("setUp")
        self.doc = FreeCAD.newDocument("AvangardeCamFacing")
        self.helpers.doc = self.doc
        self.helpers.library = library.load(LIBRARY)
        self.plate, self.job, self.tc = self.helpers.adaptive_setup()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def floor(self, z, x=None):
        return self.helpers.floor(self.plate, z, x)

    def cuts(self, op):
        return self.helpers.cuts(op)

    def boss_distance(self, p):
        return self.helpers.box_distance(p, -20, -3, -10, 3)

    def cleared(self, segments, points, msg):
        self.helpers.assertCleared(segments, points, 3.0 + 1e-3, msg)

    def test_top_face_over_the_whole_stock(self):
        """Nothing above the face: the whole stock, zigzag along X, half
        circles out past the stock."""
        op = self.engine.add_facing(self.job, facing.Facing(), self.tc, self.plate, [self.floor(12.0)])
        self.assertEqual(self.engine.facing_of(op), (self.plate, facing.Facing()))
        self.assertEqual(op.Label, "Facing 1")
        self.assertEqual(self.engine.facing_faces(op), [self.floor(12.0)])
        cuts = self.cuts(op)
        self.assertEqual(list(cuts), [0.0])
        grid = [(x * 1.0, y * 1.0) for x in range(-21, 22) for y in range(-11, 12)]
        self.cleared(cuts[0.0], grid, "all the stock")
        xs = [p[0] for s in cuts[0.0] for p in s]
        self.assertAlmostEqual(min(xs), -21.0 - 3.0 - 2.0 - 2.0, places=6, msg="out past the stock by the overrun, the half circles beyond")  # fmt: skip
        arcs = [c for c in op.Path.Commands if c.Name in ("G2", "G3")]
        self.assertEqual(len(arcs), 5, "six passes, five half circles")
        first = next(c for c in op.Path.Commands if c.Name == "G1")
        self.assertAlmostEqual(first.Placement.Base.y, -10.0, msg="in over the stock's Y- edge, 4 mm of 24")
        # from Y+: the first pass in over the other edge, conventional
        values = facing.Facing(start_side=facing.FROM_PLUS)
        op = self.engine.add_facing(self.job, values, self.tc, self.plate, [self.floor(12.0)])
        ys = [c.Placement.Base.y for c in op.Path.Commands if c.Name == "G1"]
        self.assertAlmostEqual(ys[0], 10.0, msg="in over the stock's Y+ edge")
        self.assertAlmostEqual(min(ys), -10.0, msg="the tool's edge the overrun past the Y- edge")
        self.assertAlmostEqual(self.cam.path_summary(op)[1], 0.0)
        # FreeCAD's own values follow the user's, for expert mode
        self.assertAlmostEqual(op.StartDepth.Value, 1.0)
        self.assertAlmostEqual(op.FinalDepth.Value, 0.0)
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0)
        self.assertAlmostEqual(op.ClearanceHeight.Value, 20.0)
        self.assertEqual((op.ClearingPattern, op.StepOver, op.BoundaryShape), ("ZigZag", 70, "Stock"))

    def test_only_the_top(self):
        """For now (the user's choice) only a face at the very top: the
        plate's top under the boss and the pocket's floor are refused."""
        for z, x in ((10.0, 18.0), (7.0, None)):
            with self.assertRaises(self.cam.ProjectError) as caught:
                self.engine.add_facing(self.job, facing.Facing(), self.tc, self.plate, [self.floor(z, x)])
            self.assertIn("top of the model", str(caught.exception))
            self.assertIn("up to Z+0.000", str(caught.exception))
        self.assertIsNone(self.engine.material_top(self.job, 0.0))
        self.assertAlmostEqual(self.engine.material_top(self.job, -2.0), 0.0)
        self.assertEqual(self.cam.operations(self.job), [], "nothing made")

    def plan_points(self, plan):
        return [run.start for run in plan.runs] + [m[1] for run in plan.runs for m in run.moves]

    def test_area_beside_walls(self):
        """For later (faces lower down): the plate's top up to the boss going
        up from it, the tool's edge on its walls (or at the offset), around
        it out past the stock, then once along it; the pocket's floor, walls
        all around: the tool comes down in it; a tool too big for it."""
        base = self.cam.picked_floors(self.job, self.plate, [self.floor(10.0, x=18.0)])
        plan, rows, walls = self.engine.plan_for(self.job, facing.Facing(), base, 6.0)
        self.assertEqual((rows, walls), (6, 1))
        near = min(self.boss_distance(p) for p in self.plan_points(plan))
        self.assertAlmostEqual(near, 3.0, delta=0.01, msg="the tool's edge on the boss")
        self.assertEqual(plan.closed_entries(), 0, "in from outside the stock, to the boss where the passes cut")
        plan = self.engine.plan_for(self.job, facing.Facing(offset_xy_mm=0.5), base, 6.0)[0]
        self.assertAlmostEqual(min(self.boss_distance(p) for p in self.plan_points(plan)), 3.5, delta=0.01)
        pocket = self.cam.picked_floors(self.job, self.plate, [self.floor(7.0)])
        plan = self.engine.plan_for(self.job, facing.Facing(), pocket, 6.0)[0]
        for p in self.plan_points(plan):
            self.assertTrue(3.0 - 1e-6 <= p[0] <= 11.0 + 1e-6 and -2.0 - 1e-6 <= p[1] <= 2.0 + 1e-6, p)
        self.assertGreater(plan.closed_entries(), 0)
        with self.assertRaises(self.cam.ProjectError) as caught:
            self.engine.plan_for(self.job, facing.Facing(), pocket, 50.0)
        self.assertIn("does not fit", str(caught.exception))

    def test_start_z_and_one_way(self):
        values = facing.Facing(start_z_mm=-1.0, pattern=facing.ONE_WAY, direction=facing.Y_MINUS)
        with self.assertRaises(self.cam.ProjectError):
            self.engine.add_facing(self.job, values, self.tc, self.plate, [self.floor(12.0)])  # Start Z under the face (Z0)
        values = facing.Facing(start_z_mm=0.5, pattern=facing.ONE_WAY, direction=facing.Y_MINUS)
        op = self.engine.add_facing(self.job, values, self.tc, self.plate, [self.floor(12.0)])
        self.assertAlmostEqual(op.StartDepth.Value, 0.5)
        self.assertAlmostEqual(op.SafeHeight.Value, 3.0, msg="2 mm over the stock, above Start Z")
        self.assertEqual(op.ClearingPattern, "Line")
        position = None
        along = 0
        for c in op.Path.Commands:
            p = c.Parameters
            if c.Name not in ("G0", "G1", "G2", "G3"):
                continue
            to = tuple(p.get(a, position[i] if position else 0.0) for i, a in enumerate("XYZ"))
            if c.Name == "G1" and position is not None and abs(to[2] - position[2]) < 1e-9 and abs(to[0] - position[0]) < 1e-9:
                along += 1
                self.assertLess(to[1], position[1], "every pass along Y towards Y-")
            position = to
        self.assertEqual(along, 11, "the stock 42 wide and the overrun 2, Ø6 at most 4.2 mm apart: 11 passes")

    def test_refuses(self):
        cam, engine = self.cam, self.engine
        drill = cam.add_tool(self.job, self.helpers.variant(40, "RVS"))
        with self.assertRaises(cam.ProjectError):
            engine.add_facing(self.job, facing.Facing(), drill, self.plate, [self.floor(12.0)])
        with self.assertRaises(cam.ProjectError) as caught:
            engine.add_facing(self.job, facing.Facing(), self.tc, self.plate, [self.floor(12.0), self.floor(10.0, x=18.0)])
        self.assertIn("different heights", str(caught.exception))
        with self.assertRaises(cam.ProjectError):
            engine.add_facing(self.job, facing.Facing(), self.tc, self.plate, [self.helpers.face(self.plate, (1, 0, 0))])
        with self.assertRaises(cam.ProjectError):
            engine.add_facing(self.job, facing.Facing(), self.tc, self.plate, [])
        self.assertEqual(cam.operations(self.job), [], "nothing made")

    def test_nc_program(self):
        from avangardecam.post import heidenhain

        self.engine.add_facing(self.job, facing.Facing(), self.tc, self.plate, [self.floor(12.0)])
        text = heidenhain.write(self.cam.nc_program(self.doc, "FACING"))
        lines = [line.split(" ", 1)[1] for line in text.split("\r\n") if line]
        self.assertIn("*- Facing", lines)
        self.assertTrue(any(line.startswith("CC X+") for line in lines), "the half circles")
        start = next(i for i, line in enumerate(lines) if line.startswith("FN0: Q31="))
        self.assertEqual(lines[start + 1 : start + 4], ["L X-26. Y-10. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+3. R0 FMAX"])

    def test_changes_and_file(self):
        import os
        import tempfile

        op = self.engine.add_facing(self.job, facing.Facing(), self.tc, self.plate, [self.floor(12.0)])
        t7 = self.cam.add_tool(self.job, self.helpers.variant(7, "Aluminium"))  # Ø10
        self.cam.set_tool(op, t7)
        grid = [(x * 1.0, y * 1.0) for x in range(-21, 22) for y in range(-11, 12)]
        self.helpers.assertCleared(self.cuts(op)[0.0], grid, 5.0 + 1e-3, "Ø10: all the stock")
        self.cam.change_operation(op, facing.Facing(z_step_mm=0.4), self.tc)
        self.assertEqual(sorted(self.cuts(op), reverse=True), [0.6, 0.2, 0.0])
        with self.assertRaises(self.cam.ProjectError):
            self.cam.set_tool(op, self.cam.add_tool(self.job, self.helpers.variant(40, "RVS")))
        path = os.path.join(tempfile.mkdtemp(), "facing.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        job = self.cam.find_job(self.doc)
        op = self.cam.operations(job)[0]
        self.assertEqual(self.engine.facing_of(op)[1], facing.Facing(z_step_mm=0.4))
        self.assertEqual(type(op.Proxy).__module__, "avangardecam.engine.facing")
        op.touch()
        self.doc.recompute()
        self.assertEqual(sorted(self.cuts(op), reverse=True), [0.6, 0.2, 0.0])
        # the zero point turned: the stock goes with it, new X = old Y
        self.cam.rotate_zero(job, 90.0)
        cuts = self.cuts(op)
        self.assertEqual(sorted(cuts, reverse=True), [0.6, 0.2, 0.0])
        grid = [(x * 1.0, y * 1.0) for x in range(-11, 12) for y in range(-21, 22)]
        self.helpers.assertCleared(cuts[0.0], grid, 3.0 + 1e-3, "all the turned stock")
        xs = [p[0] for s in cuts[0.0] for p in s]
        self.assertAlmostEqual(min(xs), -11.0 - 3.0 - 2.0 - 2.0, places=6, msg="out past the turned stock by the overrun, the half circles beyond")  # fmt: skip


if __name__ == "__main__":
    unittest.main()
