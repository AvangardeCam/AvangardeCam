# GUI test: zero points of operations (experimental). Move 0-Point with
# "5 axes": Select wall turns the zero point's Z out of the wall; the
# operation made before keeps its zero point (marked "other 0-Point" in the
# list, drawn where it is on the part, its details say where it counts from).
# "Make 0-Point active" in its menu puts the zero point back there; Reset
# 0-Point and Set 0-Point as default on the ribbon beside Move 0-Point;
# editing an operation of another zero point makes that one active first.
# The program: the Soraluce postprocessor writes the shift and the tilted
# plane, the Bridgeport one refuses a turned zero point.
#
# A block with a hole, made as a STEP by the test (AC_STEP not used).
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from avangardecam import edition
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_op_zero.txt"), "w")
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


def engine():
    from avangardecam.engine import op_zero

    return op_zero


def ui_zero():
    from avangardecam.ui import op_zero

    return op_zero


def turn():
    return tuple(round(part("Turn" + axis).value(), 6) + 0.0 for axis in "XYZ")


def axis():
    from avangardecam.engine import geometry

    return tuple(round(c, 6) + 0.0 for c in geometry.tool_axis(cam().zero(job())))


def ops():
    return cam().operations(job())


def item_text(op):
    item = layout().panel.find_item(("operation", op.Name))
    return item.text(0) if item is not None else None


def drawn_at(op):
    """Where the 3D view puts an operation's path: the first node of its own scene."""
    node = op.ViewObject.RootNode.getChild(0)
    return tuple(round(c, 6) + 0.0 for c in node.translation.getValue().getValue())


def contour(normal, depth):
    """A contour on the outline of the block's face along normal, as one undo step."""
    from avangardecam.engine import geometry
    from avangardecam.model import operations

    doc().openTransaction("Contour tooling")
    sketch = geometry.extract_boundary(doc(), [body()], body(), face(normal))
    op = cam().add_contour(job(), sketch, operations.Contour(depth), SEEN["tc"])
    doc().recompute()
    doc().commitTransaction()
    scene().apply(doc())
    layout().panel.refresh()
    return op


def close_modal(seen_key):
    """Close the modal window that is open (a message or an operation's window), keeping its text."""
    box = QtWidgets.QApplication.activeModalWidget()
    SEEN[seen_key] = None if box is None else (box.text() if isinstance(box, QtWidgets.QMessageBox) else box.windowTitle())
    if box is not None:
        box.reject()


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
    from avangardecam.model import library
    from avangardecam.tests.test_model import LIBRARY

    move, default, reset, turn90 = (
        button(k) for k in ("cam_move_zero", "cam_set_default_zero", "cam_reset_zero", "cam_rotate_zero_90")
    )
    for b, text in ((default, "Set 0-Point as default"), (reset, "Reset 0-Point")):
        check(b is not None and b.isVisible() and b.isEnabled(), "ribbon: {} shown".format(text))
        check(b.text().replace("\n", " ") == text, "its text: {!r}".format(b.text()))
        check(not b.icon().isNull(), "it has an icon")
    left = [b.mapTo(layout().ribbon, QtCore.QPoint(0, 0)).x() for b in (move, default, turn90)]
    check(left[0] < left[1], "beside Move 0-Point: {}".format(left))
    reset.click()
    message = mw().statusBar().currentMessage()
    check(message == "Setup 1: the zero point is on its default one.", "Reset on the default says so: {}".format(message))
    default.click()
    message = mw().statusBar().currentMessage()
    check(message == "Setup 1: the zero point is its default one already.", "Set as default too: {}".format(message))
    variant = next(e for e in library.load(LIBRARY) if e.number == 21 and e.workpiece_material == "RVS")
    doc().openTransaction("Add tool")
    SEEN["tc"] = cam().add_tool(job(), variant)
    doc().commitTransaction()
    SEEN["top"] = contour((0, 0, 1), -1.0).Name
    check(item_text(ops()[0]) == ops()[0].Label, "a contour on the top, not marked: {}".format(item_text(ops()[0])))
    r = rows() if layout().panel.select_entry("setup", job().Name) is None else rows()
    check(r.get("From the default 0-Point") == "the default 0-Point", "setup details: {}".format(r.get("From the default 0-Point")))
    move.click()
    later(800, step3)


@safe
def step3():
    w = window()
    check(w is not None, "Move 0-Point opens its window")
    five = part("5X")
    check(five is not None and five.text() == "5 axes" and not five.isChecked(), "5 axes, not ticked")
    # shown only in the version with 5 axes (edition.FIVE_AXES); the turn under it is
    # the same code in both, so the test ticks it anyway
    check(five.isVisible() == edition.FIVE_AXES, "5 axes shown: {}".format(five.isVisible()))
    check(not part("Turn").isVisible(), "the turn is not shown without it")
    five.click()
    check(part("Turn").isVisible(), "ticked: the turn is shown")
    check(part("ZOut").text() == "Z out of the model" and part("ZOut").isChecked(), "Z out of the model, ticked")
    check(turn() == (0.0, 0.0, 0.0), "no turn at first: {}".format(turn()))
    part("TurnZ").setValue(30.0)
    QtWidgets.QApplication.processEvents()
    check(ui().preview_shown(job()), "a typed turn is drawn in 3D")
    part("Wall").click()
    click_face(face((1, 0, 0)))
    later(600, step4)


