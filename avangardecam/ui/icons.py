# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Icon lookup: FreeCAD's resource icons first, then the module's own."""

import os

from PySide import QtCore, QtGui

from avangardecam import icon_path

PLACEHOLDER = "AvangardeCam_Placeholder.svg"


def load_resources():
    """Register the resource icons of the modules the catalog borrows from.

    Each import only loads the module's compiled resources; a missing module
    leaves its actions with the placeholder icon.
    """
    for module in ("Draft_rc", "PathGui", "MeasureGui", "SketcherGui"):
        try:
            __import__(module)
        except ImportError:
            pass


def get(name):
    """Return the QIcon for an icon name of actions.py."""
    if name:
        resource = ":/icons/{}.svg".format(name)
        if QtCore.QFile.exists(resource):
            return QtGui.QIcon(resource)
        own = icon_path(name if name.endswith(".svg") else name + ".svg")
        if os.path.exists(own):
            return QtGui.QIcon(own)
    return QtGui.QIcon(icon_path(PLACEHOLDER))
