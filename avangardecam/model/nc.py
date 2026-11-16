# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""An NC program as the machine runs it, before it is written for one
control: the setups, each with its zero point (a preset of the machine)
and stock, and the tool moves of their operations in the setup's
coordinates (the G-code coordinates). Postprocessors (post/) write it.
"""

import datetime
from dataclasses import dataclass
from typing import NamedTuple, Optional, Tuple

from avangardecam.model.stock import Bounds

RAPID = "rapid"
LINE = "line"
ARC = "arc"

# operation kinds the postprocessors know
CONTOUR = "contour"
DRILLING = "drilling"  # moves: none, the cycle drills the holes
THREAD_MILLING = "thread_milling"  # moves: the helices, with compensation (model.threads)
ADAPTIVE = "adaptive"  # moves: the clearing (model.clearing)
FACING = "facing"  # moves: the passes (model.facing)
SLOT_MILLING = "slot_milling"  # moves: the slots, finished with compensation (model.slot)
HELIX_MILLING = "helix_milling"  # moves: the holes, with compensation (model.helix)
DEBURRING = "deburring"  # moves: a contour of a chamfer mill, without compensation (model.deburring)

# radius compensation of a move, seen along the tool's direction: the
# control keeps the tool this side of the programmed point by its radius
# from the tool table (Heidenhain RL/RR, G41/G42); None: the tool centre
# is on the point (R0)
LEFT = "left"
RIGHT = "right"


@dataclass(frozen=True)
class Tool:
    number: int
    name: str
    diameter_mm: float
    spindle_rpm: float
    feed_z_mm_min: float  # plunging
    feed_xy_mm_min: float  # cutting
    clockwise: bool = True


class Move(NamedTuple):
    """A move to an end point, absolute; an axis is None while the program
    has not moved it yet (the first moves after a tool change)."""

    kind: str  # RAPID, LINE or ARC
    x: Optional[float]
    y: Optional[float]
    z: Optional[float]
    feed_mm_min: Optional[float] = None  # LINE and ARC
    center: Optional[Tuple[float, float]] = None  # ARC, in the XY plane
    clockwise: bool = False  # ARC, seen from +Z
    compensation: Optional[str] = None  # LEFT or RIGHT, the side of the tool


class DrillHole(NamedTuple):
    """A hole of a drilling, in the setup's coordinates."""

    x: float
    y: float
    surface_z: float  # its top (Heidenhain: Z of CYCL CALL POS)
    depth_mm: float  # Q201, of the tip, below its top (negative)


@dataclass(frozen=True)
class DrillCycle:
    """A drilling as the control's universal pecking cycle runs it
    (Heidenhain cycle 205), on each hole in turn. Heights are measured from
    the surface, the top of each hole (negative: below it). Holes picked in
    a model have each their own top and may have their own depth."""

    peck_mm: Optional[float]  # Q202, the depth of one peck; None: the whole depth at once
    feed_mm_min: float  # Q206, down
    clearance_mm: float  # Q200, the cycle starts there
    second_clearance_mm: float  # Q204, from hole to hole
    decrement_mm: float  # Q212
    min_peck_mm: float  # Q205
    upper_stop_mm: float  # Q258
    lower_stop_mm: float  # Q259
    chip_break_mm: float  # Q257, 0: no chip breaking
    chip_retract_mm: float  # Q256
    dwell_s: float  # Q211
    start_mm: float  # Q379, deepened starting point
    preposition_feed_mm_min: float  # Q253, to the deepened starting point
    holes: tuple  # DrillHole, in the order the tool drills them


@dataclass(frozen=True)
class Operation:
    kind: str  # CONTOUR, DRILLING, or another kind a postprocessor may not know
    label: str
    tool: Tool
    moves: tuple
    cycle: Optional[DrillCycle] = None  # DRILLING
    # the zero point the operation counts from when it is not the setup's
    # preset (experimental, model.op_zero): a model.frame.Frame, its origin
    # and axes in the preset's coordinates; the moves are counted from it
    zero: Optional[object] = None


@dataclass(frozen=True)
class Setup:
    preset: int  # the machine's preset (zero point) the setup runs on
    label: str
    stock: Optional[Bounds]  # None: the program has no BLK FORM
    operations: tuple


@dataclass(frozen=True)
class Program:
    name: str
    comment: str
    date: datetime.date
    setups: tuple

    def operations(self):
        return [op for setup in self.setups for op in setup.operations]
