# SPDX-License-Identifier: MIT
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Heidenhain TNC plain language (Klartext, .H), written like the programs
the shop runs on its machine (a TNC 620):

- the control's dialog texts in Dutch (CYCL DEF 247 REF.PUNT VASTL.),
- feeds in Q30 (Z) and Q31 (XY), so the operator changes them in one place,
- numbers with a sign and a point (X+50., Y-4.667), every line numbered,
- tool moves as L, CC and C blocks, helices (thread and helix milling)
  as CC and CP blocks (CP IPA-180. IZ-0.25 DR-); radius compensation RL/RR where the
  operation asks for it, switched on and off in L blocks, else R0; an
  operation that goes up with it on switches it off above the part,
- drilling with the universal pecking cycle (CYCL DEF 205) and a
  CYCL CALL POS on each hole, the spindle starting on the first one,
- one program for all setups, each on its own preset (CYCL DEF 247),
- ISO-8859-1 text with CRLF line ends.

The program does not lean on the machine for anything but the preset:
each tool starts above its first point (XY first, then Z with the
spindle and coolant on) and ends high, with an optional stop (M01).
"""

import math
from dataclasses import dataclass

from avangardecam.model import nc

EXTENSION = ".H"
ENCODING = "iso-8859-1"
NEWLINE = "\r\n"


@dataclass(frozen=True)
class Machine:
    name: str
    retract_z_mm: float  # after each operation
    tool_end: tuple  # blocks after the last operation of a tool
    park: str  # block at the end of the program
    coolant_on: str = "M8"


BRIDGEPORT_V1000 = Machine(
    name="BRIDGEPORT V1000",
    retract_z_mm=40.0,
    tool_end=("L Z100 R0 FMAX", "M01", "L Z100 R0 FMAX M5 M9"),
    park="L X+500  Y+0  Z+0 R0 FMAX M91 M31",
)

# structure lines of the operations, as the operators know them
_TITLES = {
    nc.CONTOUR: "Contourbewerking",
    nc.DRILLING: "Deep Drilling With Chip Breaking",
    nc.THREAD_MILLING: "Thread Milling",
    nc.ADAPTIVE: "Adaptive Clearing",
    nc.FACING: "Facing",
    nc.SLOT_MILLING: "Slot Milling",
    nc.HELIX_MILLING: "Helix Milling",
    nc.DEBURRING: "Deburring",  # the user's choice: easier to translate later
}

_RADIUS = {None: "R0", nc.LEFT: "RL", nc.RIGHT: "RR"}


def number(value):
    """Coordinates as the shop's programs have them: +50., -4.667, +0."""
    value = round(value, 3)
    if value == 0.0:
        value = 0.0  # no -0.
    return "{:+.3f}".format(value).rstrip("0")


def plain(value):
    """Spindle speeds and feeds: 12000, 1310, 87.5."""
    value = round(value, 3)
    return str(int(value)) if value == int(value) else "{:.3f}".format(value).rstrip("0")


def _q(name, value, text):
    """A cycle parameter line."""
    return "   {:<10} ;{}".format("{}={}".format(name, value), text)


def _unsigned(value):
    """0., 0.25: a number without its sign."""
    return number(value).lstrip("+")


def _no_point(value):
    """+0, +7.5: a number without its point."""
    return number(value).rstrip(".")


