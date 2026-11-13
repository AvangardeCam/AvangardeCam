# Simulation window GUI test: two contours on the top's boundary, the
# second with another tool. CAM > Play opens the simulation in a window of
# its own (the project's view untouched: the operations' paths stay):
# its 3D view, the operations with their times, the whole program with the
# line the machine runs, the time line and the buttons. The whole time is
# the cycle time; at the start the stock is the whole block and the line
# the first TOOL CALL; Right block by block runs lines of the exported
# program; Down to the next operation (its tool change and TOOL CALL), Up
# back; a click on a line of the program goes to where that block has
# run; End: material taken; Space plays at x10 (the tool moves, the stock is
# drawn again while it plays), Space pauses; Fine makes the cells smaller;
# Part shows the part; Escape closes the window. A third contour with the
# first tool deeper than its cutting length (its shank in material), its
# safe height (FreeCAD's) 5 below the top (FMAX down into the material),
# found as the stock is cut (End): red marks on the time line, red lines of the program, the
# button says which and goes to the next; played from the start it stops
# at the end of the first one's block. Closing the document closes it too.
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
LOG = open(os.path.join(OUT, "test_playback.txt"), "w")
FAILURES = []
OPS = []
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
    """The simulation window (with its 3D view) or the main window."""
    window = ui().window()
    path = os.path.join(OUT, name + ".png")
    (window if window is not None else mw()).grab().save(path)
    log("screenshot", path)


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def handlers():
    from avangardecam import handlers as h

    return h


def doc():
    return FreeCAD.ActiveDocument


def job():
    return cam().find_job(doc())


def ui():
    from avangardecam.ui import playback

    return playback


def key(k):
    """A key pressed in the simulation window, on its 3D view."""
    window = ui().window()
    window.activateWindow()
    QtWidgets.QApplication.setActiveWindow(window)
    view = window.view
    view.setFocus()
    for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
        event = QtGui.QKeyEvent(kind, k, QtCore.Qt.NoModifier, " " if k == QtCore.Qt.Key_Space else "")
        QtWidgets.QApplication.sendEvent(view, event)
    QtCore.QCoreApplication.processEvents()


def line_text():
    return ui().window().current_line()


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    from avangardecam import tool_library_path
    from avangardecam.engine import geometry
    from avangardecam.model import library, operations

    body = cam().models(doc())[0]
    top = max(
        (f for f in body.Shape.Faces if f.findPlane() is not None and f.normalAt(0, 0).z > 0.99),
        key=lambda f: (round(f.BoundBox.ZMax, 6), f.Area),
    )
    name = "Face{}".format(next(i for i, f in enumerate(body.Shape.Faces, start=1) if f.isSame(top)))
    sketch = geometry.extract_boundary(doc(), [body], body, name)
    entries = library.load(tool_library_path())
    first = next(e for e in entries if e.number == 21 and e.workpiece_material == "RVS")
    second = next(e for e in entries if e.number != 21 and e.tool.shape == "Endmill" and e.tool.feed_xy_mm_min)
    tc1 = cam().add_tool(job(), first)
    tc2 = cam().add_tool(job(), second)
    OPS.append(cam().add_contour(job(), sketch, operations.Contour(-1.0), tc1))
    OPS.append(cam().add_contour(job(), sketch, operations.Contour(-2.0), tc2))
    doc().recompute()
    SEEN["tools"] = (first.number, second.number)
    later(800, step3)


@safe
def step3():
    from avangardecam.ui.layout import LAYOUT

    LAYOUT.ribbon.tabs.setCurrentIndex(1)
    button = LAYOUT.ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_cam_play")
    check(button is not None and button.isEnabled(), "CAM > Output has the Play button")
    button.click()
    later(2000, step4)


