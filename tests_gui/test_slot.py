# Slot milling GUI test on a plate made here (60 x 40 x 20, a blind slot
# 30 x 10 along X, 6 deep, its ends at (-15, 8) and (5, 8); a through slot
# 18 x 8 along Y, its ends at (20, -12) and (20, -2); saved as STEP and
# imported, the zero on the middle of its top). CAM > Slot with nothing
# clicked only says what to click. A wall of the blind slot clicked: the
# window (the slot, the depth from the model, no tool: OK refused, a drill
# refused, T7 Ø10 as wide as the slot: along the centre only, T5 Ø6: the
# Z levels and passes as typed, a depth through the floor refused, the
# automatic approach radius), the slot milling, the details (RR live,
# undo), the program with RL, Edit..., two slots (Shift+click) starting
# with the values and the tool used last; save and reopen, Activate
# geometry.
#
# Run like test_layout.py (see README.md); AC_STEP is not used.
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_slot.txt"), "w")
FAILURES = []
STEP = os.path.join(OUT, "slot_plate.step")
SAVED = os.path.join(OUT, "slot.FCStd")


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


def shot(name, whole_screen=False):
    path = os.path.join(OUT, name + ".png")
    if whole_screen:  # with the windows over the main window
        QtGui.QGuiApplication.primaryScreen().grabWindow(0).save(path)
    else:
        mw().grab().save(path)
    log("screenshot", path)


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def engine():
    from avangardecam.engine import slot

    return slot


def handlers():
    from avangardecam import handlers as h

    return h


def slot():
    from avangardecam.model import slot as s

    return s


def scene():
    from avangardecam.ui import scene as s

    return s


def drawn(op):
    """Feed points of the path AvangardeCam draws for op, and whether
    FreeCAD's own lines (the tool centre) are shown."""
    from pivy import coin

    root = op.ViewObject.RootNode
    points = []
    for i in range(root.getNumChildren()):
        group = root.getChild(i)
        if group.getName() != scene()._DRAWING_NAME:
            continue
        for j in range(group.getNumChildren()):
            node = group.getChild(j)
            if str(node.getName()) != cam().DRAW_FEED:
                continue
            coords = next(node.getChild(k) for k in range(node.getNumChildren())
                          if node.getChild(k).isOfType(coin.SoCoordinate3.getClassTypeId()))  # fmt: skip
            points += [FreeCAD.Vector(*p.getValue()) for p in coords.point.getValues()]
    search = coin.SoSearchAction()
    search.setName(scene()._FREECAD_LINES_NAME)
    search.setSearchingAll(True)
    search.apply(root)
    shown = search.getPath() is None or search.getPath().getTail().whichChild.getValue() != coin.SO_SWITCH_NONE
    return points, shown


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


def nc_blocks():
    from avangardecam.post import heidenhain

    text = heidenhain.write(cam().nc_program(doc(), "TEST"))
    return [line.split(" ", 1)[1] for line in text.split("\r\n") if line and not line.startswith(" ")]


def raw(widget):
    return float(widget.property("rawValue"))


def lowest(op):
    return round(cam().path_summary(op)[1], 6)


def _stadium(start, end, width, z0, z1):
    import Part

    a, b = FreeCAD.Vector(start[0], start[1], z0), FreeCAD.Vector(end[0], end[1], z0)
    u = b - a
    u.normalize()
    n = FreeCAD.Vector(-u.y, u.x, 0) * (width / 2.0)
    wire = Part.Wire(
        [
            Part.LineSegment(a - n, b - n).toShape(),
            Part.Arc(b - n, b + u * (width / 2.0), b + n).toShape(),
            Part.LineSegment(b + n, a + n).toShape(),
            Part.Arc(a + n, a - u * (width / 2.0), a - n).toShape(),
        ]
    )
    return Part.Face(wire).extrude(FreeCAD.Vector(0, 0, z1 - z0))


