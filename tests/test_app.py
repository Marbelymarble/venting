import curses
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from venting.app import App


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "thoughts.txt"
        self.app = App()
        self.app.open_path(str(self.path), create=True)
        self.addCleanup(self.app.close)

    def type(self, text):
        for char in text:
            self.app.handle(char)

    def test_enter_saves_and_clears_without_a_separate_save_step(self):
        self.type("A thought")
        self.app.handle("\n")
        self.assertEqual(self.path.read_text(), "A thought\n")
        self.assertEqual(self.app.draft.text, "")
        self.type("Another one")
        self.app.handle("\r")
        self.assertEqual(self.path.read_text(), "A thought\nAnother one\n")

    def test_failed_save_retains_draft_and_does_not_increment_count(self):
        self.type("Do not lose me")
        with patch.object(self.app.file, "append", side_effect=OSError("disk full")):
            self.app.handle("\n")
        self.assertEqual(self.app.draft.text, "Do not lose me")
        self.assertEqual(self.app.saved_count, 0)
        self.assertTrue(self.app.error)

    def test_escape_saves_the_draft_and_returns_to_file_selection(self):
        self.type("Save this on the way back")
        self.app.handle("\x1b")
        self.assertEqual(self.path.read_text(), "Save this on the way back\n")
        self.assertEqual(self.app.draft.text, "")
        self.assertTrue(self.app.chooser)

    def test_escape_stays_in_the_writer_when_saving_fails(self):
        self.type("Do not lose me")
        with patch.object(self.app.file, "append", side_effect=OSError("disk full")):
            self.app.handle("\x1b")
        self.assertFalse(self.app.chooser)
        self.assertEqual(self.app.draft.text, "Do not lose me")

    def test_preview_is_hidden_by_default_and_hiding_drops_cache(self):
        self.assertFalse(self.app.preview)
        self.app.handle("\x10")
        self.assertTrue(self.app.preview)
        self.assertIsNotNone(self.app.file_editor)
        self.app.handle("\x10")
        self.assertFalse(self.app.preview)
        self.assertIsNone(self.app.file_editor)
        self.assertIsNone(self.app.document)

    def test_autocorrect_is_toggleable_and_applies_on_space_and_enter(self):
        self.assertFalse(self.app.autocorrect)
        self.app.handle("\x14")
        self.type("teh ")
        self.assertEqual(self.app.draft.text, "the ")
        self.type("thier")
        self.app.handle("\n")
        self.assertEqual(self.path.read_text(), "the their\n")
        self.app.handle("\x14")
        self.type("teh")
        self.app.handle("\n")
        self.assertTrue(self.path.read_text().endswith("teh\n"))

    def test_undo_stops_save_from_reapplying_correction(self):
        self.app.handle("\x14")
        self.type("teh ")
        self.app.handle("\x1a")
        self.assertEqual(self.app.draft.text, "teh ")
        self.app.handle("\n")
        self.assertEqual(self.path.read_text(), "teh \n")
        self.type("teh ")
        self.assertEqual(self.app.draft.text, "the ")

    def test_pairing_is_active_in_draft_but_not_path_input(self):
        self.type('(a) [b] {c} "d"')
        self.app.handle("\n")
        self.assertEqual(self.path.read_text(), '(a) [b] {c} "d"\n')
        self.app.handle("\x0e")
        self.app.path.clear()
        self.type('("')
        self.assertEqual(self.app.path.text, '("')

    def test_multiline_paste_waits_for_enter(self):
        self.app.handle(("paste", 'first\r\nsecond ("'))
        self.assertEqual(self.path.read_text(), "")
        self.assertEqual(self.app.draft.text, 'first\nsecond ("')
        self.app.handle("\n")
        self.assertEqual(self.path.read_text(), 'first\nsecond ("\n')

    def test_quit_cancel_save_and_discard(self):
        self.type("Keep me")
        self.app.handle("\x11")
        self.assertEqual(self.app.modal, "draft")
        self.app.handle("\x1b")
        self.assertTrue(self.app.running)
        self.assertEqual(self.app.draft.text, "Keep me")
        self.app.handle("\x03")
        self.app.handle("s")
        self.assertFalse(self.app.running)
        self.assertEqual(self.path.read_text(), "Keep me\n")

    def test_quit_can_discard_a_draft(self):
        self.type("Discard me")
        self.app.handle("\x11")
        self.app.handle("d")
        self.assertFalse(self.app.running)
        self.assertEqual(self.path.read_text(), "")

    def test_failed_save_on_quit_returns_to_the_draft(self):
        self.type("Keep me")
        self.app.handle("\x11")
        with patch.object(self.app.file, "append", side_effect=OSError("disk full")):
            self.app.handle("s")
        self.assertTrue(self.app.running)
        self.assertEqual(self.app.draft.text, "Keep me")
        self.assertIsNone(self.app.modal)

    def test_switch_file_cancellation_keeps_original_destination(self):
        self.app.handle("\x0e")
        self.assertTrue(self.app.chooser)
        self.app.handle("\x1b")
        self.assertFalse(self.app.chooser)
        self.assertEqual(self.app.file.path, self.path)

    def test_a_failed_draft_can_be_carried_to_a_reopened_destination(self):
        self.type("Keep this through a file replacement")
        self.path.rename(self.path.with_suffix(".old"))
        self.path.write_text("Replacement\n")
        self.app.handle("\n")
        self.assertTrue(self.app.error)
        self.app.handle("\x0e")
        self.assertTrue(self.app.chooser)
        self.assertIsNone(self.app.modal)
        self.app.handle("\x06")
        self.app.path.clear()
        self.app.path.insert(str(self.path))
        self.app.handle("\n")
        self.assertEqual(self.app.draft.text, "Keep this through a file replacement")
        self.app.handle("\n")
        self.assertEqual(self.path.read_text(), "Replacement\nKeep this through a file replacement\n")

    def test_up_and_down_move_without_recalling_saved_thoughts(self):
        self.app.screen = Mock()
        self.app.screen.getmaxyx.return_value = (28, 100)
        self.type("Released text")
        self.app.handle("\n")
        self.app.handle(curses.KEY_UP)
        self.assertEqual(self.app.draft.text, "")
        self.app.handle(("paste", "first\nsecond"))
        self.app.handle(curses.KEY_UP)
        self.assertLessEqual(self.app.draft.cursor, 5)


if __name__ == "__main__":
    unittest.main()
