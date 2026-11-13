# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""AvangardeCam package: shared paths, parameters and the translate helper.

FreeCAD is imported lazily, so the model layer (avangardecam.model) stays
importable and testable with a plain Python interpreter.
"""

import os

PARAM_PATH = "User parameter:BaseApp/Preferences/Mod/AvangardeCam"

# Qt translation context of every user-visible text of the module
CONTEXT = "AvangardeCam"

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_MOD_DIR = os.path.dirname(_PKG_DIR)


def params():
    """Return the AvangardeCam parameter group."""
    import FreeCAD

    return FreeCAD.ParamGet(PARAM_PATH)


def forget_last_values():
    """Forget the values remembered from earlier work: every parameter named
    Last... (the last tool, depth, passes and folders of the dialogs). The
    GUI tests start with it, so they run the same on a used profile."""
    group = params()
    remove = {
        "String": group.RemString,
        "Float": group.RemFloat,
        "Integer": group.RemInt,
        "Unsigned": group.RemUnsigned,
        "Boolean": group.RemBool,
    }
    for kind, name, _value in group.GetContents() or ():
        if name.startswith("Last") and kind in remove:
            remove[kind](name)


def icon_path(name):
    """Return the absolute path of an icon shipped with the module."""
    return os.path.join(_MOD_DIR, "Resources", "icons", name)


def image_path(name):
    """Return the absolute path of a picture shipped with the module."""
    return os.path.join(_MOD_DIR, "Resources", "images", name)


def tool_library_path():
    """The shop's tool library file: the ToolLibraryFile parameter, or the
    library shipped with the module (the shop's tool table)."""
    path = params().GetString("ToolLibraryFile", "")
    return path or os.path.join(_MOD_DIR, "Resources", "library", "tools.json")


def tr(text):
    """Translate an English source text for display."""
    import FreeCAD

    return FreeCAD.Qt.translate(CONTEXT, text)
