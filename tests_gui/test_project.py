# Stage 2 GUI test: the project on real data. STEP import creates the first
# setup (CAM job), stock allowances are edited in the details, tools come
# from the shop's library, selection follows between list and 3D view,
# and the project survives saving and reopening.
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
LOG = open(os.path.join(OUT, "test_project.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "project.FCStd")


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


def shot(name, whole_screen=False):
    path = os.path.join(OUT, name + ".png")
    if whole_screen:
        QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)
    else:
        mw().grab().save(path)
    log("screenshot", path)


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def group_texts(key):
    """Texts of a group's entries; a setup's groups are keyed "tools:<Job>"."""
    item = panel().find_item(("group", key))
    if item is None:
        return None
    return [item.child(j).text(0) for j in range(item.childCount())]


def tools_texts():
    return group_texts("tools:" + cam().find_job(FreeCAD.ActiveDocument).Name)


def stock_text():
    job = cam().find_job(FreeCAD.ActiveDocument)
    item = panel().find_item(("stock", job.Stock.Name))
    return item.text(0) if item is not None else None


def click_item(kind, name):
    item = panel().find_item((kind, name))
    tree = panel().tree
    tree.scrollToItem(item)
    from PySide6 import QtTest

    rect = tree.visualItemRect(item)
    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center())


def rows():
    return dict(panel().view.rows())


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    doc = FreeCAD.ActiveDocument
    job = cam().find_job(doc)
    check(job is not None, "import created the CAM job")
    check(group_texts("model") == ["Body"], "model listed: {}".format(group_texts("model")))
    check(
        stock_text() == "Stock  Box 42.00 × 22.00 × 13.00 mm",
        "default stock listed: {}".format(stock_text()),
    )
    check(tools_texts() == ["(none)"], "no tools yet: {}".format(tools_texts()))
    shot("01_imported")
    click_item("stock", job.Stock.Name)
    later(500, step3)


@safe
def step3():
    view = panel().view
    log("  stock details:", view.rows())
    check(type(view).__name__ == "StockView", "stock details open")
    check(rows().get("Size") == "42.00 × 22.00 × 13.00 mm", "stock size shown")
    # the user's example: stock flush with the part, 0.1 mm to take off the top
    for name in ("x_neg_mm", "x_pos_mm", "y_neg_mm", "y_pos_mm"):
        view.boxes[name].setProperty("rawValue", 0.0)
    view.boxes["z_pos_mm"].setProperty("rawValue", 0.1)
    later(1200, step4)


@safe
def step4():
    job = cam().find_job(FreeCAD.ActiveDocument)
    bounds = cam().stock_bounds(job)
    log("  stock bounds:", bounds)
    # setup coordinates: zero point on top of the part, in the middle
    check(abs(bounds.z_max - 0.1) < 1e-6 and abs(bounds.x_max - 20) < 1e-6, "allowances applied")
    check(rows().get("Size") == "40.00 × 20.00 × 12.10 mm", "details follow: {}".format(rows().get("Size")))
    check(
        stock_text() == "Stock  Box 40.00 × 20.00 × 12.10 mm",
        "list follows: {}".format(stock_text()),
    )
    shot("02_stock")
    FreeCAD.ActiveDocument.undo()
    later(800, step5)


@safe
def step5():
    job = cam().find_job(FreeCAD.ActiveDocument)
    check(abs(cam().stock_bounds(job).z_max - 1) < 1e-6, "undo restores the stock in one step")
    log("  after undo:", stock_text(), rows().get("Size"))
    FreeCAD.ActiveDocument.redo()
    from avangardecam.ui.tool_library import ToolLibraryDialog

    dialog = ToolLibraryDialog(FreeCAD.ActiveDocument)
    dialog.setObjectName("TestToolLibrary")
    dialog.show()
    later(500, step6)


def dialog():
    return mw().findChild(QtWidgets.QDialog, "TestToolLibrary")


