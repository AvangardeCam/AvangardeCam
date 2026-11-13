# Thread milling GUI test: the two Ø4.5 holes on top of the test model,
# clicked (real mouse events, Shift+click adds the second) in the order they
# are threaded. The Thread milling window: no thread mill fits a standard
# thread in Ø4.5 holes, so none is chosen (OK refused); a drill is not a
# thread mill (refused); T218 (M5, P0.8) from the library: the major
# diameter suggested from the holes (4.5 + 0.8), typed 5 (M5), the helix
# shown. The thread milling keeps the click order; its path is the tool
# centre's helix; the details show it and change it live (undo); the NC
# program has the helices with RR; the simulator opens; Edit... changes
# the depth; a hole clicked in the model starts with the thread mill used
# last; save and reopen.
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
LOG = open(os.path.join(OUT, "test_thread_milling.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "thread_milling.FCStd")


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


def variant(number, name):
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == number and e.tool.name == name)


def m5():
    return variant(218, "Draadfrees M5 P=0.8 St")


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


def nc_blocks():
    from avangardecam.post import heidenhain

    text = heidenhain.write(cam().nc_program(doc(), "TEST"))
    return [line.split(" ", 1)[1] for line in text.split("\r\n") if line and not line.startswith(" ")]


def helices(op):
    return [c for c in op.Path.Commands if c.Name in ("G2", "G3")]


def raw(widget):
    return float(widget.property("rawValue"))


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
    LEFT, RIGHT = sorted(circles, key=lambda n: SKETCH.Shape.getElement(n).Curve.Center.x)
    FreeCADGui.Selection.clearSelection()
    view().viewTop()
    later(1500, step4)


def on_circle(name):
    edge = SKETCH.Shape.getElement(name)
    return edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) / 4.0)


@safe
def step4():
    view().fitAll()
    QtWidgets.QApplication.processEvents()
    click(on_circle(RIGHT))
    click(on_circle(LEFT), QtCore.Qt.ShiftModifier)
    check(selection() == [(SKETCH.Name, [RIGHT, LEFT])], "two circles clicked, right first: {}".format(selection()))
    modal(dialog1)
    handlers().thread_milling()
    later(500, step5)


def picker_thread_mills_only(picker):
    only = field(picker, "AvangardeCamToolKindFilter")
    check(only is not None and only.isChecked(), "Choose tool...: Thread mills only on, as in the window")
    shapes = {e.tool.shape for e in picker.shown}
    check(shapes == {"ThreadMill"}, "Choose tool... shows only thread mills: {}".format(shapes))
    only.setChecked(False)
    check(len(picker.shown) == len(picker.entries), "off: all tools")
    picker.reject()


