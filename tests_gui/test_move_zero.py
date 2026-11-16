# GUI test: CAM > Move 0-Point beside Snap-0-Point. Its window does not block
# the 3D view: Select wall, then a real click on a face, puts the face's
# plane through the zero point (the shift along the setup's axes shown in the
# Move X / Y / Z fields, which can be typed too); a second wall keeps the
# first (a corner), a round face is refused and the button keeps waiting. The
# view shows where the zero point would be. OK moves the zero point in one
# undo step, the stock and the view follow; a face selected before the click
# on the ribbon is taken at once; Cancel and OK without a shift change nothing.
#
# A block with a hole, made as a STEP by the test (AC_STEP not used).
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_move_zero.txt"), "w")
FAILURES = []
SEEN = {}


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
    QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)  # with the window
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


def ui():
    from avangardecam.ui import move_zero

    return move_zero


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


def rows():
    return dict(layout().panel.view.rows())


def button(key):
    ribbon = layout().ribbon
    ribbon.tabs.setCurrentIndex(1)  # CAM
    return ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_" + key)


def windows():
    return [w for w in mw().findChildren(QtWidgets.QDialog, "AvangardeCamMoveZero") if w.isVisible()]


def window():
    found = windows()
    return found[0] if found else None


def part(name):
    return window().findChild(QtWidgets.QWidget, "AvangardeCamMoveZero" + name)


def shift():
    return tuple(round(float(part(axis).property("rawValue")), 6) + 0.0 for axis in "XYZ")


def zero():
    return tuple(round(c, 6) + 0.0 for c in cam().zero(job()).Base)


def face(normal):
    """The name of the flat face of the block that looks along normal."""
    from avangardecam.engine import geometry

    wanted = FreeCAD.Vector(*normal)
    shape = body().Shape
    return next(
        "Face{}".format(i) for i, f in enumerate(shape.Faces, start=1)
        if f.findPlane() is not None and geometry.outward_normal(shape, f).getAngle(wanted) < 1e-6
    )  # fmt: skip


def round_face():
    return next("Face{}".format(i) for i, f in enumerate(body().Shape.Faces, start=1) if f.findPlane() is None)


def selected():
    return [(s.Object.Name, n) for s in FreeCADGui.Selection.getSelectionEx() for n in s.SubElementNames]


def select(name):
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, name)


def mouse(kind, button_, buttons, pos):
    widget = viewport()
    event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button_, buttons, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(widget, event)


def click_face(name):
    """A real left click of the mouse on a face of the model."""
    f = body().Shape.getElement(name)
    u0, u1, v0, v1 = f.ParameterRange
    point = f.valueAt(u0 + (u1 - u0) / 4, v0 + (v1 - v0) / 4)
    x, y = view().getPointOnScreen(scene().to_view(doc(), point))
    pos = QtCore.QPointF(x, viewport().height() - y)  # Coin counts from the bottom
    mouse(QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton, pos)
    mouse(QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, pos)
    mouse(QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, pos)
    QtWidgets.QApplication.processEvents()


def undo_tip():
    return layout().ribbon.undo_button.tooltip()


@safe
def step1():
    import Part

    mw().setGeometry(0, 0, 1920, 1080)
    V = FreeCAD.Vector
    path = os.path.join(OUT, "block_with_hole.step")
    Part.makeBox(40, 20, 12, V(-20, -10, 0)).cut(Part.makeCylinder(3, 12, V(8, 0, 0))).exportStep(path)
    from avangardecam import handlers

    handlers.import_step(path)
    later(1500, step2)


@safe
def step2():
    check(zero() == (0.0, 0.0, 12.0), "the first setup: zero on the top, in the middle: {}".format(zero()))
    snap, move, turn = (button(k) for k in ("cam_snap_zero", "cam_move_zero", "cam_rotate_zero_90"))
    check(move is not None and move.isVisible() and move.isEnabled(), "ribbon: Move 0-Point shown")
    check(move.text().replace("\n", " ") == "Move 0-Point", "its text: {!r}".format(move.text()))
    check(not move.icon().isNull(), "it has an icon")
    left = [b.mapTo(layout().ribbon, QtCore.QPoint(0, 0)).x() for b in (snap, move, turn)]
    check(left[0] < left[1] < left[2], "beside Snap-0-Point, before the rotations: {}".format(left))
    check(move.height() == snap.height(), "as large as Snap-0-Point")
    SEEN["undo"] = undo_tip()
    move.click()
    later(800, step3)


@safe
def step3():
    w = window()
    check(w is not None, "Move 0-Point opens its window")
    check(not w.isModal(), "the window does not block the 3D view")
    check(w.windowTitle() == "Move 0-Point", "its title: {}".format(w.windowTitle()))
    check(shift() == (0.0, 0.0, 0.0), "no shift at first: {}".format(shift()))
    check(not part("Wall").isChecked() and part("Wall").text() == "Select wall", "Select wall, not pressed")
    check(not ui().preview_shown(job()), "nothing drawn without a shift")
    part("X").setProperty("rawValue", 5.0)
    QtWidgets.QApplication.processEvents()
    check(ui().preview_shown(job()), "a typed shift is drawn in 3D")
    part("Wall").click()
    check(part("Wall").isChecked(), "Select wall stays pressed")
    check(part("WallText").text() == "Click a flat face of the model.", "and says what to click: {}".format(part("WallText").text()))  # fmt: skip
    click_face(face((1, 0, 0)))
    later(600, step4)


