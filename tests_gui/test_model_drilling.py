# Drilling of holes clicked in the model (GUI test): the two Ø4.5 holes
# through the test model, clicked on their walls (real mouse events in the
# isometric view; Shift+click adds the second, takes it away and adds it
# again). The Drilling window: the model and its holes, From the model on
# (the depth field off, 1 mm out under through holes), the shop's Ø4.5 drill
# (T47) suggested in the material of the drill used last, a drill of another
# size warned about. The drilling keeps the click order, drills each
# hole through from its top; the details switch From the model off and on
# (undo); the NC program calls cycle 205 on the holes; a second drilling
# starts with the setup's Ø4.5 drill; save and reopen.
#
# Run like test_layout.py (see README.md).
import math
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_model_drilling.txt"), "w")
FAILURES = []
SAVED = os.path.join(OUT, "model_drilling.FCStd")
TIP = 2.25 / math.tan(math.radians(59))  # of a Ø4.5 drill, 118°


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


def geometry():
    from avangardecam.engine import geometry as g

    return g


def handlers():
    from avangardecam import handlers as h

    return h


def operations():
    from avangardecam.model import operations as o

    return o


def doc():
    return FreeCAD.ActiveDocument


def body():
    return cam().models(doc())[0]


def view():
    return FreeCADGui.ActiveDocument.ActiveView


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


def click(point, modifiers=QtCore.Qt.NoModifier):
    """A real left click of the mouse on the 3D view at a part point."""
    widget = view().graphicsView().viewport()
    from avangardecam.ui import scene as _scene

    x, y = view().getPointOnScreen(_scene.to_view(doc(), point))  # the view is in the setup's coordinates
    pos = QtCore.QPointF(x, widget.height() - y)  # Coin counts from the bottom
    log("  click at", pos, modifiers)
    events = (
        (QtCore.QEvent.MouseMove, QtCore.Qt.NoButton, QtCore.Qt.NoButton),
        (QtCore.QEvent.MouseButtonPress, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton),
        (QtCore.QEvent.MouseButtonRelease, QtCore.Qt.LeftButton, QtCore.Qt.NoButton),
    )
    for kind, button, buttons in events:
        event = QtGui.QMouseEvent(kind, pos, widget.mapToGlobal(pos), button, buttons, modifiers)
        QtWidgets.QApplication.sendEvent(widget, event)
        QtWidgets.QApplication.processEvents()


def selection():
    return [(s.Object.Name, [n.split(".")[-1] for n in s.SubElementNames]) for s in FreeCADGui.Selection.getSelectionEx()]


def variant(number, material):
    from avangardecam import tool_library_path
    from avangardecam.model import library

    return next(e for e in library.load(tool_library_path()) if e.number == number and e.workpiece_material == material)


def t40(material="Aluminium"):
    return variant(40, material)


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


def nc_text():
    from avangardecam.post import heidenhain

    return heidenhain.write(cam().nc_program(doc(), "TEST"))


def params():
    from avangardecam import params as p

    return p()


def on_wall(x, y, z=10.5, radius=2.25):
    """A point of the wall of the hole at (x, y) the camera sees, 1.5 mm under
    the top, beside the hole's axis on the screen (a drilling's path is there)."""
    d = view().getViewDirection()
    across = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 50).multVec(FreeCAD.Vector(d.x, d.y, 0))
    across.normalize()
    return FreeCAD.Vector(x, y, z) + across * radius


def picked():
    """(x of each hole picked, in order) from the 3D selection."""
    import Part

    xs = []
    for s in FreeCADGui.Selection.getSelectionEx():
        for name in s.SubElementNames:
            element = s.Object.Shape.getElement(name.split(".")[-1])
            surface = getattr(element, "Surface", None) or getattr(element, "Curve", None)
            xs.append(round(surface.Center.x, 3) if surface is not None else None)
    return xs


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    params().SetString("LastDrillingTool", t40("Aluminium").id)  # a drill used before, in aluminium
    handlers().import_step(STEP)
    later(1500, step2)


@safe
def step2():
    view().viewIsometric()
    later(1500, step3)


@safe
def step3():
    view().fitAll()
    QtWidgets.QApplication.processEvents()
    FreeCADGui.Selection.clearSelection()
    click(on_wall(15, 0))
    check(picked() == [15.0], "the right hole's wall clicked: {} {}".format(picked(), selection()))
    click(on_wall(-15, 0), QtCore.Qt.ShiftModifier)
    check(picked() == [15.0, -15.0], "Shift+click adds the left hole: {}".format(picked()))
    click(on_wall(-15, 0), QtCore.Qt.ShiftModifier)
    check(picked() == [15.0], "Shift+click again takes it away: {}".format(picked()))
    click(on_wall(-15, 0), QtCore.Qt.ShiftModifier)
    check(picked() == [15.0, -15.0], "and adds it again: {}".format(picked()))
    shot("01_holes_clicked")
    modal(dialog1)
    handlers().drilling()
    later(500, step4)


