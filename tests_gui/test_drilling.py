# Drilling GUI test: the two Ø4.5 holes on top of the test model, clicked
# (real mouse events, Shift+click adds the second) in the order they are
# drilled. The Drilling window: no tool yet (OK refused), T40 from the
# library, its feeds and the tip depth to the full diameter, a positive
# depth refused, Advanced shows the cycle's other values. The drilling
# keeps the click order; the details show it and change it live (undo);
# the NC program has cycle 205 with CYCL CALL POS on the holes in that
# order; the simulator opens; the window remembers the values and suggests
# the Ø4.5 drill in the material of the tool used last; a whole sketch means
# all its circles; save and reopen.
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
LOG = open(os.path.join(OUT, "test_drilling.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "drilling.FCStd")


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


def view():
    return FreeCADGui.ActiveDocument.ActiveView


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


def click(point, modifiers=QtCore.Qt.NoModifier):
    """A real left click of the mouse on the 3D view at a part point."""
    widget = view().graphicsView().viewport()
    from avangardecam.ui import scene as _scene

    x, y = view().getPointOnScreen(_scene.to_view(doc(), point))  # the view is in the setup's coordinates
    pos = QtCore.QPointF(x, widget.height() - y)  # Coin counts from the bottom
    log("  click at", pos, modifiers)
    events = (
        (QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
        (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
        (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton),
    )
    for kind, button, buttons in events:
        event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button, buttons, modifiers)
        QtWidgets.QApplication.sendEvent(widget, event)
        QtWidgets.QApplication.processEvents()


def selection():
    return [(s.Object.Name, [n.split(".")[-1] for n in s.SubElementNames]) for s in FreeCADGui.Selection.getSelectionEx()]


def t40_alu():
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == 40 and e.workpiece_material == "Aluminium")


def t21_rvs():
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


def nc_text():
    from avangardecam.post import heidenhain

    return heidenhain.write(cam().nc_program(doc(), "TEST"))


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    shape = body().Shape
    top = max(
        (f.BoundBox.ZMax, f.Area, "Face{}".format(i))
        for i, f in enumerate(shape.Faces, start=1)
        if f.findPlane() is not None and geometry().outward_normal(shape, f).getAngle(FreeCAD.Vector(0, 0, 1)) < 1e-6
    )[2]
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, top)
    handlers().extract_boundary()
    later(800, step3)


@safe
def step3():
    global SKETCH, RIGHT, LEFT
    SKETCH = next(o for o in doc().Objects if o.TypeId == "Sketcher::SketchObject")
    circles = geometry().sketch_circles(SKETCH)
    check(len(circles) == 2, "the top's sketch has the two holes: {}".format(circles))
    by_x = sorted(circles, key=lambda n: SKETCH.Shape.getElement(n).Curve.Center.x)
    LEFT, RIGHT = by_x
    FreeCADGui.Selection.clearSelection()
    view().viewTop()
    later(1500, step4)


def on_circle(name):
    """A point of the circle away from its direction arrow (in its middle)."""
    edge = SKETCH.Shape.getElement(name)
    return edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) / 4.0)


@safe
def step4():
    view().fitAll()
    QtWidgets.QApplication.processEvents()
    # the right hole first, then Shift+click the left one
    click(on_circle(RIGHT))
    click(on_circle(LEFT), QtCore.Qt.ShiftModifier)
    check(selection() == [(SKETCH.Name, [RIGHT, LEFT])], "two circles clicked, right first: {}".format(selection()))
    shot("01_circles_clicked")
    modal(dialog1)
    handlers().drilling()
    later(500, step5)


