# Sketch lines GUI test: the extracted sketch is selected at once, drawn
# green and thick, red when selected; clicks on its lines in the 3D view
# (real mouse events) win over the model's edges under them, and Contour
# tooling follows the clicked lines in the order they were clicked.
# Blender-like picking: Shift+click adds, Ctrl+click the shortest way,
# Alt+click a loop. Arrows in the middle of the selected lines show the
# tool's direction; a plain click on one turns its chain round. The tool
# compensation and approach menus in the dialog and in the details (RL,
# arc radius, undo); another tool from the library in the details; the
# passes in XY and Z; the selected operation's path red; its right click
# menu (edit, switch off, hide).
#
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
import Part
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_lines.txt"), "w")
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



def close_to(a, b, tol=1e-6):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def picking():
    from avangardecam.ui import picking as p

    return p


def view():
    return FreeCADGui.ActiveDocument.ActiveView


def middle(edge):
    return edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)


def quarter(edge):
    """A point of the line away from its direction arrow."""
    return edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) / 4.0)


def click(point, modifiers=QtCore.Qt.NoModifier):
    """A real left click of the mouse on the 3D view at a part point."""
    widget = view().graphicsView().viewport()
    x, y = view().getPointOnScreen(scene().to_view(doc(), point))  # the view is in the setup's coordinates
    pos = QtCore.QPointF(x, widget.height() - y)  # Coin counts from the bottom
    log("  click at", pos, modifiers, "coin", (x, y))
    infos = view().getObjectsInfo((int(x), int(y))) or []
    log("  under it:", [(i.get("Object"), i.get("Component")) for i in infos])
    events = (
        (QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
        (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
        (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton),
    )
    for kind, button, buttons in events:
        # the mouse comes to the line first, as a hand does
        event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button, buttons, modifiers)
        QtWidgets.QApplication.sendEvent(widget, event)
        QtWidgets.QApplication.processEvents()


def selection():
    return [(s.Object.Name, [n.split(".")[-1] for n in s.SubElementNames]) for s in FreeCADGui.Selection.getSelectionEx()]


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    top = face((0, 0, 1), lambda f: (round(f.BoundBox.ZMax, 6), f.Area))
    select_face(top)
    handlers().extract_boundary()
    later(800, step3)


@safe
def step3():
    from avangardecam import profile

    global SKETCH, LINE_A, LINE_B
    sketches = [o for o in doc().Objects if o.TypeId == "Sketcher::SketchObject"]
    check(len(sketches) == 1, "one sketch made")
    SKETCH = sketches[0]
    check(selection() == [(SKETCH.Name, [])], "the new sketch is selected at once: {}".format(selection()))
    vo = SKETCH.ViewObject
    check(close_to(vo.LineColor[:3], scene().SKETCH_COLOR, 1e-3), "sketch lines are green: {}".format(vo.LineColor))
    check(vo.LineWidth > body().ViewObject.LineWidth, "sketch lines thicker than the model's: {} > {}".format(vo.LineWidth, body().ViewObject.LineWidth))
    colors = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View")
    check(colors.GetUnsigned("SelectionColor") == profile.SELECTION_COLOR, "selected is red")
    view().viewIsometric()
    view().fitAll()
    later(1500, step3b)


@safe
def step3b():
    shot("01_sketch_selected_red")
    FreeCADGui.Selection.clearSelection()
    # two straight lines that meet, long enough to click
    edges = SKETCH.Shape.Edges
    lines = sorted(
        ((e.Length, i) for i, e in enumerate(edges, start=1) if e.Curve.TypeId == "Part::GeomLine"), reverse=True
    )
    global LINE_A, LINE_B, START
    for _length, i in lines:
        a = edges[i - 1]
        for _l2, j in lines:
            b = edges[j - 1]
            if j == i or b.Length < 5:
                continue
            ends_a = [v.Point for v in a.Vertexes]
            ends_b = [v.Point for v in b.Vertexes]
            shared = [p for p in ends_a if any(p.distanceToPoint(q) < 1e-6 for q in ends_b)]
            if shared:
                LINE_A, LINE_B = "Edge{}".format(i), "Edge{}".format(j)
                START = next(p for p in ends_a if p.distanceToPoint(shared[0]) > 1e-6)
                break
        else:
            continue
        break
    log("  lines:", LINE_A, LINE_B, "start:", START)
    later(300, step4)


@safe
def step4():
    shot("02_sketch_green")
    click(middle(SKETCH.Shape.getElement(LINE_A)))
    later(500, step5)


@safe
def step5():
    log("  after click:", selection())
    check(selection() == [(SKETCH.Name, [LINE_A])], "a click on the line selects the sketch line, not the model edge")
    click(middle(SKETCH.Shape.getElement(LINE_B)), QtCore.Qt.ShiftModifier)
    later(500, step6)


def direction():
    from avangardecam.ui import direction as d

    return d


def arrow_towards(line, point):
    """The drawn arrow of the line points towards point (part coordinates)."""
    names = picking().selected_lines()[1]
    to_part = SKETCH.Placement
    for name, at, way in geometry().line_arrows(SKETCH, names, direction().backwards(SKETCH)):
        if name == line:
            return to_part.Rotation.multVec(way).dot(point - to_part.multVec(at)) > 0
    raise AssertionError("no arrow on " + line)


def shared_point():
    a, b = SKETCH.Shape.getElement(LINE_A), SKETCH.Shape.getElement(LINE_B)
    return next(p.Point for p in a.Vertexes if any(p.Point.distanceToPoint(q.Point) < 1e-6 for q in b.Vertexes))


@safe
def step6():
    log("  after shift+click:", selection())
    check(picking().selected_lines() == (SKETCH, [LINE_A, LINE_B]), "Shift+click adds the second line, in click order")
    shown = sorted(line for _d, _s, line, _p, _c in direction()._State.shown)
    check(shown == sorted([LINE_A, LINE_B]), "an arrow on each selected line: {}".format(shown))
    check(arrow_towards(LINE_A, shared_point()), "the first line's arrow points to the second line")
    check(not arrow_towards(LINE_B, shared_point()), "the second line's arrow points away from the first")
    shot("03_two_lines_red")
    click(middle(SKETCH.Shape.getElement(LINE_A)))  # on the arrow
    later(500, step6a)


@safe
def step6a():
    check(selection() == [(SKETCH.Name, [LINE_A, LINE_B])], "a click on an arrow keeps the selection: {}".format(selection()))
    check(direction().backwards(SKETCH) == {LINE_A, LINE_B}, "the click turned the chain round")
    check(not arrow_towards(LINE_A, shared_point()) and arrow_towards(LINE_B, shared_point()), "the arrows point the other way")
    check(direction()._State.hovered is not None, "the arrow under the mouse is highlighted")
    shot("03a_turned_round")
    click(middle(SKETCH.Shape.getElement(LINE_B)))  # turned back
    later(500, step6b)


@safe
def step6b():
    check(direction().backwards(SKETCH) == set(), "a click on the other arrow turns the chain back")
    check(arrow_towards(LINE_A, shared_point()), "the arrows point as clicked again")

    def fill(dialog):
        lines = dialog.findChild(QtWidgets.QLabel, "AvangardeCamContourLines").text()
        check(lines == "2: {} → {}".format(LINE_A, LINE_B), "dialog shows the picked lines: " + lines)
        check(dialog.pictures.shown == "contour_start.svg", "the window opens with its picture")
        dialog.passes.boxes["z_step_mm"].setFocus()
        check(dialog.pictures.shown == "contour_order_by_pass.svg", "in Z step the picture of the order: " + str(dialog.pictures.shown))
        dialog.passes.order.setCurrentIndex(dialog.passes.order.findData("levels"))
        check(dialog.pictures.shown == "contour_order_by_level.svg", "the picture follows the order chosen")
        dialog.passes.order.setCurrentIndex(dialog.passes.order.findData("passes"))
        dialog.use(t21_rvs())
        dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourDepth").setProperty("rawValue", -1.0)
        approach = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourApproach")
        approach.setCurrentIndex(approach.findData("none"))  # straight down on the first line
        dialog.accept()

    modal(fill)
    handlers().contour_tooling()
    later(1000, step7)


@safe
def step7():
    job = cam().find_job(doc())
    ops = cam().operations(job)
    check(len(ops) == 1, "one contour made")
    op = ops[0]
    check(cam().contour_lines(op) == [LINE_A, LINE_B], "the contour follows the clicked lines")
    first = next(c for c in op.Path.Commands if c.Name == "G1" and "X" in c.Parameters)
    start = SKETCH.Placement.inverse().multVec(START)  # sketch = setup coordinates here
    log("  first cut at", first.Parameters, "expected", start)
    check(close_to((first.Parameters["X"], first.Parameters["Y"]), (start.x, start.y)), "the tool starts on the first clicked line, away from the second")
    check(rows().get("Lines") == "2: {} → {}".format(LINE_A, LINE_B), "details show the lines: {}".format(rows().get("Lines")))
    shot("04_contour")

    later(300, step7b)


def touches(a, b):
    ea, eb = SKETCH.Shape.getElement(a), SKETCH.Shape.getElement(b)
    return any(p.Point.distanceToPoint(q.Point) < 1e-6 for p in ea.Vertexes for q in eb.Vertexes)


@safe
def step7b():
    global FAR
    lines = ["Edge{}".format(i) for i, e in enumerate(SKETCH.Shape.Edges, start=1) if e.Curve.TypeId == "Part::GeomLine"]
    FAR = next(n for n in lines if n != LINE_A and not touches(n, LINE_A))
    # the clicked lines are still selected: their middle is an arrow now
    click(quarter(SKETCH.Shape.getElement(LINE_A)))
    later(400, lambda: click(middle(SKETCH.Shape.getElement(FAR)), QtCore.Qt.ControlModifier))
    later(1000, step7c)


@safe
def step7c():
    lines = picking().selected_lines()[1]
    log("  after ctrl+click on", FAR, ":", lines)
    check(len(lines) == 3 and lines[0] == LINE_A and lines[2] == FAR and touches(lines[1], LINE_A) and touches(lines[1], FAR),
          "Ctrl+click adds the shortest way to the line")  # fmt: skip
    shot("05_ctrl_path")
    click(middle(SKETCH.Shape.getElement(LINE_B)), QtCore.Qt.AltModifier)
    later(600, step7d)


@safe
def step7d():
    lines = picking().selected_lines()[1]
    log("  after alt+click on", LINE_B, ":", lines)
    check(len(lines) == 4 and lines[0] == LINE_B and len(set(lines)) == 4, "Alt+click selects the loop, starting with the line")
    shot("06_alt_loop")
    click(middle(SKETCH.Shape.getElement(LINE_B)), QtCore.Qt.ShiftModifier)
    later(600, step7e)


@safe
def step7e():
    lines = picking().selected_lines()[1]
    log("  after shift+click on", LINE_B, "again:", lines)
    check(len(lines) == 3 and LINE_B not in lines, "Shift+click on a selected line takes it away")
    # a model edge picked under a sketch line goes over to the sketch line
    FreeCADGui.Selection.clearSelection()
    mid = middle(SKETCH.Shape.getElement(LINE_B))
    global MODEL_EDGE
    MODEL_EDGE = next(
        "Edge{}".format(i) for i, e in enumerate(body().Shape.Edges, start=1) if e.distToShape(Part.Vertex(mid))[0] < 1e-6
    )
    at = scene().to_view(doc(), mid)  # a click gives the point where the view draws it
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, MODEL_EDGE, at.x, at.y, at.z)
    later(500, step8)


