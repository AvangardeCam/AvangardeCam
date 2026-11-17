# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The box of the models from their exact faces, for FreeCAD's stock too
(user 2026-11-17: "popraw też zwykły stock").

FreeCAD builds the stock with allowances around Path.Main.Stock.shapeBoundBox,
which takes each model's Shape.BoundBox. Once a shape is drawn (the GUI),
OCC takes that box from the triangles drawn, and they lie inside a large
arc: on the user's part 2.4 m long (Detal_testowy_Soraluce) the box's top
was 1.44 mm under the part's, so a stock 1 mm over the top was 0.44 mm
under it. install() puts a shapeBoundBox in FreeCAD's module that takes
the box from the exact faces (optimalBoundingBox without the triangles):
FreeCAD's stock (its execute, by the module's name), the Job, and
AvangardeCam (engine.stock_size, freecad_cam._place_stock) all read it.
FreeCADCmd draws nothing, so there the box was right before too.
"""

import FreeCAD


def exact(shape):
    """The box (FreeCAD.BoundBox) of a shape from its exact faces; its
    BoundBox when that cannot be worked out (a null shape, an old FreeCAD)."""
    try:
        if not shape.isNull():
            return shape.optimalBoundingBox(False, False)
    except Exception:
        pass
    return shape.BoundBox


def install():
    """Put the exact shapeBoundBox in FreeCAD's Path.Main.Stock (once)."""
    try:
        import Path.Main.Stock as PathStock
    except ImportError:  # FreeCAD without CAM: no stock to build
        return
    current = PathStock.shapeBoundBox
    if getattr(current, "avangardecam_exact", False):
        return

    def shapeBoundBox(obj):
        if isinstance(obj, list) and obj:
            boxes = [b for b in (shapeBoundBox(o) for o in obj) if b is not None]
            if not boxes:
                return current(obj)
            box = FreeCAD.BoundBox()
            for b in boxes:
                box.add(b)
            return box
        shape = getattr(obj, "Shape", None)
        if shape is not None:
            return exact(shape)
        return current(obj)  # an App::Part (its Group comes back here), nothing

    shapeBoundBox.avangardecam_exact = True
    shapeBoundBox.__doc__ = current.__doc__
    PathStock.shapeBoundBox = shapeBoundBox
