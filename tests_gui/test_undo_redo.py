# Undo and Redo next to File: FreeCAD's own Std_Undo / Std_Redo actions
# (disabled on an empty project), the tooltip names the step, the buttons
# and Ctrl+Z / Ctrl+Shift+Z take a stock allowance back and do it again,
# the list and the details follow; after expert mode and back they still
# work, and an empty project disables them again.
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
LOG = open(os.path.join(OUT, "test_undo_redo.txt"), "w")
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


def panel():
    return layout().panel


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def undo_button():
    return layout().ribbon.undo_button


def redo_button():
    return layout().ribbon.redo_button


def top_z():
    return cam().stock_bounds(cam().find_job(FreeCAD.ActiveDocument)).z_max


def stock_text():
    job = cam().find_job(FreeCAD.ActiveDocument)
    item = panel().find_item(("stock", job.Stock.Name))
    return item.text(0) if item is not None else None


def view_widget():
    """The GL widget of the 3D view, where the shortcuts are typed."""
    view = FreeCADGui.ActiveDocument.ActiveView
    return view.graphicsView().viewport() if hasattr(view, "graphicsView") else mw()


def press(key, modifiers):
    from PySide6 import QtTest

    mw().activateWindow()
    widget = view_widget()
    widget.setFocus()
    QtTest.QTest.keyClick(widget, key, modifiers)


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    undo, redo = undo_button(), redo_button()
    check(undo.isVisible() and redo.isVisible(), "Undo and Redo shown next to File")
    check(undo.defaultAction() is not None, "Undo is FreeCAD's Std_Undo action")
    check(redo.defaultAction() is not None, "Redo is FreeCAD's Std_Redo action")
    check(not undo.isEnabled() and not redo.isEnabled(), "empty project: both disabled")
    check(undo.tooltip() == "Undo (Ctrl+Z)", "tooltip without a step: " + undo.tooltip())
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    job = cam().find_job(FreeCAD.ActiveDocument)
    check(job is not None, "import created the CAM job")
    item = panel().find_item(("stock", job.Stock.Name))
    panel().tree.setCurrentItem(item)
    later(500, step3)


@safe
def step3():
    view = panel().view
    check(type(view).__name__ == "StockView", "stock details open")
    view.boxes["z_pos_mm"].setProperty("rawValue", 0.1)
    later(1200, step4)


@safe
def step4():
    check(abs(top_z() - 0.1) < 1e-6, "allowance applied: top Z 0.1")
    check(undo_button().isEnabled(), "Undo enabled")
    check(not redo_button().isEnabled(), "Redo disabled")
    check(undo_button().tooltip() == "Undo: Stock allowance (Ctrl+Z)", "tooltip: " + undo_button().tooltip())
    shot("01_undo_enabled")
    undo_button().click()
    later(800, step5)


@safe
def step5():
    check(abs(top_z() - 1.0) < 1e-6, "Undo button: top Z 1 again")
    check(stock_text() == "Stock  Box 42.00 × 22.00 × 13.00 mm", "list follows the undo: {}".format(stock_text()))
    check(abs(panel().view.boxes["z_pos_mm"].property("rawValue") - 1.0) < 1e-9, "details follow the undo")
    check(redo_button().isEnabled(), "Redo enabled after undo")
    redo_tip = redo_button().tooltip()
    check(redo_tip.startswith("Redo: Stock allowance ("), "Redo tooltip: " + redo_tip)
    redo_button().click()
    later(800, step6)


@safe
def step6():
    check(abs(top_z() - 0.1) < 1e-6, "Redo button: top Z 0.1 again")
    check(stock_text() == "Stock  Box 42.00 × 22.00 × 12.10 mm", "list follows the redo: {}".format(stock_text()))
    check(not redo_button().isEnabled(), "Redo disabled again")
    press(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
    later(800, step7)


@safe
def step7():
    check(abs(top_z() - 1.0) < 1e-6, "Ctrl+Z: top Z 1 again")
    press(QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier)
    later(800, step8)


@safe
def step8():
    check(abs(top_z() - 0.1) < 1e-6, "Ctrl+Shift+Z: top Z 0.1 again")
    FreeCADGui.activateWorkbench("CAMWorkbench")
    later(1000, step9)


@safe
def step9():
    FreeCADGui.activateWorkbench("AvangardeCamWorkbench")
    later(1500, step10)


@safe
def step10():
    check(undo_button().isVisible() and undo_button().isEnabled(), "back from expert mode: Undo shown, enabled")
    undo_button().click()
    later(800, step11)


@safe
def step11():
    check(abs(top_z() - 1.0) < 1e-6, "back from expert mode: Undo works")
    shot("02_after_undo")
    FreeCAD.closeDocument(FreeCAD.ActiveDocument.Name)
    FreeCAD.newDocument()
    later(1000, step12)


@safe
def step12():
    check(not undo_button().isEnabled() and not redo_button().isEnabled(), "new project: both disabled")
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
