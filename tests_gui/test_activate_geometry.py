# GUI test: Activate geometry in the menu of an operation in the list (a
# real right click on it). The test model gets, made by the engine as the
# windows make them: a contour of two lines of the top's outline run
# backwards, a contour of the whole sketch, a drilling of the two holes
# picked in the model (the second first), a facing of the top and an
# adaptive clearing around the whole model. Activate geometry selects
# each one's geometry as it uses it: the contour's lines in its order with
# the arrows turned its way (a new contour from that selection follows the
# same lines the same way), the whole sketch, the holes in drilling order
# (a new drilling from them drills them in that order), the top face, and
# nothing for the adaptive clearing (made with nothing selected); the
# status bar says what was selected.
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
LOG = open(os.path.join(OUT, "test_activate_geometry.txt"), "w")
FAILURES = []
OPS = {}


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
    QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)
    log("screenshot", path)


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def doc():
    return FreeCAD.ActiveDocument


def job():
    return cam().find_job(doc())


def body():
    return cam().models(doc())[0]


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def variant(number, material):
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == number and e.workpiece_material == material)


def selected():
    return [(s.Object.Name, n) for s in FreeCADGui.Selection.getSelectionEx() for n in s.SubElementNames]


def status():
    return mw().statusBar().currentMessage()


def top_face():
    shape = body().Shape
    tops = [(f.CenterOfMass.z, "Face{}".format(i)) for i, f in enumerate(shape.Faces, start=1) if f.findPlane() is not None]
    return max(tops)[1]


def hole_walls():
    """One wall of each Ø4.5 hole of the model, left to right."""
    import Part

    walls = {}
    for i, f in enumerate(body().Shape.Faces, start=1):
        if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 2.25) < 1e-6:
            walls.setdefault(round(f.Surface.Center.x, 3), "Face{}".format(i))
    return [walls[x] for x in sorted(walls)]


def activate(op):
    """A real right click on the operation in the list, then Activate geometry."""
    from PySide6 import QtTest

    tree = panel().tree
    item = panel().find_item(("operation", op.Name))
    tree.scrollToItem(item)
    at = tree.visualItemRect(item).center()
    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.RightButton, QtCore.Qt.NoModifier, at)
    event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, at, tree.viewport().mapToGlobal(at))
    QtWidgets.QApplication.sendEvent(tree.viewport(), event)
    menu = QtWidgets.QApplication.activePopupWidget()
    texts = [a.text() for a in menu.actions()] if menu is not None else None
    found = next((a for a in menu.actions() if a.objectName() == "AvangardeCamActivateGeometry"), None) if menu else None
    check(found is not None and found.isEnabled(), "{}: its menu has Activate geometry ({})".format(op.Label, texts))
    if found is None:
        return
    if op is OPS["contour"]:
        shot("01_menu")
    found.trigger()
    menu.close()
    QtWidgets.QApplication.processEvents()


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    from avangardecam.engine import facing as engine_facing
    from avangardecam.engine import geometry
    from avangardecam.model import facing, operations

    global SKETCH, LINES, HOLES, TOP
    FreeCADGui.ActiveDocument.ActiveView.viewIsometric()
    TOP = top_face()
    SKETCH = geometry.extract_boundary(doc(), [body()], body(), TOP)
    loop = geometry.line_loop(SKETCH, next(n for n in geometry.all_lines(SKETCH) if SKETCH.Shape.getElement(n).Curve.TypeId == "Part::GeomLine"))  # fmt: skip
    LINES = [loop[1], loop[0]]  # two lines of the outline, clicked against the loop's way
    HOLES = hole_walls()
    check(len(HOLES) == 2, "the model's two holes: {}".format(HOLES))
    # each tool just before its operation: FreeCAD asks which tool to use when a setup
    # with no operation has several
    mill = cam().add_tool(job(), variant(21, "RVS"))
    doc().openTransaction("ops")
    OPS["contour"] = cam().add_contour(job(), SKETCH, operations.Contour(-1.0), mill, LINES, set(LINES))
    drill, t5 = cam().add_tool(job(), variant(47, "Aluminium")), cam().add_tool(job(), variant(5, "Aluminium"))
    OPS["all"] = cam().add_contour(job(), SKETCH, operations.Contour(-1.0), mill)
    OPS["drilling"] = cam().add_model_drilling(job(), body(), operations.Drilling(None), drill, list(reversed(HOLES)))
    OPS["facing"] = engine_facing.add_facing(job(), facing.Facing(), t5, body(), [TOP])
    OPS["adaptive"] = cam().add_adaptive(job(), operations.Adaptive(-3.0), t5)
    doc().commitTransaction()
    doc().recompute()
    panel().refresh()
    FreeCADGui.Selection.clearSelection()
    log("lines", LINES, "the contour runs", cam().contour_lines(OPS["contour"]))
    later(1000, step3)


