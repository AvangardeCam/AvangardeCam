# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Verification of a setup: what model.verify needs, taken from FreeCAD.

The setup's NC program (the same the postprocessor writes), its stock box
and its tools; the part as triangles from the Job's model clones, which
are already in the setup's coordinates. prepare() reads FreeCAD and must
run in FreeCAD's thread; model.verify.verify() then needs none of it.
"""

from typing import NamedTuple

import numpy as np

from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import next_setup
from avangardecam.model import verify as model_verify
from avangardecam.post import heidenhain

# how far the part's triangles may be from its faces: half of what counts
# as too deep, so a hole's chords do not make its wall look cut (a tenth
# took 27 s and 351 000 triangles on a plate of the user, half 1.8 s, 85 000)
DEFLECTION_MM = model_verify.TOLERANCE_MM / 2.0

# the part's triangles of the last setup, while its shapes stay the same
_meshes = {}


class Prepared(NamedTuple):
    label: str  # of the setup
    stock: object  # model.stock.Bounds
    vertices: np.ndarray
    triangles: np.ndarray
    planned: list  # model.verify.Planned
    start: object = None  # the material in the stock box (model.start_stock.Mesh), None: all of it


def model_mesh(job, deflection=DEFLECTION_MM):
    """The part of a setup as triangles in the setup's coordinates; worked
    out again only when a shape of its model changed."""
    key = (job.Document.Name, job.Name, deflection,
           tuple((c.Name, c.Shape.hashCode(), str(c.Placement)) for c in job.Model.Group if getattr(c, "Shape", None) is not None))  # fmt: skip
    if key in _meshes:
        return _meshes[key]
    vertices, triangles = [], []
    for clone in job.Model.Group:
        shape = getattr(clone, "Shape", None)
        if shape is None or shape.isNull():
            continue
        points, faces = shape.tessellate(deflection)
        offset = len(vertices)
        vertices += [(p.x, p.y, p.z) for p in points]
        triangles += [(a + offset, b + offset, c + offset) for a, b, c in faces]
    if not triangles:
        raise ProjectError("{} has no model to check the program against.".format(job.Label))
    _meshes.clear()
    _meshes[key] = np.array(vertices, dtype=float), np.array(triangles, dtype=np.int64)
    return _meshes[key]


def prepare(job):
    """Everything model.verify.verify needs for the active operations of a setup."""
    doc = job.Document
    index = cam.setups(doc).index(job)
    setup = cam.nc_program(doc, "VERIFY").setups[index]
    if not setup.operations:
        raise ProjectError("{} has no active operations to verify.".format(job.Label))
    if setup.stock is None:
        raise ProjectError("{} has no stock.".format(job.Label))
    tools = {t.number: t.tool for t in cam.project_tools(job)}
    try:
        planned = model_verify.plan(setup, tools, heidenhain.BRIDGEPORT_V1000.retract_z_mm)
    except ValueError as e:
        raise ProjectError(str(e))
    vertices, triangles = model_mesh(job)
    return Prepared(job.Label, setup.stock, vertices, triangles, planned, next_setup.start_mesh(job))


def run(prepared, resolution=model_verify.stocklab.DEFAULT_RESOLUTION, progress=None):
    """Cut and check (model.verify.verify); needs no FreeCAD, may run in another thread."""
    return model_verify.verify(
        prepared.stock, prepared.vertices, prepared.triangles, prepared.planned, resolution, progress=progress,
        start=prepared.start,
    )
