# AvangardeCam tests

## Unit tests

```sh
# model layer and postprocessors, plain Python, from src/Mod/AvangardeCam
python3 -m unittest avangardecam.tests.test_model avangardecam.tests.test_post

# model + engine inside FreeCADCmd (its console output is swallowed, read the report);
# the add-on installed in FreeCAD's Mod folder
AC_TEST_REPORT=/tmp/ac.txt FreeCADCmd <Mod folder>/AvangardeCam/avangardecam/tests/run.py
cat /tmp/ac.txt
```

## GUI tests

- `test_layout.py`: stage 1, the layout, no placeholder shown (nor an empty group), Extract boundary edges also on the CAM tab, File menu, expert mode and back.
- `test_project.py`: stage 2, STEP import creating the job, stock allowances with undo,
  tools from the shop's library (Ø beside the name; a click on the T or Ø header sorts
  smallest first, again largest first, also with a filter), selection list <-> 3D, save and reopen.
- `test_stock_size.py`: the stock's details, Stock size...: the dialog starts at the present
  size, 50 × 30 × 20 puts the 40 × 20 × 12 model in the middle (allowances 5, 5, 4 follow),
  undo in one step, a size smaller than the model refused with a message, the dialog open.
- `test_stock_window.py`: CAM > Stock on the ribbon opens the Stock window (the details in a
  window, a picture beside the fields: the allowances, or the size for Size X/Y/Z); the size puts
  the model in the middle, a typed allowance changes the size, the stock changes on OK in one undo
  step, a size smaller than the model refused in the red line, Cancel changes nothing.
- `test_setups.py`: stage 3, Extract boundary edges, Contour tooling from the top (no tool
  yet: OK refused, Choose tool picks T21 RVS from the library; Z-Depth not above Start Z, equal = one pass, Start Z
  and Z-Depth above the zero typed in the details, undo in one step), Snap-0-Point
  making a second setup on the front face (the view in its coordinates: the front up, the
  zero at the origin) with its own contour (starting with the tool
  used last), switching setups, double-click in 3D, save and reopen, the Heidenhain .H program of both
  setups, expert mode and back.
