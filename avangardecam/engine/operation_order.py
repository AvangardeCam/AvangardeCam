# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The order of the operations of a setup.

The operations run in the order of the setup's Operations group (the
program, the simulation, the cycle time read it), so moving one is moving
it in that group. Only within its own setup: an operation uses the tools
of its setup.
"""


def moved(items, item, index):
    """items with item taken out and put back before the one at index of
    the old order (len(items): at the end)."""
    items = list(items)
    old = items.index(item)
    index = max(0, min(index, len(items)))
    items.pop(old)
    if index > old:
        index -= 1
    items.insert(index, item)
    return items


def move(job, op, index):
    """Move an operation of a setup before the one at index of the present
    order (len: to the end). False: it was there already."""
    ops = list(job.Operations.Group)
    order = moved(ops, op, index)
    if order == ops:
        return False
    job.Operations.Group = order
    job.Document.recompute()
    return True