@safe
def step4():
    check(shift() == (20.0, 0.0, 0.0), "a click on the right wall: X to the wall (the typed 5 replaced): {}".format(shift()))  # fmt: skip
    check(not part("Wall").isChecked(), "Select wall released")
    wanted = "{} of {}".format(face((1, 0, 0)), body().Label)
    check(part("WallText").text() == wanted, "the wall named: {}".format(part("WallText").text()))
    check(selected() == [], "the wall is not left selected: {}".format(selected()))
    check(zero() == (0.0, 0.0, 12.0), "the zero point waits for OK")
    check(ui().preview_shown(job()), "where it would be is drawn")
    shot("01_wall_picked")
    part("Z").setProperty("rawValue", -2.0)
    part("Wall").click()
    select(round_face())
    later(600, step5)


@safe
def step5():
    check("not flat" in part("WallText").text(), "a round face is refused: {}".format(part("WallText").text()))
    check(part("Wall").isChecked(), "Select wall still waits")
    check(shift() == (20.0, 0.0, -2.0), "the shift stays: {}".format(shift()))
    select(face((0, -1, 0)))
    later(600, step6)


@safe
def step6():
    check(shift() == (20.0, -10.0, -2.0), "the front wall too: a corner, the typed Z kept: {}".format(shift()))
    check(not part("Wall").isChecked(), "Select wall released again")
    SEEN["stock"] = tuple(round(c, 6) for c in cam().stock_bounds(job()))
    shot("02_corner")
    window().accept()
    later(800, step7)


@safe
def step7():
    check(window() is None, "OK closes the window")
    check(zero() == (20.0, -10.0, 10.0), "the zero point moved: {}".format(zero()))
    check(cam().zero_rotation(job()) == 0.0, "its axes stay")
    stock = tuple(round(c, 6) for c in cam().stock_bounds(job()))
    wanted = tuple(round(c - d, 6) for c, d in zip(SEEN["stock"], (20.0, -10.0, -2.0) * 2))
    check(stock == wanted, "the stock follows: {}".format(stock))
    check(not ui().preview_shown(job()), "the drawing is gone")
    r = rows()
    log("  setup details:", layout().panel.view.rows())
    check(r.get("Zero point") == "X 20.00  Y -10.00  Z 10.00 mm", "details: {}".format(r.get("Zero point")))
    check(undo_tip() == "Undo: Move 0-Point (Ctrl+Z)", "Undo names the step: {}".format(undo_tip()))
    message = mw().statusBar().currentMessage()
    check(message == "Setup 1: zero point moved X+20 Y-10 Z-2", "the status bar says it: {}".format(message))
    origin = scene().to_view(doc(), FreeCAD.Vector(20, -10, 10))
    check(origin.Length < 1e-6, "the view follows: the zero point at its origin ({})".format(origin))
    shot("03_moved")
    layout().ribbon.undo_button.click()
    later(800, step8)


@safe
def step8():
    check(zero() == (0.0, 0.0, 12.0), "Undo takes the move back in one step: {}".format(zero()))
    check(tuple(round(c, 6) for c in cam().stock_bounds(job())) == SEEN["stock"], "and the stock")
    SEEN["undo"] = undo_tip()
    select(face((0, 0, -1)))
    button("cam_move_zero").click()
    later(800, step9)


@safe
def step9():
    check(window() is not None, "the window opens with a face selected")
    check(shift() == (0.0, 0.0, -12.0), "the selected face (the bottom) is taken at once: {}".format(shift()))
    check(part("WallText").text().startswith(face((0, 0, -1)) + " of "), "and named: {}".format(part("WallText").text()))
    check(selected() == [], "not left selected")
    check(ui().preview_shown(job()), "drawn")
    window().reject()
    later(500, step10)


@safe
def step10():
    check(window() is None, "Cancel closes the window")
    check(zero() == (0.0, 0.0, 12.0), "and changes nothing")
    check(not ui().preview_shown(job()), "the drawing is gone")
    check(undo_tip() == SEEN["undo"], "no undo step: {}".format(undo_tip()))
    button("cam_move_zero").click()
    button("cam_move_zero").click()
    later(800, step11)


@safe
def step11():
    check(len(windows()) == 1, "one window at a time: {}".format(len(windows())))
    check(shift() == (0.0, 0.0, 0.0), "nothing selected: no shift")
    window().accept()
    later(500, step12)


@safe
def step12():
    check(window() is None, "OK without a shift closes the window")
    check(zero() == (0.0, 0.0, 12.0), "the zero point stays")
    check(undo_tip() == SEEN["undo"], "and makes no undo step: {}".format(undo_tip()))
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
