# Adaptive clearing GUI test on the test model (a block 40 x 20 x 12 with
# two Ø4.5 holes through it; zero on its top). CAM > Adaptive with nothing
# selected: around the whole model. The window: the area, Z-Depth from the
# model's lowest floor (its top, Z0), no tool (OK refused), a drill refused,
# T2 too short for 12 mm at once, T5 (Ø6): the step over in mm, the Z levels
# as they are typed (the Z steps and the floor), Start Z: the top of the
# stock ticked, typed on the top (only the stock over it) and under it (the
# top left as it is), ticked again. The clearing: its values,
# its path down to Z-Depth, the details (live, undo), the program, the
# simulator, Edit...; a floor picked in the model: the area of that floor,
# the tool and Z step used last; save and reopen.
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
LOG = open(os.path.join(OUT, "test_adaptive.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "adaptive.FCStd")


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


def geometry():
    from avangardecam.engine import geometry as g

    return g


def handlers():
    from avangardecam import handlers as h

    return h


def operations():
    from avangardecam.model import operations as o

    return o


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


def variant(number, material):
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == number and e.workpiece_material == material)


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


def nc_blocks():
    from avangardecam.post import heidenhain

    text = heidenhain.write(cam().nc_program(doc(), "TEST"))
    return [line.split(" ", 1)[1] for line in text.split("\r\n") if line and not line.startswith(" ")]


def raw(widget):
    return float(widget.property("rawValue"))


def lowest(op):
    return round(cam().path_summary(op)[1], 6)


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    FreeCADGui.Selection.clearSelection()
    modal(dialog1)
    handlers().adaptive()
    later(500, step3)


def dialog1(dialog):
    check(dialog.objectName() == "AvangardeCamAdaptiveDialog", "the Adaptive window opens")
    area = field(dialog, "AvangardeCamAdaptiveArea").text()
    check(area == "Around the whole model (Body)", "nothing picked: the whole model: " + area)
    depth = field(dialog, "AvangardeCamAdaptiveDepth")
    check(raw(depth) == 0.0, "Z-Depth from the model's lowest floor, its top: {}".format(raw(depth)))
    levels = field(dialog, "AvangardeCamAdaptiveLevels")
    check(levels.text() == "Z +0.00 (1 level)", "the levels: " + levels.text())
    tool = field(dialog, "AvangardeCamAdaptiveTool")
    check(tool.currentIndex() == -1, "no tool in the setup yet: none chosen")
    dialog.accept()
    message = field(dialog, "AvangardeCamAdaptiveMessage").text()
    check(dialog.isVisible() and message.startswith("Choose a tool"), "OK without a tool refused: " + message)
    fit = field(dialog, "AvangardeCamAdaptiveFit")
    dialog.use(variant(40, "Aluminium"))
    check(fit.isVisible() and "not an end mill" in fit.text(), "a drill: " + fit.text())
    dialog.accept()
    check(dialog.isVisible(), "a drill refused")
    depth.setProperty("rawValue", -12.0)
    check(levels.text() == "Z +0.00, -12.00 (2 levels)", "Z-Depth -12, no steps: " + levels.text())
    dialog.use(variant(2, "Aluminium"))  # Ø3, cuts 4 mm
    check(fit.isVisible() and "cutting length" in fit.text(), "12 mm at once with T2: " + fit.text())
    dialog.use(variant(5, "Aluminium"))
    check(not fit.isVisible(), "T5 cuts 30 mm: " + fit.text())
    check(field(dialog, "AvangardeCamAdaptiveStepOverMm").text() == "= 1.2 mm", "20 % of Ø6")
    feeds = field(dialog, "AvangardeCamAdaptiveFeeds").text()
    check(feeds == "Z 937, XY 1250 mm/min", "the feeds: " + feeds)
    field(dialog, "AvangardeCamAdaptiveZStep").setProperty("rawValue", 4.0)
    check(levels.text() == "Z +0.00, -3.00, -7.00, -11.00, -12.00 (5 levels)", "Z steps from the top of the stock: " + levels.text())  # fmt: skip
    start = field(dialog, "AvangardeCamAdaptiveStartZ")
    from_stock = field(dialog, "AvangardeCamAdaptiveFromStock")
    check(from_stock.isChecked() and not start.isEnabled() and raw(start) == 1.0, "Start Z: the top of the stock, Z+1")
    from_stock.setChecked(False)
    check(start.isEnabled(), "Start Z typed when not ticked")
    start.setProperty("rawValue", 0.0)
    depth.setProperty("rawValue", 0.0)
    check(levels.text() == "Z +0.00 (1 level)", "Start Z = Z-Depth on the top: the stock over it: " + levels.text())
    start.setProperty("rawValue", -0.1)
    depth.setProperty("rawValue", -12.0)
    check(levels.text() == "Z -4.10, -8.10, -12.00 (3 levels)", "Start Z under the top: the top left: " + levels.text())  # fmt: skip
    from_stock.setChecked(True)
    check(raw(start) == 1.0 and levels.text().endswith("(5 levels)"), "ticked again: the top of the stock: " + levels.text())  # fmt: skip
    field(dialog, "AvangardeCamAdaptiveAdvanced").setChecked(True)
    shot("01_adaptive_dialog", whole_screen=True)
    dialog.accept()


@safe
def step3():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1 and ops[0].Label == "Adaptive 1", "one adaptive clearing made: {}".format([o.Label for o in ops]))  # fmt: skip
    OP = ops[0]
    found = cam().adaptive_of(OP)
    check(found == (body(), operations().Adaptive(-12.0, 4.0)), "its values: {}".format(found))
    check(lowest(OP) == -12.0, "down to Z-12: {}".format(lowest(OP)))
    r = rows()
    check(r.get("Area") == "Around the whole model (Body)", "details: area {}".format(r.get("Area")))
    check(r.get("Tool", "").startswith("T5 "), "details: tool {}".format(r.get("Tool")))
    check(r.get("Z levels") == "Z +0.00, -3.00, -7.00, -11.00, -12.00 (5 levels)", "details: levels {}".format(r.get("Z levels")))  # fmt: skip
    check(r.get("Path", "").endswith("down to Z -12.00 mm"), "details: path {}".format(r.get("Path")))
    check(field(panel().view, "AvangardeCamAdaptiveFromStock").isChecked(), "details: Start Z the top of the stock")
    blocks = nc_blocks()
    check("*- Adaptive Clearing" in blocks and "TOOL CALL 5 Z S12000 DL0 DR0;VHM ALU Frees 6mm" in blocks, "program: the clearing and its tool")  # fmt: skip
    check("L Z+20. R0 FMAX M3 M8" in blocks and "L Z+3. R0 FMAX" in blocks, "program: down over the start, 2 mm above the stock")  # fmt: skip
    shot("02_adaptive_details")
    field(panel().view, "AvangardeCamAdaptiveZStep").setProperty("rawValue", 6.0)
    later(2500, step4)


