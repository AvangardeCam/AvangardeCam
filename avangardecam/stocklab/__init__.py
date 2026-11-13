# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCamLab - the stock left after the tool, for AvangardeCam.
"""The material left of the stock after the moves of the tool."""

from .cut import cut_arc, cut_line, cut_lines
from .dexel import DEFAULT_RESOLUTION, Stock
from .mesh import surface
from .model import Model
from .program import Arc, Line, Operation, simulate
from .section import area
from .verify import colors, verify

__all__ = [
    "DEFAULT_RESOLUTION", "Stock", "area", "cut_arc", "cut_line", "cut_lines", "surface",
    "Model", "Arc", "Line", "Operation", "simulate", "colors", "verify",
]
