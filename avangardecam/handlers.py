# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""What the actions of actions.py do.

Each handler takes no arguments. An action whose handler is empty is a
placeholder: clicking it only says so in the status bar and the details panel.
"""

import os
from typing import NamedTuple

import FreeCAD
import FreeCADGui
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import params, tool_library_path, tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import geometry

STATUS_TIMEOUT_MS = 4000


def run(action):
    """Run the handler of an action, or report it as a placeholder."""
    if not action.handler:
        _placeholder(action)
        return
    globals()[action.handler]()


def _placeholder(action):
    from avangardecam.ui.layout import LAYOUT

    message = tr("{}: not implemented yet").format(tr(action.text))
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)
    if LAYOUT.panel is not None:
        LAYOUT.panel.show_placeholder(action)


# -- File ------------------------------------------------------------------


def new_document():
    FreeCADGui.runCommand("Std_New", 0)


def open_document():
    FreeCADGui.runCommand("Std_Open", 0)


def save_document():
    FreeCADGui.runCommand("Std_Save", 0)


def save_document_as():
    FreeCADGui.runCommand("Std_SaveAs", 0)


def import_step(path=None):
    """Add a STEP model to the active document (a new one if there is none).

    Without a path a file dialog asks for one; returns the imported path or None.
    """
    if path is None:
        from PySide import QtWidgets

        path, _filter = QtWidgets.QFileDialog.getOpenFileName(
            FreeCADGui.getMainWindow(),
            tr("Import model (STEP)"),
            params().GetString("LastImportDir", os.path.expanduser("~")),
            tr("STEP models") + " (*.step *.stp *.STEP *.STP)",
        )
        if not path:
            return None
    params().SetString("LastImportDir", os.path.dirname(path))

    import ImportGui

    doc = FreeCAD.ActiveDocument or FreeCAD.newDocument()
    before = {obj.Name for obj in doc.Objects}
    ImportGui.insert(path, doc.Name)
    doc.recompute()

    # every model belongs to every setup (CAM job), which also holds the
    # stock and the tools
    if cam.find_job(doc) is None:
        cam.ensure_job(doc)
    else:
        imported = [obj for obj in cam.models(doc) if obj.Name not in before]
        doc.openTransaction(tr("Add model"))
        for obj in imported:
            cam.add_model(doc, obj)
        doc.commitTransaction()

    from avangardecam.ui import scene

    scene.show_all(doc, isometric=True)
    return path


def export_nc(path=None, post=None):
    """The project as one Heidenhain program (.H): every setup on its own
    preset, written by the postprocessor of one machine (post.machines).
    Without a path a file dialog asks for the file and the machine; with
    one and no postprocessor, the one chosen last writes it. Returns the
    path written or None."""
    from avangardecam.ui import postprocessors

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return None
    if not any(cam.operations(job) for job in cam.setups(doc)):
        _status(tr("Add an operation first (CAM > Contour tooling)."))
        return None
    if path is None:
        asked = postprocessors.ask(doc)
        if asked is None:
            return None
        path, post = asked
    post = post or postprocessors.last()
    module = post.module
    if os.path.splitext(path)[1].upper() != module.EXTENSION:
        path += module.EXTENSION
    name = module.program_name(os.path.splitext(os.path.basename(path))[0])
    doc.recompute()
    try:
        text = post.write(cam.nc_program(doc, name, doc.Label))
        module.save(text, path)
    except (cam.ProjectError, ValueError, OSError) as exc:
        _error(str(exc))
        return None
    params().SetString("LastExportDir", os.path.dirname(path))
    postprocessors.remember(post)
    _status(tr("NC program saved: {} ({})").format(path, tr(post.label)))
    return path


def simulate():
    """The active setup's operations machining its stock, in the simulator."""
    from avangardecam.ui import scene, simulation

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return None
    job = scene.active_setup(doc)
    doc.recompute()
    ops = simulation.operations(job)
    if not ops:
        _status(tr("{} has no operation to simulate yet (CAM > Contour tooling, Drilling, Thread milling, Adaptive, Facing, Slot).").format(job.Label))  # fmt: skip
        return None
    try:
        return simulation.start(job, ops)
    except Exception as exc:  # the simulator is FreeCAD's C++ module and its OpenGL
        _error(tr("The simulation could not start: {}").format(exc))
        return None


def verify():
    """The active setup's program cut out of its stock and checked against the part."""
    from avangardecam.ui import scene
    from avangardecam.ui import verify as ui_verify

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return None
    job = scene.active_setup(doc)
    if not any(getattr(op, "Active", True) for op in job.Operations.Group):
        _status(tr("{} has no operation to verify yet.").format(job.Label))
        return None
    # at once: the window recomputes and reads the setup on Start
    return ui_verify.start(job)


