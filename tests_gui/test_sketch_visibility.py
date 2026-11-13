# Sketch visibility GUI test: the top's boundary extracted and a contour
# made on it. A real right click on the sketch in the project list opens
# its menu (Hide in 3D); hidden, the sketch is not drawn, the list says
# "(hidden)", its selected lines get no direction arrows, the contour stays
# shown and in the program; saved and reopened it is still hidden; Show in
# 3D draws it again with its arrows. A right click on a model opens no menu.
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
LOG = open(os.path.join(OUT, "test_sketch_visibility.txt"), "w")
SAVED = os.path.join(OUT, "sketch_visibility.FCStd")
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


def arrows():
    from avangardecam.ui import direction

    return list(direction._State.shown)


def entry_menu(kind, name):
    """A real right click on a list entry: its menu, or None."""
    from PySide6 import QtTest

    tree = panel().tree
    item = panel().find_item((kind, name))
    tree.scrollToItem(item)
    at = tree.visualItemRect(item).center()
    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.RightButton, QtCore.Qt.NoModifier, at)
    event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, at, tree.viewport().mapToGlobal(at))
    QtWidgets.QApplication.sendEvent(tree.viewport(), event)
    menu = QtWidgets.QApplication.activePopupWidget()
    return menu if menu is not None and menu.objectName() == "AvangardeCamSketchMenu" else None


def hide_action(menu):
    return next(a for a in menu.actions() if a.objectName() == "AvangardeCamHideSketch")


def sketch_text():
    return panel().find_item(("sketch", NAMES["sketch"])).text(0)


def select_lines():
    FreeCADGui.Selection.clearSelection()
    for edge in ("Edge1", "Edge2"):
        FreeCADGui.Selection.addSelection(doc().Name, NAMES["sketch"], edge)


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    from avangardecam import tool_library_path
    from avangardecam.engine import geometry
    from avangardecam.model import library, operations

    body = cam().models(doc())[0]
    top = max(
        (f for f in body.Shape.Faces if f.findPlane() is not None and f.normalAt(0, 0).z > 0.99),
        key=lambda f: (round(f.BoundBox.ZMax, 6), f.Area),
    )
    name = "Face{}".format(next(i for i, f in enumerate(body.Shape.Faces, start=1) if f.isSame(top)))
    made = geometry.extract_boundary(doc(), [body], body, name)
    job = cam().find_job(doc())
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    NAMES["sketch"] = made.Name
    NAMES["op"] = cam().add_contour(job, made, operations.Contour(-1.0), cam().add_tool(job, variant)).Name
    doc().recompute()
    later(800, step3)


@safe
def step3():
    panel().refresh()
    check(sketch().ViewObject.Visibility and sketch_text() == sketch().Label, "the sketch shown: " + sketch_text())
    select_lines()
    later(400, step4)


@safe
def step4():
    check(len(arrows()) == 1, "its selected lines (one chain) have an arrow: {}".format(len(arrows())))
    check(entry_menu("model", cam().models(doc())[0].Name) is None, "a right click on a model opens no menu")
    menu = entry_menu("sketch", NAMES["sketch"])
    check(menu is not None and menu.isVisible(), "a right click on the sketch opens its menu")
    check(panel().current_entry() == ("sketch", sketch()), "and selects it")
    check([a.text() for a in menu.actions()] == ["Hide in 3D"], "menu: {}".format([a.text() for a in menu.actions()]))
    shot("01_sketch_menu")
    hide_action(menu).trigger()
    menu.close()
    select_lines()
    later(400, step5)


@safe
def step5():
    check(not sketch().ViewObject.Visibility, "Hide in 3D: the sketch hidden")
    check(sketch_text() == "{}  (hidden)".format(sketch().Label), "the list says hidden: " + sketch_text())
    check(arrows() == [], "no arrows on its selected lines")
    check(op().ViewObject.Visibility, "the contour on it still shown")
    nc = cam().nc_program(doc(), "Sketch")
    check([o.label for o in nc.setups[0].operations] == [op().Label], "and in the program")
    shot("02_hidden")
    FreeCADGui.Selection.clearSelection()
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(1500, step6)


@safe
def step6():
    panel().refresh()
    check(not sketch().ViewObject.Visibility, "reopened: still hidden")
    check(sketch_text().endswith("(hidden)"), "reopened: the list says hidden: " + sketch_text())
    menu = entry_menu("sketch", NAMES["sketch"])
    check(menu is not None and hide_action(menu).text() == "Show in 3D", "menu: Show in 3D")
    hide_action(menu).trigger()
    menu.close()
    select_lines()
    later(400, step7)


@safe
def step7():
    check(sketch().ViewObject.Visibility and sketch_text() == sketch().Label, "Show in 3D: shown again: " + sketch_text())
    check(len(arrows()) == 1, "its arrow again: {}".format(len(arrows())))
    shot("03_shown")
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
