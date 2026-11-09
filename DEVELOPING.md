# Developing Venting

Python 3.10+; standard library only. Run from the repository root with
`python3 -m venting` or `./run`. Keep the bundled English dictionary in the package.

## Project layout

| File | Responsibility |
| --- | --- |
| `venting/__main__.py` | CLI arguments, terminal checks, curses lifecycle |
| `venting/app.py` | File picker, writer, split panes, keys, modal transitions |
| `venting/keyboard.py` | Terminal reporting modes, CSI-u and modifyOtherKeys decoding |
| `venting/settings.py` | Default-directory paths, JSON preferences, atomic settings saves |
| `venting/shortcuts.py` | Global action bindings, safe key validation, and display labels |
| `venting/recent.py` | Uncapped directory listing ordered by file modification time |
| `venting/summaries.py` | Local Ollama client, background queue, and revision-checked metadata |
| `venting/clipboard.py` | Read and copy the saved file via native helpers or OSC 52 |
| `venting/editor.py` | Text editing, pairing, common Unicode cluster and cell layout |
| `venting/document.py` | Full-file editor buffer, wrapped rows, delta-based undo/redo |
| `venting/storage.py` | Append/rollback, full snapshots, conflict checks, atomic file saves |
| `venting/autocorrect.py` | Conservative English/German corrections and correction undo |
| `venting/data/` | Bundled frequency dictionary and upstream licenses |
| `tests/` | Unit tests plus real pseudo-terminal integration tests |

The curses interface is intentionally separate from file operations and editor
state. Most behavior can be tested without a terminal. `App.handle()` accepts
decoded curses keys; the PTY tests exercise the actual executable and paste
protocol in addition to those state transitions.