def play():
    """The active setup's program played as the machine runs it, in a window of its own."""
    from avangardecam.ui import playback, scene

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return None
    job = scene.active_setup(doc)
    if not any(getattr(op, "Active", True) for op in job.Operations.Group):
        _status(tr("{} has no operation to play yet.").format(job.Label))
        return None
    return playback.start_or_say(job)


def cycle_time():
    """How long each setup and operation of the project takes on the machine, in a window."""
    from avangardecam.ui import cycle_time as ui_cycle_time

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return None
    if not cam.setups(doc):
        _status(tr("The project has no setup yet."))
        return None
    return ui_cycle_time.show_window(doc)


# -- helpers ---------------------------------------------------------------


def _status(message):
    FreeCADGui.getMainWindow().statusBar().showMessage(message, STATUS_TIMEOUT_MS)


def _error(message):
    from PySide import QtWidgets

    QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), "AvangardeCam", message)


def _panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def _select(kind, name):
    if _panel() is not None:
        _panel().select_entry(kind, name)


def _model_elements():
    """(model, "FaceN"/"EdgeN") of the elements of project models selected
    in 3D, in the order they were clicked (cam.model_element)."""
    found = []
    for selection in FreeCADGui.Selection.getSelectionEx("", 0):
        for sub in selection.SubElementNames:
            element = cam.model_element(selection.Object, sub)
            if element is not None:
                found.append(element)
    return found


def _selected_face():
    """(model, "FaceN") of the one face selected in 3D, else None."""
    faces = []
    for selection in FreeCADGui.Selection.getSelectionEx("", 0):
        for sub in selection.SubElementNames:
            if sub.split(".")[-1].startswith("Face"):
                faces.append(cam.model_element(selection.Object, sub))
    if len(faces) != 1:
        return None
    return faces[0]  # a face of a job's clone is the same face of the original


def _selected_sketch():
    """The sketch selected in 3D or in the project list, else None."""
    for obj in FreeCADGui.Selection.getSelection():
        if geometry.is_sketch(obj):
            return obj
    entry = _panel().current_entry() if _panel() is not None else None
    if entry is not None and entry[0] == "sketch":
        return entry[1]
    return None


def _models_or_say(doc):
    if doc is None or not cam.models(doc):
        _status(tr("Import a model first (File > Import model)."))
        return None
    return cam.models(doc)


# -- CAD -------------------------------------------------------------------


def extract_boundary():
    """Sketch of the boundary edges of the selected flat face."""
    doc = FreeCAD.ActiveDocument
    models = _models_or_say(doc)
    if models is None:
        return
    picked = _selected_face()
    if picked is None:
        _status(tr("Select one flat face of the model first, then click Extract boundary edges."))
        return
    doc.openTransaction(tr("Extract boundary edges"))
    try:
        sketch = geometry.extract_boundary(doc, models, *picked)
    except cam.ProjectError as exc:
        doc.abortTransaction()
        _error(str(exc))
        return
    doc.commitTransaction()
    _select("sketch", sketch.Name)
    # selected at once: its lines are red, ready for Contour tooling
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc.Name, sketch.Name)


# -- CAM -------------------------------------------------------------------


def edit_stock():
    """Show the active setup's stock, creating the first setup if needed."""
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return
    job = scene.active_setup(doc)
    if job is None:
        doc.openTransaction(tr("Create setup"))
        try:
            job = cam.ensure_job(doc)
        finally:
            doc.commitTransaction()
    _select("stock", job.Stock.Name)


def stock_window():
    """CAM > Stock: the active setup's stock in a window (ui.stock_dialog),
    the first setup made if there is none yet."""
    from avangardecam.ui import scene, stock_dialog

    edit_stock()
    doc = FreeCAD.ActiveDocument
    job = scene.active_setup(doc) if doc is not None else None
    if job is None or job.Stock is None:
        return False
    return stock_dialog.ask(job)


def custom_stock(path=None, middle=None):
    """CAM > Custom stock: the active setup starts from a model of the blank
    in a file (ui.custom_stock), the first setup made if there is none yet;
    path given: no window (tests)."""
    from avangardecam.ui import custom_stock as ui_custom_stock
    from avangardecam.ui import scene

    edit_stock()
    doc = FreeCAD.ActiveDocument
    job = scene.active_setup(doc) if doc is not None else None
    if job is None or job.Stock is None:
        return False
    return ui_custom_stock.ask(job, path, middle)


