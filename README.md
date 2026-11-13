# AvangardeCam

A clear CAM interface for [FreeCAD](https://www.freecad.org), made in a machine shop for
everyday 2.5D milling on Heidenhain TNC controls.

AvangardeCam is a FreeCAD workbench (add-on). It hides the many settings of FreeCAD's CAM
behind a few windows that speak the language of the shop floor: pick lines or faces in the
3D view, choose a tool from the library, get a Heidenhain plain language program (`.H`).

> **Status: beta.** It is used on real parts, but it is young. Always check the program in
> the simulation and on the machine (dry run, reduced feed) before cutting.

## Features

- **Setups and zero points:** several setups per part, Snap-0-Point on a face, zero rotated
  around Z, next setup from the stock the previous one leaves.
- **Stock:** allowances or exact size, the model in the middle.
- **Operations:** Contour tooling (compensation RL/RR, approach arcs, passes in XY and Z,
  ramps, start/end of the contour), Drilling (cycle 205, depth from the 3D model),
  Thread milling, Helix milling of holes, Slot milling, Facing, Adaptive clearing,
  Deburring.
- **Selection like in Blender:** Shift+click add/remove, Ctrl+click shortest path, Alt+click loop.
- **Simulation:** Play window with the stock removed live and the program line by line,
  Verify (stock against the model), collisions of rapid moves, holder and neck.
- **Cycle time** from the machine's dynamics.
- **Tool library** with feeds and speeds per material.
- **Postprocessor:** Heidenhain TNC plain language (`.H`), every setup on its own preset.

## Installation

Needs **FreeCAD 1.1** or newer (Windows, Linux, macOS).

1. Download this repository (green *Code* button → *Download ZIP*) and unpack it, or `git clone` it.
2. Rename the folder to `AvangardeCam` (the ZIP gives `AvangardeCam-main`) and put it into
   FreeCAD's `Mod` folder (create `Mod` if it is not there yet):
   - Windows: `%APPDATA%\FreeCAD\v1-1\Mod\`
   - Linux: `~/.local/share/FreeCAD/v1-1/Mod/` (Flatpak: `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/`)
   - macOS: `~/Library/Application Support/FreeCAD/v1-1/Mod/`

   FreeCAD shows its folder in the Python console: `App.getUserAppDataDir()`.
   The files must lie directly in it, e.g. `...\FreeCAD\v1-1\Mod\AvangardeCam\InitGui.py`.
3. Restart FreeCAD.

On its first start AvangardeCam becomes FreeCAD's start workbench, hides the Start page and
sets red/yellow selection colours (they mean something in AvangardeCam). Another start
workbench can be chosen again in *Edit → Preferences → General*.

**Units:** set *Edit → Preferences → General → Units* to *Metric small parts & CNC* (mm, mm/min).

## Tests

See [tests_gui/README.md](tests_gui/README.md): over 300 engine tests run in `FreeCADCmd`,
the GUI tests in a real FreeCAD window on the demo model `tests_gui/models/demo_bridge.step`.

## Support

AvangardeCam is free and stays free, postprocessors included.
If it saves you time, you can support its development via
[GitHub Sponsors](https://github.com/sponsors/AvangardeCam).

Training and remote consulting (CAM, Heidenhain programming, CNC in schools): contact via
GitHub.

## License

[LGPL-2.1-or-later](LICENSE), like FreeCAD. It comes **without any warranty**: you are
responsible for every program you run on a machine.
