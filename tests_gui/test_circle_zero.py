# GUI test: Move 0-Point > Select circle. A tube along Y, hollow inside, as
# the test part of a horizontal borer: its bore and the holes in its end are
# drilled with the head turned 90°. Select circle, then a real click on the
# round edge of the bore, puts the zero point in the middle of the circle;
# without 5 axes the window says the axis is not along Z, and ticking 5 axes
# then turns Z out of the end of the tube ("Z out of the model"). A flat face
# is refused and the button keeps waiting; Select wall and Select circle are
# not pressed together. A real click deep in the bore (on its wall or the
# far edge where it opens into the hollow) still gives its mouth on the end.
# OK moves and turns the zero point in one undo step; the holes in the end
# can then be drilled. 5 axes stays ticked for the next window; a hole's
# wall selected before it opens is taken at once, at the hole's mouth.
#
# The tube is made as a STEP by the test (AC_STEP not used).
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_circle_zero.txt"), "w")
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


def turn():
    return tuple(round(window().turn()[i], 6) + 0.0 for i in range(3))


def text():
    return part("WallText").text()


def zero():
    return tuple(round(c, 6) + 0.0 for c in cam().zero(job()).Base)


def tool_axis():
    from avangardecam.engine import geometry

    return tuple(round(c, 6) + 0.0 for c in geometry.tool_axis(cam().zero(job())))


def edge(radius, centre):
    """The name of the round edge of radius about centre."""
    for i, e in enumerate(body().Shape.Edges, start=1):
        c = e.Curve
        if type(c).__name__ == "Circle" and abs(c.Radius - radius) < 1e-6 and (c.Center - FreeCAD.Vector(*centre)).Length < 1e-6:  # fmt: skip
            return "Edge{}".format(i)
    raise AssertionError("no edge R{} about {}".format(radius, centre))


def wall(radius, at, beside=None):
    """The name of the cylinder face of radius whose axis goes through at
    (of several, the one within its radius of the point beside)."""
    import Part

    point = FreeCAD.Vector(*at)
    found = []
    for i, f in enumerate(body().Shape.Faces, start=1):
        s = f.Surface
        if type(s).__name__ == "Cylinder" and abs(s.Radius - radius) < 1e-6:
            off = point - s.Center
            if (off - s.Axis * off.dot(s.Axis)).Length < 1e-6:
                found.append((i, f))
    if beside is not None:
        found = [(i, f) for i, f in found if f.distToShape(Part.Vertex(FreeCAD.Vector(*beside)))[0] < radius + 1e-6]
    if len(found) != 1:
        raise AssertionError("{} walls R{} through {}".format(len(found), radius, at))
    return "Face{}".format(found[0][0])


def seen_on(name):
    """A point inside the face name of the model that the view shows (not
    hidden, away from its edges), else None."""
    f = body().Shape.getElement(name)
    u0, u1, v0, v1 = f.ParameterRange
    for i in range(1, 12):
        for j in range(2, 7):
            point = f.valueAt(u0 + (u1 - u0) * i / 12.0, v0 + (v1 - v0) * j / 8.0)
            x, y = view().getPointOnScreen(scene().to_view(doc(), point))
            info = view().getObjectInfo((int(round(x)), int(round(y))))
            if not info or not info.get("Component", "").split(".")[-1].startswith("Face"):
                continue
            element = cam().model_element(doc().getObject(info["Object"]), info["Component"])
            if element is not None and element[1] == name:
                return point
    return None


def selected():
    return [(s.Object.Name, n) for s in FreeCADGui.Selection.getSelectionEx() for n in s.SubElementNames]


def mouse(kind, button_, buttons, pos):
    widget = viewport()
    event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button_, buttons, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(widget, event)


def click_at(point):
    """A real left click of the mouse on a point of the part (part coordinates)."""
    x, y = view().getPointOnScreen(scene().to_view(doc(), FreeCAD.Vector(*point)))
    pos = QtCore.QPointF(x, viewport().height() - y)  # Coin counts from the bottom
    mouse(QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton, pos)
    mouse(QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, pos)
    mouse(QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, pos)
    QtWidgets.QApplication.processEvents()


# a point on the round edge of the bore at the end Y-100, and one on the flat end
ON_BORE_EDGE = (14.142136, -100.0, 14.142136)
ON_THE_END = (19.0919, -100.0, -19.0919)


def undo_tip():
    return layout().ribbon.undo_button.tooltip()