@safe
def step8():
    log("  model edge", MODEL_EDGE, "->", selection())
    check(selection() == [(SKETCH.Name, [LINE_B])], "a model edge under a sketch line becomes the sketch line")
    FreeCADGui.Selection.clearSelection()
    low = min(body().Shape.Edges, key=lambda e: middle(e).z)
    name = next("Edge{}".format(i) for i, e in enumerate(body().Shape.Edges, start=1) if e.isSame(low))
    m = middle(low)
    FreeCADGui.Selection.addSelection(doc().Name, body().Name, name, m.x, m.y, m.z)
    global LOW_EDGE
    LOW_EDGE = name
    later(500, step9)


@safe
def step9():
    name = LOW_EDGE
    check(selection() == [(body().Name, [name])], "a model edge without a sketch line stays selected: {}".format(selection()))
    check(direction()._State.shown == [], "no arrows without selected sketch lines")
    FreeCADGui.Selection.clearSelection()
    click(middle(SKETCH.Shape.getElement(LINE_A)))
    later(500, step10)


@safe
def step10():
    check(selection() == [(SKETCH.Name, [LINE_A])], "one line selected anew: {}".format(selection()))
    check(direction().backwards(SKETCH) == set(), "a line selected anew runs as drawn")
    click(middle(SKETCH.Shape.getElement(LINE_A)))  # on its arrow
    later(500, step11)


