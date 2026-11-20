# Tool library editing GUI test. The tool library window: New tool...,
# Edit..., Duplicate... and Delete (one tool selected). New tool: the next
# T number, the type's drawing and fields (a corner radius for a bull
# nose), OK with nothing filled in says what is missing and stays open;
# filled in, saved into the user's own copy of the library (the shipped
# one untouched, used from then on) and selected. Edit... of T21 in the
# project: changed there too when the user wants. Duplicate... for another
# material: a variant of T21 (the window lists the other T21 tools).
# Delete takes it out again. Every shipped tool opened with Edit... and
# OK without a change stays as it was (a pointed tip kept 0, no rounding).
#
# Run like test_layout.py (see README.md).
import json
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtGui, QtWidgets

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
STEP = os.environ.get("AC_STEP") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "demo_bridge.step")
LOG = open(os.path.join(OUT, "test_tool_editing.txt"), "w")
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


def shot(widget, name):
    path = os.path.join(OUT, name + ".png")
    QtWidgets.QApplication.processEvents()
    widget.grab().save(path)
    log("screenshot", path)


def cam():
    from avangardecam.engine import freecad_cam

    return freecad_cam


def doc():
    return FreeCAD.ActiveDocument


def field(parent, name):
    return parent.findChild(QtWidgets.QWidget, name)


def library():
    from avangardecam.model import library as lib

    return lib


def form_label(form, widget):
    return form.labelForField(widget).text()


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    from avangardecam.engine import tool_library_file

    avangardecam.params().RemString("ToolLibraryFile")  # the shipped library, as on a new profile
    if os.path.exists(tool_library_file.user_path()):
        os.remove(tool_library_file.user_path())  # left by an earlier run
    handlers = __import__("avangardecam.handlers", fromlist=["handlers"])
    handlers.import_step(STEP)
    later(1500, step2)


@safe
def step2():
    global LIB, SHIPPED, T21, JOB
    from avangardecam.ui.tool_library import ToolLibraryDialog

    SHIPPED = avangardecam.shipped_tool_library_path()
    with open(SHIPPED, encoding="utf-8") as f:
        SHIPPED_TEXT = f.read()
    globals()["SHIPPED_TEXT"] = SHIPPED_TEXT
    entries = library().load(SHIPPED)
    T21 = next(e for e in entries if e.number == 21 and e.workpiece_material == "RVS")
    JOB = cam().ensure_job(doc())
    cam().add_tool(JOB, T21)
    LIB = ToolLibraryDialog(doc())
    LIB.show()
    QtWidgets.QApplication.processEvents()
    check(unchanged(entries) == [], "Edit... and OK without a change: every shipped tool as it was")
    for name in ("New", "Edit", "Duplicate", "Delete"):
        check(field(LIB, "AvangardeCamTool" + name) is not None, "the button " + name)
    check(not field(LIB, "AvangardeCamToolEdit").isEnabled(), "Edit... needs one tool selected")
    LIB.confirm = lambda title, text: (log("  asked:", text.replace("\n", " ")), True)[1]
    LIB.run_editor = new_tool
    LIB.new_tool()
    later(300, step3)


def unchanged(entries):
    """The tools the window changes with nothing typed (rounding, a 0 lost)."""
    from avangardecam.ui.tool_editor import ToolEditorDialog

    changed = []
    for e in entries:
        dialog = ToolEditorDialog(e, entries, "Edit tool")
        if dialog.entry() != e or dialog.problems():
            changed.append(e.id)
            log("  changed:", e.id)
        dialog.deleteLater()
    return changed


def new_tool(dialog):
    check(dialog.windowTitle() == "New tool", "the window: " + dialog.windowTitle())
    number = field(dialog, "AvangardeCamToolNumber")
    check(number.value() == 10, "the lowest free T number: {}".format(number.value()))
    check(dialog.drawing.shown.endswith("endmill.svg"), "the end mill's drawing")
    check(field(dialog, "AvangardeCamToolcorner_radius_mm") is None, "an end mill: no corner radius")
    shape = field(dialog, "AvangardeCamToolShape")
    shape.setCurrentIndex(shape.findData("Bullnose"))
    radius = field(dialog, "AvangardeCamToolcorner_radius_mm")
    check(radius is not None and form_label(dialog.geometry, radius) == "Corner radius (R):", "a bull nose: its corner radius (R)")
    check(dialog.drawing.shown.endswith("bullnose.svg"), "the bull nose's drawing")
    dialog.show()
    dialog.accept()
    message = field(dialog, "AvangardeCamToolEditorMessage").text()
    check(dialog.isVisible() and "The tool needs a name." in message and "Diameter (D)" not in message, "OK with nothing filled in: " + message.replace("\n", " | "))  # fmt: skip
    field(dialog, "AvangardeCamToolName").setText("Test Frees 10mm R0.5")
    field(dialog, "AvangardeCamTooldiameter_mm").setValue(10.0)
    radius.setValue(0.5)
    field(dialog, "AvangardeCamToolflutes").setValue(4)
    field(dialog, "AvangardeCamToolcutting_length_mm").setValue(22.0)
    field(dialog, "AvangardeCamToollength_mm").setValue(60.0)
    field(dialog, "AvangardeCamToolshank_diameter_mm").setValue(10.0)
    field(dialog, "AvangardeCamToolspindle_rpm").setValue(8000)
    field(dialog, "AvangardeCamToolfeed_xy_mm_min").setValue(1600)
    field(dialog, "AvangardeCamToolfeed_z_mm_min").setValue(500)
    field(dialog, "AvangardeCamToolWorkpieceMaterial").setCurrentText("Aluminium")
    vc = field(dialog, "AvangardeCamToolVc").text()
    fz = field(dialog, "AvangardeCamToolFz").text()
    check((vc, fz) == ("Vc 251 m/min", "fz 0.050 mm"), "Vc and fz: {} {}".format(vc, fz))
    shot(dialog, "tool_editor")
    dialog.accept()
    return dialog.result() == QtWidgets.QDialog.Accepted


