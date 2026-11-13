# Start contour and End contour GUI test: two joined lines of the top's
# outline, Contour tooling: the two fields hidden without Advanced, shown
# with it, 0 mm at first; +5 / -3 mm make the contour. In the details
# Advanced is checked for it; Start contour 0 moves where the tool goes
# down by 5 mm, undo; Advanced unchecked runs the whole lines. Edit...
# opens with Advanced and the values, -1 mm typed there.
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
LOG = open(os.path.join(OUT, "test_contour_ends.txt"), "w")
FAILURES = []
NAMES = {}  # "sketch", "op": object names (they outlive reopening)


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


def handlers():
    from avangardecam import handlers as h

    return h


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def doc():
    return FreeCAD.ActiveDocument


def sketch():
    return doc().getObject(NAMES["sketch"])


def op():
    return doc().getObject(NAMES["op"])


def contour():
    return cam().contour_of(op())[1]


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


def box(widget, name):
    return widget.findChild(QtWidgets.QWidget, "AvangardeCam" + name)


def first_cut():
    """(x, y) where the tool goes down to cut, in the setup's coordinates."""
    moves = [c for c in op().Path.Commands if c.Name in ("G1", "G2", "G3") and "X" in c.Parameters]
    return round(moves[0].Parameters["X"], 3), round(moves[0].Parameters["Y"], 3)


def open_lines():
    """Two joined lines of the top's outline: an open chain."""
    for i, a in enumerate(sketch().Shape.Edges, start=1):
        for j, b in enumerate(sketch().Shape.Edges, start=1):
            if i < j and a.Curve.TypeId == b.Curve.TypeId == "Part::GeomLine" and a.Length > 10 and b.Length > 10:
                if any(p.isEqual(q, 1e-6) for p in (a.Vertexes[0].Point, a.Vertexes[1].Point)
                       for q in (b.Vertexes[0].Point, b.Vertexes[1].Point)):  # fmt: skip
                    return ["Edge{}".format(i), "Edge{}".format(j)]
    raise AssertionError("no two joined lines")


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    from avangardecam import tool_library_path
    from avangardecam.engine import geometry
    from avangardecam.model import library

    body = cam().models(doc())[0]
    top = max(
        (f for f in body.Shape.Faces if f.findPlane() is not None and f.normalAt(0, 0).z > 0.99),
        key=lambda f: (round(f.BoundBox.ZMax, 6), f.Area),
    )
    name = "Face{}".format(next(i for i, f in enumerate(body.Shape.Faces, start=1) if f.isSame(top)))
    made = geometry.extract_boundary(doc(), [body], body, name)
    job = cam().find_job(doc())
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    cam().add_tool(job, variant)
    NAMES["sketch"] = made.Name
    doc().recompute()
    panel().refresh()
    FreeCADGui.Selection.clearSelection()
    for edge in open_lines():
        FreeCADGui.Selection.addSelection(doc().Name, made.Name, edge)
    modal(dialog_plain)
    handlers().contour_tooling()
    later(800, step3)


def dialog_plain(widget):
    start, end = box(widget, "StartContour"), box(widget, "EndContour")
    check(start is not None and end is not None, "the window has Start contour and End contour")
    check(not start.isVisible() and not end.isVisible(), "hidden without Advanced")
    box(widget, "ContourAdvanced").setChecked(True)
    check(start.isVisible() and end.isVisible(), "shown with Advanced")
    check(start.property("rawValue") == 0.0 and end.property("rawValue") == 0.0, "0 mm at first")
    start.setProperty("rawValue", 5.0)
    end.setProperty("rawValue", -3.0)
    QtWidgets.QApplication.processEvents()  # the window grows for the rows of Advanced
    widget.grab().save(os.path.join(OUT, "01_dialog_ends.png"))
    check(all(b.height() >= b.minimumSizeHint().height() for b in (start, end)), "the rows of Advanced not squashed")
    check(not any(len(label.text()) > 400 for label in widget.findChildren(QtWidgets.QLabel)), "no long note under the fields")
    manual = box(widget, "Manual")
    check(manual is not None, "a Manual button")
    if manual is not None:
        manual.click()
        QtWidgets.QApplication.processEvents()
        window = widget.findChild(QtWidgets.QDialog, "AvangardeCamManualWindow")
        text = window.findChild(QtWidgets.QTextBrowser).toPlainText() if window is not None else ""
        check(window is not None and window.isVisible(), "Manual opens its window")
        check("Start contour and End contour" in text, "the Manual has how the contour works")
        if window is not None:
            window.grab().save(os.path.join(OUT, "01_manual.png"))
            window.close()
        check(widget.isVisible(), "the contour window stays open")
    widget.accept()


@safe
def step3():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "OK made the contour")
    NAMES["op"] = ops[0].Name
    c = contour()
    check((c.start_extend_mm, c.end_extend_mm) == (5.0, -3.0), "its values: {} {}".format(c.start_extend_mm, c.end_extend_mm))
    NAMES["cut"] = first_cut()
    panel().select_entry("operation", NAMES["op"])
    later(600, step4)


@safe
def step4():
    view = panel().view
    check(view.ends.boxes["start_extend_mm"].isVisible(), "details: Advanced open, Start contour shown")
    check(view.advanced.check.isChecked(), "details: Advanced checked for it")
    shot("02_details_ends")
    doc_ = doc()
    view.ends.boxes["start_extend_mm"].setProperty("rawValue", 0.0)
    view.apply()
    check(contour().start_extend_mm == 0.0, "details: Start contour 0 typed")
    cut = first_cut()
    moved = abs(cut[0] - NAMES["cut"][0]) + abs(cut[1] - NAMES["cut"][1])
    check(abs(moved - 5.0) < 1e-3, "the tool goes down 5 mm further on: {} -> {}".format(NAMES["cut"], cut))
    doc_.undo()
    check(contour().start_extend_mm == 5.0, "undo: 5 mm again")
    view = panel().view
    view.advanced.check.setChecked(False)
    later(300, step5)


@safe
def step5():
    c = contour()
    check((c.start_extend_mm, c.end_extend_mm) == (0.0, 0.0), "Advanced unchecked: the whole lines")
    view = panel().view
    view.advanced.check.setChecked(True)
    view.ends.boxes["end_extend_mm"].setProperty("rawValue", 2.0)
    view.apply()
    check(contour().end_extend_mm == 2.0, "End contour +2 typed")
    modal(dialog_edit)
    handlers().edit_operation(op())
    later(800, step6)


def dialog_edit(widget):
    check(box(widget, "ContourAdvanced").isChecked(), "Edit...: Advanced checked")
    check(box(widget, "EndContour").property("rawValue") == 2.0, "Edit...: End contour 2 mm")
    box(widget, "StartContour").setProperty("rawValue", -1.0)
    widget.accept()


@safe
def step6():
    check(contour().start_extend_mm == -1.0, "Edit...: Start contour -1 mm")
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


avangardecam.forget_last_values()
later(4000, step1)
