# Facing GUI test on the test model (a block 40 x 20 x 12 with two Ø4.5
# holes through it; zero on its top, the stock 1 mm around and on top).
# Facing levels the top of the model only (the user's choice). CAM > Facing
# with nothing clicked only says what to click. The top face
# clicked: the window (the face, Start Z from the stock, the Z levels, no
# tool: OK refused, a drill refused, T5: 6 passes of at most 4.2 mm, the face mill
# T16 Ø50: 1 pass), the facing over the whole stock, the details (the
# pattern live, undo), the program, Edit... (the first pass along Y), a
# second facing starting with the tool used last; save and reopen.
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
LOG = open(os.path.join(OUT, "test_facing.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "facing.FCStd")


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
    from avangardecam.engine import facing

    return facing


def handlers():
    from avangardecam import handlers as h

    return h


def facing():
    from avangardecam.model import facing as f

    return f


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


def top_face():
    from avangardecam.engine import geometry

    shape = body().Shape
    return max(
        (f.BoundBox.ZMax, f.Area, "Face{}".format(i))
        for i, f in enumerate(shape.Faces, start=1)
        if f.findPlane() is not None and geometry.outward_normal(shape, f).getAngle(FreeCAD.Vector(0, 0, 1)) < 1e-6
    )[2]


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    global TOP
    FreeCADGui.Selection.clearSelection()
    handlers().facing()  # nothing clicked: no window
    check(QtWidgets.QApplication.activeModalWidget() is None, "nothing clicked: no window")
    message = mw().statusBar().currentMessage()
    check(message.startswith("Click the flat face at the top"), "it says what to click: " + message)
    TOP = top_face()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, TOP)
    modal(dialog1)
    handlers().facing()
    later(500, step3)


def dialog1(dialog):
    check(dialog.objectName() == "AvangardeCamFacingDialog", "the Facing window opens")
    check(dialog.pictures.shown == "facing_start.svg", "the window opens with its picture")
    face = field(dialog, "AvangardeCamFacingFace").text()
    check(face == "{} of Body: Z +0.00".format(TOP), "the face: " + face)
    start = field(dialog, "AvangardeCamFacingStartZ")
    check(raw(start) == 1.0 and not start.isEnabled(), "Start Z: the top of the stock, +1")
    check(field(dialog, "AvangardeCamFacingFromStock").isChecked(), "Top of the stock ticked")
    levels = field(dialog, "AvangardeCamFacingLevels")
    check(levels.text() == "Z +0.00 (1 level)", "the levels: " + levels.text())
    check(field(dialog, "AvangardeCamFacingTool").currentIndex() == -1, "no tool in the setup yet: none chosen")
    dialog.accept()
    message = field(dialog, "AvangardeCamFacingMessage").text()
    check(dialog.isVisible() and message.startswith("Choose a tool"), "OK without a tool refused: " + message)
    fit = field(dialog, "AvangardeCamFacingFit")
    dialog.use(variant(40, "Aluminium"))
    check(fit.isVisible() and "not a face mill" in fit.text(), "a drill: " + fit.text())
    dialog.accept()
    check(dialog.isVisible(), "a drill refused")
    dialog.use(variant(5, "Aluminium"))
    check(not fit.isVisible(), "T5 fits: " + fit.text())
    check(field(dialog, "AvangardeCamFacingStepOverMm").text() == "= 4.2 mm", "70 % of Ø6")
    passes = field(dialog, "AvangardeCamFacingPasses").text()
    check(passes == "6 passes, on each level", "Ø6 over the stock 22 wide: " + passes)
    dialog.use(variant(16, "Aluminium"))  # the face mill Ø50
    passes = field(dialog, "AvangardeCamFacingPasses").text()
    check(passes == "1 pass, on each level", "Ø50: " + passes)
    feeds = field(dialog, "AvangardeCamFacingFeeds").text()
    check(feeds == "Z 3750, XY 3500 mm/min", "the feeds: " + feeds)
    check(not field(dialog, "AvangardeCamFacingEntries").isVisible(), "in from outside the stock: no warning")
    field(dialog, "AvangardeCamFacingFromStock").setChecked(False)
    check(start.isEnabled(), "Start Z can be typed")
    start.setProperty("rawValue", -1.0)
    check(fit.isVisible() and "above the face" in fit.text(), "Start Z under the face: " + fit.text())
    field(dialog, "AvangardeCamFacingFromStock").setChecked(True)
    check(raw(start) == 1.0 and not fit.isVisible(), "back to the top of the stock")
    field(dialog, "AvangardeCamFacingAdvanced").setChecked(True)
    shot("01_facing_dialog", whole_screen=True)
    dialog.accept()


@safe
def step3():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1 and ops[0].Label == "Facing 1", "one facing made: {}".format([o.Label for o in ops]))
    OP = ops[0]
    found = engine().facing_of(OP)
    check(found == (body(), facing().Facing()), "its values: {}".format(found))
    check(lowest(OP) == 0.0, "on the top, Z0: {}".format(lowest(OP)))
    check(FreeCADGui.Selection.getSelection() == [], "the model is not left selected")
    r = rows()
    check(r.get("Face") == "{} of Body: Z +0.00".format(TOP), "details: face {}".format(r.get("Face")))
    check(r.get("Tool", "").startswith("T16 "), "details: tool {}".format(r.get("Tool")))
    check(r.get("Z levels") == "Z +0.00 (1 level)", "details: levels {}".format(r.get("Z levels")))
    check(r.get("Path", "").endswith("down to Z 0.00 mm"), "details: path {}".format(r.get("Path")))
    blocks = nc_blocks()
    check("*- Facing" in blocks, "program: the facing")
    check("L Z+20. R0 FMAX M3 M8" in blocks and "L Z+3. R0 FMAX" in blocks, "program: down over the start, 2 mm above the stock")  # fmt: skip
    shot("02_facing_details")
    pattern = field(panel().view, "AvangardeCamFacingPattern")
    pattern.setCurrentIndex(pattern.findData(facing().ONE_WAY))
    later(2500, step4)


