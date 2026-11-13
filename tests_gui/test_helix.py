# Helix milling GUI test: the two Ø4.5 holes through the test model
# (12 deep), picked in the model right one first. CAM > Helix with nothing
# selected only says what to click. The window: the holes, the depth from
# the model (1 mm out under them), no tool (OK refused), a drill refused,
# T2 (Ø3 end mill) from the library: the pitch Ø3 x tan 5° (0.2625), the
# step over in mm, the passes as typed (two helices, one without Finish
# XY). The helix milling keeps the click order, its program has RL from
# the first pass, the view draws the walls; the details change the XY
# offset live (undo); the simulator opens; Edit... switches to a helix
# then circles on Z steps; Helix milling... of the top's sketch starts
# with the tool used last and a depth to type; save and reopen.
#
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_helix.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "helix_milling.FCStd")


def log(*args):
    LOG.write(" ".join(str(a) for a in args) + "\n")
    LOG.flush()


def check(condition, text):
    log(("ok    " if condition else "FAIL  ") + text)
    if not condition:
        FAILURES.append(text)


def later(ms, fn):
    QtCore.QTimer.singleShot(ms, fn)


def safe(fn):
    def wrapper():
        try:
            fn()
        except Exception:
            log("EXCEPTION in", fn.__name__)
            log(traceback.format_exc())
            FAILURES.append("exception in " + fn.__name__)
            finish()

    return wrapper


def mw():
    return FreeCADGui.getMainWindow()


def shot(name, whole_screen=False):
    path = os.path.join(OUT, name + ".png")
    if whole_screen:  # with the windows over the main window
        QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)
    else:
        mw().grab().save(path)
    log("screenshot", path)


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def engine():
    from avangardecam.engine import helix

    return helix


def geometry():
    from avangardecam.engine import geometry as g

    return g


def handlers():
    from avangardecam import handlers as h

    return h


def helix():
    from avangardecam.model import helix as m

    return m


def doc():
    return FreeCAD.ActiveDocument


def body():
    return cam().models(doc())[0]


def rows():
    return dict(panel().view.rows())


def modal(fn, ms=600):
    """Run fn(widget) on the modal window a handler is about to open."""

    def run():
        widget = QtWidgets.QApplication.activeModalWidget()
        if widget is None:
            later(200, run)
            return
        try:
            fn(widget)
        except Exception:
            log("EXCEPTION in modal handler")
            log(traceback.format_exc())
            FAILURES.append("exception in modal handler")
            widget.reject()

    later(ms, run)


def variant(number, name):
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == number and e.tool.name == name)


def mill():
    return variant(2, "VHM ALU Frees 3mm")


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


def raw(widget):
    return float(widget.property("rawValue"))


def nc_blocks():
    from avangardecam.post import heidenhain

    text = heidenhain.write(cam().nc_program(doc(), "TEST"))
    return [line.split(" ", 1)[1] for line in text.split("\r\n") if line and not line.startswith(" ")]


def walls():
    """(right, left): the wall of each Ø4.5 hole of the model."""
    import Part

    shape = body().Shape
    found = {}
    for i, f in enumerate(shape.Faces, start=1):
        if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 2.25) < 1e-6:
            found.setdefault(f.Surface.Center.x > 0, "Face{}".format(i))
    return found[True], found[False]


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    FreeCADGui.Selection.clearSelection()
    handlers().helix_milling()
    message = mw().statusBar().currentMessage()
    check(message.startswith("Click the holes in the model or the circles of a sketch in the order they are milled") and message.endswith("then click Helix."), "nothing selected: " + message)  # fmt: skip
    right, left = walls()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, right)
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, left)
    modal(dialog1)
    handlers().helix_milling()
    later(500, step3)


