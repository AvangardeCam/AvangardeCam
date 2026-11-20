# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""The stock of a setup when it is no box with allowances (CAM > Next
setup, user 2026-10-30): what another setup's program leaves of its stock
("Stock from Setup N"), or a model of the blank from a file (a casting
the foundry sends, STEP or STL).

The material is kept in the part's coordinates, as a hidden object of
its own (the source, role STOCK_SOURCE_ROLE): a mesh for the stock left by
a setup (model.start_stock.left, worked out once, again on request) and
for an STL; a solid for a STEP. The Job's stock is then a shape
in the setup's coordinates, put there again whenever the zero point moves
(place, from freecad_cam._place_stock): the solid itself, or the box of a
mesh (FreeCAD's operations only read the stock's box). Verify and the
playback cut the material itself (start_mesh), Adaptive clears what there
is of a mesh on each of its levels (material, engine.adaptive), FreeCAD's
simulator starts from it made coarser (simulator_stock).

A setup's stock is of the kind kind() says: STANDARD (FreeCAD's stock
from the model with allowances), FROM_SETUP, CUSTOM, OTHER (made in
FreeCAD itself).
"""

import datetime
import os
from typing import NamedTuple

import numpy as np

import FreeCAD

from avangardecam.engine import ProjectError
from avangardecam.engine import freecad_cam as cam
from avangardecam.model import start_stock
from avangardecam.model import verify as model_verify
from avangardecam.post import heidenhain

STANDARD = "standard"
FROM_SETUP = "setup"
CUSTOM = "custom"
OTHER = "other"

STOCK_SOURCE_ROLE = "stock-source"
KIND_PROPERTY = "AvangardeStockKind"
SOURCE_PROPERTY = "AvangardeStockSource"
FROM_PROPERTY = "AvangardeStockFrom"  # the Name of the setup it was worked out from
ACCURACY_PROPERTY = "AvangardeStockAccuracy"  # cells on the longest edge it was cut with
MADE_PROPERTY = "AvangardeStockMade"  # when it was worked out
FILE_PROPERTY = "AvangardeStockFile"

MESH_FILES = (".stl", ".obj", ".ply", ".off", ".ast", ".bms")
SOLID_FILES = (".step", ".stp", ".iges", ".igs", ".brep", ".brp")

# how far the triangles of a custom solid may be from its faces (the
# playback's part: they only make the start of a stock model)
DEFLECTION_MM = 0.02
# cells on the longest edge of the stock model Adaptive clears (material)
# when the stock was worked out at no accuracy (a blank from a mesh file)
ADAPTIVE_RESOLUTION = 250
# triangles of a stock drawn by FreeCAD's simulator (simulator_stock): it
# numbers the corners in 16 bits, three for each triangle (no more than
# 21845 triangles), and turns each into a face (8000: about a second)
SIMULATOR_TRIANGLES = 8000


def kind(job):
    stock = getattr(job, "Stock", None)
    if stock is None:
        return OTHER
    own = getattr(stock, KIND_PROPERTY, "")
    if own:
        return own
    return STANDARD if cam.stock(job) is not None else OTHER


def source(job):
    """The object the stock's material is kept in (part coordinates), or None."""
    return getattr(job.Stock, SOURCE_PROPERTY, None) if job.Stock is not None else None


def from_setup(job):
    """The setup a FROM_SETUP stock was worked out from (None when it is gone)."""
    name = getattr(job.Stock, FROM_PROPERTY, "") if job.Stock is not None else ""
    return next((j for j in cam.setups(job.Document) if j.Name == name), None)


def description(job):
    """What the stock of a setup is, in a few words (Details)."""
    k = kind(job)
    if k == FROM_SETUP:
        previous = from_setup(job)
        return "What {} leaves, worked out {} at {} cells".format(
            previous.Label if previous is not None else "a removed setup",
            getattr(job.Stock, MADE_PROPERTY, ""), getattr(job.Stock, ACCURACY_PROPERTY, 0),
        )  # fmt: skip
    if k == CUSTOM:
        return "A model of the blank: {}".format(getattr(job.Stock, FILE_PROPERTY, ""))
    return ""


def _matrix(placement):
    return np.array(placement.toMatrix().A, float).reshape(4, 4)


def _mesh_of(mesh_object):
    """A Mesh::Feature's triangles in the document's coordinates (its
    Topology has its placement in it)."""
    points, facets = mesh_object.Mesh.Topology
    vertices = np.array([(p.x, p.y, p.z) for p in points], float).reshape(-1, 3)
    return start_stock.Mesh(vertices, np.array(facets, np.int64).reshape(-1, 3))


def _is_mesh(obj):
    return obj is not None and obj.isDerivedFrom("Mesh::Feature")