def next_setup():
    """CAM > Next setup: a new setup and the stock it starts from (ui.next_setup)."""
    from avangardecam.ui import next_setup as ui_next_setup
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    models = _models_or_say(doc)
    if models is None:
        return None
    job = ui_next_setup.run(doc, models, _selected_face())
    if job is not None:
        FreeCADGui.Selection.clearSelection()
        scene.set_active_setup(job)
        _select("setup", job.Name)
    return job


def _ask_move_or_new(job, same_axis):
    """"move", "new" or None (cancelled) for a setup that has operations."""
    from PySide import QtWidgets

    box = QtWidgets.QMessageBox(FreeCADGui.getMainWindow())
    box.setWindowTitle(tr("Snap-0-Point"))
    box.setIcon(QtWidgets.QMessageBox.Question)
    new = box.addButton(tr("New setup"), QtWidgets.QMessageBox.AcceptRole)
    move = None
    if same_axis:
        box.setText(
            tr("{} already has operations.\n\nMove its zero point to this face (the operations follow), or make a new setup for another clamping?").format(job.Label)  # fmt: skip
        )
        move = box.addButton(tr("Move zero of {}").format(job.Label), QtWidgets.QMessageBox.AcceptRole)
    else:
        box.setText(
            tr("{} already has operations, and this face needs the tool from another side.\n\nMake a new setup (another clamping) with its zero point on this face?").format(job.Label)  # fmt: skip
        )
    box.addButton(QtWidgets.QMessageBox.Cancel)
    box.setDefaultButton(new)
    box.exec()
    if box.clickedButton() is new:
        return "new"
    if move is not None and box.clickedButton() is move:
        return "move"
    return None


def snap_zero():
    """Put the active setup's zero point on the selected flat face.

    Z points out of the face, Z0 is in its plane and X0 Y0 in the middle of
    the part. Without a setup the first one is made; a setup with
    operations asks whether to move its zero or to make a new setup.
    """
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    models = _models_or_say(doc)
    if models is None:
        return
    picked = _selected_face()
    if picked is None:
        _status(tr("Select one flat face of the model first, then click Snap-0-Point."))
        return
    try:
        place = geometry.zero_on_face(models, *picked)
    except cam.ProjectError as exc:
        _error(str(exc))
        return
    job = scene.active_setup(doc)
    choice = "new" if job is None else "move"
    if job is not None and cam.operations(job):
        same_axis = geometry.same_direction(geometry.tool_axis(place), geometry.tool_axis(cam.zero(job)))
        choice = _ask_move_or_new(job, same_axis)
        if choice is None:
            return
    doc.openTransaction(tr("Snap-0-Point"))
    try:
        if choice == "new":
            job = cam.new_setup(doc, place)
        else:
            cam.set_zero(job, place)
    except cam.ProjectError as exc:
        doc.abortTransaction()
        _error(str(exc))
        return
    doc.commitTransaction()
    FreeCADGui.Selection.clearSelection()
    scene.set_active_setup(job)
    _select("setup", job.Name)


def move_zero():
    """CAM > Move 0-Point (ui.move_zero, on its own)."""
    from avangardecam.ui import move_zero as ui_move_zero

    return ui_move_zero.run()


def set_default_zero():
    """CAM > Set 0-Point as default (ui.op_zero, on its own)."""
    from avangardecam.ui import op_zero as ui_op_zero

    return ui_op_zero.set_default()


def reset_zero():
    """CAM > Reset 0-Point (ui.op_zero, on its own)."""
    from avangardecam.ui import op_zero as ui_op_zero

    return ui_op_zero.reset()


def _rotate_zero(degrees):
    """Turn the active setup's zero point about Z (the first setup is made
    if there is none yet)."""
    from avangardecam.ui import scene

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return
    job = scene.active_setup(doc)
    doc.openTransaction(tr("Rotate 0-Point"))
    try:
        if job is None:
            job = cam.ensure_job(doc)
        cam.rotate_zero(job, degrees)
    except cam.ProjectError as exc:
        doc.abortTransaction()
        _error(str(exc))
        return
    doc.commitTransaction()
    scene.set_active_setup(job)
    _select("setup", job.Name)
    _status(tr("{}: zero point turned {:g}° about Z").format(job.Label, round(cam.zero_rotation(job), 3)))


def rotate_zero_90():
    _rotate_zero(90.0)


def rotate_zero_180():
    _rotate_zero(180.0)


