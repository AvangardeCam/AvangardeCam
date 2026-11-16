# SPDX-License-Identifier: MIT
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Heidenhain plain language (.H) for a machine that turns its spindle
head (experimental: not run on the machine yet), written like the
programs the shop runs on its Soraluce:

- the setup's preset once (CYCL DEF 247), the stock from it (BLK FORM),
- every operation on its own, whatever came before it: the labels RESET
  (tilt and datum shift off) and FREE (coolant off, away along the
  machine's axes, M91), the tool call, the head high (M91), then
    CYCL DEF 7        the datum shift to the operation's zero point,
    M138 A B          the axes that tilt,
    PLANE SPATIAL     the zero point's axes as spatial angles, STAY,
    CYCL DEF 397      the machine's own cycle that turns the head there,
  and its moves in the tilted plane, counted from the shifted zero point;
  an operation on the preset gets the same lines with zeros,
- the moves, feeds (Q30, Q31), radius compensation and drilling cycle as
  post/heidenhain.py writes them; the spindle starts with the coolant
  (M13) on the first move,
- at the end the head straight again (the label HEAD0) and the three
  labels.

The spatial angles are those of model.op_zero.turn_of: SPA, SPB, SPC
about the fixed X, Y, Z in this order. One angle at a time (a wall of a
block) is the case the shop's programs show; check a program with more
than one angle on the machine's own simulation before it cuts.
"""

from dataclasses import dataclass

from avangardecam.model import nc
from avangardecam.model import op_zero
from avangardecam.post import heidenhain
from avangardecam.post.heidenhain import NEWLINE, number, plain, program_name, save  # noqa: F401 (a postprocessor's parts)

EXTENSION = heidenhain.EXTENSION
ENCODING = heidenhain.ENCODING


@dataclass(frozen=True)
class Machine:
    name: str
    retract_z_mm: float  # after each operation, from its own zero point
    head_high: str  # before the head turns: up along the machine's Z
    away: str  # then away along the machine's X and Y
    start_z: str  # the first block in the tilted plane
    park: str  # block at the end of the program
    coolant_on: str = "M8"


SORALUCE_T35 = Machine(
    name="SORALUCE T35",
    retract_z_mm=40.0,
    head_high="L Z1196.47 R0 FMAX M91",
    away="L X1750 Y1124.52 R0 FMAX M91",
    start_z="L Z100 R0 FMAX",
    park="L X1750 Y1124.52 FMAX M91",
)

_HEAD_CYCLE = (
    "CYCL DEF 397 HEAD CYCLE ~",
    heidenhain._Continued(" Q1507=+Q121 ; VERT. JOINT DEGREES ~"),
    heidenhain._Continued(" Q1506=+Q120 ; HORIZ. JOINT DEGREE"),
)
_FREE = ('CALL LBL "RESET"', 'CALL LBL "FREE"')
START_Z_MM = 100.0  # of Machine.start_z


def angle(value):
    """Spatial angles as the shop's programs have them: 0., 90., -90."""
    return number(value).lstrip("+")


def plane(zero):
    """PLANE SPATIAL of a zero point as the preset sees it (None: the preset)."""
    turn = op_zero.NO_TURN if zero is None else op_zero.turn_of((zero.x_axis, zero.y_axis, zero.z_axis))
    return "PLANE SPATIAL SPA{} SPB{} SPC{} STAY COORD ROT".format(*(angle(value) for value in turn))


class _Writer(heidenhain._Writer):
    def write(self):
        program = self.program
        machine = self.machine
        self.add(
            "BEGIN PGM {} MM".format(program.name),
            ";" + machine.name,
            ";" + (program.comment or "commentaar"),
            ";" + program.date.strftime("%d-%m-%Y"),
            ";",
        )
        order = [op.tool.number for op in program.operations()]
        first = True
        index = 0
        for setup_index, setup in enumerate(program.setups):
            if not setup.operations:
                continue
            if not first:
                self.add(*_FREE)  # away before the preset changes
            self.add(
                "CYCL DEF 247 REF.PUNT VASTL. ~",
                heidenhain._q("Q339", "{:+d}".format(setup.preset), "REF.PUNT-NUMMER"),
            )
            if first and setup.stock is not None:
                s = setup.stock
                self.add(
                    "BLK FORM 0.1 Z X{} Y{} Z{}".format(number(s.x_min), number(s.y_min), number(s.z_min)),
                    "BLK FORM 0.2 X{} Y{} Z{}".format(number(s.x_max), number(s.y_max), number(s.z_max)),
                )
            first = False
            self.add(*_FREE)
            for op_index, op in enumerate(setup.operations):
                self.where = (setup_index, op_index)
                later = [n for n in order[index + 1 :] if n != op.tool.number]
                self._operation(op, later[0] if later else order[0])
                index += 1
        self.add(*_FREE)
        self.add('CALL LBL "HEAD0"', machine.park, "* - M30", "M30")
        self.add(
            "* - LABELS",
            'LBL "RESET"',
            "M138",
            "PLANE RESET STAY",
            "CYCL DEF 7.0 NULPUNT",
            "CYCL DEF 7.1  X0",
            "CYCL DEF 7.2  Y0",
            "CYCL DEF 7.3  Z0",
            "LBL 0",
            'LBL "FREE"',
            "M9",
            machine.head_high,
            machine.away,
            "LBL 0",
            'LBL "HEAD0"',
            "M138 A B",
            "PLANE SPATIAL SPA0 SPB0 SPC0 STAY COORD ROT",
            *_HEAD_CYCLE,
            "LBL 0",
            "END PGM {} MM".format(program.name),
        )
        lines = []
        line_number = 0
        for block, source in zip(self.blocks, self.sources):
            if isinstance(block, heidenhain._Continued):
                lines.append(block + NEWLINE)
            else:
                lines.append("{} {}{}".format(line_number, block, NEWLINE))
                line_number += 1
                if source is not None:
                    self.lines_of[source] = len(lines) - 1
        return "".join(lines)

    def _operation(self, op, following):
        tool = op.tool
        machine = self.machine
        zero = op.zero
        self.add("* - T{} {} ({})".format(tool.number, tool.name, op.label), "M1", *_FREE)
        self._from("call")
        feed = tool.feed_z_mm_min if op.kind == nc.DRILLING else tool.feed_xy_mm_min
        self.add("TOOL CALL {} Z S{} F{} DL0 DR0".format(tool.number, plain(tool.spindle_rpm), plain(feed)))
        self._from()
        self.add("TOOL DEF {}".format(following))
        if op.kind != nc.DRILLING:
            self.add(
                "FN0: Q30={} ;voeding Z".format(plain(tool.feed_z_mm_min)),
                "FN0: Q31={} ;voeding XY".format(plain(tool.feed_xy_mm_min)),
            )
        self.add(";KOP POSITIONEREN", machine.head_high, *_FREE)
        self.add("M1")
        self.add(*heidenhain.cycle_7((0.0, 0.0, 0.0) if zero is None else zero.origin))
        self.add("M138 A B", plane(zero), *_HEAD_CYCLE)
        self.add(machine.start_z)
        self.tool = tool
        self.feed_word = None
        self.compensation = None
        self.position = [None, None, START_Z_MM]
        self.last_rapid = True
        self.spindle_on = True  # started here, with the coolant, on the first block
        start = len(self.blocks)
        if op.kind == nc.DRILLING:
            self._drilling(op)
            first = next(i for i in range(start, len(self.blocks)) if self.blocks[i].startswith("CYCL CALL POS"))
        else:
            self._moves(op)
            first = start
            retract = number(machine.retract_z_mm)
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
        self.blocks[first] += " M13" if tool.clockwise else " M14"
        self.add("M9")


def write(program, machine=SORALUCE_T35):
    """The program's text, with CRLF line ends."""
    return _Writer(program, machine).write()


def numbered(program, machine=SORALUCE_T35):
    """The program's lines (without line ends) and where each move of an
    operation went, as post.heidenhain.numbered."""
    writer = _Writer(program, machine)
    text = writer.write()
    return text.split(NEWLINE)[:-1], writer.lines_of
