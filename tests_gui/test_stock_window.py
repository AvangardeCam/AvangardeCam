# GUI test: the Stock window (CAM > Stock on the ribbon). The details of the
# stock in a window with a picture beside the fields: the size X × Y × Z puts
# the model in its middle, the allowances follow the size and the size the
# allowances, the stock changes on OK in one undo step, Cancel changes nothing,
# a size smaller than the model is refused in the window's red line.
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
LOG = open(os.path.join(OUT, "test_stock_window.txt"), "w")
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


def button(key):
    from avangardecam.ui.layout import LAYOUT

    LAYOUT.ribbon.tabs.setCurrentIndex(1)  # CAM
    return LAYOUT.ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_" + key)


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


def values(d):
    sizes = [float(b.property("rawValue")) for b in d.sizes]
    names = ("x_neg_mm", "x_pos_mm", "y_neg_mm", "y_pos_mm", "z_neg_mm", "z_pos_mm")
    allowances = [float(d.allowances[n].property("rawValue")) for n in names]
    return sizes, allowances


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


def focus(d, widget):
    widget.setFocus()
    QtWidgets.QApplication.processEvents()
    return d.pictures.shown


@safe
def step2():
    b = button("cam_stock")
    check(b is not None, "Stock on the CAM ribbon")
    modal(first_window)
    b.click()
    later(800, step3)


def first_window(d):
    check(d.objectName() == "AvangardeCamStockDialog" and d.windowTitle() == "Stock", "the Stock window opens")
    sizes, allowances = values(d)
    check(near(sizes, (42, 22, 13)), "sizes of the stock: {}".format(sizes))
    check(near(allowances, (1, 1, 1, 1, 0, 1)), "allowances as in the details: {}".format(allowances))
    check(d.summary.text() == "42.00 × 22.00 × 13.00 mm, top Z 1.00 mm, bottom Z -12.00 mm", "summary: " + d.summary.text())
    check(focus(d, d.allowances["x_neg_mm"]) == "stock_allowances.svg", "picture of the allowances")
    check(focus(d, d.sizes[1]) == "stock_size.svg", "picture of the size")
    for box, value in zip(d.sizes, (50.0, 30.0, 20.0)):
        box.setProperty("rawValue", value)
    sizes, allowances = values(d)
    check(near(allowances, (5, 5, 5, 5, 4, 4)), "the size puts the model in the middle: {}".format(allowances))
    d.allowances["z_pos_mm"].setProperty("rawValue", 6.0)
    sizes, allowances = values(d)
    check(near(sizes, (50, 30, 22)), "the size follows an allowance: {}".format(sizes))
    check(d.summary.text() == "50.00 × 30.00 × 22.00 mm, top Z 6.00 mm, bottom Z -16.00 mm", "summary follows: " + d.summary.text())
    check(near(cam().stock_bounds(job()).size, (42, 22, 13)), "nothing changes before OK")
    shot("stock_window_01")
    d.accept()


@safe
def step3():
    bounds = cam().stock_bounds(job())
    log("  stock bounds:", bounds)
    check(near(bounds, (-25, -15, -16, 25, 15, 6)), "OK: the stock as typed")
    check(stock_text() == "Stock  Box 50.00 × 30.00 × 22.00 mm", "list follows: {}".format(stock_text()))
    check(type(panel().view).__name__ == "StockView", "the stock selected, its details shown")
    check(rows().get("Size") == "50.00 × 30.00 × 22.00 mm", "details follow: {}".format(rows().get("Size")))
    FreeCAD.ActiveDocument.undo()
    check(near(cam().stock_bounds(job()).size, (42, 22, 13)), "undo in one step")
    FreeCAD.ActiveDocument.redo()
    check(near(cam().stock_bounds(job()).size, (50, 30, 22)), "redo")
    modal(refused_window)
    button("cam_stock").click()
    later(800, step4)


def refused_window(d):
    sizes, allowances = values(d)
    check(near(sizes, (50, 30, 22)) and near(allowances, (5, 5, 5, 5, 4, 6)), "opens with the stock: {} {}".format(sizes, allowances))
    d.sizes[0].setProperty("rawValue", 30.0)
    check(near(values(d)[1][:2], (5, 5)), "a size smaller than the model leaves the allowances")
    check(d.summary.text() == "—", "no summary for it: " + d.summary.text())
    d.accept()
    log("  message:", d.message.text())
    check("smaller than the model" in d.message.text(), "OK refused in the red line")
    check(d.isVisible(), "the window stays open")
    shot("stock_window_02_refused")
    d.sizes[0].setProperty("rawValue", 60.0)
    check(d.message.text() == "", "typing clears the message")
    d.reject()


@safe
def step4():
    check(near(cam().stock_bounds(job()).size, (50, 30, 22)), "Cancel changes nothing")
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