@safe
def step4():
    from avangardecam.model import cycle_time, playback as model_playback
    from avangardecam.post import heidenhain

    window = ui().window()
    check(window is not None and window.isVisible(), "Play opens the simulation window")
    check(window.isWindow() and window.windowTitle() == "Simulation - " + job().Label, "a window of its own: " + window.windowTitle())
    check(all(op.ViewObject.Visibility for op in OPS), "the project's view untouched: the paths stay")
    check(window.list.topLevelItemCount() == 2, "the list has both operations")
    exported = heidenhain.write(cam().nc_program(doc(), heidenhain.program_name(doc().Label), doc().Label)).split(heidenhain.NEWLINE)[:-1]
    check([window.program.item(k).text() for k in range(window.program.count())] == exported, "the whole exported program in the list")
    times = cycle_time.setup_time(cam().nc_program(doc(), "X").setups[0], retract_z=heidenhain.BRIDGEPORT_V1000.retract_z_mm)
    check(abs(window.timeline.total_s - times.total_s) < 1e-6, "the whole time is the cycle time")
    total = model_playback.clock_text(times.total_s)
    check(window.clock.text() == "0:00 / " + total, "the clock: " + window.clock.text())
    check("TOOL CALL {} Z".format(SEEN["tools"][0]) in line_text() and window.feed_label.text() == "Tool change", "at the start: the first TOOL CALL: " + line_text())
    stock = job().Stock.Shape.BoundBox
    check(window.material is not None and abs(window.material.volume() - stock.XLength * stock.YLength * stock.ZLength) < 1e-3, "at the start the stock is the whole block")
    check("cell" in window.material_label.text(), "the window says the cell's size: " + window.material_label.text())
    log("  first drawing:", window.material_label.text())
    shot("01_open")
    texts = []
    for _ in range(4):
        key(QtCore.Qt.Key_Right)
        texts.append(line_text())
    log("  blocks:", texts)
    check(all(t in exported for t in texts), "Right runs lines of the exported program")
    numbers = [int(t.split(" ", 1)[0]) for t in texts]
    check(numbers == sorted(numbers) and len(set(numbers)) >= 3, "block by block, on through the program")
    SEEN["t_right"] = window.t
    key(QtCore.Qt.Key_Left)
    check(window.t < SEEN["t_right"], "Left goes one block back")
    key(QtCore.Qt.Key_Down)
    second = window.timeline.operations[1]
    check(abs(window.t - second.start_s) < 1e-9, "Down: the start of the next operation")
    key(QtCore.Qt.Key_Right)  # up to the tool change height with the tool before
    key(QtCore.Qt.Key_Right)  # the tool change
    check(window.operation == 1 and window.list.currentItem() is window.list.topLevelItem(1), "the list follows the operation")
    check("TOOL CALL {} Z".format(SEEN["tools"][1]) in line_text(), "its tool change runs its TOOL CALL: " + line_text())
    check(window.tool_label.text().startswith("T{} ".format(SEEN["tools"][1])), "the second tool: " + window.tool_label.text())
    key(QtCore.Qt.Key_Up)
    key(QtCore.Qt.Key_Up)
    check(window.t == 0.0, "Up twice: the start")
    # a click on a line of the program: where that block has run
    row = next(k for k in range(window.program.count()) if window.program.item(k).text().endswith("L Z-1. R0 FQ30"))
    item = window.program.item(row)
    window.program.scrollToItem(item)
    rect = window.program.visualItemRect(item)
    from PySide6.QtTest import QTest

    QTest.mouseClick(window.program.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center())
    QtCore.QCoreApplication.processEvents()
    check(window.program.currentRow() == row and abs(window.scene.place.translation.getValue()[2] + 1.0) < 1e-6, "a click on a line: that block has run (down at -1): " + line_text())
    SEEN["before_end"] = window.material.volume()
    key(QtCore.Qt.Key_End)
    check(abs(window.t - window.timeline.total_s) < 1e-9 and window.clock.text() == total + " / " + total, "End: the end")
    SEEN["end_volume"] = window.material.volume()
    check(SEEN["end_volume"] < SEEN["before_end"] - 1.0, "at the end material is taken: {:.0f} -> {:.0f} mm3".format(SEEN["before_end"], SEEN["end_volume"]))
    log("  drawing at the end:", window.material_label.text())
    window.view.set_direction("isometric")
    shot("02_end")
    window.view.grab_image().save(os.path.join(OUT, "02_end_view.png"))
    key(QtCore.Qt.Key_Home)
    check(window.t == 0.0, "Home: the start")
    window.speed_box.setCurrentIndex(model_playback.SPEEDS.index(10.0))
    key(QtCore.Qt.Key_Space)
    check(window.playing, "Space plays")
    SEEN["tip"] = tuple(window.scene.place.translation.getValue())
    SEEN["drawn"] = window._material_drawn
    later(2500, step5)