# cycle 205 as the shop's programs have it: the parameter, its value from the
# cycle, how it is written, the spaces after it and the control's text
_CYCLE_205 = (
    ("Q200", "clearance_mm", plain, 3, "VEILIGHEIDSAFSTAND"),
    ("Q201", "depth_mm", number, 4, "DIEPTE"),
    ("Q206", "feed_mm_min", plain, 2, "AANZET DIEPTEVERPL."),
    ("Q202", "peck_mm", number, 4, "DIEPTEVERPLAATSING"),
    ("Q203", None, plain, 4, "COORD. OPPERVLAK"),  # 0: the holes' top is in CYCL CALL POS
    ("Q204", "second_clearance_mm", plain, 3, "2e VEILIGHEIDSAFST."),
    ("Q212", "decrement_mm", number, 4, "AFNAMEWAARDE"),
    ("Q205", "min_peck_mm", number, 4, "MIN. DIEPTEVERPL."),
    ("Q258", "upper_stop_mm", plain, 2, "ONDERBR.AFST. BOVEN"),
    ("Q259", "lower_stop_mm", plain, 2, "ONDERBR.AFST. ONDER"),
    ("Q257", "chip_break_mm", plain, 4, "BOORDPTE SPAANBREUK"),
    ("Q256", "chip_retract_mm", plain, 2, "TERUGTR.HGT SPAANBR."),
    ("Q211", "dwell_s", _unsigned, 4, "STILSTANDSTIJD ONDER"),
    ("Q379", "start_mm", _no_point, 4, "STARTPUNT"),
    ("Q253", "preposition_feed_mm_min", plain, 2, "AANZET VOORPOS."),
)


class _Continued(str):
    """A line of the block before it, without a number of its own (the shop's
    programs number the parameter line of cycle 247, not those of cycle 205)."""


def _cycle_205(cycle, depth):
    """CYCL DEF 205 with its parameter lines, for holes depth deep (Q201)."""
    values = {"depth_mm": depth, "peck_mm": -depth if cycle.peck_mm is None else cycle.peck_mm}
    lines = ["CYCL DEF 205 UNIVERSEELBOREN ~"]
    for i, (name, field, write, spaces, text) in enumerate(_CYCLE_205):
        end = "" if i == len(_CYCLE_205) - 1 else " ~"
        value = values[field] if field in values else getattr(cycle, field) if field else 0.0
        lines.append(_Continued("    {}={}{};{}{}".format(name, write(value), " " * spaces, text, end)))
    return lines


