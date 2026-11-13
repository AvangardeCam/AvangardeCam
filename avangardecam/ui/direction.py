# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Arrows showing the way the tool runs along the selected sketch lines.

Every selected line gets an arrow in the middle of its length, pointing
the way the tool follows it (geometry.line_runs: the click order, a chain
from its first line clicked to its last). A click on an arrow turns its
whole chain round. Which chains are turned is kept for the lines while
they stay selected; a line selected anew runs the way of the click order.

The arrows are drawn in the sketch's own scene graph (after its
placement): cones lying on the sketch plane, so they read as arrowheads
from any side, the same size on screen at any zoom and a hair nearer to
the eye than the sketch's lines. They cannot be
picked by FreeCAD: picking.py asks arrow_at() on a plain click and keeps
the click from FreeCAD when it hits an arrow.
"""

import math

import FreeCAD
import FreeCADGui

from PySide import QtCore

from avangardecam.engine import geometry

_NODE_NAME = "AvangardeCamDirection"

# dark red on the red of the selected line; yellow under the mouse, as
# FreeCAD shows what a click would take
ARROW_COLOR = (0.55, 0.0, 0.0)
HOVER_COLOR = (0.88, 0.78, 0.08)
# the arrow in screen pixels
ARROW_LENGTH_PX = 30.0
ARROW_RADIUS_PX = 7.0
# how near a click has to come to an arrow's middle, in screen pixels
PICK_PX = 14.0
# nearer to the eye than the sketch's lines (scene.style_sketch: 0.9999)
_NEARER_RANGE = (0.0, 0.9998)


class _State:
    backwards = {}  # (document, sketch) -> names of lines whose chain is turned round
    shown = []  # (document, sketch, line, part point, material) of the arrows drawn
    drawn = {}  # (document, sketch) -> sketch with arrows in its scene graph
    hovered = None  # (document, sketch, line) of the arrow under the mouse
    scheduled = False


def _key(sketch):
    return sketch.Document.Name, sketch.Name


def _selected():
    """{(document, sketch): (sketch, names of its selected lines in click
    order)}; all its lines when the whole sketch is selected."""
    from avangardecam.ui import picking

    result = {}
    for sketch, edges in picking.selections():
        result[_key(sketch)] = (sketch, list(edges) or geometry.all_lines(sketch))
    return result


def backwards(sketch):
    """Names of the selected lines of the sketch whose chain the tool runs
    the other way round (for freecad_cam.add_contour)."""
    found = _selected().get(_key(sketch))
    if found is None:
        return set()
    return _State.backwards.get(_key(sketch), set()) & set(found[1])


# -- drawing -------------------------------------------------------------------


def schedule():
    """Redraw the arrows once the selection has settled."""
    if not _State.scheduled:
        _State.scheduled = True
        QtCore.QTimer.singleShot(0, refresh)


def refresh():
    from avangardecam.ui import picking

    _State.scheduled = False
    if picking.busy():
        schedule()  # a click is still rebuilding the selection
        return
    selected = _selected()
    for key in list(_State.backwards):
        if key not in selected:
            del _State.backwards[key]
    for key, sketch in list(_State.drawn.items()):
        _remove(key, sketch)
    _State.shown = []
    for key, (sketch, names) in selected.items():
        flags = _State.backwards.get(key)
        if flags is not None:
            flags &= set(names)
        vo = getattr(sketch, "ViewObject", None)
        if vo is None or not vo.Visibility:
            continue
        arrows = geometry.line_arrows(sketch, names, flags or ())
        _draw(sketch, arrows)
    # the mouse still over a redrawn arrow (one just turned round)
    hovered, _State.hovered = _State.hovered, None
    hover(next((a[:3] for a in _State.shown if a[:3] == hovered), None))


def clear():
    """Take all arrows away (AvangardeCam stops)."""
    for key, sketch in list(_State.drawn.items()):
        _remove(key, sketch)
    _State.shown = []
    _State.hovered = None
    _State.backwards = {}


def _remove(key, sketch):
    del _State.drawn[key]
    try:
        vo = sketch.ViewObject if sketch.isAttachedToDocument() else None
    except Exception:  # deleted, its document closed
        vo = None
    if vo is None:
        return
    root = vo.RootNode
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName() == _NODE_NAME:
            root.removeChild(i)


def _arrow_shape():
    """A cone pointing along +X, lying on the plane z = 0 (on the face the
    sketch was taken from, not sunk into it), in screen pixels."""
    from pivy import coin

    shape = coin.SoSeparator()
    place = coin.SoTransform()
    place.translation.setValue(0.0, 0.0, ARROW_RADIUS_PX)
    place.rotation.setValue(coin.SbVec3f(0, 0, 1), -math.pi / 2.0)  # the cone's +Y to +X
    shape.addChild(place)
    cone = coin.SoCone()
    cone.height = ARROW_LENGTH_PX
    cone.bottomRadius = ARROW_RADIUS_PX
    shape.addChild(cone)
    return shape


def _draw(sketch, arrows):
    from pivy import coin

    group = coin.SoSeparator()
    group.setName(_NODE_NAME)
    style = coin.SoPickStyle()
    style.style = coin.SoPickStyle.UNPICKABLE
    group.addChild(style)
    depth = coin.SoDepthBuffer()
    depth.range.setValue(*_NEARER_RANGE)
    group.addChild(depth)

    to_part = sketch.getGlobalPlacement()
    for name, point, direction in arrows:
        arrow = coin.SoSeparator()
        color = coin.SoMaterial()
        _paint(color, ARROW_COLOR)
        arrow.addChild(color)
        move = coin.SoTransform()
        move.translation.setValue(point.x, point.y, point.z)
        move.rotation.setValue(coin.SbVec3f(0, 0, 1), math.atan2(direction.y, direction.x))
        arrow.addChild(move)
        # one unit = one pixel on screen
        scale = coin.SoType.fromName("SoShapeScale").createInstance()
        scale.setPart("shape", _arrow_shape())
        scale.scaleFactor = 1.0
        arrow.addChild(scale)
        group.addChild(arrow)
        _State.shown.append((sketch.Document.Name, sketch.Name, name, to_part.multVec(point), color))
    sketch.ViewObject.RootNode.addChild(group)
    _State.drawn[_key(sketch)] = sketch


# -- clicking --------------------------------------------------------------------


def shown():
    return bool(_State.shown)


def arrow_at(doc_name, view, widget, pos):
    """The arrow drawn under pos (a position in widget, the viewport of
    view, a 3D view of the document): (document, sketch, line), or None."""
    from avangardecam.ui import scene

    ratio = widget.devicePixelRatioF()
    height = widget.height() * ratio
    best = None
    for doc, sketch_name, name, point, color in _State.shown:
        if doc != doc_name:
            continue
        x, y = view.getPointOnScreen(scene.to_view(FreeCAD.getDocument(doc), point))  # device pixels, from the bottom
        distance = math.hypot(x / ratio - pos.x(), (height - y - 1) / ratio - pos.y())
        if distance <= PICK_PX and (best is None or distance < best[0]):
            best = (distance, (doc, sketch_name, name))
    return best[1] if best is not None else None


def _color(arrow):
    return next((a[4] for a in _State.shown if a[:3] == arrow), None)


def _paint(material, rgb):
    """Shaded, so the cone reads as one, but never dark."""
    material.diffuseColor.setValue(*rgb)
    material.emissiveColor.setValue(*(c * 0.45 for c in rgb))
    material.specularColor.setValue(0.0, 0.0, 0.0)


def hover(arrow):
    """Show the arrow (found by arrow_at, or None) as the one a click would take."""
    if arrow == _State.hovered:
        return
    for key, rgb in ((_State.hovered, ARROW_COLOR), (arrow, HOVER_COLOR)):
        color = _color(key) if key is not None else None
        if color is not None:
            _paint(color, rgb)
    _State.hovered = arrow


def turn_round(arrow):
    """Turn round the chain of selected lines the arrow's line belongs to."""
    doc_name, sketch_name, line = arrow
    if doc_name not in FreeCAD.listDocuments():
        return
    sketch = FreeCAD.getDocument(doc_name).getObject(sketch_name)
    found = _selected().get((doc_name, sketch_name)) if sketch is not None else None
    if found is None:
        return
    flags = _State.backwards.setdefault((doc_name, sketch_name), set())
    for chain in geometry.line_chains(sketch, found[1]):
        if line in chain:
            if flags & set(chain):
                flags.difference_update(chain)
            else:
                flags.update(chain)
    refresh()


# -- visibility ------------------------------------------------------------------


class _ViewObserver:
    """Arrows of a sketch hidden or shown again."""

    def slotChangedObject(self, vp, prop):
        # vp is not touched: FreeCAD reports Visibility while it still builds
        # a view provider, and vp.Object then crashes it
        if prop == "Visibility":
            schedule()


_observer = None


def start():
    global _observer
    if _observer is None:
        _observer = _ViewObserver()
        FreeCADGui.addDocumentObserver(_observer)


def stop():
    global _observer
    if _observer is not None:
        FreeCADGui.removeDocumentObserver(_observer)
        _observer = None
    clear()
