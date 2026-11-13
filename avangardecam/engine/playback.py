# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Playback of a setup (model.playback), taken from FreeCAD: the NC
program the postprocessor gets (the active operations of every setup, so
the lines are numbered as in the exported program), the setup's steps
over time, its tools (for their shapes), its stock box (cut by
model.playback_stock) and the part as triangles, in the setup's
coordinates (the Job's model clones are)."""

from typing import NamedTuple

import numpy as np

from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import next_setup
from avangardecam.model import playback as model_playback
from avangardecam.post import heidenhain


# how far the part's triangles may be from its faces, to look at (Verify's are finer)
DEFLECTION_MM = 0.02


class Prepared(NamedTuple):
    label: str  # of the setup
    timeline: model_playback.Timeline
    tools: dict  # tool number -> model.tools.Tool
    stock: object  # model.stock.Bounds, None: the setup has none
    vertices: np.ndarray  # of the part
    triangles: np.ndarray
    start: object = None  # the material in the stock box (model.start_stock.Mesh), None: all of it


def part_mesh(job, deflection=DEFLECTION_MM):
    """The part of a setup as triangles in the setup's coordinates."""
    vertices, triangles = [], []
    for clone in job.Model.Group:
        shape = getattr(clone, "Shape", None)
        if shape is None or shape.isNull():
            continue
        points, faces = shape.tessellate(deflection)
        offset = len(vertices)
        vertices += [(p.x, p.y, p.z) for p in points]
        triangles += [(a + offset, b + offset, c + offset) for a, b, c in faces]
    return np.array(vertices, dtype=float).reshape(-1, 3), np.array(triangles, dtype=np.int64).reshape(-1, 3)


def prepare(job):
    """Everything the player needs for the active operations of a setup;
    raises ProjectError (an operation the program cannot be written for,
    no operation)."""
    doc = job.Document
    index = cam.setups(doc).index(job)
    try:
        program = cam.nc_program(doc, heidenhain.program_name(doc.Label), doc.Label)
        setup = program.setups[index]
        if not setup.operations:
            raise ProjectError("{} has no active operations to play.".format(job.Label))
        lines, lines_of = heidenhain.numbered(program)
        timeline = model_playback.timeline(setup, index, lines, lines_of, retract_z=heidenhain.BRIDGEPORT_V1000.retract_z_mm)
    except ValueError as e:  # a move the program cannot have, a cutting move without a feed
        raise ProjectError(str(e))
    tools = {t.number: t.tool for t in cam.project_tools(job)}
    vertices, triangles = part_mesh(job)
    return Prepared(job.Label, timeline, tools, setup.stock, vertices, triangles, next_setup.start_mesh(job))
