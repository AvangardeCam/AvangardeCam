# AvangardeCam — step-by-step manual

*Polska wersja: [README.pl.md](README.pl.md)*

This manual takes one part from the 3D model to a Heidenhain program (`.H`).
The example is a simple demo plate (70 × 40 × 10 mm, aluminium):
two counterbores for screw heads and four M6 holes, machined in two clampings.

## Contents

1. [The interface](#1-the-interface)
2. [Setup and Stock](#2-setup-and-stock)
3. [Drilling from the 3D model](#3-drilling-from-the-3d-model)
4. [Facing](#4-facing)
5. [The operation list](#5-the-operation-list)
6. [Simulation — Simulate](#6-simulation--simulate)
7. [Adaptive clearing](#7-adaptive-clearing)
8. [A sketch from the edges and picking lines](#8-a-sketch-from-the-edges-and-picking-lines)
9. [Contour tooling](#9-contour-tooling)
10. [Thread milling](#10-thread-milling)
11. [The second clamping — Next setup](#11-the-second-clamping--next-setup)
12. [NC program and checks](#12-nc-program-and-checks)

---

## 1. The interface

![AvangardeCam window](images/01_setup.jpg)

- **CAM ribbon** (top), in groups:
  - **Setup:** Job, Next setup, Snap-0-Point, Move 0-Point, Set 0-Point as default, Reset 0-Point, zero rotation, Stock, Tool library;
  - **Geometry:** Extract boundary edges;
  - **Measure:** measuring;
  - **Milling:** Contour tooling, Facing, Adaptive…;
  - **Holes:** Drilling, Helix, Thread milling;
  - **Output:** Simulate, Verify, Cycle time, FreeCAD sim, Export NC.
- **Project tree** (left): Model, Sketches, and in each Setup its Stock, Tools and Operations.
- **Details** (under the tree): what the selected item is. The main fields can be changed here without opening its window.
- **3D view:** a click selects faces, edges and sketch lines. The red line is the tool path of the selected operation.

Every operation window has a **Manual** button with the full description of how that operation works.

**View navigation (Blender style):** middle button rotates, Shift+middle pans, Ctrl+middle zooms.

---

## 2. Setup and Stock

### Setup

Click **Job**. **Setup 1 (active)** appears in the tree: the first clamping, with Stock, Tools and Operations.

The zero point starts on top of the model, in the middle. To move it:

- select a flat face and click **Snap-0-Point**: Z points out of the face, X0 Y0 lands in the middle of the part;
- **Rotate 0-Point 90° / 180° / …** turns the zero point about Z.

#### Moving the zero point within a setup (experimental)

> This part is experimental: it has not run on a machine yet. Check such a program on the control's own simulation and with a dry run.

The zero point Snap-0-Point gives is the setup's **default zero point**: the machine's preset. **Move 0-Point** moves the zero point away from it, and **every operation keeps the zero point it was made on**: operations made before the move stay as they are, new ones count from where the zero point was left. In the program each operation's zero point is given from the default one (a datum shift, and a tilted plane when it is turned).

- **Move 0-Point**: in its window click **Select wall**, then a flat face of the part: the zero point goes the shortest way onto that face (a wall square to X changes X only; a second wall adds to the first, so two or three walls give a corner). Or type how far it moves in **Move X / Y / Z**. The 3D view shows where the zero point would be; **OK** moves it.
- **5 axes** (a tick box in that window), for a machine that tilts: with **Z out of the wall** ticked, Select wall also turns the zero point's Z out of the wall, square to it, so the tool stands on that wall. **Turn about X / Y / Z** turns the zero point by the angles typed, about its own axes (X first, then Y, then Z, about the axes as they stand before the turn).
- **Set 0-Point as default**: the zero point as it stands becomes the default one (the preset).
- **Reset 0-Point**: the zero point goes back to the default one.
- **Make 0-Point active** (right click on an operation): the zero point goes to the one that operation counts from, to change it or to add operations there. An operation on another zero point is marked *(other 0-Point)* in the tree; **Edit…** on it makes its zero point active first.

Snap-0-Point and Rotate 0-Point move the whole setup (its default zero point with the operations on it); use them while the zero point is on the default one. Change the stock there too: on another zero point the stock is shown as the box around the same block.

Play, Verify and Cycle time run a setup on its preset: operations on a shifted zero point are shown in their place, operations on a tilted zero point are left out there for now.

### Stock

Click **Stock** on the ribbon. The stock is the model's box plus an allowance on each side.

![Stock window](images/02_stock.jpg)

| Field | Meaning |
| --- | --- |
| Size X / Y / Z | Size of the raw block. The model stays in the middle. |
| Allowance X− / X+ / Y− / Y+ | Allowance on each side separately. |
| Allowance bottom (Z−) | Material under the model (e.g. removed in the second clamping). |
| Allowance top (Z+) | Material above the model (removed by Facing). |

**OK** applies the changes. In the example the stock is 74.20 × 50.22 × 15.20 mm.

---

## 3. Drilling from the 3D model

Holes are drilled straight from the model: the diameter and depth are read from it. The program uses **CYCL 205** (deep drilling with chip breaking).

1. Click the wall of a hole in the 3D view. Add more holes with **Shift+click**.
   The click order is the drilling order.
2. Click **Drilling**.
3. Pick a drill from the list, or from the tool library with **Choose tool…**.
   A tool that is not in the setup yet is added to it.
4. Click **OK**.

![Drilling window](images/03_drilling_dialog.jpg)

| Field | Meaning |
| --- | --- |
| Depth (Q201) + From the model | Ticked: each hole as deep as the model has it. Unticked: a negative depth from the top of the hole (−10 = 10 mm deep). |
| Out under through holes | How far the drill comes out under a through hole. |
| Peck depth (Q202) | How often the drill leaves the hole (0 = the whole depth at once). |
| Chip break depth (Q257) | How often it backs off to break the chip (0 = never). |
| Chip break retract (Q256) | How far it backs off when breaking the chip. |
| Dwell at bottom (Q211) | Dwell time at the bottom. |

The line **The tip goes** shows how deep the drill tip goes, including its point.

![Drilling path](images/05_drilling_path.jpg)

The example has two drilling operations: **Drilling 1** (Ø6.5 drill in the counterbores) and **Drilling 2** (Ø5 drill for the M6 threads).

---

## 4. Facing

Facing takes the allowance off the top of the whole stock, down to the top face of the model.

1. Click the top face of the model.
2. Click **Facing**.
3. Pick a flat-end tool, e.g. a Ø50 face mill.

![Facing window](images/06_facing_dialog.jpg)

| Field | Meaning |
| --- | --- |
| Start Z + Top of the stock | Where the material starts. Ticked: always the top of the stock. |
| Z step | Depth of one level. The *Z levels* line shows the result. |
| Step over | Distance between passes, in % of the tool diameter. |
| Pattern | *Zigzag* (back and forth) or *One way*. |
| First pass | Direction of the first pass, along X or along Y. |
| Start from | The side of the stock where the tool starts. |

![Facing path](images/07_facing_path.jpg)

---

## 5. The operation list

![Operation list](images/08_operation_order.jpg)

- **Order:** drag an operation up or down in the tree, e.g. Facing 1 before the drilling.
- **Edit:** right click → **Edit...** opens the window the operation was made in. Quick changes can also be made in Details.
- **Hide:** right click → **Hide in 3D**. The operation is marked *(hidden)* and its path no longer clutters the view. It stays in the program.
- **Switch off:** right click → **Switch off**. The operation stays in the list but is left out of the program and the simulation.
- **Delete:** right click → Delete.

---

## 6. Simulation — Simulate

Click **Simulate**. The active setup's program is played as the machine runs it, with the stock cut away live.

![Simulation window](images/09_play.jpg)

- **Right:** the operations with their tool and time, and below them the `.H` program. The highlighted line is the one running.
- **Bottom:** a timeline of the operations. Click in it to jump.
- **Buttons:** play/pause (Space), step forward and back, speed from ×0.1 to ×100.
- **Top:** views (Isometric, Top, Front, Right, Fit), Stock / Part / Path on or off, and Accuracy.

![Adaptive in the simulation](images/19_play_adaptive.jpg)

---

## 7. Adaptive clearing

Adaptive roughs out material with an even load on the tool: a small step over and deep cuts. It never cuts into the model.

1. Click **Adaptive** with nothing selected to clear around the whole model.
   Select floors first to clear only their area.
2. Pick an end mill, e.g. Ø6.

![Adaptive window](images/12_adaptive_dialog.jpg)

| Field | Meaning |
| --- | --- |
| Start Z + Top of the stock | Where clearing starts. Ticked: the top of the stock. |
| Z-Depth | The lowest level. |
| Z step | Depth of one cut. Every flat floor of the model gets a level of its own as well. |
| Step over | Side step in % of the diameter. |
| Finish XY / Finish Z | Material left on walls and floors for finishing. |

The **Z levels** line lists every level.

![Adaptive path](images/13_adaptive_path.jpg)

---

## 8. A sketch from the edges and picking lines

Contour operations follow the lines of a sketch, and one click makes that sketch.

1. Select a flat face (e.g. the top of the plate).
2. Click **Extract boundary edges**. A sketch with all edges of that face appears under Sketches.

![Picking lines](images/15_pick_lines.jpg)

Lines are picked in the 3D view as in Blender:

| Click | Result |
| --- | --- |
| click | this line only |
| Shift+click | add the line (again: remove it) |
| Ctrl+click | the shortest way from the last line to this one |
| Alt+click | the line's whole closed loop |

Picked lines show **direction arrows**. Click an arrow to reverse the direction.
The picking order is the machining order.

---

## 9. Contour tooling

The tool follows the picked lines, with radius compensation or with its centre on the lines.
Pick the lines and click **Contour tooling**. With no lines picked, all lines of the sketch are used.

![Contour tooling](images/20_contour2_dialog.jpg)

| Field | Meaning |
| --- | --- |
| Start Z | Top of the material. |
| Z-Depth | Bottom of the contour. |
| Relative | Ticked: Start Z and Z-Depth are measured from each line's own height (−1 = 1 mm below the line). Unticked: from the zero point. |
| Compensation | *Left (RL)* / *Right (RR)*: the control keeps the tool beside the line by the radius from the tool table. *Off*: tool centre on the line. |
| Approach | *Arc*: in on an arc from beside the line. *None*: straight down onto the line. |
| Approach radius | Radius of the approach arc (with compensation it must be larger than the tool radius). |
| Z step / Finish Z | Depth per cut and the allowance on the floor. |
| XY width / XY step / Finish XY | Width cleared in XY, the step and the finishing pass. |
| XY offset | Moves the tool centre sideways (e.g. for a chamfer mill). |
| Order | Order of the passes: each XY pass all the way down, or level by level. |

Under **Advanced**:

- **Contour side:** which side of the lines (RL climbs with M3);
- **Off with arc:** centre on the line, but with an arc approach;
- **Start / End contour:** makes open lines longer (or, negative, shorter) at their start and end.

### Example: the four contours of the plate

**Contour 1 — counterbores.** The counterbore lines, Z-Depth −6.8 mm.

![Counterbore path](images/18_contour_path.jpg)

**Contour 2 — outer profile.** The outline, compensation RL, arc approach.

![Outline path](images/21_contour2_path.jpg)

**Contour 3 — deburring.** All lines, chamfer mill T29, **Relative** ticked, Z-Depth −1 mm, compensation Off and XY offset 0.85 mm (under Advanced).

![Deburring](images/22_contour3_dialog.jpg)

Hover over **Relative** to see its tip:

![Relative tip](images/23_relative_tip.jpg)

**Contour 4 — edges at the bottom of the counterbores.** Lines from several sketches at once (Face20 and Face27). Each line is cut at its own height.

![Contour from several sketches](images/27_contour4_dialog.jpg)

---

## 10. Thread milling

1. Shift+click the holes in the model (in machining order).
2. Click **Thread milling**.
3. Pick a thread mill (*Thread mills only*).

![Thread milling](images/25_thread_dialog.jpg)

| Field | Meaning |
| --- | --- |
| Major diameter | Nominal diameter of the thread (M6 = 6 mm). The pitch comes from the tool. |
| Depth | Negative, from the top of the hole. |
| Passes | How many times the same helix is run. |

The tool goes down to the top of the hole, out to the thread with RR compensation and down a clockwise helix (right-hand thread).

![Thread milling path](images/26_thread_path.jpg)

Clamping 1 finished, in the simulation:

![End of clamping 1](images/29_play_final.jpg)

---

## 11. The second clamping — Next setup

Turn the part over to machine its underside. Click **Next setup**.

![Next setup](images/31_next_setup.jpg)

| Option | Meaning |
| --- | --- |
| Stock from Setup 1 | The stock is what Setup 1's program leaves (worked out at *Medium*, *Fine*… accuracy). |
| Standard stock | The model's box with allowances. |
| Custom stock | A model of the blank (e.g. a casting) from a STEP, IGES, BREP or STL file. |

Click **Make setup**. **Setup 2 (active)** is created.

### Zero point for the second side

The zero point is still the one of Setup 1. Click the face that is now on top (the underside of the part), then **Snap-0-Point**. The stock follows.

![Zero on the underside](images/34_zero_bottom.jpg)

### Machining the underside

From here it works as in clamping 1:

- **Facing 2:** face off the allowance on the underside;

  ![Facing 2](images/35_facing2_dialog.jpg)

- **Extract boundary edges** on the bottom face and **Contour tooling** with a chamfer mill: deburring the underside.

  ![Deburring the underside](images/36_contour_setup2_dialog.jpg)

The Setup 2 simulation starts from what Setup 1 left:

![Setup 2 simulation](images/38_play_setup2.jpg)

---

## 12. NC program and checks

| Button | What it does |
| --- | --- |
| **Simulate** | The program played as on the machine (section 6). |
| **Verify** | The active setup's program cut out of its stock: too deep into the part in red, material left in blue, and rapid moves into material. |
| **Cycle time** | Time of each operation and setup in a table, from the machine's dynamics. |
| **Play** | The program played as on the machine (section 6). |
| **Export NC** | Heidenhain plain language (`.H`), every setup on its own preset. The machine is chosen as the file type of the export window. |

> The **Bridgeport V1000** postprocessor (TNC 620) is made for and tested on that machine. On another machine, check the first programs carefully. It writes a shifted zero point as a datum shift (`CYCL DEF 7`, experimental) and refuses a turned one.
>
> The **Soraluce T35** postprocessor (turning head) is experimental and has not run on the machine yet. It writes every operation on its own: the labels RESET and FREE, the tool call, the datum shift (`CYCL DEF 7`), `PLANE SPATIAL` with the zero point's angles and the head cycle. Programs with one angle (a wall of a block) follow the shop's own programs; check programs with more than one angle with extra care.
