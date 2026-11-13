# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Cycle time tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_cycle_time   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import dataclasses
import math
import unittest

from avangardecam.model import cycle_time, machine, nc, operations, threads
from avangardecam.model.machine import Segment

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

TIMES = cycle_time.BRIDGEPORT_V1000
FULL_SPEED = dataclasses.replace(TIMES, acceleration_mm_s2=0.0)  # no dynamics
MILL_6 = nc.Tool(1, "Frees 6mm", 6.0, 8000.0, 200.0, 600.0)
DRILL_5 = nc.Tool(2, "Boor 5", 5.0, 3000.0, 100.0, 100.0)
THREAD_MILL = nc.Tool(3, "Draadfrees M3", 2.4, 12000.0, 225.0, 300.0)


def cycle(**values):
    fields = dict(
        peck_mm=3.0, feed_mm_min=100.0, clearance_mm=2.0, second_clearance_mm=10.0, decrement_mm=0.0,
        min_peck_mm=0.0, upper_stop_mm=0.2, lower_stop_mm=0.2, chip_break_mm=0.0, chip_retract_mm=0.2,
        dwell_s=0.0, start_mm=0.0, preposition_feed_mm_min=100.0, holes=(nc.DrillHole(0.0, 0.0, 0.0, -10.0),),
    )  # fmt: skip
    fields.update(values)
    return nc.DrillCycle(**fields)


def setup_of(*ops):
    return nc.Setup(1, "Setup 1", None, tuple(ops))


class MoveTest(unittest.TestCase):
    def test_rapid_the_slowest_axis(self):
        for end, seconds in (((430.0, 0.0, 0.0), 0.6), ((430.0, 430.0, 0.0), 0.6), ((43.0, 0.0, 360.0), 0.6), ((0.0, 0.0, -36.0), 0.06)):
            self.assertAlmostEqual(cycle_time.rapid_s(Segment((0.0, 0.0, 0.0), end, True), TIMES), seconds, msg=end)

    def test_length_of_a_helix(self):
        half = Segment((1.0, 0.0, 0.0), (-1.0, 0.0, -0.5), False, (0.0, 0.0), True)
        self.assertAlmostEqual(cycle_time.length(half), math.hypot(math.pi, 0.5))
        whole = Segment((1.0, 0.0, 0.0), (1.0, 0.0, 0.0), False, (0.0, 0.0), False)
        self.assertAlmostEqual(cycle_time.length(whole), 2.0 * math.pi)
        quarter = Segment((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), False, (0.0, 0.0), True)  # clockwise: three quarters
        self.assertAlmostEqual(cycle_time.length(quarter), 1.5 * math.pi)

    def test_duration_text(self):
        texts = [cycle_time.duration_text(s) for s in (0.04, 7.25, 45.4, 65.0, 799.0, 3725.0)]
        self.assertEqual(texts, ["0.0 s", "7.2 s", "45 s", "1 min 05 s", "13 min 19 s", "1 h 02 min"])


