# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Custom stock tests (CAM > Custom stock): the model ones are plain
Python (python3 -m unittest avangardecam.tests.test_custom_stock), the
engine ones need FreeCADCmd (tests/run.py)."""

import os
import tempfile
import unittest

import numpy as np

try:
    import FreeCAD
except ImportError:  # plain Python: only the model tests
    FreeCAD = None

from avangardecam.model import custom_stock
from avangardecam.model.stock import Bounds


class TestCustomStockModel(unittest.TestCase):
    def test_centre_shift(self):
        blank = Bounds(100.0, 200.0, 50.0, 144.0, 224.0, 65.0)
        model = Bounds(-20.0, -10.0, 0.0, 20.0, 10.0, 12.0)
        shift = custom_stock.centre_shift(blank, model)
        self.assertEqual(shift, (-122.0, -212.0, -51.5))
        moved = custom_stock.moved(blank, shift)
        self.assertEqual(custom_stock.middle(moved), custom_stock.middle(model))
        self.assertEqual(moved, Bounds(-22.0, -12.0, -1.5, 22.0, 12.0, 13.5))
        self.assertEqual(custom_stock.sticking_out(moved, model), [])

    def test_sticking_out(self):
        model = Bounds(-20.0, -10.0, 0.0, 20.0, 10.0, 12.0)
        # turned 90°: 24 long in X, 44 in Y; on the middle
        blank = Bounds(-12.0, -22.0, -1.5, 12.0, 22.0, 13.5)
        out = custom_stock.sticking_out(blank, model)
        self.assertEqual([s.side for s in out], ["X−", "X+"])
        self.assertAlmostEqual(out[0].mm, 8.0)
        # largest first, rounding left out
        blank = Bounds(-20.005, -9.0, 0.5, 20.0, 10.0, 12.0)
        self.assertEqual([(s.side, round(s.mm, 6)) for s in custom_stock.sticking_out(blank, model)], [("Y−", 1.0), ("Z−", 0.5)])


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (run inside FreeCADCmd)")
class TestCustomStockEngine(unittest.TestCase):
    """The part with holes of test_engine (40 x 20 x 12, X -20..20, Y -10..10,
    Z 0..12), Setup 1 from the top; a blank 44 x 24 x 15 drawn far away from
    it, as a foundry or a saw draws it."""

    def setUp(self):
        from avangardecam.engine import custom_stock as engine
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry, next_setup, stock_size
        from avangardecam.tests.test_engine import TestEngine

        self.cam, self.geometry, self.next, self.engine, self.size = cam, geometry, next_setup, engine, stock_size
        self.helpers = TestEngine("setUp")
        self.helpers.setUp()
        self.doc = self.helpers.doc
        self.obj = self.helpers.model_with_holes()
        self.job = cam.ensure_job(self.doc, [self.obj])
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def step(self, size=(44, 24, 15), corner=(100, 200, 50), name="casting.step"):
        import Part

        path = os.path.join(self.folder, name)
        Part.makeBox(*size, FreeCAD.Vector(*corner)).exportStep(path)
        return path

    def stl(self, size=(44, 24, 15), corner=(-300, 40, 7)):
        import Mesh
        import Part

        path = os.path.join(self.folder, "sawn.stl")
        shape = Part.makeBox(*size, FreeCAD.Vector(*corner))
        Mesh.Mesh(shape.tessellate(0.01)).write(path)
        return path

    def middles(self, job):
        stock = self.cam.stock_bounds(job)
        model = self.size.models_bounds(job)
        return custom_stock.middle(stock), custom_stock.middle(model)

    def test_step_put_in_the_middle(self):
        model = self.size.models_bounds(self.job)
        loaded = self.engine.load(self.job, self.step())
        self.assertEqual(self.next.kind(self.job), self.next.CUSTOM)
        self.assertIn("casting.step", self.next.description(self.job))
        self.assertEqual(loaded.out, [])
        stock, middle = self.middles(self.job)
        np.testing.assert_allclose(stock, middle, atol=1e-6)
        np.testing.assert_allclose(self.cam.stock_bounds(self.job), custom_stock.moved(Bounds(0, 0, 0, 44, 24, 15), (-22 + (model.x_min + model.x_max) / 2, -12 + (model.y_min + model.y_max) / 2, -7.5 + (model.z_min + model.z_max) / 2)), atol=1e-6)  # fmt: skip
        self.assertTrue(self.engine.is_on_middle(self.job))
        # the material Play and Verify start from: the blank where it is drawn
        start = self.next.start_mesh(self.job)
        from avangardecam.model import start_stock

        np.testing.assert_allclose(start_stock.bounds(start), self.cam.stock_bounds(self.job), atol=1e-6)
        # the source moved, in the part's coordinates; the shift on the setup's axes
        src = self.next.source(self.job)
        box = src.Shape.BoundBox
        self.assertAlmostEqual((box.XMin + box.XMax) / 2, 0.0, places=6)
        self.assertAlmostEqual((box.ZMin + box.ZMax) / 2, 6.0, places=6)
        self.assertEqual(len(loaded.shift), 3)

    def test_file_place_kept_without_middle(self):
        self.engine.load(self.job, self.step(corner=(-22, -12, -1)), middle=False)
        before = self.cam.stock_bounds(self.job)
        self.assertFalse(self.engine.is_on_middle(self.job))  # 1 mm under, 2 over the part: Z middle 0.5 higher
        np.testing.assert_allclose(self.engine.off_middle(self.job), (0.0, 0.0, -0.5), atol=1e-6)
        # Put in the middle afterwards (Details)
        shift = self.engine.centre(self.job)
        np.testing.assert_allclose(shift, (0.0, 0.0, -0.5), atol=1e-6)
        after = self.cam.stock_bounds(self.job)
        np.testing.assert_allclose(np.array(after) - np.array(before), (0, 0, -0.5, 0, 0, -0.5), atol=1e-6)
        self.assertTrue(self.engine.is_on_middle(self.job))

    def test_setup_from_the_bottom_and_zero_moved(self):
        import Part

        bottom = next(
            "Face{}".format(i)
            for i, f in enumerate(self.obj.Shape.Faces, start=1)
            if isinstance(f.Surface, Part.Plane) and abs(f.BoundBox.ZMax) < 1e-9 and f.Area > 400
        )
        job = self.cam.new_setup(self.doc, self.geometry.zero_on_face([self.obj], self.obj, bottom))
        self.engine.load(job, self.step(corner=(-500, 30, 7)))
        stock, middle = self.middles(job)
        np.testing.assert_allclose(stock, middle, atol=1e-6)
        b = self.cam.stock_bounds(job)
        np.testing.assert_allclose((b.x_max - b.x_min, b.y_max - b.y_min, b.z_max - b.z_min), (44, 24, 15), atol=1e-6)
        # the zero moves to the top: the blank stays on the part
        self.cam.set_zero(job, self.geometry.zero_on_top([self.obj]))
        stock, middle = self.middles(job)
        np.testing.assert_allclose(stock, middle, atol=1e-6)

    def test_stl_put_in_the_middle(self):
        loaded = self.engine.load(self.job, self.stl())
        self.assertEqual(loaded.out, [])
        self.assertTrue(self.next._is_mesh(self.next.source(self.job)))
        stock, middle = self.middles(self.job)
        np.testing.assert_allclose(stock, middle, atol=1e-6)
        from avangardecam.model import start_stock

        np.testing.assert_allclose(start_stock.bounds(self.next.start_mesh(self.job)), self.cam.stock_bounds(self.job), atol=1e-6)
        self.assertIsNotNone(self.next.material(self.job))

    def test_blank_too_small_or_turned(self):
        loaded = self.engine.load(self.job, self.step(size=(24, 44, 15)))  # turned 90°
        self.assertEqual(sorted(s.side for s in loaded.out), ["X+", "X−"])
        self.assertAlmostEqual(loaded.out[0].mm, 8.0, places=6)
        self.assertEqual(self.next.kind(self.job), self.next.CUSTOM)  # loaded all the same: the user is told

    def test_middle_of_a_large_arc(self):
        """A part with a large arc on top (R 1000, as the user's part 2.4 m
        long): the middle from the exact faces. In the GUI FreeCAD's
        BoundBox comes from the triangles drawn, under the arc (1.44 mm on
        the user's part); FreeCADCmd draws nothing, so that is checked by
        hand in the GUI (docs/notes-pl.md)."""
        import Part

        V = FreeCAD.Vector
        arc = Part.makeCylinder(1000, 100, V(0, -50, -1000), V(0, 1, 0)).common(Part.makeBox(800, 100, 200, V(-130, -50, -200)))
        part = self.doc.addObject("Part::Feature", "Arc")
        part.Shape = arc
        self.doc.recompute()
        job = self.cam.new_setup(self.doc, FreeCAD.Placement(), [part])
        exact = self.engine.models_bounds(job)
        np.testing.assert_allclose(exact, (-130.0, -50.0, -200.0, 600.0, 50.0, 0.0), atol=1e-6)
        self.engine.load(job, self.step(size=(740, 110, 210), corner=(5000, 0, 0)))
        np.testing.assert_allclose(self.cam.stock_bounds(job), (-135.0, -55.0, -205.0, 605.0, 55.0, 5.0), atol=1e-6)

    def test_drawn_around_the_model_kept(self):
        """The foundry drew the casting over the part (1 mm under, 2 over):
        left there, the middle checked or not."""
        loaded = self.engine.load(self.job, self.step(corner=(-22, -12, -1)))
        self.assertTrue(loaded.kept)
        self.assertEqual(loaded.shift, (0.0, 0.0, 0.0))
        np.testing.assert_allclose(self.engine.off_middle(self.job), (0.0, 0.0, -0.5), atol=1e-6)
        # a hair outside (a coarse STL) is around it all the same; more is not
        self.assertTrue(self.engine.load(self.job, self.step(size=(44, 24, 12.95), corner=(-22, -12, 0.05))).kept)
        loaded = self.engine.load(self.job, self.step(size=(44, 24, 12.5), corner=(-22, -12, 0.5)))
        self.assertFalse(loaded.kept)
        self.assertTrue(self.engine.is_on_middle(self.job))

    def test_move_along_the_setup_axes(self):
        import Part

        self.engine.load(self.job, self.step())
        before = np.array(self.cam.stock_bounds(self.job))
        self.assertEqual(self.engine.move(self.job, (5.0, -3.0, 2.0)), (5.0, -3.0, 2.0))
        np.testing.assert_allclose(np.array(self.cam.stock_bounds(self.job)) - before, (5, -3, 2, 5, -3, 2), atol=1e-6)
        np.testing.assert_allclose(self.engine.off_middle(self.job), (-5.0, 3.0, -2.0), atol=1e-6)
        # from the bottom: along that setup's axes
        bottom = next(
            "Face{}".format(i)
            for i, f in enumerate(self.obj.Shape.Faces, start=1)
            if isinstance(f.Surface, Part.Plane) and abs(f.BoundBox.ZMax) < 1e-9 and f.Area > 400
        )
        job = self.cam.new_setup(self.doc, self.geometry.zero_on_face([self.obj], self.obj, bottom))
        self.engine.load(job, self.stl())
        before = np.array(self.cam.stock_bounds(job))
        self.engine.move(job, (0.0, 0.0, 3.0))
        np.testing.assert_allclose(np.array(self.cam.stock_bounds(job)) - before, (0, 0, 3, 0, 0, 3), atol=1e-6)
        from avangardecam.model import start_stock

        np.testing.assert_allclose(start_stock.bounds(self.next.start_mesh(job)), self.cam.stock_bounds(job), atol=1e-6)
        self.cam.set_stock(job, self.cam.model_stock.BoxStock())
        with self.assertRaises(self.cam.ProjectError):
            self.engine.move(job, (1.0, 0.0, 0.0))  # a box follows the model

    def test_freecad_stock_on_the_exact_box(self):
        """FreeCAD's shapeBoundBox is AvangardeCam's: the exact faces."""
        import Path.Main.Stock as PathStock

        self.assertTrue(getattr(PathStock.shapeBoundBox, "avangardecam_exact", False))
        box = PathStock.shapeBoundBox(self.job.Model.Group)
        exact = self.engine.models_bounds(self.job)
        np.testing.assert_allclose((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax), exact, atol=1e-6)
        self.assertIsNone(PathStock.shapeBoundBox([]))
        # the stock with allowances around it (1 mm on the sides and top)
        np.testing.assert_allclose(self.cam.stock_bounds(self.job), (exact.x_min - 1, exact.y_min - 1, exact.z_min, exact.x_max + 1, exact.y_max + 1, exact.z_max + 1), atol=1e-6)  # fmt: skip

    def test_back_to_a_box_and_bad_files(self):
        self.engine.load(self.job, self.step())
        name = self.next.source(self.job).Name
        self.cam.set_stock(self.job, self.cam.model_stock.BoxStock())
        self.assertEqual(self.next.kind(self.job), self.next.STANDARD)
        self.assertIsNone(self.doc.getObject(name))
        with self.assertRaises(self.cam.ProjectError):
            self.engine.load(self.job, os.path.join(self.folder, "casting.txt"))
        with self.assertRaises(self.cam.ProjectError):
            self.engine.centre(self.job)  # a box: nothing to put in the middle
        self.assertEqual(self.next.kind(self.job), self.next.STANDARD)


if __name__ == "__main__":
    unittest.main()
