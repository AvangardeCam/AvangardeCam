# SPDX-License-Identifier: MIT
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The postprocessors to choose from when a program is exported: one for
each machine, each on its own (a change for one machine does not reach
the programs of another)."""

from typing import NamedTuple

from avangardecam.post import heidenhain
from avangardecam.post import soraluce


class Postprocessor(NamedTuple):
    key: str  # kept in the settings
    label: str  # English; the interface translates it
    module: object  # write(program) -> text, save(text, path), program_name(stem), EXTENSION
    tilts: bool  # whether it writes operations on a turned zero point

    def write(self, program):
        return self.module.write(program)


BRIDGEPORT_V1000 = Postprocessor("bridgeport_v1000", "Bridgeport V1000 - Heidenhain TNC 620", heidenhain, False)
SORALUCE_T35 = Postprocessor(
    "soraluce_t35", "Soraluce T35 - Heidenhain, turning head (experimental)", soraluce, True
)

ALL = (BRIDGEPORT_V1000, SORALUCE_T35)
DEFAULT = BRIDGEPORT_V1000


def find(key):
    """The postprocessor with that key; the default one for an unknown key."""
    return next((post for post in ALL if post.key == key), DEFAULT)
