# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""Checking a program against the part.

- Too deep (gouges), exactly: points close together on the surface of the
  part (Model.samples) are checked against the volume each move's
  tool sweeps, with the formulas of the cut, so the grid of the stock does
  not count. A point inside the swept volume was cut, as deep as its
  distance to the edge of the swept volume. The way out along the three
  axes (from the rays of the cut) is quick and never shorter, so it sorts
  out the points to look at: only where it is more than the tolerance is
  the true distance worked out, as the nearest plane touching the swept
  volume (its support function, exact for a solid of revolution moved
  along a line: min over directions n of h(n) - p.n), searched over 200
  directions, then on a 5 x 5 grid of directions around the best, halved
  while the best is inside it (a grid, not steps along two lines: the
  least is often on a fold of h, where the side of the tool meets its
  bottom or top, and steps along two lines stop on a fold). Near the end
  of a move there are two hollows (out through the side, out through the
  round end), so the search starts twice: from the best direction and
  from the best one 40 degrees or more away from it. Any h(n) - p.n is
  at least the distance, so the lesser of the two is the answer.
  Many moves are checked at once (pairs of a point and a move whose box
  holds it, the way out along the tool axis first: mostly the point is
  not inside). A point's depth is the most over the moves, so its true
  distance is worked out from the move with the greatest bound down, and
  not for a move whose bound is no more than the depth already found.
- Material left: the distance of the surface of the simulated stock from
  the part (positive outside), as fine as the stock's grid.
- Rapid moves into material: from the simulation (program.simulate).

