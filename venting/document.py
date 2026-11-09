"""Full-file editor buffer with multiline movement and delta-based undo/redo."""

from bisect import bisect_right
from dataclasses import dataclass

from .editor import PAIRS, Editor, cell_width, iter_clusters, safe_text


@dataclass
class Edit:
    start: int
    removed: str
    inserted: str
    before: int
    after: int


@dataclass
class Row:
    start: int
    end: int
    text: str


class DocumentEditor(Editor):
    def __init__(self, text: str = "", cursor: int = 0):
        super().__init__(text, cursor)
        self.undo_stack: list[Edit] = []
        self.redo_stack: list[Edit] = []
        self.top = 0
        self._rows: list[Row] = []
        self._starts: list[int] = []
        self._layout_key: tuple[str, int] | None = None
        self.preferred_column: int | None = None

    def replace(self, start: int, end: int, replacement: str, *, cursor: int | None = None) -> None:
        removed = self.text[start:end]
        before = self.cursor
        super().replace(start, end, replacement, cursor=cursor)
        self.preferred_column = None
        if removed != replacement:
            self.undo_stack.append(Edit(start, removed, replacement, before, self.cursor))
            if len(self.undo_stack) > 1000:
                del self.undo_stack[0]
            self.redo_stack.clear()
            self._layout_key = None

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        edit = self.undo_stack.pop()
        super().replace(edit.start, edit.start + len(edit.inserted), edit.removed, cursor=edit.before)
        self.redo_stack.append(edit)
        self._layout_key = None
        self.preferred_column = None
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        edit = self.redo_stack.pop()
        super().replace(edit.start, edit.start + len(edit.removed), edit.inserted, cursor=edit.after)
        self.undo_stack.append(edit)
        self._layout_key = None
        self.preferred_column = None
        return True

    def home(self) -> None:
        self.cursor = self.text.rfind("\n", 0, self.cursor) + 1
        self.preferred_column = None

    def previous_boundary(self) -> int:
        if self.cursor == 0:
            return 0
        if self.text[self.cursor - 1] == "\n":
            return self.cursor - 1
        start = self.text.rfind("\n", 0, self.cursor) + 1
        return start + max((a for a, _, _ in iter_clusters(self.text[start:self.cursor])), default=0)

    def next_boundary(self) -> int:
        end = self.text.find("\n", self.cursor)
        limit = len(self.text) if end < 0 else end + 1
        return self.cursor + next((b for _, b, _ in iter_clusters(self.text[self.cursor:limit])), 0)

    def left(self) -> None:
        self.cursor = self.previous_boundary()
        self.preferred_column = None

    def right(self) -> None:
        self.cursor = self.next_boundary()
        self.preferred_column = None

    def backspace(self, *, paired: bool = False) -> None:
        if (paired and self.cursor and self.text[self.cursor - 1] in PAIRS
                and self.text[self.cursor:self.cursor + 1] == PAIRS[self.text[self.cursor - 1]]):
            self.replace(self.cursor - 1, self.cursor + 1, "")
        else:
            self.replace(self.previous_boundary(), self.cursor, "")

    def delete(self) -> None:
        self.replace(self.cursor, self.next_boundary(), "")

    def end(self) -> None:
        end = self.text.find("\n", self.cursor)
        self.cursor = len(self.text) if end < 0 else end
        self.preferred_column = None

    def rows(self, width: int) -> list[Row]:
        width = max(2, width)
        if self._layout_key == (self.text, width):
            return self._rows
        rows: list[Row] = []
        start, used = 0, 0
        line: list[str] = []
        for index, end, cluster in iter_clusters(self.text):
            if cluster == "\n":
                rows.append(Row(start, index, "".join(line)))
                start, used, line = end, 0, []
                continue
            display = safe_text(cluster)
            size = cell_width(display)
            if used + size > width:
                rows.append(Row(start, index, "".join(line)))
                start, used, line = index, 0, []
            line.append(display)
            used += size
        rows.append(Row(start, len(self.text), "".join(line)))
        if used >= width:
            rows.append(Row(len(self.text), len(self.text), ""))
        self._rows = rows
        self._starts = [row.start for row in rows]
        self._layout_key = self.text, width
        return rows

    def position(self, width: int) -> tuple[int, int]:
        rows = self.rows(width)
        index = max(0, bisect_right(self._starts, self.cursor) - 1)
        source = self.text[rows[index].start:self.cursor].split("\n", 1)[0]
        column = cell_width(safe_text(source))
        if column >= width and index + 1 < len(rows):
            return index + 1, 0
        return index, min(column, width - 1)

    def move_rows(self, delta: int, width: int) -> None:
        rows = self.rows(width)
        row, column = self.position(width)
        if self.preferred_column is None:
            self.preferred_column = column
        target = max(0, min(len(rows) - 1, row + delta))
        item = rows[target]
        cursor = item.start
        used = 0
        for start, end, cluster in iter_clusters(self.text[item.start:item.end]):
            size = cell_width(safe_text(cluster))
            if used + size > self.preferred_column:
                break
            used += size
            cursor = item.start + end
        self.cursor = cursor
