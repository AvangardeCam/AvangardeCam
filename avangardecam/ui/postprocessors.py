# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""File > Export NC program: the file and the machine, on its own.

One file window asks for both: each machine's postprocessor
(post.machines) is a file type of the window, the one used last is
chosen first.
"""

import os

import FreeCADGui

from PySide import QtWidgets

from avangardecam import params, tr
from avangardecam.post import machines

_PARAM = "Postprocessor"


def last():
    """The postprocessor chosen last (the first time: the default one)."""
    return machines.find(params().GetString(_PARAM, machines.DEFAULT.key))


def remember(post):
    params().SetString(_PARAM, post.key)


def filter_text(post):
    return "{} (*.H *.h)".format(tr(post.label))


def ask(doc):
    """(path, postprocessor) from the file window, None when it is cancelled."""
    chosen = last()
    module = chosen.module
    stem = os.path.splitext(os.path.basename(doc.FileName))[0] if doc.FileName else doc.Label
    folder = params().GetString("LastExportDir", os.path.dirname(doc.FileName) or os.path.expanduser("~"))
    filters = {filter_text(post): post for post in machines.ALL}
    path, picked = QtWidgets.QFileDialog.getSaveFileName(
        FreeCADGui.getMainWindow(),
        tr("Export NC program"),
        os.path.join(folder, module.program_name(stem) + module.EXTENSION),
        ";;".join(filters),
        filter_text(chosen),
    )
    if not path:
        return None
    return path, filters.get(picked, chosen)