@safe
def step4():
    check(cam().adaptive_of(OP)[1].z_step_mm == 6.0, "details: Z step 6 applied after the pause")
    check(rows().get("Z levels") == "Z +0.00, -5.00, -11.00, -12.00 (4 levels)", "details follow: {}".format(rows().get("Z levels")))  # fmt: skip
    doc().undo()
    later(1500, step5)


@safe
def step5():
    check(cam().adaptive_of(OP)[1].z_step_mm == 4.0, "undo: Z step 4 again")
    check(raw(field(panel().view, "AvangardeCamAdaptiveZStep")) == 4.0, "details follow the undo")
    handlers().simulate()
    later(3000, step6)


@safe
def step6():
    from avangardecam.ui import simulation

    window = simulation.simulator_window()
    check(window is not None, "the simulator opens for the clearing")
    shot("03_simulation")
    if window is not None:
        window.close()

    def edit(dialog):
        check(dialog.windowTitle() == "Edit " + OP.Label, "Edit opens the window: {}".format(dialog.windowTitle()))
        values = (raw(field(dialog, "AvangardeCamAdaptiveDepth")), raw(field(dialog, "AvangardeCamAdaptiveZStep")))
        check(values == (-12.0, 4.0), "with its values: {}".format(values))
        check(field(dialog, "AvangardeCamAdaptiveTool").currentText().startswith("T5 "), "and its tool")
        field(dialog, "AvangardeCamAdaptiveStepOver").setValue(15.0)
        dialog.accept()

    modal(edit)
    handlers().edit_operation(OP)  # until the window closes
    check(cam().adaptive_of(OP)[1] == operations().Adaptive(-12.0, 4.0, 15.0), "edited: step over 15 %")
    later(500, step7)


@safe
def step7():
    # the top picked in the model (as a click on it does), the first clearing hidden
    global TOP
    from avangardecam.ui import scene

    scene.set_hidden(OP, True)
    shape = body().Shape
    TOP = max(
        (f.BoundBox.ZMax, f.Area, "Face{}".format(i))
        for i, f in enumerate(shape.Faces, start=1)
        if f.findPlane() is not None and geometry().outward_normal(shape, f).getAngle(FreeCAD.Vector(0, 0, 1)) < 1e-6
    )[2]
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, TOP)
    modal(dialog2)
    handlers().adaptive()
    later(500, step8)


def dialog2(dialog):
    area = field(dialog, "AvangardeCamAdaptiveArea").text()
    check(area == "1 floor of Body: Z +0.00", "a floor picked: " + area)
    tool = field(dialog, "AvangardeCamAdaptiveTool").currentText()
    check(tool.startswith("T5 ") and "new in" not in tool, "the tool used last: " + tool)
    check(raw(field(dialog, "AvangardeCamAdaptiveDepth")) == 0.0, "Z-Depth: the floor")
    check(raw(field(dialog, "AvangardeCamAdaptiveZStep")) == 4.0, "the Z step used last (not the edit)")
    check(field(dialog, "AvangardeCamAdaptiveStepOver").value() == 20.0, "the step over used last (not the edit)")
    dialog.accept()


@safe
def step8():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 2 and ops[1].Label == "Adaptive 2", "a second clearing: {}".format([o.Label for o in ops]))
    check(cam().adaptive_floors(ops[1]) == [TOP], "of the picked floor: {}".format(cam().adaptive_floors(ops[1])))
    check(lowest(ops[1]) == 0.0, "down to the floor: {}".format(lowest(ops[1])))
    check(FreeCADGui.Selection.getSelection() == [], "the model is not left selected")
    shot("04_floor")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step9)


@safe
def step9():
    ops = cam().operations(cam().find_job(doc()))
    check([cam().adaptive_of(o)[1] for o in ops] == [operations().Adaptive(-12.0, 4.0, 15.0), operations().Adaptive(0.0, 4.0)], "reopened: both clearings")  # fmt: skip
    for op in ops:
        op.touch()
    doc().recompute()
    check([lowest(o) for o in ops] == [-12.0, 0.0], "reopened: the paths again")
    handlers()._select("operation", ops[1].Name)
    QtWidgets.QApplication.processEvents()
    check(rows().get("Area") == "1 floor of Body: Z +0.00", "reopened: the details {}".format(rows().get("Area")))
    shot("05_reopened")
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
