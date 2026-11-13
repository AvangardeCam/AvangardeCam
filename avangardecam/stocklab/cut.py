# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""Cutting the stock with the moves of the tool's tip, in the part's frame.

The tool axis goes from the tip to the shank, along X, Y or Z of the part
("+Z": the tool comes from above). Lines are cut as they are; arcs and
helices as chords no further than CHORD cells from the arc. A rapid move
cuts as a feed move (the verification will tell them apart).

Many moves are cut at once (cut_lines), about PAIRS pairs of a ray and a
move at a time (more is slower: the numbers no longer stay in the
processor's cache): the pairs of a ray and a move whose box holds the
ray and that has material there, the interval each move takes off its
ray (sweep), and then each ray loses the union of the intervals that
take material. Mostly they share a point (the moves follow each other),
so the union is from the least start to the most end, found without
sorting; only the other rays are sorted. A move across the tool axis
(2.5D) cuts the rays across it at the heights of the tool's cylinder
with the same disc: there each column of rays is worked out once.
"""

import math

import numpy as np

from . import sweep
from .dexel import other_axes
from .tools import Line

AXES = {"X": 0, "Y": 1, "Z": 2}

# How far a chord of an arc may go from the arc, in cells (of the smallest).
# 0.25 cut a helix of R0.75 at cells of 1.2 mm as 4 chords 0.3 mm inside it:
# the floor it cleared kept material, and a rapid move over it was a
# collision. The more chords cost little: the tests 52 s -> 56 s, a plate's
# whole program (AvangardeCam) at 250 and 500 cells in the same time.
CHORD = 0.02

# About this many pairs of a ray and a move are worked out at once: the
# fastest on a laptop with 3 MB of cache (i5-4200H): 1.4x faster than 250 000.
PAIRS = 15_000


def tool_axis(axis):
    """(k, sigma) of a tool axis: "+Z", "-X", ... or a vector along an axis."""
    if isinstance(axis, str):
        name = axis.strip().upper()
        sigma = -1 if name.startswith("-") else 1
        name = name.lstrip("+-")
        if name not in AXES:
            raise ValueError("the tool axis must be X, Y or Z, with + or -")
        return AXES[name], sigma
    vector = np.asarray(axis, dtype=float)
    k = int(np.argmax(np.abs(vector)))
    length = np.linalg.norm(vector)
    if length == 0.0 or np.linalg.norm(np.delete(vector, k)) > 1e-9 * length:
        raise ValueError("the tool axis must go along X, Y or Z of the part")
    return k, 1 if vector[k] > 0 else -1


def swept_box(part, k, sigma, start, end):
    """The box around what the part sweeps from `start` to `end` (points,
    or arrays (n, 3) of them): (low, high)."""
    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)
    low = np.minimum(start, end) - part.rmax
    high = np.maximum(start, end) + part.rmax
    ends = [point[..., k] + sigma * h for point in (start, end) for h in (part.h0, part.h1)]
    low[..., k] = np.min(ends, axis=0)
    high[..., k] = np.max(ends, axis=0)
    return low, high


def cut_line(stock, tool, axis, start, end):
    """Cut what the tool sweeps going straight from `start` to `end` (its
    tip). Returns the volume taken (the mean of the three families)."""
    return cut_lines(stock, tool, axis, [start], [end])


def cut_lines(stock, tool, axis, starts, ends):
    """Cut the moves from starts[i] to ends[i] (arrays (n, 3)) all at once:
    the same as one after another, as material once taken stays taken.
    Returns the volume taken (the mean of the three families)."""
    k, sigma = tool_axis(axis)
    starts = np.asarray(starts, dtype=float).reshape(-1, 3)
    ends = np.asarray(ends, dtype=float).reshape(-1, 3)
    taken = 0.0
    for part in tool.parts:
        low, high = swept_box(part, k, sigma, starts, ends)
        band = _band(part)
        for a in range(3):
            first, last = stock.blocks(a, low, high)
            shared = np.zeros(len(starts), bool)
            columns = 0
            if a != k and band is not None:
                # moves across the tool axis, at the heights of the
                # cylinder (_cut_band)
                b_low, b_high = low.copy(), high.copy()
                b_low[:, k] = starts[:, k] + min(sigma * band[0], sigma * band[1])
                b_high[:, k] = starts[:, k] + max(sigma * band[0], sigma * band[1])
                b_first, b_last = stock.blocks(a, b_low, b_high)
                shared = (np.abs(ends[:, k] - starts[:, k]) < sweep.TINY) & np.all(b_first <= b_last, axis=1)
                # their other rays: at the heights of the tip
                kk = 0 if other_axes(a)[0] == k else 1
                if sigma > 0:
                    last[shared, kk] = b_first[shared, kk] - 1
                else:
                    first[shared, kk] = b_last[shared, kk] + 1
                columns = np.where(shared, b_last[:, 1 - kk] - b_first[:, 1 - kk] + 1, 0)
            # a column shared costs about two rays
            count = np.prod(np.clip(last - first + 1, 0, None), axis=1) + 2 * columns
            moves = np.flatnonzero(count)
            if moves.size == 0:
                continue
            # moves after each other (so near each other), about PAIRS
            # pairs of a ray and a move at a time
            chunk = (np.cumsum(count[moves]) - count[moves]) // PAIRS
            for some in np.split(moves, np.flatnonzero(np.diff(chunk)) + 1):
                rest = some[np.all(first[some] <= last[some], axis=1)]
                if rest.size:
                    taken += _cut_some(stock, part, k, sigma, a, starts[rest], ends[rest],
                                       low[rest, a], high[rest, a], first[rest], last[rest])
                column = some[shared[some]]
                if column.size:
                    taken += _cut_band(stock, part, k, sigma, a, band, starts[column], ends[column],
                                       b_first[column], b_last[column])
    return taken / 3.0


def _band(part):
    """From and to how high above the tip the part is a cylinder (its top
    piece), or None."""
    top = part.pieces[-1]
    if isinstance(top, Line) and top.slope == 0.0:
        return top.h0, top.h1
    return None


def _cut_some(stock, part, k, sigma, a, starts, ends, low, high, first, last):
    """Cut a few moves on the rays along `a`. low, high: the boxes of the
    moves along `a`; first, last: their rays (Stock.blocks)."""
    family = stock.rays[a]
    corner = first.min(axis=0)
    width = int(last[:, 1].max() - corner[1]) + 1
    box = tuple(slice(c, e + 1) for c, e in zip(corner, last.max(axis=0)))
    lo_box = family.lo[box]
    hi_box = family.hi[box]
    # the rays with material where any of the moves goes along them
    # (numbered in the box: u * width + v), sorted
    candidates = np.flatnonzero(np.any((lo_box < high.max()) & (hi_box > low.min()), axis=-1))
    if candidates.size == 0:
        return 0.0
    # each move, row by row: the candidates between its first and last ray
    first = first - corner
    last = last - corner
    rows = last[:, 0] - first[:, 0] + 1
    move = np.repeat(np.arange(len(rows)), rows)
    row = first[move, 0] + np.arange(rows.sum()) - np.repeat(np.cumsum(rows) - rows, rows)
    begin = np.searchsorted(candidates, row * width + first[move, 1], "left")
    count = np.searchsorted(candidates, row * width + last[move, 1], "right") - begin
    move = np.repeat(move, count)
    ray = candidates[np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count) + np.repeat(begin, count)]
    # only where this move goes along them
    keep = (lo_box[..., 0].ravel()[ray] < high[move]) & (hi_box.max(axis=-1).ravel()[ray] > low[move])
    move, ray = move[keep], ray[keep]
    if move.size == 0:
        return 0.0
    iu = ray // width + corner[0]
    iv = ray % width + corner[1]
    u, v = other_axes(a)
    at = {u: stock.centers(u)[iu], v: stock.centers(v)[iv]}
    if a == k:
        order = [k, u, v]
        hit, lo, hi = sweep.along(part, sigma, starts[move][:, order].T, ends[move][:, order].T, at[u], at[v])
    else:
        j = 3 - a - k
        order = [a, k, j]
        hit, lo, hi = sweep.across(part, sigma, starts[move][:, order].T, ends[move][:, order].T, at[k], at[j])
    return _take(stock, a, iu[hit], iv[hit], lo[hit], hi[hit])


def _cut_band(stock, part, k, sigma, a, band, starts, ends, first, last):
    """Moves across the tool axis, on the rays along `a` at the heights of
    the part's cylinder (`band`, Stock.blocks first and last): the disc is
    the same at all of them, so the chords of each move are worked out once
    for a column of rays, and their union shared up the column."""
    u, v = other_axes(a)
    kk = 0 if u == k else 1  # which of (u, v) is along the tool axis
    jj = 1 - kk
    j = (u, v)[jj]
    columns = last[:, jj] - first[:, jj] + 1
    move = np.repeat(np.arange(len(columns)), columns)
    column = first[move, jj] + np.arange(columns.sum()) - np.repeat(np.cumsum(columns) - columns, columns)
    middle = starts[move, k] + sigma * (band[0] + band[1]) / 2.0
    order = [a, k, j]
    hit, lo, hi = sweep.across(part, sigma, starts[move][:, order].T, ends[move][:, order].T,
                               middle, stock.centers(j)[column])
    if not hit.any():
        return 0.0
    move, column, lo, hi = move[hit], column[hit], lo[hit], hi[hit]
    # the moves with the same rays up the column together (the same
    # height): the union of their chords on each column
    cells = stock.counts[k] + 1
    heights, group = np.unique(first[:, kk] * cells + last[:, kk], return_inverse=True)
    width = stock.counts[j]
    rounds = _union(group.ravel()[move] * width + column, lo, hi, len(heights) * width)
    pieces, lo, hi = (np.concatenate(x) for x in zip(*rounds))
    group, column = np.divmod(pieces, width)
    lowest, highest = np.divmod(heights[group], cells)
    # up each column
    count = highest - lowest + 1
    piece = np.repeat(np.arange(len(count)), count)
    ray = [None, None]
    ray[kk] = lowest[piece] + np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count)
    ray[jj] = column[piece]
    return _take(stock, a, ray[0], ray[1], lo[piece], hi[piece])


def _take(stock, a, iu, iv, lo, hi):
    """Take [lo[i], hi[i]] off the ray (iu[i], iv[i]) along `a`; a ray met
    by several moves loses the union of their intervals. Returns the
    volume taken."""
    # only what takes material (most moves go mostly over air cut before)
    family = stock.rays[a]
    takes = np.any((family.lo[iu, iv] < hi[:, None]) & (family.hi[iu, iv] > lo[:, None]), axis=1)
    iu, iv, lo, hi = iu[takes], iv[takes], lo[takes], hi[takes]
    if iu.size == 0:
        return 0.0
    # the rays numbered in the box around them
    corner_u, corner_v = iu.min(), iv.min()
    width = int(iv.max() - corner_v) + 1
    size = (int(iu.max() - corner_u) + 1) * width
    taken = 0.0
    for r, l, h in _union((iu - corner_u) * width + (iv - corner_v), lo, hi, size):
        taken += stock.subtract(a, (r // width + corner_u, r % width + corner_v), l, h)
    return taken


def _union(ray, lo, hi, size):
    """The union of the intervals [lo, hi] on each ray (numbered below
    `size`), in rounds of one piece of a ray each: [(rays, lo, hi), ...]."""
    low = np.full(size, np.inf)
    np.minimum.at(low, ray, lo)
    high = np.full(size, -np.inf)
    np.maximum.at(high, ray, hi)
    latest_start = np.full(size, -np.inf)
    np.maximum.at(latest_start, ray, lo)
    earliest_end = np.full(size, np.inf)
    np.minimum.at(earliest_end, ray, hi)
    rays = np.flatnonzero(low < np.inf)
    # the intervals of a ray share a point: their union is one interval
    one = latest_start[rays] <= earliest_end[rays]
    rounds = [(rays[one], low[rays[one]], high[rays[one]])]
    if not one.all():
        rounds += _unions(ray, lo, hi, rays[~one], size)
    return rounds


def _unions(ray, lo, hi, which, size):
    """The unions of the intervals of the rays `which`, in rounds of one
    piece of a ray each: [(rays, lo, hi), ...]."""
    picked = np.zeros(size, bool)
    picked[which] = True
    picked = picked[ray]
    ray, lo, hi = ray[picked], lo[picked], hi[picked]
    # the starts and the ends of the intervals of a ray, each sorted on
    # their own: the union has a gap where a start is after the end before
    starts = lo[np.lexsort((lo, ray))]
    ends = hi[np.lexsort((hi, ray))]
    ray = np.sort(ray)
    new_ray = np.ones(len(ray), bool)
    new_ray[1:] = ray[1:] != ray[:-1]
    new_piece = new_ray.copy()
    new_piece[1:] |= starts[1:] > ends[:-1]
    first = np.flatnonzero(new_piece)
    final = np.append(first[1:] - 1, len(ray) - 1)
    # the number of each piece on its ray
    head = new_ray[first]
    rank = np.arange(len(first)) - np.flatnonzero(head)[np.cumsum(head) - 1]
    return [(ray[first][rank == r], starts[first][rank == r], ends[final][rank == r])
            for r in range(int(rank.max()) + 1)]


def arc_points(axis, start, end, center, ccw, tolerance):
    """The points of an arc (or a helix) from `start` to `end` around
    `center`, turning counterclockwise when looking at the tip from the
    shank side of the tool axis when `ccw` (G3), else clockwise (G2). The
    same start and end on the plane make a full circle. The radius and the
    height along the tool axis go evenly from start to end."""
    k, sigma = tool_axis(axis)
    u, v = other_axes(k)
    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)
    center = np.asarray(center, dtype=float)

    def polar(point):
        x = point[u] - center[u]
        y = sigma * (point[v] - center[v])
        return math.hypot(x, y), math.atan2(y, x)

    r0, angle0 = polar(start)
    r1, angle1 = polar(end)
    turn = angle1 - angle0
    if ccw:
        turn %= 2.0 * math.pi
        if turn < 1e-12:
            turn = 2.0 * math.pi
    else:
        turn = -((-turn) % (2.0 * math.pi))
        if turn > -1e-12:
            turn = -2.0 * math.pi
    radius = max(r0, r1)
    if radius <= tolerance:
        return [start, end]
    step = 2.0 * math.acos(max(1.0 - tolerance / radius, -1.0))
    count = max(1, int(math.ceil(abs(turn) / step)))
    points = []
    for i in range(count + 1):
        f = i / count
        r = r0 + (r1 - r0) * f
        angle = angle0 + turn * f
        point = start + (end - start) * f
        point[u] = center[u] + r * math.cos(angle)
        point[v] = center[v] + sigma * r * math.sin(angle)
        points.append(point)
    points[0] = start
    points[-1] = end
    return points


def cut_arc(stock, tool, axis, start, end, center, ccw=True):
    """Cut what the tool sweeps along an arc or a helix (see arc_points).
    Returns the volume taken."""
    tolerance = CHORD * stock.spacing.min()
    points = arc_points(axis, start, end, center, ccw, tolerance)
    return cut_lines(stock, tool, axis, points[:-1], points[1:])
