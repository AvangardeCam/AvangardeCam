# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""CAM > Play: the active setup's program played as the machine runs it,
in a window of its own (user, 2026-10-28: the project's view stays as it
is; the window can be maximized or put on a second screen).

- its own 3D view (ui.coin_view) in the setup's coordinates: the stock as
  the machine leaves it (model.playback_stock, cut while it plays), the
  part (transparent, on request, seen through the material), the tool in its shape where it is, the
  path of the operation going on (done in colours, the rest pale; seen
  through the material), the stock's box and the zero point;
- on the right the setup's operations with their times and the whole
  program (.H, as exported) with the line the machine runs; a click on an
  operation goes to its start, a click on a line to where that block has
  run;
- below the time line with the operations (a click or a drag goes there),
  the buttons, the speed, the clock, the tool and what it does (F1250,
  FMAX, Tool change, Dwell).

The material is cut on while it plays and the stock's surface drawn again
as often as it takes: at most every MESH_MS, and at most half the time
(the rest for the tool); paused or stepped it is always where the tool
is. The surface is in pieces (model.playback_stock.PIECE_CUBES), each a
node of its own: only the pieces whose material changed are drawn again. Accuracy: Rough, Medium (at first), Fine, as Verify's (cells on the
stock's longest edge); the window says the cell's size and how long the
last drawing took.

What the machine runs into is found as the stock is cut (model.crashes):
a rapid move (FMAX) taking material, the tool's shank or neck in material.
Each is a red mark on the time line and a red line of the program; the
button beside the feed says which (1 of 18: ...) and goes to the next; while
it plays it stops at the end of the block of each (found before, or found
just now). Found as far as the stock has been cut, so the marks come as it
plays (Verify finds them all at once).

Keys while the window is active (not while typing in a field): Space plays
or pauses, Left/Right go back/on one block, Up/Down to the operation
before or after, Home/End to the start or the end, Escape closes it.
"""

import time

import numpy as np

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

from avangardecam import params, tr
from avangardecam.engine import ProjectError
from avangardecam.engine import playback as engine_playback
from avangardecam.model import crashes as model_crashes
from avangardecam.model import cycle_time, nc
from avangardecam.model import playback as model_playback
from avangardecam.model import playback_stock, tilted
from avangardecam.ui import postprocessors
from avangardecam.ui.coin_view import CoinView

_LAST_SPEED = "LastPlaybackSpeed"
_LAST_RESOLUTION = "LastPlaybackResolution"
# cells on the stock's longest edge, as Verify's
RESOLUTIONS = ((QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Rough"), 150),
               (QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Medium"), 250),
               (QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Fine"), 500))  # fmt: skip
DEFAULT_RESOLUTION = 250
_FRAME_MS = 20
MESH_MS = 100  # the stock drawn again at most this often while it plays
# a frame plays at most this much of the real time: a computer too slow for
# the speed plays slower instead of jumping (and cutting ever more at once)
_MOST_FRAME_S = 0.1
_WINDOW_SHARE = 0.8  # of the screen
STOCK_COLOR = (0.62, 0.68, 0.78)
PART_COLOR = (0.25, 0.75, 0.35)
PART_TRANSPARENCY = 0.55
CUTTING_COLOR = (0.93, 0.62, 0.10)  # the tool's cutting part
BODY_COLOR = (0.55, 0.57, 0.62)  # its neck and shank
PALE_COLOR = (0.55, 0.60, 0.70)  # the path still to come
DONE_FEED_COLOR = (0.0, 0.4, 1.0)  # cutting moves done
CRASH_COLOR = "#d40000"  # what the machine runs into: the marks, the button
CRASH_LINE_COLOR = "#ffd2d2"  # the program's lines of the blocks
PATH_WIDTH = 2.0
_TOOL_SIDES = 32

_window = None


def window():
    """The open simulation window, or None."""
    return _window if _window is not None and _window.isVisible() else None


def start(job):
    """Open the window on a setup: its program worked out first (the
    document recomputed); returns the window, or raises ProjectError."""
    global _window
    if _window is not None:
        _window.close()
    QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
    try:
        job.Document.recompute()
        prepared = engine_playback.prepare(job, postprocessors.last())
        _window = SimulationWindow(job, prepared, FreeCADGui.getMainWindow())
    finally:
        QtWidgets.QApplication.restoreOverrideCursor()
    _window.show()
    _window.view.fit()
    return _window


def start_or_say(job):
    """start(), the reason it cannot in a message box."""
    try:
        return start(job)
    except ProjectError as exc:
        QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", str(exc))
        return None


def close():
    """Close the open window, if any."""
    if _window is not None:
        _window.close()


def last_speed():
    value = params().GetFloat(_LAST_SPEED, 1.0)
    return value if value in model_playback.SPEEDS else 1.0


def last_resolution():
    value = params().GetInt(_LAST_RESOLUTION, DEFAULT_RESOLUTION)
    return value if value in [r for _name, r in RESOLUTIONS] else DEFAULT_RESOLUTION


def rapid_color():
    """FreeCAD's colour of rapid moves (its preference, packed RGBA)."""
    packed = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/CAM").GetUnsigned("DefaultRapidPathColor", 2852126975)
    return tuple(((packed >> shift) & 0xFF) / 255.0 for shift in (24, 16, 8))


