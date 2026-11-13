# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Deburring: a chamfer mill along picked sketch lines (the edges of a
face), without compensation, its centre beside the lines on the side
chosen (left of the arrows by default: with M3 climbing, as RL).

By default the user enters only the size of the chamfer and how far the
tool's tip goes below it; the depth and the offset of the tool centre
follow from the tool's cone (cut). Under Advanced the user enters them
(Z-Depth, XY offset) as in Contour tooling, and Start contour / End
contour. Either way it is made as a contour (to_contour): one pass at
the depth, Relative to the lines, compensation off, the approach on an
arc on the tool's side or straight down.

The chamfer's size is its width on the face of the lines (for the usual
90° tool: both legs). A cone of half angle a, tip radius r and tip e
below the chamfer of size c cuts it with its tip at

    depth  = c / tan(a) + e      below the lines
    offset = r + e * tan(a)      the tool centre beside them,

so the offset does not depend on the chamfer: a larger chamfer is the
tool going deeper on the same line. The tip's edge stays e * tan(a) clear
of the wall under the chamfer.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple, Optional

from avangardecam.model import operations as model_operations
from avangardecam.model.nc import LEFT, RIGHT

DEFAULT_CHAMFER_MM = 0.5
DEFAULT_TIP_MM = 0.5
SHAPES = ("Chamfer", "VBit")  # tools with a cone that chamfers an edge
_EPSILON_MM = 1e-6


class Cone(NamedTuple):
    """The cutting cone of a chamfer mill: radius of its tip, tangent of
    its half angle, radius where it ends (the tool's)."""

    tip_radius_mm: float
    slope: float  # tan(half angle): how much the radius grows per mm up
    radius_mm: float

    def radius_at(self, height_mm):
        """Radius of the cone height_mm above the tip."""
        return self.tip_radius_mm + height_mm * self.slope


def cone(tool):
    """The Cone of a model Tool; ValueError for a tool without one."""
    if tool.shape not in SHAPES:
        raise ValueError(
            "{} is not a chamfer mill: deburring needs a tool with a cone (chamfer mill or V-bit)".format(tool.name)
        )
    if not tool.angle_deg or not 0.0 < tool.angle_deg < 180.0:
        raise ValueError("{} has no angle between 0° and 180°: its cone is not known".format(tool.name))
    tip = (tool.tip_diameter_mm or 0.0) / 2.0
    radius = tool.diameter_mm / 2.0
    if tip >= radius:
        raise ValueError("{}: its tip ({:g} mm) is not smaller than the tool ({:g} mm)".format(tool.name, 2 * tip, 2 * radius))
    return Cone(tip, math.tan(math.radians(tool.angle_deg) / 2.0), radius)


@dataclass(frozen=True)
class Deburring:
    """What the user asked for. chamfer_mm: width of the chamfer on the
    face of the lines; tip_mm: how far the tool's tip goes below it.
    side: the tool's side of the lines seen along the arrows (LEFT: with
    M3 climbing). approach NONE (straight down beside the lines) or ARC
    (lead_radius_mm, None: the default for the tool).

    advanced: the user's own z_depth_mm (the tip, from the lines; negative
    below them) and offset_xy_mm (the tool centre beside the lines, on the
    side) instead of the ones worked out of the chamfer, and Start / End
    contour (start_extend_mm, end_extend_mm, as model Contour). Without
    Advanced those are kept as the window last showed them but not used.
    """

    chamfer_mm: float = DEFAULT_CHAMFER_MM
    tip_mm: float = DEFAULT_TIP_MM
    side: str = LEFT
    approach: str = model_operations.NONE  # an arc does not fit in small holes
    lead_radius_mm: Optional[float] = None
    advanced: bool = False
    z_depth_mm: float = -(DEFAULT_CHAMFER_MM + DEFAULT_TIP_MM)
    offset_xy_mm: float = DEFAULT_TIP_MM
    start_extend_mm: float = 0.0
    end_extend_mm: float = 0.0

    KIND = "deburring"

    def validate(self):
        limit = model_operations.MAX_DEPTH_MM
        if not 0.0 < self.chamfer_mm <= limit:
            raise ValueError("The chamfer must be larger than 0 mm, got {:g} mm".format(self.chamfer_mm))
        if not 0.0 <= self.tip_mm <= limit:
            raise ValueError("Tip below chamfer must be 0 mm or more, got {:g} mm".format(self.tip_mm))
        if self.side not in (LEFT, RIGHT):
            raise ValueError("unknown side of the lines: {!r}".format(self.side))
        if self.approach not in model_operations.APPROACHES:
            raise ValueError("unknown approach: {!r}".format(self.approach))
        if not isinstance(self.advanced, bool):
            raise ValueError("Advanced must be true or false, got {!r}".format(self.advanced))
        if self.lead_radius_mm is not None and not 0.0 < self.lead_radius_mm <= limit:
            raise ValueError("The approach radius must be larger than 0 mm, got {:g} mm".format(self.lead_radius_mm))
        if self.advanced and not -limit <= self.z_depth_mm < -_EPSILON_MM:
            raise ValueError("Z-Depth must be below the lines (negative), got {:g} mm".format(self.z_depth_mm))
        for text, value in (
            ("The XY offset", self.offset_xy_mm), ("Start contour", self.start_extend_mm), ("End contour", self.end_extend_mm),
        ):  # fmt: skip
            if not -limit <= value <= limit:
                raise ValueError("{} must be within {:g} mm, got {:g} mm".format(text, limit, value))
        return self


