# Stage 1 GUI test: AvangardeCam layout, STEP import, placeholders,
# File menu and the switch to FreeCAD and back.
#
# Run (see README.md):
#   AC_TEST_OUT=<dir> [AC_STEP=<file.step>] FREECAD_USER_HOME=<dir> DISPLAY=:5 \
#       FreeCAD tests_gui/test_layout.py   (default model: models/demo_bridge.step)
import os
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", "/tmp")
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_layout.txt"), "w")
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


def shot(name, whole_screen=False):
    path = os.path.join(OUT, name + ".png")
    if whole_screen:
        QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)
    else:
        mw().grab().save(path)
    log("screenshot", path)


def visible_docks():
    return sorted(d.objectName() for d in mw().findChildren(QtWidgets.QDockWidget) if d.isVisible())


def visible_toolbars():
    return sorted(t.objectName() for t in mw().findChildren(QtWidgets.QToolBar) if t.isVisible())


def layout():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT


def check_kiosk(label):
    check(FreeCADGui.activeWorkbench().name() == "AvangardeCamWorkbench", label + ": workbench active")
    check(not mw().menuBar().isVisible(), label + ": FreeCAD menu bar hidden")
    check(visible_docks() == ["AvangardeCam_Project"], label + ": only the project panel docked")
    check(visible_toolbars() == ["AvangardeCam_Ribbon"], label + ": only the ribbon toolbar")
    log("  docks:", visible_docks(), "toolbars:", visible_toolbars())
    for dock in mw().findChildren(QtWidgets.QDockWidget):
        if dock.isVisible() and dock.objectName() != "AvangardeCam_Project":
            log(
                "  visible dock:",
                dock.objectName(),
                "watched:",
                dock.property("AvangardeCamWatched"),
                "floating:",
                dock.isFloating(),
                "area:",
                mw().dockWidgetArea(dock),
                "geometry:",
                dock.geometry(),
                "action checked:",
                dock.toggleViewAction().isChecked(),
                "parent:",
                dock.parentWidget().metaObject().className(),
            )


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    check_kiosk("start")
    check(len(FreeCAD.listDocuments()) == 1, "start: an empty project is open")
    corner = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/NaviCube").GetInt("CornerNaviCube", 1)
    check(corner == 1, "start: navigation cube in the top right corner")
    later(800, step2)


@safe
def step2():
    shot("01_start")
    from avangardecam import handlers

    check(bool(STEP) and os.path.exists(STEP), "STEP test file exists: " + STEP)
    handlers.import_step(STEP)
    later(1500, step3)


@safe
def step3():
    shot("02_model")
    panel = layout().panel
    tree = panel.tree
    groups = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    # the import made the first setup, which holds the stock, tools and operations
    check(groups == ["Model", "Sketches", "Setup 1 (active)"], "list groups: {}".format(groups))
    model_group = tree.topLevelItem(0)
    models = [model_group.child(i).text(0) for i in range(model_group.childCount())]
    log("  models:", models)
    check(len(models) >= 1 and models[0] != "(none)", "imported model is listed")
    item = model_group.child(0)
    rect = tree.visualItemRect(item)
    from PySide6 import QtTest

    QtTest.QTest.mouseClick(tree.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center())
    later(500, step4)


@safe
def step4():
    panel = layout().panel
    rows = panel.view.rows()
    log("  details:", panel.view.title.text(), rows)
    check(("Size X", "40.00 mm") in rows, "details show the model size")
    sel = FreeCADGui.Selection.getSelection()
    check(len(sel) == 1, "clicking the model selects it in the 3D view")
    shot("03_details")

    ribbon = layout().ribbon
    ribbon.tabs.setCurrentIndex(1)
    facing = ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_cam_facing")
    check(facing is not None and facing.isVisible(), "CAM tab shows the Facing button")
    button = ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_cam_profile")
    check(button is not None and button.isVisible(), "CAM tab shows the Profile button")
    extract = ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_cam_extract_boundary")
    check(extract is not None and extract.isVisible(), "CAM tab shows Extract boundary edges too")
    button.click()
    later(300, step5)


@safe
def step5():
    message = mw().statusBar().currentMessage()
    check(message == "Profile: not implemented yet", "status bar: " + message)
    check(layout().panel.view.title.text() == "Profile", "details show the placeholder")
    shot("04_cam_profile")
    button = layout().ribbon.file_button
    button.menu().popup(button.mapToGlobal(QtCore.QPoint(0, button.height())))
    later(500, step6)


@safe
def step6():
    menu = layout().ribbon.file_button.menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    log("  File menu:", texts)
    shot("05_file_menu", whole_screen=True)
    menu.close()
    expert = menu.findChild(QtGui.QAction, "AvangardeCam_file_expert_mode")
    check(expert is not None, "File menu has the expert mode entry")
    expert.trigger()
    later(1500, step7)


@safe
def step7():
    check(FreeCADGui.activeWorkbench().name() == "CAMWorkbench", "expert mode: CAM workbench active")
    check(mw().menuBar().isVisible(), "expert mode: menu bar back")
    check(not layout().ribbon_toolbar.isVisible(), "expert mode: ribbon hidden")
    check("AvangardeCam_Project" not in visible_docks(), "expert mode: project panel hidden")
    check(len(visible_docks()) >= 1, "expert mode: FreeCAD panels back")
    log("  docks:", visible_docks())
    log("  toolbars:", visible_toolbars())
    shot("06_expert")
    FreeCADGui.activateWorkbench("AvangardeCamWorkbench")
    later(1500, step8)


@safe
def step8():
    check_kiosk("back")
    shot("07_back")
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
