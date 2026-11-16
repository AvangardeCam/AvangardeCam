# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""CAM > Verify: the active setup's program cut out of its stock and
checked against the part (engine.verify), in a window beside the 3D view.

The window opens at once, with nothing worked out yet: the user chooses
how fine (Rough, Medium, Fine) and presses Start (user, 2026-10-27). Start
recomputes the document and reads the setup (engine.verify.prepare, in
FreeCAD's thread: the part's triangles take a few seconds the first time),
then the cutting runs in a thread of its own (it takes seconds to minutes), the
window says which step it is on. Then the 3D view shows the stock left, in
colours, instead of the part, its stock and the paths: gray the part,
blue material left, red too deep or a thread without its hole. Export...
saves the stock left (.ply with the colours, .stl the bare shape). Closing
the window gives the view back.
The stock left is in the setup's coordinates, the coordinates the view is
drawn in (ui.scene), so its node goes before the view's transform.
"""

import threading

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets

from avangardecam import params, tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import op_zero
from avangardecam.engine import verify as engine_verify
from avangardecam.model import crashes
from avangardecam.model import verify as model_verify
from avangardecam.model.verify import stock_verify
from avangardecam.ui import postprocessors, scene

# cells on the longest edge of the stock (user, 2026-10-27: a choice, Medium at first)
RESOLUTIONS = ((QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Rough"), 150),
               (QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Medium"), 250),
               (QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "Fine"), 500))  # fmt: skip
DEFAULT_RESOLUTION = 250
_LAST_RESOLUTION = "LastVerifyResolution"
_LAST_EXPORT_DIR = "LastVerifyExportDir"
_NODE_NAME = "AvangardeCamVerify"
_POLL_MS = 150
_MARGIN_PX = 24
_TOP_PX = 190  # below the ribbon
_LEGEND = (
    (stock_verify.GRAY, QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "the part")),
    (stock_verify.BLUE, QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "material left")),
    (stock_verify.RED, QtCore.QT_TRANSLATE_NOOP("AvangardeCam", "too deep, thread without its hole")),
)

_window = None


def verify_window():
    """The open Verify window, or None."""
    return _window if _window is not None and _window.isVisible() else None


def start(job):
    """Open the window for a setup; it works when the user presses Start."""
    global _window
    if verify_window() is not None:
        _window.close()
    main = FreeCADGui.getMainWindow()
    _window = VerifyWindow(job, main)
    _window.show()
    # in the top right corner, under the ribbon: the part stays in sight
    frame = main.frameGeometry()
    _window.move(frame.right() - _window.frameGeometry().width() - _MARGIN_PX, frame.top() + _TOP_PX)
    return _window


def last_resolution():
    value = params().GetInt(_LAST_RESOLUTION, DEFAULT_RESOLUTION)
    return value if value in [r for _name, r in RESOLUTIONS] else DEFAULT_RESOLUTION


# -- the 3D view -------------------------------------------------------------------


def _views(doc):
    gui_doc = FreeCADGui.getDocument(doc.Name)
    return gui_doc.mdiViewsOfType("Gui::View3DInventor") if gui_doc is not None else []


def _node(result, place=None):
    """The stock left; place: where the view has its coordinates (the
    setup's default zero point seen from the active one), None: as they are."""
    from pivy import coin

    node = coin.SoSeparator()
    node.setName(_NODE_NAME)
    if place is not None:
        move = coin.SoTransform()
        move.translation.setValue(place.Base.x, place.Base.y, place.Base.z)
        move.rotation.setValue(*place.Rotation.Q)
        node.addChild(move)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.SOLID
    hints.creaseAngle = 0.5
    binding = coin.SoMaterialBinding()
    binding.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
    material = coin.SoMaterial()
    material.diffuseColor.setValues(0, len(result.colors), result.colors.tolist())
    points = coin.SoCoordinate3()
    points.point.setValues(0, len(result.vertices), result.vertices.tolist())
    faces = coin.SoIndexedFaceSet()
    index = [-1] * (4 * len(result.triangles))
    for k in range(3):
        index[k::4] = result.triangles[:, k].tolist()
    faces.coordIndex.setValues(0, len(index), index)
    for child in (hints, binding, material, points, faces):
        node.addChild(child)
    return node


def shown(doc):
    """Whether a 3D view of doc shows the stock left."""
    for view in _views(doc):
        root = view.getSceneGraph()
        if any(root.getChild(i).getName() == _NODE_NAME for i in range(root.getNumChildren())):
            return True
    return False


def _remove(doc):
    for view in _views(doc):
        root = view.getSceneGraph()
        for i in reversed(range(root.getNumChildren())):
            if root.getChild(i).getName() == _NODE_NAME:
                root.removeChild(i)


def show(job, result):
    """The stock left in every 3D view instead of the part, its stock and paths."""
    doc = job.Document
    _remove(doc)
    node = _node(result, op_zero.from_default_placement(job))
    for view in _views(doc):
        root = view.getSceneGraph()
        names = [root.getChild(i).getName() for i in range(root.getNumChildren())]
        # before the setup's transform (ui.scene): the stock left is in the setup's coordinates
        for before in (scene._FRAME_NAME, scene._FRAME_BEFORE):
            if before in names:
                root.insertChild(node, names.index(before))
                break
        else:
            root.addChild(node)
    hide = list(cam.models(doc)) + [job.Stock] + list(job.Operations.Group)
    for obj in hide:
        vo = getattr(obj, "ViewObject", None) if obj is not None else None
        if vo is not None:
            vo.Visibility = False


def hide(doc):
    """The view as ui.scene draws it again."""
    if doc is None or doc.Name not in FreeCAD.listDocuments():
        return
    _remove(doc)
    scene.apply(doc)


# -- the window ----------------------------------------------------------------------


class VerifyWindow(QtWidgets.QDialog):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self.doc = job.Document
        self.result = None
        self._state = None  # of the thread: {"step": text, "result": ..., "error": ...}
        self.setWindowTitle(tr("Verify - {}").format(job.Label))
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        layout = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(tr("Accuracy")))
        self.resolution = QtWidgets.QComboBox()
        for name, cells in RESOLUTIONS:
            self.resolution.addItem("{} ({} {})".format(tr(name), cells, tr("cells")), cells)
        self.resolution.setCurrentIndex([r for _n, r in RESOLUTIONS].index(last_resolution()))
        self.resolution.setToolTip(tr("Cells on the longest edge of the stock: finer takes longer"))
        row.addWidget(self.resolution, 1)
        self.start_button = QtWidgets.QPushButton(tr("Start"))
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.run)
        row.addWidget(self.start_button)
        layout.addLayout(row)

        self.step = QtWidgets.QLabel(tr("Choose the accuracy and press Start."))
        layout.addWidget(self.step)
        self.busy = QtWidgets.QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.hide()
        layout.addWidget(self.busy)

        self.report = QtWidgets.QTextBrowser()
        self.report.setMinimumSize(460, 220)
        layout.addWidget(self.report, 1)

        legend = QtWidgets.QHBoxLayout()
        for rgb, text in _LEGEND:
            swatch = QtWidgets.QLabel()
            pixmap = QtGui.QPixmap(14, 14)
            pixmap.fill(QtGui.QColor.fromRgbF(*(float(c) for c in rgb)))
            swatch.setPixmap(pixmap)
            legend.addWidget(swatch)
            legend.addWidget(QtWidgets.QLabel(tr(text)))
            legend.addSpacing(12)
        legend.addStretch(1)
        layout.addLayout(legend)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        self.export_button = buttons.addButton(tr("Export..."), QtWidgets.QDialogButtonBox.ActionRole)
        self.export_button.setToolTip(tr("Save the stock left: .ply with the colours, .stl the bare shape"))
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        layout.addWidget(buttons)

        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(_POLL_MS)
        self.timer.timeout.connect(self._poll)

    def running(self):
        return self._state is not None and "done" not in self._state

    def run(self):
        """Read the setup, then cut and check at the chosen accuracy in a
        thread of its own."""
        if self.running():
            return
        cells = self.resolution.currentData()
        params().SetInt(_LAST_RESOLUTION, cells)
        state = {"step": "Reading the program and the part"}
        self._state = state
        self.start_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.resolution.setEnabled(False)
        self.busy.show()
        self.step.setText(tr(state["step"]))
        self.report.clear()
        # the window shows the step before FreeCAD's thread is busy
        QtCore.QTimer.singleShot(50, lambda: self._prepare_and_cut(state, cells))

    def _prepare_and_cut(self, state, cells):
        if self.doc.Name not in FreeCAD.listDocuments():
            state.update(done=True, error=tr("the document is closed"))
            self._poll()
            return
        try:
            self.doc.recompute()
            prepared = engine_verify.prepare(self.job, postprocessors.last())
        except Exception as exc:  # ProjectError and what FreeCAD raises, shown in the window
            state.update(done=True, error=exc)
            self._poll()
            return

        def work():
            try:
                state["result"] = engine_verify.run(prepared, cells, progress=lambda text: state.update(step=text))
            except Exception as exc:  # shown in the window, the thread must not die silently
                state["error"] = exc
            state["done"] = True

        threading.Thread(target=work, daemon=True).start()
        self.timer.start()

    def _poll(self):
        state = self._state
        self.step.setText(tr(state["step"]))
        if "done" not in state:
            return
        self.timer.stop()
        self.busy.hide()
        self.start_button.setEnabled(True)
        self.resolution.setEnabled(True)
        if "error" in state:
            self.step.setText(tr("The verification failed: {}").format(state["error"]))
            return
        if self.doc.Name not in FreeCAD.listDocuments():
            return
        self.result = state["result"]
        self.step.setText(tr("Done"))
        self.report.setHtml(report_html(self.result))
        self.export_button.setEnabled(True)
        show(self.job, self.result)

    def export(self):
        """Ask where, then save the stock left (export_to)."""
        import os

        folder = params().GetString(_LAST_EXPORT_DIR, "") or os.path.expanduser("~")
        name = "{} {} stock".format(self.doc.Label, self.job.Label)
        ply, stl = tr("Stock with colours") + " (*.ply)", tr("Stock shape") + " (*.stl)"
        path, chosen = QtWidgets.QFileDialog.getSaveFileName(
            self, tr("Export the stock left"), os.path.join(folder, name + ".ply"), ";;".join((ply, stl))
        )
        if not path:
            return None
        if os.path.splitext(path)[1].lower() not in (".ply", ".stl"):
            path += ".stl" if chosen == stl else ".ply"
        return self.export_to(path)

    def export_to(self, path):
        import os

        try:
            model_verify.export(self.result, path)
        except (OSError, ValueError) as exc:
            self.step.setText(tr("Not saved: {}").format(exc))
            return None
        params().SetString(_LAST_EXPORT_DIR, os.path.dirname(path))
        self.step.setText(tr("Saved: {}").format(path))
        return path

    def closeEvent(self, event):
        self.timer.stop()  # a cutting still running ends unseen
        hide(self.doc)
        super().closeEvent(event)