def make_step():
    import Part

    shape = Part.makeBox(60, 40, 20, FreeCAD.Vector(-30, -20, 0))
    shape = shape.cut(_stadium((-15, 8), (5, 8), 10.0, 14.0, 21.0))
    shape = shape.cut(_stadium((20, -12), (20, -2), 8.0, -1.0, 21.0)).removeSplitter()
    shape.exportStep(STEP)


def face(test):
    for i, f in enumerate(body().Shape.Faces, start=1):
        if test(f):
            return "Face{}".format(i)
    raise AssertionError("no such face")


def wall():
    """The wall of the blind slot at Y+3 (part coordinates)."""
    return face(lambda f: f.findPlane() is not None and f.BoundBox.YLength < 1e-9 and abs(f.BoundBox.YMin - 3.0) < 1e-6)  # fmt: skip


def floor():
    return face(lambda f: f.findPlane() is not None and f.BoundBox.ZLength < 1e-9 and abs(f.BoundBox.ZMin - 14.0) < 1e-6)  # fmt: skip


def through_end():
    return face(lambda f: hasattr(f.Surface, "Radius") and abs(f.Surface.Center.x - 20) < 1e-6 and abs(f.Surface.Center.y + 2) < 1e-6)  # fmt: skip


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    make_step()
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    global WALL
    FreeCADGui.Selection.clearSelection()
    handlers().slot_milling()  # nothing clicked: no window
    check(QtWidgets.QApplication.activeModalWidget() is None, "nothing clicked: no window")
    message = mw().statusBar().currentMessage()
    check(message.startswith("Click a wall, a round end or the floor of a slot"), "it says what to click: " + message)
    WALL = wall()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, WALL)
    modal(dialog1)
    handlers().slot_milling()
    later(500, step3)


def dialog1(dialog):
    check(dialog.objectName() == "AvangardeCamSlotDialog", "the Slot milling window opens")
    slots = field(dialog, "AvangardeCamSlotSlots").text()
    check(slots == "Slot 30 × 10, 6 deep in {}".format(body().Label), "the slot: " + slots)
    depth = field(dialog, "AvangardeCamSlotDepth")
    check(raw(depth) == -6.0 and not depth.isEnabled(), "the depth from the model: -6")
    check(field(dialog, "AvangardeCamSlotFromModel").isChecked(), "From the model ticked")
    levels = field(dialog, "AvangardeCamSlotLevels")
    check(levels.text() == "Z -6.00 (1 level)", "the levels: " + levels.text())
    check(field(dialog, "AvangardeCamSlotTool").currentIndex() == -1, "no tool in the setup yet: none chosen")
    dialog.accept()
    message = field(dialog, "AvangardeCamSlotMessage").text()
    check(dialog.isVisible() and message.startswith("Choose a tool"), "OK without a tool refused: " + message)
    fit = field(dialog, "AvangardeCamSlotFit")
    dialog.use(variant(40, "Aluminium"))
    check(fit.isVisible() and "not an end mill" in fit.text(), "a drill: " + fit.text())
    dialog.accept()
    check(dialog.isVisible(), "a drill refused")
    passes = field(dialog, "AvangardeCamSlotPasses")
    dialog.use(variant(7, "Aluminium"))  # Ø10
    check(not fit.isVisible(), "Ø10 fits the slot 10 wide: " + fit.text())
    check("as wide as the tool" in passes.text(), "Ø10: along the centre only: " + passes.text())
    dialog.use(variant(5, "Aluminium"))  # Ø6
    check(not fit.isVisible(), "T5 fits: " + fit.text())
    check(field(dialog, "AvangardeCamSlotStepOverMm").text() == "= 3 mm", "50 % of Ø6")
    check(passes.text() == "Ramp to and fro, along the centre line; the walls finished with RL on 1 level", "Ø6: " + passes.text())  # fmt: skip
    field(dialog, "AvangardeCamSlotZStep").setProperty("rawValue", 3.0)
    field(dialog, "AvangardeCamSlotFinishXY").setProperty("rawValue", 0.2)
    check(levels.text() == "Z -3.00, -6.00 (2 levels)", "Z step 3: " + levels.text())
    check(passes.text() == "Ramp to and fro, along the centre line, 1 pass around it; the walls finished with RL on 2 levels", "with an allowance: " + passes.text())  # fmt: skip
    feeds = field(dialog, "AvangardeCamSlotFeeds").text()
    check(feeds.startswith("Z ") and "(ramps), XY " in feeds, "the feeds: " + feeds)
    field(dialog, "AvangardeCamSlotFromModel").setChecked(False)
    check(depth.isEnabled(), "the depth can be typed")
    depth.setProperty("rawValue", -7.0)
    check(fit.isVisible() and "goes through its floor" in fit.text(), "deeper than the floor: " + fit.text())
    field(dialog, "AvangardeCamSlotFromModel").setChecked(True)
    check(raw(depth) == -6.0 and not fit.isVisible(), "back to the depth from the model")
    field(dialog, "AvangardeCamSlotAdvanced").setChecked(True)
    lead = field(dialog, "AvangardeCamSlotLeadRadius")
    check(raw(lead) == 3.5 and not lead.isEnabled(), "the approach radius: R3 + 0.5 = {}".format(raw(lead)))
    for _repaint in range(5):
        QtWidgets.QApplication.processEvents()
    shot("01_slot_dialog", whole_screen=True)
    dialog.accept()


