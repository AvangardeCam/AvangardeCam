# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The tool library file that tools are added to and edited in
(model.tool_editing), and the projects' tools made from an edited one.

The library shipped with the module is replaced by every update, so the
first change copies it into FreeCAD's user data folder
(AvangardeCam/tools.json) and the ToolLibraryFile parameter points there
from then on. A library opened from elsewhere (Open other library...) is
changed where it is.
"""

import os
import shutil

import FreeCAD

from avangardecam import params, shipped_tool_library_path, tool_library_path
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import library

PARAMETER = "ToolLibraryFile"


def user_path():
    """The user's own copy of the library, kept over updates of the module."""
    return os.path.join(FreeCAD.getUserAppDataDir(), "AvangardeCam", "tools.json")


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def editable_path():
    """The library file to write changes to: the one in use, or the user's
    copy of the shipped one (made now when there is none; one there
    already is used as it is). (path, copied: whether it changed)."""
    path = tool_library_path()
    if not _same(path, shipped_tool_library_path()):
        return path, False
    target = user_path()
    if not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
    params().SetString(PARAMETER, target)
    return target, True


def save(path, entries):
    """Write the library (OSError when it cannot be written)."""
    source = ""
    try:
        with open(path, encoding="utf-8") as f:
            import json

            source = json.load(f).get("source", "")
    except (OSError, ValueError):
        pass
    library.save(path, entries, source=source)


def project_tools_of(doc, entry_id):
    """[(setup, ProjectTool)] made from the library tool of that id."""
    if doc is None:
        return []
    return [(job, t) for job in cam.setups(doc) for t in cam.project_tools(job) if t.library_id == entry_id]


def update_projects(doc, entry):
    """The tools made from entry (its id) in the document's setups made
    again from it, so the operations get its geometry, speeds and feeds.
    (setups updated, setups left: their tool has another T number now)."""
    done, left = [], []
    for job, tool in project_tools_of(doc, entry.id):
        if tool.number != entry.number:
            left.append(job)
            continue
        cam.replace_tool(job, tool.controller, entry)
        done.append(job)
    return done, left
