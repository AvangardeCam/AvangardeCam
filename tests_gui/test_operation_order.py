# Operation order GUI test: three contours on the top's boundary. Real
# mouse events on the project list: pressing the first and dragging it
# below the third shows a line under the third, releasing moves it there
# (the list and the program follow, the moved one stays selected, one undo
# step); dragging the last above the first; a plain click moves nothing;
# Escape mid-drag, a drag onto the tools and a drop where it already is
# change nothing (the line gone, no undo step).
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
LOG = open(os.path.join(OUT, "test_operation_order.txt"), "w")
FAILURES = []
OPS = []
UNDO = []  # the number of undo steps before the drags that move nothing


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


def job():
    return cam().find_job(doc())


def order():
    return [op.Name for op in cam().operations(job())]


def program_order():
    return [op.label for op in cam().nc_program(doc(), "Order").setups[0].operations]


def entry_rect(kind, name):
    tree = panel().tree
    return tree.visualItemRect(panel().find_item((kind, name)))


def mouse(kind, pos, button, buttons):
    widget = panel().tree.viewport()
    pos = QtCore.QPointF(pos)
    event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button, buttons, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(widget, event)
    QtWidgets.QApplication.processEvents()


def press(pos):
    mouse(QtCore.QEvent.MouseButtonPress, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)


def move_to(start, end, steps=6):
    """The mouse with its button down from start to end, a few moves."""
    for i in range(1, steps + 1):
        pos = start + (end - start) * i / steps
        mouse(QtCore.QEvent.MouseMove, pos, QtCore.Qt.NoButton, QtCore.Qt.LeftButton)


def release(pos):
    mouse(QtCore.QEvent.MouseButtonRelease, pos, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)


def drag():
    return panel().drag


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
        OPS.append(cam().add_contour(job(), sketch, operations.Contour(depth), tc).Name)
    doc().recompute()
    later(800, step3)


@safe
def step3():
    """The first dragged below the third."""
    panel().refresh()
    QtCore.QCoreApplication.processEvents()
    first, third = entry_rect("operation", OPS[0]), entry_rect("operation", OPS[2])
    check(first.isValid() and third.isValid(), "the operations in the list")
    check(order() == OPS, "the order they were made in: " + str(order()))
    start = first.center()
    end = QtCore.QPoint(third.center().x(), third.bottom() - 2)  # the lower half of the third
    press(start)
    move_to(start, end)
    line = drag().line
    check(drag().dragging and drag().target == 3, "dragging, to the end: {}".format(drag().target))
    check(line.isVisible() and abs(line.geometry().center().y() - third.bottom()) <= 2, "the line under the third")
    check(order() == OPS, "nothing moved yet")
    shot("01_dragging")
    release(end)
    later(500, step4)


@safe
def step4():
    expected = [OPS[1], OPS[2], OPS[0]]
    check(order() == expected, "the first moved to the end: " + str(order()))
    labels = [doc().getObject(n).Label for n in expected]
    check(program_order() == labels, "the program in that order: " + str(program_order()))
    check(not drag().line.isVisible() and not drag().dragging, "the line gone")
    current = panel().current_entry()
    check(current is not None and current[1].Name == OPS[0], "the moved one selected")
    names = [i.data(0, QtCore.Qt.UserRole + 1) for i in panel()._items() if i.data(0, QtCore.Qt.UserRole) == "operation"]
    check(names == expected, "the list in that order: " + str(names))
    check(doc().UndoNames[:1] == ["Move operation"], "one undo step: " + str(doc().UndoNames[:2]))
    shot("02_moved")
    # the last (now the first one made) above the first
    last, top = entry_rect("operation", OPS[0]), entry_rect("operation", OPS[1])
    start, end = last.center(), QtCore.QPoint(top.center().x(), top.top() + 2)
    press(start)
    move_to(start, end)
    check(drag().target == 0, "to the top: {}".format(drag().target))
    release(end)
    later(500, step5)


@safe
def step5():
    check(order() == [OPS[0], OPS[1], OPS[2]], "back on top: " + str(order()))
    undo_count = len(doc().UndoNames)
    # a plain click
    rect = entry_rect("operation", OPS[1])
    press(rect.center())
    release(rect.center())
    QtCore.QCoreApplication.processEvents()
    check(order() == OPS and len(doc().UndoNames) == undo_count, "a click moves nothing")
    current = panel().current_entry()
    check(current is not None and current[1].Name == OPS[1], "the click selects it")
    # Escape mid-drag
    start, end = rect.center(), entry_rect("operation", OPS[2]).bottomLeft() + QtCore.QPoint(20, -2)
    press(start)
    move_to(start, end)
    check(drag().dragging and drag().line.isVisible(), "dragging again")
    key = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(panel().tree, key)
    check(not drag().dragging and not drag().line.isVisible(), "Escape: the drag stops")
    release(end)
    QtCore.QCoreApplication.processEvents()
    later(300, step6)


@safe
def step6():
    UNDO.append(len(doc().UndoNames))
    check(order() == OPS, "Escape moved nothing: " + str(order()))
    # onto the tools of the setup
    tool = next(i for i in panel()._items() if i.data(0, QtCore.Qt.UserRole) == "tool")
    start, end = entry_rect("operation", OPS[2]).center(), panel().tree.visualItemRect(tool).center()
    press(start)
    move_to(start, end)
    check(drag().dragging and drag().target is None and not drag().line.isVisible(), "over the tools: nowhere to go")
    check(panel().tree.viewport().cursor().shape() == QtCore.Qt.ForbiddenCursor, "the forbidden cursor")
    shot("03_over_the_tools")
    release(end)
    # where it already is: the lower half of the one before it
    start = entry_rect("operation", OPS[1]).center()
    end = QtCore.QPoint(start.x(), entry_rect("operation", OPS[0]).bottom() - 2)
    press(start)
    move_to(start, end)
    check(drag().target is None and not drag().line.isVisible(), "where it is: no line")
    release(end)
    later(400, step7)


@safe
def step7():
    check(order() == OPS and len(doc().UndoNames) == UNDO[0], "nothing moved, no undo step")
    # undo the two moves
    doc().undo()
    QtCore.QCoreApplication.processEvents()
    check(order() == [OPS[1], OPS[2], OPS[0]], "undo: the first move again: " + str(order()))
    doc().undo()
    QtCore.QCoreApplication.processEvents()
    check(order() == OPS, "undo: as made")
    later(500, step8)


@safe
def step8():
    names = [i.data(0, QtCore.Qt.UserRole + 1) for i in panel()._items() if i.data(0, QtCore.Qt.UserRole) == "operation"]
    check(names == OPS, "the list after undo: " + str(names))
    shot("04_undone")
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
