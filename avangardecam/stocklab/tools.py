# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""The tool: a solid of revolution around its axis, measured from its tip.

A tool is a union of convex parts on one axis (the cutting part, later a
neck or a shank), because a convex part moved along a straight line sweeps
a convex volume, which takes at most one interval off each ray. A part is
its profile r(h) on [h0, h1] (h: height above the tip), made of pieces:
lines (a cone, or a cylinder when the slope is 0) and arcs (a sphere or a
torus: the rising lower quarter of a circle in the (r, h) half-plane).
The profile of a part goes up and bends down (concave, never decreasing),
so its inverse, bottom(rho), the lowest h where the part is rho wide, is
convex and never decreasing.
"""

import math

import numpy as np


class Line:
    """r = r0 + slope * (h - h0) on [h0, h1]."""

    def __init__(self, h0, h1, r0, slope=0.0):
        self.h0, self.h1, self.r0, self.slope = h0, h1, r0, slope
        self.r1 = r0 + slope * (h1 - h0)

    def radius(self, h):
        return self.r0 + self.slope * (h - self.h0)

    def height(self, rho):
        if self.slope == 0.0:
            return np.full_like(rho, self.h0)
        return self.h0 + (rho - self.r0) / self.slope

    def support(self, nr, na):
        """The furthest r * nr + h * na of the piece: at an end."""
        return np.maximum(self.r0 * nr + self.h0 * na, self.r1 * nr + self.h1 * na)


class Arc:
    """r = rc + sqrt(q^2 - (h - hc)^2) on [h0, h1], h1 <= hc: the rising
    lower quarter of a circle of radius q around (rc, hc)."""

    def __init__(self, h0, h1, rc, hc, q):
        self.h0, self.h1, self.rc, self.hc, self.q = h0, h1, rc, hc, q
        self.r0 = self.radius(h0)
        self.r1 = self.radius(h1)

    def radius(self, h):
        return self.rc + np.sqrt(np.clip(self.q**2 - (h - self.hc) ** 2, 0.0, None))

    def height(self, rho):
        return self.hc - np.sqrt(np.clip(self.q**2 - (rho - self.rc) ** 2, 0.0, None))

    def support(self, nr, na):
        """The furthest r * nr + h * na of the piece (nr^2 + na^2 = 1): at
        an end, or where the circle faces (nr, na) if that is on the piece."""
        ends = np.maximum(self.r0 * nr + self.h0 * na, self.r1 * nr + self.h1 * na)
        h = self.hc + self.q * na
        on = (h >= self.h0) & (h <= self.h1)
        return np.where(on, np.maximum(ends, self.rc * nr + self.hc * na + self.q), ends)


class Part:
    """A convex part of the tool: pieces one above the other from h0 to h1."""

    def __init__(self, pieces):
        self.pieces = list(pieces)
        for below, above in zip(self.pieces, self.pieces[1:]):
            if not math.isclose(below.h1, above.h0, abs_tol=1e-12):
                raise ValueError("the pieces of a tool part must follow each other")
            if above.r0 < below.r1 - 1e-9:
                raise ValueError("a tool part may not get narrower upwards")
        self.h0 = self.pieces[0].h0
        self.h1 = self.pieces[-1].h1
        self.rmin = self.pieces[0].r0
        self.rmax = self.pieces[-1].r1

    def radius(self, h):
        """The radius at height h, which must be in [h0, h1]."""
        h = np.asarray(h, dtype=float)
        result = self.pieces[0].radius(h)
        for piece in self.pieces[1:]:
            result = np.where(h >= piece.h0, piece.radius(h), result)
        return result

    def support(self, nr, na):
        """The support function of the part, tip at 0: the furthest
        r * nr + h * na over its profile (nr >= 0 across the axis, na along
        it, nr^2 + na^2 = 1)."""
        result = self.pieces[0].support(nr, na)
        for piece in self.pieces[1:]:
            result = np.maximum(result, piece.support(nr, na))
        return result

    def bottom(self, rho):
        """The lowest height where the part is rho wide, rho in [0, rmax]."""
        rho = np.asarray(rho, dtype=float)
        result = np.full_like(rho, self.h0)
        for piece in self.pieces:
            if piece.r1 > piece.r0:
                inside = rho > piece.r0
                result = np.where(inside, piece.height(np.minimum(rho, piece.r1)), result)
        return result


class Tool:
    """A tool: its convex parts and its largest radius."""

    def __init__(self, parts, name=""):
        self.parts = list(parts)
        self.name = name
        self.radius = max(part.rmax for part in self.parts)
        self.length = max(part.h1 for part in self.parts)


def _check(diameter, length, tip):
    if diameter <= 0:
        raise ValueError("the diameter must be more than 0")
    if length < tip:
        raise ValueError("the tool must be at least as long as its tip")


def flat_end_mill(diameter, length):
    _check(diameter, length, 0.0)
    return Tool([Part([Line(0.0, length, diameter / 2.0)])], "flat end mill")


def ball_end_mill(diameter, length):
    r = diameter / 2.0
    _check(diameter, length, r)
    pieces = [Arc(0.0, r, 0.0, r, r)]
    if length > r:
        pieces.append(Line(r, length, r))
    return Tool([Part(pieces)], "ball end mill")


def bull_nose_mill(diameter, corner_radius, length):
    r = diameter / 2.0
    if not 0.0 < corner_radius <= r:
        raise ValueError("the corner radius must be more than 0 and at most the radius")
    _check(diameter, length, corner_radius)
    pieces = [Arc(0.0, corner_radius, r - corner_radius, corner_radius, corner_radius)]
    if length > corner_radius:
        pieces.append(Line(corner_radius, length, r))
    return Tool([Part(pieces)], "bull nose mill")


def drill(diameter, tip_angle, length):
    """A drill with its point of `tip_angle` degrees (118 for most)."""
    return chamfer_mill(diameter, tip_angle, length, tip_diameter=0.0, name="drill")


def chamfer_mill(diameter, angle, length, tip_diameter=0.0, name="chamfer mill"):
    """A cone of `angle` degrees (full angle) from `tip_diameter` up to
    `diameter`, then a cylinder."""
    if not 0.0 < angle < 180.0:
        raise ValueError("the angle must be between 0 and 180 degrees")
    if not 0.0 <= tip_diameter < diameter:
        raise ValueError("the tip must be narrower than the tool")
    slope = math.tan(math.radians(angle) / 2.0)
    tip = (diameter - tip_diameter) / 2.0 / slope
    _check(diameter, length, tip)
    pieces = [Line(0.0, tip, tip_diameter / 2.0, slope)]
    if length > tip:
        pieces.append(Line(tip, length, diameter / 2.0))
    return Tool([Part(pieces)], name)