@safe
def step4():
    check(shift() == (20.0, 0.0, 0.0), "the right wall: the zero point onto it: {}".format(shift()))
    check(turn() == (0.0, 90.0, 0.0), "and its Z out of it: 90° about Y (the typed turn replaced): {}".format(turn()))
    check(axis() == (0.0, 0.0, 1.0), "the zero point waits for OK")
    shot("01_z_out_of_the_wall")
    window().accept()
    later(1000, step5)


@safe
def step5():
    top = doc().getObject(SEEN["top"])
    check(window() is None, "OK closes the window")
    check(zero() == (20.0, 0.0, 12.0) and axis() == (1.0, 0.0, 0.0), "the zero point on the wall, Z out of it: {} {}".format(zero(), axis()))  # fmt: skip
    message = mw().statusBar().currentMessage()
    check(message == "Setup 1: zero point moved X+20 Y+0 Z+0, turned X+0 Y+90 Z+0", "the status bar says it: {}".format(message))
    check(undo_tip() == "Undo: Move 0-Point (Ctrl+Z)", "one undo step: {}".format(undo_tip()))
    check(engine().parked(top), "the contour on the top keeps its zero point")
    check(item_text(top) == top.Label + "  (other 0-Point)", "marked in the list: {}".format(item_text(top)))
    check(drawn_at(top) == (0.0, 0.0, 12.0), "its path is drawn on its own zero point: {}".format(drawn_at(top)))
    check(scene().to_view(doc(), FreeCAD.Vector(20, 0, 12)).Length < 1e-6, "the view follows the zero point")
    layout().panel.select_entry("setup", job().Name)
    r = rows()
    check(r.get("From the default 0-Point") == "X+20 Y+0 Z+0, A+0 B+90 C+0", "setup details: {}".format(r.get("From the default 0-Point")))  # fmt: skip
    check(r.get("Tool axis", "").startswith("X+"), "tool axis: {}".format(r.get("Tool axis")))
    stock = tuple(round(c, 6) for c in cam().stock_bounds(job()))
    check(stock == (-1.0, -11.0, -41.0, 12.0, 11.0, 1.0), "the same block from the wall: {}".format(stock))
    side = contour((1, 0, 0), -2.0)
    SEEN["side"] = side.Name
    check(not engine().parked(side), "a contour on the wall counts from the new zero point")
    check(len(side.Path.Commands) > 4, "and has a path")
    check(drawn_at(side) == (20.0, 0.0, 12.0), "drawn on the active zero point: {}".format(drawn_at(side)))
    layout().panel.select_entry("operation", top.Name)
    later(600, step6)


@safe
def step6():
    from avangardecam.ui import project_panel

    top, side = doc().getObject(SEEN["top"]), doc().getObject(SEEN["side"])
    view_ = layout().panel.view
    check(type(view_).__name__ == "ParkedView", "details of the top contour: where it counts from ({})".format(type(view_).__name__))  # fmt: skip
    check(rows().get("Counts from") == "the default 0-Point", "from the default: {}".format(rows().get("Counts from")))
    check(view_.findChild(QtWidgets.QPushButton, "AvangardeCamMakeZeroActiveButton") is not None, "with a button to go there")
    shot("02_other_zero_point")
    menu = project_panel.operation_menu(side)
    action = next(a for a in menu.actions() if a.objectName() == "AvangardeCamMakeZeroActive")
    check(action.text() == "Make 0-Point active" and not action.isEnabled(), "menu of the wall contour: its zero point is the active one")  # fmt: skip
    menu = project_panel.operation_menu(top)
    SEEN["menu"] = menu
    action = next(a for a in menu.actions() if a.objectName() == "AvangardeCamMakeZeroActive")
    check(action.isEnabled(), "menu of the top contour: Make 0-Point active")
    action.trigger()
    later(1000, step7)


