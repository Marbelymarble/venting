"""File handling, deliberately separate from the terminal interface."""

import codecs
from dataclasses import dataclass
import fcntl
import hashlib
import os
from pathlib import Path
import stat
import tempfile

MAX_EDIT_BYTES = 16 * 1024 * 1024


class ConflictError(OSError):
    """The file on disk no longer matches the editor's loaded revision."""


def stat_key(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@dataclass(frozen=True)
class Document:
    text: str
    revision: tuple[tuple[int, int, int, int, int], bytes]
    newline: str = "\n"
    bom: bool = False


@dataclass(frozen=True)
class DocumentSave:
    document: Document
    directory_synced: bool = True


class SaveError(OSError):
    """An append failed; the caller must retain its draft."""


class TextFile:
    """An open regular UTF-8 file. Appending never truncates existing text."""

    def __init__(self, path: str | Path, *, create: bool = False):
        self.path = Path(path).expanduser().absolute()
        flags = os.O_RDWR | os.O_APPEND | os.O_NONBLOCK
        if create:
            flags |= os.O_CREAT | os.O_EXCL
        self.fd = os.open(self.path, flags, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(self.fd).st_mode):
                raise ValueError("Choose a regular text file, not a directory or device.")
            self._validate_utf8()
        except BaseException:
            self.close()
            raise

    def _validate_utf8(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")()
        offset = 0
        try:
            while True:
                chunk = os.pread(self.fd, 65536, offset)
                if not chunk:
                    decoder.decode(b"", final=True)
                    break
                if b"\x00" in chunk:
                    raise ValueError("This looks like a binary file. Choose UTF-8 plain text.")
                decoder.decode(chunk)
                offset += len(chunk)
        except UnicodeDecodeError:
            raise ValueError("This file is not UTF-8 plain text. Convert it before opening.") from None

    def _check_identity(self) -> None:
        current = self.path.stat()
        opened = os.fstat(self.fd)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise SaveError("The file was replaced. Reopen it before saving.")

    def append(self, thought: str) -> None:
        """Append and fsync a thought, rolling back a failed write if possible.

        Advisory locking serializes other Venting instances. Editors that ignore
        flock should not write this file at the same time.
        """
        if not thought.strip():
            return
        if "\x00" in thought:
            raise ValueError("A thought cannot contain a NUL character.")
        payload = thought.encode("utf-8") + b"\n"
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        try:
            self._check_identity()
            original_size = os.fstat(self.fd).st_size
            if original_size and os.pread(self.fd, 1, original_size - 1) != b"\n":
                payload = b"\n" + payload
            try:
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(self.fd, remaining)
                    if written <= 0:
                        raise OSError("No bytes could be written.")
                    remaining = remaining[written:]
                os.fsync(self.fd)
            except OSError as error:
                try:
                    os.ftruncate(self.fd, original_size)
                    os.fsync(self.fd)
                except OSError:
                    raise SaveError(
                        "Save failed; the file may contain part of this thought. "
                        "Check it before retrying."
                    ) from error
                raise SaveError("Save failed; your draft is still here. Try again.") from error
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)

    def signature(self) -> tuple[int, int]:
        self._check_identity()
        info = os.fstat(self.fd)
        return info.st_size, info.st_mtime_ns

    def state(self) -> tuple[int, int, int, int, int]:
        self._check_identity()
        return stat_key(os.fstat(self.fd))

    def _read_document(self) -> tuple[bytes, tuple[tuple[int, int, int, int, int], bytes]]:
        self._check_identity()
        before = os.fstat(self.fd)
        if before.st_size > MAX_EDIT_BYTES:
            raise ValueError("The file is larger than 16 MiB; use an external editor. Nothing was changed.")
        chunks = []
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(self.fd, min(65536, before.st_size - offset), offset)
            if not chunk:
                break
            chunks.append(chunk)
            offset += len(chunk)
        data = b"".join(chunks)
        self._check_identity()
        if stat_key(before) != stat_key(os.fstat(self.fd)) or len(data) != before.st_size:
            raise ConflictError("The file changed while being read. Try again.")
        return data, (stat_key(before), hashlib.sha256(data).digest())

    def load_document(self) -> Document:
        fcntl.flock(self.fd, fcntl.LOCK_SH)
        try:
            data, revision = self._read_document()
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ValueError("The file is no longer valid UTF-8. Your buffer was kept.") from None
        if "\x00" in text:
            raise ValueError("The file contains binary data. Your buffer was kept.")
        newline = "\r\n" if "\r\n" in text and "\n" not in text.replace("\r\n", "") else "\n"
        return Document(text.replace("\r\n", "\n").replace("\r", "\n"), revision,
                        newline, data.startswith(codecs.BOM_UTF8))

    def save_document(self, text: str, original: Document) -> DocumentSave:
        """Compare the loaded revision, then atomically replace the entire file.

        Failures before replace leave the old file untouched. The returned flag
        reports a rare directory-sync failure after the replacement committed.
        The live descriptor is moved to the replacement so later appends work.
        """
        if "\x00" in text:
            raise ValueError("A text file cannot contain a NUL character.")
        payload = (codecs.BOM_UTF8 if original.bom else b"") + text.replace("\n", original.newline).encode("utf-8")
        if len(payload) > MAX_EDIT_BYTES:
            raise ValueError("The edited file exceeds 16 MiB. Your changes are still in the editor.")
        old_fd = self.fd
        temporary_fd = -1
        directory_fd = -1
        temporary_path: str | None = None
        committed = False
        fcntl.flock(old_fd, fcntl.LOCK_EX)
        try:
            _, revision = self._read_document()
            if revision != original.revision:
                raise ConflictError("File changed on disk. Edits kept; Ctrl+R reloads the latest file.")
            destination = self.path.resolve(strict=True)  # Preserve a selected symlink.
            info = os.fstat(old_fd)
            directory_fd = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            temporary_fd, temporary_path = tempfile.mkstemp(prefix=".venting-", dir=destination.parent)
            new_info = os.fstat(temporary_fd)
            if (new_info.st_uid, new_info.st_gid) != (info.st_uid, info.st_gid):
                os.fchown(temporary_fd, info.st_uid, info.st_gid)
            os.fchmod(temporary_fd, stat.S_IMODE(info.st_mode))
            # Copy user/ACL attributes where the filesystem supports them.
            if hasattr(os, "listxattr"):
                for name in os.listxattr(old_fd):
                    os.setxattr(temporary_fd, name, os.getxattr(old_fd, name))
            remaining = memoryview(payload)
            while remaining:
                written = os.write(temporary_fd, remaining)
                if written <= 0:
                    raise OSError("No bytes could be written.")
                remaining = remaining[written:]
            os.fsync(temporary_fd)
            # Recheck after preparing the temp file, including non-locking writers.
            _, revision = self._read_document()
            if revision != original.revision or self.path.resolve(strict=True) != destination:
                raise ConflictError("File changed on disk. Edits kept; Ctrl+R reloads the latest file.")
            fcntl.fcntl(temporary_fd, fcntl.F_SETFL, fcntl.fcntl(temporary_fd, fcntl.F_GETFL) | os.O_APPEND)
            fcntl.flock(temporary_fd, fcntl.LOCK_EX)
            os.replace(temporary_path, destination)
            self.fd = temporary_fd
            temporary_fd = -1
            committed = True
            document = Document(text, (stat_key(os.fstat(self.fd)), hashlib.sha256(payload).digest()),
                                original.newline, original.bom)
            synced = True
            try:
                os.fsync(directory_fd)
            except OSError:
                synced = False
            return DocumentSave(document, synced)
        finally:
            fcntl.flock(old_fd, fcntl.LOCK_UN)
            if committed:
                os.close(old_fd)
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            if temporary_fd >= 0:
                os.close(temporary_fd)
            if temporary_path:
                Path(temporary_path).unlink(missing_ok=True)
            if directory_fd >= 0:
                os.close(directory_fd)

    def reopen(self) -> None:
        """Follow the current path after an external atomic replacement."""
        replacement = TextFile(self.path)
        previous = self.fd
        self.fd = replacement.fd
        replacement.fd = -1
        os.close(previous)

    def tail(self, max_bytes: int = 262144) -> tuple[str, bool]:
        """Read a bounded tail for the optional pane. Never parse terminal escapes."""
        fcntl.flock(self.fd, fcntl.LOCK_SH)
        try:
            self._check_identity()
            size = os.fstat(self.fd).st_size
            start = max(0, size - max_bytes)
            data = os.pread(self.fd, max_bytes, start)
        finally:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        if start:
            # Drop the first partial line, or only its incomplete UTF-8 prefix.
            newline = data.find(b"\n")
            if 0 <= newline < len(data) - 1:
                data = data[newline + 1:]
            else:
                while data and data[0] & 0xC0 == 0x80:
                    data = data[1:]
        return data.decode("utf-8", errors="replace"), bool(start)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
