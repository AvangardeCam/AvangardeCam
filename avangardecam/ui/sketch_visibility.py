# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Hiding a sketch (one made by Extract boundary edges) in 3D, as an
operation's path can be hidden.

A right click on a sketch in the project list opens its menu: Hide in 3D /
Show in 3D. Only the view: the contours made on the sketch stay as they are,
and in the program. A hidden sketch has "(hidden)" after its name, grey, its
lines and direction arrows are not drawn and cannot be clicked. It is
FreeCAD's own visibility of the sketch, so it is saved with the project.
"""

from PySide import QtGui, QtWidgets

from avangardecam import tr


def hidden(sketch):
    """Whether the sketch is hidden in 3D."""
    vo = getattr(sketch, "ViewObject", None)
    return vo is not None and not vo.Visibility


def set_hidden(sketch, hide):
    vo = getattr(sketch, "ViewObject", None)
    if vo is not None and vo.Visibility == hide:
        vo.Visibility = not hide


def mark(item, sketch):
    """A hidden sketch's list entry: said after its name, grey."""
    if hidden(sketch):
        item.setText(0, "{}  ({})".format(sketch.Label, tr("hidden")))
        item.setForeground(0, item.treeWidget().palette().brush(QtGui.QPalette.Disabled, QtGui.QPalette.Text))
    item.setToolTip(0, tr("Right click for the menu: hide in 3D"))


def menu(sketch, panel=None):
    """Hide in 3D (Show in 3D) of a sketch."""
    result = QtWidgets.QMenu(panel)
    result.setObjectName("AvangardeCamSketchMenu")
    is_hidden = hidden(sketch)
    action = result.addAction(tr("Show in 3D") if is_hidden else tr("Hide in 3D"))
    action.setObjectName("AvangardeCamHideSketch")
    action.setToolTip(tr("Only the view: the contours made on it stay in the program"))
    action.triggered.connect(lambda: _hide(sketch, not is_hidden, panel))
    result.setToolTipsVisible(True)
    return result


def _hide(sketch, hide, panel):
    set_hidden(sketch, hide)
    if panel is not None:
        panel.refresh()  # the mark after its name
