# Contour on the part's bottom from the top GUI test: a block 40 x 20 x 12
# (made here as a STEP), the first setup from the top. The bottom's sketch
# (Extract boundary edges) faces away from the tool: its details list the
# setup from the other side, its lines at Z-12; Contour tooling opens on it
# (no "no setup" message) and cuts 1 mm below them.
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
LOG = open(os.path.join(OUT, "test_contour_from_below.txt"), "w")
FAILURES = []
NAMES = {}  # "bottom", "op": object names


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



def step1():
    import Part

    mw().setGeometry(0, 0, 1920, 1080)
    path = os.path.join(OUT, "block.step")
    Part.makeBox(40, 20, 12, FreeCAD.Vector(-20, -10, 0)).exportStep(path)
    handlers().import_step(path)
    later(1500, step2)


@safe
def step2():
    from avangardecam import tool_library_path
    from avangardecam.engine import geometry
    from avangardecam.model import library

    body = cam().models(doc())[0]
    bottom = next(
        "Face{}".format(i) for i, f in enumerate(body.Shape.Faces, start=1)
        if f.findPlane() is not None and f.normalAt(0, 0).z < -0.99
    )  # fmt: skip
    sketch = geometry.extract_boundary(doc(), [body], body, bottom)
    NAMES["bottom"] = sketch.Name
    job = cam().find_job(doc())
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    cam().add_tool(job, variant)
    doc().recompute()
    panel().refresh()
    panel().select_entry("sketch", sketch.Name)
    later(600, step3)


@safe
def step3():
    found = rows()
    check(found.get("Faces the tool") == "Z− (from the bottom)", "the sketch faces the bottom: {}".format(found.get("Faces the tool")))  # fmt: skip
    check("from the other side" in found.get("Setups", ""), "Setups: the top's setup, from the other side: {}".format(found.get("Setups")))  # fmt: skip
    check(found.get("Lines at", "").endswith(": Z -12.00 mm"), "Lines at Z-12: {}".format(found.get("Lines at")))
    shot("01_bottom_sketch")
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, NAMES["bottom"])
    modal(dialog)
    handlers().contour_tooling()
    later(800, step4)


def dialog(widget):
    check(widget.objectName() == "AvangardeCamContourDialog", "Contour tooling opens (no setup message)")
    box(widget, "ContourDepth").setProperty("rawValue", -1.0)
    widget.accept()


@safe
def step4():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "OK made the contour")
    NAMES["op"] = ops[0].Name
    check(cutting_z() == [-13.0], "1 mm below the bottom's lines: {}".format(cutting_z()))
    panel().select_entry("operation", NAMES["op"])
    later(600, step5)


@safe
def step5():
    check(rows().get("Lines at") == "Z -12.00 mm", "details: Lines at {}".format(rows().get("Lines at")))
    shot("02_bottom_contour")
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
