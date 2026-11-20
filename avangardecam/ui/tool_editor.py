# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The window of one tool of the tool library: a new one, a copy or one to
change (model.tool_editing). Its type chooses the geometry fields, named
with the letters of FreeCAD's drawing of the type shown beside them. The
spindle speed and feeds with Vc and fz to check them. OK says what is
missing or wrong and keeps the window open until the tool can be saved.

ui.tool_library saves it (engine.tool_library_file).
"""

import dataclasses
import os

import FreeCAD

from PySide import QtCore, QtGui, QtSvg, QtWidgets

from avangardecam import tr
from avangardecam.model import cutting_data, library, tool_editing
from avangardecam.model.tools import SHAPES, Tool

# how the window names the types
SHAPE_LABELS = {
    "Endmill": "End mill",
    "Bullnose": "End mill with corner radius",
    "Ballend": "Ball end mill",
    "Drill": "Drill",
    "Chamfer": "Chamfer mill",
    "VBit": "V-bit",
    "ThreadMill": "Thread mill",
}
_ANGLES = {"angle_deg"}
_COUNTS = {"flutes"}
# 0 is a value here (a pointed tip), not "none": FreeCAD would put its own in
_ZERO_IS_A_VALUE = {"tip_diameter_mm"}
_SPEEDS = (
    ("spindle_rpm", "Spindle speed", " rpm", 100000.0, 0),
    ("feed_xy_mm_min", "Feed XY", " mm/min", 50000.0, 1),
    ("feed_z_mm_min", "Feed Z", " mm/min", 50000.0, 1),
)
_TEXTS = (("manufacturer", "Manufacturer"), ("order_code", "Order code"), ("comment", "Comment"))


def drawing_path(shape):
    """FreeCAD's drawing of a tool type, "" when it is not there."""
    path = os.path.join(FreeCAD.getHomePath(), "Mod", "CAM", "Tools", "Shape", tool_editing.DRAWINGS[shape])
    return path if os.path.exists(path) else ""


