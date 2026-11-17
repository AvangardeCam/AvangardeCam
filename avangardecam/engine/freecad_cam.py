# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Translator between the model and FreeCAD CAM.

An AvangardeCam project is a list of setups (clampings of the part on the
machine); each setup is one FreeCAD CAM Job in the document:
- the models are the originals behind the Job's model clones; the user
  sees and picks the originals, in part coordinates;
- the setup's zero point is a placement on the part. FreeCAD always cuts
  along Z from the Job's origin, so the Job's clones are the part moved by
  the inverse of the zero point: in the Job, X0 Y0 Z0 is the zero point
  and Z is the side the tool comes from;
- the stock is the Job's stock, made from the clones with allowances;
- the tools are the Job's tool controllers, one per T number; each one
  remembers which variant of the shop's tool library it was made from;
- operations are FreeCAD operations of the Job; the user's own values are
  stored next to them as JSON (model.operations).

Every value crosses this border in the model's units (mm, mm/min, rpm);
FreeCAD stores feeds in mm/s internally, so they are always read with an
explicit unit.
"""

import contextlib
import datetime
from typing import NamedTuple

import FreeCAD

from avangardecam.engine import ProjectError, geometry
from avangardecam.model import clearing as model_clearing
from avangardecam.model import frame as model_frame
from avangardecam.model import leads as model_leads
from avangardecam.model import nc as model_nc
from avangardecam.model import operations as model_operations
from avangardecam.model import stock as model_stock
from avangardecam.model import threads as model_threads
from avangardecam.model import tools as model_tools

__all__ = ["ProjectError"]  # raised by every function here

# FreeCAD's stock around the models' exact box, not the triangles drawn (engine.exact_box)
from avangardecam.engine import exact_box as _exact_box  # noqa: E402

_exact_box.install()


def _value(quantity, unit):
    """A FreeCAD quantity as a float in the given unit."""
    result = quantity.getValueAs(unit)
    return float(getattr(result, "Value", result))


def _quantity(value, unit):
    """A FreeCAD quantity of value in unit, checked by reading it back.

    Built from text on purpose: Quantity(1250, Unit("mm/min")) is 1250 mm/s,
    because a Unit carries the dimension but not the scale.
    """
    quantity = FreeCAD.Units.Quantity("{!r} {}".format(float(value), unit))
    back = _value(quantity, unit)
    if abs(back - value) > 1e-9 * max(1.0, abs(value)):
        raise ProjectError(
            "unit conversion failed: {} {} became {} {}".format(value, unit, back, unit)
        )
    return quantity


class ToolNumberTaken(ProjectError):
    """The T number is already used by another variant in the project."""

    def __init__(self, existing, wanted):
        self.existing = existing  # ProjectTool
        self.wanted = wanted  # LibraryTool
        super().__init__(
            "T{} is already in the project: {}{}".format(
                existing.number,
                existing.tool.name,
                " ({})".format(existing.workpiece_material) if existing.workpiece_material else "",
            )
        )


class ProjectTool(NamedTuple):
    controller: object  # FreeCAD tool controller
    number: int
    tool: model_tools.Tool
    library_id: str  # "" for a tool not made from the library
    workpiece_material: str


# -- finding things ----------------------------------------------------------

# helper objects AvangardeCam adds to the document carry their role here
_ROLE_PROPERTY = "AvangardeRole"
CONTOUR_GEOMETRY = "contour-geometry"
HOLE_GEOMETRY = "hole-geometry"


_JOB_PARTS = ("Model", "Stock", "Tools", "Operations")


def _is_job(obj):
    """A complete CAM Job; while FreeCAD builds one, observers already see
    the object before all its properties exist."""
    import Path.Main.Job as PathJob

    return isinstance(getattr(obj, "Proxy", None), PathJob.ObjectJob) and all(
        getattr(obj, name, None) is not None for name in _JOB_PARTS
    )


def setups(doc):
    """The project's setups (CAM Jobs) in the order they were made."""
    if doc is None:
        return []
    return [obj for obj in doc.Objects if _is_job(obj)]


def find_job(doc):
    """The first setup, or None."""
    found = setups(doc)
    return found[0] if found else None


def setup_of(obj):
    """The setup (Job) an object of a Job belongs to, or None."""
    for job in setups(obj.Document):
        if obj is job or obj is job.Stock or obj in job.Model.Group:
            return job
        if obj in job.Tools.Group or obj in job.Operations.Group:
            return job
    return None


def _shape(obj):
    import Part

    try:
        return Part.getShape(obj)
    except Exception:
        return None


def _original(clone):
    """The object a Job model clone was made from (the clone if unknown)."""
    objects = getattr(clone, "Objects", None)
    return objects[0] if objects else clone


def models(doc):
    """The solid models of the project, as the user sees them in 3D."""
    if doc is None:
        return []
    job = find_job(doc)
    if job is not None and job.Model is not None:
        return [_original(clone) for clone in job.Model.Group]
    result = []
    for obj in doc.RootObjects:
        if obj.TypeId.startswith("Path::") or obj.TypeId == "App::Origin":
            continue
        if geometry.is_sketch(obj) or getattr(obj, _ROLE_PROPERTY, ""):
            continue
        shape = _shape(obj)
        if shape is not None and not shape.isNull():
            result.append(obj)
    return result