class _Writer:
    def __init__(self, program, machine):
        self.program = program
        self.machine = machine
        self.blocks = []
        self.tool = None  # the tool in the spindle
        self.feeds = None  # (Q30, Q31) set
        self.spindle_on = False
        self.position = [None, None, None]
        self.last_rapid = True  # FMAX holds for its own block only
        self.feed_word = None
        self.compensation = None  # radius compensation on (nc.LEFT, nc.RIGHT)
        self.where = ()  # (setup index, operation index) being written
        self.source = None  # where in the operation the blocks added come from (model.machine)
        self.sources = []  # of each block
        self.lines_of = {}  # (setup index, operation index) + source: index of its last line

    def add(self, *blocks):
        self.blocks.extend(blocks)
        self.sources.extend([None if self.source is None else self.where + self.source] * len(blocks))

    def _from(self, *source):
        """The blocks added from now on come from there (none: from nowhere)."""
        self.source = source or None

    # -- program -----------------------------------------------------------------

    def write(self):
        program = self.program
        self.add(
            "BEGIN PGM {} MM".format(program.name),
            ";" + self.machine.name,
            ";" + (program.comment or "commentaar"),
            ";" + program.date.strftime("%d-%m-%Y"),
            ";",
        )
        order = self._tool_order()
        first = True
        for setup_index, setup in enumerate(program.setups):
            if not setup.operations:
                continue
            if self.spindle_on:
                self.add(self.machine.tool_end[0])  # high before the preset changes
            self.add("CYCL DEF 247 REF.PUNT VASTL. ~", _q("Q339", "{:+d}".format(setup.preset), "REF.PUNT-NUMMER"))
            self.position = [None, None, None]
            if first and setup.stock is not None:
                s = setup.stock
                self.add(
                    "BLK FORM 0.1 Z X{} Y{} Z{}".format(number(s.x_min), number(s.y_min), number(s.z_min)),
                    "BLK FORM 0.2 X{} Y{} Z{}".format(number(s.x_max), number(s.y_max), number(s.z_max)),
                )
            first = False
            for op_index, op in enumerate(setup.operations):
                self.where = (setup_index, op_index)
                self._operation(op, order)
        if self.tool is not None:
            self.add(*self.machine.tool_end)
        self.add(self.machine.park, "*- M30", "M30", "END PGM {} MM".format(program.name))
        lines = []
        line_number = 0
        for block, source in zip(self.blocks, self.sources):
            if isinstance(block, _Continued):
                lines.append(block + NEWLINE)
            else:
                lines.append("{} {}{}".format(line_number, block, NEWLINE))
                line_number += 1
                if source is not None:
                    self.lines_of[source] = len(lines) - 1
        return "".join(lines)

    def _tool_order(self):
        """Tool numbers in the order they are called."""
        order = []
        for op in self.program.operations():
            if not order or order[-1] != op.tool.number:
                order.append(op.tool.number)
        return order

    def _operation(self, op, order):
        tool = op.tool
        change = self.tool is None or self.tool.number != tool.number
        if change and self.tool is not None:
            self._from("change")
            self.add(self.machine.tool_end[0])
            self._from()
            self.add(*self.machine.tool_end[1:])
        self.add("*- " + _TITLES.get(op.kind, op.label))
        if change:
            called = len([b for b in self.blocks if b.startswith("TOOL CALL ")])
            following = order[called + 1] if called + 1 < len(order) else order[0]
            self._from("call")
            if op.kind == nc.DRILLING:  # the shop's programs call a drill so
                self.add(
                    "  * -TOOL#: {} Diameter: Ø{} -- {}".format(tool.number, number(tool.diameter_mm), tool.name),
                    "TOOL CALL {} Z S{} DL0 DR0;".format(tool.number, plain(tool.spindle_rpm)),
                )
            else:
                self.add(
                    "  *- {} - TOOL#: {} - Diameter: Ø{}".format(tool.name, tool.number, number(tool.diameter_mm)),
                    "TOOL CALL {} Z S{} DL0 DR0;{}".format(tool.number, plain(tool.spindle_rpm), tool.name),
                )
            self._from()
            self.add("TOOL DEF {}".format(following))
            self.tool = tool
            self.feeds = None
            self.spindle_on = False
            self.position = [None, None, None]
        if op.kind == nc.DRILLING:
            self._drilling(op)
            return
        feeds = (tool.feed_z_mm_min, tool.feed_xy_mm_min)
        if feeds != self.feeds:
            self.add(
                "FN0: Q30={} ;voeding Z".format(plain(feeds[0])),
                "FN0: Q31={} ;voeding XY".format(plain(feeds[1])),
            )
            self.feeds = feeds
            self.feed_word = None
        self._moves(op)
        retract = number(self.machine.retract_z_mm)
        self._from("retract")
        if self.compensation is None:
            self.add("L Z{} R0 FMAX".format(retract))
        else:
            # up with the compensation, then off where the tool is (in XY, as the control needs)
            self.add("L Z{} FMAX".format(retract))
            self._from("off")
            self.add("L X{} Y{} R0 FMAX".format(number(self.position[0]), number(self.position[1])))
            self.compensation = None
        self._from()
        self.position[2] = self.machine.retract_z_mm
        self.last_rapid = True

    def _drilling(self, op):
        """The cycle, called on each hole; it ends at its 2nd set-up clearance.
        Holes of another depth (picked in a model) get the cycle again with
        that depth."""
        cycle = op.cycle
        if cycle is None or not cycle.holes:
            raise ValueError("{}: the drilling has no holes.".format(op.label))
        if self.compensation is not None:
            raise ValueError("{}: the radius compensation is still on.".format(op.label))
        depth = None
        for k, hole in enumerate(cycle.holes):
            self._from("hole", k)
            if depth is None or abs(hole.depth_mm - depth) > 5e-4:
                depth = hole.depth_mm
                self.add(*_cycle_205(cycle, depth))
            # the TNC adds Z to the surface coordinate (Q203 = 0): the hole's top
            block = "CYCL CALL POS X{} Y{} Z{} FMAX".format(number(hole.x), number(hole.y), plain(hole.surface_z))
            if not self.spindle_on:
                block += " {} {}".format("M3" if self.tool.clockwise else "M4", self.machine.coolant_on)
                self.spindle_on = True
            self.add(block)
        self._from()
        last = cycle.holes[-1]
        self.position = [last.x, last.y, last.surface_z + max(cycle.clearance_mm, cycle.second_clearance_mm)]
        self.last_rapid = True

    # -- moves -------------------------------------------------------------------

    def _moves(self, op):
        moves = list(op.moves)
        # the operation's own way up at its end: the retract follows
        if len(moves) > 1 and moves[-1].kind == nc.RAPID and (moves[-1].x, moves[-1].y) == (moves[-2].x, moves[-2].y):
            moves.pop()
        lead = 0
        while lead < len(moves) and moves[lead].kind == nc.RAPID:
            lead += 1
        if lead == len(moves):
            raise ValueError("{}: the operation does not cut anything.".format(op.label))
        # over the first point at the height the tool has, then down to it
        first = next((m for m in moves[:lead] if m.x is not None and m.y is not None), None)
        if first is None:
            raise ValueError("{}: the operation does not say where it starts.".format(op.label))
        self._from("approach")
        self._rapid(first.x, first.y, None, first.compensation)
        for i, move in enumerate(moves[:lead]):
            self._from("move", i)
            self._rapid(None, None, move.z, first.compensation)
        for i, move in enumerate(moves[lead:], lead):
            self._from("move", i)
            if move.kind == nc.RAPID:
                self._rapid(move.x, move.y, move.z, move.compensation)
            elif move.kind == nc.LINE:
                self._line(move)
            elif move.kind == nc.ARC:
                self._arc(move, op)
            else:
                raise ValueError("{}: unknown move {!r}.".format(op.label, move.kind))
        self._from()

    def _axes(self, x, y, z):
        words = []
        for i, (axis, value) in enumerate((("X", x), ("Y", y), ("Z", z))):
            if value is not None and (self.position[i] is None or abs(self.position[i] - value) > 5e-4):
                words.append(axis + number(value))
                self.position[i] = value
        return words

    def _rapid(self, x, y, z, compensation=None):
        start = list(self.position)
        words = self._axes(x, y, z)
        switch = compensation != self.compensation
        if not words and not switch:
            return
        if switch and not any(w[0] in "XY" for w in words):
            # the control switches the compensation on a move in XY
            words = ["X" + number(start[0]), "Y" + number(start[1])] + words
        radius = self._radius(nc.Move(nc.RAPID, x, y, z, compensation=compensation), rapid=True)
        block = "L {}{} FMAX".format(" ".join(words), " " + radius if radius else "")
        if z is not None and not self.spindle_on:
            block += " {} {}".format("M3" if self.tool.clockwise else "M4", self.machine.coolant_on)
            self.spindle_on = True
        self.add(block)
        self.last_rapid = True

    def _feed(self, move, plunge):
        """F word of a cutting move, or "" when the feed holds on."""
        tool = self.tool
        feed = move.feed_mm_min
        if feed is None:
            word = self.feed_word or "FQ31"
        elif abs(feed - tool.feed_z_mm_min) < 0.01 and (plunge or abs(feed - tool.feed_xy_mm_min) >= 0.01):
            word = "FQ30"
        elif abs(feed - tool.feed_xy_mm_min) < 0.01:
            word = "FQ31"
        else:
            word = "F" + plain(feed)
        if word == self.feed_word and not self.last_rapid:
            return ""
        self.feed_word = word
        return word

    def _radius(self, move, rapid=False):
        """RL, RR or R0 when the move switches the compensation, R0 on rapid
        moves and the first move after them without it, else ""."""
        if move.compensation != self.compensation:
            if move.compensation not in _RADIUS:
                raise ValueError("unknown radius compensation {!r}".format(move.compensation))
            self.compensation = move.compensation
            return _RADIUS[move.compensation]
        return "R0" if self.compensation is None and (rapid or self.last_rapid) else ""

    def _line(self, move):
        start = list(self.position)
        words = self._axes(move.x, move.y, move.z)
        switch = move.compensation != self.compensation
        if not words and not switch:
            return
        if not words:  # the control switches the compensation on a move
            words = ["X" + number(start[0]), "Y" + number(start[1])]
        plunge = all(w.startswith("Z") for w in words) and start[2] is not None
        parts = ["L"] + words
        radius = self._radius(move)
        if radius:
            parts.append(radius)
        feed = self._feed(move, plunge)
        if feed:
            parts.append(feed)
        self.add(" ".join(parts))
        self.last_rapid = False

    def _arc(self, move, op):
        if move.center is None or move.x is None or move.y is None:
            raise ValueError("{}: an arc without its centre or end.".format(op.label))
        if move.compensation != self.compensation:
            raise ValueError("{}: the radius compensation can only change on a straight line.".format(op.label))
        helix = move.z is not None and self.position[2] is not None and abs(move.z - self.position[2]) > 5e-4
        if helix and None in self.position[:2]:
            raise ValueError("{}: a helix must start where the tool is.".format(op.label))
        self.add("CC X{} Y{}".format(number(move.center[0]), number(move.center[1])))
        direction = "DR-" if move.clockwise else "DR+"
        if helix:
            # IZ from the rounded heights, so that the rounding adds up to
            # nothing over many turns (the shop's programs: -0.131, -0.132)
            down = round(move.z, 3) - round(self.position[2], 3)
            sweep = _sweep(self.position[:2], (move.x, move.y), move.center, move.clockwise)
            parts = ["CP", "IPA" + number(sweep), "IZ" + number(down), direction]
            self.position[2] = move.z
        else:
            parts = ["C", "X" + number(move.x), "Y" + number(move.y), direction]
        if self.last_rapid:
            parts.append("R0")
        feed = self._feed(move, False)
        if feed:
            parts.append(feed)
        self.add(" ".join(parts))
        self.position[0], self.position[1] = move.x, move.y
        self.last_rapid = False


