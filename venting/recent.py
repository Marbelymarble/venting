"""Uncapped directory listing for the recent vents browser."""

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class RecentVent:
    path: Path
    modified_ns: int


def list_vents(directory: Path, *, exclude: Path) -> list[RecentVent]:
    vents = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.startswith(".") or directory / entry.name == exclude:
                continue
            try:
                if entry.is_file(follow_symlinks=False):
                    info = entry.stat(follow_symlinks=False)
                    vents.append(RecentVent(directory / entry.name, info.st_mtime_ns))
            except OSError:
                continue  # The file may have disappeared during the scan.
    return sorted(vents, key=lambda vent: (-vent.modified_ns, vent.path.name.casefold(), vent.path.name))