@safe
def step3():
    from avangardecam.ui import direction, picking

    op = OPS["contour"]
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, TOP)  # something else selected before
    activate(op)
    check(selected() == [(SKETCH.Name, n) for n in LINES], "the contour's lines in click order: {}".format(selected()))
    check(direction.backwards(SKETCH) == set(LINES), "its arrows turned its way: {}".format(direction.backwards(SKETCH)))
    check(status() == "{}: 2 lines selected.".format(op.Label), "status: " + status())
    # Contour tooling from this selection follows the same lines the same way
    sketch, lines = picking.selected_lines()
    again = cam().add_contour(job(), sketch, cam().contour_of(op)[1], op.ToolController, lines, direction.backwards(sketch))
    check(cam().contour_lines(again) == cam().contour_lines(op), "a new contour runs as it: {}".format(cam().contour_lines(again)))
    doc().recompute()
    cam().remove_operation(again)
    panel().refresh()
    later(500, step4)


@safe
def step4():
    QtWidgets.QApplication.processEvents()
    shot("02_contour_selected")
    from avangardecam.ui import direction

    activate(OPS["all"])
    check(selected() == [(SKETCH.Name, "")] or [s.Object for s in FreeCADGui.Selection.getSelectionEx()] == [SKETCH], "a contour of all lines: the whole sketch ({})".format(selected()))  # fmt: skip
    check(not direction.backwards(SKETCH), "its arrows not turned (they were for the contour before)")
    check(status() == "{}: the whole sketch selected.".format(OPS["all"].Label), "status: " + status())
    activate(OPS["drilling"])
    want = [(body().Name, h) for h in reversed(HOLES)]
    check(selected() == want, "the drilling's holes in drilling order: {}".format(selected()))
    check(status() == "{}: 2 holes selected.".format(OPS["drilling"].Label), "status: " + status())
    from avangardecam.model import operations

    names = [n for _o, n in selected()]
    again = cam().add_model_drilling(job(), body(), operations.Drilling(None), OPS["drilling"].ToolController, names)
    doc().recompute()
    same = [(round(t.x, 3), round(t.y, 3)) for t in cam().drill_targets(again)] == [(round(t.x, 3), round(t.y, 3)) for t in cam().drill_targets(OPS["drilling"])]  # fmt: skip
    check(same, "a new drilling from them drills them in that order")
    cam().remove_operation(again)
    panel().refresh()
    later(500, step5)


@safe
def step5():
    activate(OPS["facing"])
    check(selected() == [(body().Name, TOP)], "the facing's top face: {}".format(selected()))
    check(status() == "{}: 1 face selected.".format(OPS["facing"].Label), "status: " + status())
    activate(OPS["adaptive"])
    check(selected() == [], "the adaptive clearing around the whole model: nothing selected ({})".format(selected()))
    check(status() == "{}: the whole model, nothing to select.".format(OPS["adaptive"].Label), "status: " + status())
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
