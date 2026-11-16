# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""What the 3D view shows: the part as it is clamped in the active setup.

FreeCAD computes a setup in its Job's coordinates, where the part is moved
by the inverse of the setup's zero point. The original models are shown
(the user's sketches lie on them) and the Job's clones hidden, and the
Job's own objects (stock, operations and the axis cross FreeCAD draws at
the Job's origin) are drawn moved by the zero point, so the paths lie on
the part and the axis cross sits on the zero point. Then the whole view is
drawn in the active setup's coordinates (a transform on top of each 3D
view's scene, view_placement): the zero point at the origin, the tool's
axis up. So FreeCAD's navigation cube and its Top, Front, ... views are
those of the setup, as on the machine. Points of the document are on the
screen where to_view puts them. Only the drawing changes; the document is
touched for visibility only.

In expert mode (plain FreeCAD) the view goes back to FreeCAD's own: the
active setup's clones in the Job's coordinates.
"""

import FreeCAD
import FreeCADGui

from PySide import QtCore

from avangardecam.engine import freecad_cam as cam

_NODE_NAME = "AvangardeCamZeroPoint"

SKETCH_COLOR = (0.0, 0.66, 0.0)
# model edges are 2 px wide (FreeCAD's default)
SKETCH_LINE_WIDTH = 4.0
SKETCH_POINT_SIZE = 5.0
# a sketch on a face lies exactly on the model's edges: drawn a hair nearer
# to the eye (a share of the depth range), its lines cover the black ones
_NEARER_NAME = "AvangardeCamSketchNearer"
_NEARER_RANGE = (0.0, 0.9999)

# the path of the operation selected in the list: its cutting moves drawn
# red and wide over it (FreeCAD's own colours stay)
PATH_HIGHLIGHT_COLOR = (1.0, 0.0, 0.0)
PATH_HIGHLIGHT_WIDTH = 3.0
_HIGHLIGHT_NAME = "AvangardeCamPathHighlight"
# a contour with radius compensation: the tool goes down with its centre,
# the lines show where its edge cuts, yellow lines join the two
PATH_LINK_COLOR = (1.0, 1.0, 0.0)
_DRAWING_NAME = "AvangardeCamPathDrawing"
_FREECAD_LINES_NAME = "AvangardeCamFreeCADLines"
_FRAME_NAME = "AvangardeCamSetupFrame"
# the transform goes before this node of a view's scene: the lights stay
_FRAME_BEFORE = "EditingRoot"
_CUTTING = ("G1", "G2", "G3", "G01", "G02", "G03")
# arcs drawn as lines this close to them, mm
_DEFLECTION_MM = 0.01

# document name -> Job name of the setup the user works on (not saved)
_active = {}
# document name -> name of the operation whose path is red (not saved)
_highlighted = {}
# document name -> names of the operations hidden in 3D (not saved)
_hidden = {}
# (document name, operation name) -> (its path as G-code, path_drawing)
_drawings = {}


def active_setup(doc):
    """The setup the user works on: the last one picked, else the first."""
    jobs = cam.setups(doc)
    if not jobs:
        return None
    name = _active.get(doc.Name)
    return next((job for job in jobs if job.Name == name), jobs[0])


def set_active_setup(job):
    if _active.get(job.Document.Name) != job.Name:
        _active[job.Document.Name] = job.Name
        apply(job.Document)


def view_placement(doc):
    """The view draws the document moved by this: the inverse of the active
    setup's zero point (none without a setup)."""
    job = active_setup(doc)
    return cam.zero(job).inverse() if job is not None else FreeCAD.Placement()


def to_view(doc, point):
    """Where the view draws a point of the document."""
    return view_placement(doc).multVec(point)


def hidden(op):
    """Whether the user hid an operation's path in 3D."""
    return op.Name in _hidden.get(op.Document.Name, ())


def set_hidden(op, hide):
    names = _hidden.setdefault(op.Document.Name, set())
    if hide != (op.Name in names):
        names.symmetric_difference_update({op.Name})
        apply(op.Document)


def highlight_operation(doc, op):
    """Draw the path of op (None: of no operation) red."""
    if doc is None:
        return
    name = op.Name if op is not None else None
    if _highlighted.get(doc.Name) != name:
        _highlighted[doc.Name] = name
        _paint_paths(doc)


# -- drawing -------------------------------------------------------------------


def _view(obj):
    return getattr(obj, "ViewObject", None) if obj is not None else None


def _show(obj, visible):
    vo = _view(obj)
    if vo is not None and vo.Visibility != visible:
        vo.Visibility = visible


def _set_transform(obj, place):
    """Draw obj moved by place (in front of its own placement)."""
    vo = _view(obj)
    if vo is None:
        return
    from pivy import coin

    root = vo.RootNode
    node = root.getChild(0) if root.getNumChildren() else None
    if node is None or node.getName() != _NODE_NAME:
        node = coin.SoTransform()
        node.setName(_NODE_NAME)
        root.insertChild(node, 0)
    node.translation.setValue(place.Base.x, place.Base.y, place.Base.z)
    node.rotation.setValue(*place.Rotation.Q)


def _clear_transform(obj):
    vo = _view(obj)
    if vo is None:
        return
    root = vo.RootNode
    if root.getNumChildren() and root.getChild(0).getName() == _NODE_NAME:
        root.removeChild(0)


def _show_axis(job, visible):
    proxy = getattr(_view(job), "Proxy", None)
    if proxy is not None and hasattr(proxy, "showOriginAxis"):
        proxy.showOriginAxis(visible)


def _close(a, b):
    return all(abs(x - y) < 1e-3 for x, y in zip(a, b))


def style_sketch(sketch):
    """Green, thick lines (outside the sketch editor)."""
    vo = _view(sketch)
    if vo is None:
        return
    if not _close(vo.LineColor[:3], SKETCH_COLOR):
        vo.LineColor = SKETCH_COLOR
    if not _close(vo.PointColor[:3], SKETCH_COLOR):
        vo.PointColor = SKETCH_COLOR
    if vo.LineWidth != SKETCH_LINE_WIDTH:
        vo.LineWidth = SKETCH_LINE_WIDTH
    if vo.PointSize != SKETCH_POINT_SIZE:
        vo.PointSize = SKETCH_POINT_SIZE
    root = vo.RootNode
    if not (root.getNumChildren() and root.getChild(0).getName() == _NEARER_NAME):
        from pivy import coin

        node = coin.SoDepthBuffer()
        node.setName(_NEARER_NAME)
        node.range.setValue(*_NEARER_RANGE)
        root.insertChild(node, 0)


def _cutting_lines(path):
    """The cutting moves (G1, G2, G3) of a path as polylines of points."""
    import Path

    lines, at = [], FreeCAD.Vector()
    for command in path.Commands:
        params = command.Parameters
        end = FreeCAD.Vector(params.get("X", at.x), params.get("Y", at.y), params.get("Z", at.z))
        if command.Name in _CUTTING:
            edge = Path.Geom.edgeForCmd(command, at)
            if edge is not None:
                points = edge.discretize(Deflection=_DEFLECTION_MM)
                if lines and lines[-1][-1].isEqual(points[0], 1e-9):
                    lines[-1].extend(points[1:])
                else:
                    lines.append(points)
        at = end
    return lines


def _remove_drawn(vo, name):
    root = vo.RootNode
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == name:
            root.removeChild(i)


def _lines_node(name, lines, color, width, depth_test=True):
    """Unpickable polylines of one colour."""
    from pivy import coin

    group = coin.SoSeparator()
    group.setName(name)
    style = coin.SoPickStyle()
    style.style = coin.SoPickStyle.UNPICKABLE
    group.addChild(style)
    if not depth_test:
        depth = coin.SoDepthBuffer()
        depth.test = False
        group.addChild(depth)
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    group.addChild(light)
    rgb = coin.SoBaseColor()
    rgb.rgb.setValue(*color)
    group.addChild(rgb)
    draw = coin.SoDrawStyle()
    draw.lineWidth = width
    group.addChild(draw)
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, [(p.x, p.y, p.z) for line in lines for p in line])
    group.addChild(coords)
    polylines = coin.SoLineSet()
    polylines.numVertices.setValues(0, [len(line) for line in lines])
    group.addChild(polylines)
    return group


