import codecs
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from venting.storage import ConflictError, TextFile


class FileSavingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "thoughts.txt"
        self.path.write_text("First thought\nSecond thought\n", encoding="utf-8")
        self.file = TextFile(self.path)
        self.addCleanup(self.file.close)

    def assert_no_temporary_files(self):
        self.assertEqual(list(self.path.parent.glob(".venting-*")), [])

    def test_full_file_save_is_persistent_and_next_append_uses_new_file(self):
        snapshot = self.file.load_document()
        edited = "Changed first thought\nA new line\nLast thought without newline"
        result = self.file.save_document(edited, snapshot)
        self.assertTrue(result.directory_synced)
        self.assertEqual(self.path.read_text(), edited)
        reopened = TextFile(self.path)
        try:
            self.assertEqual(reopened.load_document().text, edited)
        finally:
            reopened.close()
        self.file.append("Another thought")
        self.assertEqual(self.path.read_text(), edited + "\nAnother thought\n")
        self.assert_no_temporary_files()

    def test_save_can_shorten_or_empty_the_whole_file(self):
        snapshot = self.file.load_document()
        result = self.file.save_document("x", snapshot)
        self.assertEqual(self.path.read_bytes(), b"x")
        self.file.save_document("", result.document)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_unicode_bom_and_crlf_are_preserved(self):
        self.path.write_bytes(codecs.BOM_UTF8 + "Grüße\r\n日本🌿\r\n".encode())
        snapshot = self.file.load_document()
        self.assertEqual(snapshot.text, "Grüße\n日本🌿\n")
        self.file.save_document(snapshot.text.replace("Grüße", "Hallo"), snapshot)
        self.assertEqual(self.path.read_bytes(), codecs.BOM_UTF8 + "Hallo\r\n日本🌿\r\n".encode())

    def test_entire_file_larger_than_old_preview_limit_is_preserved(self):
        contents = "Important first line\n" + "A preserved old thought\n" * 15000 + "last\n"
        self.path.write_text(contents)
        snapshot = self.file.load_document()
        self.assertGreater(len(snapshot.text), 262144)
        self.file.save_document(snapshot.text[:-5] + "edited\n", snapshot)
        self.assertEqual(self.path.read_text(), contents[:-5] + "edited\n")

    def test_external_append_is_not_overwritten(self):
        snapshot = self.file.load_document()
        other = TextFile(self.path)
        try:
            other.append("External thought")
        finally:
            other.close()
        with self.assertRaises(ConflictError):
            self.file.save_document("My edited buffer", snapshot)
        self.assertTrue(self.path.read_text().endswith("External thought\n"))
        self.assert_no_temporary_files()

    def test_same_size_edit_with_restored_mtime_is_detected(self):
        snapshot = self.file.load_document()
        info = self.path.stat()
        self.path.write_text("Other thought\nSecond thought\n")
        os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.assertRaises(ConflictError):
            self.file.save_document("My edited buffer", snapshot)
        self.assertTrue(self.path.read_text().startswith("Other"))

    def test_external_replacement_is_not_overwritten(self):
        snapshot = self.file.load_document()
        other = self.path.with_suffix(".new")
        other.write_text("A replacement\n")
        os.replace(other, self.path)
        with self.assertRaises(OSError):
            self.file.save_document("My edited buffer", snapshot)
        self.assertEqual(self.path.read_text(), "A replacement\n")
        self.file.reopen()
        latest = self.file.load_document()
        self.file.save_document("An intentional edit\n", latest)
        self.assertEqual(self.path.read_text(), "An intentional edit\n")

    def test_write_sync_and_replace_failures_leave_original_file_untouched(self):
        original = self.path.read_bytes()
        snapshot = self.file.load_document()
        for operation in ("os.write", "os.fsync", "os.replace"):
            with self.subTest(operation=operation):
                with patch("venting.storage." + operation, side_effect=OSError("simulated failure")):
                    with self.assertRaises(OSError):
                        self.file.save_document("Do not lose the old file", snapshot)
                self.assertEqual(self.path.read_bytes(), original)
                self.assert_no_temporary_files()

    def test_partial_writes_are_completed(self):
        snapshot = self.file.load_document()
        write = os.write
        with patch("venting.storage.os.write", side_effect=lambda fd, data: write(fd, data[:3])):
            self.file.save_document("A complete replacement", snapshot)
        self.assertEqual(self.path.read_text(), "A complete replacement")

    def test_change_during_save_preparation_is_detected(self):
        snapshot = self.file.load_document()
        fsync = os.fsync
        def race(fd):
            self.path.write_text("An outside edit during save\n")
            fsync(fd)
        with patch("venting.storage.os.fsync", side_effect=race):
            with self.assertRaises(ConflictError):
                self.file.save_document("My edited buffer", snapshot)
        self.assertEqual(self.path.read_text(), "An outside edit during save\n")
        self.assert_no_temporary_files()

    def test_symlink_is_preserved_and_target_is_updated(self):
        link = self.path.with_name("journal-link.txt")
        link.symlink_to(self.path.name)
        linked = TextFile(link)
        try:
            linked.save_document("Edited via link\n", linked.load_document())
            self.assertTrue(link.is_symlink())
            self.assertEqual(self.path.read_text(), "Edited via link\n")
            linked.append("After editing")
            self.assertEqual(self.path.read_text(), "Edited via link\nAfter editing\n")
        finally:
            linked.close()

    def test_file_permissions_are_preserved(self):
        self.path.chmod(0o640)
        self.file.save_document("Updated", self.file.load_document())
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)

    def test_directory_sync_failure_is_reported_after_a_committed_save(self):
        snapshot = self.file.load_document()
        fsync = os.fsync
        def sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("directory sync failed")
            fsync(fd)
        with patch("venting.storage.os.fsync", side_effect=sync):
            result = self.file.save_document("Edits reached the file", snapshot)
        self.assertFalse(result.directory_synced)
        self.assertEqual(self.path.read_text(), "Edits reached the file")
        self.assertEqual(result.document.revision, self.file.load_document().revision)


if __name__ == "__main__":
    unittest.main()
