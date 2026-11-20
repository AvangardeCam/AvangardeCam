# SPDX-License-Identifier: LGPL-2.1-or-later
# AvangardeCam - a clear CAD/CAM interface that drives FreeCAD.
"""Adding and editing tools of the library (model.tool_editing) and the
file they are kept in (engine.tool_library_file)."""

import dataclasses
import os
import shutil
import tempfile
import unittest

from avangardecam.model import library, tool_editing
from avangardecam.model.tools import SHAPES, Tool
from avangardecam.tests.test_model import LIBRARY


def mill(**values):
    tool = Tool("VHM Frees 6mm", "Endmill", 6.0, flutes=3, cutting_length_mm=13.0, length_mm=50.0, shank_diameter_mm=6.0,
                spindle_rpm=10000.0, feed_xy_mm_min=900.0, feed_z_mm_min=300.0)  # fmt: skip
    entry = library.LibraryTool("t7-alu", 7, "Aluminium", tool)
    return dataclasses.replace(entry, tool=dataclasses.replace(tool, **values)) if values else entry


class TestModel(unittest.TestCase):
    def setUp(self):
        self.entries = library.load(LIBRARY)

    def test_every_type_has_its_fields(self):
        for shape in SHAPES:
            names = [f.name for f in tool_editing.FIELDS[shape]]
            self.assertEqual(names[0], "diameter_mm", shape)
            self.assertEqual(len(names), len(set(names)), shape)
        self.assertIn("corner_radius_mm", [f.name for f in tool_editing.FIELDS["Bullnose"]])
        self.assertIn("pitch_mm", [f.name for f in tool_editing.FIELDS["ThreadMill"]])

    def test_the_library_tools_can_be_saved(self):
        """Every tool of the shop's library passes, so Edit... and OK keep them."""
        failing = [(e.id, tool_editing.problems(e)) for e in self.entries if tool_editing.problems(e)]
        self.assertEqual(failing, [])
        self.assertEqual([e for e in self.entries if tool_editing.fitted(e.tool) != e.tool], [], "no geometry beside the type's")

    def test_problems(self):
        self.assertEqual(tool_editing.problems(mill()), [])
        self.assertIn("The tool needs a name.", tool_editing.problems(mill(name=" ")))
        self.assertIn("Diameter is needed.", tool_editing.problems(mill(diameter_mm=0.0)))
        self.assertIn("A program needs the spindle speed and both feeds.", tool_editing.problems(mill(feed_z_mm_min=None)))
        bull = mill(shape="Bullnose")
        self.assertIn("Corner radius is needed.", tool_editing.problems(bull))
        self.assertIn("The corner radius cannot be more than half the diameter.", tool_editing.problems(mill(shape="Bullnose", corner_radius_mm=3.5)))  # fmt: skip
        self.assertIn("The cutting length cannot be more than the length out of the holder.", tool_editing.problems(mill(cutting_length_mm=60.0)))  # fmt: skip
        self.assertIn("Pitch is needed.", tool_editing.problems(mill(shape="ThreadMill", angle_deg=60.0)))
        self.assertIn("The T number must be 1 or more.", tool_editing.problems(dataclasses.replace(mill(), number=0)))

    def test_fitted_drops_the_other_types_geometry(self):
        tool = tool_editing.fitted(mill(shape="Drill", angle_deg=140.0, corner_radius_mm=0.5).tool)
        self.assertEqual((tool.corner_radius_mm, tool.cutting_length_mm, tool.angle_deg, tool.length_mm), (None, None, 140.0, 50.0))  # fmt: skip

    def test_added_replaced_removed(self):
        entry = tool_editing.with_new_id(self.entries, dataclasses.replace(mill(), id="", number=5))
        self.assertTrue(entry.id.startswith("t5-aluminium-vhm-frees-6mm"))
        self.assertNotIn(entry.id, {e.id for e in self.entries})
        more = tool_editing.added(self.entries, entry)
        index = more.index(entry)
        self.assertEqual((more[index - 1].number <= 5, more[index + 1].number > 5), (True, True), "after the last T5")
        with self.assertRaises(ValueError):
            tool_editing.added(more, entry)
        changed = dataclasses.replace(entry, tool=dataclasses.replace(entry.tool, spindle_rpm=8000.0))
        again = tool_editing.replaced(more, changed)
        self.assertEqual((again.index(changed), len(again)), (index, len(more)), "in its place")
        self.assertEqual(tool_editing.removed(again, entry.id), self.entries)
        with self.assertRaises(ValueError):
            tool_editing.removed(self.entries, entry.id)

    def test_same_number(self):
        t21 = [e for e in self.entries if e.number == 21]
        copy = dataclasses.replace(t21[0], id="")
        self.assertEqual(tool_editing.same_number(self.entries, copy), t21, "a copy: both variants")
        self.assertEqual(tool_editing.same_number(self.entries, t21[0]), t21[1:], "not itself")

    def test_blank(self):
        entry = tool_editing.blank(self.entries, "Drill", "RVS")
        self.assertEqual(entry.number, 10, "the lowest number the library does not use")
        self.assertEqual((entry.tool.shape, entry.tool.angle_deg, entry.workpiece_material), ("Drill", 118.0, "RVS"))
        self.assertTrue(tool_editing.problems(entry), "to fill in")


