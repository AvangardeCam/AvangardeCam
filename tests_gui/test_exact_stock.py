# GUI test: the stock with allowances around the model's exact box. A plate
# with a round top of R 515 at each end of a base 2400 long (as the user's
# part), from STEP (AC_EXACT_STEP: a part of one's own, its top at Z 515):
# drawn in the GUI, FreeCAD's BoundBox comes from the triangles, under the
# arc; the stock 1 mm over the top is 1 mm over the arc's top all the same
# (engine.exact_box), also after a zero point moved and an allowance typed.
#
# Run like test_project.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_exact_stock.txt"), "w")
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


def near(values, wanted, tol=1e-6):
    return all(abs(a - b) < tol for a, b in zip(values, wanted))


@safe
def step1():
    import Part

    mw().setGeometry(0, 0, 1920, 1080)
    V = FreeCAD.Vector
    # a plate 250 thick with a round top (half a cylinder of R 515 lying
    # along Y), as the end plates of the user's part; imported from STEP as
    # the user does (File > Import STEP)
    def plate(y):
        arch = Part.makeCylinder(515, 250, V(0, y, 0), V(0, 1, 0)).common(Part.makeBox(1030, 250, 515, V(-515, y, 0)))
        return arch.fuse(Part.makeBox(1030, 250, 645, V(-515, y, -645)))

    # two of them on a base 2400 long, as the user's part (the triangles drawn
    # are coarser on a larger part)
    part = plate(-1000).fuse(plate(750)).fuse(Part.makeBox(1030, 2400, 100, V(-515, -1200, -745))).removeSplitter()
    path = os.path.join(OUT, "arch.step")
    part.exportStep(path)
    path = os.environ.get("AC_EXACT_STEP") or path  # a part of one's own (top at Z 515)
    from avangardecam import handlers

    handlers.import_step(path)
    FreeCADGui.SendMsgToActiveView("ViewFit")
    later(1500, step2)


@safe
def step2():
    doc = FreeCAD.ActiveDocument
    part = cam().models(doc)[0]
    drawn = part.Shape.BoundBox
    log("  drawn BoundBox", drawn, "exact", part.Shape.optimalBoundingBox(False, False))
    # FreeCAD does not always put a corner of the triangles under the top
    # (the user's part: 1.44 mm under it; this one: on it), so only said
    log("  drawn top {:.3f}, {} the exact one".format(drawn.ZMax, "UNDER" if drawn.ZMax < 515 - 0.05 else "on"))
    job = cam().find_job(doc)
    b = cam().stock_bounds(job)
    log("  stock", b, "zero", cam().zero(job))
    top = cam().zero(job).inverse().multVec(FreeCAD.Vector(0, 0, 515)).z  # the arch's top in the setup
    check(abs(b.z_max - (top + 1.0)) < 1e-6, "the stock 1 mm over the arch's top: {:.4f} (top {:.4f})".format(b.z_max, top))
    check(abs((b.x_max - b.x_min) - 1032.0) < 1e-6, "1030 + 2 × 1 mm wide: {:.4f}".format(b.x_max - b.x_min))
    from avangardecam.model import stock as model_stock

    doc.openTransaction("allowance")
    cam().set_stock(job, model_stock.BoxStock(1, 1, 1, 1, 0, 3))
    doc.commitTransaction()
    b = cam().stock_bounds(job)
    check(abs(b.z_max - (top + 3.0)) < 1e-6, "3 mm typed: 3 mm over the top: {:.4f}".format(b.z_max))
    from avangardecam.engine import stock_size

    m = stock_size.models_bounds(job)
    check(abs(m.z_max - top) < 1e-6, "the model's size in the details from its exact box: top {:.4f}".format(m.z_max))
    shot("exact_stock_01")
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