T5_ALU = "t5-aluminium-vhm-alu-frees-6mm"
T40_ALU = "t40-aluminium-nx-boor-6.8mm-alu"
T40_RVS = "t40-rvs-nx-boor-6.8mm-rvs"
T40_ST = "t40-staal-nx-boor-6.8mm-st"


def rows_with_number(d, number):
    return [r for r in range(d.table.rowCount()) if d.table.item(r, 0).text() == "T{}".format(number)]


@safe
def step6():
    d = dialog()
    log("  library:", d.path_label.text(), "message:", d.message.text())
    check(d.path_label.text().endswith("Resources/library/tools.json"), "shop library outside FreeCAD")
    check(d.table.rowCount() == 276, "276 tools listed: {}".format(d.table.rowCount()))
    check(len(rows_with_number(d, 40)) == 3, "T40 listed three times (Alu, RVS, St)")
    d.select_ids({T40_ALU, T40_RVS})
    d.add_button.click()
    check("one variant per T number" in d.message.text(), "two variants of one T refused: " + d.message.text())
    d.select_ids({T5_ALU, T40_ALU})
    shot("03_tool_library", whole_screen=True)
    check(d.add_button.isEnabled(), "Add enabled with a selection")
    d.add_button.click()
    later(800, step7)


@safe
def step7():
    d = dialog()
    log("  dialog message:", d.message.text())
    job = cam().find_job(FreeCAD.ActiveDocument)
    check([t.number for t in cam().project_tools(job)] == [5, 40], "T5 and T40 in the project")
    row = next(r for r, e in enumerate(d.shown) if e.id == T5_ALU)
    check(
        not (d.table.item(row, 0).flags() & QtCore.Qt.ItemIsSelectable),
        "the variant in the project cannot be added twice",
    )
    rvs_row = next(r for r, e in enumerate(d.shown) if e.id == T40_RVS)
    check(d.table.item(rvs_row, 1).font().italic(), "other T40 variants are marked")

    # material filter: RVS shows only RVS variants
    d.material_box.setCurrentIndex(d.material_box.findData("RVS"))
    check(
        all(d.table.item(r, 3).text() == "RVS" for r in range(d.table.rowCount())),
        "material filter RVS: {} rows".format(d.table.rowCount()),
    )
    shot("03b_filter_rvs", whole_screen=True)

    # switch the drill to the RVS variant: the project keeps one T40
    questions = []
    d.confirm_replace = lambda taken: questions.append(taken) or True
    d.select_ids({T40_RVS})
    d.add_button.click()
    check(len(questions) == 1, "replacing asks first")
    tools = cam().project_tools(job)
    t40 = next(t for t in tools if t.number == 40)
    check([t.number for t in tools] == [5, 40], "still one T40")
    check(t40.library_id == T40_RVS and t40.workpiece_material == "RVS", "T40 is now the RVS variant")
    check(abs(t40.tool.spindle_rpm - 562) < 1e-6, "RVS speed: {}".format(t40.tool.spindle_rpm))

    # saying no changes nothing
    d.confirm_replace = lambda taken: False
    d.material_box.setCurrentIndex(0)
    d.select_ids({T40_ST})
    d.add_button.click()
    check(cam().tool_with_number(job, 40).library_id == T40_RVS, "declined replace keeps RVS")

    # Ø right after the name; a click on the T or Ø header sorts, again the other way round
    header = d.table.horizontalHeader()
    check(d.table.horizontalHeaderItem(2).text() == "Ø mm", "Ø beside the name: {}".format(d.table.horizontalHeaderItem(2).text()))
    numbers = lambda: [int(d.table.item(r, 0).text()[1:]) for r in range(d.table.rowCount())]
    diameters = lambda: [float(d.table.item(r, 2).text()) for r in range(d.table.rowCount()) if d.table.item(r, 2).text()]
    header.sectionClicked.emit(0)
    check(numbers() == sorted(numbers()) and d.table.horizontalHeaderItem(0).text() == "T ▲", "T: smallest first")
    header.sectionClicked.emit(0)
    check(numbers() == sorted(numbers(), reverse=True) and d.table.horizontalHeaderItem(0).text() == "T ▼", "T again: largest first")
    header.sectionClicked.emit(2)
    check(diameters() == sorted(diameters()) and d.table.horizontalHeaderItem(2).text() == "Ø mm ▲", "Ø: smallest first")
    check(d.table.horizontalHeaderItem(0).text() == "T", "the T arrow gone")
    QtWidgets.QApplication.processEvents()
    shot("03c_sorted_by_diameter", whole_screen=True)
    header.sectionClicked.emit(2)
    check(diameters() == sorted(diameters(), reverse=True), "Ø again: largest first: {}".format(diameters()[:5]))
    before = numbers()
    header.sectionClicked.emit(1)
    check(numbers() == before, "the name header does not sort")
    d.material_box.setCurrentIndex(d.material_box.findData("RVS"))
    check(diameters() == sorted(diameters(), reverse=True), "the sorting stays with a filter")
    check(rows_with_number(d, 40) and d.shown[rows_with_number(d, 40)[0]].id == T40_RVS, "rows still match their tools")
    d.close()
    later(500, step7b)  # the list refreshes in the next event loop pass


