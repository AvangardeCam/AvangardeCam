# Relative GUI test: a block 40 x 20 x 10 with an island 10 x 10 x 4 on it
# (made here as a STEP), the zero point on the island's top, so the plate
# is at Z-4. A line of the island and a line of the plate in one contour:
# Relative checked at first (its note and the tool tips say from the
# lines); unchecked, Z-Depth -10 cuts both at Z-10. The details: Relative
# unchecked, Lines at Z 0 and -4; checked there cuts at -10 and -14, undo
# in one step. A new contour starts with Relative as used last; Edit...
# opens with the contour's. The plate sketch's details show its Z from the
# zero point.
#
# Run like test_layout.py (see README.md); AC_STEP is not used.
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_contour_relative.txt"), "w")
FAILURES = []
NAMES = {}  # "island", "plate", "op": object names


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


def op():
    return doc().getObject(NAMES["op"])


def contour():
    return cam().contour_of(op())[1]


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


def box(widget, name):
    return widget.findChild(QtWidgets.QWidget, "AvangardeCam" + name)


def cutting_z():
    """Z of the contour's cutting moves, without repeats."""
    moves = [c for c in op().Path.Commands if c.Name in ("G1", "G2", "G3") and "Z" in c.Parameters]
    return sorted({round(c.Parameters["Z"], 3) for c in moves})


def line_at(name, x):
    """Name of the sketch's line along Y at x (the part's coordinates)."""
    sketch = doc().getObject(name)
    for i, e in enumerate(sketch.Shape.Edges, start=1):
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if e.Curve.TypeId == "Part::GeomLine" and abs(a.x - x) < 1e-6 and abs(b.x - x) < 1e-6:
            return "Edge{}".format(i)
    raise AssertionError("no line at x={} in {}".format(x, sketch.Label))


def select_lines():
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, NAMES["island"], line_at(NAMES["island"], -5.0))
    FreeCADGui.Selection.addSelection(doc().Name, NAMES["plate"], line_at(NAMES["plate"], 20.0))


def step1():
    import Part

    mw().setGeometry(0, 0, 1920, 1080)
    V = FreeCAD.Vector
    shape = Part.makeBox(40, 20, 10, V(-20, -10, 0)).fuse(Part.makeBox(10, 10, 4, V(-15, -5, 10))).removeSplitter()
    path = os.path.join(OUT, "stepped.step")
    shape.exportStep(path)
    handlers().import_step(path)
    later(1500, step2)


@safe
def step2():
    from avangardecam import tool_library_path
    from avangardecam.engine import geometry
    from avangardecam.model import library

    body = cam().models(doc())[0]
    tops = sorted(
        ("Face{}".format(i) for i, f in enumerate(body.Shape.Faces, start=1)
         if f.findPlane() is not None and f.normalAt(0, 0).z > 0.99),
        key=lambda name: -body.Shape.getElement(name).BoundBox.ZMax,
    )  # fmt: skip
    island = geometry.extract_boundary(doc(), [body], body, tops[0])
    plate = geometry.extract_boundary(doc(), [body], body, tops[1])
    NAMES["island"], NAMES["plate"] = island.Name, plate.Name
    job = cam().find_job(doc())
    cam().set_zero(job, geometry.zero_on_face([body], body, tops[0]))
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    cam().add_tool(job, variant)
    doc().recompute()
    panel().refresh()
    select_lines()
    modal(dialog_new)
    handlers().contour_tooling()
    later(800, step3)


def dialog_new(widget):
    relative, note, depth = box(widget, "ContourRelative"), box(widget, "ContourRelativeNote"), box(widget, "ContourDepth")
    check(relative is not None and relative.isVisible(), "the window has Relative")
    check(relative.isChecked(), "Relative checked at first")
    check("each line" in note.text(), "its note: from each line ({})".format(note.text()))
    check("each line" in depth.toolTip(), "Z-Depth's tool tip: from the lines")
    relative.setChecked(False)
    check("zero point" in note.text(), "unchecked, the note: from the zero point ({})".format(note.text()))
    check("zero point" in depth.toolTip() and "zero point" in box(widget, "ContourStartZ").toolTip(), "the tool tips follow it")
    depth.setProperty("rawValue", -10.0)
    widget.grab().save(os.path.join(OUT, "01_dialog_relative.png"))
    widget.accept()


@safe
def step3():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "OK made the contour")
    NAMES["op"] = ops[0].Name
    check(not contour().relative and contour().z_depth_mm == -10.0, "unchecked, Z-Depth -10")
    check(cutting_z() == [-10.0], "the island and the plate cut at Z-10: {}".format(cutting_z()))
    panel().select_entry("operation", NAMES["op"])
    later(600, step4)


@safe
def step4():
    view = panel().view
    check(not view.relative.check.isChecked(), "details: Relative unchecked")
    check(rows().get("Lines at") == "Z 0.00, -4.00 mm", "details: Lines at {}".format(rows().get("Lines at")))
    shot("02_details_relative")
    view.relative.check.setChecked(True)  # applied at once
    check(contour().relative, "details: checked")
    check(cutting_z() == [-14.0, -10.0], "checked: 10 mm below each line: {}".format(cutting_z()))
    doc().undo()
    check(not contour().relative and cutting_z() == [-10.0], "undo: unchecked again, Z-10")
    later(400, step5)


@safe
def step5():
    check(not panel().view.relative.check.isChecked(), "details after undo: unchecked")
    select_lines()
    modal(dialog_remembered)
    handlers().contour_tooling()
    later(800, step6)


def dialog_remembered(widget):
    check(not box(widget, "ContourRelative").isChecked(), "a new contour: Relative as used last (unchecked)")
    check(box(widget, "ContourDepth").property("rawValue") == -10.0, "with the Z-Depth used last")
    widget.reject()


@safe
def step6():
    check(len(cam().operations(cam().find_job(doc()))) == 1, "Cancel made nothing")
    modal(dialog_edit)
    handlers().edit_operation(op())
    later(800, step7)


def dialog_edit(widget):
    relative = box(widget, "ContourRelative")
    check(not relative.isChecked(), "Edit...: unchecked, as the contour")
    relative.setChecked(True)
    box(widget, "ContourDepth").setProperty("rawValue", -1.0)
    widget.accept()


@safe
def step7():
    check(contour().relative and cutting_z() == [-5.0, -1.0], "Edit...: checked, -1: {}".format(cutting_z()))
    panel().select_entry("sketch", NAMES["plate"])
    later(600, step8)


@safe
def step8():
    found = rows().get("Lines at", "")
    check(found.endswith(": Z -4.00 mm"), "the plate sketch: Lines at {}".format(found))
    shot("03_sketch_details")
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
