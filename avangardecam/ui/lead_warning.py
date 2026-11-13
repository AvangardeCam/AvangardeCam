# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The question on OK of the Contour tooling window when its approach
arcs do not fit (engine.lead_check): the user may go on anyway."""

import FreeCAD

from PySide import QtWidgets

from avangardecam import tr
from avangardecam.engine import ProjectError


def go_on(window, message, title, warn, *values):
    """True when there is nothing to warn about (warn(*values) is "") or
    the user goes on anyway; else the warning goes into message (a label
    under the fields) and the window stays open."""
    if warn is None:
        return True
    try:
        warning = warn(*values)
    except (ProjectError, ValueError, ArithmeticError) as exc:
        FreeCAD.Console.PrintLog("AvangardeCam approach check: {}\n".format(exc))  # the operation says what is wrong
        return True
    if not warning:
        return True
    answer = QtWidgets.QMessageBox.warning(
        window, title, warning + "\n\n" + tr("Go on anyway?"),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No,
    )  # fmt: skip
    if answer == QtWidgets.QMessageBox.Yes:
        return True
    message.setText(warning)
    return False