def start_mesh(job):
    """The material a setup starts from, as a model.start_stock.Mesh in
    the setup's coordinates; None: its stock box is full of it."""
    if kind(job) not in (FROM_SETUP, CUSTOM):
        return None
    src = source(job)
    if src is None:
        raise ProjectError("The stock of {} has lost the model it was made from.".format(job.Label))
    if _is_mesh(src):
        return start_stock.moved(_mesh_of(src), _matrix(cam.zero(job).inverse()))
    points, faces = job.Stock.Shape.tessellate(DEFLECTION_MM)
    vertices = np.array([(p.x, p.y, p.z) for p in points], float).reshape(-1, 3)
    return start_stock.Mesh(vertices, np.array(faces, np.int64).reshape(-1, 3))


def material(job):
    """The material a setup starts from as a stock model (stocklab.Stock,
    the setup's coordinates) when its stock is a mesh (the stock another
    setup left, a blank from an STL file), at the accuracy it was worked
    out at: what Adaptive clears (its Stock is only the box around it).
    None when the Job's stock is the material (a box, a blank from a STEP
    file)."""
    if kind(job) not in (FROM_SETUP, CUSTOM) or not _is_mesh(source(job)):
        return None
    start = start_mesh(job)
    resolution = getattr(job.Stock, ACCURACY_PROPERTY, 0) or ADAPTIVE_RESOLUTION
    return start_stock.block(start_stock.bounds(start), start, resolution)


def simulator_stock(job):
    """The stock of a setup starting from a mesh as FreeCAD's simulator
    takes it (CAM > FreeCAD sim), in the setup's coordinates: the mesh made
    coarser (SIMULATOR_TRIANGLES), as faces. None when the Job's stock is
    the material (a box, a blank from a STEP file)."""
    if kind(job) not in (FROM_SETUP, CUSTOM) or not _is_mesh(source(job)):
        return None
    import Part

    src = source(job)
    mesh = src.Mesh.copy()
    mesh.Placement = cam.zero(job).inverse().multiply(src.Placement)  # its Topology in the setup's coordinates
    if mesh.CountFacets > SIMULATOR_TRIANGLES:
        mesh.decimate(SIMULATOR_TRIANGLES)
    shape = Part.Shape()
    shape.makeShapeFromMesh(mesh.Topology, 0.05, False)
    return shape


# -- the stock a setup leaves ----------------------------------------------------------


class Prepared(NamedTuple):
    label: str  # of the setup
    stock: object  # its box, model.stock.Bounds
    start: object  # its start mesh or None
    planned: list  # model.verify.Planned
    to_part: np.ndarray  # 4x4: its coordinates to the part's


def prepare_left(job):
    """What left needs of a setup (read from FreeCAD): its active operations
    as the stock model cuts them, its stock."""
    doc = job.Document
    index = cam.setups(doc).index(job)
    setup = cam.nc_program(doc, "STOCK").setups[index]
    if setup.stock is None:
        raise ProjectError("{} has no stock.".format(job.Label))
    tools = {t.number: t.tool for t in cam.project_tools(job)}
    try:
        planned = model_verify.plan(setup, tools, heidenhain.BRIDGEPORT_V1000.retract_z_mm)
    except ValueError as e:
        raise ProjectError(str(e))
    return Prepared(job.Label, setup.stock, start_mesh(job), planned, _matrix(cam.zero(job)))


def left(prepared, resolution, progress=None):
    """The stock the setup's program leaves, as a mesh in the part's
    coordinates; needs no FreeCAD, may run in another thread."""
    mesh = start_stock.left(prepared.stock, prepared.start, prepared.planned, resolution, progress)
    if mesh is None:
        raise ProjectError("The program of {} leaves no stock.".format(prepared.label))
    return start_stock.moved(mesh, prepared.to_part)


# -- setting the stock ---------------------------------------------------------------


def _mesh_object(doc, mesh, label):
    import Mesh

    obj = doc.addObject("Mesh::Feature", "StockSource")
    obj.Mesh = Mesh.Mesh(np.asarray(mesh.vertices, float)[np.asarray(mesh.triangles)].tolist())
    return _source(obj, label)


def _source(obj, label):
    cam._helper(obj, STOCK_SOURCE_ROLE, label)
    vo = getattr(obj, "ViewObject", None)
    if vo is not None:  # drawn instead of its box when its setup is active (ui.next_setup)
        vo.Transparency = 85
        if hasattr(vo, "Selectable"):
            vo.Selectable = False
        if hasattr(vo, "Lighting"):
            vo.Lighting = "Two side"
    return obj


def set_stock_from_setup(job, previous, mesh, resolution):
    """Make the stock of job what previous leaves (mesh: left's result)."""
    if previous is job:
        raise ProjectError("A setup cannot start from its own stock.")
    src = _mesh_object(job.Document, mesh, "Stock left by {}".format(previous.Label))
    _replace(job, src, FROM_SETUP, previous=previous, accuracy=resolution)


def update_from_setup(job, mesh, resolution):
    """Put a stock left worked out again in a FROM_SETUP stock."""
    import Mesh

    src = source(job)
    src.Mesh = Mesh.Mesh(np.asarray(mesh.vertices, float)[np.asarray(mesh.triangles)].tolist())
    setattr(job.Stock, ACCURACY_PROPERTY, int(resolution))
    setattr(job.Stock, MADE_PROPERTY, _now())
    _placed(job)


