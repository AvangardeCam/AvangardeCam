# Next setup GUI test: CAM > Next setup opens its window (Stock from the
# last setup checked at first, Medium; Cancel makes nothing; Custom without
# a file refused); a contour in Setup 1, then Next setup from Setup 1 at
# Rough: a busy window while the stock is cut, Setup 2 active with the
# stock left drawn instead of its box, its details (From, Work it out
# again), Setup 1 active shows its own box; undo takes Setup 2 and the
# stock left away in one step; Standard from the window: a box; Custom: a
# casting from a STEP the test makes, its details; another setup from
# Setup 1 with Adaptive in it, Simulate and Play on its stock.
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
LOG = open(os.path.join(OUT, "test_next_setup.txt"), "w")
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


def engine():
    from avangardecam.engine import next_setup

    return next_setup


def handlers():
    from avangardecam import handlers as h

    return h


def ui():
    from avangardecam.ui import next_setup

    return next_setup


def scene():
    from avangardecam.ui import scene as s

    return s


def doc():
    return FreeCAD.ActiveDocument


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def visible(obj):
    return bool(obj is not None and obj.ViewObject is not None and obj.ViewObject.Visibility)


def dialog():
    return next((w for w in QtWidgets.QApplication.topLevelWidgets()
                 if w.objectName() == "AvangardeCamNextSetupDialog" and w.isVisible()), None)  # fmt: skip


def with_dialog(then):
    """then(dialog) once Next setup's window is up (it is modal)."""

    def look(tries=0):
        d = dialog()
        if d is None and tries < 40:
            later(100, lambda: look(tries + 1))
            return
        safe(lambda: then(d))()

    later(300, look)


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    with_dialog(look_and_cancel)
    check(handlers().next_setup() is None, "Cancel: no setup")
    check(len(cam().setups(doc())) == 1, "still one setup")
    later(300, step3)


def look_and_cancel(d):
    check(d is not None, "Next setup opens its window")
    if d is None:
        return
    check(d.windowTitle() == "Next setup", "titled Next setup")
    check(d.from_setup.isChecked(), "Stock from ... checked at first")
    check(d.setups.currentText() == "Setup 1", "from the last setup: " + d.setups.currentText())
    check(d.accuracy.currentData() == 250 and d.accuracy.isEnabled(), "Medium at first")
    zero = d.findChild(QtWidgets.QLabel, "AvangardeCamNextSetupZero").text()
    check("Snap-0-Point" in zero and "Setup 1" in zero, "says where the zero point goes: " + zero)
    d.standard.setChecked(True)
    check(not d.accuracy.isEnabled(), "Standard: no accuracy")
    d.custom.setChecked(True)
    shot("01_window")
    later(300, lambda: refused(d))  # first: the click waits for the message
    d.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok).click()


def refused(d):
    try:
        box = QtWidgets.QApplication.activeModalWidget()
        check(isinstance(box, QtWidgets.QMessageBox) and "file of the blank" in box.text(), "Custom without a file refused")
        if isinstance(box, QtWidgets.QMessageBox):
            box.done(0)
        check(d.isVisible(), "the window stays")
    except Exception:
        log(traceback.format_exc())
        FAILURES.append("exception in refused")
    d.reject()


@safe
def step3():
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
    later(500, step4)


@safe
def step4():
    with_dialog(rough_and_ok)
    job = handlers().next_setup()
    first, = [j for j in cam().setups(doc()) if j.Label == "Setup 1"]
    check(job is not None and job.Label == "Setup 2", "Setup 2 made")
    if job is None:
        finish()
        return
    log("  undo after Next setup:", doc().UndoNames[:3])
    check(scene().active_setup(doc()) is job, "Setup 2 active")
    check(engine().kind(job) == engine().FROM_SETUP, "its stock: from Setup 1")
    check(engine().from_setup(job) is first, "worked out from Setup 1")
    check(getattr(job.Stock, engine().ACCURACY_PROPERTY) == 150, "at Rough")
    check(avangardecam.params().GetInt("LastNextSetupAccuracy", 0) == 150, "Rough remembered")
    src = engine().source(job)
    check(visible(src) and not visible(job.Stock), "the stock left drawn, not its box")
    check(not visible(first.Stock), "Setup 1's box hidden")
    check(all(visible(m) for m in cam().models(doc())), "the part shown")
    a, b = cam().stock_bounds(first), cam().stock_bounds(job)
    log("  Setup 1 stock", a, "Setup 2 stock", b)
    check(abs(a.z_max - b.z_max) < 0.5 and b.x_max - b.x_min <= a.x_max - a.x_min + 1e-6, "the zero as in Setup 1: the same place, no bigger")
    shot("02_setup2")
    panel().select_entry("stock", job.Stock.Name)
    later(500, safe(lambda: step5(job, first)))


def rough_and_ok(d):
    check(d is not None, "the window again")
    if d is None:
        return
    d.accuracy.setCurrentIndex(0)
    later(100, lambda: d.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok).click())
    later(400, look_busy)


def look_busy():
    busy = next((w for w in QtWidgets.QApplication.topLevelWidgets() if w.objectName() == "AvangardeCamBusy" and w.isVisible()), None)
    log("  busy window seen:", busy is not None, busy.labelText() if busy is not None else "")


