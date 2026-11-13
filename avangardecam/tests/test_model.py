# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Model layer tests; plain Python, no FreeCAD:

    python3 -m unittest avangardecam.tests.test_model   (from src/Mod/AvangardeCam)
"""

import dataclasses
import json
import os
import tempfile
import unittest

from avangardecam.model import clearing, frame, leads, library, nc, operations, stock, threads, tools, units

LIBRARY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "Resources", "library", "tools.json"
)


class TestUnits(unittest.TestCase):
    def test_lengths(self):
        self.assertEqual(units.length_mm("6.0000 mm"), 6.0)
        self.assertEqual(units.length_mm("2 cm"), 20.0)
        self.assertAlmostEqual(units.length_mm("0.5 in"), 12.7)
        self.assertEqual(units.length_mm("3", default_unit="mm"), 3.0)

    def test_feeds(self):
        self.assertEqual(units.feed_mm_min("1250 mm/min"), 1250.0)
        self.assertEqual(units.feed_mm_min("20 mm/s"), 1200.0)
        self.assertEqual(units.feed_mm_min("187.5", default_unit="mm/min"), 187.5)

    def test_angles(self):
        self.assertEqual(units.angle_deg("118.0000 °"), 118.0)

    def test_refuses_what_it_cannot_be_sure_of(self):
        for bad in ("6", "6 furlong", "1,25 mm", "abc", ""):
            with self.assertRaises(units.UnitError, msg=bad):
                units.length_mm(bad)
        with self.assertRaises(units.UnitError):
            units.feed_mm_min("1250 mm")  # a length is not a feed
        with self.assertRaises(units.UnitError):
            units.plain_number("12000 rpm")


class TestTools(unittest.TestCase):
    def test_describe(self):
        t = tools.Tool("VHM ALU Frees 6mm", "Bullnose", 6.0, corner_radius_mm=0.2)
        self.assertEqual(tools.describe(t), "Bullnose Ø6 mm R0.2")
        self.assertEqual(tools.describe(tools.Tool("Boor", "Drill", 6.8, angle_deg=118)), "Drill Ø6.8 mm")
        thread_mill = tools.Tool("Draadfrees M6", "ThreadMill", 4.8, angle_deg=60, pitch_mm=1.0)
        self.assertEqual(tools.describe(thread_mill), "ThreadMill Ø4.8 mm P1 60°")

    def test_drill_tip(self):
        self.assertAlmostEqual(tools.tip_length_mm(tools.Tool("Boor", "Drill", 6.8, angle_deg=118)), 2.0429, places=4)
        self.assertAlmostEqual(tools.tip_length_mm(tools.Tool("Spot", "Drill", 10.0, angle_deg=90)), 5.0)
        for flat in (
            tools.Tool("Tijdelijk", "Drill", 8.0, angle_deg=180),
            tools.Tool("Boor", "Drill", 8.0),
            tools.Tool("Frees", "Endmill", 8.0, angle_deg=118),
        ):
            self.assertEqual(tools.tip_length_mm(flat), 0.0, flat)

    def test_invalid_tool(self):
        with self.assertRaises(ValueError):
            tools.Tool("broken", "Endmill", 0.0).validate()
        with self.assertRaises(ValueError):
            tools.Tool("odd", "Spoon", 6.0).validate()
        with self.assertRaises(ValueError):
            tools.Tool("slow", "Endmill", 6.0, spindle_rpm=0).validate()
        with self.assertRaises(ValueError):
            tools.Tool("no pitch", "ThreadMill", 4.8).validate()


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.entries = library.load(LIBRARY)

    def variants(self, number):
        return {e.workpiece_material: e for e in self.entries if e.number == number}

    def test_shop_library(self):
        self.assertEqual(len(self.entries), 276)
        self.assertEqual(len({e.id for e in self.entries}), 276, "ids are unique")
        self.assertEqual(
            library.materials(self.entries),
            ["Aluminium", "Ampco", "Gietijzer", "Phosphorbronze", "RVS", "Staal"],
        )
        t5 = self.variants(5)["Aluminium"].tool
        self.assertEqual((t5.shape, t5.diameter_mm, t5.corner_radius_mm, t5.flutes), ("Bullnose", 6, 0.2, 3))
        self.assertEqual((t5.spindle_rpm, t5.feed_xy_mm_min, t5.feed_z_mm_min), (12000, 1250, 937))

    def test_one_number_many_variants(self):
        self.assertEqual(sorted(self.variants(19)), ["RVS", "Staal"])
        self.assertEqual(len([e for e in self.entries if e.number == 14]), 3, "T14: three inserts")
        drills = self.variants(40)
        self.assertEqual(sorted(drills), ["Aluminium", "RVS", "Staal"])
        self.assertEqual(
            [drills[m].tool.spindle_rpm for m in ("Aluminium", "RVS", "Staal")], [3280, 562, 1640]
        )
        self.assertTrue(all(d.tool.shape == "Drill" and d.tool.angle_deg == 118 for d in drills.values()))

    def test_centre_drills(self):
        """Names with "°" are read too: the 90° centre drills, T18 in three
        materials and T31."""
        self.assertEqual(sorted(self.variants(18)), ["Aluminium", "RVS", "Staal"])
        t31 = self.variants(31)["Aluminium"].tool
        self.assertEqual(t31.name, "VHM Centerboor 90° 12mm Alu")
        self.assertEqual((t31.shape, t31.diameter_mm, t31.angle_deg), ("Drill", 12, 90))
        self.assertEqual((t31.spindle_rpm, t31.feed_xy_mm_min, t31.feed_z_mm_min), (12000, 1500, 1125))

    def test_thread_mills(self):
        mills = [e for e in self.entries if e.tool.shape == "ThreadMill"]
        self.assertEqual(len(mills), 22)
        m6 = self.variants(221)
        self.assertEqual(sorted(m6), ["Aluminium", "RVS", "Staal"])
        t = m6["Aluminium"].tool
        self.assertEqual(
            (t.diameter_mm, t.pitch_mm, t.angle_deg, t.neck_diameter_mm, t.neck_length_mm, t.length_mm),
            (4.8, 1.0, 60, 3.6, 20, 28),
        )
        self.assertEqual((t.spindle_rpm, t.feed_xy_mm_min, t.flutes), (8500, 500, 3))
        (g,) = self.variants(225).values()
        self.assertEqual((g.tool.pitch_mm, g.tool.angle_deg), (1.337, 55), "G (BSP) threads are 55°")
        self.assertEqual(self.variants(222)["Aluminium"].tool.diameter_mm, 5.9, "no floating point noise")

    def test_material_from_the_name(self):
        """The shop's table holds the drill's own name in the material field of T300-T330."""
        self.assertEqual(sorted(self.variants(330)), ["Aluminium", "RVS", "Staal"])
        (t61,) = [e for e in self.entries if e.tool.name == "NX Boor 12mm RVS"]
        self.assertEqual(t61.workpiece_material, "RVS", "empty material, taken from the name")
        self.assertFalse([e for e in self.entries if e.number in (131, 1001)], "left out")

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "tools.json")
            library.save(path, self.entries, source="test")
            self.assertEqual(library.load(path), self.entries)

    def test_refuses_broken_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "tools.json")
            with open(path, "w") as f:
                json.dump({"format": "something-else", "tools": []}, f)
            with self.assertRaises(ValueError):
                library.load(path)
            library.save(path, self.entries[:2])
            with open(path) as f:
                data = json.load(f)
            data["tools"][1]["id"] = data["tools"][0]["id"]
            with open(path, "w") as f:
                json.dump(data, f)
            with self.assertRaises(ValueError):
                library.load(path)

    def test_make_id(self):
        first = library.make_id(19, "RVS", "Iscar ruw frees 6mm RVS")
        self.assertEqual(first, "t19-rvs-iscar-ruw-frees-6mm-rvs")
        self.assertEqual(library.make_id(19, "RVS", "Iscar ruw frees 6mm RVS", {first}), first + "-2")


class TestStock(unittest.TestCase):
    MODEL = stock.Bounds(0, 0, 0, 40, 20, 12)

    def test_default_allowance(self):
        box = stock.BoxStock().validate().bounds(self.MODEL)
        self.assertEqual(box, stock.Bounds(-1, -1, 0, 41, 21, 13))
        self.assertEqual(box.size, (42, 22, 13))

    def test_top_allowance_only(self):
        s = stock.BoxStock(0, 0, 0, 0, 0, 0.1)
        self.assertAlmostEqual(s.bounds(self.MODEL).z_max, 12.1)

    def test_negative_allowance_refused(self):
        with self.assertRaises(ValueError):
            stock.BoxStock(z_pos_mm=-0.1).validate()

    def test_turned_about_z(self):
        s = stock.BoxStock(1, 2, 3, 4, 5, 6)
        # 90°: new X = old Y, new Y = -old X
        self.assertEqual(s.turned_about_z(90), stock.BoxStock(3, 4, 2, 1, 5, 6))
        self.assertEqual(s.turned_about_z(180), stock.BoxStock(2, 1, 4, 3, 5, 6))
        self.assertEqual(s.turned_about_z(-90), stock.BoxStock(4, 3, 1, 2, 5, 6))
        self.assertEqual(s.turned_about_z(270), s.turned_about_z(-90))
        self.assertEqual(s.turned_about_z(360), s)
        self.assertEqual(s.turned_about_z(90).turned_about_z(-90), s)
        self.assertIsNone(s.turned_about_z(12.5))


class TestFrame(unittest.TestCase):
    def assertVector(self, actual, expected, msg=None):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=12, msg=msg)

    def assertRightHanded(self, axes):
        x, y, z = axes
        self.assertVector(frame._cross(x, y), z)

    def test_top_face_keeps_the_part_axes(self):
        axes = frame.axes_for_normal((0, 0, 1))
        self.assertEqual(axes, ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))

    def test_bottom_face_turns_the_part_over_x(self):
        axes = frame.axes_for_normal((0, 0, -1))
        self.assertEqual(axes, ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)))

    def test_side_faces_keep_up_up(self):
        for normal, x in (
            ((0, -1, 0), (1, 0, 0)),  # front: X to the right
            ((1, 0, 0), (0, 1, 0)),  # right side
            ((-1, 0, 0), (0, -1, 0)),  # left side
            ((0, 1, 0), (-1, 0, 0)),  # back
        ):
            axes = frame.axes_for_normal(normal)
            self.assertVector(axes[0], x)
            self.assertVector(axes[1], (0, 0, 1))
            self.assertRightHanded(axes)

    def test_slanted_face(self):
        axes = frame.axes_for_normal((0, -1, 1))
        self.assertRightHanded(axes)
        self.assertVector(axes[0], (1, 0, 0))

    def test_zero_in_the_middle_on_the_face(self):
        # part 40 x 20 x 12 with its corner at the origin, top face at z = 12
        axes = frame.axes_for_normal((0, 0, 1))
        f = frame.centered_on_face(axes, (0, 40), (0, 20), 12)
        self.assertVector(f.origin, (20, 10, 12))
        self.assertVector(f.to_frame((40, 20, 12)), (20, 10, 0))
        self.assertVector(f.to_part((0, 0, -3)), (20, 10, 9))

    def test_zero_on_a_side_face(self):
        # front face (y = 0) of the same part: X along the part's X, Y up
        axes = frame.axes_for_normal((0, -1, 0))
        # extents of the part along the new axes: x 0..40, y (= part z) 0..12;
        # the face lies at distance 0 along the new z (= -part y)
        f = frame.centered_on_face(axes, (0, 40), (0, 12), 0)
        self.assertVector(f.origin, (20, 0, 6))
        self.assertVector(f.to_frame((20, 20, 6)), (0, 0, -20), "the back is 20 mm deep")

    def test_rotated_about_z(self):
        f = frame.centered_on_face(frame.axes_for_normal((0, 0, 1)), (0, 40), (0, 20), 12)
        quarter = frame.rotated_about_z(f, 90)
        # counter-clockwise seen from the tool: the new X is the old Y, exactly
        self.assertEqual(quarter.x_axis, (0.0, 1.0, 0.0))
        self.assertEqual(quarter.y_axis, (-1.0, 0.0, 0.0))
        self.assertEqual(quarter.z_axis, (0.0, 0.0, 1.0))
        self.assertEqual(quarter.origin, f.origin, "turned about X0 Y0")
        self.assertVector(quarter.to_frame((40, 20, 12)), (10, -20, 0))
        self.assertEqual(frame.rotation_about_z(quarter), 90.0)
        half = frame.rotated_about_z(quarter, 90)
        self.assertEqual(half.x_axis, (-1.0, 0.0, 0.0))
        self.assertEqual(frame.rotation_about_z(half), 180.0)
        self.assertEqual(frame.rotated_about_z(f, 180), half)
        self.assertEqual(frame.rotated_about_z(f, -90).x_axis, (0.0, -1.0, 0.0))
        self.assertEqual(frame.rotation_about_z(frame.rotated_about_z(f, 270)), -90.0)
        self.assertEqual(frame.rotated_about_z(f, 360), f)
        slanted = frame.rotated_about_z(f, 30)
        self.assertRightHanded((slanted.x_axis, slanted.y_axis, slanted.z_axis))
        self.assertAlmostEqual(frame.rotation_about_z(slanted), 30.0)
        self.assertAlmostEqual(frame.rotation_about_z(frame.rotated_about_z(slanted, -45.5)), -15.5)

    def test_rotated_on_a_side_face(self):
        f = frame.centered_on_face(frame.axes_for_normal((0, -1, 0)), (0, 40), (0, 12), 0)
        self.assertEqual(frame.rotation_about_z(f), 0.0)
        quarter = frame.rotated_about_z(f, 90)
        self.assertEqual(quarter.z_axis, (0.0, -1.0, 0.0), "the tool axis stays")
        self.assertEqual(quarter.x_axis, (0.0, 0.0, 1.0), "X up, the old Y")
        self.assertRightHanded((quarter.x_axis, quarter.y_axis, quarter.z_axis))
        self.assertEqual(frame.rotation_about_z(quarter), 90.0)

    def test_axis_names(self):
        self.assertEqual(frame.axis_name((0, 0, 2)), "Z+")
        self.assertEqual(frame.axis_name((0, -1, 0)), "Y−")
        self.assertEqual(frame.axis_name((0, -1, 1)), "(0.000, -0.707, 0.707)")


class TestOperations(unittest.TestCase):
    def test_contour_depth_is_below_start_z(self):
        operations.Contour(-3.0).validate()
        for bad in (0.001, 2.0, -1001.0):
            with self.assertRaises(ValueError, msg=bad):
                operations.Contour(bad).validate()
        # above the sketch plane (the zero point): from Start Z down to a Z-Depth above or below it
        operations.Contour(2.0, start_z_mm=10.0).validate()
        operations.Contour(-3.0, start_z_mm=5.0).validate()
        operations.Contour(-6.0, start_z_mm=-1.0).validate()  # material lower than the sketch
        # both the same: one pass at that height (deburring along Z0, a pass at Z+5)
        for z in (0.0, 5.0, -3.0):
            same = operations.Contour(z, start_z_mm=z, z_step_mm=2.0).validate()
            self.assertEqual(same.levels(), [z])
            self.assertEqual(len(same.cuts()), 1)
        with self.assertRaises(ValueError, msg="no allowance for a single pass"):
            operations.Contour(0.0, finish_z_mm=0.1).validate()
        for depth, start in ((5.1, 5.0), (6.0, 5.0), (-1.0, 1001.0), (-2.9, -3.0)):
            with self.assertRaises(ValueError, msg=(depth, start)):
                operations.Contour(depth, start_z_mm=start).validate()
        with self.assertRaises(ValueError, msg="the allowance is the whole depth from Start Z"):
            operations.Contour(2.0, start_z_mm=4.0, finish_z_mm=2.0).validate()

    def test_json_round_trip(self):
        contour = operations.Contour(-2.5)
        text = operations.to_json(contour)
        self.assertEqual(
            json.loads(text),
            {"approach": "none", "compensation": "off", "kind": "contour", "lead_radius_mm": None, "z_depth_mm": -2.5,
             "z_step_mm": None, "xy_width_mm": 0.0, "xy_step_mm": None, "finish_xy_mm": 0.0, "finish_z_mm": 0.0,
             "offset_xy_mm": 0.0, "order": "passes", "start_z_mm": 0.0, "arc_side": "left", "start_extend_mm": 0.0,
             "end_extend_mm": 0.0, "relative": True},
        )  # fmt: skip
        self.assertEqual(operations.from_json(text), contour)
        left = operations.Contour(-2.5, operations.LEFT)
        self.assertEqual(operations.from_json(operations.to_json(left)), left)
        # files from before compensation
        self.assertEqual(operations.from_json('{"kind": "contour", "z_depth_mm": -2.5}'), contour)
        self.assertEqual(contour.approach, operations.NONE)
        # the first contours with compensation always came in on an arc
        first = operations.from_json('{"compensation": "left", "kind": "contour", "z_depth_mm": -2.5}')
        self.assertEqual((first.approach, first.lead_radius_mm), (operations.ARC, None))
        arc = operations.Contour(-2.5, operations.OFF, operations.ARC, 4.5)
        self.assertEqual(operations.from_json(operations.to_json(arc)), arc)
        right = operations.Contour(-2.5, operations.OFF, operations.ARC, arc_side=operations.RIGHT)
        self.assertEqual(operations.from_json(operations.to_json(right)), right)
        # without compensation the XY offset only (a chamfer mill's centre beside the lines), one pass
        for offset in (0.3, -0.3):
            chamfer = operations.Contour(-0.5, offset_xy_mm=offset, arc_side=operations.RIGHT).validate()
            self.assertEqual(chamfer.xy_offsets(), [offset])
        for bad in (operations.Contour(-0.5, xy_width_mm=3.0, xy_step_mm=1.0), operations.Contour(-0.5, finish_xy_mm=0.1)):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()
        for bad in (
            operations.Contour(-2.5, "RL"),
            operations.Contour(-2.5, approach="loop"),
            operations.Contour(-2.5, approach=operations.ARC, lead_radius_mm=0.0),
            operations.Contour(-2.5, arc_side="up"),
        ):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()
        with self.assertRaises(ValueError):
            operations.from_json('{"kind": "contour", "z_depth_mm": 1}')
        with self.assertRaises(ValueError):
            operations.from_json('{"kind": "teleport"}')
        passes = operations.Contour(-10.0, operations.LEFT, z_step_mm=4.0, xy_width_mm=10.0, xy_step_mm=4.0)
        self.assertEqual(operations.from_json(operations.to_json(passes)), passes)

    def test_contour_one_pass(self):
        contour = operations.Contour(-3.0)
        self.assertEqual((contour.xy_offsets(), contour.levels(), contour.cuts()), ([0.0], [-3.0], [(0, -3.0)]))
        self.assertIsNone(contour.rough_step_mm())

    def test_contour_z_steps(self):
        # full steps, the last one what is left (the user's choice, as the TNC)
        self.assertEqual(operations.Contour(-10.0, z_step_mm=4.0).levels(), [-4.0, -8.0, -10.0])
        self.assertEqual(operations.Contour(-8.0, z_step_mm=4.0).levels(), [-4.0, -8.0])
        self.assertEqual(operations.Contour(-3.0, z_step_mm=4.0).levels(), [-3.0])
        self.assertEqual(operations.Contour(-1.0, z_step_mm=0.3).levels(), [-0.3, -0.6, -0.9, -1.0])
        # the finishing allowance on the floor: the rough levels stop above it, a last level takes it
        finish = operations.Contour(-10.0, z_step_mm=4.0, finish_z_mm=0.1)
        self.assertEqual(finish.levels(), [-4.0, -8.0, -9.9, -10.0])
        self.assertEqual(operations.Contour(-2.0, finish_z_mm=0.1).levels(), [-1.9, -2.0])
        with self.assertRaises(ValueError, msg="the allowance is the whole depth"):
            operations.Contour(-2.0, finish_z_mm=2.0).validate()
        # from Start Z: Z+10 to Z+2 by 3 mm, and from Z+5 to Z-3 with a finishing level
        self.assertEqual(operations.Contour(2.0, start_z_mm=10.0, z_step_mm=3.0).levels(), [7.0, 4.0, 2.0])
        above = operations.Contour(-3.0, start_z_mm=5.0, z_step_mm=2.0, finish_z_mm=0.1)
        self.assertEqual(above.levels(), [3.0, 1.0, -1.0, -2.9, -3.0])
        self.assertEqual(operations.Contour(1.0, start_z_mm=1.5).levels(), [1.0])

    def test_contour_xy_passes(self):
        left = operations.LEFT
        # 10 mm beside the lines, steps up to 4 mm: three equal passes from the outside in
        wide = operations.Contour(-1.0, left, xy_width_mm=10.0, xy_step_mm=4.0).validate()
        self.assertEqual(wide.xy_offsets(), [6.666667, 3.333333, 0.0])
        self.assertAlmostEqual(wide.rough_step_mm(), 10.0 / 3.0)
        self.assertEqual(operations.Contour(-1.0, left, xy_width_mm=8.0, xy_step_mm=4.0).xy_offsets(), [4.0, 0.0])
        # leave 0.1 mm for a finishing pass
        finish = operations.Contour(-1.0, left, xy_width_mm=10.0, xy_step_mm=4.0, finish_xy_mm=0.1)
        self.assertEqual(finish.xy_offsets(), [6.7, 3.4, 0.1, 0.0])
        self.assertEqual(operations.Contour(-1.0, left, finish_xy_mm=0.1).xy_offsets(), [0.1, 0.0])
        # an offset: leave material, or cut past the lines for a toleranced fit
        self.assertEqual(operations.Contour(-1.0, left, offset_xy_mm=0.2).xy_offsets(), [0.2])
        fit = operations.Contour(-1.0, left, finish_xy_mm=0.1, offset_xy_mm=-0.02).validate()
        self.assertEqual(fit.xy_offsets(), [0.08, -0.02])
        for bad in (
            operations.Contour(-1.0, xy_width_mm=5.0, xy_step_mm=2.0),  # no compensation: which side?
            operations.Contour(-1.0, finish_xy_mm=0.1),
            operations.Contour(-1.0, left, xy_width_mm=5.0),  # no step
            operations.Contour(-1.0, left, xy_width_mm=-1.0),
            operations.Contour(-1.0, left, xy_width_mm=5.0, xy_step_mm=0.0),
            operations.Contour(-1.0, z_step_mm=0.0),
            operations.Contour(-1.0, left, finish_xy_mm=-0.1),
            operations.Contour(-1.0, order="random"),
            operations.Contour(-100.0, left, z_step_mm=0.01, xy_width_mm=100.0, xy_step_mm=1.0),  # too many
        ):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()

    def test_contour_order(self):
        left = operations.LEFT
        contour = operations.Contour(-10.0, left, z_step_mm=5.0, xy_width_mm=8.0, xy_step_mm=4.0, finish_xy_mm=0.1)
        self.assertEqual(contour.xy_offsets(), [4.05, 0.1, 0.0])
        # by default each XY pass all the way down, then the next one; the finishing pass last, by the same steps
        self.assertEqual(contour.cuts(), [(0, -5.0), (0, -10.0), (1, -5.0), (1, -10.0), (2, -5.0), (2, -10.0)])
        levels = dataclasses.replace(contour, order=operations.BY_LEVEL)
        self.assertEqual(levels.cuts(), [(0, -5.0), (1, -5.0), (0, -10.0), (1, -10.0), (2, -5.0), (2, -10.0)])


    def test_drilling(self):
        drilling = operations.Drilling(-10.0)
        self.assertIs(drilling.validate(), drilling)
        self.assertEqual(operations.from_json(operations.to_json(drilling)), drilling)
        self.assertEqual(json.loads(operations.to_json(drilling))["kind"], "drilling")
        # the depth to the tip, or to the full diameter: the tip goes deeper
        self.assertEqual(drilling.final_depth_mm(2.0), -10.0)
        full = operations.Drilling(-10.0, operations.FULL_DIAMETER)
        self.assertEqual(full.final_depth_mm(2.0), -12.0)
        # by default (the user's) a peck of 1 mm and chip breaking every 4 mm
        self.assertEqual((drilling.peck_mm, drilling.chip_break_mm), (1.0, 4.0))
        self.assertTrue(drilling.pecks(0.0))
        # one plunge, or pecks shorter than the hole (from the deepened start)
        self.assertFalse(operations.Drilling(-10.0, peck_mm=None).pecks(0.0))
        self.assertEqual(operations.from_json(operations.to_json(operations.Drilling(-10.0, peck_mm=None))).peck_mm, None)
        self.assertTrue(operations.Drilling(-10.0, peck_mm=4.0).pecks(0.0))
        self.assertFalse(operations.Drilling(-10.0, peck_mm=10.0).pecks(0.0))
        self.assertTrue(operations.Drilling(-10.0, operations.FULL_DIAMETER, peck_mm=10.0).pecks(2.0))
        self.assertFalse(operations.Drilling(-10.0, peck_mm=6.0, start_mm=4.0).pecks(0.0))
        every = operations.Drilling(-20.0, operations.FULL_DIAMETER, 5.0, 0.5, 2.0, 0.5, 1.0, 3.0, 0.3, 0.25, 4.0)
        self.assertEqual(operations.from_json(operations.to_json(every.validate())), every)
        for bad in (
            operations.Drilling(0.0),
            operations.Drilling(2.0),
            operations.Drilling(-1001.0),
            operations.Drilling(-10.0, "middle"),
            operations.Drilling(-10.0, peck_mm=0.0),
            operations.Drilling(-10.0, decrement_mm=-1.0),
            operations.Drilling(-10.0, chip_break_mm=2.0, chip_retract_mm=0.0),
            operations.Drilling(-10.0, dwell_s=-1.0),
            operations.Drilling(-10.0, start_mm=10.0),
            operations.Drilling(-10.0, peck_mm=2.0, min_peck_mm=3.0),
        ):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()

    def test_drilling_from_the_model(self):
        """No depth: each hole as deep as the model has it, its full
        diameter to the end of its cylinder, 1 mm out of a through hole."""
        drilling = operations.Drilling(None).validate()
        self.assertEqual(operations.from_json(operations.to_json(drilling)), drilling)
        blind, through = operations.HoleDepth(-12.0, False), operations.HoleDepth(-20.0, True)
        self.assertEqual(drilling.final_depth_mm(2.0, blind), -14.0)
        self.assertEqual(drilling.final_depth_mm(2.0, through), -23.0)
        self.assertEqual(operations.Drilling(None, through_mm=0.5).final_depth_mm(0.0, through), -20.5)
        self.assertTrue(drilling.pecks(2.0, blind))
        self.assertFalse(operations.Drilling(None, peck_mm=None).pecks(2.0, blind))
        with self.assertRaises(ValueError):
            drilling.final_depth_mm(2.0)  # a sketch's circles have no depth of their own
        # the user's depth is the same for every hole, from its top
        self.assertEqual(operations.Drilling(-5.0).final_depth_mm(2.0, through), -5.0)
        drilling.check(2.0, blind)
        with self.assertRaises(ValueError):
            operations.Drilling(None, start_mm=14.0).check(2.0, blind)
        with self.assertRaises(ValueError):
            operations.Drilling(None, through_mm=-1.0).validate()
        # files from before the model's holes have no through_mm
        old = json.loads(operations.to_json(operations.Drilling(-8.0)))
        del old["through_mm"]
        self.assertEqual(operations.from_json(json.dumps(old)), operations.Drilling(-8.0))

    def test_adaptive(self):
        adaptive = operations.Adaptive(-1.5)
        self.assertIs(adaptive.validate(), adaptive)
        self.assertEqual(operations.from_json(operations.to_json(adaptive)), adaptive)
        self.assertEqual(json.loads(operations.to_json(adaptive))["kind"], "adaptive")
        # FreeCAD's step over and helix; 0.5 mm over cleared floor (the user's)
        self.assertEqual((adaptive.step_over_percent, adaptive.helix_angle_deg, adaptive.lift_mm), (20.0, 5.0, 0.5))
        every = operations.Adaptive(-10.0, 2.0, 12.5, 0.2, 0.1, 3.0, 0.0, False)
        self.assertEqual(operations.from_json(operations.to_json(every.validate())), every)
        self.assertEqual(operations.Adaptive(2.0).validate().z_depth_mm, 2.0, "above the zero point too")
        for bad in (
            operations.Adaptive(-1001.0),
            operations.Adaptive(-1.0, z_step_mm=0.0),
            operations.Adaptive(-1.0, step_over_percent=0.5),
            operations.Adaptive(-1.0, step_over_percent=101.0),
            operations.Adaptive(-1.0, finish_xy_mm=-0.1),
            operations.Adaptive(-1.0, finish_z_mm=-0.1),
            operations.Adaptive(-1.0, helix_angle_deg=0.0),
            operations.Adaptive(-1.0, helix_angle_deg=90.0),
            operations.Adaptive(-1.0, lift_mm=-1.0),
        ):
            with self.assertRaises(ValueError, msg=bad):
                bad.validate()

    def test_adaptive_levels(self):
        """Full Z steps from the top of the stock, a level on every floor
        (the user's choice), Z-Depth; none at the top of the stock."""
        adaptive = operations.Adaptive(-2.0, z_step_mm=1.5)
        self.assertEqual(adaptive.levels(1.0, [0.0, -2.0, -5.0]), [0.0, -0.5, -2.0])
        self.assertEqual(operations.Adaptive(-2.0).levels(1.0, [0.0]), [0.0, -2.0], "no steps: floors and Z-Depth")
        # the allowance in Z stays on the floors and above Z-Depth (beside the part too)
        self.assertEqual(operations.Adaptive(-2.0, finish_z_mm=0.2).levels(1.0, [0.0, -2.0]), [0.2, -1.8])
        self.assertEqual(operations.Adaptive(-3.0, 2.0, finish_z_mm=0.2).levels(1.0, [0.0, -2.0]), [0.2, -1.0, -1.8, -2.8])
        self.assertEqual(operations.Adaptive(-1.5, finish_z_mm=0.1).bottom_mm(), -1.4)
        self.assertEqual(operations.Adaptive(-2.0, z_step_mm=1.0).levels(0.0, [0.0]), [-1.0, -2.0])
        self.assertEqual(operations.Adaptive(1.0).levels(1.0), [])
        self.assertEqual(operations.Adaptive(-1.0, z_step_mm=0.3).levels(0.0), [-0.3, -0.6, -0.9, -1.0])

    def test_adaptive_full_levels(self):
        """The whole area only on the Z steps and Z-Depth; on a floor's own
        level only around it (the user: into a counterbore 6 deep, not all
        round the part again, the rest on the next Z step)."""
        # the user's plate: Start Z -0.1, Z step 8, floors of steps, counterbores and pockets
        plate = operations.Adaptive(-16.0, z_step_mm=8.0, finish_z_mm=0.1, start_z_mm=-0.1).validate()
        floors = [0.0, -3.5, -5.5, -10.0]
        self.assertEqual(plate.levels(1.0, floors), [-3.4, -5.4, -8.1, -9.9, -15.9])
        self.assertEqual(plate.full_levels(1.0), [-8.1, -15.9])
        self.assertEqual(operations.Adaptive(-2.0, z_step_mm=1.5).full_levels(1.0), [-0.5, -2.0])
        self.assertEqual(operations.Adaptive(-5.0).full_levels(1.0), [-5.0], "no steps: Z-Depth at once")
        self.assertEqual(operations.Adaptive(-2.0, finish_z_mm=0.2).full_levels(1.0), [-1.8])
        self.assertEqual(operations.Adaptive(1.0).full_levels(1.0), [])
        for adaptive in (plate, operations.Adaptive(-3.0, 2.0, finish_z_mm=0.2), operations.Adaptive(-2.0, z_step_mm=1.0, start_z_mm=5.0)):  # fmt: skip
            self.assertTrue(set(adaptive.full_levels(1.0)) <= set(adaptive.levels(1.0, floors)), adaptive)

    def test_adaptive_start_z(self):
        """Start Z: the top of the range of the levels, not a level itself
        (the user's); a floor above it is left as it is."""
        # the plate's top at Z0, the stock 1 mm over it, a step at Z-3.5
        floors = [0.0, -3.5]
        top_only = operations.Adaptive(0.0, start_z_mm=0.0).validate()
        self.assertEqual(top_only.levels(1.0, floors), [0.0], "Start Z = Z-Depth on the top face: the stock over it")
        under = operations.Adaptive(-3.5, z_step_mm=1.0, start_z_mm=-0.1).validate()
        self.assertEqual(under.levels(1.0, floors), [-1.1, -2.1, -3.1, -3.5], "the top face left as it is")
        self.assertEqual(operations.Adaptive(-3.5, start_z_mm=-0.1).levels(1.0, floors), [-3.5], "no steps")
        self.assertEqual(operations.Adaptive(-5.0, start_z_mm=-3.5).levels(1.0, floors), [-3.5, -5.0], "a floor on Start Z")
        self.assertEqual(operations.Adaptive(0.5, start_z_mm=0.5).levels(1.0, floors), [0.5], "above the top face")
        self.assertEqual(operations.Adaptive(1.0, start_z_mm=1.0).levels(1.0, floors), [], "the top of the stock cuts nothing")
        self.assertEqual(operations.Adaptive(-2.0, z_step_mm=1.0, start_z_mm=5.0).levels(1.0), [0.0, -1.0, -2.0], "steps from above the stock")  # fmt: skip
        self.assertEqual(operations.Adaptive(-2.0, z_step_mm=1.0).levels(1.0), operations.Adaptive(-2.0, z_step_mm=1.0, start_z_mm=1.0).levels(1.0))  # fmt: skip
        self.assertEqual(operations.Adaptive(-1.0, start_z_mm=0.0).top_mm(1.0), 0.0)
        self.assertEqual(operations.Adaptive(-1.0).top_mm(1.0), 1.0, "None: the top of the stock")
        with self.assertRaises(ValueError):
            operations.Adaptive(0.0, start_z_mm=-0.1).validate()  # Z-Depth above Start Z
        with self.assertRaises(ValueError):
            operations.Adaptive(-1.0, start_z_mm=1001.0).validate()
        kept = operations.Adaptive(-3.5, start_z_mm=-0.1)
        self.assertEqual(operations.from_json(operations.to_json(kept)), kept)
        # files from before Start Z have none: the top of the stock
        old = json.loads(operations.to_json(operations.Adaptive(-2.0)))
        del old["start_z_mm"]
        self.assertEqual(operations.from_json(json.dumps(old)), operations.Adaptive(-2.0))


def _xyz(move):
    return (move.kind, round(move.x, 6), round(move.y, 6), round(move.z, 6), move.feed_mm_min)


class TestClearing(unittest.TestCase):
    def test_half_turns(self):
        # radius 3 at 5°: half a turn goes pi * 3 * tan(5°) = 0.8246 down; the last arc shorter
        arcs = clearing.half_turns(2.0, 3.0, 5.0)
        half = 3.0 * 3.141592653589793 * 0.08748866352592401
        self.assertEqual([sweep for sweep, _down in arcs[:2]], [180.0, 180.0])
        self.assertAlmostEqual(arcs[2][0], 180.0 * (2.0 - 2 * half) / half)
        self.assertAlmostEqual(sum(down for _sweep, down in arcs), 2.0)

    def test_moves_in_from_the_side(self):
        """Over the start at Z+20, to 2 mm above the stock, down with the Z
        feed; over cleared floor 0.5 mm above the level, over uncut material
        up to the safe height and back fast to 2 mm above where it cut
        before; up to the safe height after each area."""
        piece = clearing.Piece(
            (0.0, -1.0), 1.0, None, (-10.0, 0.0),
            ((clearing.CUT, ((-5.0, 0.0), (5.0, 0.0))), (clearing.LINK, ((5.0, 2.0),)),
             (clearing.CUT, ((-5.0, 2.0),)), (clearing.UP, ((0.0, 5.0),)), (clearing.CUT, ((0.0, 6.0),))),
        )  # fmt: skip
        moves = clearing.moves([piece], safe_z=3.0, lift_mm=0.5, helix_angle_deg=5.0, feed_z_mm_min=100, feed_xy_mm_min=200)  # fmt: skip
        R, L = nc.RAPID, nc.LINE
        level_0 = [
            (R, -10, 0, 20, None), (R, -10, 0, 3, None), (L, -10, 0, 0, 100),
            (L, -5, 0, 0, 200), (L, 5, 0, 0, 200),
            (R, 5, 0, 0.5, None), (R, 5, 2, 0.5, None), (L, 5, 2, 0, 100), (L, -5, 2, 0, 200),
            (R, -5, 2, 3, None), (R, 0, 5, 3, None), (L, 0, 5, 0, 100), (L, 0, 6, 0, 200),
            (R, 0, 6, 3, None),
        ]  # fmt: skip
        level_1 = [
            (R, -10, 0, 3, None), (R, -10, 0, 2, None), (L, -10, 0, -1, 100),
            (L, -5, 0, -1, 200), (L, 5, 0, -1, 200),
            (R, 5, 0, -0.5, None), (R, 5, 2, -0.5, None), (L, 5, 2, -1, 100), (L, -5, 2, -1, 200),
            (R, -5, 2, 3, None), (R, 0, 5, 3, None), (R, 0, 5, 2, None), (L, 0, 5, -1, 100), (L, 0, 6, -1, 200),
            (R, 0, 6, 3, None),
        ]  # fmt: skip
        self.assertEqual([_xyz(m) for m in moves], level_0 + level_1)

    def test_moves_on_a_helix(self):
        """Into a closed area on a helix in half turns from where its
        material starts, clockwise, with the Z feed, then a whole turn on
        the level with the XY feed."""
        piece = clearing.Piece((-2.0,), 0.0, (0.0, 0.0), (3.01, 0.0), ((clearing.CUT, ((1.0, 1.0),)),))
        self.assertAlmostEqual(clearing.helix_radius(piece), 3.0)
        moves = clearing.moves([piece], 3.0, 0.5, 5.0, 100, 200)
        self.assertEqual([_xyz(m) for m in moves[:3]], [(nc.RAPID, 3, 0, 20, None), (nc.RAPID, 3, 0, 2, None), (nc.LINE, 3, 0, 0, 100)])  # fmt: skip
        arcs = [m for m in moves if m.kind == nc.ARC]
        self.assertEqual(len(arcs), 5, "3 down (the last shorter), a whole turn on the level")
        self.assertTrue(all(m.clockwise and m.center == (0.0, 0.0) for m in arcs))
        self.assertEqual([m.feed_mm_min for m in arcs], [100, 100, 100, 200, 200])
        self.assertAlmostEqual(arcs[0].x, -3.0)
        self.assertAlmostEqual(arcs[2].z, -2.0)
        self.assertAlmostEqual(arcs[4].x, arcs[2].x)
        self.assertAlmostEqual(arcs[4].y, arcs[2].y)
        self.assertEqual(_xyz(moves[-2]), (nc.LINE, 1, 1, -2, 200))
        self.assertEqual(_xyz(moves[-1]), (nc.RAPID, 1, 1, 3, None))


class TestThreads(unittest.TestCase):
    def test_suggested_major(self):
        cases = (
            (2.5, 0.5, 3.0),  # the hole drilled for M3
            (3.0, 0.5, 3.0),  # a circle drawn at M3 (M3.5 has P0.6)
            (6.8, 1.25, 8.0),
            (10.2, 1.75, 12.0),  # drilled 10.2 for 10.25
            (8.8, 1.25, 10.0),  # M10x1.25
            (11.8, 25.4 / 19, 13.157),  # G1/4
            (4.2, 0.7, 4.9),  # no standard thread: the hole plus the pitch
        )
        for hole, pitch, major in cases:
            self.assertAlmostEqual(threads.suggested_major(hole, pitch), major, msg=(hole, pitch))

    def test_names(self):
        self.assertEqual(threads.name(3.0, 0.5), "M3")
        self.assertEqual(threads.name(10.0, 1.0), "M10x1")
        self.assertEqual(threads.name(13.157, 1.337), "G1/4")
        self.assertEqual(threads.name(3.2, 0.5), "Ø3.2 P0.5")

    def test_turns(self):
        self.assertEqual(threads.turns(operations.ThreadMilling(3.0, -6.5), 0.5), (26, 0.0))
        full, rest = threads.turns(operations.ThreadMilling(3.0, -6.6), 0.5)
        self.assertEqual(full, 26)
        self.assertAlmostEqual(rest, 0.1)

    def test_tool_centre(self):
        """Without compensation the helix runs where the tool centre goes."""
        thread = operations.ThreadMilling(3.0, -1.0, passes=1)
        moves = threads.moves(thread, [threads.ThreadHole(5.0, 0.0, -2.0)], 0.5, 0.3, 225, 300)
        arcs = [m for m in moves if m.kind == nc.ARC]
        self.assertEqual(len(arcs), 4)
        self.assertTrue(all(m.compensation is None and m.clockwise and m.center == (5.0, 0.0) for m in arcs))
        self.assertAlmostEqual(arcs[0].x, 4.7)
        self.assertAlmostEqual(arcs[-1].z, -3.0)
        self.assertEqual(moves[0], nc.Move(nc.RAPID, 5.0, 0.0, 20.0))
        self.assertEqual(moves[-1], nc.Move(nc.RAPID, 5.0, 0.0, 8.0), "10 above the top")

    def test_thread_milling(self):
        thread = operations.ThreadMilling(3.0, -6.5)
        self.assertEqual(thread.passes, 2, "as the shop's programs")
        self.assertEqual(operations.from_json(operations.to_json(thread)), thread)
        thread.check(2.4, 0.5)
        for broken in (
            operations.ThreadMilling(0.0, -6.5),
            operations.ThreadMilling(3.0, 0.0),
            operations.ThreadMilling(3.0, 2.0),
            operations.ThreadMilling(3.0, -6.5, passes=0),
        ):
            with self.assertRaises(ValueError, msg=broken):
                broken.validate()
        with self.assertRaises(ValueError):
            thread.check(3.0, 0.5)  # the tool as big as the thread
        with self.assertRaises(ValueError):
            thread.check(2.4, None)


class TestLeads(unittest.TestCase):
    def assertPoint(self, actual, expected):
        self.assertAlmostEqual(actual[0], expected[0], places=9)
        self.assertAlmostEqual(actual[1], expected[1], places=9)

    def test_like_the_shop(self):
        # 12 mm tool on y = 50 running +X, tool on the left (outside): arc
        # radius 6.6 (the shop's programs: 1.1 x the tool radius) around (0, 56.6),
        # 45 degrees of it on each side
        r = 6.6
        h = 6.6 * 0.5 ** 0.5
        centre, start = leads.lead_in((0, 50), (1, 0), nc.LEFT, r)
        self.assertPoint(centre, (0, 56.6))
        self.assertPoint(start, (-h, 56.6 - h))
        centre, end = leads.lead_out((0, 50), (1, 0), nc.LEFT, r)
        self.assertPoint(centre, (0, 56.6))
        self.assertPoint(end, (h, 56.6 - h))
        self.assertFalse(leads.clockwise(nc.LEFT))

    def test_default_radius(self):
        # the tool goes down 0.5 mm clear of the contour
        self.assertAlmostEqual(leads.default_radius(4.0), 4.5)

    def test_right_side(self):
        h = 2.0 * 0.5 ** 0.5
        # running -Y on x = 10, tool on the right (-X): arcs turn clockwise
        centre, start = leads.lead_in((10, 0), (0, -1), nc.RIGHT, 2.0)
        self.assertPoint(centre, (8, 0))
        self.assertPoint(start, (8 + h, h))
        centre, end = leads.lead_out((10, 0), (0, -1), nc.RIGHT, 2.0)
        self.assertPoint(end, (8 + h, -h))
        self.assertTrue(leads.clockwise(nc.RIGHT))
        with self.assertRaises(ValueError):
            leads.side_normal((1, 0), None)


if __name__ == "__main__":
    unittest.main()
