# Selection kept GUI test: a sketch from a saved file (the case where FreeCAD
# lost it), its lines clicked for an operation whose tool comes new from the
# library. FreeCAD makes the tool bit's shape in a hidden document and
# copies it in, and after that the whole sketch was selected instead of the
# clicked lines; they stay selected now, in click order, with their arrows:
# two circles drilled with T40 (the setup has no tool yet), then two lines
# of the top contoured with T21.
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
LOG = open(os.path.join(OUT, "test_selection_kept.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "selection_kept.FCStd")


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


def shot(name):
    path = os.path.join(OUT, name + ".png")
    mw().grab().save(path)
    log("screenshot", path)


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def geometry():
    from avangardecam.engine import geometry as g

    return g


def handlers():
    from avangardecam import handlers as h

    return h


def scene():
    from avangardecam.ui import scene as s

    return s


def direction():
    from avangardecam.ui import direction as d

    return d


def doc():
    return FreeCAD.ActiveDocument


def body():
    return cam().models(doc())[0]


def view():
    return FreeCADGui.ActiveDocument.ActiveView


def entry(number, material):
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == number and e.workpiece_material == material)


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


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


def on_line(name):
    """A point of a line away from its direction arrow (in its middle)."""
    edge = SKETCH.Shape.getElement(name)
    return edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) / 4.0)


def click(point, modifiers=QtCore.Qt.NoModifier):
    """A real left click of the mouse on the 3D view at a part point."""
    widget = view().graphicsView().viewport()
    x, y = view().getPointOnScreen(scene().to_view(doc(), point))
    pos = QtCore.QPointF(x, widget.height() - y)  # Coin counts from the bottom
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


def arrows():
    return sorted(line for _d, _s, line, _p, _c in direction()._State.shown)


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
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step4)


@safe
def step4():
    global SKETCH, LEFT, RIGHT
    SKETCH = next(o for o in doc().Objects if o.TypeId == "Sketcher::SketchObject")
    circles = sorted(geometry().sketch_circles(SKETCH), key=lambda n: SKETCH.Shape.getElement(n).Curve.Center.x)
    check(len(circles) == 2, "reopened: the top's sketch has the two holes: {}".format(circles))
    LEFT, RIGHT = circles
    check(cam().project_tools(cam().find_job(doc())) == [], "the setup has no tool yet")
    FreeCADGui.Selection.clearSelection()
    view().viewTop()
    later(1500, step5)


@safe
def step5():
    view().fitAll()
    QtWidgets.QApplication.processEvents()
    click(on_line(RIGHT))
    click(on_line(LEFT), QtCore.Qt.ShiftModifier)
    check(selection() == [(SKETCH.Name, [RIGHT, LEFT])], "two circles clicked, right first: {}".format(selection()))

    def fill(dialog):
        dialog.use(entry(40, "Aluminium"))
        field(dialog, "AvangardeCamDrillingDepth").setProperty("rawValue", -8.0)
        dialog.accept()

    modal(fill)
    handlers().drilling()
    later(1000, step6)


@safe
def step6():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1 and ops[0].ToolController.ToolNumber == 40, "drilled with T40, new from the library")
    check(selection() == [(SKETCH.Name, [RIGHT, LEFT])], "the circles stay selected, not the whole sketch: {}".format(selection()))  # fmt: skip
    check(arrows() == sorted([RIGHT, LEFT]), "their arrows stay: {}".format(arrows()))
    shot("01_drilled_circles_selected")
    FreeCADGui.Selection.clearSelection()
    # two straight lines of the outline that meet
    edges = SKETCH.Shape.Edges
    lines = [i for i, e in enumerate(edges, start=1) if e.Curve.TypeId == "Part::GeomLine" and e.Length > 5]
    global LINE_A, LINE_B
    LINE_A, LINE_B = next(
        ("Edge{}".format(i), "Edge{}".format(j))
        for i in lines
        for j in lines
        if i != j
        and any(p.Point.distanceToPoint(q.Point) < 1e-6 for p in edges[i - 1].Vertexes for q in edges[j - 1].Vertexes)
    )
    later(500, step7)


@safe
def step7():
    click(on_line(LINE_A))
    click(on_line(LINE_B), QtCore.Qt.ShiftModifier)
    check(selection() == [(SKETCH.Name, [LINE_A, LINE_B])], "two lines clicked: {}".format(selection()))

    def fill(dialog):
        dialog.use(entry(21, "RVS"))
        field(dialog, "AvangardeCamContourDepth").setProperty("rawValue", -1.0)
        dialog.accept()

    modal(fill)
    handlers().contour_tooling()
    later(1000, step8)


@safe
def step8():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 2 and ops[1].ToolController.ToolNumber == 21, "contoured with T21, new from the library")
    check(cam().contour_lines(ops[1]) == [LINE_A, LINE_B], "the contour follows the clicked lines")
    check(selection() == [(SKETCH.Name, [LINE_A, LINE_B])], "the lines stay selected, not the whole sketch: {}".format(selection()))  # fmt: skip
    check(arrows() == sorted([LINE_A, LINE_B]), "their arrows stay: {}".format(arrows()))
    shot("02_contour_lines_selected")
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
