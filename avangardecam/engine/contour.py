# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""FreeCAD's Engrave operation, running a contour's passes in the user's
order.

Engrave sorts the wires of a shape by where they lie and runs each of them
on all its Z levels. A contour has XY passes beside its lines and Z
levels, in an order the user chose (model Contour.cuts). This proxy is
FreeCAD's own Engrave (properties, path, task panel in expert mode) but
for that: it runs the cuts of freecad_cam.contour_cuts, chain by chain.
Between the cuts of a chain the tool goes up to the safe height; going
down again it comes fast to just above where the same pass cut before
(the tool cleared that much on its way down there).
"""

import Path
import Path.Op.Engrave as PathEngrave

from avangardecam.model import operations as model_operations


class Contour(PathEngrave.ObjectEngrave):
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

    def opExecute(self, obj):
        from avangardecam.engine import freecad_cam

        chains = freecad_cam.contour_cuts(obj)
        if chains is None:  # not one of AvangardeCam's contours
            return super().opExecute(obj)
        clearance, safe = obj.ClearanceHeight.Value, obj.SafeHeight.Value
        commands = self.commandlist
        commands.append(Path.Command("G0", {"Z": clearance, "F": self.vertRapid}))
        for cuts in chains:
            done = {}  # XY pass: depth it cut last
            at = None
            for i, (index, run, z) in enumerate(cuts):
                start = run.centre[0].valueAt(run.centre[0].FirstParameter)
                if i == 0:  # as Engrave: up to the clearance height, over the start, down to the safe height
                    commands.append(Path.Command("G0", {"Z": clearance, "F": self.vertRapid}))
                else:
                    commands.append(Path.Command("G0", {"Z": safe, "F": self.vertRapid}))
                if at is None or not Path.Geom.pointsCoincide(at, start):
                    commands.append(Path.Command("G0", {"X": start.x, "Y": start.y, "F": self.horizRapid}))
                above = done.get(index)
                if above is not None and above + model_operations.SAFETY_MM < safe:
                    commands.append(Path.Command("G0", {"Z": above + model_operations.SAFETY_MM, "F": self.vertRapid}))  # fmt: skip
                elif i == 0:
                    commands.append(Path.Command("G0", {"Z": safe, "F": self.vertRapid}))
                commands.append(Path.Command("G1", {"X": start.x, "Y": start.y, "Z": z, "F": self.vertFeed}))
                for edge in run.centre:
                    for command in Path.Geom.cmdsForEdge(edge):
                        params = command.Parameters
                        params.update({"Z": z, "F": self.horizFeed})
                        commands.append(Path.Command(command.Name, params))
                last = run.centre[-1]
                at = last.valueAt(last.LastParameter)
                done[index] = z
            commands.append(Path.Command("G0", {"Z": clearance, "F": self.vertRapid}))
        self.wires = []
        # the last command is a move to clearance, which is automatically added by PathOp
        if commands:
            commands.pop()