def dialog1(dialog):
    check(dialog.objectName() == "AvangardeCamHelixDialog", "the helix milling window opens")
    holes = field(dialog, "AvangardeCamHelixHoles").text()
    check(holes == "2: Ø4.5 through → Ø4.5 through", "the holes in the click order: {}".format(holes))
    depth, from_model = field(dialog, "AvangardeCamHelixDepth"), field(dialog, "AvangardeCamHelixFromModel")
    check(from_model.isChecked() and from_model.isEnabled() and not depth.isEnabled(), "the depth from the model")
    check(abs(raw(depth) + 12.0) < 1e-9, "shown: the hole, 12 deep ({})".format(raw(depth)))
    check(abs(raw(field(dialog, "AvangardeCamHelixThrough")) - 1.0) < 1e-9, "1 mm out under through holes")
    tool = field(dialog, "AvangardeCamHelixTool")
    check(tool.currentIndex() == -1, "a new setup, nothing used last: no tool chosen")
    dialog.accept()
    message = field(dialog, "AvangardeCamHelixMessage").text()
    check(dialog.isVisible() and message.startswith("Choose a tool"), "OK without a tool refused: {}".format(message))
    from avangardecam import tool_library_path
    from avangardecam.model import library

    drill = next(e for e in library.load(tool_library_path()) if e.number == 40 and e.workpiece_material == "Aluminium")
    dialog.use(drill)
    fit = field(dialog, "AvangardeCamHelixFit")
    check(fit.isVisible() and "not an end mill" in fit.text(), "a drill: {}".format(fit.text()))
    dialog.accept()
    check(dialog.isVisible(), "a drill refused")
    dialog.use(mill())
    check(not fit.isVisible(), "T2 fits: {}".format(fit.text()))
    pitch, auto = field(dialog, "AvangardeCamHelixPitch"), field(dialog, "AvangardeCamHelixAutoPitch")
    check(auto.isChecked() and not pitch.isEnabled() and abs(pitch.value() - 0.2625) < 1e-9, "Auto pitch: Ø3 x tan 5° = {}".format(pitch.text()))  # fmt: skip
    step_over = field(dialog, "AvangardeCamHelixStepOverMm").text()
    check(step_over == "= 1.5 mm", "the step over in mm: " + step_over)
    feeds = field(dialog, "AvangardeCamHelixFeeds").text()
    check(feeds == "Z 225 (down to the top), XY 300 mm/min", "the feeds: " + feeds)
    passes = field(dialog, "AvangardeCamHelixPasses")
    check(passes.text() == "2 helices: Ø4.3, Ø4.5 (finishing); 50 turns of P0.2625 each", "the passes: " + passes.text())
    finish_xy = field(dialog, "AvangardeCamHelixFinishXY")
    finish_xy.setValue(0.0)
    check(passes.text() == "1 helix Ø4.5, 50 turns of P0.2625", "without Finish XY one helix: " + passes.text())
    finish_xy.setValue(0.1)
    check(not field(dialog, "AvangardeCamHelixZStep").isEnabled(), "Z step only for circles")
    shot("01_helix_dialog", whole_screen=True)
    dialog.accept()