def dialog1(dialog):
    check(dialog.objectName() == "AvangardeCamThreadDialog", "thread milling window opens")
    holes = field(dialog, "AvangardeCamThreadHoles").text()
    check(holes == "2: Ø4.5 → Ø4.5", "holes in the click order: {}".format(holes))
    tool = field(dialog, "AvangardeCamThreadTool")
    check(tool.currentIndex() == -1, "no thread mill makes a standard thread of Ø4.5: none chosen")
    dialog.accept()
    message = field(dialog, "AvangardeCamThreadMessage").text()
    check(dialog.isVisible() and message.startswith("Choose a tool"), "OK without a tool refused: {}".format(message))
    from avangardecam import tool_library_path
    from avangardecam.model import library

    drill = next(e for e in library.load(tool_library_path()) if e.number == 40 and e.workpiece_material == "Aluminium")
    only = field(dialog, "AvangardeCamThreadToolFilter")
    check(only is not None and only.isChecked() and only.text() == "Thread mills only", "Thread mills only, on at the start")
    dialog.use(drill)
    check(not only.isChecked(), "a drill chosen: Thread mills only off, all tools shown")
    fit = field(dialog, "AvangardeCamThreadFit")
    check(fit.isVisible() and "not a thread mill" in fit.text(), "a drill: {}".format(fit.text()))
    dialog.accept()
    check(dialog.isVisible(), "a drill refused")
    dialog.use(m5())
    check(not fit.isVisible(), "T218 fits: {}".format(fit.text()))
    only.setChecked(True)
    texts = [tool.itemText(i) for i in range(tool.count())]
    check(not any(t.startswith("T40 ") for t in texts), "Thread mills only hides the drill: {}".format(texts))
    check(dialog.tool().number == 218, "T218 stays chosen")
    modal(picker_thread_mills_only)
    field(dialog, "AvangardeCamChooseTool").click()
    major = field(dialog, "AvangardeCamThreadMajor")
    name = field(dialog, "AvangardeCamThreadName")
    check(abs(raw(major) - 5.3) < 1e-9 and name.text() == "Ø5.3 P0.8", "suggested from the holes: {} {}".format(raw(major), name.text()))
    feeds = field(dialog, "AvangardeCamThreadFeeds").text()
    check(feeds == "Z {:g}, XY {:g} mm/min".format(m5().tool.feed_z_mm_min, m5().tool.feed_xy_mm_min), "the feeds: " + feeds)
    major.setProperty("rawValue", 5.0)
    field(dialog, "AvangardeCamThreadDepth").setProperty("rawValue", -8.0)
    check(name.text() == "M5", "typed 5: M5 ({})".format(name.text()))
    helix = field(dialog, "AvangardeCamThreadHelix").text()
    check(helix == "10 turns of P0.8, 2 passes", "the helix: " + helix)
    shot("01_thread_dialog", whole_screen=True)
    dialog.accept()


@safe
def step5():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "one thread milling made")
    OP = ops[0]
    found = cam().thread_milling_of(OP)
    check(found == (SKETCH, operations().ThreadMilling(5.0, -8.0, 2)), "M5, 8 deep, 2 passes: {}".format(found))
    check([(round(t.x, 3), round(t.y, 3)) for t in cam().drill_targets(OP)] == [(15.0, 0.0), (-15.0, 0.0)], "in the click order")  # fmt: skip
    check(len(helices(OP)) == 2 * 2 * 20, "20 half turns a pass: {}".format(len(helices(OP))))
    first = helices(OP)[0].Parameters
    check(abs(first["X"] - 14.5) < 1e-6 and abs(first["Z"] + 0.4) < 1e-6, "the tool centre 0.5 from the axis: {}".format(first))
    check(abs(cam().path_summary(OP)[1] + 8.0) < 1e-6, "down to Z-8")
    r = rows()
    check(r.get("Holes") == "2: Ø4.5 → Ø4.5", "details: holes {}".format(r.get("Holes")))
    check(r.get("Tool", "").startswith("T218 "), "details: tool {}".format(r.get("Tool")))
    check(r.get("Helix") == "10 turns of P0.8, 2 passes", "details: helix {}".format(r.get("Helix")))
    check(r.get("Path") == "2 holes, down to Z -8.00 mm", "details: path {}".format(r.get("Path")))
    blocks = nc_blocks()
    check("*- Thread Milling" in blocks and "TOOL CALL 218 Z S{:g} DL0 DR0;Draadfrees M5 P=0.8 St".format(m5().tool.spindle_rpm) in blocks, "program: the tool")  # fmt: skip
    check(blocks.count("CP IPA-180. IZ-0.4 DR-") == 80, "program: the helices")
    rr = [b for b in blocks if " RR " in b]
    check(rr == ["L X+17.5 RR FQ31"] * 2 + ["L X-12.5 RR FQ31"] * 2, "program: out to the thread with RR, right hole first: {}".format(rr))  # fmt: skip
    shot("02_thread_details")
    field(panel().view, "AvangardeCamThreadPasses").setValue(1)
    later(1500, step6)


