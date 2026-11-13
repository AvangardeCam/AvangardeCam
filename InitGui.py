# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Registers the AvangardeCam workbench (see avangardecam/workbench.py)."""

import FreeCADGui

from avangardecam import profile
from avangardecam.workbench import AvangardeCamWorkbench

FreeCADGui.addWorkbench(AvangardeCamWorkbench)

# FreeCAD runs this before it picks the start workbench, so on the first
# start the profile makes AvangardeCam the start workbench right away
profile.apply_once()