@safe
def step3():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "one helix milling made")
    OP = ops[0]
    found = engine().helix_milling_of(OP)
    check(found == (body(), helix().HelixMilling()), "from the model, the values shown: {}".format(found))
    check([(round(h.x, 3), round(h.y, 3), h.bottom) for h in engine().holes(OP)] == [(15.0, 0.0, -13.0), (-15.0, 0.0, -13.0)], "in the click order, 1 mm under the holes")  # fmt: skip
    check(abs(cam().path_summary(OP)[1] + 13.0) < 1e-6, "the path down to Z-13")
    r = rows()
    check(r.get("Holes") == "2: Ø4.5 through → Ø4.5 through", "details: holes {}".format(r.get("Holes")))
    check(r.get("Tool", "").startswith("T2 "), "details: tool {}".format(r.get("Tool")))
    check(r.get("Passes") == "2 helices: Ø4.3, Ø4.5 (finishing); 50 turns of P0.2625 each", "details: passes {}".format(r.get("Passes")))  # fmt: skip
    check(r.get("Path") == "2 holes, down to Z -13.00 mm", "details: path {}".format(r.get("Path")))
    blocks = nc_blocks()
    check("*- Helix Milling" in blocks and "TOOL CALL 2 Z S12000 DL0 DR0;VHM ALU Frees 3mm" in blocks, "program: the title and tool")  # fmt: skip
    rl = [b for b in blocks if " RL " in b]
    check(rl == ["L X+13.4 RL FQ31"] * 2 + ["L X-16.6 RL FQ31"] * 2, "program: RL from the first pass, right hole first: {}".format(rl))  # fmt: skip
    check(blocks.count("CP IPA+180. IZ-0.13 DR+") == 2 * 2 * 100, "program: 100 half turns of 0.13 a helix")
    drawing = cam().path_drawing(OP)
    check(drawing is not None and len(drawing) > 2, "the view draws the program")
    field(panel().view, "AvangardeCamHelixOffsetXY").setValue(0.025)
    shot("02_helix_details")
    later(1500, step4)


@safe
def step4():
    check(engine().helix_milling_of(OP)[1].offset_xy_mm == 0.025, "details: the XY offset to 3 decimals, applied after the pause")  # fmt: skip
    check(rows().get("Passes") == "2 helices: Ø4.35, Ø4.55 (finishing); 50 turns of P0.2625 each", "details follow: {}".format(rows().get("Passes")))  # fmt: skip
    check("C X+17.275 Y+0. DR+" in nc_blocks(), "the program follows: the wall 2.275 from the axis")
    doc().undo()
    later(800, step5)


@safe
def step5():
    check(engine().helix_milling_of(OP)[1].offset_xy_mm == 0.0, "undo: no offset again")
    check(abs(field(panel().view, "AvangardeCamHelixOffsetXY").value()) < 1e-9, "the details follow the undo")
    handlers().simulate()
    later(2500, step6)


@safe
def step6():
    from avangardecam.ui import simulation

    window = simulation.simulator_window()
    check(window is not None, "the simulator opens for the helix milling")
    shot("03_simulation")
    if window is not None:
        window.close()

    def edit(dialog):
        check(dialog.windowTitle() == "Edit " + OP.Label, "Edit opens the window: {}".format(dialog.windowTitle()))
        check(field(dialog, "AvangardeCamHelixTool").currentText().startswith("T2 "), "with its tool")
        method = field(dialog, "AvangardeCamHelixMethod")
        method.setCurrentIndex(method.findData(helix().HELIX_CONTOUR))
        z_step = field(dialog, "AvangardeCamHelixZStep")
        check(z_step.isEnabled(), "circles: Z step on")
        fit = field(dialog, "AvangardeCamHelixFit")
        check(fit.isVisible() and "enter a Z step" in fit.text(), "13 deep at once is more than T2 cuts: {}".format(fit.text()))  # fmt: skip
        z_step.setProperty("rawValue", 4.0)
        passes = field(dialog, "AvangardeCamHelixPasses").text()
        check(passes == "Helix Ø4.3, 50 turns of P0.2625; then circles Ø4.5 (finishing) on 4 levels", "the passes: " + passes)  # fmt: skip
        dialog.accept()

    modal(edit)
    handlers().edit_operation(OP)  # until the window closes
    check(engine().helix_milling_of(OP)[1] == helix().HelixMilling(method=helix().HELIX_CONTOUR, z_step_mm=4.0), "edited: a helix, then circles")  # fmt: skip
    rl = [b for b in nc_blocks() if " RL " in b]
    check(len(rl) == 2 * (1 + 4), "a helix and 4 circles in each hole: {}".format(len(rl)))
    from avangardecam.ui import activate_geometry

    picked = activate_geometry.geometry_of(OP)
    check(picked is not None and picked.text() == "2 holes", "Activate geometry: {}".format(picked.text() if picked else None))
    # the sketch of the top
    shape = body().Shape
    top = max(
        (f.BoundBox.ZMax, f.Area, "Face{}".format(i))
        for i, f in enumerate(shape.Faces, start=1)
        if f.findPlane() is not None and geometry().outward_normal(shape, f).getAngle(FreeCAD.Vector(0, 0, 1)) < 1e-6
    )[2]
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, top)
    handlers().extract_boundary()
    later(800, step7)