class TestFile(unittest.TestCase):
    """The shipped library is copied once into the user's file, which is
    used from then on; another library is changed where it is."""

    def setUp(self):
        from avangardecam import params
        from avangardecam.engine import tool_library_file

        self.module = tool_library_file
        self.folder = tempfile.mkdtemp()
        self.shipped = os.path.join(self.folder, "shipped.json")
        shutil.copyfile(LIBRARY, self.shipped)
        self.user = os.path.join(self.folder, "user", "tools.json")
        self.kept = params().GetString(tool_library_file.PARAMETER, "")
        params().SetString(tool_library_file.PARAMETER, "")
        self.patched = (tool_library_file.shipped_tool_library_path, tool_library_file.tool_library_path, tool_library_file.user_path)  # fmt: skip
        tool_library_file.shipped_tool_library_path = lambda: self.shipped
        tool_library_file.tool_library_path = lambda: params().GetString(tool_library_file.PARAMETER, "") or self.shipped
        tool_library_file.user_path = lambda: self.user

    def tearDown(self):
        from avangardecam import params

        m = self.module
        m.shipped_tool_library_path, m.tool_library_path, m.user_path = self.patched
        if self.kept:
            params().SetString(m.PARAMETER, self.kept)
        else:
            params().RemString(m.PARAMETER)
        shutil.rmtree(self.folder)

    def test_copy_of_the_shipped(self):
        path, copied = self.module.editable_path()
        self.assertEqual((path, copied), (self.user, True))
        entries = library.load(path)
        new = tool_editing.with_new_id(entries, dataclasses.replace(mill(), id=""))
        self.module.save(path, tool_editing.added(entries, new))
        self.assertEqual(self.module.editable_path(), (self.user, False), "the user's file from now on")
        self.assertIn(new, library.load(self.user))
        self.assertNotIn(new.id, {e.id for e in library.load(self.shipped)}, "the shipped one untouched")

    def test_other_library_where_it_is(self):
        from avangardecam import params

        other = os.path.join(self.folder, "other.json")
        shutil.copyfile(LIBRARY, other)
        params().SetString(self.module.PARAMETER, other)
        self.assertEqual(self.module.editable_path(), (other, False))
        self.assertFalse(os.path.exists(self.user))


class TestProject(unittest.TestCase):
    def setUp(self):
        import FreeCAD

        self.doc = FreeCAD.newDocument("AvangardeCamToolEditing")
        box = self.doc.addObject("Part::Box", "Part")
        self.doc.recompute()
        self.part = box
        self.entries = library.load(LIBRARY)

    def tearDown(self):
        import FreeCAD

        FreeCAD.closeDocument(self.doc.Name)

    def test_update_projects(self):
        from avangardecam.engine import freecad_cam as cam
        from avangardecam.engine import tool_library_file

        entry = next(e for e in self.entries if e.number == 21 and e.workpiece_material == "RVS")
        job = cam.ensure_job(self.doc, [self.part])
        cam.add_tool(job, entry)
        self.assertEqual([j for j, _t in tool_library_file.project_tools_of(self.doc, entry.id)], [job])
        faster = dataclasses.replace(entry, tool=dataclasses.replace(entry.tool, spindle_rpm=3500.0, length_mm=60.0))
        self.assertEqual(tool_library_file.update_projects(self.doc, faster), ([job], []))
        tool = cam.tool_with_number(job, 21).tool
        self.assertEqual((tool.spindle_rpm, tool.length_mm), (3500.0, 60.0))
        moved = dataclasses.replace(faster, number=22)
        self.assertEqual(tool_library_file.update_projects(self.doc, moved), ([], [job]), "another T number: left")
        self.assertEqual(cam.tool_with_number(job, 21).tool.spindle_rpm, 3500.0)


if __name__ == "__main__":
    unittest.main()
