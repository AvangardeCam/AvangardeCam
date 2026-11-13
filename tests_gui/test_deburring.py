# Deburring GUI test: Extract boundary edges of the top, the whole sketch
# selected, CAM > Deburring on the ribbon: the window with no tool (OK
# refused), T29 from the library, the chamfer 0.5 / tip 0.5 by default,
# side left, straight down, Advanced hidden; the line under the fields
# follows the chamfer; Advanced starts with where the chamfer puts the tool;
# Manual; OK makes "Deburring 1" (chamfer 0.15, tip 0.85 = the user's own
# contour: XY offset 0.85, Z-Depth -1). The details: the chamfer typed
# makes it deeper, undo; Advanced checked keeps the tool where it was.
# Edit...: its values, the right side. The .H program has it. A new
# deburring starts with the values and the tool used last. The sketch's
# details have Deburring...
#
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_deburring.txt"), "w")
FAILURES = []
NAMES = {}


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


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def engine():
    from avangardecam.engine import deburring

    return deburring


def handlers():
    from avangardecam import handlers as h

    return h


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def doc():
    return FreeCAD.ActiveDocument


def op():
    return doc().getObject(NAMES["op"])


def values():
    return engine().deburring_of(op())[1]


def contour():
    return cam().contour_of(op())[1]


def library():
    from avangardecam import tool_library_path
    from avangardecam.model import library as model_library

    return model_library.load(tool_library_path())


def modal(fn, ms=600):
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


def box(widget, name):
    return widget.findChild(QtWidgets.QWidget, "AvangardeCam" + name)


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    from avangardecam.engine import geometry

    body = cam().models(doc())[0]
    top = max(
        (f for f in body.Shape.Faces if f.findPlane() is not None and f.normalAt(0, 0).z > 0.99),
        key=lambda f: (round(f.BoundBox.ZMax, 6), f.Area),
    )
    name = "Face{}".format(next(i for i, f in enumerate(body.Shape.Faces, start=1) if f.isSame(top)))
    made = geometry.extract_boundary(doc(), [body], body, name)
    NAMES["sketch"] = made.Name
    doc().recompute()
    panel().refresh()
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, made.Name)  # the whole sketch: all its lines
    ribbon = mw().findChild(QtWidgets.QToolButton, "AvangardeCam_cam_deburring")
    check(ribbon is not None, "CAM > Deburring on the ribbon")
    modal(dialog_new)
    if ribbon is not None:
        ribbon.click()
    else:
        handlers().deburring()
    later(1000, step3)


def dialog_new(widget):
    check(widget.objectName() == "AvangardeCamDeburringDialog", "the Deburring window opens")
    chamfer, tip = box(widget, "DeburringChamfer"), box(widget, "DeburringTipBelow")
    check((chamfer.property("rawValue"), tip.property("rawValue")) == (0.5, 0.5), "chamfer 0.5, tip 0.5 by default")
    check(box(widget, "DeburringSide").currentData() == "left", "left of the lines by default")
    check(box(widget, "DeburringApproach").currentData() == "none", "straight down by default")
    check(not box(widget, "DeburringLeadRadius").isEnabled(), "no approach radius straight down")
    check(not box(widget, "DeburringDepth").isVisible(), "Z-Depth hidden without Advanced")
    widget.accept()
    check(widget.isVisible() and "chamfer mill" in box(widget, "DeburringMessage").text(), "OK without a tool refused")
    t29 = next(e for e in library() if e.id == "t29-aluminium-afbraamfrees-6mm-alu")
    widget.use(t29)
    cut = box(widget, "DeburringCut")
    check("1.00 mm below" in cut.text() and "0.50 mm beside" in cut.text(), "the line under the fields: " + cut.text())
    chamfer.setProperty("rawValue", 0.15)
    tip.setProperty("rawValue", 0.85)
    QtWidgets.QApplication.processEvents()
    check("1.00 mm below" in cut.text() and "0.85 mm beside" in cut.text(), "0.15 / 0.85: " + cut.text())
    chamfer.setProperty("rawValue", 2.5)
    QtWidgets.QApplication.processEvents()
    check("too small" in cut.text(), "a chamfer too large for T29 said under the fields")
    chamfer.setProperty("rawValue", 0.15)
    advanced = box(widget, "DeburringAdvanced")
    advanced.setChecked(True)
    QtWidgets.QApplication.processEvents()
    depth, offset = box(widget, "DeburringDepth"), box(widget, "DeburringOffsetXY")
    check(depth.isVisible() and offset.isVisible(), "Advanced shows Z-Depth and XY offset")
    check((depth.property("rawValue"), offset.property("rawValue")) == (-1.0, 0.85), "they start where the chamfer puts the tool")
    check(not chamfer.isEnabled(), "the chamfer not typed with Advanced")
    check("chamfer of 0.15 mm" in cut.text(), "Advanced: the chamfer they make: " + cut.text())
    widget.grab().save(os.path.join(OUT, "01_dialog_advanced.png"))
    advanced.setChecked(False)
    manual = box(widget, "Manual")
    manual.click()
    QtWidgets.QApplication.processEvents()
    window = widget.findChild(QtWidgets.QDialog, "AvangardeCamManualWindow")
    check(window is not None and "Tip below chamfer" in window.findChild(QtWidgets.QTextBrowser).toPlainText(), "Manual says how it works")  # fmt: skip
    if window is not None:
        window.close()
    widget.grab().save(os.path.join(OUT, "01_dialog.png"))
    # on this part the outline's arrows run with the part on their left: the tool would cut a groove
    answer(widget, QtWidgets.QMessageBox.No)
    widget.accept()
    check(widget.isVisible(), "No: the window stays open")
    check("groove" in box(widget, "DeburringMessage").text(), "the warning stays under the fields")
    widget.grab().save(os.path.join(OUT, "01_dialog_warning.png"))
    answer(widget, QtWidgets.QMessageBox.Yes)
    widget.accept()


