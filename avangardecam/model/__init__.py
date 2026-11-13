# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Model layer: what the user wants machined, in mm, mm/min and rpm.

Plain Python on purpose: no FreeCAD and no Qt imports anywhere below this
package, so it can be tested with any Python interpreter and survives
FreeCAD API changes. The engine layer translates it to FreeCAD objects.
"""
