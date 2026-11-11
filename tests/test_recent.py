import curses
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from venting.app import App
from venting.recent import list_vents
from venting.settings import Settings
from venting.summaries import cached_summary, manual_summary_token, metadata_path, revision, save_summary


class RecentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = Settings(self.root / "config.json")
        self.settings.ensure_directory()
        self.directory = self.settings.default_directory
        self.app = App(settings=self.settings)
        self.addCleanup(self.app.close)

    def test_listing_is_newest_first_and_excludes_non_vent_entries(self):
        for name, timestamp in [("one.txt", 1000), ("two.md", 3000), ("no-extension", 2000)]:
            path = self.directory / name
            path.touch()
            os.utime(path, (timestamp, timestamp))
        (self.directory / ".metadata.json").touch()
        (self.directory / "folder").mkdir()
        (self.directory / "link").symlink_to(self.directory / "one.txt")
        config = self.directory / "config.json"
        config.touch()
        self.assertEqual([v.path.name for v in list_vents(self.directory, exclude=config)],
                         ["two.md", "no-extension", "one.txt"])

    def test_create_adds_only_missing_extension_and_does_not_overwrite(self):
        self.app.open_path(str(self.directory / "today"), create=True)
        self.assertEqual(self.app.file.path.name, "today.txt")
        self.app.draft.insert("Original")
        self.app.save()
        with self.assertRaises(FileExistsError):
            self.app.open_path(str(self.directory / "today"), create=True)
        self.assertEqual((self.directory / "today.txt").read_text(), "Original\n")
        for filename in ("other.md", "archive.v1.json", "CAPS.TXT"):
            self.app.open_path(str(self.directory / filename), create=True)
            self.assertEqual(self.app.file.path.name, filename)

    def test_append_resolves_txt_only_when_exact_name_does_not_exist(self):
        raw = self.directory / "journal"
        suffixed = raw.with_suffix(".txt")
        suffixed.touch()
        self.app.open_path(str(raw), create=False)
        self.assertEqual(self.app.file.path, suffixed)
        raw.touch()
        self.app.open_path(str(raw), create=False)
        self.assertEqual(self.app.file.path, raw)

    def test_recent_open_preserves_draft_and_uses_exact_file(self):
        old = self.directory / "journal"
        old.write_text("Old entry.\n")
        self.app.open_path(str(self.directory / "active.txt"), create=True)
        self.app.draft.insert("Kept draft")
        self.app.handle("\x0e")
        self.app.handle("\t")
        self.app.handle(curses.KEY_END)
        self.app.handle("\n")
        self.assertIsNone(self.app.recent)
        self.assertEqual(self.app.file.path, old)
        self.assertEqual(self.app.draft.text, "Kept draft")
        self.assertIsNone(self.app.summaries)

    def test_recent_vents_are_part_of_start_screen_and_can_be_hidden(self):
        newest = self.directory / "newest.txt"
        newest.write_text("New entry.\n")
        self.app.prepare_default_directory()
        self.assertEqual([vent.path for vent in self.app.recent], [newest])
        self.assertFalse(self.app.recent_focus)
        self.app.handle("\t")
        self.assertTrue(self.app.recent_focus)
        self.app.handle("\t")
        self.assertFalse(self.app.recent_focus)

        self.settings.set_preferences("vents", "", False)
        hidden = App(settings=self.settings)
        self.addCleanup(hidden.close)
        hidden.prepare_default_directory()
        self.assertIsNone(hidden.recent)
        hidden.handle("\t")
        self.assertEqual([vent.path for vent in hidden.recent], [newest])
        self.assertTrue(hidden.recent_focus)

    def test_recent_file_can_be_renamed_without_breaking_active_file_or_summary(self):
        original = self.directory / "original.txt"
        original.write_text("Original entry.\n")
        save_summary(original, revision(original), "Thinking about names and figuring out a better one.",
                     manual=True)
        old_metadata = metadata_path(original)
        self.app.open_path(str(original), create=False)
        self.app.handle("\x0e")
        self.app.handle("\t")
        self.app.handle("e")
        self.assertEqual(self.app.modal, "edit_vent")
        self.app.handle("\t")
        self.app.handle("\x15")
        for character in "renamed.md":
            self.app.handle(character)
        self.app.handle("\n")

        renamed = self.directory / "renamed.md"
        self.assertFalse(original.exists())
        self.assertTrue(renamed.exists())
        self.assertEqual(self.app.file.path, renamed.absolute())
        self.assertEqual(cached_summary(renamed, revision(renamed)),
                         "Thinking about names and figuring out a better one.")
        self.assertIsNotNone(manual_summary_token(renamed))
        self.assertFalse(old_metadata.exists())
        self.assertEqual(self.app.message, "Renamed to renamed.md.")
        self.app.file.append("After rename")
        self.assertEqual(renamed.read_text(), "Original entry.\nAfter rename\n")

    def test_rename_rejects_directories_and_existing_destinations(self):
        source = self.directory / "source.txt"
        source.touch()
        existing = self.directory / "existing.txt"
        existing.touch()
        self.app.recent = list_vents(self.directory, exclude=self.settings.config_path)
        self.app.recent_index = next(index for index, vent in enumerate(self.app.recent)
                                     if vent.path == source)
        self.app.recent_focus = True
        self.app.open_edit_vent()
        self.app.edit_focus = 1

        self.app.edit_name.text = "../outside.txt"
        self.app.edit_name.cursor = len(self.app.edit_name.text)
        self.app.save_vent_edits()
        self.assertEqual(self.app.edit_error, "Use a filename only, without a directory.")
        self.assertTrue(source.exists())

        self.app.edit_name.text = existing.name
        self.app.edit_name.cursor = len(existing.name)
        self.app.save_vent_edits()
        self.assertEqual(self.app.edit_error, "A file with that name already exists.")
        self.assertTrue(source.exists())
        self.assertTrue(existing.exists())

    def test_summary_failure_after_rename_keeps_sheet_and_active_path_recoverable(self):
        source = self.directory / "source.txt"
        source.write_text("Original.\n")
        self.app.open_path(str(source), create=False)
        self.app.handle("\x0e")
        self.app.handle("\t")
        self.app.handle("e")
        self.app.edit_summary.insert("Thinking about recovery.")
        self.app.edit_name.text = "renamed.txt"
        self.app.edit_name.cursor = len(self.app.edit_name.text)
        with patch("venting.app.save_summary", side_effect=OSError("disk full")):
            self.app.save_vent_edits()

        target = self.directory / "renamed.txt"
        self.assertTrue(target.exists())
        self.assertEqual(self.app.file.path, target.absolute())
        self.assertEqual(self.app.edit_source, target)
        self.assertEqual(self.app.modal, "edit_vent")
        self.assertIn("File renamed, but summary was not saved", self.app.edit_error)

    def test_edit_sheet_saves_manual_summary_and_rejects_a_stale_edit(self):
        source = self.directory / "journal.txt"
        source.write_text("Original entry.\n")
        self.app.prepare_default_directory()
        self.app.handle("\t")
        self.app.handle("e")
        self.assertEqual(self.app.modal, "edit_vent")
        for character in "Thinking manually about plans.":
            self.app.handle(character)
        self.app.handle("\n")
        self.assertEqual(cached_summary(source, revision(source)),
                         "Thinking manually about plans.")
        self.assertIsNotNone(manual_summary_token(source))
        self.assertEqual(self.app.message, "Manual summary saved.")

        self.app.handle("e")
        source.write_text("Changed entry.\n")
        self.app.handle("\x15")
        for character in "A stale summary":
            self.app.handle(character)
        self.app.handle("\n")
        self.assertEqual(self.app.modal, "edit_vent")
        self.assertEqual(self.app.edit_error,
                         "File changed while editing. Cancel and try again.")

    def test_edit_sheet_previews_the_latest_saved_text(self):
        source = self.directory / "journal.txt"
        source.write_text("Earlier text. " + "filler " * 100 + "Latest saved thought.")
        self.app.prepare_default_directory()
        self.app.handle("\t")
        self.app.handle("e")

        self.assertTrue(self.app.edit_preview.startswith("… "))
        self.assertTrue(self.app.edit_preview.endswith("Latest saved thought."))
        with patch.object(self.app, "put") as put, patch.object(self.app, "box"), \
                patch.object(self.app, "cursor"):
            self.app.draw_edit_vent(18, 80)
        rendered = " ".join(call.args[2] for call in put.call_args_list)
        self.assertIn("SAVED TEXT PREVIEW · read-only", rendered)
        self.assertIn("Short label shown in Recent vents", rendered)
        self.assertIn("File name (same folder)", rendered)
        self.assertIn("Latest saved thought.", rendered)

    def test_reload_manual_summary_requires_explicit_confirmation(self):
        source = self.directory / "journal.txt"
        source.write_text("A saved journal entry.")
        sentence = "My own summary."
        save_summary(source, revision(source), sentence, manual=True)
        token = manual_summary_token(source)
        self.app.prepare_default_directory()
        self.app.handle("\t")
        self.app.summaries = Mock()

        for cancel in ("n", "\x1b"):
            with self.subTest(cancel=cancel):
                self.app.handle("R")
                self.assertEqual(self.app.modal, "redo_manual_summary")
                self.app.summaries.submit.assert_not_called()
                self.app.handle("\n")
                self.assertEqual(self.app.modal, "redo_manual_summary")
                self.app.handle(cancel)
                self.assertIsNone(self.app.modal)
                self.app.summaries.submit.assert_not_called()
                self.assertEqual(cached_summary(source, revision(source)), sentence)

        self.app.handle("r")
        self.app.handle("Y")
        self.assertIsNone(self.app.modal)
        self.app.summaries.submit.assert_called_once_with(
            (source,), priority=True, retry=True, force=True, replace_manual=token)

    def test_reload_ai_summary_does_not_require_confirmation(self):
        source = self.directory / "journal.txt"
        source.write_text("A saved journal entry.")
        save_summary(source, revision(source), "Thinking about the day.")
        self.app.prepare_default_directory()
        self.app.handle("\t")
        self.app.summaries = Mock()
        self.app.handle("R")
        self.assertIsNone(self.app.modal)
        self.app.summaries.submit.assert_any_call(
            (source,), priority=True, retry=True, force=True)

    def test_edit_sheet_leaves_terminal_cursor_in_active_field(self):
        source = self.directory / "journal.txt"
        source.write_text("A saved journal entry.")
        self.app.prepare_default_directory()
        self.app.handle("\t")
        self.app.handle("e")
        for focus, row, editor in ((0, 7, self.app.edit_summary),
                                   (1, 11, self.app.edit_name)):
            with self.subTest(focus=focus):
                self.app.edit_focus = focus
                events = []
                with patch.object(self.app, "put", side_effect=lambda *a, **k: events.append("put")), \
                        patch.object(self.app, "box"), \
                        patch.object(self.app, "cursor", side_effect=lambda *a: events.append(a)):
                    self.app.draw_edit_vent(18, 80)
                self.assertEqual(events[-1], (row, 5 + len(editor.text)))

    def test_picker_separates_guidance_from_shortcut_footer(self):
        self.app.prepare_default_directory()
        with patch.object(self.app, "put") as put, patch.object(self.app, "box"), \
                patch.object(self.app, "cursor"):
            self.app.draw_chooser(28, 100)
        rows = [(call.args[0], call.args[2]) for call in put.call_args_list]
        self.assertTrue(any(y == 24 and "Enter a file above" in text for y, text in rows))
        self.assertTrue(any(y == 25 and text == "─" * 96 for y, text in rows))
        self.assertTrue(any(y == 26 and "Tab recent vents" in text for y, text in rows))

    def test_edit_sheet_delete_requires_confirmation_and_cleans_active_file(self):
        source = self.directory / "delete-me.txt"
        source.write_text("Private entry.\n")
        save_summary(source, revision(source), "Thinking about deleting this entry.")
        summary_path = metadata_path(source)
        self.app.open_path(str(source), create=False)
        self.app.draft.insert("Keep this draft")
        self.app.handle("\x0e")
        self.app.handle("\t")
        self.app.handle("e")
        self.app.handle("\x04")
        self.assertEqual(self.app.modal, "edit_vent")
        self.assertTrue(source.exists())
        self.app.handle("\x1b")
        self.assertTrue(source.exists())

        self.app.handle("e")
        self.app.handle("\x04")
        self.app.handle("\x04")
        self.assertFalse(source.exists())
        self.assertFalse(summary_path.exists())
        self.assertIsNone(self.app.file)
        self.assertEqual(self.app.draft.text, "Keep this draft")
        self.assertEqual(self.app.message, "Deleted delete-me.txt.")

    def test_delete_refuses_a_file_changed_after_confirmation(self):
        source = self.directory / "changed.txt"
        source.write_text("Original.\n")
        self.app.prepare_default_directory()
        self.app.handle("\t")
        self.app.handle("e")
        self.app.handle("\x04")
        source.write_text("Changed.\n")
        self.app.handle("\x04")
        self.assertTrue(source.exists())
        self.assertEqual(self.app.modal, "edit_vent")
        self.assertEqual(self.app.edit_error,
                         "File changed after selection. Cancel and try again.")