class OperationTimeTest(unittest.TestCase):
    def test_contour(self):
        """Down 3 mm at the Z feed, 100 mm along X at the XY feed, from Z100
        after the tool change: rapid to Z2, up to Z40 after."""
        moves = (nc.Move(nc.RAPID, 0.0, 0.0, 2.0), nc.Move(nc.LINE, 0.0, 0.0, -1.0, 200.0), nc.Move(nc.LINE, 100.0, 0.0, -1.0, 600.0))
        t = cycle_time.setup_time(setup_of(nc.Operation(nc.CONTOUR, "Contour", MILL_6, moves)), FULL_SPEED).operations[0]
        self.assertAlmostEqual(t.feed_s, 60.0 * (3.0 / 200.0 + 100.0 / 600.0))
        self.assertAlmostEqual(t.rapid_s, 60.0 * (98.0 + 41.0) / 36000.0)
        self.assertEqual((t.dwell_s, t.tool_change_s), (0.0, 1.5))

    def test_a_move_keeps_the_feed(self):
        moves = (nc.Move(nc.RAPID, 0.0, 0.0, 2.0), nc.Move(nc.LINE, 0.0, 0.0, -1.0, 300.0), nc.Move(nc.LINE, 100.0, 0.0, -1.0))
        t = cycle_time.setup_time(setup_of(nc.Operation(nc.CONTOUR, "Contour", MILL_6, moves)), FULL_SPEED).operations[0]
        self.assertAlmostEqual(t.feed_s, 60.0 * 103.0 / 300.0)

    def test_tool_change_once_per_tool(self):
        moves = (nc.Move(nc.RAPID, 0.0, 0.0, 2.0), nc.Move(nc.LINE, 10.0, 0.0, 0.0, 600.0))
        ops = [nc.Operation(nc.CONTOUR, name, tool, moves) for name, tool in (("A", MILL_6), ("B", MILL_6), ("C", THREAD_MILL))]
        result = cycle_time.setup_time(setup_of(*ops), FULL_SPEED)
        self.assertEqual([t.tool_change_s for t in result.operations], [1.5, 0.0, 1.5])
        self.assertEqual([t.tool for t in result.operations], ["T1 Frees 6mm", "T1 Frees 6mm", "T3 Draadfrees M3"])
        # C goes up from Z40 to the tool change height, back over X0, then down to Z2
        self.assertAlmostEqual(result.operations[2].rapid_s, 60.0 * ((60.0 + 98.0 + 40.0) / 36000.0 + 10.0 / 43000.0))
        self.assertAlmostEqual(result.total_s, sum(t.total_s for t in result.operations))
        self.assertAlmostEqual(result.part("tool_change_s"), 3.0)

    def test_thread_at_the_tool_centre(self):
        """M3 with RR: the TNC keeps the feed of the tool centre, on a helix
        of R0.3 (1.5 less the tool's 1.2), not of the programmed R1.5."""
        thread = operations.ThreadMilling(3.0, -6.0, passes=1)
        moves = threads.moves(thread, [threads.ThreadHole(0.0, 0.0, 0.0)], 0.5, 1.5, 225.0, 300.0, nc.RIGHT)
        t = cycle_time.setup_time(setup_of(nc.Operation(nc.THREAD_MILLING, "Thread", THREAD_MILL, moves)), FULL_SPEED).operations[0]
        helix = 24 * math.hypot(math.pi * 0.3, 0.25)  # half turns of 0.25 down to -6
        # down to the top at the Z feed, out to R0.3 and back to the centre at the XY feed
        self.assertAlmostEqual(t.feed_s, 60.0 * (2.0 / 225.0 + (0.3 + helix + 0.3) / 300.0), places=6)


