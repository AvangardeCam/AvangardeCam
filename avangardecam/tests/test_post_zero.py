# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Postprocessors and the zero points of operations (experimental); plain
Python, no FreeCAD:

    python3 -m unittest avangardecam.tests.test_post_zero   (from the add-on's folder)

The Soraluce program follows the programs the shop runs on that machine:
every operation between the labels RESET and FREE, the datum shift, the
tilted plane and the head cycle. It has not run on the machine yet.
"""

import datetime
import unittest

from avangardecam.model import frame, nc
from avangardecam.model.stock import Bounds
from avangardecam.post import heidenhain, machines, soraluce

MILL = nc.Tool(162, "Face mill 125", 125.0, 500.0, 200.0, 300.0)
DRILL = nc.Tool(18, "Centre drill 12", 12.0, 1000.0, 50.0, 50.0)
AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# on the right wall of a block 953 wide: shifted along X, the tool axis along X (SPB90)
RIGHT = frame.Frame((476.5, 0.0, -1.75), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
LEFT = frame.Frame((-476.5, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0))
SHIFTED = frame.Frame((20.0, -10.0, -2.0), *AXES)


def R(x, y, z):
    return nc.Move(nc.RAPID, x, y, z)


def L(x, y, z, feed, compensation=None):
    return nc.Move(nc.LINE, x, y, z, feed, compensation=compensation)


# a cut along a wall with RL, coming in on a line and going out on one
WALL = (
    R(-180.5, -233.727, None),
    R(-180.5, -233.727, 25.0),
    R(-180.5, -233.727, 7.0),
    L(-180.5, -233.727, 2.5, 200.0),
    L(-131.886, -185.114, 2.5, 300.0, nc.LEFT),
    nc.Move(nc.ARC, -111.75, -136.5, 2.5, 300.0, (-180.5, -136.5), False, nc.LEFT),
    L(-111.75, 136.5, 2.5, 300.0, nc.LEFT),
    L(-180.5, 233.727, 2.5, 300.0),
    R(-180.5, 233.727, 45.0),
)
LINE = (R(-50.0, 50.0, None), R(-50.0, 50.0, 20.0), R(-50.0, 50.0, 2.0), L(-50.0, 50.0, -20.0, 200.0), L(50.0, 50.0, -20.0, 300.0), R(50.0, 50.0, 20.0))
CYCLE = nc.DrillCycle(
    5.1, 50.0, 2.0, 10.0, 0.0, 0.0, 0.2, 0.2, 0.0, 0.2, 0.0, 0.0, 3000.0,
    (nc.DrillHole(-120.0, 0.0, 0.0, -5.1), nc.DrillHole(120.0, 0.0, 0.0, -5.1)),
)  # fmt: skip
STOCK = Bounds(-476.5, -170.5, -203.0, 476.5, 170.5, 167.0)


def program(*operations, stock=None):
    return nc.Program("DEMO", "demo", datetime.date(2026, 11, 16), (nc.Setup(1, "Setup 1", stock, tuple(operations)),))


def contour(label, tool=MILL, moves=LINE, zero=None):
    return nc.Operation(nc.CONTOUR, label, tool, moves, zero=zero)


def text(written):
    return written.replace("\r\n", "\n")


SORALUCE = """0 BEGIN PGM DEMO MM
1 ;SORALUCE T35
2 ;demo
3 ;16-11-2026
4 ;
5 CYCL DEF 247 REF.PUNT VASTL. ~
6    Q339=+1    ;REF.PUNT-NUMMER
7 BLK FORM 0.1 Z X-476.5 Y-170.5 Z-203.
8 BLK FORM 0.2 X+476.5 Y+170.5 Z+167.
9 CALL LBL "RESET"
10 CALL LBL "FREE"
11 * - T162 Face mill 125 (Contour)
12 M1
13 CALL LBL "RESET"
14 CALL LBL "FREE"
15 TOOL CALL 162 Z S500 F300 DL0 DR0
16 TOOL DEF 18
17 FN0: Q30=200 ;voeding Z
18 FN0: Q31=300 ;voeding XY
19 ;KOP POSITIONEREN
20 L Z1196.47 R0 FMAX M91
21 CALL LBL "RESET"
22 CALL LBL "FREE"
23 M1
24 CYCL DEF 7.0 NULPUNT
25 CYCL DEF 7.1  X+476.5
26 CYCL DEF 7.2  Y+0.
27 CYCL DEF 7.3  Z-1.75
28 M138 A B
29 PLANE SPATIAL SPA0. SPB90. SPC0. STAY COORD ROT
30 CYCL DEF 397 HEAD CYCLE ~
 Q1507=+Q121 ; VERT. JOINT DEGREES ~
 Q1506=+Q120 ; HORIZ. JOINT DEGREE
31 L Z100 R0 FMAX
32 L X-180.5 Y-233.727 R0 FMAX M13
33 L Z+25. R0 FMAX
34 L Z+7. R0 FMAX
35 L Z+2.5 R0 FQ30
36 L X-131.886 Y-185.114 RL FQ31
37 CC X-180.5 Y-136.5
38 C X-111.75 Y-136.5 DR+
39 L Y+136.5
40 L X-180.5 Y+233.727 R0
41 L Z+40. R0 FMAX
42 M9
43 * - T18 Centre drill 12 (Drilling)
44 M1
45 CALL LBL "RESET"
46 CALL LBL "FREE"
47 TOOL CALL 18 Z S1000 F50 DL0 DR0
48 TOOL DEF 162
49 ;KOP POSITIONEREN
50 L Z1196.47 R0 FMAX M91
51 CALL LBL "RESET"
52 CALL LBL "FREE"
53 M1
54 CYCL DEF 7.0 NULPUNT
55 CYCL DEF 7.1  X-476.5
56 CYCL DEF 7.2  Y+0.
57 CYCL DEF 7.3  Z+0.
58 M138 A B
59 PLANE SPATIAL SPA0. SPB-90. SPC0. STAY COORD ROT
60 CYCL DEF 397 HEAD CYCLE ~
 Q1507=+Q121 ; VERT. JOINT DEGREES ~
 Q1506=+Q120 ; HORIZ. JOINT DEGREE
61 L Z100 R0 FMAX
62 CYCL DEF 205 UNIVERSEELBOREN ~
    Q200=2   ;VEILIGHEIDSAFSTAND ~
    Q201=-5.1    ;DIEPTE ~
    Q206=50  ;AANZET DIEPTEVERPL. ~
    Q202=+5.1    ;DIEPTEVERPLAATSING ~
    Q203=0    ;COORD. OPPERVLAK ~
    Q204=10   ;2e VEILIGHEIDSAFST. ~
    Q212=+0.    ;AFNAMEWAARDE ~
    Q205=+0.    ;MIN. DIEPTEVERPL. ~
    Q258=0.2  ;ONDERBR.AFST. BOVEN ~
    Q259=0.2  ;ONDERBR.AFST. ONDER ~
    Q257=0    ;BOORDPTE SPAANBREUK ~
    Q256=0.2  ;TERUGTR.HGT SPAANBR. ~
    Q211=0.    ;STILSTANDSTIJD ONDER ~
    Q379=+0    ;STARTPUNT ~
    Q253=3000  ;AANZET VOORPOS.
63 CYCL CALL POS X-120. Y+0. Z0 FMAX M13
64 CYCL CALL POS X+120. Y+0. Z0 FMAX
65 M9
66 * - T162 Face mill 125 (Top)
67 M1
68 CALL LBL "RESET"
69 CALL LBL "FREE"
70 TOOL CALL 162 Z S500 F300 DL0 DR0
71 TOOL DEF 162
72 FN0: Q30=200 ;voeding Z
73 FN0: Q31=300 ;voeding XY
74 ;KOP POSITIONEREN
75 L Z1196.47 R0 FMAX M91
76 CALL LBL "RESET"
77 CALL LBL "FREE"
78 M1
79 CYCL DEF 7.0 NULPUNT
80 CYCL DEF 7.1  X+0.
81 CYCL DEF 7.2  Y+0.
82 CYCL DEF 7.3  Z+0.
83 M138 A B
84 PLANE SPATIAL SPA0. SPB0. SPC0. STAY COORD ROT
85 CYCL DEF 397 HEAD CYCLE ~
 Q1507=+Q121 ; VERT. JOINT DEGREES ~
 Q1506=+Q120 ; HORIZ. JOINT DEGREE
86 L Z100 R0 FMAX
87 L X-180.5 Y-233.727 R0 FMAX M13
88 L Z+25. R0 FMAX
89 L Z+7. R0 FMAX
90 L Z+2.5 R0 FQ30
91 L X-131.886 Y-185.114 RL FQ31
92 CC X-180.5 Y-136.5
93 C X-111.75 Y-136.5 DR+
94 L Y+136.5
95 L X-180.5 Y+233.727 R0
96 L Z+40. R0 FMAX
97 M9
98 CALL LBL "RESET"
99 CALL LBL "FREE"
100 CALL LBL "HEAD0"
101 L X1750 Y1124.52 FMAX M91
102 * - M30
103 M30
104 * - LABELS
105 LBL "RESET"
106 M138
107 PLANE RESET STAY
108 CYCL DEF 7.0 NULPUNT
109 CYCL DEF 7.1  X0
110 CYCL DEF 7.2  Y0
111 CYCL DEF 7.3  Z0
112 LBL 0
113 LBL "FREE"
114 M9
115 L Z1196.47 R0 FMAX M91
116 L X1750 Y1124.52 R0 FMAX M91
117 LBL 0
118 LBL "HEAD0"
119 M138 A B
120 PLANE SPATIAL SPA0 SPB0 SPC0 STAY COORD ROT
121 CYCL DEF 397 HEAD CYCLE ~
 Q1507=+Q121 ; VERT. JOINT DEGREES ~
 Q1506=+Q120 ; HORIZ. JOINT DEGREE
122 LBL 0
123 END PGM DEMO MM
"""

BRIDGEPORT = """0 BEGIN PGM DEMO MM
1 ;BRIDGEPORT V1000
2 ;demo
3 ;16-11-2026
4 ;
5 CYCL DEF 247 REF.PUNT VASTL. ~
6    Q339=+1    ;REF.PUNT-NUMMER
7 *- Contourbewerking
8   *- Face mill 125 - TOOL#: 162 - Diameter: Ø+125.
9 TOOL CALL 162 Z S500 DL0 DR0;Face mill 125
10 TOOL DEF 18
11 FN0: Q30=200 ;voeding Z
12 FN0: Q31=300 ;voeding XY
13 L X-50. Y+50. R0 FMAX
14 L Z+20. R0 FMAX M3 M8
15 L Z+2. R0 FMAX
16 L Z-20. R0 FQ30
17 L X+50. FQ31
18 L Z+40. R0 FMAX
19 *- Contourbewerking
20 L Z100 R0 FMAX
21 CYCL DEF 7.0 NULPUNT
22 CYCL DEF 7.1  X+20.
23 CYCL DEF 7.2  Y-10.
24 CYCL DEF 7.3  Z-2.
25 L X-50. Y+50. R0 FMAX
26 L Z+20. R0 FMAX
27 L Z+2. R0 FMAX
28 L Z-20. R0 FQ30
29 L X+50. FQ31
30 L Z+40. R0 FMAX
31 CYCL DEF 7.0 NULPUNT
32 CYCL DEF 7.1  X+0.
33 CYCL DEF 7.2  Y+0.
34 CYCL DEF 7.3  Z+0.
35 L Z100 R0 FMAX
36 M01
37 L Z100 R0 FMAX M5 M9
38 *- Contourbewerking
39   *- Centre drill 12 - TOOL#: 18 - Diameter: Ø+12.
40 TOOL CALL 18 Z S1000 DL0 DR0;Centre drill 12
41 TOOL DEF 162
42 CYCL DEF 7.0 NULPUNT
43 CYCL DEF 7.1  X+20.
44 CYCL DEF 7.2  Y-10.
45 CYCL DEF 7.3  Z-2.
46 FN0: Q30=50 ;voeding Z
47 FN0: Q31=50 ;voeding XY
48 L X-50. Y+50. R0 FMAX
49 L Z+20. R0 FMAX M3 M8
50 L Z+2. R0 FMAX
51 L Z-20. R0 F200
52 L X+50. F300
53 L Z+40. R0 FMAX
54 *- Contourbewerking
55 CYCL DEF 7.0 NULPUNT
56 CYCL DEF 7.1  X+0.
57 CYCL DEF 7.2  Y+0.
58 CYCL DEF 7.3  Z+0.
59 L Z100 R0 FMAX
60 L X-50. Y+50. R0 FMAX
61 L Z+20. R0 FMAX
62 L Z+2. R0 FMAX
63 L Z-20. R0 F200
64 L X+50. F300
65 L Z+40. R0 FMAX
66 L Z100 R0 FMAX
67 M01
68 L Z100 R0 FMAX M5 M9
69 L X+500  Y+0  Z+0 R0 FMAX M91 M31
70 *- M30
71 M30
72 END PGM DEMO MM
"""


class TestSoraluce(unittest.TestCase):
    maxDiff = None

    def test_like_the_shop(self):
        """A wall cut on the right side (SPB90), a drilling on the left one
        (SPB-90) and a cut on the preset: each operation on its own."""
        written = soraluce.write(
            program(
                contour("Contour", moves=WALL, zero=RIGHT),
                nc.Operation(nc.DRILLING, "Drilling", DRILL, (), CYCLE, LEFT),
                contour("Top", moves=WALL),
                stock=STOCK,
            )
        )
        self.assertEqual(text(written), SORALUCE)
        self.assertEqual(written.count("\r\n"), SORALUCE.count("\n"), "CRLF line ends")

    def test_spatial_angles(self):
        self.assertEqual(soraluce.plane(None), "PLANE SPATIAL SPA0. SPB0. SPC0. STAY COORD ROT")
        self.assertEqual(soraluce.plane(SHIFTED), "PLANE SPATIAL SPA0. SPB0. SPC0. STAY COORD ROT")
        self.assertEqual(soraluce.plane(RIGHT), "PLANE SPATIAL SPA0. SPB90. SPC0. STAY COORD ROT")
        self.assertEqual(soraluce.plane(LEFT), "PLANE SPATIAL SPA0. SPB-90. SPC0. STAY COORD ROT")
        back = frame.Frame((0.0, 85.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))
        self.assertEqual(soraluce.plane(back), "PLANE SPATIAL SPA-90. SPB0. SPC0. STAY COORD ROT")
        turned = frame.Frame((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        self.assertEqual(soraluce.plane(turned), "PLANE SPATIAL SPA0. SPB0. SPC90. STAY COORD ROT")

    def test_every_operation_calls_its_tool(self):
        written = text(soraluce.write(program(contour("A"), contour("B"), contour("C", DRILL))))
        self.assertEqual(written.count("TOOL CALL 162 Z S500 F300 DL0 DR0"), 2)
        # the tool after it: the next other one, at the end the first one
        self.assertEqual([line.split(" ", 1)[1] for line in written.split("\n") if "TOOL DEF" in line], ["TOOL DEF 18", "TOOL DEF 18", "TOOL DEF 162"])
        self.assertEqual(written.count("CYCL DEF 397 HEAD CYCLE ~"), 4, "each operation and the label HEAD0")
        self.assertEqual(written.count(" FMAX M13\n"), 3)

    def test_counter_clockwise_spindle(self):
        left_hand = nc.Tool(7, "Left hand mill", 10.0, 800.0, 100.0, 200.0, clockwise=False)
        self.assertIn("L X-50. Y+50. R0 FMAX M14", soraluce.write(program(contour("A", left_hand))))

    def test_lines_of_the_moves(self):
        lines, lines_of = soraluce.numbered(program(contour("A")))
        self.assertTrue(lines[lines_of[(0, 0, "call")]].endswith("TOOL CALL 162 Z S500 F300 DL0 DR0"))
        self.assertTrue(lines[lines_of[(0, 0, "move", 4)]].endswith("L X+50. FQ31"))


class TestBridgeportShift(unittest.TestCase):
    maxDiff = None

    def test_datum_shift(self):
        """A on the preset, B shifted with the same tool (high on the preset
        first), C shifted with another tool, D on the preset again."""
        written = heidenhain.write(program(contour("A"), contour("B", zero=SHIFTED), contour("C", DRILL, zero=SHIFTED), contour("D", DRILL)))
        self.assertEqual(text(written), BRIDGEPORT)

    def test_no_shift_no_cycle_7(self):
        self.assertNotIn("CYCL DEF 7", heidenhain.write(program(contour("A"), contour("B", DRILL))))

    def test_shift_ends_before_the_program_does(self):
        written = text(heidenhain.write(program(contour("B", zero=SHIFTED))))
        end = written[written.rindex("CYCL DEF 7.0 NULPUNT") :]
        self.assertTrue(end.startswith("CYCL DEF 7.0 NULPUNT\n24 CYCL DEF 7.1  X+0.\n25 CYCL DEF 7.2  Y+0.\n26 CYCL DEF 7.3  Z+0.\n27 L Z100 R0 FMAX\n"), end)

    def test_turned_zero_point_is_refused(self):
        with self.assertRaisesRegex(ValueError, "Contour counts from a turned zero point .A\\+0 B\\+90 C\\+0.*BRIDGEPORT V1000"):
            heidenhain.write(program(contour("Contour", zero=RIGHT)))
        turned = frame.Frame((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        with self.assertRaises(ValueError):
            heidenhain.write(program(contour("Contour", zero=turned)))


class TestMachines(unittest.TestCase):
    def test_one_postprocessor_for_each_machine(self):
        self.assertEqual([post.key for post in machines.ALL], ["bridgeport_v1000", "soraluce_t35"])
        self.assertIs(machines.find("soraluce_t35"), machines.SORALUCE_T35)
        self.assertIs(machines.find("unknown"), machines.BRIDGEPORT_V1000)
        self.assertFalse(machines.BRIDGEPORT_V1000.tilts)
        self.assertTrue(machines.SORALUCE_T35.tilts)
        flat = program(contour("A"))
        self.assertEqual(machines.BRIDGEPORT_V1000.write(flat), heidenhain.write(flat))
        self.assertIn(";SORALUCE T35", machines.SORALUCE_T35.write(flat))
        for post in machines.ALL:
            self.assertEqual(post.module.EXTENSION, ".H")


if __name__ == "__main__":
    unittest.main()
