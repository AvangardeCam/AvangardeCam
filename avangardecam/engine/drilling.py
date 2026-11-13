# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""FreeCAD's drilling operation, drilling the holes in the user's order,
each from its own top.

FreeCAD sorts the holes of a drilling (PathUtils.sort_locations) and
drills them all between the operation's StartDepth and FinalDepth. The
user picks the holes in the order the machine drills them, like the lines
of a contour, and holes picked in a model have each their own top and
depth. This proxy is FreeCAD's own Drilling (properties, path, task panel
in expert mode) but for that: it drills the holes in the order of its Base
features, each from its top to its depth (freecad_cam.drill_moves).
"""

import FreeCAD
import Part
import Path
import Path.Base.FeedRate as PathFeedRate
import Path.Base.Generator.drill as drill
import Path.Op.Drilling as PathDrilling


class Drilling(PathDrilling.ObjectDrilling):
    def __init__(self, obj, name, parentJob, tc=None):
        # FreeCAD takes the tool of the operation before it in the setup, else
        # the only one it supports; with more it asks: tc is the only one
        self._tool = tc
        try:
            super().__init__(obj, name, parentJob)
        finally:
            self._tool = None

    def isToolSupported(self, obj, tool):
        if getattr(self, "_tool", None) is not None:
            return tool is self._tool.Tool
        return super().isToolSupported(obj, tool)

    def circularHoleExecute(self, obj, holes):
        from avangardecam.engine import freecad_cam

        moves = freecad_cam.drill_moves(obj)
        if not moves:  # not one of AvangardeCam's drillings
            return super().circularHoleExecute(obj, holes)
        # as FreeCAD's Drilling, with the retract plane (R) over each hole's own top
        retract = obj.RetractHeight.Value - obj.StartDepth.Value
        self.commandlist.append(Path.Command("(Begin Drilling)"))
        self.commandlist.append(Path.Command("G90"))
        self.commandlist.append(Path.Command("G0", {"Z": obj.ClearanceHeight.Value}))
        obj.RetractMode = "G99" if obj.KeepToolDown else "G98"
        self.commandlist.append(Path.Command(obj.RetractMode))
        dwell = float(obj.DwellTime) if obj.DwellEnabled else 0.0
        peck = float(obj.PeckDepth.Value) if obj.PeckEnabled else 0.0
        chip_break = obj.chipBreakEnabled and obj.PeckEnabled
        first = True
        for x, y, top, tip in moves:
            self.commandlist.append(Path.Command("G0", {"X": x, "Y": y}))
            if first:
                self.commandlist.append(Path.Command("G0", {"Z": obj.SafeHeight.Value}))
                first = False
            edge = Part.makeLine(FreeCAD.Vector(x, y, top), FreeCAD.Vector(x, y, tip))
            try:
                commands = drill.generate(
                    edge, dwell, peck, 1, float(top + retract), chipBreak=chip_break, feedRetract=obj.feedRetractEnabled
                )
            except ValueError as exc:  # FreeCAD leaves such a hole out too
                Path.Log.info(exc)
                continue
            self.commandlist.extend(commands)
        self.commandlist.append(Path.Command("G80"))
        PathFeedRate.setFeedRate(self.commandlist, obj.ToolController)
