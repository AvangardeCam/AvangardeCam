# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Strict unit parsing: lengths become mm, feeds mm/min, angles degrees.

A unit we do not know, or a missing unit where one is required, raises
UnitError: a wrong unit must stop the work, never be guessed.
"""

import re


class UnitError(ValueError):
    pass


LENGTH_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
FEED_TO_MM_MIN = {"mm/min": 1.0, "mm/s": 60.0, "cm/min": 10.0, "m/min": 1000.0, "in/min": 25.4}
ANGLE_TO_DEG = {"°": 1.0, "deg": 1.0}

# a plain decimal number with a point; a comma is refused as "1,250" could
# be read as 1.25 or 1250
_VALUE = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*$")


def _split(text):
    match = _VALUE.match(str(text))
    if not match:
        raise UnitError("not a number: {!r}".format(text))
    return float(match.group(1)), match.group(2)


def _convert(text, table, kind, default_unit):
    value, unit = _split(text)
    if not unit:
        if default_unit is None:
            raise UnitError("{} without unit: {!r}".format(kind, text))
        unit = default_unit
    if unit not in table:
        raise UnitError("unknown {} unit {!r} in {!r}".format(kind, unit, text))
    return value * table[unit]


def length_mm(text, default_unit=None):
    """'6.0000 mm' -> 6.0; '0.5 in' -> 12.7."""
    return _convert(text, LENGTH_TO_MM, "length", default_unit)


def feed_mm_min(text, default_unit=None):
    """'1250 mm/min' -> 1250.0; '20 mm/s' -> 1200.0."""
    return _convert(text, FEED_TO_MM_MIN, "feed", default_unit)


def angle_deg(text, default_unit=None):
    """'118.0000 °' -> 118.0."""
    return _convert(text, ANGLE_TO_DEG, "angle", default_unit)


def plain_number(text):
    """A count or a speed without unit, e.g. flutes or rpm."""
    value, unit = _split(text)
    if unit:
        raise UnitError("expected a plain number, got {!r}".format(text))
    return value