def read_model(path):
    """The model of a blank in a file: a Mesh.Mesh (STL, ...) or a solid
    (Part.Shape, STEP, ...); ProjectError when it is none."""
    ext = os.path.splitext(path)[1].lower()
    if ext in MESH_FILES:
        import Mesh

        mesh = Mesh.Mesh(path)
        if mesh.CountFacets == 0:
            raise ProjectError("{} has no triangles.".format(os.path.basename(path)))
        if not mesh.isSolid():
            raise ProjectError("{} is not closed: it has holes in its surface.".format(os.path.basename(path)))
        return mesh
    if ext in SOLID_FILES:
        import Part

        shape = Part.Shape()
        try:
            shape.read(path)
        except Exception as exc:
            raise ProjectError("{} could not be read: {}".format(os.path.basename(path), exc))
        solids = shape.Solids
        if not solids:
            raise ProjectError("{} has no solid.".format(os.path.basename(path)))
        return solids[0] if len(solids) == 1 else Part.makeCompound(solids)
    raise ProjectError("A model of the blank can be a STEP, IGES, BREP or STL file, not {}.".format(os.path.basename(path)))


def set_custom_stock(job, path):
    """Make the stock of job the model of a blank in a file, lying in the
    part's coordinates as the file has it (the foundry draws the casting
    over the part)."""
    model = read_model(path)
    doc = job.Document
    name = os.path.basename(path)
    if hasattr(model, "CountFacets"):
        src = doc.addObject("Mesh::Feature", "StockSource")
        src.Mesh = model
    else:
        src = doc.addObject("Part::Feature", "StockSource")
        src.Shape = model
    _source(src, "Blank {}".format(name))
    _replace(job, src, CUSTOM, file=name)


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _replace(job, src, stock_kind, previous=None, accuracy=0, file=""):
    doc = job.Document
    old = job.Stock
    # Python: FreeCAD's Job asks its stock's view for a proxy (IconViewProvider)
    stock = doc.addObject("Part::FeaturePython", "Stock")
    stock.Label = "Stock"
    cam._add_property(stock, "App::PropertyString", KIND_PROPERTY, "What the stock is made from")
    cam._add_property(stock, "App::PropertyLink", SOURCE_PROPERTY, "The material in the part's coordinates")
    cam._add_property(stock, "App::PropertyString", FROM_PROPERTY, "The setup it was worked out from")
    cam._add_property(stock, "App::PropertyInteger", ACCURACY_PROPERTY, "Cells on the longest edge it was cut with")
    cam._add_property(stock, "App::PropertyString", MADE_PROPERTY, "When it was worked out")
    cam._add_property(stock, "App::PropertyString", FILE_PROPERTY, "The file of the blank")
    setattr(stock, KIND_PROPERTY, stock_kind)
    setattr(stock, SOURCE_PROPERTY, src)
    setattr(stock, FROM_PROPERTY, previous.Name if previous is not None else "")
    setattr(stock, ACCURACY_PROPERTY, int(accuracy))
    setattr(stock, MADE_PROPERTY, _now() if previous is not None else "")
    setattr(stock, FILE_PROPERTY, file)
    if getattr(stock, "ViewObject", None) is not None:
        import Path.Base.Gui.IconViewProvider as IconViewProvider

        IconViewProvider.Attach(stock.ViewObject, "Stock")
    job.Stock = stock
    if old is not None:
        forget(old)
        doc.removeObject(old.Name)
    cam._show_stock(stock)
    _placed(job)


def _placed(job):
    place(job)
    cam._sync_operations(job)
    job.Document.recompute()


def forget(stock):
    """Remove the source of a stock that is replaced (nothing else uses it)."""
    src = getattr(stock, SOURCE_PROPERTY, None)
    if src is None or getattr(src, cam._ROLE_PROPERTY, "") != STOCK_SOURCE_ROLE:
        return
    setattr(stock, SOURCE_PROPERTY, None)
    if not src.InList:
        stock.Document.removeObject(src.Name)


def place(job):
    """Put a FROM_SETUP or CUSTOM stock in the setup's coordinates again
    (after its zero point moved); False for a stock of another kind."""
    if kind(job) not in (FROM_SETUP, CUSTOM):
        return False
    import Part

    src = source(job)
    if src is None:
        return True
    to_setup = cam.zero(job).inverse()
    stock = job.Stock
    if _is_mesh(src):
        b = start_stock.bounds(start_stock.moved(_mesh_of(src), _matrix(to_setup)))
        shape = Part.makeBox(b.x_max - b.x_min, b.y_max - b.y_min, b.z_max - b.z_min, FreeCAD.Vector(b.x_min, b.y_min, b.z_min))
        stock.Shape = shape
        stock.Placement = FreeCAD.Placement()
    else:
        stock.Shape = src.Shape.copy()
        stock.Placement = to_setup.multiply(src.Placement)
    return True
