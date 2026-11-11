import curses
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from venting.app import App
from venting.settings import Settings, default_locations


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "app/venting.json"
        self.settings = Settings.load(self.config)

    def test_source_default_is_vents_beside_project_launcher(self):
        path, value = default_locations()
        self.assertTrue((path.parent / "run").is_file())
        self.assertEqual(value, "vents")
        self.assertEqual(Settings().default_directory, path.parent / "vents")

    def test_missing_config_uses_relative_vents_and_creates_directory_on_demand(self):
        self.assertFalse(self.config.exists())
        self.assertEqual(self.settings.default_directory, self.config.parent / "vents")
        self.settings.ensure_directory()
        self.assertTrue(self.settings.default_directory.is_dir())

    def test_save_creates_folder_and_survives_restart_and_different_working_directory(self):
        self.settings.set_directory('my vents/Grüße "private"')
        with patch("os.getcwd", return_value=str(self.root)):
            reloaded = Settings.load(self.config)
        self.assertEqual(reloaded.directory_value, 'my vents/Grüße "private"')
        self.assertEqual(reloaded.default_directory,
                         self.config.parent / 'my vents/Grüße "private"')
        self.assertTrue(reloaded.default_directory.is_dir())
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_absolute_and_home_paths(self):
        self.settings.set_directory(str(self.root / "absolute"))
        self.assertEqual(self.settings.default_directory, self.root / "absolute")
        with patch.dict(os.environ, {"HOME": str(self.root)}):
            self.settings.set_directory("~/home vents")
            self.assertEqual(self.settings.default_directory, self.root / "home vents")

    def test_packaged_install_uses_user_config_and_data_directories(self):
        with patch("venting.settings.__file__", str(self.root / "installed/venting/settings.py")), \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config"),
                                     "XDG_DATA_HOME": str(self.root / "data")}):
            settings = Settings()
        self.assertEqual(settings.config_path, self.root / "config/venting/config.json")
        self.assertEqual(settings.default_directory, self.root / "data/venting/vents")

    def test_bad_directory_does_not_replace_preference(self):
        self.settings.set_directory("old")
        original = self.config.read_bytes()
        file = self.root / "a file"
        file.write_text("keep")
        for value in ("", "   ", "bad\npath", "bad\0path", str(file)):
            with self.subTest(value=value), self.assertRaises((ValueError, OSError)):
                self.settings.set_directory(value)
            self.assertEqual(self.settings.directory_value, "old")
            self.assertEqual(self.config.read_bytes(), original)

    def test_failed_settings_save_keeps_old_config_and_removes_temporary(self):
        self.settings.set_directory("old")
        original = self.config.read_bytes()
        with patch("venting.settings.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.settings.set_directory("new")
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(self.settings.directory_value, "old")
        self.assertEqual(list(self.config.parent.glob(".venting-settings-*")), [])

    def test_invalid_json_or_setting_is_reported_without_rewriting_config(self):
        self.config.parent.mkdir()
        for raw in ('{"oops":', '[]', '{"default_directory": null}'):
            with self.subTest(raw=raw):
                self.config.write_text(raw)
                with self.assertRaises(ValueError):
                    Settings.load(self.config)
                self.assertEqual(self.config.read_text(), raw)

    def test_saving_directory_retains_other_configuration_keys(self):
        self.config.parent.mkdir()
        self.config.write_text('{"default_directory":"old", "future_setting":42}')
        Settings.load(self.config).set_directory("new")
        self.assertEqual(json.loads(self.config.read_text())["future_setting"], 42)

    def test_expanded_preferences_are_validated_and_persisted(self):
        self.settings.set_preferences("journals", "gemma3:1b", False, "de")
        reloaded = Settings.load(self.config)
        self.assertEqual(reloaded.directory_value, "journals")
        self.assertEqual(reloaded.summary_model, "gemma3:1b")
        self.assertFalse(reloaded.show_recent_vents)
        self.assertEqual(reloaded.autocorrect_language, "de")
        with self.assertRaises(ValueError):
            self.settings.set_preferences("journals", "remote/cloud", True)
        with self.assertRaises(ValueError):
            self.settings.set_preferences("journals", "", True, "fr")

        self.config.write_text('{"default_directory":"journals","show_recent_vents":"yes"}')
        with self.assertRaises(ValueError):
            Settings.load(self.config)
        self.config.write_text('{"default_directory":"journals","autocorrect_language":"fr"}')
        with self.assertRaises(ValueError):
            Settings.load(self.config)


class DirectoryInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root / "app/venting.json")
        self.app = App(settings=self.settings)
        self.addCleanup(self.app.close)
        self.app.prepare_default_directory()

    def type(self, value):
        for character in value:
            self.app.handle(character)

    def choose_directory(self, value):
        self.app.handle("\x0f")
        self.app.handle("d")
        self.app.handle("\x15")
        self.type(value)
        self.app.handle("\n")

    def test_main_screen_changes_default_for_new_and_append_files(self):
        self.choose_directory("new vents")
        self.assertIsNone(self.app.modal)
        directory = self.settings.default_directory
        self.assertEqual(Path(self.app.path.text).parent, directory)
        self.app.handle("\x06")
        self.assertEqual(Path(self.app.path.text), directory)
        existing = directory / "previous.txt"
        existing.write_text("previous\n")
        self.app.path.clear()
        self.app._entries()
        self.assertEqual(self.app.entries, [existing])
        self.type("previous.txt")
        self.app.handle("\n")
        self.assertEqual(self.app.file.path, existing)

    def test_new_file_relative_name_is_saved_under_default_directory(self):
        self.app.path.clear()
        self.type("my vent.txt\n")
        self.type("My thought\n")
        self.assertEqual((self.settings.default_directory / "my vent.txt").read_text(),
                         "My thought\n")

    def test_settings_do_not_switch_active_file_or_discard_either_buffer(self):
        old = self.root / "active.txt"
        self.app.open_path(str(old), create=True)
        self.type("An unfinished vent")
        self.app.handle("\t")
        self.type("An unsaved file edit")
        editor = self.app.file_editor
        self.choose_directory('other (vents) "folder"')
        self.assertEqual(self.app.file.path, old)
        self.assertEqual(self.app.draft.text, "An unfinished vent")
        self.assertIs(self.app.file_editor, editor)
        self.assertEqual(editor.text, "An unsaved file edit")
        self.assertTrue(self.app.file_focus)
        self.assertTrue(self.app.file_dirty)
        self.assertEqual(self.settings.directory_value, 'other (vents) "folder"')

    def test_settings_cancel_and_error_leave_preference_and_picker_unchanged(self):
        original = self.app.path.text
        self.app.handle("\x0f")
        self.app.handle("d")
        self.app.handle("\x15")
        self.app.handle("\n")
        self.assertEqual(self.app.modal, "settings")
        self.assertTrue(self.app.directory_error)
        self.assertFalse(self.settings.config_path.exists())
        self.type("do not save")
        self.app.handle("\x1b")
        self.assertEqual(self.app.path.text, original)
        self.assertEqual(self.settings.directory_value, "vents")

    def test_ctrl_n_returns_to_create_screen_and_escape_keeps_draft(self):
        self.app.open_path(str(self.root / "active.txt"), create=True)
        self.type("Keep my draft")
        self.app.handle("\x0e")
        self.assertTrue(self.app.chooser)
        self.assertTrue(self.app.create)
        self.assertEqual(Path(self.app.path.text).parent, self.settings.default_directory)
        self.assertEqual(self.app.draft.text, "Keep my draft")
        self.app.handle("\x1b")
        self.assertFalse(self.app.chooser)
        self.assertEqual(self.app.draft.text, "Keep my draft")

    def test_app_still_opens_settings_after_invalid_configuration(self):
        self.settings.config_path.parent.mkdir(exist_ok=True)
        self.settings.config_path.write_text("not json")
        app = App(config_path=self.settings.config_path)
        self.addCleanup(app.close)
        self.assertTrue(app.error)
        app.handle("\x0f")
        app.handle("d")
        self.assertEqual(app.modal, "settings")

    def test_settings_toggle_start_recents_and_set_summary_model(self):
        self.app.handle("\x0f")
        self.app.handle("d")
        self.app.handle("\t")
        self.app.handle(" ")
        self.app.handle("\t")
        self.app.handle(" ")
        self.app.handle("\t")
        self.type("gemma3:1b")
        self.app.handle("\n")
        self.assertFalse(self.settings.show_recent_vents)
        self.assertEqual(self.settings.autocorrect_language, "de")
        self.assertEqual(self.settings.summary_model, "gemma3:1b")
        self.assertIsNone(self.app.recent)
        self.assertIsNotNone(self.app.summaries)

    def test_settings_fields_describe_what_each_value_controls(self):
        self.app.open_settings()
        with patch.object(self.app, "put") as put, patch.object(self.app, "box"), \
                patch.object(self.app, "cursor"):
            self.app.draw_directory_settings(20, 90)
        rendered = " ".join(call.args[2] for call in put.call_args_list)
        self.assertIn("Folder used for new files and Recent vents", rendered)
        self.assertIn("Language used when autocorrect is enabled", rendered)
        self.assertIn("Local Ollama model for Recent-list summaries", rendered)

    def test_settings_leaves_terminal_cursor_in_active_field(self):
        self.app.open_settings()
        for focus, row, editor in ((0, 5, self.app.directory),
                                   (3, 12, self.app.summary_model)):
            with self.subTest(focus=focus):
                self.app.settings_focus = focus
                events = []
                with patch.object(self.app, "put", side_effect=lambda *a, **k: events.append("put")), \
                        patch.object(self.app, "box"), \
                        patch.object(self.app, "cursor", side_effect=lambda *a: events.append(a)):
                    self.app.draw_directory_settings(20, 90)
                self.assertEqual(events[-1], (row, 10 + len(editor.text)))