def feed_text(step):
    """What the machine does in a step: F1250, FMAX, Tool change, Dwell."""
    if step.kind == model_playback.TOOL_CHANGE:
        return tr("Tool change")
    if step.kind == model_playback.DWELL:
        return tr("Dwell")
    if step.kind == nc.RAPID:
        return "FMAX"
    return "F{:g}".format(round(step.feed, 1)) if step.feed else ""


def crash_text(crash, lines):
    """What the machine ran into (model.playback_stock.PlayedCrash), the
    block of the program by its number."""
    what = tr("FMAX into material") if crash.kind == model_crashes.RAPID else tr("Shank in material")
    block = lines[crash.line].split(" ", 1)[0] if crash.line is not None and crash.line < len(lines) else "?"
    return tr("{}: block {} ({:.1f} mm³)").format(what, block, crash.volume_mm3)


def tool_text(tool):
    return "T{} {}".format(tool.number, tool.name)


# -- the scene ---------------------------------------------------------------------


def _set_points(field, points):
    """A Coin multiple field of points from an (n, 3) array, n values exactly."""
    points = np.ascontiguousarray(points, dtype=np.float32).reshape(-1, 3)
    field.setNum(len(points))
    if len(points):
        field.setValues(0, len(points), points)


def _set_faces(field, triangles):
    index = np.full((len(triangles), 4), -1, dtype=np.int32)
    index[:, :3] = triangles
    field.setNum(index.size)
    if index.size:
        field.setValues(0, index.size, index.ravel())


