# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Tests of what runs a program with operations on other zero points
(experimental): the stock model's cutting with a tool along any axis
(stocklab.oblique), model.tilted, the machine between zero points
(model.machine), Verify, the playback and its crashes. Plain Python with
numpy:

    python3 -m unittest avangardecam.tests.test_tilted   (from the add-on's folder)
"""

import datetime
import math
import unittest

import numpy as np

from avangardecam import stocklab
from avangardecam.model import crashes, cycle_time, frame, machine, nc, op_zero, operations, playback, playback_stock
from avangardecam.model import threads, tilted, verify
from avangardecam.model.stock import Bounds
from avangardecam.model.tools import Tool
from avangardecam.post import heidenhain, machines, soraluce
from avangardecam.stocklab import cut, oblique
from avangardecam.stocklab import tools as stock_tools
from avangardecam.tests.test_verify import box_mesh

MILL_6 = Tool("Frees 6mm", "Endmill", 6.0, cutting_length_mm=15.0)
NC_6 = nc.Tool(1, "Frees 6mm", 6.0, 8000.0, 200.0, 600.0)
THREAD_MILL = Tool("Draadfrees M3", "ThreadMill", 2.4, angle_deg=60.0, cutting_length_mm=1.33, pitch_mm=0.5)
NC_THREAD_MILL = nc.Tool(3, "Draadfrees M3", 2.4, 12000.0, 225.0, 300.0)

# a block 40 x 20 x 12, the preset in the middle of its top
BLOCK = Bounds(-20.0, -10.0, -12.0, 20.0, 10.0, 0.0)
# the zero point in the middle of its right wall (+X), Z out of it, X down
WALL = frame.Frame((20.0, 0.0, -6.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
# the preset turned 30° about Y
TILT_30 = frame.Frame((0.0, 0.0, 0.0), *op_zero.axes_of((0.0, 30.0, 0.0)))
SHIFT = frame.Frame((10.0, 0.0, -5.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def slot(depth, zero, label="Slot", rapid_through=False):
    """A slot Ø6 along Y through the block at X0 of the zero point, depth
    below its Z0; rapid_through: the cut at rapid traverse (a crash)."""
    cutting = nc.Move(nc.RAPID, 0.0, 15.0, depth) if rapid_through else nc.Move(nc.LINE, 0.0, 15.0, depth, 600.0)
    moves = (
        nc.Move(nc.RAPID, 0.0, -15.0, 5.0),
        nc.Move(nc.LINE, 0.0, -15.0, depth, 200.0),
        cutting,
    )
    return nc.Operation(nc.CONTOUR, label, NC_6, moves, zero=zero)


def setup_of(*ops):
    return nc.Setup(1, "Setup 1", BLOCK, tuple(ops))


def taken(setup, resolution=120, anew=True):
    """(mm3 the setup's operations take of the block, what they ran into)."""
    planned = verify.plan(setup, {1: MILL_6}, anew=anew)
    block = stocklab.Stock.box((-20.0, -10.0, -12.0), (20.0, 10.0, 0.0), resolution)
    before = block.volume()
    found = crashes.simulate(block, [p.operation for p in planned], [p.shank for p in planned])
    return before - block.volume(), found


class ObliqueTest(unittest.TestCase):
    """stocklab.oblique against the stock model's own cutting."""

    def moves(self, n=30):
        rng = np.random.default_rng(7)
        a = rng.uniform((-18, -9, -6), (18, 9, 8), (n, 3))
        return a, a + rng.uniform(-6, 6, (n, 3))

    def test_direction(self):
        self.assertIsNone(oblique.direction("+Z"))
        self.assertIsNone(oblique.direction((0.0, -2.0, 0.0)))
        d = oblique.direction((1.0, 0.0, 1.0))
        np.testing.assert_allclose(d, (math.sqrt(0.5), 0.0, math.sqrt(0.5)))
        np.testing.assert_allclose(oblique.unit("-X"), (-1.0, 0.0, 0.0))
        with self.assertRaises(ValueError):
            oblique.unit((0.0, 0.0, 0.0))

    def test_along_an_axis_as_the_stock_model_cuts(self):
        a, b = self.moves()
        shapes = (stock_tools.flat_end_mill(6.0, 20.0), stock_tools.drill(6.0, 118.0, 20.0), stock_tools.chamfer_mill(8.0, 90.0, 20.0, 1.0))
        for axis in ("+Z", "-Z", "+X", "-Y"):
            for tool in shapes:
                own = stocklab.Stock.box((-20, -10, -12), (20, 10, 0), 80)
                other = stocklab.Stock.box((-20, -10, -12), (20, 10, 0), 80)
                volume = cut.cut_lines(own, tool, axis, a, b)
                self.assertAlmostEqual(oblique.cut_lines(other, tool, oblique.unit(axis), a, b), volume, places=6, msg=(axis, tool.name))
                for family in range(3):
                    self.assertAlmostEqual(other.volume(family), own.volume(family), places=6)

    def test_round_tools_as_chords(self):
        a, b = self.moves()
        for tool in (stock_tools.ball_end_mill(6.0, 20.0), stock_tools.bull_nose_mill(6.0, 1.0, 20.0)):
            own = stocklab.Stock.box((-20, -10, -12), (20, 10, 0), 80)
            other = stocklab.Stock.box((-20, -10, -12), (20, 10, 0), 80)
            volume = cut.cut_lines(own, tool, "+Z", a, b)
            found = oblique.cut_lines(other, tool, oblique.unit("+Z"), a, b)
            self.assertLessEqual(found, volume + 1e-6, "the chords stay inside the arc")
            # the chords leave a twentieth of a cell at most (oblique.CHORD_CELLS)
            self.assertAlmostEqual(found / volume, 1.0, delta=0.008)

    def test_a_tall_tool_in_pieces(self):
        """In a stock a tall cone is cut in pieces and an arc in no more
        chords than the cells can tell: the same tool all the same."""
        tool = stock_tools.bull_nose_mill(6.0, 1.0, 20.0)
        whole = oblique.cones(tool.parts[0])
        pieces = oblique.cones(tool.parts[0], 0.5)
        self.assertLess(len([c for c in pieces if c[1] <= 1.0 + 1e-9]), len([c for c in whole if c[1] <= 1.0 + 1e-9]), "fewer chords")
        shaft = [c for c in pieces if c[0] >= 1.0 - 1e-9]
        self.assertEqual(len(shaft), 4, "19 mm of a 6 mm shaft: four pieces")
        self.assertAlmostEqual(pieces[0][0], whole[0][0])
        self.assertAlmostEqual(pieces[-1][1], whole[-1][1])
        for below, above in zip(pieces, pieces[1:]):
            self.assertAlmostEqual(below[1], above[0], msg="no gap between the pieces")
            self.assertAlmostEqual(below[2] + below[3] * (below[1] - below[0]), above[2], msg="the same radius where they meet")

    def test_a_tilted_tool_takes_what_a_straight_one_does(self):
        # the same move of the same tool in a block all around it, seen from the tool and from the block
        a, b = np.array((-10.0, 0.0, -5.0)), np.array((10.0, 2.0, -3.0))
        for tool in (stock_tools.flat_end_mill(6.0, 20.0), stock_tools.ball_end_mill(6.0, 20.0), stock_tools.drill(6.0, 118.0, 20.0)):
            straight = stocklab.Stock.box((-40, -40, -40), (40, 40, 40), 160)
            volume = cut.cut_lines(straight, tool, "+Z", [a], [b])
            for turn in ((0.0, 30.0, 0.0), (57.3, 0.0, 0.0), (20.0, -35.0, 70.0)):
                zero = frame.Frame((0.0, 0.0, 0.0), *op_zero.axes_of(turn))
                block = stocklab.Stock.box((-40, -40, -40), (40, 40, 40), 160)
                found = stocklab.cut_lines(block, tool, zero.z_axis, [zero.to_part(a)], [zero.to_part(b)])
                self.assertAlmostEqual(found / volume, 1.0, delta=0.005, msg=(tool.name, turn))

    def test_would_take(self):
        block = stocklab.Stock.box((-20, -10, -12), (20, 10, 0), 80)
        tool = stock_tools.flat_end_mill(6.0, 20.0)
        d = (math.sqrt(0.5), 0.0, math.sqrt(0.5))
        starts = [(0.0, 0.0, 20.0), (0.0, 0.0, 20.0), (40.0, 0.0, 5.0)]
        ends = [(0.0, 5.0, 20.0), (0.0, 0.0, -2.0), (40.0, 5.0, 5.0)]
        before = block.volume()
        would = oblique.would_take(block, tool, d, starts, ends)
        self.assertEqual(block.volume(), before, "nothing is cut")
        self.assertEqual(would[0], 0.0, "in the air above the block")
        self.assertGreater(would[1], 10.0, "down into it")
        self.assertEqual(would[2], 0.0, "beside it")
        took = stocklab.cut_lines(block, tool, d, [starts[1]], [ends[1]])
        self.assertAlmostEqual(would[1] / took, 1.0, delta=0.05)
        self.assertEqual(oblique.would_take(block, tool, d, [starts[1]], [ends[1]])[0], 0.0, "taken already")

    def test_arcs_round_the_tool_axis(self):
        zero = TILT_30
        centre = (5.0, 2.0, 0.0)
        start, end = (9.0, 2.0, -1.0), (5.0, 6.0, -3.0)
        own = cut.arc_points("+Z", start, end, centre, True, 0.01)
        found = cut.arc_points(zero.z_axis, zero.to_part(start), zero.to_part(end), zero.to_part(centre), True, 0.01)
        self.assertEqual(len(found), len(own))
        np.testing.assert_allclose(found, [zero.to_part(p) for p in own], atol=1e-9)
        # the other way round: the long way
        self.assertGreater(len(cut.arc_points(zero.z_axis, zero.to_part(start), zero.to_part(end), zero.to_part(centre), False, 0.01)), len(found))


class TiltedTest(unittest.TestCase):
    def test_axis(self):
        self.assertEqual(tilted.axis(None), "+Z")
        self.assertEqual(tilted.axis(SHIFT), "+Z")
        self.assertEqual(tilted.axis(frame.rotated_about_z(SHIFT, 30.0)), "+Z", "the tool stands as on the preset")
        self.assertEqual(tilted.axis(WALL), (1.0, 0.0, 0.0))
        self.assertEqual(tilted.direction(None), (0.0, 0.0, 1.0))
        self.assertEqual(tilted.direction(WALL), (1.0, 0.0, 0.0))

    def test_points(self):
        self.assertEqual(tilted.point(None, (1.0, 2.0, 3.0)), (1.0, 2.0, 3.0))
        self.assertEqual(tilted.point(WALL, (1.0, 2.0, 3.0)), (23.0, 2.0, -7.0))
        points = np.array(((1.0, 2.0, 3.0), (0.0, 0.0, 0.0)))
        np.testing.assert_allclose(tilted.points(WALL, points), ((23.0, 2.0, -7.0), (20.0, 0.0, -6.0)))
        np.testing.assert_allclose(tilted.seen(WALL, tilted.points(WALL, points)), points)
        np.testing.assert_allclose(tilted.seen(TILT_30, tilted.points(TILT_30, points)), points, atol=1e-12)
        self.assertIs(tilted.points(None, points), points)

    def test_stock_moves(self):
        line = tilted.stock_move(WALL, stocklab.Line((0.0, 0.0, 5.0), (0.0, 0.0, -3.0), rapid=True))
        np.testing.assert_allclose((line.start, line.end), ((25.0, 0.0, -6.0), (17.0, 0.0, -6.0)))
        self.assertTrue(line.rapid)
        arc = tilted.stock_move(WALL, stocklab.Arc((2.0, 0.0, -1.0), (0.0, 2.0, -1.0), (0.0, 0.0, 0.0), ccw=True))
        np.testing.assert_allclose(arc.center, (20.0, 0.0, -6.0))
        self.assertTrue(arc.ccw)
        plain = stocklab.Line((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertIs(tilted.stock_move(None, plain), plain)

    def test_rotation(self):
        self.assertIsNone(tilted.rotation(None))
        self.assertIsNone(tilted.rotation(SHIFT))
        for zero in (WALL, TILT_30, frame.Frame((0, 0, 0), *op_zero.axes_of((180.0, 0.0, 0.0))), frame.Frame((0, 0, 0), *op_zero.axes_of((10.0, 100.0, -170.0)))):
            x, y, z, w = tilted.rotation(zero)
            # the quaternion turns the axes as the zero point is turned
            for axis, turned in zip(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (zero.x_axis, zero.y_axis, zero.z_axis)):
                v = np.array(axis)
                q = np.array((x, y, z))
                found = v + 2.0 * np.cross(q, np.cross(q, v) + w * v)
                np.testing.assert_allclose(found, turned, atol=1e-9)

    def test_turned(self):
        self.assertFalse(tilted.turned(setup_of(slot(-2.0, None), slot(-2.0, SHIFT))))
        self.assertTrue(tilted.turned(setup_of(slot(-2.0, None), slot(-3.0, WALL))))


class MachineTest(unittest.TestCase):
    def test_a_shifted_zero_point(self):
        """The tool goes high on the preset, then the zero point shifts."""
        follower = machine.Machine(full=True)
        first = follower.elements(slot(-2.0, None))
        self.assertEqual(first[-1].end, (0.0, 15.0, 40.0))
        second = follower.elements(slot(-2.0, SHIFT))
        self.assertFalse(follower.changed)
        # where it was, as the shifted zero point sees it; up to Z100 of the preset
        self.assertEqual((second[0].start, second[0].end), ((-10.0, 15.0, 45.0), (-10.0, 15.0, 105.0)))
        self.assertEqual((second[0].kind, second[0].source), (nc.RAPID, None))
        self.assertEqual((second[1].end, second[1].source), ((0.0, -15.0, 105.0), ("approach",)))
        self.assertEqual(second[2].end, (0.0, -15.0, 5.0))
        # back on the preset the same way
        third = follower.elements(slot(-2.0, None))
        self.assertEqual((third[0].start, third[0].end), ((10.0, 15.0, 35.0), (10.0, 15.0, 100.0)))

    def test_the_same_zero_point_goes_on(self):
        follower = machine.Machine(full=True)
        follower.elements(slot(-2.0, SHIFT))
        again = follower.elements(slot(-3.0, SHIFT))
        self.assertEqual((again[0].start, again[0].end, again[0].source), ((0.0, 15.0, 40.0), (0.0, -15.0, 40.0), ("approach",)))

    def test_a_tool_change_on_a_shifted_zero_point(self):
        """The tool change height is the preset's."""
        follower = machine.Machine(full=True)
        follower.elements(slot(-2.0, SHIFT))
        other = nc.Operation(nc.CONTOUR, "Other", nc.Tool(2, "Frees 8", 8.0, 6000.0, 200.0, 600.0), slot(-2.0, SHIFT).moves, zero=SHIFT)
        elements = follower.elements(other)
        self.assertTrue(follower.changed)
        self.assertEqual((elements[0].end, elements[0].source), ((0.0, 15.0, 105.0), ("change",)))

    def test_a_turning_head_starts_anew(self):
        follower = machine.Machine(full=True, anew=True)
        follower.elements(slot(-2.0, None))
        side = follower.elements(slot(-3.0, WALL))
        self.assertFalse(follower.changed, "the same tool")
        self.assertEqual((side[0].start, side[0].end, side[0].source), ((0.0, -15.0, 100.0), (0.0, -15.0, 100.0), ("approach",)))
        self.assertEqual(side[1].end, (0.0, -15.0, 5.0))
        again = follower.elements(slot(-4.0, WALL))
        self.assertEqual(again[0].start, (0.0, -15.0, 100.0), "on the same zero point too")

    def test_a_turned_zero_point_without_a_turning_head(self):
        follower = machine.Machine(full=True)
        follower.elements(slot(-2.0, None))
        side = follower.elements(slot(-3.0, WALL))
        self.assertEqual(side[0].start, (0.0, -15.0, 100.0))

    def test_which_machine_runs_it(self):
        def program(*ops):
            return nc.Program("P", "", datetime.date(2026, 11, 16), (setup_of(*ops),))

        shifted = program(slot(-2.0, None), slot(-2.0, SHIFT))
        turned = program(slot(-2.0, None), slot(-3.0, WALL))
        self.assertIs(machines.able(None, shifted), machines.BRIDGEPORT_V1000)
        self.assertIs(machines.able(machines.BRIDGEPORT_V1000, turned), machines.SORALUCE_T35)
        self.assertIs(machines.able(machines.SORALUCE_T35, shifted), machines.SORALUCE_T35)
        self.assertTrue(machines.SORALUCE_T35.anew and not machines.BRIDGEPORT_V1000.anew)
        self.assertEqual((machines.SORALUCE_T35.retract_z_mm, machines.SORALUCE_T35.start_z_mm), (40.0, 100.0))
        lines, lines_of = machines.SORALUCE_T35.numbered(turned)
        self.assertIn("PLANE SPATIAL SPA0. SPB90. SPC0. STAY COORD ROT", " ".join(lines))
        self.assertIn((0, 1, "move", 2), lines_of)

    def test_cycle_time(self):
        """The moves take as long on any zero point."""
        plain = cycle_time.setup_time(setup_of(slot(-3.0, None)))
        side = cycle_time.setup_time(setup_of(slot(-3.0, WALL)), anew=True)
        self.assertAlmostEqual(side.operations[0].feed_s, plain.operations[0].feed_s)
        both = cycle_time.program_time(nc.Program("P", "", datetime.date(2026, 11, 16), (setup_of(slot(-3.0, None), slot(-3.0, WALL)),)), anew=True)
        self.assertEqual(len(both[0].operations), 2)
        self.assertEqual(both[0].operations[1].tool_change_s, 0.0, "the same tool")


class VerifyTest(unittest.TestCase):
    def test_a_slot_in_the_wall(self):
        # 6 wide, 3 into the wall, all along its 20 mm
        volume, found = taken(setup_of(slot(-3.0, WALL)))
        self.assertAlmostEqual(volume, 360.0, delta=360.0 * 0.02)
        self.assertEqual(found, [])

    def test_a_slot_on_a_tilted_plane(self):
        # across the block's top, the tool leaning 30°: 2 + x tan(30°) deep over its 6 mm, 20 long
        volume, found = taken(setup_of(slot(-2.0, TILT_30)), resolution=200)
        self.assertAlmostEqual(volume, 240.0, delta=240.0 * 0.03)
        self.assertEqual(found, [])

    def test_a_shifted_zero_point_cuts_where_it_is(self):
        on_preset, _ = taken(setup_of(slot(-7.0, None)), anew=False)
        shifted, _ = taken(setup_of(slot(-2.0, SHIFT)), anew=False)  # Z0 5 mm under the top
        self.assertAlmostEqual(shifted, on_preset, places=6)

    def test_operations_one_after_another(self):
        top, _ = taken(setup_of(slot(-2.0, None)))
        side, _ = taken(setup_of(slot(-3.0, WALL)))
        both, found = taken(setup_of(slot(-2.0, None), slot(-3.0, WALL)))
        # they do not meet: the top one at X0, the wall's 17 mm away
        self.assertAlmostEqual(both, top + side, delta=0.5)
        self.assertEqual(found, [])

    def test_a_rapid_move_through_the_wall(self):
        for zero, depth, volume in ((WALL, -3.0, 360.0), (TILT_30, -2.0, 240.0)):
            setup = setup_of(slot(depth, zero, rapid_through=True))
            planned = verify.plan(setup, {1: MILL_6}, anew=True)
            block = stocklab.Stock.box((-20.0, -10.0, -12.0), (20.0, 10.0, 0.0), 200)
            (crash,) = crashes.simulate(block, [p.operation for p in planned], [p.shank for p in planned])
            self.assertEqual(crash.kind, crashes.RAPID)
            move = planned[0].operation.moves[crash.move]
            self.assertTrue(move.rapid)
            np.testing.assert_allclose((move.start, move.end), (zero.to_part((0.0, -15.0, depth)), zero.to_part((0.0, 15.0, depth))), atol=1e-9)
            self.assertAlmostEqual(crash.volume, volume, delta=volume * 0.03)

    def test_the_shank_in_the_wall(self):
        """Deeper than the flutes are long: the shank takes what is beside the slot."""
        short = Tool("Frees 6mm kort", "Endmill", 6.0, cutting_length_mm=4.0, shank_diameter_mm=10.0, length_mm=40.0)
        for zero, depth in ((WALL, -8.0), (TILT_30, -9.0)):
            setup = setup_of(slot(depth, zero))
            planned = verify.plan(setup, {1: short}, anew=True)
            block = stocklab.Stock.box((-20.0, -10.0, -12.0), (20.0, 10.0, 0.0), 120)
            found = crashes.simulate(block, [p.operation for p in planned], [p.shank for p in planned])
            self.assertEqual({c.kind for c in found}, {crashes.SHANK}, zero)
            self.assertIn(2, [c.move for c in found])
        # with flutes long enough nothing
        _volume, found = taken(setup_of(slot(-8.0, WALL)))
        self.assertEqual(found, [])

    def verified(self, part, *ops, resolution=120):
        setup = setup_of(*ops)
        vertices, triangles = box_mesh(*part)
        return verify.verify(setup.stock, vertices, triangles, verify.plan(setup, {1: MILL_6}, anew=True), resolution=resolution)

    def test_too_deep_in_the_wall(self):
        # the part's wall where the slot's floor is: clean
        result = self.verified(((-20.0, -10.0, -12.0), (17.0, 10.0, 0.0)), slot(-3.0, WALL))
        self.assertEqual((result.gouges, result.collisions), ((), ()))
        # the part is the whole block: 3 mm into it
        result = self.verified(((-20.0, -10.0, -12.0), (20.0, 10.0, 0.0)), slot(-3.0, WALL))
        self.assertEqual([g.operation for g in result.gouges], ["Slot"])
        self.assertAlmostEqual(result.gouges[0].depth_mm, 3.0, delta=0.05)

    def test_too_deep_on_a_tilted_plane(self):
        # the tool's lowest corner is 3 sin(30°) + 2 cos(30°) = 3.23 under the top
        result = self.verified(((-20.0, -10.0, -12.0), (20.0, 10.0, -4.0)), slot(-2.0, TILT_30))
        self.assertEqual(result.gouges, ())
        result = self.verified(((-20.0, -10.0, -12.0), (20.0, 10.0, -2.0)), slot(-2.0, TILT_30))
        self.assertEqual(len(result.gouges), 1)
        # 1.23 into the part there; the nearest way out is between the tool's floor and its side
        deepest = 1.232 * math.sin(math.radians(45.0)) / math.sin(math.radians(75.0))
        self.assertAlmostEqual(result.gouges[0].depth_mm, deepest, delta=0.08)

    def threads(self, zero, drilled):
        """An M3 thread 6 deep at X2 Y3 of the zero point, its hole drilled first or not."""
        thread = operations.ThreadMilling(3.0, -6.0, passes=2)
        moves = threads.moves(thread, [threads.ThreadHole(2.0, 3.0, 0.0)], 0.5, 1.5, 225.0, 300.0, nc.RIGHT)
        ops = [nc.Operation(nc.THREAD_MILLING, "Thread milling", NC_THREAD_MILL, moves, zero=zero)]
        tools = {3: THREAD_MILL}
        if drilled:
            cycle = nc.DrillCycle(
                peck_mm=None, feed_mm_min=100.0, clearance_mm=2.0, second_clearance_mm=10.0, decrement_mm=0.0,
                min_peck_mm=0.0, upper_stop_mm=0.0, lower_stop_mm=0.0, chip_break_mm=0.0, chip_retract_mm=0.0,
                dwell_s=0.0, start_mm=0.0, preposition_feed_mm_min=0.0, holes=(nc.DrillHole(2.0, 3.0, 0.0, -8.0),),
            )  # fmt: skip
            tools[4] = Tool("Boor", "Drill", 2.5, angle_deg=118.0, cutting_length_mm=20.0)
            ops.insert(0, nc.Operation(nc.DRILLING, "Drilling", nc.Tool(4, "Boor", 2.5, 3000.0, 300.0, 300.0), (), cycle, zero))
        setup = setup_of(*ops)
        vertices, triangles = box_mesh((-150.0, -150.0, -160.0), (-140.0, -140.0, -150.0))  # out of the way
        return verify.verify(setup.stock, vertices, triangles, verify.plan(setup, tools, anew=True), resolution=80)

    def test_threads_on_other_zero_points(self):
        for zero in (WALL, TILT_30):
            result = self.threads(zero, drilled=False)
            (hole,) = result.holes
            np.testing.assert_allclose(hole.centre, zero.to_part((2.0, 3.0, 0.0)), atol=1e-9, err_msg="in the setup's coordinates")
            self.assertGreater(hole.volume_mm3, 15.0, "no hole there: the thread mill's body in material")
            red = np.all(result.colors == verify.stock_verify.RED, axis=1)
            away = np.linalg.norm(result.vertices - np.array(hole.centre), axis=1)
            self.assertTrue(red[away < 2.0].any() and not red[away > 9.0].any(), "red in and round the hole only")
            (hole,) = self.threads(zero, drilled=True).holes
            self.assertEqual(hole.volume_mm3, 0.0, zero)


class PlaybackTest(unittest.TestCase):
    def line(self, *ops, post=machines.SORALUCE_T35):
        setup = setup_of(*ops)
        program = nc.Program("P", "", datetime.date(2026, 11, 16), (setup,))
        lines, lines_of = post.numbered(program)
        return playback.timeline(setup, 0, lines, lines_of, retract_z=post.retract_z_mm, change_z=post.start_z_mm, anew=post.anew)

    def test_the_tool_in_the_presets_coordinates(self):
        line = self.line(slot(-2.0, None), slot(-3.0, WALL))
        top, side = line.operations
        self.assertIsNone(top.zero)
        self.assertEqual(side.zero, WALL)
        self.assertEqual(line.tool_axis(top.start_s + 0.1), (0.0, 0.0, 1.0))
        self.assertEqual(line.tool_axis(line.total_s), (1.0, 0.0, 0.0))
        self.assertEqual(line.zero_at(line.total_s), WALL)
        # at the end 40 out of the wall, where the slot ends
        np.testing.assert_allclose(line.position(line.total_s), (60.0, 15.0, -6.0))
        # the wall's path as drawn: from 100 out of the wall, to its floor 3 mm in it
        drawn, first = playback.operation_polyline(line, side)
        np.testing.assert_allclose(drawn.points[0], (120.0, -15.0, -6.0))
        self.assertAlmostEqual(float(drawn.points[:, 0].min()), 17.0)
        self.assertEqual(first, line.steps[side.first].first)
        self.assertEqual(line.zero_of[first], WALL)
        self.assertIsNone(line.zero_of[0])

    def test_each_step_runs_its_line(self):
        line = self.line(slot(-2.0, None), slot(-3.0, WALL))
        side = line.operations[1]
        cutting = [s for s in line.steps[side.first : side.end] if s.kind == nc.LINE]
        self.assertTrue(all(line.lines[s.line].split(" ", 1)[1].startswith("L ") for s in cutting))
        self.assertIn("Y+15.", line.lines[cutting[-1].line])
        before = [text for text in line.lines[: cutting[0].line] if "PLANE SPATIAL" in text]
        self.assertEqual(before[-1].split(" ", 1)[1], "PLANE SPATIAL SPA0. SPB90. SPC0. STAY COORD ROT")

    def test_the_stock_as_verify_leaves_it(self):
        for ops in ((slot(-2.0, None), slot(-3.0, WALL)), (slot(-2.0, TILT_30),), (slot(-2.0, None), slot(-2.0, SHIFT))):
            post = machines.SORALUCE_T35 if tilted.turned(setup_of(*ops)) else machines.BRIDGEPORT_V1000
            line = self.line(*ops, post=post)
            # 97 cells: no ray stands just where the tool's edge goes (cut
            # in pieces, such a ray is taken by some and not by others)
            material = playback_stock.Material(line, BLOCK, {1: MILL_6}, resolution=97)
            start = material.volume()
            material.cut_to(line.total_s)
            volume, _found = taken(setup_of(*ops), resolution=97, anew=post.anew)
            self.assertAlmostEqual(start - material.volume(), volume, delta=1e-6 * start)
            self.assertEqual(material.crashes, {})
            # bit by bit and back again: the same stock
            again = playback_stock.Material(line, BLOCK, {1: MILL_6}, resolution=97, snapshot_segments=2)
            for t in np.linspace(0.0, line.total_s, 23):
                again.cut_to(t)
            again.cut_to(line.total_s * 0.4)
            again.cut_to(line.total_s)
            self.assertAlmostEqual(again.volume(), material.volume(), delta=1e-6 * start)

    def test_crashes_on_the_time_line(self):
        line = self.line(slot(-2.0, None), slot(-3.0, WALL, rapid_through=True))
        material = playback_stock.Material(line, BLOCK, {1: MILL_6}, resolution=100)
        material.cut_to(line.total_s)
        (crash,) = playback_stock.played_crashes(material)
        self.assertEqual(crash.kind, crashes.RAPID)
        self.assertEqual(line.operations[line.steps[crash.step].operation].label, "Slot")
        self.assertEqual(line.zero_of[crash.segment], WALL)
        self.assertIn("FMAX", line.lines[crash.line])

    def test_the_bridgeport_goes_high_between_zero_points(self):
        line = self.line(slot(-2.0, None), slot(-2.0, SHIFT), post=machines.BRIDGEPORT_V1000)
        shifted = line.operations[1]
        first = line.steps[shifted.first]
        # up to Z100 of the preset, where the first slot ended
        np.testing.assert_allclose(line.position(first.end_s), (0.0, 15.0, 100.0))
        self.assertEqual(line.tool_axis(first.end_s), (0.0, 0.0, 1.0))
        text = "\n".join(line.lines)
        self.assertIn("CYCL DEF 7.1  X+10.", text)
        self.assertEqual(heidenhain.numbered(nc.Program("P", "", datetime.date(2026, 11, 16), (setup_of(slot(-2.0, None), slot(-2.0, SHIFT)),)))[0], line.lines)


if __name__ == "__main__":
    unittest.main()
