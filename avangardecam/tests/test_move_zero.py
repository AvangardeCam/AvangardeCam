# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Move 0-Point tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_move_zero   (from the add-on's folder)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import math
import unittest

from avangardecam.model import frame, move_zero, operations

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

# a setup snapped on the top of a part: the part's axes, Z0 at 12 mm
TOP = frame.Frame((0.0, 0.0, 12.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
# a setup on the front: X to the right, Y up (the part's Z), Z towards the viewer
FRONT = frame.Frame((0.0, -10.0, 6.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))


class TestModel(unittest.TestCase):
    def assertShift(self, actual, expected):
        self.assertEqual(len(actual), 3)
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=6)

    def test_moved_along_the_setups_axes(self):
        self.assertEqual(move_zero.moved(TOP, (476.5, 0.0, -1.75)).origin, (476.5, 0.0, 10.25))
        # Y of the front setup is the part's Z, its Z the part's -Y
        moved = move_zero.moved(FRONT, (5.0, 2.0, 3.0))
        self.assertEqual(moved.origin, (5.0, -13.0, 8.0))
        self.assertEqual((moved.x_axis, moved.y_axis, moved.z_axis), FRONT[1:], "the axes stay")

    def test_no_shift(self):
        self.assertTrue(move_zero.is_none((0.0, 0.0, 0.0)))
        self.assertTrue(move_zero.is_none((1e-9, -1e-9, 0.0)), "rounding noise is no shift")
        self.assertFalse(move_zero.is_none((0.0, 0.001, 0.0)))
        self.assertEqual(move_zero.moved(TOP, move_zero.NONE), TOP)

    def test_wall_square_to_an_axis(self):
        # the right-hand end of a part 953 long, whichever way its normal points
        for normal in ((1.0, 0.0, 0.0), (-2.0, 0.0, 0.0)):
            self.assertEqual(move_zero.to_plane(TOP, (476.5, 33.0, 5.0), normal), (476.5, 0.0, 0.0))
        self.assertEqual(move_zero.to_plane(TOP, (-476.5, 0.0, 0.0), (1.0, 0.0, 0.0)), (-476.5, 0.0, 0.0))
        # the bottom of a pocket: down along Z only
        self.assertEqual(move_zero.to_plane(TOP, (3.0, 4.0, 8.0), (0.0, 0.0, 1.0)), (0.0, 0.0, -4.0))

    def test_wall_in_a_turned_setup(self):
        # the part's top (Z 12) is 6 mm up the front setup's Y
        self.assertEqual(move_zero.to_plane(FRONT, (0.0, 0.0, 12.0), (0.0, 0.0, 1.0)), (0.0, 6.0, 0.0))
        # the part's back (Y +10) is 20 mm behind the front: down its Z
        self.assertEqual(move_zero.to_plane(FRONT, (7.0, 10.0, 0.0), (0.0, 1.0, 0.0)), (0.0, 0.0, -20.0))

    def test_oblique_wall(self):
        # a wall at 45° through X 10: the shortest way is half along X, half along Y
        s = math.sqrt(0.5)
        shift = move_zero.to_plane(TOP, (10.0, 0.0, 0.0), (s, s, 0.0))
        self.assertShift(shift, (5.0, 5.0, 0.0))
        on_wall = move_zero.moved(TOP, shift)
        self.assertShift(move_zero.to_plane(on_wall, (10.0, 0.0, 0.0), (s, s, 0.0)), (0.0, 0.0, 0.0))

    def test_a_wall_already_through_the_zero_point(self):
        self.assertEqual(move_zero.to_plane(TOP, (50.0, 50.0, 12.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))

    def test_two_walls_make_a_corner(self):
        first = move_zero.to_plane(TOP, (-20.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        second = move_zero.to_plane(move_zero.moved(TOP, first), (0.0, -10.0, 0.0), (0.0, 1.0, 0.0))
        self.assertEqual(move_zero.added(first, second), (-20.0, -10.0, 0.0))

    def test_refused(self):
        with self.assertRaisesRegex(ValueError, "along Y"):
            move_zero.validate((0.0, float("nan"), 0.0))
        with self.assertRaisesRegex(ValueError, "along Z"):
            move_zero.validate((0.0, 0.0, "1"))
        with self.assertRaisesRegex(ValueError, "at most"):
            move_zero.moved(TOP, (move_zero.MAX_SHIFT_MM + 1.0, 0.0, 0.0))
        with self.assertRaises(ValueError):
            move_zero.validate((1.0, 2.0))
        with self.assertRaises(ValueError):
            move_zero.to_plane(TOP, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        move_zero.validate((move_zero.MAX_SHIFT_MM, -move_zero.MAX_SHIFT_MM, 0))


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestEngine(unittest.TestCase):
    """A block 40 x 20 x 12 with its bottom in Z0; the first setup has its
    zero point on the top, in the middle."""

    def setUp(self):
        import Part

        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry
        from avangardecam.engine import move_zero as engine

        self.cam, self.geometry, self.engine = cam, geometry, engine
        self.doc = FreeCAD.newDocument("AvangardeCamMoveZero")
        self.part = self.doc.addObject("Part::Feature", "Block")
        self.part.Shape = Part.makeBox(40, 20, 12, FreeCAD.Vector(-20, -10, 0))
        self.doc.recompute()
        self.job = cam.ensure_job(self.doc, [self.part])

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def face(self, normal):
        """The name of the block's face that looks along normal."""
        wanted = FreeCAD.Vector(*normal)
        shape = self.part.Shape
        for i, face in enumerate(shape.Faces, start=1):
            if self.geometry.outward_normal(shape, face).getAngle(wanted) < 1e-9:
                return "Face{}".format(i)
        raise AssertionError("no face along {}".format(normal))

    def assertPoint(self, actual, expected, msg=None):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=6, msg=msg)

    def stock(self):
        return tuple(self.cam.stock_bounds(self.job))

    def test_move_by_a_shift(self):
        self.assertPoint(self.cam.zero(self.job).Base, (0, 0, 12))
        self.assertPoint(self.stock(), (-21, -11, -12, 21, 11, 1))
        place = self.engine.move(self.job, (20.0, -10.0, -2.0))
        self.assertPoint(place.Base, (20, -10, 10))
        self.assertPoint(self.cam.zero(self.job).Base, (20, -10, 10))
        self.assertEqual(self.cam.zero_rotation(self.job), 0.0, "the axes stay")
        # the same block, seen from the new zero point
        self.assertPoint(self.stock(), (-41, -1, -10, 1, 21, 3))

    def test_no_shift_touches_nothing(self):
        before = self.cam.zero(self.job)
        self.doc.recompute()
        self.engine.move(self.job, (0.0, 0.0, 0.0))
        self.assertTrue(self.cam.zero(self.job).isSame(before, 1e-12))
        self.assertFalse([o.Name for o in self.doc.Objects if "Touched" in o.State])

    def test_refused_shift_changes_nothing(self):
        before = self.cam.zero(self.job)
        with self.assertRaises(ValueError):
            self.engine.move(self.job, (20000.0, 0.0, 0.0))
        self.assertTrue(self.cam.zero(self.job).isSame(before, 1e-12))

    def test_walls(self):
        self.assertEqual(self.engine.wall_shift(self.job, self.part, self.face((1, 0, 0))), (20.0, 0.0, 0.0))
        self.assertEqual(self.engine.wall_shift(self.job, self.part, self.face((-1, 0, 0))), (-20.0, 0.0, 0.0))
        self.assertEqual(self.engine.wall_shift(self.job, self.part, self.face((0, 1, 0))), (0.0, 10.0, 0.0))
        self.assertEqual(self.engine.wall_shift(self.job, self.part, self.face((0, 0, -1))), (0.0, 0.0, -12.0))
        self.assertEqual(self.engine.wall_shift(self.job, self.part, self.face((0, 0, 1))), (0.0, 0.0, 0.0))

    def test_second_wall_keeps_the_first(self):
        left = self.engine.wall_shift(self.job, self.part, self.face((-1, 0, 0)))
        corner = self.engine.wall_shift(self.job, self.part, self.face((0, -1, 0)), left)
        self.assertEqual(corner, (-20.0, -10.0, 0.0))
        self.assertEqual(self.engine.wall_shift(self.job, self.part, self.face((-1, 0, 0)), corner), corner, "again: the same")
        # a typed shift along the wall stays, the one across it is replaced
        self.assertEqual(
            self.engine.wall_shift(self.job, self.part, self.face((1, 0, 0)), (3.0, 4.0, 5.0)), (20.0, 4.0, 5.0)
        )
        self.engine.move(self.job, corner)
        self.assertPoint(self.cam.zero(self.job).Base, (-20, -10, 12))

    def test_wall_in_a_turned_setup(self):
        """Turned 90° about Z the setup's X is the part's Y."""
        self.cam.rotate_zero(self.job, 90.0)
        shift = self.engine.wall_shift(self.job, self.part, self.face((0, 1, 0)))
        self.assertEqual(shift, (10.0, 0.0, 0.0))
        self.engine.move(self.job, shift)
        self.assertPoint(self.cam.zero(self.job).Base, (0, 10, 12))
        self.assertEqual(self.cam.zero_rotation(self.job), 90.0)

    def test_wall_from_a_setup_on_the_side(self):
        """A setup on the front (Z out of it): the part's top is up its Y."""
        front = self.geometry.zero_on_face([self.part], self.part, self.face((0, -1, 0)))
        job = self.cam.new_setup(self.doc, front)
        shift = self.engine.wall_shift(job, self.part, self.face((0, 0, 1)))
        self.assertEqual(shift, (0.0, 6.0, 0.0))
        self.engine.move(job, shift)
        self.assertPoint(self.cam.zero(job).Base, (0, -10, 12))
        self.assertPoint(self.cam.zero(self.job).Base, (0, 0, 12), "the other setup stays")

    def test_not_a_wall(self):
        import Part

        from avangardecam.engine import ProjectError

        rod = self.doc.addObject("Part::Feature", "Rod")
        rod.Shape = Part.makeCylinder(5, 20)
        self.doc.recompute()
        round_face = next(
            "Face{}".format(i) for i, f in enumerate(rod.Shape.Faces, start=1) if f.findPlane() is None
        )
        with self.assertRaisesRegex(ProjectError, "not flat"):
            self.engine.wall_shift(self.job, rod, round_face)
        with self.assertRaises(ProjectError):
            self.engine.wall_shift(self.job, self.part, "Edge1")

    def test_target(self):
        place = self.engine.target(self.job, (1.0, 2.0, 3.0))
        self.assertPoint(place.Base, (1, 2, 15))
        self.assertTrue(place.Rotation.isSame(self.cam.zero(self.job).Rotation, 1e-12))
        self.assertPoint(self.cam.zero(self.job).Base, (0, 0, 12), "only asked")

    def test_operations_stay(self):
        """An operation counts from the zero point it was made on; the next
        one counts from where the zero point was left (tests/test_op_zero)."""
        from avangardecam.engine import op_zero
        from avangardecam.model import library
        from avangardecam.tests.test_model import LIBRARY

        variant = next(e for e in library.load(LIBRARY) if e.number == 21 and e.workpiece_material == "RVS")
        tc = self.cam.add_tool(self.job, variant)
        sketch = self.geometry.extract_boundary(self.doc, [self.part], self.part, self.face((0, 0, 1)))
        first = self.cam.add_contour(self.job, sketch, operations.Contour(-1.0), tc)
        self.doc.recompute()

        def cutting(op):
            moves = [m for m in self.cam.nc_moves(op) if m.kind != "rapid"]
            xs = [m.x for m in moves if m.x is not None]
            ys = [m.y for m in moves if m.y is not None]
            return min(xs), max(xs), min(ys), max(ys), min(m.z for m in moves)

        before = cutting(first)
        # onto the left wall, the front wall and 2 mm below the top
        shift = self.engine.wall_shift(self.job, self.part, self.face((-1, 0, 0)))
        shift = self.engine.wall_shift(self.job, self.part, self.face((0, -1, 0)), shift)
        self.engine.move(self.job, (shift[0], shift[1], -2.0))
        self.doc.recompute()
        self.assertEqual(cutting(first), before, "it stays as it is")
        self.assertPoint(op_zero.zero_of(first).Base, (0, 0, 12))
        second = self.cam.add_contour(self.job, sketch, operations.Contour(-1.0), tc)
        self.doc.recompute()
        after = cutting(second)
        self.assertPoint(after[:4], (before[0] + 20, before[1] + 20, before[2] + 10, before[3] + 10))
        self.assertAlmostEqual(after[4], 1.0, msg="1 mm below the lines, which are 2 mm above the zero point now")
        program = self.cam.nc_program(self.doc, "MOVED", zeros=True)
        self.assertPoint(tuple(program.setups[0].stock), (-21, -11, -12, 21, 11, 1), "the stock from the preset")
        self.assertEqual(program.setups[0].operations[1].zero.origin, (-20.0, -10.0, -2.0))

    def test_move_and_turn(self):
        """5 axes: shifted along its axes, then turned about them."""
        place = self.engine.move(self.job, (20.0, 0.0, 0.0), (0.0, 90.0, 0.0))
        self.assertPoint(place.Base, (20, 0, 12))
        self.assertPoint(self.geometry.tool_axis(self.cam.zero(self.job)), (1, 0, 0))
        with self.assertRaises(ValueError):
            self.engine.move(self.job, (0.0, 0.0, 0.0), (0.0, 720.0, 0.0))
        # a turn alone: about its own Z, where it is
        self.engine.move(self.job, (0.0, 0.0, 0.0), (0.0, 0.0, 90.0))
        self.assertPoint(self.cam.zero(self.job).Base, (20, 0, 12))
        self.assertPoint(self.geometry.tool_axis(self.cam.zero(self.job)), (1, 0, 0))

    def test_wall_turn(self):
        self.assertEqual(self.engine.wall_turn(self.job, self.part, self.face((1, 0, 0))), (0.0, 90.0, 0.0))
        self.assertEqual(self.engine.wall_turn(self.job, self.part, self.face((0, -1, 0))), (90.0, 0.0, 0.0))
        self.assertEqual(self.engine.wall_turn(self.job, self.part, self.face((0, 0, 1))), (0.0, 0.0, 0.0))
        self.assertEqual(self.engine.wall_turn(self.job, self.part, self.face((0, 0, -1))), (180.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
