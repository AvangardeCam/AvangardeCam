# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The stock a setup starts from when it is no plain box: what the setup
before left (CAM > Next setup, "Stock from Setup N"), or a model of the
blank (a casting the foundry sends). Both are a closed mesh of triangles
(Mesh: vertices, triangles); the setup's stock box (model.stock.Bounds)
is the mesh's box.

- block: the stock model (stocklab) a setup's Verify and playback cut,
  from its stock box or, when the setup has a start mesh, from the mesh;
- left: what a setup's program leaves of its stock, as a mesh (cut as
  Verify cuts it, without the check against the part);
- moved: a mesh's points moved by a 4x4 matrix (from one setup's
  coordinates to the part's, from the part's to another setup's);
- area: where a stock model has material between two heights seen from
  the tool, as Adaptive takes its stock (one outline and holes in it).

Plain Python with numpy, no FreeCAD.
"""

from typing import NamedTuple

import numpy as np

from avangardecam import stocklab
from avangardecam.model import crashes
from avangardecam.model.stock import Bounds
from avangardecam.stocklab.section import contains, signed_area


class Mesh(NamedTuple):
    vertices: np.ndarray  # (V, 3)
    triangles: np.ndarray  # (T, 3)


def bounds(mesh):
    """The box of a mesh (model.stock.Bounds)."""
    used = np.asarray(mesh.vertices, float)[np.unique(np.asarray(mesh.triangles))]
    low, high = used.min(axis=0), used.max(axis=0)
    return Bounds(*(float(c) for c in low), *(float(c) for c in high))


def block(stock, start, resolution, lower=None, upper=None):
    """The stock model of a setup: the box stock (model.stock.Bounds) full
    of material, or the material of start (a Mesh, None: the box) inside
    it; lower/upper: only this part of it (a small stock around a hole)."""
    lower = (stock.x_min, stock.y_min, stock.z_min) if lower is None else lower
    upper = (stock.x_max, stock.y_max, stock.z_max) if upper is None else upper
    if start is None:
        return stocklab.Stock.box(lower, upper, resolution)
    return stocklab.Stock.from_mesh(start.vertices, start.triangles, resolution, lower, upper)


def left(stock, start, planned, resolution, progress=None):
    """What the planned operations (model.verify.Planned) leave of the
    stock (Bounds, start as for block), as a Mesh in the same coordinates;
    None when nothing is left."""
    if progress is not None:
        progress("Cutting the stock")
    material = block(stock, start, resolution)
    crashes.simulate(material, [p.operation for p in planned], [p.shank for p in planned])
    if progress is not None:
        progress("The surface of the stock left")
    surface = stocklab.surface(material)
    if len(surface.triangles) == 0:
        return None
    return Mesh(np.asarray(surface.vertices, float), np.asarray(surface.triangles, np.int64))


def moved(mesh, matrix):
    """The mesh with its points moved by matrix (4x4, rows; a rotation
    and a move, as a placement's)."""
    m = np.asarray(matrix, float).reshape(4, 4)
    points = np.asarray(mesh.vertices, float) @ m[:3, :3].T + m[:3, 3]
    return Mesh(points, np.asarray(mesh.triangles, np.int64))


def area(material, low, high):
    """What the tool (along Z, from above) sees of the material of a stock
    model (stocklab.Stock) between heights low and high: (outline, holes),
    arrays of (x, y), never less than the material (stocklab.area,
    conservative, kept apart); None when there is none.

    libarea's Adaptive takes a stock as one outline with holes in it:
    material in several pieces is the convex hull around them all, with
    the holes no piece of material lies in."""
    loops = stocklab.area(material, "+Z", low, max(high - low, material.sliver), apart=True)
    outlines = [loop for loop in loops if signed_area(loop) > 0.0]
    holes = [loop for loop in loops if signed_area(loop) < 0.0]
    if not outlines:
        return None
    if len(outlines) == 1:
        return outlines[0], holes
    holes = [h for h in holes if not any(contains([h], o[:1])[0] for o in outlines)]
    return _hull(np.concatenate(outlines)), holes


def _hull(points):
    """The convex hull of points (x, y), counterclockwise (Andrew's monotone
    chain)."""
    points = sorted(set(map(tuple, np.asarray(points, float).tolist())))

    def half(ordered):
        chain = []
        for p in ordered:
            while len(chain) >= 2 and _cross(chain[-2], chain[-1], p) <= 0.0:
                chain.pop()
            chain.append(p)
        return chain[:-1]

    return np.array(half(points) + half(points[::-1]), float)


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
