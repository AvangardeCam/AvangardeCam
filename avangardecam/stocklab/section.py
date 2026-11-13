# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""Where the stock still has material at a level: outlines for Adaptive.

Seen along the tool axis, the area of a level is where the material
reaches the level or above it (toward the tool), optionally only up to a
height above it. The rays along the tool axis tell it for the middles of
their cells; between a middle with material and one without, the edge of
the material is somewhere in between. The conservative area (the default,
for Adaptive) puts the edge at the middle without material, so it never
leaves out material: a tool taking that area for air could go into
material at full width or at rapid. The other one puts it half way.

The outlines are closed loops in the plane's coordinates (u, v), the two
other axes in cyclic order after the tool axis (X: (Y, Z), Y: (Z, X),
Z: (X, Y)): counterclockwise around material, clockwise around a hole;
loops may touch at a corner, never cross. Kept apart (apart=True), they do
not touch either: where two squares with material meet at a corner only,
the two squares beside them take material too (more material, never
less), for a CAD kernel that takes no face whose loops touch.
"""

import numpy as np

from .cut import tool_axis
from .dexel import other_axes

# Material thinner than this part of the cell is the rounding of a floor
# cut at the level, not material.
THIN = 1e-6


def material_mask(stock, axis, level, height=None):
    """True on the rays along the tool axis with material between `level`
    and `height` above it toward the tool (None: up to the end of the
    stock). Shape: the grid of those rays (u, v)."""
    k, sigma = tool_axis(axis)
    if sigma > 0:
        low, high = level, np.inf if height is None else level + height
    else:
        low, high = -np.inf if height is None else level - height, level
    family = stock.rays[k]
    overlap = np.minimum(family.hi, high) - np.maximum(family.lo, low)
    return (overlap > THIN * stock.spacing.min()).any(axis=-1)


def area(stock, axis, level, height=None, conservative=True, apart=False):
    """The outlines of the material at `level` (see material_mask), as a
    list of arrays of (u, v) points, the first point not repeated; apart:
    no two of them touching at a corner (apart_mask)."""
    k, _ = tool_axis(axis)
    mask = material_mask(stock, axis, level, height)
    edges = []
    for other in other_axes(k):
        middles = stock.centers(other)
        if conservative:
            edges.append(np.concatenate(([stock.lower[other]], middles, [stock.upper[other]])))
        else:
            edges.append(stock.lower[other] + np.arange(stock.counts[other] + 1) * stock.spacing[other])
    if conservative:
        # a square between four middles holds material if one of them has it
        padded = np.pad(mask, 1)
        mask = padded[:-1, :-1] | padded[1:, :-1] | padded[:-1, 1:] | padded[1:, 1:]
    if apart:
        mask = apart_mask(mask)
    return outline(mask, edges[0], edges[1])


def apart_mask(mask):
    """The mask with material in every 2 x 2 squares where two of them on
    a diagonal have it and the other two not, until there is none such:
    then the outlines of no two pieces of material, no two holes and no
    hole and its material touch at a corner."""
    mask = np.array(mask, bool)
    while True:
        a, b = mask[:-1, :-1], mask[1:, :-1]
        c, d = mask[:-1, 1:], mask[1:, 1:]
        p, q = np.nonzero((a & d & ~b & ~c) | (b & c & ~a & ~d))
        if len(p) == 0:
            return mask
        for dp in (0, 1):
            for dq in (0, 1):
                mask[p + dp, q + dq] = True


def outline(mask, edges_u, edges_v):
    """The outlines of the True squares of `mask`; square (p, q) spans
    [edges_u[p], edges_u[p + 1]] x [edges_v[q], edges_v[q + 1]]."""
    full = np.pad(np.asarray(mask, bool), 1)
    inner = full[1:-1, 1:-1]
    # every side between a full and an empty square, material on its left,
    # as (start corner, end corner) on the lattice of corners
    p, q = np.nonzero(inner & ~full[1:-1, :-2])  # below empty: along +u
    sides = [np.stack((p, q, p + 1, q), axis=1)]
    p, q = np.nonzero(inner & ~full[2:, 1:-1])  # right empty: along +v
    sides.append(np.stack((p + 1, q, p + 1, q + 1), axis=1))
    p, q = np.nonzero(inner & ~full[1:-1, 2:])  # above empty: along -u
    sides.append(np.stack((p + 1, q + 1, p, q + 1), axis=1))
    p, q = np.nonzero(inner & ~full[:-2, 1:-1])  # left empty: along -v
    sides.append(np.stack((p, q + 1, p, q), axis=1))
    sides = np.concatenate(sides)

    leaving = {}
    for index, (p0, q0, _, _) in enumerate(sides.tolist()):
        leaving.setdefault((p0, q0), []).append(index)
    used = np.zeros(len(sides), bool)
    loops = []
    for first in range(len(sides)):
        if used[first]:
            continue
        corners = []
        index = first
        while not used[index]:
            used[index] = True
            p0, q0, p1, q1 = sides[index]
            corners.append((p0, q0))
            direction = (p1 - p0, q1 - q0)
            choices = [i for i in leaving[(p1, q1)] if not used[i]]
            if not choices:
                break
            if len(choices) > 1:
                # two squares touching at a corner only: turn left, round
                # the material on the left, so the loops only touch there
                choices.sort(key=lambda i: _turn(direction, sides[i]))
            index = choices[0]
        loops.append(_corners_to_points(corners, edges_u, edges_v))
    return loops


def _turn(direction, side):
    """0 for a left turn, 1 straight on, 2 right."""
    new = (side[2] - side[0], side[3] - side[1])
    cross = direction[0] * new[1] - direction[1] * new[0]
    if cross > 0:
        return 0
    return 1 if cross == 0 else 2


def _corners_to_points(corners, edges_u, edges_v):
    """Drop the corners in the middle of a straight run, then (u, v)."""
    corners = np.array(corners)
    before = np.roll(corners, 1, axis=0)
    after = np.roll(corners, -1, axis=0)
    a = corners - before
    b = after - corners
    keep = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0] != 0
    corners = corners[keep]
    return np.stack((edges_u[corners[:, 0]], edges_v[corners[:, 1]]), axis=1)


def signed_area(loop):
    """The area of a loop: positive counterclockwise."""
    u, v = loop[:, 0], loop[:, 1]
    return 0.5 * float(np.sum(u * np.roll(v, -1) - np.roll(u, -1) * v))


def contains(loops, points):
    """True for the points (an array of (u, v)) inside the outlines (even
    and odd crossings over all the loops)."""
    points = np.asarray(points, dtype=float)
    inside = np.zeros(len(points), bool)
    pu, pv = points[:, 0][:, None], points[:, 1][:, None]
    for loop in loops:
        u0, v0 = loop[:, 0][None, :], loop[:, 1][None, :]
        u1, v1 = np.roll(loop[:, 0], -1)[None, :], np.roll(loop[:, 1], -1)[None, :]
        crosses = (v0 > pv) != (v1 > pv)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = u0 + (pv - v0) * (u1 - u0) / (v1 - v0)
        inside ^= (crosses & (pu < at)).sum(axis=1) % 2 == 1
    return inside
