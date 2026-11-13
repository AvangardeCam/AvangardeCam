# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""A picture beside the fields of an operation window showing what the
field the user is in does (clicked into, or reached with Tab).

The window's own picture shows when it opens and while the field in use
has none. A field's picture may follow its value (the order of the passes:
one picture per choice); refresh() redraws it after a change.
"""

from PySide import QtCore, QtGui, QtSvg, QtWidgets

from avangardecam import image_path

WIDTH = 350  # the pictures are drawn 560 × 400
HEIGHT = 250
_BACKGROUND = "#FFFFFF"
_BORDER = "#E2E8F0"


class FieldPictures(QtWidgets.QWidget):
    """start: the window's picture (file in Resources/images)."""

    def __init__(self, start, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamFieldPictures")
        self.setFixedSize(WIDTH, HEIGHT)
        self.start = start
        self.fields = []  # (widget, picture file or function giving one)
        self.field = None  # the widget whose picture shows, None: the start
        self.shown = None  # file of the picture drawn
        self.renderer = QtSvg.QSvgRenderer(self)
        self._show(start)

    def add(self, widget, picture):
        """picture: a file name, or a function giving the file for the
        field's current value."""
        self.fields.append((widget, picture))

    def refresh(self):
        """Draw the picture of the field in use again (its value changed)."""
        self._show(self._picture(self.field))

    def _picture(self, field):
        for widget, picture in self.fields:
            if widget is field:
                return picture() if callable(picture) else picture
        return self.start

    def _show(self, name):
        if name != self.shown:
            self.shown = name
            self.renderer.load(image_path(name))
            self.update()

    def _focus_changed(self, _old, new):
        window = self.window()
        if new is None or new.window() is not window:
            return  # another window or none: keep the picture
        field = None
        while new is not None and new is not window:
            if any(widget is new for widget, _picture in self.fields):
                field = new
                break
            new = new.parentWidget()
        self.field = field
        self.refresh()

    def showEvent(self, event):
        QtWidgets.QApplication.instance().focusChanged.connect(self._focus_changed)
        super().showEvent(event)

    def hideEvent(self, event):
        QtWidgets.QApplication.instance().focusChanged.disconnect(self._focus_changed)
        super().hideEvent(event)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        frame = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QtGui.QPen(QtGui.QColor(_BORDER), 1))
        painter.setBrush(QtGui.QColor(_BACKGROUND))
        painter.drawRoundedRect(frame, 8, 8)
        self.renderer.render(painter, QtCore.QRectF(self.rect()))
        painter.end()