def rotate_zero_angle(degrees=None):
    """Turn the zero point by an angle the user types (remembered for next time)."""
    from PySide import QtWidgets

    if degrees is None:
        last = params().GetFloat("LastZeroRotation", 90.0)
        degrees, ok = QtWidgets.QInputDialog.getDouble(
            FreeCADGui.getMainWindow(),
            tr("Rotate 0-Point"),
            tr("Turn the zero point about Z by (degrees, counter-clockwise seen from the tool; negative turns clockwise):"),  # fmt: skip
            last,
            -360.0,
            360.0,
            3,
        )
        if not ok:
            return
        params().SetFloat("LastZeroRotation", degrees)
    _rotate_zero(degrees)


def measure_from_zero():
    """CAM > Measure from 0-Point (ui.measure, on its own)."""
    from avangardecam.ui import measure

    return measure.from_zero()


def measure_local():
    """CAM > Measure local (ui.measure, on its own)."""
    from avangardecam.ui import measure

    return measure.local()


def contour_tooling(sketch=None):
    """The tool follows the selected sketch lines, in the order they were
    clicked, from Start Z down to Z-Depth (Relative: from the Z of the
    lines, else from the zero point; above or below), its centre on them or beside
    them (tool compensation RL/RR). A whole sketch selected (e.g. in the
    list) means all its lines. Lines of several sketches (several Extract
    boundary edges) make one contour, sketch after sketch, relative each
    from its own plane."""
    from avangardecam.engine import geometry
    from avangardecam.model import library
    from avangardecam.ui import direction, picking, scene
    from avangardecam.ui.contour_dialog import ContourDialog

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return
    picks = picking.selections()  # lines of several sketches: sketch after sketch, in the order clicked
    if not picks or (sketch is not None and all(s is not sketch for s, _lines in picks)):
        _status(tr("Click the sketch lines the tool follows (Shift+click adds a line, Alt+click a loop), then click Contour tooling."))  # fmt: skip
        return
    jobs = None
    for one, _lines in picks:
        fits = cam.setups_for_contour(doc, one)  # facing the tool or away from it (the part's bottom)
        if not fits:
            _error(
                tr("No setup has its tool across the lines of {}.\n\nSelect the face the sketch was taken from and click Snap-0-Point first.").format(one.Label)  # fmt: skip
            )
            return
        jobs = [job for job in (jobs if jobs is not None else fits) if job in fits]
    if not jobs:
        _error(tr("The sketches face the tools of different setups: one contour is made in one setup."))
        return
    active = scene.active_setup(doc)
    job = active if active in jobs else jobs[0]
    turned = [direction.backwards(one) for one, _lines in picks]
    tool_order = [
        (one, [name for chain in geometry.line_runs(one, lines, back) for name, _r in chain] if lines else [])
        for (one, lines), back in zip(picks, turned)
    ]
    try:
        entries = library.load(tool_library_path())
    except (OSError, ValueError, KeyError, TypeError):
        entries = []  # the setup's tools still work; Choose tool says what is wrong
    from avangardecam.engine import lead_check

    runs = [(one, lines, back) for (one, lines), back in zip(picks, turned)]
    warn = lambda contour, radius: lead_check.text(lead_check.for_picks(job, runs, contour, radius), tr)  # noqa: E731
    dialog = ContourDialog(job, tool_order, (), entries, warn=warn)
    if not dialog.exec():
        return
    try:
        tc = _tool_controller(job, dialog.tool())
    except (cam.ProjectError, ValueError) as exc:
        _error(str(exc))
        return
    doc.openTransaction(tr("Contour tooling"))
    try:
        op = cam.add_contour_sketches(job, [(one, lines, back) for (one, lines), back in zip(picks, turned)], dialog.contour(), tc)  # fmt: skip
    except (cam.ProjectError, ValueError) as exc:
        doc.abortTransaction()
        _error(str(exc))
        return
    doc.commitTransaction()
    scene.set_active_setup(job)
    _select("operation", op.Name)


class _Holes(NamedTuple):
    """Holes picked for an operation on holes: circles of a sketch (names,
    [] for all of them) or holes of a model (the names of an element of
    each), in the order they were clicked."""

    job: object
    source: object  # the sketch or the model
    names: list
    text: str  # the holes as the windows show them
    holes: list  # (diameter, HoleDepth of a model's hole or None) of each
    ignored: int  # other lines selected (left out)

    @property
    def model(self):
        return not geometry.is_sketch(self.source)


# what the messages of picking holes say for each operation
_DRILL_WORDS = {
    "done": QT_TRANSLATE_NOOP("AvangardeCam", "drilled"),
    "to": QT_TRANSLATE_NOOP("AvangardeCam", "to drill"),
    "button": QT_TRANSLATE_NOOP("AvangardeCam", "Drilling"),
}
_THREAD_WORDS = {
    "done": QT_TRANSLATE_NOOP("AvangardeCam", "threaded"),
    "to": QT_TRANSLATE_NOOP("AvangardeCam", "to mill a thread in"),
    "button": QT_TRANSLATE_NOOP("AvangardeCam", "Thread milling"),
}


