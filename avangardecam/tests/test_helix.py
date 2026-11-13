# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Helix milling tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_helix   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import datetime
import json
import math
import unittest

from avangardecam.model import helix, nc, operations
from avangardecam.post import heidenhain

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

# the shop's Ø3 end mill for aluminium (T2), as the tool library has it
MILL_3 = nc.Tool(2, "VHM ALU Frees 3mm", 3.0, 12000.0, 225.0, 300.0)

# the half turns going down by -0.132 (the others -0.131) of a helix 16 mm
# down in 122 half turns, as the shop's program rounds them
DEEPER = (3, 10, 16, 23, 30, 37, 44, 50, 57, 64, 71, 77, 84, 91, 98, 105, 111, 118)


# where the two holes of shop_holes are (made up: not the real part's)
HOLES = ((12.0, 5.0), (-12.0, 5.0))


def shop_holes():
    """Two Ø4.5 holes 16 deep milled with the Ø3 end mill, block for block
    as a real part's program of the shop (not in the repository) mills
    its holes, here at HOLES:
    over the hole, down to its top with Q30, out with RL to 1.6 from the
    centre, a half circle onto the wall, 61 turns down in half turns, once
    round at the depth, a half circle off the wall, back to the centre
    with R0; 10 mm above the top to the next hole. The title is
    AvangardeCam's (the shop's is the user's name of the operation) and
    one block differs on purpose, as in the thread milling: the shop's program drops
    the R0 of the plunge on the second hole (L Z+0. FQ30)."""
    blocks = [
        "*- Helix Milling",
        "  *- VHM ALU Frees 3mm - TOOL#: 2 - Diameter: Ø+3.",
        "TOOL CALL 2 Z S12000 DL0 DR0;VHM ALU Frees 3mm",
        "TOOL DEF 2",
        "FN0: Q30=225 ;voeding Z",
        "FN0: Q31=300 ;voeding XY",
        "L X+12. Y+5. R0 FMAX",
        "L Z+20. R0 FMAX M3 M8",
    ]
    X = heidenhain.number
    for k, (x, y) in enumerate(HOLES):
        Y = X(y)
        if k:
            blocks += ["L Z+10. R0 FMAX", "L X{} R0 FMAX".format(X(x))]  # Y stays
        blocks += ["L Z+2. R0 FMAX", "L Z+0. R0 FQ30", "L X{} RL FQ31".format(X(x - 1.6))]
        blocks += ["CC X{} Y{}".format(X(x + 0.325), Y), "C X{} Y{} DR+".format(X(x + 2.25), Y)]
        for i in range(122):
            blocks += ["CC X{} Y{}".format(X(x), Y), "CP IPA+180. IZ-0.13{} DR+".format(2 if i in DEEPER else 1)]
        blocks += ["CC X{} Y{}".format(X(x), Y), "C X{} Y{} DR+".format(X(x - 2.25), Y)]
        blocks += ["CC X{} Y{}".format(X(x), Y), "C X{} Y{} DR+".format(X(x + 2.25), Y)]
        blocks += ["CC X{} Y{}".format(X(x + 0.325), Y), "C X{} Y{} DR+".format(X(x - 1.6), Y)]
        blocks.append("L X{} R0".format(X(x)))
    return blocks + ["L Z+40. R0 FMAX", "L Z100 R0 FMAX", "M01", "L Z100 R0 FMAX M5 M9"]


def holes(*centres, diameter=4.5, depth=16.0):
    return [helix.HelixHole(x, y, 0.0, -depth, diameter) for x, y in centres]


def program_blocks(milling, found, tool=MILL_3):
    moves = helix.moves(milling, found, tool.diameter_mm, tool.feed_z_mm_min, tool.feed_xy_mm_min)
    operation = nc.Operation(nc.HELIX_MILLING, "Helix milling 1", tool, moves)
    setup = nc.Setup(1, "Setup 1", None, (operation,))
    program = nc.Program("HELIX", "", datetime.date(2026, 10, 26), (setup,))
    text = heidenhain.write(program)
    lines = [line.split(" ", 1)[1] for line in text.split("\r\n") if line]
    return lines[lines.index("*- Helix Milling") : lines.index("L X+500  Y+0  Z+0 R0 FMAX M91 M31")]