- `test_lines.py`: the extracted sketch selected at once, green and thick, red when
  selected; real mouse clicks on its lines win over the model's edges and faces, Contour
  tooling follows the clicked lines in click order (its picture beside the fields: the
  contour, in Z step the order of the passes chosen); Shift+click adds or takes away a line,
  Ctrl+click adds the shortest way, Alt+click selects a loop; direction arrows in the
  middle of the selected lines, a click on one turns its chain round (also a single
  line) and the contour follows the arrows; the tool compensation and approach menus in the
  dialog (off = straight down, RL, RR; Advanced: the contour side (= RL/RR with compensation), off with arc,
  a radius of tool radius + 0.5 mm, the XY offset without compensation; unchecked: off again; the last choice remembered) and in the details (RL without an approach: down beside the line,
  RL above the part, drawn: the tool centre down, yellow across to where its edge cuts,
  the lines there, yellow back; on an arc: down in its centre, no yellow; radius typed;
  undo: FreeCAD's tool centre drawn again); Change tool in
  the details takes T8 from the library, undo gives T21 back and T8 stays whole; the passes in
  the details (XY off without compensation, Z step, XY width and step, finishing allowance:
  3 XY × 2 Z, undo) and in the dialog (an XY offset past the line, by Z level, remembered);
  the path of the operation selected in the list red (its cutting moves only, again after
  the path changes, none with a sketch selected); a right click on an operation opens its
  menu where it was clicked (a left click only selects it; Edit..., Activate geometry, Make 0-Point active, Switch off, Hide in 3D, Delete): Hide in 3D and Show in 3D, Switch off (no
  path, not in the program, "(off)" in the list, undo), Edit... (its window with its values,
  tool and lines; one undo step; the values used last for new contours stay).
- `test_deburring.py`: Extract boundary edges of the top, the whole sketch, CAM > Deburring on
  the ribbon: chamfer 0.5 / tip 0.5, left, straight down, Advanced hidden by default; OK without a
  tool refused, T29 from the library; the line under the fields follows the chamfer (0.15 / 0.85:
  0.85 mm beside, 1 mm deep; 2.5 too large for T29); Advanced starts where the chamfer puts the tool
  and says the chamfer they make; Manual; on this part the outline would be cut inside: OK asks
  "Deburr anyway?" (No keeps the window, Yes makes Deburring 1 = the user's contour), the details
  say it too; the chamfer typed in the details goes deeper, undo; Advanced there keeps the tool;
  Edit... (Advanced off, the right side: asks about the two holes); the .H program; a new one starts
  with the values and tool used last, on an arc of 3.5 mm asks about the holes (the arc does not
  fit; the warning under the fields not cut off); the .H title "Deburring"; the sketch's details have Deburring...
- `test_contour_ends.py`: Start contour and End contour under Advanced: hidden without it,
  +5 / -3 mm make the contour; the rows not squashed, no long note under the fields, Manual
  opens how the contour works in a window of its own; in the details Advanced checked for it, Start contour 0 moves
  where the tool goes down by 5 mm, undo; Advanced unchecked runs the whole lines; Edit...
  opens with Advanced and the values.
- `test_contour_from_below.py`: a block (made as a STEP by the test, AC_STEP not used), the first
  setup from the top; the bottom's sketch faces away from the tool: its details list the setup from
  the other side, its lines at Z-12; Contour tooling opens on it and cuts 1 mm below them.
- `test_contour_relative.py`: a block with an island (made as a STEP by the test, AC_STEP not
  used), the zero point on the island's top: a line of the island and one of the plate (Z-4) in one
  contour; Relative checked at first (its note and the tool tips: from the lines), unchecked
  Z-Depth -10 cuts both at Z-10; in the details unchecked, Lines at Z 0 and -4, checked cuts at -10
  and -14, undo in one step; a new contour starts with Relative as used last; Edit... opens with
  the contour's; the plate sketch's details show Lines at Z-4 from the zero point.
- `test_cycle_time.py`: two contours with one tool; looking works nothing out (the Time rows
  of the setup and the operations offer a link), the link does: total, then feed, rapid, tool
  change, the setup's the sum of its operations', the tool change in the first only; other
  entries and a hidden operation keep the times. CAM > Cycle time: a table (setup, operations,
  tool), Copy; an operation switched off makes the rows and the window out of date,
  Recalculate shows it switched off and the setup's time down by it.
- `test_verify.py`: CAM > Verify without operations only says so; with a contour on the top's
  boundary its window opens (titled after the setup, Medium 250 at first) and waits for Start, then
  cuts in the background, reports too deep and rapid moves (and threads without their hole, or
  nothing about them without threads), the 3D view shows the stock left in
  colours instead of the part, Export saves it as .ply and .stl; Rough and Start cut once more
  (remembered); closing gives the part back.
- `test_drilling.py`: the two holes of the test model's top clicked (Shift+click the
  second) in the order they are drilled; the Drilling window (no tool: OK refused, T40
  from the library with its feeds Q206/Q253, Drills only on: an end mill chosen switches it
  off, on again hides it, Choose tool... shows only drills until switched off, a positive depth refused, the tip's depth to
  the full diameter, Advanced shows the cycle's other values), the drilling in click order,
  its details live with undo, cycle 205 and CYCL CALL POS in the program, the simulator, the
  window remembering the values and suggesting the Ø4.5 drill (T47) in the material
  of the tool used last, a whole sketch meaning all its circles, save
  and reopen, then Edit... of the reopened drilling (its holes, tool and values; the peck
  changed, the click order kept).
- `test_model_drilling.py`: the two Ø4.5 holes through the test model clicked on their
  walls in the isometric view (Shift+click adds, takes away, adds again); the Drilling
  window: the model, its holes (through), From the model on (depth off, 1 mm out under
  through holes), the shop's Ø4.5 drill (T47) suggested in the
  material of the drill used last, T40 Ø6.8 warned about; the drilling in click order
  through the part; the details switch From the model off and back by undo; CYCL CALL POS
  in the program; a second drilling starts with the setup's T47; save and reopen.
- `test_thread_milling.py`: the two Ø4.5 holes of the test model's top clicked (Shift+click
  the second) in the order they are threaded; the Thread milling window (no thread mill
  makes a standard thread of Ø4.5: none chosen, OK refused; Thread mills only on: a drill
  chosen switches it off and is refused, on again hides it, Choose tool... shows only thread
  mills until switched off; T218 M5 P0.8
  from the library: the major diameter suggested 4.5 + 0.8, typed 5 = M5, the helix
  "10 turns of P0.8, 2 passes"); the tool centre's helix in click order; the details
  (passes live, undo); the program (CP IPA-180. IZ-0.4 DR-, out to the thread with RR); the
  simulator; Edit... (6 deep); a hole clicked in the model starts with the thread mill and
  depth used last; save and reopen.
- `test_adaptive.py`: CAM > Adaptive with nothing selected (the whole model): the window's
  area, Z-Depth from the model's lowest floor (its top), no tool (OK refused), a drill refused,
  T2 too short for 12 mm at once, T5 (step over 1.2 mm, its feeds), the Z levels as Z-Depth and
  the Z step are typed (-3, -7, -11, -12 and the floor), Start Z (the top of the stock ticked;
  typed 0 with Z-Depth 0: one level on the top; -0.1: the top left, -4.1, -8.1, -12; ticked
  again); the clearing down to Z-12, its details
  (Z step live, undo), the program (Adaptive Clearing, Z+20, 2 mm above the stock), the
  simulator, Edit... (step over); the top picked in the model: its area, the tool and the Z
  step used last; save and reopen.
- `test_rotate_zero.py`: CAM > Rotate 0-Point 90°, 180° and by an angle typed in its window
  (90° offered the first time, then the last angle; Cancel changes nothing); the details
  show the rotation, the stock turns with the axes, the zero point stays, the view
  follows, Undo names the step and takes it back.
- `test_move_zero.py`: a block with a hole (made as a STEP by the test, AC_STEP not used); CAM >
  Move 0-Point beside Snap-0-Point opens a window that does not block the 3D view; Select wall
  and a real click on the right wall: Move X to the wall (a typed value replaced), the wall
  named, not left selected, where the zero point would be drawn in 3D; a round face refused,
  the button still waiting; the front wall too (a corner, the typed Z kept); OK moves the zero
  point, the stock and the view follow, the details and the status bar say it, Undo names the
  step and takes it back; a face selected before the click on the ribbon is taken at once;
  Cancel and OK without a shift change nothing and make no undo step; one window at a time.
- `test_circle_zero.py` (experimental): a tube along Y, hollow inside, with a bore into the
  hollow and four holes in its end (made as a STEP by the test); Move 0-Point > Select circle
  and a real click on the bore's round edge: the shift to its middle, without 5 axes no turn
  and a word that the axis is not along Z; 5 axes ticked after the pick turns Z out of the end
  then; a flat face refused, the button still waiting; Select wall and Select circle not
  pressed together; a real click deep in the bore (its wall) and its far edge where it opens
  into the hollow still give its mouth on the end, Z out of the tube; OK: the zero point there,
  the tool out of the end, one undo step, the status bar; the holes in the end can be drilled
  from it; the next window keeps 5 axes ticked and takes a hole's wall selected before it opens
  at once (its mouth); 5 axes unticked is kept too; Cancel; Undo takes it back.
- `test_op_zero.py` (experimental): the same block with a contour on its top; Set 0-Point as
  default and Reset 0-Point beside Move 0-Point; Move 0-Point with "5 axes" and "Z out of the
  model": a click on the right wall gives the shift and 90° about Y; after OK the tool axis is
  the wall's, the contour made before keeps its zero point (marked "other 0-Point", drawn on
  its own zero point, its details say where it counts from), the stock is the same block; a
  contour on the wall counts from the new zero point; "Make 0-Point active" in the menu of
  the first one goes back; the Soraluce program has the datum shift and the tilted plane and
  leaves the zero point and the undo list alone, the Bridgeport one refuses the turned zero
  point; Set 0-Point as default and its Undo, Reset 0-Point; Edit on an operation of another
  zero point opens its window on that zero point; Rotate 0-Point away from the default zero
  point is refused.
