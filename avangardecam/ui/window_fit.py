# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Windows tall enough for their contents.

Qt opens a new window at most 2/3 of the screen high, and a window whose
labels wrap (the long notes of the operation windows) gets no minimum
height: its rows were squashed below their own height (Choose tool... 9 px
high, its text gone). fit_contents keeps such a window as high as its
contents need at its width; when that does not fit on the screen, the
window opens wider first (the notes take fewer lines).
"""

from PySide import QtCore

_MARGIN = 80  # the window's title bar and the desktop's panels
_WIDER = 40
_WIDEST = 900  # wider only spreads the fields out


class _Fit(QtCore.QObject):
    def eventFilter(self, window, event):
        kind = event.type()
        if kind == QtCore.QEvent.Show:
            _open(window)
        elif kind in (QtCore.QEvent.Resize, QtCore.QEvent.LayoutRequest):
            _keep(window)
        return False


def fit_contents(window):
    """Keep window (a dialog with a layout) as high as its contents need."""
    window._avangardecam_fit = _Fit(window)
    window.installEventFilter(window._avangardecam_fit)


def _room(window):
    return window.screen().availableGeometry()


def _needed(window, width):
    return window.layout().totalHeightForWidth(width)


def _open(window):
    room = _room(window)
    width = window.width()
    while _needed(window, width) > room.height() - _MARGIN and width + _WIDER <= min(room.width() - _MARGIN, _WIDEST):
        width += _WIDER
    if width != window.width():
        window.resize(width, window.height())
    _keep(window)


def _keep(window):
    layout = window.layout()
    if layout is None or not layout.hasHeightForWidth():
        return
    needed = min(_needed(window, window.width()), _room(window).height() - _MARGIN)
    if window.minimumHeight() != needed:
        window.setMinimumHeight(needed)
