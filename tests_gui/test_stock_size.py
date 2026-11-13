# GUI test: Stock > Stock size... The stock's details have a button that asks
# for the block's X, Y and Z; the stock is put with the model in its middle,
# the allowances follow, one undo step; a size smaller than the model is
# refused with a message and the dialog stays open.
#
# Run like test_project.py (see README.md), with demo_bridge.step
# (40 x 20 x 12).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_stock_size.txt"), "w")
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
    QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)
    log("screenshot", path)


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def job():
    return cam().find_job(FreeCAD.ActiveDocument)


def stock_text():
    item = panel().find_item(("stock", job().Stock.Name))
    return item.text(0) if item is not None else None


def rows():
    return dict(panel().view.rows())


def size_dialog():
    return mw().findChild(QtWidgets.QDialog, "AvangardeCamStockSize")


def near(values, wanted):
    return all(abs(a - b) < 1e-6 for a, b in zip(values, wanted))


def click_item(kind, name):
    item = panel().find_item((kind, name))
    tree = panel().tree
    tree.scrollToItem(item)
    from PySide6 import QtTest

    rect = tree.visualItemRect(item)
    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center())


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    check(stock_text() == "Stock  Box 42.00 × 22.00 × 13.00 mm", "default stock: {}".format(stock_text()))
    click_item("stock", job().Stock.Name)
    later(500, step3)


@safe
def step3():
    view = panel().view
    check(type(view).__name__ == "StockView", "stock details open")
    button = view.findChild(QtWidgets.QPushButton, "AvangardeCamStockSizeButton")
    check(button is not None and button.text() == "Stock size...", "Stock size... button in the details")
    button.click()
    later(500, step4)


@safe
def step4():
    d = size_dialog()
    check(d is not None and d.isVisible(), "stock size dialog open")
    check(near(d.sizes(), (42, 22, 13)), "starts at the present size: {}".format(d.sizes()))
    for box, value in zip(d.boxes, (50.0, 30.0, 20.0)):
        box.setProperty("rawValue", value)
    shot("stock_size_01_dialog")
    d.accept()
    later(800, step5)


@safe
def step5():
    check(size_dialog() is None, "OK closes the dialog")
    bounds = cam().stock_bounds(job())
    log("  stock bounds:", bounds)
    check(near(bounds, (-25, -15, -16, 25, 15, 4)), "model in the middle of the block")
    check(stock_text() == "Stock  Box 50.00 × 30.00 × 20.00 mm", "list follows: {}".format(stock_text()))
    check(rows().get("Size") == "50.00 × 30.00 × 20.00 mm", "details follow: {}".format(rows().get("Size")))
    allowances = [float(panel().view.boxes[n].property("rawValue")) for n, _ in panel().view.ALLOWANCES]
    check(near(allowances, (5, 5, 5, 5, 4, 4)), "allowances follow: {}".format(allowances))
    shot("stock_size_02_applied")
    FreeCAD.ActiveDocument.undo()
    later(800, step6)


@safe
def step6():
    check(near(cam().stock_bounds(job()).size, (42, 22, 13)), "undo in one step")
    FreeCAD.ActiveDocument.redo()
    check(near(cam().stock_bounds(job()).size, (50, 30, 20)), "redo")
    panel().view.findChild(QtWidgets.QPushButton, "AvangardeCamStockSizeButton").click()
    later(500, step7)


MESSAGES = []


def close_message():
    box = QtWidgets.QApplication.activeModalWidget()
    if isinstance(box, QtWidgets.QMessageBox):
        MESSAGES.append(box.text())
        box.accept()


@safe
def step7():
    d = size_dialog()
    check(near(d.sizes(), (50, 30, 20)), "starts at the block typed: {}".format(d.sizes()))
    d.boxes[0].setProperty("rawValue", 30.0)
    later(500, close_message)
    d.accept()
    log("  message:", MESSAGES)
    check(MESSAGES and "smaller than the model" in MESSAGES[0], "smaller than the model refused")
    check(d.isVisible(), "the dialog stays open")
    shot("stock_size_03_refused")
    check(near(cam().stock_bounds(job()).size, (50, 30, 20)), "a refused size changes nothing")
    d.reject()
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