class DrillingTest(unittest.TestCase):
    def test_pecks(self):
        self.assertEqual(machine.pecks(cycle(), 10.0), [3.0, 6.0, 9.0, 10.0])
        self.assertEqual(machine.pecks(cycle(decrement_mm=1.0, min_peck_mm=1.5), 10.0), [3.0, 5.0, 6.5, 8.0, 9.5, 10.0])
        self.assertEqual(machine.pecks(cycle(peck_mm=None), 10.0), [10.0])

    def drilled(self, **values):
        op = nc.Operation(nc.DRILLING, "Drilling", DRILL_5, (), cycle(**values))
        return cycle_time.setup_time(setup_of(op), FULL_SPEED).operations[0]

    def test_pecked(self):
        """10 deep in pecks of 3 from Z100: rapid to the set-up clearance
        (Z2), drill to -3, up to Z2 and down to 0.2 over -3 for each next
        peck, up to the 2nd set-up clearance (Z10) at the end."""
        t = self.drilled()
        self.assertAlmostEqual(t.feed_s, 60.0 * (5.0 + 3.2 + 3.2 + 1.2) / 100.0)
        self.assertAlmostEqual(t.rapid_s, 60.0 * (98.0 + (5.0 + 4.8) + (8.0 + 7.8) + (11.0 + 10.8) + 20.0) / 36000.0)
        self.assertEqual(self.drilled(peck_mm=None).feed_s, 60.0 * 12.0 / 100.0)

    def test_dwell_and_chip_breaking(self):
        t = self.drilled(peck_mm=None, dwell_s=0.5, chip_break_mm=4.0, holes=(nc.DrillHole(0.0, 0.0, 0.0, -10.0), nc.DrillHole(20.0, 0.0, 0.0, -10.0)))  # fmt: skip
        self.assertEqual(t.dwell_s, 1.0)
        self.assertAlmostEqual(t.feed_s, 2 * 60.0 * 12.0 / 100.0)  # the chip breaks take no feed
        # each hole: up 0.2 and down again at -4 and -8
        no_breaks = self.drilled(peck_mm=None, holes=(nc.DrillHole(0.0, 0.0, 0.0, -10.0), nc.DrillHole(20.0, 0.0, 0.0, -10.0)))
        self.assertAlmostEqual(t.rapid_s - no_breaks.rapid_s, 2 * 60.0 * 4 * 0.2 / 36000.0)

    def test_deepened_start(self):
        t = self.drilled(peck_mm=None, start_mm=4.0, preposition_feed_mm_min=200.0)
        # down to 2 over -4 at Q253, then drilled from there to -10
        self.assertAlmostEqual(t.feed_s, 60.0 * (4.0 / 200.0 + 8.0 / 100.0))