@safe
def step3():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1 and ops[0].Label == "Slot milling 1", "one slot milling made: {}".format([o.Label for o in ops]))
    OP = ops[0]
    found = engine().slot_milling_of(OP)
    wanted = slot().SlotMilling(z_step_mm=3.0, finish_xy_mm=0.2)
    check(found == (body(), wanted), "its values: {}".format(found))
    check(lowest(OP) == -6.0, "down to the floor, Z-6: {}".format(lowest(OP)))
    check(FreeCADGui.Selection.getSelection() == [], "the model is not left selected")
    r = rows()
    check(r.get("Slots") == "Slot 30 × 10, 6 deep in {}".format(body().Label), "details: slots {}".format(r.get("Slots")))
    check(r.get("Tool", "").startswith("T5 "), "details: tool {}".format(r.get("Tool")))
    check(r.get("Z levels") == "Z -3.00, -6.00 (2 levels)", "details: levels {}".format(r.get("Z levels")))
    check(r.get("Path", "").endswith("down to Z -6.00 mm"), "details: path {}".format(r.get("Path")))
    blocks = nc_blocks()
    check("*- Slot Milling" in blocks, "program: the slot milling")
    check(sum(1 for b in blocks if " RL " in b) == 2, "program: RL onto the wall on both levels")
    check("C X-5. Y+3. DR+" in blocks, "program: onto the middle of the wall at Y+3")
    points, shown = drawn(OP)
    walls = sorted({round(p.y, 3) for p in points if abs(p.y - 8.0) > 2.0})
    check(not shown and walls[:1] == [3.0] and walls[-1:] == [13.0],
          "drawn: the finishing pass on the walls at Y+3 and Y+13 (RL), FreeCAD's tool centre hidden: {} {}".format(walls[:1] + walls[-1:], shown))  # fmt: skip
    check(round(min(p.y for p in points if abs(p.y - 8.0) <= 2.0), 3) == 6.2 if points else False,
          "drawn: the rough passes where the tool centre goes, 0.2 mm from the finishing")  # fmt: skip
    shot("02_slot_details")
    side = field(panel().view, "AvangardeCamSlotSide")
    side.setCurrentIndex(side.findData("right"))
    later(2500, step4)


@safe
def step4():
    check(engine().slot_milling_of(OP)[1].compensation == "right", "details: RR applied")
    check(sum(1 for b in nc_blocks() if " RR " in b) == 2, "program: RR")
    doc().undo()
    later(1500, step5)


