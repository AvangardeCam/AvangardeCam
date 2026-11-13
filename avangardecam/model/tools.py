# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""A cutting tool: its geometry and the cutting data it runs with."""

import math
from dataclasses import dataclass
from typing import Optional

SHAPES = ("Endmill", "Bullnose", "Ballend", "Drill", "Chamfer", "VBit", "ThreadMill")


@dataclass(frozen=True)
class Tool:
    name: str
    shape: str  # one of SHAPES
    diameter_mm: float
    flutes: Optional[int] = None
    corner_radius_mm: Optional[float] = None
    angle_deg: Optional[float] = None  # drill point angle, chamfer/V-bit/thread profile included angle
    tip_diameter_mm: Optional[float] = None  # chamfer/V-bit
    cutting_length_mm: Optional[float] = None
    length_mm: Optional[float] = None
    shank_diameter_mm: Optional[float] = None
    neck_diameter_mm: Optional[float] = None  # thread mill
    neck_length_mm: Optional[float] = None  # thread mill: from the tip up to the shank
    pitch_mm: Optional[float] = None  # thread mill
    tool_material: str = ""  # what the tool is made of, e.g. Carbide
    spindle_rpm: Optional[float] = None
    feed_xy_mm_min: Optional[float] = None
    feed_z_mm_min: Optional[float] = None

    def validate(self):
        """Raise ValueError when a value cannot be right."""
        if self.shape not in SHAPES:
            raise ValueError("{}: unknown tool shape {!r}".format(self.name, self.shape))
        if not self.diameter_mm > 0:
            raise ValueError("{}: diameter must be > 0 mm".format(self.name))
        if self.shape == "ThreadMill" and not (self.pitch_mm or 0) > 0:
            raise ValueError("{}: a thread mill needs a pitch > 0 mm".format(self.name))
        for label, value in (
            ("spindle speed", self.spindle_rpm),
            ("XY feed", self.feed_xy_mm_min),
            ("Z feed", self.feed_z_mm_min),
        ):
            if value is not None and not value > 0:
                raise ValueError("{}: {} must be > 0".format(self.name, label))
        return self


def tip_length_mm(tool):
    """Length of a drill's point: how much deeper its tip goes than its
    full diameter. 0 for flat tools (180°) and tools without a point angle."""
    if tool.shape != "Drill" or not tool.angle_deg or not 0.0 < tool.angle_deg < 180.0:
        return 0.0
    return tool.diameter_mm / 2.0 / math.tan(math.radians(tool.angle_deg) / 2.0)


def describe(tool):
    """Short one-line description, e.g. 'Bullnose Ø6 mm R0.2'."""
    text = "{} Ø{:g} mm".format(tool.shape, tool.diameter_mm)
    if tool.corner_radius_mm:
        text += " R{:g}".format(tool.corner_radius_mm)
    if tool.pitch_mm:
        text += " P{:g}".format(tool.pitch_mm)
    if tool.angle_deg and tool.shape != "Drill":
        text += " {:g}°".format(tool.angle_deg)
    return text
