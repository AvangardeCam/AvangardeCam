# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Left panel: the project list on top and the details of the selected
entry below it.

The list shows the project as the engine reads it from the document: the
models and sketches, then each setup (one clamping of the part) with its
stock, tools and operations. The setup of the selected entry is the active
one, the one shown in 3D. Selecting an entry selects it in the 3D view and
the other way round. A right click on an operation opens its menu: edit
it in its window, select its geometry again (activate_geometry), switch it
off or on, hide or show its path in 3D, delete it (delete_operation, also
the Delete key). Dragging an operation changes the
order of its setup's operations (operation_order). A right click on a
sketch hides or shows it in 3D (sketch_visibility).
"""

import FreeCAD
import FreeCADGui

from PySide import QtCore, QtGui, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

from avangardecam import tr
from avangardecam.engine import freecad_cam as cam
from avangardecam.ui import activate_geometry, cycle_time, delete_operation, details, operation_order, picking, scene, sketch_visibility
from avangardecam.ui import next_setup as ui_next_setup
from avangardecam.ui import op_zero as ui_op_zero

KIND_ROLE = QtCore.Qt.UserRole
NAME_ROLE = QtCore.Qt.UserRole + 1

GROUP = "group"
MODEL = "model"
SKETCH = "sketch"
SETUP = "setup"
STOCK = "stock"
TOOL = "tool"
OPERATION = "operation"
PLACEHOLDER = "placeholder"

# group keys; the groups of a setup are keyed "<key>:<Job name>"
GROUPS = (
    (
        "model",
        QT_TRANSLATE_NOOP("AvangardeCam", "Model"),
        QT_TRANSLATE_NOOP("AvangardeCam", "Parts to machine. Add one with File > Import model."),
    ),
    (
        "sketches",
        QT_TRANSLATE_NOOP("AvangardeCam", "Sketches"),
        QT_TRANSLATE_NOOP("AvangardeCam", "Flat outlines the tool can follow. Select a flat face of the model and click Extract boundary edges (CAD or CAM tab)."),  # fmt: skip
    ),
    (
        "setup",
        QT_TRANSLATE_NOOP("AvangardeCam", "Setup"),
        QT_TRANSLATE_NOOP("AvangardeCam", "A setup is one clamping of the part on the machine, with its own zero point. The first one is made when you import a model; for another one select a face and click CAM > Snap-0-Point."),  # fmt: skip
    ),
    (
        "tools",
        QT_TRANSLATE_NOOP("AvangardeCam", "Tools"),
        QT_TRANSLATE_NOOP("AvangardeCam", "Cutting tools used by the operations of this setup."),
    ),
    (
        "operations",
        QT_TRANSLATE_NOOP("AvangardeCam", "Operations"),
        QT_TRANSLATE_NOOP("AvangardeCam", "Machining steps of this setup, in the order they run."),
    ),
)


def group_key(key, job=None):
    return key if job is None else "{}:{}".format(key, job.Name)


def _split_group_key(name):
    key, _sep, job_name = name.partition(":")
    return key, job_name


class _DocumentObserver:
    """Refreshes the panel once per event loop pass after document changes."""

    def __init__(self, panel):
        self.panel = panel

    def _changed(self, *args):
        self.panel.schedule_refresh()

    slotCreatedDocument = _changed
    slotDeletedDocument = _changed
    slotActivateDocument = _changed
    slotCreatedObject = _changed
    slotDeletedObject = _changed
    slotRelabelObject = _changed
    slotRecomputedDocument = _changed
    slotUndoDocument = _changed
    slotRedoDocument = _changed


class _SelectionObserver:
    """Follows the selection of the 3D view in the list."""

    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, doc, obj, sub, pnt):
        self.panel.select_from_view(doc, obj)

    def setSelection(self, doc):
        selection = FreeCADGui.Selection.getSelection(doc)
        if selection:
            self.panel.select_from_view(doc, selection[0].Name)


class ProjectPanel(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamProjectPanel")
        self._refresh_pending = False
        self._observer = None
        self._selection_observer = None
        self._pushing_selection = False
        self.view = None
        self._view_key = None
        self.menu = None  # the menu of the operation clicked last

        splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical, self)
        splitter.setObjectName("AvangardeCamProjectSplitter")
        splitter.setChildrenCollapsible(False)

        self.tree = QtWidgets.QTreeWidget(splitter)
        self.tree.setObjectName("AvangardeCamProjectList")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.itemClicked.connect(self._on_clicked)
        self.tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_menu)
        self.drag = operation_order.install(self.tree, self._operation_of_item)
        self.delete_key = delete_operation.install(self.tree, self._operation_of_item, self)

        self.scroll = QtWidgets.QScrollArea(splitter)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([3000, 2000])  # proportions; the splitter scales them
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.setStyleSheet(
            """
            #AvangardeCamDetailsCaption { color: palette(mid); font-size: 8pt; }
            #AvangardeCamDetailsTitle { font-weight: bold; font-size: 11pt; }
            #AvangardeCamDetailsNote { color: palette(mid); }
            """
        )
        self.refresh()

    # -- tracking -----------------------------------------------------------

    def start_tracking(self):
        if self._observer is None:
            self._observer = _DocumentObserver(self)
            FreeCAD.addDocumentObserver(self._observer)
            self._selection_observer = _SelectionObserver(self)
            FreeCADGui.Selection.addObserver(self._selection_observer)
            scene.watch_edits(self.show_object)
            picking.start()
        self.refresh()

    def stop_tracking(self):
        if self._observer is not None:
            FreeCAD.removeDocumentObserver(self._observer)
            FreeCADGui.Selection.removeObserver(self._selection_observer)
            scene.stop_watching_edits()
            picking.stop()
            self._observer = None
            self._selection_observer = None
        for name in FreeCAD.listDocuments():
            scene.restore_freecad_view(FreeCAD.getDocument(name))

    def schedule_refresh(self):
        if not self._refresh_pending:
            self._refresh_pending = True
            QtCore.QTimer.singleShot(0, self.refresh)

    # -- list ---------------------------------------------------------------

    def refresh(self):
        self._refresh_pending = False
        current = self._key(self.tree.currentItem())
        doc = FreeCAD.ActiveDocument
        jobs = cam.setups(doc)
        active = scene.active_setup(doc)

        self.tree.blockSignals(True)
        self.tree.clear()
        self._add_group(self.tree, "model", [(MODEL, o.Name, o.Label, o) for o in cam.models(doc)])
        sketches = [o for o in (doc.Objects if doc else []) if cam.owner(o) == ("sketch", o)]
        group = self._add_group(self.tree, "sketches", [(SKETCH, o.Name, o.Label, o) for o in sketches])
        for i, sketch in enumerate(sketches):
            sketch_visibility.mark(group.child(i), sketch)
        for job in jobs:
            self._add_setup(job, job is active)
        if not jobs:
            self._add_group(self.tree, "setup", [])
        restore = self.find_item(current) if current else None
        if restore is not None:
            self.tree.setCurrentItem(restore)
        self.tree.blockSignals(False)
        if self._observer is not None:
            # not after expert mode began: a refresh may come late
            scene.apply(doc)
            picking.watch_views()

        if self._view_key is not None and self._view_key[0] == PLACEHOLDER and restore is None:
            return
        if restore is not None and self._view_key == current and getattr(self.view, "LIVE", False):
            try:
                self.view.update_view()
                return
            except Exception:  # the shown object is gone (undo, delete)
                pass
        self._show_item(restore)

    @staticmethod
    def _add_item(parent, kind, name, label, icon_obj=None):
        item = QtWidgets.QTreeWidgetItem(parent, [label])
        item.setData(0, KIND_ROLE, kind)
        item.setData(0, NAME_ROLE, name)
        view_object = getattr(icon_obj, "ViewObject", None)
        if view_object is not None:
            item.setIcon(0, view_object.Icon)
        return item

    def _add_group(self, parent, key, children, job=None):
        """A bold group with its entries: (kind, name, label, object for the icon)."""
        text = next(text for k, text, _note in GROUPS if k == key)
        group = self._add_item(parent, GROUP, group_key(key, job), tr(text))
        font = group.font(0)
        font.setBold(True)
        group.setFont(0, font)
        for kind, name, label, icon_obj in children:
            self._add_item(group, kind, name, label, icon_obj)
        if not group.childCount():
            empty = QtWidgets.QTreeWidgetItem(group, [tr("(none)")])
            empty.setFlags(QtCore.Qt.NoItemFlags)
        group.setExpanded(True)
        return group

    def _add_setup(self, job, active):
        label = tr("{} (active)").format(job.Label) if active else job.Label
        item = self._add_item(self.tree, SETUP, job.Name, label, job)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setToolTip(0, tr("Active setup: shown in 3D") if active else tr("Click to show this setup in 3D"))
        if job.Stock is not None:
            text = tr("Stock") + "  " + ui_next_setup.kind_text(job) + " " + details.size_text(cam.stock_bounds(job))
            self._add_item(item, STOCK, job.Stock.Name, text, job.Stock)
        tools = [
            (TOOL, t.controller.Name, "T{}  {}".format(t.number, t.tool.name), t.controller)
            for t in cam.project_tools(job)
        ]
        self._add_group(item, "tools", tools, job)
        ops = [(OPERATION, op.Name, op.Label, op) for op in cam.operations(job)]
        group = self._add_group(item, "operations", ops, job)
        for i, op in enumerate(cam.operations(job)):
            self._mark_operation(group.child(i), op)
        item.setExpanded(True)

    @staticmethod
    def _mark_operation(item, op):
        """An operation switched off or hidden: said after its name, grey."""
        marks = []
        if not op.Active:
            marks.append(tr("off"))
        if scene.hidden(op):
            marks.append(tr("hidden"))
        if ui_op_zero.parked(op):
            marks.append(tr("other 0-Point"))
        if marks:
            item.setText(0, "{}  ({})".format(op.Label, ", ".join(marks)))
            item.setForeground(0, item.treeWidget().palette().brush(QtGui.QPalette.Disabled, QtGui.QPalette.Text))
        item.setToolTip(0, tr("Right click for the menu: edit, switch off, hide, delete. Drag it up or down to change the order"))

    def _items(self):
        iterator = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            yield iterator.value()
            iterator += 1

    def find_item(self, key):
        for item in self._items():
            if self._key(item) == key:
                return item
        return None

    @staticmethod
    def _key(item):
        if item is None:
            return None
        return item.data(0, KIND_ROLE), item.data(0, NAME_ROLE)

    def _on_current_changed(self, current, _previous):
        job = self._setup_of_item(current)
        if job is not None and job is not scene.active_setup(job.Document):
            scene.set_active_setup(job)
            self.schedule_refresh()  # the "(active)" mark moves
        self._show_item(current)

    @staticmethod
    def _setup_of_item(item):
        """The setup an entry of the list belongs to, or None."""
        doc = FreeCAD.ActiveDocument
        while item is not None and doc is not None:
            if item.data(0, KIND_ROLE) == SETUP:
                return doc.getObject(item.data(0, NAME_ROLE))
            item = item.parent()
        return None

    @staticmethod
    def _operation_of_item(item):
        doc = FreeCAD.ActiveDocument
        if item is None or doc is None or item.data(0, KIND_ROLE) != OPERATION:
            return None
        return doc.getObject(item.data(0, NAME_ROLE))

    def _on_clicked(self, item, _column):
        """Clicking a model or a sketch selects it in the 3D view too."""
        doc = FreeCAD.ActiveDocument
        if doc is None or item.data(0, KIND_ROLE) is None:
            return
        self._pushing_selection = True
        try:
            FreeCADGui.Selection.clearSelection()
            if item.data(0, KIND_ROLE) in (MODEL, SKETCH):
                FreeCADGui.Selection.addSelection(doc.Name, item.data(0, NAME_ROLE))
        finally:
            self._pushing_selection = False

    def _on_menu(self, at):
        """A right click on an operation, a sketch or a stock selects it and opens its menu."""
        item = self.tree.itemAt(at)
        doc = FreeCAD.ActiveDocument
        if item is None or doc is None or item.data(0, KIND_ROLE) not in (OPERATION, SKETCH, STOCK):
            return
        obj = doc.getObject(item.data(0, NAME_ROLE))
        if obj is None:
            return
        self.tree.setCurrentItem(item)
        if item.data(0, KIND_ROLE) == STOCK:
            from avangardecam.ui import custom_stock

            job = cam.setup_of(obj)
            if job is None:
                return
            self.menu = custom_stock.stock_menu(job, self)
        elif item.data(0, KIND_ROLE) == SKETCH:
            self.menu = sketch_visibility.menu(obj, self)
        else:
            self.menu = operation_menu(obj, self)
        self.menu.popup(self.tree.viewport().mapToGlobal(at))

    def select_from_view(self, doc_name, obj_name):
        """Show the entry of an object picked in the 3D view."""
        if self._pushing_selection:
            return
        doc = FreeCAD.getDocument(doc_name) if doc_name in FreeCAD.listDocuments() else None
        obj = doc.getObject(obj_name) if doc is not None else None
        found = cam.owner(obj) if obj is not None else None
        if found is None:
            return
        kind, target = found
        item = self.find_item((kind, target.Name))
        if item is not None and item is not self.tree.currentItem():
            self.tree.setCurrentItem(item)  # shows its details

    # -- details ------------------------------------------------------------

    def _set_view(self, view, key):
        self.view = view
        self._view_key = key
        self.scroll.setWidget(view)

    def _show_item(self, item):
        doc = FreeCAD.ActiveDocument
        kind = item.data(0, KIND_ROLE) if item is not None else None
        name = item.data(0, NAME_ROLE) if item is not None else None
        key = (kind, name) if kind else None
        obj = doc.getObject(name) if doc is not None and kind not in (None, GROUP) else None
        job = cam.setup_of(obj) if obj is not None else None
        view = None
        if kind == GROUP:
            view = self._group_view(name, doc)
        elif kind == MODEL and obj is not None:
            view = details.ModelView(obj)
        elif kind == SKETCH and obj is not None:
            view = details.SketchView(obj)
        elif kind == SETUP and obj is not None:
            view = details.SetupView(obj)
        elif kind == STOCK and job is not None:
            view = details.StockView(job)
        elif kind == TOOL and job is not None:
            for t in cam.project_tools(job):
                if t.controller is obj:
                    view = details.ToolView(job, t)
        elif kind == OPERATION and obj is not None:
            if ui_op_zero.parked(obj):  # its values wait until its zero point is the active one
                view = ui_op_zero.ParkedView(obj)
            elif _deburring_of(obj) is not None:
                from avangardecam.ui.deburring import DeburringView

                view = DeburringView(obj)
            elif cam.contour_of(obj) is not None:
                view = details.ContourView(obj)
            elif cam.drilling_of(obj) is not None:
                view = details.DrillingView(obj)
            elif cam.thread_milling_of(obj) is not None:
                view = details.ThreadMillingView(obj)
            elif cam.adaptive_of(obj) is not None:
                view = details.AdaptiveView(obj)
            elif _facing_of(obj) is not None:
                from avangardecam.ui.facing import FacingView

                view = FacingView(obj)
            elif _slot_milling_of(obj) is not None:
                from avangardecam.ui.slot import SlotView

                view = SlotView(obj)
            elif _helix_milling_of(obj) is not None:
                from avangardecam.ui.helix import HelixView

                view = HelixView(obj)
            else:
                view = details.DetailsView(
                    obj.Label,
                    tr("This operation was made in FreeCAD; change it in expert mode."),
                )
        if view is None:
            view = details.DetailsView(note=tr("Select an entry of the list to see its details."))
            key = None
        elif kind in (SETUP, OPERATION):
            cycle_time.attach(view, obj)
        if self._observer is not None:  # not in expert mode
            scene.highlight_operation(doc, obj if kind == OPERATION else None)
        self._set_view(view, key)

    def _group_view(self, name, doc):
        key, job_name = _split_group_key(name)
        for group_key_, text, note in GROUPS:
            if group_key_ == key:
                view = details.DetailsView(tr(text), tr(note))
                break
        else:
            return None
        from avangardecam import handlers

        if key == "model":
            view.add_button(tr("Import model (STEP)..."), handlers.import_step)
        elif key == "setup" and cam.models(doc):
            view.add_button(tr("Create setup"), handlers.edit_stock, "AvangardeCamCreateStock")
        elif key == "tools" and job_name:
            view.add_button(
                tr("Add tools from library..."), handlers.tool_library, "AvangardeCamOpenLibrary"
            )
        return view

    def current_entry(self):
        """(kind, document object) of the current list entry, or None."""
        item = self.tree.currentItem()
        doc = FreeCAD.ActiveDocument
        if item is None or doc is None or item.data(0, KIND_ROLE) in (None, GROUP):
            return None
        obj = doc.getObject(item.data(0, NAME_ROLE))
        return (item.data(0, KIND_ROLE), obj) if obj is not None else None

    def show_object(self, obj):
        """Show the entry of a project object (e.g. one double-clicked in 3D)."""
        found = cam.owner(obj)
        if found is not None:
            self.select_entry(found[0], found[1].Name)

    def select_entry(self, kind, name):
        """Make an entry current; a group's name is its group_key()."""
        self.refresh()
        item = self.find_item((kind, name))
        if item is not None:
            self.tree.setCurrentItem(item)
        return item

    def show_placeholder(self, action):
        """Say in the details area that a clicked function is not built yet."""
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(None)
        self.tree.blockSignals(False)
        scene.highlight_operation(FreeCAD.ActiveDocument, None)
        view = details.DetailsView(
            tr(action.text),
            tr("Not implemented yet. The settings of this function will appear here."),
        )
        self._set_view(view, (PLACEHOLDER, action.key))


