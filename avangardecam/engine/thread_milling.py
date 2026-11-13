# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""FreeCAD's thread milling operation, milling the thread as the shop's
programs do.

FreeCAD's Thread Milling cuts in passes of growing radius between the
thread's minor and major diameter, from a lead-in "elevator" position,
holes sorted. The shop's way (model.threads) is one helix at the major
diameter from the top of each hole down, repeated for each pass, in the
order the user picked the holes. This proxy is FreeCAD's own operation
(properties, task panel in expert mode) but its path is that helix, run
by the tool centre (freecad_cam.thread_moves): for the 3D view and the
simulation; the NC program has it with the radius compensation (RR).
"""

import Path
import Path.Base.FeedRate as PathFeedRate
import Path.Op.ThreadMilling as PathThreadMilling

from avangardecam.model import nc

_G = {nc.RAPID: "G0", nc.LINE: "G1"}


class ThreadMilling(PathThreadMilling.ObjectThreadMilling):
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

        if freecad_cam.thread_milling_of(obj) is None:  # not one of AvangardeCam's
            return super().circularHoleExecute(obj, holes)
        try:
            moves = freecad_cam.thread_moves(obj)
        except freecad_cam.ProjectError as exc:  # e.g. another tool chosen in expert mode
            Path.Log.error("{}: {}".format(obj.Label, exc))
            return
        self.commandlist.append(Path.Command("(Begin Thread Milling)"))
        position = [None, None, None]
        for move in moves:
            p = {axis: value for axis, value in zip("XYZ", (move.x, move.y, move.z)) if value is not None}
            if move.kind == nc.ARC:
                p["I"] = move.center[0] - position[0]
                p["J"] = move.center[1] - position[1]
                name = "G2" if move.clockwise else "G3"
            else:
                name = _G[move.kind]
            self.commandlist.append(Path.Command(name, p))
            position = [move.x, move.y, move.z]
        PathFeedRate.setFeedRate(self.commandlist, obj.ToolController)
