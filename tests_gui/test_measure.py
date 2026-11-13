# GUI test: CAM > Measure from 0-Point. The top face of the test model
# clicked (real mouse events in the isometric view), Shift+click adds its
# front face: the window shows the smallest and largest X, Y, Z of both
# together from the setup's zero point (as FreeCAD's exact box of the faces,
# moved by the zero point), it does not block the program and shows new
# values when clicked again; the whole model selected in the list; nothing
# selected only says so; after Rotate 0-Point 90° X and Y follow the zero
# point. Measure local (in the turned setup): the top face's sizes, a hole
# of the model (Ø4.5 through, its centre), two holes (the distance between
# their centres and between their nearest points), the front face and a hole (face to centre, to the nearest
# and the far side); its window does not block the program either.
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
LOG = open(os.path.join(OUT, "test_measure.txt"), "w")
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
    QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)  # with the measure window
    log("screenshot", path)


def layout():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def doc():
    return FreeCAD.ActiveDocument


def job():
    return cam().find_job(doc())


def body():
    return cam().models(doc())[0]


def view():
    return FreeCADGui.ActiveDocument.ActiveView


def button(key):
    ribbon = layout().ribbon
    ribbon.tabs.setCurrentIndex(1)  # CAM
    return ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_" + key)


def window():
    return mw().findChild(QtWidgets.QDialog, "AvangardeCam_MeasureDialog")


def shown():
    """{axis: (min, max, size)} as the measure window shows them."""
    w = window()
    return {axis: tuple(w.text(axis, kind) for kind in ("min", "max", "size")) for axis in "XYZ"}


def face(normal, highest=True):
    """Name of the model's flat face with this outward normal, the highest
    (or the frontmost) one."""
    from avangardecam.engine import geometry

    shape = body().Shape
    found = []
    for i, f in enumerate(shape.Faces, start=1):
        if f.findPlane() is not None and geometry.outward_normal(shape, f).getAngle(FreeCAD.Vector(*normal)) < 1e-6:
            found.append((f.CenterOfMass.dot(FreeCAD.Vector(*normal)), "Face{}".format(i)))
    return max(found)[1]


def inside(name):
    """A point inside a face of the model for a click: as near a quarter of
    its size from a corner as there is one, away from the setup's axes on the
    zero point (a click there picks the setup)."""
    f = body().Shape.getElement(name)
    b = f.BoundBox
    steps = [i / 20.0 for i in range(1, 20)]
    points = [
        FreeCAD.Vector(b.XMin + b.XLength * u, b.YMin + b.YLength * v, b.ZMin + b.ZLength * w)
        for u in steps
        for v in steps
        for w in steps
    ]
    aim = FreeCAD.Vector(b.XMin + b.XLength / 4, b.YMin + b.YLength / 4, b.ZMin + b.ZLength / 4)
    points.sort(key=lambda p: (p - aim).Length)
    return next(p for p in points if f.isInside(p, 1e-6, True))


def expected(*names):
    """{axis: (min, max, size)} of faces of the model from the zero point of
    a setup that is not turned: their exact box less the zero."""
    box = None
    for name in names:
        b = body().Shape.getElement(name).optimalBoundingBox(False, False)
        box = b if box is None else box.united(b)
    zero = cam().zero(job()).Base

    def mm(v):
        return "{:.3f}".format(round(v, 3) + 0.0)

    ranges = {"X": (box.XMin - zero.x, box.XMax - zero.x), "Y": (box.YMin - zero.y, box.YMax - zero.y), "Z": (box.ZMin - zero.z, box.ZMax - zero.z)}  # fmt: skip
    return {axis: (mm(lo), mm(hi), mm(hi - lo)) for axis, (lo, hi) in ranges.items()}


def click(point, modifiers=QtCore.Qt.NoModifier):
    """A real left click of the mouse on the 3D view at a part point."""
    widget = view().graphicsView().viewport()
    from avangardecam.ui import scene as _scene

    x, y = view().getPointOnScreen(_scene.to_view(doc(), point))  # the view is in the setup's coordinates
    pos = QtCore.QPointF(x, widget.height() - y)  # Coin counts from the bottom
    log("  click at", pos, modifiers)
    events = (
        (QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
        (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
        (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton),
    )
    for kind, button_, buttons in events:
        event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button_, buttons, modifiers)
        QtWidgets.QApplication.sendEvent(widget, event)
        QtWidgets.QApplication.processEvents()


def selected():
    return [n.split(".")[-1] for s in FreeCADGui.Selection.getSelectionEx() for n in s.SubElementNames]


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam import handlers

    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    view().viewIsometric()
    later(1500, step3)


@safe
def step3():
    global TOP, FRONT
    view().fitAll()
    QtWidgets.QApplication.processEvents()
    for key in ("cam_measure_zero", "cam_measure_local"):
        b = button(key)
        check(b is not None and b.isVisible() and b.isEnabled(), "ribbon: {} shown".format(key))
    check(cam().zero_rotation(job()) == 0.0 and cam().zero(job()).Rotation.Angle < 1e-9, "the setup is not turned")
    TOP, FRONT = face((0, 0, 1)), face((0, -1, 0))
    FreeCADGui.Selection.clearSelection()
    click(inside(TOP))
    check(selected() == [TOP], "the top face clicked: {} ({})".format(selected(), TOP))
    button("cam_measure_zero").click()
    later(500, step4)


@safe
def step4():
    check(window() is not None and window().isVisible(), "the measure window opens")
    check(not window().isModal(), "it does not block the program")
    want = expected(TOP)
    check(shown() == want, "the top face: {} (expected {})".format(shown(), want))
    check(shown()["Z"] == ("0.000", "0.000", "0.000"), "the top face is at Z0")
    check("Setup 1" in window().origin.text(), "it names the setup: {}".format(window().origin.text()))
    click(inside(FRONT), QtCore.Qt.ShiftModifier)
    check(selected() == [TOP, FRONT], "Shift+click adds the front face: {}".format(selected()))
    button("cam_measure_zero").click()
    later(500, step5)


@safe
def step5():
    want = expected(TOP, FRONT)
    check(shown() == want, "both faces together: {} (expected {})".format(shown(), want))
    check(float(shown()["Z"][0]) < 0, "the front face reaches below Z0")
    check(window().count.text() == "Selected elements: 2", window().count.text())
    shot("01_top_and_front")
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name)  # the whole model, as a click in the list
    button("cam_measure_zero").click()
    later(500, step6)