class Drawing(QtWidgets.QWidget):
    """A tool type's drawing, kept in proportion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamToolDrawing")
        self.setFixedSize(230, 300)
        self.renderer = QtSvg.QSvgRenderer(self)
        self.shown = ""

    def show_shape(self, shape):
        path = drawing_path(shape)
        self.shown = path
        self.renderer.load(path) if path else self.renderer.load(QtCore.QByteArray())
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#FFFFFF"))
        if self.shown and self.renderer.isValid():
            size = self.renderer.defaultSize()
            size.scale(self.width() - 16, self.height() - 16, QtCore.Qt.KeepAspectRatio)
            x = (self.width() - size.width()) / 2.0
            y = (self.height() - size.height()) / 2.0
            self.renderer.render(painter, QtCore.QRectF(x, y, size.width(), size.height()))
        painter.end()


def _number_box(name, decimals, suffix, highest):
    box = QtWidgets.QDoubleSpinBox()
    box.setObjectName(name)
    box.setDecimals(decimals)
    box.setRange(0.0, highest)
    box.setSuffix(suffix)
    box.setSpecialValueText("-")  # 0: none
    box.setKeyboardTracking(False)
    return box


class ToolEditorDialog(QtWidgets.QDialog):
    """entry: the LibraryTool to start from (tool_editing.blank for a new
    one); entries: the library, for the materials and the T numbers."""

    def __init__(self, entry, entries, title, parent=None):
        super().__init__(parent)
        self.setObjectName("AvangardeCamToolEditor")
        self.setWindowTitle(title)
        self.start = entry
        self.entries = list(entries)
        self.values = dataclasses.asdict(entry.tool)  # geometry kept over a change of type
        self.start_values = dict(self.values)
        self.tried = False  # OK was clicked: the problems show as they change
        outer = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        outer.addLayout(left, 1)

        top = QtWidgets.QFormLayout()
        self.number = QtWidgets.QSpinBox()
        self.number.setObjectName("AvangardeCamToolNumber")
        self.number.setRange(0, 9999)
        self.number.setPrefix("T")
        self.number.setValue(entry.number)
        top.addRow(tr("T number") + ":", self.number)
        self.same = QtWidgets.QLabel()
        self.same.setObjectName("AvangardeCamToolSameNumber")
        self.same.setWordWrap(True)
        self.same.setStyleSheet("color: #808080;")
        top.addRow(self.same)
        self.name = QtWidgets.QLineEdit(entry.tool.name)
        self.name.setObjectName("AvangardeCamToolName")
        self.name.setPlaceholderText(tr("as the machine's tool table names it, e.g. VHM ALU Frees 6mm"))
        top.addRow(tr("Name") + ":", self.name)
        self.shape = QtWidgets.QComboBox()
        self.shape.setObjectName("AvangardeCamToolShape")
        for shape in SHAPES:
            self.shape.addItem(tr(SHAPE_LABELS[shape]), shape)
        self.shape.setCurrentIndex(SHAPES.index(entry.tool.shape))
        top.addRow(tr("Type") + ":", self.shape)
        self.material = QtWidgets.QComboBox()
        self.material.setObjectName("AvangardeCamToolWorkpieceMaterial")
        self.material.setEditable(True)
        self.material.addItems(library.materials(self.entries))
        self.material.setCurrentText(entry.workpiece_material)
        self.material.setToolTip(tr("What the spindle speed and feeds are for; the same T number may have one variant per material"))  # fmt: skip
        top.addRow(tr("Workpiece material") + ":", self.material)
        left.addLayout(top)

        self.geometry_box = QtWidgets.QGroupBox(tr("Geometry"))
        self.geometry = QtWidgets.QFormLayout(self.geometry_box)
        self.boxes = {}  # geometry field name: its box, of the type shown
        left.addWidget(self.geometry_box)

        speeds_box = QtWidgets.QGroupBox(tr("Spindle speed and feeds"))
        speeds = QtWidgets.QGridLayout(speeds_box)
        self.speeds = {}
        for row, (field, label, unit, highest, decimals) in enumerate(_SPEEDS):
            box = _number_box("AvangardeCamTool" + field, decimals, unit, highest)
            box.setValue(getattr(entry.tool, field) or 0.0)
            box.valueChanged.connect(self._changed)
            speeds.addWidget(QtWidgets.QLabel(tr(label) + ":"), row, 0)
            speeds.addWidget(box, row, 1)
            self.speeds[field] = box
        self.vc = QtWidgets.QLabel()
        self.vc.setObjectName("AvangardeCamToolVc")
        speeds.addWidget(self.vc, 0, 2)
        self.fz = QtWidgets.QLabel()
        self.fz.setObjectName("AvangardeCamToolFz")
        speeds.addWidget(self.fz, 1, 2)
        speeds.setColumnStretch(1, 1)
        left.addWidget(speeds_box)

        more = QtWidgets.QFormLayout()
        self.tool_material = QtWidgets.QComboBox()
        self.tool_material.setObjectName("AvangardeCamToolMaterial")
        self.tool_material.setEditable(True)
        self.tool_material.addItems(tool_editing.TOOL_MATERIALS)
        self.tool_material.setCurrentText(entry.tool.tool_material)
        more.addRow(tr("Tool material") + ":", self.tool_material)
        self.texts = {}
        for field, label in _TEXTS:
            edit = QtWidgets.QLineEdit(getattr(entry, field))
            edit.setObjectName("AvangardeCamTool" + field)
            more.addRow(tr(label) + ":", edit)
            self.texts[field] = edit
        left.addLayout(more)

        self.message = QtWidgets.QLabel()
        self.message.setObjectName("AvangardeCamToolEditorMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        left.addWidget(self.message)
        left.addStretch(1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        left.addWidget(buttons)

        self.drawing = Drawing()
        right = QtWidgets.QVBoxLayout()
        right.addWidget(self.drawing)
        right.addStretch(1)
        outer.addLayout(right)

        self.number.valueChanged.connect(self._changed)
        self.name.textChanged.connect(self._changed)
        self.material.currentTextChanged.connect(self._changed)
        self.shape.currentIndexChanged.connect(self._shape_changed)
        self._show_geometry()
        self._changed()
        self.name.setFocus()

    # -- geometry of the type -------------------------------------------------

    def _shape(self):
        return self.shape.currentData()

    def _keep_geometry(self):
        for name, box in self.boxes.items():
            value = box.value()
            start = self.start_values.get(name)
            if isinstance(box, QtWidgets.QDoubleSpinBox) and start is not None and abs(start - value) < 0.5 * 10**-box.decimals():
                value = start  # as it was, not as the box rounds it: OK without a change changes nothing
            self.values[name] = value if value or name in _ZERO_IS_A_VALUE else None

    def _shape_changed(self, *_args):
        self._keep_geometry()
        shape = self._shape()
        for name, value in tool_editing.DEFAULTS.get(shape, {}).items():
            if not self.values.get(name):
                self.values[name] = value
        self._show_geometry()
        self._changed()

    def _show_geometry(self):
        while self.geometry.rowCount():
            self.geometry.removeRow(0)
        self.boxes = {}
        shape = self._shape()
        for field in tool_editing.FIELDS[shape]:
            if field.name in _COUNTS:
                box = QtWidgets.QSpinBox()
                box.setObjectName("AvangardeCamTool" + field.name)
                box.setRange(0, 20)
                box.setSpecialValueText("-")
                box.setValue(int(self.values.get(field.name) or 0))
            else:
                angle = field.name in _ANGLES
                box = _number_box("AvangardeCamTool" + field.name, 1 if angle else 3, " °" if angle else " mm", 180.0 if angle else 1000.0)  # fmt: skip
                box.setValue(self.values.get(field.name) or 0.0)
                if field.name in _ZERO_IS_A_VALUE:
                    box.setSpecialValueText("")
            box.valueChanged.connect(self._changed)
            label = tr(field.label) + (" ({})".format(field.letter) if field.letter else "") + ":"
            self.geometry.addRow(label, box)
            self.boxes[field.name] = box
        self.drawing.show_shape(shape)

    # -- the tool -------------------------------------------------------------

    def entry(self):
        """The LibraryTool as the window has it (the start's id)."""
        self._keep_geometry()
        geometry = {name: self.values.get(name) for name in tool_editing.GEOMETRY}
        geometry["flutes"] = int(geometry["flutes"]) if geometry.get("flutes") else None
        tool = Tool(
            name=self.name.text().strip(),
            shape=self._shape(),
            diameter_mm=geometry.pop("diameter_mm") or 0.0,
            tool_material=self.tool_material.currentText().strip(),
            **geometry,
            **{field: (self.speeds[field].value() or None) for field, *_rest in _SPEEDS},
        )
        return library.LibraryTool(
            id=self.start.id,
            number=self.number.value(),
            workpiece_material=self.material.currentText().strip(),
            tool=tool_editing.fitted(tool),
            **{field: edit.text().strip() for field, edit in self.texts.items()},
        )

    def problems(self):
        return tool_editing.problems(self.entry(), self.entries)

    def _changed(self, *_args):
        entry = self.entry()
        tool = entry.tool
        vc = cutting_data.vc_m_min(tool.diameter_mm, tool.spindle_rpm)
        self.vc.setText("Vc {:.0f} m/min".format(vc) if vc else "")
        fz = cutting_data.fz_mm(tool.feed_xy_mm_min, tool.spindle_rpm, tool.flutes)
        if fz:
            self.fz.setText("fz {:.3f} mm".format(fz))
        elif tool.feed_xy_mm_min and tool.spindle_rpm:
            self.fz.setText("f {:.3f} mm/{}".format(tool.feed_xy_mm_min / tool.spindle_rpm, tr("rev")))
        else:
            self.fz.setText("")
        others = tool_editing.same_number(self.entries, entry)
        self.same.setText(
            tr("T{} in the library also: {}").format(
                entry.number, ", ".join("{} ({})".format(e.tool.name, e.workpiece_material or "?") for e in others)
            )
            if others
            else ""
        )
        self.same.setVisible(bool(others))
        if self.tried:
            self.message.setText("\n".join(tr(p) for p in self.problems()))

    def accept(self):
        self.tried = True
        found = self.problems()
        if found:
            self.message.setText("\n".join(tr(p) for p in found))
            return
        super().accept()
