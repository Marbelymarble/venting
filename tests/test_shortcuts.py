import curses
from pathlib import Path
import tempfile
import unittest

from venting.app import App
from venting.settings import Settings
from venting.shortcuts import DEFAULT_BINDINGS, key_for, validate_bindings


class ShortcutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(self.root / "config.json")

    def test_validation_merges_defaults_and_rejects_collisions_or_editor_keys(self):
        bindings = validate_bindings({"commands": "Control+G"})
        self.assertEqual(bindings["commands"], "ctrl+g")
        self.assertEqual(bindings["files"], DEFAULT_BINDINGS["files"])
        with self.assertRaisesRegex(ValueError, "different key"):
            validate_bindings({"commands": "ctrl+f"})
        with self.assertRaisesRegex(ValueError, r"Ctrl\+B"):
            validate_bindings({"commands": "ctrl+s"})
        unbound = validate_bindings({"copy": "menu only", "settings": "none"})
        self.assertEqual(unbound["copy"], "none")
        self.assertIsNone(key_for("none"))
        with self.assertRaisesRegex(ValueError, "Program menu needs"):
            validate_bindings({"commands": "none"})

    def test_bindings_persist_and_function_keys_map_to_curses_values(self):
        bindings = dict(DEFAULT_BINDINGS, commands="ctrl+g", settings="f6")
        self.settings.set_keybindings(bindings)
        loaded = Settings.load(self.settings.config_path)
        self.assertEqual(loaded.keybindings, bindings)
        self.assertEqual(key_for("f6"), curses.KEY_F6)

    def test_command_surface_runs_actions_without_nested_menus(self):
        app = App(settings=self.settings)
        self.addCleanup(app.close)
        path = self.root / "journal.txt"
        app.open_path(str(path), create=True)
        app.handle("\x0f")
        self.assertEqual(app.modal, "commands")
        app.handle("p")
        self.assertIsNone(app.modal)
        self.assertTrue(app.preview)

    def test_command_surface_is_navigable_and_exposes_default_path(self):
        app = App(settings=self.settings)
        self.addCleanup(app.close)
        app.handle("\x0f")
        labels = [label for _, _, label, _ in app.command_options()]
        self.assertIn("Default path & settings", labels)
        app.handle(curses.KEY_DOWN)  # Disabled pane action is skipped in the picker.
        app.handle(curses.KEY_DOWN)
        app.handle(curses.KEY_DOWN)
        app.handle("\n")
        self.assertEqual(app.modal, "settings")
        self.assertEqual(app.settings_focus, 0)

    def test_shortcut_can_be_edited_in_place_and_used_immediately(self):
        app = App(settings=self.settings)
        self.addCleanup(app.close)
        app.handle("\x0f")
        app.handle("k")
        self.assertTrue(app.command_editing)
        app.handle("\n")
        app.handle("\x07")  # Ctrl+G
        app.handle("s")
        self.assertEqual(self.settings.keybindings["commands"], "ctrl+g")
        self.assertFalse(app.command_editing)
        app.handle("\x1b")
        self.assertIsNone(app.modal)
        app.handle("\x07")
        self.assertEqual(app.modal, "commands")


if __name__ == "__main__":
    unittest.main()
