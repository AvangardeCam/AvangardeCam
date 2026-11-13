# GUI test: CAM > Rotate 0-Point 90°, 180° and by an angle typed in its
# window. The details show the rotation, the stock turns with the setup's
# axes, the view follows the zero point, Undo names the step and takes it
# back, the window remembers the angle.
#
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_rotate_zero.txt"), "w")
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
    mw().grab().save(path)
    log("screenshot", path)


def layout():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def scene():
    from avangardecam.ui import scene as s

    return s


def doc():
    return FreeCAD.ActiveDocument


def job():
    return cam().find_job(doc())


def rows():
    return dict(layout().panel.view.rows())


def button(key):
    ribbon = layout().ribbon
    ribbon.tabs.setCurrentIndex(1)  # CAM
    return ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_" + key)


def stock_size():
    b = cam().stock_bounds(job())
    return round(b.x_max - b.x_min, 6), round(b.y_max - b.y_min, 6)


def view_x_axis():
    """Where the view draws the part's X direction."""
    return tuple(round(c, 9) + 0.0 for c in scene().view_placement(doc()).Rotation.multVec(FreeCAD.Vector(1, 0, 0)))


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


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    global SIZE, ZERO
    SIZE = stock_size()
    ZERO = cam().zero(job()).Base
    log("  stock:", SIZE, "zero:", ZERO)
    check(cam().zero_rotation(job()) == 0.0, "a new setup is not turned")
    for key in ("cam_rotate_zero_90", "cam_rotate_zero_180", "cam_rotate_zero_angle"):
        b = button(key)
        check(b is not None and b.isVisible() and b.isEnabled(), "ribbon: {} shown".format(key))
    check(view_x_axis() == (1.0, 0.0, 0.0), "the view: the part's X to the right")
    shot("01_before")
    button("cam_rotate_zero_90").click()
    later(800, step3)


@safe
def step3():
    r = rows()
    log("  setup details:", layout().panel.view.rows())
    check(r.get("Rotation about Z") == "90°", "details: rotation {}".format(r.get("Rotation about Z")))
    check(stock_size() == (SIZE[1], SIZE[0]), "the stock turned with the axes: {}".format(stock_size()))
    check(cam().zero(job()).Base.isEqual(ZERO, 1e-9), "turned about X0 Y0, the zero point stays")
    # the new X is the part's Y: the part's X now points down the view's -Y
    check(view_x_axis() == (0.0, -1.0, 0.0), "the view follows: {}".format(view_x_axis()))
    tip = layout().ribbon.undo_button.tooltip()
    check(tip == "Undo: Rotate 0-Point (Ctrl+Z)", "Undo names the step: {}".format(tip))
    shot("02_rotated_90")
    button("cam_rotate_zero_180").click()
    later(800, step4)


@safe
def step4():
    check(rows().get("Rotation about Z") == "-90°", "180° more: {}".format(rows().get("Rotation about Z")))
    check(stock_size() == (SIZE[1], SIZE[0]), "stock still across")

    def answer(dialog):
        check(isinstance(dialog, QtWidgets.QInputDialog), "Rotate 0-Point... asks for the angle")
        check(abs(dialog.doubleValue() - 90.0) < 1e-9, "first time it offers 90°")
        dialog.setDoubleValue(30.0)
        dialog.accept()

    modal(answer)
    button("cam_rotate_zero_angle").click()
    later(800, step5)


@safe
def step5():
    check(rows().get("Rotation about Z") == "-60°", "30° more: {}".format(rows().get("Rotation about Z")))
    check(avangardecam.params().GetFloat("LastZeroRotation", 0.0) == 30.0, "the angle is remembered")
    shot("03_rotated_minus_60")
    layout().ribbon.undo_button.click()
    later(800, step6)


@safe
def step6():
    check(rows().get("Rotation about Z") == "-90°", "Undo takes the angle back: {}".format(rows().get("Rotation about Z")))
    check(stock_size() == (SIZE[1], SIZE[0]), "and the stock")

    def cancel(dialog):
        check(abs(dialog.doubleValue() - 30.0) < 1e-9, "next time it offers the last angle")
        dialog.reject()

    modal(cancel)
    button("cam_rotate_zero_angle").click()
    later(800, step7)


@safe
def step7():
    check(rows().get("Rotation about Z") == "-90°", "Cancel changes nothing")
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
