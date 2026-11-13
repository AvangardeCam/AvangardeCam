# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The stock a setup starts from (CAM > Next setup). The model ones are
plain Python with numpy:

    python3 -m unittest avangardecam.tests.test_start_stock   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import math
import os
import tempfile
import unittest

import numpy as np

from avangardecam import stocklab
from avangardecam.model import nc, operations, playback, playback_stock, start_stock, threads, verify
from avangardecam.model.stock import Bounds
from avangardecam.stocklab.cut import cut_line
from avangardecam.stocklab.section import contains, signed_area
from avangardecam.stocklab.tools import flat_end_mill
from avangardecam.tests.test_verify import MILL_6, NC_6, NC_THREAD_MILL, THREAD_MILL, box_mesh

try:
    import FreeCAD
except ImportError:
    FreeCAD = None

STOCK = Bounds(0.0, 0.0, -9.0, 30.0, 20.0, 1.0)


def _mesh(vertices, triangles):
    return start_stock.Mesh(np.asarray(vertices, float), np.asarray(triangles))


def _drilled(holes, diameter, bottom, resolution=120):
    """The stock 30 x 20 x 10 with holes drilled from the top, as a mesh
    (what a setup before leaves)."""
    stock = stocklab.Stock.box((STOCK.x_min, STOCK.y_min, STOCK.z_min), (STOCK.x_max, STOCK.y_max, STOCK.z_max), resolution)
    for x, y in holes:
        cut_line(stock, flat_end_mill(diameter, 20.0), "+Z", (x, y, 5.0), (x, y, bottom))
    surface = stocklab.surface(stock)
    return _mesh(surface.vertices, surface.triangles)


def _material(boxes):
    """The stock model of a mesh made of box_mesh boxes."""
    vertices = np.concatenate([v for v, _t in boxes])
    triangles = np.concatenate([t + 8 * i for i, (_v, t) in enumerate(boxes)])
    return stocklab.Stock.from_mesh(vertices, triangles, 150)


def _facing(z):
    moves = [nc.Move(nc.RAPID, -5.0, 2.0, 2.0), nc.Move(nc.LINE, -5.0, 2.0, z, 200.0)]
    for k, y in enumerate((2.0, 7.0, 12.0, 17.0)):
        moves += [nc.Move(nc.LINE, -5.0 if k % 2 == 0 else 35.0, y, z, 600.0), nc.Move(nc.LINE, 35.0 if k % 2 == 0 else -5.0, y, z, 600.0)]
    return nc.Setup(1, "Setup 1", STOCK, (nc.Operation(nc.FACING, "Facing", NC_6, tuple(moves)),))