def _facing_of(op):
    from avangardecam.engine import facing

    return facing.facing_of(op)


def _slot_milling_of(op):
    from avangardecam.engine import slot

    return slot.slot_milling_of(op)


def _helix_milling_of(op):
    from avangardecam.engine import helix

    return helix.helix_milling_of(op)


def _deburring_of(op):
    from avangardecam.engine import deburring

    return deburring.deburring_of(op)


def operation_menu(op, parent=None):
    """Edit..., Activate geometry, Make 0-Point active, Switch off (on), Hide in 3D (Show in 3D), Delete of an operation."""
    from avangardecam import handlers

    menu = QtWidgets.QMenu(parent)
    menu.setObjectName("AvangardeCamOperationMenu")
    edit = menu.addAction(tr("Edit..."))
    edit.setObjectName("AvangardeCamEditOperation")
    made = (cam.contour_of, cam.drilling_of, cam.thread_milling_of, cam.adaptive_of, _facing_of, _slot_milling_of, _helix_milling_of)  # fmt: skip
    edit.setEnabled(any(f(op) is not None for f in made))
    edit.setToolTip(tr("Change it in the window it was made in"))
    edit.triggered.connect(lambda: handlers.edit_operation(op))
    activate_geometry.add_to_menu(menu, op)
    ui_op_zero.add_to_menu(menu, op)
    on = bool(op.Active)
    switch = menu.addAction(tr("Switch off") if on else tr("Switch on"))
    switch.setObjectName("AvangardeCamSwitchOperation")
    switch.setToolTip(tr("Off: it stays in the list, but not in the program or the simulation"))
    switch.triggered.connect(lambda: handlers.switch_operation(op, not on))
    hidden = scene.hidden(op)
    hide = menu.addAction(tr("Show in 3D") if hidden else tr("Hide in 3D"))
    hide.setObjectName("AvangardeCamHideOperation")
    hide.setToolTip(tr("Only the view: the operation stays in the program"))
    hide.triggered.connect(lambda: _hide(op, not hidden, parent))
    menu.addSeparator()
    delete_operation.add_to_menu(menu, op, parent)
    menu.setToolTipsVisible(True)
    return menu


def _hide(op, hide, panel):
    scene.set_hidden(op, hide)
    if panel is not None:
        panel.refresh()  # the mark after its name