def _picked_holes(sketch, words):
    """The selected circles of a sketch or holes clicked in the model, for
    an operation on holes (_Holes), else None after saying what to do. A
    whole sketch selected (e.g. in the list) means all its circles; other
    selected lines are left out."""
    from avangardecam.ui import picking, scene
    from avangardecam.ui.drilling_dialog import holes_text, picked_text

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return None
    try:
        picked = picking.selected_lines()
        holes = _selected_holes() if sketch is None else None
    except ValueError as exc:
        _status(tr(str(exc)))
        return None
    if holes is not None:
        if picked is not None:
            _status(tr("Select the circles of a sketch or the holes of the model, not both."))
            return None
        model, names = holes
        found = _model_setup(doc, model, names)
        if found is None:
            return None
        job, model_holes = found
        diameters = [(h.radius * 2.0, h.depth) for h in model_holes]
        return _Holes(job, model, names, picked_text(diameters), diameters, 0)
    if picked is None or (sketch is not None and picked[0] is not sketch):
        _status(
            tr("Click the holes in the model or the circles of a sketch in the order they are {} (Shift+click adds one), then click {}.").format(tr(words["done"]), tr(words["button"]))  # fmt: skip
        )
        return None
    sketch, lines = picked
    # a line of a hole of arcs picks the hole, each hole once in click order
    parts = [hole for hole in (geometry.hole_name(sketch, name) for name in lines) if hole is not None]
    circles = list(dict.fromkeys(parts))
    if lines and not circles:
        _status(
            tr("None of the selected lines is a circle. Click the circles {}, then click {}.").format(tr(words["to"]), tr(words["button"]))  # fmt: skip
        )
        return None
    if not lines and not geometry.sketch_circles(sketch):
        _status(tr("{} has no circles {}.").format(sketch.Label, tr(words["to"])))
        return None
    jobs = cam.setups_for_sketch(doc, sketch)
    if not jobs:
        _error(
            tr("No setup has its tool facing {}.\n\nSelect the face the sketch was taken from and click Snap-0-Point first.").format(sketch.Label)  # fmt: skip
        )
        return None
    active = scene.active_setup(doc)
    job = active if active in jobs else jobs[0]
    names = list(circles) or geometry.sketch_circles(sketch)
    diameters = [(sketch.Shape.getElement(n).Curve.Radius * 2.0, None) for n in names]
    return _Holes(job, sketch, circles, holes_text(sketch, circles), diameters, len(lines) - len(parts))


def drilling(sketch=None):
    """Drill the selected circles of a sketch, or the holes clicked in the
    model, with cycle 205, in the order they were clicked (_picked_holes)."""
    from avangardecam.ui.drilling_dialog import DrillingDialog

    picked = _picked_holes(sketch, _DRILL_WORDS)
    if picked is None:
        return
    job, source, names = picked.job, picked.source, picked.names
    dialog = DrillingDialog(job, source, picked.text, picked.holes, _library(), picked.ignored)
    if picked.model:
        make = lambda tc: cam.add_model_drilling(job, source, dialog.drilling(), tc, names)  # noqa: E731
    else:
        make = lambda tc: cam.add_drilling(job, source, dialog.drilling(), tc, names)  # noqa: E731
    if _add_operation(source.Document, job, dialog, make, tr("Drilling")) and picked.model:
        # FreeCAD leaves the whole model selected (all red); its holes are the operation's now
        FreeCADGui.Selection.clearSelection()


def thread_milling(sketch=None):
    """Mill threads in the selected circles of a sketch, or the holes
    clicked in the model, in the order they were clicked (_picked_holes)."""
    from avangardecam.ui.thread_dialog import ThreadMillingDialog

    picked = _picked_holes(sketch, _THREAD_WORDS)
    if picked is None:
        return
    job, source, names = picked.job, picked.source, picked.names
    dialog = ThreadMillingDialog(job, source, picked.text, picked.holes, _library(), picked.ignored)
    if picked.model:
        make = lambda tc: cam.add_model_thread_milling(job, source, dialog.thread(), tc, names)  # noqa: E731
    else:
        make = lambda tc: cam.add_thread_milling(job, source, dialog.thread(), tc, names)  # noqa: E731
    if _add_operation(source.Document, job, dialog, make, tr("Thread milling")) and picked.model:
        FreeCADGui.Selection.clearSelection()