@safe
def step11():
    check(direction().backwards(SKETCH) == {LINE_A}, "a single line turned round")
    edge = SKETCH.Shape.getElement(LINE_A)
    check(arrow_towards(LINE_A, edge.valueAt(edge.FirstParameter)), "its arrow points to the line's start")

    def fill(dialog):
        lines = dialog.findChild(QtWidgets.QLabel, "AvangardeCamContourLines").text()
        check(lines == "1: {}".format(LINE_A), "dialog shows the line: " + lines)
        box = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourCompensation")
        texts = [box.itemText(i) for i in range(box.count())] if box else []
        log("  compensation:", texts)
        check([box.itemData(i) for i in range(box.count())] == ["off", "left", "right"], "compensation menu: off, RL, RR")
        box.setCurrentIndex(box.findData("off"))
        approach = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourApproach")
        lead = dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourLeadRadius")
        check(approach.currentData() == "none" and not approach.isEnabled(), "off: straight down, no other approach")
        check(not lead.isEnabled(), "no approach: no radius")
        # Advanced: the contour side and Off with arc
        advanced = dialog.findChild(QtWidgets.QCheckBox, "AvangardeCamContourAdvanced")
        side = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourArcSide")
        offset = passes_box(dialog, "XYOffset")
        check(not advanced.isChecked() and not side.isVisible(), "Advanced closed at first")
        check(not offset.isEnabled(), "off without Advanced: no XY offset (no side)")
        advanced.setChecked(True)
        check(side.isVisible() and offset.isEnabled(), "Advanced: the contour side and the XY offset")
        check(not passes_box(dialog, "XYWidth").isEnabled(), "still no XY passes without compensation")
        check([box.itemData(i) for i in range(box.count())] == ["off", "off_arc", "left", "right"], "Advanced: off with arc in the menu")  # fmt: skip
        box.setCurrentIndex(box.findData("off_arc"))
        check(approach.currentData() == "arc" and not approach.isEnabled(), "off with arc: on an arc")
        check(abs(lead.property("rawValue") - 4.5) < 1e-9 and lead.isEnabled(), "approach radius: 8 mm tool + 0.5 mm clear")
        check(side.isEnabled() and side.currentData() == "left", "contour side: left at first")
        side.setCurrentIndex(side.findData("right"))
        contour = dialog.contour()
        check((contour.compensation, contour.approach, contour.arc_side) == ("off", "arc", "right"), "off with arc on the right: {}".format(contour))  # fmt: skip
        shot("07_contour_dialog", whole_screen=True)
        offset.setProperty("rawValue", 0.3)  # a chamfer mill's centre 0.3 mm right of the lines
        contour = dialog.contour()
        check((contour.offset_xy_mm, contour.arc_side) == (0.3, "right"), "off with arc and an XY offset: {}".format(contour))  # fmt: skip
        box.setCurrentIndex(box.findData("left"))
        check(approach.isEnabled() and side.currentData() == "left", "RL: the approach to choose, the contour side left")
        side.setCurrentIndex(side.findData("right"))
        check(box.currentData() == "right", "contour side right: RR")
        box.setCurrentIndex(box.findData("left"))
        check(side.currentData() == "left", "RL: contour side left again")
        box.setCurrentIndex(box.findData("off_arc"))
        advanced.setChecked(False)
        check(not offset.isEnabled() and dialog.contour().offset_xy_mm == 0.0, "Advanced closed: no XY offset")
        check(box.currentData() == "off" and box.findData("off_arc") < 0, "Advanced closed: off with arc becomes off")
        check(dialog.contour().approach == "none" and not lead.isEnabled(), "off again: straight down")
        dialog.accept()

    modal(fill)
    handlers().contour_tooling()
    later(1000, step12)


