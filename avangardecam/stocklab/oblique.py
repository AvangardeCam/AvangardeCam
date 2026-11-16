# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""Cutting with a tool whose axis goes along none of the stock's axes (a
tilted working plane, a turning head), on its own: cut.cut_lines and
cut.arc_points hand such an axis over to here.

The tool axis is a unit vector d from the tip to the shank, in the stock's
frame. A convex part of the tool is taken as cones one above the other
(a cylinder is one, the arc of a ball or a bull nose a few chords, which
leave less than ARC_CHORDS says of its radius): what the cones sweep
together is what the part sweeps. In a stock the chords are as few as its
cells can tell and a tall cone is cut in pieces (cones): less to work out.

A cone h0 <= h <= h1, rho <= r0 + m (h - h0) (h along d from the tip, rho
from the axis) whose tip goes straight from A to B takes one interval off
a ray. With t along the ray and s in [0, 1] along the move, the point t
of the ray seen from the tip at s is P + t e - s V (e the ray's axis,
V = B - A); it is in the cone where

    F(t, s) = rho^2 - r(h)^2 <= 0   (a quadratic in t and s),
    h0 <= h(t, s) <= h1             (h linear in t and s),
    0 <= s <= 1,

a convex region of the (t, s) plane. Its least and its most t are at one
of a few points, all worked out exactly (interval): where the conic
F = 0 turns back in t, where it meets one of the four lines, where two
of the lines meet.