def helix_milling(sketch=None):
    """Mill the holes clicked in the model, or the selected circles of a
    sketch, down a helix (ui.helix)."""
    from avangardecam.ui import helix as ui_helix

    ui_helix.make(sketch)


def adaptive():
    """Adaptive clearing in the active setup: around the whole model, or
    only over the flat floors clicked in the model (Shift+click adds one)."""
    from avangardecam.ui.adaptive_dialog import AdaptiveDialog

    doc = FreeCAD.ActiveDocument
    if _models_or_say(doc) is None:
        return
    elements = _model_elements()  # a face of a job's clone is the same face of the original
    faces = [name for _model, name in elements if name.startswith("Face")]
    if len({model.Name for model, _name in elements}) > 1:
        _status(tr("Click the floors of one model only."))
        return
    if elements and not faces:
        _status(tr("Click flat floors of the model (Shift+click adds one), or nothing to clear around the whole model, then click Adaptive."))  # fmt: skip
        return
    model = elements[0][0] if faces else None
    job = _floors_setup(doc, model, faces)
    if job is None:
        return
    dialog = AdaptiveDialog(job, model, faces, _library())
    make = lambda tc: cam.add_adaptive(job, dialog.adaptive(), tc, model, faces)  # noqa: E731
    if _add_operation(doc, job, dialog, make, tr("Adaptive")) and faces:
        # FreeCAD leaves the whole model selected (all red)
        FreeCADGui.Selection.clearSelection()


def facing():
    """Facing of the flat faces clicked in the model (ui.facing)."""
    from avangardecam.ui import facing as ui_facing

    ui_facing.make()


def deburring(sketch=None):
    """Deburring of the selected sketch lines with a chamfer mill (ui.deburring)."""
    from avangardecam.ui import deburring as ui_deburring

    ui_deburring.make(sketch)


def slot_milling():
    """Slot milling of the slots clicked in the model (ui.slot)."""
    from avangardecam.ui import slot as ui_slot

    ui_slot.make()


def _floors_setup(doc, model, faces):
    """The setup of an adaptive clearing: the active one (the first, made
    now, when there is none) when the picked floors face its tool, else the
    first setup whose tool they face; else None after saying why."""
    from avangardecam.ui import scene

    if not cam.setups(doc):
        doc.openTransaction(tr("Create setup"))
        try:
            cam.ensure_job(doc)
        finally:
            doc.commitTransaction()
    active = scene.active_setup(doc)
    jobs = cam.setups(doc)
    if active in jobs:
        jobs.remove(active)
        jobs.insert(0, active)
    refused = None
    for job in jobs:
        try:
            cam.picked_floors(job, model, faces)
            return job
        except cam.ProjectError as exc:
            refused = refused or exc
    _error(str(refused))
    return None


def _selected_holes():
    """(model, ["Face12", "Edge7", ...]) of the faces and edges clicked in a
    project model, in the order they were clicked, else None. ValueError
    when they are of more than one model."""
    elements = _model_elements()  # a face of a job's clone is the same face of the original
    if len({model.Name for model, _name in elements}) > 1:
        raise ValueError("Click the holes of one model only.")
    return (elements[0][0], [name for _model, name in elements]) if elements else None


def _model_setup(doc, model, names):
    """(setup, its holes) for holes clicked in the model: the active setup
    when its tool can reach them, else the first setup that can; else None
    after saying why."""
    from avangardecam.ui import scene

    active = scene.active_setup(doc)
    jobs = cam.setups(doc)
    if active in jobs:
        jobs.remove(active)
        jobs.insert(0, active)
    found, refused = None, None
    for job in jobs:
        try:
            found = job, cam.model_holes(job, model, names)
            break
        except cam.ProjectError as exc:
            refused = refused or exc
    if found is None:
        _error(str(refused) if refused else tr("Import a model first (File > Import model)."))
    return found


def _library():
    from avangardecam.model import library

    try:
        return library.load(tool_library_path())
    except (OSError, ValueError, KeyError, TypeError):
        return []  # the setup's tools still work; Choose tool says what is wrong


def _add_operation(doc, job, dialog, make, step):
    """Run the window of an operation on holes; on OK make(tool controller)
    the operation as one undo step. True when it was made."""
    from avangardecam.ui import scene

    if not dialog.exec():
        return
    try:
        tc = _tool_controller(job, dialog.tool())
    except (cam.ProjectError, ValueError) as exc:
        _error(str(exc))
        return
    doc.openTransaction(step)
    try:
        op = make(tc)
    except (cam.ProjectError, ValueError) as exc:
        doc.abortTransaction()
        _error(str(exc))
        return
    doc.commitTransaction()
    scene.set_active_setup(job)
    _select("operation", op.Name)
    return True