@safe
def step12():
    job = cam().find_job(doc())
    op = cam().operations(job)[-1]
    edge = SKETCH.Shape.getElement(LINE_A)
    end = SKETCH.Placement.inverse().multVec(edge.valueAt(edge.LastParameter))
    first = next(c for c in op.Path.Commands if c.Name == "G1" and "X" in c.Parameters)
    log("  first cut at", first.Parameters, "expected", end)
    check(close_to((first.Parameters["X"], first.Parameters["Y"]), (end.x, end.y)), "the turned line is cut from its end")
    check([h.Reversed for h in cam().helper_objects(op)] == [True], "the contour keeps the direction")
    global OP, FIRST_CUT
    OP, FIRST_CUT = op, (first.Parameters["X"], first.Parameters["Y"])
    check(panel().current_entry() == ("operation", op), "the new contour is in the details")
    box = panel().view.compensation
    check(box.currentData() == "off", "details: compensation off")
    check(panel().view.approach.currentData() == "none", "details: no approach")
    box.setCurrentIndex(box.findData("left"))  # applied at once
    later(800, step13)


def plunge_distance():
    """How far from the line's start the tool goes down."""
    first = next(c for c in OP.Path.Commands if c.Name == "G1" and "X" in c.Parameters)
    return abs(complex(first.Parameters["X"], first.Parameters["Y"]) - complex(*FIRST_CUT))


