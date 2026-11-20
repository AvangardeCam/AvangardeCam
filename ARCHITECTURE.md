# AvangardeCam: architecture

A short map of the code. The full log of design decisions, details and FreeCAD pitfalls
(Polish) is in [docs/notes-pl.md](docs/notes-pl.md); AI assistants read it well.

## Goal

FreeCAD computes well but is hard to read. AvangardeCam is a **layer and a translator**: the
user works in a clear interface, and the program turns their decisions into FreeCAD objects
(Job, CAM operations, tool controllers). FreeCAD's own code is not touched; the module is
plain Python that works in the `Mod` folder of any FreeCAD 1.1.x.

## Three layers, dependencies only downwards

```
 ui/      windows, ribbon, project list, 3D view     (PySide, FreeCADGui)
   │
   ▼
 engine/  translator: model → FreeCAD CAM objects    (the only place that knows the CAM API)
   │
   ▼
 model/   the project and its operations             (plain Python: no FreeCAD, no Qt)

 post/    postprocessors: model/nc.py → text for one control (depends on model/ only)
```

- **model/** says *what* is to be done: stock, tools, zero point, operations and their
  parameters, machine moves, cycle time, collisions. It does not import FreeCAD, so it is
  tested with plain `python3` and FreeCAD API changes cannot break it.
- **engine/** says *how*: `freecad_cam.py` creates and updates FreeCAD CAM objects,
  `geometry.py` works on the part (flat faces, normals, zero point, sketches from faces),
  one module per operation (`contour`, `drilling`, `thread_milling`, `adaptive`, ...).
  When FreeCAD changes its API, only this layer changes.
- **ui/** shows the model and collects decisions. It never calls the CAM API directly.
- **post/** turns the control-neutral NC program (`model/nc.py`, built by the engine from the
  toolpaths) into text for one control. `post/heidenhain.py` writes Heidenhain TNC plain
  language (`.H`), checked byte for byte against real shop programs (`tests/test_post.py`).

## Rules

- **Every function in its own modules.** A new function gets `engine/<name>.py`,
  `ui/<name>.py`, `tests/test_<name>.py` and `tests_gui/test_<name>.py`; `actions.py` and
  `handlers.py` only get an entry and a thin function that delegates to it. Shared code
  (`geometry`, `freecad_cam`, `picking`, `scene`) may be called but is not reshaped for a new
  function; a function that needs something different keeps its own version. Changing
  shared code means running all tests. (A change to measuring must never break drilling.)
- **Units:** the model holds only mm, mm/min and rpm, with the unit in the field name
  (`depth_mm`, `feed_mm_min`, `spindle_rpm`). Conversions happen only in the engine, at the
  border with FreeCAD. The model validates ranges before anything reaches FreeCAD.
- **Geometry references** are `GeometryRef(object, ["Face12", "Edge3"])`, OCCT names.
- **Saved in the file:** each operation's model (JSON) is stored next to the FreeCAD CAM object
  it made, so a double click opens AvangardeCam's window. The `.FCStd` still opens in plain
  FreeCAD as an ordinary Job.
- **Texts** in the code are English and go through `avangardecam.tr` (Qt translations).

## Setups and the zero point

FreeCAD always cuts along Z from the Job's origin, so **a project is a list of setups and a
setup is one FreeCAD CAM Job**, each with its own zero point, stock, tools and operations.
The zero point is a placement in the part's coordinates (`freecad_cam.zero(job)`); FreeCAD
works on clones of the model moved by its inverse. Snap-0-Point puts Z0 on a picked face,
Rotate 0-Point turns it around Z, Next setup starts a setup from the stock the previous one
leaves. Custom stock (`engine/custom_stock.py`) makes any setup start from a model of the blank
in a file, by default moved so that the middle of its box is on the middle of the model's box
(on the setup's axes; moved, never turned; a blank the file draws around the model already
stays there; a right click on the stock moves it along the axes). The stock with allowances is
built around the models' exact box (`engine/exact_box.py` replaces FreeCAD's
`Path.Main.Stock.shapeBoundBox`: in the GUI FreeCAD takes a shape's box from the triangles
drawn, which lie inside large arcs). The 3D view shows the part as it lies in the **active setup** (a `SoTransform` on top
of the scene), so FreeCAD's NaviCube and the Top/Front views are the machine's views.

### Zero points of operations (experimental)

What a version shows is set in `avangardecam/edition.py`: `FIVE_AXES = False` on `main`
(Move 0-Point shifts only, the export window offers only machines that do not tilt), `True`
on `experimental`. The code below is the same on both branches.

A setup has a **default zero point** (the machine's preset) and an **active** one, which Move
0-Point moves away from it (onto a wall, by a typed shift; with 5 axes it turns). **Each
operation counts from the zero point it was made on and keeps it.** FreeCAD computes a Job
on one zero point, so `engine/op_zero.py` works on one at a time: the operations of another
zero point are *parked* (their zero point in `AvangardeZero`, their path kept; a guard on
FreeCAD's `ObjectOp.execute` keeps FreeCAD from computing them on the wrong zero point) and
come alive when their zero point is made the active one (`activate`: Make 0-Point active,
Reset 0-Point, or editing them). A setup whose zero point was never moved away has none of
this and works as before. Snap-0-Point and Rotate 0-Point move the setup itself (its default
zero point with what counts from it) and start from the default.

The **stock has a zero point of its own**: the one its block is a box on (the default zero
point it was made on; kept in `AvangardeStockZero`, the block in `AvangardeBlock`). On another
zero point FreeCAD's stock is the box around that block: the same block a quarter turn away, a
larger box at an odd angle, where the 3D view draws the block itself (`ui/op_zero.show_block`).
A stock typed on another zero point is the block on the default one, counted from where it was
typed (`op_zero.stock_changed`); at an odd angle the stock's windows work along the stock's own
axes and say so (`op_zero.stock_edit`, `set_stock`).

For the NC program `op_zero.setup_program` visits each zero point, reads its operations there
and comes back (a dropped transaction: no undo step). `freecad_cam.nc_program` gives each
operation its zero point from the preset (`Operation.zero`: origin and axes) and its moves
counted from it: a postprocessor shifts and tilts there, and Play, Verify, the cycle time and
the stock a setup leaves run it from there (`model/tilted.py`): the machine's moves are worked
out on the operation's own zero point (`model/machine.py`: the tool high on the preset before
the zero point is shifted; a machine that turns its head starts every operation anew), then
turned into the preset's coordinates, where the stock and the part are, with the tool axis of
that zero point. `post/machines.py` says which machine's program is run: the one chosen for
the export, or one that tilts when an operation is on a turned zero point.

### Cutting data of an operation

The spindle speed and feeds come from the tool (the tool controller, shared by the operations
with that tool); an operation may keep its own (`engine/cutting_data.py`: `AvangardeSpindle`,
`AvangardeFeedXY`, `AvangardeFeedZ`, 0 = the tool's). The paths are made with the tool's
values; `freecad_cam.nc_operation` puts the own ones on the NC operation
(`model/cutting_data.py`: the tool, the moves' feeds, a drilling cycle's Q206/Q253), so the
program, Simulate, Verify and the cycle time all run with them. The same tool with another
spindle speed is a tool call (`post/heidenhain._calls`, `model/machine.py`). The fields are in
`ui/cutting_data.py`, under the tool of `ui/tool_choice.ToolChooser`; the handlers keep them on
OK (`handlers._keep_cutting_data`), Change tool drops them.

### Editing the tool library

`model/tool_editing.py` has the fields of each tool type (named with the letters of FreeCAD's
drawings, `Mod/CAM/Tools/Shape/*.svg`), the checks before a tool is saved and the changes of
the list (ids kept: a project knows its tools by them). `engine/tool_library_file.py` writes to
the user's copy of the shipped library (`<user data>/AvangardeCam/tools.json`, made on the first
change; the `ToolLibraryFile` parameter points there) and makes a project's tools again from
an edited one (`freecad_cam.replace_tool`). The window is `ui/tool_editor.py`, opened from
`ui/tool_library.py`.

## Simulation and checking

- `stocklab/`: material removal on a tri-dexel grid (numpy, no FreeCAD), used by **Play**
  (separate window, stock removed live, program line by line), **Verify** (stock against the
  model) and the stock of a next setup. The tool axis is along X, Y or Z of the stock
  (`cut.py`, `sweep.py`), or, experimental, along any direction (`oblique.py`: the tool as
  cones, what a cone takes off a ray worked out exactly; the same cut as `cut.py` makes where
  both can).
- `model/crashes.py`: rapid moves into material, holder and neck collisions.
- `model/cycle_time.py`: cycle time from the machine's dynamics.

## Kiosk and expert mode

AvangardeCam is a FreeCAD workbench. Activated, it hides FreeCAD's menus, toolbars and panels
and shows its own layout; `File → FreeCAD (expert mode)` gives the full FreeCAD back.

## Folders

```
Init.py, InitGui.py   registration in FreeCAD
package.xml           add-on metadata
Resources/            icons, pictures of the operation windows, tool library (tools.json)
avangardecam/
  __init__.py         paths, parameters, tr()
  workbench.py        the workbench (kiosk on/off)
  profile.py          profile settings (start workbench, selection colours)
  actions.py          catalogue of functions: tabs, groups, buttons, File menu
  handlers.py         what the buttons do (thin, delegates to ui/ and engine/)
  model/              plain Python description of the project
  engine/             translator to FreeCAD CAM, part geometry, one module per operation
  ui/                 ribbon, project list and details, 3D view, operation windows, Play
  post/               postprocessors
  stocklab/           material removal simulation
  tests/              engine and model tests (FreeCADCmd: tests/run.py)
tests_gui/            GUI tests in a real FreeCAD window, models/demo_bridge.step
docs/notes-pl.md      full design notes (Polish)
```

## Adding a postprocessor

One postprocessor for each machine, each in its own file, listed in `post/machines.py` (the
export window offers them as file types): `post/heidenhain.py` for the Bridgeport V1000 (3
axes; a shifted zero point as `CYCL DEF 7`, a turned one refused) and, experimental,
`post/soraluce.py` for a machine that turns its head (`CYCL DEF 7`, `PLANE SPATIAL`, the
machine's head cycle and the labels RESET, FREE, HEAD0 around every operation).

Copy the shape of `post/heidenhain.py`: a `write(program, machine) -> str` that walks the
`Program` of `model/nc.py` (its `Setup`s, their `Operation`s with a `Tool`, the `Move`s and
`DrillCycle`s) and formats them for your control, plus `EXTENSION` and `ENCODING`. Pin it down with golden tests
in `tests/test_post.py` style: a small program in, the exact text of a trusted program out.
Then check it on the machine (simulation, dry run) before it cuts.
