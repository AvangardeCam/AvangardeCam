# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Cycle time of the setups of a document (model.cycle_time), from the NC
program the postprocessor gets (the active operations of each setup)."""

from avangardecam.engine import freecad_cam as cam
from avangardecam.model import cycle_time
from avangardecam.post import machines


def program_times(doc, times=cycle_time.BRIDGEPORT_V1000, post=None):
    """model.cycle_time.SetupTime of each setup, in their order; raises
    ProjectError (an operation the program cannot be written for) or
    ValueError (a cutting move without a feed). post: the machine's
    postprocessor (post.machines) whose program is timed, None: the
    default one (machines.able)."""
    program = cam.nc_program(doc, "TIME")
    machine = machines.able(post, program)
    return cycle_time.program_time(program, times, machine.retract_z_mm, machine.start_z_mm, machine.anew)
