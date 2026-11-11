import curses
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from venting.app import App, DOC_HOME


class FilePaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "journal.txt"
        self.path.write_text("First line\nSecond line\n")
        self.app = App()
        self.app.open_path(str(self.path), create=False)
        self.addCleanup(self.app.close)

    def type(self, text):
        for character in text:
            self.app.handle(character)

    def open_editor(self):
        self.app.handle("\x10")
        self.assertTrue(self.app.file_focus)
        self.assertEqual(self.app.file_editor.text, self.path.read_text())

    def test_file_enter_is_newline_and_ctrl_s_persists_it_without_clearing(self):
        self.open_editor()
        self.type("Third line\nFourth line")
        expected = "First line\nSecond line\nThird line\nFourth line"
        self.assertEqual(self.path.read_text(), "First line\nSecond line\n")
        self.assertEqual(self.app.file_editor.text, expected)
        self.app.handle("\x13")
        self.assertEqual(self.path.read_text(), expected)
        self.assertEqual(self.app.file_editor.text, expected)
        self.assertFalse(self.app.file_dirty)

    def test_escape_saves_file_edits_and_draft_before_returning_to_selection(self):
        self.type("A draft")
        self.open_editor()
        self.type("A file edit")
        self.app.handle("\x1b")
        self.assertTrue(self.app.chooser)
        self.assertEqual(self.path.read_text(),
                         "First line\nSecond line\nA file edit\nA draft\n")
        self.assertEqual(self.app.draft.text, "")
        self.assertFalse(self.app.file_dirty)

    def test_edit_beginning_and_preserve_rest_of_file(self):
        self.open_editor()
        self.app.handle(DOC_HOME)
        self.type("New ")
        self.app.handle("\x13")
        self.assertEqual(self.path.read_text(), "New First line\nSecond line\n")

    def test_switch_to_venting_saves_pending_file_edits_before_appending(self):
        self.open_editor()
        self.type("File edit")
        self.app.handle("\t")
        self.assertFalse(self.app.file_focus)
        self.type("New vent\n")
        self.assertEqual(self.path.read_text(), "First line\nSecond line\nFile edit\nNew vent\n")
        self.assertEqual(self.app.file_editor.text, self.path.read_text())
        self.assertEqual(self.app.draft.text, "")
        self.assertFalse(self.app.file_dirty)

    def test_failed_save_retains_both_file_edits_and_venting_draft(self):
        self.open_editor()
        self.type("File edit")
        self.app.handle("\t")
        self.type("New vent")
        with patch.object(self.app.file, "save_document", side_effect=OSError("disk full")):
            self.app.handle("\n")
        self.assertTrue(self.app.file_dirty)
        self.assertTrue(self.app.file_editor.text.endswith("File edit"))
        self.assertEqual(self.app.draft.text, "New vent")
        self.assertEqual(self.path.read_text(), "First line\nSecond line\n")

    def test_hiding_dirty_editor_offers_save_discard_and_cancel(self):
        self.open_editor()
        self.type("An edit")
        self.app.handle("\x10")
        self.assertEqual(self.app.modal, "file_changes")
        self.app.handle("\x1b")
        self.assertTrue(self.app.preview)
        self.assertTrue(self.app.file_dirty)
        self.app.handle("\x10")
        self.app.handle("s")
        self.assertFalse(self.app.preview)
        self.assertIsNone(self.app.file_editor)
        self.assertTrue(self.path.read_text().endswith("An edit"))

    def test_discarding_file_edits_leaves_disk_unchanged(self):
        original = self.path.read_text()
        self.open_editor()
        self.type("Discard this")
        self.app.handle("\x10")
        self.app.handle("d")
        self.assertFalse(self.app.preview)
        self.assertEqual(self.path.read_text(), original)

    def test_quit_guards_file_edits_and_venting_draft_separately(self):
        self.type("A venting draft")
        self.open_editor()
        self.type("A file edit")
        self.app.handle("\x11")
        self.assertEqual(self.app.modal, "file_changes")
        self.app.handle("s")
        self.assertEqual(self.app.modal, "draft")
        self.assertTrue(self.app.running)
        self.app.handle("s")
        self.assertFalse(self.app.running)
        self.assertEqual(self.path.read_text(), "First line\nSecond line\nA file edit\nA venting draft\n")

    def test_file_switch_does_not_silently_lose_file_changes(self):
        self.open_editor()
        self.type("An edit")
        self.app.handle("\x0e")
        self.assertFalse(self.app.chooser)
        self.assertEqual(self.app.modal, "file_changes")
        self.app.handle("s")
        self.assertTrue(self.app.chooser)
        self.assertTrue(self.path.read_text().endswith("An edit"))

    def test_outside_changes_are_preserved_until_explicit_reload_discard(self):
        self.open_editor()
        self.type("My unsaved change")
        with self.path.open("a") as destination:
            destination.write("Outside change\n")
        self.app.handle("\x13")
        self.assertTrue(self.app.file_dirty)
        self.assertTrue(self.app.file_conflict)
        self.assertTrue(self.path.read_text().endswith("Outside change\n"))
        self.assertTrue(self.app.file_editor.text.endswith("My unsaved change"))
        self.app.handle("\x12")
        self.assertEqual(self.app.modal, "file_changes")
        self.app.handle("\x1b")
        self.assertTrue(self.app.file_dirty)
        self.app.handle("\x12")
        self.app.handle("d")
        self.assertEqual(self.app.file_editor.text, self.path.read_text())
        self.assertFalse(self.app.file_dirty)

    def test_clean_editor_refreshes_external_replacement(self):
        self.open_editor()
        replacement = self.path.with_suffix(".new")
        replacement.write_text("New file content\n")
        replacement.replace(self.path)
        self.app.refresh_file_editor()
        self.assertEqual(self.app.file_editor.text, "New file content\n")
        self.type("An edit")
        self.app.handle("\x13")
        self.assertEqual(self.path.read_text(), "New file content\nAn edit")

    def test_undo_redo_and_save_after_undo(self):
        self.open_editor()
        self.type("x")
        self.app.handle("\x1a")
        self.assertFalse(self.app.file_dirty)
        self.app.handle("\x19")
        self.assertTrue(self.app.file_dirty)
        self.app.handle("\x13")
        self.assertTrue(self.path.read_text().endswith("x"))
        self.app.handle("\x1a")
        self.app.handle("\x13")
        self.assertEqual(self.path.read_text(), "First line\nSecond line\n")

    def test_single_mode_switch_keeps_draft_dirty_editor_cursor_and_undo(self):
        self.type("My draft")
        self.app.handle("\t")
        self.assertFalse(self.app.preview)
        self.type("An edit")
        editor = self.app.file_editor
        cursor = editor.cursor
        self.app.handle("\t")
        self.assertFalse(self.app.file_focus)
        self.assertEqual(self.app.draft.text, "My draft")
        self.assertTrue(self.app.file_dirty)
        self.app.handle("\t")
        self.assertIs(self.app.file_editor, editor)
        self.assertEqual(editor.cursor, cursor)
        self.app.handle("\x1a")
        self.assertTrue(editor.text.endswith("An edi"))
        self.app.handle("\x19")
        self.app.handle("\x13")
        self.assertTrue(self.path.read_text().endswith("An edit"))

    def test_f2_reuses_unsaved_single_editor_instead_of_reloading(self):
        self.app.handle("\t")
        self.type("Keep these edits")
        editor = self.app.file_editor
        self.app.handle("\t")
        self.app.handle("\x10")
        self.assertTrue(self.app.preview)
        self.assertIs(self.app.file_editor, editor)
        self.assertTrue(editor.text.endswith("Keep these edits"))
        self.app.handle("\x13")
        self.assertTrue(self.path.read_text().endswith("Keep these edits"))

    def test_single_mode_append_refreshes_file_and_reload_guards_dirty_edits(self):
        self.app.handle("\t")
        self.type("File edit")
        self.app.handle("\t")
        self.type("A thought\n")
        self.assertEqual(self.app.file_editor.text, self.path.read_text())
        self.assertFalse(self.app.preview)
        self.app.handle("\t")
        self.type("Unsaved")
        self.app.handle("\x12")
        self.assertEqual(self.app.modal, "file_changes")
        self.app.handle("d")
        self.assertEqual(self.app.file_editor.text, self.path.read_text())
        self.assertFalse(self.app.preview)

    def test_visible_panes_at_every_supported_width(self):
        for width in (48, 60, 91, 92, 110):
            for both in (False, True):
                for focus in (False, True):
                    with self.subTest(width=width, both=both, focus=focus):
                        self.app.preview, self.app.file_focus = both, focus
                        with patch.object(self.app, "put"), \
                             patch.object(self.app, "draw_draft") as draft, \
                             patch.object(self.app, "draw_preview") as file:
                            self.app.draw_writer(28, width)
                        self.assertEqual(draft.call_count, int(both or not focus))
                        self.assertEqual(file.call_count, int(both or focus))
                        if both:
                            dy, dx, dh, dw = draft.call_args.args
                            fy, fx, fh, fw = file.call_args.args
                            if width < 92:
                                self.assertEqual(dx, fx)
                                self.assertEqual(dw, fw)
                                self.assertEqual(fy, dy + dh)
                            else:
                                self.assertEqual(dy, fy)
                                self.assertGreater(fx, dx + dw)
                        else:
                            shown = file if focus else draft
                            self.assertEqual(shown.call_args.args, (5, 2, 19, width - 4))

    def test_narrow_file_header_keeps_shortcuts_and_separates_summary_from_text(self):
        self.open_editor()
        self.app.handle(DOC_HOME)
        original = self.app.file_editor.text
        with patch.object(self.app, "put") as put, patch.object(self.app, "box"), \
                patch.object(self.app, "cursor") as cursor, \
                patch.object(self.app, "recent_summary", return_value="Long summary " * 12):
            self.app.draw_preview(5, 2, 19, 40)
        rows = {call.args[0]: call.args[2] for call in put.call_args_list}
        self.assertIn("Ctrl+S save", " ".join(rows.values()))
        self.assertIn("Tab thought", " ".join(rows.values()))
        separator = next(y for y, text in rows.items() if text == "─" * 36)
        self.assertTrue(rows[separator - 1].endswith("…"))
        self.assertEqual(rows[separator + 1], "First line")
        self.assertEqual(cursor.call_args.args, (separator + 1, 4))
        self.assertEqual(self.app._file_rows, 5 + 19 - 1 - (separator + 1))
        self.assertEqual(self.app.file_editor.text, original)

    def test_short_file_pane_reserves_content_inside_bottom_border(self):
        self.open_editor()
        self.app.handle(DOC_HOME)
        for height in (4, 5, 6, 8):
            with self.subTest(height=height), patch.object(self.app, "put") as put, \
                    patch.object(self.app, "box"), patch.object(self.app, "cursor"):
                self.app.draw_preview(5, 2, height, 40)
            rows = {call.args[0]: call.args[2] for call in put.call_args_list}
            self.assertIn("First line", rows.values())
            self.assertTrue(all(5 < row < 5 + height - 1 for row in rows))


if __name__ == "__main__":
    unittest.main()