def drawn(op):
    """{kind: points} of the path AvangardeCam draws for op, and whether
    FreeCAD's own lines (the tool centre) are shown."""
    from pivy import coin

    root = op.ViewObject.RootNode
    kinds = {}
    for i in range(root.getNumChildren()):
        group = root.getChild(i)
        if group.getName() != scene()._DRAWING_NAME:
            continue
        for j in range(group.getNumChildren()):
            node = group.getChild(j)
            coords = next(node.getChild(k) for k in range(node.getNumChildren())
                          if node.getChild(k).isOfType(coin.SoCoordinate3.getClassTypeId()))  # fmt: skip
            kinds[str(node.getName())] = [FreeCAD.Vector(*p.getValue()) for p in coords.point.getValues()]
    search = coin.SoSearchAction()
    search.setName(scene()._FREECAD_LINES_NAME)
    search.setSearchingAll(True)
    search.apply(root)
    shown = search.getPath() is None or search.getPath().getTail().whichChild.getValue() != coin.SO_SWITCH_NONE
    return kinds, shown


def t21_rvs():
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")


def nc_text():
    from avangardecam.post import heidenhain

    return heidenhain.write(cam().nc_program(doc(), "TEST"))


@safe
def step13():
    contour = cam().contour_of(OP)[1]
    check(contour.compensation == "left", "details: compensation left (RL) set")
    radius = OP.ToolController.Tool.Diameter.Value / 2.0
    log("  plunge", plunge_distance(), "from the line's start")
    check(abs(plunge_distance() - radius) < 1e-6, "no approach: the tool centre goes down beside the line's start")
    check(abs(cam().path_summary(OP)[1] + 1) < 1e-6, "still at Z-Depth -1")
    text = nc_text()
    check(" RL FMAX\r\n" in text and text.count(" RL ") == 1, "RL switched on once, above the part")
    kinds, shown = drawn(OP)
    log("  drawn:", {k: len(v) for k, v in kinds.items()}, "FreeCAD's lines shown:", shown)
    check(not shown and set(kinds) == {"rapid", "feed", "link"}, "drawn: the tool centre down, its edge along the lines")
    link = kinds.get("link", [])
    check(len(link) == 4 and abs((link[0] - link[1]).Length - radius) < 1e-4, "yellow from the centre to the edge and back")
    shot("07b_compensation_without_approach")
    check(not panel().view.lead.isEnabled(), "details: no approach radius without an approach")
    panel().view.approach.setCurrentIndex(panel().view.approach.findData("arc"))
    later(800, step13b)


@safe
def step13b():
    check(cam().contour_of(OP)[1].approach == "arc", "details: approach on an arc set")
    view = panel().view
    check(view.lead.isEnabled() and abs(view.lead.property("rawValue") - 4.5) < 1e-9, "details: approach radius 4.5 mm")
    check(abs(plunge_distance() - 4.5) < 1e-6, "the tool goes down in the arc's centre, 0.5 mm clear of the line")
    text = nc_text()
    check(" RL FQ31\r\n" in text and text.count(" RL ") == 1, "RL switched on by the line to the arc")
    kinds, shown = drawn(OP)
    check(not shown and set(kinds) == {"rapid", "feed"}, "drawn: on the arcs the program starts in the centre, no link")
    shot("08_compensation_left")
    view.lead.setProperty("rawValue", 6.0)
    later(1500, step13c)


@safe
def step13c():
    check(abs(cam().lead_radius(OP) - 6.0) < 1e-9 and abs(plunge_distance() - 6.0) < 1e-6, "approach radius typed: 6 mm")
    doc().undo()
    later(800, step13d)


@safe
def step13d():
    check(abs(cam().lead_radius(OP) - 4.5) < 1e-9, "undo: the default radius again")
    check(abs(panel().view.lead.property("rawValue") - 4.5) < 1e-9, "details follow the undo")
    doc().undo()
    doc().undo()
    later(800, step14)


@safe
def step14():
    contour = cam().contour_of(OP)[1]
    check((contour.compensation, contour.approach) == ("off", "none"), "undo: compensation off, no approach again")
    kinds, shown = drawn(OP)
    check(shown and not kinds, "off: FreeCAD draws the tool centre again")
    check(panel().view.compensation.currentData() == "off", "details follow the undo")
    check(" RL " not in nc_text(), "undo: no RL in the program")

    # another tool from the library for the contour
    def pick(picker):
        entry = next(e for e in picker.entries if e.number == 8)
        picker.select_ids({entry.id})
        picker.findChild(QtWidgets.QPushButton, "AvangardeCamUseTool").click()

    modal(pick)
    panel().view.findChild(QtWidgets.QPushButton, "AvangardeCamChangeTool").click()  # until picked
    later(800, step15)


