# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""A 3D view of its own (Coin, as FreeCAD's views) for a window that shows
a scene apart from the project's view, e.g. the simulation's.

A QOpenGLWidget renders a Coin scene with SoRenderManager (pivy's Quarter
widget does not load with this pivy and Qt 6: its Qt shim has no
QtOpenGLWidgets), with a depth buffer of its own. An orthographic camera, a light from the eye and a
weaker one from behind (no black sides), its own cache context (the GL
context is not FreeCAD's).

The view is turned and moved as AvangardeCam's 3D view (Blender style):
the middle button turns it (round the world's Z and the screen's
horizontal), Shift+middle moves it, Ctrl+middle zooms, the wheel zooms to
the cursor. The left button does the same (nothing to select here; a
laptop's touchpad has no middle button). Top, Front, Right, Isometric and
Fit set the camera (Fit: what set_fit_node gives, e.g. the stock, not a
tool high above it); Z stays up on the screen.
"""

import math

from PySide import QtCore, QtGui
from PySide6.QtOpenGLWidgets import QOpenGLWidget

BACKGROUND = (0.86, 0.88, 0.91)
_TURN_PER_PX = math.pi / 600.0  # half a turn for 600 pixels
_ZOOM_PER_STEP = 1.15  # a wheel step


class CoinView(QOpenGLWidget):
    """A Coin scene (scene: an SoNode) in a widget, see the module."""

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        # a depth buffer asked for: FreeCAD's default format has one only on
        # Wayland, without it the faces drawn last cover the nearer ones
        surface = QtGui.QSurfaceFormat(self.format())
        surface.setDepthBufferSize(24)
        self.setFormat(surface)
        from pivy import coin

        self.coin = coin
        self.root = coin.SoSeparator()
        # the depth test on (Quarter turns it on in its paintGL; without it
        # the faces drawn last cover the nearer ones)
        depth = coin.SoDepthBuffer()
        depth.test = True
        depth.write = True
        depth.function = coin.SoDepthBuffer.LESS
        self.root.addChild(depth)
        self.camera = coin.SoOrthographicCamera()
        self.root.addChild(self.camera)
        self.light = coin.SoDirectionalLight()
        self.back_light = coin.SoDirectionalLight()
        self.back_light.intensity = 0.35
        self.root.addChild(self.light)
        self.root.addChild(self.back_light)
        self.root.addChild(scene)
        self.manager = coin.SoRenderManager()
        self.manager.setSceneGraph(self.root)
        self.manager.setBackgroundColor(coin.SbColor4f(*BACKGROUND, 1.0))
        action = self.manager.getGLRenderAction()
        action.setCacheContext(coin.SoGLCacheContextElement.getUniqueCacheContext())
        action.setTransparencyType(coin.SoGLRenderAction.SORTED_OBJECT_BLEND)
        self._drag = None  # (mode, last position)
        self.fit_node = None
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.setMinimumSize(200, 150)
        self.set_direction("isometric")

    # -- rendering -----------------------------------------------------------------

    def resizeGL(self, w, h):
        ratio = self.devicePixelRatio()
        size = self.coin.SbVec2s(max(int(w * ratio), 1), max(int(h * ratio), 1))
        self.manager.setWindowSize(size)
        self.manager.setSize(size)
        self.manager.setViewportRegion(self.coin.SbViewportRegion(size[0], size[1]))

    def paintGL(self):
        coin = self.coin
        rotation = self.camera.orientation.getValue()
        self.light.direction.setValue(rotation.multVec(coin.SbVec3f(0.25, -0.35, -1.0)))
        self.back_light.direction.setValue(rotation.multVec(coin.SbVec3f(-0.3, 0.4, 1.0)))
        self._clip_to_scene()
        self.manager.render(True, True)

    def _clip_to_scene(self):
        """Near and far planes round the whole scene, every frame: viewAll
        sets them round the fit node only, so the tool above the stock or
        anything after a turn was cut off by them."""
        coin = self.coin
        action = coin.SoGetBoundingBoxAction(self._region())
        action.apply(self.root)
        box = action.getBoundingBox()
        if box.isEmpty():
            return
        camera = self.camera
        eye = camera.position.getValue()
        look = camera.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        lo, hi = box.getMin().getValue(), box.getMax().getValue()
        depths = [(coin.SbVec3f(x, y, z) - eye).dot(look) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        margin = max(max(depths) - min(depths), 1.0) * 0.05
        back = margin - min(depths)
        if back > 0:  # the eye moved back out of the scene: the same picture (orthographic)
            camera.position.setValue(eye - look * back)
            camera.focalDistance.setValue(camera.focalDistance.getValue() + back)
            depths = [d + back for d in depths]
        camera.nearDistance.setValue(min(depths) - margin)
        camera.farDistance.setValue(max(depths) + margin)

    def redraw(self):
        self.update()

    # -- camera --------------------------------------------------------------------

    def _region(self):
        ratio = self.devicePixelRatio()
        return self.coin.SbViewportRegion(max(int(self.width() * ratio), 1), max(int(self.height() * ratio), 1))

    def fit(self):
        """In sight: the fit node (set_fit_node), else the whole scene."""
        self.camera.viewAll(self.fit_node if self.fit_node is not None else self.root, self._region(), 1.1)
        self.redraw()

    def set_fit_node(self, node):
        """What Fit and the directions put in sight (None: everything)."""
        self.fit_node = node

    def set_direction(self, name):
        """The camera looking from: top, front, right, isometric (Z up)."""
        coin = self.coin
        turns = {
            "top": coin.SbRotation(),
            "front": coin.SbRotation(coin.SbVec3f(1, 0, 0), math.pi / 2.0),
            "right": coin.SbRotation(coin.SbVec3f(1, 0, 0), math.pi / 2.0) * coin.SbRotation(coin.SbVec3f(0, 0, 1), math.pi / 2.0),
            "isometric": coin.SbRotation(coin.SbVec3f(1, 0, 0), math.radians(54.7356)) * coin.SbRotation(coin.SbVec3f(0, 0, 1), math.pi / 4.0),
        }
        self.camera.orientation.setValue(turns[name])
        self.fit()

    def _focal_point(self):
        camera = self.camera
        direction = camera.orientation.getValue().multVec(self.coin.SbVec3f(0, 0, -1))
        return camera.position.getValue() + direction * camera.focalDistance.getValue()

    def _turn(self, dx, dy):
        """Round the focal point: about the world's Z for dx, about the
        screen's horizontal for dy."""
        coin = self.coin
        camera = self.camera
        focal = self._focal_point()
        rotation = camera.orientation.getValue()
        right = rotation.multVec(coin.SbVec3f(1, 0, 0))
        turn = coin.SbRotation(coin.SbVec3f(0, 0, 1), -dx * _TURN_PER_PX)
        tilt = coin.SbRotation(right, -dy * _TURN_PER_PX)
        new = rotation * tilt * turn
        camera.orientation.setValue(new)
        back = new.multVec(coin.SbVec3f(0, 0, 1)) * camera.focalDistance.getValue()
        camera.position.setValue(focal + back)

    def _units_per_px(self):
        return self.camera.height.getValue() / max(self.height(), 1)

    def _pan(self, dx, dy):
        rotation = self.camera.orientation.getValue()
        step = self._units_per_px()
        shift = rotation.multVec(self.coin.SbVec3f(-dx * step, dy * step, 0.0))
        self.camera.position.setValue(self.camera.position.getValue() + shift)

    def _zoom(self, factor, at=None):
        """Height times factor; at (widget point): the point under it stays."""
        camera = self.camera
        if at is not None:
            step = self._units_per_px()
            cx, cy = self.width() / 2.0, self.height() / 2.0
            dx, dy = (at.x() - cx) * step, (cy - at.y()) * step
            shift = camera.orientation.getValue().multVec(self.coin.SbVec3f(dx * (1.0 - factor), dy * (1.0 - factor), 0.0))
            camera.position.setValue(camera.position.getValue() + shift)
        camera.height.setValue(max(camera.height.getValue() * factor, 1e-3))

    # -- mouse ---------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() in (QtCore.Qt.MiddleButton, QtCore.Qt.LeftButton):
            mods = event.modifiers()
            mode = "pan" if mods & QtCore.Qt.ShiftModifier else "zoom" if mods & QtCore.Qt.ControlModifier else "turn"
            self._drag = (mode, event.position())
            self.setCursor(QtCore.Qt.ClosedHandCursor if mode != "zoom" else QtCore.Qt.SizeVerCursor)

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        mode, last = self._drag
        here = event.position()
        dx, dy = here.x() - last.x(), here.y() - last.y()
        if mode == "turn":
            self._turn(dx, dy)
        elif mode == "pan":
            self._pan(dx, dy)
        else:
            self._zoom(math.exp(dy * 0.01))
        self._drag = (mode, here)
        self.redraw()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.unsetCursor()

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if steps:
            self._zoom(_ZOOM_PER_STEP ** (-steps), event.position())
            self.redraw()

    def grab_image(self):
        """What the view shows (QImage)."""
        return self.grabFramebuffer()