@safe
def step5():
    window = ui().window()
    check(window.t > 15.0, "the time goes on at x10: {:.1f} s".format(window.t))
    check(tuple(window.scene.place.translation.getValue()) != SEEN["tip"], "the tool moves")
    check(window._material_drawn > SEEN["drawn"], "the stock is drawn again while it plays ({})".format(window.material_label.text()))
    shot("03_playing")
    key(QtCore.Qt.Key_Space)
    check(not window.playing, "Space pauses")
    check(window._material_at == window.t, "paused: the stock where the tool is")
    from avangardecam import params

    check(params().GetFloat("LastPlaybackSpeed", 1.0) == 10.0, "the speed is remembered")
    cell = window.material.cell_mm
    window.accuracy.setCurrentIndex(2)  # Fine
    QtCore.QCoreApplication.processEvents()
    check(window.material.cell_mm < cell * 0.6, "Fine: smaller cells ({:.2f} -> {:.2f} mm)".format(cell, window.material.cell_mm))
    log("  Fine:", window.material_label.text())
    window.part_box.setChecked(True)
    check(window.scene.part_switch.whichChild.getValue() == -3, "Part shows the part")
    window.view.set_direction("top")
    shot("04_fine_part")
    window.accuracy.setCurrentIndex(1)
    key(QtCore.Qt.Key_Escape)
    later(500, step6)


@safe
def step6():
    from avangardecam.model import operations

    check(ui().window() is None, "Escape closes the window")
    check(all(op.ViewObject.Visibility for op in OPS), "the paths in the project's view as they were")
    first = next(t for t in cam().project_tools(job()) if t.number == SEEN["tools"][0])
    cutting = first.tool.cutting_length_mm
    log("  T{} cutting length {} mm".format(first.number, cutting))
    tc = next(t for t in job().Tools.Group if t.ToolNumber == first.number)
    sketch = next(o for o in doc().Objects if o.TypeId == "Sketcher::SketchObject")
    op = cam().add_contour(job(), sketch, operations.Contour(-(cutting + 3.0)), tc)
    OPS.append(op)
    op.setExpression("SafeHeight", None)
    op.SafeHeight = -5.0
    doc().recompute()
    handlers().play()
    later(1500, step7)


@safe
def step7():
    from avangardecam.model import crashes

    window = ui().window()
    check(window is not None, "Play opens it again")
    check(window.crashes == [] and not window.crash_button.isVisible(), "at the start no crash found yet")
    key(QtCore.Qt.Key_End)
    kinds = {c.kind for c in window.crashes}
    log("  crashes:", [(c.kind, c.segment, round(c.volume_mm3, 1), window.timeline.lines[c.line]) for c in window.crashes][:12])
    check(kinds == {crashes.RAPID, crashes.SHANK}, "End: FMAX into material and the shank in material found: {}".format(sorted(kinds)))
    check(all(window.timeline.operations[window.timeline.steps[c.step].operation].label == OPS[2].Label
              for c in window.crashes if c.kind == crashes.SHANK), "the shank in the third contour")  # fmt: skip
    check(window.timeline.steps[window.crashes[0].step].kind == "rapid", "the first: FMAX down to the safe height")
    check(window.crash_button.isVisible() and window.crash_button.text().startswith("⚠ "), "the button says it: " + window.crash_button.text())
    rows = {c.line for c in window.crashes}
    check(all(window.program.item(r).background().color() == QtGui.QColor(ui().CRASH_LINE_COLOR) for r in rows), "their lines of the program red")
    check(window.program.item(0).background().style() == QtCore.Qt.NoBrush, "the other lines as they were")
    shot("05_crashes")
    key(QtCore.Qt.Key_Home)
    window.crash_button.click()
    first = window.crashes[0]
    check(abs(window.t - window.timeline.steps[first.step].end_s) < 1e-9, "the button: to the end of the first one's block")
    check(window.crash_button.text().startswith("⚠ 1 of {}: ".format(len(window.crashes))), "which it is: " + window.crash_button.text())
    check(window.program.currentRow() == first.line, "its line of the program: " + line_text())
    if len(window.crashes) > 1:
        window.crash_button.click()
        second = window.crashes[1]
        check(abs(window.t - window.timeline.steps[second.step].end_s) < 1e-9 or second.step == first.step, "again: the next one")
    key(QtCore.Qt.Key_Home)
    window.speed_box.setCurrentIndex(window.speed_box.count() - 1)  # x100
    key(QtCore.Qt.Key_Space)
    later(4000, step7b)


@safe
def step7b():
    window = ui().window()
    first = window.crashes[0]
    check(not window.playing, "playing it stops at a crash")
    check(abs(window.t - window.timeline.steps[first.step].end_s) < 1e-9, "at the end of the first one's block ({:.2f} s)".format(window.t))
    shot("06_stopped")
    FreeCAD.closeDocument(doc().Name)
    later(500, step8)


@safe
def step8():
    check(ui().window() is None, "closing the document closes the window")
    later(300, finish)


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
