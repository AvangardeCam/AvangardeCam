# GUI test: CAM > Custom stock. Custom stock on the CAM ribbon opens its
# window (the middle checked at first; OK without a file refused in the red
# line); a casting 46 x 26 x 16 drawn far away from the part is loaded with
# its middle on the model's middle (stock -23..23, -13..13, -14..2), the list
# says Blank, the details name the file and say "on the model's middle";
# undo gives the box back in one step, redo the blank. The Stock window's
# Custom stock... opens the same window: a blank turned 90° is loaded and
# a message says the model sticks out of it. A blank kept where the file
# draws it (middle unchecked): the details say how far off it is, Put in
# the middle puts it there (one undo step). A blank from an STL file is drawn
# itself, not the box around it; from a STEP file the stock is the solid.
# A blank the file draws over the part stays there with the middle checked;
# a right click on the stock: Move stock... (X+5, Z-2, one undo step), Put
# in the middle, Custom stock..., Stock...; a box's menu has no Move stock.
# Next setup has the same check box.
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
LOG = open(os.path.join(OUT, "test_custom_stock.txt"), "w")
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


def engine():
    from avangardecam.engine import next_setup

    return next_setup


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


def modal(fn, ms=600, name=None):
    """Run fn(widget) on the modal window about to open (of this objectName,
    or a message box when name is "box")."""

    def run():
        widget = QtWidgets.QApplication.activeModalWidget()
        wanted = widget is not None and (
            name is None
            or (name == "box" and isinstance(widget, QtWidgets.QMessageBox))
            or widget.objectName() == name
        )
        if not wanted:
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


def near(values, wanted, tol=1e-6):
    return all(abs(a - b) < tol for a, b in zip(values, wanted))


def casting(name, size, corner):
    import Part

    path = os.path.join(OUT, name)
    Part.makeBox(*size, FreeCAD.Vector(*corner)).exportStep(path)
    return path


def ok_button(d):
    return d.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    check(near(cam().stock_bounds(job()).size, (42, 22, 13)), "a box with allowances at first")
    b = button("cam_custom_stock")
    check(b is not None, "Custom stock on the CAM ribbon")
    modal(first_window, name="AvangardeCamCustomStockDialog")
    b.click()
    later(800, step3)


def first_window(d):
    check(d.windowTitle() == "Custom stock", "the Custom stock window opens")
    check(d.middle.isChecked(), "the middle on the model's middle checked at first")
    ok_button(d).click()
    check(d.isVisible() and "file of the blank" in d.message.text(), "OK without a file refused: " + d.message.text())
    d.file.setText(casting("casting.step", (46, 26, 16), (300, -400, 80)))
    shot("custom_stock_01_window")
    ok_button(d).click()


@safe
def step3():
    j = job()
    check(engine().kind(j) == engine().CUSTOM, "the stock is the casting")
    bounds = cam().stock_bounds(j)
    log("  stock bounds:", bounds)
    check(near(bounds, (-23, -13, -14, 23, 13, 2)), "its middle on the model's middle")
    check(stock_text() == "Stock  Blank 46.00 × 26.00 × 16.00 mm", "the list says Blank: {}".format(stock_text()))
    check(type(panel().view).__name__ == "StockView", "the stock selected, its details shown")
    r = rows()
    check(r.get("Blank") == "casting.step", "the details name the file: {}".format(r.get("Blank")))
    check(r.get("Middle") == "on the model's middle", "the details: on the middle: {}".format(r.get("Middle")))
    check(panel().view.findChild(QtWidgets.QPushButton, "AvangardeCamStockPutInMiddle") is not None, "Put in the middle in the details")
    shot("custom_stock_02_loaded")
    FreeCAD.ActiveDocument.undo()
    check(engine().kind(job()) == engine().STANDARD and near(cam().stock_bounds(job()).size, (42, 22, 13)), "undo: the box in one step")
    FreeCAD.ActiveDocument.redo()
    check(engine().kind(job()) == engine().CUSTOM and near(cam().stock_bounds(job()), (-23, -13, -14, 23, 13, 2)), "redo: the casting")
    # the Stock window's Custom stock...: a blank turned 90°
    modal(stock_window, name="AvangardeCamStockDialog")
    button("cam_stock").click()
    later(800, step4)


