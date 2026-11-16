# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Simulation: the stock of a setup machined by its operations.

For now this drives FreeCAD's OpenGL CAM simulator (the CAMSimulator
module) directly, without FreeCAD's task panel, which AvangardeCam hides:
its own window shows the stock, the part and the tools, with play, pause,
step and speed buttons drawn in the window. It runs FreeCAD's paths of
one setup, in the setup's coordinates, from a fresh stock box (or the
stock another setup left: engine.next_setup.simulator_stock).

The view is turned and moved as AvangardeCam's 3D view (Blender style):
the middle button rotates, Shift+middle pans, Ctrl+middle and the wheel
zoom (see _WindowFilter).

It is meant to change or to be replaced, so nothing else depends on it:
handlers.simulate() calls start() and nothing more.
"""

import math

from PySide import QtCore, QtGui

from avangardecam import tr

# the simulator's own default ("High" in FreeCAD's panel), 1..10
QUALITY = 10
# tool profiles are made of segments of this length, mm
_PROFILE_RESOLUTION_MM = 0.5
# share of the main window the simulator window covers, in its middle
_WINDOW_SHARE = 0.7


def operations(job):
    """The operations of a setup the simulation runs: active, with a tool
    and a path, counting from the setup's active zero point (FreeCAD's
    simulator runs the paths on one zero point; engine.op_zero)."""
    from avangardecam.engine import op_zero

    result = []
    for op in job.Operations.Group if job is not None else []:
        tc = getattr(op, "ToolController", None)
        if op_zero.parked(op):
            continue
        if getattr(op, "Active", True) and tc is not None and getattr(tc, "Tool", None) is not None:
            if op.Path is not None and op.Path.Commands:
                result.append(op)
    return result


def start(job, ops):
    """Open the simulator window with the setup's stock, its models and
    the operations' paths; returns the simulator object."""
    import CAMSimulator
    import Part
    import Path.Main.Gui.SimulatorGL as SimulatorGL
    from PathScripts import PathUtils

    profiles = SimulatorGL.CAMSimulation()  # only for its tool profiles
    simulator = CAMSimulator.PathSim()
    simulator.ResetSimulation()
    for op in ops:
        tc = op.ToolController
        profile = profiles.GetToolProfile(tc.Tool, _PROFILE_RESOLUTION_MM)
        simulator.AddTool(profile, int(tc.ToolNumber), float(tc.Tool.Diameter), 1)
        for command in PathUtils.getPathWithPlacement(op).Commands:
            simulator.AddCommand(command)
    from avangardecam.engine import next_setup

    stock = next_setup.simulator_stock(job)  # the stock another setup left
    simulator.BeginSimulation(job.Stock.Shape if stock is None else stock, QUALITY)
    models = [clone.Shape for clone in job.Model.Group]
    if models:
        simulator.SetBaseShape(Part.makeCompound(models), 1)
    window = simulator_window()
    if window is not None:
        window.setTitle(tr("Simulation - {}").format(job.Label))
        if not window.findChild(_WindowFilter):
            _WindowFilter(window)
        _place(window)
    return simulator


_SHIFT = QtCore.Qt.ShiftModifier
_CTRL = QtCore.Qt.ControlModifier
_ALT = QtCore.Qt.AltModifier
_MIDDLE = QtCore.Qt.MiddleButton
_ROTATE = _ALT
_PAN = _SHIFT
_ZOOM = _CTRL | _SHIFT


