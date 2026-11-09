"""Draft editing and display-cell layout, independent of curses."""

from dataclasses import dataclass
import unicodedata

PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"'}


def iter_clusters(text: str):
    """Group common combining marks, emoji joins, and pairs of flag letters."""
    start = 0
    for index, char in enumerate(text):
        category = unicodedata.category(char)
        attach = index > start and (
            category.startswith("M")
            or char == "\u200d"
            or text[index - 1] == "\u200d"
            or "\U0001f3fb" <= char <= "\U0001f3ff"
            or ("\U0001f1e6" <= char <= "\U0001f1ff"
                and index - start == 1
                and "\U0001f1e6" <= text[start] <= "\U0001f1ff")
        )
        if index and not attach:
            yield start, index, text[start:index]
            start = index
    if text:
        yield start, len(text), text[start:]


def clusters(text: str) -> list[tuple[int, int, str]]:
    return list(iter_clusters(text))


def cell_width(text: str) -> int:
    if text.isascii() and text.isprintable():
        return len(text)
    total = 0
    for _, _, cluster in clusters(text):
        widths = [
            0 if (unicodedata.category(c).startswith(("M", "C")) or "\U0001f3fb" <= c <= "\U0001f3ff")
            else 2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
            for c in cluster
        ]
        if "\u200d" in cluster or "\ufe0f" in cluster:
            total += max(2, max(widths, default=0))
        elif len(cluster) == 2 and all("\U0001f1e6" <= c <= "\U0001f1ff" for c in cluster):
            total += 2
        else:
            total += sum(widths)
    return total


def safe_text(text: str) -> str:
    """Replace terminal control characters while keeping normal Unicode text."""
    if text.isascii() and text.isprintable():
        return text
    return "".join(
        "    " if c == "\t" else
        "?" if (unicodedata.category(c) == "Cc" or c in "\u2028\u2029") else c
        for c in text
    )


def clip(text: str, width: int) -> str:
    result: list[str] = []
    used = 0
    for _, _, item in clusters(safe_text(text)):
        size = cell_width(item)
        if used + size > width:
            break
        result.append(item)
        used += size
    return "".join(result)


def layout(text: str, width: int) -> tuple[list[str], dict[int, tuple[int, int]]]:
    """Lay out a draft once, including all cluster-boundary cursor positions."""
    width = max(2, width)
    lines = [""]
    x = 0
    soft_wrap = False
    positions = {}
    for start, end, item in clusters(text):
        display = safe_text(item)
        size = cell_width(display)
        if item != "\n" and x + size > width:
            lines.append("")
            x = 0
        positions[start] = (len(lines) - 1, x)
        if item == "\n":
            if not soft_wrap:
                lines.append("")
            x = 0
            soft_wrap = False
        else:
            soft_wrap = False
            lines[-1] += display
            x += size
            if x >= width:
                lines.append("")
                x = 0
                soft_wrap = True
    positions[len(text)] = (len(lines) - 1, x)
    return lines, positions


def wrap(text: str, width: int, cursor: int | None = None) -> tuple[list[str], tuple[int, int]]:
    """Wrap by terminal cells; return the corresponding draft cursor position."""
    lines, positions = layout(text, width)
    return lines, positions.get(cursor, (0, 0))


@dataclass
class Editor:
    text: str = ""
    cursor: int = 0

    def replace(self, start: int, end: int, replacement: str, *, cursor: int | None = None) -> None:
        self.text = self.text[:start] + replacement + self.text[end:]
        self.cursor = start + len(replacement) if cursor is None else cursor

    def insert(self, text: str, *, paste: bool = False) -> None:
        if paste:
            text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
        text = "".join(c for c in text if c.isprintable() or (paste and c == "\n") or c == "\u200d")
        self.replace(self.cursor, self.cursor, text)

    def type_character(self, char: str) -> None:
        """Pair typed delimiters; pasted text goes through insert() unchanged."""
        if char in PAIRS.values() and self.text[self.cursor:self.cursor + 1] == char:
            self.cursor += 1
        elif char in PAIRS:
            self.replace(self.cursor, self.cursor, char + PAIRS[char], cursor=self.cursor + 1)
        else:
            self.insert(char)

    def left(self) -> None:
        self.cursor = max((start for start, _, _ in clusters(self.text) if start < self.cursor), default=0)

    def right(self) -> None:
        self.cursor = next((end for _, end, _ in clusters(self.text) if end > self.cursor), len(self.text))

    def backspace(self, *, paired: bool = False) -> None:
        if (paired and self.cursor and self.text[self.cursor - 1] in PAIRS
                and self.text[self.cursor:self.cursor + 1] == PAIRS[self.text[self.cursor - 1]]):
            self.replace(self.cursor - 1, self.cursor + 1, "")
            return
        start = max((start for start, _, _ in iter_clusters(self.text) if start < self.cursor), default=0)
        self.replace(start, self.cursor, "")

    def delete(self) -> None:
        end = next((end for _, end, _ in iter_clusters(self.text) if end > self.cursor), len(self.text))
        self.replace(self.cursor, end, "")

    def delete_word(self) -> None:
        start = self.cursor
        while start and self.text[start - 1].isspace():
            start -= 1
        while start and not self.text[start - 1].isspace():
            start -= 1
        self.replace(start, self.cursor, "")

    def clear(self) -> None:
        self.replace(0, len(self.text), "")
