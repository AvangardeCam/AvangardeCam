# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Picking sketch lines in the 3D view.

A sketch line wins over the model: a sketch extracted from a face lies
exactly on the face's edges, so a click there hits the sketch line, the
model's edge and its faces. FreeCAD keeps only the first object along the
ray, which is often the model (its face, as FreeCAD prefers an edge over a
face only within one object). When the model's edge or face is picked and
a sketch line runs under the cursor (within FreeCAD's pick radius), the
selection moves to the line.

Clicks on sketch lines work as in Blender:
  click            this line only
  Shift+click      add the line (again: take it away)
  Ctrl+click       add the shortest way from the last line to this one
  Alt+click        the line's whole loop, starting with it (Shift+Alt adds it)

The order of the selection is the order of the clicks (FreeCAD keeps it),
which Contour tooling follows. FreeCAD itself clears the selection on a
plain or Shift click and adds on a Ctrl click; the modifiers of the click
are taken from the 3D view's mouse events, and the selection is rebuilt
right after FreeCAD's own.

The selected lines show the tool's direction with arrows (direction.py).
A plain click on an arrow turns its chain round and does not reach
FreeCAD, so the selection stays as it is.
"""

import FreeCAD
import FreeCADGui

from PySide import QtCore

from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry
from avangardecam.ui import direction

_SHIFT = QtCore.Qt.ShiftModifier
_CTRL = QtCore.Qt.ControlModifier
_ALT = QtCore.Qt.AltModifier


class _State:
    click = 0  # left-button presses in 3D views
    modifiers = QtCore.Qt.NoModifier  # of the last click
    active = None  # the click being handled; None for selections made by code
    # (sketch name, "EdgeN") and (model name, "FaceN"/"EdgeN") selected, in click order; the
    # element of a model made of other objects as FreeCAD names it ("Part__Feature.Face1")
    lines = []
    before_clear = []  # lines and model elements selected before the last clearing
    cleared_on = -1  # the click that cleared them
    busy = False  # rebuilding the selection
    pending = 0  # clicks waiting to rebuild the selection
    swallowed = False  # the press went to an arrow: so does its release
    next_view = 0  # numbers of the watched 3D views


def _project_sketch(obj):
    return geometry.is_sketch(obj) and cam.owner(obj) == ("sketch", obj)


def _current_lines():
    """Selected sketch lines and model elements (holes), in click order."""
    lines = []
    for selection in FreeCADGui.Selection.getSelectionEx("", 0):
        obj = selection.Object
        sketch = _project_sketch(obj)
        for sub in map(cam.plain_sub, selection.SubElementNames):
            if sketch and sub.startswith("Edge"):
                lines.append((obj.Name, sub))
            elif not sketch and _is_model_element(obj, sub):
                lines.append((obj.Name, sub))
    return lines


def _remember():
    _State.lines = _current_lines()
    direction.schedule()


def busy():
    """The selection is not settled yet: a click is rebuilding it."""
    return _State.busy or _State.pending > 0


def _sketch_line_under(doc, point):
    """(sketch name, "EdgeN") of a project sketch's line under the screen
    position of point (part coordinates), else None."""
    gui_doc = FreeCADGui.getDocument(doc.Name)
    view = getattr(gui_doc, "ActiveView", None) if gui_doc is not None else None
    if view is None or not hasattr(view, "getObjectsInfo"):
        return None
    x, y = view.getPointOnScreen(point)
    for info in view.getObjectsInfo((int(round(x)), int(round(y)))) or []:
        obj = doc.getObject(info.get("Object", ""))
        component = info.get("Component", "").split(".")[-1]
        if obj is not None and component.startswith("Edge") and _project_sketch(obj):
            return obj.Name, component
    return None


def _model_element_under(doc, obj, point):
    """Name of obj's face or edge under the screen position of point, else None."""
    gui_doc = FreeCADGui.getDocument(doc.Name)
    view = getattr(gui_doc, "ActiveView", None) if gui_doc is not None else None
    if view is None or not hasattr(view, "getObjectsInfo"):
        return None
    x, y = view.getPointOnScreen(point)
    for info in view.getObjectsInfo((int(round(x)), int(round(y)))) or []:
        component = info.get("Component", "").split(".")[-1]
        if info.get("Object") == obj.Name and component.startswith(("Face", "Edge")):
            return component
    return None


def _is_model(obj):
    found = cam.owner(obj)
    return found is not None and found[0] == "model"


def _is_model_element(obj, sub):
    """A face or edge of a project model (obj: the object clicked at the top)."""
    return cam.model_element(obj, sub) is not None


class _Observer:
    def addSelection(self, doc_name, obj_name, sub, pnt):
        if _State.busy or doc_name not in FreeCAD.listDocuments():
            return
        doc = FreeCAD.getDocument(doc_name)
        obj = doc.getObject(obj_name)
        if obj is not None and sub and not _project_sketch(obj):
            # an object inside a model (App::Part of a STEP file): named from the model
            obj, sub = cam.model_path(obj, sub)  # its sub without topological names
            obj_name = obj.Name
        line = None
        if obj is not None and sub:
            if _project_sketch(obj) and sub.split(".")[-1].startswith("Edge"):
                line = (obj_name, sub.split(".")[-1])
            elif _is_model_element(obj, sub):
                line = _sketch_line_under(doc, FreeCAD.Vector(*pnt))
                if line is None and _State.active is not None and _State.modifiers & _SHIFT:
                    line = (obj_name, sub)  # Shift+click adds a hole as it adds a line
        elif obj is not None and _State.active is not None and _State.modifiers & _SHIFT and _is_model(obj):
            # a click on a selected face selects the whole model: Shift+click takes the face away
            name = _model_element_under(doc, obj, FreeCAD.Vector(*pnt))
            line = (obj_name, name) if name else None
        _remember()
        if line is not None:
            click = _State.active
            _State.pending += 1
            # not inside FreeCAD's selection notification
            QtCore.QTimer.singleShot(0, lambda: _after_click(doc_name, obj_name, sub, line, click))

    def removeSelection(self, doc_name, obj_name, sub):
        if not _State.busy:
            _remember()

    def setSelection(self, doc_name):
        if not _State.busy:
            _remember()

    def clearSelection(self, doc_name):
        if not _State.busy:
            _State.before_clear = _State.lines
            _State.cleared_on = _State.active
            _State.lines = []
            direction.schedule()


def _after_click(doc_name, obj_name, sub, clicked, click):
    _State.pending -= 1
    _rebuild(doc_name, obj_name, sub, clicked, click)


def _rebuild(doc_name, obj_name, sub, clicked, click):
    """Rebuild the selection after a click that picked a sketch line (or
    the model under one), or Shift+clicked the model (a hole), as the
    click's modifiers ask."""
    if doc_name not in FreeCAD.listDocuments():
        return
    doc = FreeCAD.getDocument(doc_name)
    obj = doc.getObject(obj_name)
    if obj is None or not FreeCADGui.Selection.isSelected(obj, sub):
        return  # the selection changed meanwhile
    mods = _State.modifiers if click is not None else QtCore.Qt.NoModifier
    current = _current_lines()
    others = [p for p in current if p != clicked]
    previous = _State.before_clear if click is not None and _State.cleared_on == click else others
    sketch = doc.getObject(clicked[0])
    if not _project_sketch(sketch):
        mods &= _SHIFT  # a model's element (a hole): Shift adds or takes it away, nothing else
    if mods & _ALT:
        base = list(previous) if mods & _SHIFT else []
        wanted = base + [(clicked[0], e) for e in geometry.line_loop(sketch, clicked[1]) if (clicked[0], e) not in base]
    elif mods & _SHIFT:
        wanted = [p for p in previous if p != clicked] if clicked in previous else list(previous) + [clicked]
    elif mods & _CTRL:
        mine = [e for s, e in others if s == clicked[0]]
        path = [(clicked[0], e) for e in geometry.line_path(sketch, mine, clicked[1])]
        wanted = others + [p for p in path if p not in others] + [clicked]
    else:
        wanted = [clicked]
    if wanted != current or obj is not sketch:
        _select(doc_name, wanted)


def _select(doc_name, lines):
    _State.busy = True
    try:
        FreeCADGui.Selection.clearSelection()
        for sketch_name, edge in lines:
            FreeCADGui.Selection.addSelection(doc_name, sketch_name, edge)
    finally:
        _State.busy = False
    _remember()


_MODIFIERS = _SHIFT | _CTRL | _ALT


def _arrow_under(viewport, event):
    """The direction arrow under the mouse (direction.arrow_at), or None."""
    if not direction.shown():
        return None  # every mouse move comes here
    found = _view_of(viewport)
    if found is None:
        return None
    doc_name, view = found
    pos = event.position() if hasattr(event, "position") else event.pos()
    return direction.arrow_at(doc_name, view, viewport, pos)


class _ClickWatcher(QtCore.QObject):
    """Keeps the keyboard modifiers of the clicks in the 3D views; plain
    clicks on direction arrows go to the arrows."""

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.MouseMove and event.buttons() == QtCore.Qt.NoButton:
            arrow = _arrow_under(watched, event)
            direction.hover(arrow)
            if arrow is not None:
                # only the arrow shows what a click takes, not the face under it
                FreeCADGui.Selection.clearPreselection()
                return True
        elif kind == QtCore.QEvent.Leave:
            direction.hover(None)
        elif kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
            if event.button() == QtCore.Qt.LeftButton:
                if kind == QtCore.QEvent.MouseButtonPress and not event.modifiers() & _MODIFIERS:
                    arrow = _arrow_under(watched, event)
                    if arrow is not None:
                        _State.swallowed = True
                        direction.turn_round(arrow)
                        return True
                if kind == QtCore.QEvent.MouseButtonRelease and _State.swallowed:
                    _State.swallowed = False
                    return True
                if kind == QtCore.QEvent.MouseButtonPress:
                    _State.click += 1
                _State.modifiers = event.modifiers()
                _State.active = _State.click
                if kind == QtCore.QEvent.MouseButtonRelease:
                    # FreeCAD selects while handling the release
                    QtCore.QTimer.singleShot(0, _end_click)
        return False


def _end_click():
    _State.active = None


_observer = None
_watcher = None


def _views():
    for name in FreeCAD.listDocuments():
        gui_doc = FreeCADGui.getDocument(name)
        for view in gui_doc.mdiViewsOfType("Gui::View3DInventor") if gui_doc is not None else []:
            yield name, view


def _view_of(viewport):
    """(document name, 3D view) of a watched viewport."""
    number = viewport.property("AvangardeCamWatched")
    for name, view in _views():
        if view.graphicsView().viewport().property("AvangardeCamWatched") == number:
            return name, view
    return None


def watch_views():
    """Watch the clicks of every open 3D view (new views come with new documents)."""
    if _watcher is None:
        return
    for _name, view in _views():
        viewport = view.graphicsView().viewport()
        if not viewport.property("AvangardeCamWatched"):
            viewport.installEventFilter(_watcher)
            _State.next_view += 1
            viewport.setProperty("AvangardeCamWatched", _State.next_view)


def start():
    global _observer, _watcher
    if _observer is None:
        _observer = _Observer()
        FreeCADGui.Selection.addObserver(_observer)
    if _watcher is None:
        _watcher = _ClickWatcher(FreeCADGui.getMainWindow())
    watch_views()
    direction.start()
    direction.schedule()


def stop():
    global _observer
    if _observer is not None:
        FreeCADGui.Selection.removeObserver(_observer)
        _observer = None
    direction.stop()


def selections():
    """(sketch, ["EdgeN", ...]) of each project sketch with selected lines,
    in the order they were clicked; [] when the whole sketch is selected."""
    found = []
    for selection in FreeCADGui.Selection.getSelectionEx():
        obj = selection.Object
        if not _project_sketch(obj):
            continue
        subs = [s.split(".")[-1] for s in selection.SubElementNames]
        edges = [s for s in subs if s.startswith("Edge")]
        if subs and not edges:
            continue  # only its points
        found.append((obj, edges))
    return found


def selected_lines():
    """(sketch, ["EdgeN", ...]) of the selected lines of one project sketch,
    in the order they were clicked; [] when the whole sketch is selected
    (all its lines). None when no sketch is selected; ValueError when lines
    of more than one sketch are."""
    found = selections()
    if len(found) > 1:
        raise ValueError("Select lines of one sketch only.")
    return found[0] if found else None
