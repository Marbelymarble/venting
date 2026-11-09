"""End-to-end tests against an actual curses process in a pseudo-terminal."""

from base64 import b64encode
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

from venting.summaries import cached_summary, metadata_path, revision, save_summary


PROJECT = Path(__file__).resolve().parent.parent


class Terminal:
    def __init__(self, *args, rows=28, columns=110, cwd=PROJECT, launcher=False):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        self.original_attributes = termios.tcgetattr(slave)
        self.output = bytearray()
        env = dict(os.environ, TERM="xterm-256color", LC_ALL="C.UTF-8")
        env.pop("NO_COLOR", None)
        command = [sys.executable, str(PROJECT / "run")] if launcher else [sys.executable, "-m", "venting"]
        self.process = subprocess.Popen(
            [*command, *map(str, args)],
            stdin=slave, stdout=slave, stderr=slave, cwd=cwd, env=env,
        )
        os.close(slave)
        self.wait(lambda: b"\x1b[?2004h" in self.output)

    def read(self, timeout=0.05):
        if select.select([self.master], [], [], timeout)[0]:
            try:
                data = os.read(self.master, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    return b""
                raise
            self.output.extend(data)
            return data
        return b""

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read()
            if predicate():
                return
            if self.process.poll() is not None:
                self.read()
                if predicate():
                    return
                raise AssertionError("Venting exited early:\n" + self.output.decode(errors="replace"))
        raise AssertionError("Terminal action timed out:\n" + self.output.decode(errors="replace"))

    def send(self, text):
        os.write(self.master, text.encode("utf-8") if isinstance(text, str) else text)

    def ctrl_tab(self, protocol="kitty"):
        # Emulate a terminal that only distinguishes Ctrl+Tab after opt-in.
        enabled = (b"\x1b[>1u" if protocol == "kitty" else b"\x1b[>4;2m") in self.output
        self.send(("\x1b[9;5u" if protocol == "kitty" else "\x1b[27;5;9~")
                  if enabled else "\t")

    def resize(self, rows, columns):
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        self.process.send_signal(signal.SIGWINCH)

    def finish(self):
        self.wait(lambda: self.process.poll() is not None)
        self.process.wait(timeout=2)
        self.read()
        if self.process.returncode != 0:
            raise AssertionError(self.output.decode(errors="replace"))
        if b"\x1b[<u" not in self.output or b"\x1b[?2004l" not in self.output:
            raise AssertionError("Terminal reporting modes were not restored")
        # wrapper() must restore raw keyboard settings before returning to shell.
        restored = termios.tcgetattr(self.master)
        if restored[3] != self.original_attributes[3]:
            raise AssertionError("Terminal keyboard settings were not restored")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=3)
        os.close(self.master)


