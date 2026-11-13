# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Stock of a typed size centred on the setup's models (model.stock_size),
written as allowances to the Job's stock, so it stays an ordinary BoxStock."""

from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import stock as model_stock
from avangardecam.model import stock_size


def models_bounds(job):
    """Box of the setup's models in the setup's coordinates, the one the
    stock is built around."""
    import Path.Main.Stock as PathStock

    if not job.Model.Group:
        raise ProjectError("{} has no model to put the stock around.".format(job.Label))
    box = PathStock.shapeBoundBox(job.Model.Group)
    return model_stock.Bounds(box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def set_size(job, size_x_mm, size_y_mm, size_z_mm):
    """Make the stock a block of this size with the models in its middle."""
    box = stock_size.centred(models_bounds(job), size_x_mm, size_y_mm, size_z_mm)
    cam.set_stock(job, box)
    return box