@safe
def step5():
    check(engine().slot_milling_of(OP)[1].compensation == "left", "undo: RL again")
    side = field(panel().view, "AvangardeCamSlotSide")
    check(side.currentData() == "left", "details follow the undo")

    def edit(dialog):
        check(dialog.windowTitle() == "Edit " + OP.Label, "Edit opens the window: {}".format(dialog.windowTitle()))
        check(field(dialog, "AvangardeCamSlotTool").currentText().startswith("T5 "), "with its tool")
        check(raw(field(dialog, "AvangardeCamSlotZStep")) == 3.0, "with its values")
        field(dialog, "AvangardeCamSlotStepOver").setValue(40.0)
        ramp = field(dialog, "AvangardeCamSlotRamp")
        check(ramp.currentData() == "to_and_fro", "the ramp to and fro by default")
        ramp.setCurrentIndex(ramp.findData("contour"))
        passes = field(dialog, "AvangardeCamSlotPasses").text()
        check(passes.startswith("Ramp along the contour 1.8 mm from the centre line, once round;"), "passes: " + passes)
        dialog.accept()

    modal(edit)
    handlers().edit_operation(OP)  # until the window closes
    wanted = slot().SlotMilling(z_step_mm=3.0, finish_xy_mm=0.2, step_over_percent=40.0, ramp=slot().RAMP_CONTOUR)
    check(engine().slot_milling_of(OP)[1] == wanted, "edited: {}".format(engine().slot_milling_of(OP)[1]))
    blocks = nc_blocks()
    check(sum(1 for b in blocks if b.startswith("CP IPA+180. IZ-")) >= 4, "program: the ramp along the contour, helices")
    check(lowest(OP) == -6.0, "still down to the floor")
    points, shown = drawn(OP)
    check(not shown and min(round(p.y, 3) for p in points) == 3.0, "drawn as programmed, the walls at Y+3")
    later(1500, step6)


@safe
def step6():
    shot("03_contour_ramp")
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, through_end())
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, floor())

    def dialog2(dialog):
        slots = field(dialog, "AvangardeCamSlotSlots").text()
        check(slots == "2 slots in {}: 18 × 8, through; 30 × 10, 6 deep".format(body().Label), "two slots in click order: " + slots)  # fmt: skip
        tool = field(dialog, "AvangardeCamSlotTool").currentText()
        check(tool.startswith("T5 "), "the tool used last: " + tool)
        check(raw(field(dialog, "AvangardeCamSlotZStep")) == 3.0, "the values used last")
        check(field(dialog, "AvangardeCamSlotStepOver").value() == 50.0, "the values used last (not the edit)")
        check(raw(field(dialog, "AvangardeCamSlotDepth")) == -20.0, "the depth of the first slot: through, 20")
        dialog.reject()

    modal(dialog2)
    handlers().slot_milling()
    later(500, step7)


@safe
def step7():
    check(len(cam().operations(cam().find_job(doc()))) == 1, "Cancel makes nothing")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step8)


@safe
def step8():
    from avangardecam.ui import activate_geometry

    ops = cam().operations(cam().find_job(doc()))
    wanted = slot().SlotMilling(z_step_mm=3.0, finish_xy_mm=0.2, step_over_percent=40.0, ramp=slot().RAMP_CONTOUR)
    check([engine().slot_milling_of(o)[1] for o in ops] == [wanted], "reopened: the slot milling")
    ops[0].touch()
    doc().recompute()
    check(lowest(ops[0]) == -6.0, "reopened: the path again")
    handlers()._select("operation", ops[0].Name)
    QtWidgets.QApplication.processEvents()
    check(rows().get("Slots", "").startswith("Slot 30 × 10"), "reopened: the details {}".format(rows().get("Slots")))
    check(activate_geometry.activate(ops[0]), "Activate geometry")
    selected = [(s.ObjectName, list(s.SubElementNames)) for s in FreeCADGui.Selection.getSelectionEx("", 0)]
    check(selected == [(body().Name, [WALL])], "the wall it was made on selected: {}".format(selected))
    shot("04_reopened")
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
