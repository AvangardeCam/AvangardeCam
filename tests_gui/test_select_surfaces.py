# GUI test: Select all surfaces in the 3D view's right-click menu. A real
# right click on the view (away from the model) opens FreeCAD's menu with
# Select all surfaces first; it selects every face of the test model
# (the top face clicked before is one of them, not twice) and says how many.
# The faces count as clicked ones: Measure from 0-Point shows the whole
# model and Shift+click on a face takes it away.
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
LOG = open(os.path.join(OUT, "test_select_surfaces.txt"), "w")
FAILURES = []


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
    QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)  # with the menu
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


def view():
    return FreeCADGui.ActiveDocument.ActiveView


def viewport():
    return view().graphicsView().viewport()


def selected():
    return [(s.Object.Name, n) for s in FreeCADGui.Selection.getSelectionEx() for n in s.SubElementNames]


def top_face():
    shape = body().Shape
    tops = [(f.CenterOfMass.z, "Face{}".format(i)) for i, f in enumerate(shape.Faces, start=1) if f.findPlane() is not None]
    return max(tops)[1]


def mouse(kind, button_, buttons, pos, modifiers=QtCore.Qt.NoModifier):
    widget = viewport()
    event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button_, buttons, modifiers)
    QtWidgets.QApplication.sendEvent(widget, event)


def click_face(name, modifiers=QtCore.Qt.NoModifier):
    """A real left click of the mouse on the middle of a face of the model."""
    from avangardecam.ui import scene as _scene

    face = body().Shape.getElement(name)
    u0, u1, v0, v1 = face.ParameterRange
    point = face.valueAt(u0 + (u1 - u0) / 4, v0 + (v1 - v0) / 4)  # off the setup's axes on the zero
    x, y = view().getPointOnScreen(_scene.to_view(doc(), point))
    pos = QtCore.QPointF(x, viewport().height() - y)  # Coin counts from the bottom
    mouse(QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton, pos, modifiers)
    mouse(QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, pos, modifiers)
    mouse(QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, pos, modifiers)
    QtWidgets.QApplication.processEvents()


MENU = {}


def right_click(handle):
    """A real right click on an empty corner of the 3D view. FreeCAD's menu
    runs its own event loop: handle(menu) is called while it is open."""

    def in_menu():
        menu = QtWidgets.QApplication.activePopupWidget()
        MENU["texts"] = [a.text() for a in menu.actions()] if menu is not None else None
        try:
            handle(menu)
        finally:
            if menu is not None and menu.isVisible():
                menu.close()

    later(500, safe(in_menu))
    pos = QtCore.QPointF(40, 40)
    mouse(QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton, pos)
    mouse(QtCore.QEvent.MouseButtonPress, QtCore.Qt.RightButton, QtCore.Qt.RightButton, pos)
    mouse(QtCore.QEvent.MouseButtonRelease, QtCore.Qt.RightButton, QtCore.Qt.NoButton, pos)  # returns when the menu closes
    QtWidgets.QApplication.processEvents()


def action(menu, text):
    return next((a for a in menu.actions() if a.text() == text), None)


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    view().viewIsometric()
    view().fitAll()
    later(1500, step3)


@safe
def step3():
    global TOP
    TOP = top_face()
    FreeCADGui.Selection.clearSelection()
    click_face(TOP)
    check(selected() == [(body().Name, TOP)], "the top face clicked: {}".format(selected()))

    def take(menu):
        check(menu is not None and menu.isVisible(), "a right click on the view opens its menu")
        found = action(menu, "Select all surfaces")
        check(found is not None and found.isEnabled(), "with Select all surfaces")
        shown = [a for a in menu.actions() if a.isVisible()]
        texts = [a.text() for a in shown]
        check(texts[:3] == ["Select all surfaces", "", "Link Actions"], "first: {}".format(texts[:3]))
        check(texts.count("Select all surfaces") == 1, "once")
        shot("01_menu")
        found.trigger()

    right_click(take)
    later(500, step4)


@safe
def step4():
    count = len(body().Shape.Faces)
    want = [(body().Name, "Face{}".format(i)) for i in range(1, count + 1)]
    check(sorted(selected()) == sorted(want), "every face of the model selected: {} of {}".format(len(selected()), count))
    check(len(set(selected())) == len(selected()), "each once (the top face clicked before too)")
    message = mw().statusBar().currentMessage()
    check(message == "Selected surfaces: {}".format(count), "it says how many: {}".format(message))
    shot("02_all_surfaces")
    from avangardecam.ui import layout

    layout.LAYOUT.ribbon.tabs.setCurrentIndex(1)  # CAM
    layout.LAYOUT.ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_cam_measure_zero").click()
    later(500, step5)


@safe
def step5():
    w = mw().findChild(QtWidgets.QDialog, "AvangardeCam_MeasureDialog")
    whole = body().Shape.optimalBoundingBox(False, False)
    zero = cam().zero(job()).Base
    want = "{:.3f}".format(round(whole.XLength, 3))
    check(w is not None and w.text("X", "size") == want, "Measure from 0-Point: the whole model, X {}".format(want))
    check(w.text("Z", "max") == "0.000", "its top at Z0")
    check(w.text("Z", "min") == "{:.3f}".format(round(whole.ZMin - zero.z, 3) + 0.0), "and its bottom")
    w.close()
    global COUNT
    COUNT = len(selected())
    click_face(TOP, QtCore.Qt.ShiftModifier)
    later(300, step6)


@safe
def step6():
    count = COUNT
    check(len(selected()) == count - 1 and (body().Name, TOP) not in selected(), "Shift+click takes a face away: {} left".format(len(selected())))  # fmt: skip
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
