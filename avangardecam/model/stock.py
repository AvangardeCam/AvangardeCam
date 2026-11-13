# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Stock: the raw material the part is machined from."""

from dataclasses import dataclass, fields, replace
from typing import NamedTuple


class Bounds(NamedTuple):
    """Axis aligned box in mm."""

    x_min: float
    y_min: float
    z_min: float
    x_max: float
    y_max: float
    z_max: float

    @property
    def size(self):
        return (self.x_max - self.x_min, self.y_max - self.y_min, self.z_max - self.z_min)


@dataclass(frozen=True)
class BoxStock:
    """The bounding box of the model plus an allowance on each side, in mm.

    By default the stock sits flush with the bottom of the part (it lies
    on the machine table) and has 1 mm extra on the top and the sides.
    """

    x_neg_mm: float = 1.0
    x_pos_mm: float = 1.0
    y_neg_mm: float = 1.0
    y_pos_mm: float = 1.0
    z_neg_mm: float = 0.0
    z_pos_mm: float = 1.0

    MAX_ALLOWANCE_MM = 1000.0

    def validate(self):
        for f in fields(self):
            value = getattr(self, f.name)
            if not 0.0 <= value <= self.MAX_ALLOWANCE_MM:
                raise ValueError(
                    "stock allowance {} must be between 0 and {:g} mm, got {:g}".format(
                        f.name, self.MAX_ALLOWANCE_MM, value
                    )
                )
        return self

    def turned_about_z(self, degrees):
        """The allowances seen from a zero point turned about Z by degrees
        (counter-clockwise seen from the tool, as frame.rotated_about_z): the
        block stays where it is, its sides get other names. At 90° the new X
        is the old Y, so X− takes the old Y−, Y− the old X+. Only quarter
        turns keep the block a box in the new axes; another angle returns
        None."""
        quarters = degrees / 90.0
        if abs(quarters - round(quarters)) > 1e-9:
            return None
        box = self
        for _ in range(int(round(quarters)) % 4):
            box = replace(
                box,
                x_neg_mm=box.y_neg_mm,
                x_pos_mm=box.y_pos_mm,
                y_neg_mm=box.x_pos_mm,
                y_pos_mm=box.x_neg_mm,
            )
        return box

    def bounds(self, model):
        """Stock box around the model Bounds."""
        return Bounds(
            model.x_min - self.x_neg_mm,
            model.y_min - self.y_neg_mm,
            model.z_min - self.z_neg_mm,
            model.x_max + self.x_pos_mm,
            model.y_max + self.y_pos_mm,
            model.z_max + self.z_pos_mm,
        )