def _point(p):
    # + 0.0: a hair below 0 (-1.7e-08 on a STEP part's top) is Z+0.000, not Z-0.000
    return "X{:+.3f} Y{:+.3f} Z{:+.3f}".format(*(round(float(v), 3) + 0.0 for v in p))


def report_html(result):
    """What the verification found, for the window."""
    parts = []
    if result.gouges:
        rows = "".join(
            "<li><b>{}</b>: {} {} {} ({} {})</li>".format(
                g.operation, tr("{:.3f} mm too deep").format(g.depth_mm), tr("at"), _point(g.point), g.points, tr("points")
            )
            for g in result.gouges
        )  # fmt: skip
        parts.append("<p><span style='color:#c00'><b>{}</b></span></p><ul>{}</ul>".format(tr("Too deep into the part"), rows))
    else:
        parts.append("<p><b>{}</b></p>".format(tr("Nowhere too deep into the part.")))
    rapid = [c for c in result.collisions if c.kind == crashes.RAPID]
    if rapid:
        rows = "".join(
            "<li><b>{}</b>: {} {} → {} ({:.1f} mm³)</li>".format(c.operation, tr("rapid"), _point(c.start), _point(c.end), c.volume_mm3)
            for c in rapid
        )  # fmt: skip
        parts.append("<p><span style='color:#c00'><b>{}</b></span></p><ul>{}</ul>".format(tr("Rapid moves into material"), rows))
    else:
        parts.append("<p><b>{}</b></p>".format(tr("No rapid move into material.")))
    shank = [c for c in result.collisions if c.kind == crashes.SHANK]
    if shank:
        rows = "".join(
            "<li><b>{}</b>: {} → {} ({:.1f} mm³)</li>".format(c.operation, _point(c.start), _point(c.end), c.volume_mm3)
            for c in shank
        )  # fmt: skip
        parts.append(
            "<p><span style='color:#c00'><b>{}</b></span><br>{}</p><ul>{}</ul>".format(
                tr("Shank or neck in material"), tr("The tool goes deeper than its cutting length: what is above it does not cut."), rows
            )
        )  # fmt: skip
    without = [h for h in result.holes if h.volume_mm3]
    if without:
        rows = "".join(
            "<li><b>{}</b>: {} {} ({})</li>".format(
                h.operation, tr("the hole at"), _point(h.centre), tr("{:.1f} mm³ in the way of the thread mill's body").format(h.volume_mm3)
            )
            for h in without
        )  # fmt: skip
        parts.append(
            "<p><span style='color:#c00'><b>{}</b></span><br>{}</p><ul>{}</ul>".format(
                tr("Threads without their hole"), tr("Not drilled, or drilled too small or too shallow for the thread mill."), rows
            )
        )  # fmt: skip
    elif any(h.volume_mm3 == 0.0 for h in result.holes):
        parts.append("<p><b>{}</b></p>".format(tr("Every thread has its hole.")))
    unchecked = [h for h in result.holes if h.volume_mm3 is None]
    if unchecked:
        rows = "".join("<li><b>{}</b>: {}</li>".format(h.operation, _point(h.centre)) for h in unchecked)
        parts.append("<p><b>{}</b></p><ul>{}</ul>".format(tr("Holes not checked: the thread mill is no wider than its teeth"), rows))
    if result.notes:
        rows = "".join("<li>{}</li>".format(n) for n in result.notes)
        parts.append("<p><b>{}</b></p><ul>{}</ul>".format(tr("The control would stop"), rows))
    parts.append(
        "<p style='color:gray'>{}</p>".format(
            tr("Cells of {:.2f} mm; too deep from {:g} mm. Thread milling is not checked for too deep, "
               "only for material in its hole inside the thread mill's teeth.").format(
                result.cell_mm, result.tolerance_mm
            )
        )
    )
    return "".join(parts)
