import curses
import unittest

from venting.keyboard import CTRL_TAB, DOC_END, DOC_HOME, KeyboardModes


class KeyboardTests(unittest.TestCase):
    def setUp(self):
        self.keyboard = KeyboardModes()

    def test_modern_ctrl_shortcuts_and_tab_are_distinct(self):
        for key, expected in [(9, CTRL_TAB), (115, "\x13"),
                              (113, "\x11"), (99, "\x03"), (122, "\x1a")]:
            for sequence in (f"{key};5u", f"27;5;{key}~"):
                with self.subTest(sequence=sequence):
                    self.assertEqual(self.keyboard.decode(sequence), expected)
        self.assertEqual(self.keyboard.decode("9u"), "\t")
        self.assertEqual(self.keyboard.decode("13u"), "\r")
        self.assertEqual(self.keyboard.decode("9;6u"), CTRL_TAB)

    def test_release_reports_and_unknown_sequences_do_not_insert_text(self):
        for sequence in ("9;5:3u", "115;5:3u", "?1u", "?1;2c", "9999999999u",
                         "0;0u", "9;garbageu", "97;3u"):
            with self.subTest(sequence=sequence):
                self.assertIsNone(self.keyboard.decode(sequence))
        self.assertEqual(self.keyboard.decode("115;5:2u"), "\x13")

    def test_modern_navigation_and_shifted_text(self):
        self.assertEqual(self.keyboard.decode("1;5H"), DOC_HOME)
        self.assertEqual(self.keyboard.decode("8;5~"), DOC_END)
        self.assertEqual(self.keyboard.decode("1;1A"), curses.KEY_UP)
        self.assertEqual(self.keyboard.decode("1;1Q"), curses.KEY_F2)
        self.assertEqual(self.keyboard.decode("97;2;65u"), "A")

    def test_enable_and_restore_prior_xterm_mode_and_kitty_stack(self):
        self.assertIn("\x1b[>4;2m", self.keyboard.enable())
        self.assertIn("\x1b[>1u", self.keyboard.enable())
        self.keyboard.decode(">4;1m")
        self.assertIn("\x1b[>4;1m", self.keyboard.restore())
        self.assertIn("\x1b[<u", self.keyboard.restore())
        self.assertIn("\x1b[>4m", KeyboardModes().restore())