class _Scene:
    """The window's Coin scene: stock, part, box, zero point, path, tool."""

    def __init__(self, coin):
        self.coin = coin
        self.root = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        self.root.addChild(pick)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        hints.shapeType = coin.SoShapeHints.SOLID
        hints.creaseAngle = 0.6
        self.root.addChild(hints)
        self.stock_switch, group = self._switch(self.root)
        group.addChild(self._material(STOCK_COLOR))
        self.stock_group = coin.SoGroup()
        group.addChild(self.stock_group)
        self.stock_pieces = {}  # (i, j, k) -> (separator, points, faces)
        # after the stock and through it: the part lies in the material
        part = coin.SoAnnotation()
        self.root.addChild(part)
        self.part_switch, self.part_points, self.part_faces = self._solid(PART_COLOR, PART_TRANSPARENCY, parent=part)
        self.lines = coin.SoSeparator()
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        self.lines.addChild(light)
        self.root.addChild(self.lines)
        self._build_path()
        self._build_tool()
        self.count = 0
        self.array = None

    def _switch(self, parent):
        switch = self.coin.SoSwitch()
        group = self.coin.SoSeparator()
        switch.addChild(group)
        switch.whichChild = self.coin.SO_SWITCH_ALL
        parent.addChild(switch)
        return switch, group

    def _material(self, rgb, transparency=0.0):
        material = self.coin.SoMaterial()
        material.diffuseColor.setValue(*rgb)
        material.specularColor.setValue(0.25, 0.25, 0.25)
        material.shininess = 0.3
        material.transparency = transparency
        return material

    def _solid(self, rgb, transparency=0.0, parent=None):
        coin = self.coin
        switch, group = self._switch(parent if parent is not None else self.root)
        group.addChild(self._material(rgb, transparency))
        points = coin.SoCoordinate3()
        group.addChild(points)
        faces = coin.SoIndexedFaceSet()
        group.addChild(faces)
        return switch, points, faces

    def _color(self, rgb):
        node = self.coin.SoBaseColor()
        node.rgb.setValue(*rgb)
        return node

    def _width(self, width):
        node = self.coin.SoDrawStyle()
        node.lineWidth = width
        return node

    def add_lines(self, points, color, width=1.0):
        """Polylines (lists of points) drawn as they are."""
        coin = self.coin
        group = coin.SoSeparator()
        group.addChild(self._color(color))
        group.addChild(self._width(width))
        coords = coin.SoCoordinate3()
        _set_points(coords.point, np.array([p for line in points for p in line], dtype=float))
        group.addChild(coords)
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, len(points), [len(line) for line in points])
        group.addChild(lines)
        self.lines.addChild(group)

    def _build_path(self):
        coin = self.coin
        # after the rest of the scene and through it: the path lies in the material
        path = coin.SoAnnotation()
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        path.addChild(light)
        self.path_switch = coin.SoSwitch()
        self.path_switch.whichChild = coin.SO_SWITCH_ALL
        inner = coin.SoSeparator()
        self.path_switch.addChild(inner)
        path.addChild(self.path_switch)
        self.points = coin.SoCoordinate3()
        inner.addChild(self.points)
        self.future_switch, group = self._switch(inner)
        group.addChild(self._color(PALE_COLOR))
        group.addChild(self._width(1.0))
        self.future = coin.SoLineSet()
        group.addChild(self.future)
        self.done_switch, group = self._switch(inner)
        group.addChild(self._width(PATH_WIDTH))
        binding = coin.SoMaterialBinding()
        binding.value = coin.SoMaterialBinding.PER_PART
        group.addChild(binding)
        self.colors = coin.SoMaterial()
        group.addChild(self.colors)
        self.done = coin.SoLineSet()
        group.addChild(self.done)
        self.current_switch, group = self._switch(inner)
        self.current_color = coin.SoBaseColor()
        group.addChild(self.current_color)
        group.addChild(self._width(PATH_WIDTH))
        self.current_points = coin.SoCoordinate3()
        group.addChild(self.current_points)
        group.addChild(coin.SoLineSet())
        self.root.addChild(path)

    def _build_tool(self):
        coin = self.coin
        tool = coin.SoSeparator()
        self.place = coin.SoTranslation()
        tool.addChild(self.place)
        self.turn = coin.SoRotation()  # the tool along the Z of the zero point it works on
        tool.addChild(self.turn)
        self.cutting = self._solid(CUTTING_COLOR, parent=tool)[1:]
        self.body = self._solid(BODY_COLOR, parent=tool)[1:]
        self.root.addChild(tool)

    def show(self, switch, on):
        switch.whichChild = self.coin.SO_SWITCH_ALL if on else self.coin.SO_SWITCH_NONE

    def set_part(self, vertices, triangles):
        _set_points(self.part_points.point, vertices)
        _set_faces(self.part_faces.coordIndex, triangles)

    def set_stock(self, whole, pieces):
        """Pieces of the stock's surface (model.playback_stock.Material.
        changed_pieces): whole, they are all, the others go."""
        coin = self.coin
        if whole:
            self.stock_group.removeAllChildren()
            self.stock_pieces = {}
        for key, mesh in pieces.items():
            node = self.stock_pieces.get(key)
            if not len(mesh.triangles):
                if node is not None:
                    self.stock_group.removeChild(node[0])
                    del self.stock_pieces[key]
                continue
            if node is None:
                node = (coin.SoSeparator(), coin.SoCoordinate3(), coin.SoIndexedFaceSet())
                node[0].addChild(node[1])
                node[0].addChild(node[2])
                self.stock_group.addChild(node[0])
                self.stock_pieces[key] = node
            _set_points(node[1].point, mesh.vertices)
            _set_faces(node[2].coordIndex, mesh.triangles)

    def set_path(self, polyline):
        """The path of an operation (model.playback.Polyline)."""
        self.count = len(polyline.points)
        self.array = polyline.points
        _set_points(self.points.point, polyline.points)
        rapid = rapid_color()
        colors = np.array([rapid if r else DONE_FEED_COLOR for r in polyline.rapid.tolist()], dtype=np.float32).reshape(-1, 3)
        self.colors.diffuseColor.setNum(len(colors))
        if len(colors):
            self.colors.diffuseColor.setValues(0, len(colors), colors)

    def set_done(self, count, tip, rapid):
        """count points passed; the tool's tip at tip on a rapid move or not."""
        n = self.count
        count = min(max(count, 1), n) if n else 0
        if count >= 2:
            self.done.numVertices.setValues(0, 1, [count])
        self.show(self.done_switch, count >= 2)
        if n - count + 1 >= 2:
            self.future.startIndex = count - 1
            self.future.numVertices.setValues(0, 1, [n - count + 1])
        self.show(self.future_switch, n - count + 1 >= 2)
        partial = tip is not None and 1 <= count < n
        if partial:
            self.current_points.point.setValues(0, 2, [self.array[count - 1].tolist(), list(tip)])
            self.current_color.rgb.setValue(*(rapid_color() if rapid else DONE_FEED_COLOR))
        self.show(self.current_switch, partial)

    def set_tool(self, meshes):
        """The tool's (cutting, body) meshes (vertices, triangles), tip at 0."""
        for (points, faces), (vertices, triangles) in zip((self.cutting, self.body), meshes):
            _set_points(points.point, vertices)
            _set_faces(faces.coordIndex, triangles)

    def set_tip(self, tip, turn=None):
        """The tool's tip there; turn: the quaternion of the zero point it
        works on (model.tilted.rotation), None: not turned."""
        self.place.translation.setValue(*tip)
        self.turn.rotation.setValue(*(turn or (0.0, 0.0, 0.0, 1.0)))


# -- the widgets ---------------------------------------------------------------------


