# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Postprocessor tests; plain Python, no FreeCAD:

    python3 -m unittest avangardecam.tests.test_post   (from src/Mod/AvangardeCam)
"""

import datetime
import os
import tempfile
import unittest

from avangardecam.model import clearing, leads, nc, operations, threads
from avangardecam.model.stock import Bounds
from avangardecam.post import heidenhain

# a program the shop runs on its TNC 620 (a 100 x 100 square cut
# 20 deep with a 12 mm end mill, no radius compensation), as it runs there
SHOP_SQUARE = """0 BEGIN PGM 0000 MM
1 ;BRIDGEPORT V1000
2 ;commentaar
3 ;16-10-2026
4 ;
5 CYCL DEF 247 REF.PUNT VASTL. ~
6    Q339=+1    ;REF.PUNT-NUMMER
7 BLK FORM 0.1 Z X-55. Y-55. Z-20.
8 BLK FORM 0.2 X+55. Y+55. Z+0.
9 *- Contourbewerking
10   *- VHM ALU Frees 12mm - TOOL#: 8 - Diameter: Ø+12.
11 TOOL CALL 8 Z S12000 DL0 DR0;VHM ALU Frees 12mm
12 TOOL DEF 8
13 FN0: Q30=1310 ;voeding Z
14 FN0: Q31=1750 ;voeding XY
15 L X-50. Y+50. R0 FMAX
16 L Z+20. R0 FMAX M3 M8
17 L Z+2. R0 FMAX
18 L Z-20. R0 FQ30
19 L X+50. FQ31
20 L Y-50.
21 L X-50.
22 L Y+50.
23 L Z+40. R0 FMAX
24 L Z100 R0 FMAX
25 M01
26 L Z100 R0 FMAX M5 M9
27 L X+500  Y+0  Z+0 R0 FMAX M91 M31
28 *- M30
29 M30
30 END PGM 0000 MM
"""

# the same square with RL (tool left of the contour, climb
# milling): it starts in the middle of the first line, comes in and leaves
# on 45 degrees of an arc of 1.1 x the tool radius, from and back to its centre
SHOP_SQUARE_RL = SHOP_SQUARE.replace(
    """15 L X-50. Y+50. R0 FMAX
16 L Z+20. R0 FMAX M3 M8
17 L Z+2. R0 FMAX
18 L Z-20. R0 FQ30
19 L X+50. FQ31
20 L Y-50.
21 L X-50.
22 L Y+50.
23 L Z+40. R0 FMAX
24 L Z100 R0 FMAX
25 M01
26 L Z100 R0 FMAX M5 M9
27 L X+500  Y+0  Z+0 R0 FMAX M91 M31
28 *- M30
29 M30
30 END PGM 0000 MM
""",
    """15 L X+0. Y+56.6 R0 FMAX