@safe
def step15():
    check(int(OP.ToolController.ToolNumber) == 8, "Change tool: T8 for the contour")
    check(rows().get("Tool", "").startswith("T8 "), "details show T8: {}".format(rows().get("Tool")))
    check(" TOOL CALL 8 Z " in nc_text(), "the program calls T8")
    check(sorted(t.number for t in cam().project_tools(cam().setup_of(OP))) == [8, 21], "T8 added to the setup")
    doc().undo()
    later(800, step16)


@safe
def step16():
    check(int(OP.ToolController.ToolNumber) == 21, "undo: T21 again")
    # FreeCAD cannot undo making a tool: T8 stays in the setup, whole
    tools = cam().project_tools(cam().setup_of(OP))
    check([t.number for t in tools] == [8, 21] and all(t.controller.Tool for t in tools), "undo: T8 stays, whole")
    later(300, step17)


def passes_box(owner, name):
    return owner.findChild(QtWidgets.QWidget, "AvangardeCamContour" + name)


@safe
def step17():
    view = panel().view
    check(not passes_box(view, "XYWidth").isEnabled(), "details: no XY passes without compensation")
    check(passes_box(view, "ZStep").isEnabled(), "details: Z steps without compensation")
    check(rows().get("Passes") == "one", "details: one pass: {}".format(rows().get("Passes")))
    view.compensation.setCurrentIndex(view.compensation.findData("left"))  # applied at once
    later(800, step17b)


@safe
def step17b():
    view = panel().view
    check(passes_box(view, "XYWidth").isEnabled(), "details: XY passes with compensation")
    for name, value in (("ZStep", 0.5), ("XYWidth", 6.0), ("XYStep", 4.0), ("FinishXY", 0.1)):
        passes_box(view, name).setProperty("rawValue", value)  # applied together after a pause
    later(1500, step17c)


@safe
def step17c():
    contour = cam().contour_of(OP)[1]
    log("  passes", contour)
    check((contour.z_step_mm, contour.xy_width_mm, contour.xy_step_mm, contour.finish_xy_mm) == (0.5, 6.0, 4.0, 0.1),
          "details: the passes typed")  # fmt: skip
    check(contour.xy_offsets() == [3.05, 0.1, 0.0] and contour.levels() == [-0.5, -1.0], "3 XY passes by 2 Z levels")
    passes = rows().get("Passes")
    check(passes == "3 XY × 2 Z = 6 cuts, the last XY one finishing", "details: {}".format(passes))
    check(nc_text().count("L Z-0.5 FQ30") == 3, "the program goes down to Z-0.5 in each XY pass")
    shot("10_passes")
    doc().undo()
    doc().undo()
    later(800, step17d)


@safe
def step17d():
    contour = cam().contour_of(OP)[1]
    check((contour.compensation, contour.z_step_mm, contour.xy_width_mm) == ("off", None, 0.0), "undo: one pass again")
    view = panel().view
    check(abs(passes_box(view, "XYWidth").property("rawValue")) < 1e-9, "details follow the undo")
    check(not passes_box(view, "XYWidth").isEnabled(), "details: XY off again")
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, SKETCH.Name, LINE_B)

    def fill(dialog):
        dialog.use(t21_rvs())
        box = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourCompensation")
        check(not passes_box(dialog, "XYWidth").isEnabled() or box.currentData() != "off", "dialog: XY off without compensation")  # fmt: skip
        box.setCurrentIndex(box.findData("left"))
        check(passes_box(dialog, "XYWidth").isEnabled(), "dialog: XY passes with compensation")
        approach = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourApproach")
        approach.setCurrentIndex(approach.findData("none"))
        dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourDepth").setProperty("rawValue", -1.0)
        for name, value in (("ZStep", 0.5), ("XYWidth", 3.0), ("XYStep", 2.0), ("XYOffset", -0.02)):
            passes_box(dialog, name).setProperty("rawValue", value)
        order = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourOrder")
        check(order.currentData() == "passes", "dialog: by XY pass by default")
        order.setCurrentIndex(order.findData("levels"))
        summary = dialog.findChild(QtWidgets.QLabel, "AvangardeCamContourPasses").text()
        check(summary == "2 XY × 2 Z = 4 cuts", "dialog: {}".format(summary))
        dialog.accept()

    modal(fill)
    handlers().contour_tooling()
    later(1000, step18)