def bounds(obj):
    box = _shape(obj).BoundBox
    return model_stock.Bounds(box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def owner(obj):
    """Map a selected FreeCAD object to the project entry it belongs to.

    Returns ("model", original), ("sketch", sketch), ("setup", job),
    ("stock", stock object), ("tool", tool controller), ("operation", op)
    or None.
    """
    doc = obj.Document
    if getattr(obj, "PathResource", None) == "Model":
        return ("model", _original(obj))
    if geometry.is_sketch(obj):
        # a sketch inside a body is a feature of that body (e.g. a tool shape)
        return ("sketch", obj) if obj.getParentGeoFeatureGroup() is None else None
    for job in setups(doc):
        if obj is job:
            return ("setup", job)
        if obj is job.Stock:
            return ("stock", obj)
        for tc in job.Tools.Group:
            if obj is tc or obj is getattr(tc, "Tool", None):
                return ("tool", tc)
        for op in job.Operations.Group:
            if obj is op or obj in helper_objects(op):
                return ("operation", op)
    if obj in models(doc):
        return ("model", obj)
    return None


def model_element(top, sub):
    """(model, "FaceN" or "EdgeN") of a face or edge of a project model
    selected in 3D, else None.

    FreeCAD names a selected element from the object clicked at the top
    (top, sub as getSelectionEx("", 0) gives them): "Face3" of a model or
    its Job clone, but "Part__Feature.Face1" of a model made of other
    objects (an App::Part from a STEP file, a Body in a Part). The element
    is then found again in the model's own shape: the one of the same
    topology (OCCT partner), the nearest one when several are. An object
    inside a model works too ("Face1" of the Part__Feature in it), as
    FreeCAD's selection observers name it."""
    top, sub = model_path(top, plain_sub(sub))
    names = sub.split(".")
    element = names[-1]
    if not element.startswith(("Face", "Edge")):
        return None
    obj, path = top, names[:-1]
    while True:
        found = owner(obj)
        if found is not None and found[0] == "model":
            model = found[1]
            break
        if not path:
            return None
        obj = top.Document.getObject(path[0])
        path = path[1:]
        if obj is None:
            return None
    if not path:
        return model, element  # the model's (or its clone's) own element
    try:
        picked = _shape_element(obj, ".".join(path + [element]))
    except Exception:
        return None
    whole = _shape(model)
    if picked is None or whole is None:
        return None
    kind = "Face" if element.startswith("Face") else "Edge"
    elements = whole.Faces if kind == "Face" else whole.Edges
    partners = [i for i, e in enumerate(elements) if e.isPartner(picked)]
    if not partners:
        return None
    centre = picked.BoundBox.Center
    best = min(partners, key=lambda i: (elements[i].BoundBox.Center - centre).Length)
    return model, "{}{}".format(kind, best + 1)


def plain_sub(sub):
    """A selection's subname without FreeCAD's topological names: an
    unresolved click gives "Part__Feature.;#a:1;:G;XTR;:H1,F.Face1" for
    "Part__Feature.Face1"."""
    return ".".join(n for n in sub.split(".") if not n.startswith(";"))


def model_path(obj, sub):
    """(top object, sub) naming the element sub of obj from the project
    model obj lies in (its App::Part, its Body, ...); obj and sub when obj
    is in none."""
    sub = plain_sub(sub)
    path, up = sub, obj
    while up is not None:
        found = owner(up)
        if found is not None and found[0] == "model":
            return up, path
        parent = up.getParentGeoFeatureGroup()
        if parent is not None:
            path = "{}.{}".format(up.Name, path)
        up = parent
    return obj, sub


def _shape_element(obj, sub):
    import Part

    return Part.getShape(obj, sub, needSubElement=True)


# -- setups --------------------------------------------------------------------


def ensure_job(doc, model_objects=None):
    """Return the first setup, creating it for the given models if needed.

    Its zero point is on top of the models, in the middle.
    """
    job = find_job(doc)
    if job is not None:
        return job
    model_objects = model_objects if model_objects is not None else models(doc)
    if not model_objects:
        raise ProjectError("A project needs a model before it can get a setup, stock or tools.")
    return new_setup(doc, geometry.zero_on_top(model_objects), model_objects)


def new_setup(doc, zero_point, model_objects=None):
    """A new setup (CAM Job) of the project's models with the given zero point.

    It gets the default stock of the model layer and no tools: FreeCAD's
    default 5 mm end mill is not one of the shop's tools.
    """
    model_objects = model_objects if model_objects is not None else models(doc)
    if not model_objects:
        raise ProjectError("A project needs a model before it can get a setup, stock or tools.")
    number = len(setups(doc)) + 1
    if FreeCAD.ActiveDocument is not doc:
        FreeCAD.setActiveDocument(doc.Name)
    import Path.Main.Job as PathJob

    with _no_default_tool():
        job = PathJob.Create("Job", model_objects, None)
    if job is not None and FreeCAD.GuiUp:
        import Path.Main.Gui.Job as PathJobGui

        # as PathJobGui.Create does, without its own undo step "Create Job": the
        # caller's transaction (Snap-0-Point, Next setup) holds the whole setup
        job.ViewObject.Proxy = PathJobGui.ViewProvider(job.ViewObject)
        job.ViewObject.addExtension("Gui::ViewProviderGroupExtensionPython")
        job.ViewObject.Proxy.deleteOnReject = False
    if job is None:
        raise ProjectError("FreeCAD could not create the CAM job.")
    job.Label = "Setup {}".format(number)
    for tc in list(job.Tools.Group):
        _remove_controller(tc)
    _move_clones(job, zero_point)
    set_stock(job, model_stock.BoxStock())
    return job


@contextlib.contextmanager
def _no_default_tool():
    """While FreeCAD makes a Job, it makes no 5 mm end mill: not one of the
    shop's tools, and its tool bit (a PartDesign body read from a file)
    commits the transaction open in the GUI, so a new setup would take
    several undo steps, the last ones half undone."""
    import Path.Main.Job as PathJob

    controllers = PathJob.PathToolController
    create, add = controllers.Create, PathJob.ObjectJob.addToolController
    controllers.Create = lambda *args, **kwargs: None
    PathJob.ObjectJob.addToolController = lambda self, tc: None if tc is None else add(self, tc)
    try:
        yield
    finally:
        controllers.Create = create
        PathJob.ObjectJob.addToolController = add


def add_model(doc, obj):
    """Add an imported model to every setup (their stock grows with it)."""
    import Path.Main.Job as PathJob

    if obj in models(doc):
        return
    for job in setups(doc):
        clone = PathJob.createModelResourceClone(job, obj)
        clone.Placement = zero(job).inverse().multiply(obj.Placement)
        job.Model.addObject(clone)
        doc.recompute()
        _place_stock(job)
        _sync_operations(job)
    doc.recompute()


# -- zero point ----------------------------------------------------------------


def zero(job):
    """The setup's zero point: a placement in part coordinates whose Z axis
    is the side the tool comes from. Read from the Job's model clones, so a
    Job set up in FreeCAD itself is understood too."""
    for clone in job.Model.Group:
        original = _original(clone)
        if original is not clone:
            return original.Placement.multiply(clone.Placement.inverse())
    return FreeCAD.Placement()


def _move_clones(job, zero_point):
    inverse = zero_point.inverse()
    for clone in job.Model.Group:
        clone.Placement = inverse.multiply(_original(clone).Placement)
    job.Document.recompute()


def set_zero(job, zero_point):
    """Move the setup's zero point; its stock and operations follow.

    The tool axis of a setup with contours can only turn round: their
    sketches must lie level in it (facing the tool or away from it).
    Another change needs a new setup.
    """
    _op_zero().before_setup_move(job)
    axis = geometry.tool_axis(zero_point)
    if not geometry.same_direction(axis, geometry.tool_axis(zero(job))):

        def level(sketch):
            tool = geometry.tool_axis(sketch.Placement)
            return geometry.same_direction(tool, axis) or geometry.opposite_direction(tool, axis)

        users = [
            op.Label for op in job.Operations.Group
            if contour_of(op) is not None  # the oldest ones, on a clone of the sketch, cannot turn round
            and not _op_zero().parked(op)  # it stays on its own zero point
            and not (helper_objects(op) and all(level(sketch) for sketch, _names in contour_sketches(op)))
        ]  # fmt: skip
        if users:
            raise ProjectError(
                "{} has operations on sketches that would not lie across the new tool axis ({}). A zero "
                "point with that tool axis needs a new setup.".format(job.Label, ", ".join(users))
            )
    _move_clones(job, zero_point)
    _place_stock(job)
    _sync_operations(job)
    job.Document.recompute()
    _op_zero().after_setup_move(job)


def rotate_zero(job, degrees):
    """Turn the setup's zero point about its Z axis through X0 Y0; positive
    degrees counter-clockwise seen from the tool. Stock and operations follow.

    At a quarter turn the stock's allowances turn with the axes, so the block
    stays the same block (303 × 96 does not become 303.5 × 95.5 when X and Y
    allowances differ). At another angle they stay with the axes.
    """
    box = stock(job)
    turned = model_frame.rotated_about_z(geometry.frame_of(zero(job)), degrees)
    set_zero(job, geometry.placement(turned))
    if box is not None:
        kept = box.turned_about_z(degrees)
        if kept is not None and kept != box:
            set_stock(job, kept)


def zero_rotation(job):
    """Degrees the zero point is turned about Z from where Snap-0-Point puts it."""
    return model_frame.rotation_about_z(geometry.frame_of(zero(job)))


# -- stock ---------------------------------------------------------------------


def stock(job):
    """The project's stock as a BoxStock, or None when the Job's stock is of
    another kind (a box or cylinder of fixed size made in FreeCAD)."""
    if job is None or job.Stock is None or not hasattr(job.Stock, "ExtXneg"):
        return None
    s = job.Stock
    return model_stock.BoxStock(
        _value(s.ExtXneg, "mm"),
        _value(s.ExtXpos, "mm"),
        _value(s.ExtYneg, "mm"),
        _value(s.ExtYpos, "mm"),
        _value(s.ExtZneg, "mm"),
        _value(s.ExtZpos, "mm"),
    )


def set_stock(job, box):
    """Make the Job's stock the model box plus the allowances of box."""
    import Path.Main.Stock as PathStock

    box.validate()
    doc = job.Document
    if job.Stock is None or not hasattr(job.Stock, "ExtXneg"):
        old = job.Stock
        job.Stock = PathStock.CreateFromBase(job)
        if old is not None:
            _next_setup().forget(old)
            doc.removeObject(old.Name)
    s = job.Stock
    s.ExtXneg = _quantity(box.x_neg_mm, "mm")
    s.ExtXpos = _quantity(box.x_pos_mm, "mm")
    s.ExtYneg = _quantity(box.y_neg_mm, "mm")
    s.ExtYpos = _quantity(box.y_pos_mm, "mm")
    s.ExtZneg = _quantity(box.z_neg_mm, "mm")
    s.ExtZpos = _quantity(box.z_pos_mm, "mm")
    _place_stock(job)
    _op_zero().stock_changed(job)  # the stock's block, kept for the setup's other zero points
    _sync_operations(job)
    _show_stock(s)
    doc.recompute()


def _place_stock(job):
    """Put the stock box around the clones again: FreeCAD places a stock made
    from the model only once, when it is created."""
    import Path.Main.Stock as PathStock

    s = job.Stock
    if _next_setup().place(job):  # a stock left by another setup, a blank's model
        return
    if s is None or not hasattr(s, "ExtXneg") or not job.Model.Group:
        return
    box = PathStock.shapeBoundBox(job.Model.Group)
    s.Placement = FreeCAD.Placement(FreeCAD.Vector(box.XMin, box.YMin, box.ZMin), FreeCAD.Rotation())
    s.Proxy.execute(s)


def stock_bounds(job):
    box = job.Stock.Shape.BoundBox
    return model_stock.Bounds(box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)


def _show_stock(obj):
    """Stock is shown as a faint box that clicks go through, so faces of the
    model inside stay pickable."""
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    vo.Visibility = True
    vo.Transparency = 85
    if hasattr(vo, "Selectable"):
        vo.Selectable = False


# -- tools -----------------------------------------------------------------------

_ID_PROPERTY = "AvangardeToolId"
_MATERIAL_PROPERTY = "AvangardeMaterial"
_NAME_PROPERTY = "AvangardeToolName"

_SHAPE_FILES = {
    "Endmill": "endmill.fcstd",
    "Bullnose": "bullnose.fcstd",
    "Ballend": "ballend.fcstd",
    "Drill": "drill.fcstd",
    "Chamfer": "chamfer.fcstd",
    "VBit": "v-bit.fcstd",
    "ThreadMill": "thread-mill.fcstd",
}
_LENGTHS = (
    ("Diameter", "diameter_mm"),
    ("CornerRadius", "corner_radius_mm"),
    ("TipDiameter", "tip_diameter_mm"),
    ("CuttingEdgeHeight", "cutting_length_mm"),
    ("Length", "length_mm"),
    ("ShankDiameter", "shank_diameter_mm"),
    ("NeckDiameter", "neck_diameter_mm"),
    ("NeckLength", "neck_length_mm"),
)
# FreeCAD's thread mill has no pitch: it is kept in an extra property of the bit
_PITCH_PROPERTY = "Pitch"

_assets_ready = False


def _ensure_assets():
    """Set up FreeCAD's CAM assets (tool shapes) as the CAM workbench does
    when it loads; AvangardeCam may run without it ever loading."""
    global _assets_ready
    if not _assets_ready:
        from Path.Tool.camassets import cam_assets

        cam_assets.setup()
        _assets_ready = True


def _angle_property(shape):
    if shape == "ThreadMill":
        return "cuttingAngle"
    return "TipAngle" if shape == "Drill" else "CuttingEdgeAngle"


def _toolbit_dict(tool):
    """The tool as a FreeCAD tool bit description (the .fctb layout)."""
    parameters = {}
    for name, field in _LENGTHS:
        value = getattr(tool, field)
        if value is not None:
            parameters[name] = "{:.4f} mm".format(value)
    if tool.angle_deg is not None:
        parameters[_angle_property(tool.shape)] = "{:.4f} °".format(tool.angle_deg)
    if tool.flutes:
        parameters["Flutes"] = str(tool.flutes)
    if tool.tool_material:
        parameters["Material"] = tool.tool_material
    return {
        "version": 2,
        "name": tool.name,
        "shape": _SHAPE_FILES[tool.shape],
        "shape-type": tool.shape,
        "parameter": parameters,
        "attribute": {},
    }


def _unique_label(obj, text, job):
    """text, or "text (Setup 2)" when another object of the document has it:
    FreeCAD keeps labels unique and would add a number instead."""
    taken = {o.Label for o in obj.Document.Objects if o is not obj}
    return text if text not in taken else "{} ({})".format(text, job.Label)


def _make_bit(job, tool):
    from Path.Tool.toolbit import ToolBit

    _ensure_assets()
    bit = ToolBit.from_dict(_toolbit_dict(tool.validate())).attach_to_doc(doc=job.Document)
    bit.Label = _unique_label(bit, tool.name, job)
    if tool.pitch_mm is not None:
        _add_property(bit, "App::PropertyLength", _PITCH_PROPERTY, "Thread pitch of the tool")
        setattr(bit, _PITCH_PROPERTY, _quantity(tool.pitch_mm, "mm"))
    if getattr(bit, "ViewObject", None) is not None:
        bit.ViewObject.Visibility = False
    return bit


def _label(entry):
    return "T{}: {}".format(entry.number, entry.tool.name)


def _apply(tc, entry, job):
    """Cutting data and library reference of a variant onto a tool controller."""
    tool = entry.tool
    if tool.spindle_rpm:
        tc.SpindleSpeed = float(tool.spindle_rpm)
    if tool.feed_xy_mm_min:
        tc.HorizFeed = _quantity(tool.feed_xy_mm_min, "mm/min")
    if tool.feed_z_mm_min:
        tc.VertFeed = _quantity(tool.feed_z_mm_min, "mm/min")
    for name, value, tip in (
        (_ID_PROPERTY, entry.id, "AvangardeCam tool library variant this tool was made from"),
        (_MATERIAL_PROPERTY, entry.workpiece_material, "Workpiece material of the cutting data"),
        (_NAME_PROPERTY, tool.name, "Name of the tool in the shop's tool library"),
    ):
        _add_property(tc, "App::PropertyString", name, tip)
        setattr(tc, name, value)
    tc.Label = _unique_label(tc, _label(entry), job)


def _tool_from_controller(tc):
    """The tool as FreeCAD will use it: geometry from the tool bit, speeds and
    feeds from the tool controller."""
    bit = tc.Tool

    def mm(name):
        value = getattr(bit, name, None)
        if isinstance(value, str):
            # a parameter the shape does not know (the thread mill's
            # CuttingEdgeHeight) is kept by FreeCAD as text, e.g. "2.7000 mm"
            value = FreeCAD.Units.Quantity(value) if value else None
        return _value(value, "mm") if value is not None else None

    shape = str(getattr(bit, "ShapeType", "") or "")
    angle = getattr(bit, _angle_property(shape), None)
    flutes = getattr(bit, "Flutes", None)
    return model_tools.Tool(
        name=getattr(tc, _NAME_PROPERTY, "") or bit.Label,
        shape=shape,
        diameter_mm=mm("Diameter"),
        flutes=int(flutes) if flutes not in (None, "") else None,
        corner_radius_mm=mm("CornerRadius"),
        angle_deg=_value(angle, "deg") if angle is not None else None,
        tip_diameter_mm=mm("TipDiameter"),
        cutting_length_mm=mm("CuttingEdgeHeight"),
        length_mm=mm("Length"),
        shank_diameter_mm=mm("ShankDiameter"),
        neck_diameter_mm=mm("NeckDiameter"),
        neck_length_mm=mm("NeckLength"),
        pitch_mm=mm(_PITCH_PROPERTY),
        tool_material=str(getattr(bit, "Material", "") or ""),
        spindle_rpm=float(tc.SpindleSpeed) or None,
        feed_xy_mm_min=_value(tc.HorizFeed, "mm/min") or None,
        feed_z_mm_min=_value(tc.VertFeed, "mm/min") or None,
    )


def project_tools(job):
    """The tools of the project, ordered by tool number."""
    if job is None or job.Tools is None:
        return []
    result = [
        ProjectTool(
            tc,
            int(tc.ToolNumber),
            _tool_from_controller(tc),
            getattr(tc, _ID_PROPERTY, ""),
            getattr(tc, _MATERIAL_PROPERTY, ""),
        )
        for tc in job.Tools.Group
        if getattr(tc, "Tool", None) is not None
    ]
    result.sort(key=lambda t: t.number)
    return result


def tool_with_number(job, number):
    return next((t for t in project_tools(job) if t.number == number), None)


def add_tool(job, entry):
    """Add a library variant (LibraryTool) to the project under its T number.

    Raises ToolNumberTaken when another variant already has the number:
    the machine knows one tool per number, so a project has one variant.
    """
    import Path.Tool.Controller as PathToolController

    existing = tool_with_number(job, entry.number)
    if existing is not None:
        raise ToolNumberTaken(existing, entry)
    bit = _make_bit(job, entry.tool)
    tc = PathToolController.Create(_label(entry), tool=bit, toolNumber=entry.number)
    _apply(tc, entry, job)
    job.Proxy.addToolController(tc)
    job.Document.recompute()
    return tc


def replace_tool(job, tc, entry):
    """Make a project tool another variant of the same T number.

    The tool controller stays, so operations using it keep working and get
    the new variant's geometry, spindle speed and feeds.
    """
    if int(tc.ToolNumber) != entry.number:
        raise ProjectError(
            "T{} cannot be replaced by T{}: a variant keeps its number".format(
                int(tc.ToolNumber), entry.number
            )
        )
    doc = job.Document
    old_bit = tc.Tool
    tc.Tool = _make_bit(job, entry.tool)
    if hasattr(tc.Tool, "SpindleDirection"):
        tc.SpindleDir = tc.Tool.SpindleDirection
    _apply(tc, entry, job)
    if old_bit is not None and not old_bit.InList:
        _remove_bit(old_bit)
    _sync_operations(job)  # a compensated contour follows the new radius
    doc.recompute()
    return tc


def library_tool(job, entry, replace=False):
    """The setup's tool controller of a library variant: the one made from
    it, else a new one under its T number. When another variant has the
    number: ToolNumberTaken, or with replace that tool controller becomes
    this variant (replace_tool)."""
    existing = tool_with_number(job, entry.number)
    if existing is None:
        return add_tool(job, entry)
    if existing.library_id == entry.id:
        return existing.controller
    if not replace:
        raise ToolNumberTaken(existing, entry)
    return replace_tool(job, existing.controller, entry)


def remove_tool(job, tc):
    """Remove a tool from the project unless an operation still uses it."""
    users = [op.Label for op in job.Operations.Group if getattr(op, "ToolController", None) is tc]
    if users:
        raise ProjectError("{} is used by: {}".format(tc.Label, ", ".join(users)))
    _remove_controller(tc)
    job.Document.recompute()


def _remove_controller(tc):
    doc = tc.Document
    tool = getattr(tc, "Tool", None)
    doc.removeObject(tc.Name)
    if tool is not None and not tool.InList:
        _remove_bit(tool)


def _remove_bit(bit):
    """Remove a tool bit and the shape body FreeCAD built for it (Body,
    sketch, revolution, origin): removeObject() alone leaves the body
    behind, only deleting it in FreeCAD's tree cleans it up."""
    doc = bit.Document
    body = getattr(bit, "BitBody", None)
    doc.removeObject(bit.Name)
    if body is not None and body.isValid():
        body.removeObjectsFromDocument()
        doc.removeObject(body.Name)


# -- operations ------------------------------------------------------------------

_OPERATION_PROPERTY = "AvangardeOperation"
_SKETCH_PROPERTY = "AvangardeSketch"
_MODEL_PROPERTY = "AvangardeModel"  # a drilling of holes picked in a model


def _add_property(obj, kind, name, tip, read_only=True):
    if not hasattr(obj, name):
        obj.addProperty(kind, name, "AvangardeCam", tip)
        if read_only:
            obj.setEditorMode(name, 1)  # read-only in FreeCAD's property editor


def operations(job):
    return list(job.Operations.Group) if job is not None else []


def sketch_fits(job, sketch):
    """True when the sketch faces the tool of the setup."""
    return geometry.same_direction(geometry.tool_axis(sketch.Placement), geometry.tool_axis(zero(job)))


def setups_for_sketch(doc, sketch):
    return [job for job in setups(doc) if sketch_fits(job, sketch)]


def sketch_faces_away(job, sketch):
    """True when the sketch faces away from the setup's tool (a face of the
    part's bottom in a setup from the top): a contour still follows its
    lines, seen from the tool's side (geometry.facing_tool)."""
    return geometry.opposite_direction(geometry.tool_axis(sketch.Placement), geometry.tool_axis(zero(job)))


def contour_fits(job, sketch):
    """True when a contour of the setup can follow the sketch's lines: they
    lie level in it, the sketch facing the tool or away from it. The sketch
    has no zero point of its own: its lines are where they are on the part."""
    return sketch_fits(job, sketch) or sketch_faces_away(job, sketch)


def setups_for_contour(doc, sketch):
    """Setups a contour can follow the sketch's lines in, the ones it faces
    first."""
    jobs = [job for job in setups(doc) if contour_fits(job, sketch)]
    return sorted(jobs, key=lambda job: not sketch_fits(job, sketch))


def _operation_of(op, kind):
    """(sketch or model, model operation) of an operation AvangardeCam made
    as kind, else None."""
    text = getattr(op, _OPERATION_PROPERTY, "")
    sketch = getattr(op, _SKETCH_PROPERTY, None) or getattr(op, _MODEL_PROPERTY, None)
    if not text or sketch is None:
        return None
    operation = model_operations.from_json(text)
    if not isinstance(operation, kind):
        return None
    return sketch, operation


def contour_of(op):
    """(sketch, model Contour) of a contour made by AvangardeCam, else None."""
    return _operation_of(op, model_operations.Contour)


def drilling_of(op):
    """(sketch, model Drilling) of a drilling made by AvangardeCam, else None;
    (model, model Drilling) for holes picked in a model."""
    return _operation_of(op, model_operations.Drilling)


def _next_label(doc, text):
    """"Contour 1", "Contour 2", ...: the first one not in the document."""
    labels = {o.Label for o in doc.Objects}
    number = next(n for n in range(1, len(labels) + 2) if "{} {}".format(text, n) not in labels)
    return "{} {}".format(text, number)


def _helper(obj, role, label):
    _add_property(obj, "App::PropertyString", _ROLE_PROPERTY, "What AvangardeCam uses this object for")
    setattr(obj, _ROLE_PROPERTY, role)
    obj.Label = label
    if getattr(obj, "ViewObject", None) is not None:
        obj.ViewObject.Visibility = False
    return obj


def _user_values(op, sketch, operation, tip, link=_SKETCH_PROPERTY):
    _add_property(op, "App::PropertyString", _OPERATION_PROPERTY, "The operation as the user set it up in AvangardeCam")
    _add_property(op, "App::PropertyLink", link, tip)
    setattr(op, link, sketch)
    setattr(op, _OPERATION_PROPERTY, model_operations.to_json(operation))


def _attach_op_view(op):
    """FreeCAD's own view provider, so the operation looks and edits as
    usual in plain FreeCAD."""
    import Path.Op.Gui.Base as PathOpGui
    import Path.Op.Gui.Engrave as PathEngraveGui

    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, PathEngraveGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False


def _contour_lines(doc, sketch, names, reversed_, label):
    """Helper object with the lines of a sketch the tool follows."""
    obj = doc.addObject("Part::FeaturePython", "ContourLines")
    geometry.ContourLines(obj)
    obj.Sketch = sketch
    obj.Edges = list(names)
    obj.Reversed = reversed_
    return _helper(obj, CONTOUR_GEOMETRY, label)


def add_contour(job, sketch, contour, tc, lines=(), backwards=()):
    """Contour tooling: the tool follows lines of the sketch from
    contour.start_z_mm down to contour.z_depth_mm (both from the Z of the
    lines, above them or below; not contour.relative: from the setup's
    zero point), by its Z levels: its centre on
    them, or beside them with contour.compensation (RL/RR).

    lines: names of the sketch's lines ("Edge3") in the order the user
    picked them; the tool starts on the first and ends on the last. Lines
    that do not meet are run one chain after the other. No lines: all of
    the sketch's lines. backwards: names of lines whose chain the tool
    runs the other way round (geometry.line_runs).

    Made of FreeCAD's Engrave operation on helper objects holding the lines
    (one per chain, so Engrave keeps their order), moved into the setup's
    coordinates. With compensation the helpers hold where the tool centre
    goes (the lines moved by the tool radius, with the lead arcs), so the
    path in 3D and the simulation show the cut; the NC program has the
    lines themselves with RL/RR (nc_moves).
    """
    return add_contour_sketches(job, [(sketch, lines, backwards)], contour, tc)


def add_contour_sketches(job, picks, contour, tc, name="Contour"):
    """Contour tooling on lines of several sketches (add_contour): picks
    are (sketch, lines, backwards) in the tool's order, sketch after
    sketch. Relative, Start Z and Z-Depth are from each sketch's own plane,
    so lines of faces at other heights are cut each as deep below its face;
    not relative, from the zero point, so all as deep. name: of the
    operation ("Contour 1"; engine.deburring: "Deburring 1")."""
    from avangardecam.engine import contour as engine_contour

    contour.validate()
    if not picks:
        raise ProjectError("No sketch lines to follow.")
    for sketch, _lines, _backwards in picks:
        if not contour_fits(job, sketch):
            raise ProjectError(
                "{} does not lie level in {}: its lines are not across the tool. Select the sketch's face and "
                "use Snap-0-Point first.".format(sketch.Label, job.Label)
            )
    if tc not in job.Tools.Group:
        raise ProjectError("{} is not a tool of {}.".format(tc.Label, job.Label))
    runs = []  # (sketch, chain, backwards) of each helper
    for sketch, lines, backwards in picks:
        lines = list(lines)
        backwards = set(backwards)
        if backwards and not lines:
            lines = geometry.all_lines(sketch)  # each chain keeps its own direction
        _check_fit(sketch, lines, backwards, contour, tc, sketch_faces_away(job, sketch))
        chains = geometry.line_chains(sketch, lines) if lines else [[]]
        runs += [(sketch, chain, bool(backwards & set(chain))) for chain in chains]
    doc = job.Document
    label = _next_label(doc, name)

    helpers = []
    for i, (sketch, chain, reversed_) in enumerate(runs, start=1):
        part = " {}".format(i) if len(runs) > 1 else ""
        helpers.append(_contour_lines(doc, sketch, chain, reversed_, "{} lines{} ({})".format(label, part, job.Label)))

    op = doc.addObject("Path::FeaturePython", name)
    op.Proxy = engine_contour.Contour(op, name, job, tc)
    if FreeCAD.GuiUp:
        _attach_op_view(op)
    op.Label = label
    op.BaseShapes = helpers
    op.ToolController = tc
    # depths come from the lines (or the zero point) and the user's Z-Depth and passes
    for name in ("StartDepth", "FinalDepth", "StepDown"):
        op.setExpression(name, None)
    _user_values(op, picks[0][0], contour, "Sketch the tool follows (the first one)")
    _sync_contour(job, op)
    doc.recompute()
    return op


def contour_sketches(op):
    """(sketch, names of its lines in the tool's order) a contour follows,
    sketch by sketch in the tool's order; [] names for all its lines."""
    found = []
    for helper in helper_objects(op):
        edges = list(getattr(helper, "Edges", []))
        names = list(reversed(edges)) if getattr(helper, "Reversed", False) else edges
        if found and found[-1][0] is helper.Sketch:
            found[-1][1].extend(names)
        else:
            found.append((helper.Sketch, names))
    return found


def contour_planes(op):
    """Z of the planes of a contour's sketches in the setup's coordinates,
    highest first (one for a contour on one sketch's plane)."""
    levels = []
    for helper in helper_objects(op):
        z = helper.Placement.Base.z
        if not any(abs(z - level) < 1e-6 for level in levels):
            levels.append(z)
    return sorted(levels, reverse=True)


def contour_lines(op):
    """Names of the sketch lines a contour follows, in the tool's order;
    [] when it follows all of them."""
    names = []
    for helper in helper_objects(op):
        edges = list(getattr(helper, "Edges", []))
        names.extend(reversed(edges) if getattr(helper, "Reversed", False) else edges)
    return names


def set_contour_tool(op, tc):
    """Another tool of its setup for a contour. Its approach radius follows
    the tool unless the user set it."""
    job = setup_of(op)
    if job is None or tc not in job.Tools.Group:
        raise ProjectError("{} is not a tool of {}.".format(tc.Label, job.Label if job else "the setup"))
    _sketch, contour = contour_of(op)
    for helper in helper_objects(op):
        names, backwards = geometry.helper_lines(helper)
        _check_fit(helper.Sketch, names, backwards, contour, tc, getattr(helper, "Flipped", False))
    op.ToolController = tc
    _sync_contour(job, op)
    op.Document.recompute()


def set_contour(op, contour):
    """Change the user's values of a contour."""
    contour.validate()
    if not helper_objects(op) and (len(contour.xy_offsets()) > 1 or contour.offset_xy_mm or contour.finish_z_mm):
        raise ProjectError("{} is from an older version: make it again for XY passes.".format(op.Label))
    for helper in helper_objects(op):
        names, backwards = geometry.helper_lines(helper)
        _check_fit(helper.Sketch, names, backwards, contour, op.ToolController, getattr(helper, "Flipped", False))
    setattr(op, _OPERATION_PROPERTY, model_operations.to_json(contour))
    _sync_contour(setup_of(op), op)
    op.Document.recompute()


def _sync_operations(job):
    """The operations follow a new zero point, stock or tool. One that
    counts from another zero point than the active one waits for it
    (engine.op_zero)."""
    for op in job.Operations.Group:
        if _op_zero().parked(op):
            continue
        if _deburring().deburring_of(op) is not None:
            _deburring().follow_tool(op)  # its depth and offset come from the tool's cone
            _sync_contour(job, op)
        elif contour_of(op) is not None:
            _sync_contour(job, op)
        elif drilling_of(op) is not None:
            _sync_drilling(job, op)
        elif thread_milling_of(op) is not None:
            _sync_thread_milling(job, op)
        elif adaptive_of(op) is not None:
            _sync_adaptive(job, op)
        elif _facing().facing_of(op) is not None:
            _facing().sync(job, op)
        elif _slot().slot_milling_of(op) is not None:
            _slot().sync(job, op)
        elif _helix().helix_milling_of(op) is not None:
            _helix().sync(job, op)


def _tool_radius(tc):
    """Radius of a tool controller's tool in mm, 0 without one."""
    bit = getattr(tc, "Tool", None)
    diameter = getattr(bit, "Diameter", None)
    return _value(diameter, "mm") / 2.0 if diameter is not None else 0.0


def _lead_radius(contour, tc):
    """Radius of a contour's approach arcs, mm: the user's, or by default
    the tool goes down 0.5 mm clear of the lines."""
    if contour.lead_radius_mm is not None:
        return contour.lead_radius_mm
    return model_leads.default_radius(_tool_radius(tc))


def lead_radius(op):
    """Radius of a contour's approach arcs, mm, as the tool runs them."""
    return _lead_radius(contour_of(op)[1], op.ToolController)


def _runs(sketch, names, backwards, contour, tc, flipped=False):
    """Run of each chain and XY pass (chain by chain, pass by pass);
    flipped: the sketch faces away from the tool (geometry.facing_tool)."""
    offsets = contour.xy_offsets()  # without compensation only the XY offset
    return geometry.contour_runs(
        sketch, names, backwards, contour.compensation, contour.approach, _lead_radius(contour, tc), _tool_radius(tc),
        offsets, contour.arc_side, contour.start_extend_mm, contour.end_extend_mm, flipped,
    )  # fmt: skip


def _check_fit(sketch, names, backwards, contour, tc, flipped=False):
    """Raise ProjectError when the tool cannot run the lines with the
    contour's compensation, approach and passes (too big for them, or too
    small for the XY step)."""
    radius = _tool_radius(tc)
    if contour.compensation != model_operations.OFF and radius <= 0.0:
        raise ProjectError("{} has no diameter for the radius compensation.".format(tc.Label))
    for text, width in (("XY step", contour.rough_step_mm()), ("finishing allowance in XY", contour.finish_xy_mm)):
        if width is not None and width > 2.0 * radius + 1e-9:
            raise ProjectError(
                "The {} ({:g} mm) is wider than the tool ({:g} mm): it would leave material between the "
                "passes.".format(text, round(width, 3), 2.0 * radius)
            )
    _runs(sketch, names, backwards, contour, tc, flipped)


def contour_cuts(op):
    """The cuts of a contour in the tool's order, chain by chain: for each
    chain a list of (XY pass, Run in the setup's coordinates, Z) (model
    Contour.cuts). None for a contour without AvangardeCam's helpers."""
    found = contour_of(op)
    helpers = helper_objects(op)
    if found is None or not helpers:
        return None
    contour = found[1]
    cuts = contour.cuts()
    chains = []
    for helper in helpers:
        to_setup = helper.Placement.toMatrix()
        # the sketch faces the tool: its plane is level, the Z of its lines
        base = contour.base_mm(helper.Placement.Base.z)
        names, backwards = geometry.helper_lines(helper)
        passes = {}
        for run in _runs(helper.Sketch, names, backwards, contour, op.ToolController, getattr(helper, "Flipped", False)):
            run = run._replace(
                program=[e.transformed(to_setup) for e in run.program],
                centre=[e.transformed(to_setup) for e in run.centre],
            )
            passes.setdefault(run.chain, []).append(run)
        for chain in sorted(passes):
            runs = passes[chain]
            # without compensation one run for all the XY passes (only one then)
            chains.append([(p, runs[min(p, len(runs) - 1)], base + z) for p, z in cuts])
    return chains


def _sync_contour(job, op):
    """Sketch clone, depths and heights of a contour from its sketch, the
    user's Z-Depth (relative or not) and compensation, the tool's radius,
    the setup's zero point and its stock."""
    import Path.Op.Engrave as PathEngrave

    from avangardecam.engine import contour as engine_contour

    sketch, contour = contour_of(op)
    if type(op.Proxy) is PathEngrave.ObjectEngrave and helper_objects(op):
        op.Proxy.__class__ = engine_contour.Contour  # older documents: FreeCAD's Engrave, which sorts the cuts
    to_setup = zero(job).inverse()
    place = to_setup.multiply(sketch.Placement)
    tc = op.ToolController
    for helper in helper_objects(op):
        geometry.add_compensation(helper)  # older documents
        # a contour may follow several sketches, also facing away from the tool (seen from its side)
        flipped = sketch_faces_away(job, helper.Sketch)
        if helper.Flipped != flipped:
            helper.Flipped = flipped
        helper.Placement = to_setup.multiply(geometry.facing_tool(helper.Sketch.Placement, flipped))
        for name, value in (
            ("Compensation", contour.compensation), ("Approach", contour.approach), ("ArcSide", contour.arc_side),
        ):  # fmt: skip
            if getattr(helper, name) != value:
                setattr(helper, name, value)
        for name, value in (
            ("ToolRadius", _tool_radius(tc)), ("LeadRadius", _lead_radius(contour, tc)),
            ("StartExtend", contour.start_extend_mm), ("EndExtend", contour.end_extend_mm),
        ):  # fmt: skip
            if abs(_value(getattr(helper, name), "mm") - value) > 1e-9:
                setattr(helper, name, _quantity(value, "mm"))
    # the sketches face the tool, so their planes are level in the setup
    levels = contour_planes(op) or [place.Base.z]
    top = contour.base_mm(levels[0]) + contour.start_z_mm
    op.StartDepth = _quantity(top, "mm")
    op.FinalDepth = _quantity(contour.base_mm(levels[-1]) + contour.z_depth_mm, "mm")
    # FreeCAD's own Engrave (contours from before the passes) steps down by it, full steps as ours
    op.StepDown = _quantity(contour.z_step_mm or 0.0, "mm")
    _set_heights(job, op, max(top, levels[0]))


def _set_heights(job, op, level):
    """Heights of an operation starting at level (a plane, or a contour's
    Start Z above it), as the shop's programs have them: 2 mm above the stock's top (or the
    level, when higher), and Z+20 to come down to."""
    top = stock_bounds(job).z_max if job.Stock is not None else level
    safe = max(top, level) + model_operations.SAFETY_MM
    for name in ("SafeHeight", "ClearanceHeight"):
        op.setExpression(name, None)  # FreeCAD's SetupSheet values
    op.SafeHeight = _quantity(safe, "mm")
    op.ClearanceHeight = _quantity(max(model_operations.APPROACH_Z_MM, safe), "mm")


# -- drilling ------------------------------------------------------------------


def _attach_drilling_view(op):
    import Path.Op.Gui.Base as PathOpGui
    import Path.Op.Gui.Drilling as PathDrillingGui

    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, PathDrillingGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False


def add_drilling(job, sketch, drilling, tc, circles=()):
    """Drilling: the tool drills circles of the sketch with the TNC's cycle
    205 (model Drilling), from the sketch plane down.

    circles: names of the sketch's circles ("Edge5") in the order the user
    picked them, the order the tool drills them. None: all the sketch's
    circles, in FreeCAD's order (a short way from hole to hole).

    Made of FreeCAD's Drilling operation (engine.drilling: it keeps the
    order and drills each hole from its own top) on a helper object holding
    the circles, moved into the setup's coordinates. Its path is how FreeCAD
    drills them (G81, G82 with the dwell, G83 pecking, G73 breaking the
    chips), for the 3D view and the simulation; the NC program has the cycle.
    """
    drilling.validate()
    if drilling.depth_mm is None:
        raise ProjectError("The circles of a sketch have no depth of their own; enter the depth.")
    _check_tool(job, tc)
    names = _sketch_circles(job, sketch, circles, "drill")
    label = _next_label(job.Document, "Drilling")
    helper = _circles_helper(job, sketch, names, label)
    return _drilling_op(job, helper, len(names), label, drilling, tc, sketch, _SKETCH_PROPERTY, "Sketch with the circles the tool drills")  # fmt: skip


def _sketch_circles(job, sketch, circles, verb):
    """Names of a sketch's circles for an operation on holes, each once in
    the user's order; all of them in FreeCAD's order without circles."""
    if not sketch_fits(job, sketch):
        raise ProjectError(
            "{} does not face the tool of {}. Select the sketch's face and use "
            "Snap-0-Point first.".format(sketch.Label, job.Label)
        )
    place = zero(job).inverse().multiply(sketch.Placement)
    names = list(dict.fromkeys(circles))  # each hole once, in the user's order
    if not names:
        names = _short_way(sketch, geometry.sketch_circles(sketch), place)
        if not names:
            raise ProjectError("{} has no circles to {}.".format(sketch.Label, verb))
    geometry.hole_circles(sketch, names)
    return names


def _circles_helper(job, sketch, names, label):
    """Helper object with circles of a sketch, in the setup's coordinates."""
    helper = job.Document.addObject("Part::FeaturePython", "HoleCircles")
    geometry.HoleCircles(helper)
    helper.Sketch = sketch
    helper.Edges = names
    _helper(helper, HOLE_GEOMETRY, "{} holes ({})".format(label, job.Label))
    helper.Placement = zero(job).inverse().multiply(sketch.Placement)
    helper.recompute()
    return helper


def _model_holes_helper(job, model, picked, label):
    """Helper object with the circles of the tops of holes of a model
    (geometry.ModelHoles), in the setup's coordinates."""
    helper = job.Document.addObject("Part::FeaturePython", "ModelHoles")
    geometry.ModelHoles(helper)
    helper.Model = model
    helper.Holes = [h.name for h in picked]
    _helper(helper, HOLE_GEOMETRY, "{} holes ({})".format(label, job.Label))
    helper.Placement = zero(job).inverse()
    helper.recompute()
    return helper


def add_model_drilling(job, model, drilling, tc, holes):
    """Drilling of holes picked in a model: holes are one element of each
    (its wall "Face12" or its round edge "Edge7"), in the order the tool
    drills them. Each hole is drilled from its own top; without the user's
    depth (drilling.depth_mm None) as deep as the model has it (model
    Drilling). The holes must run along the setup's tool axis and open
    towards it (geometry.model_hole).

    Made like add_drilling, on a helper object (geometry.ModelHoles) with
    the circles of the holes' tops in the setup's coordinates."""
    drilling.validate()
    _check_tool(job, tc)
    names = list(dict.fromkeys(holes))
    if not names:
        raise ProjectError("Click the holes to drill in the model.")
    picked = model_holes(job, model, names)
    _check_holes(drilling, tc, [h.depth for h in picked])
    label = _next_label(job.Document, "Drilling")
    helper = _model_holes_helper(job, model, picked, label)
    return _drilling_op(job, helper, len(picked), label, drilling, tc, model, _MODEL_PROPERTY, "Model with the holes the tool drills")  # fmt: skip


def model_holes(job, model, names):
    """The holes of a model picked by one of their elements each (names), as
    the tool of a setup sees them (geometry.model_holes): ProjectError when
    one is not a hole the setup can drill."""
    return geometry.model_holes(model, names, geometry.setup_up(zero(job).inverse()))


def _check_tool(job, tc):
    if tc not in job.Tools.Group:
        raise ProjectError("{} is not a tool of {}.".format(tc.Label, job.Label))


def _check_holes(drilling, tc, depths):
    """ProjectError when the drill cannot drill one of the holes (HoleDepth
    of a model's hole, None of a sketch's circle)."""
    tip = drill_tip_mm(tc)
    try:
        for depth in depths:
            drilling.check(tip, depth)
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc


def _drilling_op(job, helper, count, label, drilling, tc, source, link, tip):
    from avangardecam.engine import drilling as engine_drilling

    doc = job.Document
    op = doc.addObject("Path::FeaturePython", "Drilling")
    op.Proxy = engine_drilling.Drilling(op, "Drilling", job, tc)
    if FreeCAD.GuiUp:
        _attach_drilling_view(op)
    op.Label = label
    op.Base = [(helper, tuple("Edge{}".format(i) for i in range(1, count + 1)))]
    op.ToolController = tc
    # depths and heights come from the holes' tops and the user's values
    for name in ("StartDepth", "FinalDepth", "RetractHeight", "PeckDepth"):
        op.setExpression(name, None)
    op.ExtraOffset = "None"
    op.KeepToolDown = False  # G98: back up to the safe height between the holes
    _user_values(op, source, drilling, tip, link)
    _sync_drilling(job, op)
    doc.recompute()
    return op


def _short_way(sketch, names, place):
    """Circles of a sketch in FreeCAD's order for drilling them: a short way
    from hole to hole (place: sketch -> setup coordinates)."""
    import PathScripts.PathUtils as PathUtils

    holes = []
    for name, edge in zip(names, geometry.hole_circles(sketch, names)):
        centre = place.multVec(edge.Curve.Center)
        holes.append({"x": centre.x, "y": centre.y, "name": name})
    return [hole["name"] for hole in PathUtils.sort_locations(holes, ["x", "y"])] if holes else []


def drilling_circles(op):
    """Names of the sketch circles a drilling drills, in the tool's order;
    of the picked element of each hole of a model."""
    return [
        name for helper in helper_objects(op) for name in getattr(helper, "Edges", None) or getattr(helper, "Holes", [])
    ]


class DrillTarget(NamedTuple):
    """A hole of a drilling in the setup's coordinates, mm: its top's centre,
    its diameter, and its model.operations.HoleDepth (None: a sketch's circle)."""

    x: float
    y: float
    top: float
    diameter: float
    hole: object


def drill_targets(op):
    """The holes of a drilling (DrillTarget) in the order the tool drills them."""
    targets = []
    for helper in helper_objects(op):
        if getattr(helper, "Model", None) is not None:
            up = geometry.setup_up(helper.Placement)
            for hole in geometry.model_holes(helper.Model, list(helper.Holes), up):
                top = helper.Placement.multVec(hole.top)
                targets.append(DrillTarget(top.x, top.y, top.z, hole.radius * 2.0, hole.depth))
        elif getattr(helper, "Sketch", None) is not None:
            for edge in geometry.hole_circles(helper.Sketch, list(helper.Edges)):
                centre = helper.Placement.multVec(edge.Curve.Center)
                targets.append(DrillTarget(centre.x, centre.y, centre.z, edge.Curve.Radius * 2.0, None))
    return targets


def drilling_holes(op):
    """(x, y, diameter) of a drilling's holes in the setup's coordinates, mm,
    in the order the path drills them."""
    holes = []
    for command in op.Path.Commands:
        if command.Name in ("G73", "G81", "G82", "G83", "G85"):
            holes.append((command.Parameters["X"], command.Parameters["Y"]))
    diameters = {}
    for helper in helper_objects(op):
        for edge in helper.Shape.Edges:
            diameters[(round(edge.Curve.Center.x, 6), round(edge.Curve.Center.y, 6))] = edge.Curve.Radius * 2.0
    return [(x, y, diameters.get((round(x, 6), round(y, 6)))) for x, y in holes]


def set_drilling(op, drilling):
    """Change the user's values of a drilling."""
    drilling.validate()
    source, _old = drilling_of(op)
    if drilling.depth_mm is None and geometry.is_sketch(source):
        raise ProjectError("The circles of a sketch have no depth of their own; enter the depth.")
    _check_holes(drilling, op.ToolController, [t.hole for t in drill_targets(op)])
    setattr(op, _OPERATION_PROPERTY, model_operations.to_json(drilling))
    _sync_drilling(setup_of(op), op)
    op.Document.recompute()


def set_tool(op, tc):
    """Another tool of its setup for an operation."""
    job = setup_of(op)
    if job is None or tc not in job.Tools.Group:
        raise ProjectError("{} is not a tool of {}.".format(tc.Label, job.Label if job else "the setup"))
    if _deburring().deburring_of(op) is not None:
        return _deburring().set_deburring_tool(op, tc)
    if contour_of(op) is not None:
        return set_contour_tool(op, tc)
    if drilling_of(op) is not None:
        _check_holes(drilling_of(op)[1], tc, [t.hole for t in drill_targets(op) if t.hole is not None])
    if thread_milling_of(op) is not None:
        _check_thread(thread_milling_of(op)[1], tc, [(t.diameter, t.hole) for t in drill_targets(op)])
    if adaptive_of(op) is not None:
        _check_adaptive(job, adaptive_of(op)[1], tc, op.Base)
    if _facing().facing_of(op) is not None:
        _facing().facing_plan(job, _facing().facing_of(op)[1], tc, op.Base)
    if _slot().slot_milling_of(op) is not None:
        _slot().check(job, _slot().slot_milling_of(op)[1], tc, op.Base)
    if _helix().helix_milling_of(op) is not None:
        _helix().check(job, _helix().helix_milling_of(op)[1], tc, drill_targets(op))
    op.ToolController = tc
    _sync_operations(job)
    op.Document.recompute()


def change_operation(op, operation, tc):
    """New values (model Contour, Drilling, ...) and tool of an operation at
    once: the values are checked with the new tool, not the old one."""
    job = setup_of(op)
    if job is None or tc not in job.Tools.Group:
        raise ProjectError("{} is not a tool of {}.".format(tc.Label, job.Label if job else "the setup"))
    old = op.ToolController
    op.ToolController = tc
    try:
        if _deburring().deburring_of(op) is not None:
            _deburring().set_deburring(op, operation)
        elif contour_of(op) is not None:
            set_contour(op, operation)
        elif drilling_of(op) is not None:
            set_drilling(op, operation)
        elif thread_milling_of(op) is not None:
            set_thread_milling(op, operation)
        elif adaptive_of(op) is not None:
            set_adaptive(op, operation)
        elif _facing().facing_of(op) is not None:
            _facing().set_facing(op, operation)
        elif _slot().slot_milling_of(op) is not None:
            _slot().set_slot_milling(op, operation)
        elif _helix().helix_milling_of(op) is not None:
            _helix().set_helix_milling(op, operation)
        else:
            raise ProjectError("{} was made in FreeCAD; change it in expert mode.".format(op.Label))
    except (ProjectError, ValueError):
        op.ToolController = old
        raise


def set_active(op, on):
    """Switch an operation on or off: off, it has no path and is left out
    of the program and the simulation (FreeCAD's Active)."""
    if op.Active != on:
        op.Active = on
        op.Document.recompute()


def drill_tip_mm(tc):
    """Length of the point of a tool controller's drill, mm (0: flat)."""
    if getattr(tc, "Tool", None) is None:
        return 0.0
    return model_tools.tip_length_mm(_tool_from_controller(tc))


def _sync_drilling(job, op):
    """Holes, depths and heights of a drilling from its sketch or model, the
    user's values, the drill's point, the setup's zero point and stock.

    Each hole is drilled from its own top (engine.drilling); the operation's
    depths span them all. FreeCAD's path shows the cycle as well as FreeCAD
    can: pecking (G83) when the drill comes out of a hole before its depth,
    else breaking the chips (G73) or the dwell (G82); FreeCAD cannot peck
    and dwell in one hole, nor do the cycle's decrement and stop distances."""
    source, drilling = drilling_of(op)
    place = _place_holes(job, op, source)
    try:
        targets = drill_targets(op)
    except ProjectError:
        targets = []  # the model changed: recomputing says what is wrong
    tip = drill_tip_mm(op.ToolController)
    if targets:
        top = max(t.top for t in targets)
        bottom = min(t.top + _final_depth(drilling, tip, t) for t in targets)
        pecks = any(drilling.pecks(tip, t.hole) for t in targets if _drillable(drilling, t))
    else:
        top = place.Base.z  # a sketch faces the tool: its plane is level
        bottom, pecks = top - 1.0, False
    op.StartDepth = _quantity(top, "mm")
    op.FinalDepth = _quantity(bottom, "mm")
    op.RetractHeight = _quantity(top + drilling.clearance_mm, "mm")
    op.PeckEnabled = pecks or drilling.chip_break_mm > 0.0
    op.chipBreakEnabled = not pecks and drilling.chip_break_mm > 0.0
    op.PeckDepth = _quantity(drilling.peck_mm if pecks else drilling.chip_break_mm or 1.0, "mm")
    op.DwellEnabled = not op.PeckEnabled and drilling.dwell_s > 0.0
    op.DwellTime = float(drilling.dwell_s or 1.0)
    # from hole to hole at the 2nd set-up clearance, as the cycle; the
    # program comes to the first hole from the tool change (Z100)
    safe = top + max(drilling.clearance_mm, drilling.second_clearance_mm)
    for name in ("SafeHeight", "ClearanceHeight"):
        op.setExpression(name, None)
        setattr(op, name, _quantity(safe, "mm"))


def _place_holes(job, op, source):
    """The helper objects of an operation on holes follow the setup's zero
    point; their placement."""
    place = zero(job).inverse()
    if geometry.is_sketch(source):
        place = place.multiply(source.Placement)
    for helper in helper_objects(op):
        if not helper.Placement.isSame(place, 1e-12):
            helper.Placement = place
    return place


def _drillable(drilling, target):
    return drilling.depth_mm is not None or target.hole is not None


def _final_depth(drilling, tip, target):
    """Where the tip ends in a hole, below its top (a sketch's circle under
    a drilling from the model: 1 mm, until the user enters a depth)."""
    return drilling.final_depth_mm(tip, target.hole) if _drillable(drilling, target) else -1.0


def drill_moves(op):
    """(x, y, top, tip) of each hole of a drilling in the setup's
    coordinates, mm, in the order the tool drills them: where the drill
    starts and where its tip ends (engine.drilling draws them)."""
    found = drilling_of(op)
    if found is None:
        return []
    _source, drilling = found
    tip = drill_tip_mm(op.ToolController)
    return [(t.x, t.y, t.top, t.top + _final_depth(drilling, tip, t)) for t in drill_targets(op)]


def _drill_cycle(op, tool):
    """The NC program's cycle of a drilling, for its nc.Tool."""
    _source, drilling = drilling_of(op)
    tip = drill_tip_mm(op.ToolController)
    if not drilling_holes(op):
        raise ProjectError("{} drills no holes; recompute the project.".format(op.Label))
    holes = []
    for target in drill_targets(op):
        try:
            depth = drilling.final_depth_mm(tip, target.hole)
        except ValueError as exc:
            raise ProjectError("{}: {}.".format(op.Label, exc)) from exc
        holes.append(model_nc.DrillHole(target.x, target.y, target.top, depth))
    return model_nc.DrillCycle(
        peck_mm=drilling.peck_mm,
        feed_mm_min=tool.feed_xy_mm_min,  # the shop's programs drill with the tool's feed
        clearance_mm=drilling.clearance_mm,
        second_clearance_mm=drilling.second_clearance_mm,
        decrement_mm=drilling.decrement_mm,
        min_peck_mm=drilling.min_peck_mm,
        upper_stop_mm=drilling.upper_stop_mm,
        lower_stop_mm=drilling.lower_stop_mm,
        chip_break_mm=drilling.chip_break_mm,
        chip_retract_mm=drilling.chip_retract_mm,
        dwell_s=drilling.dwell_s,
        start_mm=drilling.start_mm,
        preposition_feed_mm_min=tool.feed_z_mm_min,  # and its plunge feed to come down
        holes=tuple(holes),
    )


# -- thread milling ---------------------------------------------------------------


def thread_milling_of(op):
    """(sketch or model, model ThreadMilling) of a thread milling made by
    AvangardeCam, else None."""
    return _operation_of(op, model_operations.ThreadMilling)


def thread_mill(tc):
    """(diameter, pitch) of a tool controller's thread mill, mm; ProjectError
    when its tool is not a thread mill."""
    tool = _tool_from_controller(tc) if getattr(tc, "Tool", None) is not None else None
    if tool is None or tool.shape != "ThreadMill" or not tool.pitch_mm:
        raise ProjectError(
            "{} is not a thread mill; choose a thread mill (Draadfrees).".format(getattr(tc, "Label", "The tool"))
        )
    return tool.diameter_mm, tool.pitch_mm


def _check_thread(thread, tc, holes):
    """ProjectError when the thread mill cannot mill the thread in the holes:
    (diameter, HoleDepth of a model's hole or None) of each."""
    diameter, pitch = thread_mill(tc)
    try:
        thread.check(diameter, pitch)
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc
    for hole_diameter, depth in holes:
        if diameter >= hole_diameter - 1e-6:
            raise ProjectError(
                "The thread mill (Ø{:g}) does not fit into a Ø{:g} hole.".format(diameter, round(hole_diameter, 3))
            )
        if depth is not None and not depth.through and thread.depth_mm < depth.depth_mm - 1e-6:
            raise ProjectError(
                "The thread ({:g} mm) is deeper than a hole of the model ({:g} mm).".format(
                    -thread.depth_mm, round(-depth.depth_mm, 3)
                )
            )


def add_thread_milling(job, sketch, thread, tc, circles=()):
    """Thread milling (model ThreadMilling) in circles of a sketch, from the
    sketch plane down; circles as for add_drilling (None: all of them)."""
    thread.validate()
    _check_tool(job, tc)
    names = _sketch_circles(job, sketch, circles, "mill a thread in")
    _check_thread(thread, tc, [(e.Curve.Radius * 2.0, None) for e in geometry.hole_circles(sketch, names)])
    label = _next_label(job.Document, "Thread milling")
    helper = _circles_helper(job, sketch, names, label)
    return _thread_op(job, helper, len(names), label, thread, tc, sketch, _SKETCH_PROPERTY, "Sketch with the circles of the threads")  # fmt: skip


def add_model_thread_milling(job, model, thread, tc, holes):
    """Thread milling in holes picked in a model (as add_model_drilling),
    each from its own top. A hole that does not go through must be as deep
    as the thread."""
    thread.validate()
    _check_tool(job, tc)
    names = list(dict.fromkeys(holes))
    if not names:
        raise ProjectError("Click the holes to mill the threads in, in the model.")
    picked = model_holes(job, model, names)
    _check_thread(thread, tc, [(h.radius * 2.0, h.depth) for h in picked])
    label = _next_label(job.Document, "Thread milling")
    helper = _model_holes_helper(job, model, picked, label)
    return _thread_op(job, helper, len(picked), label, thread, tc, model, _MODEL_PROPERTY, "Model with the holes of the threads")  # fmt: skip


def _attach_thread_view(op):
    import Path.Op.Gui.Base as PathOpGui
    import Path.Op.Gui.ThreadMilling as PathThreadMillingGui

    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, PathThreadMillingGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False


def _thread_op(job, helper, count, label, thread, tc, source, link, tip):
    from avangardecam.engine import thread_milling as engine_threads

    doc = job.Document
    op = doc.addObject("Path::FeaturePython", "ThreadMilling")
    op.Proxy = engine_threads.ThreadMilling(op, "ThreadMilling", job, tc)
    if FreeCAD.GuiUp:
        _attach_thread_view(op)
    op.Label = label
    op.Base = [(helper, tuple("Edge{}".format(i) for i in range(1, count + 1)))]
    op.ToolController = tc
    for name in ("StartDepth", "FinalDepth"):
        op.setExpression(name, None)
    _user_values(op, source, thread, tip, link)
    _sync_thread_milling(job, op)
    doc.recompute()
    return op


def set_thread_milling(op, thread):
    """Change the user's values of a thread milling."""
    thread.validate()
    _check_thread(thread, op.ToolController, [(t.diameter, t.hole) for t in drill_targets(op)])
    setattr(op, _OPERATION_PROPERTY, model_operations.to_json(thread))
    _sync_thread_milling(setup_of(op), op)
    op.Document.recompute()


def _sync_thread_milling(job, op):
    """Holes and heights of a thread milling from its sketch or model and
    the setup's zero point; FreeCAD's own thread values from the user's
    and the thread mill, so expert mode shows them."""
    import Path.Op.ThreadMilling as PathThreadMilling

    source, thread = thread_milling_of(op)
    place = _place_holes(job, op, source)
    try:
        tops = [t.top for t in drill_targets(op)]
    except ProjectError:
        tops = []  # the model changed: recomputing says what is wrong
    tops = tops or [place.Base.z]
    top = max(tops)
    op.StartDepth = _quantity(top, "mm")
    op.FinalDepth = _quantity(min(tops) + thread.depth_mm, "mm")
    heights = (
        ("SafeHeight", top + model_threads.BETWEEN_MM),
        ("ClearanceHeight", max(model_operations.APPROACH_Z_MM, top + model_operations.SAFETY_MM)),
    )
    for name, value in heights:
        op.setExpression(name, None)
        setattr(op, name, _quantity(value, "mm"))
    try:
        _diameter, pitch = thread_mill(op.ToolController)
    except ProjectError:
        pitch = None
    major = thread.major_diameter_mm
    op.MajorDiameter = _quantity(major, "mm")
    if pitch:
        op.Pitch = _quantity(pitch, "mm")
        op.MinorDiameter = _quantity(major - 1.0825 * pitch, "mm")  # ISO internal: D1 = D - 1.0825 P
        op.ThreadName = model_threads.name(major, pitch)
    op.TPI = 0
    op.Passes = thread.passes
    op.ThreadOrientation = PathThreadMilling.RightHand
    op.ThreadType = PathThreadMilling.ThreadTypeCustomInternal
    op.Direction = PathThreadMilling.DirectionConventional  # down, clockwise
    op.LeadInOut = False


def thread_moves(op, tool=None):
    """The tool moves of a thread milling (model.threads.moves), in the
    setup's coordinates: where the tool centre runs (FreeCAD's path); for
    the NC program (tool: its nc.Tool) the thread's major radius with the
    radius compensation right. [] for another operation."""
    found = thread_milling_of(op)
    if found is None:
        return []
    _source, thread = found
    diameter, pitch = thread_mill(op.ToolController)
    holes = [model_threads.ThreadHole(t.x, t.y, t.top) for t in drill_targets(op)]
    if tool is None:
        own = _tool_from_controller(op.ToolController)
        feeds, radius, side = (own.feed_z_mm_min, own.feed_xy_mm_min), (thread.major_diameter_mm - diameter) / 2.0, None
    else:
        feeds, radius, side = (tool.feed_z_mm_min, tool.feed_xy_mm_min), thread.major_diameter_mm / 2.0, model_nc.RIGHT
    return model_threads.moves(thread, holes, pitch, radius, feeds[0], feeds[1], side)


def _facing():
    """engine.facing: the facing lives in its own module, which uses this one."""
    from avangardecam.engine import facing

    return facing


def _slot():
    """engine.slot: the slot milling lives in its own module, which uses this one."""
    from avangardecam.engine import slot

    return slot


def _helix():
    """engine.helix: the helix milling lives in its own module, which uses this one."""
    from avangardecam.engine import helix

    return helix


def _deburring():
    """engine.deburring: a contour of a chamfer mill, in its own module, which uses this one."""
    from avangardecam.engine import deburring

    return deburring


def _op_zero():
    """Zero points of operations, on their own (engine.op_zero)."""
    from avangardecam.engine import op_zero

    return op_zero


def _next_setup():
    """engine.next_setup: a stock left by another setup or a blank's model, in its own module."""
    from avangardecam.engine import next_setup

    return next_setup


# -- adaptive clearing --------------------------------------------------------------

# tools that cut with their side: a drill, a chamfer or a thread mill clears nothing
_CLEARING_SHAPES = ("Endmill", "Bullnose", "Ballend")


def adaptive_of(op):
    """(model, model Adaptive) of an adaptive clearing made by AvangardeCam,
    else None."""
    return _operation_of(op, model_operations.Adaptive)


def _clone(job, model):
    """The Job's clone of a model (in the setup's coordinates)."""
    for clone in job.Model.Group:
        if clone is model or _original(clone) is model:
            return clone
    raise ProjectError("{} is not a model of {}.".format(model.Label, job.Label))


def picked_floors(job, model, faces):
    """The Base of an adaptive clearing (FreeCAD: [(clone, names)]) for
    faces picked in a model ("Face23"): flat floors facing the setup's
    tool, each once, in the Job's clone of the model. [] without faces."""
    names = list(dict.fromkeys(faces))
    if not names:
        return []
    clone = _clone(job, model)
    for name in names:
        try:
            face = clone.Shape.getElement(name) if name.startswith("Face") else None
        except Exception:
            face = None
        if (
            face is None
            or face.findPlane() is None
            or face.BoundBox.ZLength > 1e-6
            or geometry.outward_normal(clone.Shape, face).z < 1.0 - 1e-9
        ):
            raise ProjectError(
                "{} of {} is not a flat floor facing the tool of {}. Pick flat faces the tool "
                "looks at, or none to clear around the whole model.".format(name, _original(clone).Label, job.Label)
            )
    return [(clone, tuple(names))]


def floor_heights(base):
    """Z of each picked floor (FreeCAD Base [(clone, names)]) in the setup's coordinates."""
    return [obj.Shape.getElement(name).BoundBox.ZMin for obj, names in base for name in names]


def _floor_levels(job, base):
    """Z of the flat floors facing the tool of the setup's models (setup
    coordinates), from the top; with picked floors (base) those under their
    area only."""
    from avangardecam.engine import adaptive as engine_adaptive

    faces = engine_adaptive.floor_faces([clone.Shape for clone in job.Model.Group])
    if base:
        picked = [obj.Shape.getElement(name) for obj, names in base for name in names]
        faces = engine_adaptive.under(faces, picked)
    return sorted({round(face.BoundBox.ZMin, 6) + 0.0 for face in faces}, reverse=True)


def adaptive_levels(job, adaptive, base=()):
    """The Z levels of an adaptive clearing of the setup (model Adaptive.levels)."""
    return adaptive.levels(stock_bounds(job).z_max, _floor_levels(job, base))


def suggested_adaptive_depth(job, model=None, faces=()):
    """Z-Depth to offer for an adaptive clearing (setup coordinates): the
    lowest picked floor, else the lowest floor facing the tool of the
    setup's models under the top of the stock, else their bottom."""
    base = picked_floors(job, model, faces) if model is not None else []
    if base:
        return min(floor_heights(base))
    top = stock_bounds(job).z_max
    found = [z for z in _floor_levels(job, []) if z < top]
    if found:
        return min(found)
    return min(clone.Shape.BoundBox.ZMin for clone in job.Model.Group)


def _check_adaptive(job, adaptive, tc, base):
    """The Z levels of an adaptive clearing; ProjectError when the tool cannot clear them."""
    try:
        adaptive.validate()
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc
    _check_tool(job, tc)
    if getattr(tc, "Tool", None) is None:
        raise ProjectError("{} has no tool.".format(tc.Label))
    tool = _tool_from_controller(tc)
    if tool.shape not in _CLEARING_SHAPES:
        raise ProjectError("{} is not an end mill; adaptive clearing needs one.".format(tc.Label))
    if job.Stock is None:
        raise ProjectError("{} has no stock to clear.".format(job.Label))
    top = stock_bounds(job).z_max
    levels = adaptive.levels(top, _floor_levels(job, base))
    if not levels:
        raise ProjectError(
            "Z-Depth ({:g} mm) plus the allowance in Z must be below the top of the stock (Z{:+g} mm).".format(
                adaptive.z_depth_mm, round(top, 3)
            )
        )
    if len(levels) > model_operations.MAX_CUTS:
        raise ProjectError("{} Z levels are too many (at most {}); take a larger Z step.".format(len(levels), model_operations.MAX_CUTS))  # fmt: skip
    full = adaptive.full_levels(top)  # a floor's own level cuts less than the next of these
    deepest = max(a - b for a, b in zip([top] + full, full))
    if tool.cutting_length_mm and deepest > tool.cutting_length_mm + 1e-6:
        raise ProjectError(
            "A level cuts {:g} mm deep, more than the cutting length of {} ({:g} mm). Enter a Z step.".format(
                round(deepest, 3), tc.Label, tool.cutting_length_mm
            )
        )
    return levels


def _attach_adaptive_view(op):
    import Path.Op.Gui.Adaptive as PathAdaptiveGui
    import Path.Op.Gui.Base as PathOpGui

    op.ViewObject.Proxy = PathOpGui.ViewProvider(op.ViewObject, PathAdaptiveGui.Command.res)
    op.ViewObject.Proxy.deleteOnReject = False


def add_adaptive(job, adaptive, tc, model=None, faces=()):
    """Adaptive clearing (model Adaptive) in the setup: around all its
    models from the top of the stock down to Z-Depth, or only over the area
    of floors picked in a model (faces: names of flat faces facing the
    tool, "Face23").

    Made of FreeCAD's Adaptive operation (engine.adaptive: AvangardeCam's Z
    levels and moves); its Base are the picked floors of the Job's clone of
    the model, which moves with the zero point."""
    from avangardecam.engine import adaptive as engine_adaptive

    if faces and model is None:
        raise ProjectError("Picked floors need their model.")
    base = picked_floors(job, model, faces)
    _check_adaptive(job, adaptive, tc, base)
    doc = job.Document
    op = doc.addObject("Path::FeaturePython", "Adaptive")
    op.Proxy = engine_adaptive.Adaptive(op, "Adaptive", job, tc)
    if FreeCAD.GuiUp:
        _attach_adaptive_view(op)
    op.Label = _next_label(doc, "Adaptive")
    op.Base = base
    op.ToolController = tc
    # depths and heights come from the stock and the user's values
    for name in ("StartDepth", "FinalDepth", "StepDown"):
        op.setExpression(name, None)
    source = model if model is not None else _original(job.Model.Group[0])
    _user_values(op, source, adaptive, "Model the tool clears around", _MODEL_PROPERTY)
    _sync_adaptive(job, op)
    doc.recompute()
    return op


def adaptive_floors(op):
    """Names of the floors picked for an adaptive clearing; [] for all around the models."""
    return [name for _obj, names in getattr(op, "Base", []) for name in names]


def set_adaptive(op, adaptive):
    """Change the user's values of an adaptive clearing."""
    job = setup_of(op)
    _check_adaptive(job, adaptive, op.ToolController, op.Base)
    setattr(op, _OPERATION_PROPERTY, model_operations.to_json(adaptive))
    _sync_adaptive(job, op)
    op.Document.recompute()


def _sync_adaptive(job, op):
    """FreeCAD's own values of an adaptive clearing from the user's, the
    stock and the setup, so expert mode shows them; heights as the shop's programs have them."""
    _model, adaptive = adaptive_of(op)
    top = stock_bounds(job).z_max if job.Stock is not None else 0.0
    start = adaptive.top_mm(top)
    op.StartDepth = _quantity(start, "mm")
    op.FinalDepth = _quantity(adaptive.z_depth_mm, "mm")
    op.StepDown = _quantity(adaptive.z_step_mm or max(start - adaptive.z_depth_mm, 0.0), "mm")
    _set_heights(job, op, top)
    op.Side = "Inside"  # of the picked floors
    op.OperationType = "Clearing"
    op.ModelAwareExperiment = True
    op.UseHelixArcs = True
    op.UseOutline = False
    op.StepOver = int(round(adaptive.step_over_percent))
    op.StockToLeave = _quantity(adaptive.finish_xy_mm, "mm")
    op.ZStockToLeave = _quantity(adaptive.finish_z_mm, "mm")
    op.HelixAngle = _quantity(adaptive.helix_angle_deg, "deg")
    op.LiftDistance = _quantity(adaptive.lift_mm, "mm")
    op.FinishingProfile = adaptive.finishing_pass


def adaptive_moves(op, proxy):
    """The tool moves (nc.Move) of an adaptive clearing in the setup's
    coordinates, where the tool centre goes; proxy: the operation's
    (engine.adaptive), with its Job's model and stock. ProjectError when
    the tool cannot clear it."""
    from avangardecam.engine import adaptive as engine_adaptive

    job = setup_of(op)
    _model, adaptive = adaptive_of(op)
    tc = op.ToolController
    levels = _check_adaptive(job, adaptive, tc, op.Base)
    tool = _tool_from_controller(tc)
    pieces = engine_adaptive.pieces(proxy, op, levels, stock_bounds(job).z_max, tool.diameter_mm, adaptive)
    return model_clearing.moves(
        pieces,
        _value(op.SafeHeight, "mm"),
        adaptive.lift_mm,
        adaptive.helix_angle_deg,
        tool.feed_z_mm_min,
        tool.feed_xy_mm_min,
        _value(op.ClearanceHeight, "mm"),
    )


def contour_depths(op):
    """(start, final) depth of a contour (Start Z, Z-Depth) or a drilling
    (top of the holes, tip) in the setup's coordinates, mm."""
    return _value(op.StartDepth, "mm"), _value(op.FinalDepth, "mm")


def path_summary(op):
    """(number of moves, lowest Z of the cutting moves or None) of an
    operation's path, in the setup's coordinates."""
    moves = 0
    lowest = None
    for command in op.Path.Commands:
        if command.Name not in ("G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"):
            continue
        moves += 1
        z = command.Parameters.get("Z")
        if z is not None and command.Name not in ("G0", "G00"):
            lowest = z if lowest is None else min(lowest, z)
    return moves, lowest


# -- drawing a path --------------------------------------------------------------

# kinds of the pieces of path_drawing
DRAW_RAPID = "rapid"
DRAW_FEED = "feed"
DRAW_LINK = "link"  # from the tool centre to where its edge cuts, or back
# arcs drawn as lines this close to them, mm
_DRAW_DEFLECTION_MM = 0.01


def path_drawing(op):
    """How the 3D view draws a contour with radius compensation (a slot
    milling: engine.slot.path_drawing, a helix milling:
    engine.helix.path_drawing), as (kind, points) pieces in the
    setup's coordinates; None for any other operation (its path, the tool
    centre, is drawn as it is).

    The tool goes down with its centre where FreeCAD's path has it; along
    the lines the drawing shows where its edge cuts (the program's lines,
    Run.program); a DRAW_LINK joins the two where they differ (without the
    approach arcs the centre goes down beside the lines). With the arcs the
    program starts and ends in their centre, where the tool goes down and up.
    """
    if _slot().slot_milling_of(op) is not None:
        return _slot().path_drawing(op)
    if _helix().helix_milling_of(op) is not None:
        return _helix().path_drawing(op)
    found = contour_of(op)
    if found is None or found[1].compensation == model_operations.OFF or op.Path is None:
        return None
    runs = [run for chain in contour_cuts(op) or () for _p, run, _z in chain]
    if not runs:
        return None

    def point(edges, last=False):
        edge = edges[-1] if last else edges[0]
        return edge.valueAt(edge.LastParameter if last else edge.FirstParameter)

    def same_xy(a, b):
        return abs(a.x - b.x) < 1e-3 and abs(a.y - b.y) < 1e-3

    def at_depth(edges, z):
        points = []
        for edge in edges:
            for p in edge.discretize(Deflection=_DRAW_DEFLECTION_MM)[1 if points else 0 :]:
                points.append(FreeCAD.Vector(p.x, p.y, z))
        return points

    position = [None, None, None]

    def move(command):
        """(start, end) of a move; None where a coordinate is not known yet."""
        start = FreeCAD.Vector(*position) if None not in position else None
        for k, axis in enumerate("XYZ"):
            if axis in command.Parameters:
                position[k] = float(command.Parameters[axis])
        return start, FreeCAD.Vector(*position) if None not in position else None

    commands = [c for c in op.Path.Commands if c.Name in _MOVES]
    pieces = []
    i = 0
    while i < len(commands):
        start, end = move(commands[i])
        i += 1
        if _MOVES[commands[i - 1].Name] == model_nc.RAPID:
            if start is not None and end is not None and not start.isEqual(end, 1e-9):
                pieces.append((DRAW_RAPID, [start, end]))
            continue
        # a cut: down (this move), then along the lines up to the next rapid move
        centre_end = end
        while i < len(commands) and _MOVES[commands[i].Name] != model_nc.RAPID:
            centre_end = move(commands[i])[1]
            i += 1
        if end is None or centre_end is None:
            return None
        run = next((r for r in runs if same_xy(end, point(r.centre)) and same_xy(centre_end, point(r.centre, True))), None)
        if run is None:  # the path does not match the lines (not recomputed yet)
            return None
        runs.remove(run)
        if start is not None:
            pieces.append((DRAW_FEED, [start, end]))
        lines = at_depth(run.program, end.z)
        if not same_xy(end, lines[0]):
            pieces.append((DRAW_LINK, [end, lines[0]]))
        pieces.append((DRAW_FEED, lines))
        if not same_xy(lines[-1], centre_end):
            pieces.append((DRAW_LINK, [lines[-1], centre_end]))
    return pieces


# -- NC program ------------------------------------------------------------------

_MOVES = {
    "G0": model_nc.RAPID,
    "G00": model_nc.RAPID,
    "G1": model_nc.LINE,
    "G01": model_nc.LINE,
    "G2": model_nc.ARC,
    "G02": model_nc.ARC,
    "G3": model_nc.ARC,
    "G03": model_nc.ARC,
}
# commands of a path that do not move the tool and need nothing in the program
_QUIET = {"G17", "G80", "G90", "G94"}


def nc_moves(op):
    """The tool moves of an operation, in the setup's coordinates: its
    path, but for a contour with radius compensation the lines themselves."""
    moves = _path_moves(op, op.Path.Commands)
    found = contour_of(op)
    if found is not None and found[1].compensation != model_operations.OFF:
        moves = _programmed(op, moves, found[1])
    return moves


def _path_moves(op, commands):
    moves = []
    position = [None, None, None]
    for command in commands:
        name = command.Name.upper()
        if name.startswith("(") or name in _QUIET:
            continue
        kind = _MOVES.get(name)
        if kind is None:
            raise ProjectError("{}: {} cannot be written to an NC program yet.".format(op.Label, command.Name))
        p = command.Parameters
        start = list(position)
        for i, axis in enumerate("XYZ"):
            if axis in p:
                position[i] = float(p[axis])
        feed = None
        if "F" in p and kind != model_nc.RAPID:
            # FreeCAD keeps feeds in mm/s
            feed = _value(FreeCAD.Units.Quantity(p["F"], FreeCAD.Units.Velocity), "mm/min")
        center = None
        if kind == model_nc.ARC:
            if abs(p.get("K", 0.0)) > 1e-9 or None in start[:2]:
                raise ProjectError("{}: only arcs in the XY plane can be written yet.".format(op.Label))
            center = (start[0] + p.get("I", 0.0), start[1] + p.get("J", 0.0))
        moves.append(model_nc.Move(kind, *position, feed, center, name in ("G2", "G02")))
    return tuple(moves)


def _programmed(op, moves, contour):
    """A contour's moves with radius compensation.

    FreeCAD's path runs the tool centre beside the lines; the program has
    the lines themselves and the control keeps the tool beside them
    (geometry.contour_runs). Each cut of the path (from its plunge to the
    next rapid move) becomes the program of the run whose tool centre
    starts and ends where it does, at the cut's depth and feed:
    - with the approach arcs the tool goes down in their centre without
      compensation, the line to the arc switches it on, the line back
      switches it off;
    - without, the compensation goes on over the start, above the part, and
      stays on down, along the lines and up again; it goes off above the
      part before the tool moves to another start (and at the end of the
      operation, see post).
    """
    # one run for each cut, each XY pass as often as it has Z levels
    runs = [run for chain in contour_cuts(op) or () for _p, run, _z in chain]

    def point(edges, last=False):
        edge = edges[-1] if last else edges[0]
        p = edge.valueAt(edge.LastParameter if last else edge.FirstParameter)
        return (p.x, p.y)

    def at(move, xy):
        return move.x is not None and move.y is not None and abs(move.x - xy[0]) < 1e-3 and abs(move.y - xy[1]) < 1e-3

    def moved(move, xy, compensation):
        return move._replace(x=xy[0], y=xy[1], compensation=compensation)

    mismatch = ProjectError("{}: its path does not match its lines; recompute the project.".format(op.Label))
    result = []
    on = None  # the run whose compensation stays on over rapid moves (no approach)

    def rapids(group, run):
        nonlocal on
        for move in group:
            if on is not None and at(move, point(on.centre, True)):
                result.append(moved(move, point(on.program, True), on.side))
                continue
            if on is not None:  # off above the part, where the tool is
                last = result[-1]
                result.append(model_nc.Move(model_nc.RAPID, last.x, last.y, last.z))
                on = None
            if run is not None and not run.lead and at(move, point(run.centre)):
                move = moved(move, point(run.program), run.side)
            result.append(move)

    group = []
    i = 0
    while i < len(moves):
        if moves[i].kind == model_nc.RAPID:
            group.append(moves[i])
            i += 1
            continue
        end = i + 1
        while end < len(moves) and moves[end].kind != model_nc.RAPID:
            end += 1
        plunge, cut = moves[i], moves[i + 1 : end]
        run = next((r for r in runs if cut and at(plunge, point(r.centre)) and at(cut[-1], point(r.centre, True))), None)
        if run is None:
            raise mismatch
        runs.remove(run)
        rapids(group, run)
        group = []
        if not run.lead:
            plunge = moved(plunge, point(run.program), run.side)
        result.append(plunge)
        for k, edge in enumerate(run.program):
            # with the arcs the last line, back to their centre, switches the compensation off
            compensation = None if run.lead and k == len(run.program) - 1 else run.side
            result.extend(_edge_moves(edge, plunge.z, cut[0].feed_mm_min, compensation))
        on = None if run.lead else run
        i = end
    rapids(group, None)
    if runs:
        raise mismatch
    return tuple(result)


def _edge_moves(edge, z, feed, compensation):
    """Moves along an edge of the setup's XY plane, at height z."""
    import Part

    end = edge.valueAt(edge.LastParameter)
    curve = edge.Curve
    if isinstance(curve, (Part.Line, Part.LineSegment)):
        return [model_nc.Move(model_nc.LINE, end.x, end.y, z, feed, compensation=compensation)]
    if isinstance(curve, Part.Circle) and abs(abs(curve.Axis.z) - 1.0) < 1e-9 and not edge.isClosed():
        start = edge.valueAt(edge.FirstParameter)
        middle = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        c = curve.Center
        clockwise = (start.x - c.x) * (middle.y - c.y) - (start.y - c.y) * (middle.x - c.x) < 0.0
        return [model_nc.Move(model_nc.ARC, end.x, end.y, z, feed, (c.x, c.y), clockwise, compensation)]
    points = edge.discretize(Deflection=0.01)[1:]
    return [model_nc.Move(model_nc.LINE, p.x, p.y, z, feed, compensation=compensation) for p in points]


def _nc_tool(op):
    tc = getattr(op, "ToolController", None)
    if tc is None or getattr(tc, "Tool", None) is None:
        raise ProjectError("{} has no tool.".format(op.Label))
    tool = _tool_from_controller(tc)
    number = int(tc.ToolNumber)
    if not (tool.spindle_rpm and tool.feed_z_mm_min and tool.feed_xy_mm_min):
        raise ProjectError("T{} ({}) needs a spindle speed and feeds.".format(number, tool.name))
    return model_nc.Tool(
        number,
        tool.name,
        tool.diameter_mm,
        tool.spindle_rpm,
        tool.feed_z_mm_min,
        tool.feed_xy_mm_min,
        clockwise=str(getattr(tc, "SpindleDir", "Forward")) != "Reverse",
    )


def nc_operation(op):
    """An operation as the NC program has it, read on the setup's active
    zero point."""
    if drilling_of(op) is not None:
        tool = _nc_tool(op)
        return model_nc.Operation(model_nc.DRILLING, op.Label, tool, (), _drill_cycle(op, tool))
    if thread_milling_of(op) is not None:
        tool = _nc_tool(op)
        return model_nc.Operation(model_nc.THREAD_MILLING, op.Label, tool, thread_moves(op, tool))
    if adaptive_of(op) is not None:
        return model_nc.Operation(model_nc.ADAPTIVE, op.Label, _nc_tool(op), nc_moves(op))
    if _facing().facing_of(op) is not None:
        return model_nc.Operation(model_nc.FACING, op.Label, _nc_tool(op), nc_moves(op))
    if _slot().slot_milling_of(op) is not None:
        return model_nc.Operation(model_nc.SLOT_MILLING, op.Label, _nc_tool(op), _slot().program_moves(op))
    if _helix().helix_milling_of(op) is not None:
        return model_nc.Operation(model_nc.HELIX_MILLING, op.Label, _nc_tool(op), _helix().program_moves(op))
    kind = model_nc.CONTOUR if contour_of(op) is not None else ""
    if kind and _deburring().deburring_of(op) is not None:
        kind = model_nc.DEBURRING
    return model_nc.Operation(kind, op.Label, _nc_tool(op), nc_moves(op))


def nc_program(doc, name, comment=""):
    """The project as one NC program: each setup on its own preset (setup 1
    on preset 1, ...), the active operations in their order.

    An operation that counts from another zero point than the setup's
    preset (experimental, engine.op_zero) has that zero point
    (Operation.zero) and its moves counted from it: a postprocessor shifts
    and tilts there, Play, Verify and the cycle time run it from there
    (model.tilted)."""
    result = []
    for preset, job in enumerate(setups(doc), start=1):
        stock_, ops = _op_zero().setup_program(job)
        result.append(model_nc.Setup(preset, job.Label, stock_, tuple(ops)))
    return model_nc.Program(name, comment, datetime.date.today(), tuple(result))


def helper_objects(op):
    """Objects AvangardeCam made for an operation (the sketch lines or circles)."""
    objects = list(getattr(op, "BaseShapes", [])) + [base for base, _subs in getattr(op, "Base", [])]
    return [o for o in objects if getattr(o, _ROLE_PROPERTY, "")]


def remove_operation(op):
    """Remove an operation and the helper objects made for it."""
    doc = op.Document
    helpers = helper_objects(op)
    doc.removeObject(op.Name)
    for helper in helpers:
        if not helper.InList:
            doc.removeObject(helper.Name)
    doc.recompute()