def dialog1(dialog):
    check(dialog.objectName() == "AvangardeCamDrillingDialog", "drilling window opens")
    holes = field(dialog, "AvangardeCamDrillingHoles").text()
    check(holes == "2: Ø4.5 → Ø4.5", "holes shown in the click order: {}".format(holes))
    tool = field(dialog, "AvangardeCamDrillingTool")
    check(tool.currentIndex() == -1, "no tool in the setup: none chosen")
    peck = float(field(dialog, "AvangardeCamDrillingPeck").property("rawValue"))
    chip = float(field(dialog, "AvangardeCamDrillingChipBreak").property("rawValue"))
    check((peck, chip) == (1.0, 4.0), "first time: Q202 1 mm, Q257 4 mm: {}".format((peck, chip)))
    dialog.accept()
    message = field(dialog, "AvangardeCamDrillingMessage").text()
    check(dialog.isVisible() and message.startswith("Choose a tool"), "OK without a tool refused: {}".format(message))
    dialog.use(t40_alu())
    feeds = field(dialog, "AvangardeCamDrillingFeeds").text()
    check(feeds == "Q206 500, Q253 375 mm/min", "the cycle's feeds from T40 Alu: {}".format(feeds))
    hint = field(dialog, "AvangardeCamDrillingToolHint").text()
    check("added" in hint, "T40 is added to the setup: {}".format(hint))
    only = field(dialog, "AvangardeCamDrillingToolFilter")
    check(only is not None and only.isChecked() and only.text() == "Drills only", "Drills only, on at the start")
    dialog.use(t21_rvs())
    check(not only.isChecked(), "an end mill chosen: Drills only off, all tools shown")
    check(dialog.tool().number == 21, "T21 chosen: {}".format(dialog.tool().number))
    only.setChecked(True)
    tool = field(dialog, "AvangardeCamDrillingTool")
    texts = [tool.itemText(i) for i in range(tool.count())]
    check(not any(t.startswith("T21 ") for t in texts), "Drills only hides T21: {}".format(texts))
    check(dialog.tool() is None, "the hidden T21 is no longer chosen")
    only.setChecked(False)
    texts = [tool.itemText(i) for i in range(tool.count())]
    check(any(t.startswith("T21 ") for t in texts), "off: T21 in the list again: {}".format(texts))
    dialog.use(t40_alu())
    only.setChecked(True)
    check(dialog.tool().number == 40, "T40 stays chosen with Drills only on")
    modal(picker_drills_only)
    field(dialog, "AvangardeCamChooseTool").click()
    field(dialog, "AvangardeCamDrillingDepth").setProperty("rawValue", 8.0)
    dialog.accept()
    message = field(dialog, "AvangardeCamDrillingMessage").text()
    check(dialog.isVisible() and "negative" in message, "a positive depth refused: {}".format(message))
    field(dialog, "AvangardeCamDrillingDepth").setProperty("rawValue", -8.0)
    depth_to = field(dialog, "AvangardeCamDrillingDepthTo")
    depth_to.setCurrentIndex(depth_to.findData(operations().FULL_DIAMETER))
    tip = field(dialog, "AvangardeCamDrillingTip").text()
    check(tip == "10.043 mm deep (point 2.043 mm)", "to the full diameter the 118° tip goes deeper: {}".format(tip))
    field(dialog, "AvangardeCamDrillingPeck").setProperty("rawValue", 3.0)
    field(dialog, "AvangardeCamDrillingChipBreak").setProperty("rawValue", 1.0)
    second = field(dialog, "AvangardeCamDrillingSecondClearance")
    check(not second.isVisible(), "the cycle's other values under Advanced, hidden")
    field(dialog, "AvangardeCamDrillingAdvanced").click()
    QtWidgets.QApplication.processEvents()
    check(second.isVisible(), "Advanced shows them")
    check(abs(float(second.property("rawValue")) - 50.0) < 1e-9, "2nd set-up clearance 50 as the shop's programs")
    second.setProperty("rawValue", 30.0)
    QtWidgets.QApplication.processEvents()
    shot("02_drilling_dialog", whole_screen=True)
    dialog.accept()


def picker_drills_only(picker):
    only = field(picker, "AvangardeCamToolKindFilter")
    check(only is not None and only.isChecked(), "Choose tool...: Drills only on, as in the window")
    shapes = {e.tool.shape for e in picker.shown}
    check(shapes == {"Drill"}, "Choose tool... shows only drills: {}".format(shapes))
    only.setChecked(False)
    check(len(picker.shown) > len([e for e in picker.entries if e.tool.shape == "Drill"]), "off: all tools")
    picker.reject()


@safe
def step5():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "one drilling made")
    OP = ops[0]
    found = cam().drilling_of(OP)
    check(found is not None, "it is a drilling of AvangardeCam")
    wanted = operations().Drilling(-8.0, operations().FULL_DIAMETER, peck_mm=3.0, chip_break_mm=1.0, second_clearance_mm=30.0)
    check(found[1] == wanted, "the window's values: {}".format(found[1]))
    holes = [(round(x, 3), round(y, 3)) for x, y, _d in cam().drilling_holes(OP)]
    check(holes == [(15.0, 0.0), (-15.0, 0.0)], "drilled in the click order: {}".format(holes))
    check(int(OP.ToolController.ToolNumber) == 40, "with T40")
    r = rows()
    check(r.get("Holes") == "2: Ø4.5 → Ø4.5", "details: holes {}".format(r.get("Holes")))
    check(r.get("Tool", "").startswith("T40 "), "details: tool {}".format(r.get("Tool")))
    check(r.get("Path") == "2 holes, tip at Z -10.04 mm", "details: path {}".format(r.get("Path")))
    shot("03_drilling_details")
    field(panel().view, "AvangardeCamDrillingDepth").setProperty("rawValue", -6.0)
    later(1500, step6)


@safe
def step6():
    check(cam().drilling_of(OP)[1].depth_mm == -6.0, "details: depth -6 applied after the pause")
    check(rows().get("Path") == "2 holes, tip at Z -8.04 mm", "details follow: {}".format(rows().get("Path")))
    depth_to = field(panel().view, "AvangardeCamDrillingDepthTo")
    depth_to.setCurrentIndex(depth_to.findData(operations().TIP))
    check(cam().drilling_of(OP)[1].depth_to == operations().TIP, "details: depth to the tip applied at once")
    doc().undo()
    later(800, step7)


