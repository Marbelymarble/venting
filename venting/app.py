"""Curses interface. Storage, editing, and spelling remain reusable modules."""

import curses
from datetime import datetime
import os
from pathlib import Path
import sys
import textwrap

from .autocorrect import Autocorrect, Correction, LANGUAGE_NAMES
from .clipboard import copy_file
from .document import DocumentEditor
from .editor import Editor, cell_width, clip, layout, wrap
from .keyboard import CTRL_TAB, DOC_HOME, DOC_END, PASTE, KeyboardModes
from .recent import RecentVent, list_vents
from .settings import Settings
from .shortcuts import (ACTION_LABELS, DEFAULT_BINDINGS, binding_for_key, display_binding,
                        key_for, validate_bindings)
from .storage import Document, TextFile
from .summaries import (DEFAULT_MODEL, MAX_SUMMARY_CHARS, SummaryWorker, cached_summary,
                        manual_summary_token, metadata_path, revision, save_summary, snapshot)
from .topicmap import TopicGraph, TopicMapWorker, VALID_DAYS, graph_positions
from . import kitty_graphics


class App:
    def __init__(self, *, show_preview: bool = False, no_color: bool = False,
                 settings: Settings | None = None, config_path: Path | None = None,
                 enable_summaries: bool = False):
        self.file: TextFile | None = None
        self.draft = Editor()
        self.preview = show_preview
        self.no_color = no_color
        self.corrector: Autocorrect | None = None
        self.autocorrect = False
        self.undo_correction: Correction | None = None
        self.skip_correction_once = False
        self.saved_count = 0
        self.chooser = True
        self.create = True
        self.path = Editor()
        self.selection = -1
        self.entries: list[Path] = []
        self.recent: list[RecentVent] | None = None
        self.recent_index = 0
        self.recent_top = 0
        self.recent_focus = False
        self.modal: str | None = None
        self.pending: str | None = None
        self.running = True
        self.message = ""
        self.error = False
        try:
            self.settings = settings if settings is not None else Settings.load(config_path)
        except (OSError, ValueError, UnicodeError):
            self.settings = Settings(config_path)
            self.note("Invalid settings. Check the configuration file.", error=True)
        model = self.settings.summary_model or (DEFAULT_MODEL if enable_summaries else "")
        self.summaries = SummaryWorker(model) if model else None
        self.directory = Editor()
        self.summary_model = Editor()
        self.edit_name = Editor()
        self.edit_summary = Editor()
        self.edit_source: Path | None = None
        self.edit_revision: tuple[int, int, int, int, int] | None = None
        self.edit_original_summary = ""
        self.edit_preview = ""
        self.edit_focus = 0
        self.edit_delete_armed = False
        self.edit_error = ""
        self.settings_show_recent = True
        self.settings_autocorrect_language = "en"
        self.settings_focus = 0
        self.directory_error = ""
        self.shortcut_values = self.settings.keybindings
        self.shortcut_index = 0
        self.shortcut_capture = False
        self.command_editing = False
        self.command_index = 0
        self.command_error = ""
        self.document: Document | None = None
        self.file_editor: DocumentEditor | None = None
        self.file_focus = False
        self.file_conflict = False
        self.file_sync_pending = False
        self._file_width = 40
        self._file_rows = 10
        self.palette: dict[str, int] = {}
        self._paste: list[str] | None = None
        self._paste_tail = ""
        self.keyboard = KeyboardModes()
        self.topic_worker: TopicMapWorker | None = None
        self.topic_days = self.settings.topic_map_days
        self.topic_selected = 0
        self.topic_reference = 0
        self.topic_reference_focus = False
        self.topic_error = ""
        self.topic_hitboxes: list[tuple[int, int, int, int, str, int]] = []
        self.pending_reference: tuple[Path, str, int] | None = None
        self._topic_image: tuple[bytes, int, int, int, int, int, int] | None = None
        self._topic_image_key: object = None
        self._topic_image_sent: object = None
        self._default_path()

    def _default_path(self) -> None:
        value = str(self.settings.default_directory / f"thoughts-{datetime.now():%Y-%m-%d-%H%M%S}.txt")
        self.path = Editor(value, len(value))
        self.selection = -1

    def _append_path(self) -> None:
        value = str(self.settings.default_directory) + os.sep
        self.path = Editor(value, len(value))
        self.selection = -1

    def picker_path(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.settings.default_directory / path

    def prepare_default_directory(self) -> None:
        try:
            self.settings.ensure_directory()
        except (OSError, ValueError):
            self.note("Default directory unavailable. Open the program menu, then Settings.", error=True)
        else:
            if self.chooser and self.settings.show_recent_vents:
                self.refresh_recent()

    def open_path(self, path: str, *, create: bool, guess_extension: bool = True) -> None:
        target = Path(path).expanduser()
        if guess_extension and target.name and not target.suffix and not target.name.endswith("."):
            with_extension = target.with_name(target.name + ".txt")
            if create and not target.is_dir():
                target = with_extension
            elif not create and not os.path.lexists(target):
                target = with_extension if with_extension.is_file() else target
        new = TextFile(target, create=create)
        old = self.file
        self.file = new
        if old:
            old.close()
        self.chooser = False
        self.recent = None
        self.recent_focus = False
        self.drop_file_buffer()
        self.saved_count = 0
        self.note("File opened. Draft kept." if self.draft.text else "File opened.")
        if self.preview:
            self.load_file_editor()

    def close(self) -> None:
        kitty_graphics.clear()
        if self.topic_worker:
            self.topic_worker.close()
        if self.summaries:
            self.summaries.close()
        if self.file:
            self.file.close()
            self.file = None

    def note(self, message: str, *, error: bool = False) -> None:
        self.message, self.error = message, error

    def _colors(self) -> None:
        self.palette = {name: 0 for name in ("accent", "muted", "text", "error", "success")}
        if self.no_color or not curses.has_colors():
            self.palette["accent"] = curses.A_BOLD
            self.palette["muted"] = curses.A_DIM
            self.palette["error"] = curses.A_BOLD
            return
        curses.start_color()
        try:
            curses.use_default_colors()
            background = -1
        except curses.error:
            background = curses.COLOR_BLACK
        colors = [curses.COLOR_CYAN, curses.COLOR_WHITE, curses.COLOR_WHITE,
                  curses.COLOR_RED, curses.COLOR_GREEN]
        # ANSI colors are deliberately used even in 256-color terminals: Kitty
        # maps these through its live theme, including DMS-generated palettes.
        for index, (name, color) in enumerate(zip(self.palette, colors), 1):
            curses.init_pair(index, color, background)
            self.palette[name] = curses.color_pair(index)

    def run(self, screen: "curses.window") -> None:
        self.screen = screen
        if self.chooser:
            self.prepare_default_directory()
        curses.raw()  # Ctrl+C is handled with the same draft guard as Ctrl+Q.
        curses.noecho()
        screen.keypad(True)
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
            curses.mouseinterval(0)
        except curses.error:
            pass
        screen.timeout(100)
        if hasattr(curses, "set_escdelay"):
            curses.set_escdelay(25)
        self._colors()
        # Prevent pasted newlines from silently submitting thoughts.
        sys.stdout.write(self.keyboard.enable())
        sys.stdout.flush()
        try:
            while self.running:
                self.draw()
                # Drain a bounded burst before repainting. Redrawing a full
                # pane per buffered character creates avoidable input lag.
                for index in range(256):
                    screen.timeout(100 if index == 0 else 0)
                    key = self.read_key()
                    if key is None:
                        break
                    self.handle(key)
                    if not self.running or key == curses.KEY_RESIZE:
                        break
        finally:
            sys.stdout.write(self.keyboard.restore())
            sys.stdout.flush()
            try:
                curses.curs_set(1)
            except curses.error:
                pass

    def read_key(self) -> str | int | tuple[str, str] | None:
        if self._paste is not None:
            return self._read_paste()
        try:
            key = self.screen.get_wch()
        except curses.error:
            return None
        if key != "\x1b":
            return key
        # ncurses does not decode CSI-u or modifyOtherKeys on many systems.
        sequence = ""
        self.screen.timeout(50)
        try:
            for _ in range(128):
                following = self.screen.get_wch()
                if not isinstance(following, str):
                    curses.ungetch(following)
                    break
                sequence += following
                if sequence[0] != "[" or (len(sequence) > 1 and "@" <= following <= "~"):
                    break
        except curses.error:
            pass
        finally:
            self.screen.timeout(100)
        if sequence.startswith("["):
            decoded = self.keyboard.decode(sequence[1:])
            if decoded != PASTE:
                return decoded
        else:
            # Return an ordinary Escape without discarding subsequently typed keys.
            for char in reversed(sequence):
                curses.unget_wch(char)
            return "\x1b"
        self._paste = []
        self._paste_tail = ""
        return self._read_paste()

    def _read_paste(self) -> tuple[str, str] | None:
        assert self._paste is not None
        try:
            for _ in range(4096):
                try:
                    item = self.screen.get_wch()
                except curses.error:
                    break
                self.screen.timeout(0)
                if item in ("\x03", "\x11"):
                    # Recover a partial paste if its terminator never arrived.
                    text = "".join(self._paste)
                    self._paste = None
                    curses.unget_wch(item)
                    return "paste", text
                if isinstance(item, str):
                    self._paste.append(item)
                    self._paste_tail = (self._paste_tail + item)[-6:]
                    if self._paste_tail == "\x1b[201~":
                        text = "".join(self._paste)[:-6]
                        self._paste = None
                        return "paste", text
        finally:
            self.screen.timeout(100)
        return None

    def put(self, y: int, x: int, text: str, style: str = "text", *, width: int | None = None) -> None:
        height, columns = self.screen.getmaxyx()
        if not 0 <= y < height or not 0 <= x < columns:
            return
        limit = columns - x - (1 if y == height - 1 else 0)
        if width is not None:
            limit = min(limit, width)
        try:
            self.screen.addstr(y, x, clip(text, max(0, limit)), self.palette[style])
        except curses.error:
            pass  # Resize or a terminal's different emoji cell width.

    def box(self, y: int, x: int, height: int, width: int, title: str) -> None:
        if height < 2 or width < 4:
            return
        self.put(y, x, "╭" + "─" * (width - 2) + "╮", "muted")
        self.put(y + height - 1, x, "╰" + "─" * (width - 2) + "╯", "muted")
        for row in range(y + 1, y + height - 1):
            self.put(row, x, "│", "muted")
            self.put(row, x + width - 1, "│", "muted")
        self.put(y, x + 2, f" {title} ", "accent", width=width - 4)

    def cursor(self, y: int, x: int) -> None:
        h, w = self.screen.getmaxyx()
        try:
            curses.curs_set(1)
            self.screen.move(max(0, min(h - 1, y)), max(0, min(w - 1, x)))
        except curses.error:
            pass

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 18 or width < 48:
            self.put(1, 2, "venting", "accent")
            self.put(5, 2, "Resize to at least 48 columns × 18 rows.", "muted")
            self.put(7, 2, "Ctrl+Q quit", "muted")
        elif self.chooser:
            self.draw_chooser(height, width)
        else:
            self.draw_writer(height, width)
        if self.modal:
            self.draw_modal(height, width)
        self.screen.refresh()
        if self.modal == "topic_map" and self._topic_image:
            pixels, pixel_width, pixel_height, y, x, rows, columns = self._topic_image
            if self._topic_image_sent != self._topic_image_key:
                if self._topic_image_sent is not None:
                    kitty_graphics.clear()
                kitty_graphics.display_rgba(pixels, pixel_width, pixel_height,
                                            y, x, rows, columns)
                self._topic_image_sent = self._topic_image_key
        elif self._topic_image_sent is not None:
            kitty_graphics.clear()
            self._topic_image_sent = None

    def _draw_path(self, y: int, x: int, width: int, *, editor: Editor | None = None,
                   show_cursor: bool = True) -> None:
        editor = self.path if editor is None else editor
        before = editor.text[:editor.cursor]
        start = 0
        while start < len(before) and cell_width(before[start:]) >= width:
            start += 1
        self.put(y, x, editor.text[start:], width=width)
        if show_cursor:
            self.cursor(y, x + cell_width(before[start:]))

    def _entries(self) -> None:
        raw = self.path.text
        try:
            expanded = self.picker_path(raw)
            browsing = not raw or raw.endswith(os.sep)
            directory = expanded if browsing else expanded.parent
            prefix = "" if browsing else expanded.name.lower()
            self.entries = sorted(
                (p for p in directory.iterdir()
                 if p.name.lower().startswith(prefix)
                 and (not p.name.startswith(".") or prefix.startswith("."))
                 and (p.is_dir() or not self.create)),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )[:200]
        except (OSError, ValueError):
            self.entries = []
        if self.selection >= len(self.entries):
            self.selection = -1

    def draw_chooser(self, height: int, width: int) -> None:
        self.put(1, 3, "venting", "accent")
        self.put(3, 3, "Choose a file action")
        new = "● Create new" if self.create else "○ Create new"
        append = "○ Open existing" if self.create else "● Open existing"
        self.put(4, 3, new + "  Ctrl+N", "accent" if self.create else "muted")
        self.put(4, 27, append + "  " + self.shortcut_label("files"),
                 "muted" if self.create else "accent",
                 width=max(1, width - 27))
        self.put(5, 3, "Default folder: " + str(self.settings.default_directory),
                 "muted", width=width - 6)
        self.box(6, 2, 3, width - 4,
                 "NEW FILE NAME OR PATH" if self.create else "EXISTING FILE NAME OR PATH")
        self._entries()
        if self.recent is None:
            available = height - 14
            first = max(0, self.selection - available + 1)
            for row, item in enumerate(self.entries[first:first + available]):
                selected = first + row == self.selection
                label = ("› " if selected else "  ") + item.name + ("/" if item.is_dir() else "")
                self.put(10 + row, 4, label, "accent" if selected else "muted", width=width - 8)
            status = self.message or "Recent vents are hidden on startup; Tab shows them."
        else:
            self.draw_start_recents(height, width)
            if self.selection >= 0 and self.entries:
                status = "Path match: " + self.entries[self.selection].name
            elif self.recent_focus and self.recent:
                status = self.message or "Selected file: " + self.recent[self.recent_index].path.name
            else:
                status = self.message or ("Choose a saved vent below."
                                          if self.recent_focus else
                                          "Enter a file above, or use Tab to browse recent vents.")
        self.put(height - 4, 3, status, "error" if self.error else "muted", width=width - 6)
        self.put(height - 3, 2, "─" * (width - 4), "muted", width=width - 4)
        commands = self.shortcut_label("commands")
        self.put(height - 2, 2,
                 ("E edit details · R redo summary · S summarize missing" if self.recent_focus
                  else "Tab recent vents · Ctrl+N create · " +
                  self.shortcut_label("files") + " open existing"), "muted")
        self.put(height - 1, 2,
                 (f"Enter open · {self.shortcut_label('topic_map')} graph · ↑/↓ select · Tab path · {commands} menu"
                  if self.recent_focus else
                  f"Enter {'create' if self.create else 'open'} · {self.shortcut_label('topic_map')} graph · "
                  f"↑/↓ matches · {commands} menu"), "muted", width=width - 4)
        if self.recent_focus:
            try:
                curses.curs_set(0)
            except curses.error:
                pass
        else:
            self._draw_path(7, 4, width - 8)

    def refresh_recent(self, *, retry: bool = False, reload_selected: bool = False) -> None:
        previous = self.recent[self.recent_index].path if self.recent else None
        try:
            self.recent = list_vents(self.settings.default_directory, exclude=self.settings.config_path)
        except OSError:
            self.recent = []
            self.note("Cannot read the default directory.", error=True)
        else:
            self.note("")
        self.recent_index = next((index for index, vent in enumerate(self.recent)
                                  if vent.path == previous), 0)
        self.recent_top = 0
        if self.summaries:
            if reload_selected and self.recent:
                selected = self.recent[self.recent_index].path
                token = manual_summary_token(selected)
                if token:
                    self.summary_redo = (selected, token)
                    self.modal = "redo_manual_summary"
                    return
                self.summaries.submit((selected,), priority=True, retry=retry, force=True)
                self.summaries.submit(vent.path for vent in self.recent if vent.path != selected)
                self.note("Reloading summary: " + selected.name)
            else:
                self.summaries.submit((vent.path for vent in self.recent), retry=retry)
        elif reload_selected:
            self.note("Set a local summary model in Settings first.", error=True)

    def recent_summary(self, path: Path) -> str:
        try:
            current = revision(path)
        except (OSError, ValueError):
            return "File unavailable. Press R to reload."
        if current[2] == 0:
            return "Empty file."
        sentence = cached_summary(path, current)
        if sentence:
            return sentence
        if self.summaries:
            return self.summaries.failure(path, current) or "Summary pending. R reloads it."
        return "No summary. Enable a local model in Settings."

    def summarize_missing(self) -> None:
        if not self.summaries:
            self.note("Set a local summary model in Settings first.", error=True)
            return
        missing = []
        for vent in self.recent or []:
            try:
                current = revision(vent.path)
            except (OSError, ValueError):
                continue
            if current[2] and not cached_summary(vent.path, current):
                missing.append(vent.path)
        self.summaries.submit(missing, retry=True)
        self.note(f"Queued {len(missing)} missing summar" +
                  ("y." if len(missing) == 1 else "ies."))

    def draw_start_recents(self, height: int, width: int) -> None:
        assert self.recent is not None
        list_y = 10
        rows = max(1, height - 14)
        self.put(9, 3, f"Recent vents ({len(self.recent)})" +
                 (" — BROWSING" if self.recent_focus else ""),
                 "accent" if self.recent_focus else "muted", width=width - 6)
        self.recent_top = max(0, min(self.recent_top, self.recent_index, len(self.recent) - rows))
        self.recent_top = max(self.recent_top, self.recent_index - rows + 1)
        for index, vent in enumerate(self.recent[self.recent_top:self.recent_top + rows], self.recent_top):
            selected = index == self.recent_index
            y = list_y + index - self.recent_top
            self.put(y, 3, ("› " if selected else "  ") + self.recent_summary(vent.path),
                     "accent" if selected and self.recent_focus else "text",
                     width=width - (26 if width >= 68 else 6))
            if width >= 68:
                when = datetime.fromtimestamp(vent.modified_ns / 1_000_000_000).strftime("%Y-%m-%d %H:%M")
                self.put(y, width - 19, when, "muted")
        if not self.recent:
            self.put(10, 3, "No files in this directory.", "muted")

    def handle_recent(self, key: str | int | tuple[str, str]) -> None:
        if key in ("\x1b", "\t"):
            self.recent_focus = False
            self.note("")
        elif key in ("r", "R", "\x12"):
            self.refresh_recent(retry=True, reload_selected=True)
        elif key in ("e", "E") and self.recent:
            self.open_edit_vent()
        elif key in ("s", "S"):
            self.summarize_missing()
        elif self.recent:
            if key in ("\n", "\r", curses.KEY_ENTER):
                try:
                    self.open_path(str(self.recent[self.recent_index].path), create=False, guess_extension=False)
                except (OSError, ValueError) as error:
                    self.note(str(error), error=True)
            elif key in (curses.KEY_HOME, DOC_HOME):
                self.recent_index = 0
            elif key in (curses.KEY_END, DOC_END):
                self.recent_index = len(self.recent) - 1
            elif key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
                height = self.screen.getmaxyx()[0]
                page = max(1, height - 13)
                delta = {curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                         curses.KEY_PPAGE: -page, curses.KEY_NPAGE: page}[key]
                self.recent_index = max(0, min(len(self.recent) - 1, self.recent_index + delta))

    def copy_saved_file(self) -> None:
        if self.recent:
            path = self.recent[self.recent_index].path
        elif not self.chooser and self.file:
            path = self.file.path
        else:
            self.note("No file selected.", error=True)
            return
        try:
            confirmed = copy_file(path)
        except (OSError, ValueError) as error:
            self.note(f"Copy failed: {error}", error=True)
        else:
            self.note("Copied saved file." if confirmed else "Clipboard copy requested.")

    def draw_writer(self, height: int, width: int) -> None:
        assert self.file is not None
        self.put(1, 3, "venting", "accent")
        language = (self.corrector.language if self.corrector else
                    self.settings.autocorrect_language).upper()
        state = f"{language} autocorrect ON" if self.autocorrect else f"autocorrect off · {language}"
        self.put(1, width - len(state) - 3, state, "accent" if self.autocorrect else "muted")
        self.put(3, 3, str(self.file.path), "muted", width=width - 6)
        top, body = 5, height - 9
        if not self.preview:
            rect = (top, 2, body, width - 4)
            draft_rect = None if self.file_focus else rect
            file_rect = rect if self.file_focus else None
        elif width >= 92:
            left_width = (width - 5) // 2
            draft_rect = (top, 2, body, left_width)
            file_rect = (top, left_width + 3, body, width - left_width - 5)
        else:
            first_height = max(4, body // 2)
            draft_rect = (top, 2, first_height, width - 4)
            file_rect = (top + first_height, 2, body - first_height, width - 4)
        self.put(height - 4, 3, self.message,
                 "error" if self.error else "success", width=width - 6)
        self.put(height - 3, 2, "─" * (width - 4), "muted", width=width - 4)
        self.put(height - 2, 2, f"Esc save & file selection · {self.shortcut_label('files')} open/switch file · "
                 f"{self.shortcut_label('topic_map')} graph · {self.shortcut_label('commands')} program menu", "muted")
        if self.file_focus:
            footer = ("Ctrl+S save file · Tab thought · " + self.shortcut_label("panes") +
                      (" hide editor" if self.preview else " show both fields"))
        elif self.preview:
            footer = ("Enter append thought · Tab edit file · " + self.shortcut_label("panes") +
                      " hide editor · " + self.shortcut_label("autocorrect") + " " + language)
        else:
            footer = ("Enter append thought · Tab edit file · " + self.shortcut_label("panes") +
                      " show editor · " + self.shortcut_label("autocorrect") + " " + language)
        self.put(height - 1, 2, footer, "muted")
        # Draw the active pane last to leave the terminal cursor in that pane.
        if self.file_focus and file_rect:
            if draft_rect:
                self.draw_draft(*draft_rect)
            self.draw_preview(*file_rect)
        else:
            if file_rect:
                self.draw_preview(*file_rect)
            if draft_rect:
                self.draw_draft(*draft_rect)

    def draw_draft(self, y: int, x: int, height: int, width: int) -> None:
        self.box(y, x, height, width, "THOUGHT TO APPEND" +
                 (" · ACTIVE" if not self.file_focus else ""))
        inner_width = width - 4
        rows = max(1, height - 4)
        self.put(y + 1, x + 2, "Enter appends this text to the saved file, then clears it.",
                 "muted", width=inner_width)
        lines, (row, column) = wrap(self.draft.text, inner_width, self.draft.cursor)
        start = max(0, row - rows + 1)
        for index, line in enumerate(lines[start:start + rows]):
            self.put(y + 2 + index, x + 2, line, width=inner_width)
        if not self.file_focus:
            self.cursor(y + 2 + row - start, x + 2 + column)

    def draw_preview(self, y: int, x: int, height: int, width: int) -> None:
        self.refresh_file_editor()
        dirty = " *" if self.file_dirty else ""
        status = " · CHANGED ON DISK" if self.file_conflict else ""
        active = " · ACTIVE" if self.file_focus else ""
        self.box(y, x, height, width, "SAVED FILE CONTENT" + dirty + active + status)
        self._file_width = max(2, width - 4)
        # Reserve a real text viewport before allocating header rows. In a
        # narrow split, shortcuts wrap instead of being silently cut off.
        header_budget = max(0, height - 3)
        help_lines = textwrap.wrap("Enter newline · Ctrl+S save · Tab thought", self._file_width)
        help_rows = min(len(help_lines), 2, header_budget)
        for index, line in enumerate(help_lines[:help_rows]):
            self.put(y + 1 + index, x + 2, line, "muted", width=self._file_width)
        summary = "RECENT-LIST SUMMARY · " + self.recent_summary(self.file.path)
        summary_lines = textwrap.wrap(summary, self._file_width)
        summary_rows = min(len(summary_lines), 2, max(0, header_budget - help_rows - 1))
        for index, line in enumerate(summary_lines[:summary_rows]):
            if index == summary_rows - 1 and len(summary_lines) > summary_rows:
                line = clip(line, self._file_width - 1) + "…"
            self.put(y + 1 + help_rows + index, x + 2, line, "muted", width=self._file_width)
        content_y = y + 1 + help_rows + summary_rows
        if header_budget > help_rows + summary_rows:
            self.put(content_y, x + 2, "─" * self._file_width, "muted", width=self._file_width)
            content_y += 1
        self._file_rows = max(1, y + height - 1 - content_y)
        if self.file_editor is None:
            self.put(content_y, x + 2, "File could not be loaded.", "error", width=width - 4)
            return
        editor = self.file_editor
        lines = editor.rows(self._file_width)
        row, column = editor.position(self._file_width)
        editor.top = max(0, min(editor.top, row))
        if row >= editor.top + self._file_rows:
            editor.top = row - self._file_rows + 1
        for index, line in enumerate(lines[editor.top:editor.top + self._file_rows]):
            self.put(content_y + index, x + 2, line.text, width=width - 4)
        if self.file_focus:
            self.cursor(content_y + row - editor.top, x + 2 + column)

    def draw_modal(self, height: int, width: int) -> None:
        if self.modal == "commands":
            self.draw_commands(height, width)
            return
        if self.modal == "settings":
            self.draw_directory_settings(height, width)
            return
        if self.modal == "edit_vent":
            self.draw_edit_vent(height, width)
            return
        if self.modal == "topic_map":
            self.draw_topic_map(height, width)
            return
        if self.modal == "redo_manual_summary":
            title = "REPLACE YOUR SUMMARY?"
            lines = ["You wrote this summary yourself.",
                     "Replace it with an LLM-generated summary?", "",
                     "Y  Confirm and redo", "N / Esc  Keep your summary"]
        elif self.modal == "help":
            title = "HELP · KEYS"
            lines = [
                "Enter        Append thought; newline in file editor",
                f"{self.shortcut_label('panes'):<12} Show or hide the saved-file editor",
                "Tab          Switch thought / saved-file fields",
                "Ctrl+S       Save changes made in the file editor",
                "Ctrl+R       Reload the saved file (guards edits)",
                "Ctrl+Z/Y     Undo / redo in the file editor",
                "Home/End     Start / end of the current line",
                f"{self.shortcut_label('files'):<12} Open or switch to an existing file",
                f"{self.shortcut_label('autocorrect'):<12} Toggle thought autocorrect",
                f"{self.shortcut_label('commands'):<12} Open the full program menu",
                f"{self.shortcut_label('topic_map'):<12} Open / close the graphical topic map",
                "Esc          Save and return to file selection",
                "Recent vents E edit details · R redo summary",
                '() [] {} ""  Auto-pair typed delimiters',
                "Ctrl+Q/C quit; Esc closes this help",
            ]
        else:
            title = "UNSAVED FILE CHANGES" if self.modal == "file_changes" else "UNSAVED DRAFT"
            lines = ["Save before continuing?", "", "S  Save and continue",
                     "D  Discard and continue", "Esc  Keep editing"]
        box_width = min(width - 4, 62)
        box_height = min(height - 2, len(lines) + 4)
        y, x = (height - box_height) // 2, (width - box_width) // 2
        for row in range(y, y + box_height):
            self.put(row, x, " " * box_width)
        self.box(y, x, box_height, box_width, title)
        for row, line in enumerate(lines[:box_height - 3]):
            self.put(y + 2 + row, x + 2, line, width=box_width - 4)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def open_topic_map(self, *, force: bool = False) -> None:
        """Open immediately; graph construction continues in the background."""
        self.modal = "topic_map"
        self.topic_selected = 0
        self.topic_reference = 0
        self.topic_reference_focus = False
        self.topic_error = ""
        self._topic_image_key = None
        model = self.summaries.model if self.summaries else self.settings.summary_model
        if not model:
            self.topic_error = "Set a local Ollama model in Default path & settings first."
            return
        if (self.topic_worker is None or self.topic_worker.model != model or
                self.topic_worker.directory != self.settings.default_directory):
            if self.topic_worker:
                self.topic_worker.close()
            self.topic_worker = TopicMapWorker(self.settings.default_directory,
                                               self.settings.config_path, model)
        self.topic_worker.submit(self.topic_days, force=force)

    @staticmethod
    def _days_label(days: int) -> str:
        return "all time" if days == 0 else f"last {days} days"

    def draw_topic_map(self, height: int, width: int) -> None:
        # Unlike compact dialogs, the topic map owns the entire viewport. Clear
        # the chooser/writer first so their text and borders cannot bleed
        # through the transparent Kitty image layer.
        self.screen.erase()
        self.topic_hitboxes = []
        self.put(0, 2, "TOPIC MAP", "accent")
        self.put(0, 14, "Local Ollama · " + self._days_label(self.topic_days), "muted",
                 width=width - 16)
        self.put(height - 2, 2,
                 "T timeframe · R rebuild · Tab topics/references · arrows select · Enter open source",
                 "muted", width=width - 4)
        self.put(height - 1, 2, "Mouse: click a topic or source · Esc close", "muted",
                 width=width - 4)
        if self.topic_error:
            self.box(2, 2, height - 5, width - 4, "GRAPH")
            self.put(5, 5, self.topic_error, "error", width=width - 10)
            self.put(7, 5, "The map only connects to Ollama on 127.0.0.1.", "muted",
                     width=width - 10)
            self._topic_image = None
            return
        if not self.topic_worker:
            self._topic_image = None
            return
        loading, graph, error = self.topic_worker.state()
        if error:
            self.box(2, 2, height - 5, width - 4, "GRAPH")
            self.put(5, 5, error, "error", width=width - 10)
            self.put(7, 5, "Press R to retry, T to change timeframe, or Esc to close.",
                     "muted", width=width - 10)
            self._topic_image = None
            return
        if graph is None:
            self.box(2, 2, height - 5, width - 4, "GRAPH")
            self.put(5, 5, "Building a contextual map…", "accent")
            self.put(7, 5, "You can close this view; analysis continues in the background.",
                     "muted", width=width - 10)
            self._topic_image = None
            return
        self.topic_selected = min(self.topic_selected, len(graph.topics) - 1)
        topic = graph.topics[self.topic_selected]
        self.topic_reference = min(self.topic_reference, len(topic.references) - 1)
        reference_width = 38 if width >= 88 else max(24, width // 3)
        graph_x, graph_y = 1, 2
        graph_width, graph_height = width - reference_width - 3, height - 5
        reference_x = graph_x + graph_width + 1
        self.box(graph_y, graph_x, graph_height, graph_width,
                 f"GRAPH · {len(graph.topics)} TOPICS · {graph.file_count} VENTS" +
                 (" · UPDATING" if loading else ""))
        self.box(graph_y, reference_x, graph_height, reference_width, "TEXT REFERENCES")
        self.put(graph_y + 1, graph_x + 2, "Bubble area: passages · links: context", "muted",
                 width=graph_width - 4)
        inner_columns, inner_rows = max(1, graph_width - 4), max(1, graph_height - 3)
        positions = graph_positions(graph, inner_columns, inner_rows)
        absolute_positions = [(graph_x + 2 + x, graph_y + 1 + y) for x, y in positions]
        if kitty_graphics.supported():
            palette = kitty_graphics.kitty_palette()
            cell_width_px, cell_height_px = kitty_graphics.cell_size()
            key = (id(graph), self.topic_selected, inner_columns, inner_rows, palette,
                   cell_width_px, cell_height_px)
            if key != self._topic_image_key:
                pixels = kitty_graphics.render_graph(graph, positions, inner_columns, inner_rows,
                                                     self.topic_selected, palette=palette,
                                                     cell_width=cell_width_px,
                                                     cell_height=cell_height_px)
                self._topic_image = (pixels, inner_columns * cell_width_px, inner_rows * cell_height_px,
                                     graph_y + 1, graph_x + 2, inner_rows, inner_columns)
                self._topic_image_key = key
        else:
            self._topic_image = None
            self.put(graph_y + 2, graph_x + 3,
                     "Graphical canvas requires Kitty; topics remain usable below.",
                     "muted", width=graph_width - 6)
        for index, ((x, y), item) in enumerate(zip(absolute_positions, graph.topics)):
            label = clip(item.name, min(26, inner_columns))
            label_width = cell_width(label)
            start_x = max(graph_x + 2, min(x - label_width // 2,
                                         graph_x + graph_width - label_width - 2))
            label_y = min(y + 2, graph_y + graph_height - 2)
            selected = index == self.topic_selected
            self.put(label_y, start_x, label, "accent" if selected else "muted",
                     width=graph_x + graph_width - start_x - 1)
            self.topic_hitboxes.append((y - 1, min(x - 1, start_x), label_y,
                                        max(x + 1, start_x + label_width - 1), "topic", index))
        self.put(graph_y + 2, reference_x + 2, topic.name, "accent",
                 width=reference_width - 4)
        count = topic.frequency
        vents = len({reference.path for reference in topic.references})
        self.put(graph_y + 3, reference_x + 2,
                 f"{count} passage{'s' if count != 1 else ''} · {vents} vent{'s' if vents != 1 else ''}", "muted",
                 width=reference_width - 4)
        row = graph_y + 5
        for index, reference in enumerate(topic.references):
            if row >= graph_y + graph_height - 2:
                break
            selected = self.topic_reference_focus and index == self.topic_reference
            prefix = "› " if selected else "  "
            self.put(row, reference_x + 2, prefix + reference.path.name,
                     "accent" if selected else "text", width=reference_width - 4)
            excerpt_lines, _ = wrap("“" + reference.excerpt + "”", reference_width - 6, 0)
            shown = min(3, len(excerpt_lines), graph_y + graph_height - 2 - row)
            for offset, line in enumerate(excerpt_lines[:shown], 1):
                self.put(row + offset, reference_x + 4, line, "muted",
                         width=reference_width - 6)
            end = row + shown
            self.topic_hitboxes.append((row, reference_x + 1, end,
                                        reference_x + reference_width - 2, "reference", index))
            row = end + 2
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _open_topic_reference(self, graph: TopicGraph) -> None:
        topic = graph.topics[self.topic_selected]
        reference = topic.references[self.topic_reference]
        self.pending_reference = (reference.path, reference.excerpt, reference.offset)
        self.modal = None
        self.request("topic_reference")

    def handle_topic_map(self, key: str | int | tuple[str, str]) -> None:
        if key == "\x1b" or self.shortcut("topic_map", key):
            self.modal = None
            return
        if key in ("\x11", "\x03"):
            self.modal = None
            self.request("quit")
            return
        if key in ("t", "T"):
            index = (VALID_DAYS.index(self.topic_days) + 1) % len(VALID_DAYS)
            self.topic_days = VALID_DAYS[index]
            try:
                self.settings.set_topic_map_days(self.topic_days)
            except OSError as error:
                self.topic_error = "Could not save timeframe: " + str(error)
                return
            self.topic_selected = self.topic_reference = 0
            self._topic_image_key = None
            if self.topic_worker:
                self.topic_worker.submit(self.topic_days)
            return
        if key in ("r", "R"):
            if self.topic_worker:
                self.topic_worker.submit(self.topic_days, force=True)
            return
        if key == "\t":
            self.topic_reference_focus = not self.topic_reference_focus
            return
        if key == curses.KEY_MOUSE:
            try:
                _, x, y, _, state = curses.getmouse()
            except curses.error:
                return
            if not state & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED |
                            curses.BUTTON1_RELEASED):
                return
            for top, left, bottom, right, kind, index in reversed(self.topic_hitboxes):
                if top <= y <= bottom and left <= x <= right:
                    if kind == "topic":
                        self.topic_selected, self.topic_reference = index, 0
                        self.topic_reference_focus = False
                        self._topic_image_key = None
                    else:
                        self.topic_reference, self.topic_reference_focus = index, True
                    return
        if not self.topic_worker:
            return
        _, graph, _ = self.topic_worker.state()
        if graph is None:
            return
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_UP, curses.KEY_DOWN):
            if self.topic_reference_focus:
                count = len(graph.topics[self.topic_selected].references)
                delta = -1 if key in (curses.KEY_LEFT, curses.KEY_UP) else 1
                self.topic_reference = (self.topic_reference + delta) % count
            else:
                delta = -1 if key in (curses.KEY_LEFT, curses.KEY_UP) else 1
                self.topic_selected = (self.topic_selected + delta) % len(graph.topics)
                self.topic_reference = 0
                self._topic_image_key = None
        elif key in ("\n", "\r", curses.KEY_ENTER):
            if self.topic_reference_focus:
                self._open_topic_reference(graph)
            else:
                self.topic_reference_focus = True

    def shortcut(self, action: str, key: str | int | tuple[str, str]) -> bool:
        return key == key_for(self.settings.keybindings[action])

    def shortcut_label(self, action: str) -> str:
        return display_binding(self.settings.keybindings[action])

    def open_commands(self) -> None:
        self.shortcut_values = self.settings.keybindings
        self.shortcut_index = 0
        self.shortcut_capture = False
        self.command_editing = False
        self.command_index = 0
        self.command_error = ""
        self.modal = "commands"

    def command_options(self) -> list[tuple[str, str, str, bool]]:
        language = LANGUAGE_NAMES[self.settings.autocorrect_language]
        autocorrect = language + (" · ON" if self.autocorrect else " · off")
        can_copy = bool((self.chooser and self.recent) or (not self.chooser and self.file))
        return [
            ("new", "N", "Create a new file", True),
            ("files", "F", "Open or switch to an existing file", True),
            ("panes", "P", "Show / hide file editor", not self.chooser),
            ("autocorrect", "A", "Autocorrect: " + autocorrect, True),
            ("settings", "D", "Default path & settings", True),
            ("topic_map", "M", "Explore the graphical topic map", True),
            ("copy", "C", "Copy selected saved file", can_copy),
            ("shortcuts", "K", "Edit keyboard shortcuts", True),
            ("help", "H", "Help", True),
            ("quit", "Q", "Quit", True),
        ]

    def draw_commands(self, height: int, width: int) -> None:
        if self.command_editing:
            self.draw_shortcut_editor(height, width)
            return
        options = self.command_options()
        box_width, box_height = min(width - 4, 64), min(height, 16)
        y, x = (height - box_height) // 2, (width - box_width) // 2
        for row in range(y, y + box_height):
            self.put(row, x, " " * box_width)
        self.box(y, x, box_height, box_width, "PROGRAM MENU")
        for row, (_, key, label, enabled) in enumerate(options[:box_height - 4]):
            selected = row == self.command_index
            marker = "› " if selected else "  "
            self.put(y + 2 + row, x + 2, f"{marker}{key}  {label}",
                     "accent" if selected and enabled else "text" if enabled else "muted",
                     width=box_width - 6)
        self.put(y + box_height - 2, x + 2,
                 "↑/↓ select · Enter run action · Esc return", "muted", width=box_width - 4)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def draw_shortcut_editor(self, height: int, width: int) -> None:
        actions = list(ACTION_LABELS)
        box_width, box_height = min(width - 4, 68), min(height, 16)
        y, x = (height - box_height) // 2, (width - box_width) // 2
        for row in range(y, y + box_height):
            self.put(row, x, " " * box_width)
        self.box(y, x, box_height, box_width, "PROGRAM MENU · KEYBOARD SHORTCUTS")
        for index, action in enumerate(actions):
            selected = index == self.shortcut_index
            label = ("› " if selected else "  ") + ACTION_LABELS[action]
            self.put(y + 2 + index, x + 2, label, "accent" if selected else "text",
                     width=box_width - 18)
            binding = display_binding(self.shortcut_values[action])
            self.put(y + 2 + index, x + box_width - len(binding) - 3, binding,
                     "accent" if selected else "muted")
        prompt = ("Press a Ctrl/F key · Backspace makes it menu only" if self.shortcut_capture
                  else "↑/↓ select · Enter change · R defaults · S save")
        self.put(y + 10, x + 2, prompt, "accent" if self.shortcut_capture else "muted",
                 width=box_width - 4)
        self.put(y + 11, x + 2, self.command_error, "error", width=box_width - 4)
        self.put(y + 13, x + 2, "Esc back to program menu", "muted", width=box_width - 4)
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def handle_commands(self, key: str | int | tuple[str, str]) -> None:
        if self.command_editing:
            self.handle_shortcut_editor(key)
            return
        if key == "\x1b" or self.shortcut("commands", key):
            self.modal = None
            return
        if key in (curses.KEY_UP, curses.KEY_DOWN):
            options = self.command_options()
            delta = -1 if key == curses.KEY_UP else 1
            for _ in options:
                self.command_index = (self.command_index + delta) % len(options)
                if options[self.command_index][3]:
                    break
            return
        if key in ("\n", "\r", curses.KEY_ENTER):
            action, _, _, enabled = self.command_options()[self.command_index]
            if enabled:
                self.run_command(action)
            return
        hotkeys = {
            "n": "new", "f": "files", "m": "topic_map", "p": "panes", "a": "autocorrect",
            "d": "settings", "s": "settings", "c": "copy", "k": "shortcuts",
            "h": "help", "q": "quit",
        }
        if key in ("\x11", "\x03"):
            self.run_command("quit")
        elif isinstance(key, str) and key.lower() in hotkeys:
            self.run_command(hotkeys[key.lower()])

    def run_command(self, action: str) -> None:
        if action == "shortcuts":
            self.command_editing = True
            self.command_error = ""
        elif action == "settings":
            self.open_settings()
        elif action == "topic_map":
            self.open_topic_map()
        elif action == "help":
            self.modal = "help"
        elif action == "copy":
            self.modal = None
            self.copy_saved_file()
        elif action == "new":
            self.modal = None
            self.request("new_file")
        elif action == "files":
            self.modal = None
            self.request("open_file")
        elif action == "panes":
            if self.chooser:
                return
            self.modal = None
            if self.preview:
                self.request("hide")
            else:
                self.show_file_editor()
        elif action == "autocorrect":
            self.modal = None
            self.toggle_autocorrect()
        elif action == "quit":
            self.modal = None
            self.request("quit")

    def handle_shortcut_editor(self, key: str | int | tuple[str, str]) -> None:
        actions = list(ACTION_LABELS)
        if self.shortcut_capture:
            if key in (curses.KEY_BACKSPACE, curses.KEY_DC, "\x7f", "\b"):
                action = actions[self.shortcut_index]
                if action == "commands":
                    self.command_error = "The Program menu needs a keyboard shortcut."
                    return
                self.shortcut_values[action] = "none"
                self.shortcut_capture = False
                self.command_error = "This action is available from the program menu."
                return
            binding = binding_for_key(key)
            if binding is None:
                self.command_error = "Use an available Ctrl/F key, Backspace for menu only, or Esc."
                if key == "\x1b":
                    self.shortcut_capture = False
                    self.command_error = ""
                return
            action = actions[self.shortcut_index]
            used_by = next((other for other, value in self.shortcut_values.items()
                            if other != action and value == binding), None)
            if used_by:
                self.command_error = display_binding(binding) + " is already used by " + ACTION_LABELS[used_by] + "."
                return
            self.shortcut_values[action] = binding
            self.shortcut_capture = False
            self.command_error = ""
            return
        if key == "\x1b":
            self.command_editing = False
            self.command_error = ""
        elif key in (curses.KEY_UP, curses.KEY_DOWN):
            delta = -1 if key == curses.KEY_UP else 1
            self.shortcut_index = (self.shortcut_index + delta) % len(actions)
            self.command_error = ""
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self.shortcut_capture = True
            self.command_error = ""
        elif key in ("r", "R"):
            self.shortcut_values = dict(DEFAULT_BINDINGS)
            self.command_error = "Defaults restored in this draft. Press S to save."
        elif key in ("s", "S"):
            try:
                bindings = validate_bindings(self.shortcut_values)
                self.settings.set_keybindings(bindings)
            except (OSError, ValueError, UnicodeError) as error:
                self.command_error = str(error)
                return
            self.shortcut_values = bindings
            self.command_editing = False
            self.command_error = ""
            self.note("Shortcuts saved.")

    def draw_edit_vent(self, height: int, width: int) -> None:
        box_width, box_height = min(width - 4, 76), min(height, 18)
        y, x = (height - box_height) // 2, (width - box_width) // 2
        for row in range(y, y + box_height):
            self.put(row, x, " " * box_width)
        self.box(y, x, box_height, box_width, "EDIT RECENT VENT DETAILS")
        self.put(y + 2, x + 2, "SAVED TEXT PREVIEW · read-only", "muted",
                 width=box_width - 4)
        preview_lines, _ = wrap(self.edit_preview, box_width - 4, 0)
        visible_preview = preview_lines[-2:]
        if len(preview_lines) > 2:
            visible_preview[0] = "… " + visible_preview[0]
        for index, line in enumerate(visible_preview):
            self.put(y + 3 + index, x + 2, line, "text", width=box_width - 4)
        self.put(y + 5, x + 2, ("› " if self.edit_focus == 0 else "  ") +
                 "Short label shown in Recent vents",
                 "accent" if self.edit_focus == 0 else "text", width=box_width - 4)
        self.box(y + 6, x + 1, 3, box_width - 2, "RECENT-LIST SUMMARY")
        self.put(y + 9, x + 2, ("› " if self.edit_focus == 1 else "  ") +
                 "File name (same folder)",
                 "accent" if self.edit_focus == 1 else "text", width=box_width - 4)
        self.box(y + 10, x + 1, 3, box_width - 2, "FILE NAME")
        delete_text = ("Press Ctrl+D again to permanently delete" if self.edit_delete_armed
                       else "Ctrl+D twice  Delete this vent")
        self.put(y + 13, x + 2, ("› " if self.edit_focus == 2 else "  ") + delete_text,
                 "error" if self.edit_delete_armed or self.edit_focus == 2 else "muted",
                 width=box_width - 4)
        self.put(y + 14, x + 2, self.edit_error, "error", width=box_width - 4)
        self.put(y + 16, x + 2, "Tab next · Enter save (delete row: twice) · Esc cancel", "muted",
                 width=box_width - 4)
        # Writing an inactive field also moves the terminal cursor. Draw the
        # focused field last so the visible cursor stays where typing goes.
        fields = [(0, y + 7, self.edit_summary), (1, y + 11, self.edit_name)]
        for focus, row, editor in sorted(fields, key=lambda field: field[0] == self.edit_focus):
            self._draw_path(row, x + 3, box_width - 6, editor=editor,
                            show_cursor=self.edit_focus == focus)
        if self.edit_focus == 2:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def open_edit_vent(self) -> None:
        if not self.recent:
            self.note("No recent file selected.", error=True)
            return
        source = self.recent[self.recent_index].path
        try:
            current = revision(source)
        except (OSError, ValueError) as error:
            self.note(str(error), error=True)
            return
        existing = cached_summary(source, current) or ""
        try:
            contents = snapshot(source, current)
        except (OSError, ValueError, UnicodeError):
            preview = "Preview unavailable for this file."
        else:
            preview = " ".join((contents or "").split())
            if not preview:
                preview = "Empty file."
            elif len(preview) > 500:
                preview = "… " + preview[-498:]
        self.edit_source = source
        self.edit_revision = current
        self.edit_original_summary = existing
        self.edit_preview = preview
        self.edit_summary = Editor(existing, len(existing))
        self.edit_name = Editor(source.name, len(source.name))
        self.edit_focus = 0
        self.edit_delete_armed = False
        self.edit_error = ""
        self.modal = "edit_vent"

    def handle_edit_vent(self, key: str | int | tuple[str, str]) -> None:
        if key == "\x1b":
            self.modal = None
            self.edit_source = None
            return
        if key in ("\x11", "\x03"):
            self.modal = None
            self.edit_source = None
            self.request("quit")
            return
        if key == "\x04":
            if self.edit_delete_armed:
                self.delete_recent()
            else:
                self.edit_delete_armed = True
                self.edit_focus = 2
                self.edit_error = "Deletion armed. Ctrl+D again verifies it."
            return
        if key in ("\t", curses.KEY_BTAB):
            delta = -1 if key == curses.KEY_BTAB else 1
            self.edit_focus = (self.edit_focus + delta) % 3
            self.edit_delete_armed = False
            self.edit_error = ""
            return
        if key in ("\n", "\r", curses.KEY_ENTER):
            if self.edit_focus == 2:
                if self.edit_delete_armed:
                    self.delete_recent()
                else:
                    self.edit_delete_armed = True
                    self.edit_error = "Deletion armed. Enter again verifies it."
            else:
                self.save_vent_edits()
            return
        editor = self.edit_summary if self.edit_focus == 0 else self.edit_name
        if self.edit_focus == 2:
            return
        if isinstance(key, tuple):
            text = key[1].replace("\r", "").replace("\n", " ")
            if self.edit_focus == 0:
                text = " ".join(text.splitlines())
            editor.insert(text, paste=True)
            changed = True
        else:
            changed = self._edit(editor, key)
        if changed:
            self.edit_delete_armed = False
            self.edit_error = ""

    @staticmethod
    def _valid_filename(name: str) -> str | None:
        if not name.strip():
            return "Enter a filename."
        if (name in (".", "..") or Path(name).name != name or os.sep in name
                or (os.altsep and os.altsep in name)):
            return "Use a filename only, without a directory."
        return None

    def save_vent_edits(self) -> None:
        source, expected = self.edit_source, self.edit_revision
        if source is None or expected is None:
            self.modal = None
            return
        name = self.edit_name.text
        sentence = " ".join(self.edit_summary.text.split())
        filename_error = self._valid_filename(name)
        if filename_error:
            self.edit_focus = 1
            self.edit_error = filename_error
            return
        if sentence != self.edit_original_summary:
            if not sentence:
                self.edit_focus = 0
                self.edit_error = "Write a summary, or leave the original unchanged."
                return
            if len(sentence) > MAX_SUMMARY_CHARS:
                self.edit_focus = 0
                self.edit_error = f"Keep the summary to {MAX_SUMMARY_CHARS} characters."
                return
        was_manual = bool(manual_summary_token(source))
        target = source.with_name(name)
        if target != source and os.path.lexists(target):
            self.edit_focus = 1
            self.edit_error = "A file with that name already exists."
            return
        try:
            if revision(source) != expected:
                self.edit_error = "File changed while editing. Cancel and try again."
                return
            if target != source:
                source.rename(target)
            current = revision(target)
        except (OSError, ValueError) as error:
            self.edit_error = str(error)
            return

        active = bool(self.file and self.file.path == source.absolute())
        if active and target != source:
            self.file.path = target.absolute()
            if self.file_editor is not None:
                self.load_file_editor(keep_cursor=True)
        renamed = target != source
        summarized = sentence != self.edit_original_summary
        try:
            if sentence:
                save_summary(target, current, sentence, manual=summarized or was_manual)
        except (OSError, ValueError) as error:
            # The file rename has committed. Keep the sheet usable so the
            # summary can be retried against the new path without losing track
            # of an active destination.
            self.edit_source = target
            self.edit_revision = current
            self.edit_name = Editor(target.name, len(target.name))
            self.edit_error = (("File renamed, but summary was not saved: " if renamed else "")
                               + str(error))
            self.refresh_recent()
            if self.recent:
                self.recent_index = next((index for index, vent in enumerate(self.recent)
                                          if vent.path == target), 0)
            return
        if renamed:
            try:
                metadata_path(source).unlink(missing_ok=True)
            except OSError:
                pass  # Stale generated metadata does not affect the saved vent.
        self.modal = None
        self.edit_source = None
        self.refresh_recent()
        if self.recent:
            self.recent_index = next((index for index, vent in enumerate(self.recent)
                                      if vent.path == target), 0)
        if renamed and summarized:
            self.note("Filename and summary saved.")
        elif renamed:
            self.note("Renamed to " + name + ".")
        elif summarized:
            self.note("Manual summary saved.")
        else:
            self.note("No changes made.")

    def delete_recent(self) -> None:
        source = self.edit_source
        expected = self.edit_revision
        if source is None or expected is None:
            self.modal = None
            return
        try:
            if revision(source) != expected:
                self.edit_error = "File changed after selection. Cancel and try again."
                return
            source.unlink()
        except (OSError, ValueError) as error:
            self.edit_error = str(error)
            return

        active = bool(self.file and self.file.path == source.absolute())
        if active:
            self.file.close()
            self.file = None
            self.drop_file_buffer()
            self.saved_count = 0

        metadata_removed = True
        try:
            metadata_path(source).unlink(missing_ok=True)
        except OSError:
            metadata_removed = False

        deleted_index = self.recent_index
        name = source.name
        self.modal = None
        self.edit_source = None
        self.edit_revision = None
        self.refresh_recent()
        if self.recent:
            self.recent_index = min(deleted_index, len(self.recent) - 1)
        message = "Deleted " + name + "."
        if not metadata_removed:
            message += " Cached summary cleanup failed."
        self.note(message, error=not metadata_removed)

    def draw_directory_settings(self, height: int, width: int) -> None:
        box_width, box_height = min(width - 4, 76), min(height, 17)
        y, x = (height - box_height) // 2, (width - box_width) // 2
        for row in range(y, y + box_height):
            self.put(row, x, " " * box_width)
        self.box(y, x, box_height, box_width, "DEFAULTS & SETTINGS")
        self.put(y + 2, x + 2, ("› " if self.settings_focus == 0 else "  ") +
                 "Folder used for new files and Recent vents",
                 "accent" if self.settings_focus == 0 else "text",
                 width=box_width - 4)
        self.box(y + 3, x + 1, 3, box_width - 2, "DEFAULT FOLDER PATH")
        recent = "ON" if self.settings_show_recent else "OFF"
        self.put(y + 7, x + 2, ("› " if self.settings_focus == 1 else "  ") +
                 f"Show Recent vents when the file screen opens: {recent}",
                 "accent" if self.settings_focus == 1 else "text", width=box_width - 4)
        language = LANGUAGE_NAMES[self.settings_autocorrect_language]
        self.put(y + 8, x + 2, ("› " if self.settings_focus == 2 else "  ") +
                 f"Language used when autocorrect is enabled: {language}",
                 "accent" if self.settings_focus == 2 else "text", width=box_width - 4)
        self.put(y + 9, x + 2, ("› " if self.settings_focus == 3 else "  ") +
                 "Local Ollama model for Recent-list summaries (empty = off)",
                 "accent" if self.settings_focus == 3 else "text", width=box_width - 4)
        self.box(y + 10, x + 1, 3, box_width - 2, "LOCAL OLLAMA MODEL NAME")
        self.put(y + 13, x + 2, self.directory_error, "error", width=box_width - 4)
        self.put(y + 14, x + 2, "Tab next field · Space change option · Enter save · Esc cancel",
                 "muted", width=box_width - 4)
        self.put(y + 15, x + 2, "Summaries stay separate from vent files.",
                 "muted", width=box_width - 4)
        fields = [(0, y + 4, self.directory), (3, y + 11, self.summary_model)]
        for focus, row, editor in sorted(fields, key=lambda field: field[0] == self.settings_focus):
            self._draw_path(row, x + 3, box_width - 6, editor=editor,
                            show_cursor=self.settings_focus == focus)
        if self.settings_focus in (1, 2):
            try:
                curses.curs_set(0)
            except curses.error:
                pass

    def open_settings(self) -> None:
        value = self.settings.directory_value
        self.directory = Editor(value, len(value))
        model = self.settings.summary_model
        self.summary_model = Editor(model, len(model))
        self.settings_show_recent = self.settings.show_recent_vents
        self.settings_autocorrect_language = self.settings.autocorrect_language
        self.settings_focus = 0
        self.directory_error = ""
        self.modal = "settings"

    def handle_settings(self, key: str | int | tuple[str, str]) -> None:
        if key == "\x1b":
            self.modal = None
        elif key in ("\x11", "\x03"):
            self.modal = None
            self.request("quit")
        elif key in ("\n", "\r", curses.KEY_ENTER):
            try:
                self.settings.set_preferences(self.directory.text, self.summary_model.text,
                                              self.settings_show_recent,
                                              self.settings_autocorrect_language)
            except (OSError, ValueError, UnicodeError) as error:
                self.directory_error = str(error)
                return
            model = self.settings.summary_model
            if (self.summaries.model if self.summaries else "") != model:
                if self.summaries:
                    self.summaries.close()
                self.summaries = SummaryWorker(model) if model else None
                if self.topic_worker:
                    self.topic_worker.close()
                    self.topic_worker = None
            if self.corrector and self.corrector.language != self.settings.autocorrect_language:
                self.corrector = Autocorrect(self.settings.autocorrect_language)
            self.modal = None
            if self.chooser:
                if self.create:
                    self._default_path()
                else:
                    self._append_path()
            if self.chooser and self.settings.show_recent_vents:
                self.refresh_recent()
            elif self.chooser:
                self.recent = None
                self.recent_focus = False
            self.note("Settings saved.")
        elif key in ("\t", CTRL_TAB):
            self.settings_focus = (self.settings_focus + 1) % 4
            self.directory_error = ""
        elif self.settings_focus == 1 and key in (" ", curses.KEY_LEFT, curses.KEY_RIGHT):
            self.settings_show_recent = not self.settings_show_recent
        elif self.settings_focus == 2 and key in (" ", curses.KEY_LEFT, curses.KEY_RIGHT):
            self.settings_autocorrect_language = (
                "de" if self.settings_autocorrect_language == "en" else "en")
        elif isinstance(key, tuple):
            editor = self.directory if self.settings_focus == 0 else self.summary_model
            if self.settings_focus in (0, 3):
                editor.insert(key[1].replace("\r", "").replace("\n", ""), paste=True)
            self.directory_error = ""
        elif self.settings_focus in (0, 3) and self._edit(
                self.directory if self.settings_focus == 0 else self.summary_model, key):
            self.directory_error = ""

    def _edit(self, editor: Editor, key: str | int) -> bool:
        is_file = isinstance(editor, DocumentEditor)
        is_path = (editor is self.path or editor is self.directory or editor is self.summary_model
                   or editor is self.edit_name or editor is self.edit_summary)
        if key == curses.KEY_LEFT:
            editor.left()
        elif key == curses.KEY_RIGHT:
            editor.right()
        elif key in (curses.KEY_HOME, "\x01"):
            if is_file:
                editor.home()
            else:
                editor.cursor = 0
        elif key in (curses.KEY_END, "\x05"):
            if is_file:
                editor.end()
            else:
                editor.cursor = len(editor.text)
        elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
            editor.backspace(paired=not is_path)
        elif key == curses.KEY_DC:
            editor.delete()
        elif key == "\x17":
            editor.delete_word()
        elif key == "\x15":
            if is_file:
                editor.replace(editor.text.rfind("\n", 0, editor.cursor) + 1, editor.cursor, "")
            else:
                editor.clear()
        elif isinstance(key, str) and key.isprintable():
            if not is_path:
                editor.type_character(key)
            else:
                editor.insert(key)
        else:
            return False
        if is_file:
            editor.preferred_column = None
        return True

    def handle(self, key: str | int | tuple[str, str]) -> None:
        if key == curses.KEY_RESIZE:
            return
        if self.modal:
            if self.modal == "redo_manual_summary":
                if key in ("y", "Y"):
                    path, token = self.summary_redo
                    self.modal = None
                    if self.summaries:
                        self.summaries.submit((path,), priority=True, retry=True,
                                              force=True, replace_manual=token)
                        self.note("Reloading summary: " + path.name)
                elif key in ("n", "N", "\x1b", "\x11", "\x03"):
                    self.modal = None
                    self.note("Kept your summary.")
                return
            if self.modal == "commands":
                self.handle_commands(key)
                return
            if self.modal == "settings":
                self.handle_settings(key)
                return
            if self.modal == "edit_vent":
                self.handle_edit_vent(key)
                return
            if self.modal == "topic_map":
                self.handle_topic_map(key)
                return
            if self.modal == "help":
                if key in ("\x1b", "\n", "\r") or self.shortcut("help", key):
                    self.modal = None
                elif key in ("\x11", "\x03"):
                    self.modal = None
                    self.request("quit")
                return
            modal = self.modal
            if key in ("\x1b", "\x11", "\x03"):
                self.modal = None
                self.pending = None
            elif key in ("s", "S"):
                self.modal = None
                saved = self.save_file() if modal == "file_changes" else self.save()
                if saved:
                    self.complete_pending()
            elif key in ("d", "D"):
                if modal == "file_changes":
                    if self.pending != "reload":
                        self.drop_file_buffer()
                else:
                    self.draft.clear()
                    self.undo_correction = None
                self.modal = None
                self.complete_pending()
            return
        if key in ("\x11", "\x03"):
            self.request("quit")
            return
        if self.shortcut("commands", key):
            self.open_commands()
            return
        if self.shortcut("settings", key):
            self.open_settings()
            return
        if self.shortcut("help", key):
            self.modal = "help"
            return
        if self.shortcut("copy", key) and ((self.chooser and self.recent) or not self.chooser):
            self.copy_saved_file()
            return
        if self.shortcut("topic_map", key):
            self.open_topic_map()
            return
        if key == "\x0e":  # Ctrl+N is the conventional, fixed New-file action.
            self.request("new_file")
            return
        if self.shortcut("files", key):
            self.request("open_file")
            return
        if self.chooser:
            self.handle_chooser(key)
            return
        if key == "\x1b":
            self.save_and_open_chooser()
        elif self.shortcut("panes", key):
            if self.preview:
                self.request("hide")
            else:
                self.show_file_editor()
        elif key in ("\t", CTRL_TAB):
            self.switch_field()
        elif self.shortcut("autocorrect", key):
            self.toggle_autocorrect()
        elif key == "\x13":
            self.save_file()
        elif key == "\x12" and self.file_editor is not None:
            self.request("reload")
        elif self.file_focus:
            self.handle_file_key(key)
        elif isinstance(key, tuple):
            self.draft.insert(key[1], paste=True)
            self.undo_correction = None
            self.skip_correction_once = False
            self.note("Pasted into the draft. Press Enter when you are ready.")
        elif key == "\x1a":
            if self.undo_correction and self.undo_correction.undo(self.draft):
                self.skip_correction_once = True
                self.note("Correction undone. This draft will save exactly as it is.")
            else:
                self.note("No word correction to undo.")
            self.undo_correction = None
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self.save()
        elif key in (curses.KEY_UP, curses.KEY_DOWN):
            self.move_vertical(-1 if key == curses.KEY_UP else 1)
        elif key in (DOC_HOME, DOC_END):
            self.draft.cursor = 0 if key == DOC_HOME else len(self.draft.text)
        else:
            if isinstance(key, str) and key in " .,!?;:)" and not self.skip_correction_once:
                self.correct_at_cursor()
            if self._edit(self.draft, key) and self.error:
                self.note("Draft kept. Press Enter to try saving again.")

    def handle_file_key(self, key: str | int | tuple[str, str]) -> None:
        editor = self.file_editor
        if editor is None:
            return
        if isinstance(key, tuple):
            editor.insert(key[1], paste=True)
        elif key in ("\n", "\r", curses.KEY_ENTER):
            editor.insert("\n", paste=True)
        elif key == "\x1a":
            editor.undo()
        elif key == "\x19":
            editor.redo()
        elif key in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_PPAGE, curses.KEY_NPAGE):
            delta = {curses.KEY_UP: -1, curses.KEY_DOWN: 1,
                     curses.KEY_PPAGE: -self._file_rows, curses.KEY_NPAGE: self._file_rows}[key]
            editor.move_rows(delta, self._file_width)
        elif key in (DOC_HOME, DOC_END):
            editor.cursor = 0 if key == DOC_HOME else len(editor.text)
            editor.preferred_column = None
        elif isinstance(key, int) and key > 0 and curses.keyname(key) in (b"kHOM5", b"kEND5"):
            editor.cursor = 0 if curses.keyname(key) == b"kHOM5" else len(editor.text)
            editor.preferred_column = None
        else:
            self._edit(editor, key)

    @property
    def file_dirty(self) -> bool:
        return bool(self.file_editor is not None and self.document is not None
                    and (self.file_editor.text != self.document.text or self.file_sync_pending))

    def drop_file_buffer(self) -> None:
        self.document = None
        self.file_editor = None
        self.file_focus = False
        self.file_conflict = False
        self.file_sync_pending = False

    def load_file_editor(self, *, reopen: bool = False, keep_cursor: bool = False) -> bool:
        if self.file is None:
            return False
        try:
            if reopen:
                self.file.reopen()
            document = self.file.load_document()
        except (OSError, ValueError) as error:
            self.note(str(error), error=True)
            self.file_conflict = True
            return False
        cursor = min(self.file_editor.cursor, len(document.text)) if keep_cursor and self.file_editor else len(document.text)
        self.document = document
        self.file_editor = DocumentEditor(document.text, cursor)
        self.file_conflict = False
        self.file_sync_pending = False
        return True

    def show_file_editor(self) -> None:
        if self.file_editor is not None or self.load_file_editor():
            self.preview = True
            self.file_focus = True
            self.note("Saved-file editor active. Ctrl+S saves; Tab returns to the thought field.")

    def switch_field(self) -> None:
        if not self.file_focus and self.file_editor is None and not self.load_file_editor():
            return
        self.file_focus = not self.file_focus
        self.note("Saved-file editor active. Ctrl+S saves." if self.file_focus else
                  "Thought field active. Enter appends it to the file and clears the field.")

    def refresh_file_editor(self) -> None:
        if self.file is None:
            return
        if self.document is None:
            self.load_file_editor()
            return
        try:
            changed = self.file.state() != self.document.revision[0]
        except OSError:
            if self.file_dirty:
                self.file_conflict = True
            else:
                self.load_file_editor(reopen=True, keep_cursor=True)
            return
        if changed:
            if self.file_dirty:
                self.file_conflict = True
            else:
                self.load_file_editor(keep_cursor=True)

    def save_file(self) -> bool:
        if self.file is None or self.file_editor is None or self.document is None:
            self.note(self.shortcut_label("panes") + " opens the file editor.")
            return True
        if not self.file_dirty:
            self.refresh_file_editor()
            self.note("No unsaved file changes." if not self.file_conflict else "File could not be reloaded; buffer kept.",
                      error=self.file_conflict)
            return not self.file_conflict
        try:
            result = self.file.save_document(self.file_editor.text, self.document)
        except (OSError, ValueError) as error:
            self.file_focus = True
            try:
                self.file_conflict = self.file.state() != self.document.revision[0]
            except OSError:
                self.file_conflict = True
            self.note(str(error) + " Edits kept.", error=True)
            return False
        self.document = result.document
        self.file_conflict = False
        self.file_sync_pending = not result.directory_synced
        if self.file_sync_pending:
            self.note("Edits written, but directory sync failed. Ctrl+S to retry.", error=True)
            return False
        self.note("File changes saved.")
        self.queue_summary()
        return True

    def move_vertical(self, direction: int) -> None:
        # Mirror the draft panel's inner width for responsive cursor movement.
        _, width = self.screen.getmaxyx()
        inner = ((width - 5) // 2 - 4) if self.preview and width >= 92 else width - 8
        _, (row, column) = wrap(self.draft.text, inner, self.draft.cursor)
        target = row + direction
        _, positions = layout(self.draft.text, inner)
        candidates = [(abs(col - column), index) for index, (r, col) in positions.items() if r == target]
        if candidates:
            self.draft.cursor = min(candidates)[1]

    def toggle_autocorrect(self) -> None:
        try:
            language = self.settings.autocorrect_language
            if self.corrector is None or self.corrector.language != language:
                self.corrector = Autocorrect(language)
            self.autocorrect = not self.autocorrect
            name = LANGUAGE_NAMES[language]
            self.note(name + " autocorrect " + (
                "on. Ctrl+Z undoes the last correction." if self.autocorrect else "off."))
        except (OSError, ValueError):
            self.note("Autocorrect data is unavailable. Reinstall Venting.", error=True)

    def correct_at_cursor(self) -> None:
        if self.autocorrect and self.corrector:
            changes = self.corrector.at_cursor(self.draft)
            if changes:
                self.undo_correction = changes[-1]
                self.note("Word corrected. Ctrl+Z to undo.")

    def save(self) -> bool:
        if not self.draft.text.strip():
            self.note("No text to save.")
            return not self.draft.text  # An empty draft needs no saving.
        assert self.file is not None
        if self.file_dirty and not self.save_file():
            return False
        if self.autocorrect and self.corrector and not self.skip_correction_once:
            corrected, changes = self.corrector.correct(self.draft.text)
            if changes:
                self.draft.text = corrected
                self.draft.cursor = len(corrected)
                self.undo_correction = changes[-1]
        try:
            self.file.append(self.draft.text)
        except (OSError, ValueError) as error:
            self.note(str(error) + " Draft kept.", error=True)
            return False
        self.draft.clear()
        self.undo_correction = None
        self.skip_correction_once = False
        self.saved_count += 1
        if self.file_editor is not None:
            self.refresh_file_editor()
            if self.file_editor and not self.file_focus:
                self.file_editor.cursor = len(self.file_editor.text)
        self.note("Thought appended to the file.")
        self.queue_summary()
        return True

    def queue_summary(self) -> None:
        if self.summaries and self.file:
            self.summaries.submit((self.file.path,), priority=True)

    def save_and_open_chooser(self) -> None:
        if self.file_dirty and not self.save_file():
            return
        if self.draft.text and not self.save():
            return
        self.request("new_file")

    def request(self, action: str) -> None:
        self.pending = action
        if self.file_dirty:
            self.modal = "file_changes"
        elif action == "quit" and self.draft.text:
            self.modal = "draft"
        else:
            self.complete_pending()

    def complete_pending(self) -> None:
        action = self.pending
        if action == "quit" and self.draft.text:
            self.modal = "draft"
            return
        self.pending = None
        if action == "quit":
            self.running = False
        elif action == "hide":
            self.preview = False
            self.drop_file_buffer()
            self.note("File editor hidden.")
        elif action == "reload":
            if self.load_file_editor(reopen=True, keep_cursor=True):
                self.note("File reloaded.")
        elif action == "topic_reference" and self.pending_reference:
            path, excerpt, offset = self.pending_reference
            self.pending_reference = None
            try:
                self.open_path(str(path), create=False, guess_extension=False)
                self.preview = True
                if self.load_file_editor() and self.file_editor:
                    first_word = excerpt.split()[0] if excerpt.split() else ""
                    position = (offset if first_word and
                                self.file_editor.text[offset:offset + len(first_word)].casefold()
                                == first_word.casefold() else
                                self.file_editor.text.casefold().find(excerpt.casefold()))
                    if position >= 0:
                        self.file_editor.cursor = position
                self.file_focus = True
                self.note("Opened topic reference: " + path.name)
            except (OSError, ValueError) as error:
                self.note("Could not open topic reference: " + str(error), error=True)
        elif action in ("new_file", "open_file", "file"):
            self.chooser = True
            self.file_focus = False
            self.create = action != "open_file"
            if self.create:
                self._default_path()
            else:
                self._append_path()
            self.note("")
            self.prepare_default_directory()

    def handle_chooser(self, key: str | int | tuple[str, str]) -> None:
        if self.recent_focus:
            self.handle_recent(key)
        elif key == "\t":
            if self.recent is None:
                self.refresh_recent()
            self.recent_focus = True
            self.selection = -1
        elif isinstance(key, tuple):
            self.path.insert(key[1].replace("\r", "").replace("\n", ""), paste=True)
            self.selection = -1
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT):
            self.create = not self.create
            self.selection = -1
            if self.create:
                self._default_path()
            else:
                self._append_path()
            self.note("")
        elif key == "\x1b":
            if self.file:
                self.chooser = False
                self.note("Back to the thought field.")
        elif key in (curses.KEY_UP, curses.KEY_DOWN):
            self._entries()
            if self.entries:
                delta = -1 if key == curses.KEY_UP else 1
                if self.selection < 0:
                    self.selection = 0 if delta > 0 else len(self.entries) - 1
                else:
                    self.selection = (self.selection + delta) % len(self.entries)
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self._entries()
            value = self.path.text
            if self.selection >= 0:
                value = str(self.entries[self.selection])
            try:
                expanded = self.picker_path(value)
                if not value.strip():
                    raise ValueError("Choose a file path first.")
                if expanded.is_dir():
                    value = str(expanded) + os.sep
                    self.path = Editor(value, len(value))
                    self.selection = -1
                    self.note("")
                    return
                self.open_path(str(expanded), create=self.create, guess_extension=self.selection < 0)
            except FileExistsError:
                self.note("That file already exists. " + self.shortcut_label("files") +
                          " switches to Open existing.", error=True)
            except FileNotFoundError:
                self.note("Path not found. Choose an existing folder or file.", error=True)
            except (OSError, ValueError) as error:
                self.note(str(error), error=True)
        elif self._edit(self.path, key):
            self.selection = -1
            self.note("")