16 L Z+20. R0 FMAX M3 M8
17 L Z+2. R0 FMAX
18 L Z-20. R0 FQ30
19 L X-4.667 Y+51.933 RL FQ31
20 CC X+0. Y+56.6
21 C X+0. Y+50. DR+
22 L X+50.
23 L Y-50.
24 L X-50.
25 L Y+50.
26 L X+0.
27 CC X+0. Y+56.6
28 C X+4.667 Y+51.933 DR+
29 L X+0. Y+56.6 R0
30 L Z+40. R0 FMAX
31 L Z100 R0 FMAX
32 M01
33 L Z100 R0 FMAX M5 M9
34 L X+500  Y+0  Z+0 R0 FMAX M91 M31
35 *- M30
36 M30
37 END PGM 0000 MM
""",
)

# a program the shop runs on its TNC 620: two holes drilled 30
# deep with a 10.2 mm drill, cycle 205 pecking 2 mm and breaking the chip
# every 5 mm, no stock. Line 4 is the path of the project file of
# the shop's CAM there, ";" when it has none (as in the square); the structure line 7 is
# English (the user's choice), the shop's programs have "*- Diepboren met Spaanlossen".
SHOP_DRILLING = """0 BEGIN PGM 0000 MM
1 ;BRIDGEPORT V1000
2 ;commentaar
3 ;16-10-2026
4 ;
5 CYCL DEF 247 REF.PUNT VASTL. ~
6    Q339=+1    ;REF.PUNT-NUMMER
7 *- Deep Drilling With Chip Breaking
8   * -TOOL#: 42 Diameter: Ø+10.2 -- NX Boor 10.2mm  Alu
9 TOOL CALL 42 Z S2185 DL0 DR0;
10 TOOL DEF 42
11 CYCL DEF 205 UNIVERSEELBOREN ~
    Q200=2   ;VEILIGHEIDSAFSTAND ~
    Q201=-30.    ;DIEPTE ~
    Q206=500  ;AANZET DIEPTEVERPL. ~
    Q202=+2.    ;DIEPTEVERPLAATSING ~
    Q203=0    ;COORD. OPPERVLAK ~
    Q204=50   ;2e VEILIGHEIDSAFST. ~
    Q212=+0.    ;AFNAMEWAARDE ~
    Q205=+0.    ;MIN. DIEPTEVERPL. ~
    Q258=0.2  ;ONDERBR.AFST. BOVEN ~
    Q259=0.2  ;ONDERBR.AFST. ONDER ~
    Q257=5    ;BOORDPTE SPAANBREUK ~
    Q256=0.2  ;TERUGTR.HGT SPAANBR. ~
    Q211=0.    ;STILSTANDSTIJD ONDER ~
    Q379=+0    ;STARTPUNT ~
    Q253=375  ;AANZET VOORPOS.