@safe
def step6():
    check(cam().thread_milling_of(OP)[1].passes == 1, "details: 1 pass applied after the pause")
    check(len(helices(OP)) == 2 * 20, "the path follows: {}".format(len(helices(OP))))
    check(rows().get("Helix") == "10 turns of P0.8, 1 pass", "details follow: {}".format(rows().get("Helix")))
    doc().undo()
    later(800, step7)


@safe
def step7():
    check(cam().thread_milling_of(OP)[1].passes == 2, "undo: 2 passes again")
    check(field(panel().view, "AvangardeCamThreadPasses").value() == 2, "details follow the undo")
    handlers().simulate()
    later(2500, step8)


@safe
def step8():
    from avangardecam.ui import simulation

    window = simulation.simulator_window()
    check(window is not None, "the simulator opens for the thread milling")
    shot("03_simulation")
    if window is not None:
        window.close()

    def edit(dialog):
        check(dialog.windowTitle() == "Edit " + OP.Label, "Edit opens the window: {}".format(dialog.windowTitle()))
        values = (raw(field(dialog, "AvangardeCamThreadMajor")), raw(field(dialog, "AvangardeCamThreadDepth")), field(dialog, "AvangardeCamThreadPasses").value())  # fmt: skip
        check(values == (5.0, -8.0, 2), "with its values: {}".format(values))
        check(field(dialog, "AvangardeCamThreadTool").currentText().startswith("T218 "), "and its tool")
        field(dialog, "AvangardeCamThreadDepth").setProperty("rawValue", -6.0)
        dialog.accept()

    modal(edit)
    handlers().edit_operation(OP)  # until the window closes
    check(cam().thread_milling_of(OP)[1] == operations().ThreadMilling(5.0, -6.0, 2), "edited: 6 deep")
    check(len(helices(OP)) == 2 * 2 * 15, "15 half turns a pass now")
    later(500, step9)


@safe
def step9():
    import Part

    # a hole clicked in the model: its wall
    shape = body().Shape
    wall = next(
        "Face{}".format(i) for i, f in enumerate(shape.Faces, start=1)
        if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 2.25) < 1e-6 and f.Surface.Center.x > 0
    )  # fmt: skip
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, wall)
    modal(dialog2)
    handlers().thread_milling()
    later(500, step10)


def dialog2(dialog):
    holes = field(dialog, "AvangardeCamThreadHoles").text()
    check(holes == "1: Ø4.5 through", "a hole of the model: {}".format(holes))
    tool = field(dialog, "AvangardeCamThreadTool").currentText()
    check(tool.startswith("T218 ") and "new in" not in tool, "the thread mill used last: {}".format(tool))
    check(abs(raw(field(dialog, "AvangardeCamThreadDepth")) + 8.0) < 1e-9, "the depth used last (not the edited one)")
    check(abs(raw(field(dialog, "AvangardeCamThreadMajor")) - 5.3) < 1e-9, "the diameter from the hole again")
    dialog.accept()


@safe
def step10():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 2 and ops[1].Label == "Thread milling 2", "a second thread milling: {}".format([o.Label for o in ops]))
    found = cam().thread_milling_of(ops[1])
    check(found is not None and found[0] is body(), "of the model")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step11)


@safe
def step11():
    ops = cam().operations(cam().find_job(doc()))
    check([cam().thread_milling_of(o)[1] for o in ops] == [operations().ThreadMilling(5.0, -6.0, 2), operations().ThreadMilling(5.3, -8.0, 2)], "reopened: both thread millings")  # fmt: skip
    ops[0].touch()
    doc().recompute()
    check(len(helices(ops[0])) == 2 * 2 * 15, "reopened: the path again")
    check([(round(t.x, 3), round(t.y, 3)) for t in cam().drill_targets(ops[0])] == [(15.0, 0.0), (-15.0, 0.0)], "reopened: the click order stays")  # fmt: skip
    handlers()._select("operation", ops[0].Name)
    QtWidgets.QApplication.processEvents()
    check(rows().get("Helix") == "7.5 turns of P0.8, 2 passes", "reopened: the details {}".format(rows().get("Helix")))
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