def step5(job, first):
    view = panel().details_view() if hasattr(panel(), "details_view") else None
    tree = mw().findChildren(QtWidgets.QTreeWidget)
    rows = [i.text(0) for t in tree for i in t.findItems("Stock", QtCore.Qt.MatchStartsWith | QtCore.Qt.MatchRecursive)]
    check(any("From Setup 1" in r for r in rows), "the list names it: " + str(rows))
    texts = [w.text() for w in mw().findChildren(QtWidgets.QLabel) if w.isVisible()]
    check(any("What the program of the setup before leaves" in t for t in texts), "the details say what the stock is")
    check(mw().findChild(QtWidgets.QPushButton, "AvangardeCamStockWorkOutAgain") is not None, "Work it out again in the details")
    log("  details view", view)
    shot("03_details")
    log("  undo after the details:", doc().UndoNames[:3])
    scene().set_active_setup(first)
    src = engine().source(job)
    check(not visible(src) and visible(first.Stock), "Setup 1 active: its own box, not the stock left")
    scene().set_active_setup(job)
    name = src.Name
    check(doc().UndoNames[:1] == ["Next setup"], "one undo step: " + str(doc().UndoNames[:3]))
    FreeCADGui.runCommand("Std_Undo", 0)
    later(800, safe(lambda: step6(name)))


def step6(name):
    log("  after undo:", [j.Label for j in cam().setups(doc())], doc().UndoNames)
    check(len(cam().setups(doc())) == 1, "undo: Setup 2 gone")
    check(doc().getObject(name) is None, "and the stock left with it")
    with_dialog(standard_and_ok)
    job = handlers().next_setup()
    check(job is not None and engine().kind(job) == engine().STANDARD, "Standard: a box with allowances")
    later(300, step7)


def standard_and_ok(d):
    d.standard.setChecked(True)
    d.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok).click()


@safe
def step7():
    import Part

    box = cam().models(doc())[0].Shape.BoundBox
    path = os.path.join(OUT, "casting.step")
    Part.makeBox(box.XLength + 4, box.YLength + 4, box.ZLength + 3, FreeCAD.Vector(box.XMin - 2, box.YMin - 2, box.ZMin - 1)).exportStep(path)
    job = ui().run(doc(), cam().models(doc()), None, (ui().CUSTOM, path))
    check(job is not None and engine().kind(job) == engine().CUSTOM, "Custom: the casting")
    if job is not None:
        scene().set_active_setup(job)
        b = cam().stock_bounds(job)
        check(abs((b.x_max - b.x_min) - (box.XLength + 4)) < 1e-6, "the casting's size")
        check(visible(job.Stock), "the casting drawn")
        panel().select_entry("stock", job.Stock.Name)
        later(500, step8)
    else:
        finish()


@safe
def step8():
    texts = [w.text() for w in mw().findChildren(QtWidgets.QLabel) if w.isVisible()]
    check(any("casting.step" in t for t in texts), "the details name the casting's file")
    shot("04_casting")
    later(300, step9)


@safe
def step9():
    # Setup 1 (the contour 2 deep round the top) again, then Adaptive down
    # to Z-4 in the setup from its stock: no cuts at Z-1 and Z-2 where the
    # contour took it all, Simulate and Play start from that stock
    import time

    from avangardecam import tool_library_path
    from avangardecam.model import library, operations

    first, = [j for j in cam().setups(doc()) if j.Label == "Setup 1"]
    job = ui().run(doc(), cam().models(doc()), None, (ui().FROM_SETUP, first.Name, 150))
    check(job is not None and engine().kind(job) == engine().FROM_SETUP, "another setup from Setup 1")
    if job is None:
        finish()
        return
    scene().set_active_setup(job)
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    began = time.perf_counter()
    op = cam().add_adaptive(job, operations.Adaptive(-4.0, z_step_mm=1.0), cam().add_tool(job, variant))
    doc().recompute()
    log("  Adaptive from the stock left: {:.2f} s, {} commands".format(time.perf_counter() - began, len(op.Path.Commands)))
    levels = sorted({round(c.Parameters["Z"], 3) for c in op.Path.Commands if c.Name == "G1" and "Z" in c.Parameters})
    log("  its cut levels:", levels)
    check(op.Path.Commands and min(levels) <= -4.0 + 1e-6, "Adaptive cuts down to Z-4 in it")
    check(-1.0 not in levels and -2.0 not in levels, "but not at Z-1 and Z-2, where the contour took it all")
    check(engine().simulator_stock(job) is not None, "Simulate takes the stock left")
    handlers().simulate()
    later(3000, safe(lambda: step10(job)))


def step10(job):
    from avangardecam.ui import simulation

    window = simulation.simulator_window()
    check(window is not None, "the simulator opens on the stock left")
    shot("05_simulate_from_setup")
    if window is not None:
        window.close()
    from avangardecam.ui import playback

    try:  # not handlers().play(): its message box would wait
        playback.start(job)
    except Exception as exc:
        log("  Play:", exc)
    later(3000, step11)


@safe
def step11():
    from avangardecam.ui import playback

    play = next((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.windowTitle().startswith("Simulation - ")), None)
    check(play is not None, "Play opens on the stock left")
    shot("06_play_from_setup")
    playback.close()
    later(500, finish)


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