@safe
def step3():
    from avangardecam.engine import tool_library_file

    user = tool_library_file.user_path()
    check(avangardecam.tool_library_path() == user, "the user's own library from now on: " + user)
    added = [e for e in library().load(user) if e.tool.name == "Test Frees 10mm R0.5"]
    check(len(added) == 1 and added[0].tool.corner_radius_mm == 0.5 and added[0].tool.shape == "Bullnose", "saved in it")
    with open(SHIPPED, encoding="utf-8") as f:
        check(f.read() == SHIPPED_TEXT, "the shipped library untouched")
    selected = LIB.selected_entries()
    check([e.id for e in selected] == [added[0].id] if added else False, "the new tool selected")
    message = field(LIB, "AvangardeCamToolLibraryMessage").text()
    check(message.startswith("Saved in " + user), "it says where: " + message.replace("\n", " | "))
    shot(LIB, "tool_library_new")
    # Edit... T21 of the project
    LIB.select_ids([T21.id])
    check(field(LIB, "AvangardeCamToolEdit").isEnabled(), "a tool of the project selected: Edit... on")
    check(not LIB.add_button.isEnabled(), "but not Add to project: it is there")
    LIB.run_editor = edit_t21
    LIB.edit_selected()
    later(300, step4)


def edit_t21(dialog):
    check(dialog.windowTitle() == "Edit tool", "the window: " + dialog.windowTitle())
    check(field(dialog, "AvangardeCamToolName").text() == T21.tool.name, "its values")
    field(dialog, "AvangardeCamToolspindle_rpm").setValue(2800)
    dialog.accept()
    return dialog.result() == QtWidgets.QDialog.Accepted


@safe
def step4():
    from avangardecam.engine import tool_library_file

    edited = library().find(library().load(tool_library_file.user_path()), T21.id)
    check(edited is not None and edited.tool.spindle_rpm == 2800, "the library has the new speed, the same id")
    check(cam().tool_with_number(JOB, 21).tool.spindle_rpm == 2800, "the project's T21 too (the user said yes)")
    LIB.select_ids([T21.id])
    LIB.run_editor = duplicate
    count = len(LIB.entries)
    LIB.duplicate_selected()
    check(len(LIB.entries) == count + 1, "Duplicate...: one more tool")
    copy = LIB.selected_entries()
    check(len(copy) == 1 and copy[0].number == 21 and copy[0].workpiece_material == "Brons" and copy[0].id != T21.id, "a variant of T21 for Brons")  # fmt: skip
    LIB.delete_selected()
    check(len(LIB.entries) == count and library().find(LIB.entries, copy[0].id) is None, "Delete: gone again")
    finish()


def duplicate(dialog):
    check(dialog.windowTitle() == "Duplicate tool", "the window: " + dialog.windowTitle())
    same = field(dialog, "AvangardeCamToolSameNumber")
    check(not same.isHidden() and T21.tool.name in same.text(), "the other T21 tools shown: " + same.text())
    field(dialog, "AvangardeCamToolNumber").setValue(12)  # T10 is the new tool now
    check(same.isHidden(), "a free T number: none")
    field(dialog, "AvangardeCamToolNumber").setValue(21)
    field(dialog, "AvangardeCamToolWorkpieceMaterial").setCurrentText("Brons")
    dialog.accept()
    return dialog.result() == QtWidgets.QDialog.Accepted


def finish():
    log("FAILURES:", len(FAILURES))
    for text in FAILURES:
        log("  ", text)
    log("done")
    LOG.close()
    try:
        LIB.close()
    except Exception:
        pass
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)
    QtCore.QTimer.singleShot(200, mw().close)


# start as on a new profile: no values remembered from earlier work
avangardecam.forget_last_values()
later(4000, step1)
