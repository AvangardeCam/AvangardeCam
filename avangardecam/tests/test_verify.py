# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Verification tests. The model ones are plain Python with numpy:

    python3 -m unittest avangardecam.tests.test_verify   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import dataclasses
import math
import unittest

import numpy as np

from avangardecam.model import crashes, helix, nc, operations, threads, verify
from avangardecam.model.stock import Bounds
from avangardecam.model.tools import Tool

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

MILL_6 = Tool("Frees 6mm", "Endmill", 6.0, cutting_length_mm=15.0)
MILL_3 = Tool("Frees 3mm", "Endmill", 3.0, cutting_length_mm=10.0)
NC_6 = nc.Tool(1, "Frees 6mm", 6.0, 8000.0, 200.0, 600.0)


def box_mesh(lower, upper):
    """A closed box of 12 triangles, counterclockwise seen from outside."""
    (x0, y0, z0), (x1, y1, z1) = lower, upper
    vertices = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    triangles = [
        (0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6),  # bottom, top
        (0, 1, 4), (1, 5, 4), (2, 6, 3), (3, 6, 7),  # front, back
        (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5),  # left, right
    ]  # fmt: skip
    return np.array(vertices, float), np.array(triangles)


class ToolTest(unittest.TestCase):
    def test_shapes(self):
        flat = verify.stock_tool(MILL_6)
        self.assertAlmostEqual(flat.radius, 3.0)
        self.assertAlmostEqual(flat.length, 15.0)
        ball = verify.stock_tool(Tool("Bol 6", "Ballend", 6.0, cutting_length_mm=12.0))
        self.assertAlmostEqual(float(ball.parts[0].radius(0.0)), 0.0)
        bull = verify.stock_tool(Tool("R1", "Bullnose", 10.0, corner_radius_mm=1.0, cutting_length_mm=20.0))
        self.assertAlmostEqual(float(bull.parts[0].radius(0.0)), 4.0)
        drill = verify.stock_tool(Tool("Boor 6.8", "Drill", 6.8, angle_deg=140.0, cutting_length_mm=40.0))
        self.assertAlmostEqual(float(drill.parts[0].radius(0.0)), 0.0)
        tip = 3.4 / math.tan(math.radians(70.0))
        self.assertAlmostEqual(float(drill.parts[0].radius(tip)), 3.4)
        chamfer = verify.stock_tool(Tool("Fase", "Chamfer", 10.0, angle_deg=90.0, tip_diameter_mm=1.0))
        self.assertAlmostEqual(float(chamfer.parts[0].radius(0.0)), 0.5)
        self.assertAlmostEqual(chamfer.length, 30.0)  # 3 diameters without a cutting length

    def test_no_length_no_angle(self):
        drill = verify.stock_tool(Tool("Boor 2", "Drill", 2.0))
        self.assertAlmostEqual(drill.length, 6.0)
        self.assertAlmostEqual(float(drill.parts[0].radius(1.0 / math.tan(math.radians(59.0)))), 1.0)


