# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Operations: what the user asked for, independent of how FreeCAD does it.

The engine stores an operation as JSON next to the FreeCAD operation made
from it, so the file remembers the user's own values.
"""

import json
import math
from dataclasses import asdict, dataclass
from typing import NamedTuple, Optional

from avangardecam.model.nc import LEFT, RIGHT

MAX_DEPTH_MM = 1000.0

# radius compensation of a contour, seen along the tool's direction
OFF = "off"  # the tool centre on the lines
COMPENSATIONS = (OFF, LEFT, RIGHT)  # LEFT: RL, RIGHT: RR

# how a contour's tool comes onto the lines and leaves them (model.leads)
ARC = "arc"  # on an arc, going down beside the lines
NONE = "none"  # straight down on the start of the lines
APPROACHES = (ARC, NONE)

# the order of a contour's rough passes
BY_PASS = "passes"  # each XY pass all the way down, then the next one closer to the lines
BY_LEVEL = "levels"  # all XY passes on a Z level, then the next level
ORDERS = (BY_PASS, BY_LEVEL)

MAX_CUTS = 5000  # passes x levels of one contour
_EPSILON_MM = 1e-6

# heights of the tool between the cuts, in the setup's coordinates, as
# the shop's programs have them: the tool comes down to APPROACH_Z_MM
# over its first point (the spindle starts there), then rapid to SAFETY_MM
# above the stock's top, and cuts from there
APPROACH_Z_MM = 20.0
SAFETY_MM = 2.0


@dataclass(frozen=True)
class Contour:
    """Contour tooling: the tool follows the lines of a sketch in one pass.

    relative (the user's Relative): z_depth_mm and start_z_mm are measured
    from the Z of the lines (their sketch's plane, in the setup's
    coordinates), each line from its own, so lines at other heights are cut
    each as deep below them; not relative: from the setup's zero point,
    wherever the lines are (base_mm). z_depth_mm -3 means 3 mm below that,
    into the material, +5 that the cut ends 5 mm above it (a step above
    the zero point). start_z_mm is the top of the material there: the Z
    levels go down from it (relative 0: the cut starts at the lines), so it
    must not be below z_depth_mm. Both the same: one pass at that height
    (e.g. deburring along Z0).

    compensation OFF: the tool centre is on the lines. LEFT or RIGHT: the
    program has the lines with RL or RR, so the control keeps the tool on
    that side of them by its radius.

    approach ARC: the tool goes down beside the lines and comes onto them
    on an arc of lead_radius_mm (None: model.leads.default_radius of the
    tool), and leaves them the same way. NONE: it goes down on the start
    of the lines (with compensation already on, above the part). Without
    compensation the arcs are on arc_side of the lines (LEFT or RIGHT,
    seen along the arrows).

    Passes (the user's choices). In Z: steps of z_step_mm (None: the whole
    depth at once), the last one what is left. In XY, with compensation
    only (it tells which side of the lines the material is on): xy_width_mm
    of material beside the lines is cut in equal passes no wider than
    xy_step_mm. Finishing: the rough passes leave finish_xy_mm on the wall
    and finish_z_mm on the floor; the last Z level takes the floor's, a
    last XY pass (by the same Z steps) the wall's. offset_xy_mm: the
    program's lines this far beside the sketch's on the tool's side, so
    the last pass leaves that much (negative: cuts past the lines, for a
    toleranced fit). Without compensation only offset_xy_mm, to arc_side:
    the tool centre runs that far beside the lines (a chamfer mill's centre
    beside the edge sets the chamfer's size). order: the rough passes BY_PASS (each XY pass all the
    way down, then the next one closer to the lines) or BY_LEVEL (all XY
    passes on one Z level, then the next level); the finishing pass comes
    last.

    start_extend_mm, end_extend_mm (Start contour, End contour; open lines
    only): the cut longer at its start or end by that much, straight on
    along the first or last line (e.g. to take the stock off past the
    part's corner), or negative shorter, starting or leaving that far
    along the lines (a chamfer mill leaves before a wall standing up at
    the end).
    """

    z_depth_mm: float
    compensation: str = OFF  # files from before compensation have none
    approach: str = NONE  # nor an approach (see from_json)
    lead_radius_mm: Optional[float] = None
    z_step_mm: Optional[float] = None  # files from before the passes have none of these
    xy_width_mm: float = 0.0
    xy_step_mm: Optional[float] = None
    finish_xy_mm: float = 0.0
    finish_z_mm: float = 0.0
    offset_xy_mm: float = 0.0
    order: str = BY_PASS
    start_z_mm: float = 0.0  # files from before Start Z start at the sketch plane
    arc_side: str = LEFT  # files from before the side came onto the lines from the left
    start_extend_mm: float = 0.0  # files from before Start/End contour run the whole lines
    end_extend_mm: float = 0.0
    relative: bool = True  # files from before Relative measure from the lines (the sketch plane)

    KIND = "contour"

    def validate(self):
        base = "the lines" if self.relative else "the zero point"
        for text, value in (("Z-Depth", self.z_depth_mm), ("Start Z", self.start_z_mm)):
            if not -MAX_DEPTH_MM <= value <= MAX_DEPTH_MM:
                raise ValueError("{} must be within {:g} mm of {}, got {:g} mm".format(text, MAX_DEPTH_MM, base, value))
        if self.z_depth_mm > self.start_z_mm + _EPSILON_MM:
            raise ValueError(
                "Z-Depth ({:g} mm) must not be above Start Z ({:g} mm), the top of the material".format(
                    self.z_depth_mm, self.start_z_mm
                )
            )
        if self.compensation not in COMPENSATIONS:
            raise ValueError("unknown tool compensation: {!r}".format(self.compensation))
        if not isinstance(self.relative, bool):
            raise ValueError("Relative must be true or false, got {!r}".format(self.relative))
        if self.approach not in APPROACHES:
            raise ValueError("unknown approach: {!r}".format(self.approach))
        if self.arc_side not in (LEFT, RIGHT):
            raise ValueError("unknown side of the lines: {!r}".format(self.arc_side))
        if self.lead_radius_mm is not None and not 0.0 < self.lead_radius_mm <= MAX_DEPTH_MM:
            raise ValueError("The approach radius must be larger than 0 mm, got {:g} mm".format(self.lead_radius_mm))
        for text, value in (("Z step", self.z_step_mm), ("XY step", self.xy_step_mm)):
            if value is not None and not 0.0 < value <= MAX_DEPTH_MM:
                raise ValueError("The {} must be larger than 0 mm, got {:g} mm".format(text, value))
        for text, value in (
            ("XY width", self.xy_width_mm),
            ("finishing allowance in XY", self.finish_xy_mm),
            ("finishing allowance in Z", self.finish_z_mm),
        ):
            if not 0.0 <= value <= MAX_DEPTH_MM:
                raise ValueError("The {} must be 0 mm or more, got {:g} mm".format(text, value))
        if not -MAX_DEPTH_MM <= self.offset_xy_mm <= MAX_DEPTH_MM:
            raise ValueError("The XY offset must be within {:g} mm, got {:g} mm".format(MAX_DEPTH_MM, self.offset_xy_mm))
        for text, value in (("Start contour", self.start_extend_mm), ("End contour", self.end_extend_mm)):
            if not -MAX_DEPTH_MM <= value <= MAX_DEPTH_MM:
                raise ValueError("{} must be within {:g} mm, got {:g} mm".format(text, MAX_DEPTH_MM, value))
        if self.order not in ORDERS:
            raise ValueError("unknown order of the passes: {!r}".format(self.order))
        if self.finish_z_mm and self.finish_z_mm >= self.depth_mm():
            raise ValueError(
                "The finishing allowance in Z ({:g} mm) must be less than the depth from Start Z ({:g} mm)".format(
                    self.finish_z_mm, self.depth_mm()
                )
            )
        if self.compensation == OFF and (self.xy_width_mm or self.finish_xy_mm):
            raise ValueError(
                "XY passes and the finishing allowance in XY need compensation left (RL) or right (RR): "
                "it tells on which side of the lines the material is"
            )
        if self._rough_room() > _EPSILON_MM and self.xy_step_mm is None:
            raise ValueError("Enter an XY step: the XY width is cut in passes no wider than it")
        if len(self.cuts()) > MAX_CUTS:
            raise ValueError(
                "{} passes are too many (at most {}); take larger steps".format(len(self.cuts()), MAX_CUTS)
            )
        return self

    def base_mm(self, lines_z_mm):
        """Z that Start Z, Z-Depth and levels() are measured from, in the
        setup's coordinates, for lines at lines_z_mm: their own Z when
        relative, else the zero point."""
        return lines_z_mm if self.relative else 0.0

    # -- passes ----------------------------------------------------------------

    def _rough_offset(self):
        """Where the innermost rough pass runs, from the lines."""
        return self.offset_xy_mm + self.finish_xy_mm

    def _rough_room(self):
        """Width of material the rough passes cut beside the innermost one
        (none without compensation: one pass, at the XY offset)."""
        if self.compensation == OFF:
            return 0.0
        return self.xy_width_mm - self._rough_offset()

    def rough_step_mm(self):
        """How much of the wall each rough XY pass takes (the XY width
        split into equal passes); None: one pass."""
        room = self._rough_room()
        if room <= _EPSILON_MM or self.xy_step_mm is None:
            return None
        return room / math.ceil(room / self.xy_step_mm - _EPSILON_MM)

    def xy_offsets(self):
        """Where the program's lines of each XY pass run, mm from the
        sketch's lines on the tool's side, in the order of the passes: the
        rough ones from the outside in, then the finishing one."""
        inner = self._rough_offset()
        step = self.rough_step_mm()
        count = 1 if step is None else int(round(self._rough_room() / step))
        offsets = [_round(inner + (count - 1 - k) * (step or 0.0)) for k in range(count)]
        if self.finish_xy_mm:
            offsets.append(self.offset_xy_mm)
        return offsets

    def depth_mm(self):
        """How deep the contour cuts, from Start Z down to Z-Depth."""
        return self.start_z_mm - self.z_depth_mm

    def levels(self):
        """Z levels from base_mm (negative below it), from the top:
        full Z steps down from Start Z, the last one what is left, and the
        finishing level."""
        rough = self.depth_mm() - self.finish_z_mm
        depths = []
        if self.z_step_mm is not None:
            k = 1
            while k * self.z_step_mm < rough - _EPSILON_MM:
                depths.append(_round(self.start_z_mm - k * self.z_step_mm))
                k += 1
        depths.append(_round(self.start_z_mm - rough))
        if self.finish_z_mm:
            depths.append(self.z_depth_mm)
        return depths

    def cuts(self):
        """(XY pass, depth) of each cut in the tool's order: an index into
        xy_offsets() and a depth of levels()."""
        passes = list(range(len(self.xy_offsets())))
        finish = [passes.pop()] if self.finish_xy_mm else []
        levels = self.levels()
        if self.order == BY_LEVEL:
            rough = [(p, z) for z in levels for p in passes]
        else:
            rough = [(p, z) for p in passes for z in levels]
        return rough + [(p, z) for p in finish for z in levels]


def _round(value):
    """No 9.900000000000002 mm from adding up steps."""
    return round(value, 6) + 0.0


# what a drilling's depth reaches (Drilling.depth_to)
TIP = "tip"  # the drill's tip
FULL_DIAMETER = "full"  # the end of its full diameter: the tip goes deeper by its point
DEPTH_REFERENCES = (TIP, FULL_DIAMETER)

# a through hole of a model: the drill's full diameter comes out under it this far
THROUGH_MM = 1.0


class HoleDepth(NamedTuple):
    """A hole of a model as deep as the model has it: the length of its
    cylinder below its top (negative) and whether it comes out the other
    side of the part."""

    depth_mm: float
    through: bool


@dataclass(frozen=True)
class Drilling:
    """Drilling: the TNC's universal pecking cycle (CYCL DEF 205) on each
    hole, in the order the user picked them.

    depth_mm is measured from the top of the holes (the sketch plane, or
    the top of each hole picked in a model) and negative, like a contour's
    Z-Depth. depth_to TIP: the drill's tip reaches it; FULL_DIAMETER: its
    full diameter does, so the tip goes deeper by the length of its point
    (tools.tip_length_mm).

    depth_mm None (holes picked in a model): each hole as deep as the model
    has it (HoleDepth). The full diameter reaches the end of the hole's
    cylinder, and comes out under a through hole by through_mm (the user's
    choice: 1 mm).

    The others are the cycle's own values, in its order:
    - peck_mm (Q202): how deep the drill goes before it comes out of the
      hole to clear the chips; None: the whole depth at once (by default
      1 mm, the user's choice);
    - decrement_mm (Q212): each peck is that much shorter than the one
      before, down to min_peck_mm (Q205);
    - upper_stop_mm (Q258), lower_stop_mm (Q259): back into the hole after
      a peck, the drill stops this far above where it was (rapid), at the
      first and at the last peck;
    - chip_break_mm (Q257): every so deep the drill backs off by
      chip_retract_mm (Q256) to break the chip, without leaving the hole;
      0: no chip breaking (by default 4 mm, the user's choice);
    - dwell_s (Q211): seconds at the bottom of the hole;
    - start_mm (Q379): the drilling starts this far below the top (a
      pilot hole is already there), the drill goes down to it with the
      pre-positioning feed;
    - clearance_mm (Q200): the cycle starts this far above the top;
    - second_clearance_mm (Q204): above the top the drill goes from hole
      to hole and ends at (the shop's programs: 50).

    The drill goes down with the tool's XY feed (Q206) and to a deepened
    start with its Z feed (Q253), as the shop's programs do.
    """

    depth_mm: Optional[float]
    depth_to: str = TIP
    peck_mm: Optional[float] = 1.0
    decrement_mm: float = 0.0
    min_peck_mm: float = 0.0
    upper_stop_mm: float = 0.2
    lower_stop_mm: float = 0.2
    chip_break_mm: float = 4.0
    chip_retract_mm: float = 0.2
    dwell_s: float = 0.0
    start_mm: float = 0.0
    clearance_mm: float = 2.0
    second_clearance_mm: float = 50.0
    through_mm: float = THROUGH_MM

    KIND = "drilling"

    def validate(self):
        if self.depth_mm is not None and not -MAX_DEPTH_MM <= self.depth_mm < 0.0:
            raise ValueError(
                "The depth must be negative (below the top of the holes) and not deeper "
                "than {:g} mm, got {:g} mm".format(-MAX_DEPTH_MM, self.depth_mm)
            )
        if self.depth_to not in DEPTH_REFERENCES:
            raise ValueError("unknown depth reference: {!r}".format(self.depth_to))
        if self.peck_mm is not None and not 0.0 < self.peck_mm <= MAX_DEPTH_MM:
            raise ValueError("The peck depth must be larger than 0 mm, got {:g} mm".format(self.peck_mm))
        for text, value in (
            ("decrement", self.decrement_mm),
            ("minimum peck depth", self.min_peck_mm),
            ("upper advanced stop distance", self.upper_stop_mm),
            ("lower advanced stop distance", self.lower_stop_mm),
            ("chip breaking depth", self.chip_break_mm),
            ("deepened starting point", self.start_mm),
            ("set-up clearance", self.clearance_mm),
            ("2nd set-up clearance", self.second_clearance_mm),
            ("depth under a through hole", self.through_mm),
        ):
            if not 0.0 <= value <= MAX_DEPTH_MM:
                raise ValueError("The {} must be 0 mm or more, got {:g} mm".format(text, value))
        if self.chip_break_mm and not 0.0 < self.chip_retract_mm <= MAX_DEPTH_MM:
            raise ValueError("The chip breaking retraction must be larger than 0 mm, got {:g} mm".format(self.chip_retract_mm))  # fmt: skip
        if not 0.0 <= self.dwell_s <= 3600.0:
            raise ValueError("The dwell time must be 0 s or more, got {:g} s".format(self.dwell_s))
        if self.depth_mm is not None:
            self.check(0.0)
        if self.peck_mm is not None and self.min_peck_mm > self.peck_mm:
            raise ValueError(
                "The minimum peck depth ({:g} mm) cannot be larger than the peck depth ({:g} mm)".format(
                    self.min_peck_mm, self.peck_mm
                )
            )
        return self

    def final_depth_mm(self, tip_mm, hole=None):
        """Where the drill's tip ends, mm below the top of the hole
        (negative), for a drill whose point is tip_mm long. hole: the
        HoleDepth of a hole picked in a model (needed without depth_mm)."""
        if self.depth_mm is None:
            if hole is None:
                raise ValueError("The depth comes from the model, but these holes are not a model's; enter a depth")
            return hole.depth_mm - (self.through_mm if hole.through else 0.0) - tip_mm
        return self.depth_mm - tip_mm if self.depth_to == FULL_DIAMETER else self.depth_mm

    def check(self, tip_mm, hole=None):
        """ValueError when the drill cannot start drilling above its depth."""
        depth = self.depth_mm if self.depth_mm is not None else self.final_depth_mm(tip_mm, hole)
        if self.start_mm >= -depth:
            raise ValueError(
                "The deepened starting point ({:g} mm) must be above the depth ({:g} mm)".format(self.start_mm, depth)
            )
        return self

    def pecks(self, tip_mm, hole=None):
        """True when the drill comes out of the hole before its depth."""
        return self.peck_mm is not None and self.peck_mm < -self.final_depth_mm(tip_mm, hole) - self.start_mm


MAX_PASSES = 10  # of a thread milling


@dataclass(frozen=True)
class ThreadMilling:
    """Thread milling with a thread mill, as the shop's programs mill
    it (model.threads): an internal right-hand thread in each hole, in
    the order the user picked them, milled from the top of the hole down,
    clockwise with the radius compensation right (RR).

    major_diameter_mm: the thread's nominal (major) diameter, M3: 3; the
    pitch is the thread mill's. depth_mm: negative, where the helix ends
    below the top of each hole (the sketch plane, or the top of each hole
    picked in a model); the helix goes down in half turns, the last one
    shorter when the depth needs it. passes: how many times the tool runs
    the same helix (the shop's programs: 2).
    """

    major_diameter_mm: float
    depth_mm: float
    passes: int = 2

    KIND = "thread_milling"

    def validate(self):
        if not 0.0 < self.major_diameter_mm <= MAX_DEPTH_MM:
            raise ValueError("The major diameter must be larger than 0 mm, got {:g} mm".format(self.major_diameter_mm))
        if not -MAX_DEPTH_MM <= self.depth_mm < 0.0:
            raise ValueError(
                "The depth must be negative (below the top of the holes) and not deeper "
                "than {:g} mm, got {:g} mm".format(-MAX_DEPTH_MM, self.depth_mm)
            )
        if not 1 <= self.passes <= MAX_PASSES:
            raise ValueError("The passes must be 1 to {}, got {}".format(MAX_PASSES, self.passes))
        return self

    def check(self, tool_diameter_mm, pitch_mm):
        """ValueError when a thread mill of that diameter and pitch cannot mill the thread."""
        if not pitch_mm or pitch_mm <= 0.0:
            raise ValueError("The thread mill has no pitch")
        if tool_diameter_mm >= self.major_diameter_mm - _EPSILON_MM:
            raise ValueError(
                "The thread mill (Ø{:g}) is too big for a thread of Ø{:g}".format(tool_diameter_mm, self.major_diameter_mm)
            )
        if -self.depth_mm / pitch_mm * 2 * self.passes > MAX_CUTS:
            raise ValueError("The thread is too deep for its pitch (at most {} half turns)".format(MAX_CUTS))
        return self


LIFT_MM = 0.5  # adaptive clearing: rapid moves over cleared floor (the user's choice)
_LEVEL_GAP_MM = 1e-3  # a level closer than this under the top of the stock cuts nothing


@dataclass(frozen=True)
class Adaptive:
    """Adaptive clearing (FreeCAD's Adaptive, model.clearing): the tool
    clears the stock around the setup's models from the top of the stock
    (or Start Z) down to z_depth_mm, with an even load (a small step over and deep cuts).
    Without faces picked in the model it clears all it can reach outside
    the models (roughing); with picked flat floors, only their area (the
    user's choice).

    z_depth_mm is in the setup's coordinates (the Z of the program): where
    the clearing ends, its last level. The models are never cut, so it may
    lie below their floors. start_z_mm: the top of the range the levels
    are worked out in (not a level itself); None: the top of the stock.
    The Z levels (levels()): full steps of z_step_mm down from Start Z
    (None: no steps), one on every flat floor of the models facing the
    tool from Start Z down (the user's choice; FreeCAD cuts on its steps
    only, so a floor between two steps kept up to a step of material; a
    floor above Start Z is left as it is), and z_depth_mm, also when it is
    Start Z itself (the user: Start Z = Z-Depth = the top face clears the
    stock over it). On a level only a floor has, the tool clears around
    the floors lying there only (full_levels).

    step_over_percent: the most of the tool's diameter it takes sideways.
    finish_xy_mm and finish_z_mm: left on the models' walls and floors;
    finish_z_mm above Z-Depth too (bottom_mm).
    helix_angle_deg: of the helix the tool goes down on into a closed area
    (in half turns, the user's choice; 2° by default, the user's choice:
    safer than FreeCAD's 5°). lift_mm: over cleared floor the
    tool moves rapid this much above the level it cuts (the user's choice:
    0.5 mm). finishing_pass: a last pass along the walls of each area
    (FreeCAD's finishing profile).
    """

    z_depth_mm: float
    z_step_mm: Optional[float] = None
    step_over_percent: float = 20.0
    finish_xy_mm: float = 0.0
    finish_z_mm: float = 0.0
    helix_angle_deg: float = 2.0
    lift_mm: float = LIFT_MM
    finishing_pass: bool = True
    start_z_mm: Optional[float] = None

    KIND = "adaptive"

    def validate(self):
        if not -MAX_DEPTH_MM <= self.z_depth_mm <= MAX_DEPTH_MM:
            raise ValueError("Z-Depth must be within {:g} mm of the zero point, got {:g} mm".format(MAX_DEPTH_MM, self.z_depth_mm))  # fmt: skip
        if self.start_z_mm is not None:
            if not -MAX_DEPTH_MM <= self.start_z_mm <= MAX_DEPTH_MM:
                raise ValueError("Start Z must be within {:g} mm of the zero point, got {:g} mm".format(MAX_DEPTH_MM, self.start_z_mm))  # fmt: skip
            if self.z_depth_mm > self.start_z_mm + _EPSILON_MM:
                raise ValueError("Z-Depth ({:g} mm) must not be above Start Z ({:g} mm)".format(self.z_depth_mm, self.start_z_mm))  # fmt: skip
        if self.z_step_mm is not None and not 0.0 < self.z_step_mm <= MAX_DEPTH_MM:
            raise ValueError("The Z step must be larger than 0 mm, got {:g} mm".format(self.z_step_mm))
        if not 1.0 <= self.step_over_percent <= 100.0:
            raise ValueError("The step over must be 1 to 100 % of the tool, got {:g} %".format(self.step_over_percent))
        for text, value in (
            ("finishing allowance in XY", self.finish_xy_mm),
            ("finishing allowance in Z", self.finish_z_mm),
            ("lift over cleared floor", self.lift_mm),
        ):
            if not 0.0 <= value <= MAX_DEPTH_MM:
                raise ValueError("The {} must be 0 mm or more, got {:g} mm".format(text, value))
        if not 0.0 < self.helix_angle_deg < 90.0:
            raise ValueError("The helix angle must be between 0° and 90°, got {:g}°".format(self.helix_angle_deg))
        return self

    def bottom_mm(self):
        """The lowest level: Z-Depth raised by the allowance in Z, which an
        adaptive roughing leaves everywhere, beside the part too (the user:
        cut down to Z-Depth itself, the stock beside the part's walls went
        0.1 mm below the allowance left on its floor)."""
        return _round(self.z_depth_mm + self.finish_z_mm)

    def top_mm(self, stock_top_mm):
        """The top of the range of the levels: Start Z, else the top of the stock."""
        return stock_top_mm if self.start_z_mm is None else self.start_z_mm

    def full_levels(self, top_mm):
        """The levels the whole area is cleared on, from the top: full Z
        steps down from Start Z and Z-Depth plus finish_z_mm (top_mm: the
        top of the stock); none at the top of the stock or above.

        On a level only a floor has (levels()) the tool clears around the
        floors lying there only and leaves the rest to the next of these (the
        user: down into a counterbore 6 deep, not all round the part again,
        the rest goes on the next Z step). So without Z steps all but the
        floors goes down to Z-Depth at once, and the deepest cut is between
        two of these (or the top of the stock and the first)."""
        start = self.top_mm(top_mm)
        bottom = self.bottom_mm()
        found = {bottom}
        if self.z_step_mm is not None:
            k = 1
            while start - k * self.z_step_mm > bottom + _EPSILON_MM:
                found.add(_round(start - k * self.z_step_mm))
                k += 1
        return sorted((z for z in found if z < top_mm - _LEVEL_GAP_MM), reverse=True)

    def levels(self, top_mm, floors_mm=()):
        """Z levels in the setup's coordinates, from the top: the full ones
        (full_levels: Z steps down from Start Z, top_mm: the top of the
        stock, also without Start Z, and Z-Depth plus finish_z_mm) and a
        level finish_z_mm above each floor (floors_mm: Z of the flat floors
        facing the tool) from Start Z down, not below Z-Depth; none at the
        top of the stock or above."""
        start = self.top_mm(top_mm)
        bottom = self.bottom_mm()
        found = set(self.full_levels(top_mm))
        for floor in floors_mm:
            if bottom - _EPSILON_MM <= floor + self.finish_z_mm and floor <= start + _EPSILON_MM:
                found.add(_round(floor + self.finish_z_mm))
        return sorted((z for z in found if z < top_mm - _LEVEL_GAP_MM), reverse=True)


_KINDS = {Contour.KIND: Contour, Drilling.KIND: Drilling, ThreadMilling.KIND: ThreadMilling, Adaptive.KIND: Adaptive}


def to_json(operation):
    data = {"kind": operation.KIND}
    data.update(asdict(operation))
    return json.dumps(data, sort_keys=True)


def from_json(text):
    from avangardecam.model.facing import Facing  # their own modules (they import this one)
    from avangardecam.model.helix import HelixMilling
    from avangardecam.model.slot import SlotMilling

    data = json.loads(text)
    own = {Facing.KIND: Facing, SlotMilling.KIND: SlotMilling, HelixMilling.KIND: HelixMilling}
    kind = dict(_KINDS, **own).get(data.pop("kind", None))
    if kind is None:
        raise ValueError("unknown operation: {}".format(text))
    if kind is Contour and "approach" not in data and data.get("compensation", OFF) != OFF:
        data["approach"] = ARC  # the first contours with compensation always came in on an arc
    return kind(**data).validate()
