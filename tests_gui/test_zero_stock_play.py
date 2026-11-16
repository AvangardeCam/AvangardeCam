# GUI test: the stock's own zero point and what runs the program on other
# zero points (experimental). A contour on the top and one on the right
# wall (the zero point turned onto it, 5 axes):
# - the Stock window on the wall's zero point (a quarter turn): its sizes
#   and allowances are along the axes the user sees; typed there, the block
#   changes on the default zero point (counted from the wall's);
# - on a zero point at an odd angle FreeCAD's stock is the box around the
#   block: the block itself is drawn, the Stock window works along the
#   stock's own axes and says so;
# - Play runs the wall's contour with the tool lying along the wall's Z, in
#   the program of the machine that tilts; Verify cuts both contours and
#   shows the stock left where the part is, whichever zero point is active.
#
# A block with a hole, made as a STEP by the test (AC_STEP not used).
# Run like test_layout.py (see README.md).
import os
import tempfile
import time
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_zero_stock_play.txt"), "w")
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


def engine():
    from avangardecam.engine import op_zero

    return op_zero


def handlers():
    from avangardecam import handlers as h

    return h


def near(a, b, tolerance=1e-4):
    return len(a) == len(b) and all(abs(x - y) <= tolerance for x, y in zip(a, b))


def refresh():
    scene().apply(doc())
    layout().panel.refresh()


def move_zero(shift, turn):
    """Move 0-Point with these values, as one undo step."""
    from avangardecam.engine import move_zero as engine_move

    doc().openTransaction("Move 0-Point")
    engine_move.move(job(), shift, turn)
    doc().commitTransaction()
    refresh()


def contour(normal, depth):
    """A contour on the outline of the block's face along normal, as one undo step."""
    from avangardecam.engine import geometry
    from avangardecam.model import operations

    doc().openTransaction("Contour tooling")
    sketch = geometry.extract_boundary(doc(), [body()], body(), face(normal))
    op = cam().add_contour(job(), sketch, operations.Contour(depth), SEEN["tc"])
    doc().recompute()
    doc().commitTransaction()
    refresh()
    return op


def modal(fn, ms=600):
    """Run fn(widget) on the modal window a handler is about to open."""

    def run():
        widget = QtWidgets.QApplication.activeModalWidget()
        if widget is None:
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


def values(d):
    sizes = tuple(float(box.property("rawValue")) for box in d.sizes)
    allowances = tuple(float(d.allowances[n].property("rawValue")) for n in ("x_neg_mm", "x_pos_mm", "y_neg_mm", "y_pos_mm", "z_neg_mm", "z_pos_mm"))
    return sizes, allowances


def own_note(d):
    label = d.findChild(QtWidgets.QLabel, "AvangardeCamStockOwnZero")
    return label.text() if label is not None else None


def program_stock():
    return tuple(cam().nc_program(doc(), "TEST").setups[0].stock)


def block_node():
    root = job().ViewObject.RootNode
    return next((root.getChild(i) for i in range(root.getNumChildren()) if root.getChild(i).getName() == "AvangardeCamStockBlock"), None)


@safe
def step1():
    import Part

    mw().setGeometry(0, 0, 1920, 1080)
    V = FreeCAD.Vector
    path = os.path.join(OUT, "block_with_hole.step")
    Part.makeBox(40, 20, 12, V(-20, -10, 0)).cut(Part.makeCylinder(3, 12, V(8, 0, 0))).exportStep(path)
    handlers().import_step(path)
    later(1500, step2)


@safe
def step2():
    from avangardecam.model import library
    from avangardecam.tests.test_model import LIBRARY

    variant = next(e for e in library.load(LIBRARY) if e.number == 21 and e.workpiece_material == "RVS")
    doc().openTransaction("Add tool")
    SEEN["tc"] = cam().add_tool(job(), variant)
    doc().commitTransaction()
    SEEN["top"] = contour((0, 0, 1), -1.0).Name
    move_zero((20.0, 0.0, -6.0), (0.0, 90.0, 0.0))
    SEEN["side"] = contour((1, 0, 0), -2.0).Name
    check(zero() == (20.0, 0.0, 6.0), "the zero point on the right wall: {}".format(zero()))
    check(near(program_stock(), (-21, -11, -12, 21, 11, 1)), "the block on the default zero point: {}".format(program_stock()))
    modal(wall_window)
    button("cam_stock").click()
    later(1000, step3)