def answer(widget, button):
    """Answer the warning the window is about to ask."""

    def run():
        box_ = QtWidgets.QApplication.activeModalWidget()
        if not isinstance(box_, QtWidgets.QMessageBox):
            later(100, run)
            return
        NAMES.setdefault("warnings", []).append(box_.text())
        box_.grab().save(os.path.join(OUT, "01_warning.png"))
        box_.button(button).click()

    later(300, run)


@safe
def step3():
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "OK made the operation")
    NAMES["op"] = ops[0].Name
    check(op().Label == "Deburring 1", "named " + op().Label)
    v = values()
    check((v.chamfer_mm, v.tip_mm, v.advanced) == (0.15, 0.85, False), "its values: {}".format(v))
    c = contour()
    check((c.z_depth_mm, c.offset_xy_mm, c.compensation, c.approach) == (-1.0, 0.85, "off", "none"), "made as the user's contour: {}".format(c))  # fmt: skip
    check("T29" in op().ToolController.Label, "with T29")
    warnings = NAMES.get("warnings", [])
    check(len(warnings) == 2 and "Deburr anyway?" in warnings[0], "OK asked twice whether to deburr anyway")
    panel().select_entry("operation", NAMES["op"])
    later(600, step4)


@safe
def step4():
    view = panel().view
    check(type(view).__name__ == "DeburringView", "the details of a deburring")
    check(view.warning.isVisible() and "groove" in view.warning.text(), "the details say it too")
    shot("02_details")
    view.fields.boxes["chamfer_mm"].setProperty("rawValue", 0.3)
    view.apply()
    check(abs(contour().z_depth_mm + 1.15) < 1e-9, "chamfer 0.3: 1.15 mm deep, got {}".format(contour().z_depth_mm))
    check(contour().offset_xy_mm == 0.85, "on the same line")
    doc().undo()
    check(values().chamfer_mm == 0.15 and contour().z_depth_mm == -1.0, "undo: 0.15 again")
    later(800, step4b)


@safe
def step4b():
    view = panel().view
    check(view.fields.boxes["chamfer_mm"].property("rawValue") == 0.15, "the details show 0.15 after undo")
    view.fields.check.setChecked(True)
    later(300, step5)


@safe
def step5():
    v = values()
    check(v.advanced and (v.z_depth_mm, v.offset_xy_mm) == (-1.0, 0.85), "details Advanced: the tool stays where it was: {}".format(v))  # fmt: skip
    check(contour().z_depth_mm == -1.0, "the contour the same")
    modal(dialog_edit)
    handlers().edit_operation(op())
    later(1000, step6)


def dialog_edit(widget):
    check(box(widget, "DeburringAdvanced").isChecked(), "Edit...: Advanced checked")
    check(box(widget, "DeburringOffsetXY").property("rawValue") == 0.85, "Edit...: XY offset 0.85")
    box(widget, "DeburringAdvanced").setChecked(False)
    side = box(widget, "DeburringSide")
    side.setCurrentIndex(side.findData("right"))
    # right of these arrows: the outline outside, the two holes outside too (on the material)
    answer(widget, QtWidgets.QMessageBox.Yes)
    widget.accept()


@safe
def step6():
    check(contour().arc_side == "right" and not values().advanced, "Edit...: the right side, Advanced off")
    warnings = NAMES.get("warnings", [])
    check(len(warnings) == 3 and warnings[-1].count(": Edge") == 2, "Edit...: asked about the two holes: {}".format(warnings[-1:]))  # fmt: skip
    from avangardecam.post import heidenhain

    text = heidenhain.write(cam().nc_program(doc(), "TEST"))
    check("*- Deburring\r\n" in text and "TOOL CALL 29 " in text, "the .H program has the deburring under its own title, T29")
    check(" Z-1. " in text.replace("\r\n", " \r\n"), "cut at Z-1")
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, NAMES["sketch"])
    modal(dialog_again)
    handlers().deburring()
    later(1000, step7)


def dialog_again(widget):
    check(box(widget, "DeburringChamfer").property("rawValue") == 0.15, "a new one starts with the chamfer used last")
    check(box(widget, "DeburringTipBelow").property("rawValue") == 0.85, "and the tip")
    check("T29" in box(widget, "DeburringTool").currentText(), "and T29")
    # on an arc of the default 3.5 mm the holes (the tool 1.4 mm round their centre) are too small
    approach = box(widget, "DeburringApproach")
    approach.setCurrentIndex(approach.findData("arc"))
    answer(widget, QtWidgets.QMessageBox.No)
    widget.accept()
    check("does not fit" in NAMES["warnings"][-1] and NAMES["warnings"][-1].count(": Edge") >= 2, "an arc that does not fit in the holes is asked about")  # fmt: skip
    check("does not fit" in box(widget, "DeburringMessage").text(), "and stays under the fields")
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    message = box(widget, "DeburringMessage")
    check(message.height() >= message.heightForWidth(message.width()) - 2, "the warning not cut off: {} of {} px".format(message.height(), message.heightForWidth(message.width())))  # fmt: skip
    widget.grab().save(os.path.join(OUT, "04_arc_warning.png"))
    widget.reject()


@safe
def step7():
    check(len(cam().operations(cam().find_job(doc()))) == 1, "Cancel made nothing")
    panel().select_entry("sketch", NAMES["sketch"])
    later(500, step8)


@safe
def step8():
    button = panel().view.findChild(QtWidgets.QPushButton, "AvangardeCamDeburring")
    check(button is not None, "the sketch's details have Deburring...")
    shot("03_sketch")
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
