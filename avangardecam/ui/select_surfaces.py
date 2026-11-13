# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Select all surfaces, on its own: first in the 3D view's right-click menu.

Selects every face of the project's models, as if each one had been
Shift+clicked: one by one, so the measures and the operations that take
faces see them as clicked faces. A model made of other objects (an
App::Part from a STEP file) is selected through its parts, the way a click
names them ("Part__Feature.Face1"); hidden parts are left out.
"""

import FreeCAD
import FreeCADGui

from avangardecam import tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.ui import picking

COMMAND = "AvangardeCam_SelectAllSurfaces"
WORKBENCH = "AvangardeCamWorkbench"
STATUS_TIMEOUT_MS = 4000


def _status(message):
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)


def _visible(obj):
    view = getattr(obj, "ViewObject", None)
    return view is None or view.Visibility


def face_names(obj, prefix=""):
    """The faces of obj as a click on obj names them: "FaceN" of a shape,
    "Child.FaceN" of an object inside it (an App::Part)."""
    if obj.isDerivedFrom("Part::Feature"):
        import Part

        shape = Part.getShape(obj, transform=False)
        return ["{}Face{}".format(prefix, i) for i in range(1, len(shape.Faces) + 1)]
    names = []
    for sub in obj.getSubObjects():
        child = obj.getSubObject(sub, retType=1)
        if child is not None and _visible(child):
            names += face_names(child, prefix + sub)
    return names


def surfaces(doc):
    """(model name, face name) of every face of the project's visible models."""
    return [(model.Name, name) for model in cam.models(doc) if _visible(model) for name in face_names(model)]


def select_all(doc):
    """Select every face of the project's models; their number."""
    found = surfaces(doc)
    picking._select(doc.Name, found)  # code's selection: no click to rebuild it after
    return len(found)


class SelectAllSurfaces:
    def GetResources(self):
        return {
            "MenuText": tr("Select all surfaces"),
            "ToolTip": tr("Select every face of the model"),
        }

    def IsActive(self):
        return bool(cam.models(FreeCAD.ActiveDocument))

    def Activated(self):
        doc = FreeCAD.ActiveDocument
        count = select_all(doc)
        _status(tr("Selected surfaces: {}").format(count))


class _FirstInMenu:
    """Puts the command at the top of the 3D view's menu. A workbench can
    only add to the end of it (before FreeCAD's Navigation styles); a
    manipulator inserts before FreeCAD's first item. Manipulators work in
    every workbench: only in AvangardeCam's this one does something."""

    def modifyContextMenu(self, recipient):
        workbench = FreeCADGui.activeWorkbench()
        if recipient != "View" or workbench is None or workbench.name() != WORKBENCH:
            return []
        # FreeCAD's first item: Link Actions, which it adds only with a document open
        first = "Link Actions" if FreeCAD.ActiveDocument is not None else "Std_ViewFitAll"
        return [{"insert": COMMAND, "menuItem": first}, {"insert": "Separator", "menuItem": first}]


_manipulator = None


def register():
    global _manipulator
    if COMMAND not in FreeCADGui.listCommands():
        FreeCADGui.addCommand(COMMAND, SelectAllSurfaces())
    if _manipulator is None:
        _manipulator = _FirstInMenu()
        FreeCADGui.addWorkbenchManipulator(_manipulator)