def _draw_highlight(op, drawing):
    """op's cutting moves red and wide over its path, seen through the part
    (a contour lies under the face it follows)."""
    vo = _view(op)
    if drawing is not None:
        lines = [points for kind, points in drawing if kind == cam.DRAW_FEED]
    else:
        lines = _cutting_lines(op.Path) if op.Path is not None else []
    if lines:
        vo.RootNode.addChild(_lines_node(_HIGHLIGHT_NAME, lines, PATH_HIGHLIGHT_COLOR, PATH_HIGHLIGHT_WIDTH, False))


def _rapid_color():
    """FreeCAD's colour of rapid moves (its preference, packed RGBA)."""
    packed = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/CAM").GetUnsigned(
        "DefaultRapidPathColor", 2852126975
    )
    return tuple(((packed >> shift) & 0xFF) / 255.0 for shift in (24, 16, 8))


def _draw_path(op, drawing):
    """A contour with radius compensation (a slot milling) drawn by path_drawing: FreeCAD's
    colours and width, the links between the tool centre and its edge
    yellow."""
    vo = _view(op)
    width = float(vo.LineWidth)
    colors = {cam.DRAW_RAPID: _rapid_color(), cam.DRAW_FEED: tuple(vo.NormalColor[:3]), cam.DRAW_LINK: PATH_LINK_COLOR}
    from pivy import coin

    group = coin.SoSeparator()
    group.setName(_DRAWING_NAME)
    for kind, color in colors.items():
        lines = [points for k, points in drawing if k == kind]
        if lines:
            group.addChild(_lines_node(kind, lines, color, width))
    vo.RootNode.addChild(group)