@safe
def step7():
    global SKETCH
    SKETCH = FreeCADGui.Selection.getSelection()[0]  # Extract boundary edges selects its sketch (a tool's shape has one too)
    check(SKETCH.TypeId == "Sketcher::SketchObject", "the top's sketch: {}".format(SKETCH.Label))
    handlers()._select("sketch", SKETCH.Name)
    QtWidgets.QApplication.processEvents()
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, SKETCH.Name)  # the whole sketch: all its circles
    QtWidgets.QApplication.processEvents()
    button = field(panel().view, "AvangardeCamHelixMilling")
    check(button is not None and button.text() == "Helix milling...", "the sketch's details: Helix milling...")
    modal(dialog2)
    button.click()
    later(500, step8)


def dialog2(dialog):
    holes = field(dialog, "AvangardeCamHelixHoles").text()
    check(holes == "all 2: Ø4.5", "the whole sketch: its circles ({})".format(holes))
    from_model = field(dialog, "AvangardeCamHelixFromModel")
    check(not from_model.isChecked() and not from_model.isEnabled(), "a sketch: no depth from the model")
    depth = field(dialog, "AvangardeCamHelixDepth")
    check(depth.isEnabled() and abs(raw(depth) + 10.0) < 1e-9, "a depth to type, -10 at first ({})".format(raw(depth)))
    tool = field(dialog, "AvangardeCamHelixTool").currentText()
    check(tool.startswith("T2 ") and "new in" not in tool, "the tool used last: {}".format(tool))
    method = field(dialog, "AvangardeCamHelixMethod").currentData()
    check(method == helix().HELIX, "the values used last for new ones, not the edited ones: {}".format(method))
    depth.setProperty("rawValue", -5.0)
    dialog.accept()


@safe
def step8():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 2 and ops[1].Label == "Helix milling 2", "a second helix milling: {}".format([o.Label for o in ops]))
    found = engine().helix_milling_of(ops[1])
    check(found is not None and found[0] is SKETCH and found[1].depth_mm == -5.0, "of the sketch, 5 deep")
    check(abs(cam().path_summary(ops[1])[1] + 5.0) < 1e-6, "its path down to Z-5")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step9)


@safe
def step9():
    ops = cam().operations(cam().find_job(doc()))
    values = [engine().helix_milling_of(o)[1] for o in ops]
    check(values[0] == helix().HelixMilling(method=helix().HELIX_CONTOUR, z_step_mm=4.0) and values[1].depth_mm == -5.0, "reopened: both helix millings")  # fmt: skip
    before = ops[0].Path.toGCode()
    ops[0].touch()
    doc().recompute()
    check(ops[0].Path.toGCode() == before, "reopened: the same path")
    handlers()._select("operation", ops[0].Name)
    QtWidgets.QApplication.processEvents()
    check(rows().get("Passes") == "Helix Ø4.3, 50 turns of P0.2625; then circles Ø4.5 (finishing) on 4 levels", "reopened: the details {}".format(rows().get("Passes")))  # fmt: skip
    shot("04_reopened")
    finish()


def finish():
    log("FAILURES:", len(FAILURES))
    for text in FAILURES:
        log("  ", text)
    log("done")
    LOG.close()
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)
    QtCore.QTimer.singleShot(200, mw().close)


# start as on a new profile: no values remembered from earlier work
avangardecam.forget_last_values()
later(4000, step1)
