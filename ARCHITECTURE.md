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
leaves. The 3D view shows the part as it lies in the **active setup** (a `SoTransform` on top
of the scene), so FreeCAD's NaviCube and the Top/Front views are the machine's views.

## Simulation and checking

- `stocklab/`: material removal on a tri-dexel grid (numpy, no FreeCAD), used by **Play**
  (separate window, stock removed live, program line by line), **Verify** (stock against the
  model) and the stock of a next setup.
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

Copy the shape of `post/heidenhain.py`: a `write(program, machine) -> str` that walks the
`Program` of `model/nc.py` (its `Setup`s, their `Operation`s with a `Tool`, the `Move`s and
`DrillCycle`s) and formats them for your control, plus `EXTENSION` and `ENCODING`. Pin it down with golden tests
in `tests/test_post.py` style: a small program in, the exact text of a trusted program out.
Then check it on the machine (simulation, dry run) before it cuts.
