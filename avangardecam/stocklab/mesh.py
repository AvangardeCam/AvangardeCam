# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""The surface of the stock as triangles, to show it.

The lattice is the middles of the cells, closed by a layer on the faces
of the block; a point is in the material when its Z ray has material
there (the layer on the faces never). Every edge of the lattice lies on a
ray of its own direction, so where the edge goes from material to air is
known exactly from that ray. The surface is a surface net: one vertex in
each cube of the lattice the surface goes through, the mean of where it
crosses the cube's edges, and a quad of the four cubes around every
crossed edge, facing out of the material.

A flat face along the grid comes out exact; a sharp edge of the material
is rounded off by up to about half a cell.
"""

import struct

import numpy as np

from .dexel import other_axes


class Mesh:
    """vertices: (V, 3) floats; triangles: (T, 3) vertex indices,
    counterclockwise seen from outside the material."""

    def __init__(self, vertices, triangles):
        self.vertices = vertices
        self.triangles = triangles

    def volume(self):
        v = self.vertices[self.triangles]
        return float(np.einsum("ij,ij->i", v[:, 0], np.cross(v[:, 1], v[:, 2])).sum() / 6.0)

    def normals(self):
        """The unit normal of each triangle, out of the material."""
        v = self.vertices[self.triangles]
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        length = np.linalg.norm(n, axis=1, keepdims=True)
        return n / np.where(length > 0.0, length, 1.0)

    def save_stl(self, path, name="stock"):
        """A binary STL, to look at the stock in any viewer."""
        normals = self.normals().astype("<f4")
        corners = self.vertices[self.triangles].astype("<f4").reshape(-1, 9)
        records = np.zeros(len(self.triangles), dtype=[("n", "<f4", 3), ("v", "<f4", 9), ("a", "<u2")])
        records["n"] = normals
        records["v"] = corners
        with open(path, "wb") as f:
            f.write(name.encode("ascii", "replace")[:80].ljust(80, b" "))
            f.write(struct.pack("<I", len(records)))
            f.write(records.tobytes())


def save_ply(path, vertices, triangles, colors=None):
    """A binary PLY with a colour per vertex (r, g, b in 0..1), to look at
    the verification in a viewer (Blender, MeshLab)."""
    vertices = np.asarray(vertices, dtype="<f4")
    triangles = np.asarray(triangles)
    header = ["ply", "format binary_little_endian 1.0", "element vertex %d" % len(vertices),
              "property float x", "property float y", "property float z"]
    fields = [("p", "<f4", 3)]
    if colors is not None:
        header += ["property uchar red", "property uchar green", "property uchar blue"]
        fields.append(("c", "u1", 3))
    header += ["element face %d" % len(triangles), "property list uchar int vertex_indices", "end_header"]
    points = np.zeros(len(vertices), dtype=fields)
    points["p"] = vertices
    if colors is not None:
        points["c"] = np.clip(np.round(np.asarray(colors) * 255.0), 0, 255)
    faces = np.zeros(len(triangles), dtype=[("n", "u1"), ("i", "<i4", 3)])
    faces["n"] = 3
    faces["i"] = triangles
    with open(path, "wb") as f:
        f.write(("\n".join(header) + "\n").encode("ascii"))
        f.write(points.tobytes())
        f.write(faces.tobytes())


def lattice(stock):
    """The coordinates of the lattice on each axis: the face, the middles of
    the cells, the other face."""
    return [np.concatenate(([stock.lower[a]], stock.centers(a), [stock.upper[a]])) for a in range(3)]


def inside(stock, start=None, stop=None):
    """Which points of the lattice are in the material (from the Z rays):
    all, or the points from `start` to `stop` (lattice indices on each
    axis, stop not included)."""
    coords = lattice(stock)
    n = np.array(stock.counts) + 2
    start = np.zeros(3, np.int64) if start is None else np.asarray(start)
    stop = n if stop is None else np.asarray(stop)
    result = np.zeros(stop - start, bool)
    # the points in the middles of the cells (the faces' layer is never in it)
    first = np.maximum(start, 1)
    last = np.minimum(stop, n - 1)
    if np.any(first >= last):
        return result
    z = coords[2][first[2]:last[2]]
    family = stock.rays[2]
    rays = (slice(first[0] - 1, last[0] - 1), slice(first[1] - 1, last[1] - 1))
    part = np.zeros(tuple(last - first), bool)
    for k in range(family.depth):
        lo = family.lo[rays + (k, None)]
        hi = family.hi[rays + (k, None)]
        part |= (lo <= z) & (z < hi)
    result[tuple(slice(f - s, l - s) for f, l, s in zip(first, last, start))] = part
    return result


def _crossings(stock, coords, status, axis, start):
    """The crossed edges along `axis` of the points `status` (from the
    lattice point `start`): their lattice indices (of the lower end),
    whether the material is at the lower end, and where they cross."""
    low = [slice(None)] * 3
    high = [slice(None)] * 3
    low[axis] = slice(None, -1)
    high[axis] = slice(1, None)
    first = status[tuple(low)]
    second = status[tuple(high)]
    found = np.nonzero(first != second)
    material_first = first[found]
    index = tuple(i + s for i, s in zip(found, start))
    u, v = other_axes(axis)
    family = stock.rays[axis]
    lo = family.lo[index[u] - 1, index[v] - 1]
    hi = family.hi[index[u] - 1, index[v] - 1]
    p0 = coords[axis][index[axis]]
    p1 = coords[axis][index[axis] + 1]
    # the material end of the edge, and the interval of the ray holding it
    p = np.where(material_first, p0, p1)[:, None]
    holding = (lo <= p) & (p <= hi)
    found = holding.any(axis=1)
    k = np.argmax(holding, axis=1)
    rows = np.arange(len(k))
    end = np.where(material_first, hi[rows, k], lo[rows, k])
    crossing = np.where(found, np.clip(end, p0, p1), (p0 + p1) / 2.0)
    return index, material_first, crossing


def _part(stock, low, high):
    """The surface net of the quads owned by the cubes from `low` to `high`
    (cube indices on each axis, high not included): a crossed edge is owned
    by the cube whose lowest corner is its lower end. Returns the vertices
    (one in each cube used, the cubes in order), the quads (vertex indices,
    facing out) and the owning cube of each quad (flat index)."""
    coords = lattice(stock)
    n = np.array(stock.counts) + 2
    cubes = tuple(n - 1)
    # the points of the cubes around the edges owned: one cube more below
    start = np.maximum(low - 1, 0)
    stop = np.minimum(high + 1, n)
    status = inside(stock, start, stop)
    whole = bool(np.all(low <= 0) and np.all(high >= n - 1))
    owners = []  # the cubes each crossing counts in, and the crossing
    points = []
    quads = []
    owning = []
    for axis in range(3):
        index, material_first, crossing = _crossings(stock, coords, status, axis, start)
        if len(crossing) == 0:
            continue
        point = np.stack([coords[a][index[a]] for a in range(3)], axis=1)
        point[:, axis] = crossing
        u, v = other_axes(axis)
        # the four cubes around the edge, counterclockwise around +axis
        around = []
        for du, dv in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            cube = list(index)
            cube[u] = index[u] + du
            cube[v] = index[v] + dv
            around.append(np.ravel_multi_index(cube, cubes))
        around = np.stack(around, axis=1)
        owners.append(around.ravel())
        points.append(np.repeat(point, 4, axis=0))
        # facing out of the material: +axis when the material is first
        facing = np.where(material_first[:, None], around, around[:, ::-1])
        if whole:
            quads.append(facing)
            owning.append(around[:, 2])
        else:
            owned = np.all([(i >= l) & (i < h) for i, l, h in zip(index, low, high)], axis=0)
            quads.append(facing[owned])
            owning.append(around[owned, 2])
    if not quads or not sum(len(q) for q in quads):
        return np.zeros((0, 3)), np.zeros((0, 4), np.int64), np.zeros(0, np.int64)
    used, number = np.unique(np.concatenate(owners), return_inverse=True)
    points = np.concatenate(points)
    counts = np.bincount(number, minlength=len(used))
    vertices = np.stack([np.bincount(number, weights=points[:, a], minlength=len(used)) for a in range(3)], axis=1)
    vertices /= counts[:, None]
    quads = np.searchsorted(used, np.concatenate(quads))
    return vertices, quads, np.concatenate(owning)


def _mesh(vertices, quads):
    triangles = np.concatenate((quads[:, [0, 1, 2]], quads[:, [0, 2, 3]]))
    return Mesh(vertices, triangles)


def surface(stock):
    """The surface of the stock (a Mesh)."""
    n = np.array(stock.counts) + 2
    vertices, quads, _owning = _part(stock, np.zeros(3, np.int64), n - 1)
    if len(quads) == 0:
        return Mesh(np.zeros((0, 3)), np.zeros((0, 3), int))
    return _mesh(vertices, quads)


def piece_count(stock, size):
    """How many pieces of `size` cubes (pieces) there are on each axis."""
    n = np.array(stock.counts) + 1
    return tuple(int(c) for c in -(-n // int(size)))


def pieces(stock, size, cells=None):
    """The surface of the stock in pieces of `size` cubes of the lattice on
    each axis, to draw it again only where the material changed: a dict
    (i, j, k) -> Mesh, each with vertices of its own (the pieces meet
    without a gap: a vertex on their border is in both, the same).

    cells: the cells whose material changed (first, last on each axis, as
    Stock.changed_cells gives them): only the pieces whose surface may have
    changed by them, each piece of them in the dict, empty when it has no
    surface now; None: all the pieces with a surface."""
    size = int(size)
    count = np.array(piece_count(stock, size))
    if cells is None:
        first, last = np.zeros(3, np.int64), count - 1
    else:
        # cell c is lattice point c + 1: the cubes with it as a corner (c, c +
        # 1), the quads using their vertices (owned up to c + 2), and an edge
        # along a ray holding a crossing in cell c (lower end c or c + 1)
        lower = np.asarray(cells[0]) - 1
        upper = np.asarray(cells[1]) + 3
        first = np.clip(lower // size, 0, count - 1)
        last = np.clip(upper // size, 0, count - 1)
    n = np.array(stock.counts) + 2
    cubes = n - 1
    low = first * size
    high = np.minimum((last + 1) * size, cubes)
    vertices, quads, owning = _part(stock, low, high)
    result = {}
    if cells is not None:
        for key in np.ndindex(*(last - first + 1)):
            result[tuple(int(f + k) for f, k in zip(first, key))] = Mesh(np.zeros((0, 3)), np.zeros((0, 3), np.int64))
    if len(quads) == 0:
        return result
    owner = np.stack(np.unravel_index(owning, tuple(cubes)), axis=1) // size
    piece = np.ravel_multi_index(owner.T, tuple(count))
    order = np.argsort(piece, kind="stable")
    piece, quads = piece[order], quads[order]
    # each piece's vertices: the (piece, vertex) pairs its quads use
    pairs = piece[:, None] * len(vertices) + quads
    used, local = np.unique(pairs, return_inverse=True)
    local = local.reshape(quads.shape)
    used_piece = used // len(vertices)
    names, first_quad = np.unique(piece, return_index=True)
    first_vertex = np.searchsorted(used_piece, names)
    ends_quad = np.append(first_quad[1:], len(piece))
    ends_vertex = np.append(first_vertex[1:], len(used))
    for name, q0, q1, v0, v1 in zip(names, first_quad, ends_quad, first_vertex, ends_vertex):
        key = tuple(int(i) for i in np.unravel_index(name, tuple(count)))
        result[key] = _mesh(vertices[used[v0:v1] % len(vertices)], local[q0:q1] - v0)
    return result