def _tool_controller(job, choice):
    """The setup's tool controller of a tool chosen for an operation (a
    ProjectTool, or a library variant added or replacing its T number).

    Call it outside a transaction: FreeCAD cannot undo the making of a tool
    (in the GUI the undo stops at its tool bit and leaves the rest of the
    step done), so tools come and go only in the tool list, not by undo."""
    if isinstance(choice, cam.ProjectTool):
        return choice.controller
    before = _selected_elements()
    try:
        return cam.library_tool(job, choice, replace=True)
    finally:
        # FreeCAD makes a tool bit's shape in a hidden document and copies it
        # in; after that a sketch whose lines were selected is selected whole
        # (a sketch from a saved file): the operation's lines are selected again
        if _selected_elements() != before:
            from avangardecam.ui import picking

            picking._select(job.Document.Name, before)


def _selected_elements():
    """(object, element) of what is selected in 3D in click order, element
    "" for a whole object, as FreeCADGui.Selection.addSelection takes them."""
    found = []
    for selection in FreeCADGui.Selection.getSelectionEx("", 0):
        for sub in selection.SubElementNames or [""]:
            # ";g5;SKT;:H,E.Edge5": FreeCAD's mapped name before the element's own
            found.append((selection.ObjectName, ".".join(p for p in sub.split(".") if not p.startswith(";"))))
    return found


def change_tool(op):
    """Another tool for an operation of AvangardeCam (a contour, a drilling,
    a thread, slot or helix milling, ...), from the tool library (its setup's tools are there too)."""
    from avangardecam.engine import facing as engine_facing
    from avangardecam.engine import helix as engine_helix
    from avangardecam.engine import slot as engine_slot
    from avangardecam.ui import adaptive_dialog, contour_dialog, drilling_dialog, thread_dialog
    from avangardecam.ui import facing as ui_facing
    from avangardecam.ui import helix as ui_helix
    from avangardecam.ui import slot as ui_slot
    from avangardecam.ui.tool_library import ToolLibraryDialog

    from avangardecam.engine import deburring as engine_deburring
    from avangardecam.ui import deburring as ui_deburring

    from avangardecam.ui import op_zero as ui_op_zero

    if not ui_op_zero.ready(op):
        return
    job = cam.setup_of(op)
    only = None  # the operation's kind of tools only (switchable)
    if engine_deburring.deburring_of(op) is not None:
        last = ui_deburring.LAST_TOOL
        only = ui_deburring.CHAMFER_MILLS_ONLY
    elif cam.contour_of(op) is not None:
        last = contour_dialog.LAST_TOOL
    elif cam.drilling_of(op) is not None:
        last = drilling_dialog.LAST_TOOL
        only = drilling_dialog.DRILLS_ONLY
    elif cam.thread_milling_of(op) is not None:
        last = thread_dialog.LAST_TOOL
        only = thread_dialog.THREAD_MILLS_ONLY
    elif cam.adaptive_of(op) is not None:
        last = adaptive_dialog.LAST_TOOL
    elif engine_facing.facing_of(op) is not None:
        last = ui_facing.LAST_TOOL
    elif engine_slot.slot_milling_of(op) is not None:
        last = ui_slot.LAST_TOOL
    elif engine_helix.helix_milling_of(op) is not None:
        last = ui_helix.LAST_TOOL
    else:
        return
    if job is None:
        return
    picker = ToolLibraryDialog(op.Document, pick=True, job=job, only=only)
    if not picker.exec() or picker.picked is None:
        return
    doc = op.Document
    try:
        tc = _tool_controller(job, picker.picked)
    except (cam.ProjectError, ValueError) as exc:
        _error(str(exc))
        return
    doc.openTransaction(tr("Change tool"))
    try:
        cam.set_tool(op, tc)
    except (cam.ProjectError, ValueError) as exc:
        doc.abortTransaction()
        _error(str(exc))
        return
    doc.commitTransaction()
    params().SetString(last, picker.picked.id)
    _select("operation", op.Name)


