# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Operation order tests. The list ones are plain Python:

    python3 -m unittest avangardecam.tests.test_operation_order   (from src/Mod/AvangardeCam)

the engine ones run inside FreeCADCmd (avangardecam/tests/run.py) and are
skipped without FreeCAD.
"""

import unittest

from avangardecam.engine.operation_order import moved

try:
    import FreeCAD
except ImportError:
    FreeCAD = None


class TestMoved(unittest.TestCase):
    def test_up(self):
        self.assertEqual(moved("ABCD", "C", 0), list("CABD"))
        self.assertEqual(moved("ABCD", "D", 1), list("ADBC"))

    def test_down(self):
        # before the one at index of the old order: past itself counts one less
        self.assertEqual(moved("ABCD", "A", 2), list("BACD"))
        self.assertEqual(moved("ABCD", "A", 4), list("BCDA"))
        self.assertEqual(moved("ABCD", "B", 3), list("ACBD"))

    def test_in_place(self):
        for index in (1, 2):  # before itself or before the next one
            self.assertEqual(moved("ABCD", "B", index), list("ABCD"))

    def test_out_of_range_clamped(self):
        self.assertEqual(moved("ABC", "B", -3), list("BAC"))
        self.assertEqual(moved("ABC", "B", 99), list("ACB"))


@unittest.skipIf(FreeCAD is None, "needs FreeCAD (avangardecam/tests/run.py)")
class TestMoveEngine(unittest.TestCase):
    """Three contours on the top of the part with a hole of test_engine."""

    def setUp(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.model import library, operations
        from avangardecam.tests.test_engine import TestEngine
        from avangardecam.tests.test_model import LIBRARY

        self.cam = cam
        self.helpers = TestEngine("setUp")
        self.helpers.setUp()
        self.helpers.library = library.load(LIBRARY)
        _body, self.job, tc, sketch = self.helpers.contour_setup()
        self.ops = [cam.add_contour(self.job, sketch, operations.Contour(-d), tc) for d in (1.0, 2.0, 3.0)]
        self.doc = self.helpers.doc

    def tearDown(self):
        self.helpers.tearDown()

    def labels(self):
        return [op.Label for op in self.cam.operations(self.job)]

    def test_move_down_and_up(self):
        from avangardecam.engine import operation_order

        first, second, third = self.ops
        self.assertTrue(operation_order.move(self.job, first, 3))
        self.assertEqual(self.cam.operations(self.job), [second, third, first])
        self.assertTrue(operation_order.move(self.job, first, 0))
        self.assertEqual(self.cam.operations(self.job), [first, second, third])

    def test_in_place_changes_nothing(self):
        from avangardecam.engine import operation_order

        self.assertFalse(operation_order.move(self.job, self.ops[1], 1))
        self.assertFalse(operation_order.move(self.job, self.ops[1], 2))
        self.assertEqual(self.cam.operations(self.job), self.ops)

    def test_program_follows(self):
        from avangardecam.engine import operation_order

        operation_order.move(self.job, self.ops[2], 0)
        program = self.cam.nc_program(self.doc, "Order")
        self.assertEqual(
            [op.label for op in program.setups[0].operations],
            [self.ops[2].Label, self.ops[0].Label, self.ops[1].Label],
        )
        self.assertEqual([op.Label for op in self.job.Operations.Group], self.labels())

    def test_undo_one_step(self):
        from avangardecam.engine import operation_order

        self.doc.UndoMode = 1
        self.doc.openTransaction("Move operation")
        operation_order.move(self.job, self.ops[0], 2)
        self.doc.commitTransaction()
        self.assertEqual(self.cam.operations(self.job), [self.ops[1], self.ops[0], self.ops[2]])
        self.doc.undo()
        self.assertEqual(self.cam.operations(self.job), self.ops)
        self.doc.redo()
        self.assertEqual(self.cam.operations(self.job), [self.ops[1], self.ops[0], self.ops[2]])