class VerifyTest(unittest.TestCase):
    """A part 30 x 20 x 9 under a stock 1 mm higher, faced by a Ø6 end mill."""

    def run_facing(self, z, kind=nc.FACING):
        moves = [nc.Move(nc.RAPID, -5.0, y, 2.0) for y in (2.0,)]
        moves += [nc.Move(nc.LINE, -5.0, 2.0, z, 200.0)]
        for k, y in enumerate((2.0, 7.0, 12.0, 17.0)):
            x = 35.0 if k % 2 == 0 else -5.0
            moves += [nc.Move(nc.LINE, -5.0 if k % 2 == 0 else 35.0, y, z, 600.0), nc.Move(nc.LINE, x, y, z, 600.0)]
        op = nc.Operation(kind, "Facing", NC_6, tuple(moves))
        setup = nc.Setup(1, "Setup 1", Bounds(0.0, 0.0, -9.0, 30.0, 20.0, 1.0), (op,))
        vertices, triangles = box_mesh((0.0, 0.0, -9.0), (30.0, 20.0, 0.0))
        planned = verify.plan(setup, {1: MILL_6})
        steps = []
        result = verify.verify(setup.stock, vertices, triangles, planned, resolution=60, progress=steps.append)
        self.assertEqual(steps[0], "Cutting the stock")
        return result

    def test_faced_to_the_part(self):
        result = self.run_facing(0.0)
        self.assertEqual(result.gouges, ())
        self.assertEqual(result.collisions, ())
        self.assertEqual(len(result.vertices), len(result.colors))
        top = result.vertices[:, 2] > -0.01
        self.assertTrue(top.any())
        # the top of the part is finished: gray, not blue
        np.testing.assert_allclose(result.colors[top & (result.vertices[:, 2] < 0.01)].max(axis=0), verify.stock_verify.GRAY)

    def test_too_deep(self):
        result = self.run_facing(-0.5)
        self.assertEqual(len(result.gouges), 1)
        gouge = result.gouges[0]
        self.assertEqual(gouge.operation, "Facing")
        self.assertAlmostEqual(gouge.depth_mm, 0.5, places=3)
        red = (result.colors[:, 0] > 0.8) & (result.colors[:, 2] < 0.1)
        self.assertTrue(red.any())

    def test_not_checked(self):
        self.assertEqual(self.run_facing(-0.5, nc.THREAD_MILLING).gouges, ())

    def test_rapid_into_the_stock(self):
        moves = (nc.Move(nc.RAPID, 15.0, 10.0, 2.0), nc.Move(nc.RAPID, 15.0, 10.0, -3.0), nc.Move(nc.LINE, 20.0, 10.0, -3.0, 600.0))
        setup = nc.Setup(1, "Setup 1", Bounds(0.0, 0.0, -9.0, 30.0, 20.0, 1.0), (nc.Operation(nc.CONTOUR, "Pocket", NC_6, moves),))
        vertices, triangles = box_mesh((-50.0, -50.0, -60.0), (-40.0, -40.0, -50.0))  # the part out of the way
        result = verify.verify(setup.stock, vertices, triangles, verify.plan(setup, {1: MILL_6}), resolution=60)
        self.assertEqual(len(result.collisions), 1)
        c = result.collisions[0]
        self.assertEqual((c.operation, c.end), ("Pocket", (15.0, 10.0, -3.0)))
        self.assertAlmostEqual(c.volume_mm3, math.pi * 9.0 * 4.0, delta=3.0)

    def test_shank_into_the_stock(self):
        """A thread mill M4 (teeth Ø3.2 2.1 high, neck Ø2.4 up to 12.5, shank
        Ø6 up to 22) along a helix 14 deep in a hole of Ø3.3: its shank in
        the hole from 12.5 deep on."""
        mill = Tool("Draadfrees M4", "ThreadMill", 3.2, pitch_mm=0.7, cutting_length_mm=2.1, length_mm=22.0,
                    shank_diameter_mm=6.0, neck_diameter_mm=2.4, neck_length_mm=12.5)  # fmt: skip
        shank = crashes.shank_tool(mill)
        self.assertEqual([(p.h0, p.h1, p.rmax) for p in shank.parts], [(2.1, 12.5, 1.2), (12.5, 22.0, 3.0)])
        tool = nc.Tool(1, "Draadfrees M4", 3.2, 12000.0, 225.0, 300.0)
        drill = nc.Tool(2, "Boor 3.3", 3.3, 3000.0, 100.0, 100.0)
        hole = (nc.Move(nc.RAPID, 15.0, 10.0, 2.0), nc.Move(nc.LINE, 15.0, 10.0, -15.0, 100.0), nc.Move(nc.RAPID, 15.0, 10.0, 2.0))
        moves = [nc.Move(nc.RAPID, 15.0, 10.0, 2.0), nc.Move(nc.LINE, 15.0, 10.0, 0.0, 300.0), nc.Move(nc.LINE, 15.4, 10.0, 0.0, 300.0)]
        z = 0.0
        for k in range(40):  # half turns down to -14
            z -= 0.35
            x = 14.6 if k % 2 == 0 else 15.4
            moves.append(nc.Move(nc.ARC, x, 10.0, z, 225.0, center=(15.0, 10.0), clockwise=True))
        moves += [nc.Move(nc.LINE, 15.0, 10.0, z, 225.0), nc.Move(nc.RAPID, 15.0, 10.0, 2.0)]
        ops = (nc.Operation(nc.CONTOUR, "Drilling", drill, hole), nc.Operation(nc.THREAD_MILLING, "Thread", tool, tuple(moves)))
        setup = nc.Setup(1, "Setup 1", Bounds(0.0, 0.0, -20.0, 30.0, 20.0, 0.0), ops)
        vertices, triangles = box_mesh((-50.0, -50.0, -60.0), (-40.0, -40.0, -50.0))  # the part out of the way
        tools = {1: mill, 2: Tool("Boor 3.3", "Drill", 3.3, angle_deg=118.0, cutting_length_mm=20.0)}
        result = verify.verify(setup.stock, vertices, triangles, verify.plan(setup, tools), resolution=100)
        self.assertTrue(result.collisions)
        self.assertEqual({c.kind for c in result.collisions}, {crashes.SHANK})
        self.assertTrue(all(c.operation == "Thread" for c in result.collisions))
        self.assertGreater(min(c.end[2] for c in result.collisions), -14.01)
        self.assertLess(max(c.start[2] for c in result.collisions), -12.0)  # not before 12.5 deep (an arc: from half a turn above)
        # the shank Ø6, 0.4 off the hole's axis (round it out to R3.4), in the
        # thread the teeth cut (R2.0) for 1.5 mm
        volume = sum(c.volume_mm3 for c in result.collisions)
        self.assertAlmostEqual(volume, math.pi * (3.4**2 - 2.0**2) * 1.5, delta=0.1 * math.pi * (3.4**2 - 2.0**2) * 1.5)
        # with a neck as long as the hole is deep: none
        tools[1] = dataclasses.replace(mill, neck_length_mm=15.0)
        result = verify.verify(setup.stock, vertices, triangles, verify.plan(setup, tools), resolution=100)
        self.assertEqual(result.collisions, ())

    def test_shank_after_the_cutter_round_a_helix(self):
        """A Ø4 end mill (flutes 6 long) milling a hole Ø6 along a helix 12
        deep: a shank Ø4 goes where the flutes went (nothing, also not what
        the chords of the arcs leave); a shank Ø6 goes round R1 + 3 in the
        hole of R3 from 5 deep on (the stock 1 over the top)."""
        tool = nc.Tool(1, "Frees 4", 4.0, 12000.0, 270.0, 360.0)
        moves = [nc.Move(nc.RAPID, 16.0, 10.0, 3.0), nc.Move(nc.LINE, 16.0, 10.0, 1.0, 270.0)]
        z = 1.0
        for k in range(48):  # half turns down to -11
            z -= 0.25
            moves.append(nc.Move(nc.ARC, 14.0 if k % 2 == 0 else 16.0, 10.0, z, 360.0, center=(15.0, 10.0)))
        moves += [nc.Move(nc.ARC, 14.0, 10.0, z, 360.0, center=(15.0, 10.0)), nc.Move(nc.ARC, 16.0, 10.0, z, 360.0, center=(15.0, 10.0))]
        moves.append(nc.Move(nc.RAPID, 16.0, 10.0, 5.0))
        setup = nc.Setup(1, "Setup 1", Bounds(0.0, 0.0, -15.0, 30.0, 20.0, 1.0), (nc.Operation(nc.HELIX_MILLING, "Helix", tool, tuple(moves)),))
        vertices, triangles = box_mesh((-50.0, -50.0, -60.0), (-40.0, -40.0, -50.0))  # the part out of the way
        for shank, expected in ((4.0, 0.0), (6.0, math.pi * (4.0**2 - 3.0**2) * 6.0)):
            mill = Tool("Frees 4", "Endmill", 4.0, cutting_length_mm=6.0, length_mm=20.0, shank_diameter_mm=shank)
            result = verify.verify(setup.stock, vertices, triangles, verify.plan(setup, {1: mill}), resolution=80)
            self.assertEqual({c.kind for c in result.collisions} - {crashes.SHANK}, set())
            self.assertAlmostEqual(sum(c.volume_mm3 for c in result.collisions), expected, delta=0.1 * max(expected, 1.0), msg=shank)

    def test_rapid_moves_as_the_stock_model_finds_them(self):
        """model.crashes finds the rapid moves into material the stock
        model's simulate finds (each cut on its own there): down into the
        block, across it, up and down again in a pocket cut just before
        (none), and leaves the same stock."""
        from avangardecam import stocklab

        def line(a, b, rapid=True):
            return stocklab.Line(a, b, rapid=rapid)

        moves = [
            line((5, 5, 5), (5, 5, -2)),  # down into the block
            line((5, 5, -2), (15, 5, -2), False),
            line((15, 5, -2), (15, 5, 3)),  # up out of the pocket: nothing
            line((15, 5, 3), (15, 5, -1.5)),  # down into it again: nothing
            line((15, 5, -1.5), (15, 15, -1.5)),  # across the block
            line((15, 15, -1.5), (15, 15, 5)),
            line((25, 15, 5), (25, 15, 0.5)),  # above it: nothing
        ]
        moves.append(stocklab.Arc((25, 15, -1), (25, 15, -1), (22, 15, 0), ccw=True))
        moves.append(line((25, 15, -1), (25, 15, 5)))
        operation = stocklab.Operation(verify.stock_tool(MILL_6), "+Z", moves)
        old = stocklab.Stock.box((0, 0, -9), (30, 20, 0), 60)
        new = old.copy()
        expected = stocklab.simulate(old, [operation])
        found = crashes.simulate(new, [operation], [None])
        self.assertEqual([c.move for c in expected], [0, 4])
        self.assertEqual([(c.operation, c.move) for c in found], [(c.operation, c.move) for c in expected])
        self.assertEqual({c.kind for c in found}, {crashes.RAPID})
        for a, b in zip(expected, found):
            self.assertAlmostEqual(a.volume, b.volume, places=6)
        self.assertAlmostEqual(old.volume(), new.volume(), places=6)

    def test_no_shank_without_a_cutting_length(self):
        self.assertIsNone(crashes.shank_tool(Tool("Boor 2", "Drill", 2.0)))
        self.assertIsNone(crashes.shank_tool(None))
        plain = crashes.shank_tool(MILL_6)  # no length: two diameters more, as drawn
        self.assertEqual([(p.h0, p.h1, p.rmax) for p in plain.parts], [(15.0, 27.0, 3.0)])

    def test_export(self):
        import os
        import tempfile

        result = self.run_facing(0.0)
        folder = tempfile.mkdtemp()
        ply, stl = os.path.join(folder, "a.ply"), os.path.join(folder, "a.STL")
        verify.export(result, ply)
        verify.export(result, stl)
        with open(ply, "rb") as f:
            head = f.read(200)
        self.assertIn(b"element vertex %d" % len(result.vertices), head)
        self.assertIn(b"property uchar red", head)
        self.assertEqual(os.path.getsize(stl), 84 + 50 * len(result.triangles))
        with self.assertRaises(ValueError):
            verify.export(result, os.path.join(folder, "a.step"))

    def test_unknown_tool(self):
        setup = nc.Setup(1, "Setup 1", None, (nc.Operation(nc.CONTOUR, "A", NC_6, (nc.Move(nc.RAPID, 0.0, 0.0, 2.0), nc.Move(nc.LINE, 1.0, 0.0, 0.0))),))
        with self.assertRaises(ValueError):
            verify.plan(setup, {})