class DynamicsTest(unittest.TestCase):
    """The machine's dynamics (BRIDGEPORT_V1000: 2100 mm/s2, jerk
    100 000 mm/s3 on feed moves, none on rapid moves, corners within
    0.002 mm)."""

    @staticmethod
    def time(*segments, feed=600.0):
        feeds = [None if s.rapid else feed for s in segments]
        return sum(cycle_time._dynamic_times(list(segments), feeds, TIMES))

    @staticmethod
    def line(start, end, rapid=False):
        return Segment(start, end, rapid)

    def test_a_line_from_rest_to_rest(self):
        """100 mm at 10 mm/s: up to speed and down again at 2100 mm/s2, each
        change longer by the jerk: 2 sqrt(10 / 100 000) - 10 / 2100."""
        jerk = 2.0 * math.sqrt(10.0 / 1e5) - 10.0 / 2100.0
        self.assertAlmostEqual(self.time(self.line((0, 0, 0), (100, 0, 0))), 10.0 + 10.0 / 2100.0 + 2.0 * jerk)

    def test_rapid(self):
        """430 mm along X at 43 m/min (716.7 mm/s): up to it and down at 2100 mm/s2, no jerk."""
        v = 43000.0 / 60.0
        self.assertAlmostEqual(self.time(self.line((0, 0, 0), (430, 0, 0), True)), 0.6 + v / 2100.0)

    def test_short_rapid_moves(self):
        """The TNC's simulation: 500 times 2 mm in Z, there and back, 0:31."""
        there, back = self.line((0, 0, 20), (0, 0, 22), True), self.line((0, 0, 22), (0, 0, 20), True)
        self.assertAlmostEqual(250 * self.time(there, back), 31.0, delta=1.0)

    def test_straight_on_keeps_the_speed(self):
        pieces = [self.line((10.0 * k, 0, 0), (10.0 * (k + 1), 0, 0)) for k in range(10)]
        self.assertAlmostEqual(self.time(*pieces), self.time(self.line((0, 0, 0), (100, 0, 0))))

    def test_a_corner_slows_down(self):
        """Round a square corner at sqrt(2100 0.002 sin 45 / (1 - sin 45)) = 3.2 mm/s, not to a stop."""
        first = self.line((0, 0, 0), (50, 0, 0))
        corner = self.time(first, self.line((50, 0, 0), (50, 50, 0)))
        straight = self.time(first, self.line((50, 0, 0), (100, 0, 0)))
        stop = 2.0 * self.time(first)
        self.assertGreater(corner, straight)
        self.assertLess(corner, stop)

    def test_turning_back_stops(self):
        there = self.line((0, 0, 0), (50, 0, 0))
        self.assertAlmostEqual(self.time(there, self.line((50, 0, 0), (0, 0, 0))), 2.0 * self.time(there))

    def test_a_small_arc(self):
        """A circle of R0.1 at 6000 mm/min: at most sqrt(2100 0.1) = 14.5 mm/s, not 100."""
        circle = Segment((0.1, 0.0, 0.0), (0.1, 0.0, 0.0), False, (0.0, 0.0), False)
        at_most = 2.0 * math.pi * 0.1 / math.sqrt(210.0)
        t = self.time(circle, feed=6000.0)
        self.assertGreater(t, at_most)
        self.assertLess(t, at_most + 0.05)

    def test_the_operation_longer(self):
        moves = (nc.Move(nc.RAPID, 0.0, 0.0, 2.0), nc.Move(nc.LINE, 0.0, 0.0, -1.0, 200.0), nc.Move(nc.LINE, 100.0, 0.0, -1.0, 600.0), nc.Move(nc.LINE, 100.0, 50.0, -1.0))  # fmt: skip
        op = nc.Operation(nc.CONTOUR, "Contour", MILL_6, moves)
        dynamic = cycle_time.setup_time(setup_of(op)).operations[0]
        ideal = cycle_time.setup_time(setup_of(op), FULL_SPEED).operations[0]
        self.assertGreater(dynamic.feed_s, ideal.feed_s)
        self.assertGreater(dynamic.rapid_s, ideal.rapid_s)
        self.assertEqual(dynamic.tool_change_s, ideal.tool_change_s)


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestCycleTimeEngine(unittest.TestCase):
    """The part with holes of test_engine, its holes A and D milled along a
    helix with a Ø4 end mill."""

    def setUp(self):
        from avangardecam.engine import cycle_time as engine_cycle_time
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import helix as engine_helix
        from avangardecam.model import helix, library
        from avangardecam.tests.test_engine import TestEngine
        from avangardecam.tests.test_model import LIBRARY

        self.cam, self.engine = cam, engine_cycle_time
        self.helpers = TestEngine("setUp")
        self.helpers.setUp()
        self.helpers.library = library.load(LIBRARY)
        obj = self.helpers.model_with_holes()
        self.job = cam.ensure_job(self.helpers.doc, [obj])
        tc = cam.add_tool(self.job, self.helpers.variant(3, "Aluminium"))  # Ø4
        holes = [self.helpers.wall(obj, -15, 0, 3)[0], self.helpers.wall(obj, 12, 0, 5)[0]]
        self.op = engine_helix.add_model_helix_milling(self.job, obj, helix.HelixMilling(), tc, holes)

    def tearDown(self):
        FreeCAD.closeDocument(self.helpers.doc.Name)

    def test_times(self):
        found = self.engine.program_times(self.helpers.doc)
        self.assertEqual([s.label for s in found], [self.job.Label])
        self.assertEqual([t.label for t in found[0].operations], [self.op.Label])
        t = found[0].operations[0]
        self.assertGreater(t.feed_s, 1.0)
        self.assertGreater(t.rapid_s, 0.0)
        self.assertEqual(t.tool_change_s, cycle_time.BRIDGEPORT_V1000.tool_change_s)
        # the same as from the program the postprocessor gets
        program = self.cam.nc_program(self.helpers.doc, "TIME")
        self.assertAlmostEqual(found[0].total_s, cycle_time.program_time(program)[0].total_s)

    def test_switched_off(self):
        self.op.Active = False
        self.helpers.doc.recompute()
        self.assertEqual(self.engine.program_times(self.helpers.doc)[0].operations, ())


if __name__ == "__main__":
    unittest.main()