def _freecad_lines(vo, show):
    """Show or hide the lines FreeCAD draws for a path (its tool centre).
    They are put in a switch of their own, in their place: FreeCAD keeps
    and updates them, and draws them with what goes before them."""
    from pivy import coin

    search = coin.SoSearchAction()
    search.setName(_FREECAD_LINES_NAME)
    search.setInterest(coin.SoSearchAction.FIRST)
    search.setSearchingAll(True)
    search.apply(vo.RootNode)
    if search.getPath() is not None:
        switch = search.getPath().getTail()
    elif show:
        return
    else:
        search = coin.SoSearchAction()
        search.setType(coin.SoType.fromName("SoBrepEdgeSet"))
        search.setInterest(coin.SoSearchAction.FIRST)
        search.setSearchingAll(True)
        search.apply(vo.RootNode)
        found = search.getPath()
        if found is None:
            return
        lines, parent = found.getTail(), found.getNodeFromTail(1)
        switch = coin.SoSwitch()
        switch.setName(_FREECAD_LINES_NAME)
        index = parent.findChild(lines)
        switch.addChild(lines)
        parent.replaceChild(index, switch)
    switch.whichChild = coin.SO_SWITCH_ALL if show else coin.SO_SWITCH_NONE


def _drawing(op):
    """path_drawing of op, computed again only when its path changed."""
    key = op.Path.toGCode() if op.Path is not None else None
    cached = _drawings.get((op.Document.Name, op.Name))
    if cached is None or cached[0] != key:
        try:
            drawing = cam.path_drawing(op)
        except cam.ProjectError:  # the lines cannot be run now: FreeCAD draws its path
            drawing = None
        cached = (key, drawing)
        _drawings[(op.Document.Name, op.Name)] = cached
    return cached[1]


def _paint_paths(doc, on=True):
    """Each path as FreeCAD draws it, but contours with radius compensation
    and slot millings
    (_draw_path); the highlighted operation's path red over it."""
    if not FreeCAD.GuiUp or FreeCADGui.getDocument(doc.Name) is None:
        return
    name = _highlighted.get(doc.Name) if on else None
    for job in cam.setups(doc):
        for op in job.Operations.Group:
            vo = _view(op)
            if vo is None:
                continue
            _remove_drawn(vo, _DRAWING_NAME)
            _remove_drawn(vo, _HIGHLIGHT_NAME)
            # FreeCAD hides its own drawing only, not these ones
            drawing = _drawing(op) if on and vo.Visibility else None
            _freecad_lines(vo, drawing is None)
            if drawing is not None:
                _draw_path(op, drawing)
            if op.Name == name and vo.Visibility:
                _draw_highlight(op, drawing)


def _views(doc):
    gui_doc = FreeCADGui.getDocument(doc.Name)
    return gui_doc.mdiViewsOfType("Gui::View3DInventor") if gui_doc is not None else []


def _set_frame(doc, place):
    """Draw each 3D view of doc moved by place (None: as the document is);
    a view whose drawing turns is fitted again."""
    from pivy import coin

    for view in _views(doc):
        root = view.getSceneGraph()
        names = [root.getChild(i).getName() for i in range(root.getNumChildren())]
        node = root.getChild(names.index(_FRAME_NAME)) if _FRAME_NAME in names else None
        if place is None:
            if node is not None:
                root.removeChild(node)
            continue
        if node is None:
            if _FRAME_BEFORE not in names:
                continue
            node = coin.SoTransform()
            node.setName(_FRAME_NAME)
            root.insertChild(node, names.index(_FRAME_BEFORE))
            old = FreeCAD.Placement()
        else:
            old = FreeCAD.Placement(FreeCAD.Vector(*node.translation.getValue()), FreeCAD.Rotation(*node.rotation.getValue().getValue()))  # fmt: skip
        if old.isSame(place, 1e-9):
            continue
        node.translation.setValue(place.Base.x, place.Base.y, place.Base.z)
        node.rotation.setValue(*place.Rotation.Q)
        _fit(view)