@safe
def step1():
    import Part

    mw().setGeometry(0, 0, 1920, 1080)
    V = FreeCAD.Vector
    tube = Part.makeCylinder(50, 200, V(0, -100, 0), V(0, 1, 0))
    tube = tube.cut(Part.makeCylinder(35, 140, V(0, -70, 0), V(0, 1, 0)))  # hollow inside
    tube = tube.cut(Part.makeCylinder(20, 202, V(0, -101, 0), V(0, 1, 0)))
    for x, z in ((35, 0), (0, 35), (-35, 0), (0, -35)):
        tube = tube.cut(Part.makeCylinder(5, 16, V(x, -101, z), V(0, 1, 0)))
    path = os.path.join(OUT, "tube_with_holes.step")
    tube.removeSplitter().exportStep(path)
    from avangardecam import handlers

    handlers.import_step(path)
    later(1500, step2)


@safe
def step2():
    check(zero() == (0.0, 0.0, 50.0), "the first setup: zero on the top, in the middle: {}".format(zero()))
    # looking at the end Y-100, a little from the side: the bore's wall is seen
    view().setViewDirection(FreeCAD.Vector(0.35, 1, -0.3))
    view().fitAll()
    SEEN["undo"] = undo_tip()
    button("cam_move_zero").click()
    later(800, step3)


@safe
def step3():
    w = window()
    check(w is not None, "Move 0-Point opens its window")
    log("  the view looks along", tuple(round(c, 3) for c in view().getViewDirection()))
    circle = part("Circle")
    check(circle is not None and circle.isVisible(), "Select circle is in it")
    check(circle.text() == "Select circle" and not circle.isChecked(), "Select circle, not pressed")
    check(not circle.toolTip() == "", "with a tip")
    check(part("ZOut").text() == "Z out of the model", "the tick box: {!r}".format(part("ZOut").text()))
    check(not part("5X").isChecked(), "5 axes not ticked")
    circle.click()
    check(circle.isChecked(), "Select circle stays pressed")
    wanted = "Click a round edge of the model, or the wall of a round hole or pin."
    check(text() == wanted, "and says what to click: {}".format(text()))
    part("Wall").click()
    check(part("Wall").isChecked() and not circle.isChecked(), "Select wall releases Select circle")
    circle.click()
    check(circle.isChecked() and not part("Wall").isChecked(), "and the other way round")
    click_at(ON_BORE_EDGE)
    later(600, step4)


@safe
def step4():
    bore = edge(20, (0, -100, 0))
    check(shift() == (0.0, -100.0, -50.0), "the middle of the bore's end, along the setup's axes: {}".format(shift()))
    check(turn() == (0.0, 0.0, 0.0), "no turn without 5 axes")
    check(not part("Circle").isChecked(), "Select circle released")
    check(text().startswith("{} of {}: the middle of Ø40".format(bore, body().Label)), "the circle named: {}".format(text()))  # fmt: skip
    check("tick 5 axes" in text(), "its axis is not along Z: the window says so")
    check(selected() == [], "the circle is not left selected: {}".format(selected()))
    check(zero() == (0.0, 0.0, 50.0), "the zero point waits for OK")
    check(ui().preview_shown(job()), "where it would be is drawn")
    shot("01_circle_no_5_axes")
    part("5X").setChecked(True)
    QtWidgets.QApplication.processEvents()
    check(turn() == (90.0, 0.0, 0.0), "5 axes ticked after the pick: Z turns out of the end then: {}".format(turn()))
    check("tick 5 axes" not in text(), "and the word of 5 axes is gone: {}".format(text()))
    part("5X").setChecked(False)
    part("5X").setChecked(True)
    check(turn() == (90.0, 0.0, 0.0), "again the same")
    part("Circle").click()
    click_at(ON_THE_END)
    later(600, step5)


@safe
def step5():
    check("is not round" in text(), "a flat face is refused: {}".format(text()))
    check(part("Circle").isChecked(), "Select circle still waits")
    check(shift() == (0.0, -100.0, -50.0), "the shift stays: {}".format(shift()))
    FreeCADGui.Selection.clearSelection()
    part("X").setProperty("rawValue", 7.0)
    part("TurnX").setValue(0.0)
    later(300, step5b)


@safe
def step5b():
    point = seen_on(wall(20, (0, 0, 0), beside=(0, -85, 0)))
    check(point is not None, "the bore's wall is seen: {}".format(point))
    SEEN["deep"] = point
    click_at(tuple(point))
    later(600, step6)