@safe
def step18():
    op = cam().operations(cam().find_job(doc()))[-1]
    contour = cam().contour_of(op)[1]
    log("  dialog passes", contour)
    check(op is not OP and contour.xy_offsets() == [1.49, -0.02], "the last pass 0.02 mm past the line")
    check(contour.order == "levels" and contour.cuts() == [(0, -0.5), (1, -0.5), (0, -1.0), (1, -1.0)], "by Z level")

    def look(dialog):
        values = {n: passes_box(dialog, n).property("rawValue") for n in ("ZStep", "XYWidth", "XYStep", "XYOffset")}
        check(values == {"ZStep": 0.5, "XYWidth": 3.0, "XYStep": 2.0, "XYOffset": -0.02}, "dialog remembers the passes: {}".format(values))  # fmt: skip
        order = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourOrder")
        check(order.currentData() == "levels", "dialog remembers the order")
        dialog.reject()

    modal(look)
    handlers().contour_tooling()
    later(800, step19)


def red(op):
    """The points of op's path drawn red (FreeCAD's own path stays)."""
    root = op.ViewObject.RootNode
    for i in range(root.getNumChildren()):
        node = root.getChild(i)
        if node.getName() == scene()._HIGHLIGHT_NAME:
            from pivy import coin

            coords = next(node.getChild(j) for j in range(node.getNumChildren())
                          if node.getChild(j).isOfType(coin.SoCoordinate3.getClassTypeId()))  # fmt: skip
            return [FreeCAD.Vector(*p.getValue()) for p in coords.point.getValues()]
    return []


def red_is_cutting(op):
    """op's red points are those of its cutting moves (coin keeps floats):
    with radius compensation where the tool's edge cuts."""
    points = red(op)
    drawing = cam().path_drawing(op)
    if drawing is not None:
        cutting = [p for kind, line in drawing if kind == cam().DRAW_FEED for p in line]
    else:
        cutting = [p for line in scene()._cutting_lines(op.Path) for p in line]
    return len(points) == len(cutting) and all(p.isEqual(q, 1e-4) for p, q in zip(points, cutting))


@safe
def step19():
    new = cam().operations(cam().find_job(doc()))[-1]
    check(panel().current_entry() == ("operation", new), "the new contour is selected in the list")
    points = red(new)
    check(points and not red(OP), "its path red, the other one's not")
    check(red_is_cutting(new) and abs(min(p.z for p in points) + 1.0) < 1e-6, "only its cutting moves red, down to Z-1")
    panel().select_entry("operation", OP.Name)
    check(red(OP) and not red(new), "another operation clicked: its path red")
    panel().view.compensation.setCurrentIndex(panel().view.compensation.findData("left"))  # a new path
    later(800, step19b)


@safe
def step19b():
    new = cam().operations(cam().find_job(doc()))[-1]
    check(cam().contour_of(OP)[1].compensation == "left", "details: compensation changed")
    check(red_is_cutting(OP) and not red(new), "the changed path is red")
    shot("11_path_red")
    doc().undo()
    panel().select_entry("sketch", SKETCH.Name)
    check(not red(OP) and not red(new), "a sketch selected: no path red")
    later(300, step20)


def op_menu(op, button=QtCore.Qt.RightButton):
    """Click an operation in the list; its menu, or None. A right click is
    a press and release and the context menu event the window system adds."""
    from PySide6 import QtTest

    tree = panel().tree
    item = panel().find_item(("operation", op.Name))
    tree.scrollToItem(item)
    at = tree.visualItemRect(item).center()
    QtTest.QTest.mouseClick(tree.viewport(), button, QtCore.Qt.NoModifier, at)
    if button == QtCore.Qt.RightButton:
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, at, tree.viewport().mapToGlobal(at))
        QtWidgets.QApplication.sendEvent(tree.viewport(), event)
    menu = QtWidgets.QApplication.activePopupWidget()
    return menu if menu is not None and menu.objectName() == "AvangardeCamOperationMenu" else None


def menu_action(menu, name):
    return next(a for a in menu.actions() if a.objectName() == name)


def op_text(op):
    return panel().find_item(("operation", op.Name)).text(0)


@safe
def step20():
    new = cam().operations(cam().find_job(doc()))[-1]
    check(op_menu(new, QtCore.Qt.LeftButton) is None, "a left click opens no menu")
    check(panel().current_entry() == ("operation", new), "it only selects the operation")
    menu = op_menu(OP)
    check(menu is not None and menu.isVisible(), "a right click on an operation opens its menu")
    check(panel().current_entry() == ("operation", OP), "and selects it")
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    check(texts == ["Edit...", "Activate geometry", "Make 0-Point active", "Switch off", "Hide in 3D", "Delete"], "menu: {}".format(texts))
    later(400, step20a)


