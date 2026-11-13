# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""AvangardeCam preference profile.

Applied once per PROFILE_VERSION, so users can still change any of these
settings afterwards; raise PROFILE_VERSION to push a changed profile.
Only settings the AvangardeCam layout needs are touched: navigation style,
units and the rest of the user's FreeCAD preferences stay as they are.
"""

import FreeCAD

from avangardecam import params

PROFILE_VERSION = 1

WORKBENCH = "AvangardeCamWorkbench"


def _group(path):
    return FreeCAD.ParamGet("User parameter:" + path)


def apply_once():
    """Apply the profile if this version was not applied yet.

    Returns True when settings were written.
    """
    if params().GetInt("ProfileVersion", 0) >= PROFILE_VERSION:
        return False

    _group("BaseApp/Preferences/General").SetString("AutoloadModule", WORKBENCH)
    # the 3D view, not FreeCAD's start page, is the first thing to see
    _group("BaseApp/Preferences/Mod/Start").SetBool("ShowOnStartup", False)
    # FreeCAD 1.1 puts the Tasks panel in overlay mode (floating over the 3D
    # view) by default; hiding it there leaves an empty frame over the view,
    # so it becomes a normal panel. FreeCAD reads this after InitGui.py.
    _group("BaseApp/MainWindow/DockWindows/OverlayRight").SetString("Widgets", "")

    params().SetInt("ProfileVersion", PROFILE_VERSION)
    FreeCAD.Console.PrintMessage("AvangardeCam: profile {} applied.\n".format(PROFILE_VERSION))
    return True


# 0xRRGGBBAA. Selected is red; the mouse-over colour must be neither red
# (selected) nor green (sketch lines, see ui/scene.py).
SELECTION_COLOR = 0xDC1E1EFF
HIGHLIGHT_COLOR = 0xE1C814FF


def apply_colors():
    """Selection colours of the 3D view; applied at every start, as they
    carry meaning in AvangardeCam. Open views take them at once."""
    view = _group("BaseApp/Preferences/View")
    if view.GetUnsigned("SelectionColor", 0) != SELECTION_COLOR:
        view.SetUnsigned("SelectionColor", SELECTION_COLOR)
    if view.GetUnsigned("HighlightColor", 0) != HIGHLIGHT_COLOR:
        view.SetUnsigned("HighlightColor", HIGHLIGHT_COLOR)