def edit_operation(op):
    """The window an operation was made in, with its values and tool; OK
    changes them as one undo step. Its lines or holes stay."""
    from avangardecam.engine import facing as engine_facing
    from avangardecam.engine import geometry
    from avangardecam.engine import helix as engine_helix
    from avangardecam.engine import slot as engine_slot
    from avangardecam.ui import facing as ui_facing
    from avangardecam.ui import helix as ui_helix
    from avangardecam.ui import slot as ui_slot
    from avangardecam.ui.adaptive_dialog import AdaptiveDialog
    from avangardecam.ui.contour_dialog import ContourDialog
    from avangardecam.ui.drilling_dialog import DrillingDialog, holes_text, picked_text
    from avangardecam.ui.thread_dialog import ThreadMillingDialog

    from avangardecam.ui import op_zero as ui_op_zero

    if not ui_op_zero.ready(op):
        return
    job = cam.setup_of(op)
    from avangardecam.engine import deburring as engine_deburring
    from avangardecam.ui import deburring as ui_deburring

    tool = next((t for t in cam.project_tools(job) if t.controller is op.ToolController), None) if job else None
    if engine_deburring.deburring_of(op) is not None:
        dialog, values = ui_deburring.edit_dialog(op, job, tool, _library())
    elif cam.contour_of(op) is not None:
        from avangardecam.engine import lead_check

        sketch, contour = cam.contour_of(op)
        picks = lead_check.op_picks(op)
        warn = lambda values, radius: lead_check.text(lead_check.for_picks(job, picks, values, radius), tr)  # noqa: E731
        dialog = ContourDialog(job, cam.contour_sketches(op) or [(sketch, [])], (), _library(), start=contour, tool=tool, warn=warn)  # fmt: skip
        values = dialog.contour
    elif cam.drilling_of(op) is not None:
        source, drilling = cam.drilling_of(op)
        holes = [(t.diameter, t.hole) for t in cam.drill_targets(op)]
        text = holes_text(source, cam.drilling_circles(op)) if geometry.is_sketch(source) else picked_text(holes)
        dialog = DrillingDialog(job, source, text, holes, _library(), start=drilling, tool=tool)
        values = dialog.drilling
    elif cam.thread_milling_of(op) is not None:
        source, thread = cam.thread_milling_of(op)
        holes = [(t.diameter, t.hole) for t in cam.drill_targets(op)]
        text = holes_text(source, cam.drilling_circles(op)) if geometry.is_sketch(source) else picked_text(holes)
        dialog = ThreadMillingDialog(job, source, text, holes, _library(), start=thread, tool=tool)
        values = dialog.thread
    elif cam.adaptive_of(op) is not None:
        model, adaptive = cam.adaptive_of(op)
        dialog = AdaptiveDialog(job, model, cam.adaptive_floors(op), _library(), start=adaptive, tool=tool)
        values = dialog.adaptive
    elif engine_facing.facing_of(op) is not None:
        dialog, values = ui_facing.edit_dialog(op, job, tool, _library())
    elif engine_slot.slot_milling_of(op) is not None:
        dialog, values = ui_slot.edit_dialog(op, job, tool, _library())
    elif engine_helix.helix_milling_of(op) is not None:
        dialog, values = ui_helix.edit_dialog(op, job, tool, _library())
    else:
        _status(tr("{} was made in FreeCAD; change it in expert mode.").format(op.Label))
        return
    dialog.setWindowTitle(tr("Edit {}").format(op.Label))
    if not dialog.exec():
        return
    doc = op.Document
    try:
        tc = _tool_controller(job, dialog.tool())
    except (cam.ProjectError, ValueError) as exc:
        _error(str(exc))
        return
    doc.openTransaction(tr("Edit operation"))
    try:
        cam.change_operation(op, values(), tc)
    except (cam.ProjectError, ValueError) as exc:
        doc.abortTransaction()
        _error(str(exc))
        return
    doc.commitTransaction()
    _select("operation", op.Name)


def switch_operation(op, on):
    """Switch an operation on or off (one undo step): off, it stays in the
    list but is left out of the program and the simulation."""
    doc = op.Document
    doc.openTransaction(tr("Switch operation on") if on else tr("Switch operation off"))
    cam.set_active(op, on)
    doc.commitTransaction()
    _select("operation", op.Name)


def move_operation(op, index):
    """Move an operation of its setup before the one at index (len: to the
    end), one undo step; the program runs them in this order."""
    from avangardecam.engine import operation_order

    job = cam.setup_of(op)
    doc = op.Document
    doc.openTransaction(tr("Move operation"))
    operation_order.move(job, op, index)
    doc.commitTransaction()
    _select("operation", op.Name)


def tool_library():
    from avangardecam.ui import project_panel, scene
    from avangardecam.ui.tool_library import ToolLibraryDialog

    doc = FreeCAD.ActiveDocument or FreeCAD.newDocument()
    ToolLibraryDialog(doc).exec()
    job = scene.active_setup(doc)
    if job is not None:
        _select(project_panel.GROUP, project_panel.group_key("tools", job))


def expert_mode():
    FreeCADGui.activateWorkbench("CAMWorkbench")


def exit_program():
    FreeCADGui.getMainWindow().close()
