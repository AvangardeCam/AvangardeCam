# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Kiosk layout: puts the ribbon and the project panel into the FreeCAD main
window while the workbench is active and hides FreeCAD's own menu bar and
panels; gives everything back when another workbench takes over.

FreeCAD's toolbars need no hiding: the workbench removes the standard ones
from its toolbar list, so ToolBarManager shows none. The ribbon is a plain
QToolBar and the panel a plain QDockWidget, which FreeCAD's managers leave
alone, so we show and hide them ourselves. FreeCAD restores the saved main
window state after activating the start workbench, therefore visibility is
applied again from the event loop.

The names of the FreeCAD panels we hid are kept in the parameters, so even
after a crash in kiosk mode the next switch to FreeCAD brings them back.
"""

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtWidgets

from avangardecam import params, tr
from avangardecam.ui.project_panel import ProjectPanel
from avangardecam.ui.ribbon import RibbonBar

RIBBON_NAME = "AvangardeCam_Ribbon"
PANEL_NAME = "AvangardeCam_Project"
PANEL_WIDTH = 340
PANEL_MIN_WIDTH = 300  # below this the details values get cut off
_HIDDEN_DOCKS = "HiddenFreeCADDocks"


class Layout:
    def __init__(self):
        self.ribbon_toolbar = None
        self.ribbon = None
        self.dock = None
        self.panel = None
        self.active = False

    # -- creation ---------------------------------------------------------

    def _create(self):
        mw = FreeCADGui.getMainWindow()

        toolbar = QtWidgets.QToolBar("AvangardeCam", mw)
        toolbar.setObjectName(RIBBON_NAME)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setAllowedAreas(QtCore.Qt.TopToolBarArea)
        toolbar.setContextMenuPolicy(QtCore.Qt.PreventContextMenu)
        toolbar.toggleViewAction().setVisible(False)
        toolbar.setStyleSheet("QToolBar { padding: 0px; spacing: 0px; border: none; }")
        mw.addToolBarBreak(QtCore.Qt.TopToolBarArea)
        mw.addToolBar(QtCore.Qt.TopToolBarArea, toolbar)
        self.ribbon = RibbonBar()
        toolbar.addWidget(self.ribbon)
        self.ribbon_toolbar = toolbar

        dock = QtWidgets.QDockWidget(tr("Project"), mw)
        dock.setObjectName(PANEL_NAME)
        dock.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea)
        dock.toggleViewAction().setVisible(False)
        self.panel = ProjectPanel()
        self.panel.setMinimumWidth(PANEL_MIN_WIDTH)
        dock.setWidget(self.panel)
        mw.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
        self.dock = dock
        # resizing only works once the window is laid out
        QtCore.QTimer.singleShot(600, self._initial_width)

        # Give FreeCAD its panels back before it saves the window state
        mw.mainWindowClosed.connect(self.deactivate)

    def _initial_width(self):
        """Widen a panel narrower than the default; a width the user chose
        (saved with the window state) is kept."""
        if self.dock.width() < PANEL_WIDTH:
            FreeCADGui.getMainWindow().resizeDocks(
                [self.dock], [PANEL_WIDTH], QtCore.Qt.Horizontal
            )

    # -- workbench hooks ----------------------------------------------------

    def activate(self):
        if self.ribbon_toolbar is None:
            self._create()
        self.active = True
        self.ribbon.attach_history()
        self._apply()
        self.panel.start_tracking()
        QtCore.QTimer.singleShot(0, self._apply)
        QtCore.QTimer.singleShot(500, self._apply)
        QtCore.QTimer.singleShot(500, self._ensure_document)

    def deactivate(self):
        if not self.active:
            return
        self.active = False
        if self.panel is not None:
            self.panel.stop_tracking()
        self._apply()

    def _apply(self):
        if self.ribbon_toolbar is None:
            return
        on = self.active
        mw = FreeCADGui.getMainWindow()
        self.ribbon_toolbar.setVisible(on)
        self.dock.setVisible(on)
        mw.menuBar().setVisible(not on)
        if on:
            self._hide_freecad_docks(mw)
        else:
            self._restore_freecad_docks(mw)

    def _hide_freecad_docks(self, mw):
        hidden = self._hidden_names()
        for dock in mw.findChildren(QtWidgets.QDockWidget):
            if dock is self.dock:
                continue
            self._watch(dock)
            if not dock.isVisible():
                continue
            if dock.objectName():
                hidden.add(dock.objectName())
            self._set_dock_visible(dock, False)
        params().SetString(_HIDDEN_DOCKS, ";".join(sorted(hidden)))

    @staticmethod
    def _set_dock_visible(dock, visible):
        """Show or hide a panel through its toggle action: a panel in
        FreeCAD's overlay mode (floating over the 3D view) only reacts to
        that, a normal one shows or hides as with setVisible()."""
        action = dock.toggleViewAction()
        if action.isChecked() != visible:
            action.trigger()
        if dock.isVisible() != visible:
            dock.setVisible(visible)

    def _watch(self, dock):
        """FreeCAD shows some panels by itself (e.g. Tasks when the first 3D
        view is created); hide them again while the kiosk layout is active.

        A panel in overlay mode does not emit visibilityChanged when it
        appears, but its toggle action gets checked."""
        if dock.property("AvangardeCamWatched"):
            return
        dock.setProperty("AvangardeCamWatched", True)
        dock.visibilityChanged.connect(self._on_dock_visibility)
        dock.toggleViewAction().toggled.connect(self._on_dock_visibility)

    def _on_dock_visibility(self, visible):
        if visible and self.active:
            QtCore.QTimer.singleShot(0, self._apply)

    def _restore_freecad_docks(self, mw):
        for name in self._hidden_names():
            dock = mw.findChild(QtWidgets.QDockWidget, name)
            if dock is not None:
                self._set_dock_visible(dock, True)
        params().SetString(_HIDDEN_DOCKS, "")

    @staticmethod
    def _hidden_names():
        return {name for name in params().GetString(_HIDDEN_DOCKS, "").split(";") if name}

    def _ensure_document(self):
        """Always show the 3D view: open an empty project when none is open."""
        if not self.active or FreeCAD.listDocuments():
            return
        FreeCAD.newDocument()
        view = FreeCADGui.ActiveDocument.ActiveView if FreeCADGui.ActiveDocument else None
        if view is not None and hasattr(view, "viewIsometric"):
            view.viewIsometric()


LAYOUT = Layout()