def cut(deburring, tool):
    """(depth below the lines, offset of the tool centre beside them), mm,
    as the tool runs: Advanced the user's, else worked out of the chamfer
    and the tool's cone."""
    if deburring.advanced:
        return -deburring.z_depth_mm, deburring.offset_xy_mm
    c = cone(tool)
    return (
        _round(deburring.chamfer_mm / c.slope + deburring.tip_mm),
        _round(c.tip_radius_mm + deburring.tip_mm * c.slope),
    )


def chamfer_of(depth_mm, offset_mm, tool):
    """(chamfer, tip below it), mm, that a cut depth_mm below the lines with
    the tool centre offset_mm beside them makes (Advanced shows it)."""
    c = cone(tool)
    tip = (offset_mm - c.tip_radius_mm) / c.slope
    return _round((depth_mm - tip) * c.slope), _round(tip)


def check(deburring, tool):
    """Raise ValueError when the tool cannot make the chamfer: the cone
    ends below the face of the lines (the chamfer too large for it), or
    its tip cuts the wall under the chamfer, or the cut makes no chamfer."""
    deburring.validate()
    c = cone(tool)
    depth, offset = cut(deburring, tool)
    chamfer, tip = chamfer_of(depth, offset, tool)
    if tip < -_EPSILON_MM:
        raise ValueError(
            "The tool centre is {:g} mm beside the lines, less than the radius of {}'s tip ({:g} mm): the tip would cut "
            "into the wall under the chamfer".format(offset, tool.name, c.tip_radius_mm)
        )
    if chamfer <= _EPSILON_MM:
        raise ValueError(
            "The tip is not deep enough for a chamfer: {:g} mm below the lines with the tool centre {:g} mm beside "
            "them makes none".format(depth, offset)
        )
    needed = c.radius_at(depth)
    if needed > c.radius_mm + _EPSILON_MM:
        largest = c.radius_mm - offset  # the cone's radius at the face is offset + chamfer
        raise ValueError(
            "{} is too small for this chamfer: at the face its cone would have to be Ø{:g} mm, the tool is Ø{:g} mm. "
            "With the tip {:g} mm below it the chamfer can be at most {:g} mm.".format(
                tool.name, _round(2 * needed), 2 * c.radius_mm, _round(tip), max(0.0, _round(largest))
            )
        )
    return deburring


def to_contour(deburring, tool):
    """The model Contour the deburring is made as (check it first)."""
    depth, offset = cut(deburring, tool)
    extend = deburring.advanced
    return model_operations.Contour(
        -depth,
        compensation=model_operations.OFF,
        approach=deburring.approach,
        lead_radius_mm=deburring.lead_radius_mm if deburring.approach == model_operations.ARC else None,
        offset_xy_mm=offset,
        start_z_mm=0.0,  # the top of the material: the lines; one pass (no Z steps)
        arc_side=deburring.side,
        start_extend_mm=deburring.start_extend_mm if extend else 0.0,
        end_extend_mm=deburring.end_extend_mm if extend else 0.0,
        relative=True,
    ).validate()


def to_json(deburring):
    return model_operations.to_json(deburring)


def from_json(text):
    import json

    data = json.loads(text)
    if data.pop("kind", None) != Deburring.KIND:
        raise ValueError("not a deburring: {}".format(text))
    return Deburring(**data).validate()


def _round(value):
    return round(value, 6) + 0.0
