# Verify GUI test: CAM > Verify without operations only says so; with a
# contour it opens its window and waits for the accuracy (Medium at first)
# and Start; then it cuts the stock in the background, reports and shows
# the stock left in colours instead of the part (the report: also threads
# without their hole); Export saves it (.ply, .stl); Rough and Start cut
# once more (remembered); closing the window gives the part back.
#
# Run like test_layout.py (see README.md).
import os
import tempfile
import time
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_verify.txt"), "w")
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


def ui():
    from avangardecam.ui import verify

    return verify


def doc():
    return FreeCAD.ActiveDocument


def status():
    return mw().statusBar().currentMessage()


def model_visible():
    return all(m.ViewObject.Visibility for m in cam().models(doc()))


def when_done(then, started=None):
    """then() once the window's cutting has ended (at most 5 minutes)."""
    started = time.time() if started is None else started
    window = ui().verify_window()
    if window is not None and window.running() and time.time() - started < 300:
        later(500, lambda: when_done(then, started))
        return
    log("  cut in {:.1f} s".format(time.time() - started))
    later(500, then)


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    handlers().verify()
    check(ui().verify_window() is None, "no operations: no window")
    check("no operation to verify" in status(), "no operations: says so: " + status())

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
    started = time.time()
    handlers().verify()
    took = time.time() - started
    window = ui().verify_window()
    check(window is not None, "the Verify window opens")
    check(took < 1.0, "at once ({:.2f} s)".format(took))
    check(window is not None and window.windowTitle() == "Verify - Setup 1", "titled after the setup")
    check(window is not None and window.resolution.currentData() == 250, "Medium (250) at first")
    check(window is not None and not window.running(), "it waits for Start")
    check(window is not None and not window.export_button.isEnabled(), "nothing to export yet")
    check(model_visible(), "the part still shown")
    shot("01_open")
    window.start_button.click()
    check(window.running(), "Start: it works")
    check(window.step.text() == "Reading the program and the part", "first it reads: " + window.step.text())
    shot("01_running")
    when_done(step4)


@safe
def step4():
    window = ui().verify_window()
    result = window.result
    check(result is not None, "a result: " + window.step.text())
    if result is not None:
        log("  gouges", result.gouges, "collisions", result.collisions, "notes", result.notes)
        log("  cell", result.cell_mm, "vertices", len(result.vertices))
        text = window.report.toPlainText()
        log("  report:", text.replace("\n", " | "))
        check("too deep" in text.lower(), "the report says about too deep")
        check("rapid move" in text.lower(), "the report says about rapid moves")
        check("Threads without" not in text and "Every thread" not in text, "no threads: nothing about their holes")
        # threads, one without its hole (model.verify checks them, tests/test_verify.py)
        from avangardecam.model.verify import HoleCheck

        holes = (HoleCheck("Thread milling 1", (-110.0, 6.5, -1.7e-08), 26.9, 1.81), HoleCheck("Thread milling 1", (-87.0, 6.5, 0.0), 0.0, 1.81))
        html = ui().report_html(result._replace(holes=holes))
        check("Threads without their hole" in html and "26.9 mm³" in html and "X-110.000 Y+6.500 Z+0.000" in html and "X-87.000" not in html,
              "the report names the thread without its hole")  # fmt: skip
        check("Every thread has its hole" in ui().report_html(result._replace(holes=holes[1:])), "or says each has its hole")
    check(ui().shown(doc()), "the 3D view shows the stock left")
    check(not model_visible(), "the part hidden")
    check(window.export_button.isEnabled(), "Export enabled")
    for name in ("stock.ply", "stock.stl"):
        path = os.path.join(OUT, name)
        check(window.export_to(path) == path and os.path.getsize(path) > 1000, "exported " + name)
    check("Saved" in window.step.text(), "says where it saved: " + window.step.text())
    shot("02_result")
    window.resolution.setCurrentIndex(0)
    window.start_button.click()
    check(window.running(), "Start cuts again")
    when_done(step5)


@safe
def step5():
    window = ui().verify_window()
    check(window.result is not None and window.result.cell_mm > 0, "a result again")
    check(avangardecam.params().GetInt("LastVerifyResolution", 0) == 150, "Rough remembered")
    check(ui().shown(doc()), "the stock left shown again")
    shot("03_rough")
    window.close()
    later(800, step6)


@safe
def step6():
    check(ui().verify_window() is None, "the window closes")
    check(not ui().shown(doc()), "the stock left gone")
    check(model_visible(), "the part back")
    shot("04_closed")
    handlers().verify()
    window = ui().verify_window()
    check(window is not None and window.resolution.currentData() == 150, "opens again at Rough")
    check(window is not None and not window.running(), "and waits for Start again")
    later(500, step7)


@safe
def step7():
    ui().verify_window().close()
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