THREAD_MILL = Tool("Draadfrees M3", "ThreadMill", 2.4, angle_deg=60.0, cutting_length_mm=1.33, pitch_mm=0.5)
NC_THREAD_MILL = nc.Tool(3, "Draadfrees M3", 2.4, 12000.0, 225.0, 300.0)


class ThreadHoleTest(unittest.TestCase):
    """M3 threads 6 deep milled in a plate 30 x 20 x 9 (top at Z0, the part
    out of the way), with or without their holes drilled first."""

    HOLES = ((10.0, 10.0), (20.0, 10.0))

    def run_threads(self, drill_mm=None, drill_depth=-8.0, resolution=60):
        thread = operations.ThreadMilling(3.0, -6.0, passes=2)
        moves = threads.moves(thread, [threads.ThreadHole(x, y, 0.0) for x, y in self.HOLES], 0.5, 1.5, 225.0, 300.0, nc.RIGHT)
        milling = nc.Operation(nc.THREAD_MILLING, "Thread milling", NC_THREAD_MILL, moves)
        tools = {3: THREAD_MILL}
        ops = (milling,)
        if drill_mm is not None:
            cycle = nc.DrillCycle(
                peck_mm=None, feed_mm_min=100.0, clearance_mm=2.0, second_clearance_mm=10.0, decrement_mm=0.0,
                min_peck_mm=0.0, upper_stop_mm=0.0, lower_stop_mm=0.0, chip_break_mm=0.0, chip_retract_mm=0.0,
                dwell_s=0.0, start_mm=0.0, preposition_feed_mm_min=0.0,
                holes=tuple(nc.DrillHole(x, y, 0.0, drill_depth) for x, y in self.HOLES),
            )  # fmt: skip
            tools[4] = Tool("Boor", "Drill", drill_mm, angle_deg=118.0, cutting_length_mm=20.0)
            ops = (nc.Operation(nc.DRILLING, "Drilling", nc.Tool(4, "Boor", drill_mm, 3000.0, 300.0, 300.0), (), cycle), milling)
        setup = nc.Setup(1, "Setup 1", Bounds(0.0, 0.0, -9.0, 30.0, 20.0, 0.0), ops)
        vertices, triangles = box_mesh((-50.0, -50.0, -60.0), (-40.0, -40.0, -50.0))
        return verify.verify(setup.stock, vertices, triangles, verify.plan(setup, tools), resolution=resolution)

    def test_teeth(self):
        # FreeCAD's minor diameter of M3: 2.45875 (with 1.0825 P)
        self.assertAlmostEqual(3.0 - 2.0 * verify.teeth_depth(THREAD_MILL), 2.45875, places=4)

    def test_planned_holes(self):
        thread = operations.ThreadMilling(3.0, -6.0, passes=2)
        moves = threads.moves(thread, [threads.ThreadHole(x, y, -1.0) for x, y in self.HOLES], 0.5, 1.5, 225.0, 300.0, nc.RIGHT)
        setup = nc.Setup(1, "Setup 1", None, (nc.Operation(nc.THREAD_MILLING, "Thread milling", NC_THREAD_MILL, moves),))
        planned = verify.plan(setup, {3: THREAD_MILL})[0]
        self.assertEqual([h.centre for h in planned.holes], [(10.0, 10.0, -1.0), (20.0, 10.0, -1.0)])
        self.assertAlmostEqual(planned.holes[0].bottom, -7.0)
        self.assertAlmostEqual(planned.holes[0].reach, 1.5)  # the teeth on the major diameter
        # every feed move in one of the holes, none twice
        feed = [i for i, m in enumerate(planned.operation.moves) if not m.rapid]
        self.assertEqual(sorted(planned.holes[0].moves + planned.holes[1].moves), feed)

    def test_no_hole(self):
        """The user's mistake (2026-10-27): a thread milled where no hole was drilled."""
        for resolution in (20, 60):  # a Rough stock's cells as wide as the hole: found all the same
            result = self.run_threads(resolution=resolution)
            self.assertEqual([h.centre[:2] for h in result.holes], list(self.HOLES))
            for h in result.holes:
                # the body inside the minor diameter, less a little: about its swept cylinder
                self.assertGreater(h.volume_mm3, 20.0)
                self.assertLess(h.volume_mm3, math.pi * 1.23**2 * 6.0)
        # red in and round each hole (1.5 cells of 0.5 beyond the teeth), nowhere else
        red = np.all(result.colors == verify.stock_verify.RED, axis=1)
        gap = [np.hypot(result.vertices[:, 0] - x, result.vertices[:, 1] - y) for x, y in self.HOLES]
        self.assertTrue(red[gap[0] < 1.5].any() and red[gap[1] < 1.5].any())
        self.assertFalse(red[(gap[0] > 2.3) & (gap[1] > 2.3)].any())

    def test_drilled(self):
        for drill_mm in (2.5, 2.46):  # the drill for M3, and the minor diameter
            result = self.run_threads(drill_mm)
            self.assertEqual([h.volume_mm3 for h in result.holes], [0.0, 0.0], drill_mm)
            self.assertFalse(np.all(result.colors == verify.stock_verify.RED, axis=1).any())
        # deep enough for the drill's point under the thread mill's body
        self.assertEqual([h.volume_mm3 for h in self.run_threads(2.5, -6.8).holes], [0.0, 0.0])

    def test_drilled_too_shallow(self):
        # the drill's point where the thread mill's end goes
        for h in self.run_threads(2.5, -6.0).holes:
            self.assertGreater(h.volume_mm3, 1.0)

    def test_drilled_too_small(self):
        for h in self.run_threads(2.0).holes:
            self.assertGreater(h.volume_mm3, 5.0)

    def test_other_operations_not_checked(self):
        self.assertEqual(VerifyTest("run_facing").run_facing(0.0).holes, ())


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestVerifyEngine(unittest.TestCase):
    """The part with holes of test_engine (top at Z12, the zero on its
    middle), its holes A (Ø6 through at x -15) and D (Ø10 3 deep at x 12)
    milled along a helix with a Ø4 end mill."""

    def setUp(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import helix as engine_helix
        from avangardecam.engine import verify as engine_verify
        from avangardecam.model import library
        from avangardecam.tests.test_engine import TestEngine
        from avangardecam.tests.test_model import LIBRARY

        self.cam, self.helix, self.engine = cam, engine_helix, engine_verify
        self.helpers = TestEngine("setUp")
        self.helpers.setUp()
        self.helpers.library = library.load(LIBRARY)
        self.doc = self.helpers.doc

    def tearDown(self):
        FreeCAD.closeDocument(self.helpers.doc.Name)

    def milled(self, values):
        obj = self.helpers.model_with_holes()
        job = self.cam.ensure_job(self.doc, [obj])
        tc = self.cam.add_tool(job, self.helpers.variant(3, "Aluminium"))  # Ø4
        holes = [self.helpers.wall(obj, -15, 0, 3)[0], self.helpers.wall(obj, 12, 0, 5)[0]]
        self.helix.add_model_helix_milling(job, obj, values, tc, holes)
        return job

    def test_prepared(self):
        job = self.milled(helix.HelixMilling())
        prepared = self.engine.prepare(job)
        self.assertEqual(prepared.label, job.Label)
        self.assertEqual([p.label for p in prepared.planned], ["Helix milling 1"])
        self.assertEqual(prepared.planned[0].kind, nc.HELIX_MILLING)
        self.assertAlmostEqual(prepared.stock.z_max, 1.0)  # 1 mm over the top
        # the part in the setup's coordinates: its top on Z0
        self.assertAlmostEqual(float(prepared.vertices[:, 2].max()), 0.0, places=6)
        self.assertAlmostEqual(float(prepared.vertices[:, 2].min()), -12.0, places=6)

    def test_clean(self):
        result = self.engine.run(self.engine.prepare(self.milled(helix.HelixMilling())), resolution=80)
        self.assertEqual([c for c in result.collisions if c.kind != crashes.SHANK], [])
        # but the Ø4's shank (Ø6, its flutes 6 long) round hole A (Ø6 through)
        # more than 5 below the top (the stock 1 over it)
        shank = [c for c in result.collisions if c.kind == crashes.SHANK]
        self.assertTrue(shank)
        self.assertTrue(all(abs(c.start[0] + 15.0) < 1.5 and min(c.start[2], c.end[2]) < -5.0 for c in shank))
        self.assertEqual(result.gouges, ())
        self.assertEqual(result.notes, ())

    def test_too_big(self):
        steps = []
        prepared = self.engine.prepare(self.milled(helix.HelixMilling(offset_xy_mm=0.2)))
        result = self.engine.run(prepared, resolution=80, progress=steps.append)
        self.assertIn("Checking for too deep", steps)
        self.assertEqual([g.operation for g in result.gouges], ["Helix milling 1"])
        self.assertAlmostEqual(result.gouges[0].depth_mm, 0.2, delta=0.01)  # the wall 0.2 further out

    def test_threads_holes(self):
        """M6 in A milled along a helix first has its hole; in C, a hole of
        the model the program never makes (the user's mistake, 2026-10-27),
        it has none."""
        obj = self.helpers.model_with_holes()
        job = self.cam.ensure_job(self.doc, [obj])
        a, c = self.helpers.wall(obj, -15, 0, 3)[0], self.helpers.wall(obj, 3, 0, 2.5)[0]
        self.helix.add_model_helix_milling(job, obj, helix.HelixMilling(), self.cam.add_tool(job, self.helpers.variant(3, "Aluminium")), [a])  # fmt: skip
        mill = self.cam.add_tool(job, self.helpers.variant(218, "Staal"))  # M5 thread mill, Ø4, P0.8
        self.cam.add_model_thread_milling(job, obj, operations.ThreadMilling(6.0, -5.0, passes=1), mill, [a, c])
        result = self.engine.run(self.engine.prepare(job), resolution=80)
        self.assertEqual([h.operation for h in result.holes], ["Thread milling 1"] * 2)
        self.assertEqual(result.holes[0].volume_mm3, 0.0)
        # the body Ø2.6 round a circle of R1 in C, 5 deep
        self.assertGreater(result.holes[1].volume_mm3, 60.0)

    def test_nothing_to_verify(self):
        obj = self.helpers.model_with_holes()
        job = self.cam.ensure_job(self.doc, [obj])
        with self.assertRaises(self.cam.ProjectError):
            self.engine.prepare(job)


if __name__ == "__main__":
    unittest.main()
