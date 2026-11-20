# SPDX-License-Identifier: MIT
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The postprocessors to choose from when a program is exported: one for
each machine, each on its own (a change for one machine does not reach
the programs of another)."""

from typing import NamedTuple

from avangardecam import edition
from avangardecam.model import machine as model_machine
from avangardecam.model import tilted
from avangardecam.post import heidenhain
from avangardecam.post import soraluce


class Postprocessor(NamedTuple):
    key: str  # kept in the settings
    label: str  # English; the interface translates it
    module: object  # write(program) -> text, save(text, path), program_name(stem), EXTENSION
    tilts: bool  # whether it writes operations on a turned zero point
    # how its program moves the tool, for what runs it (Play, Verify, the
    # cycle time; model.machine.Machine)
    retract_z_mm: float = model_machine.RETRACT_Z_MM  # after an operation
    start_z_mm: float = model_machine.TOOL_CHANGE_Z_MM  # after a tool change
    anew: bool = False  # every operation starts high over its own zero point (a turning head)

    def write(self, program):
        return self.module.write(program)

    def numbered(self, program):
        """The program's lines and where each move of an operation went."""
        return self.module.numbered(program)


BRIDGEPORT_V1000 = Postprocessor(
    "bridgeport_v1000", "Bridgeport V1000 - Heidenhain TNC 620", heidenhain, False,
    retract_z_mm=heidenhain.BRIDGEPORT_V1000.retract_z_mm,
)  # fmt: skip
SORALUCE_T35 = Postprocessor(
    "soraluce_t35", "Soraluce T35 - Heidenhain, turning head (experimental)", soraluce, True,
    retract_z_mm=soraluce.SORALUCE_T35.retract_z_mm, start_z_mm=soraluce.START_Z_MM, anew=True,
)  # fmt: skip

ALL = (BRIDGEPORT_V1000, SORALUCE_T35)
DEFAULT = BRIDGEPORT_V1000
# the ones the export window offers: without edition.FIVE_AXES none that tilts
CHOICES = ALL if edition.FIVE_AXES else tuple(post for post in ALL if not post.tilts)


def find(key):
    """The postprocessor with that key; the default one for an unknown key."""
    return next((post for post in ALL if post.key == key), DEFAULT)


def able(post, program):
    """The postprocessor that runs a program (model.nc.Program) for Play,
    Verify and the cycle time: post (None: the default one), or, when an
    operation counts from a turned zero point and post only shifts, the
    first one of a machine that tilts."""
    post = post or DEFAULT
    if post.tilts or not any(tilted.turned(setup) for setup in program.setups):
        return post
    return next((other for other in ALL if other.tilts), post)
