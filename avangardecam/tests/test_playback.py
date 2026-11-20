# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Playback tests (model.playback, the program's lines from
post.heidenhain.numbered), plain Python:

    python3 -m unittest avangardecam.tests.test_playback   (from src/Mod/AvangardeCam)
"""

import math
import unittest

import numpy as np

from avangardecam import stocklab
from avangardecam.model import crashes, cycle_time, machine, nc, operations, playback, playback_stock, stock, threads, tools
from avangardecam.post import heidenhain

MILL_6 = nc.Tool(1, "Frees 6mm", 6.0, 8000.0, 200.0, 600.0)
DRILL_5 = nc.Tool(2, "Boor 5", 5.0, 3000.0, 100.0, 100.0)
THREAD_MILL = nc.Tool(3, "Draadfrees M3", 2.4, 12000.0, 225.0, 300.0)


def drill_cycle(**values):
    fields = dict(
        peck_mm=3.0, feed_mm_min=100.0, clearance_mm=2.0, second_clearance_mm=10.0, decrement_mm=0.0,
        min_peck_mm=0.0, upper_stop_mm=0.2, lower_stop_mm=0.2, chip_break_mm=0.0, chip_retract_mm=0.2,
        dwell_s=0.5, start_mm=0.0, preposition_feed_mm_min=100.0,
        holes=(nc.DrillHole(10.0, 10.0, 0.0, -10.0), nc.DrillHole(30.0, 10.0, 0.0, -10.0)),
    )  # fmt: skip
    fields.update(values)
    return nc.DrillCycle(**fields)


def square(compensation=nc.RIGHT):
    """Round a 40 x 20 square at -2 with the radius compensation (RR: outside), in from the side."""
    return (
        nc.Move(nc.RAPID, -10.0, 0.0, 5.0),
        nc.Move(nc.LINE, -10.0, 0.0, -2.0, 200.0),
        nc.Move(nc.LINE, 0.0, 0.0, -2.0, 600.0, compensation=compensation),
        nc.Move(nc.LINE, 40.0, 0.0, -2.0, compensation=compensation),
        nc.Move(nc.LINE, 40.0, 20.0, -2.0, compensation=compensation),
        nc.Move(nc.LINE, 0.0, 20.0, -2.0, compensation=compensation),
        nc.Move(nc.LINE, 0.0, 0.0, -2.0, compensation=compensation),
        nc.Move(nc.LINE, -10.0, 0.0, -2.0),
    )


def program():
    thread = operations.ThreadMilling(3.0, -6.0, passes=1)
    thread_moves = threads.moves(thread, [threads.ThreadHole(10.0, 10.0, 0.0)], 0.5, 1.5, 225.0, 300.0, nc.RIGHT)
    ops = (
        nc.Operation(nc.CONTOUR, "Contour", MILL_6, square()),
        nc.Operation(nc.DRILLING, "Drilling", DRILL_5, (), drill_cycle()),
        nc.Operation(nc.THREAD_MILLING, "Thread", THREAD_MILL, thread_moves),
    )
    setup = nc.Setup(1, "Setup 1", None, ops)
    import datetime

    return nc.Program("TEST", "", datetime.date(2026, 10, 28), (setup,))


def made(prog=None):
    prog = prog or program()
    lines, lines_of = heidenhain.numbered(prog)
    return playback.timeline(prog.setups[0], 0, lines, lines_of), prog


class TimelineTest(unittest.TestCase):
    def test_as_long_as_the_cycle_time(self):
        line, prog = made()
        times = cycle_time.setup_time(prog.setups[0], retract_z=heidenhain.BRIDGEPORT_V1000.retract_z_mm)
        self.assertAlmostEqual(line.total_s, times.total_s, places=9)
        for span, t in zip(line.operations, times.operations):
            self.assertAlmostEqual(span.duration_s, t.total_s, places=9, msg=span.label)

    def test_steps_one_after_another(self):
        line, _ = made()
        now, segment = 0.0, 0
        for step in line.steps:
            self.assertAlmostEqual(step.start_s, now, places=9)
            self.assertEqual(step.first, segment)
            if step.count:
                self.assertAlmostEqual(line.starts[step.first], step.start_s, places=9)
                last = step.first + step.count - 1
                self.assertAlmostEqual(line.starts[last] + line.durations[last], step.end_s, places=9)
            now, segment = step.end_s, segment + step.count
        self.assertEqual(segment, len(line.segments))
        self.assertAlmostEqual(now, line.total_s, places=9)
        # each operation's steps one after another
        self.assertEqual([(o.first, o.end) for o in line.operations], [(0, line.operations[1].first), (line.operations[1].first, line.operations[2].first), (line.operations[2].first, len(line.steps))])

    def test_tool_changes_and_dwells(self):
        line, _ = made()
        changes = [s for s in line.steps if s.kind == playback.TOOL_CHANGE]
        self.assertEqual([(s.operation, s.duration_s, s.tool.number) for s in changes], [(0, 1.5, 1), (1, 1.5, 2), (2, 1.5, 3)])
        dwells = [s for s in line.steps if s.kind == playback.DWELL]
        self.assertEqual([(s.operation, s.duration_s) for s in dwells], [(1, 0.5), (1, 0.5)])
        for dwell in dwells:  # at the bottom of its hole
            self.assertAlmostEqual(line.position(dwell.start_s + 0.25)[2], -10.0)
        # the way up to the tool change with the tool before
        up = line.steps[line.operations[1].first]
        self.assertEqual((up.kind, up.tool.number), (nc.RAPID, 1))
        self.assertAlmostEqual(line.position(up.end_s)[2], machine.TOOL_CHANGE_Z_MM)
        self.assertEqual(line.steps[line.operations[1].first + 1].kind, playback.TOOL_CHANGE)

    def test_the_tool_where_the_machine_is(self):
        line, _ = made()
        self.assertEqual(line.position(0.0), line.segments[0].start)
        np.testing.assert_allclose(line.position(line.total_s), line.segments[-1].end)
        # halfway along each segment: halfway along its line or round its arc
        for i, segment in enumerate(line.segments):
            if line.durations[i] <= 0.0:
                continue
            p = line.position(line.starts[i] + line.durations[i] / 2.0)
            if segment.centre is None:
                np.testing.assert_allclose(p, np.add(segment.start, segment.end) / 2.0, atol=1e-9)
            else:
                cx, cy = segment.centre
                r0 = math.hypot(segment.start[0] - cx, segment.start[1] - cy)
                r1 = math.hypot(segment.end[0] - cx, segment.end[1] - cy)
                self.assertAlmostEqual(math.hypot(p[0] - cx, p[1] - cy), (r0 + r1) / 2.0)
                self.assertAlmostEqual(p[2], (segment.start[2] + segment.end[2]) / 2.0)
        # the compensated square: the tool's centre 3 mm outside it on its bottom side
        op = line.operations[0]
        bottom = [s for s in line.steps[op.first : op.end] if s.count and abs(line.segments[s.first].end[0] - 40.0) < 1e-9
                  and abs(line.segments[s.first + s.count - 1].end[1] + 3.0) < 1e-9]  # fmt: skip
        self.assertEqual(len(bottom), 1)

    def test_a_corner_with_the_move_after_it(self):
        """The arc round the square's corner (RR: outside) belongs to the move
        along the next side: that step has the arc and then the side."""
        line, _ = made()
        op = line.operations[0]
        arcs = [s for s in line.steps[op.first : op.end] if any(line.segments[k].centre is not None for k in range(s.first, s.first + s.count))]
        self.assertEqual(len(arcs), 3)  # the corners at (40, 0), (40, 20), (0, 20)
        for step in arcs:
            self.assertEqual(step.count, 2)
            self.assertIsNotNone(line.segments[step.first].centre)
            self.assertIsNone(line.segments[step.first + 1].centre)
            self.assertEqual(step.kind, nc.LINE)

    def test_owners_cover_every_segment(self):
        prog = program()
        follower = machine.Machine(full=True)
        for op in prog.setups[0].operations:
            elements = follower.elements(op)
            owners = []
            found = machine.machine_segments(elements, op.tool.diameter_mm / 2.0, [], owners)
            self.assertEqual(len(owners), len(found))
            self.assertEqual(owners, sorted(owners))
            self.assertEqual(found, machine.machine_segments(elements, op.tool.diameter_mm / 2.0, []))


class LinesTest(unittest.TestCase):
    def test_numbered_is_the_program(self):
        prog = program()
        lines, _ = heidenhain.numbered(prog)
        self.assertEqual("".join(l + heidenhain.NEWLINE for l in lines), heidenhain.write(prog))

    def test_each_step_runs_its_line(self):
        line, _ = made()
        text = [line.lines[s.line] if s.line is not None else None for s in line.steps]
        contour = line.operations[0]
        kinds = [(s.kind, t) for s, t in zip(line.steps[contour.first : contour.end], text[contour.first : contour.end])]
        self.assertEqual(kinds[0][0], playback.TOOL_CHANGE)
        self.assertIn("TOOL CALL 1 Z", kinds[0][1])
        self.assertTrue(kinds[1][1].endswith("L X-10. Y+0. R0 FMAX"), kinds[1][1])  # over the first point
        self.assertIn("L Z+5. R0 FMAX M3 M8", kinds[2][1])
        self.assertIn("L Z-2. R0 FQ30", kinds[3][1])
        self.assertIn("L X+0. RR FQ31", kinds[4][1])
        self.assertTrue(kinds[5][1].endswith("L X+40."), kinds[5][1])
        self.assertTrue(kinds[-1][1].endswith("L Z+40. R0 FMAX"), kinds[-1][1])  # the retract
        drilling = line.operations[1]
        steps = line.steps[drilling.first : drilling.end]
        self.assertIn("L Z100 R0 FMAX", line.lines[steps[0].line])  # up to the tool change: the tool's end
        self.assertIn("TOOL CALL 2 Z", line.lines[steps[1].line])
        holes = [line.lines[s.line] for s in steps[2:]]
        self.assertEqual(sorted(set(h.split(" ", 1)[1] for h in holes)), ["CYCL CALL POS X+10. Y+10. Z0 FMAX M3 M8", "CYCL CALL POS X+30. Y+10. Z0 FMAX"])
        thread = line.operations[2]
        self.assertTrue(any(" CP IPA" in line.lines[s.line] for s in line.steps[thread.first : thread.end]))

    def test_line_numbers_go_on(self):
        """Every step after the first runs a line at or after the line before."""
        line, _ = made()
        numbers = [s.line for s in line.steps]
        self.assertNotIn(None, numbers)
        self.assertEqual(numbers, sorted(numbers))

    def test_without_lines(self):
        prog = program()
        line = playback.timeline(prog.setups[0])
        self.assertTrue(all(s.line is None for s in line.steps))
        self.assertIsNone(line.line_at(1.0))


class SteppingTest(unittest.TestCase):
    def test_move_by_move(self):
        line, _ = made()
        t, stops = 0.0, []
        while t < line.total_s:
            t = line.next_stop(t)
            stops.append(t)
        timed = [s.end_s for s in line.steps if s.duration_s > 0.0]
        self.assertEqual(len(stops), len(timed))
        np.testing.assert_allclose(stops, timed)
        # at the end of a step it is still the one going on; back to its start
        step = line.steps[5]
        self.assertEqual(line.step_at(step.end_s), 5)
        self.assertAlmostEqual(line.previous_stop(step.end_s), step.start_s)
        self.assertAlmostEqual(line.previous_stop(step.start_s), line.steps[4].start_s)
        self.assertEqual(line.previous_stop(0.0), 0.0)
        self.assertEqual(line.next_stop(line.total_s), line.total_s)

    def test_operation_by_operation(self):
        line, _ = made()
        starts = [o.start_s for o in line.operations]
        self.assertEqual(line.next_operation(0.0), starts[1])
        self.assertEqual(line.next_operation(starts[1]), starts[2])
        self.assertEqual(line.next_operation(starts[2] + 1.0), line.total_s)
        self.assertEqual(line.previous_operation(starts[2] + 1.0), starts[2])
        self.assertEqual(line.previous_operation(starts[2]), starts[1])
        self.assertEqual(line.operation_at(starts[1] + 0.1), 1)
        self.assertEqual(line.operation_at(0.0), 0)


class PolylineTest(unittest.TestCase):
    def test_arcs_as_chords(self):
        whole = machine.Segment((5.0, 0.0, 0.0), (5.0, 0.0, -1.0), False, (0.0, 0.0), False)
        line = playback.polyline([machine.Segment((5.0, 0.0, 2.0), (5.0, 0.0, 0.0), True), whole])
        n = len(line.points)
        self.assertEqual(list(line.firsts), [0, 1, n - 1])
        self.assertEqual(list(line.rapid[:1]), [True])
        self.assertFalse(line.rapid[1:].any())
        r = np.hypot(line.points[1:, 0], line.points[1:, 1])
        np.testing.assert_allclose(r, 5.0)
        # chords within CHORD_MM of the circle
        self.assertLessEqual(5.0 * (1.0 - math.cos(math.pi / (n - 2))), playback.CHORD_MM + 1e-12)
        np.testing.assert_allclose(line.points[-1], (5.0, 0.0, -1.0))
        self.assertEqual(line.done(0, 0.0), 1)
        self.assertEqual(line.done(0, 1.0), 2)
        self.assertEqual(line.done(1, 0.5), 2 + (n - 2) // 2)
        self.assertEqual(line.done(1, 1.0), n)

    def test_an_operation(self):
        line, _ = made()
        for op in line.operations:
            drawn, first = playback.operation_polyline(line, op)
            steps = line.steps[op.first : op.end]
            count = sum(s.count for s in steps)
            self.assertEqual(len(drawn.firsts), count + 1)
            np.testing.assert_allclose(drawn.points[0], line.segments[first].start)
            np.testing.assert_allclose(drawn.points[-1], line.segments[first + count - 1].end)


class ToolShapeTest(unittest.TestCase):
    def closed(self, profile):
        vertices, triangles = playback.revolve(profile, 16)
        edges = {}
        for a, b, c in triangles:
            for e in ((a, b), (b, c), (c, a)):
                edges[e] = edges.get(e, 0) + 1
        for (a, b), n in edges.items():
            self.assertEqual(n, 1, (a, b))
            self.assertIn((b, a), edges)  # each edge once each way: closed, turned the same way
        return vertices

    def test_shapes(self):
        cases = (
            (tools.Tool("End", "Endmill", 6.0, cutting_length_mm=12.0, length_mm=50.0), 0.0),
            (tools.Tool("Ball", "Ballend", 6.0), 0.0),
            (tools.Tool("Bull", "Bullnose", 10.0, corner_radius_mm=1.0), 0.0),
            (tools.Tool("Drill", "Drill", 5.0, angle_deg=118.0), 0.0),
            (tools.Tool("Chamfer", "Chamfer", 10.0, angle_deg=90.0, tip_diameter_mm=1.0), 0.0),
            (tools.Tool("M3", "ThreadMill", 2.4, pitch_mm=0.5, cutting_length_mm=1.5, neck_diameter_mm=1.8,
                        neck_length_mm=8.0, shank_diameter_mm=6.0, length_mm=50.0), 0.0),  # fmt: skip
            (None, 0.0),
        )
        for tool, tip in cases:
            cutting, body = playback.tool_profile(tool, 4.0)
            self.assertEqual(cutting[0], (0.0, tip), tool)
            self.assertEqual(cutting[-1][1], body[0][1])
            vertices = self.closed(cutting)
            self.closed(body)
            r = (tool.diameter_mm if tool else 4.0) / 2.0
            self.assertAlmostEqual(np.hypot(vertices[:, 0], vertices[:, 1]).max(), r)
        cutting, body = playback.tool_profile(cases[0][0], 0.0)
        self.assertEqual((cutting[-1][1], body[-1][1]), (12.0, 50.0))
        cutting, body = playback.tool_profile(cases[5][0], 0.0)
        self.assertEqual(body[1:4], [(0.9, 1.5), (0.9, 8.0), (3.0, 8.0)])
        cutting, _ = playback.tool_profile(cases[3][0], 0.0)
        self.assertAlmostEqual(cutting[1][1], 2.5 / math.tan(math.radians(59.0)))
        cutting, _ = playback.tool_profile(None, 4.0)
        self.assertEqual(cutting, [(0.0, 0.0), (2.0, 0.0), (2.0, 12.0), (0.0, 12.0)])


BOUNDS = stock.Bounds(-5.0, -5.0, -12.0, 45.0, 25.0, 0.0)
TOOLS = {
    1: tools.Tool("Frees 6mm", "Endmill", 6.0, cutting_length_mm=15.0),
    2: tools.Tool("Boor 5", "Drill", 5.0, angle_deg=118.0, cutting_length_mm=20.0),
    3: tools.Tool("Draadfrees M3", "ThreadMill", 2.4, pitch_mm=0.5, cutting_length_mm=8.0),
}


class MaterialTest(unittest.TestCase):
    """The stock as the machine leaves it (model.playback_stock)."""

    RESOLUTION = 80

    def volume(self, line, t):
        return float(playback_stock.fresh_cut(line, BOUNDS, TOOLS, t, self.RESOLUTION).volume())

    def test_at_the_start_the_block(self):
        line, _ = made()
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION)
        self.assertAlmostEqual(material.volume(), 50.0 * 30.0 * 12.0, delta=1e-6)
        self.assertAlmostEqual(material.cell_mm, 50.0 / self.RESOLUTION, delta=0.02 * 50.0 / self.RESOLUTION)  # whole cells on each axis

    def test_on_bit_by_bit_as_at_once(self):
        """Played on in small bits (pieces of segments cut up to the tool)
        the stock is the one cut at once, at every operation's end."""
        line, _ = made()
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION)
        cell = (50.0 / self.RESOLUTION) ** 3
        previous = material.volume()
        for k in range(1, 301):
            t = line.total_s * k / 300.0
            v = material.cut_to(t).volume()
            self.assertLessEqual(v, previous + 1e-6)
            previous = v
        for op in line.operations:
            material.cut_to(op.end_s)
            self.assertAlmostEqual(material.volume(), self.volume(line, op.end_s), delta=cell, msg=op.label)
        # half way along a long cutting move: the material up to the tool only
        side = next(s for s in line.steps if s.kind == nc.LINE and s.duration_s > 3.0)
        middle = (side.start_s + side.end_s) / 2.0
        self.assertLess(self.volume(line, side.end_s), self.volume(line, middle) - 5.0 * cell)
        self.assertLess(self.volume(line, middle), self.volume(line, side.start_s) - 5.0 * cell)

    def test_on_against_a_deadline(self):
        """Cut for no time at all (the player in a hurry), each call stops at
        the end of a segment past where it was, and on and on it gets to the
        end: the stock the one cut at once."""
        line, _ = made()
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION)
        ends = [float(s + d) for s, d in zip(line.starts, line.durations)]
        calls = 0
        while material.t < line.total_s - 1e-9:
            before = material.t
            material.cut_to(line.total_s, seconds=0.0)
            calls += 1
            self.assertGreater(material.t, before)
            self.assertTrue(any(abs(material.t - e) < 1e-9 for e in ends), material.t)
        self.assertGreater(calls, 5)
        whole = playback_stock.fresh_cut(line, BOUNDS, TOOLS, line.total_s, self.RESOLUTION)
        for a in range(3):  # each ray as much material (their storage may differ)
            np.testing.assert_allclose(material.stock.rays[a].length(), whole.rays[a].length(), atol=1e-9)
        # a time it gets to in time: all the way
        material.cut_to(0.0)
        material.cut_to(line.total_s * 0.3, seconds=60.0)
        self.assertEqual(material.t, line.total_s * 0.3)
        self.assertAlmostEqual(material.volume(), self.volume(line, line.total_s * 0.3), delta=1e-6)

    def test_back_from_a_copy(self):
        line, _ = made()
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION, snapshot_segments=5)
        material.cut_to(line.total_s)
        kept = playback_stock.kept_times(material)
        self.assertGreater(len(kept), 5)
        cell = (50.0 / self.RESOLUTION) ** 3
        for t in (line.total_s * 0.7, line.total_s * 0.3, kept[3], 0.0, line.total_s * 0.9):
            self.assertAlmostEqual(material.cut_to(t).volume(), self.volume(line, t), delta=cell, msg=t)
        self.assertAlmostEqual(material.cut_to(0.0).volume(), 50.0 * 30.0 * 12.0, delta=1e-6)

    def test_rapid_moves_cut_too(self):
        """A rapid move into the block takes material as a feed move would,
        and is found (model.crashes)."""
        moves = (
            nc.Move(nc.RAPID, 10.0, 10.0, 5.0),
            nc.Move(nc.RAPID, 10.0, 10.0, -3.0),  # down into the block at FMAX
            nc.Move(nc.LINE, 20.0, 10.0, -3.0, 600.0),
        )
        setup = nc.Setup(1, "Setup 1", None, (nc.Operation(nc.CONTOUR, "Contour", MILL_6, moves),))
        line = playback.timeline(setup)
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION)
        down = next(k for k, s in enumerate(line.segments) if s.rapid and s.end[2] < -1.0)
        before = material.cut_to(float(line.starts[down])).volume()
        after = material.cut_to(float(line.starts[down] + line.durations[down])).volume()
        self.assertAlmostEqual(before - after, math.pi * 9.0 * 3.0, delta=0.2 * math.pi * 9.0 * 3.0)
        found = playback_stock.played_crashes(material)
        self.assertEqual([(c.kind, c.segment) for c in found], [(crashes.RAPID, down)])
        self.assertAlmostEqual(found[0].volume_mm3, math.pi * 9.0 * 3.0, delta=0.2 * math.pi * 9.0 * 3.0)
        step = line.steps[found[0].step]
        self.assertTrue(step.kind == nc.RAPID and step.first <= down < step.first + step.count)
        self.assertEqual(found[0].line, step.line)
        # found once: going back and on again finds it again, not twice
        material.cut_to(0.0)
        material.cut_to(line.total_s)
        self.assertEqual(len(material.crashes), 1)

    def test_none_in_a_good_program(self):
        line, _ = made()
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION)
        material.cut_to(line.total_s)
        self.assertEqual(material.crashes, {})

    def test_shank_in_material(self):
        """An end mill of 3 mm cutting length 5 deep: down at feed its
        cutting part goes first (nothing), along the side its shank takes
        2 mm of the block's top."""
        moves = (
            nc.Move(nc.RAPID, 10.0, 10.0, 5.0),
            nc.Move(nc.LINE, 10.0, 10.0, -5.0, 200.0),
            nc.Move(nc.LINE, 20.0, 10.0, -5.0, 600.0),
        )
        setup = nc.Setup(1, "Setup 1", None, (nc.Operation(nc.CONTOUR, "Contour", MILL_6, moves),))
        line = playback.timeline(setup)
        short = {1: tools.Tool("Frees 6mm", "Endmill", 6.0, cutting_length_mm=3.0, length_mm=30.0)}
        material = playback_stock.Material(line, BOUNDS, short, self.RESOLUTION)
        material.cut_to(line.total_s)
        found = playback_stock.played_crashes(material)
        side = next(k for k, s in enumerate(line.segments) if not s.rapid and s.end[0] > 15.0)
        self.assertEqual([(c.kind, c.segment) for c in found], [(crashes.SHANK, side)])
        self.assertAlmostEqual(found[0].volume_mm3, 10.0 * 6.0 * 2.0, delta=0.15 * 120.0)

    def test_mesh(self):
        line, _ = made()
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION)
        mesh = material.cut_to(line.total_s / 2.0) and material.mesh()
        self.assertAlmostEqual(mesh.volume(), material.volume(), delta=0.02 * material.volume())

    def test_pieces_follow_the_stock(self):
        """The pieces drawn again only where the material changed, going on
        bit by bit, back (from a copy kept) and on again, are always the
        surface of the stock then."""
        line, _ = made()
        material = playback_stock.Material(line, BOUNDS, TOOLS, self.RESOLUTION, snapshot_segments=5)
        drawn = {}

        def draw():
            whole, pieces = material.changed_pieces()
            if whole:
                drawn.clear()
            drawn.update(pieces)
            return whole, pieces

        self.assertTrue(draw()[0])
        total = len(drawn)
        times = [line.total_s * k / 40.0 for k in range(1, 41)]
        times += [line.total_s * 0.55, line.total_s * 0.2, line.total_s * 0.9, 0.0, line.total_s * 0.35]
        some = False
        for t in times:
            material.cut_to(t)
            whole, pieces = draw()
            self.assertFalse(whole)
            some = some or 0 < len(pieces) < total
            self.assertEqual(triangles(drawn.values()), triangles([stocklab.surface(material.stock)]), msg=t)
        self.assertTrue(some)  # not all again each time
        material.cut_to(material.t)
        self.assertEqual(draw(), (False, {}))  # nothing changed: nothing again


def triangles(meshes):
    """The triangles of meshes as their corners (to compare meshes numbered
    differently), sorted."""
    rows = [np.round(m.vertices[m.triangles].reshape(-1, 9), 9) for m in meshes if len(m.triangles)]
    return sorted(map(tuple, np.concatenate(rows).tolist())) if rows else []


class TextTest(unittest.TestCase):
    def test_clock(self):
        self.assertEqual([playback.clock_text(s) for s in (0.0, 7.9, 65.0, 1433.0, 3725.0)], ["0:00", "0:07", "1:05", "23:53", "1:02:05"])

    def test_speed(self):
        self.assertEqual([playback.speed_text(s) for s in (0.1, 1.0, 25.0)], ["×0.1", "×1", "×25"])


if __name__ == "__main__":
    unittest.main()