class TimeBar(QtWidgets.QWidget):
    """The time line: the operations one after another as long as they
    take, the time played darker, a mark where the player is; a click or
    a drag goes there."""

    def __init__(self, player, parent=None):
        super().__init__(parent)
        self.player = player
        self.setMinimumHeight(30)
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def _x(self, t):
        total = self.player.timeline.total_s or 1.0
        return 4 + (self.width() - 8) * t / total

    def time_at(self, x):
        total = self.player.timeline.total_s
        return min(max((x - 4) / max(self.width() - 8, 1), 0.0), 1.0) * total

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        line = self.player.timeline
        current = self.player.operation
        h = self.height()
        for k, op in enumerate(line.operations):
            x0, x1 = self._x(op.start_s), self._x(op.end_s)
            rect = QtCore.QRectF(x0, 3, max(x1 - x0, 1.0), h - 6)
            base = QtGui.QColor("#4a7ab8") if k % 2 == 0 else QtGui.QColor("#6f9bd1")
            if k != current:
                base = base.lighter(135)
            painter.fillRect(rect, base)
            done = min(max(self.player.t, op.start_s), op.end_s)
            if done > op.start_s:
                painter.fillRect(QtCore.QRectF(x0, 3, self._x(done) - x0, h - 6), base.darker(135))
            if rect.width() > 24:
                painter.setPen(QtGui.QColor("white"))
                text = painter.fontMetrics().elidedText(op.label, QtCore.Qt.ElideRight, int(rect.width()) - 6)
                painter.drawText(rect.adjusted(3, 0, -3, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, text)
        painter.setPen(QtGui.QPen(QtGui.QColor(CRASH_COLOR), 2))
        for crash in self.player.crashes:
            x = self._x(crash.start_s)
            painter.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, h))
        x = self._x(self.player.t)
        painter.setPen(QtGui.QPen(self.palette().color(QtGui.QPalette.WindowText), 2))
        painter.drawLine(QtCore.QPointF(x, 0), QtCore.QPointF(x, h))
        painter.setBrush(QtGui.QColor("#ef2929"))
        painter.drawEllipse(QtCore.QPointF(x, h / 2.0), 5, 5)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.player.seek(self.time_at(event.position().x()))

    def mouseMoveEvent(self, event):
        t = self.time_at(event.position().x())
        if event.buttons() & QtCore.Qt.LeftButton:
            self.player.seek(t, draw_material=False)
        op = next((o for o in self.player.timeline.operations if o.start_s <= t <= o.end_s), None)
        if op is not None:
            self.setToolTip("{} ({})".format(op.label, model_playback.clock_text(t)))

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.player.seek(self.time_at(event.position().x()))


class _DocumentObserver:
    """Closes the window when its document closes."""

    def __init__(self, player):
        self.player = player

    def slotDeletedDocument(self, doc):
        if doc.Name == self.player.doc_name:
            QtCore.QTimer.singleShot(0, self.player.close)


