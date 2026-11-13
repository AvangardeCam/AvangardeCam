# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""AvangardeCam workbench: switches the main window to the AvangardeCam
layout while active.

Lives in the package rather than in InitGui.py, because FreeCAD executes
InitGui.py in a namespace whose module-level names are not visible from
the workbench methods.
"""

import FreeCAD
import FreeCADGui

# Toolbars every Python workbench inherits from the standard workbench.
# Removing them leaves ToolBarManager nothing to show while AvangardeCam is
# active; other workbenches bring them back with their own toolbar lists.
_STANDARD_TOOLBARS = (
    "File",
    "Edit",
    "Clipboard",
    "Workbench",
    "Macro",
    "View",
    "Individual Views",
    "Structure",
    "Help",
)


class AvangardeCamWorkbench(FreeCADGui.Workbench):
    """A clear CAD/CAM interface that drives FreeCAD."""

    def __init__(self):
        import avangardecam

        self.__class__.Icon = avangardecam.icon_path("AvangardeCamWorkbench.svg")
        self.__class__.MenuText = "AvangardeCam"
        self.__class__.ToolTip = "AvangardeCam: a clear CAD/CAM interface on the FreeCAD engine"

    def Initialize(self):
        from avangardecam.ui import icons, select_surfaces

        icons.load_resources()
        select_surfaces.register()
        existing = self.listToolbars()
        for name in _STANDARD_TOOLBARS:
            if name in existing:
                self.removeToolbar(name)
        FreeCAD.Console.PrintLog("Loading AvangardeCam workbench, done.\n")

    def Activated(self):
        from avangardecam import profile
        from avangardecam.ui.layout import LAYOUT

        profile.apply_colors()
        LAYOUT.activate()
        FreeCAD.Console.PrintLog("AvangardeCam workbench activated.\n")

    def Deactivated(self):
        from avangardecam.ui import playback
        from avangardecam.ui.layout import LAYOUT

        playback.close()  # a window of AvangardeCam's
        LAYOUT.deactivate()
        FreeCAD.Console.PrintLog("AvangardeCam workbench deactivated.\n")

    def GetClassName(self):
        return "Gui::PythonWorkbench"