def _fit(view, isometric=False):
    """The whole scene in view at once: FreeCAD's camera animation would
    first show the part jumped to its new place, then zoom out and in."""
    animated = view.isAnimationEnabled()
    view.setAnimationEnabled(False)
    try:
        if isometric:
            view.viewIsometric()
        view.fitAll()
    finally:
        view.setAnimationEnabled(animated)


def show_all(doc, isometric=False):
    """Every 3D view of doc shows the whole project in the active setup's
    coordinates at once (e.g. after an import)."""
    apply(doc)  # the setup's frame first, then the camera
    for view in _views(doc):
        _fit(view, isometric)


def _drawn(job):
    """The Job's objects drawn in the Job's coordinates."""
    result = [job]
    if job.Stock is not None:
        result.append(job.Stock)
    result.extend(job.Operations.Group)
    return result


def apply(doc):
    """Make the 3D view show the project as described in the module doc."""
    if doc is None or not FreeCAD.GuiUp or FreeCADGui.getDocument(doc.Name) is None:
        return
    from avangardecam.engine import op_zero
    from avangardecam.ui import next_setup
    from avangardecam.ui import op_zero as ui_op_zero

    jobs = cam.setups(doc)
    active = active_setup(doc)
    if active is not None and _view(active) is not None and not _view(active).Visibility:
        _view(active).Visibility = True  # FreeCAD then shows its children: fixed below
    for model in cam.models(doc):
        _show(model, True)
    for obj in doc.Objects:
        if cam.owner(obj) == ("sketch", obj):
            style_sketch(obj)
    for job in jobs:
        on = job is active
        place = cam.zero(job)
        for clone in job.Model.Group:
            _show(clone, False)
        for tc in job.Tools.Group:
            _show(getattr(tc, "Tool", None), False)
        for op in job.Operations.Group:
            for helper in cam.helper_objects(op):
                _show(helper, False)
        _show(job.Stock, on)
        next_setup.show_stock(job, on)  # a stock left by another setup: its own shape, not its box
        ui_op_zero.show_block(job, on)  # a block at an odd angle to the zero point: as it lies, not the box around it
        for op in job.Operations.Group:
            _show(op, on and not hidden(op))
        for obj in _drawn(job):
            # an operation that counts from another zero point lies on that one
            _set_transform(obj, op_zero.drawn_at(obj, place))
        _show_axis(job, on)
    _set_frame(doc, view_placement(doc))
    _paint_paths(doc)


def restore_freecad_view(doc):
    """FreeCAD's own view of the active setup, for expert mode."""
    if doc is None or not FreeCAD.GuiUp or FreeCADGui.getDocument(doc.Name) is None:
        return
    active = active_setup(doc)
    _set_frame(doc, None)
    _paint_paths(doc, on=False)
    for job in cam.setups(doc):
        for obj in _drawn(job):
            _clear_transform(obj)
        _show_axis(job, job is active)
    if active is not None:
        for model in cam.models(doc):
            _show(model, False)
        for clone in active.Model.Group:
            _show(clone, True)


# -- editing ---------------------------------------------------------------------


class _EditObserver:
    """Double-clicking a project object in 3D starts FreeCAD's editor in a
    panel that is hidden in AvangardeCam; show the object in our panel
    instead."""

    def __init__(self, on_edit):
        self.on_edit = on_edit

    def slotInEdit(self, vp):
        obj = getattr(vp, "Object", None)
        if obj is not None and cam.owner(obj) is not None:
            QtCore.QTimer.singleShot(0, lambda: self._take_over(obj))

    def _take_over(self, obj):
        gui_doc = FreeCADGui.getDocument(obj.Document.Name)
        if gui_doc is not None and gui_doc.getInEdit() is not None:
            gui_doc.resetEdit()
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        self.on_edit(obj)


_edit_observer = None


def watch_edits(on_edit):
    """Call on_edit(obj) instead of FreeCAD's editor while AvangardeCam is active."""
    global _edit_observer
    if _edit_observer is None:
        _edit_observer = _EditObserver(on_edit)
        FreeCADGui.addDocumentObserver(_edit_observer)


def stop_watching_edits():
    global _edit_observer
    if _edit_observer is not None:
        FreeCADGui.removeDocumentObserver(_edit_observer)
        _edit_observer = None