@safe
def step7():
    drilling = cam().drilling_of(OP)[1]
    check((drilling.depth_mm, drilling.depth_to) == (-6.0, operations().FULL_DIAMETER), "undo: to the full diameter again")
    check(field(panel().view, "AvangardeCamDrillingDepthTo").currentData() == operations().FULL_DIAMETER, "details follow the undo")
    doc().undo()
    later(800, step8)


@safe
def step8():
    check(cam().drilling_of(OP)[1].depth_mm == -8.0, "undo: depth -8 again")
    text = nc_text()
    blocks = [line.split(" ", 1)[1] for line in text.split("\r\n") if line and not line.startswith(" ")]
    calls = [b for b in blocks if b.startswith("CYCL CALL POS")]
    check(calls == ["CYCL CALL POS X+15. Y+0. Z0 FMAX M3 M8", "CYCL CALL POS X-15. Y+0. Z0 FMAX"], "program: holes in the click order {}".format(calls))  # fmt: skip
    check("CYCL DEF 205 UNIVERSEELBOREN ~" in blocks and "*- Deep Drilling With Chip Breaking" in blocks, "program: cycle 205")
    for wanted in ("    Q201=-10.043    ;DIEPTE ~", "    Q202=+3.    ;DIEPTEVERPLAATSING ~", "    Q204=30   ;2e VEILIGHEIDSAFST. ~"):
        check(wanted in text, "program has " + wanted.strip())
    handlers().simulate()
    later(2500, step9)


@safe
def step9():
    from avangardecam.ui import simulation

    window = simulation.simulator_window()
    check(window is not None, "the simulator opens for the drilling")
    shot("04_simulation")
    if window is not None:
        window.close()
    # the window starts with the values used last and the shop's drill of the
    # holes' size (T47) in the material of the drill used last (T40 Alu); a
    # whole sketch: all circles
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, SKETCH.Name)
    modal(dialog2)
    handlers().drilling()
    later(500, step10)


def dialog2(dialog):
    holes = field(dialog, "AvangardeCamDrillingHoles").text()
    check(holes == "all 2: Ø4.5", "whole sketch: all its circles: {}".format(holes))
    tool = field(dialog, "AvangardeCamDrillingTool").currentText()
    check(tool.startswith("T47  NX Boor 4.5mm Alu"), "a Ø4.5 drill in the material used last: {}".format(tool))
    depth = float(field(dialog, "AvangardeCamDrillingDepth").property("rawValue"))
    check(depth == -8.0, "the depth used last: {}".format(depth))
    check(field(dialog, "AvangardeCamDrillingDepthTo").currentData() == operations().FULL_DIAMETER, "the depth reference used last")
    dialog.reject()


@safe
def step10():
    check(len(cam().operations(cam().find_job(doc()))) == 1, "cancel makes nothing")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step11)


@safe
def step11():
    op = cam().operations(cam().find_job(doc()))[0]
    holes = [(round(x, 3), round(y, 3)) for x, y, _d in cam().drilling_holes(op)]
    check(holes == [(15.0, 0.0), (-15.0, 0.0)], "reopened: the click order stays {}".format(holes))
    handlers()._select("operation", op.Name)
    QtWidgets.QApplication.processEvents()
    check(rows().get("Holes") == "2: Ø4.5 → Ø4.5", "reopened: the details of the drilling")
    shot("05_reopened")

    def edit(dialog):
        check(dialog.windowTitle() == "Edit " + op.Label, "Edit opens the Drilling window: {}".format(dialog.windowTitle()))
        holes = field(dialog, "AvangardeCamDrillingHoles").text()
        tool = field(dialog, "AvangardeCamDrillingTool").currentText()
        depth = float(field(dialog, "AvangardeCamDrillingDepth").property("rawValue"))
        check((holes, tool[:4], depth) == ("2: Ø4.5 → Ø4.5", "T40 ", -8.0), "with its holes, tool and values: {}".format((holes, tool, depth)))  # fmt: skip
        field(dialog, "AvangardeCamDrillingPeck").setProperty("rawValue", 2.0)
        dialog.accept()

    modal(edit)
    handlers().edit_operation(op)  # until the window closes
    drilling = cam().drilling_of(op)[1]
    check((drilling.peck_mm, drilling.depth_mm, drilling.second_clearance_mm) == (2.0, -8.0, 30.0), "edited: peck 2, the rest kept")  # fmt: skip
    holes = [(round(x, 3), round(y, 3)) for x, y, _d in cam().drilling_holes(op)]
    check(holes == [(15.0, 0.0), (-15.0, 0.0)], "and the click order")
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
