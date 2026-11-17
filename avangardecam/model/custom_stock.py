# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""A custom stock (CAM > Custom stock, user 2026-11-17): a model of the
blank from a file (a casting, a sawn or pre-machined block), put with the
middle of its box on the middle of the part's box. The file may draw the
blank anywhere (the foundry's or the saw's zero point): the middle is the
easiest thing to match without asking the user to place it.

Plain Python, no FreeCAD: boxes are model.stock.Bounds in the setup's
coordinates.
"""

from typing import NamedTuple

# a model sticking out of the blank by less than this is no sticking out
# (rounding of the boxes, a file written with a coarse tolerance)
TOLERANCE_MM = 0.01


def middle(bounds):
    """The middle of a box: (x, y, z)."""
    return (
        (bounds.x_min + bounds.x_max) / 2.0,
        (bounds.y_min + bounds.y_max) / 2.0,
        (bounds.z_min + bounds.z_max) / 2.0,
    )


def centre_shift(blank, model):
    """How far the blank (its box) moves to have its middle on the
    model's middle: (dx, dy, dz)."""
    return tuple(m - b for m, b in zip(middle(model), middle(blank)))


def moved(bounds, shift):
    """The box moved by shift (dx, dy, dz)."""
    dx, dy, dz = shift
    return type(bounds)(
        bounds.x_min + dx, bounds.y_min + dy, bounds.z_min + dz,
        bounds.x_max + dx, bounds.y_max + dy, bounds.z_max + dz,
    )  # fmt: skip


class SticksOut(NamedTuple):
    side: str  # "X−", "X+", "Y−", "Y+", "Z−" (bottom), "Z+" (top)
    mm: float


def sticking_out(blank, model, tolerance=TOLERANCE_MM):
    """Where the model's box reaches past the blank's box (SticksOut,
    largest first): the blank is smaller than the part there, or turned
    the other way. Only the boxes: a casting with a pocket where the part
    is solid is not found."""
    out = [
        SticksOut("X−", blank.x_min - model.x_min),
        SticksOut("X+", model.x_max - blank.x_max),
        SticksOut("Y−", blank.y_min - model.y_min),
        SticksOut("Y+", model.y_max - blank.y_max),
        SticksOut("Z−", blank.z_min - model.z_min),
        SticksOut("Z+", model.z_max - blank.z_max),
    ]
    return sorted((s for s in out if s.mm > tolerance), key=lambda s: -s.mm)