12 CYCL CALL POS X+0. Y+0. Z0 FMAX M3 M8
13 CYCL CALL POS X+15. Y+0. Z0 FMAX
14 L Z100 R0 FMAX
15 M01
16 L Z100 R0 FMAX M5 M9
17 L X+500  Y+0  Z+0 R0 FMAX M91 M31
18 *- M30
19 M30
20 END PGM 0000 MM
"""

# the shop's name of the drill has two spaces
DRILL_10 = nc.Tool(42, "NX Boor 10.2mm  Alu", 10.2, 2185, feed_z_mm_min=375, feed_xy_mm_min=500)


def drill_cycle(holes=((0, 0), (15, 0)), surface_z=0.0, depth_mm=-30.0, **values):
    """holes: (x, y) at surface_z, depth_mm deep, or nc.DrillHole."""
    holes = tuple(h if isinstance(h, nc.DrillHole) else nc.DrillHole(h[0], h[1], surface_z, depth_mm) for h in holes)
    cycle = nc.DrillCycle(
        peck_mm=2.0, feed_mm_min=500, clearance_mm=2.0, second_clearance_mm=50.0,
        decrement_mm=0.0, min_peck_mm=0.0, upper_stop_mm=0.2, lower_stop_mm=0.2, chip_break_mm=5.0,
        chip_retract_mm=0.2, dwell_s=0.0, start_mm=0.0, preposition_feed_mm_min=375, holes=holes,
    )  # fmt: skip
    return cycle.__class__(**dict(cycle.__dict__, **values))


def drilling(tool=DRILL_10, cycle=None):
    return nc.Operation(nc.DRILLING, "Drilling", tool, (), cycle or drill_cycle())


MILL_12 = nc.Tool(8, "VHM ALU Frees 12mm", 12.0, 12000, feed_z_mm_min=1310, feed_xy_mm_min=1750)
MILL_8 = nc.Tool(21, "Iscar Vingerfrees 8mm RVS", 8.0, 3000, feed_z_mm_min=150, feed_xy_mm_min=525)


def R(x, y, z):
    return nc.Move(nc.RAPID, x, y, z)


def L(x, y, z, feed):
    return nc.Move(nc.LINE, x, y, z, feed)


def square_moves(tool):
    """The square as FreeCAD's Engrave runs it: up to the clearance height,
    over the start, down to the safe height, plunge, cut, up again."""
    z, xy = tool.feed_z_mm_min, tool.feed_xy_mm_min
    return (
        R(None, None, 20),
        R(-50, 50, 20),
        R(-50, 50, 2),
        L(-50, 50, -20, z),
        L(50, 50, -20, xy),
        L(50, -50, -20, xy),
        L(-50, -50, -20, xy),
        L(-50, 50, -20, xy),
        R(-50, 50, 20),
    )


def square_moves_rl(tool):
    """The square with RL as the engine gives it: the lines themselves from
    the middle of the first one, with the lead arcs of model.leads (radius
    1.1 x the tool radius, as the shop's programs take them)."""
    z, xy = tool.feed_z_mm_min, tool.feed_xy_mm_min
    r = 1.1 * tool.diameter_mm / 2.0
    centre, start = leads.lead_in((0, 50), (1, 0), nc.LEFT, r)
    out_centre, end = leads.lead_out((0, 50), (1, 0), nc.LEFT, r)
    ccw = leads.clockwise(nc.LEFT)

    def C(x, y, centre):
        return nc.Move(nc.ARC, x, y, -20, xy, centre, ccw, nc.LEFT)

    def RL(x, y):
        return nc.Move(nc.LINE, x, y, -20, xy, compensation=nc.LEFT)

    return (
        R(None, None, 20),
        R(centre[0], centre[1], 20),
        R(centre[0], centre[1], 2),
        L(centre[0], centre[1], -20, z),
        RL(*start),
        C(0, 50, centre),
        RL(50, 50),
        RL(50, -50),
        RL(-50, -50),
        RL(-50, 50),
        RL(0, 50),
        C(end[0], end[1], out_centre),
        L(out_centre[0], out_centre[1], -20, xy),
        R(out_centre[0], out_centre[1], 20),
    )


THREAD_MILL_M3 = nc.Tool(216, "Draadfrees M3 P=0.5 Alu", 2.4, 12000, feed_z_mm_min=225, feed_xy_mm_min=300)


def shop_thread(holes, half_turns=26):
    """An M3 thread milled in each hole, its blocks as the shop's programs have them
    for the shop (a real part's program, not in the repository):
    over the hole, down to its top with Q30, out to the major radius with
    RR, 13 turns of the helix down in half turns of half the pitch, back to
    the centre, and the same helix again; 10 mm above the top to the next
    hole. One block differs on purpose: the shop's programs drop the R0 of the
    plunge on the second hole and after (L Z+0. FQ30), AvangardeCam writes
    it on every hole as on the first."""
    blocks = [
        "*- Thread Milling",
        "  *- Draadfrees M3 P=0.5 Alu - TOOL#: 216 - Diameter: Ø+2.4",
        "TOOL CALL 216 Z S12000 DL0 DR0;Draadfrees M3 P=0.5 Alu",
        "TOOL DEF 216",
        "FN0: Q30=225 ;voeding Z",
        "FN0: Q31=300 ;voeding XY",
    ]
    previous = None
    for x, y in holes:
        X, Y = heidenhain.number(x), heidenhain.number(y)
        if previous is None:
            blocks += ["L X{} Y{} R0 FMAX".format(X, Y), "L Z+20. R0 FMAX M3 M8"]
        else:
            moved = ["X" + X] if x != previous[0] else []
            moved += ["Y" + Y] if y != previous[1] else []
            blocks += ["L Z+10. R0 FMAX", "L {} R0 FMAX".format(" ".join(moved))]
        blocks += ["L Z+2. R0 FMAX", "L Z+0. R0 FQ30"]
        for k in range(2):
            if k:
                blocks.append("L Z+0. R0 FMAX")
            blocks.append("L X{} RR FQ31".format(heidenhain.number(x + 1.5)))
            blocks += ["CC X{} Y{}".format(X, Y), "CP IPA-180. IZ-0.25 DR-"] * half_turns
            blocks.append("L X{} R0".format(X))
        previous = (x, y)
    return blocks + ["L Z+40. R0 FMAX", "L Z100 R0 FMAX", "M01", "L Z100 R0 FMAX M5 M9"]


def thread_milling(holes, tool=THREAD_MILL_M3, thread=None, pitch=0.5):
    thread = thread or operations.ThreadMilling(3.0, -6.5)
    moves = threads.moves(
        thread, [threads.ThreadHole(x, y, 0.0) for x, y in holes], pitch, thread.major_diameter_mm / 2.0,
        tool.feed_z_mm_min, tool.feed_xy_mm_min, nc.RIGHT,
    )  # fmt: skip
    return nc.Operation(nc.THREAD_MILLING, "Thread milling 1", tool, moves)


def program(*setups, name="0000"):
    return nc.Program(name, "commentaar", datetime.date(2026, 10, 16), tuple(setups))


def setup(preset, *operations):
    return nc.Setup(preset, "Setup {}".format(preset), Bounds(-55, -55, -20, 55, 55, 0), tuple(operations))


def contour(tool, moves=None):
    return nc.Operation(nc.CONTOUR, "Contour", tool, moves or square_moves(tool))


def blocks(text):
    return [line.split(" ", 1)[1] for line in text.split("\r\n") if line]


class TestHeidenhain(unittest.TestCase):
    def test_adaptive_clearing(self):
        """Its own title; the helix into a closed area in half turns (CP,
        IZ from the rounded heights), a whole turn on the level, the moves
        over cleared floor rapid 0.5 mm above the level."""
        pocket = clearing.Piece(
            (-2.0,), 0.0, (0.0, 0.0), (3.01, 0.0),
            ((clearing.CUT, ((1.0, 1.0), (2.0, 1.0))), (clearing.LINK, ((2.0, -1.0),)), (clearing.CUT, ((1.0, -1.0),))),
        )  # fmt: skip
        moves = clearing.moves([pocket], 3.0, 0.5, 5.0, MILL_12.feed_z_mm_min, MILL_12.feed_xy_mm_min)
        text = blocks(heidenhain.write(program(setup(1, nc.Operation(nc.ADAPTIVE, "Adaptive 1", MILL_12, moves)))))
        self.assertIn("*- Adaptive Clearing", text)
        i = text.index("L X+3. Y+0. R0 FMAX")
        self.assertEqual(text[i : i + 4], ["L X+3. Y+0. R0 FMAX", "L Z+20. R0 FMAX M3 M8", "L Z+2. R0 FMAX", "L Z+0. R0 FQ30"])  # fmt: skip
        self.assertEqual(text[i + 4 : i + 9], ["CC X+0. Y+0.", "CP IPA-180. IZ-0.825 DR-", "CC X+0. Y+0.", "CP IPA-180. IZ-0.824 DR-", "CC X+0. Y+0."])  # fmt: skip
        self.assertTrue(text[i + 9].startswith("CP IPA-76.") and text[i + 9].endswith(" IZ-0.351 DR-"), text[i + 9])
        self.assertTrue(text[i + 11].startswith("C X") and text[i + 11].endswith(" DR- FQ31"), text[i + 11])
        cut = text[text.index("L X+1. Y+1.") :]
        self.assertEqual(cut[:7], ["L X+1. Y+1.", "L X+2.", "L Z-1.5 R0 FMAX", "L Y-1. R0 FMAX", "L Z-2. R0 FQ30", "L X+1. FQ31", "L Z+40. R0 FMAX"])  # fmt: skip

    def test_drilling_like_the_shop(self):
        no_stock = nc.Setup(1, "Setup 1", None, (drilling(),))
        text = heidenhain.write(program(no_stock))
        self.assertEqual(text, SHOP_DRILLING.replace("\n", "\r\n"))

    def test_drilling_values(self):
        cycle = drill_cycle(
            ((-12.5, 4.25),), surface_z=-5.0, depth_mm=-10.043, peck_mm=10.043, dwell_s=0.25, start_mm=7.5,
            decrement_mm=0.5, min_peck_mm=1.0,
        )  # fmt: skip
        text = blocks(heidenhain.write(program(setup(2, drilling(cycle=cycle)))))
        self.assertIn("BLK FORM 0.1 Z X-55. Y-55. Z-20.", text)
        q = {line.split("=")[0].strip(): line for line in text if line.strip().startswith("Q")}
        self.assertEqual(q["Q201"].split(";")[0].strip(), "Q201=-10.043")
        self.assertEqual(q["Q203"].split(";")[0].strip(), "Q203=0", "the surface is in CYCL CALL POS")
        self.assertEqual(q["Q211"].split(";")[0].strip(), "Q211=0.25")
        self.assertEqual(q["Q379"].split(";")[0].strip(), "Q379=+7.5")
        self.assertEqual(q["Q212"].split(";")[0].strip(), "Q212=+0.5")
        self.assertIn("CYCL CALL POS X-12.5 Y+4.25 Z-5 FMAX M3 M8", text)
        # a mill after the drill: its tool call as for a contour, from above the last hole
        both = blocks(heidenhain.write(program(setup(1, drilling(cycle=cycle), contour(MILL_12)))))
        self.assertEqual(both.count("TOOL DEF 8"), 1)
        self.assertEqual(both.count("TOOL DEF 42"), 1, "the drill is called first, the mill after it")
        mill = both.index("TOOL CALL 8 Z S12000 DL0 DR0;VHM ALU Frees 12mm")
        self.assertEqual(both[mill - 1], "  *- VHM ALU Frees 12mm - TOOL#: 8 - Diameter: Ø+12.")
        self.assertEqual(both[mill + 2 : mill + 5], ["FN0: Q30=1310 ;voeding Z", "FN0: Q31=1750 ;voeding XY", "L X-50. Y+50. R0 FMAX"])  # fmt: skip
        with self.assertRaises(ValueError):
            heidenhain.write(program(setup(1, drilling(cycle=drill_cycle(())))))

    def test_drilling_holes_of_a_model(self):
        """Holes picked in a model: each at its own top; the cycle again
        when the depth changes, the whole depth at once without a peck."""
        holes = (
            nc.DrillHole(0, 0, 0.0, -12.0),
            nc.DrillHole(10, 0, -5.0, -12.0),
            nc.DrillHole(20, 0, -5.0, -7.5),
            nc.DrillHole(30, 0, 0.0, -12.0),
        )
        text = blocks(heidenhain.write(program(setup(1, drilling(cycle=drill_cycle(holes, peck_mm=None))))))
        calls = [line for line in text if line.startswith(("CYCL DEF 205", "CYCL CALL POS"))]
        self.assertEqual(
            calls,
            [
                "CYCL DEF 205 UNIVERSEELBOREN ~",
                "CYCL CALL POS X+0. Y+0. Z0 FMAX M3 M8",
                "CYCL CALL POS X+10. Y+0. Z-5 FMAX",
                "CYCL DEF 205 UNIVERSEELBOREN ~",
                "CYCL CALL POS X+20. Y+0. Z-5 FMAX",
                "CYCL DEF 205 UNIVERSEELBOREN ~",
                "CYCL CALL POS X+30. Y+0. Z0 FMAX",
            ],
        )
        lines = heidenhain.write(program(setup(1, drilling(cycle=drill_cycle(holes, peck_mm=None))))).split("\r\n")
        depths = [line.split(";")[0].strip() for line in lines if line.strip().startswith(("Q201", "Q202"))]
        self.assertEqual(depths, ["Q201=-12.", "Q202=+12.", "Q201=-7.5", "Q202=+7.5", "Q201=-12.", "Q202=+12."])

    def test_thread_milling_like_the_shop(self):
        holes = ((12.5, 4.0), (12.5, -4.0), (-12.5, 4.0))
        text = blocks(heidenhain.write(program(setup(1, thread_milling(holes)))))
        start = text.index("*- Thread Milling")
        self.assertEqual(text[start : text.index("L X+500  Y+0  Z+0 R0 FMAX M91 M31")], shop_thread(holes))

    def test_thread_milling_last_arc_shorter(self):
        """6.6 deep with P0.5: 26 half turns to 6.5, then 72° for the last 0.1."""
        op = thread_milling(((0.0, 0.0),), thread=operations.ThreadMilling(3.0, -6.6, passes=1))
        text = blocks(heidenhain.write(program(setup(1, op))))
        arcs = [line for line in text if line.startswith("CP ")]
        self.assertEqual(arcs, ["CP IPA-180. IZ-0.25 DR-"] * 26 + ["CP IPA-72. IZ-0.1 DR-"])
        back = text[text.index(arcs[-1]) + 1]
        self.assertEqual(back, "L X+0. Y+0. R0", "back to the centre from where the last arc ends")

    def test_thread_milling_pitch_does_not_drift(self):
        """A pipe thread's half pitch (G1/4: 0.6685) has more digits than the
        program: the half turns go down by -0.668 and -0.669 so that they add
        up to the depth, as the shop's programs round their helices."""
        pitch = 25.4 / 19
        thread = operations.ThreadMilling(13.157, -12 * pitch, passes=1)
        tool = nc.Tool(225, "Draadfrees G1/4-G3/8 Alu", 9.84, 8850, feed_z_mm_min=1125, feed_xy_mm_min=1500)
        text = blocks(heidenhain.write(program(setup(1, thread_milling(((0.0, 0.0),), tool, thread, pitch)))))
        downs = [float(line.split("IZ")[1].split()[0]) for line in text if line.startswith("CP ")]
        self.assertEqual(len(downs), 24)
        self.assertEqual(set(downs), {-0.668, -0.669})
        self.assertAlmostEqual(sum(downs), round(-12 * pitch, 3), places=9)

    def test_like_the_shop(self):
        text = heidenhain.write(program(setup(1, contour(MILL_12))))
        self.assertEqual(text, SHOP_SQUARE.replace("\n", "\r\n"))

    def test_radius_compensation_like_the_shop(self):
        moves = square_moves_rl(MILL_12)
        text = heidenhain.write(program(setup(1, contour(MILL_12, moves))))
        self.assertEqual(text, SHOP_SQUARE_RL.replace("\n", "\r\n"))
        # RR: the same words, the arcs clockwise
        right = tuple(
            m._replace(compensation=nc.RIGHT, clockwise=True) if m.compensation else m for m in moves
        )
        cut = blocks(heidenhain.write(program(setup(1, contour(MILL_12, right)))))
        self.assertIn("L X-4.667 Y+51.933 RR FQ31", cut)
        self.assertIn("C X+0. Y+50. DR-", cut)

    def test_radius_compensation_only_on_lines(self):
        moves = square_moves_rl(MILL_12)
        on_arc = moves[:4] + (moves[5],)  # switched on by the arc
        with self.assertRaises(ValueError):
            heidenhain.write(program(setup(1, contour(MILL_12, on_arc))))

    def test_radius_compensation_without_approach(self):
        # over the start with RL above the part, straight down, up with it
        # and off above the part
        z, xy = MILL_12.feed_z_mm_min, MILL_12.feed_xy_mm_min

        def on(kind, x, y, height, feed=None):
            return nc.Move(kind, x, y, height, feed, compensation=nc.LEFT)

        moves = (
            R(None, None, 20),
            on(nc.RAPID, 0, 50, 20),
            on(nc.RAPID, 0, 50, 2),
            on(nc.LINE, 0, 50, -20, z),
            on(nc.LINE, 50, 50, -20, xy),
            on(nc.LINE, 50, -50, -20, xy),
            on(nc.LINE, -50, -50, -20, xy),
            on(nc.LINE, -50, 50, -20, xy),
            on(nc.LINE, 0, 50, -20, xy),
            on(nc.RAPID, 0, 50, 20),
        )
        text = blocks(heidenhain.write(program(setup(1, contour(MILL_12, moves)))))
        start = text.index("FN0: Q31=1750 ;voeding XY") + 1
        self.assertEqual(
            text[start : start + 13],
            ["L X+0. Y+50. RL FMAX", "L Z+20. FMAX M3 M8", "L Z+2. FMAX", "L Z-20. FQ30", "L X+50. FQ31", "L Y-50.",
             "L X-50.", "L Y+50.", "L X+0.", "L Z+40. FMAX", "L X+0. Y+50. R0 FMAX", "L Z100 R0 FMAX", "M01"],
        )  # fmt: skip

    def test_saved_as_the_control_reads_it(self):
        text = heidenhain.write(program(setup(1, contour(MILL_12))))
        path = os.path.join(tempfile.mkdtemp(), "0000.H")
        heidenhain.save(text, path)
        with open(path, "rb") as f:
            data = f.read()
        self.assertIn(b"Diameter: \xd8+12.\r\n", data, "ISO-8859-1, CRLF")

    def test_numbers(self):
        self.assertEqual(
            [heidenhain.number(v) for v in (50, -4.6667, 56.6, 0, -0.0001, 0.25)],
            ["+50.", "-4.667", "+56.6", "+0.", "+0.", "+0.25"],
        )
        self.assertEqual([heidenhain.plain(v) for v in (12000.0, 87.5)], ["12000", "87.5"])
        self.assertEqual(heidenhain.program_name("Mostek 1 (top)"), "Mostek_1__top_")

    def test_arcs_and_other_feeds(self):
        moves = (
            R(None, None, 20),
            R(0, 10, 20),
            R(0, 10, 3),
            L(0, 10, -1, 150),
            nc.Move(nc.ARC, 10, 0, -1, 525, (0, 0), True),
            nc.Move(nc.ARC, 10, 0, -1, 525, (5, 0), False),  # a full circle
            L(20, 0, -1, 400),
            R(20, 0, 20),
        )
        text = blocks(heidenhain.write(program(setup(1, contour(MILL_8, moves)))))
        cut = text[text.index("L Z-1. R0 FQ30") :]
        self.assertEqual(
            cut[:7],
            ["L Z-1. R0 FQ30", "CC X+0. Y+0.", "C X+10. Y+0. DR- FQ31", "CC X+5. Y+0.", "C X+10. Y+0. DR+",
             "L X+20. F400", "L Z+40. R0 FMAX"],
        )  # fmt: skip
        # a helix: a quarter turn clockwise 1 mm down, then a whole turn on up
        helix = moves[:4] + (
            nc.Move(nc.ARC, 10, 0, -2, 525, (0, 0), True),
            nc.Move(nc.ARC, 10, 0, -1, 525, (5, 0), False),
        )
        text = blocks(heidenhain.write(program(setup(1, contour(MILL_8, helix)))))
        cut = text[text.index("L Z-1. R0 FQ30") + 1 :]
        self.assertEqual(cut[:4], ["CC X+0. Y+0.", "CP IPA-90. IZ-1. DR- FQ31", "CC X+5. Y+0.", "CP IPA+360. IZ+1. DR+"])

    def test_setups_and_tools(self):
        text = blocks(
            heidenhain.write(program(setup(1, contour(MILL_12), contour(MILL_8)), setup(2, contour(MILL_8))))
        )
        self.assertEqual([b for b in text if b.startswith("TOOL")], ["TOOL CALL 8 Z S12000 DL0 DR0;VHM ALU Frees 12mm",
                         "TOOL DEF 21", "TOOL CALL 21 Z S3000 DL0 DR0;Iscar Vingerfrees 8mm RVS", "TOOL DEF 8"])  # fmt: skip
        self.assertEqual([b for b in text if "Q339" in b], ["   Q339=+1    ;REF.PUNT-NUMMER", "   Q339=+2    ;REF.PUNT-NUMMER"])  # fmt: skip
        self.assertEqual(len([b for b in text if b.startswith("BLK FORM")]), 2, "one stock, of the first setup")
        # the first tool ends before the second is called
        second = text.index("TOOL CALL 21 Z S3000 DL0 DR0;Iscar Vingerfrees 8mm RVS")
        self.assertEqual(text[second - 6 : second - 1], ["L Z+40. R0 FMAX", "L Z100 R0 FMAX", "M01", "L Z100 R0 FMAX M5 M9", "*- Contourbewerking"])  # fmt: skip
        # up high before the preset changes, then over the first point again
        preset = text.index("CYCL DEF 247 REF.PUNT VASTL. ~", second)
        self.assertEqual(text[preset - 1], "L Z100 R0 FMAX")
        self.assertEqual(text[preset + 2 : preset + 6], ["*- Contourbewerking", "L X-50. Y+50. R0 FMAX", "L Z+20. R0 FMAX", "L Z+2. R0 FMAX"])  # fmt: skip
        self.assertEqual(text[-4:], ["L X+500  Y+0  Z+0 R0 FMAX M91 M31", "*- M30", "M30", "END PGM 0000 MM"])


if __name__ == "__main__":
    unittest.main()
