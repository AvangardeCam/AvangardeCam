# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""What the machine runs into (model.crashes) with a tool that does not
come from +Z (an operation on a turned zero point, model.tilted), on its
own: model.crashes.cut hands such a tool axis over to here.

The same crashes are found the same way: the moves are cut in order as
one batch, a move is cut on its own, to know what it took, only when
material is in its way. What is in the way is asked of the stock as it is
before the batch (stocklab.oblique.would_take: how much a move would
take, nothing cut): a rapid move, or a shank, that would take nothing
then takes nothing later either, as material only goes. Those that would
are looked at again in their turn, the moves before them cut.

Plain Python with numpy, no FreeCAD.
"""

import numpy as np

from avangardecam import stocklab
from avangardecam.model import crashes
from avangardecam.stocklab import oblique
from avangardecam.stocklab import program as stock_program
from avangardecam.stocklab import tools as stock_tools


def _would_take(stock, tool, axis, a, b):
    return bool(oblique.would_take(stock, tool, axis, [a], [b])[0] > 0.0)


def cut(stock, tool, shank, pieces, axis):
    """model.crashes.cut with the tool along axis (stocklab's: "-X", a
    vector)."""
    touch = stock_program.TOUCH * float(np.prod(stock.spacing))
    narrow = None
    if shank is not None:
        slack = crashes.SHANK_SLACK_CELLS * float(stock.spacing.min())
        parts = [stock_tools.Part([stock_tools.Line(p.h0, p.h1, p.rmax - slack)]) for p in shank.parts if p.rmax > slack]
        narrow = stock_tools.Tool(parts, shank.name) if parts else None
    found = {}

    def crash(kind, key, taken):
        if taken > touch:
            found[(kind, key)] = found.get((kind, key), 0.0) + taken

    pieces = [(np.asarray(a, dtype=float), np.asarray(b, dtype=float), rapid, key) for a, b, rapid, key in pieces]
    for first in range(0, len(pieces), stock_program.BATCH):
        batch = pieces[first : first + stock_program.BATCH]
        starts = np.array([p[0] for p in batch])
        ends = np.array([p[1] for p in batch])
        rapid = np.array([p[2] for p in batch], dtype=bool)
        # what may be in the way, in the stock as it is now
        may = np.zeros(len(batch), dtype=bool)
        if rapid.any():
            may[rapid] = oblique.would_take(stock, tool, axis, starts[rapid], ends[rapid]) > 0.0
        rubs = np.zeros(len(batch), dtype=bool)
        if shank is not None:
            rubs = oblique.would_take(stock, shank, axis, starts, ends) > 0.0
        waiting = []  # indices of the moves cut together

        def flush():
            if waiting:
                stocklab.cut_lines(stock, tool, axis, starts[waiting], ends[waiting])
                waiting.clear()

        move = []  # the pieces of the move going on
        for i, (a, b, is_rapid, key) in enumerate(batch):
            move.append(i)
            if is_rapid and may[i]:
                flush()
                if _would_take(stock, tool, axis, a, b):
                    crash(crashes.RAPID, key, stocklab.cut_line(stock, tool, axis, a, b))
                else:
                    waiting.append(i)
            else:
                waiting.append(i)
            last = i + 1 == len(batch) or batch[i + 1][3] != key
            if last:
                # the shank after the move's cutting, all the move's pieces at once
                near = [k for k in move if rubs[k]]
                if near:
                    flush()
                    near = [k for k in near if _would_take(stock, shank, axis, starts[k], ends[k])]
                if near:
                    if narrow is not None:
                        crash(crashes.SHANK, key, stocklab.cut_lines(stock, narrow, axis, starts[near], ends[near]))
                    stocklab.cut_lines(stock, shank, axis, starts[near], ends[near])
                move = []
        flush()
    return [crashes.Crash(kind, key, volume) for (kind, key), volume in found.items()]
