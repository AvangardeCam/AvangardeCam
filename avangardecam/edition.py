# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""What this version of AvangardeCam shows, in one place.

FIVE_AXES: whether the zero point can be turned (Move 0-Point "5 axes")
and the postprocessors of machines that tilt (a turning head) are offered.
The tested version (branch main) moves the zero point only: 3 axes. The
code under it is the same in both versions, so a fix reaches both; a
project that already has a turned zero point still plays and verifies.
"""

FIVE_AXES = True