def dialog1(dialog):
    check(dialog.objectName() == "AvangardeCamDrillingDialog", "drilling window opens")
    labels = [w.text() for w in dialog.findChildren(QtWidgets.QLabel)]
    check("Model:" in labels and body().Label in labels, "the window names the model")
    holes = field(dialog, "AvangardeCamDrillingHoles").text()
    check(holes == "2: Ø4.5 through → Ø4.5 through", "holes in the click order, through: {}".format(holes))
    from_model = field(dialog, "AvangardeCamDrillingFromModel")
    check(from_model is not None and from_model.isChecked(), "From the model on")
    check(not field(dialog, "AvangardeCamDrillingDepth").isEnabled(), "its depth field off")
    check(not field(dialog, "AvangardeCamDrillingDepthTo").isEnabled(), "to the full diameter")
    through = field(dialog, "AvangardeCamDrillingThrough")
    check(through.isEnabled() and abs(float(through.property("rawValue")) - 1.0) < 1e-9, "1 mm out under through holes")
    tool = field(dialog, "AvangardeCamDrillingTool").currentText()
    check(tool.startswith("T47  NX Boor 4.5mm Alu"), "a Ø4.5 drill in the material used last: {}".format(tool))
    fit = field(dialog, "AvangardeCamDrillingFit")
    check(not fit.isVisible(), "it fits the holes")
    tip = field(dialog, "AvangardeCamDrillingTip").text()
    wanted = "{:.3f} mm deep in the deepest hole (point {:.3f} mm)".format(13 + TIP, TIP)
    check(tip == wanted, "the tip: {}".format(tip))
    dialog.use(t40())
    check(fit.isVisible() and "Ø6.8" in fit.text() and "Ø4.5" in fit.text(), "T40 does not fit: {}".format(fit.text()))
    dialog.use(variant(47, "Aluminium"))
    check(not fit.isVisible(), "T47 fits again")
    shot("02_drilling_dialog", whole_screen=True)
    dialog.accept()


@safe
def step4():
    global OP
    ops = cam().operations(cam().find_job(doc()))
    check(len(ops) == 1, "one drilling made")
    OP = ops[0]
    found = cam().drilling_of(OP)
    check(found is not None and found[0] is body(), "a drilling of the model")
    check(found is not None and found[1].depth_mm is None, "as deep as the model has the holes: {}".format(found and found[1]))
    holes = [(round(x, 3), round(y, 3)) for x, y, _d in cam().drilling_holes(OP)]
    check(holes == [(15.0, 0.0), (-15.0, 0.0)], "drilled in the click order: {}".format(holes))
    check(int(OP.ToolController.ToolNumber) == 47, "with T47")
    zs = sorted({round(c.Parameters["Z"], 3) for c in OP.Path.Commands if c.Name in ("G73", "G81", "G82", "G83")})
    check(zs == [round(-13 - TIP, 3)], "through the 12 mm part, 1 mm out, and the point: {}".format(zs))
    r = rows()
    check(r.get("Model") == body().Label, "details: the model {}".format(r.get("Model")))
    check(r.get("Holes") == "2: Ø4.5 through → Ø4.5 through", "details: holes {}".format(r.get("Holes")))
    check(field(panel().view, "AvangardeCamDrillingFromModel").isChecked(), "details: From the model")
    shot("03_drilling_details")
    field(panel().view, "AvangardeCamDrillingFromModel").setChecked(False)
    later(800, step5)


@safe
def step5():
    drilling = cam().drilling_of(OP)[1]
    check(drilling.depth_mm == -10.0, "details: own depth, the field's -10 mm: {}".format(drilling.depth_mm))
    check(field(panel().view, "AvangardeCamDrillingDepth").isEnabled(), "details: the depth field on")
    doc().undo()
    later(800, step6)


@safe
def step6():
    check(cam().drilling_of(OP)[1].depth_mm is None, "undo: from the model again")
    check(field(panel().view, "AvangardeCamDrillingFromModel").isChecked(), "details follow the undo")
    text = nc_text()
    blocks = [line.split(" ", 1)[1] for line in text.split("\r\n") if line and not line.startswith(" ")]
    calls = [b for b in blocks if b.startswith("CYCL CALL POS")]
    check(calls == ["CYCL CALL POS X+15. Y+0. Z0 FMAX M3 M8", "CYCL CALL POS X-15. Y+0. Z0 FMAX"], "program: holes in the click order {}".format(calls))  # fmt: skip
    check("    Q201=-{:.3f}    ;DIEPTE ~".format(13 + TIP) in text, "program: Q201 through the part")
    # a second drilling starts with the setup's Ø4.5 drill
    FreeCADGui.Selection.clearSelection()
    click(on_wall(-15, 0))
    check(picked() == [-15.0], "the left hole clicked again: {}".format(selection()))
    modal(dialog2)
    handlers().drilling()
    later(500, step7)


SECOND = []


def dialog2(dialog):
    SECOND.append(dialog)
    tool = field(dialog, "AvangardeCamDrillingTool").currentText()
    check(tool.startswith("T47 ") and "new in" not in tool, "the setup's Ø4.5 drill: {}".format(tool))
    dialog.reject()


@safe
def step7():
    check(len(SECOND) == 1, "a second drilling window opened")
    check(len(cam().operations(cam().find_job(doc()))) == 1, "cancel makes nothing")
    doc().saveAs(SAVED)
    FreeCAD.closeDocument(doc().Name)
    FreeCAD.openDocument(SAVED)
    later(2000, step8)


@safe
def step8():
    op = cam().operations(cam().find_job(doc()))[0]
    holes = [(round(x, 3), round(y, 3)) for x, y, _d in cam().drilling_holes(op)]
    check(holes == [(15.0, 0.0), (-15.0, 0.0)], "reopened: the click order stays {}".format(holes))
    handlers()._select("operation", op.Name)
    QtWidgets.QApplication.processEvents()
    check(rows().get("Holes") == "2: Ø4.5 through → Ø4.5 through", "reopened: the details of the drilling")
    shot("04_reopened")
    finish()


def finish():
    log("FAILURES:", len(FAILURES))
    for text in FAILURES:
        log("  ", text)
    log("done")
    LOG.close()
    params().SetString("ToolLibraryFile", "")
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)
    QtCore.QTimer.singleShot(200, mw().close)


# start as on a new profile: no values remembered from earlier work
avangardecam.forget_last_values()
later(4000, step1)
