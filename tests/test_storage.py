import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from venting.storage import SaveError, TextFile


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "thoughts.txt"

    def open(self, *, create=True):
        file = TextFile(self.path, create=create)
        self.addCleanup(file.close)
        return file

    def test_new_file_is_private_and_each_thought_is_immediately_saved(self):
        file = self.open()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode) & 0o077, 0)
        with patch("venting.storage.os.fsync", wraps=os.fsync) as sync:
            file.append("First thought")
            self.assertEqual(self.path.read_text(), "First thought\n")
            file.append("Second thought")
            self.assertEqual(self.path.read_text(), "First thought\nSecond thought\n")
            self.assertEqual(sync.call_count, 2)

    def test_create_never_overwrites_existing_content(self):
        self.path.write_text("Keep this")
        with self.assertRaises(FileExistsError):
            self.open()
        self.assertEqual(self.path.read_text(), "Keep this")

    def test_append_requires_an_existing_file(self):
        with self.assertRaises(FileNotFoundError):
            self.open(create=False)
        self.assertFalse(self.path.exists())

    def test_append_preserves_existing_content_and_adds_missing_newline(self):
        self.path.write_text("Existing thought")
        file = self.open(create=False)
        file.append("Another thought")
        self.assertEqual(self.path.read_text(), "Existing thought\nAnother thought\n")

    def test_multiline_and_unicode_are_preserved(self):
        file = self.open()
        text = 'A thought about "life".\nGrüße 🌿 日本語 e\u0301'
        file.append(text)
        self.assertEqual(self.path.read_text(encoding="utf-8"), text + "\n")

    def test_blank_drafts_are_ignored(self):
        file = self.open()
        for text in ("", " ", "\n\t"):
            file.append(text)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_binary_and_invalid_utf8_are_rejected(self):
        for data in (b"hello\x00world", b"\xff\xfehello"):
            self.path.write_bytes(data)
            with self.assertRaises(ValueError):
                self.open(create=False)
            self.assertEqual(self.path.read_bytes(), data)

    def test_regular_files_only(self):
        fifo = Path(self.temp.name) / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            TextFile(fifo)

    def test_partial_write_is_completed(self):
        file = self.open()
        write = os.write
        with patch("venting.storage.os.write", side_effect=lambda fd, data: write(fd, data[:2])):
            file.append("Long thought")
        self.assertEqual(self.path.read_text(), "Long thought\n")

    def test_failed_partial_write_is_rolled_back(self):
        file = self.open()
        file.append("Before")
        write = os.write
        calls = 0

        def fail_second_write(fd, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("disk full")
            return write(fd, data[:3])

        with patch("venting.storage.os.write", side_effect=fail_second_write):
            with self.assertRaises(SaveError):
                file.append("A thought that does not fit")
        self.assertEqual(self.path.read_text(), "Before\n")

    def test_sync_failure_does_not_report_success(self):
        file = self.open()
        with patch("venting.storage.os.fsync", side_effect=[OSError("sync failed"), None]):
            with self.assertRaises(SaveError):
                file.append("Keep this draft")
        self.assertEqual(self.path.read_bytes(), b"")

    def test_failed_rollback_reports_possible_partial_content(self):
        file = self.open()
        with patch("venting.storage.os.fsync", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(SaveError, "may contain part"):
                file.append("Uncertain write")

    def test_replaced_file_is_not_silently_written_to(self):
        file = self.open()
        self.path.rename(self.path.with_suffix(".old"))
        self.path.write_text("Replacement\n")
        with self.assertRaisesRegex(SaveError, "replaced"):
            file.append("Do not lose me")
        self.assertEqual(self.path.read_text(), "Replacement\n")
        self.assertEqual(self.path.with_suffix(".old").read_text(), "")

    def test_tail_is_bounded_and_does_not_break_utf8(self):
        file = self.open()
        file.append("🌿" * 100)
        text, truncated = file.tail(max_bytes=31)
        self.assertTrue(truncated)
        self.assertNotIn("\ufffd", text)
        self.assertTrue(text.endswith("\n"))
        self.assertLessEqual(len(text.encode("utf-8")), 31)

    def test_two_open_instances_preserve_both_appends(self):
        first = self.open()
        second = self.open(create=False)
        first.append("One")
        second.append("Two")
        first.append("Three")
        self.assertEqual(self.path.read_text(), "One\nTwo\nThree\n")


if __name__ == "__main__":
    unittest.main()
