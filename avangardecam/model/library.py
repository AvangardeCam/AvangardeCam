# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The shop's tool library, kept outside FreeCAD.

One physical tool often appears several times under the same T number,
once per workpiece material (aluminium, RVS, steel) with its own spindle
speed and feeds, or with another insert. Every such variant is a
LibraryTool with its own id; the T number is what the machine uses. A
project holds at most one variant per T number (see engine.freecad_cam).

File format (JSON, units in the key names):

    {"format": "avangardecam-tool-library", "version": 1, "source": "...",
     "tools": [{"id": "...", "number": 5, "workpiece_material": "Aluminium",
                "name": "...", "shape": "Bullnose", "diameter_mm": 6.0, ...}]}
"""

import json
import re
from dataclasses import asdict, dataclass, fields

from avangardecam.model.tools import Tool

FORMAT = "avangardecam-tool-library"
VERSION = 1

_TOOL_FIELDS = tuple(f.name for f in fields(Tool))


@dataclass(frozen=True)
class LibraryTool:
    id: str  # unique in the library, stable across imports
    number: int  # T number on the machine; several variants may share it
    workpiece_material: str  # what this variant's cutting data is for
    tool: Tool
    manufacturer: str = ""
    order_code: str = ""
    comment: str = ""

    def validate(self):
        if not self.id:
            raise ValueError("library tool without id: {}".format(self.tool.name))
        if self.number < 0:
            raise ValueError("{}: tool number must be >= 0".format(self.id))
        self.tool.validate()
        return self


def make_id(number, material, name, taken=()):
    """A readable, stable id such as 't19-rvs-iscar-ruw-frees-6mm-rvs'."""
    slug = re.sub(r"[^a-z0-9.]+", "-", "{} {}".format(material, name).lower()).strip("-")
    base = "t{}-{}".format(number, slug)
    result, n = base, 2
    while result in taken:
        result, n = "{}-{}".format(base, n), n + 1
    return result


def to_dict(entry):
    data = {"id": entry.id, "number": entry.number, "workpiece_material": entry.workpiece_material}
    data.update({k: v for k, v in asdict(entry.tool).items() if v not in (None, "")})
    for key in ("manufacturer", "order_code", "comment"):
        if getattr(entry, key):
            data[key] = getattr(entry, key)
    return data


def from_dict(data):
    tool = Tool(**{k: data[k] for k in _TOOL_FIELDS if k in data})
    return LibraryTool(
        id=data["id"],
        number=int(data["number"]),
        workpiece_material=data.get("workpiece_material", ""),
        tool=tool,
        manufacturer=data.get("manufacturer", ""),
        order_code=data.get("order_code", ""),
        comment=data.get("comment", ""),
    ).validate()


def load(path):
    """Read a library file; raises ValueError when it is not a valid one."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != FORMAT:
        raise ValueError("{} is not an AvangardeCam tool library".format(path))
    if data.get("version", 0) > VERSION:
        raise ValueError("{} needs a newer AvangardeCam (library version {})".format(path, data["version"]))
    entries = [from_dict(item) for item in data.get("tools", [])]
    ids = [e.id for e in entries]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError("duplicate tool ids in {}: {}".format(path, ", ".join(duplicates)))
    return entries


def save(path, entries, source=""):
    data = {
        "format": FORMAT,
        "version": VERSION,
        "source": source,
        "tools": [to_dict(e.validate()) for e in entries],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")


def materials(entries):
    """The workpiece materials of a library, sorted."""
    return sorted({e.workpiece_material for e in entries if e.workpiece_material})


def find(entries, entry_id):
    return next((e for e in entries if e.id == entry_id), None)
