# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""The part as a closed mesh of triangles: distance and inside.

The bridge in AvangardeCam turns the part's solid into triangles; here
they are welded (the same corner of two faces of a STEP is one vertex),
then the questions the verification asks:

- distance(points, limit): the distance to the surface, up to `limit`
  (further points get `limit`); the triangles are kept in a grid of
  cells, each in the cells its box grown by `limit` reaches, so a point
  only meets the triangles of its own cell;
- inside(points): even or odd crossings of a ray going up from the point,
  in coordinates slightly sheared so that the ray goes through no edge or
  corner of a mesh made of round numbers;
- samples(spacing): points on the surface, one in each cell of
  `spacing` it goes through (for each way the surface faces), with the
  surface's normal there: as many as the area needs, however long and
  thin the triangles are (a STEP's cylinder sides).
"""

import numpy as np

# The ray of inside() goes up along (SHEAR_X, SHEAR_Y, 1).
SHEAR_X = 0.0123456789
SHEAR_Y = 0.0234567891
CHUNK = 500_000  # point-triangle pairs worked out at once


class Model:
    def __init__(self, vertices, triangles, weld=1e-7):
        vertices = np.asarray(vertices, dtype=float).reshape(-1, 3)
        triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        size = float(np.ptp(vertices, axis=0).max()) if len(vertices) else 1.0
        keys = np.round(vertices / (weld * max(size, 1e-12))).astype(np.int64)
        _, first, number = np.unique(keys, axis=0, return_index=True, return_inverse=True)
        number = number.ravel()
        triangles = number[triangles]
        vertices = vertices[first]
        a, b, c = (vertices[triangles[:, i]] for i in range(3))
        area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
        keep = (triangles[:, 0] != triangles[:, 1]) & (triangles[:, 1] != triangles[:, 2])
        keep &= (triangles[:, 2] != triangles[:, 0]) & (area > 0.0)
        self.vertices = vertices
        self.triangles = triangles[keep]
        self.lower = vertices.min(axis=0)
        self.upper = vertices.max(axis=0)

    def corners(self):
        return [self.vertices[self.triangles[:, i]] for i in range(3)]

    def closed(self):
        """Every edge in two triangles, once each way (needed by inside())."""
        t = self.triangles
        directed = np.concatenate((t[:, [0, 1]], t[:, [1, 2]], t[:, [2, 0]]))
        unique, counts = np.unique(directed, axis=0, return_counts=True)
        if np.any(counts != 1):
            return False
        back = np.unique(directed[:, ::-1], axis=0)
        return len(back) == len(unique) and bool(np.all(back == unique))

    def area(self):
        a, b, c = self.corners()
        return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2.0)

    def volume(self):
        a, b, c = self.corners()
        return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0)

    # -- distance -------------------------------------------------------------

    def distance(self, points, limit):
        """The distance of each point to the surface, `limit` for the points
        further than that."""
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        result = np.full(len(points), float(limit))
        if len(points) == 0 or len(self.triangles) == 0:
            return result
        a, b, c = self.corners()
        low = np.minimum(np.minimum(a, b), c) - limit
        high = np.maximum(np.maximum(a, b), c) + limit
        origin = np.minimum(points.min(axis=0), low.min(axis=0))
        cell = max(2.0 * limit, float(np.ptp(np.concatenate((points, a)), axis=0).max()) / 40.0, 1e-9)
        for cell_points, near in pairs(points, low, high, origin, cell):
            p = points[cell_points]
            best = np.full(len(p), float(limit))
            step = max(1, CHUNK // max(len(near), 1))
            for start in range(0, len(p), step):
                part = p[start:start + step]
                q = part[:, None, :]
                closest = closest_on_triangles(q, a[near][None], b[near][None], c[near][None])
                d = np.linalg.norm(closest - q, axis=2).min(axis=1)
                best[start:start + step] = np.minimum(best[start:start + step], d)
            result[cell_points] = best
        return result

    # -- inside ---------------------------------------------------------------

    def inside(self, points):
        """True for the points inside the closed surface."""
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        result = np.zeros(len(points), bool)
        if len(points) == 0 or len(self.triangles) == 0:
            return result
        shear = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [-SHEAR_X, -SHEAR_Y, 1.0]])
        p = points @ shear
        a, b, c = (corner @ shear for corner in self.corners())
        low = np.minimum(np.minimum(a, b), c)
        high = np.maximum(np.maximum(a, b), c)
        flat = [0, 1]  # columns over (x, y): the ray goes up in z
        low[:, 2] = -np.inf
        high[:, 2] = np.inf
        size = float(np.ptp(np.concatenate((p, a)), axis=0)[flat].max())
        cell = max(size / 60.0, 1e-9)
        origin = np.minimum(p.min(axis=0), low.min(axis=0))
        origin[2] = 0.0
        for cell_points, near in pairs(p, low, high, origin, cell, axes=flat):
            q = p[cell_points]
            crossings = np.zeros(len(q), np.int64)
            step = max(1, CHUNK // max(len(near), 1))
            for start in range(0, len(q), step):
                part = q[start:start + step, None, :]
                hit = _crossing_above(part, a[near][None], b[near][None], c[near][None])
                crossings[start:start + step] = hit.sum(axis=1)
            result[cell_points] = crossings % 2 == 1
        return result

    def signed_distance(self, points, limit):
        """The distance to the surface, negative inside, +-limit beyond."""
        d = self.distance(points, limit)
        return np.where(self.inside(points), -d, d)

    # -- samples --------------------------------------------------------------

    def samples(self, spacing):
        """(points, normals): a point of the surface in each cubic cell of
        `spacing` the surface goes through, with the normal of the surface
        there; one for each way the surface faces in the cell (the nearest
        axis and its sign), so both faces of a thin wall or an edge keep
        theirs. Every point of the surface has one within about 1.7
        spacings, the same way of facing.

        Each triangle is first covered by rows parallel to its longest
        edge, half a spacing apart, with points half a spacing apart."""
        a, b, c = self.corners()
        # the longest edge first: (p0, p1) the base, p2 the apex
        lengths = np.stack([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)], 1)
        turn = np.argmax(lengths, axis=1)
        corners = np.stack((a, b, c), axis=1)
        rows = np.arange(len(a))
        p0, p1, p2 = (corners[rows, (turn + i) % 3] for i in range(3))
        cross = np.cross(p1 - p0, p2 - p0)
        double = np.linalg.norm(cross, axis=1)
        normal = cross / double[:, None]
        base = np.linalg.norm(p1 - p0, axis=1)
        step = spacing / 2.0
        count = np.ceil(double / base / step).astype(np.int64)  # rows: height / step
        owner, j = _numbered(count + 1)
        v = (j / count[owner])[:, None]
        along = np.ceil(base[owner] * (1.0 - v[:, 0]) / step).astype(np.int64)
        row, i = _numbered(along + 1)
        tri = owner[row]
        f = np.where(along[row] > 0, i / np.maximum(along[row], 1), 0.0)[:, None]
        start = p0[tri] + v[row] * (p2 - p0)[tri]
        points = start + f * (1.0 - v[row]) * (p1 - p0)[tri]
        normals = normal[tri]
        # one point for each cell and way of facing
        way = np.argmax(np.abs(normals), axis=1) * 2 + (normals[np.arange(len(normals)), np.argmax(np.abs(normals), axis=1)] > 0)
        cell = np.floor((points - self.lower) / spacing).astype(np.int64)
        keys = np.column_stack((cell, way))
        _, first = np.unique(keys, axis=0, return_index=True)
        return points[first], normals[first]


def vertex_normals(model):
    """The normal at each vertex: the mean of its triangles' normals,
    weighted by their area."""
    a, b, c = model.corners()
    n = np.cross(b - a, c - a)
    total = np.zeros_like(model.vertices)
    for i in range(3):
        for axis in range(3):
            total[:, axis] += np.bincount(model.triangles[:, i], weights=n[:, axis], minlength=len(total))
    length = np.linalg.norm(total, axis=1, keepdims=True)
    return total / np.where(length > 0.0, length, 1.0)


def _numbered(count):
    """For counts per item: (item of each, its number 0.. within the item)."""
    owner = np.repeat(np.arange(len(count)), count)
    return owner, np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)


def pairs(points, low, high, origin, cell, axes=(0, 1, 2)):
    """For each cell of a grid holding points: (indices of its points,
    indices of the boxes [low, high] reaching it)."""
    axes = list(axes)
    point_cells = np.floor((points[:, axes] - origin[axes]) / cell).astype(np.int64)
    first = np.floor((low[:, axes] - origin[axes]) / cell).astype(np.int64)
    last = np.floor((high[:, axes] - origin[axes]) / cell).astype(np.int64)
    top = point_cells.max(axis=0)
    first = np.maximum(first, 0)
    last = np.minimum(last, top)
    reach = last >= first
    boxes = np.nonzero(reach.all(axis=1))[0]
    first, last = first[boxes], last[boxes]
    span = last - first + 1
    shape = top + 1
    # every (box, cell) the box reaches, as a flat cell number
    counts = span.prod(axis=1)
    owner = np.repeat(np.arange(len(boxes)), counts)
    offset = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
    cells = np.zeros(len(owner), np.int64)
    for i in range(len(axes)):
        inner = np.prod(span[:, i + 1:], axis=1) if i + 1 < len(axes) else np.ones(len(boxes), np.int64)
        coord = first[owner, i] + (offset // inner[owner]) % span[owner, i]
        cells = cells * shape[i] + coord
    order = np.argsort(cells, kind="stable")
    cells, owner = cells[order], owner[order]
    flat_points = np.ravel_multi_index(point_cells.T, shape)
    by_cell = np.argsort(flat_points, kind="stable")
    occupied, starts = np.unique(flat_points[by_cell], return_index=True)
    ends = np.append(starts[1:], len(by_cell))
    lo = np.searchsorted(cells, occupied, "left")
    hi = np.searchsorted(cells, occupied, "right")
    for cell_id, s, e, l, h in zip(occupied, starts, ends, lo, hi):
        if h > l:
            yield by_cell[s:e], boxes[owner[l:h]]


def closest_on_triangles(p, a, b, c):
    """The point of triangle (a, b, c) closest to p, all broadcast (the
    regions of the corners, the edges and the face, by the dot products)."""
    ab, ac = b - a, c - a
    ap, bp, cp = p - a, p - b, p - c
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        total = va + vb + vc
        v = np.where(total != 0, vb / total, 0.0)[..., None]
        w = np.where(total != 0, vc / total, 0.0)[..., None]
        result = a + ab * v + ac * w
        # the regions, the last written first: the first one true wins
        t = ((d4 - d3) / ((d4 - d3) + (d5 - d6)))[..., None]
        result = np.where(((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0))[..., None], b + (c - b) * t, result)
        t = (d2 / (d2 - d6))[..., None]
        result = np.where(((vb <= 0) & (d2 >= 0) & (d6 <= 0))[..., None], a + ac * t, result)
        result = np.where(((d6 >= 0) & (d5 <= d6))[..., None], c, result)
        t = (d1 / (d1 - d3))[..., None]
        result = np.where(((vc <= 0) & (d1 >= 0) & (d3 <= 0))[..., None], a + ab * t, result)
        result = np.where(((d3 >= 0) & (d4 <= d3))[..., None], b, result)
        result = np.where(((d1 <= 0) & (d2 <= 0))[..., None], a, result)
    return result


def _crossing_above(p, a, b, c):
    """True where the ray up from p (along z) goes through triangle
    (a, b, c) above p."""
    x, y = p[..., 0], p[..., 1]
    w0 = (b[..., 0] - x) * (c[..., 1] - y) - (b[..., 1] - y) * (c[..., 0] - x)
    w1 = (c[..., 0] - x) * (a[..., 1] - y) - (c[..., 1] - y) * (a[..., 0] - x)
    w2 = (a[..., 0] - x) * (b[..., 1] - y) - (a[..., 1] - y) * (b[..., 0] - x)
    total = w0 + w1 + w2
    within = ((w0 > 0) & (w1 > 0) & (w2 > 0)) | ((w0 < 0) & (w1 < 0) & (w2 < 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (w0 * a[..., 2] + w1 * b[..., 2] + w2 * c[..., 2]) / total
    return within & (z > p[..., 2])


def _dot(u, v):
    return np.einsum("...i,...i->...", u, v)
