# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Engine layer: translates the model to FreeCAD CAM objects and back.

freecad_cam is the only part of AvangardeCam that knows the FreeCAD CAM API;
geometry works on the part's shapes (faces, zero points, sketches).
"""


class ProjectError(Exception):
    """An action that would leave the project in a wrong state; the message
    is meant for the user."""