class StartStockTest(unittest.TestCase):
    def test_block(self):
        self.assertAlmostEqual(start_stock.block(STOCK, None, 30).volume(), 6000.0, places=6)
        smaller = _mesh(*box_mesh((0.0, 0.0, -9.0), (30.0, 20.0, 0.0)))
        self.assertAlmostEqual(start_stock.block(STOCK, smaller, 30).volume(), 5400.0, places=6)
        self.assertEqual(start_stock.bounds(smaller), Bounds(0.0, 0.0, -9.0, 30.0, 20.0, 0.0))

    def test_left(self):
        setup = _facing(0.0)
        steps = []
        left = start_stock.left(setup.stock, None, verify.plan(setup, {1: MILL_6}), 60, steps.append)
        self.assertEqual(steps, ["Cutting the stock", "The surface of the stock left"])
        b = start_stock.bounds(left)
        self.assertAlmostEqual(b.z_max, 0.0, delta=0.5)  # faced; the surface on the cells' middles
        self.assertAlmostEqual(stocklab.Stock.from_mesh(left.vertices, left.triangles, 60).volume() / 5400.0, 1.0, delta=0.03)
        # what it leaves of a stock already faced 0.5 lower: the same
        start = _mesh(*box_mesh((0.0, 0.0, -9.0), (30.0, 20.0, -0.5)))
        again = start_stock.left(setup.stock, start, verify.plan(setup, {1: MILL_6}), 60)
        self.assertAlmostEqual(start_stock.bounds(again).z_max, -0.5, delta=0.5)

    def test_moved(self):
        mesh = _mesh(*box_mesh((0.0, 0.0, -9.0), (30.0, 20.0, 0.0)))
        upside_down = np.diag((1.0, -1.0, -1.0, 1.0))
        upside_down[:3, 3] = (0.0, 0.0, -9.0)
        b = start_stock.bounds(start_stock.moved(mesh, upside_down))
        np.testing.assert_allclose(b, (0.0, -20.0, -9.0, 30.0, 0.0, 0.0), atol=1e-12)

    def test_verify_starts_from_the_mesh(self):
        """A rapid move down where the setup before took the material: no crash."""
        moves = (nc.Move(nc.RAPID, 15.0, 10.0, 2.0), nc.Move(nc.RAPID, 15.0, 10.0, -3.0), nc.Move(nc.LINE, 20.0, 10.0, -3.0, 600.0))
        setup = nc.Setup(1, "Setup 1", STOCK, (nc.Operation(nc.CONTOUR, "Pocket", NC_6, moves),))
        part = box_mesh((-50.0, -50.0, -60.0), (-40.0, -40.0, -50.0))
        planned = verify.plan(setup, {1: MILL_6})
        self.assertEqual(len(verify.verify(STOCK, *part, planned, resolution=60).collisions), 1)
        start = _mesh(*box_mesh((0.0, 0.0, -9.0), (8.0, 20.0, 1.0)))  # material only at x < 8
        self.assertEqual(verify.verify(STOCK, *part, planned, resolution=60, start=start).collisions, ())

    def test_threads_in_holes_drilled_before(self):
        """No false alarm for a thread whose hole the setup before drilled."""
        holes = ((10.0, 10.0), (20.0, 10.0))
        thread = operations.ThreadMilling(3.0, -6.0, passes=2)
        moves = threads.moves(thread, [threads.ThreadHole(x, y, 0.0) for x, y in holes], 0.5, 1.5, 225.0, 300.0, nc.RIGHT)
        stock = Bounds(0.0, 0.0, -9.0, 30.0, 20.0, 0.0)
        setup = nc.Setup(1, "Setup 1", stock, (nc.Operation(nc.THREAD_MILLING, "Thread milling", NC_THREAD_MILL, moves),))
        part = box_mesh((-50.0, -50.0, -60.0), (-40.0, -40.0, -50.0))
        planned = verify.plan(setup, {3: THREAD_MILL})
        bare = verify.verify(stock, *part, planned, resolution=60)
        self.assertTrue(all(h.volume_mm3 > 20.0 for h in bare.holes))
        drilled = _drilled(holes, 2.5, -8.0)
        result = verify.verify(stock, *part, planned, resolution=60, start=drilled)
        self.assertEqual([h.volume_mm3 for h in result.holes], [0.0, 0.0])

    def test_area_with_a_hole(self):
        """Adaptive's stock of a level: the outline and the hole drilled before
        as far down as it goes."""
        material = stocklab.Stock.from_mesh(*_drilled(((10.0, 10.0),), 4.0, -6.0), 120)
        outline, holes = start_stock.area(material, -4.0, 1.0)
        self.assertEqual(len(holes), 1)
        self.assertGreater(signed_area(outline), 30.0 * 20.0 - 1e-6)
        hole = -signed_area(holes[0])
        self.assertLess(hole, math.pi * 4.0)  # never less than the material
        self.assertGreater(hole, math.pi * 4.0 * 0.6)
        self.assertEqual(start_stock.area(material, -8.5, -7.0)[1], [])  # under the hole's end
        self.assertIsNone(start_stock.area(material, 1.5, 3.0))  # over the stock

    def test_area_only_up_to_the_level_over(self):
        """A step the setup before left (material only at x < 8 under Z-4):
        a level under it sees the step only, with the level over it."""
        material = _material([box_mesh((0.0, 0.0, -9.0), (8.0, 20.0, 1.0)), box_mesh((8.0, 0.0, -4.0), (30.0, 20.0, 1.0))])
        whole = signed_area(start_stock.area(material, -6.0, 1.0)[0])
        step = signed_area(start_stock.area(material, -6.0, -4.0)[0])
        self.assertAlmostEqual(whole, 600.0, delta=6.0)
        self.assertAlmostEqual(step, 8.0 * 20.0, delta=0.5 * 20.0 + 1.0)

    def test_area_in_pieces(self):
        """Material in pieces: one outline around them all, the holes in them
        but not one with a piece in it."""
        sides = [((0.0, 0.0), (30.0, 4.0)), ((0.0, 16.0), (30.0, 20.0)), ((0.0, 4.0), (4.0, 16.0)), ((26.0, 4.0), (30.0, 16.0))]  # fmt: skip
        frame = [box_mesh((x0, y0, -9.0), (x1, y1, 1.0)) for (x0, y0), (x1, y1) in sides]
        island = box_mesh((12.0, 8.0, -9.0), (18.0, 12.0, 1.0))
        far = box_mesh((40.0, 0.0, -9.0), (44.0, 4.0, 1.0))
        _outline, holes = start_stock.area(_material(frame), -2.0, 1.0)
        self.assertEqual(len(holes), 1)  # the frame and the air in it
        outline, holes = start_stock.area(_material(frame + [island]), -2.0, 1.0)
        self.assertEqual(holes, [])  # the island in the frame's hole: no hole
        self.assertGreater(signed_area(outline), 600.0 - 1e-6)
        outline, holes = start_stock.area(_material(frame + [far]), -2.0, 1.0)
        self.assertEqual(len(holes), 1)
        inside = contains([outline], [(42.0, 2.0), (35.0, 2.0), (35.0, 19.0)])
        self.assertEqual(inside.tolist(), [True, True, False])  # the hull: convex

    def test_playback_starts_from_the_mesh(self):
        setup = _facing(0.0)
        line = playback.timeline(setup, 0, [], {}, retract_z=20.0)
        start = _mesh(*box_mesh((0.0, 0.0, -9.0), (30.0, 20.0, -2.0)))
        material = playback_stock.Material(line, STOCK, {1: MILL_6}, 60, start=start)
        self.assertAlmostEqual(material.volume(), 4200.0, places=6)
        material.cut_to(line.total_s)  # the facing at Z0 takes nothing of it
        self.assertAlmostEqual(material.volume(), 4200.0, places=6)
        self.assertEqual(material.crashes, {})


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (run inside FreeCADCmd)")
class TestNextSetupEngine(unittest.TestCase):
    """The part with holes of test_engine (40 x 20 x 12, top at Z12), Setup 1
    from the top milling its holes A (Ø6 through at x -15) and D (Ø10 3 deep
    at x 12) along a helix with a Ø4 end mill; Setup 2 from the bottom."""

    def setUp(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry
        from avangardecam.engine import helix as engine_helix
        from avangardecam.engine import next_setup
        from avangardecam.model import helix, library
        from avangardecam.tests.test_engine import TestEngine
        from avangardecam.tests.test_model import LIBRARY

        self.cam, self.geometry, self.next = cam, geometry, next_setup
        self.helpers = TestEngine("setUp")
        self.helpers.setUp()
        self.helpers.library = library.load(LIBRARY)
        self.doc = self.helpers.doc
        self.obj = self.helpers.model_with_holes()
        self.first = cam.ensure_job(self.doc, [self.obj])
        tc = cam.add_tool(self.first, self.helpers.variant(3, "Aluminium"))  # Ø4
        holes = [self.helpers.wall(self.obj, -15, 0, 3)[0], self.helpers.wall(self.obj, 12, 0, 5)[0]]
        engine_helix.add_model_helix_milling(self.first, self.obj, helix.HelixMilling(), tc, holes)

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def bottom(self):
        import Part

        for i, f in enumerate(self.obj.Shape.Faces, start=1):
            if isinstance(f.Surface, Part.Plane) and abs(f.BoundBox.ZMax) < 1e-9 and f.Area > 400:
                return "Face{}".format(i)
        raise AssertionError("no bottom face")

    def second(self):
        return self.cam.new_setup(self.doc, self.geometry.zero_on_face([self.obj], self.obj, self.bottom()))

    def test_stock_from_setup(self):
        left = self.next.left(self.next.prepare_left(self.first), 80)
        # in the part's coordinates: the first stock, 1 mm over the top at Z12
        b = start_stock.bounds(left)
        self.assertAlmostEqual(b.z_max, 13.0, delta=0.3)
        self.assertAlmostEqual(b.z_min, 0.0, delta=0.3)
        job = self.second()
        self.next.set_stock_from_setup(job, self.first, left, 80)
        self.assertEqual(self.next.kind(job), self.next.FROM_SETUP)
        self.assertIs(self.next.from_setup(job), self.first)
        self.assertIn("Setup 1", self.next.description(job))
        src = self.next.source(job)
        self.assertNotIn(src, self.cam.models(self.doc))
        # from the bottom: Z0 on the bottom, the stock 13 up into -Z
        stock = self.cam.stock_bounds(job)
        self.assertAlmostEqual(stock.z_max, 0.0, delta=0.3)
        self.assertAlmostEqual(stock.z_min, -13.0, delta=0.3)
        start = self.next.start_mesh(job)
        np.testing.assert_allclose(start_stock.bounds(start), stock, atol=1e-6)
        # the material: the first stock less the holes milled through (A, D's Ø10)
        block = stocklab.Stock.from_mesh(start.vertices, start.triangles, 80)
        full = 42.0 * 22.0 * 13.0
        holes = math.pi * 9.0 * 13.0 + math.pi * 25.0 * 4.0
        self.assertAlmostEqual(block.volume() / (full - holes), 1.0, delta=0.03)
        # Verify and the playback of Setup 2 start from it
        from avangardecam.engine import verify as engine_verify

        self.assertEqual(self.next.prepare_left(job).start.vertices.shape, start.vertices.shape)
        with self.assertRaises(self.cam.ProjectError):  # no operation yet: as before
            engine_verify.prepare(job)
        # the zero moves: the stock follows
        self.cam.set_zero(job, self.geometry.zero_on_top([self.obj]))
        stock = self.cam.stock_bounds(job)
        self.assertAlmostEqual(stock.z_max, 1.0, delta=0.3)
        self.assertAlmostEqual(stock.z_min, -12.0, delta=0.3)
        # a box with allowances instead: the stock left goes
        name = src.Name
        self.cam.set_stock(job, self.cam.model_stock.BoxStock())
        self.assertEqual(self.next.kind(job), self.next.STANDARD)
        self.assertIsNone(self.doc.getObject(name))

    def test_work_out_again(self):
        job = self.second()
        self.next.set_stock_from_setup(job, self.first, self.next.left(self.next.prepare_left(self.first), 60), 60)
        before = len(self.next.source(job).Mesh.Points)
        self.next.update_from_setup(job, self.next.left(self.next.prepare_left(self.first), 100), 100)
        self.assertEqual(getattr(job.Stock, self.next.ACCURACY_PROPERTY), 100)
        self.assertGreater(len(self.next.source(job).Mesh.Points), before)

    def test_custom_stock(self):
        import Part

        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "casting.step")
        V = FreeCAD.Vector
        Part.makeBox(44, 24, 15, V(-22, -12, -1)).exportStep(path)
        job = self.second()
        self.next.set_custom_stock(job, path)
        self.assertEqual(self.next.kind(job), self.next.CUSTOM)
        self.assertIn("casting.step", self.next.description(job))
        stock = self.cam.stock_bounds(job)  # from the bottom: Z0 on the part's bottom
        np.testing.assert_allclose(stock, (-22.0, -12.0, -14.0, 22.0, 12.0, 1.0), atol=1e-6)
        block = stocklab.Stock.from_mesh(*self.next.start_mesh(job), 60)
        self.assertAlmostEqual(block.volume() / (44 * 24 * 15), 1.0, delta=0.01)
        self.cam.set_zero(job, self.geometry.zero_on_top([self.obj]))
        np.testing.assert_allclose(self.cam.stock_bounds(job), (-22.0, -12.0, -13.0, 22.0, 12.0, 2.0), atol=1e-6)

    def test_bad_files(self):
        import Mesh

        folder = tempfile.mkdtemp()
        open_mesh = Mesh.Mesh([[(0, 0, 0), (1, 0, 0), (0, 1, 0)]])
        path = os.path.join(folder, "open.stl")
        open_mesh.write(path)
        job = self.second()
        for name in (path, os.path.join(folder, "casting.txt")):
            with self.assertRaises(self.cam.ProjectError):
                self.next.set_custom_stock(job, name)
        self.assertEqual(self.next.kind(job), self.next.STANDARD)


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (run inside FreeCADCmd)")
class TestAdaptiveFromSetup(unittest.TestCase):
    """A plate 40 x 20 x 12 with a hole Ø8 through at x -10, the stock 1 mm
    around and on top. Setup 1 from the top clears around it and in the
    hole down to 8 mm under its top (Adaptive, Ø4, Z steps of 2); Setup 2
    from the bottom (Z0 on the bottom, the stock down to Z-13) clears down
    to Z-10: Setup 1 left material around the plate and in the hole only
    from Z0 to Z-4."""

    HOLE = (-10.0, 0.0)

    def setUp(self):
        import Part
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import geometry, next_setup
        from avangardecam.tests.test_engine import TestEngine

        self.cam, self.geometry, self.next = cam, geometry, next_setup
        self.helpers = TestEngine("setUp")
        self.helpers.setUp()
        self.doc = self.helpers.doc
        V = FreeCAD.Vector
        self.plate = self.doc.addObject("Part::Feature", "Plate")
        self.plate.Shape = Part.makeBox(40, 20, 12, V(-20, -10, 0)).cut(Part.makeCylinder(4, 30, V(self.HOLE[0], self.HOLE[1], -5)))
        self.doc.removeObject(self.helpers.part.Name)
        self.doc.recompute()
        self.first = cam.ensure_job(self.doc, [self.plate])
        self.tool = self.helpers.variant(3, "Aluminium")
        cam.add_adaptive(self.first, operations.Adaptive(-8.0, z_step_mm=2.0), cam.add_tool(self.first, self.tool))
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def second(self):
        import Part

        bottom = next(
            "Face{}".format(i)
            for i, f in enumerate(self.plate.Shape.Faces, start=1)
            if isinstance(f.Surface, Part.Plane) and abs(f.BoundBox.ZMax) < 1e-9
        )
        job = self.cam.new_setup(self.doc, self.geometry.zero_on_face([self.plate], self.plate, bottom))
        op = self.cam.add_adaptive(job, operations.Adaptive(-10.0, z_step_mm=2.0), self.cam.add_tool(job, self.tool))
        self.doc.recompute()
        return job, op

    @staticmethod
    def cuts(op):
        """(x, y, z) of the ends of the cutting moves (G1, G2, G3)."""
        result = []
        for c in op.Path.Commands:
            if c.Name in ("G1", "G2", "G3") and "Z" in c.Parameters:
                result.append((c.Parameters.get("X", 0.0), c.Parameters.get("Y", 0.0), c.Parameters["Z"]))
        return result

    def test_adaptive_clears_what_the_setup_before_left(self):
        import time

        self.assertTrue(self.first.Operations.Group[0].Path.Commands)
        job, op = self.second()
        box = self.cuts(op)  # Setup 2 with a box with allowances
        self.assertAlmostEqual(min(z for _x, _y, z in box), -10.0, places=6)
        left = self.next.left(self.next.prepare_left(self.first), 120)
        self.next.set_stock_from_setup(job, self.first, left, 120)
        self.assertIsNotNone(self.next.material(job))
        began = time.perf_counter()
        op.touch()
        self.doc.recompute()
        took = time.perf_counter() - began
        cuts = self.cuts(op)
        self.assertTrue(cuts)
        lowest = min(z for _x, _y, z in cuts)
        self.assertAlmostEqual(lowest, -4.0, places=6)  # nothing left under Z-4
        self.assertLess(len(cuts), len(box) / 2)
        # the hole's 4 mm Setup 1 left are cleared, and nothing deeper in it
        # (x as in Setup 2: from the bottom, turned about X or about Y)
        def in_hole(x, y):
            return min(math.hypot(x - sx, y - sy) for sx in (self.HOLE[0], -self.HOLE[0]) for sy in (self.HOLE[1], -self.HOLE[1])) < 2.5  # fmt: skip

        self.assertTrue(any(in_hole(x, y) for x, y, z in cuts))
        self.assertFalse(any(in_hole(x, y) and z < -4.0 - 1e-6 for x, y, z in cuts))
        self.assertLess(took, 20.0)
        FreeCAD.Console.PrintMessage("Adaptive from the stock left: {:.2f} s, {} cuts (box: {})\n".format(took, len(cuts), len(box)))  # fmt: skip
        # FreeCAD's simulator: the stock left, made coarser
        began = time.perf_counter()
        shape = self.next.simulator_stock(job)
        took = time.perf_counter() - began
        self.assertLessEqual(len(shape.Faces), self.next.SIMULATOR_TRIANGLES)
        np.testing.assert_allclose([shape.BoundBox.ZMin, shape.BoundBox.ZMax], [-12.0, 0.0], atol=0.05)
        np.testing.assert_allclose([shape.BoundBox.XLength, shape.BoundBox.YLength], [42.0, 22.0], atol=0.05)
        self.assertLess(took, 10.0)
        # a box with allowances again: down to Z-10 again
        self.cam.set_stock(job, self.cam.model_stock.BoxStock())
        self.doc.recompute()
        self.assertIsNone(self.next.material(job))
        self.assertIsNone(self.next.simulator_stock(job))
        self.assertAlmostEqual(min(z for _x, _y, z in self.cuts(op)), -10.0, places=6)


if __name__ == "__main__":
    unittest.main()
