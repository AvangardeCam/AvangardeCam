# Cutting data GUI test on the test model (a block 40 x 20 x 12; zero on
# its top). The Facing window with T5 Aluminium: the spindle speed and
# feeds filled from the tool, Vc and fz beside them; a changed value bold
# and "(own)", From tool puts the tool's back; another tool its values.
# OK keeps the own values on the operation: the details, the program (a
# whole TOOL CALL with the own speed, Q31 the own feed) while the tool keeps
# its own; Edit... shows them, Change tool... drops them. The drilling
# window names its feeds Q206 and Q253.
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
LOG = open(os.path.join(OUT, "test_cutting_data.txt"), "w")
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


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def cutting():
    from avangardecam.engine import cutting_data

    return cutting_data


def handlers():
    from avangardecam import handlers as h

    return h


def doc():
    return FreeCAD.ActiveDocument


def body():
    return cam().models(doc())[0]


def rows():
    return dict(panel().view.rows())


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


def variant(number, material):
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == number and e.workpiece_material == material)


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


def label(parent, name):
    return parent.findChild(QtWidgets.QLabel, name)


def title(box):
    """The text of the label beside a field of the cutting data."""
    grid = box.parentWidget().layout()
    index = grid.indexOf(box)
    row, _column, _rows, _columns = grid.getItemPosition(index)
    return grid.itemAtPosition(row, 0).widget().text()


def nc_blocks():
    from avangardecam.post import heidenhain

    text = heidenhain.write(cam().nc_program(doc(), "TEST"))
    return [line.split(" ", 1)[1] for line in text.split("\r\n") if line and not line.startswith(" ")]


def top_face():
    from avangardecam.engine import geometry

    shape = body().Shape
    return max(
        (f.BoundBox.ZMax, f.Area, "Face{}".format(i))
        for i, f in enumerate(shape.Faces, start=1)
        if f.findPlane() is not None and geometry.outward_normal(shape, f).getAngle(FreeCAD.Vector(0, 0, 1)) < 1e-6
    )[2]


T5 = None


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    global T5
    T5 = variant(5, "Aluminium").tool
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, top_face())
    modal(facing_window)
    handlers().facing()
    later(500, step3)


def facing_window(dialog):
    spindle = field(dialog, "AvangardeCamFacingSpindle")
    feed_xy = field(dialog, "AvangardeCamFacingFeedXY")
    feed_z = field(dialog, "AvangardeCamFacingFeedZ")
    from_tool = field(dialog, "AvangardeCamFacingFromTool")
    check(spindle is not None and feed_xy is not None and feed_z is not None, "the window has the cutting data")
    dialog.use(variant(5, "Aluminium"))
    QtWidgets.QApplication.processEvents()
    check(
        (spindle.value(), feed_xy.value(), feed_z.value()) == (T5.spindle_rpm, T5.feed_xy_mm_min, T5.feed_z_mm_min),
        "filled from T5: {} {} {}".format(spindle.value(), feed_xy.value(), feed_z.value()),
    )
    vc = label(dialog, "AvangardeCamFacingVc").text()
    fz = label(dialog, "AvangardeCamFacingFz").text()
    check(vc.startswith("Vc ") and vc.endswith(" m/min"), "Vc beside the speed: " + vc)
    check(fz.startswith("fz ") or fz.startswith("f "), "fz beside the feed: " + fz)
    check(not from_tool.isEnabled() and not spindle.font().bold(), "the tool's values: not bold, From tool off")
    spindle.setValue(2500)
    check(spindle.font().bold() and "(own)" in title(spindle), "a changed speed is bold and own: " + title(spindle))
    check(from_tool.isEnabled(), "From tool on")
    check("Vc {:.0f} m/min".format(3.14159265 * T5.diameter_mm * 2500 / 1000) == label(dialog, "AvangardeCamFacingVc").text(), "Vc follows the speed")  # fmt: skip
    from_tool.click()
    check(spindle.value() == T5.spindle_rpm and not spindle.font().bold(), "From tool: the tool's speed again")
    feed_xy.setValue(400)
    feeds = label(dialog, "AvangardeCamFacingFeeds").text()
    check("400" in feeds, "the feeds row follows: " + feeds)
    dialog.use(variant(16, "Aluminium"))
    QtWidgets.QApplication.processEvents()
    t16 = variant(16, "Aluminium").tool
    check(feed_xy.value() == t16.feed_xy_mm_min and not feed_xy.font().bold(), "another tool: its own values")
    dialog.use(variant(5, "Aluminium"))
    QtWidgets.QApplication.processEvents()
    spindle.setValue(2500)
    feed_xy.setValue(400)
    shot("cutting_data_window")
    dialog.accept()


@safe
def step3():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "the facing is made")
    OP = ops[0]
    own = cutting().own(OP)
    check((own.spindle_rpm, own.feed_xy_mm_min, own.feed_z_mm_min) == (2500.0, 400.0, None), "kept on it: {}".format(own))
    tool = cam().tool_with_number(cam().find_job(doc()), 5).tool
    check(tool.spindle_rpm == T5.spindle_rpm and tool.feed_xy_mm_min == T5.feed_xy_mm_min, "the tool keeps its own values")
    handlers()._select("operation", OP.Name)
    QtWidgets.QApplication.processEvents()
    text = rows().get("Tool", "")
    check("S 2500 rpm (own)" in text and "XY 400 (own)" in text, "the details: " + text.replace("\n", " | "))
    feeds = rows().get("Feeds", "")
    check("400" in feeds, "the details' feeds: " + feeds)
    blocks = nc_blocks()
    check("TOOL CALL 5 Z S2500 DL0 DR0;{}".format(T5.name) in blocks, "program: TOOL CALL with the own speed")
    check("FN0: Q31=400 ;voeding XY" in blocks, "program: Q31 the own feed")
    modal(edit_window)
    handlers().edit_operation(OP)
    later(500, step4)


def edit_window(dialog):
    spindle = field(dialog, "AvangardeCamFacingSpindle")
    feed_z = field(dialog, "AvangardeCamFacingFeedZ")
    check(spindle.value() == 2500 and spindle.font().bold(), "Edit...: the own speed, bold")
    check(feed_z.value() == T5.feed_z_mm_min and not feed_z.font().bold(), "Edit...: the tool's Z feed")
    feed_z.setValue(100)
    dialog.accept()


@safe
def step4():
    own = cutting().own(OP)
    check((own.spindle_rpm, own.feed_xy_mm_min, own.feed_z_mm_min) == (2500.0, 400.0, 100.0), "Edit...: kept {}".format(own))
    doc().undo()
    check(cutting().own(OP).feed_z_mm_min is None, "undo: one step back")
    doc().redo()
    modal(lambda picker: (picker.select_ids([variant(5, "Aluminium").id]), picker.use_selected()))
    handlers().change_tool(OP)
    later(800, step5)


@safe
def step5():
    check(cutting().own(OP).empty(), "Change tool...: the tool's values again")
    FreeCADGui.Selection.clearSelection()
    sketch = None
    from avangardecam.ui.drilling_dialog import DrillingDialog

    job = cam().find_job(doc())
    dialog = DrillingDialog(job, body(), "1 hole", [(4.5, None)], [])
    titles = [title(field(dialog, "AvangardeCamDrilling" + n)) for n in ("FeedXY", "FeedZ")]
    check(titles == ["Feed Q206 (down):", "Feed Q253 (to the start):"], "drilling: {}".format(titles))
    dialog.deleteLater()
    del sketch
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
