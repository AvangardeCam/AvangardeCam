# Cycle time GUI test: two contours on the top's boundary with one tool.
# Nothing is worked out by looking: the details of the setup and of each
# operation have a Time row with a link; the link works the times out, the
# rows show them (the total, then feed, rapid and tool change), the setup's
# the sum of its operations', the tool change only in the first; looking at
# other entries and hiding an operation keep them. CAM > Cycle time opens a
# table of them; an operation switched off makes them out of date in the
# rows and the window, Recalculate shows it switched off and the setup's
# time down by its time.
#
# Run like test_layout.py (see README.md).
import os
import re
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_cycle_time.txt"), "w")
FAILURES = []
OPS = []
BEFORE = {}  # the setup's and the second operation's time, both on


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


def handlers():
    from avangardecam import handlers as h

    return h


def panel():
    from avangardecam.ui.layout import LAYOUT

    return LAYOUT.panel


def doc():
    return FreeCAD.ActiveDocument


def job():
    return cam().find_job(doc())


def time_row(kind, obj):
    """The Time row's text in an entry's details."""
    panel().select_entry(kind, obj.Name)
    QtCore.QCoreApplication.processEvents()
    return dict(panel().view.rows()).get("Time", "")


def time_label():
    return panel().view.form.itemAt(0, QtWidgets.QFormLayout.FieldRole).widget()


def seconds(text):
    """The total at the start of a time: 7.2 s, 45 s, 1 min 05 s."""
    found = re.match(r"(?:(\d+) min )?(\d+(?:\.\d+)?) s", text)
    return None if found is None else int(found.group(1) or 0) * 60 + float(found.group(2))


def ui():
    from avangardecam.ui import cycle_time

    return cycle_time


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
    variant = next(e for e in library.load(tool_library_path()) if e.number == 21 and e.workpiece_material == "RVS")
    tc = cam().add_tool(job(), variant)
    OPS.append(cam().add_contour(job(), sketch, operations.Contour(-1.0), tc))
    OPS.append(cam().add_contour(job(), sketch, operations.Contour(-2.0), tc))
    doc().recompute()
    later(800, step3)


@safe
def step3():
    rows = [time_row("setup", job()), time_row("operation", OPS[0]), time_row("operation", OPS[1])]
    log("  before:", rows)
    check(all("not worked out yet" in r and "Work it out" in r for r in rows), "the rows offer to work it out")
    check(ui().stored(doc()) is None, "looking works nothing out")
    shot("01_not_worked_out")
    time_label().linkActivated.emit("work")
    later(800, step4)


@safe
def step4():
    check(ui().stored(doc()) is not None and not isinstance(ui().stored(doc()), Exception), "the link worked the times out")
    setup = time_row("setup", job())
    first, second = time_row("operation", OPS[0]), time_row("operation", OPS[1])
    log("  setup:", setup)
    log("  ops:", first, "|", second)
    check(seconds(setup) is not None and "feed" in setup and "rapid" in setup, "the setup's time: " + setup)
    check("tool change 1.5 s" in first and "tool change" not in second, "the tool change in the first operation only")
    total = (seconds(first) or 0) + (seconds(second) or 0)
    check(seconds(setup) is not None and abs(seconds(setup) - total) <= 1.0, "the setup's time is the operations' sum")
    check(seconds(first) and seconds(second), "each operation has its time")
    BEFORE.update(setup=seconds(setup), second=seconds(second), setup_text=setup.split(" (")[0])
    OPS[1].Visibility = False
    QtCore.QCoreApplication.processEvents()
    check(ui().stored(doc()) is not None, "looking at the entries and hiding one keep the times")
    shot("02_operation_time")
    handlers().cycle_time()
    later(1000, step5)


@safe
def step5():
    window = ui().window()
    check(window is not None, "Cycle time opens its window")
    rows = window.rows()
    log("  table:", rows)
    check(len(rows) == 4, "the table: the header, the setup and its two operations")
    check(rows[1][0] == job().Label and rows[1][2] == BEFORE["setup_text"], "the setup's row has its total")
    check([r[0] for r in rows[2:]] == [OPS[0].Label, OPS[1].Label], "the operations in their order")
    check(all(r[1].startswith("T21 ") for r in rows[2:]), "the operations' tool")
    check(rows[2][6] == "1.5 s" and rows[3][6] == "", "the tool change in the first operation only")
    window.copy()
    pasted = QtWidgets.QApplication.clipboard().text()
    check(OPS[1].Label in pasted and "\t" in pasted, "Copy puts the table on the clipboard")
    shot("03_window")
    window.grab().save(os.path.join(OUT, "03_window_only.png"))
    from avangardecam.ui.layout import LAYOUT

    LAYOUT.ribbon.tabs.setCurrentIndex(1)
    button = LAYOUT.ribbon.findChild(QtWidgets.QToolButton, "AvangardeCam_cam_cycle_time")
    check(button is not None and button.isEnabled(), "CAM > Output has the Cycle time button")
    OPS[1].Active = False
    doc().recompute()
    later(800, step6)


@safe
def step6():
    window = ui().window()
    row = time_row("operation", OPS[0])
    check("changed since it was worked out" in row, "a change makes the row out of date: " + row)
    check("changed" in window.status.text() and not window.table.isEnabled(), "and the window: " + window.status.text())
    shot("04_changed")
    window.recalculate()
    later(1000, step7)


@safe
def step7():
    window = ui().window()
    rows = window.rows()
    log("  table:", rows)
    check(rows[3][0] == OPS[1].Label and rows[3][2] == "switched off", "the switched off operation in the table")
    check(time_row("operation", OPS[1]) == "none: switched off", "switched off: no time")
    setup = time_row("setup", job())
    left = BEFORE["setup"] - BEFORE["second"]
    check(seconds(setup) is not None and abs(left - seconds(setup)) <= 1.0, "the setup's time without it: " + setup)
    shot("05_recalculated")
    window.close()
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