@safe
def step4():
    check(engine().facing_of(OP)[1].pattern == facing().ONE_WAY, "details: one way applied")
    doc().undo()
    later(1500, step5)


@safe
def step5():
    check(engine().facing_of(OP)[1].pattern == facing().ZIGZAG, "undo: zigzag again")
    pattern = field(panel().view, "AvangardeCamFacingPattern")
    check(pattern.currentData() == facing().ZIGZAG, "details follow the undo")

    def edit(dialog):
        check(dialog.windowTitle() == "Edit " + OP.Label, "Edit opens the window: {}".format(dialog.windowTitle()))
        check(field(dialog, "AvangardeCamFacingTool").currentText().startswith("T16 "), "with its tool")
        direction = field(dialog, "AvangardeCamFacingDirection")
        side = field(dialog, "AvangardeCamFacingStartSide")
        check([side.itemText(i) for i in range(side.count())] == ["Y-", "Y+"], "start sides across passes along X")
        check(side.currentData() == facing().FROM_MINUS, "X+ starts where it climbs: Y-")
        direction.setCurrentIndex(direction.findData(facing().Y_PLUS))
        check([side.itemText(i) for i in range(side.count())] == ["X-", "X+"], "start sides across passes along Y")
        check(side.currentData() == facing().FROM_PLUS, "Y+ starts where it climbs: X+")
        side.setCurrentIndex(side.findData(facing().FROM_MINUS))
        field(dialog, "AvangardeCamFacingStepOver").setValue(60.0)
        dialog.accept()

    modal(edit)
    handlers().edit_operation(OP)  # until the window closes
    wanted = facing().Facing(step_over_percent=60.0, direction=facing().Y_PLUS, start_side=facing().FROM_MINUS)
    check(engine().facing_of(OP)[1] == wanted, "edited: {}".format(engine().facing_of(OP)[1]))
    later(500, step6)


@safe
def step6():
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, TOP)

    def dialog2(dialog):
        tool = field(dialog, "AvangardeCamFacingTool").currentText()
        check(tool.startswith("T16 "), "the tool used last: " + tool)
        check(field(dialog, "AvangardeCamFacingStepOver").value() == 70.0, "the values used last (not the edit)")
        check(field(dialog, "AvangardeCamFacingDirection").currentData() == facing().X_PLUS, "the direction used last")
        check(field(dialog, "AvangardeCamFacingStartSide").currentData() == facing().FROM_MINUS, "climbing again")
        dialog.reject()

    modal(dialog2)
    handlers().facing()
    later(500, step7)


@safe
def step7():
    check(len(cam().operations(cam().find_job(doc()))) == 1, "Cancel makes nothing")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step8)


@safe
def step8():
    ops = cam().operations(cam().find_job(doc()))
    wanted = facing().Facing(step_over_percent=60.0, direction=facing().Y_PLUS, start_side=facing().FROM_MINUS)
    check([engine().facing_of(o)[1] for o in ops] == [wanted], "reopened: the facing")
    ops[0].touch()
    doc().recompute()
    check(lowest(ops[0]) == 0.0, "reopened: the path again")
    handlers()._select("operation", ops[0].Name)
    QtWidgets.QApplication.processEvents()
    check(rows().get("Face") == "{} of Body: Z +0.00".format(TOP), "reopened: the details {}".format(rows().get("Face")))
    shot("03_reopened")
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
