# AvangardeCam

A clear CAM interface for [FreeCAD](https://www.freecad.org), made in a machine shop for
everyday 2.5D milling on Heidenhain TNC controls.

AvangardeCam is a FreeCAD workbench (add-on). It hides the many settings of FreeCAD's CAM
behind a few windows that speak the language of the shop floor: pick lines or faces in the
3D view, choose a tool from the library, get a Heidenhain plain language program (`.H`).

Website: **[avangardecam.eu](https://avangardecam.eu)** (videos, training, rates).

> **Status: beta.** It is used on real parts, but it is young. Always check the program in
> the simulation and on the machine (dry run, reduced feed) before cutting.

> **This is the `experimental` branch.** It adds zero points of operations (Move 0-Point with
> 5 axes, Set 0-Point as default, Reset 0-Point, Make 0-Point active), a stock with its own
> zero point, Play and Verify for a tilted tool (5 axes) and a second postprocessor for a
> machine with a turning head. **None of it has run on a machine yet.** Adaptive asks to be
> checked in Play or Verify before cutting.
> The tested version is the [`main`](https://github.com/AvangardeCam/AvangardeCam/tree/main)
> branch and its releases.

## Why AvangardeCam

**From a CNC programmer, for CNC programmers.** AvangardeCam was made on a shop floor, for
the work that really happens there.

The idea: **everyone can add the functions they need**, with the help of AI, to make their
own work better and easier. The code is built for it: small modules, tests, a clear map.

- **Free.** No expensive licences, no subscriptions, no seat limits.
- **Yours to change.** Use it, adapt it, share it, under the LGPL-2.1.
- **Your postprocessors are fully yours** (MIT): write one for your machine and keep it,
  share it or sell it.

## Features

- **Setups and zero points:** several setups per part, Snap-0-Point on a face, zero moved onto
  a wall or by a typed distance, rotated around Z, next setup from the stock the previous one leaves.
- **Stock:** allowances or exact size, the model in the middle.
- **Operations:** Contour tooling (compensation RL/RR, approach arcs, passes in XY and Z,
  ramps, start/end of the contour), Drilling (cycle 205, depth from the 3D model),
  Thread milling, Helix milling of holes, Slot milling, Facing, Adaptive clearing,
  Deburring.
- **Selection like in Blender:** Shift+click add/remove, Ctrl+click shortest path, Alt+click loop.
- **Simulation:** Simulate window with the stock removed live and the program line by line,
  Verify (stock against the model), collisions of rapid moves, holder and neck.
- **Cycle time** from the machine's dynamics.
- **Tool library** with feeds and speeds per material.
- **Postprocessor:** Heidenhain **TNC 620** plain language (`.H`), every setup on its own preset.
  Made for and tested on a **Bridgeport V1000 with a TNC 620** (control dialog in Dutch, e.g.
  `CYCL DEF 247 REF.PUNT VASTL.`). Other Heidenhain controls (TNC 640, 530, ...) and other
  machines may need changes: the end of tool and park moves (`M91`) are set per machine in
  `avangardecam/post/heidenhain.py`. Check the first programs carefully.
- **Experimental (this branch, not run on a machine yet):** each operation keeps the zero
  point it was made on. **Move 0-Point** moves the zero point (onto a wall, by a distance)
  and with **5 axes** turns it (Z out of a wall, or by angles about X, Y, Z); **Set 0-Point
  as default**, **Reset 0-Point** and **Make 0-Point active** (an operation's menu) go
  between them; Play, Verify and the cycle time run every operation from its own zero point,
  the tool tilted as that zero point is. The stock has a zero point of its own (the default
  one) and stays the same block wherever it is typed. One postprocessor for each machine, chosen in the export window: the
  Bridgeport V1000 one writes a shifted zero point as `CYCL DEF 7`, the **Soraluce T35** one
  (turning head) writes every operation with `CYCL DEF 7`, `PLANE SPATIAL` and the head cycle.
- **Easy to extend with AI:** add your own functions and write the postprocessor for your
  control with an AI coding assistant (see below).

## Installation

Needs **FreeCAD 1.1** or newer (Windows, Linux, macOS).

1. Download **[AvangardeCam.zip](https://github.com/AvangardeCam/AvangardeCam/releases/latest/download/AvangardeCam.zip)**
   (the latest release) and unpack it. It contains one folder, `AvangardeCam`.

   The **experimental version** (this branch, not run on a machine yet) is a pre-release of
   its own: **[AvangardeCam.zip of v0.2.0-experimental](https://github.com/AvangardeCam/AvangardeCam/releases/download/v0.2.0-experimental/AvangardeCam.zip)**.
   It installs the same way, in place of the tested one (one `AvangardeCam` folder at a time);
   to go back, put the tested version's folder there again.
2. Put the `AvangardeCam` folder into FreeCAD's `Mod` folder (create `Mod` if it is not
   there yet):
   - Windows: `%APPDATA%\FreeCAD\v1-1\Mod\`
   - Linux: `~/.local/share/FreeCAD/v1-1/Mod/` (Flatpak: `~/.var/app/org.freecad.FreeCAD/data/FreeCAD/v1-1/Mod/`)
   - macOS: `~/Library/Application Support/FreeCAD/v1-1/Mod/`

   FreeCAD shows its folder in the Python console: `App.getUserAppDataDir()`.
   The files must lie directly in it, e.g. `...\FreeCAD\v1-1\Mod\AvangardeCam\InitGui.py`.
3. Restart FreeCAD.

Developers can `git clone` the repository instead (the folder must be named `AvangardeCam`);
the green *Code → Download ZIP* gives `AvangardeCam-main`, which must be renamed.

On its first start AvangardeCam becomes FreeCAD's start workbench, hides the Start page and
sets red/yellow selection colours (they mean something in AvangardeCam). Another start
workbench can be chosen again in *Edit → Preferences → General*.

**Units:** set *Edit → Preferences → General → Units* to *Metric small parts & CNC* (mm, mm/min).

## Manual

A step-by-step [manual](docs/manual/README.md) with screenshots takes one part from the
3D model to the `.H` program, in two clampings ([Polish version](docs/manual/README.pl.md)).

## Extending with AI

AvangardeCam is built so that an AI coding assistant (Claude Code, Codex, Copilot, ...) can
work on it safely: every function lives in its own modules (`model/`, `engine/`, `ui/`) with
its own tests, so a new one does not touch the others, and
[ARCHITECTURE.md](ARCHITECTURE.md) describes how everything fits together.

**Your own postprocessor:** a postprocessor only turns the finished, control-neutral program
(`avangardecam/model/nc.py`) into text. Give the assistant
`avangardecam/post/heidenhain.py` as the example, a few real programs from your machine as
the target, and ask for `avangardecam/post/<your_control>.py` with tests like
`avangardecam/tests/test_post.py`.

> **Check every AI-written postprocessor before it cuts:** compare its output line by line
> with programs you trust, run it in the machine's own simulation, then a dry run above the
> part with reduced feed and rapid override.

## Tests

See [tests_gui/README.md](tests_gui/README.md): over 300 engine tests run in `FreeCADCmd`,
the GUI tests in a real FreeCAD window on the demo model `tests_gui/models/demo_bridge.step`.

## Training and consulting

Remote consulting and training in **English and Polish**: AvangardeCam and FreeCAD CAM,
Heidenhain TNC programming, writing a postprocessor for your machine, AI-assisted
("vibe coding") CNC courses for schools.

Details and rates: **[avangardecam.eu/training](https://avangardecam.eu/training/)**
(Polish: [avangardecam.eu/pl/szkolenia](https://avangardecam.eu/pl/szkolenia/)).

Contact: **[AvangardeCam@proton.me](mailto:AvangardeCam@proton.me)**

Bugs and ideas for the program: [GitHub issues](https://github.com/AvangardeCam/AvangardeCam/issues).

## Support

AvangardeCam is free and stays free, postprocessors included.
If it saves you time, you can support its development:
[Buy Me a Coffee](https://buymeacoffee.com/srebrzystyi).

## License

- AvangardeCam: [LGPL-2.1-or-later](LICENSE), like FreeCAD.
- Postprocessors (`avangardecam/post/`): [MIT](avangardecam/post/LICENSE), so a postprocessor
  you make from them is yours to keep, share or sell.

Both come **without any warranty**: you are responsible for every program you run on a machine.
