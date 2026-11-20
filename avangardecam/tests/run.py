# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Run all AvangardeCam unit tests inside FreeCADCmd:

    AC_TEST_REPORT=report.txt FreeCADCmd <Mod folder>/AvangardeCam/avangardecam/tests/run.py

FreeCADCmd swallows the console output of scripts, so the result goes to
AC_TEST_REPORT (default: avangardecam_tests.txt in the temp directory).
FreeCAD's own -t runner needs the TestApp module, which is not built.
"""

import os
import tempfile
import unittest

import FreeCAD

report = os.environ.get(
    "AC_TEST_REPORT", os.path.join(tempfile.gettempdir(), "avangardecam_tests.txt")
)
suite = unittest.TestSuite()
for name in ("avangardecam.tests.test_model", "avangardecam.tests.test_post", "avangardecam.tests.test_engine", "avangardecam.tests.test_measure", "avangardecam.tests.test_facing", "avangardecam.tests.test_slot", "avangardecam.tests.test_stock_size", "avangardecam.tests.test_helix", "avangardecam.tests.test_verify", "avangardecam.tests.test_machine", "avangardecam.tests.test_cycle_time", "avangardecam.tests.test_operation_order", "avangardecam.tests.test_playback", "avangardecam.tests.test_contour_relative", "avangardecam.tests.test_contour_from_below", "avangardecam.tests.test_start_stock", "avangardecam.tests.test_custom_stock", "avangardecam.tests.test_deburring", "avangardecam.tests.test_move_zero", "avangardecam.tests.test_circle_zero", "avangardecam.tests.test_op_zero", "avangardecam.tests.test_post_zero", "avangardecam.tests.test_tilted", "avangardecam.tests.test_cutting_data"):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
with open(report, "w") as stream:
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    stream.write("\nRESULT: {}\n".format("OK" if result.wasSuccessful() else "FAILED"))
FreeCAD.Console.PrintMessage("AvangardeCam tests: {}\n".format(report))
