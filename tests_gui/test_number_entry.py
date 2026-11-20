# Number boxes quick to type in (ui.number_entry). A click right of the
# number (on the unit or the empty part of the box) puts the cursor at the
# number's end, not behind the unit: Backspace takes a digit, a digit typed
# goes in. A double click selects the whole number (with its sign, not the
# unit): what is typed replaces it. "none" is selected at a click. A FreeCAD
# length box (the unit in its text), a Qt spin box with a suffix and one with
# a prefix (T number); the tool editor's boxes have it, also when they are
# made again for another type.
#
# Run like test_layout.py (see README.md).
import os
import tempfile
import traceback

import FreeCAD
import FreeCADGui
import avangardecam
from PySide import QtCore, QtWidgets
from PySide6 import QtTest

OUT = os.environ.get("AC_TEST_OUT", tempfile.gettempdir())
LOG = open(os.path.join(OUT, "test_number_entry.txt"), "w")
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


def entry():
    from avangardecam.ui import number_entry

    return number_entry


def settle():
    for _ in range(3):
        QtWidgets.QApplication.processEvents()


def click(box, x):
    edit = entry().line_edit(box)
    QtTest.QTest.mouseClick(edit, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, QtCore.QPoint(x, edit.height() // 2))
    settle()
    return edit


def double_click(box, x):
    edit = entry().line_edit(box)
    QtTest.QTest.mouseDClick(edit, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, QtCore.QPoint(x, edit.height() // 2))
    settle()
    return edit


def right_end(box):
    return entry().line_edit(box).width() - 4


def middle_of_number(box):
    edit = entry().line_edit(box)
    return edit.fontMetrics().horizontalAdvance(edit.text()[:2]) + 4


def keys(box, text):
    QtTest.QTest.keyClicks(box, text)
    settle()


def key(box, k):
    QtTest.QTest.keyClick(box, k)
    settle()


def shown(box):
    edit = entry().line_edit(box)
    text = edit.text()
    at = edit.cursorPosition()
    return "{!r} cursor {} ({!r}|{!r}) selected {!r}".format(text, at, text[:at], text[at:], edit.selectedText())


def step1():
    mw().setGeometry(0, 0, 1920, 1080)
    later(500, step2)


@safe
def step2():
    """The number of a box's text, without its unit."""
    span = entry().number_span
    for text, expected in (
        ("25.00 mm", (0, 5)), ("-12.50 mm", (0, 6)), ("1 000,25 mm", (0, 8)), ("12. mm", (0, 3)),
        ("0.5 in", (0, 3)), ("12", (0, 2)), ("none", (0, 4)), ("", (0, 0)),
    ):  # fmt: skip
        check(span(text) == expected, "FreeCAD box {!r}: the number {}".format(text, span(text)))
    for args, expected in (
        (("8000 rpm", "", " rpm"), (0, 4)), (("900.0 mm/min", "", " mm/min"), (0, 5)),
        (("T21", "T", ""), (1, 3)), (("12.5 %", "", " %"), (0, 4)), (("none", "", " rpm"), (0, 4)),
    ):  # fmt: skip
        check(span(*args) == expected, "spin box {}: the number {}".format(args, span(*args)))
    build()
    later(500, step3)


def build():
    global WINDOW, LENGTH, NEGATIVE, CUTTING, T_NUMBER
    from avangardecam.ui import cutting_data, details

    WINDOW = QtWidgets.QWidget()
    form = QtWidgets.QFormLayout(WINDOW)
    LENGTH = details.length_box(25.0, -100.0, 100.0)
    form.addRow("Length:", LENGTH)
    NEGATIVE = details.length_box(-12.5, -100.0, 100.0)
    form.addRow("Negative:", NEGATIVE)
    CUTTING = cutting_data.CuttingDataFields("AvangardeCamTest")
    form.addRow(CUTTING)
    T_NUMBER = QtWidgets.QSpinBox()
    T_NUMBER.setRange(0, 9999)
    T_NUMBER.setPrefix("T")
    T_NUMBER.setValue(21)
    entry().install(T_NUMBER)
    form.addRow("T number:", T_NUMBER)
    WINDOW.resize(600, 300)
    WINDOW.show()
    WINDOW.activateWindow()
    settle()


@safe
def step3():
    # a FreeCAD length box: "25.00 mm"
    check(entry().installed(LENGTH), "length_box: quick to type in")
    edit = click(LENGTH, right_end(LENGTH))
    log("  click right of the number:", shown(LENGTH))
    text, at = edit.text(), edit.cursorPosition()
    check(text[:at].rstrip().endswith("0") and text[at:].strip() == "mm", "a click right of the number: the cursor at its end, before the unit")  # fmt: skip
    key(LENGTH, QtCore.Qt.Key_Backspace)
    keys(LENGTH, "8")
    log("  Backspace, 8:", shown(LENGTH))
    check(edit.text().endswith(" mm") and edit.text().replace(" mm", "") in ("25.08", "25,08"), "Backspace took a digit, 8 went in, the unit kept: " + edit.text())  # fmt: skip
    key(LENGTH, QtCore.Qt.Key_Return)
    check(abs(float(LENGTH.property("rawValue")) - 25.08) < 1e-9, "the value: {}".format(LENGTH.property("rawValue")))
    edit = double_click(LENGTH, middle_of_number(LENGTH))
    log("  double click:", shown(LENGTH))
    check(edit.selectedText() in ("25.08", "25,08"), "a double click: the whole number selected, not the unit")
    keys(LENGTH, "40")
    key(LENGTH, QtCore.Qt.Key_Return)
    log("  40, Return:", shown(LENGTH))
    check(abs(float(LENGTH.property("rawValue")) - 40.0) < 1e-9, "typed over it: {}".format(LENGTH.property("rawValue")))  # fmt: skip
    edit = double_click(NEGATIVE, right_end(NEGATIVE))
    log("  double click on the unit of a negative value:", shown(NEGATIVE))
    check(edit.selectedText() in ("-12.50", "-12,50"), "a double click anywhere: the number with its sign")
    later(300, step4)


@safe
def step4():
    # Qt spin boxes: "none" (the special text), a suffix, a prefix
    spindle = CUTTING.boxes["spindle_rpm"]
    check(entry().installed(spindle), "the cutting data: quick to type in")
    edit = click(spindle, right_end(spindle))
    log("  click in none:", shown(spindle))
    check(edit.selectedText() == edit.text() == spindle.specialValueText(), "a click in none: none selected")
    keys(spindle, "1200")
    key(spindle, QtCore.Qt.Key_Return)
    log("  1200, Return:", shown(spindle))
    check(spindle.value() == 1200.0, "typed over none: {}".format(spindle.value()))
    feed = CUTTING.boxes["feed_xy_mm_min"]
    feed.setValue(900.0)
    edit = click(feed, right_end(feed))
    log("  click right of the feed:", shown(feed))
    check(edit.cursorPosition() == len(edit.text()) - len(feed.suffix()), "a spin box: the cursor at the number's end, before the unit")  # fmt: skip
    key(feed, QtCore.Qt.Key_Backspace)
    key(feed, QtCore.Qt.Key_Backspace)
    key(feed, QtCore.Qt.Key_Backspace)
    keys(feed, "5")
    key(feed, QtCore.Qt.Key_Return)
    log("  Backspace 3x, 5, Return:", shown(feed))
    check(feed.value() == 905.0, "a digit changed at once: {}".format(feed.value()))
    edit = double_click(feed, right_end(feed))
    check(edit.selectedText() in ("905.0", "905,0"), "a double click on the unit: the number selected: " + edit.selectedText())  # fmt: skip
    keys(feed, "1600")
    key(feed, QtCore.Qt.Key_Return)
    check(feed.value() == 1600.0, "typed over it: {}".format(feed.value()))
    edit = click(T_NUMBER, 1)
    log("  click on the T:", shown(T_NUMBER))
    check(edit.cursorPosition() >= 1, "a click on the prefix T: the cursor after it")
    edit = double_click(T_NUMBER, right_end(T_NUMBER))
    check(edit.selectedText() == "21", "a double click: the number without its T: " + edit.selectedText())
    keys(T_NUMBER, "7")
    key(T_NUMBER, QtCore.Qt.Key_Return)
    check(T_NUMBER.value() == 7, "typed over it: T{}".format(T_NUMBER.value()))
    later(300, step5)


@safe
def step5():
    # the tool editor's boxes, made again for each type
    from avangardecam.model import library
    from avangardecam.ui.tool_editor import ToolEditorDialog

    entries = library.load(avangardecam.shipped_tool_library_path())
    t21 = next(e for e in entries if e.number == 21)
    dialog = ToolEditorDialog(t21, entries, "Edit tool")
    boxes = dialog.findChildren(QtWidgets.QAbstractSpinBox)
    missing = [b.objectName() for b in boxes if not entry().installed(b)]
    check(boxes and not missing, "the tool editor: all {} boxes, none left {}".format(len(boxes), missing))
    shape = dialog.findChild(QtWidgets.QComboBox, "AvangardeCamToolShape")
    shape.setCurrentIndex(shape.findData("ThreadMill"))
    settle()
    boxes = [b for b in dialog.findChildren(QtWidgets.QAbstractSpinBox) if b.isVisibleTo(dialog)]
    missing = [b.objectName() for b in boxes if not entry().installed(b)]
    check(dialog.findChild(QtWidgets.QWidget, "AvangardeCamToolpitch_mm") is not None and not missing, "another type: its new boxes too {}".format(missing))  # fmt: skip
    dialog.deleteLater()
    finish()


def finish():
    log("FAILURES:", len(FAILURES))
    for text in FAILURES:
        log("  ", text)
    log("done")
    LOG.close()
    try:
        WINDOW.close()
    except Exception:
        pass
    for name in list(FreeCAD.listDocuments()):
        FreeCAD.closeDocument(name)
    QtCore.QTimer.singleShot(200, mw().close)


# start as on a new profile: no values remembered from earlier work
avangardecam.forget_last_values()
later(4000, step1)