- `test_zero_stock_play.py` (experimental): a contour on the top and one on the right wall
  (the zero point turned onto it); the Stock window on the wall's zero point works along the
  axes the user sees and the block changes on the default zero point; at an odd angle the
  block is drawn as it lies and the Stock window and the details work along the stock's own
  axes and say so; Play runs the program of the machine that tilts, the tool lying along
  the wall's Z, the stock cut there too, nothing run into; Verify checks both contours and
  shows the stock left where the active zero point has the part.
- `test_measure.py`: CAM > Measure from 0-Point: the top face clicked (away from the
  setup's axes on the zero point), Shift+click adds the front face; the window (not modal)
  shows their smallest and largest X, Y, Z together and the sizes, as FreeCAD's exact box
  of the faces less the zero; the whole model; nothing selected only says so and the
  window keeps its values; after Rotate 0-Point 90° X is the old Y and Y the old -X.
  Measure local in the turned setup: the top face's sizes, a Ø4.5 hole (centre, 12 deep,
  through), two holes (30 apart, 25.5 between their nearest points and along Y, overlapping along X, ΔY 30), the front face and a hole (10 to the centre,
  7.75 and 12.25 to its sides).
- `test_simulation.py`: CAM > Simulate opens FreeCAD's OpenGL simulator for the active
  setup (titled, over the middle of the window), middle button rotates, Shift+middle pans
  with the part following the cursor, Ctrl+middle up zooms in, Play runs it, it closes and
  opens again;
  without operations it only says so.