class TestHelixModel(unittest.TestCase):
    def test_values(self):
        values = helix.HelixMilling()
        self.assertIs(values.validate(), values)
        self.assertEqual(
            (values.depth_mm, values.through_mm, values.pitch_mm, values.finish_xy_mm, values.offset_xy_mm),
            (None, 1.0, None, 0.1, 0.0),
        )
        self.assertEqual(
            (values.step_over_percent, values.predrilled_mm, values.method, values.z_step_mm, values.compensation),
            (50.0, 0.0, helix.HELIX, None, nc.LEFT),
        )
        every = helix.HelixMilling(-12.0, 0.5, 0.4, 0.2, -0.01, 40.0, 4.2, helix.HELIX_CONTOUR, 3.0, nc.RIGHT)
        self.assertEqual(operations.from_json(operations.to_json(every)), every)
        self.assertEqual(json.loads(operations.to_json(every))["kind"], "helix_milling")
        for bad in (
            helix.HelixMilling(depth_mm=0.0),
            helix.HelixMilling(depth_mm=3.0),
            helix.HelixMilling(through_mm=-1.0),
            helix.HelixMilling(pitch_mm=0.0),
            helix.HelixMilling(finish_xy_mm=-0.1),
            helix.HelixMilling(offset_xy_mm=-2000.0),
            helix.HelixMilling(step_over_percent=0.5),
            helix.HelixMilling(step_over_percent=101.0),
            helix.HelixMilling(predrilled_mm=-1.0),
            helix.HelixMilling(method="spiral"),
            helix.HelixMilling(z_step_mm=0.0),
            helix.HelixMilling(compensation="off"),
        ):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()

    def test_pitch(self):
        """By default the tool's diameter x tan 5°: Ø3 goes 16 mm down in
        122 half turns, as the shop's program."""
        self.assertEqual(helix.auto_pitch(3.0), 0.2625)
        self.assertEqual(helix.auto_pitch(10.0), 0.8749)
        self.assertEqual(helix.HelixMilling().pitch(3.0), 0.2625)
        self.assertEqual(helix.HelixMilling(pitch_mm=0.5).pitch(3.0), 0.5)
        self.assertEqual(helix.half_turns(16.0, 0.2625), 122)
        self.assertEqual(helix.half_turns(2.0, 1.0), 4)
        self.assertEqual(helix.half_turns(2.1, 1.0), 5)
        self.assertEqual(helix.half_turns(0.1, 1.0), 1)

    def test_walls(self):
        """The circles of the passes where the tool's edge cuts: with the
        allowance a rough helix and the wall (the user: two helices), without
        it the wall only; the XY offset moves the wall."""
        self.assertEqual(helix.HelixMilling(finish_xy_mm=0.0).walls(3.0, 4.5), [2.25])
        self.assertEqual(helix.HelixMilling().walls(3.0, 4.5), [2.15, 2.25])
        self.assertEqual(helix.HelixMilling(offset_xy_mm=0.02).walls(3.0, 4.5), [2.17, 2.27])
        self.assertEqual(helix.HelixMilling(offset_xy_mm=-0.05, finish_xy_mm=0.0).walls(3.0, 4.5), [2.2])

    def test_widening(self):
        """A Ø20 hole with Ø6 from solid: the tool centre goes out 2.3 mm a
        pass (no more than the step over, 3 mm), the first leaves no core;
        drilled Ø12 before: from its wall; drilled nearly as big: the
        finishing pass only."""
        self.assertEqual(helix.HelixMilling().walls(6.0, 20.0), [5.3, 7.6, 9.9, 10.0])
        self.assertEqual(helix.HelixMilling(predrilled_mm=12.0).walls(6.0, 20.0), [7.95, 9.9, 10.0])
        self.assertEqual(helix.HelixMilling(predrilled_mm=19.9).walls(6.0, 20.0), [10.0])
        # the whole tool sideways: still no more than its radius out of the middle, else a core is left
        self.assertEqual(helix.HelixMilling(step_over_percent=100.0, finish_xy_mm=0.0).walls(6.0, 20.0), [5.333333, 7.666667, 10.0])  # fmt: skip
        # drilled Ø2 under the Ø6: the first pass may reach 3 + 1 out of the middle
        self.assertEqual(helix.HelixMilling(step_over_percent=100.0, predrilled_mm=2.0, finish_xy_mm=0.0).walls(6.0, 20.0), [6.5, 10.0])  # fmt: skip

    def test_check(self):
        values = helix.HelixMilling()
        self.assertIs(values.check(3.0, 4.5, 16.0, 4.0), values)
        for milling, args, text in (
            (values, (4.5, 4.5, 5.0), "too big"),
            (helix.HelixMilling(offset_xy_mm=-0.75), (3.0, 4.5, 5.0), "too big for a Ø3 hole"),
            (helix.HelixMilling(predrilled_mm=4.5), (3.0, 4.5, 5.0), "drilled Ø4.5 already"),
            (helix.HelixMilling(finish_xy_mm=0.8), (3.0, 4.5, 5.0), "at most 0.74 mm"),
            (values, (3.0, 4.5, 0.0), "must go down"),
            (helix.HelixMilling(pitch_mm=4.5), (3.0, 4.5, 16.0, 4.0), "cutting length"),
            (helix.HelixMilling(pitch_mm=0.001), (3.0, 4.5, 16.0), "too many turns"),
            (helix.HelixMilling(method=helix.HELIX_CONTOUR), (3.0, 4.5, 16.0, 4.0), "enter a Z step"),
        ):
            with self.assertRaises(ValueError) as caught:
                milling.check(*args)
            self.assertIn(text, str(caught.exception), (milling, args))
        # drilled bigger than the rough pass: no rough pass, the allowance is fine
        helix.HelixMilling(finish_xy_mm=0.8, predrilled_mm=4.0).check(3.0, 4.5, 5.0)
        helix.HelixMilling(method=helix.HELIX_CONTOUR, z_step_mm=4.0).check(3.0, 4.5, 16.0, 4.0)

    def test_levels(self):
        self.assertEqual(helix.HelixMilling().levels(0.0, -16.0), [-16.0])
        self.assertEqual(helix.HelixMilling(z_step_mm=5.0).levels(0.0, -16.0), [-5.0, -10.0, -15.0, -16.0])
        self.assertEqual(helix.HelixMilling(z_step_mm=4.0).levels(1.0, -7.0), [-3.0, -7.0])

    def test_like_the_shop(self):
        """The shop's Ø4.5 holes, one helix (no allowance), auto pitch."""
        found = holes(*HOLES)
        self.assertEqual(program_blocks(helix.HelixMilling(-16.0, finish_xy_mm=0.0), found), shop_holes())

    def test_tool_centre(self):
        """FreeCAD's path: the tool centre 0.1 beside the hole's centre where
        it comes onto the wall, on a half circle 0.425 round, the helix 0.75
        round (2.25 - 1.5)."""
        found = holes((0.0, 0.0))
        moves = helix.moves(helix.HelixMilling(-16.0, finish_xy_mm=0.0), found, 3.0, 225.0, 300.0, program=False)
        self.assertTrue(all(m.compensation is None for m in moves))
        lead_in, onto, first = moves[3], moves[4], moves[5]
        self.assertEqual((lead_in.kind, lead_in.x, lead_in.z), (nc.LINE, -0.1, 0.0))
        self.assertEqual((onto.kind, onto.x, onto.clockwise), (nc.ARC, 0.75, False))
        self.assertAlmostEqual(onto.center[0], 0.325)
        self.assertEqual((first.x, first.center), (-0.75, (0.0, 0.0)))
        self.assertAlmostEqual(first.z, -16.0 / 122)
        program = helix.moves(helix.HelixMilling(-16.0, finish_xy_mm=0.0), found, 3.0, 225.0, 300.0)
        self.assertEqual((program[3].x, program[3].compensation), (-1.6, nc.LEFT))
        self.assertEqual(program[4].x, 2.25)
        self.assertAlmostEqual(program[4].center[0], 0.325)

    def test_two_helices(self):
        """With the allowance: a rough helix Ø4.3 and the wall Ø4.5, each
        from the top, the compensation on from the first."""
        lines = program_blocks(helix.HelixMilling(-2.0), holes((0.0, 0.0), depth=2.0))
        self.assertEqual([line for line in lines if " RL " in line], ["L X-1.6 RL FQ31"] * 2)
        self.assertEqual(lines.count("C X+2.15 Y+0. DR+"), 2, "onto the rough wall, round at the depth")
        self.assertEqual(lines.count("C X+2.25 Y+0. DR+"), 2)
        self.assertEqual(lines.count("CP IPA+180. IZ-0.125 DR+"), 32, "16 half turns of 0.125 each")
        self.assertEqual(lines[lines.index("L X+0. R0") + 1], "L Z+0. R0 FMAX", "up to the top for the next helix")

    def test_clockwise(self):
        lines = program_blocks(helix.HelixMilling(-2.0, finish_xy_mm=0.0, compensation=nc.RIGHT), holes((0.0, 0.0), depth=2.0))
        self.assertIn("L X-1.6 RR FQ31", lines)
        self.assertIn("CP IPA-180. IZ-0.125 DR-", lines)
        self.assertNotIn("DR+", " ".join(lines))

    def test_odd_half_turns(self):
        """An odd number of half turns ends on the other side: once round
        from there and off the wall across the hole."""
        lines = program_blocks(helix.HelixMilling(-0.375, pitch_mm=0.25, finish_xy_mm=0.0), holes((0.0, 0.0), depth=0.375))
        self.assertEqual(lines.count("CP IPA+180. IZ-0.125 DR+"), 3)
        end = lines.index("L X+0. R0")
        self.assertEqual(
            lines[end - 6 : end],
            ["CC X+0. Y+0.", "C X+2.25 Y+0. DR+", "CC X+0. Y+0.", "C X-2.25 Y+0. DR+", "CC X-0.325 Y+0.", "C X+1.6 Y+0. DR+"],
        )

    def test_widening_helices(self):
        """Ø20 with Ø6 from solid: four helices, each from the top."""
        tool = nc.Tool(6, "VHM 6mm", 6.0, 8000.0, 300.0, 1000.0)
        lines = program_blocks(helix.HelixMilling(-3.0), holes((0.0, 0.0), diameter=20.0, depth=3.0), tool)
        self.assertEqual(lines.count("L X-3.1 RL FQ31"), 4)
        for x in ("+5.3", "+7.6", "+9.9", "+10."):
            self.assertIn("C X{} Y+0. DR+".format(x), lines)

    def test_helix_then_contour(self):
        """A helix opens the hole, the wider passes are circles on the Z
        steps, on and off the wall on half circles."""
        tool = nc.Tool(6, "VHM 6mm", 6.0, 8000.0, 300.0, 1000.0)
        milling = helix.HelixMilling(-8.0, method=helix.HELIX_CONTOUR, z_step_mm=5.0)
        lines = program_blocks(milling, holes((0.0, 0.0), diameter=20.0, depth=8.0), tool)
        self.assertEqual(lines.count("L X-3.1 RL FQ31"), 1 + 3 * 2, "the helix, then 3 circles on 2 levels")
        self.assertEqual(sum(1 for line in lines if line.startswith("CP ")), helix.half_turns(8.0, helix.auto_pitch(6.0)))
        first = lines.index("L X+0. R0")
        self.assertEqual(lines[first + 1], "L Z-5. R0 FMAX", "up to the first level in the hole cut")
        self.assertEqual(lines[first + 2 : first + 5], ["L X-3.1 RL FQ31", "CC X+2.25 Y+0.", "C X+7.6 Y+0. DR+"])
        down = lines.index("L Z-8. R0 FQ30")
        self.assertEqual(lines[down - 2 : down], ["L X+0. R0", "L Z-6. R0 FMAX"], "down in the hole cut, the last 2 mm with the Z feed")
        self.assertIn("C X+10. Y+0. DR+", lines)


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestHelixEngine(unittest.TestCase):
    """The test parts of test_engine: the part with holes picked in the model
    (top at Z12, the zero on its middle: A Ø6 through at x -15, B Ø4 5 deep
    at x -5, D a Ø10 counterbore 3 deep at x 12), and the part with three
    holes through it and the sketch of its top (Ø6 at x -10, Ø4 at x 10)."""

    def setUp(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import helix as engine_helix
        from avangardecam.model import library
        from avangardecam.tests.test_engine import TestEngine
        from avangardecam.tests.test_model import LIBRARY

        self.cam, self.engine = cam, engine_helix
        self.helpers = TestEngine("setUp")
        self.helpers.setUp()
        self.helpers.library = library.load(LIBRARY)
        self.doc = self.helpers.doc

    def tearDown(self):
        FreeCAD.closeDocument(self.helpers.doc.Name)

    def model_setup(self):
        obj = self.helpers.model_with_holes()
        job = self.cam.ensure_job(self.doc, [obj])
        tc = self.cam.add_tool(job, self.helpers.variant(3, "Aluminium"))  # Ø4, 6 mm cutting length
        return obj, job, tc

    def blocks(self):
        text = heidenhain.write(self.cam.nc_program(self.helpers.doc, "HELIX"))
        return [line.split(" ", 1)[1] for line in text.split("\r\n") if line]

    def arcs(self, op):
        return [c for c in op.Path.Commands if c.Name in ("G2", "G3")]

    def test_model_holes(self):
        """A and the counterbore D with Ø4 from the model: A through (1 mm
        under it), two helices; D 3 deep, Ø10: widened in three helices."""
        obj, job, tc = self.model_setup()
        a, d = self.helpers.wall(obj, -15, 0, 3)[0], self.helpers.wall(obj, 12, 0, 5)[0]
        values = helix.HelixMilling()
        op = self.engine.add_model_helix_milling(job, obj, values, tc, [a, d])
        self.assertEqual(op.Label, "Helix milling 1")
        self.assertEqual(type(op.Proxy).__module__, "avangardecam.engine.helix")
        self.assertEqual(self.engine.helix_milling_of(op), (obj, values))
        self.assertIsNone(self.cam.drilling_of(op))
        self.assertEqual(
            self.engine.holes(op),
            [helix.HelixHole(-15.0, 0.0, 0.0, -13.0, 6.0), helix.HelixHole(12.0, 0.0, 0.0, -3.0, 10.0)],
        )
        # FreeCAD's path: the tool centre, counterclockwise, 0.9 out of A's centre on its first helix
        arcs = self.arcs(op)
        self.assertEqual({c.Name for c in arcs}, {"G3"})
        first = next(c for c in arcs if abs(c.Parameters["Z"]) > 1e-9).Parameters
        self.assertAlmostEqual(first["X"], -15.9)
        self.assertAlmostEqual(self.cam.path_summary(op)[1], -13.0)
        self.assertAlmostEqual(op.StartDepth.Value, 0.0)
        self.assertAlmostEqual(op.FinalDepth.Value, -13.0)
        self.assertAlmostEqual(op.SafeHeight.Value, 10.0, msg="from hole to hole")
        self.assertAlmostEqual(op.ClearanceHeight.Value, 20.0)
        self.assertAlmostEqual(op.StepDown.Value, 0.35, msg="the pitch: Ø4 x tan 5°")
        self.assertEqual((op.StepOver, op.CutMode, op.StartSide), (50, "Climb", "Inside"))

        blocks = self.blocks()
        self.assertIn("*- Helix Milling", blocks)
        self.assertEqual([b for b in blocks if " RL " in b], ["L X-17.1 RL FQ31"] * 2 + ["L X+9.9 RL FQ31"] * 3)
        for wall in ("C X-12.1 Y+0. DR+", "C X-12. Y+0. DR+", "C X+15.45 Y+0. DR+", "C X+16.9 Y+0. DR+", "C X+17. Y+0. DR+"):
            self.assertIn(wall, blocks)
        start = next(i for i, line in enumerate(blocks) if line.startswith("FN0: Q31="))
        self.assertEqual(blocks[start + 1 : start + 5], ["L X-15. Y+0. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+2. R0 FMAX", "L Z+0. R0 FQ30"])  # fmt: skip

        # D is 3 deep: 4 goes through its floor; B (Ø4) is too small for Ø4
        with self.assertRaises(self.cam.ProjectError) as caught:
            self.engine.set_helix_milling(op, helix.HelixMilling(-4.0))
        self.assertIn("goes through its floor", str(caught.exception))
        with self.assertRaises(self.cam.ProjectError) as caught:
            self.engine.add_model_helix_milling(job, obj, values, tc, [self.helpers.wall(obj, -5, 0, 2)[0]])
        self.assertIn("too big", str(caught.exception))
        self.engine.set_helix_milling(op, helix.HelixMilling(-2.0, finish_xy_mm=0.0, compensation=nc.RIGHT))
        self.assertAlmostEqual(self.cam.path_summary(op)[1], -2.0)
        self.assertEqual({c.Name for c in self.arcs(op)}, {"G2"})
        self.assertEqual(op.CutMode, "Conventional")

    def test_tools(self):
        obj, job, tc = self.model_setup()
        a = self.helpers.wall(obj, -15, 0, 3)[0]
        drill = self.cam.add_tool(job, self.helpers.variant(40, "Aluminium"))
        with self.assertRaises(self.cam.ProjectError) as caught:
            self.engine.add_model_helix_milling(job, obj, helix.HelixMilling(), drill, [a])
        self.assertIn("not an end mill", str(caught.exception))
        op = self.engine.add_model_helix_milling(job, obj, helix.HelixMilling(), tc, [a])
        self.assertIs(op.ToolController, tc, "the one chosen among several tools")
        big = self.cam.add_tool(job, self.helpers.variant(5, "Aluminium"))  # Ø6 in a Ø6 hole
        with self.assertRaises(self.cam.ProjectError):
            self.cam.set_tool(op, big)
        self.assertIs(op.ToolController, tc)
        small = self.cam.add_tool(job, self.helpers.variant(2, "Aluminium"))  # Ø3
        self.cam.change_operation(op, helix.HelixMilling(finish_xy_mm=0.0), small)
        self.assertEqual(self.engine.helix_milling_of(op)[1], helix.HelixMilling(finish_xy_mm=0.0))
        self.assertAlmostEqual(op.StepDown.Value, 0.2625)

    def test_path_drawing(self):
        """The view draws the program: the helices on the wall, where the
        edge cuts; FreeCAD's path keeps the tool centre."""
        obj, job, tc = self.model_setup()
        op = self.engine.add_model_helix_milling(job, obj, helix.HelixMilling(finish_xy_mm=0.0), tc, [self.helpers.wall(obj, -15, 0, 3)[0]])  # fmt: skip
        pieces = self.cam.path_drawing(op)
        self.assertEqual(pieces, self.engine.path_drawing(op))
        # on the way down, between coming onto the wall at the top and leaving it at Z-Depth
        cut = [p for kind, points in pieces if kind == self.cam.DRAW_FEED for p in points if -12.5 < p.z < -0.5]
        self.assertGreater(len(cut), 100)
        for p in cut:
            self.assertAlmostEqual(math.hypot(p.x + 15.0, p.y), 3.0, places=6)

    def test_sketch_circles(self):
        _body, job, _drill, sketch = self.helpers.drilling_setup()
        tc = self.cam.add_tool(job, self.helpers.variant(2, "Aluminium"))  # Ø3, 4 mm cutting length
        picked = [self.helpers.circle(sketch, 10, 0), self.helpers.circle(sketch, -10, 0)]
        with self.assertRaises(self.cam.ProjectError) as caught:
            self.engine.add_helix_milling(job, sketch, helix.HelixMilling(), tc, picked)
        self.assertIn("enter the depth", str(caught.exception))
        values = helix.HelixMilling(-4.0, finish_xy_mm=0.0)
        op = self.engine.add_helix_milling(job, sketch, values, tc, picked)
        self.assertEqual(self.engine.helix_milling_of(op), (sketch, values))
        self.assertEqual([(round(h.x, 6), round(h.y, 6), round(h.diameter_mm, 6)) for h in self.engine.holes(op)], [(10, 0, 4), (-10, 0, 6)])
        self.assertEqual([b for b in self.blocks() if " RL " in b], ["L X+8.4 RL FQ31", "L X-11.6 RL FQ31"])
        # the zero 2 mm above the part: the holes start at Z-2
        self.cam.set_zero(job, FreeCAD.Placement(FreeCAD.Vector(0, 0, 14), FreeCAD.Rotation()))
        self.assertAlmostEqual(self.cam.path_summary(op)[1], -6.0)
        self.assertAlmostEqual(op.SafeHeight.Value, 8.0)

    def test_in_a_file(self):
        import os
        import tempfile

        _body, job, _drill, sketch = self.helpers.drilling_setup()
        tc = self.cam.add_tool(job, self.helpers.variant(2, "Aluminium"))
        values = helix.HelixMilling(-3.0, method=helix.HELIX_CONTOUR)
        picked = [self.helpers.circle(sketch, -10, 0), self.helpers.circle(sketch, 10, 0)]
        op = self.engine.add_helix_milling(job, sketch, values, tc, picked)
        before = op.Path.toGCode()
        path = os.path.join(tempfile.mkdtemp(), "helix_milling.FCStd")
        self.helpers.doc.saveAs(path)
        FreeCAD.closeDocument(self.helpers.doc.Name)
        self.helpers.doc = FreeCAD.openDocument(path)
        op = self.cam.operations(self.cam.find_job(self.helpers.doc))[0]
        self.assertEqual(self.engine.helix_milling_of(op)[1], values)
        op.touch()
        self.helpers.doc.recompute()
        self.assertEqual(op.Path.toGCode(), before)
        self.assertIn("*- Helix Milling", self.blocks())
