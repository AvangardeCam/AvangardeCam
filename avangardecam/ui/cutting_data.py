# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Cutting data in the window of an operation (model.cutting_data): the
spindle speed and feeds, filled from the chosen tool, each changeable for
this operation. A changed value is bold and marked "own"; From tool puts
the tool's values back. Another tool fills in its values.

Vc (cutting speed) and fz (feed per tooth) are worked out beside them, to
check the values; they are not typed.

ui.tool_choice.ToolChooser has the fields under the tool; the handlers keep
own() on the operation (engine.cutting_data).
"""

from PySide import QtCore, QtGui, QtWidgets

from avangardecam import tr
from avangardecam.model import cutting_data as model

# (field, label, unit, highest, decimals)
_FIELDS = (
    ("spindle_rpm", "Spindle speed", "rpm", 100000.0, 0),
    ("feed_xy_mm_min", "Feed XY", "mm/min", 50000.0, 1),
    ("feed_z_mm_min", "Feed Z", "mm/min", 50000.0, 1),
)
_NAMES = {"spindle_rpm": "Spindle", "feed_xy_mm_min": "FeedXY", "feed_z_mm_min": "FeedZ"}


def _g(value, decimals=0):
    return "{:.{}f}".format(value, decimals) if value is not None else ""


class CuttingDataFields(QtWidgets.QWidget):
    """Spindle speed, feed XY and feed Z of an operation; prefix names its
    widgets (prefix + "Spindle", "FeedXY", "FeedZ", "FromTool", "Vc", "Fz")."""

    changed = QtCore.Signal()

    def __init__(self, prefix, parent=None):
        super().__init__(parent)
        self.tool = None  # the chosen tool's model Tool
        self.boxes = {}
        self.titles = {}
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 0)
        for row, (field, label, unit, highest, decimals) in enumerate(_FIELDS):
            title = QtWidgets.QLabel(tr(label) + ":")
            box = QtWidgets.QDoubleSpinBox()
            box.setObjectName(prefix + _NAMES[field])
            box.setRange(0.0, highest)
            box.setDecimals(decimals)
            box.setSuffix(" " + unit)
            box.setSpecialValueText(tr("none"))  # 0: the tool has none and none is typed
            box.setKeyboardTracking(False)
            box.setToolTip(tr("Filled from the tool; a changed value is this operation's own (bold)."))
            box.valueChanged.connect(self._edited)
            grid.addWidget(title, row, 0)
            grid.addWidget(box, row, 1)
            self.boxes[field] = box
            self.titles[field] = title
        self.names = {field: label for field, label, *_rest in _FIELDS}  # English, translated when shown
        self.vc = QtWidgets.QLabel()
        self.vc.setObjectName(prefix + "Vc")
        self.vc.setToolTip(tr("Cutting speed at the tool's diameter: π × Ø × rpm / 1000"))
        grid.addWidget(self.vc, 0, 2)
        self.fz = QtWidgets.QLabel()
        self.fz.setObjectName(prefix + "Fz")
        self.fz.setToolTip(tr("Feed per tooth: feed XY / (rpm × flutes); without the flutes, per turn"))
        grid.addWidget(self.fz, 1, 2)
        self.from_tool = QtWidgets.QPushButton(tr("From tool"))
        self.from_tool.setObjectName(prefix + "FromTool")
        self.from_tool.setToolTip(tr("The tool's spindle speed and feeds again"))
        self.from_tool.clicked.connect(self.reset)
        grid.addWidget(self.from_tool, 2, 2)
        grid.setColumnStretch(1, 1)
        self._show()

    def set_labels(self, feed_xy, feed_z):
        """Other names of the feeds (a drilling: Q206, Q253)."""
        self.names.update(feed_xy_mm_min=feed_xy, feed_z_mm_min=feed_z)
        self._show()

    def set_tool(self, tool):
        """The chosen tool (model Tool or None): its values in the fields;
        the same tool again keeps what was typed."""
        if tool == self.tool:
            return
        self.tool = tool
        self.reset()

    def reset(self):
        """The tool's values in all fields."""
        for field, box in self.boxes.items():
            box.blockSignals(True)
            box.setValue(getattr(self.tool, field, None) or 0.0)
            box.blockSignals(False)
        self._edited()

    def start(self, data):
        """An operation's own values (model CuttingData) over the tool's."""
        for field, box in self.boxes.items():
            value = getattr(data, field)
            if value is not None:
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)
        self._edited()

    def values(self):
        """(rpm, feed XY, feed Z) as in the fields, None for none."""
        return tuple(self.boxes[field].value() or None for field, *_rest in _FIELDS)

    def own(self):
        """The values that differ from the tool's (model CuttingData)."""
        return model.own(self.tool, self.values())

    def cutting_tool(self):
        """The tool with the values of the fields (model Tool or None)."""
        return model.applied(self.tool, self.own()) if self.tool is not None else None

    def _edited(self, *_args):
        self._show()
        self.changed.emit()

    def _show(self):
        own = self.own()
        for field, box in self.boxes.items():
            mine = getattr(own, field) is not None
            font = box.font()
            font.setBold(mine)
            box.setFont(font)
            self.titles[field].setText(tr(self.names[field]) + (" " + tr("(own)") if mine else "") + ":")
        self.from_tool.setEnabled(self.tool is not None and not own.empty())
        rpm, feed_xy, _feed_z = self.values()
        tool = self.tool
        vc = model.vc_m_min(tool.diameter_mm, rpm) if tool is not None else None
        self.vc.setText("Vc {} m/min".format(_g(vc)) if vc else "")
        flutes = tool.flutes if tool is not None else None
        fz = model.fz_mm(feed_xy, rpm, flutes)
        if fz:
            self.fz.setText("fz {} mm".format(_g(fz, 3)))
        elif feed_xy and rpm:
            self.fz.setText("f {} mm/{}".format(_g(feed_xy / rpm, 3), tr("rev")))
        else:
            self.fz.setText("")