def stock_window(d):
    custom = d.findChild(QtWidgets.QPushButton, "AvangardeCamStockWindowCustom")
    check(custom is not None, "Custom stock... in the Stock window")
    check(any("model of the blank" in w.text() for w in d.findChildren(QtWidgets.QLabel)), "the Stock window says the stock is a blank")
    modal(turned_window, name="AvangardeCamCustomStockDialog")
    custom.click()


def turned_window(d):
    check(d.isVisible(), "the Stock window gives way to the Custom stock window")
    d.file.setText(casting("turned.step", (26, 46, 16), (0, 0, 0)))
    modal(sticks_out, name="box")
    ok_button(d).click()


def sticks_out(box):
    log("  message:", box.text())
    check("sticks out" in box.text() and "X− 7.00 mm" in box.text() and "X+ 7.00 mm" in box.text(), "the model sticks out of the turned blank")
    shot("custom_stock_03_sticks_out")
    box.done(0)


@safe
def step4():
    check(near(cam().stock_bounds(job()), (-13, -23, -14, 13, 23, 2)), "the turned blank loaded all the same")
    check(rows().get("Blank") == "turned.step", "the details follow: {}".format(rows().get("Blank")))
    # kept where the file draws it, then Put in the middle
    modal(kept_window, name="AvangardeCamCustomStockDialog")
    panel().view.findChild(QtWidgets.QPushButton, "AvangardeCamStockCustomButton").click()
    later(800, step5)


def kept_window(d):
    check(d.middle.isChecked(), "the middle still checked")
    d.middle.setChecked(False)
    box = cam().models(FreeCAD.ActiveDocument)[0].Shape.BoundBox  # the file is in the part's coordinates
    d.file.setText(casting("kept.step", (46, 26, 16), (box.XMin - 3, box.YMin - 3, box.ZMin - 3)))
    ok_button(d).click()


@safe
def step5():
    check(near(cam().stock_bounds(job()), (-23, -13, -15, 23, 13, 1)), "kept where the file draws it")
    log("  middle:", rows().get("Middle"))
    check(rows().get("Middle") == "X +0.00  Y +0.00  Z -1.00 mm off the model's", "the details say how far off: {}".format(rows().get("Middle")))
    put = panel().view.findChild(QtWidgets.QPushButton, "AvangardeCamStockPutInMiddle")
    put.click()
    check(near(cam().stock_bounds(job()), (-23, -13, -14, 23, 13, 2)), "Put in the middle")
    QtWidgets.QApplication.processEvents()
    check(rows().get("Middle") == "on the model's middle", "the details follow: {}".format(rows().get("Middle")))
    FreeCAD.ActiveDocument.undo()
    check(near(cam().stock_bounds(job()), (-23, -13, -15, 23, 13, 1)), "undo: off the middle again")
    from avangardecam import params

    check(not params().GetBool("LastBlankInMiddle", True), "unchecked remembered")
    later(300, step6)


def visible(obj):
    vo = getattr(obj, "ViewObject", None)
    return vo is not None and vo.Visibility


@safe
def step6():
    import Mesh
    import Part

    from avangardecam import handlers

    # a blank from an STL file: its mesh drawn, not the box around it
    cylinder = Part.makeCylinder(30, 16, FreeCAD.Vector(500, 500, 0))
    path = os.path.join(OUT, "cylinder.stl")
    Mesh.Mesh(cylinder.tessellate(0.05)).write(path)
    check(handlers.custom_stock(path, True), "an STL blank loaded")
    QtWidgets.QApplication.processEvents()
    src = engine().source(job())
    check(engine()._is_mesh(src) and visible(src), "the STL blank drawn itself")
    check(not visible(job().Stock), "its box not drawn")
    shot("custom_stock_05_stl")
    # a STEP blank: the Job's stock is the solid, drawn; the mesh gone
    path = os.path.join(OUT, "cylinder.step")
    cylinder.exportStep(path)
    check(handlers.custom_stock(path, True), "a STEP blank loaded")
    QtWidgets.QApplication.processEvents()
    check(visible(job().Stock) and len(job().Stock.Shape.Faces) == 3, "the STEP blank drawn as the stock (a cylinder)")
    check(not any(o.isDerivedFrom("Mesh::Feature") for o in FreeCAD.ActiveDocument.Objects), "the STL blank's mesh removed")
    shot("custom_stock_06_step")
    later(300, step7)


