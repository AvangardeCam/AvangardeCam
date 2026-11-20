# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Number boxes that are quick to type in.

A box shows its unit after the number ("12.50 mm", "8000 rpm"). A click right
of the number put the cursor behind the unit: the unit had to be deleted
first, or a spin box refused the keys. Now a click puts the cursor in the
number, at its end when the click was on the unit or the empty part of the
box, so one digit is changed at once. A double click selects the whole
number (with its sign, without the unit): what is typed replaces it. A box
that shows "none" or "-" (nothing typed yet) selects it at a click.

install() is called where a box is made: details.length_box (FreeCAD's
length boxes) and the spin boxes of the windows.
"""

import re

from PySide import QtCore, QtWidgets

NAME = "AvangardeCamNumberEntry"  # of the filter on the box's line edit

# the number at the start of a FreeCAD length box's text, its unit after it:
# a sign, digits with group and decimal separators ("-1 000,25 mm")
_NUMBER = re.compile(r"\s*[-+−]?[\d.,'\s  ]*\d[.,]?")


def number_span(text, prefix="", suffix=None):
    """(start, end) of the number in a box's text. suffix None: a FreeCAD
    box, the unit is in the text; else the prefix and suffix of a Qt spin
    box. A text without a number (a special text): all of it."""
    if suffix is None:
        match = _NUMBER.match(text)
        if not match:
            return 0, len(text)
        return len(text) - len(text.lstrip()), match.end()
    start = len(prefix) if prefix and text.startswith(prefix) else 0
    end = len(text) - len(suffix) if suffix and text.endswith(suffix) else len(text)
    body = text[start:end]
    if not body.strip():
        return 0, len(text)
    return start + len(body) - len(body.lstrip()), end - (len(body) - len(body.rstrip()))


def _span(box, edit):
    text = edit.text()
    if isinstance(box, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
        return number_span(text, box.prefix(), box.suffix())
    return number_span(text)


def _special(box, edit):
    """The box shows its special text ("none", "-") instead of a number."""
    special = box.specialValueText()
    return bool(special) and edit.text() == special


class _Entry(QtCore.QObject):
    def __init__(self, edit):
        super().__init__(edit)
        self.setObjectName(NAME)

    def eventFilter(self, edit, event):
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.LeftButton:
            select_number(edit.parentWidget())
            return True  # not the word under the mouse
        if kind == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            # after the line edit has placed the cursor (a click in a selection places it on release)
            QtCore.QTimer.singleShot(0, lambda: _clicked(edit))
        return False


def _clicked(edit):
    try:
        box = edit.parentWidget()
        if edit.hasSelectedText():
            return  # dragged over or double clicked
        if _special(box, edit):
            edit.selectAll()
            return
        start, end = _span(box, edit)
        position = edit.cursorPosition()
        if position > end:
            edit.setCursorPosition(end)
        elif position < start:
            edit.setCursorPosition(start)
    except RuntimeError:
        pass  # the window closed meanwhile


def line_edit(box):
    return box.findChild(QtWidgets.QLineEdit)


def select_number(box):
    """Select the whole number of a box, without its unit."""
    edit = line_edit(box)
    if _special(box, edit):
        edit.selectAll()
        return
    start, end = _span(box, edit)
    edit.setSelection(start, end - start)


def install(box):
    """A click in box puts the cursor in the number, a double click selects
    it (see above). Returns box."""
    edit = line_edit(box)
    if edit is not None and edit.findChild(QtCore.QObject, NAME) is None:
        edit.installEventFilter(_Entry(edit))
    return box


def installed(box):
    edit = line_edit(box)
    return edit is not None and edit.findChild(QtCore.QObject, NAME) is not None
