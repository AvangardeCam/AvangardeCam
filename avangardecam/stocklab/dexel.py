# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""The material as a tri-dexel: three families of rays, along X, Y and Z.

A family along axis `a` stands on a grid over the two other axes in cyclic
order (X rays over (Y, Z), Y rays over (Z, X), Z rays over (X, Y)); each
ray goes through the middle of its cell and keeps the material on it as
sorted, disjoint intervals [lo, hi]. An empty place is lo = +inf,
hi = -inf, so it takes part in every sum and comparison without a mask.

The grid has no size in mm: `resolution` is the number of cells on the
longest edge of the stock (decision of the user), the other edges get the
nearest whole number of cells of about the same size.
"""

import numpy as np

DEFAULT_RESOLUTION = 500
FORMAT = "avangardecamlab-stock"
FORMAT_VERSION = 1

# A piece of material shorter than this part of the cell is dropped: it is
# the rounding error of a cut along a face cut before, not material.
SLIVER = 1e-6

# Stock.from_mesh moves the triangles this part of a cell across the rays
# (on u and on v), so that no ray goes through an edge or a corner.
MESH_NUDGE = (1.23456789e-4, 2.34567891e-4)
CHUNK = 2_000_000  # ray-triangle pairs worked out at once


def other_axes(axis):
    """The axes (u, v) the rays along `axis` stand on, in cyclic order."""
    return (axis + 1) % 3, (axis + 2) % 3


class Rays:
    """The rays along one axis: lo and hi of shape (nu, nv, K)."""

    def __init__(self, axis, lo, hi):
        self.axis = axis
        self.lo = lo
        self.hi = hi

    @property
    def shape(self):
        return self.lo.shape[:2]

    @property
    def depth(self):
        """K: the most intervals one ray can keep now."""
        return self.lo.shape[2]

    def length(self):
        """Material length on each ray, shape (nu, nv)."""
        return np.clip(self.hi - self.lo, 0.0, None).sum(axis=2)

    def extent(self, rays):
        """The lowest and the highest material on `rays` (an index into the
        grid), -inf/+inf crossed (lo > hi) on an empty ray."""
        return self.lo[rays][..., 0], self.hi[rays].max(axis=-1)

    def subtract(self, rays, a, b, sliver):
        """Take [a, b] away from `rays`.

        rays: an index into the (nu, nv) grid (slices or index arrays); a,
        b: arrays of the shape it picks (a ray left as it is has a = b =
        +inf). Each interval gives what is left of it on the left of a and
        on the right of b; then the pieces are sorted back, and K grows if
        some interval was split. Returns the length of material taken.
        """
        lo = self.lo[rays]
        hi = self.hi[rays]
        before = np.clip(hi - lo, 0.0, None).sum()
        a = a[..., None]
        b = b[..., None]
        left_hi = np.minimum(hi, a)
        right_lo = np.maximum(lo, b)
        left = left_hi - lo > sliver
        right = hi - right_lo > sliver
        # the pieces are disjoint: sorted by their starts they are sorted by
        # their ends too, so both sort on their own (empty: +inf, last)
        new_lo = np.sort(np.concatenate((np.where(left, lo, np.inf), np.where(right, right_lo, np.inf)), axis=-1), axis=-1)
        new_hi = np.sort(np.concatenate((np.where(left, left_hi, np.inf), np.where(right, hi, np.inf)), axis=-1), axis=-1)
        empty = new_lo == np.inf
        new_hi[empty] = -np.inf
        needed = int((~empty).sum(axis=-1).max(initial=0))
        if needed > self.depth:
            self._grow(needed)
        k = self.depth
        self.lo[rays] = new_lo[..., :k]
        self.hi[rays] = new_hi[..., :k]
        return float(before - np.clip(new_hi - new_lo, 0.0, None).sum())

    def _grow(self, depth):
        more = depth - self.depth
        pad = ((0, 0), (0, 0), (0, more))
        self.lo = np.pad(self.lo, pad, constant_values=np.inf)
        self.hi = np.pad(self.hi, pad, constant_values=-np.inf)


class Stock:
    """The material in the part's frame: a box at the start, then cut."""

    def __init__(self, lower, upper, counts, rays):
        self.lower = np.asarray(lower, dtype=float)
        self.upper = np.asarray(upper, dtype=float)
        self.counts = tuple(int(n) for n in counts)
        self.rays = rays
        # the cells whose material changed since watch() (first, last), or
        # None: none; not noted at all when not watched
        self._watched = False
        self._changed = None

    @classmethod
    def box(cls, lower, upper, resolution=DEFAULT_RESOLUTION):
        """A block from corner `lower` to corner `upper`, full of material."""
        lower = np.asarray(lower, dtype=float)
        upper = np.asarray(upper, dtype=float)
        size = upper - lower
        if np.any(size <= 0):
            raise ValueError("the stock must have a length on every axis")
        if resolution < 1:
            raise ValueError("the resolution must be at least 1 cell")
        cell = size.max() / resolution
        counts = [max(1, int(round(length / cell))) for length in size]
        rays = []
        for axis in range(3):
            u, v = other_axes(axis)
            lo = np.full((counts[u], counts[v], 1), lower[axis])
            hi = np.full((counts[u], counts[v], 1), upper[axis])
            rays.append(Rays(axis, lo, hi))
        return cls(lower, upper, counts, rays)

    @classmethod
    def from_mesh(cls, vertices, triangles, resolution=DEFAULT_RESOLUTION, lower=None, upper=None):
        """The material inside a closed mesh of triangles (a casting, the
        stock another setup left, in this stock's coordinates): each ray
        keeps what lies between its crossings with the surface, taken in
        pairs (even or odd: the triangles may face either way), and only
        within the box from
        `lower` to `upper` (the mesh's box when not given).

        The rays go through no edge or corner of the mesh: its triangles
        are moved a hair across them (MESH_NUDGE of a cell), as a stock's
        surface (mesh.surface) has its corners right on the middles of the
        cells of a grid like this one."""
        vertices = np.asarray(vertices, dtype=float).reshape(-1, 3)
        triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
        if len(triangles) == 0:
            raise ValueError("the mesh has no triangles")
        used = vertices[np.unique(triangles)]
        lower = used.min(axis=0) if lower is None else np.asarray(lower, dtype=float)
        upper = used.max(axis=0) if upper is None else np.asarray(upper, dtype=float)
        stock = cls.box(lower, upper, resolution)
        corners = [vertices[triangles[:, i]] for i in range(3)]
        for axis in range(3):
            stock.rays[axis] = _crossed(stock, axis, corners)
        return stock

    @property
    def spacing(self):
        """The cell size on each axis."""
        return (self.upper - self.lower) / np.array(self.counts)

    @property
    def sliver(self):
        return SLIVER * self.spacing.min()

    def centers(self, axis):
        """The coordinates of the middles of the cells along `axis`."""
        step = self.spacing[axis]
        return self.lower[axis] + (np.arange(self.counts[axis]) + 0.5) * step

    def block(self, axis, low, high):
        """The rays along `axis` standing in the box [low, high], as slices
        over (u, v), or None when there are none."""
        first, last = self.blocks(axis, np.asarray(low, float)[None], np.asarray(high, float)[None])
        if np.any(first[0] > last[0]):
            return None
        return tuple(slice(f, l + 1) for f, l in zip(first[0], last[0]))

    def blocks(self, axis, low, high):
        """The rays along `axis` standing in each box [low[i], high[i]]
        (arrays (n, 3)): the first and the last cell on (u, v), arrays
        (n, 2); no rays where first > last."""
        others = list(other_axes(axis))
        step = self.spacing[others]
        counts = np.array(self.counts)[others]
        # in cells from the middle of the first one, kept to the grid
        # (and to numbers an integer holds)
        first = np.clip((low[:, others] - self.lower[others]) / step - 0.5, -1.0, counts)
        last = np.clip((high[:, others] - self.lower[others]) / step - 0.5, -1.0, counts)
        first = np.maximum(np.ceil(first).astype(np.int64), 0)
        last = np.minimum(np.floor(last).astype(np.int64), counts - 1)
        return first, last

    def ray_at(self, axis, point):
        """The intervals of the ray along `axis` nearest to `point`, as a
        list of (lo, hi)."""
        index = []
        for other in other_axes(axis):
            i = int((point[other] - self.lower[other]) / self.spacing[other])
            index.append(min(max(i, 0), self.counts[other] - 1))
        family = self.rays[axis]
        lo = family.lo[index[0], index[1]]
        hi = family.hi[index[0], index[1]]
        return [(float(x), float(y)) for x, y in zip(lo, hi) if np.isfinite(x)]

    def ray_point(self, axis, point):
        """The middle of the cell nearest to `point` in the grid of the rays
        along `axis` (the coordinate along `axis` is kept)."""
        result = np.array(point, dtype=float)
        for other in other_axes(axis):
            i = int((point[other] - self.lower[other]) / self.spacing[other])
            i = min(max(i, 0), self.counts[other] - 1)
            result[other] = self.lower[other] + (i + 0.5) * self.spacing[other]
        return result

    def volume(self, axis=None):
        """The volume of the material as the rays along `axis` see it, or
        the mean of the three families."""
        if axis is None:
            return sum(self.volume(a) for a in range(3)) / 3.0
        u, v = other_axes(axis)
        area = self.spacing[u] * self.spacing[v]
        return float(self.rays[axis].length().sum() * area)

    def subtract(self, axis, rays, a, b):
        """Take [a[i], b[i]] away from `rays` along `axis` (an index into
        their grid: a block of slices or index arrays). Returns the volume
        taken as these rays see it."""
        u, v = other_axes(axis)
        if self._watched:
            self._note(axis, rays, a, b)
        length = self.rays[axis].subtract(rays, a, b, self.sliver)
        return length * self.spacing[u] * self.spacing[v]

    def watch(self):
        """Note from now on the cells whose material changes (changed_cells),
        to draw the surface again only there (mesh.pieces)."""
        self._watched = True
        self._changed = None

    def changed_cells(self):
        """The cells whose material changed since watch() or the last call:
        the first and the last cell on each axis (int arrays (3,), the box
        holds them all), or None when none did. A cut that takes nothing
        may be counted in (the box is never too small)."""
        changed, self._changed = self._changed, None
        return changed

    def _note(self, axis, rays, a, b):
        """Count in the cells [a, b] may take material from on `rays`."""
        family = self.rays[axis]
        first, last = family.extent(rays)
        a = np.broadcast_to(np.asarray(a, float), first.shape)
        b = np.broadcast_to(np.asarray(b, float), first.shape)
        low = np.maximum(a, first)
        high = np.minimum(b, last)
        takes = low < high
        if not np.any(takes):
            return
        if all(isinstance(r, slice) for r in rays):
            found = np.nonzero(takes)
            numbers = [f + (r.start or 0) for f, r in zip(found, rays)]
        else:
            numbers = [np.broadcast_to(np.asarray(r), takes.shape)[takes] for r in rays]
        box_low = np.empty(3, np.int64)
        box_high = np.empty(3, np.int64)
        for other, n in zip(other_axes(axis), numbers):
            box_low[other] = n.min()
            box_high[other] = n.max()
        along = (np.array([low[takes].min(), high[takes].max()]) - self.lower[axis]) / self.spacing[axis]
        along = np.clip(np.floor(along), 0, self.counts[axis] - 1).astype(np.int64)
        box_low[axis], box_high[axis] = along
        if self._changed is None:
            self._changed = (box_low, box_high)
        else:
            self._changed = (np.minimum(self._changed[0], box_low), np.maximum(self._changed[1], box_high))

    def copy(self):
        """A copy of the material (watched when this is, nothing noted)."""
        rays = [Rays(r.axis, r.lo.copy(), r.hi.copy()) for r in self.rays]
        result = Stock(self.lower.copy(), self.upper.copy(), self.counts, rays)
        result._watched = self._watched
        return result

    def save(self, path):
        """Write the stock to an .npz file (for the next setup)."""
        arrays = {"lower": self.lower, "upper": self.upper, "counts": np.array(self.counts)}
        for family in self.rays:
            arrays["lo%d" % family.axis] = family.lo
            arrays["hi%d" % family.axis] = family.hi
        np.savez_compressed(path, format=np.array(FORMAT), version=np.array(FORMAT_VERSION), **arrays)

    @classmethod
    def load(cls, path):
        with np.load(path) as data:
            if str(data["format"]) != FORMAT:
                raise ValueError("not a stock file of AvangardeCamLab")
            if int(data["version"]) > FORMAT_VERSION:
                raise ValueError("a stock file of a newer AvangardeCamLab")
            rays = [Rays(axis, data["lo%d" % axis], data["hi%d" % axis]) for axis in range(3)]
            return cls(data["lower"], data["upper"], data["counts"], rays)


