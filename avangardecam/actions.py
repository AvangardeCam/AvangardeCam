# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Catalog of the program's functions: ribbon tabs, groups and the File menu.

The widgets are built from these tables, so adding a function means adding
one line here and, once it does something, a handler in handlers.py.
An action without a handler is a placeholder: it stays in the catalog,
but the File menu and the ribbon do not show it (shown_file_menu,
shown_tabs).

Texts are English source strings; QT_TRANSLATE_NOOP marks them for lupdate
and the widgets translate them when they are built.
"""

from dataclasses import dataclass, field

from PySide.QtCore import QT_TRANSLATE_NOOP

LARGE = "large"  # icon above the text, a column of its own
SMALL = "small"  # icon left of the text, three per column


@dataclass(frozen=True)
class Action:
    key: str
    text: str
    icon: str = ""  # FreeCAD resource icon (":/icons/<icon>.svg") or file in Resources/icons
    size: str = SMALL
    tip: str = ""
    handler: str = ""  # function name in handlers.py; empty means placeholder


@dataclass(frozen=True)
class Group:
    key: str
    text: str
    actions: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class Tab:
    key: str
    text: str
    groups: tuple = field(default_factory=tuple)


def _t(text):
    return QT_TRANSLATE_NOOP("AvangardeCam", text)


SEPARATOR = None

FILE_MENU = (
    Action("file_new", _t("New"), "document-new", handler="new_document"),
    Action("file_open", _t("Open..."), "document-open", handler="open_document"),
    Action(
        "file_import_step",
        _t("Import model (STEP)..."),
        "Std_Import",
        tip=_t("Add a STEP model to the current project"),
        handler="import_step",
    ),
    Action("file_save", _t("Save"), "document-save", handler="save_document"),
    Action("file_save_as", _t("Save as..."), "document-save-as", handler="save_document_as"),
    SEPARATOR,
    Action(
        "file_export_gcode",
        _t("Export NC program..."),
        "CAM_Post",
        tip=_t("Heidenhain TNC plain language (.H), every setup on its own preset"),
        handler="export_nc",
    ),
    Action("file_settings", _t("Settings..."), "preferences-general"),
    SEPARATOR,
    Action(
        "file_expert_mode",
        _t("FreeCAD (expert mode)"),
        "freecad",
        tip=_t("Show the full FreeCAD interface; come back by choosing the AvangardeCam workbench"),
        handler="expert_mode",
    ),
    Action("file_exit", _t("Exit"), "application-exit", handler="exit_program"),
)

TABS = (
    Tab(
        "cad",
        _t("CAD"),
        (
            Group(
                "geometry",
                _t("Geometry"),
                (
                    Action(
                        "cad_extract_boundary",
                        _t("Extract boundary edges"),
                        "Sketcher_Projection",
                        LARGE,
                        _t("Make a sketch of the edges of the selected flat face, in its plane"),
                        "extract_boundary",
                    ),
                ),
            ),
            Group(
                "draw",
                _t("Draw"),
                (
                    Action("cad_line", _t("Line"), "Draft_Line", LARGE),
                    Action("cad_polyline", _t("Polyline"), "Draft_Wire"),
                    Action("cad_rectangle", _t("Rectangle"), "Draft_Rectangle"),
                    Action("cad_circle", _t("Circle"), "Draft_Circle"),
                    Action("cad_arc", _t("Arc"), "Draft_Arc"),
                ),
            ),
            Group(
                "modify",
                _t("Modify"),
                (
                    Action("cad_move", _t("Move"), "Draft_Move", LARGE),
                    Action("cad_rotate", _t("Rotate"), "Draft_Rotate"),
                    Action("cad_mirror", _t("Mirror"), "Draft_Mirror"),
                    Action("cad_offset", _t("Offset"), "Draft_Offset"),
                    Action("cad_trim", _t("Trim / extend"), "Draft_Trimex"),
                ),
            ),
            Group(
                "measure",
                _t("Measure"),
                (
                    Action("cad_measure_distance", _t("Distance"), "Measurement-Distance"),
                    Action("cad_measure_angle", _t("Angle"), "Measurement-Angle"),
                    Action("cad_measure_radius", _t("Radius"), "Measurement-Radius"),
                ),
            ),
        ),
    ),
    Tab(
        "cam",
        _t("CAM"),
        (
            Group(
                "setup",
                _t("Setup"),
                (
                    Action(
                        "cam_job",
                        _t("Job"),
                        "CAM_Job",
                        LARGE,
                        _t("The active setup: stock around the model, tools"),
                        "edit_stock",
                    ),
                    Action(
                        "cam_next_setup",
                        _t("Next setup"),
                        "CAM_OpCopy",
                        LARGE,
                        _t("A new setup, the part clamped again: from the stock the setup before leaves, a box with allowances or a model of the blank (a casting)"),  # fmt: skip
                        "next_setup",
                    ),
                    Action(
                        "cam_snap_zero",
                        _t("Snap-0-Point"),
                        "Std_CoordinateSystem",
                        LARGE,
                        _t("Put the zero point on the selected flat face: Z out of the face, X0 Y0 in the middle of the part"),  # fmt: skip
                        "snap_zero",
                    ),
                    Action(
                        "cam_rotate_zero_90",
                        _t("Rotate 0-Point 90°"),
                        "Draft_Rotate",
                        tip=_t("Turn the zero point 90° about Z, counter-clockwise seen from the tool: the new X is the old Y"),  # fmt: skip
                        handler="rotate_zero_90",
                    ),
                    Action(
                        "cam_rotate_zero_180",
                        _t("Rotate 0-Point 180°"),
                        "Draft_Rotate",
                        tip=_t("Turn the zero point 180° about Z"),
                        handler="rotate_zero_180",
                    ),
                    Action(
                        "cam_rotate_zero_angle",
                        _t("Rotate 0-Point..."),
                        "Draft_Rotate",
                        tip=_t("Turn the zero point about Z by any angle, counter-clockwise seen from the tool"),
                        handler="rotate_zero_angle",
                    ),
                    Action("cam_stock", _t("Stock"), "CAM_Shape", tip=_t("The stock in a window: its size with the model in the middle, or the allowances"), handler="stock_window"),  # fmt: skip
                    Action("cam_machine", _t("Machine"), "CAM_Machine"),
                    Action(
                        "cam_tool_library",
                        _t("Tool library"),
                        "CAM_ToolTable",
                        LARGE,
                        _t("Add the shop's tools to the project"),
                        "tool_library",
                    ),
                ),
            ),
            Group(
                "cam_geometry",
                _t("Geometry"),
                (
                    Action(
                        "cam_extract_boundary",
                        _t("Extract boundary edges"),
                        "Sketcher_Projection",
                        LARGE,
                        _t("Make a sketch of the edges of the selected flat face, in its plane"),
                        "extract_boundary",
                    ),
                ),
            ),
            Group(
                "cam_measure",
                _t("Measure"),
                (
                    Action(
                        "cam_measure_zero",
                        _t("Measure from 0-Point"),
                        "Measurement-Position",
                        LARGE,
                        _t("The smallest and largest X, Y and Z of the selected faces and edges together, from the active setup's zero point"),  # fmt: skip
                        "measure_from_zero",
                    ),
                    Action(
                        "cam_measure_local",
                        _t("Measure local"),
                        "Measurement-Distance",
                        LARGE,
                        _t("One face: its sizes; one hole: its diameter, centre and depth; two faces, two holes or a face and a hole: the distance between them"),  # fmt: skip
                        "measure_local",
                    ),
                ),
            ),
            Group(
                "milling",
                _t("Milling"),
                (
                    Action(
                        "cam_contour",
                        _t("Contour tooling"),
                        "CAM_Engrave",
                        LARGE,
                        _t("The tool centre follows the selected sketch from Start Z down to Z-Depth, above or below it"),
                        "contour_tooling",
                    ),
                    Action(
                        "cam_facing",
                        _t("Facing"),
                        "CAM_Face",
                        LARGE,
                        _t("Level the whole stock down to the clicked face at the top of the model"),
                        "facing",
                    ),
                    Action("cam_profile", _t("Profile"), "CAM_Profile", LARGE),
                    Action("cam_pocket", _t("Pocket"), "CAM_Pocket", LARGE),
                    Action(
                        "cam_adaptive",
                        _t("Adaptive"),
                        "CAM_Adaptive",
                        tip=_t("Clear around the whole model from the top of the stock down to Z-Depth with an even load, or only over the flat floors clicked in the model"),  # fmt: skip
                        handler="adaptive",
                    ),
                    Action(
                        "cam_slot",
                        _t("Slot"),
                        "CAM_Slot",
                        tip=_t("Mill the slots clicked in the model: ramping down along them, the walls finished with RL/RR"),  # fmt: skip
                        handler="slot_milling",
                    ),
                    Action("cam_engrave", _t("Engrave"), "CAM_Engrave"),
                    Action(
                        "cam_deburring",
                        _t("Deburring"),
                        "CAM_Deburr",
                        tip=_t("A chamfer mill along the selected sketch lines, in the order clicked: enter the chamfer, the depth and the tool centre beside the lines follow from the tool"),  # fmt: skip
                        handler="deburring",
                    ),
                ),
            ),
            Group(
                "holes",
                _t("Holes"),
                (
                    Action(
                        "cam_drilling",
                        _t("Drilling"),
                        "CAM_Drilling",
                        LARGE,
                        _t("Drill the selected circles of a sketch with cycle 205, in the order they were clicked"),
                        "drilling",
                    ),
                    Action(
                        "cam_helix",
                        _t("Helix"),
                        "CAM_Helix",
                        tip=_t("Mill the holes clicked in the model or the circles of a sketch down a helix, with RL/RR from the start, in the order they were clicked"),  # fmt: skip
                        handler="helix_milling",
                    ),
                    Action(
                        "cam_thread_milling",
                        _t("Thread milling"),
                        "CAM_ThreadMilling",
                        tip=_t("Mill an internal thread in the selected circles of a sketch or holes of the model, in the order they were clicked"),  # fmt: skip
                        handler="thread_milling",
                    ),
                    Action("cam_tapping", _t("Tapping"), "CAM_Tapping"),
                ),
            ),
            Group(
                "output",
                _t("Output"),
                (
                    Action(
                        "cam_simulate",
                        _t("Simulate"),
                        "CAM_SimulatorGL",
                        LARGE,
                        tip=_t("The active setup's operations machining its stock"),
                        handler="simulate",
                    ),
                    Action(
                        "cam_verify",
                        _t("Verify"),
                        "CAM_Sanity",
                        tip=_t("The active setup's program cut out of its stock: too deep into the part red, material left blue, rapid moves into material"),  # fmt: skip
                        handler="verify",
                    ),
                    Action(
                        "cam_cycle_time",
                        _t("Cycle time"),
                        "AvangardeCam_CycleTime",
                        tip=_t("How long each operation and setup takes on the machine, in a table: worked out when pressed"),  # fmt: skip
                        handler="cycle_time",
                    ),
                    Action(
                        "cam_play",
                        _t("Play"),
                        "AvangardeCam_Play",
                        tip=_t("The active setup's program played as the machine runs it, in a window of its own: the stock cut, the tool, its path, the program's lines and the time, block by block or at a speed"),  # fmt: skip
                        handler="play",
                    ),
                    Action(
                        "cam_export_gcode",
                        _t("Export NC"),
                        "CAM_Post",
                        LARGE,
                        tip=_t("Heidenhain TNC plain language (.H), every setup on its own preset"),
                        handler="export_nc",
                    ),
                ),
            ),
        ),
    ),
)


def shown_file_menu():
    """The File menu without placeholders: a button that does nothing only
    confuses the user. No separator at the ends or two in a row."""
    result = []
    for action in FILE_MENU:
        if action is SEPARATOR:
            if result and result[-1] is not SEPARATOR:
                result.append(SEPARATOR)
        elif action.handler:
            result.append(action)
    while result and result[-1] is SEPARATOR:
        result.pop()
    return tuple(result)


def shown_tabs():
    """The ribbon without placeholders; a group or a tab left without a
    working button is left out as well."""
    tabs = []
    for tab in TABS:
        groups = []
        for group in tab.groups:
            working = tuple(a for a in group.actions if a.handler)
            if working:
                groups.append(Group(group.key, group.text, working))
        if groups:
            tabs.append(Tab(tab.key, tab.text, tuple(groups)))
    return tuple(tabs)


def all_actions():
    """Every action of the File menu and the ribbon, in display order."""
    result = [a for a in FILE_MENU if a is not SEPARATOR]
    for tab in TABS:
        for group in tab.groups:
            result.extend(group.actions)
    return result
