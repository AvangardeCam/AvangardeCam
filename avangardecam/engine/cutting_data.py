# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The cutting data of an operation (model.cutting_data) on FreeCAD.

The operation's own values are kept on it (AvangardeSpindle,
AvangardeFeedXY, AvangardeFeedZ; 0 or none: the tool's). The tool
controller, shared by the operations with that tool, keeps the tool's, so
FreeCAD's path is made with those; the NC program puts the own ones on it
(freecad_cam.nc_operation calls operation()), and with it Simulate, Verify
and the cycle time.
"""

from avangardecam.engine import freecad_cam as cam
from avangardecam.model import cutting_data as model

PROPERTIES = (
    ("spindle_rpm", "AvangardeSpindle", "Spindle speed of this operation, rpm (0: the tool's)"),
    ("feed_xy_mm_min", "AvangardeFeedXY", "XY feed of this operation, mm/min (0: the tool's)"),
    ("feed_z_mm_min", "AvangardeFeedZ", "Z feed of this operation, mm/min (0: the tool's)"),
)


def own(op):
    """The operation's own values (model CuttingData; empty: all the tool's)."""
    values = {}
    for field, name, _tip in PROPERTIES:
        value = float(getattr(op, name, 0.0) or 0.0)
        values[field] = value if value > 0 else None
    return model.CuttingData(**values)


def set_own(op, data):
    """Keep data (model CuttingData) as the operation's own values; empty
    data leaves an operation that has none untouched."""
    data = (data or model.NONE).validate()
    if data.empty() and not any(hasattr(op, name) for _field, name, _tip in PROPERTIES):
        return
    for field, name, tip in PROPERTIES:
        cam._add_property(op, "App::PropertyFloat", name, tip)
        value = getattr(data, field)
        setattr(op, name, float(value) if value is not None else 0.0)


def tool(op):
    """The model Tool the operation runs with: its tool controller's with
    the operation's own values; None without a tool."""
    tc = getattr(op, "ToolController", None)
    if tc is None or getattr(tc, "Tool", None) is None:
        return None
    return model.applied(cam._tool_from_controller(tc), own(op))


def operation(op, nc_operation):
    """The operation's model.nc.Operation (made with the tool's values) run
    with the operation's own."""
    return model.operation(nc_operation, own(op))
