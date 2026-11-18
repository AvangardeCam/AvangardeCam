# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The ribbon: File, Undo and Redo buttons in the top left corner, CAD and
CAM tabs, and under the tabs the groups of buttons of the active tab."""

import FreeCAD
import FreeCADGui
from PySide import QtCore, QtGui, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import actions, handlers, tr
from avangardecam.ui import icons

ROWS_PER_COLUMN = 3
LARGE_ICON = 32
SMALL_ICON = 16


class ActionButton(QtWidgets.QToolButton):
    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action_key = action.key
        self.setObjectName("AvangardeCam_" + action.key)
        self.setAutoRaise(True)
        self.setText(tr(action.text))
        self.setToolTip(tr(action.tip or action.text))
        self.setIcon(icons.get(action.icon))
        if action.size == actions.LARGE:
            self.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
            self.setIconSize(QtCore.QSize(LARGE_ICON, LARGE_ICON))
            self.setMinimumWidth(56)
            self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        else:
            self.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            self.setIconSize(QtCore.QSize(SMALL_ICON, SMALL_ICON))
            self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.clicked.connect(lambda: handlers.run(action))


class RibbonGroup(QtWidgets.QWidget):
    """A titled block of buttons: a large button takes a column of its own,
    small ones are stacked three per column."""

    def __init__(self, group, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamGroup_" + group.key)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 0)
        outer.setSpacing(0)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(2)
        outer.addLayout(row, 1)

        column = []

        def flush():
            if not column:
                return
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(0)
            for button in column:
                box.addWidget(button)
            box.addStretch(1)
            row.addLayout(box)
            column.clear()

        for action in group.actions:
            button = ActionButton(action)
            if action.size == actions.LARGE:
                flush()
                row.addWidget(button)
                continue
            if len(column) == ROWS_PER_COLUMN:
                flush()
            column.append(button)
        flush()

        title = QtWidgets.QLabel(tr(group.text))
        title.setObjectName("AvangardeCamGroupTitle")
        title.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom)
        outer.addWidget(title)


class RibbonPage(QtWidgets.QWidget):
    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamPage_" + tab.key)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(4)
        for i, group in enumerate(tab.groups):
            if i:
                line = QtWidgets.QFrame()
                line.setFrameShape(QtWidgets.QFrame.VLine)
                line.setFrameShadow(QtWidgets.QFrame.Sunken)
                layout.addWidget(line)
            layout.addWidget(RibbonGroup(group))
        layout.addStretch(1)


class FileButton(QtWidgets.QToolButton):
    """The File menu in the top left corner."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamFileButton")
        self.setText(tr("File"))
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("AvangardeCamFileMenu")
        for action in actions.shown_file_menu():
            if action is actions.SEPARATOR:
                menu.addSeparator()
                continue
            item = menu.addAction(icons.get(action.icon), tr(action.text))
            item.setObjectName("AvangardeCam_" + action.key)
            item.setToolTip(tr(action.tip or action.text))
            item.triggered.connect(lambda checked=False, a=action: handlers.run(a))
        menu.setToolTipsVisible(True)
        self.setMenu(menu)


class HistoryButton(QtWidgets.QToolButton):
    """Undo or Redo: shows FreeCAD's own Std_Undo / Std_Redo action, so its
    shortcut (Ctrl+Z, Ctrl+Shift+Z), its enabled state and the undo history
    are FreeCAD's; the tooltip names the step it takes back or does again."""

    def __init__(self, command, text, parent=None):
        super().__init__(parent)
        self.command = command
        self.text = text
        self.setObjectName("AvangardeCam_" + command)
        self.setAutoRaise(True)
        self.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.setIconSize(QtCore.QSize(SMALL_ICON, SMALL_ICON))
        self.setIcon(icons.get("edit-undo" if command == "Std_Undo" else "edit-redo"))
        self.setEnabled(False)
        self.attach()

    def attach(self):
        """Take over FreeCAD's action; it exists once FreeCAD has built its
        menus, so the layout calls this again on every activation."""
        if self.defaultAction() is not None:
            return
        found = FreeCADGui.Command.get(self.command).getAction()
        if found:
            self.setDefaultAction(found[0])

    def step_name(self):
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return ""
        names = doc.UndoNames if self.command == "Std_Undo" else doc.RedoNames
        return names[0] if names else ""

    def tooltip(self):
        name = self.step_name()
        action = self.defaultAction()
        shortcut = action.shortcut().toString(QtGui.QKeySequence.NativeText) if action else ""
        text = "{}: {}".format(tr(self.text), name) if name else tr(self.text)
        return "{} ({})".format(text, shortcut) if shortcut else text

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            QtWidgets.QToolTip.showText(event.globalPos(), self.tooltip(), self)
            return True
        return super().event(event)


class RibbonBar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamRibbon")
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.setObjectName("AvangardeCamTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        for tab in actions.shown_tabs():
            self.tabs.addTab(self._scrollable(RibbonPage(tab)), tr(tab.text))
        corner = QtWidgets.QWidget(self)
        corner.setObjectName("AvangardeCamQuickAccess")
        row = QtWidgets.QHBoxLayout(corner)
        row.setContentsMargins(0, 0, 4, 0)
        row.setSpacing(0)
        self.file_button = FileButton(corner)
        self.undo_button = HistoryButton("Std_Undo", QT_TRANSLATE_NOOP("AvangardeCam", "Undo"), corner)
        self.redo_button = HistoryButton("Std_Redo", QT_TRANSLATE_NOOP("AvangardeCam", "Redo"), corner)
        for widget in (self.file_button, self.undo_button, self.redo_button):
            row.addWidget(widget)
        self.tabs.setCornerWidget(corner, QtCore.Qt.TopLeftCorner)
        layout.addWidget(self.tabs)

        self.setStyleSheet(
            """
            #AvangardeCamGroupTitle { color: #808080; font-size: 8pt; }  /* palette(mid) followed the system theme: unreadable on a light or a dark system */
            #AvangardeCamFileButton {
                background-color: #2a6cb3; color: white; font-weight: bold;
                border: none; padding: 3px 16px; margin-right: 4px;
            }
            #AvangardeCamFileButton:hover { background-color: #3a7fc8; }
            #AvangardeCamFileButton::menu-indicator { image: none; }
            #AvangardeCamTabs QTabBar::tab { min-width: 56px; }
            """
        )
        self.setMinimumWidth(320)
        self.setFixedHeight(self.sizeHint().height())

    def attach_history(self):
        for button in (self.undo_button, self.redo_button):
            button.attach()

    @staticmethod
    def _scrollable(page):
        """Let a page scroll sideways instead of widening the main window
        on small screens."""
        area = QtWidgets.QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setFrameShape(QtWidgets.QFrame.NoFrame)
        area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        bar = area.style().pixelMetric(QtWidgets.QStyle.PM_ScrollBarExtent)
        area.setFixedHeight(page.sizeHint().height() + bar)
        return area