@safe
def step7():
    from avangardecam import handlers
    from avangardecam.post import machines

    top, side = doc().getObject(SEEN["top"]), doc().getObject(SEEN["side"])
    check(zero() == (0.0, 0.0, 12.0) and axis() == (0.0, 0.0, 1.0), "the zero point is the top contour's: {} {}".format(zero(), axis()))  # fmt: skip
    check(not engine().parked(top) and engine().parked(side), "the wall contour waits now")
    check(undo_tip() == "Undo: Make 0-Point active (Ctrl+Z)", "one undo step: {}".format(undo_tip()))
    check(item_text(side) == side.Label + "  (other 0-Point)", "list: {}".format(item_text(side)))
    check(type(layout().panel.view).__name__ == "ContourView", "the top contour's values are back: {}".format(type(layout().panel.view).__name__))  # fmt: skip
    stock = tuple(round(c, 6) for c in cam().stock_bounds(job()))
    check(stock == (-21.0, -11.0, -12.0, 21.0, 11.0, 1.0), "the block as before: {}".format(stock))
    # the program
    path = handlers.export_nc(os.path.join(OUT, "op_zero_soraluce.H"), machines.SORALUCE_T35)
    check(path is not None, "exported for the Soraluce")
    text = open(path, "rb").read().decode("iso-8859-1") if path else ""
    check("PLANE SPATIAL SPA0. SPB90. SPC0. STAY COORD ROT" in text, "the tilted plane of the wall contour")
    check("CYCL DEF 7.1  X+20.\r\n" in text and "CYCL DEF 7.3  Z+0.\r\n" in text, "its datum shift")
    check("PLANE SPATIAL SPA0. SPB0. SPC0. STAY COORD ROT" in text, "the top contour on the preset")
    check(text.count("TOOL CALL 21 ") == 2, "each operation calls its tool")
    check(zero() == (0.0, 0.0, 12.0) and not engine().parked(top) and engine().parked(side), "the export leaves the zero point")
    check(undo_tip() == "Undo: Make 0-Point active (Ctrl+Z)", "and no undo step: {}".format(undo_tip()))
    later(700, lambda: close_modal("refused"))
    refused = handlers.export_nc(os.path.join(OUT, "op_zero_bridgeport.H"), machines.BRIDGEPORT_V1000)
    check(refused is None, "the Bridgeport postprocessor refuses the turned zero point")
    check("turned zero point" in (SEEN.get("refused") or ""), "and says why: {}".format(SEEN.get("refused")))
    button("cam_move_zero").click()
    later(800, step8)


@safe
def step8():
    check(part("5X").isChecked(), "Move 0-Point again: 5 axes still ticked (kept for 5-axis work)")
    check(tuple(window().turn()) == (0.0, 0.0, 0.0), "no turn before a pick: {}".format(window().turn()))
    part("X").setProperty("rawValue", 5.0)
    window().accept()
    later(800, step9)


@safe
def step9():
    from avangardecam import handlers
    from avangardecam.post import machines

    top, side = doc().getObject(SEEN["top"]), doc().getObject(SEEN["side"])
    check(zero() == (5.0, 0.0, 12.0), "moved 5 along X: {}".format(zero()))
    check(engine().parked(top) and engine().parked(side), "both contours wait")
    cam().set_active(side, False)
    path = handlers.export_nc(os.path.join(OUT, "op_zero_bridgeport.H"), machines.BRIDGEPORT_V1000)
    text = open(path, "rb").read().decode("iso-8859-1") if path else ""
    check(path is not None and "CYCL DEF 7" not in text, "the Bridgeport program of the top contour alone: no shift")
    cam().set_active(side, True)
    button("cam_set_default_zero").click()
    message = mw().statusBar().currentMessage()
    check(message == "Setup 1: this zero point is the default one now.", "Set 0-Point as default: {}".format(message))
    check(engine().at_default(job()), "the default zero point is here")
    check(undo_tip() == "Undo: Set 0-Point as default (Ctrl+Z)", "one undo step: {}".format(undo_tip()))
    check(tuple(round(c, 6) for c in engine().operation_zero(top).origin) == (-5.0, 0.0, 0.0), "the top contour is shifted from it now")
    layout().ribbon.undo_button.click()
    later(800, step10)


@safe
def step10():
    check(not engine().at_default(job()), "Undo: the default is the first one again")
    check(tuple(round(c, 6) for c in engine().default_zero(job()).Base) == (0.0, 0.0, 12.0), "on the top, in the middle")
    button("cam_reset_zero").click()
    message = mw().statusBar().currentMessage()
    check(message == "Setup 1: zero point back on its default one.", "Reset 0-Point: {}".format(message))
    check(zero() == (0.0, 0.0, 12.0) and engine().at_default(job()), "the zero point is back: {}".format(zero()))
    check(undo_tip() == "Undo: Reset 0-Point (Ctrl+Z)", "one undo step: {}".format(undo_tip()))
    top, side = doc().getObject(SEEN["top"]), doc().getObject(SEEN["side"])
    check(not engine().parked(top) and engine().parked(side), "the top contour is live again")
    # editing the wall contour goes to its zero point first
    from avangardecam import handlers

    later(1200, lambda: close_modal("edit"))
    handlers.edit_operation(side)
    check(SEEN.get("edit") == "Edit " + side.Label, "Edit opens the contour's window: {}".format(SEEN.get("edit")))
    check(axis() == (1.0, 0.0, 0.0) and not engine().parked(side), "on its own zero point: {}".format(axis()))
    shot("03_edit_on_its_zero_point")
    # the setup itself moves from its default zero point only
    later(1200, lambda: close_modal("rotate"))
    later(2500, step11)
    button("cam_rotate_zero_90").click()  # its message waits for the click that closes it


@safe
def step11():
    said = SEEN.get("rotate") or mw().statusBar().currentMessage()
    check("not its default one" in said, "Rotate 0-Point away from the default is refused: {}".format(said))
    check(axis() == (1.0, 0.0, 0.0), "the zero point stays")
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