The colours go on the surface of the simulated stock (colors()): gray
where it is the part, blue where material is left, red around the points
found too deep (from the exact check only, so the grid adds no red).
"""

from typing import NamedTuple, Optional

import numpy as np

from . import sweep
from .cut import swept_box, tool_axis
from .dexel import DEFAULT_RESOLUTION, other_axes
from .mesh import surface
from .model import CHUNK, pairs
from .program import segments, simulate

TOLERANCE = 0.01  # mm deeper than the part that counts as too deep

PAIRS = 20_000  # pairs of a point and a move checked at once
EXACT = 2_000  # points whose true depth is searched at once


def _sphere(count):
    """Directions spread evenly on the sphere (the Fibonacci spiral)."""
    i = np.arange(count) + 0.5
    z = 1.0 - 2.0 * i / count
    angle = np.pi * (1.0 + 5.0**0.5) * i
    r = np.sqrt(1.0 - z * z)
    return np.column_stack((r * np.cos(angle), r * np.sin(angle), z))


def _rings(count):
    """Directions every 360 / count degrees round each axis: the least
    distance often lies across the tool axis (out through the side of
    the tool), where the spiral has few."""
    angle = np.arange(count) * 2.0 * np.pi / count
    c, s = np.cos(angle), np.sin(angle)
    zero = np.zeros(count)
    return np.concatenate([np.column_stack(v) for v in ((c, s, zero), (zero, c, s), (s, zero, c))])


DIRECTIONS = np.concatenate((_sphere(200), _rings(72)))

GRAY = np.array([0.72, 0.74, 0.78])
LIGHT_RED = np.array([1.0, 0.55, 0.5])
RED = np.array([0.85, 0.05, 0.05])
LIGHT_BLUE = np.array([0.62, 0.76, 1.0])
BLUE = np.array([0.08, 0.25, 0.85])


class Gouges(NamedTuple):
    """points: on the surface of the part; depth: how deep the tools went
    into the part there (0: not at all); operation: the number of the
    operation that went deepest there (-1: none)."""

    points: np.ndarray
    depth: np.ndarray
    tolerance: float
    operation: Optional[np.ndarray] = None

    def too_deep(self):
        return self.depth > self.tolerance

    def worst(self):
        """(depth, point) of the deepest place."""
        i = int(np.argmax(self.depth))
        return float(self.depth[i]), self.points[i]


class Leftover(NamedTuple):
    """mesh: the surface of the stock; distance: of each vertex from the
    part, positive outside it, +-limit beyond; finished: up to this the
    stock counts as the part (the stock's grid is not finer)."""

    mesh: object
    distance: np.ndarray
    finished: float
    limit: float

    def colors(self):
        """Gray where finished, blue from light to dark (`limit`) where
        material is left."""
        t = np.clip((self.distance - self.finished) / max(self.limit - self.finished, 1e-12), 0.0, 1.0)[:, None]
        blue = LIGHT_BLUE + (BLUE - LIGHT_BLUE) * t
        return np.where((self.distance > self.finished)[:, None], blue, GRAY)


class Report(NamedTuple):
    stock: object
    collisions: list
    gouges: Gouges
    leftover: Leftover


def verify(stock, model, operations, tolerance=TOLERANCE, resolution=None, limit=None):
    """Simulate the operations on a copy of `stock`, then check them
    against the part `model` (a Model)."""
    stock = stock.copy()
    collisions = simulate(stock, operations)
    return Report(stock, collisions, gouges(model, operations, tolerance, resolution), leftover(stock, model, limit))


def gouges(model, operations, tolerance=TOLERANCE, resolution=None):
    """Where the tools went into the part (Gouges). resolution: points on
    the longest edge of the part's box (half the stock's by default)."""
    size = float(np.max(model.upper - model.lower))
    resolution = DEFAULT_RESOLUTION // 2 if resolution is None else resolution
    spacing = size / resolution
    points, _ = model.samples(spacing)
    grid = PointGrid(points, max(8.0 * spacing, size / 50.0))
    depth = np.zeros(len(points))
    owner = np.full(len(points), -1)
    chord = tolerance / 20.0
    for index, operation in enumerate(operations):
        k, sigma = tool_axis(operation.axis)
        moves = [(a, b) for a, b, _, _ in segments(operation, chord)]
        if not moves:
            continue
        before = depth.copy()
        starts, ends = (np.array(x) for x in zip(*moves))
        for part in operation.tool.parts:
            low, high = swept_box(part, k, sigma, starts, ends)
            count = grid.count(low, high)
            moves = np.flatnonzero(count)
            if moves.size == 0:
                continue
            # about PAIRS pairs of a point and a move at a time
            chunk = (np.cumsum(count[moves]) - count[moves]) // PAIRS
            for some in np.split(moves, np.flatnonzero(np.diff(chunk)) + 1):
                point, move = grid.pairs(low[some], high[some])
                move = some[move]
                bound = _depth(part, k, sigma, starts[move], ends[move], points[point])
                shallow = bound <= tolerance
                np.maximum.at(depth, point[shallow], bound[shallow])
                deep = ~shallow
                _deepen(depth, part, k, sigma, starts[move[deep]], ends[move[deep]], points, point[deep], bound[deep])
        owner[depth > before] = index
    return Gouges(points, depth, tolerance, owner)


def colors(report, deep=None, near=None):
    """Colours for the vertices of report.leftover.mesh (the simulated
    stock): Leftover.colors(), and red, from light (just too deep) to dark
    (`deep` or more, 20 tolerances by default), at the vertices nearer to
    a point found too deep than its depth and `near` (1.5 cells by
    default: the stock's surface is about that fine)."""
    left = report.leftover
    result = left.colors()
    found = report.gouges
    too_deep = found.too_deep()
    if not too_deep.any() or len(left.mesh.vertices) == 0:
        return result
    tolerance = found.tolerance
    deep = 20.0 * tolerance if deep is None else deep
    near = 3.0 * left.finished if near is None else near
    p = found.points[too_deep]
    d = found.depth[too_deep]
    reach = d + near
    low = p - reach[:, None]
    high = p + reach[:, None]
    vertices = left.mesh.vertices
    worst = np.zeros(len(vertices))
    origin = np.minimum(vertices.min(axis=0), low.min(axis=0))
    cell = max(2.0 * float(reach.max()), float(np.ptp(vertices, axis=0).max()) / 40.0)
    for cell_points, boxes in pairs(vertices, low, high, origin, cell):
        step = max(1, CHUNK // len(boxes))
        for start in range(0, len(cell_points), step):
            some = cell_points[start:start + step]
            gap = np.linalg.norm(vertices[some][:, None] - p[boxes][None], axis=2)
            reached = np.where(gap <= reach[boxes][None], d[boxes][None], 0.0).max(axis=1)
            worst[some] = np.maximum(worst[some], reached)
    t = np.clip((worst - tolerance) / max(deep - tolerance, 1e-12), 0.0, 1.0)[:, None]
    return np.where((worst > 0.0)[:, None], LIGHT_RED + (RED - LIGHT_RED) * t, result)


def leftover(stock, model, limit=None):
    """How much material the stock has left over the part (Leftover).
    limit: the distance shown darkest, 25 cells by default. Up to half a
    cell counts as finished: the surface of the stock is exact on flat
    faces, but in an inner corner it stands out by about a third of a cell."""
    cell = float(stock.spacing.min())
    limit = 25.0 * cell if limit is None else limit
    mesh = surface(stock)
    return Leftover(mesh, model.signed_distance(mesh.vertices, limit), 0.5 * cell, limit)


def _depth(part, k, sigma, starts, ends, points):
    """The distance of each point to the edge of the volume swept from
    starts[i] to ends[i], the shortest way out along an axis; 0 outside
    it. Never less than the true distance."""
    u, v = other_axes(k)
    order = [k, u, v]
    hit, lo, hi = sweep.along(part, sigma, starts[:, order].T, ends[:, order].T, points[:, u], points[:, v])
    x = points[:, k]
    depth = np.where(hit & (lo < x) & (x < hi), np.minimum(x - lo, hi - x), 0.0)
    # the other two axes only where it is inside (mostly it is not)
    inside = np.flatnonzero(depth > 0.0)
    for f in (u, v):
        j = 3 - f - k
        order = [f, k, j]
        p = points[inside]
        hit, lo, hi = sweep.across(part, sigma, starts[inside][:, order].T, ends[inside][:, order].T, p[:, k], p[:, j])
        x = p[:, f]
        depth[inside] = np.minimum(depth[inside], np.where(hit & (lo < x) & (x < hi), np.minimum(x - lo, hi - x), 0.0))
    return depth


def _deepen(depth, part, k, sigma, starts, ends, points, point, bound):
    """Raise depth[point[i]] to the true depth of points[point[i]] in the
    volume swept from starts[i] to ends[i], where it can: where `bound`
    (never less) is more than the depth already found. A point's pairs go
    in turn from the greatest bound, so those of a move just touching it
    are mostly left out."""
    left = bound > depth[point]
    while left.any():
        which = np.flatnonzero(left)
        which = which[np.lexsort((-bound[which], point[which]))]
        first = which[np.append(True, point[which][1:] != point[which][:-1])]
        for some in np.array_split(first, -(-len(first) // EXACT)):
            p = point[some]
            exact = _inner_distance(part, k, sigma, starts[some], ends[some], points[p])
            depth[p] = np.maximum(depth[p], np.minimum(exact, bound[some]))
        left[first] = False
        left &= bound > depth[point]


def _gaps(part, k, sigma, starts, ends, points):
    """The gap h(n) - p.n of each point over DIRECTIONS: (values,
    gap(n, rows)), h the support function of the volume the part sweeps
    from starts[i] to ends[i] (the part's, plus the further of start.n
    and end.n)."""
    to_start = starts - points
    to_end = ends - points

    def gap(n, rows):  # n: (m, d, 3) unit directions for the points `rows`
        na = sigma * n[..., k]
        nr = np.sqrt(np.clip(1.0 - na * na, 0.0, None))
        reach = np.maximum(np.einsum("mdi,mi->md", n, to_start[rows]), np.einsum("mdi,mi->md", n, to_end[rows]))
        return part.support(nr, na) + reach

    values = gap(np.broadcast_to(DIRECTIONS, (len(points),) + DIRECTIONS.shape), np.arange(len(points)))
    return values, gap


def _inner_distance(part, k, sigma, starts, ends, points):
    """The distance of each point inside the volume the part sweeps from
    starts[i] to ends[i] to its edge: the least gap over directions
    (_gaps), searched over DIRECTIONS, then on a grid of directions around
    the best."""
    values, gap = _gaps(part, k, sigma, starts, ends, points)
    rows = np.arange(len(points))
    first = np.argmin(values, axis=1)
    apart = DIRECTIONS @ DIRECTIONS.T < np.cos(np.radians(40.0))
    second = np.argmin(np.where(apart[first], values, np.inf), axis=1)
    value = np.minimum(_closer(gap, DIRECTIONS[first], values[rows, first]),
                       _closer(gap, DIRECTIONS[second], values[rows, second]))
    return np.maximum(value, 0.0)


def _closer(gap, n, value):
    """From directions n (their gap `value`), the least gap on grids of
    directions around them, each grid halved while its best is inside;
    only the points still moving are worked out."""
    n = n.copy()
    value = value.copy()
    step = np.full(len(n), 0.25)
    grid = np.array([(i, j) for i in range(-2, 3) for j in range(-2, 3)], float) / 2.0
    edge = np.abs(grid).max(axis=1) == 1.0
    active = np.arange(len(n))
    for _ in range(80):
        m = n[active]
        # two directions across m: m x X (or m x Y near X), then m x that
        x, y, z = m.T
        zero = np.zeros(len(m))
        t1 = np.where((np.abs(x) < 0.9)[:, None], np.column_stack((zero, z, -y)), np.column_stack((-z, zero, x)))
        t1 /= np.sqrt(np.einsum("mi,mi->m", t1, t1))[:, None]
        t2 = np.column_stack((y * t1[:, 2] - z * t1[:, 1], z * t1[:, 0] - x * t1[:, 2], x * t1[:, 1] - y * t1[:, 0]))
        tries = m[:, None] + step[active, None, None] * (grid[None, :, :1] * t1[:, None] + grid[None, :, 1:] * t2[:, None])
        tries /= np.sqrt(np.einsum("mdi,mdi->md", tries, tries))[..., None]
        values = gap(tries, active)
        pick = np.argmin(values, axis=1)
        best = values[np.arange(len(active)), pick]
        lower = best < value[active]
        n[active[lower]] = tries[np.flatnonzero(lower), pick[lower]]
        value[active[lower]] = best[lower]
        # the best on the grid's edge: the least may be further, look there
        step[active] = np.where(lower & edge[pick], step[active], step[active] / 2.0)
        active = active[step[active] >= 1e-8]  # a gap off by less than 1e-7 mm
        if active.size == 0:
            break
    return value


class PointGrid:
    """Points sorted into cubic cells, to find those in boxes quickly."""

    def __init__(self, points, cell):
        self.points = points
        self.cell = cell
        self.origin = points.min(axis=0)
        index = np.floor((points - self.origin) / cell).astype(np.int64)
        self.shape = index.max(axis=0) + 1
        flat = np.ravel_multi_index(index.T, self.shape)
        self.order = np.argsort(flat, kind="stable")
        self.sorted = flat[self.order]
        # points in a cell that has any
        self.full = len(points) / (1 + np.count_nonzero(np.diff(self.sorted)))

    def _cells(self, low, high):
        """The first and the last cell of each box (arrays (n, 3)), kept to
        the grid: no cells where first > last."""
        first = np.floor(np.clip((low - self.origin) / self.cell, -1.0, self.shape)).astype(np.int64)
        last = np.floor(np.clip((high - self.origin) / self.cell, -1.0, self.shape)).astype(np.int64)
        return np.maximum(first, 0), np.minimum(last, self.shape - 1)

    def count(self, low, high):
        """About how many points each box holds (from its cells)."""
        first, last = self._cells(low, high)
        return np.ceil(np.prod(np.clip(last - first + 1, 0, None), axis=1) * self.full).astype(np.int64)

    def pairs(self, low, high):
        """The points in each box [low[i], high[i]]: (point, box) index
        arrays of the pairs."""
        first, last = self._cells(low, high)
        size = np.clip(last - first + 1, 0, None)
        # each column (x, y) of a box: its cells over z follow each other
        columns = size[:, 0] * size[:, 1] * (size[:, 2] > 0)
        box = np.repeat(np.arange(len(columns)), columns)
        place = np.arange(columns.sum()) - np.repeat(np.cumsum(columns) - columns, columns)
        ix = first[box, 0] + place // size[box, 1]
        iy = first[box, 1] + place % size[box, 1]
        begin = np.searchsorted(self.sorted, np.ravel_multi_index((ix, iy, first[box, 2]), self.shape), "left")
        count = np.searchsorted(self.sorted, np.ravel_multi_index((ix, iy, last[box, 2]), self.shape), "right") - begin
        box = np.repeat(box, count)
        found = self.order[np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count) + np.repeat(begin, count)]
        p = self.points[found]
        inside = np.all((p >= low[box]) & (p <= high[box]), axis=1)
        return found[inside], box[inside]