def _sweep(start, end, centre, clockwise):
    """The angle of an arc from start to end around centre, degrees:
    negative clockwise; a whole turn when it ends where it starts."""
    a0 = math.degrees(math.atan2(start[1] - centre[1], start[0] - centre[0]))
    a1 = math.degrees(math.atan2(end[1] - centre[1], end[0] - centre[0]))
    turn = ((a0 - a1) if clockwise else (a1 - a0)) % 360.0
    if turn < 1e-6 or turn > 360.0 - 1e-6:
        turn = 360.0
    return -turn if clockwise else turn


def write(program, machine=BRIDGEPORT_V1000):
    """The program's text, with CRLF line ends."""
    return _Writer(program, machine).write()


def numbered(program, machine=BRIDGEPORT_V1000):
    """The program's lines (without line ends) and where each move of an
    operation went: {(setup index, operation index) + source: the index of
    its last line}, source as model.machine.Element has it. A move that
    changes nothing has no line, nor has the operation's own way up at its
    end (the retract does it)."""
    writer = _Writer(program, machine)
    text = writer.write()
    return text.split(NEWLINE)[:-1], writer.lines_of


def save(text, path):
    """Write the text as the control reads it (ISO-8859-1)."""
    with open(path, "wb") as f:
        f.write(text.encode(ENCODING, errors="replace"))


def program_name(path_stem):
    """BEGIN PGM name from a file name: letters, digits, - and _."""
    name = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in path_stem)
    return name or "0000"