class SimulationWindow(QtWidgets.QMainWindow):
    """The simulation of a setup (see the module)."""

    def __init__(self, job, prepared, parent=None):
        super().__init__(parent, QtCore.Qt.Window)
        self.setObjectName("AvangardeCam_Simulation")
        self.job = job
        self.doc_name = job.Document.Name
        self.prepared = prepared
        self.timeline = prepared.timeline
        self.t = 0.0
        self.speed = last_speed()
        self.playing = False
        self.operation = None  # whose path is drawn
        self.polyline = None
        self.first_segment = 0
        self.tool_number = None
        self._meshes = {}
        self._clock = None
        self._closed = False
        self._observer = None
        self.material = None
        self._material_at = None  # the time the stock is drawn at
        self._material_drawn = 0.0  # monotonic time of the last drawing
        self.mesh_ms = 0.0  # how long the last drawing took
        self._line_shown = 0.0  # monotonic time the program's line was last selected
        self.crashes = []  # model.playback_stock.PlayedCrash found so far, in time order
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(_FRAME_MS)
        self.timer.timeout.connect(self._tick)
        from pivy import coin

        self.scene = _Scene(coin)
        self._lines_of_steps = [s.line if s.line is not None else -1 for s in self.timeline.steps]
        self.setWindowTitle(tr("Simulation - {}").format(prepared.label))
        self._build()
        self._show_static()
        self._make_material()
        self.show_time(0.0)
        self._draw_material()
        screen = QtGui.QGuiApplication.screenAt(parent.geometry().center()) if parent is not None else None
        area = (screen or QtGui.QGuiApplication.primaryScreen()).availableGeometry()
        self.resize(int(area.width() * _WINDOW_SHARE), int(area.height() * _WINDOW_SHARE))
        self.move(area.center() - self.rect().center())
        self._observer = _DocumentObserver(self)
        FreeCAD.addDocumentObserver(self._observer)
        QtWidgets.QApplication.instance().installEventFilter(self)

    # -- widgets -------------------------------------------------------------------

    def _button(self, parent, icon, tip, slot):
        button = QtWidgets.QToolButton(parent)
        button.setIcon(self.style().standardIcon(icon))
        button.setIconSize(QtCore.QSize(22, 22))
        button.setAutoRaise(True)
        button.setToolTip(tip)
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        button.clicked.connect(slot)
        return button

    def _text_button(self, parent, text, tip, slot):
        button = QtWidgets.QToolButton(parent)
        button.setText(text)
        button.setToolTip(tip)
        button.setFocusPolicy(QtCore.Qt.NoFocus)
        button.clicked.connect(slot)
        return button

    def _check(self, parent, text, on, slot):
        box = QtWidgets.QCheckBox(text, parent)
        box.setChecked(on)
        box.setFocusPolicy(QtCore.Qt.NoFocus)
        box.toggled.connect(slot)
        return box

    def _build(self):
        style = QtWidgets.QStyle
        central = QtWidgets.QWidget(self)
        column = QtWidgets.QVBoxLayout(central)
        column.setContentsMargins(6, 6, 6, 6)
        column.setSpacing(4)

        # the view's buttons, what it shows, how fine the stock is
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(4)
        for text, name in ((tr("Isometric"), "isometric"), (tr("Top"), "top"), (tr("Front"), "front"), (tr("Right"), "right")):
            top.addWidget(self._text_button(central, text, tr("Look from there"), lambda checked=False, n=name: self.view.set_direction(n)))
        top.addWidget(self._text_button(central, tr("Fit"), tr("Everything in sight"), lambda: self.view.fit()))
        top.addSpacing(16)
        self.stock_box = self._check(central, tr("Stock"), True, lambda on: self._show_switch(self.scene.stock_switch, on))
        self.part_box = self._check(central, tr("Part"), False, lambda on: self._show_switch(self.scene.part_switch, on))
        self.path_box = self._check(central, tr("Path"), True, lambda on: self._show_switch(self.scene.path_switch, on))
        for box in (self.stock_box, self.part_box, self.path_box):
            top.addWidget(box)
        top.addSpacing(16)
        top.addWidget(QtWidgets.QLabel(tr("Accuracy:"), central))
        self.accuracy = QtWidgets.QComboBox(central)
        self.accuracy.setFocusPolicy(QtCore.Qt.NoFocus)
        for name, cells in RESOLUTIONS:
            self.accuracy.addItem(tr(name), cells)
        self.accuracy.setCurrentIndex([r for _n, r in RESOLUTIONS].index(last_resolution()))
        self.accuracy.currentIndexChanged.connect(self._accuracy_chosen)
        top.addWidget(self.accuracy)
        self.material_label = QtWidgets.QLabel(central)
        self.material_label.setToolTip(tr("The size of the stock's cells and how long drawing the stock took last"))
        top.addWidget(self.material_label)
        top.addStretch(1)
        column.addLayout(top)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, central)
        self.view = CoinView(self.scene.root, split)
        self.view.set_fit_node(self.scene.lines)  # the stock's box and the zero point, not the tool at Z100
        split.addWidget(self.view)
        side = QtWidgets.QSplitter(QtCore.Qt.Vertical, split)
        ops = QtWidgets.QWidget(side)
        box = QtWidgets.QVBoxLayout(ops)
        box.setContentsMargins(0, 0, 0, 0)
        bold = QtGui.QFont(self.font())
        bold.setBold(True)
        title = QtWidgets.QLabel("{} — {}".format(self.prepared.label, model_playback.clock_text(self.timeline.total_s)), ops)
        title.setFont(bold)
        box.addWidget(title)
        self.list = QtWidgets.QTreeWidget(ops)
        self.list.setRootIsDecorated(False)
        self.list.setColumnCount(3)
        self.list.setHeaderLabels([tr("Operation"), tr("Tool"), tr("Time")])
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)
        for op in self.timeline.operations:
            item = QtWidgets.QTreeWidgetItem([op.label, "T{}".format(op.tool.number), cycle_time.duration_text(op.duration_s)])
            item.setToolTip(0, op.label)
            item.setToolTip(1, tool_text(op.tool))
            item.setTextAlignment(2, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.list.addTopLevelItem(item)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.list.itemClicked.connect(self._operation_clicked)
        box.addWidget(self.list)
        side.addWidget(ops)
        program = QtWidgets.QWidget(side)
        box = QtWidgets.QVBoxLayout(program)
        box.setContentsMargins(0, 0, 0, 0)
        title = QtWidgets.QLabel(tr("Program (.H)"), program)
        title.setObjectName("AvangardeCamPlayProgramTitle")
        title.setToolTip(tr(self.prepared.machine))  # the machine whose program this is
        title.setFont(bold)
        box.addWidget(title)
        self.program = QtWidgets.QListWidget(program)
        self.program.setObjectName("AvangardeCam_SimulationProgram")
        self.program.setUniformItemSizes(True)
        self.program.setFocusPolicy(QtCore.Qt.NoFocus)
        self.program.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.program.addItems(self.timeline.lines)
        # the lines of the other setups gray
        known = [s.line for s in self.timeline.steps if s.line is not None]
        if known:
            gray = self.palette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
            first, last = min(known), max(known)
            for row in list(range(0, first)) + list(range(last + 1, len(self.timeline.lines))):
                self.program.item(row).setForeground(gray)
        self.program.itemClicked.connect(self._line_clicked)
        box.addWidget(self.program)
        side.addWidget(program)
        side.setStretchFactor(0, 1)
        side.setStretchFactor(1, 3)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        column.addWidget(split, 1)

        # the time line and the buttons
        self.time_bar = TimeBar(self, central)
        column.addWidget(self.time_bar)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        self.first_button = self._button(central, style.SP_MediaSkipBackward, tr("The operation before (Up)"), self.previous_operation)
        self.back_button = self._button(central, style.SP_MediaSeekBackward, tr("One block back (Left)"), self.previous_step)
        self.play_button = self._button(central, style.SP_MediaPlay, tr("Play or pause (Space)"), self.toggle)
        self.on_button = self._button(central, style.SP_MediaSeekForward, tr("One block on (Right)"), self.next_step)
        self.last_button = self._button(central, style.SP_MediaSkipForward, tr("The operation after (Down)"), self.next_operation)
        for button in (self.first_button, self.back_button, self.play_button, self.on_button, self.last_button):
            row.addWidget(button)
        self.speed_box = QtWidgets.QComboBox(central)
        self.speed_box.setFocusPolicy(QtCore.Qt.NoFocus)
        self.speed_box.setToolTip(tr("How fast it plays, times the machine"))
        for speed in model_playback.SPEEDS:
            self.speed_box.addItem(model_playback.speed_text(speed), speed)
        self.speed_box.setCurrentIndex(model_playback.SPEEDS.index(self.speed))
        self.speed_box.currentIndexChanged.connect(self._speed_chosen)
        row.addWidget(self.speed_box)
        row.addSpacing(12)
        self.clock = QtWidgets.QLabel(central)
        self.clock.setFont(bold)
        row.addWidget(self.clock)
        row.addSpacing(16)
        self.tool_label = QtWidgets.QLabel(central)
        row.addWidget(self.tool_label)
        row.addSpacing(12)
        self.feed_label = QtWidgets.QLabel(central)
        self.feed_label.setFont(bold)
        row.addWidget(self.feed_label)
        metrics = QtGui.QFontMetrics(bold)
        self.clock.setMinimumWidth(metrics.horizontalAdvance("0:00:00 / 0:00:00") + 4)
        self.feed_label.setMinimumWidth(max(metrics.horizontalAdvance(t) for t in (tr("Tool change"), tr("Dwell"), "F99999.9")) + 4)
        row.addSpacing(16)
        self.crash_button = self._text_button(central, "", "", self.next_crash)
        self.crash_button.setObjectName("AvangardeCam_SimulationCrash")
        self.crash_button.setStyleSheet("QToolButton {{ color: {}; font-weight: bold; }}".format(CRASH_COLOR))
        self.crash_button.hide()
        row.addWidget(self.crash_button)
        row.addStretch(1)
        column.addLayout(row)
        self.setCentralWidget(central)

    def _show_static(self):
        """The part, the stock's box and the zero point."""
        prepared = self.prepared
        self.scene.set_part(prepared.vertices, prepared.triangles)
        self.scene.show(self.scene.part_switch, False)
        b = prepared.stock
        if b is not None:
            corners = [(b.x_min, b.y_min), (b.x_max, b.y_min), (b.x_max, b.y_max), (b.x_min, b.y_max), (b.x_min, b.y_min)]
            lines = [[(x, y, b.z_min) for x, y in corners], [(x, y, b.z_max) for x, y in corners]]
            lines += [[(x, y, b.z_min), (x, y, b.z_max)] for x, y in corners[:4]]
            self.scene.add_lines(lines, (0.2, 0.2, 0.2))
            size = 0.12 * max(b.x_max - b.x_min, b.y_max - b.y_min, b.z_max - b.z_min)
        else:
            size = 10.0
        for k, color in enumerate(((0.85, 0.1, 0.1), (0.1, 0.65, 0.1), (0.1, 0.2, 0.9))):
            end = [0.0, 0.0, 0.0]
            end[k] = size
            self.scene.add_lines([[(0.0, 0.0, 0.0), tuple(end)]], color, 2.0)

    def _show_switch(self, switch, on):
        self.scene.show(switch, on)
        self.view.redraw()

    # -- the material ----------------------------------------------------------------

    def _make_material(self):
        stock = self.prepared.stock
        if stock is None:
            self.material = None
            self.stock_box.setEnabled(False)
            self.accuracy.setEnabled(False)
            self.scene.show(self.scene.stock_switch, False)
            self.material_label.setText(tr("no stock"))
            return
        self.material = playback_stock.Material(self.timeline, stock, self.prepared.tools, last_resolution(), start=self.prepared.start)
        self._material_at = None
        self._forget_crashes()

    def _draw_material(self):
        """The stock as it is at the player's time, drawn."""
        if self.material is None or self._material_at == self.t:
            return
        busy = not self.playing
        if busy:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            began = time.monotonic()
            self.material.cut_to(self.t)
            self.scene.set_stock(*self.material.changed_pieces())
            self.mesh_ms = (time.monotonic() - began) * 1000.0
        finally:
            if busy:
                QtWidgets.QApplication.restoreOverrideCursor()
        self._material_at = self.t
        self._material_drawn = time.monotonic()
        self.material_label.setText(tr("cell {:.2f} mm, drawn in {:.0f} ms").format(self.material.cell_mm, self.mesh_ms))
        self.time_bar.update()
        self.view.redraw()
        self._take_crashes()

    # -- what the machine runs into ------------------------------------------------------

    def _forget_crashes(self):
        """None found yet (a new stock)."""
        for crash in self.crashes:
            if crash.line is not None:
                item = self.program.item(crash.line)
                item.setData(QtCore.Qt.BackgroundRole, None)
        self.crashes = []
        self.crash_button.hide()
        self.time_bar.update()

    def _take_crashes(self):
        """The crashes the stock found since, shown; while it plays it
        stops at the first new one, at the end of its block."""
        if self.material is None or len(self.material.crashes) == len(self.crashes):
            return
        known = {(c.kind, c.segment) for c in self.crashes}
        self.crashes = playback_stock.played_crashes(self.material)
        new = [c for c in self.crashes if (c.kind, c.segment) not in known]
        for crash in new:
            if crash.line is not None:
                self.program.item(crash.line).setBackground(QtGui.QColor(CRASH_LINE_COLOR))
        self._show_crash(new[0])
        self.time_bar.update()
        if self.playing:
            self.pause()
            self.seek(min(self.timeline.steps[new[0].step].end_s, self.t))

    def _show_crash(self, crash):
        text = crash_text(crash, self.timeline.lines)
        if len(self.crashes) > 1:
            text = tr("{} of {}: {}").format(self.crashes.index(crash) + 1, len(self.crashes), text)
        self.crash_button.setText("⚠ " + text)
        tips = [crash_text(c, self.timeline.lines) for c in self.crashes[:30]]
        if len(self.crashes) > 30:
            tips.append("…")
        self.crash_button.setToolTip(tr("To the next one") + "\n\n" + "\n".join(tips))
        self.crash_button.show()

    def next_crash(self):
        """To the end of the block of the next crash found (after the
        last, the first again)."""
        if not self.crashes:
            return
        ends = [self.timeline.steps[c.step].end_s for c in self.crashes]
        k = next((k for k, end in enumerate(ends) if end > self.t + 1e-6), 0)
        target = (self.crashes[k].kind, self.crashes[k].segment)
        self.pause()
        self.seek(ends[k])  # may find more: the list anew
        self._show_crash(next(c for c in self.crashes if (c.kind, c.segment) == target))

    def _accuracy_chosen(self, index):
        params().SetInt(_LAST_RESOLUTION, RESOLUTIONS[index][1])
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self._make_material()
            self._draw_material()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    # -- playing ---------------------------------------------------------------------

    def play(self):
        if self.t >= self.timeline.total_s - 1e-9:
            self.seek(0.0)
        self.playing = True
        self._clock = time.monotonic()
        self.timer.start()
        self.play_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPause))

    def pause(self):
        self.playing = False
        self.timer.stop()
        self.play_button.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay))
        index = self.timeline.step_at(self.t)
        if index is not None:
            self._show_line(self.timeline.steps[index].line)
        self._draw_material()

    def toggle(self):
        if self.playing:
            self.pause()
        else:
            self.play()

    def _tick(self):
        if self.doc_name not in FreeCAD.listDocuments():
            self.close()
            return
        now = time.monotonic()
        t = self.t + min(now - self._clock, _MOST_FRAME_S) * self.speed
        self._clock = now
        crash = next((c for c in self.crashes if self.t < self.timeline.steps[c.step].end_s <= t), None)
        if crash is not None:  # found before: it stops there
            self.show_time(self.timeline.steps[crash.step].end_s)
            self.pause()
            self._show_crash(crash)
            return
        if t >= self.timeline.total_s:
            self.show_time(self.timeline.total_s)
            self.pause()
            return
        self.show_time(t)
        # the stock again when it is due: at most every MESH_MS, and at most half the time
        if (now - self._material_drawn) * 1000.0 >= max(MESH_MS, 2.0 * self.mesh_ms):
            self._draw_material()
            self._clock = time.monotonic()  # the time the drawing took is not played over

    def seek(self, t, draw_material=True):
        self._clock = time.monotonic()
        self.show_time(min(max(t, 0.0), self.timeline.total_s))
        if draw_material and not self.playing:
            self._draw_material()

    def next_step(self):
        self.pause()
        self.seek(self.timeline.next_stop(self.t))

    def previous_step(self):
        self.pause()
        self.seek(self.timeline.previous_stop(self.t))

    def next_operation(self):
        self.seek(self.timeline.next_operation(self.t))

    def previous_operation(self):
        self.seek(self.timeline.previous_operation(self.t))

    def _speed_chosen(self, index):
        self.speed = model_playback.SPEEDS[index]
        params().SetFloat(_LAST_SPEED, self.speed)

    def _operation_clicked(self, item, _column):
        self.seek(self.timeline.operations[self.list.indexOfTopLevelItem(item)].start_s)

    def _line_clicked(self, item):
        """To where the block of that line has run (a line without a
        block: to where the next block starts)."""
        row = self.program.row(item)
        steps = self.timeline.steps
        mine = [k for k, line in enumerate(self._lines_of_steps) if line == row]
        if mine:
            self.seek(steps[mine[-1]].end_s)
            return
        after = next((k for k, line in enumerate(self._lines_of_steps) if line > row), None)
        self.seek(steps[after].start_s if after is not None else self.timeline.total_s)

    # -- showing ---------------------------------------------------------------------

    def _tool_meshes(self, tool):
        if tool.number not in self._meshes:
            profile = model_playback.tool_profile(self.prepared.tools.get(tool.number), tool.diameter_mm)
            self._meshes[tool.number] = [model_playback.revolve(p, _TOOL_SIDES) for p in profile]
        return self._meshes[tool.number]

    def show_time(self, t):
        """Everything but the stock as it is at time t."""
        self.t = t
        line = self.timeline
        index = line.step_at(t)
        if index is None:
            return
        step = line.steps[index]
        if step.operation != self.operation:
            self._show_operation(step.operation)
        if step.tool.number != self.tool_number:
            self.scene.set_tool(self._tool_meshes(step.tool))
            self.tool_number = step.tool.number
        tip = line.position(t)
        self.scene.set_tip(tip, tilted.rotation(line.zero_at(t)))
        segment, share = line.segment_at(t)
        poly = self.polyline
        last = self.first_segment + len(poly.firsts) - 1
        if segment is None or segment < self.first_segment:
            count, rapid, partial = 1, True, None
        elif segment >= last:
            count, rapid, partial = len(poly.points), True, None
        else:
            count = poly.done(segment - self.first_segment, share)
            rapid = line.segments[segment].rapid
            partial = tip
        self.scene.set_done(count, partial, rapid)
        self.clock.setText("{} / {}".format(model_playback.clock_text(t), model_playback.clock_text(line.total_s)))
        self.tool_label.setText(tool_text(step.tool))
        self.feed_label.setText(feed_text(step))
        self._show_line(step.line)
        self.time_bar.update()
        self.view.redraw()

    def _show_line(self, line):
        """The program's line the machine runs, selected and in the middle;
        while it plays at most every MESH_MS (a selection in a list of tens
        of thousands of lines takes some ms)."""
        if line is None or self.program.currentRow() == line:
            return
        now = time.monotonic()
        if self.playing and (now - self._line_shown) * 1000.0 < MESH_MS:
            return
        self._line_shown = now
        self.program.setCurrentRow(line)
        self.program.scrollToItem(self.program.item(line), QtWidgets.QAbstractItemView.PositionAtCenter)

    def _show_operation(self, index):
        self.operation = index
        op = self.timeline.operations[index]
        self.polyline, self.first_segment = model_playback.operation_polyline(self.timeline, op)
        self.scene.set_path(self.polyline)
        for k in range(self.list.topLevelItemCount()):
            item = self.list.topLevelItem(k)
            font = item.font(0)
            font.setBold(k == index)
            for column in range(3):
                item.setFont(column, font)
        self.list.setCurrentItem(self.list.topLevelItem(index))

    def current_line(self):
        """The program's line the machine runs, as shown."""
        item = self.program.currentItem()
        return item.text() if item is not None else ""

    # -- keys --------------------------------------------------------------------------

    _KEYS = (QtCore.Qt.Key_Space, QtCore.Qt.Key_Left, QtCore.Qt.Key_Right, QtCore.Qt.Key_Up, QtCore.Qt.Key_Down,
             QtCore.Qt.Key_Home, QtCore.Qt.Key_End, QtCore.Qt.Key_Escape)  # fmt: skip

    def _ours(self, event):
        """A key of the player's, without Ctrl/Alt, in this window, not in a field."""
        if event.key() not in self._KEYS or event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier):
            return False
        app = QtWidgets.QApplication.instance()
        if app.activeWindow() is not self or app.activePopupWidget() is not None:
            return False
        typing = (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)
        return not isinstance(app.focusWidget(), typing)

    def key(self, key):
        """What a key does (see the module)."""
        actions = {
            QtCore.Qt.Key_Space: self.toggle,
            QtCore.Qt.Key_Left: self.previous_step,
            QtCore.Qt.Key_Right: self.next_step,
            QtCore.Qt.Key_Up: self.previous_operation,
            QtCore.Qt.Key_Down: self.next_operation,
            QtCore.Qt.Key_Home: lambda: self.seek(0.0),
            QtCore.Qt.Key_End: lambda: self.seek(self.timeline.total_s),
            QtCore.Qt.Key_Escape: self.close,
        }
        actions[key]()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.ShortcutOverride and self._ours(event):
            event.accept()  # not a shortcut: the key press comes to us
            return True
        if kind == QtCore.QEvent.KeyPress and self._ours(event):
            if not event.isAutoRepeat() or event.key() != QtCore.Qt.Key_Space:
                self.key(event.key())
            return True
        return False

    def closeEvent(self, event):
        global _window
        if not self._closed:
            self._closed = True
            self.playing = False
            self.timer.stop()
            QtWidgets.QApplication.instance().removeEventFilter(self)
            if self._observer is not None:
                FreeCAD.removeDocumentObserver(self._observer)
                self._observer = None
            self.material = None
        if _window is self:
            _window = None
        super().closeEvent(event)
