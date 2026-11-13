# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Stock size tests. The model ones are plain Python:

    python3 -m unittest avangardecam.tests.test_stock_size   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import dataclasses
import unittest

from avangardecam.model import stock, stock_size

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

# the model 40 x 20 x 12 with its top in Z0, as a setup snapped on its top sees it
MODEL = stock.Bounds(-20.0, -10.0, -12.0, 20.0, 10.0, 0.0)


class TestStockSizeModel(unittest.TestCase):
    def test_centred(self):
        box = stock_size.centred(MODEL, 50.0, 30.0, 20.0)
        self.assertEqual(box, stock.BoxStock(5.0, 5.0, 5.0, 5.0, 4.0, 4.0))
        self.assertEqual(box.bounds(MODEL), (-25.0, -15.0, -16.0, 25.0, 15.0, 4.0))

    def test_odd_sizes(self):
        box = stock_size.centred(MODEL, 41.0, 20.5, 12.3)
        bounds = box.bounds(MODEL)
        for got, wanted in zip(bounds, (-20.5, -10.25, -12.15, 20.5, 10.25, 0.15)):
            self.assertAlmostEqual(got, wanted, places=9)

    def test_as_big_as_the_model(self):
        self.assertEqual(stock_size.centred(MODEL, 40.0, 20.0, 12.0), stock.BoxStock(0, 0, 0, 0, 0, 0))
        # rounding of the model's box is not "smaller"
        self.assertEqual(
            stock_size.centred(MODEL, 40.0 - 1e-9, 20.0, 12.0).x_neg_mm, 0.0
        )

    def test_smaller_than_the_model(self):
        for size in ((39.9, 30.0, 20.0), (50.0, 19.0, 20.0), (50.0, 30.0, 11.99)):
            with self.assertRaises(ValueError, msg=size) as caught:
                stock_size.centred(MODEL, *size)
            self.assertIn("smaller than the model", str(caught.exception))

    def test_too_big(self):
        with self.assertRaises(ValueError):
            stock_size.centred(MODEL, 40.0 + 2 * stock.BoxStock.MAX_ALLOWANCE_MM + 1, 30.0, 20.0)


@unittest.skipIf(FreeCAD is None, "needs FreeCAD")
class TestStockSizeEngine(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("AvangardeCamStockSize")
        box = self.doc.addObject("Part::Box", "Part")
        box.Length, box.Width, box.Height = 40, 20, 12
        box.Placement.Base = FreeCAD.Vector(-20, -10, 0)
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def assertBounds(self, actual, expected):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=6)

    def test_set_size(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import stock_size as engine

        job = cam.ensure_job(self.doc)
        self.assertBounds(engine.models_bounds(job), MODEL)
        box = engine.set_size(job, 50.0, 30.0, 20.0)
        self.assertEqual(cam.stock(job), box)
        self.assertBounds(cam.stock_bounds(job), (-25, -15, -16, 25, 15, 4))
        # allowances typed later start from the centred block
        cam.set_stock(job, dataclasses.replace(box, z_pos_mm=1.0))
        self.assertBounds(cam.stock_bounds(job), (-25, -15, -16, 25, 15, 1))

    def test_refused_size_changes_nothing(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import stock_size as engine

        job = cam.ensure_job(self.doc)
        before = cam.stock(job)
        with self.assertRaises(ValueError):
            engine.set_size(job, 30.0, 30.0, 20.0)
        self.assertEqual(cam.stock(job), before)
        self.assertBounds(cam.stock_bounds(job), (-21, -11, -12, 21, 11, 1))

    def test_turned_zero(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import stock_size as engine

        job = cam.ensure_job(self.doc)
        cam.rotate_zero(job, 90.0)
        self.doc.recompute()
        x, y, _z = engine.models_bounds(job).size
        self.assertAlmostEqual(x, 20.0, places=6)
        self.assertAlmostEqual(y, 40.0, places=6)
        engine.set_size(job, 30.0, 50.0, 12.0)
        sx, sy, sz = cam.stock_bounds(job).size
        self.assertAlmostEqual(sx, 30.0, places=6)
        self.assertAlmostEqual(sy, 50.0, places=6)
        self.assertAlmostEqual(sz, 12.0, places=6)