- `test_undo_redo.py`: Undo and Redo next to File are FreeCAD's Std_Undo / Std_Redo
  (disabled on an empty project), the tooltip names the step ("Undo: Stock allowance
  (Ctrl+Z)"); the buttons and Ctrl+Z / Ctrl+Shift+Z take a stock allowance back and do it
  again with the list and the details following; they still work after expert mode and
  back; a new project disables them.

- `test_facing.py`: CAM > Facing with nothing clicked only says what to click; the top face
  clicked: the window (its picture beside the fields, the face, Start Z from the top of the stock, the Z levels, no tool: OK
  refused, a drill refused, T5: 4.2 mm step over and 5 passes, the face mill T16 Ø50: 1 pass, its
  feeds; Start Z under the face refused, back to the stock), the facing on Z0, its details (one way
  live, undo), the program (Facing, Z+20, 2 mm above the stock), Edit... (first pass along Y, step
  over 60 %), a new facing starts with the tool and values used last (Cancel makes nothing); save
  and reopen.
- `test_slot.py`: a plate with a blind slot and a through slot made in the test and imported as
  STEP (AC_STEP is not used). CAM > Slot with nothing clicked only says what to click; a wall of
  the blind slot clicked: the window (the slot, the depth from the model, no tool: OK refused, a
  drill refused, Ø10 as wide as the slot: along the centre only, Ø6: Z levels and passes as typed,
  a depth through the floor refused, the automatic approach radius), the slot milling, its details
  (RR live, undo; drawn as programmed: the finishing pass on the walls), the program with RL,
  Edit... (the ramp along the contour: helices in the program), two slots (Shift+click) starting with the values
  and the tool used last, save and reopen, Activate geometry.
- `test_helix.py`: the two Ø4.5 holes through the test model picked in the model (right first);
  CAM > Helix with nothing selected only says what to click; the window (the holes, the depth from
  the model, no tool: OK refused, a drill refused, T2 Ø3: Auto pitch 0.2625, the step over in mm,
  two helices, one without Finish XY), the helix milling in click order to Z-13, RL from the first
  pass in the program, the view drawing the program; the details (XY offset 0.025 live, undo); the
  simulator; Edit... (a helix, then circles: T2 too short for 13 mm at once, Z step 4); Activate
  geometry; Helix milling... in the sketch's details (all its circles, a depth to type, the tool used
  last); save and reopen.
- `test_select_surfaces.py`: a right click on the 3D view opens FreeCAD's menu with Select all
  surfaces first; it selects every face of the test model once (also
  the top face clicked before) and says how many; Measure from 0-Point then shows the whole model and
  Shift+click on a face takes it away.
- `test_operation_order.py`: three contours, real mouse events on the list: dragging the first below
  the third shows a line under it, releasing moves it there (the list and the program follow, it stays
  selected, one undo step "Move operation"), the last dragged above the first; a plain click moves nothing;
  Escape mid-drag, over the tools (the forbidden cursor) and where it already is (no line) move nothing and
  make no undo step; undo twice gives the order they were made in.
- `test_delete_operation.py`: three contours, the middle one hidden; Delete last in its menu (a real right
  click in the list, Del beside it) takes it and its helper objects out of the document, the list and the
  program, the next one selected, the status bar says Undo brings it back, one undo step "Delete operation";
  undo gives it back in its place with its helpers, shown; redo takes it away again; the Delete key (a real
  key press on the list) deletes the selected last one, the one before it selected; the only one deleted: the
  Operations group selected; the model, the sketch and the tool stay; undo three times gives all three back.
- `test_sketch_visibility.py`: a right click on the extracted sketch in the list opens its menu (Hide in 3D;
  on a model no menu); hidden: not drawn, "(hidden)" in the list, no arrow on its selected lines, the contour
  made on it still shown and in the program; saved and reopened still hidden; Show in 3D draws it with its arrow.
- `test_activate_geometry.py`: Activate geometry in the menu of an operation (a real right click in the
  list) selects what it was made on: a contour's two lines in its order with the arrows turned its way (a new
  contour from them runs the same), a contour of all lines = the whole sketch with no arrow turned, a model
  drilling's holes in drilling order (a new drilling from them drills them so), a facing's top face, nothing
  for an adaptive clearing of the whole model; the status bar says what.