class _WindowFilter(QtCore.QObject):
    """Fixes and navigation for FreeCAD's simulator window.

    Its resize handler draws without making its OpenGL context current:
    whatever context is current then (often the 3D view's) gets its
    viewport and shaders, the 3D view turns black and the simulator's
    buttons are lost. Its context is made current before every resize.

    It turns the view while Alt is held, pans while Shift is held and zooms
    while Ctrl+Shift are held, as the mouse moves without a button; a drag
    starts where these keys change. The middle button never reaches it: its
    drags go to it as such moves, so it navigates like AvangardeCam's 3D
    view (Blender style): middle drag rotates, Shift+middle pans,
    Ctrl+middle zooms (up: in). Moves without a button reach it without
    Shift, Ctrl and Alt, so a key held alone does not move the view.

    Its own speeds are set by pixels, so the moves are scaled (a virtual
    cursor, see _speed): the part follows the cursor when panning, half a
    turn across the window when rotating, zoom as fast as FreeCAD's.
    """

    def __init__(self, window):
        super().__init__(window)
        self.sending = False
        self.cursor = None  # the real cursor during a middle button drag
        self.virtual = None  # the cursor the simulator sees then
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.Resize:
            context = watched.findChild(QtGui.QOpenGLContext)
            if context is not None:
                context.makeCurrent(watched)
        elif kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick):
            if event.button() != _MIDDLE:
                return False
            pos = _position(event)
            if kind == QtCore.QEvent.MouseButtonRelease:
                self.cursor = self.virtual = None
                self._send(watched, event, pos, QtCore.Qt.NoModifier)
            else:
                self.cursor = self.virtual = pos
                self._send(watched, event, pos, _keys(event.modifiers()))
            return True
        elif kind == QtCore.QEvent.MouseMove and not self.sending:
            mods = event.modifiers() & (_SHIFT | _CTRL | _ALT)
            if event.buttons() & _MIDDLE and self.cursor is not None:
                keys = _keys(mods)
                pos = _position(event)
                self.virtual += (pos - self.cursor) * _speed(keys, watched)
                self.cursor = pos
                self._send(watched, event, self.virtual, keys)
            elif event.buttons() == QtCore.Qt.NoButton and mods:
                self._send(watched, event, _position(event), QtCore.Qt.NoModifier)
            else:
                return False
            return True
        return False

    def _send(self, window, event, pos, keys):
        moved = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            pos,
            window.mapToGlobal(pos),
            QtCore.Qt.NoButton,
            event.buttons() & ~_MIDDLE,
            keys,
        )
        self.sending = True
        try:
            QtCore.QCoreApplication.sendEvent(window, moved)
        finally:
            self.sending = False


def _position(event):
    return event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())


def _keys(mods):
    """The simulator's keys for a middle button drag with mods held."""
    if mods & _CTRL:
        return _ZOOM
    if mods & _SHIFT:
        return _PAN
    return _ROTATE


def _speed(keys, window):
    """Simulator pixels per cursor pixel.

    The simulator (FreeCAD's SimDisplay and MillSimulation) turns by
    0.01 rad per pixel; pans the eye by 0.005 of its distance per pixel,
    seen through a 0.7 rad high perspective: 0.005 * height / (2 tan 0.35)
    screen pixels at the target, whatever the zoom; zooms by 0.003 of its
    eye factor (0.1 at the start) per pixel, where FreeCAD zooms by
    exp(10 * pixels / height).
    """
    if keys == _PAN:
        return 2.0 * math.tan(0.35) / (0.005 * window.height())
    if keys == _ZOOM:
        return 10.0 * 0.1 / (0.003 * window.height())
    return math.pi / 0.01 / window.width()


def _place(window):
    """Over the middle of the main window (FreeCAD opens it small)."""
    import FreeCADGui

    main = FreeCADGui.getMainWindow().frameGeometry()
    width = max(window.minimumWidth(), int(main.width() * _WINDOW_SHARE))
    height = max(window.minimumHeight(), int(main.height() * _WINDOW_SHARE))
    window.setGeometry(main.x() + (main.width() - width) // 2, main.y() + (main.height() - height) // 2, width, height)


def simulator_window():
    """FreeCAD's simulator window while it is open, else None."""
    for window in QtGui.QGuiApplication.topLevelWindows():
        if window.isVisible() and window.surfaceType() == QtGui.QSurface.OpenGLSurface:
            title = window.title()
            if title.endswith("CAM Simulator") or title.startswith(tr("Simulation - ")):
                return window
    return None