Plain numpy, as the rest of the stock model.
"""

import math

import numpy as np

from .dexel import other_axes
from .tools import Line

# a tool axis this close to one of the stock's axes is along it (cut.py)
ALONG = 1e-9
# an arc of a tool's profile as this many chords (a quarter circle of
# radius q stands in by 0.002 q at most)
ARC_CHORDS = 12
# in a stock an arc's chords may also leave this much of a cell (fewer
# chords: each is cut on its own)
CHORD_CELLS = 0.05
# in a stock a cone is cut in pieces no taller than its diameter, or than
# this many cells: a piece in the air costs next to nothing, a whole tall
# tool has every ray under it worked out at each move
PIECE_CELLS = 4.0
# about this many pairs of a ray and a move are worked out at once
PAIRS = 20_000

_AXES = {"X": 0, "Y": 1, "Z": 2}
_H_SLACK = 1e-7  # mm, a point this little over the cone's ends is on it
_S_SLACK = 1e-9


def unit(axis):
    """The unit vector of a tool axis: "+Z", "-X", ... or a vector."""
    if isinstance(axis, str):
        name = axis.strip().upper()
        sigma = -1.0 if name.startswith("-") else 1.0
        name = name.lstrip("+-")
        if name not in _AXES:
            raise ValueError("the tool axis must be X, Y or Z, with + or -")
        vector = np.zeros(3)
        vector[_AXES[name]] = sigma
        return vector
    vector = np.asarray(axis, dtype=float).reshape(3)
    length = float(np.linalg.norm(vector))
    if length == 0.0:
        raise ValueError("the tool axis has no length")
    return vector / length


def direction(axis):
    """The unit vector of a tool axis that goes along none of the stock's
    axes, None for one that does ("+Z", (0, -1, 0))."""
    if isinstance(axis, str):
        return None
    vector = unit(axis)
    k = int(np.argmax(np.abs(vector)))
    if float(np.linalg.norm(np.delete(vector, k))) <= ALONG:
        return None
    return vector


def basis(d):
    """Two unit vectors (p, q) across d with p x q = d: seen from the shank
    side p turns to q counterclockwise."""
    d = np.asarray(d, dtype=float)
    other = np.array((1.0, 0.0, 0.0)) if abs(d[0]) < 0.9 else np.array((0.0, 1.0, 0.0))
    p = np.cross(other, d)
    p /= np.linalg.norm(p)
    return p, np.cross(d, p)


def arc_points(d, start, end, center, ccw, tolerance):
    """cut.arc_points round the axis d through `center` (any point of it)."""
    p, q = basis(d)
    start = np.asarray(start, dtype=float)
    end = np.asarray(end, dtype=float)
    center = np.asarray(center, dtype=float)

    def polar(point):
        rel = point - center
        x, y = float(rel @ p), float(rel @ q)
        return math.hypot(x, y), math.atan2(y, x), float(rel @ d)

    r0, angle0, h0 = polar(start)
    r1, angle1, h1 = polar(end)
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
        points.append(center + d * (h0 + (h1 - h0) * f) + r * (math.cos(angle) * p + math.sin(angle) * q))
    points[0] = start
    points[-1] = end
    return points


def cones(part, cell=None):
    """A tool part as cones one above the other: (h0, h1, r0, slope).
    For a stock of cells of `cell` mm: an arc in no more chords than the
    cells can tell, a tall cone in pieces (CHORD_CELLS, PIECE_CELLS)."""
    result = []
    for h0, h1, r0, slope in _cones(part, None if cell is None else CHORD_CELLS * cell):
        count = 1
        if cell is not None:
            tall = max(2.0 * max(r0, r0 + slope * (h1 - h0)), PIECE_CELLS * cell)
            count = max(1, int(math.ceil((h1 - h0) / tall - 1e-9)))
        step = (h1 - h0) / count
        for i in range(count):
            top = h1 if i + 1 == count else h0 + (i + 1) * step
            result.append((h0 + i * step, top, r0 + slope * i * step, slope))
    return result


def _cones(part, sag):
    """cones, an arc's chords leaving sag (mm) of it at most; None: as
    ARC_CHORDS says."""
    result = []
    for piece in part.pieces:
        if isinstance(piece, Line):
            if piece.h1 > piece.h0:
                result.append((piece.h0, piece.h1, piece.r0, piece.slope))
            continue
        # h = hc - q cos(phi), r = rc + q sin(phi)
        phi0 = math.acos(min(max((piece.hc - piece.h0) / piece.q, -1.0), 1.0))
        phi1 = math.acos(min(max((piece.hc - piece.h1) / piece.q, -1.0), 1.0))
        count = max(1, int(math.ceil(ARC_CHORDS * abs(phi1 - phi0) / (math.pi / 2.0))))
        if sag is not None:
            chord = math.pi if sag >= piece.q else 2.0 * math.acos(1.0 - sag / piece.q)
            count = min(count, max(1, int(math.ceil(abs(phi1 - phi0) / chord - 1e-9))))
        h = [piece.hc - piece.q * math.cos(phi0 + (phi1 - phi0) * i / count) for i in range(count + 1)]
        r = [piece.rc + piece.q * math.sin(phi0 + (phi1 - phi0) * i / count) for i in range(count + 1)]
        h[0], h[-1] = piece.h0, piece.h1
        for i in range(count):
            if h[i + 1] - h[i] > 1e-12:
                result.append((h[i], h[i + 1], r[i], (r[i + 1] - r[i]) / (h[i + 1] - h[i])))
    return result


def swept_box(cone, d, starts, ends):
    """The box around what a cone sweeps from starts[i] to ends[i]
    (arrays (n, 3)): (low, high)."""
    h0, h1, r0, slope = cone
    across = np.sqrt(np.clip(1.0 - d * d, 0.0, None))  # how far a disc across d reaches along each axis
    low = np.full(starts.shape, np.inf)
    high = np.full(starts.shape, -np.inf)
    for tip in (starts, ends):
        for h, r in ((h0, r0), (h1, r0 + slope * (h1 - h0))):
            centre = tip + h * d
            low = np.minimum(low, centre - r * across)
            high = np.maximum(high, centre + r * across)
    return low, high


def _roots(a, b, c):
    """The two roots of a x^2 + 2 b x + c = 0 (arrays), nan where there
    is none; the one that stays when a is nothing second."""
    with np.errstate(divide="ignore", invalid="ignore"):
        disc = b * b - a * c
        root = np.sqrt(np.where(disc >= 0.0, disc, np.nan))
        q = -(b + np.where(b < 0.0, -root, root))
        return q / a, c / q


def interval(cone, d, a, starts, ends, ray_u, ray_v):
    """What the cone takes off rays along axis `a` of the stock, each ray
    with its own move: starts, ends (n, 3) the tip's, ray_u, ray_v (n,)
    where the ray stands on the two other axes. Returns (hit, lo, hi)."""
    h0, h1, r0, m = cone
    u, v = other_axes(a)
    alpha = float(d[a])
    move = ends - starts
    beta = move @ d
    # the ray's point beside the start, seen from the start (t from there)
    rel = np.zeros_like(starts)
    rel[:, u] = ray_u - starts[:, u]
    rel[:, v] = ray_v - starts[:, v]
    c0 = rel @ d
    radius0 = r0 + m * (c0 - h0)
    mm = m * m
    move2 = np.einsum("ij,ij->i", move, move)
    rel2 = np.einsum("ij,ij->i", rel, rel)
    att = (1.0 - alpha * alpha) - mm * alpha * alpha
    ass = (move2 - beta * beta) - mm * beta * beta
    ats = -(move[:, a] - alpha * beta) + mm * alpha * beta
    bt = -alpha * c0 - radius0 * m * alpha
    bs = -(np.einsum("ij,ij->i", rel, move) - c0 * beta) + radius0 * m * beta
    c = (rel2 - c0 * c0) - radius0 * radius0
    n = len(starts)
    att = np.full(n, att)
    t, s = [], []
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        # where the conic turns back in t
        turning = ass > 1e-12 * (move2 + 1e-30)
        safe = np.where(turning, ass, np.nan)
        for root in _roots(att - ats * ats / safe, bt - ats * bs / safe, c - bs * bs / safe):
            t.append(root)
            s.append(-(ats * root + bs) / safe)
        # the conic on the lines s = 0 and s = 1
        for root in _roots(att, bt, c):
            t.append(root)
            s.append(np.zeros(n))
        for root in _roots(att, bt + ats, c + ass + 2.0 * bs):
            t.append(root)
            s.append(np.ones(n))
        # the conic on the lines h = h0 and h = h1: from a point of the
        # line along (beta, alpha)
        along2 = alpha * alpha + beta * beta
        for h in (h0, h1):
            pt = (h - c0) * alpha / along2
            ps = -(h - c0) * beta / along2
            qa = att * beta * beta + 2.0 * ats * beta * alpha + ass * alpha * alpha
            qb = att * pt * beta + ats * (pt * alpha + ps * beta) + ass * ps * alpha + bt * beta + bs * alpha
            qc = att * pt * pt + ass * ps * ps + 2.0 * ats * pt * ps + 2.0 * bt * pt + 2.0 * bs * ps + c
            for root in _roots(qa, qb, qc):
                t.append(pt + root * beta)
                s.append(ps + root * alpha)
            # where the line meets s = 0 and s = 1
            t.append((h - c0) / alpha)
            s.append(np.zeros(n))
            t.append((h - c0 + beta) / alpha)
            s.append(np.ones(n))
        t = np.stack(t)
        s = np.stack(s)
        height = c0 + alpha * t - beta * s
        f = att * t * t + ass * s * s + 2.0 * ats * t * s + 2.0 * bt * t + 2.0 * bs * s + c
        slack = 1e-9 * (move2 + rel2 + radius0 * radius0 + 1.0)
        valid = np.isfinite(t) & np.isfinite(s)
        valid &= (s >= -_S_SLACK) & (s <= 1.0 + _S_SLACK)
        valid &= (height >= h0 - _H_SLACK) & (height <= h1 + _H_SLACK)
        valid &= f <= slack
    lo = np.where(valid, t, np.inf).min(axis=0)
    hi = np.where(valid, t, -np.inf).max(axis=0)
    hit = hi > lo
    return hit, lo + starts[:, a], hi + starts[:, a]


def _near(a, cone, d, starts, ends, ray_u, ray_v):
    """Whether each ray along `a` goes near enough to its move for the
    cone to reach it: within the cone's reach of the line its middle
    goes along (as the ray sees them: a point and a line)."""
    h0, h1, r0, slope = cone
    u, v = other_axes(a)
    middle = (h0 + h1) / 2.0
    reach = math.hypot(max(r0, r0 + slope * (h1 - h0)), (h1 - h0) / 2.0)
    au = starts[:, u] + middle * d[u]
    av = starts[:, v] + middle * d[v]
    du = ends[:, u] - starts[:, u]
    dv = ends[:, v] - starts[:, v]
    pu = ray_u - au
    pv = ray_v - av
    length2 = du * du + dv * dv
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(length2 > 0.0, np.clip((pu * du + pv * dv) / length2, 0.0, 1.0), 0.0)
    gu = pu - share * du
    gv = pv - share * dv
    return gu * gu + gv * gv <= reach * reach


def _pairs(stock, a, low, high, first, last):
    """Each move with the rays along `a` in its box (first, last:
    Stock.blocks; low, high: the box along `a`) that have material where
    it goes: (move, iu, iv), or None."""
    family = stock.rays[a]
    corner = first.min(axis=0)
    width = int(last[:, 1].max() - corner[1]) + 1
    box = tuple(slice(c, e + 1) for c, e in zip(corner, last.max(axis=0)))
    lo_box = family.lo[box]
    hi_box = family.hi[box]
    candidates = np.flatnonzero(np.any((lo_box < high.max()) & (hi_box > low.min()), axis=-1))
    if candidates.size == 0:
        return None
    first = first - corner
    last = last - corner
    rows = last[:, 0] - first[:, 0] + 1
    move = np.repeat(np.arange(len(rows)), rows)
    row = first[move, 0] + np.arange(rows.sum()) - np.repeat(np.cumsum(rows) - rows, rows)
    begin = np.searchsorted(candidates, row * width + first[move, 1], "left")
    count = np.searchsorted(candidates, row * width + last[move, 1], "right") - begin
    move = np.repeat(move, count)
    ray = candidates[np.arange(count.sum()) - np.repeat(np.cumsum(count) - count, count) + np.repeat(begin, count)]
    keep = (lo_box[..., 0].ravel()[ray] < high[move]) & (hi_box.max(axis=-1).ravel()[ray] > low[move])
    move, ray = move[keep], ray[keep]
    if move.size == 0:
        return None
    return move, ray // width + corner[0], ray % width + corner[1]


def _hits(stock, cone, d, a, starts, ends):
    """What the cone takes off the rays along `a` on each of the moves, a
    few moves at a time: (moves, iu, iv, lo, hi) of the rays hit."""
    low, high = swept_box(cone, d, starts, ends)
    first, last = stock.blocks(a, low, high)
    count = np.prod(np.clip(last - first + 1, 0, None), axis=1)
    moves = np.flatnonzero(count)
    if moves.size == 0:
        return
    u, v = other_axes(a)
    chunk = (np.cumsum(count[moves]) - count[moves]) // PAIRS
    for some in np.split(moves, np.flatnonzero(np.diff(chunk)) + 1):
        found = _pairs(stock, a, low[some, a], high[some, a], first[some], last[some])
        if found is None:
            continue
        move, iu, iv = found
        move = some[move]
        ray_u, ray_v = stock.centers(u)[iu], stock.centers(v)[iv]
        near = _near(a, cone, d, starts[move], ends[move], ray_u, ray_v)
        move, iu, iv, ray_u, ray_v = move[near], iu[near], iv[near], ray_u[near], ray_v[near]
        if move.size == 0:
            continue
        hit, lo, hi = interval(cone, d, a, starts[move], ends[move], ray_u, ray_v)
        if hit.any():
            yield move[hit], iu[hit], iv[hit], lo[hit], hi[hit]


def cut_lines(stock, tool, d, starts, ends):
    """cut.cut_lines with the tool axis d (a unit vector, any way)."""
    from .cut import _take

    starts = np.asarray(starts, dtype=float).reshape(-1, 3)
    ends = np.asarray(ends, dtype=float).reshape(-1, 3)
    d = np.asarray(d, dtype=float)
    taken = 0.0
    cell = float(stock.spacing.min())
    for part in tool.parts:
        for cone in cones(part, cell):
            for a in range(3):
                for _move, iu, iv, lo, hi in _hits(stock, cone, d, a, starts, ends):
                    taken += _take(stock, a, iu, iv, lo, hi)
    return taken / 3.0


def would_take(stock, tool, axis, starts, ends):
    """How much material each move from starts[i] to ends[i] would take
    of the stock as it is (mm3, nothing is cut), as the rays most across
    the tool axis see it; the pieces of a tool counted one by one (never
    less than it takes). What it misses is less than a cell, between the
    rays."""
    d = unit(axis)
    starts = np.asarray(starts, dtype=float).reshape(-1, 3)
    ends = np.asarray(ends, dtype=float).reshape(-1, 3)
    a = int(np.argmin(np.abs(d)))
    u, v = other_axes(a)
    area = float(stock.spacing[u] * stock.spacing[v])
    family = stock.rays[a]
    result = np.zeros(len(starts))
    cell = float(stock.spacing.min())
    for part in tool.parts:
        for cone in cones(part, cell):
            for move, iu, iv, lo, hi in _hits(stock, cone, d, a, starts, ends):
                there = np.minimum(family.hi[iu, iv], hi[:, None]) - np.maximum(family.lo[iu, iv], lo[:, None])
                np.add.at(result, move, np.clip(there, 0.0, None).sum(axis=1) * area)
    return result
