# GUI test: a dark system theme under FreeCAD's light theme. FreeCAD from
# Flatpak takes the system's palette (user 2026-11-18, Pop dark): the details
# under the project list were painted dark with dark text on them. The test
# gives Qt a dark palette and checks the details take the panel's background,
# and the grey captions read.
#
# Run (see README.md):
#   AC_TEST_OUT=<dir> FREECAD_USER_HOME=<dir> DISPLAY=:5 FreeCAD tests_gui/test_dark_system.py
import os
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", "/tmp")
STEP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_dark_system.txt"), "w")
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


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def dark_palette():
    """About what Qt takes from a dark GNOME theme."""
    p = QtGui.QPalette()
    dark, darker, light = QtGui.QColor(53, 53, 53), QtGui.QColor(42, 42, 42), QtGui.QColor(230, 230, 230)
    for role, color in (
        (QtGui.QPalette.Window, dark),
        (QtGui.QPalette.Base, darker),
        (QtGui.QPalette.AlternateBase, dark),
        (QtGui.QPalette.Button, dark),
        (QtGui.QPalette.Mid, QtGui.QColor(40, 40, 40)),
        (QtGui.QPalette.WindowText, light),
        (QtGui.QPalette.Text, light),
        (QtGui.QPalette.ButtonText, light),
    ):
        p.setColor(role, color)
    return p


def lightness(widget, x, y):
    """The lightness on the screen (the main window grabbed: a transparent
    widget grabbed alone comes out black)."""
    point = widget.mapTo(mw(), QtCore.QPoint(x, y))
    return mw().grab().toImage().pixelColor(point.x(), point.y()).lightness()


def background(widget):
    """The lightness of a widget's bottom right corner (nothing written there)."""
    return lightness(widget, widget.width() - 3, widget.height() - 3)


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    QtWidgets.QApplication.setPalette(dark_palette())
    later(800, step2)


@safe
def step2():
    p = panel()
    dock = mw().findChild(QtWidgets.QDockWidget, "AvangardeCam_Project")
    page = lightness(dock, 3, 3)  # the dock's own background, by its title
    details = background(p.scroll)
    log("  dock background lightness:", page, " details:", details)
    check(page > 128, "FreeCAD's light theme keeps the dock light")
    check(abs(details - page) < 30, "the details empty: the dock's background, not the system's dark one")
    shot("dark_system_01_empty")
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step3)


@safe
def step3():
    p = panel()
    tree = p.tree
    tree.setCurrentItem(tree.topLevelItem(0).child(0))
    later(500, step4)


@safe
def step4():
    p = panel()
    dock = mw().findChild(QtWidgets.QDockWidget, "AvangardeCam_Project")
    page = lightness(dock, 3, 3)
    details = background(p.scroll)
    log("  details of the model:", p.view.title.text(), " lightness:", details)
    check(abs(details - page) < 30, "the model's details on the dock's background")
    caption = p.findChild(QtWidgets.QLabel, "AvangardeCamDetailsCaption")
    if caption is not None:
        color = caption.palette().color(QtGui.QPalette.WindowText).name()
        check(color == "#808080", "the caption grey, not the system's mid: " + color)
    titles = mw().findChildren(QtWidgets.QLabel, "AvangardeCamGroupTitle")
    check(bool(titles), "the ribbon has group titles")
    colors = sorted({t.palette().color(QtGui.QPalette.WindowText).name() for t in titles})
    check(colors == ["#808080"], "the ribbon's group titles grey: " + str(colors))
    qss = QtWidgets.QApplication.instance().styleSheet()
    check("FreeCAD.qss" in str(mw().property("fc_currentStyleSheet")), "FreeCAD's light theme on (the runner seeds user.cfg)")
    log("  app stylesheet:", len(qss), "chars")
    text = p.view.title.palette().color(QtGui.QPalette.WindowText).lightness()
    check(abs(text - details) > 120, "the title reads on the details: text %d, background %d" % (text, details))
    shot("dark_system_02_model")
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