@safe
def step7b():
    job = cam().find_job(FreeCAD.ActiveDocument)
    texts = tools_texts()
    check(texts == ["T5  VHM ALU Frees 6mm", "T40  NX Boor 6.8mm RVS"], "tools listed: {}".format(texts))
    t5 = cam().project_tools(job)[0].controller
    click_item("tool", t5.Name)
    later(500, step8)


@safe
def step8():
    r = rows()
    log("  T5 details:", panel().view.rows())
    check(r.get("Material") == "Aluminium", "T5 material")
    check(r.get("Spindle speed") == "12000 rpm", "T5 speed")
    check(r.get("Feed XY") == "1250 mm/min", "T5 feed XY")
    check(r.get("Feed Z") == "937 mm/min", "T5 feed Z")
    check(r.get("Diameter") == "6.00 mm", "T5 diameter")
    shot("04_tool")
    job = cam().find_job(FreeCAD.ActiveDocument)
    t40 = cam().project_tools(job)[1].controller
    click_item("tool", t40.Name)
    later(400, step9)


@safe
def step9():
    r = rows()
    log("  T40 details:", panel().view.rows())
    check(r.get("Material") == "RVS" and r.get("Feed XY") == "50 mm/min", "T40 RVS details")
    shot("04b_drill")
    button = panel().view.findChild(QtWidgets.QPushButton, "AvangardeCamRemoveTool")
    button.click()
    later(600, step10)


@safe
def step10():
    check(tools_texts() == ["T5  VHM ALU Frees 6mm"], "T40 removed: {}".format(tools_texts()))
    doc = FreeCAD.ActiveDocument
    body = cam().models(doc)[0]
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc.Name, body.Name, "Face1")
    later(400, step11)


@safe
def step11():
    current = panel().tree.currentItem()
    check(current is not None and current.text(0) == "Body", "3D selection shows the model in the list")
    FreeCADGui.Selection.clearSelection()
    doc = FreeCAD.ActiveDocument
    doc.saveAs(SAVED)
    FreeCAD.closeDocument(doc.Name)
    FreeCAD.openDocument(SAVED)
    later(1500, step12)


@safe
def step12():
    check(group_texts("model") == ["Body"], "reopened: model")
    check(stock_text() == "Stock  Box 40.00 × 20.00 × 12.10 mm", "reopened: stock {}".format(stock_text()))
    check(tools_texts() == ["T5  VHM ALU Frees 6mm"], "reopened: tools {}".format(tools_texts()))
    shot("05_reopened")
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
