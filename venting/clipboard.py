"""Copy the saved UTF-8 file to the system clipboard on explicit request."""

from base64 import b64encode
import fcntl
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from .storage import MAX_EDIT_BYTES

MAX_OSC_BYTES = 48_000  # Keep the base64 escape sequence below 64 KiB.


def copy_file(path: Path) -> bool:
    """Copy the entire file; return False when the terminal cannot acknowledge it."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Only text files can be copied.")
        if info.st_size > MAX_EDIT_BYTES:
            raise ValueError("File is too large to copy here (16 MiB limit).")
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        data = source.read(MAX_EDIT_BYTES + 1)
    if len(data) > MAX_EDIT_BYTES:
        raise ValueError("File is too large to copy here (16 MiB limit).")
    if not data:
        raise ValueError("File is empty.")
    try:
        data.decode("utf-8")
        if b"\x00" in data:
            raise ValueError
    except ValueError:
        raise ValueError("Only UTF-8 text files can be copied.") from None

    commands = []
    if sys.platform == "darwin":
        commands.append(("pbcopy",))
    if os.environ.get("WAYLAND_DISPLAY"):
        commands.append(("wl-copy", "--type", "text/plain;charset=utf-8"))
    if os.environ.get("DISPLAY"):
        commands.append(("xclip", "-selection", "clipboard", "-in"))
    for command in commands:
        executable = shutil.which(command[0])
        if executable is None:
            continue
        try:
            result = subprocess.run((executable, *command[1:]), input=data, timeout=2,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    if not sys.stdout.isatty():
        raise ValueError("No clipboard tool or terminal clipboard available.")
    if len(data) > MAX_OSC_BYTES:
        raise ValueError("For larger files, use wl-copy, xclip, or pbcopy.")
    sys.stdout.write("\x1b]52;c;" + b64encode(data).decode("ascii") + "\x1b\\")
    sys.stdout.flush()
    return False