def wall_window(d):
    sizes, allowances = values(d)
    check(own_note(d) is None, "the Stock window on the wall: along the axes the user sees")
    check(near(sizes, (13, 22, 42)), "its sizes there (X down the wall, Z out of it): {}".format(sizes))
    check(near(allowances, (1, 0, 1, 1, 1, 1)), "its allowances there: {}".format(allowances))
    d.allowances["x_neg_mm"].setProperty("rawValue", 3.0)  # X- of the wall is up
    d.allowances["z_pos_mm"].setProperty("rawValue", 2.5)  # Z+ is out of the wall
    shot("01_stock_on_the_wall")
    d.accept()


@safe
def step3():
    check(near(tuple(cam().stock_bounds(job())), (-9, -11, -41, 6, 11, 2.5)), "OK: the stock as typed on the wall: {}".format(tuple(cam().stock_bounds(job()))))
    check(near(program_stock(), (-21, -11, -12, 22.5, 11, 3)), "the block on the default zero point, counted from the wall: {}".format(program_stock()))
    check(layout().ribbon.undo_button.tooltip() == "Undo: Stock (Ctrl+Z)", "one undo step: {}".format(layout().ribbon.undo_button.tooltip()))
    check(block_node() is None and job().Stock.ViewObject.Visibility, "a quarter turn away: FreeCAD's stock is the block")
    # at an odd angle
    doc().openTransaction("Reset 0-Point")
    engine().reset(job())
    doc().commitTransaction()
    refresh()
    check(near(tuple(cam().stock_bounds(job())), (-21, -11, -12, 22.5, 11, 3)), "Reset: the same block: {}".format(tuple(cam().stock_bounds(job()))))
    move_zero((0.0, 0.0, 0.0), (0.0, 0.0, 30.0))
    node = block_node()
    check(node is not None, "turned 30°: the block is drawn as it lies")
    check(not job().Stock.ViewObject.Visibility, "instead of the box around it")
    size = tuple(cam().stock_bounds(job()).size)
    check(size[0] > 43.5 + 5 and size[1] > 22 + 5, "FreeCAD's stock is that box: {}".format(size))
    item = layout().panel.select_entry("stock", job().Stock.Name)
    r = rows() if item is not None else {}
    check(r.get("Size") == "43.50 × 22.00 × 15.00 mm", "the details: the block's own size: {}".format(r.get("Size")))
    note = layout().panel.view.note.text()
    check("stock's own zero point" in note, "and say whose axes: {}".format(note))
    modal(odd_window)
    button("cam_stock").click()
    later(1000, step4)


def odd_window(d):
    sizes, allowances = values(d)
    note = own_note(d)
    check(note is not None and note.startswith("The zero point is turned at an odd angle to the stock's own zero point"), "the Stock window says whose axes: {}".format(note))
    check(near(sizes, (43.5, 22, 15)), "the block's own sizes: {}".format(sizes))
    check(near(allowances, (1, 2.5, 1, 1, 0, 3)), "its own allowances: {}".format(allowances))
    d.allowances["y_pos_mm"].setProperty("rawValue", 4.0)
    shot("02_stock_at_an_odd_angle")
    d.accept()


@safe
def step4():
    check(near(program_stock(), (-21, -11, -12, 22.5, 14, 3)), "OK: the block as typed, on its own axes: {}".format(program_stock()))
    check(block_node() is not None, "still drawn as it lies")
    doc().openTransaction("Reset 0-Point")
    engine().reset(job())
    doc().commitTransaction()
    refresh()
    check(block_node() is None and job().Stock.ViewObject.Visibility, "Reset: FreeCAD's stock again")
    check(near(tuple(cam().stock_bounds(job())), (-21, -11, -12, 22.5, 14, 3)), "the block: {}".format(tuple(cam().stock_bounds(job()))))
    # Play, from the wall's zero point
    doc().openTransaction("Make 0-Point active")
    engine().activate_operation(doc().getObject(SEEN["side"]))
    doc().commitTransaction()
    refresh()
    handlers().play()
    later(2500, step5)


