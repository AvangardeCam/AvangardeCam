# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Activate geometry, on its own: in the menu of an operation in the list.

Selects what the operation was made on, as if the user had clicked it
again, so another operation can be made on the same geometry:

- a contour: its sketch lines in the order the tool follows them, the
  arrows turned the way it runs (a contour of all lines: the whole sketch);
- a drilling or thread milling: its sketch circles or the holes picked in
  the model, in the order they are drilled;
- an adaptive clearing or a facing: the faces picked in the model (an
  adaptive clearing around the whole model selects nothing: made with
  nothing selected, that is what makes it again).

A model made of other objects (an App::Part from a STEP file) names its
faces and edges from its parts when clicked ("Part__Feature.Face1"); the
operation keeps the model's own names ("Face12"), found again here.
"""

import FreeCAD
import FreeCADGui

from avangardecam import tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.ui import direction, picking

STATUS_TIMEOUT_MS = 4000


def _status(message):
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)


def _part_paths(obj, prefix=""):
    """Faces and edges of obj as a click on obj names them: "FaceN" of a
    shape, "Child.FaceN" of an object inside it."""
    if obj.isDerivedFrom("Part::Feature"):
        import Part

        shape = Part.getShape(obj, transform=False)
        faces = ["{}Face{}".format(prefix, i) for i in range(1, len(shape.Faces) + 1)]
        return faces + ["{}Edge{}".format(prefix, i) for i in range(1, len(shape.Edges) + 1)]
    paths = []
    for sub in obj.getSubObjects():
        child = obj.getSubObject(sub, retType=1)
        if child is not None:
            paths += _part_paths(child, prefix + sub)
    return paths


def _click_names(model, names):
    """The names a click gives the model's own elements ("Face12")."""
    if model.isDerivedFrom("Part::Feature"):
        return list(names)
    found = {}
    for path in _part_paths(model):
        element = cam.model_element(model, path)
        if element is not None:
            found.setdefault(element[1], path)
    return [found[name] for name in names if name in found]


class Geometry:
    """What an operation was made on: elements to select ((object, sub);
    sub "" for a whole sketch) in click order, and the contour chains the
    tool runs backwards ((sketch, [lines]) each, the others forwards)."""

    def __init__(self):
        self.elements = []
        self.chains = []  # (sketch, lines, backwards)
        self.counted = {}  # "lines", "circles", "holes", "faces" or "edges": how many
        self.whole_sketch = False

    def add(self, kind, elements, count=None):
        self.elements += elements
        self.counted[kind] = self.counted.get(kind, 0) + (len(elements) if count is None else count)

    def text(self):
        words = {
            "lines": (tr("1 line"), tr("{} lines")),
            "circles": (tr("1 circle"), tr("{} circles")),
            "holes": (tr("1 hole"), tr("{} holes")),
            "faces": (tr("1 face"), tr("{} faces")),
            "edges": (tr("1 edge"), tr("{} edges")),
        }
        parts = [words[kind][0] if n == 1 else words[kind][1].format(n) for kind, n in self.counted.items() if n]
        return ", ".join(([tr("the whole sketch")] if self.whole_sketch else []) + parts)


def geometry_of(op):
    """The geometry an operation of AvangardeCam was made on, else None."""
    from avangardecam.engine import facing as engine_facing
    from avangardecam.engine import slot as engine_slot

    found = Geometry()
    helpers = cam.helper_objects(op)
    for helper in helpers:
        sketch = getattr(helper, "Sketch", None)
        model = getattr(helper, "Model", None)
        if sketch is not None:
            lines = list(getattr(helper, "Edges", []))
            contour = hasattr(helper, "Reversed")
            if not lines:
                found.elements.append((sketch, ""))
                found.whole_sketch = True
                if hasattr(helper, "Reversed"):
                    found.chains.append((sketch, [], False))  # all lines: none run backwards
                continue
            if contour:
                found.add("lines", [(sketch, name) for name in lines])
                found.chains.append((sketch, lines, bool(helper.Reversed)))
            else:  # all the arcs of a hole made of them
                found.add("circles", [(sketch, arc) for name in lines for arc in geometry.hole_lines(sketch, name)], len(lines))  # fmt: skip
        elif model is not None:
            found.add("holes", [(model, name) for name in _click_names(model, list(helper.Holes))])
    if helpers:
        return found
    if cam.adaptive_of(op) is None and engine_facing.facing_of(op) is None and engine_slot.slot_milling_of(op) is None:
        return None
    for base, names in getattr(op, "Base", []):
        owner = cam.owner(base)
        if owner is not None and owner[0] == "model":
            for kind, prefix in (("faces", "Face"), ("edges", "Edge")):  # a slot may be picked by an edge
                picked = [name for name in names if name.startswith(prefix)]
                if picked:
                    found.add(kind, [(owner[1], name) for name in _click_names(owner[1], picked)])
    return found


def activate(op):
    """Select the geometry of an operation (geometry_of); False when it has none."""
    found = geometry_of(op)
    if found is None:
        return False
    doc = op.Document
    picking._select(doc.Name, [(obj.Name, sub) for obj, sub in found.elements])
    direction.refresh()  # the arrows of the lines selected now, before turning them
    for sketch, lines, backwards in found.chains:
        if not lines:
            # the whole sketch: arrows turned while it was selected before stay turned
            for _turn in range(len(direction.backwards(sketch))):
                turned = direction.backwards(sketch)
                if turned:
                    direction.turn_round((doc.Name, sketch.Name, sorted(turned)[0]))
        elif bool(direction.backwards(sketch) & set(lines)) != backwards:
            direction.turn_round((doc.Name, sketch.Name, lines[0]))
    if not found.elements:
        _status(tr("{}: the whole model, nothing to select.").format(op.Label))
    else:
        _status(tr("{}: {} selected.").format(op.Label, found.text()))
    return True


def add_to_menu(menu, op):
    """Activate geometry in the menu of an operation."""
    action = menu.addAction(tr("Activate geometry"))
    action.setObjectName("AvangardeCamActivateGeometry")
    action.setToolTip(tr("Select what it was made on, as it uses it: for another operation on the same geometry"))
    action.setEnabled(geometry_of(op) is not None)
    action.triggered.connect(lambda: activate(op))
    return action