@safe
def step7():
    from avangardecam import handlers

    # drawn around the model by the file (1 under, 3 over): left there, the middle checked
    box = cam().models(FreeCAD.ActiveDocument)[0].Shape.BoundBox
    path = casting("over.step", (44, 24, 16), (box.XMin - 2, box.YMin - 2, box.ZMin - 1))
    check(handlers.custom_stock(path, True), "a blank drawn over the part loaded")
    check(near(cam().stock_bounds(job()), (-22, -12, -13, 22, 12, 3)), "left where the file draws it: {}".format(cam().stock_bounds(job())))
    # a right click on the stock: its menu, Move stock...
    item = panel().find_item(("stock", job().Stock.Name))
    tree = panel().tree
    tree.scrollToItem(item)
    panel()._on_menu(tree.visualItemRect(item).center())
    menu = panel().menu
    names = [a.objectName() for a in menu.actions() if a.objectName()]
    check(names == ["AvangardeCamMoveStock", "AvangardeCamStockMenuMiddle", "AvangardeCamStockMenuCustom", "AvangardeCamStockMenuWindow"], "the stock's menu: {}".format(names))
    shot("custom_stock_07_menu")
    move = next(a for a in menu.actions() if a.objectName() == "AvangardeCamMoveStock")
    menu.hide()
    modal(move_window, name="AvangardeCamMoveStockDialog")
    move.trigger()
    check(near(cam().stock_bounds(job()), (-17, -12, -15, 27, 12, 1)), "moved X+5 Z-2: {}".format(cam().stock_bounds(job())))
    FreeCAD.ActiveDocument.undo()
    check(near(cam().stock_bounds(job()), (-22, -12, -13, 22, 12, 3)), "undo: back in one step")
    # a box with allowances: no Move stock in its menu
    from avangardecam.engine import freecad_cam

    doc = FreeCAD.ActiveDocument
    doc.openTransaction("box")
    freecad_cam.set_stock(job(), freecad_cam.model_stock.BoxStock())
    doc.commitTransaction()
    later(800, step8)  # the list refreshed: the new stock in it


@safe
def step8():
    item = panel().find_item(("stock", job().Stock.Name))
    check(item is not None, "the box in the list")
    if item is None:
        finish()
        return
    panel()._on_menu(panel().tree.visualItemRect(item).center())
    names = [a.objectName() for a in panel().menu.actions() if a.objectName()]
    panel().menu.hide()
    check(names == ["AvangardeCamStockMenuCustom", "AvangardeCamStockMenuWindow"], "a box's menu: no Move stock: {}".format(names))
    # Next setup: the same check box, as last chosen
    modal(next_setup_window, name="AvangardeCamNextSetupDialog")
    button("cam_next_setup").click()
    later(800, finish)


def move_window(d):
    check(d.windowTitle() == "Move stock", "Move stock opens its window")
    for field, value in zip(d.fields, (5.0, 0.0, -2.0)):
        field.setProperty("rawValue", value)
    shot("custom_stock_08_move")
    modal(moved_out, name="box")  # 5 mm along X: the model 3 mm out of it at X−
    ok_button(d).click()


def moved_out(box):
    log("  message:", box.text())
    check("sticks out" in box.text() and "X− 3.00 mm" in box.text(), "moved too far: the message says where the model sticks out")
    box.done(0)


def next_setup_window(d):
    middle = d.findChild(QtWidgets.QCheckBox, "AvangardeCamNextSetupMiddle")
    check(middle is not None and not middle.isChecked(), "Next setup: the middle check box as last chosen")
    if middle is not None:
        middle.setChecked(True)
        check(d.custom.isChecked(), "checking it chooses Custom stock")
    shot("custom_stock_04_next_setup")
    d.reject()


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