## Validate

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q venting
python3 -m venting --help
```

The terminal tests run on POSIX with `TERM=xterm-256color`, using a temporary
directory and a pseudo-terminal. They do not modify your personal files.

Optional packaging check, after installing development tools in a venv:

```sh
python3 -m pip wheel --no-deps --no-build-isolation . -w dist
```

`pyproject.toml` defines the `venting` console command. Runtime dependencies are
empty. Setuptools is a build-time tool only. The bundled dictionary means
autocorrect also works in a fresh install without downloads or system word lists.

## Behavior to preserve

- Enter in the venting pane appends and syncs the current thought immediately.
  Only a successful save clears the draft. Enter in the file editor inserts a
  newline; Ctrl+S saves the full edited file without clearing it.
- The append path never truncates. Full-file saves are intentional editor actions
  and must compare the loaded revision before replacing the original atomically.
- Start with only the venting field visible. Tab swaps the visible field
  while preserving both buffers; with Ctrl+P on, it only changes focus. Ctrl+P shows
  both fields side by side when wide, stacked when narrow. Returning via Ctrl+P to
  single-field venting drops the file buffer and undo history after guarding
  unsaved edits. Guard edits before switching files, reloading, or quitting.
  Do not recall released thoughts with arrows in the venting pane.
- Tab switches fields instead of inserting indentation, and switches between
  the path and recent list in the picker. Preserve pasted tabs as spaces. Decode modern keyboard
  reports and affected Ctrl shortcuts, restoring prior modes when exiting.
- Do not send thoughts to an external spellchecker or service. Do not add
  network calls, telemetry, input history, or persistent drafts implicitly.
- Typed opening brackets and double quotes pair; pasting does not pair.
- Bracketed paste never submits embedded newlines. Ctrl+C and Ctrl+Q must
  preserve the normal save/discard/cancel path for an unfinished thought.
- Autocorrect remains toggleable, offline, and limited to English and German.
  Avoid changing valid words into other valid words, especially ambiguous
  German grammar pairs. Preserve the correction undo path.
- Errors and exit messages must not echo a draft or saved file content.
- Settings edits the default directory, startup recent-list visibility,
  autocorrect language, and local summary model. Keep the active file, both
  buffers, cursor, and undo history
  intact. Save preferences atomically and retain the old values if saving fails.
  Relative directory settings resolve beside the config file; relative picker
  filenames resolve inside that directory.
- Ctrl+N opens Create new; the Files binding opens Open existing. Both protect
  file edits while retaining venting drafts. Settings is available from both the
  file screen and the writer. Source checkouts
  use `venting.json` and `vents/` beside `run`; packaged installs use XDG config
  and data directories. Never package personal preferences or journal files.
- Recent vents is embedded in the file screen and lists regular visible files
  directly in the configured directory, independent of the path-completion
  limit. Tab changes focus or reveals a list hidden by the saved preference.
  Each row uses its summary as the label;
  keep the selected filename available in the status line. E opens one Edit vent
  sheet with live summary and filename fields plus verified deletion; do not
  split these actions back into nested menus.
  Renaming cannot accept a directory or replace another file; deletion must be
  confirmed and must reject a revision changed since confirmation. Keep the
  active `TextFile` path and cached summary usable when its file is renamed, and
  close an active destination safely when its vent is deleted.
  Opening a recent file uses the exact selected name and retains any draft.
- Summary generation is opt-in and only connects directly to loopback. The worker
  reads saved text and publishes revision-checked metadata outside the original
  file. A summary failure must never affect a journal save. The HTTP tests use a
  fake loopback Ollama server; no real model is required to run the test suite.
  S in the focused recent list submits only non-empty files without a current
  cached summary; the worker still rechecks revisions and cache state. Render
  summaries in the recent selector and file-editor pane, never in the venting
  input pane. R must force-regenerate the selected summary even when its current
  revision already has a valid cached result. Do not send content too thin to
  summarize meaningfully. Treat journal text as untrusted model input and reject
  placeholder, prompt-echo, or instruction-like generated labels.
- The Copy command copies the saved file only, without changing editor state, appending a
  summary, or sending anything to a recipient.
- Keep the normal footer contextual and short. Secondary actions belong in the
  full program menu. Global bindings are validated and saved atomically; never allow
  them to shadow fixed editing, save, quit, or deletion controls.
- Keep guidance/status text visually separated from shortcut footers. Field
  titles and helper text should describe what is edited and what the action does,
  not merely repeat an internal noun such as "path" or "summary".

## Limits and useful extension points

Unicode layout handles combining accents, wide characters, common joined
emoji, and flag pairs. Complex Unicode grapheme rules and emoji widths can vary
by terminal; replacing these helpers with a full grapheme/wcwidth implementation
would be a localized future change.

English autocorrect uses common typo overrides plus frequency-ranked candidates
within one edit. A candidate must be frequent and at least five times more
common than its next competitor. German uses curated, unambiguous typo
overrides rather than guessing from sentence context. Both favor predictable
behavior over aggressive repair. Adding a personal dictionary would fit in the
autocorrect module without changing storage.

File locks are advisory. Failure rollback is safe for writers honoring the
same lock. POSIX regular files are the supported destination. Existing files
are validated as UTF-8 when opened; an external writer is responsible for
keeping the file valid UTF-8 afterward. The file-editor pane loads the whole file up to
16 MiB; it must never save only a truncated tail. CRLF and UTF-8 BOM formatting
are retained by the editor; mixed/CR-only endings normalize to LF. Appends use LF.

`Document` contains normalized text, newline/BOM metadata, and a revision made
from device/inode/size/mtime/ctime plus a SHA-256 digest. Loading and saving use
advisory file locks. Full-file saves check the revision before and after staging
a replacement, sync its bytes, replace the real target (preserving symlinks),
then sync the parent directory. The live descriptor moves to the new inode so
later thought submissions append to the new file. A directory-sync failure
after commit is reported distinctly and leaves the editor marked for retry.

Outside changes refresh a clean editor. A dirty editor retains its text and
reports a conflict; Ctrl+R uses the same save/discard/cancel guard. Submitting a
thought saves pending file edits before appending, then refreshes the clean
editor to avoid dropping the appended thought in a future full-file save.

The revision check cannot eliminate the final check/replace race with another
writer that ignores locks. A crash during staging may leave a temporary file;
handled failures remove it. Atomic replacement changes the inode, so other
hard links keep their old contents. These are standard atomic-save tradeoffs.
Extended-attribute or permission-copy errors abort before replacing the file.

The startup picker validates the entire existing file once, in small chunks.
File reads and writes run on the UI thread; an unusually slow or disconnected
filesystem can pause the UI. A future worker-based I/O implementation should
keep the current save-before-clear ordering and draft retention on errors.