@safe
def step20a():
    menu = QtWidgets.QApplication.activePopupWidget()
    check(menu is not None and menu.objectName() == "AvangardeCamOperationMenu", "the menu stays open")
    tree = panel().tree
    entry = tree.visualItemRect(panel().find_item(("operation", OP.Name)))
    corner = tree.viewport().mapFromGlobal(menu.geometry().topLeft())
    check(corner == entry.center(), "where it was clicked")
    shot("12_operation_menu", whole_screen=True)
    menu_action(menu, "AvangardeCamHideOperation").trigger()
    menu.close()
    check(not OP.ViewObject.Visibility and scene().hidden(OP), "Hide in 3D: its path hidden")
    check(op_text(OP).endswith("(hidden)"), "the list says hidden: {}".format(op_text(OP)))
    check(OP.Active and " TOOL CALL 21 Z " in nc_text(), "a hidden operation stays in the program")
    menu = op_menu(OP)
    check(menu_action(menu, "AvangardeCamHideOperation").text() == "Show in 3D", "menu: Show in 3D")
    menu_action(menu, "AvangardeCamHideOperation").trigger()
    menu.close()
    check(OP.ViewObject.Visibility and not scene().hidden(OP) and op_text(OP) == OP.Label, "Show in 3D: shown again")
    check(red_is_cutting(OP), "and red, still selected")
    menu = op_menu(OP)
    menu_action(menu, "AvangardeCamSwitchOperation").trigger()
    menu.close()
    later(500, step20b)


@safe
def step20b():
    new = cam().operations(cam().find_job(doc()))[-1]
    check(not OP.Active and cam().path_summary(OP) == (0, None), "Switch off: no path")
    check(op_text(OP).endswith("(off)"), "the list says off: {}".format(op_text(OP)))
    check(rows().get("Path") == "off: not in the program or the simulation", "details: {}".format(rows().get("Path")))
    labels = [o.label for o in cam().nc_program(doc(), "TEST").operations()]
    check(OP.Label not in labels and new.Label in labels, "left out of the program: {}".format(labels))
    menu = op_menu(OP)
    check(menu_action(menu, "AvangardeCamSwitchOperation").text() == "Switch on", "menu: Switch on")
    menu.close()
    doc().undo()
    later(500, step20c)


@safe
def step20c():
    check(OP.Active and abs(cam().path_summary(OP)[1] + 1.0) < 1e-6, "undo: on again, with its path")
    check(op_text(OP) == OP.Label, "the list follows the undo")

    def edit(dialog):
        check(dialog.windowTitle() == "Edit " + OP.Label, "Edit opens the window: {}".format(dialog.windowTitle()))
        depth = dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourDepth")
        box = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamContourTool")
        check(abs(depth.property("rawValue") + 1.0) < 1e-9 and box.currentText().startswith("T21 "), "with its values and tool")  # fmt: skip
        check(dialog.findChild(QtWidgets.QLabel, "AvangardeCamContourLines").text() == "1: Edge3", "and its lines")
        depth.setProperty("rawValue", -2.0)
        passes_box(dialog, "ZStep").setProperty("rawValue", 1.0)
        dialog.accept()

    modal(edit)
    menu = op_menu(OP)
    menu_action(menu, "AvangardeCamEditOperation").trigger()  # until the window closes
    later(800, step20d)


@safe
def step20d():
    contour = cam().contour_of(OP)[1]
    check((contour.z_depth_mm, contour.z_step_mm) == (-2.0, 1.0), "edited: Z-Depth -2 by 1 mm steps")
    check(abs(cam().path_summary(OP)[1] + 2.0) < 1e-6 and red_is_cutting(OP), "its path follows, red")
    doc().undo()
    later(500, step20e)


@safe
def step20e():
    contour = cam().contour_of(OP)[1]
    check((contour.z_depth_mm, contour.z_step_mm) == (-1.0, None), "undo: the edit in one step")

    def look(dialog):
        depth = dialog.findChild(QtWidgets.QWidget, "AvangardeCamContourDepth")
        check(abs(depth.property("rawValue") + 1.0) < 1e-9, "a new contour still starts with the values used last, not the edited ones")  # fmt: skip
        dialog.reject()

    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc().Name, SKETCH.Name, LINE_B)
    modal(look)
    handlers().contour_tooling()
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