@safe
def step6():
    whole = body().Shape.optimalBoundingBox(False, False)
    zero = cam().zero(job()).Base
    check(window().count.text() == "Selected elements: 1", "the whole model: " + window().count.text())
    check(shown()["Z"][1] == "0.000", "the whole model: its top at Z0 ({})".format(shown()["Z"]))
    check(shown()["X"][2] == "{:.3f}".format(round(whole.XLength, 3)), "the whole model: its length {}".format(shown()["X"]))  # fmt: skip
    check(shown()["Z"][0] == "{:.3f}".format(round(whole.ZMin - zero.z, 3) + 0.0), "and its bottom {}".format(shown()["Z"]))  # fmt: skip
    before = shown()
    FreeCADGui.Selection.clearSelection()
    button("cam_measure_zero").click()
    message = mw().statusBar().currentMessage()
    check(message.startswith("Select faces or edges"), "nothing selected only says so: {}".format(message))
    check(shown() == before, "the window keeps the last values")
    button("cam_rotate_zero_90").click()
    later(800, step7)


@safe
def step7():
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, TOP)
    button("cam_measure_zero").click()
    later(500, step8)


@safe
def step8():
    want = expected(TOP)
    turned = shown()
    # 90° counter-clockwise: the new X is the old Y, the new Y the old -X
    check(turned["X"] == want["Y"], "after Rotate 0-Point 90° X is the old Y: {} ({})".format(turned["X"], want["Y"]))
    flipped = tuple("{:.3f}".format(-float(v) + 0.0) for v in (want["X"][1], want["X"][0])) + (want["X"][2],)
    check(turned["Y"] == flipped, "and Y the old -X: {} ({})".format(turned["Y"], flipped))
    shot("02_turned")
    window().close()
    button("cam_measure_local").click()  # the top face is still selected
    later(500, step9)


def local_window():
    return mw().findChild(QtWidgets.QDialog, "AvangardeCam_MeasureLocalDialog")


def reading():
    w = local_window()
    return w.title.text(), dict(w.rows)


def wall(x):
    """A face of the wall of the Ø4.5 hole at x (part coordinates)."""
    return next(
        "Face{}".format(i)
        for i, f in enumerate(body().Shape.Faces, start=1)
        if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - 2.25) < 1e-6 and abs(f.Surface.Center.x - x) < 1e-6
    )


def local(*names):
    FreeCADGui.Selection.clearSelection()
    for name in names:
        FreeCADGui.Selection.addSelection(doc().Name, body().Name, name)
    button("cam_measure_local").click()


@safe
def step9():
    w = local_window()
    check(w is not None and w.isVisible() and not w.isModal(), "the Measure local window opens, not modal")
    # turned 90°: the part's 40 along Y now
    want = ("<b>Flat face</b>", {"Along X": "20.000", "Along Y": "40.000", "At Z": "0.000"})
    check(reading() == want, "the top face: {}".format(reading()))
    local(wall(15))
    later(500, step10)


@safe
def step10():
    want = ("<b>Hole</b>", {"Diameter Ø": "4.500", "Centre X": "0.000", "Centre Y": "-15.000", "Centre Z": "0.000", "Depth": "12.000", "Through": "yes"})  # fmt: skip
    check(reading() == want, "a hole: {}".format(reading()))
    local(wall(15), wall(-15))
    later(500, step11)


@safe
def step11():
    title, rows = reading()
    check(title == "<b>Two holes</b>", title)
    check(rows.get("Centre distance") == "30.000" and rows.get("Between nearest points") == "25.500" and rows.get("Nearest points along Y") == "25.500" and rows.get("Nearest points along X") == "overlap" and rows.get("ΔY") == "30.000" and rows.get("ΔX") == "0.000", "two holes: {}".format(rows))  # fmt: skip
    shot("03_local_two_holes")
    local(FRONT, wall(15))
    later(500, step12)


@safe
def step12():
    want = ("<b>Face and hole</b>", {"Face to centre along X": "10.000", "Face to nearest side along X": "7.750", "Face to far side along X": "12.250", "Diameter Ø": "4.500"})  # fmt: skip
    check(reading() == want, "the front face and a hole: {}".format(reading()))
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
