# Simulation GUI test: CAM > Simulate opens FreeCAD's OpenGL simulator for
# the active setup (its stock, part and contour), without FreeCAD's task
# panel; the view turns, pans and zooms like AvangardeCam's (middle button,
# Shift+middle, Ctrl+middle); Play runs it; it closes and opens again;
# without operations it only says so.
#
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_simulation.txt"), "w")
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


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def handlers():
    from avangardecam import handlers as h

    return h


def simulation():
    from avangardecam.ui import simulation as s

    return s


def doc():
    return FreeCAD.ActiveDocument


def status():
    return mw().statusBar().currentMessage()


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    handlers().simulate()
    check(simulation().simulator_window() is None, "no operations: no simulator")
    check("no operation to simulate" in status(), "no operations: says so: " + status())

    from avangardecam import tool_library_path
    from avangardecam.engine import geometry
    from avangardecam.model import library, operations

    body = cam().models(doc())[0]
    job = cam().find_job(doc())
    top = max(
        (f for f in body.Shape.Faces if f.findPlane() is not None and f.normalAt(0, 0).z > 0.99),
        key=lambda f: (round(f.BoundBox.ZMax, 6), f.Area),
    )
    name = "Face{}".format(next(i for i, f in enumerate(body.Shape.Faces, start=1) if f.isSame(top)))
    sketch = geometry.extract_boundary(doc(), [body], body, name)
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    tc = cam().add_tool(job, variant)
    cam().add_contour(job, sketch, operations.Contour(-2.0), tc)
    doc().recompute()
    FreeCADGui.Selection.clearSelection()
    later(800, step3)


@safe
def step3():
    handlers().simulate()
    later(3000, step4)


@safe
def step4():
    window = simulation().simulator_window()
    check(window is not None, "the simulator window is open")
    if window is not None:
        check(window.title() == "Simulation - Setup 1", "titled after the setup: " + window.title())
        g, m = window.geometry(), mw().frameGeometry()
        log("  window", g, "main", m, "modal", window.modality())
        check(abs(g.center().x() - m.center().x()) <= 2 and abs(g.center().y() - m.center().y()) <= 2 and g.width() > 1000,
              "over the middle of the main window, large")  # fmt: skip
        shot("01_simulation")
        NAVIGATION[:] = [
            ("rotate", QtCore.Qt.NoModifier, (120, -60)),
            ("pan", QtCore.Qt.ShiftModifier, (60, 0)),
            ("zoom", QtCore.Qt.ControlModifier, (0, -40)),
        ]
        LAST[0] = grab(window)
        later(500, navigate)
    else:
        later(500, step5)


NAVIGATION = []
LAST = [None]


def grab(window):
    """The simulator's view, without its buttons."""
    g = window.geometry()
    return QtGui.QGuiApplication.primaryScreen().grabWindow(0, g.x(), g.y(), g.width(), g.height() - 120).toImage()


def block(image):
    """(x, y, pixels) of the stock and part drawn on the dark background."""
    sx = sy = n = 0
    for y in range(0, image.height(), 3):
        for x in range(0, image.width(), 3):
            c = QtGui.QColor(image.pixel(x, y))
            if c.blue() > 150 and c.red() > 100:
                sx, sy, n = sx + x, sy + y, n + 1
    return (sx / n, sy / n, n) if n else (None, None, 0)


def send(window, kind, pos, button, buttons, modifiers=QtCore.Qt.NoModifier):
    event = QtGui.QMouseEvent(kind, pos, window.mapToGlobal(pos), button, buttons, modifiers)
    QtGui.QGuiApplication.sendEvent(window, event)
    QtCore.QCoreApplication.processEvents()


@safe
def navigate():
    """A middle button drag across the middle of the view, then check what
    it did to the view."""
    window = simulation().simulator_window()
    name, modifiers, (dx, dy) = NAVIGATION.pop(0)
    middle = QtCore.Qt.MiddleButton
    start = QtCore.QPointF(window.width() / 2, window.height() / 2 - 60)
    send(window, QtCore.QEvent.MouseButtonPress, start, middle, middle, modifiers)
    for i in range(1, 11):
        send(window, QtCore.QEvent.MouseMove, start + QtCore.QPointF(dx * i / 10, dy * i / 10), QtCore.Qt.NoButton, middle, modifiers)
    send(window, QtCore.QEvent.MouseButtonRelease, start + QtCore.QPointF(dx, dy), middle, QtCore.Qt.NoButton, modifiers)

    def compare():
        image = grab(window)
        before, after = block(LAST[0]), block(image)
        log("  {}: block {} -> {}".format(name, before, after))
        check(image != LAST[0], "{}: the view changes".format(name))
        if name == "pan":
            moved = after[0] - before[0] if after[2] and before[2] else 0
            check(0.7 * dx < moved < 1.5 * dx, "pan: the part follows the cursor ({:.0f} px for {} px)".format(moved, dx))
        if name == "zoom":
            check(after[2] > before[2], "zoom: dragging up zooms in")
        LAST[0] = image
        shot("01_{}".format(name))
        later(300, navigate if NAVIGATION else play)

    later(700, safe(compare))


@safe
def play():
    window = simulation().simulator_window()
    g = window.geometry()
    # the play button, bottom left in the simulator's own controls; it
    # picks the button under the mouse while it moves
    pos = QtCore.QPointF(40, g.height() - 34)
    send(window, QtCore.QEvent.MouseMove, pos, QtCore.Qt.NoButton, QtCore.Qt.NoButton)
    send(window, QtCore.QEvent.MouseButtonPress, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
    send(window, QtCore.QEvent.MouseButtonRelease, pos, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
    later(8000, step5)


@safe
def step5():
    shot("02_simulation_later")
    window = simulation().simulator_window()
    if window is not None:
        window.close()
    later(1000, step6)


@safe
def step6():
    check(simulation().simulator_window() is None, "the simulator window closes")
    handlers().simulate()
    later(2000, step7)


@safe
def step7():
    window = simulation().simulator_window()
    check(window is not None, "the simulator opens again")
    shot("03_again")
    if window is not None:
        window.close()
    later(1000, finish)


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