@unittest.skipUnless(os.name == "posix", "requires a POSIX pseudo-terminal")
class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'thoughts "with spaces".txt'

    def start(self, *args, **options):
        terminal = Terminal(*args, **options)
        self.addCleanup(terminal.close)
        return terminal

    def expect_file(self, terminal, text):
        terminal.wait(lambda: self.path.exists() and self.path.read_text(encoding="utf-8") == text)

    def test_every_enter_saves_immediately_and_pairing_works(self):
        terminal = self.start("--new", self.path)
        terminal.send('("hello") [world] {thought}\n')
        self.expect_file(terminal, '("hello") [world] {thought}\n')
        terminal.send("Another thought with Grüße 🌿\r")
        self.expect_file(terminal, '("hello") [world] {thought}\nAnother thought with Grüße 🌿\n')
        terminal.send("\x11")
        terminal.finish()

    def test_new_file_picker_and_append_picker(self):
        terminal = self.start()
        terminal.send("\x15" + str(self.path) + "\n")
        terminal.send("New thought\n")
        self.expect_file(terminal, "New thought\n")
        terminal.send("\x06\x15" + str(self.path) + "\n")
        terminal.send("Append thought\n")
        self.expect_file(terminal, "New thought\nAppend thought\n")
        terminal.send("\x11")
        terminal.finish()

    def test_ctrl_t_toggles_english_autocorrect_and_undo(self):
        terminal = self.start("--new", self.path)
        terminal.send("teh\n")
        self.expect_file(terminal, "teh\n")
        terminal.send("\x14")
        terminal.send("teh becuase\n")
        self.expect_file(terminal, "teh\nthe because\n")
        terminal.send("teh \x1a\n")
        self.expect_file(terminal, "teh\nthe because\nteh \n")
        terminal.send("\x14teh\n")
        self.expect_file(terminal, "teh\nthe because\nteh \nteh\n")
        terminal.send("\x11")
        terminal.finish()

    def test_configured_german_autocorrect_is_used(self):
        config = Path(self.temp.name) / "config.json"
        config.write_text(json.dumps({
            "default_directory": "vents",
            "autocorrect_language": "de",
        }))
        terminal = self.start("--config", config, "--new", self.path, "--autocorrect")
        terminal.send("vileicht mude und das seit\n")
        self.expect_file(terminal, "vielleicht müde und das seit\n")
        terminal.send("\x11")
        terminal.finish()

    def test_ctrl_o_opens_full_menu_and_default_path_settings(self):
        terminal = self.start()
        terminal.send("\x0f")
        terminal.wait(lambda: b"Default path & settings" in terminal.output)
        terminal.send("d")
        terminal.wait(lambda: b"DEFAULT FOLDER PATH" in terminal.output)
        terminal.send("\x1b\x11")
        terminal.finish()

    def test_bracketed_paste_does_not_submit_newlines_or_duplicate_quotes(self):
        terminal = self.start("--new", self.path)
        terminal.send('\x1b[200~first\nsecond ("\x1b[201~')
        terminal.wait(lambda: b"Pasted into" in terminal.output)
        self.assertEqual(self.path.read_text(), "")
        terminal.send("\n")
        self.expect_file(terminal, 'first\nsecond ("\n')
        terminal.send("\x11")
        terminal.finish()

    def test_control_c_asks_about_unsaved_draft_and_restores_terminal(self):
        terminal = self.start("--new", self.path)
        terminal.send("Keep this draft\x03")
        terminal.wait(lambda: b"UNSAVED DRAFT" in terminal.output)
        self.assertIsNone(terminal.process.poll())
        self.assertEqual(self.path.read_text(), "")
        terminal.send("\x1b")
        terminal.send("\x11s")
        terminal.finish()
        self.assertEqual(self.path.read_text(), "Keep this draft\n")

    def test_resize_and_hidden_preview_shortcuts_do_not_lose_draft(self):
        terminal = self.start("--new", self.path)
        thought = "a long thought " * 25
        terminal.send(thought)
        terminal.send("\x10")
        terminal.resize(20, 60)
        terminal.send("\x10")  # Ctrl+P hides it again
        terminal.resize(18, 48)
        terminal.send("\n")
        self.expect_file(terminal, thought + "\n")
        terminal.send("\x11")
        terminal.finish()

    def test_interrupted_paste_can_be_saved_and_quit_without_hanging(self):
        terminal = self.start("--new", self.path)
        terminal.send("\x1b[200~partial paste\x11")
        terminal.wait(lambda: b"UNSAVED DRAFT" in terminal.output)
        terminal.send("s")
        terminal.finish()
        self.assertEqual(self.path.read_text(), "partial paste\n")

    def test_file_editor_ctrl_home_edit_save_quit_and_reopen(self):
        self.path.write_text("Original line\nSecond line\n")
        terminal = self.start(self.path)
        terminal.send("\x10\x1b[1;5HEdited \x13")
        expected = "Edited Original line\nSecond line\n"
        self.expect_file(terminal, expected)
        terminal.send("\x11")
        terminal.finish()
        reopened = self.start(self.path)
        reopened.send("A new thought\n")
        self.expect_file(reopened, expected + "A new thought\n")
        reopened.send("\x11")
        reopened.finish()

    def test_file_editor_enter_newline_ctrl_s_and_tab_to_append(self):
        terminal = self.start("--new", self.path)
        terminal.send("\x10first\nsecond")
        terminal.wait(lambda: b"SAVED FILE CONTENT" in terminal.output)
        self.assertEqual(self.path.read_text(), "")
        terminal.send("\x13")
        self.expect_file(terminal, "first\nsecond")
        terminal.send("\tA new vent\n")
        self.expect_file(terminal, "first\nsecond\nA new vent\n")
        terminal.send("\x11")
        terminal.finish()

    def test_unsaved_file_edits_are_guarded_when_hiding_and_quitting(self):
        terminal = self.start("--new", self.path)
        terminal.send("\x10An unsaved edit\x10")
        terminal.wait(lambda: b"UNSAVED FILE CHANGES" in terminal.output)
        self.assertEqual(self.path.read_text(), "")
        terminal.send("\x1b\x11s")
        terminal.finish()
        self.assertEqual(self.path.read_text(), "An unsaved edit")

    def exercise_ctrl_tab(self, sequence):
        terminal = self.start("--new", self.path)
        terminal.send("\x10edited    line\x13")
        self.expect_file(terminal, "edited    line")
        terminal.send(sequence + "A thought\n")
        self.expect_file(terminal, "edited    line\nA thought\n")
        terminal.send(sequence + "\x7f\x13")
        self.expect_file(terminal, "edited    line\nA thought")
        terminal.send(sequence + "Another thought\n")
        self.expect_file(terminal, "edited    line\nA thought\nAnother thought\n")
        terminal.send("\x11")
        terminal.finish()

    def test_ctrl_tab_csi_u_switches_both_panes(self):
        self.exercise_ctrl_tab("\x1b[9;5u")

    def test_ctrl_tab_xterm_switches_both_panes(self):
        self.exercise_ctrl_tab("\x1b[27;5;9~")

    def test_negotiated_kitty_ctrl_tab_single_mode_and_encoded_save_quit(self):
        terminal = self.start("--new", self.path)
        terminal.ctrl_tab()
        terminal.send("A file edit    end\x1b[115;5u")
        self.expect_file(terminal, "A file edit    end")
        # Key-release events must not switch back again.
        terminal.send("\x1b[9;5:3u")
        terminal.ctrl_tab()
        terminal.send("A vent\r")
        self.expect_file(terminal, "A file edit    end\nA vent\n")
        terminal.ctrl_tab()
        terminal.send("\x7f\x1b[115;5u")
        self.expect_file(terminal, "A file edit    end\nA vent")
        terminal.send("\x1b[113;5u")
        terminal.finish()
        self.assertIn(b"\x1b[>4m", terminal.output)

    def test_negotiated_xterm_ctrl_tab_and_restoring_previous_mode(self):
        terminal = self.start("--new", self.path)
        # Reply to startup's modifyOtherKeys query with the previous level.
        terminal.send("\x1b[>4;1m")
        terminal.ctrl_tab("xterm")
        terminal.send("Edit\x1b[27;5;115~")
        self.expect_file(terminal, "Edit")
        terminal.ctrl_tab("xterm")
        terminal.send("Vent\n")
        self.expect_file(terminal, "Edit\nVent\n")
        terminal.send("\x1b[27;5;113~")
        terminal.finish()
        self.assertIn(b"\x1b[>4;1m", terminal.output)

    def exercise_tab_switch(self, *args, sequence="\t"):
        terminal = self.start("--new", self.path, *args)
        # --show starts with venting focused too. Tab must enter editing,
        # then leave it without inserting spaces or submitting its newline.
        terminal.send(sequence + "File edit\nSecond line")
        terminal.wait(lambda: b"Second line" in terminal.output)
        self.assertEqual(self.path.read_text(), "")
        terminal.send("\x13")
        self.expect_file(terminal, "File edit\nSecond line")
        terminal.send(sequence + "A thought\n")
        self.expect_file(terminal, "File edit\nSecond line\nA thought\n")
        terminal.send(sequence + "\x7f\x13")
        self.expect_file(terminal, "File edit\nSecond line\nA thought")
        terminal.send(sequence + "Another thought\n")
        self.expect_file(terminal, "File edit\nSecond line\nA thought\nAnother thought\n")
        terminal.send("\x1bOP")  # F1
        terminal.wait(lambda: b"Tab          Switch thought" in terminal.output)
        terminal.send("\x1bOP\x11")
        terminal.finish()

    def test_tab_switches_single_field_without_inserting_indentation(self):
        self.exercise_tab_switch()

    def test_tab_switches_focus_with_both_fields_shown(self):
        self.exercise_tab_switch("--show")

    def test_modern_unmodified_tab_also_switches_fields(self):
        self.exercise_tab_switch(sequence="\x1b[9;1u")

    def test_directory_settings_new_append_restart_and_launch_from_another_directory(self):
        root = Path(self.temp.name)
        config = root / "app/venting.json"
        unrelated = root / "unrelated"
        unrelated.mkdir()
        terminal = self.start("--config", config, cwd=unrelated, launcher=True)
        terminal.wait(lambda: b"Choose a file action" in terminal.output)
        self.assertTrue((config.parent / "vents").is_dir())
        terminal.send("\x0fd\x15new vents (ü)\n")
        terminal.wait(lambda: config.exists())
        self.assertEqual(json.loads(config.read_text())["default_directory"], "new vents (ü)")
        directory = config.parent / "new vents (ü)"
        self.assertTrue(directory.is_dir())
        journal = directory / "journal.txt"
        terminal.send("\x15journal.txt\nA new vent\n")
        terminal.wait(lambda: journal.exists() and journal.read_text() == "A new vent\n")
        marker = len(terminal.output)
        terminal.send("\x0e")
        terminal.wait(lambda: b"Choose a file action" in terminal.output[marker:])
        terminal.send("\x06\x15journal.txt\nAn appended vent\n")
        terminal.wait(lambda: journal.read_text() == "A new vent\nAn appended vent\n")
        terminal.send("\x11")
        terminal.finish()
        restarted = self.start("--config", config, cwd=unrelated, launcher=True)
        restarted.send("\x06\x15journal.txt\nAfter restarting\n")
        restarted.wait(lambda: journal.read_text() == "A new vent\nAn appended vent\nAfter restarting\n")
        restarted.send("\x11")
        restarted.finish()
        self.assertFalse((unrelated / "journal.txt").exists())

    def test_saved_summary_model_is_visible_before_its_field_is_focused(self):
        root = Path(self.temp.name)
        config = root / "config.json"
        config.write_text(json.dumps({
            "default_directory": "vents",
            "summary_model": "gemma3:1b",
            "show_recent_vents": False,
        }))
        terminal = self.start("--config", config)
        terminal.send("\x0fd")
        terminal.wait(lambda: b"gemma3:1b" in terminal.output)
        terminal.send("\x11")
        terminal.finish()

    def test_settings_and_return_to_picker_protect_dirty_editor_and_draft(self):
        root = Path(self.temp.name)
        config = root / "app/venting.json"
        directory = root / "future vents"
        terminal = self.start("--config", config, "--new", self.path)
        terminal.send("Draft\tEdit\x0fd\x15" + str(directory) + "\n")
        terminal.wait(lambda: config.exists())
        self.assertEqual(self.path.read_text(), "")
        terminal.send("\t\x0e")
        terminal.wait(lambda: b"UNSAVED FILE CHANGES" in terminal.output)
        terminal.send("s")  # Save file edit and open picker; keep venting draft.
        self.expect_file(terminal, "Edit")
        terminal.send("\x1b\n")  # Cancel picker and submit the retained draft.
        self.expect_file(terminal, "Edit\nDraft\n")
        self.assertEqual(list(directory.iterdir()), [])
        terminal.send("\x11")
        terminal.finish()

    def test_venting_name_and_no_question_placeholder(self):
        terminal = self.start("--new", self.path)
        terminal.send("A saved thought\n")
        self.expect_file(terminal, "A saved thought\n")
        terminal.send("\x11")
        terminal.finish()
        rendered = terminal.output.decode(errors="replace").lower()
        self.assertIn("venting", rendered)
        self.assertNotIn("on your mind", rendered)
        self.assertNotIn("letgo", rendered)
        self.assertNotIn("one thought at a time", rendered)
        self.assertNotIn("enter release", rendered)
        self.assertIn("ctrl+o program menu", rendered)

    def test_recent_browser_reaches_oldest_and_opens_it_with_summary(self):
        root = Path(self.temp.name)
        directory = root / "vents"
        directory.mkdir()
        for index in range(230):
            path = directory / f"journal-{index:03d}.md"
            path.write_text("Original entry.\n", encoding="utf-8")
            os.utime(path, (1000 + index, 1000 + index))
        oldest = directory / "journal-000.md"
        save_summary(oldest, revision(oldest), "Cached summary of the oldest entry.")
        with patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            terminal = self.start("--config", root / "config.json", rows=18, columns=48)
        terminal.wait(lambda: b"Tab recent vents" in terminal.output)
        terminal.send("\t")
        terminal.wait(lambda: b"Recent vents (230)" in terminal.output)
        terminal.send("\x1bOF")  # End
        terminal.wait(lambda: b"Cached summary of the oldest entry." in terminal.output)
        terminal.send("\x0fc")  # Program menu copies the selected file, not its summary.
        clipboard = b"\x1b]52;c;" + b64encode(oldest.read_bytes()) + b"\x1b\\"
        terminal.wait(lambda: clipboard in terminal.output)
        terminal.send("\nAppended\n")
        terminal.wait(lambda: oldest.read_text() == "Original entry.\nAppended\n")
        terminal.wait(lambda: b"Thought appended" in terminal.output)
        terminal.send("\x11")
        terminal.finish()
        self.assertNotIn(b"a little room for your thoughts", terminal.output)

    def test_recent_file_can_be_renamed_and_opened(self):
        root = Path(self.temp.name)
        directory = root / "vents"
        directory.mkdir()
        original = directory / "original.txt"
        original.write_text("Original entry.\n")
        terminal = self.start("--config", root / "config.json")
        terminal.wait(lambda: b"Tab recent vents" in terminal.output)
        terminal.send("\te\t\x15renamed.md\n")
        renamed = directory / "renamed.md"
        terminal.wait(lambda: renamed.exists() and not original.exists())
        terminal.send("\nAfter rename\n")
        terminal.wait(lambda: renamed.read_text() == "Original entry.\nAfter rename\n")
        terminal.send("\x11")
        terminal.finish()

    def test_edit_sheet_can_write_summary_and_confirm_deletion(self):
        root = Path(self.temp.name)
        directory = root / "vents"
        directory.mkdir()
        path = directory / "journal.txt"
        path.write_text("Original entry.\n")
        terminal = self.start("--config", root / "config.json")
        terminal.wait(lambda: b"Tab recent vents" in terminal.output)
        terminal.send("\teThinking manually about plans.\n")
        terminal.wait(lambda: b"Thinking manually about plans." in terminal.output)
        self.assertEqual(cached_summary(path, revision(path)),
                         "Thinking manually about plans.")
        summary_path = metadata_path(path)
        terminal.send("e\x04\x04")
        terminal.wait(lambda: not path.exists())
        self.assertFalse(summary_path.exists())
        terminal.send("\x11")
        terminal.finish()

    def test_writer_copy_uses_saved_text_and_excludes_unsaved_edits(self):
        self.path.write_bytes("Saved Grüße\r\n".encode())
        with patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
            terminal = self.start(self.path)
        terminal.send("\tUnsaved edit\x0fc")
        clipboard = b"\x1b]52;c;" + b64encode(self.path.read_bytes()) + b"\x1b\\"
        terminal.wait(lambda: clipboard in terminal.output)
        terminal.send("\x11")
        terminal.wait(lambda: b"UNSAVED FILE CHANGES" in terminal.output)
        terminal.send("d")
        terminal.finish()
        self.assertEqual(self.path.read_bytes(), "Saved Grüße\r\n".encode())


if __name__ == "__main__":
    unittest.main()
