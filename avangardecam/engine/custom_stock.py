# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""A custom stock in any setup (CAM > Custom stock, user 2026-11-17): the
model of the blank from a file (STEP, IGES, BREP, STL), as Next setup's
Custom stock (engine.next_setup.set_custom_stock: the same kind CUSTOM,
the same source object in the part's coordinates), then, by default, put
with the middle of its box on the middle of the models' box
(model.custom_stock): the file may draw the blank anywhere. A blank the
file already draws around the model is left there (the foundry's
allowances may not be the same on each side). move: shifted along the
setup's axes by hand (the stock's menu, ui.custom_stock).

The middles are those of the boxes on the setup's axes, the models' and
the blank's, both from their exact faces (_tight). Only moved, never turned: a blank drawn lying another way
than the part sticks out of it, which load and sticking_out tell.
"""

from typing import NamedTuple

import FreeCAD

from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.engine import next_setup
from avangardecam.model import custom_stock as model
from avangardecam.model import stock as model_stock

# a blank this close to the model's middle is on it (Details)
ON_MIDDLE_MM = 0.005
# a blank the file draws around the model, but for this much (an STL's
# triangles inside an arc), lies where the foundry put it: not moved
FITS_MM = 0.1


class Loaded(NamedTuple):
    shift: tuple  # how far the blank was moved, on the setup's axes (0, 0, 0: not)
    out: list  # model.custom_stock.SticksOut: where the model reaches past the blank
    kept: bool = False  # the file draws it around the model already: left there


def _tight(shape):
    """The box of a shape from its exact faces. Not BoundBox: once the
    shape is drawn (the GUI), OCC takes its box from the triangles drawn,
    which lie inside a large arc (1.44 mm under the top of a part 2.4 m
    long, user's file 2026-11-17); nor the triangles with the deflection
    added (optimalBoundingBox's default), as far outside."""
    try:
        box = shape.optimalBoundingBox(False, False)
    except Exception:  # an older FreeCAD, a shape it cannot work out
        box = shape.BoundBox
    return model_stock.Bounds(box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def models_bounds(job):
    """The box of the setup's models on its axes, from their exact faces
    (_tight; engine.stock_size.models_bounds takes FreeCAD's BoundBox)."""
    if not job.Model.Group:
        raise ProjectError("{} has no model to put the stock around.".format(job.Label))
    boxes = [_tight(clone.Shape) for clone in job.Model.Group]
    return model_stock.Bounds(
        min(b.x_min for b in boxes), min(b.y_min for b in boxes), min(b.z_min for b in boxes),
        max(b.x_max for b in boxes), max(b.y_max for b in boxes), max(b.z_max for b in boxes),
    )  # fmt: skip


def _check(job):
    if next_setup.kind(job) != next_setup.CUSTOM or next_setup.source(job) is None:
        raise ProjectError("The stock of {} is no model of a blank.".format(job.Label))


def blank_bounds(job):
    """The box of a custom stock on the setup's axes."""
    _check(job)
    return _tight(job.Stock.Shape)


def off_middle(job):
    """How far the blank's middle is from the models' middle, on the
    setup's axes: what centre moves it by."""
    return model.centre_shift(blank_bounds(job), models_bounds(job))


def is_on_middle(job):
    return all(abs(d) <= ON_MIDDLE_MM for d in off_middle(job))


def move(job, shift):
    """Move the blank by shift (dx, dy, dz) on the setup's axes (its
    source moves in the part's coordinates, so it stays put when the zero
    point moves)."""
    _check(job)
    src = next_setup.source(job)
    along_part = cam.zero(job).Rotation.multVec(FreeCAD.Vector(*shift))
    placement = FreeCAD.Placement(src.Placement)
    placement.Base = placement.Base + along_part
    src.Placement = placement
    next_setup._placed(job)
    return tuple(shift)


def centre(job):
    """Move the blank so that its middle is on the models' middle; the
    shift on the setup's axes."""
    return move(job, off_middle(job))


def fits(job):
    """Whether the blank lies around the models' box (but for FITS_MM)."""
    return not model.sticking_out(blank_bounds(job), models_bounds(job), FITS_MM)


def sticking_out(job):
    """Where the models' box reaches past the blank's (model.custom_stock)."""
    return model.sticking_out(blank_bounds(job), models_bounds(job))


def load(job, path, middle=True):
    """Make the stock of job the blank in the file; middle: its middle on
    the models' middle, unless the file draws it around the model already
    (the foundry drew it over the part, its allowances where they belong:
    user's file 2026-11-17, 8 mm under the part only); False: where the
    file draws it. ProjectError when the file holds no closed model."""
    if not job.Model.Group:
        raise ProjectError("{} has no model to put the stock around.".format(job.Label))
    next_setup.set_custom_stock(job, path)
    kept = fits(job)
    shift = centre(job) if middle and not kept else (0.0, 0.0, 0.0)
    return Loaded(shift, sticking_out(job), kept)