@safe
def step6():
    log("  clicked the bore's wall at", tuple(round(c, 2) for c in SEEN["deep"]), "->", text())
    check(shift() == (0.0, -100.0, -50.0), "a click deep in the bore: its mouth on the end: {}".format(shift()))
    check(turn() == (90.0, 0.0, 0.0), "with 5 axes Z turns out of the end of the tube: {}".format(turn()))
    check("Ø40" in text() and "tick 5 axes" not in text(), "named, no word of 5 axes: {}".format(text()))
    check(ui().preview_shown(job()), "drawn")
    shot("02_circle_5_axes")
    part("Circle").click()
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, edge(20, (0, -70, 0)))
    later(600, step6b)


@safe
def step6b():
    check(text().startswith(edge(20, (0, -70, 0)) + " of "), "the far edge where the bore opens into the hollow: {}".format(text()))  # fmt: skip
    check(shift() == (0.0, -100.0, -50.0), "still the mouth on the end: {}".format(shift()))
    check(turn() == (90.0, 0.0, 0.0), "Z out of the end, not into the hollow: {}".format(turn()))
    window().accept()
    later(800, step7)


@safe
def step7():
    check(window() is None, "OK closes the window")
    check(zero() == (0.0, -100.0, 0.0), "the zero point in the middle of the bore's end: {}".format(zero()))
    check(tool_axis() == (0.0, -1.0, 0.0), "the tool stands out of the end: {}".format(tool_axis()))
    check(undo_tip() == "Undo: Move 0-Point (Ctrl+Z)", "one undo step: {}".format(undo_tip()))
    message = mw().statusBar().currentMessage()
    check(message == "Setup 1: zero point moved X+0 Y-100 Z-50, turned X+90 Y+0 Z+0", "the status bar: {}".format(message))  # fmt: skip
    holes = cam().model_holes(job(), body(), [wall(5, (0, 0, 35)), wall(20, (0, 0, 0), beside=(0, -85, 0))])
    check(len(holes) == 2, "the holes in the end and the bore can be drilled from it")
    check(round(holes[0].depth.depth_mm, 6) == -15.0, "the hole 15 deep: {}".format(holes[0].depth))
    shot("03_moved")
    # a hole's wall selected (clicked by its floor) before the window opens
    hole = wall(5, (35, 0, 0))
    near = scene().to_view(doc(), FreeCAD.Vector(30, -86, 0))
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, hole, near.x, near.y, near.z)
    SEEN["undo"] = undo_tip()
    button("cam_move_zero").click()
    later(800, step8)


@safe
def step8():
    check(window() is not None, "the window opens with the hole's wall selected")
    check(part("5X").isChecked() and part("Turn").isVisible(), "5 axes is still ticked")
    check(part("ZOut").isChecked(), "and Z out of the model")
    check(shift() == (35.0, 0.0, 0.0), "taken at once: its mouth, from the turned zero point: {}".format(shift()))
    check(turn() == (0.0, 0.0, 0.0), "the tool stands along it already: {}".format(turn()))
    check(text().startswith(wall(5, (35, 0, 0)) + " of ") and "Ø10" in text(), "named: {}".format(text()))
    check(selected() == [], "not left selected")
    part("5X").setChecked(False)
    window().reject()
    later(500, step9)


@safe
def step9():
    check(window() is None, "Cancel closes the window")
    check(zero() == (0.0, -100.0, 0.0), "and changes nothing")
    check(undo_tip() == SEEN["undo"], "no undo step: {}".format(undo_tip()))
    button("cam_move_zero").click()
    later(800, step9b)


@safe
def step9b():
    check(not part("5X").isChecked() and not part("Turn").isVisible(), "5 axes unticked is kept too")
    window().reject()
    layout().ribbon.undo_button.click()
    later(800, step10)


@safe
def step10():
    check(zero() == (0.0, 0.0, 50.0), "Undo takes the move and the turn back: {}".format(zero()))
    check(tool_axis() == (0.0, 0.0, 1.0), "the tool stands up again: {}".format(tool_axis()))
    finish()


def finish():
    log("FAILURES:", len(FAILURES))
    for line in FAILURES:
        log("  ", line)
    log("done")
    LOG.close()
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)
    QtCore.QTimer.singleShot(200, mw().close)


# start as on a new profile: no values remembered from earlier work
avangardecam.forget_last_values()
later(4000, step1)