@safe
def step5():
    from avangardecam.post import machines
    from avangardecam.ui import playback

    window = playback.window()
    check(window is not None, "Play opens")
    if window is None:
        return finish()
    title = window.findChild(QtWidgets.QLabel, "AvangardeCamPlayProgramTitle")
    check(title is not None and title.toolTip() == machines.SORALUCE_T35.label, "the program of the machine that tilts: {}".format(title.toolTip() if title else None))
    check(any("PLANE SPATIAL SPA0. SPB90. SPC0." in text for text in window.timeline.lines), "with the wall's tilted plane")
    top, side = window.timeline.operations
    window.seek(top.start_s + top.duration_s / 2.0)
    turn = tuple(round(c, 4) for c in window.scene.turn.rotation.getValue().getValue())
    check(turn == (0.0, 0.0, 0.0, 1.0), "on the top the tool stands: {}".format(turn))
    window.seek(side.start_s + side.duration_s * 0.6)
    turn = tuple(round(c, 4) for c in window.scene.turn.rotation.getValue().getValue())
    check(turn == (0.0, 0.7071, 0.0, 0.7071), "on the wall it lies along the wall's Z: {}".format(turn))
    tip = tuple(window.scene.place.translation.getValue().getValue())
    check(18.0 - 1e-3 <= tip[0] <= 120.0 + 1e-3 and abs(tip[1]) <= 15.0, "its tip at the wall, in the default zero point's coordinates: {}".format(tuple(round(c, 3) for c in tip)))
    path = window.polyline.points
    check(abs(float(path[:, 0].max()) - 120.0) < 1e-6 and abs(float(path[:, 0].min()) - 18.0) < 1e-6, "its path from 100 out of the wall to 2 in it")
    before = window.material.volume()
    window.seek(window.timeline.total_s)
    check(window.material.volume() < before - 1.0, "the stock goes on the wall too")
    check(window.crashes == [], "nothing run into: {}".format(window.crashes))
    QtWidgets.QApplication.processEvents()
    shot("03_play_on_the_wall")
    window.close()
    handlers().verify()
    later(1500, step6)


def when_done(then, started=None):
    """then() once Verify's cutting has ended (at most 5 minutes)."""
    from avangardecam.ui import verify

    started = time.time() if started is None else started
    window = verify.verify_window()
    if window is not None and window.running() and time.time() - started < 300:
        later(500, lambda: when_done(then, started))
        return
    later(500, then)


@safe
def step6():
    from avangardecam.ui import verify

    window = verify.verify_window()
    check(window is not None, "Verify opens")
    if window is None:
        return finish()
    window.start_button.click()
    when_done(step7)


@safe
def step7():
    from avangardecam.ui import verify

    window = verify.verify_window()
    result = window.result
    check(result is not None, "a result: " + window.step.text())
    if result is None:
        return finish()
    gouges = [(g.operation, round(g.depth_mm, 2)) for g in result.gouges]
    check(gouges == [("Contour 1", 1.0), ("Contour 2", 2.0)], "both contours checked, each from its own zero point: {}".format(gouges))
    check(result.collisions == (), "no collision")
    low, high = result.vertices.min(axis=0), result.vertices.max(axis=0)
    check(near(tuple(low) + tuple(high), (-21, -11, -12, 22.5, 14, 3), 0.3), "the stock left in the default zero point's coordinates: {} {}".format(low, high))
    check(verify.shown(doc()), "shown in 3D")
    root = view().getSceneGraph()
    node = next(root.getChild(i) for i in range(root.getNumChildren()) if root.getChild(i).getName() == verify._NODE_NAME)
    first = node.getChild(0)
    check(first.getTypeId().getName().getString() == "Transform", "moved to where the active zero point has the part")
    # the default zero point as the wall's sees it: 6 up the wall (-X), 20 behind it (-Z)
    place = tuple(round(c, 4) for c in first.translation.getValue().getValue())
    check(place == (-6.0, 0.0, -20.0), "the default zero point from the wall: {}".format(place))
    QtWidgets.QApplication.processEvents()
    shot("04_verify_from_the_wall")
    window.close()
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
