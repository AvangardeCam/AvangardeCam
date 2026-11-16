# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Zero points of operations (experimental). The model tests are plain Python:

    python3 -m unittest avangardecam.tests.test_op_zero   (from the add-on's folder)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import datetime
import math
import unittest

from avangardecam.model import frame, nc, op_zero, operations

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

TOP = frame.Frame((0.0, 0.0, 12.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
TOOL = nc.Tool(21, "End mill 8", 8.0, 6000.0, 300.0, 900.0)


def axes(f):
    return (f.x_axis, f.y_axis, f.z_axis)


class TestModel(unittest.TestCase):
    def assertVectors(self, actual, expected):
        for a, b in zip(actual, expected):
            for c, d in zip(a, b):
                self.assertAlmostEqual(c, d, places=9)

    def test_turn_about_one_axis(self):
        # about Y by 90°: the tool axis lies along X, X looks down
        self.assertEqual(op_zero.axes_of((0.0, 90.0, 0.0)), ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)))
        self.assertEqual(op_zero.axes_of((0.0, -90.0, 0.0)), ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)))
        self.assertEqual(op_zero.axes_of((-90.0, 0.0, 0.0)), ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
        self.assertEqual(op_zero.axes_of((0.0, 0.0, 90.0)), ((0.0, 1.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
        self.assertEqual(op_zero.axes_of(op_zero.NO_TURN), ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)))

    def test_turn_order_is_x_then_y_then_z_about_fixed_axes(self):
        """As a control's spatial angles: A, B, C about the fixed X, Y, Z."""
        # about X by 90° (Y up to Z), then about the fixed Z by 90°
        x, y, z = op_zero.axes_of((90.0, 0.0, 90.0))
        self.assertEqual((x, y, z), ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)))

    def test_turn_and_back(self):
        for turn in ((10.0, 20.0, 30.0), (-170.0, 45.0, 120.0), (33.0, 0.0, 0.0), (0.0, 90.0, 30.0), (0.0, -90.0, -45.0)):
            self.assertEqual(op_zero.turn_of(op_zero.axes_of(turn)), turn)
        # with the tool axis level, a turn about X is the same as one about Z
        self.assertVectors(op_zero.axes_of((20.0, 90.0, 0.0)), op_zero.axes_of(op_zero.turn_of(op_zero.axes_of((20.0, 90.0, 0.0)))))
        self.assertEqual(op_zero.turn_of(op_zero.axes_of((20.0, 90.0, 0.0)))[0], 0.0)

    def test_refused_turns(self):
        with self.assertRaises(ValueError):
            op_zero.axes_of((0.0, 0.0))
        with self.assertRaises(ValueError):
            op_zero.axes_of((0.0, 400.0, 0.0))
        with self.assertRaises(ValueError):
            op_zero.turned(TOP, (0.0, float("nan"), 0.0))
        with self.assertRaises(ValueError):
            op_zero.turned(TOP, ("1", 0.0, 0.0))

    def test_turned_frame_keeps_its_origin(self):
        turned = op_zero.turned(TOP, (0.0, 90.0, 0.0))
        self.assertEqual(turned.origin, TOP.origin)
        self.assertEqual(turned.z_axis, (1.0, 0.0, 0.0))
        self.assertIs(op_zero.turned(TOP, (0.0, 360.0, 0.0)), TOP)
        # a frame on the front (X right, Y up, Z to the viewer) about its own X
        front = frame.Frame((0.0, -10.0, 6.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))
        self.assertEqual(op_zero.turned(front, (-90.0, 0.0, 0.0)).z_axis, (0.0, 0.0, 1.0))

    def test_turn_onto_a_wall(self):
        """The shortest way: onto a side wall the head swings about one axis."""
        self.assertEqual(op_zero.turn_onto(TOP, (1.0, 0.0, 0.0)), (0.0, 90.0, 0.0))
        self.assertEqual(op_zero.turn_onto(TOP, (-5.0, 0.0, 0.0)), (0.0, -90.0, 0.0))
        self.assertEqual(op_zero.turn_onto(TOP, (0.0, 1.0, 0.0)), (-90.0, 0.0, 0.0))
        self.assertEqual(op_zero.turn_onto(TOP, (0.0, -1.0, 0.0)), (90.0, 0.0, 0.0))
        self.assertEqual(op_zero.turn_onto(TOP, (0.0, 0.0, 1.0)), op_zero.NO_TURN)
        self.assertEqual(op_zero.turn_onto(TOP, (0.0, 0.0, -1.0)), (180.0, 0.0, 0.0))
        self.assertEqual(op_zero.turn_onto(TOP, (1.0, 0.0, 1.0)), (0.0, 45.0, 0.0))
        for normal in ((1.0, 1.0, 0.0), (1.0, 2.0, 3.0), (-1.0, 0.5, -2.0)):
            z = op_zero.turned(TOP, op_zero.turn_onto(TOP, normal)).z_axis
            length = sum(c * c for c in normal) ** 0.5
            for c, d in zip(z, normal):  # the angles are kept to a millionth of a degree
                self.assertAlmostEqual(c, d / length, places=7)

    def test_relative(self):
        self.assertIsNone(op_zero.relative(TOP, TOP))
        shifted = frame.Frame((476.5, 0.0, 10.25), *axes(TOP))
        seen = op_zero.relative(TOP, shifted)
        self.assertEqual(seen.origin, (476.5, 0.0, -1.75))
        self.assertTrue(op_zero.is_shift(seen) and op_zero.is_level(seen) and not op_zero.is_preset(seen))
        self.assertEqual(op_zero.shift_text(seen), "X+476.5 Y+0 Z-1.75")
        side = op_zero.turned(shifted, (0.0, 90.0, 0.0))
        seen = op_zero.relative(TOP, side)
        self.assertEqual(seen.origin, (476.5, 0.0, -1.75))
        self.assertEqual(axes(seen), ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)))
        self.assertFalse(op_zero.is_shift(seen) or op_zero.is_level(seen))
        self.assertEqual(op_zero.turn_text(seen), "A+0 B+90 C+0")
        self.assertEqual(op_zero.turn_text(None), "A+0 B+0 C+0")
        # seen from a default zero point that is itself turned: 90° about Z
        default = frame.rotated_about_z(TOP, 90.0)
        seen = op_zero.relative(default, frame.Frame((0.0, 5.0, 12.0), *axes(default)))
        self.assertEqual(seen.origin, (5.0, 0.0, 0.0))
        self.assertTrue(op_zero.is_shift(seen))


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (run through avangardecam/tests/run.py)")
class TestEngine(unittest.TestCase):
    """A block 40 x 20 x 12 with its zero point on top, in the middle."""

    def setUp(self):
        import Part

        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry
        from avangardecam.engine import move_zero
        from avangardecam.engine import op_zero as engine
        from avangardecam.model import library
        from avangardecam.tests.test_model import LIBRARY

        self.cam, self.geometry, self.engine, self.move_zero = cam, geometry, engine, move_zero
        self.doc = FreeCAD.newDocument("AvangardeCamOpZero")
        self.part = self.doc.addObject("Part::Feature", "Block")
        self.part.Shape = Part.makeBox(40, 20, 12, FreeCAD.Vector(-20, -10, 0))
        self.doc.recompute()
        self.job = cam.ensure_job(self.doc, [self.part])
        variant = next(e for e in library.load(LIBRARY) if e.number == 21 and e.workpiece_material == "RVS")
        self.tc = cam.add_tool(self.job, variant)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def face(self, normal):
        wanted = FreeCAD.Vector(*normal)
        shape = self.part.Shape
        for i, face in enumerate(shape.Faces, start=1):
            if self.geometry.outward_normal(shape, face).getAngle(wanted) < 1e-9:
                return "Face{}".format(i)
        raise AssertionError("no face along {}".format(normal))

    def contour(self, normal=(0, 0, 1), depth=-1.0):
        sketch = self.geometry.extract_boundary(self.doc, [self.part], self.part, self.face(normal))
        op = self.cam.add_contour(self.job, sketch, operations.Contour(depth), self.tc)
        self.doc.recompute()
        return op

    def cutting(self, moves):
        """(x min, x max, y min, y max, z min) of the cutting moves."""
        moves = [m for m in moves if m.kind != "rapid"]
        xs = [m.x for m in moves if m.x is not None]
        ys = [m.y for m in moves if m.y is not None]
        return min(xs), max(xs), min(ys), max(ys), min(m.z for m in moves)

    def assertPoint(self, actual, expected, msg=None):
        self.assertEqual(len(actual), len(expected), msg)
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=6, msg=msg)

    def stock(self):
        return tuple(self.cam.stock_bounds(self.job))

    def program(self):
        return self.cam.nc_program(self.doc, "ZEROS").setups[0]

    def test_a_setup_on_one_zero_point_is_as_it_was(self):
        op = self.contour()
        self.assertFalse(self.engine.parked(op))
        self.assertTrue(self.engine.at_default(self.job) and self.engine.one_zero(self.job))
        self.assertIsNone(self.engine.operation_zero(op))
        setup = self.program()
        self.assertIsNone(setup.operations[0].zero)
        # Rotate 0-Point turns the setup: the operation follows, as always
        self.cam.rotate_zero(self.job, 90.0)
        self.assertFalse(self.engine.parked(op))
        self.assertTrue(self.engine.at_default(self.job))
        self.assertFalse(
            [p for o in (self.job, op) for p in o.PropertiesList if p in ("AvangardeZero", "AvangardeDefaultZero")],
            "nothing of the zero points is added to it",
        )

    def test_operations_keep_their_zero_point(self):
        first = self.contour()
        before = self.cutting(self.cam.nc_moves(first))
        self.move_zero.move(self.job, (20.0, 10.0, -2.0))
        self.assertPoint(self.cam.zero(self.job).Base, (20, 10, 10))
        self.assertTrue(self.engine.parked(first))
        self.assertPoint(self.engine.zero_of(first).Base, (0, 0, 12))
        self.assertPoint(self.engine.default_zero(self.job).Base, (0, 0, 12), "the preset stays")
        self.assertFalse(self.engine.at_default(self.job))
        self.doc.recompute()
        self.assertEqual(self.cutting(self.cam.nc_moves(first)), before, "its path waits as it was")
        self.assertPoint(self.stock(), (-41, -21, -10, 1, 1, 3), "the same block from the new zero point")
        # a second contour counts from the new zero point: the block's corner
        second = self.contour()
        self.assertFalse(self.engine.parked(second))
        on_corner = self.cutting(self.cam.nc_moves(second))
        self.assertPoint(on_corner[:4], (before[0] - 20, before[1] - 20, before[2] - 10, before[3] - 10))
        self.assertAlmostEqual(on_corner[4], 1.0, msg="1 mm below the top, which is 2 mm above the zero point")

        setup = self.program()
        self.assertPoint(tuple(setup.stock), (-21, -11, -12, 21, 11, 1), "BLK FORM on the preset")
        one, two = setup.operations
        self.assertIsNone(one.zero)
        self.assertEqual(self.cutting(one.moves), before)
        self.assertEqual(two.zero.origin, (20.0, 10.0, -2.0))
        self.assertEqual(self.cutting(two.moves), on_corner)
        self.assertPoint(self.cam.zero(self.job).Base, (20, 10, 10), "the program leaves the zero point where it was")
        self.assertTrue(self.engine.parked(first) and not self.engine.parked(second))

    def test_reset_and_the_zero_point_of_an_operation(self):
        first = self.contour()
        before = self.cutting(self.cam.nc_moves(first))
        self.move_zero.move(self.job, (20.0, 10.0, 0.0))
        second = self.contour()
        on_corner = self.cutting(self.cam.nc_moves(second))
        self.assertTrue(self.engine.reset(self.job))
        self.assertPoint(self.cam.zero(self.job).Base, (0, 0, 12))
        self.assertTrue(self.engine.at_default(self.job))
        self.assertFalse(self.engine.reset(self.job), "it is there")
        self.assertTrue(self.engine.parked(second) and not self.engine.parked(first))
        self.assertEqual(self.cutting(self.cam.nc_moves(first)), before)
        self.assertPoint(self.stock(), (-21, -11, -12, 21, 11, 1))
        self.assertEqual(self.engine.operation_zero(second).origin, (20.0, 10.0, 0.0))
        # Make 0-Point of the operation active
        self.assertTrue(self.engine.activate_operation(second))
        self.assertPoint(self.cam.zero(self.job).Base, (20, 10, 12))
        self.assertFalse(self.engine.parked(second))
        self.assertEqual(self.cutting(self.cam.nc_moves(second)), on_corner)
        self.assertFalse(self.engine.activate_operation(second), "it is the active one")

    def test_set_as_default(self):
        first = self.contour()
        self.assertFalse(self.engine.set_default(self.job), "it is the default")
        self.move_zero.move(self.job, (20.0, 10.0, 0.0))
        second = self.contour()
        self.assertTrue(self.engine.set_default(self.job))
        self.assertTrue(self.engine.at_default(self.job))
        self.assertPoint(self.engine.default_zero(self.job).Base, (20, 10, 12))
        setup = self.program()
        self.assertPoint(tuple(setup.stock), (-41, -21, -12, 1, 1, 1), "BLK FORM from the new preset")
        self.assertEqual(setup.operations[0].zero.origin, (-20.0, -10.0, 0.0), "the first one is shifted now")
        self.assertIsNone(setup.operations[1].zero)
        self.assertTrue(self.engine.parked(first) and not self.engine.parked(second))
        self.assertFalse(self.engine.reset(self.job))

    def test_tilted_onto_a_wall(self):
        """Z out of the right wall: the tool axis is the part's X."""
        top = self.contour()
        wall = self.face((1, 0, 0))
        shift = self.move_zero.wall_shift(self.job, self.part, wall)
        turn = self.move_zero.wall_turn(self.job, self.part, wall)
        self.assertEqual((shift, turn), ((20.0, 0.0, 0.0), (0.0, 90.0, 0.0)))
        place = self.move_zero.target(self.job, shift, turn)
        self.assertPoint(self.cam.zero(self.job).Base, (0, 0, 12), "only asked")
        self.move_zero.move(self.job, shift, turn)
        self.assertTrue(self.cam.zero(self.job).isSame(place, 1e-9))
        self.assertPoint(self.geometry.tool_axis(self.cam.zero(self.job)), (1, 0, 0))
        # the same block: 40 along the tool now, 12 across (X looks down)
        self.assertPoint(self.stock(), (-1, -11, -41, 12, 11, 1))
        side = self.contour((1, 0, 0), -2.0)
        cut = self.cutting(self.cam.nc_moves(side))
        self.assertPoint(cut, (0, 12, -10, 10, -2), "the wall's outline, 2 mm into it")

        setup = self.program()
        self.assertPoint(tuple(setup.stock), (-21, -11, -12, 21, 11, 1))
        one, two = setup.operations
        self.assertIsNone(one.zero)
        self.assertEqual(two.zero.origin, (20.0, 0.0, 0.0))
        self.assertEqual((two.zero.x_axis, two.zero.z_axis), ((0.0, 0.0, -1.0), (1.0, 0.0, 0.0)))
        self.assertEqual(self.cutting(two.moves), cut)
        self.assertTrue(self.engine.parked(top) and not self.engine.parked(side))

    def test_stock_at_an_odd_angle_is_the_box_around_the_block(self):
        self.move_zero.move(self.job, (0.0, 0.0, 0.0), (0.0, 0.0, 45.0))
        half = (42 + 22) / 2 ** 0.5 / 2
        self.assertPoint(self.stock(), (-half, -half, -12, half, half, 1))
        self.engine.reset(self.job)
        self.assertPoint(self.stock(), (-21, -11, -12, 21, 11, 1), "back: the block itself")

    # -- the stock's own zero point ----------------------------------------------------

    def test_stock_typed_on_a_quarter_turned_zero_point(self):
        """Typed where the zero point is, it is the block on the default one."""
        from avangardecam.model.stock import BoxStock

        self.contour()
        # onto the right wall: its X is the default one's -Z, its Z the default one's +X
        self.move_zero.move(self.job, (20.0, 0.0, -6.0), (0.0, 90.0, 0.0))
        edit = self.engine.stock_edit(self.job)
        self.assertFalse(edit.own, "a box on these axes too: typed on them")
        self.assertEqual(edit.box, BoxStock(1.0, 0.0, 1.0, 1.0, 1.0, 1.0), "the block as the wall sees it")
        self.assertPoint(tuple(edit.model), (-6, -10, -40, 6, 10, 0))
        typed = BoxStock(3.0, 0.5, 1.0, 2.0, 1.0, 4.0)
        self.engine.set_stock(self.job, typed)
        self.assertEqual(self.cam.stock(self.job), typed)
        self.assertPoint(self.stock(), (-9, -11, -41, 6.5, 12, 4))
        self.assertTrue(self.engine.same(self.engine.stock_zero(self.job), self.engine.default_zero(self.job)))
        self.assertPoint(tuple(self.program().stock), (-21, -11, -12.5, 24, 12, 3), "BLK FORM on the preset")
        self.engine.reset(self.job)
        self.assertEqual(self.cam.stock(self.job), BoxStock(1.0, 4.0, 1.0, 2.0, 0.5, 3.0), "the same block on the default one")
        self.assertPoint(self.stock(), (-21, -11, -12.5, 24, 12, 3))
        # and back on the wall as it was typed
        self.move_zero.move(self.job, (20.0, 0.0, -6.0), (0.0, 90.0, 0.0))
        self.assertEqual(self.cam.stock(self.job), typed)

    def test_stock_at_an_odd_angle_is_typed_on_its_own_zero_point(self):
        from avangardecam.engine import stock_size
        from avangardecam.model.stock import BoxStock

        self.assertFalse(self.engine.stock_edit(self.job).own)
        self.assertIsNone(self.engine.block_seen(self.job))
        self.move_zero.move(self.job, (0.0, 0.0, 0.0), (0.0, 0.0, 30.0))
        edit = self.engine.stock_edit(self.job)
        self.assertTrue(edit.own, "no box on these axes: along the stock's own")
        self.assertEqual(edit.box, BoxStock())
        self.assertPoint(tuple(edit.model), (-20, -10, -12, 20, 10, 0))
        self.assertPoint(tuple(edit.bounds), (-21, -11, -12, 21, 11, 1))
        bounds, place = self.engine.block_seen(self.job)
        self.assertPoint(tuple(bounds), (-21, -11, -12, 21, 11, 1))
        self.assertAlmostEqual(place.Rotation.Angle * place.Rotation.Axis.z, -math.radians(30.0), places=9, msg="as it lies from here")
        typed = BoxStock(2.0, 2.0, 3.0, 3.0, 0.0, 5.0)
        self.engine.set_stock(self.job, typed)
        self.assertEqual(self.engine.stock_edit(self.job).box, typed)
        cos, sin = math.cos(math.radians(30.0)), math.sin(math.radians(30.0))
        reach_x, reach_y = 22 * cos + 13 * sin, 22 * sin + 13 * cos
        self.assertPoint(self.stock(), (-reach_x, -reach_y, -12, reach_x, reach_y, 5), "FreeCAD's stock: the box around it")
        self.assertPoint(tuple(self.program().stock), (-22, -13, -12, 22, 13, 5))
        # Stock size: the model in the middle, along the stock's own axes
        stock_size.set_size(self.job, 50.0, 30.0, 20.0)
        self.assertEqual(self.engine.stock_edit(self.job).box, BoxStock(5.0, 5.0, 5.0, 5.0, 4.0, 4.0))
        self.engine.reset(self.job)
        self.assertEqual(self.cam.stock(self.job), BoxStock(5.0, 5.0, 5.0, 5.0, 4.0, 4.0))
        self.assertFalse(self.engine.stock_edit(self.job).own)
        self.assertIsNone(self.engine.block_seen(self.job))

    def test_the_block_stays_when_another_zero_point_is_the_default(self):
        from avangardecam.engine import verify as engine_verify
        from avangardecam.model.stock import BoxStock

        self.cam.set_stock(self.job, BoxStock(1.0, 2.0, 3.0, 4.0, 0.0, 1.0))
        old = self.engine.default_zero(self.job)
        # a quarter turn: the same block on the new default zero point's axes
        self.move_zero.move(self.job, (0.0, 0.0, 0.0), (0.0, 0.0, 90.0))
        self.assertTrue(self.engine.set_default(self.job))
        self.assertTrue(self.engine.same(self.engine.stock_zero(self.job), self.cam.zero(self.job)))
        self.assertEqual(self.cam.stock(self.job), BoxStock(3.0, 4.0, 2.0, 1.0, 0.0, 1.0))
        self.assertIsNone(self.engine.start_mesh(self.job))
        # at an odd angle the block keeps its own zero point: no box on the new default one
        quarter = self.cam.zero(self.job)
        self.move_zero.move(self.job, (0.0, 0.0, 0.0), (0.0, 0.0, 30.0))
        self.assertTrue(self.engine.set_default(self.job))
        self.assertTrue(self.engine.at_default(self.job))
        self.assertTrue(self.engine.same(self.engine.stock_zero(self.job), quarter))
        self.assertFalse(self.engine.same(quarter, old))
        edit = self.engine.stock_edit(self.job)
        self.assertTrue(edit.own)
        self.assertEqual(edit.box, BoxStock(3.0, 4.0, 2.0, 1.0, 0.0, 1.0))
        # the program's stock is the box around it, what is cut the block itself
        box = self.program().stock
        self.assertGreater(box.x_max - box.x_min, 20.0 + 7.0 + 1.0)
        mesh = self.engine.start_mesh(self.job)
        self.assertEqual((len(mesh.vertices), len(mesh.triangles)), (8, 12))
        self.assertPoint(tuple(mesh.vertices.min(axis=0)) + tuple(mesh.vertices.max(axis=0)), tuple(box))
        self.contour()
        prepared = engine_verify.prepare(self.job)
        self.assertIsNotNone(prepared.start)
        result = engine_verify.run(prepared, 60)
        corner = ((result.vertices[:, 0] - box.x_max) ** 2 + (result.vertices[:, 1] - box.y_max) ** 2) ** 0.5
        self.assertGreater(float(corner.min()), 3.0, "the corners of the box around the block are air")

    # -- what runs the program ------------------------------------------------------------

    def test_verify_and_play_run_every_zero_point(self):
        import numpy as np

        from avangardecam.engine import cycle_time as engine_time
        from avangardecam.engine import next_setup
        from avangardecam.engine import playback as engine_playback
        from avangardecam.engine import verify as engine_verify
        from avangardecam.post import machines

        top = self.contour()
        self.move_zero.move(self.job, (20.0, 0.0, -6.0), (0.0, 90.0, 0.0))
        side = self.contour((1, 0, 0), -2.0)
        self.assertFalse(self.engine.at_default(self.job))
        # Verify: all as the default zero point sees it, whichever is the active one
        prepared = engine_verify.prepare(self.job)
        self.assertEqual([p.label for p in prepared.planned], [top.Label, side.Label])
        self.assertEqual([p.operation.axis for p in prepared.planned], ["+Z", (1.0, 0.0, 0.0)])
        self.assertPoint(tuple(prepared.stock), (-21, -11, -12, 21, 11, 1))
        low, high = prepared.vertices.min(axis=0), prepared.vertices.max(axis=0)
        self.assertPoint(tuple(low) + tuple(high), (-20, -10, -12, 20, 10, 0), "the part too")
        result = engine_verify.run(prepared, 80)
        self.assertEqual(result.collisions, ())
        # the tool's centre on the outlines: 1 mm into the part's top, 2 mm into its wall
        on_top, on_wall = result.gouges
        self.assertEqual((on_top.operation, on_wall.operation), (top.Label, side.Label))
        self.assertAlmostEqual(on_top.depth_mm, 1.0, places=3)
        self.assertAlmostEqual(on_wall.depth_mm, 2.0, places=3)
        self.assertAlmostEqual(on_wall.point[0], 20.0, places=3, msg="on the wall, in the default zero point's coordinates")
        # the allowance on the wall is gone where the tool (Ø8, round the wall's outline) went
        on_allowance = result.vertices[result.vertices[:, 0] > 20.5]
        self.assertTrue(len(on_allowance))
        self.assertLess(float(np.abs(on_allowance[:, 1]).max()), 6.5)
        self.assertPoint(self.cam.zero(self.job).Base, (20, 0, 6), "the zero point stays where the user has it")
        self.engine.reset(self.job)
        again = engine_verify.prepare(self.job)
        np.testing.assert_allclose(again.vertices.min(axis=0), low, atol=1e-6)
        self.assertEqual([p.operation.axis for p in again.planned], ["+Z", (1.0, 0.0, 0.0)])
        self.engine.activate_operation(side)

        # Play: the program of a machine that tilts, whichever was chosen
        played = engine_playback.prepare(self.job, machines.BRIDGEPORT_V1000)
        self.assertEqual(played.machine, machines.SORALUCE_T35.label)
        line = played.timeline
        self.assertEqual(line.tool_axis(line.total_s), (1.0, 0.0, 0.0))
        self.assertEqual(line.operations[1].zero.origin, (20.0, 0.0, -6.0))
        self.assertTrue(any("PLANE SPATIAL SPA0. SPB90. SPC0." in text for text in line.lines))
        self.assertPoint(tuple(played.vertices.min(axis=0)) + tuple(played.vertices.max(axis=0)), (-20, -10, -12, 20, 10, 0))

        # the cycle time and the stock the setup leaves
        (times,) = engine_time.program_times(self.doc)
        self.assertEqual([op.label for op in times.operations], [top.Label, side.Label])
        self.assertGreater(times.operations[1].feed_s, 1.0)
        left = next_setup.prepare_left(self.job)
        self.assertPoint(tuple(left.to_part[:3, 3]), (0, 0, 12), "from the default zero point to the part")
        mesh = next_setup.left(left, 60)
        self.assertLess(float(np.abs(mesh.vertices[mesh.vertices[:, 0] > 20.5][:, 1]).max()), 6.5)
        self.assertGreater(float(mesh.vertices[:, 2].min()), -1e-6, "in the part's coordinates: the block stands on Z0")

    def test_the_setup_moves_from_its_default_zero_point_only(self):
        from avangardecam.engine import ProjectError

        first = self.contour()
        self.move_zero.move(self.job, (20.0, 0.0, 0.0))
        with self.assertRaisesRegex(ProjectError, "not its default"):
            self.cam.rotate_zero(self.job, 90.0)
        self.assertPoint(self.cam.zero(self.job).Base, (20, 0, 12))
        second = self.contour()
        self.engine.reset(self.job)
        before = self.cutting(self.cam.nc_moves(first))
        self.cam.rotate_zero(self.job, 90.0)
        self.assertTrue(self.engine.at_default(self.job), "the default zero point turned with the setup")
        after = self.cutting(self.cam.nc_moves(first))
        self.assertPoint(after[:4], (before[2], before[3], before[0], before[1]), "its operation followed")
        self.assertTrue(self.engine.parked(second))
        self.assertPoint(self.engine.zero_of(second).Base, (20, 0, 12), "the other one stays on the part")
        # from the turned preset the second zero point lies along -Y
        self.assertEqual(self.engine.operation_zero(second).origin, (0.0, -20.0, 0.0))

    def test_a_parked_operation_follows_its_tool_in_the_program(self):
        first = self.contour()
        self.move_zero.move(self.job, (20.0, 0.0, 0.0))
        self.contour()
        self.tc.HorizFeed = FreeCAD.Units.Quantity("123 mm/min")
        self.doc.recompute()
        self.assertTrue(self.engine.parked(first))
        for op in self.program().operations:
            feeds = {round(m.feed_mm_min, 3) for m in op.moves if m.kind != "rapid"}
            self.assertIn(123.0, feeds, op.label)

    def test_the_program_leaves_no_undo_step(self):
        self.doc.UndoMode = 1
        self.contour()
        self.move_zero.move(self.job, (20.0, 0.0, 0.0))
        self.contour()
        self.doc.recompute()
        steps = self.doc.UndoCount
        setup = self.program()
        self.assertEqual(len(setup.operations), 2)
        self.assertEqual(self.doc.UndoCount, steps)
        self.assertPoint(self.cam.zero(self.job).Base, (20, 0, 12))
        self.assertFalse([o.Name for o in self.doc.Objects if "Touched" in o.State])
        self.assertEqual(self.program(), setup, "and again the same")

    def test_saved_and_opened(self):
        import os
        import tempfile

        first = self.contour()
        before = self.cutting(self.cam.nc_moves(first))
        self.move_zero.move(self.job, (20.0, 0.0, 0.0), (0.0, 0.0, 90.0))
        self.contour()
        setup = self.program()
        path = os.path.join(tempfile.mkdtemp(), "zeros.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        self.job = self.cam.setups(self.doc)[0]
        first = self.cam.operations(self.job)[0]
        self.assertTrue(self.engine.parked(first))
        self.assertPoint(self.engine.default_zero(self.job).Base, (0, 0, 12))
        first.touch()
        self.doc.recompute()
        self.assertEqual(self.cutting(self.cam.nc_moves(first)), before)
        opened = self.program()
        self.assertEqual(opened.stock, setup.stock)
        self.assertEqual(len(opened.operations), 2)
        for was, now in zip(setup.operations, opened.operations):
            self.assertEqual((was.label, was.zero), (now.label, now.zero))
            self.assertEqual(len(was.moves), len(now.moves))
            for a, b in zip(was.moves, now.moves):
                self.assertEqual((a.kind, a.compensation, a.clockwise), (b.kind, b.compensation, b.clockwise))
                for c, d in zip((a.x, a.y, a.z), (b.x, b.y, b.z)):
                    self.assertEqual(c is None, d is None)
                    if c is not None:
                        self.assertAlmostEqual(c, d, places=6)

    def test_switched_off_operations_are_not_visited(self):
        first = self.contour()
        self.move_zero.move(self.job, (20.0, 0.0, 0.0))
        second = self.contour()
        self.cam.set_active(first, False)
        self.doc.recompute()
        setup = self.program()
        self.assertEqual([op.label for op in setup.operations], [second.Label])
        self.assertEqual(setup.operations[0].zero.origin, (20.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
