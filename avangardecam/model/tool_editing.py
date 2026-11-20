# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Adding and editing tools of the shop's tool library (model.library).

Each tool type has its own fields (FIELDS), named as FreeCAD's drawings of
the types letter them where they do (D, H, L, S, ...). problems() says what
keeps a tool from being saved; the library list is changed with added(),
replaced() and removed(), the ids kept stable (a project knows its tools by
them, engine.freecad_cam).
"""

import dataclasses
from typing import NamedTuple

from avangardecam.model import library
from avangardecam.model.tools import SHAPES, Tool


class Field(NamedTuple):
    name: str  # of model.tools.Tool
    label: str  # English
    letter: str  # on FreeCAD's drawing of the type, "" when it has none
    required: bool = False


DIAMETER = Field("diameter_mm", "Diameter", "D", True)
FLUTES = Field("flutes", "Flutes", "")
CUTTING = Field("cutting_length_mm", "Cutting length", "H")
LENGTH = Field("length_mm", "Length out of the holder", "L")
SHANK = Field("shank_diameter_mm", "Shank diameter", "S")

# the geometry fields of each type, in the order the window shows them
FIELDS = {
    "Endmill": (DIAMETER, FLUTES, CUTTING, LENGTH, SHANK),
    "Bullnose": (DIAMETER, Field("corner_radius_mm", "Corner radius", "R", True), FLUTES, CUTTING, LENGTH, SHANK),
    "Ballend": (DIAMETER, FLUTES, CUTTING, LENGTH, SHANK),
    "Drill": (DIAMETER, Field("angle_deg", "Point angle", "α", True), FLUTES, Field("length_mm", "Length out of the holder", "H"), SHANK._replace(letter="")),  # fmt: skip
    "Chamfer": (
        Field("diameter_mm", "Diameter", "", True), Field("tip_diameter_mm", "Tip diameter", ""),
        Field("angle_deg", "Angle", "α", True), FLUTES, CUTTING._replace(letter="h"), LENGTH, SHANK,
    ),  # fmt: skip
    "VBit": (
        DIAMETER, Field("tip_diameter_mm", "Tip diameter", "d"), Field("angle_deg", "Angle", "α", True), FLUTES,
        CUTTING._replace(letter="h"), LENGTH, SHANK,
    ),  # fmt: skip
    "ThreadMill": (
        DIAMETER, Field("pitch_mm", "Pitch", "", True), Field("angle_deg", "Thread angle", "α", True), FLUTES,
        CUTTING._replace(letter="C"), Field("neck_diameter_mm", "Neck diameter", "N"),
        Field("neck_length_mm", "Neck length", "n"), LENGTH._replace(letter=""), SHANK,
    ),  # fmt: skip
}
# the drawing of each type in FreeCAD's Mod/CAM/Tools/Shape
DRAWINGS = {
    "Endmill": "endmill.svg", "Bullnose": "bullnose.svg", "Ballend": "ballend.svg", "Drill": "drill.svg",
    "Chamfer": "chamfer.svg", "VBit": "v-bit.svg", "ThreadMill": "thread-mill.svg",
}  # fmt: skip
# what a new tool of a type starts with
DEFAULTS = {"Drill": {"angle_deg": 118.0}, "Chamfer": {"angle_deg": 90.0}, "VBit": {"angle_deg": 90.0}, "ThreadMill": {"angle_deg": 60.0}}  # fmt: skip
GEOMETRY = tuple(sorted({f.name for fields in FIELDS.values() for f in fields}))
TOOL_MATERIALS = ("Carbide", "HSS", "HSS-Co", "Cermet", "Diamond")

assert set(FIELDS) == set(SHAPES) == set(DRAWINGS)


def fitted(tool):
    """The tool with only the geometry its type has (another type chosen
    leaves the values of the old one)."""
    own = {f.name for f in FIELDS.get(tool.shape, ())}
    return dataclasses.replace(tool, **{name: None for name in GEOMETRY if name not in own})


def problems(entry, entries=()):
    """What keeps a library tool from being saved (texts in English), none
    when it can be: the model's checks and the ones a program needs."""
    tool = entry.tool
    found = []
    if entry.number < 1:
        found.append("The T number must be 1 or more.")
    if not tool.name.strip():
        found.append("The tool needs a name.")
    for field in FIELDS.get(tool.shape, ()):
        value = getattr(tool, field.name)
        if field.required and not value:
            found.append("{} is needed.".format(field.label))
        elif value is not None and value < 0:
            found.append("{} cannot be negative.".format(field.label))
    if not (tool.spindle_rpm and tool.feed_xy_mm_min and tool.feed_z_mm_min):
        found.append("A program needs the spindle speed and both feeds.")
    d = tool.diameter_mm or 0.0
    if tool.corner_radius_mm and tool.corner_radius_mm > d / 2.0 + 1e-9:
        found.append("The corner radius cannot be more than half the diameter.")
    if tool.tip_diameter_mm and tool.tip_diameter_mm >= d:
        found.append("The tip diameter must be less than the diameter.")
    if tool.angle_deg is not None and not 0.0 < tool.angle_deg <= 180.0:
        found.append("The angle must be more than 0° and at most 180°.")
    if tool.cutting_length_mm and tool.length_mm and tool.cutting_length_mm > tool.length_mm + 1e-9:
        found.append("The cutting length cannot be more than the length out of the holder.")
    if tool.neck_length_mm and tool.length_mm and tool.neck_length_mm > tool.length_mm + 1e-9:
        found.append("The neck cannot be longer than the length out of the holder.")
    if not found:
        try:
            tool.validate()
        except ValueError as exc:
            found.append(str(exc))
    return found


def same_number(entries, entry):
    """The other tools of the library under entry's T number (its variants
    for other workpiece materials or inserts), to show when a number is
    chosen."""
    return [e for e in entries if e.number == entry.number and e.id != entry.id]


def next_number(entries):
    """The lowest T number the library does not use."""
    taken = {e.number for e in entries}
    return next(n for n in range(1, len(taken) + 2) if n not in taken)


def with_new_id(entries, entry):
    """entry with an id of its own in the library (a new or duplicated tool)."""
    taken = {e.id for e in entries}
    return dataclasses.replace(entry, id=library.make_id(entry.number, entry.workpiece_material, entry.tool.name, taken))


def added(entries, entry):
    """The library with entry after the last tool of its T number or lower."""
    result = list(entries)
    if any(e.id == entry.id for e in result):
        raise ValueError("{} is in the library already".format(entry.id))
    index = max((i + 1 for i, e in enumerate(result) if e.number <= entry.number), default=0)
    result.insert(index, entry)
    return result


def replaced(entries, entry):
    """The library with the tool of entry's id changed to entry (in its place)."""
    result = list(entries)
    index = next((i for i, e in enumerate(result) if e.id == entry.id), None)
    if index is None:
        raise ValueError("{} is not in the library".format(entry.id))
    result[index] = entry
    return result


def removed(entries, entry_id):
    """The library without the tool of that id."""
    result = [e for e in entries if e.id != entry_id]
    if len(result) == len(entries):
        raise ValueError("{} is not in the library".format(entry_id))
    return result


def blank(entries, shape="Endmill", material=""):
    """A new tool of the library to fill in."""
    tool = Tool(name="", shape=shape, diameter_mm=0.0, tool_material="Carbide", **DEFAULTS.get(shape, {}))
    return library.LibraryTool(id="", number=next_number(entries), workpiece_material=material, tool=tool)
