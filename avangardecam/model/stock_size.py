# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Stock of a size the user types (a block as it comes from the saw), centred
on the model: the same allowance on both sides in X, in Y and in Z."""

from avangardecam.model import stock as model_stock

# a size typed as the model's own (40 for 39.9999999) is not smaller
TOLERANCE_MM = 1e-6
AXES = ("X", "Y", "Z")


def centred(model, size_x_mm, size_y_mm, size_z_mm):
    """The BoxStock of a block size_x × size_y × size_z mm with the model
    Bounds in its middle. A size smaller than the model raises ValueError."""
    allowances = []
    for axis, size, model_size in zip(AXES, (size_x_mm, size_y_mm, size_z_mm), model.size):
        extra = size - model_size
        if extra < -TOLERANCE_MM:
            raise ValueError(
                "stock size in {} ({:g} mm) is smaller than the model ({:.2f} mm)".format(
                    axis, size, model_size
                )
            )
        allowances.append(max(0.0, extra) / 2.0)
    x, y, z = allowances
    return model_stock.BoxStock(x, x, y, y, z, z).validate()