def _crossed(stock, axis, corners):
    """The rays along `axis` of `stock` filled with what lies inside the
    triangles' surface (corners: three (n, 3) arrays), cut to the stock's
    box (see Stock.from_mesh)."""
    u, v = other_axes(axis)
    nu, nv = stock.counts[u], stock.counts[v]
    # the corners on the grid, in cells from the middle of the first ray
    pu = [(c[:, u] - stock.lower[u]) / stock.spacing[u] - 0.5 + MESH_NUDGE[0] for c in corners]
    pv = [(c[:, v] - stock.lower[v]) / stock.spacing[v] - 0.5 + MESH_NUDGE[1] for c in corners]
    pa = [c[:, axis] for c in corners]
    first_u = np.maximum(np.ceil(np.minimum(np.minimum(pu[0], pu[1]), pu[2])), 0).astype(np.int64)
    last_u = np.minimum(np.floor(np.maximum(np.maximum(pu[0], pu[1]), pu[2])), nu - 1).astype(np.int64)
    first_v = np.maximum(np.ceil(np.minimum(np.minimum(pv[0], pv[1]), pv[2])), 0).astype(np.int64)
    last_v = np.minimum(np.floor(np.maximum(np.maximum(pv[0], pv[1]), pv[2])), nv - 1).astype(np.int64)
    width = np.clip(last_v - first_v + 1, 0, None)
    count = np.clip(last_u - first_u + 1, 0, None) * width
    area = (pu[1] - pu[0]) * (pv[2] - pv[0]) - (pu[2] - pu[0]) * (pv[1] - pv[0])
    count[np.abs(area) <= 1e-12] = 0  # standing along the rays: crossed by none
    rays, levels = [], []
    ends = np.cumsum(count)
    start = 0
    while start < len(count):
        stop = max(int(np.searchsorted(ends, (ends[start - 1] if start else 0) + CHUNK, side="right")), start + 1)
        some = np.arange(start, stop)
        n = count[some]
        some = np.repeat(some, n)
        if len(some):
            local = np.arange(len(some)) - np.repeat(np.cumsum(n) - n, n)
            iu = first_u[some] + local // width[some]
            iv = first_v[some] + local % width[some]
            a = [x[some] for x in pu]
            b = [x[some] for x in pv]
            w0 = ((a[1] - iu) * (b[2] - iv) - (a[2] - iu) * (b[1] - iv)) / area[some]
            w1 = ((a[2] - iu) * (b[0] - iv) - (a[0] - iu) * (b[2] - iv)) / area[some]
            w2 = 1.0 - w0 - w1
            hit = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
            rays.append((iu * nv + iv)[hit])
            levels.append((w0 * pa[0][some] + w1 * pa[1][some] + w2 * pa[2][some])[hit])
        start = stop
    ray = np.concatenate(rays) if rays else np.zeros(0, np.int64)
    level = np.concatenate(levels) if levels else np.zeros(0)
    order = np.lexsort((level, ray))
    ray, level = ray[order], level[order]
    # in pairs along each ray (an odd last crossing grazes the surface: dropped)
    rank = _ranks(ray, nu * nv)
    whole = 2 * (np.bincount(ray, minlength=nu * nv) // 2)
    paired = rank < whole[ray]
    ray, level, rank = ray[paired], level[paired], rank[paired]
    lo = np.maximum(level[rank % 2 == 0], stock.lower[axis])
    hi = np.minimum(level[rank % 2 == 1], stock.upper[axis])
    ray = ray[rank % 2 == 0]
    kept = hi - lo > stock.sliver
    ray, lo, hi = ray[kept], lo[kept], hi[kept]
    k = _ranks(ray, nu * nv)
    depth = int(k.max()) + 1 if len(k) else 1
    result_lo = np.full((nu * nv, depth), np.inf)
    result_hi = np.full((nu * nv, depth), -np.inf)
    result_lo[ray, k] = lo
    result_hi[ray, k] = hi
    return Rays(axis, result_lo.reshape(nu, nv, depth), result_hi.reshape(nu, nv, depth))


def _ranks(sorted_numbers, size):
    """Each entry's place among the entries of the same number (sorted_numbers sorted)."""
    counts = np.bincount(sorted_numbers, minlength=size)
    starts = np.cumsum(counts) - counts
    return np.arange(len(sorted_numbers)) - starts[sorted_numbers]
