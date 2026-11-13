# Stage 3 GUI test: setups, Snap-0-Point, Extract boundary edges and
# Contour tooling on real data, from the top and from the front (a second
# clamping). Checks the drawing (paths on the part, FreeCAD's axis cross on
# the zero point, the view in the active setup's coordinates), double-click
# in 3D, saving and reopening, the NC program
# (Heidenhain .H) of both setups, expert mode.
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
LOG = open(os.path.join(OUT, "test_setups.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "setups.FCStd")
NODE = "AvangardeCamZeroPoint"


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
    if whole_screen:
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


def geometry():
    from avangardecam.engine import geometry as g

    return g


def handlers():
    from avangardecam import handlers as h

    return h


def scene():
    from avangardecam.ui import scene as s

    return s


def doc():
    return FreeCAD.ActiveDocument


def body():
    return cam().models(doc())[0]


def face(normal, pick):
    """Name of the flat face of the body with this outward normal; pick
    chooses among several (key function, the largest value wins)."""
    shape = body().Shape
    n = FreeCAD.Vector(*normal)
    found = []
    for i, f in enumerate(shape.Faces, start=1):
        if f.findPlane() is None:
            continue
        if geometry().outward_normal(shape, f).getAngle(n) < 1e-6:
            found.append((pick(f), "Face{}".format(i)))
    return max(found)[1]


def select_face(name):
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, name)


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


def transform_of(obj):
    root = obj.ViewObject.RootNode
    node = root.getChild(0)
    if node.getName() != NODE:
        return None
    return node.translation.getValue().getValue()


def close_to(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


# -- top ---------------------------------------------------------------------------


@safe
def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    job = cam().find_job(doc())
    b = body()
    box = b.Shape.BoundBox
    log("  body bounds:", box)
    zero = cam().zero(job)
    check(close_to(zero.Base, (box.Center.x, box.Center.y, box.ZMax)), "setup 1 zero: top middle {}".format(zero.Base))
    check(b.ViewObject.Visibility, "the original model is shown")
    check(not job.Model.Group[0].ViewObject.Visibility, "the job's moved clone is hidden")
    check(close_to(transform_of(job.Stock), zero.Base), "stock drawn through the zero point")
    check(close_to(transform_of(job), zero.Base), "FreeCAD's axis cross sits on the zero point")
    texts = [panel().tree.topLevelItem(i).text(0) for i in range(panel().tree.topLevelItemCount())]
    check(texts == ["Model", "Sketches", "Setup 1 (active)"], "list: {}".format(texts))
    shot("01_setup1")

    global TOP
    TOP = face((0, 0, 1), lambda f: (round(f.BoundBox.ZMax, 6), f.Area))
    log("  top face:", TOP)
    check(
        not [o for o in doc().Objects if o.TypeId.startswith(("PartDesign::", "Sketcher::"))],
        "FreeCAD's default end mill left no shape body behind",
    )
    select_face(TOP)
    handlers().extract_boundary()
    later(800, step3)


@safe
def step3():
    sketches = [o for o in doc().Objects if o.TypeId == "Sketcher::SketchObject"]
    log("  sketches:", [(o.Name, o.Label) for o in sketches], "current:", panel().current_entry())
    check(len(sketches) == 1, "one sketch made")
    global SKETCH1
    SKETCH1 = sketches[0]
    current = panel().current_entry()
    check(current == ("sketch", SKETCH1), "the sketch is selected in the list")
    r = rows()
    log("  sketch details:", panel().view.rows())
    check(r.get("Faces the tool") == "Z+ (from the top)", "sketch faces the top")
    check(r.get("Setups") == "Setup 1", "sketch fits setup 1")
    shot("02_sketch")

    def fill(dialog):
        log("  modal:", dialog.objectName(), type(dialog).__name__, getattr(dialog, "text", lambda: "")())
        check(dialog.objectName() == "AvangardeCamContourDialog", "contour dialog opens")
        tool = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourTool")
        message = dialog.findChild(QtWidgets.QLabel, "AvangardeCamContourMessage")
        check(tool.count() == 0 and tool.currentIndex() == -1, "no tool yet: setup 1 has none, none used before")
        dialog.accept()
        check(dialog.isVisible() and "Choose a tool" in message.text(), "OK without a tool refused: " + message.text())
        picked = []

        def pick(picker):
            check(picker.objectName() == "AvangardeCamToolPicker", "Choose tool opens the tool library to pick from")
            entry = next(e for e in picker.entries if e.number == 21 and e.workpiece_material == "RVS")
            picker.select_ids({entry.id})
            shot("03_tool_picker", whole_screen=True)
            picker.findChild(QtWidgets.QPushButton, "AvangardeCamUseTool").click()
            picked.append(entry)

        modal(pick)
        dialog.findChild(QtWidgets.QPushButton, "AvangardeCamChooseTool").click()  # until picked
        log("  tool:", tool.currentText())
        check(picked and tool.currentText().startswith("T21") and "(RVS)" in tool.currentText(), "T21 RVS picked")
        hint = dialog.findChild(QtWidgets.QLabel, "AvangardeCamContourToolHint").text()
        check("not in Setup 1 yet" in hint, "it is added to the setup: " + hint)
        depth = dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourDepth")
        for wrong in (2.0, 0.5):  # above the sketch, above Start Z
            depth.setProperty("rawValue", wrong)
            dialog.accept()
            check(dialog.isVisible() and "not be above Start Z" in message.text(), "Z-Depth {} refused: {}".format(wrong, message.text()))  # fmt: skip
        start_z = dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourStartZ")
        check(start_z is not None and abs(start_z.property("rawValue")) < 1e-9, "Start Z 0: the sketch plane")
        depth.setProperty("rawValue", 0.0)  # on the sketch: one pass along Z0 (deburring)
        check(dialog.contour().validate().levels() == [0.0], "Start Z 0, Z-Depth 0: one pass on the sketch plane")
        start_z.setProperty("rawValue", 5.0)  # material above the sketch: Z-Depth +2 is fine now
        depth.setProperty("rawValue", 2.0)
        passes = dialog.findChild(QtWidgets.QLabel, "AvangardeCamContourPasses")
        check(dialog.contour().validate().levels() == [2.0] and passes.text() != "—", "Start Z 5, Z-Depth 2: one level")
        start_z.setProperty("rawValue", 0.0)
        depth.setProperty("rawValue", -2.0)
        shot("03_contour_dialog", whole_screen=True)
        dialog.accept()

    modal(fill)
    handlers().contour_tooling(SKETCH1)
    later(1000, step4)


@safe
def step4():
    job = cam().find_job(doc())
    ops = cam().operations(job)
    check(len(ops) == 1, "one operation in setup 1")
    global OP1
    OP1 = ops[0]
    tc = OP1.ToolController
    check(int(tc.ToolNumber) == 21 and tc.AvangardeMaterial == "RVS", "T21 RVS added to setup 1")
    moves, lowest = cam().path_summary(OP1)
    check(moves > 4 and abs(lowest + 2) < 1e-6, "path cuts at Z-2: {} moves, {}".format(moves, lowest))
    check(close_to(transform_of(OP1), cam().zero(job).Base), "the path is drawn on the part")
    check(OP1.ViewObject.Visibility, "the path is shown")
    check(panel().current_entry() == ("operation", OP1), "the operation is selected")
    r = rows()
    log("  contour details:", panel().view.rows())
    check(r.get("Lines at") == "Z 0.00 mm", "sketch plane at Z0")
    check(r.get("Path", "").endswith("deepest Z -2.00 mm"), "details show the depth")
    view = FreeCADGui.ActiveDocument.ActiveView
    view.viewIsometric()
    view.fitAll()
    shot("04_contour_top")
    panel().view.depth.setProperty("rawValue", -4.0)
    later(1500, step5)


@safe
def step5():
    check(abs(cam().path_summary(OP1)[1] + 4) < 1e-6, "Z-Depth typed in details: path at Z-4")
    doc().undo()
    later(800, step6)


@safe
def step6():
    check(abs(cam().path_summary(OP1)[1] + 2) < 1e-6, "undo: back to Z-2")
    check(abs(panel().view.depth.property("rawValue") + 2) < 1e-6, "details follow the undo")
    # above the zero: the material from Z+5, cut down to Z+1, typed in the details
    panel().view.start_z.setProperty("rawValue", 5.0)
    panel().view.depth.setProperty("rawValue", 1.0)
    later(1500, step6a)


@safe
def step6a():
    check(abs(cam().path_summary(OP1)[1] - 1) < 1e-6, "Start Z 5, Z-Depth 1 typed in details: path at Z+1")
    check(cam().contour_depths(OP1) == (5.0, 1.0), "the contour from Z+5 to Z+1")
    check(rows().get("Lines at") == "Z 0.00 mm", "the sketch plane stays at Z0")
    doc().undo()
    later(800, step6b)


@safe
def step6b():
    check(abs(cam().path_summary(OP1)[1] + 2) < 1e-6, "undo: back to Z-2 in one step")
    check(abs(panel().view.start_z.property("rawValue")) < 1e-6, "details follow the undo: Start Z 0")

    # double-click in 3D: FreeCAD's editor must not take over
    FreeCADGui.ActiveDocument.setEdit(OP1.Name)
    later(800, step7)


@safe
def step7():
    check(FreeCADGui.ActiveDocument.getInEdit() is None, "FreeCAD's operation editor closed again")
    check(not FreeCADGui.Control.activeDialog(), "no FreeCAD task dialog left")
    check(panel().current_entry() == ("operation", OP1), "double-click shows the operation in our panel")
    check(OP1 in cam().operations(cam().find_job(doc())), "the operation is still there")

    # -- the front: a second clamping -----------------------------------------------
    global FRONT
    FRONT = face((0, -1, 0), lambda f: (-round(f.BoundBox.YMin, 6), f.Area))
    log("  front face:", FRONT)
    select_face(FRONT)
    asked = []

    def answer(box):
        asked.append(box.text())
        log("  question:", box.text().replace("\n", " "))
        shot("05_snap_question", whole_screen=True)
        new = next(b for b in box.buttons() if b.text() == "New setup")
        new.click()

    modal(answer)
    handlers().snap_zero()
    check(len(asked) == 1, "Snap-0-Point on a setup with operations asks first")
    later(1000, step8)


@safe
def step8():
    jobs = cam().setups(doc())
    check([j.Label for j in jobs] == ["Setup 1", "Setup 2"], "setup 2 made: {}".format([j.Label for j in jobs]))
    setup2 = jobs[1]
    check(scene().active_setup(doc()) is setup2, "setup 2 is active")
    zero = cam().zero(setup2)
    box = body().Shape.BoundBox
    axis = geometry().tool_axis(zero)
    check(close_to(axis, (0, -1, 0)), "setup 2 tool comes from the front: {}".format(axis))
    check(abs(zero.Base.y - box.YMin) < 1e-6, "setup 2 zero on the front face: {}".format(zero.Base))
    check(abs(zero.Base.x - box.Center.x) < 1e-6 and abs(zero.Base.z - box.Center.z) < 1e-6, "setup 2 zero in the middle")
    check(not OP1.ViewObject.Visibility, "setup 1's path is hidden")
    check(close_to(cam().zero(jobs[0]).Base, (box.Center.x, box.Center.y, box.ZMax)), "setup 1 zero unchanged")
    r = rows()
    log("  setup 2 details:", panel().view.rows())
    check(r.get("Tool axis") == "Y− (from the front)", "details: tool from the front")
    # the view is in setup 2's coordinates: the front faces up, FreeCAD's Top is the machine's
    root = FreeCADGui.ActiveDocument.ActiveView.getSceneGraph()
    frames = [root.getChild(i) for i in range(root.getNumChildren()) if root.getChild(i).getName() == "AvangardeCamSetupFrame"]  # fmt: skip
    check(len(frames) == 1, "one setup frame on top of the view's scene")
    up = scene().view_placement(doc()).Rotation.multVec(FreeCAD.Vector(0, -1, 0))
    check(close_to(up, (0, 0, 1)), "the front faces up in the view: {}".format(up))
    check(close_to(scene().to_view(doc(), zero.Base), (0, 0, 0)), "the zero point at the view's origin")
    if frames:
        q = frames[0].rotation.getValue().getValue()
        check(FreeCAD.Rotation(*q).isSame(zero.Rotation.inverted(), 1e-6), "the frame is the inverse of the zero point")
    FreeCADGui.ActiveDocument.ActiveView.viewTop()
    later(1200, step8b)  # fit once the camera animation is over


@safe
def step8b():
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("06_setup2_front")
    select_face(FRONT)
    handlers().extract_boundary()
    later(800, step9)


@safe
def step9():
    global SKETCH2
    SKETCH2 = panel().current_entry()[1]
    check(SKETCH2 is not SKETCH1 and SKETCH2.TypeId == "Sketcher::SketchObject", "front sketch made")
    check(rows().get("Setups") == "Setup 2", "front sketch fits setup 2 only")

    def fill(dialog):
        tool = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourTool").currentText()
        check(tool.startswith("T21") and "(RVS)" in tool and "new in Setup 2" in tool, "setup 2 starts with the tool used last: " + tool)  # fmt: skip
        dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourDepth").setProperty("rawValue", -1.5)
        dialog.accept()

    modal(fill)
    handlers().contour_tooling(SKETCH2)
    later(1000, step10)


@safe
def step10():
    setup1, setup2 = cam().setups(doc())
    ops = cam().operations(setup2)
    # FreeCAD keeps labels unique in a document
    check(len(ops) == 1 and ops[0].Label == "Contour 2", "contour in setup 2: {}".format([o.Label for o in ops]))
    global OP2
    OP2 = ops[0]
    check(abs(cam().path_summary(OP2)[1] + 1.5) < 1e-6, "front path at Z-1.5 of setup 2")
    check(OP2.ViewObject.Visibility and not OP1.ViewObject.Visibility, "only the active setup's path is shown")
    check(close_to(transform_of(OP2), cam().zero(setup2).Base), "front path drawn on the part")
    check(rows().get("Tool") == "T21  Iscar Vingerfrees 8mm RVS (RVS)  Ø8", "tool named as in the library: {}".format(rows().get("Tool")))
    FreeCADGui.ActiveDocument.ActiveView.viewIsometric()
    later(1200, step10b)


@safe
def step10b():
    FreeCADGui.ActiveDocument.ActiveView.fitAll()
    shot("07_contour_front")
    setup1, _setup2 = cam().setups(doc())

    # clicking setup 1 in the list shows it again
    item = panel().find_item(("setup", setup1.Name))
    panel().tree.setCurrentItem(item)
    later(800, step11)


@safe
def step11():
    setup1, setup2 = cam().setups(doc())
    check(scene().active_setup(doc()) is setup1, "setup 1 active after clicking it")
    check(OP1.ViewObject.Visibility and not OP2.ViewObject.Visibility, "setup 1's path shown, setup 2's hidden")
    check(panel().find_item(("setup", setup1.Name)).text(0) == "Setup 1 (active)", "the list marks setup 1")
    shot("08_back_to_setup1")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step12)


@safe
def step12():
    jobs = cam().setups(doc())
    check([j.Label for j in jobs] == ["Setup 1", "Setup 2"], "reopened: two setups")
    op1 = cam().operations(jobs[0])[0]
    sketch, contour = cam().contour_of(op1)
    check(abs(contour.z_depth_mm + 2) < 1e-6, "reopened: Z-Depth -2 remembered")
    check(close_to(transform_of(op1), cam().zero(jobs[0]).Base), "reopened: path drawn on the part")
    check(close_to(geometry().tool_axis(cam().zero(jobs[1])), (0, -1, 0)), "reopened: setup 2 from the front")
    shot("09_reopened")

    path = handlers().export_nc(os.path.join(OUT, "bridge 1.h"))
    check(path == os.path.join(OUT, "bridge 1.h.H") or path == os.path.join(OUT, "bridge 1.h"), "NC program written: {}".format(path))
    with open(path, "rb") as f:
        text = f.read().decode("iso-8859-1")
    lines = text.split("\r\n")
    log("  NC program:", len(lines), "lines")
    check(lines[0] == "0 BEGIN PGM bridge_1 MM" and lines[-2].endswith(" END PGM bridge_1 MM") and lines[-1] == "",
          "program named after the file, CRLF: {} ... {}".format(lines[0], lines[-2]))  # fmt: skip
    check([l.split(" ", 1)[1] for l in lines if "Q339" in l] == ["   Q339=+1    ;REF.PUNT-NUMMER", "   Q339=+2    ;REF.PUNT-NUMMER"],
          "each setup on its own preset")  # fmt: skip
    check(sum(1 for l in lines if " TOOL CALL 21 Z " in l) == 1, "T21 called once for both setups")
    check(any(l.endswith(" L Z-2. R0 FQ30") for l in lines), "setup 1 plunges to Z-Depth -2 at the Z feed")
    FreeCADGui.activateWorkbench("CAMWorkbench")
    later(1500, step13)


@safe
def step13():
    job = scene().active_setup(doc())
    check(transform_of(cam().operations(job)[0]) is None, "expert mode: FreeCAD's own drawing")
    check(job.Model.Group[0].ViewObject.Visibility, "expert mode: the job's clone is shown")
    shot("10_expert_mode")
    FreeCADGui.activateWorkbench("AvangardeCamWorkbench")
    later(1500, step14)


@safe
def step14():
    job = scene().active_setup(doc())
    check(transform_of(cam().operations(job)[0]) is not None, "back in AvangardeCam: paths on the part again")
    check(body().ViewObject.Visibility and not job.Model.Group[0].ViewObject.Visibility, "back: original shown")
    shot("11_back")
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
