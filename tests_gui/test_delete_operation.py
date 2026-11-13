# Delete operation GUI test: three contours on the top's boundary, one
# hidden. A real right click on the middle one in the project list opens
# its menu with Delete last; Delete takes it and its helper objects out of
# the document and the program, the next one is selected, the status bar
# says how to bring it back, one undo step "Delete operation"; undo brings
# it back in its place with its helpers (shown, in the program), redo takes
# it away again. The Delete key (a real key press on the list) deletes the
# selected operation, the last one: the one before it is selected; the
# model, the sketch and the tool stay. The only operation left deleted:
# the setup's Operations group is selected.
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
LOG = open(os.path.join(OUT, "test_delete_operation.txt"), "w")
FAILURES = []
OPS = []
HELPERS = {}  # operation name: names of its helper objects
KEPT = {}  # "model", "sketch", "tool": names of what must stay
UNDO_BEFORE = []  # the number of undo steps before the first Delete


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


def scene():
    from avangardecam.ui import scene as s

    return s


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def doc():
    return FreeCAD.ActiveDocument


def job():
    return cam().find_job(doc())


def order():
    return [op.Name for op in cam().operations(job())]


def program_order():
    return [op.label for op in cam().nc_program(doc(), "Delete").setups[0].operations]


def labels(names):
    return [doc().getObject(n).Label for n in names]


def listed():
    return [i.data(0, QtCore.Qt.UserRole + 1) for i in panel()._items() if i.data(0, QtCore.Qt.UserRole) == "operation"]


def current():
    item = panel().tree.currentItem()
    return (item.data(0, QtCore.Qt.UserRole), item.data(0, QtCore.Qt.UserRole + 1)) if item is not None else None


def gone(names):
    return all(doc().getObject(n) is None for n in names)


def kept():
    return all(doc().getObject(n) is not None for n in KEPT.values()) and len(job().Tools.Group) == 1


def status():
    return mw().statusBar().currentMessage()


def op_menu(name):
    """A real right click on an operation in the list: its menu, or None."""
    from PySide6 import QtTest

    tree = panel().tree
    item = panel().find_item(("operation", name))
    tree.scrollToItem(item)
    at = tree.visualItemRect(item).center()
    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.RightButton, QtCore.Qt.NoModifier, at)
    event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, at, tree.viewport().mapToGlobal(at))
    QtWidgets.QApplication.sendEvent(tree.viewport(), event)
    menu = QtWidgets.QApplication.activePopupWidget()
    return menu if menu is not None and menu.objectName() == "AvangardeCamOperationMenu" else None


def delete_key_on(name):
    """A real click on an operation in the list, then the Delete key."""
    from PySide6 import QtTest

    tree = panel().tree
    item = panel().find_item(("operation", name))
    tree.scrollToItem(item)
    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, tree.visualItemRect(item).center())  # fmt: skip
    tree.setFocus()
    QtTest.QTest.keyClick(tree, QtCore.Qt.Key_Delete)


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
    sketch = geometry.extract_boundary(doc(), [body], body, name)
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    tc = cam().add_tool(job(), variant)
    for depth in (-1.0, -2.0, -3.0):
        op = cam().add_contour(job(), sketch, operations.Contour(depth), tc)
        OPS.append(op.Name)
        HELPERS[op.Name] = [h.Name for h in cam().helper_objects(op)]
    KEPT.update(model=body.Name, sketch=sketch.Name, tool=tc.Name)
    doc().recompute()
    scene().set_hidden(doc().getObject(OPS[1]), True)
    later(800, step3)


@safe
def step3():
    """Delete in the menu of the middle one (hidden)."""
    panel().refresh()
    QtCore.QCoreApplication.processEvents()
    check(listed() == OPS and order() == OPS, "three operations: " + str(listed()))
    check(all(HELPERS[n] for n in OPS), "each with its helper objects: " + str(HELPERS))
    menu = op_menu(OPS[1])
    check(menu is not None and menu.isVisible(), "a right click on an operation opens its menu")
    texts = [a.text() for a in menu.actions() if not a.isSeparator()] if menu else []
    check(texts[-1:] == ["Delete"], "Delete last in it: {}".format(texts))
    action = next(a for a in menu.actions() if a.objectName() == "AvangardeCamDeleteOperation")
    check(action.isEnabled() and action.shortcut() == QtGui.QKeySequence(QtCore.Qt.Key_Delete), "enabled, Del beside it")
    shot("01_menu")
    UNDO_BEFORE.append(len(doc().UndoNames))
    action.trigger()
    menu.close()
    later(500, step4)


@safe
def step4():
    deleted = OPS[1]
    check(doc().getObject(deleted) is None, "Delete: the operation out of the document")
    check(gone(HELPERS[deleted]), "with its helper objects")
    check(order() == [OPS[0], OPS[2]] and listed() == [OPS[0], OPS[2]], "out of the setup and the list: " + str(listed()))
    check(program_order() == labels([OPS[0], OPS[2]]), "and the program: " + str(program_order()))
    check(current() == ("operation", OPS[2]), "the next one selected: " + str(current()))
    check(kept(), "the model, the sketch and the tool stay")
    check(status().endswith("deleted. Undo brings it back."), "the status bar: " + status())
    check(doc().UndoNames[:1] == ["Delete operation"], "one undo step: " + str(doc().UndoNames[:2]))
    check(len(doc().UndoNames) == UNDO_BEFORE[0] + 1, "only one")
    shot("02_deleted")
    doc().undo()
    later(500, step5)


@safe
def step5():
    check(order() == OPS and listed() == OPS, "undo: back in its place: " + str(listed()))
    check(not gone(HELPERS[OPS[1]]) and [h.Name for h in cam().helper_objects(doc().getObject(OPS[1]))] == HELPERS[OPS[1]], "with its helpers")  # fmt: skip
    check(program_order() == labels(OPS), "in the program: " + str(program_order()))
    check(not scene().hidden(doc().getObject(OPS[1])), "shown")
    shot("03_undo")
    doc().redo()
    later(500, step6)


@safe
def step6():
    check(order() == [OPS[0], OPS[2]] and gone([OPS[1]] + HELPERS[OPS[1]]), "redo: deleted again")
    delete_key_on(OPS[2])
    later(500, step7)


@safe
def step7():
    check(order() == [OPS[0]] and gone([OPS[2]] + HELPERS[OPS[2]]), "the Delete key: the last one deleted")
    check(current() == ("operation", OPS[0]), "the one before it selected: " + str(current()))
    check(kept(), "FreeCAD's Delete did nothing more")
    check(doc().UndoNames[:1] == ["Delete operation"], "one undo step: " + str(doc().UndoNames[:2]))
    delete_key_on(OPS[0])
    later(500, step8)


@safe
def step8():
    check(order() == [] and gone([OPS[0]] + HELPERS[OPS[0]]), "the only one deleted")
    check(current() == ("group", "operations:" + job().Name), "the Operations group selected: " + str(current()))
    check(kept(), "the model, the sketch and the tool stay")
    shot("04_none_left")
    for _step in range(3):
        doc().undo()
    later(500, step9)


@safe
def step9():
    check(order() == OPS and listed() == OPS, "undo three times: all three back: " + str(listed()))
    check(program_order() == labels(OPS), "in the program: " + str(program_order()))
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
