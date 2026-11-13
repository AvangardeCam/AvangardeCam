# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""What a convex tool part sweeps on each ray when its tip moves along a
straight line from A to B.

The tool axis is along axis k of the part, pointing from the tip to the
shank with sign sigma; t = sigma * x_k is the height along it, so the
tip is at t_A + s * dt for s in [0, 1]. The swept volume is convex, so a
ray meets it in one interval, the union over s of what the part at s
takes off the ray:

- rays along the tool axis: the part at s covers t from its tip plus
  bottom(rho(s)) up to its tip plus h1, rho(s) the distance of the ray
  from the tool axis;
- rays across it: the part at height h(s) of the ray is a disc of radius
  r(h(s)), so the ray loses its chord, center +- sqrt(r^2 - delta(s)^2),
  delta(s) the distance of the ray from the center in the plane.

Every ray can have its own move (the coordinates of A and B are numbers
or arrays of the rays' shape), so many moves are worked out at once.

The ends of the union are the least (or the most) of a function of s:
exact formulas for the moves across the tool axis (constant height) and
along it (plunge, retract). For the other moves (ramps, helices) the
part is taken piece by piece, each piece convex (what the pieces sweep
together is what the part sweeps): on a cone, a cylinder or a sphere the
function is gamma * s +- sqrt(a quadratic in s), which turns where a
quadratic equation says, so the least is at one of a few points worked
out exactly. A torus (the corner of a bull nose mill) has no such
formula: there the golden section search finds it.
"""

import numpy as np

from .tools import Arc, Line

# The golden section search halves its range about every 1.44 steps:
# 60 steps leave 3e-13 of it, below the rounding of a long move.
STEPS = 60
GOLDEN = (np.sqrt(5.0) - 1.0) / 2.0
TINY = 1e-12


def _minimum(f, lo, hi):
    """The minimum of convex f over [lo, hi], arrays of one shape: (s, f(s))."""
    lo = lo.copy()
    hi = hi.copy()
    x1 = hi - GOLDEN * (hi - lo)
    x2 = lo + GOLDEN * (hi - lo)
    f1 = f(x1)
    f2 = f(x2)
    for _ in range(STEPS):
        left = f1 <= f2  # the minimum is in [lo, x2], else in [x1, hi]
        hi = np.where(left, x2, hi)
        lo = np.where(left, lo, x1)
        new = np.where(left, hi - GOLDEN * (hi - lo), lo + GOLDEN * (hi - lo))
        f_new = f(new)
        x1, x2 = np.where(left, new, x2), np.where(left, x1, new)
        f1, f2 = np.where(left, f_new, f2), np.where(left, f1, f_new)
    s = (lo + hi) / 2.0
    candidates = (lo, s, hi)
    values = [f(c) for c in candidates]
    best = np.argmin(np.stack(values), axis=0)
    s = np.choose(best, candidates)
    return s, np.choose(best, values)


def _root(g, inside, outside):
    """The s between `inside` (g <= 0) and `outside` (g > 0) where g = 0,
    taken on the inside."""
    inside = inside.copy()
    outside = outside.copy()
    for _ in range(STEPS):
        mid = (inside + outside) / 2.0
        ok = g(mid) <= 0.0
        inside = np.where(ok, mid, inside)
        outside = np.where(ok, outside, mid)
    return inside


def _roots(a, b, c, tries=False):
    """Both roots of a s^2 + b s + c = 0 (also when a is about 0); NaN or
    inf where there are none. tries: points to try, so a double root that
    rounding made complex counts (and the vertex where there is none)."""
    disc = b * b - 4.0 * a * c
    root = np.sqrt(np.clip(disc, 0.0, None) if tries else disc)
    q = -0.5 * (b + np.copysign(root, b))
    return q / a, c / q


def _turning(a, b, c, gamma):
    """Where gamma * s +- sqrt(Q(s)), Q = a s^2 + b s + c, may be least or
    most: Q' = -+2 gamma sqrt(Q), squared."""
    d = a - gamma * gamma
    return _roots(4.0 * a * d, 4.0 * b * d, b * b - 4.0 * gamma * gamma * c, tries=True)


def _into(s, lo, hi):
    """The points s put into [lo, hi]; no point (NaN) as lo."""
    return np.clip(np.where(np.isnan(s), lo, s), lo, hi)


def _torus(part):
    return any(isinstance(piece, Arc) and piece.rc > 0.0 for piece in part.pieces)


def _flat(*arrays):
    """The arrays broadcast to one shape and flattened, and that shape."""
    arrays = np.broadcast_arrays(*(np.asarray(x, dtype=float) for x in arrays))
    return [x.ravel() for x in arrays], arrays[0].shape


def along(part, sigma, a, b, ray_u, ray_v):
    """Rays along the tool axis k, at (ray_u, ray_v) on the other two axes.

    a, b: the tip at the start and the end in the part's coordinates
    ordered as (k, u, v), numbers or arrays (a move for each ray).
    Returns (hit, lo, hi) along x_k.
    """
    (ak, au, av, bk, bu, bv, ray_u, ray_v), shape = _flat(*a, *b, ray_u, ray_v)
    with np.errstate(divide="ignore", invalid="ignore"):
        hit, lo, hi = _along(part, sigma, ak, au, av, bk, bu, bv, ray_u, ray_v)
    return hit.reshape(shape), lo.reshape(shape), hi.reshape(shape)


def _along(part, sigma, ak, au, av, bk, bu, bv, ray_u, ray_v):
    ta, dt = sigma * ak, sigma * (bk - ak)
    du = ray_u - au
    dv = ray_v - av
    wu, wv = bu - au, bv - av
    ww = wu * wu + wv * wv
    dd = du * du + dv * dv
    dw = du * wu + dv * wv
    rmax = part.rmax
    still = ww < TINY  # along the tool axis, or not moving
    ww_safe = np.where(still, 1.0, ww)
    disc = dw * dw - ww * (dd - rmax * rmax)
    root = np.sqrt(np.clip(disc, 0.0, None))
    first = (dw - root) / ww_safe
    last = (dw + root) / ww_safe
    hit = np.where(still, dd <= rmax * rmax, (disc >= 0.0) & (last >= 0.0) & (first <= 1.0))
    s0 = np.where(still, 0.0, np.clip(first, 0.0, 1.0))
    s1 = np.where(still, 1.0, np.clip(last, 0.0, 1.0))

    top = ta + np.maximum(s0 * dt, s1 * dt) + part.h1
    # still: the lowest tip; across the tool axis: the nearest place
    nearest = np.where(still, 0.0, np.clip(dw / ww_safe, s0, s1))
    rho = np.minimum(np.hypot(du - nearest * wu, dv - nearest * wv), rmax)
    bottom = ta + np.where(still, np.minimum(0.0, dt), 0.0) + part.bottom(rho)
    other = hit & ~still & (np.abs(dt) >= TINY)
    if other.any():
        o = other
        bottom[o] = ta[o] + _lowest(part, dt[o], du[o], dv[o], wu[o], wv[o], s0[o], s1[o])
    if sigma > 0:
        return hit, bottom, top
    return hit, -top, -bottom


def _lowest(part, dt, du, dv, wu, wv, s0, s1):
    """The least of f(s) = s * dt + bottom(rho(s)) over [s0, s1], rho(s) =
    |d - s w|: at an end, where rho crosses the radius at an end of a
    piece, or where the formula of a piece turns."""

    def f(s):
        return s * dt + part.bottom(np.minimum(np.hypot(du - s * wu, dv - s * wv), part.rmax))

    if _torus(part):
        return _minimum(f, s0, s1)[1]
    ww = wu * wu + wv * wv
    dw = du * wu + dv * wv
    dd = du * du + dv * dv
    points = [s1]
    for piece in part.pieces:
        if piece.r1 <= piece.r0:
            continue  # a cylinder: the bottom is below it
        for r in (piece.r0, piece.r1):
            points += _roots(ww, -2.0 * dw, dd - r * r, tries=True)  # rho(s) = r
        if isinstance(piece, Line):  # h0 + (rho - r0) / slope
            points += _turning(ww, -2.0 * dw, dd, dt * piece.slope)
        else:  # a sphere: hc - sqrt(q^2 - rho^2)
            points += _turning(-ww, 2.0 * dw, piece.q * piece.q - dd, dt)
    best = f(s0)
    for s in points:
        best = np.minimum(best, f(_into(s, s0, s1)))
    return best


def across(part, sigma, a, b, ray_k, ray_j):
    """Rays along an axis `a` across the tool axis k, at x_k = ray_k and at
    x_j = ray_j on the third axis j.

    a, b: the tip at the start and the end ordered as (a, k, j), numbers
    or arrays (a move for each ray). Returns (hit, lo, hi) along the
    ray's axis.
    """
    (aa, ak, aj, ba, bk, bj, ray_k, ray_j), shape = _flat(*a, *b, ray_k, ray_j)
    with np.errstate(divide="ignore", invalid="ignore"):
        hit, lo, hi = _across(part, sigma, aa, ak, aj, ba, bk, bj, ray_k, ray_j)
    return hit.reshape(shape), lo.reshape(shape), hi.reshape(shape)


def _across(part, sigma, aa, ak, aj, ba, bk, bj, ray_k, ray_j):
    ta, dt = sigma * ak, sigma * (bk - ak)
    pa, va = aa, ba - aa
    delta0 = ray_j - aj
    vj = bj - aj
    height0 = sigma * ray_k - ta  # h(s) = height0 - s * dt
    hit = np.zeros(pa.shape, bool)
    lo = np.full(pa.shape, np.inf)
    hi = np.full(pa.shape, -np.inf)
    level = np.abs(dt) < TINY
    axial = ~level & (np.abs(va) < TINY) & (np.abs(vj) < TINY)
    for which, how in ((level, _across_level), (axial, _across_axial), (~level & ~axial, _across_other)):
        if which.all():
            return how(part, pa, va, delta0, vj, height0, dt)
        if which.any():
            w = which
            hit[w], lo[w], hi[w] = how(part, pa[w], va[w], delta0[w], vj[w], height0[w], dt[w])
    return hit, lo, hi


def _across_level(part, pa, va, delta0, vj, height0, dt):
    """Across the tool axis: one disc, moved along a line in the plane."""
    inside = (height0 >= part.h0) & (height0 <= part.h1)
    r = part.radius(np.clip(height0, part.h0, part.h1))
    sideways = np.abs(vj) >= TINY
    if sideways.all():
        hit, lo, hi = _sideways(pa, va, delta0, vj, r)
        return hit & inside, lo, hi
    # along the ray only (or not moving)
    half = np.sqrt(np.clip(r * r - delta0 * delta0, 0.0, None))
    hit = np.abs(delta0) <= r
    lo = pa + np.minimum(0.0, va) - half
    hi = pa + np.maximum(0.0, va) + half
    if sideways.any():
        w = sideways
        hit[w], lo[w], hi[w] = _sideways(pa[w], va[w], delta0[w], vj[w], r[w])
    return hit & inside, lo, hi


def _sideways(pa, va, delta0, vj, r):
    """A disc of radius r moved across the ray too (vj not 0): it meets
    the ray for s in [s0, s1]; the ends of the chords turn back where
    delta is r * va / speed."""
    inverse = 1.0 / vj
    t1 = (delta0 - r) * inverse
    t2 = (delta0 + r) * inverse
    s0 = np.clip(np.minimum(t1, t2), 0.0, 1.0)
    s1 = np.clip(np.maximum(t1, t2), 0.0, 1.0)
    hit = (np.maximum(t1, t2) >= 0.0) & (np.minimum(t1, t2) <= 1.0)
    side = r * va * np.sign(vj) / np.hypot(va, vj)

    def end(s, sign):
        d = delta0 - s * vj
        return pa + s * va + sign * np.sqrt(np.clip(r * r - d * d, 0.0, None))

    lo = end(np.clip((delta0 - side) * inverse, s0, s1), -1.0)
    hi = end(np.clip((delta0 + side) * inverse, s0, s1), 1.0)
    return hit, lo, hi


def _heights(part, height0, dt):
    """The s where the ray's height h(s) is on the part: [sa, sb], and
    whether there are any."""
    sa = np.clip(np.minimum((height0 - part.h0) / dt, (height0 - part.h1) / dt), 0.0, 1.0)
    sb = np.clip(np.maximum((height0 - part.h0) / dt, (height0 - part.h1) / dt), 0.0, 1.0)
    in_range = (sa < sb) | (
        (sa == sb) & (height0 - sa * dt >= part.h0 - 1e-9) & (height0 - sa * dt <= part.h1 + 1e-9)
    )
    return sa, sb, in_range


def _across_axial(part, pa, va, delta0, vj, height0, dt):
    """Along the tool axis: the widest disc of the heights passed."""
    sa, sb, in_range = _heights(part, height0, dt)

    def radius(s):
        return part.radius(np.clip(height0 - s * dt, part.h0, part.h1))

    r = np.maximum(radius(sa), radius(sb))
    half = np.sqrt(np.clip(r * r - delta0 * delta0, 0.0, None))
    hit = in_range & (np.abs(delta0) <= r)
    return hit, pa - half, pa + half


def _across_other(part, pa, va, delta0, vj, height0, dt):
    """Ramps and helices: piece by piece (see the module)."""
    if _torus(part):
        return _across_search(part, pa, va, delta0, vj, height0, dt)
    hit = np.zeros(pa.shape, bool)
    lo = np.full(pa.shape, np.inf)
    hi = np.full(pa.shape, -np.inf)
    for piece in part.pieces:
        # the s where the ray's height is on the piece
        s_top = (height0 - piece.h1) / dt
        s_bottom = (height0 - piece.h0) / dt
        first = np.maximum(np.minimum(s_top, s_bottom), 0.0)
        last = np.minimum(np.maximum(s_top, s_bottom), 1.0)
        if isinstance(piece, Line):
            # rho(s) = e0 + e1 s; the ray meets the disc where rho -+ delta >= 0
            e0 = piece.r0 + piece.slope * (height0 - piece.h0)
            e1 = -piece.slope * dt
            first, last = _at_least(e0 - delta0, e1 + vj, first, last)
            first, last = _at_least(e0 + delta0, e1 - vj, first, last)
            qa = e1 * e1 - vj * vj
            qb = 2.0 * (e0 * e1 + delta0 * vj)
            qc = e0 * e0 - delta0 * delta0
        else:
            # a sphere: rho^2 = q^2 - eta(s)^2, eta = height - hc
            eta0 = height0 - piece.hc
            qa = -(dt * dt + vj * vj)
            qb = 2.0 * (eta0 * dt + delta0 * vj)
            qc = piece.q * piece.q - eta0 * eta0 - delta0 * delta0
            r1, r2 = _roots(qa, qb, qc)
            first = np.maximum(first, np.minimum(r1, r2))
            last = np.minimum(last, np.maximum(r1, r2))
        # the chord is sqrt(Q(s)), Q = qa s^2 + qb s + qc, on [first, last]
        ok = first <= last
        piece_lo = np.full(pa.shape, np.inf)
        piece_hi = np.full(pa.shape, -np.inf)
        for s in (first, last, *_turning(qa, qb, qc, va)):
            s = _into(s, first, last)
            chord = np.sqrt(np.clip((qa * s + qb) * s + qc, 0.0, None))
            piece_lo = np.minimum(piece_lo, pa + s * va - chord)
            piece_hi = np.maximum(piece_hi, pa + s * va + chord)
        hit |= ok
        lo = np.where(ok, np.minimum(lo, piece_lo), lo)
        hi = np.where(ok, np.maximum(hi, piece_hi), hi)
    return hit, lo, hi


def _at_least(alpha, beta, first, last):
    """[first, last] cut to where alpha + beta * s >= 0."""
    bound = -alpha / beta
    first = np.where(beta > 0.0, np.maximum(first, bound), first)
    last = np.where(beta < 0.0, np.minimum(last, bound), last)
    return first, np.where((beta == 0.0) & (alpha < 0.0), -np.inf, last)


def _across_search(part, pa, va, delta0, vj, height0, dt):
    """Ramps and helices by the golden section search: the ends of the
    union are the least of a convex function of s."""
    sa, sb, in_range = _heights(part, height0, dt)

    def radius(s):
        return part.radius(np.clip(height0 - s * dt, part.h0, part.h1))

    def delta(s):
        return delta0 - s * vj

    def gap(s):  # convex; <= 0 where the ray meets the disc at s
        return np.abs(delta(s)) - radius(s)

    s_mid, g_mid = _minimum(gap, sa, sb)
    hit = in_range & (g_mid <= 0.0)
    s0 = np.where(gap(sa) <= 0.0, sa, _root(gap, s_mid, sa))
    s1 = np.where(gap(sb) <= 0.0, sb, _root(gap, s_mid, sb))

    def chord(s):
        r = radius(s)
        d = delta(s)
        return np.sqrt(np.clip(r * r - d * d, 0.0, None))

    _, lo = _minimum(lambda s: pa + s * va - chord(s), s0, s1)
    _, minus_hi = _minimum(lambda s: -(pa + s * va + chord(s)), s0, s1)
    return hit, lo, -minus_hi