- `test_playback.py`: two contours with two tools; CAM > Play opens the simulation in a window of its own
  (the project's view untouched); the whole exported program in its list, the whole time the cycle time, the
  stock the whole block and the first TOOL CALL at the start; Right block by block runs lines of the program,
  Left one back, Down/Up by operation (the second's TOOL CALL and tool); a click on a line goes to where that
  block has run; End: material taken; Space plays at x10 (the tool moves, the stock drawn again while it
  plays) and pauses (the stock where the tool is); the speed remembered; Fine: smaller cells; Part shows the
  part; Escape closes it. A third contour deeper than its tool's cutting length with its safe height 5 below
  the top: End finds FMAX into material and the shank in material (red marks, red lines of the program, the
  button says which: 1 of 9 and goes there), played from the start it stops at the first. Closing the
  document closes it too.

- `test_custom_stock.py`: CAM > Custom stock on the ribbon opens its window (the middle checked at
  first, OK without a file refused in the red line); a casting drawn far away from the part is put
  with its middle on the model's middle, the list says Blank, the details name the file and say it is
  on the middle; undo / redo in one step; Custom stock... in the Stock window opens the same window, a
  blank turned 90° is loaded and a message says the model sticks out (X− and X+ by 7 mm); a blank
  kept where the file draws it: the details say how far off it is, Put in the middle (undo); the
  unchecked box remembered and shown in Next setup, checking it chooses Custom stock; an STL blank drawn
  itself (not its box), a STEP blank as the stock; a blank drawn over the part stays there; a right
  click on the stock: Move stock... (X+5 Z-2, the message that the model sticks out 3 mm at X−, one
  undo step), a box's menu without Move stock.
- `test_dark_system.py`: FreeCAD's light theme (its profile seeded from `test_dark_system.user.cfg`)
  under a dark system palette (Pop dark: FreeCAD from Flatpak takes it): the details under the project
  list on the dock's light background with readable text, their captions and the ribbon's group titles
  grey (#808080), not the system's mid colour.
- `test_exact_stock.py`: a part with round tops of R 515 on a base 2400 long, imported from STEP: the
  stock with allowances 1 mm (then 3 mm typed) over the arcs' top, from the exact faces, also where
  FreeCAD's box of the drawn part is under it (`AC_EXACT_STEP`: a part of one's own, top at Z 515).
- `test_next_setup.py`: CAM > Next setup opens its window (Stock from the last setup checked at first,
  Medium, where the zero point goes; Standard has no accuracy; Custom without a file refused, the window
  stays; Cancel makes nothing); a contour in Setup 1, then Next setup from Setup 1 at Rough (remembered):
  Setup 2 active, its stock from Setup 1 drawn instead of its box, the list says "From Setup 1", the
  details (From, Worked out, Accuracy, Work it out again); Setup 1 active shows its own box; one undo step
  "Next setup" takes Setup 2 and the stock left away; Standard from the window: a box; Custom: a casting
  from a STEP the test makes, its size and file in the details; another setup from Setup 1 with Adaptive
  down to Z-4 in it (no cuts at Z-1 and Z-2, where the contour took the material), Simulate and Play
  open on the stock left.

- `test_selection_kept.py`: a sketch from a saved file, two circles clicked and drilled with T40 new
  from the library, then two lines contoured with T21 new from the library: after OK the clicked
  circles and lines stay selected in click order with their arrows (FreeCAD making a tool bit
  selected the whole sketch).

Each test starts with `avangardecam.forget_last_values()`: the values the dialogs remember
(parameters named `Last...`: last tool, depth, compensation, passes, drilling) would
otherwise change what a test sees, so the tests run the same on a used profile.

They need a real OpenGL display; `QT_QPA_PLATFORM=offscreen` hangs. A nested X
server works:

```sh
Xephyr :5 -screen 1920x1080 -ac -br -noreset &
OUT=$(mktemp -d)
mkdir -p $OUT/home/Mod && ln -s "$PWD" $OUT/home/Mod/AvangardeCam   # an empty profile with the add-on
AC_TEST_OUT=$OUT AC_STEP=/path/to/model.step FREECAD_USER_HOME=$OUT/home DISPLAY=:5 \
    FreeCAD tests_gui/test_project.py
cat $OUT/test_project.txt   # log; screenshots are saved next to it
```

A test with its own preferences has `tests_gui/<test>.user.cfg` next to it: copy it into the
empty profile first (`cp tests_gui/test_dark_system.user.cfg $OUT/home/user.cfg`).

After changing Python files restart FreeCAD.
