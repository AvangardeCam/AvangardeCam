# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The Manual button of an operation window.

The long note of how the operation works no longer sits under its fields
(it squashed them): Manual opens it in a window of its own, the text
wrapped and scrolled when it is long.
"""

from PySide import QtCore, QtWidgets

from avangardecam import tr

_WIDTH = 520
_HEIGHT = 420


def add_button(buttons, title, text):
    """A Manual button on the left of buttons (a QDialogButtonBox) opening
    text under title."""
    button = buttons.addButton(tr("Manual"), QtWidgets.QDialogButtonBox.HelpRole)
    button.setObjectName("AvangardeCamManual")
    button.setAutoDefault(False)
    button.clicked.connect(lambda: show(buttons.window(), title, text))
    return button


def show(parent, title, text):
    window = QtWidgets.QDialog(parent)
    window.setObjectName("AvangardeCamManualWindow")
    window.setWindowTitle(title + " - " + tr("Manual"))
    box = QtWidgets.QVBoxLayout(window)
    view = QtWidgets.QTextBrowser()
    view.setObjectName("AvangardeCamManualText")
    view.setPlainText(text)
    box.addWidget(view)
    close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
    close.rejected.connect(window.reject)
    box.addWidget(close)
    window.resize(_WIDTH, _HEIGHT)
    window.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    window.show()
    return window
