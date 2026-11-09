# Venting

Venting is a terminal app for writing and editing text files. Press **Enter**
to append the draft. The input clears after the write succeeds.

Create a new file or append to an existing one. Keep your saved thoughts hidden,
or open the whole file in an editable pane. Offline English and German autocorrect and
local AI summaries are optional. No Python package dependencies.

## Run

Requires **Python 3.10+** with curses on Linux or macOS. Tested on Linux.
From the extracted project directory:

```sh
python3 -m venting
```

Or launch the `run` script by its full path from any directory. The picker starts
in your configured default directory: initially **`vents/` beside `run`**.
Choose **Create new** with Ctrl+N or **Open existing** with Ctrl+F. Left/Right
also changes the action while the file-path field is active.
Type a path, including paths with spaces or `~`, or use the directory suggestions.
↑/↓ select a matching path and Enter opens it. **Tab** switches between the
path field and recent vents.
New-file mode never overwrites an existing file. `journal` becomes `journal.txt`;
names with extensions such as `journal.md` and `journal.json` are kept as typed.
The extension is a filename choice; Venting reads and writes UTF-8 text.
In append mode a name without an extension opens the exact file if it exists,
otherwise it can match the `.txt` version.
Switching files keeps an unfinished thought in the input so you can send it to
the new destination. Cancelling the picker returns to the original file.
From the thought or saved-file editor, **Ctrl+F** opens the existing-file screen;
Ctrl+N starts a new file. **Ctrl+O** opens the full program menu.

## Recent vents and clipboard

Recent vents is part of the file screen and lists every non-hidden
regular file directly in the default directory, regardless of extension, newest
modification first. Press **Tab** to move focus between the path field and recent
vents. Use **↑/↓**, **Page Up/Down**, or **Home/End** to move; there is no list
limit. Each row shows the file's short summary instead of its filename; the
selected filename appears in the status line. **Enter** opens the selected file
for appending. **E** opens one edit sheet with a short preview of the latest
saved text plus the summary and filename as editable fields. Tab moves between
the fields and delete action; Enter saves both fields. **Ctrl+D** twice permanently deletes the selected vent from
that same sheet. Deletion verifies that the file has not changed and removes
its cached summary. Renaming accepts a filename only and never overwrites an
existing entry. **R** refreshes the list and force-redoes that file's summary
with Ollama; **S** in the list queues every non-empty vent without a current
summary. **Tab** or **Esc** returns focus to the path field. Settings can hide
recents on startup; Tab reveals them when needed.

Choose **Copy selected saved file** from the **Ctrl+O program menu** to copy the entire selected or
open saved file as text. This excludes the draft, unsaved edits, and summary
metadata. Venting uses `wl-copy`, `xclip`, or `pbcopy` when available; otherwise
it requests a clipboard write through the terminal (OSC 52, supported by Kitty).
Terminal copying depends on terminal settings. For files over 48,000 bytes, use
one of the clipboard commands; copying supports files up to 16 MiB.

## Local AI summaries

Summaries are off until enabled. Install [Ollama](https://ollama.com/download)
and run its local server with cloud features disabled:

```sh
env OLLAMA_NO_CLOUD=1 ollama serve
```

If Ollama is already running as a service, set `OLLAMA_NO_CLOUD=1` on that
service and restart it instead. In a second terminal:

```sh
ollama pull gemma3:1b
./run --summaries
```

The model download is about 806 MB. If you use the fish alias, run
`venting --summaries`. To enable summaries on every launch, open the **Ctrl+O
program menu**, choose **Default path & settings**, enter `gemma3:1b` as the local summary model,
and save. You can also set
`"summary_model": "gemma3:1b"` directly in `venting.json` (or the settings file
for your installation). Use an installed local GGUF model; leave the model
empty and omit `--summaries` to disable generation.

Venting requests one very short sentence per file from Ollama on
`127.0.0.1:11434`. The prompt favors reflective, in-progress labels that name
the central topic and, when supported, what the writer is working through. The
journal is sent as an untrusted JSON string rather than as instructions.
Generation runs in the background after saves. Showing recent vents on the start
screen also queues existing files that need summaries. If the app closes before
generation finishes, opening the start screen again resumes work on missing or
outdated summaries. For
files larger than 12,000 bytes, the model receives the beginning and end.

Summaries are kept in `.venting-summaries/` beside the files and are reused until
the file changes. They are generated text and can be inaccurate. Metadata is
separate from the original file and can be deleted to clear the cache. Cached
summaries remain visible with generation off. A summary is shown for the selected
file on the Recent vents screen and at the top of the file-editor pane; it is
never placed in the venting input pane. If Ollama is unavailable, writing and
saving still work; restart Ollama and press **R** in Recent vents. R also replaces
an existing cached summary, so it can be regenerated whenever it is unhelpful.
Files with too little meaningful text are not sent for generation. Placeholder,
prompt-echo, and instruction-like model responses are rejected instead of being
cached; the original vent is never modified by summary generation.

## Settings

Press **Ctrl+O**, choose **Default path & settings** (or press **D**) from the
file screen or while writing. The first editable field is the default directory.
**Tab** moves between it, the startup recent-vents toggle, the English/German
autocorrect language, and the local Ollama model. **Space** changes a selected
toggle or language; **Enter** saves all preferences and
**Esc** cancels. Missing directories are created. Your current file and unfinished
thought stay in place; a new directory is used the next time you create or choose
a file.

When running this extracted project, the preference is saved in **`venting.json`
beside `run`**. It persists across restarts and works when launched through a fish
alias from another directory. Relative directories such as `vents` are relative
to that settings file; absolute paths and `~/...` work too. You can also copy
`venting.example.json` to `venting.json` and edit it directly:

```json
{
  "default_directory": "vents",
  "summary_model": "",
  "show_recent_vents": true,
  "autocorrect_language": "en",
  "keybindings": {
    "commands": "ctrl+o",
    "files": "ctrl+f",
    "panes": "ctrl+p",
    "autocorrect": "ctrl+t",
    "settings": "none",
    "copy": "none",
    "help": "f1"
  }
}
```

## Commands and shortcuts

**Ctrl+O** opens the full program menu from either the file screen or writer.
Use ↑/↓ and Enter, or the letter shown beside an action. It includes creating
and opening files, recent vents, the saved-file editor, autocorrect, settings,
copying, shortcut editing, help, and quit. Press **K** in that menu to edit
global shortcuts in place. Choose a binding with ↑/↓, press Enter, then type its
new Ctrl or function key. Backspace makes a secondary action available through
the menu only; the program menu itself must keep a shortcut. **S** saves, **R**
restores the defaults in the draft, and Esc returns to
the program menu. Venting rejects duplicate bindings and control keys already
needed for editing, saving, quitting, or verified deletion.

The defaults use Ctrl+O for the program menu, Ctrl+F for existing files, Ctrl+P
for the saved-file editor, Ctrl+T for autocorrect, and F1 for Help. Settings and
copy default to menu-only instead of occupying arbitrary function keys. Function
keys remain available as custom bindings. Tab and text-editor controls are
contextual and are not globally rebindable.

In the file picker, a relative filename such as `today.txt` is placed inside the
default directory. An absolute file path overrides it. Explicit command-line
file arguments still resolve relative to the shell's current directory.

With a packaged installation such as pipx, settings use
`~/.config/venting/config.json` and the initial directory is
`~/.local/share/venting/vents`, respecting `XDG_CONFIG_HOME` and `XDG_DATA_HOME`.
Use `--config /path/to/settings.json` to choose another settings file. Settings
contain only preferences; journal text stays in your chosen files. Keep your
`venting.json` and `vents/` directory when updating the project; the ZIP includes
an example configuration instead of replacing your saved preferences.

To install a `venting` command, use an isolated environment such as pipx:

```sh
pipx install .
venting
```

If you are developing it, use an editable install in a virtual environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/venting
```

## Direct file opening

```sh
# Create a file. Fails if it already exists.
python3 -m venting --new ~/thoughts.txt

# Append to an existing file.
python3 -m venting ~/thoughts.txt

# Show the file editor and enable the configured autocorrect language from the start.
python3 -m venting --show --autocorrect ~/thoughts.txt

# Also available: --no-color, --help, --version
```

## Keys

| Key | Action |
| --- | --- |
| Enter in venting pane | Append the current thought, then clear the input |
| Enter in file editor | Insert a newline; retain the file buffer |
| Ctrl+P | Toggle both fields on screen; focus the file editor when opening |
| Tab | Switch fields; in single-field mode, swap the visible field |
| Escape in file editor | Return to the venting pane |
| Ctrl+S | Save file edits without clearing the editor |
| Ctrl+R | Reload the file, protecting unsaved edits |
| Ctrl+N | Create a new file |
| Ctrl+F | Open or switch to an existing file |
| Ctrl+O | Open the full program menu; K edits global bindings in place |
| Ctrl+T | Toggle the configured English/German autocorrect |
| Tab on the file screen | Switch between the path field and recent vents |
| E with recent vents focused | Edit summary and filename in one sheet |
| Ctrl+D twice in Edit vent | Verify and permanently delete the selected vent |
| R with recent vents focused | Redo the selected summary with Ollama |
| S with recent vents focused | Summarize every vent missing a current summary |
| Copy in the program menu | Copy the selected saved file as text |
| Ctrl+Z in venting pane | Undo the last autocorrection |
| Ctrl+Z / Ctrl+Y in file editor | Undo / redo edits |
| Help command (F1 by default) | Help |
| PgUp / PgDn in file editor | Move by a page |
| ← / → | Move through the current draft |
| ↑ / ↓ | Move through wrapped draft lines |
| Home / End / Ctrl+A / Ctrl+E | Start/end of draft; start/end of line in file editor |
| Ctrl+Home / Ctrl+End in file editor | Start/end of the whole file |
| Backspace / Delete | Delete before / after the cursor |
| Ctrl+W | Delete the previous word |
| Ctrl+U | Clear the venting draft; delete to line start in file editor |
| Ctrl+Q / Ctrl+C | Quit; protect unsaved file edits and venting draft |

Venting starts in **single-field mode**. Tab switches between a full-window
venting field and a full-window file editor. Only the active field is displayed;
switching keeps your draft, file edits, cursor, and undo history.

Ctrl+P enables **both fields** and focuses the file editor, initially at the end of
the file. Both fields appear side by side on a wide terminal and stacked on a
narrower one. Tab changes focus without changing that layout. Ctrl+P again
returns to single-field venting, guarding unsaved file edits first. The minimum
terminal size is 48 × 18.

Tab switches fields instead of inserting indentation in the file editor. On the
file screen it switches between the path and recent list; tabs in pasted text
become spaces. Ctrl+Tab remains a compatibility shortcut when delivered by the
terminal. Modern keyboard reports are supported and reporting modes are restored
on exit.

## Editing and saving the file

Ctrl+P loads the **entire file**, not a truncated preview. Move the cursor with the
arrow, Home/End, and page keys; edit existing text, add lines, or delete text.
Ctrl+S writes the changes back to the same file. It preserves the exact edited
text, including an intentionally missing final newline or an empty file.
Undo/redo works in the file pane, including across saves, with up to 1,000
editing steps. Ctrl+P returning to single-field venting clears the file buffer and
undo history after handling unsaved edits. Tab switching retains both.

The `*` in the file-pane title means there are unsaved changes. Turning both fields off,
switching files, reloading, or quitting offers **save / discard / cancel**.
A failed save keeps the buffer and leaves the file unchanged before commit.

Submitting a thought from the venting pane saves any pending file edits first,
then appends the thought. If either save fails, the venting draft is kept. This
prevents a later editor save from overwriting a newly appended thought.

Changes made outside Venting refresh automatically when the file buffer is clean.
If you have unsaved edits, Venting keeps them and refuses to overwrite a changed
file. Ctrl+R lets you explicitly discard those edits and load the current disk
version; cancel keeps your buffer. File editing supports UTF-8 files up to
16 MiB. Larger files can still receive thoughts through the venting pane.

## Pairing and autocorrect

Typing `(`, `[`, `{`, or `"` inserts its matching closing character and leaves
the cursor between the two. Typing a closing character already under the cursor
moves past it. Backspace inside an empty pair deletes both characters. Pasted
text is inserted as supplied, without adding bracket pairs.

Autocorrect for the **venting input** is off by default and entirely offline.
Choose English or German in **Ctrl+O → Default path & settings**, then Ctrl+T
turns it on. Common typos are corrected at a word boundary; Enter also checks
the draft before saving it. English uses a bundled frequency dictionary plus
known errors. German deliberately uses a smaller known-error list so ambiguous
pairs such as `das`/`dass` and `seit`/`seid` are left alone. Both modes preserve
uncertain spellings, names, acronyms, complete URLs, and code-like tokens. This
is a spelling aid, not a grammar or context checker.

Ctrl+Z restores the most recent corrected word if you have not edited that
word again. After an undo, further correction is paused for that draft, including
its final save. This lets you submit an intentional spelling unchanged. Changes
already saved to disk are not undone by Ctrl+Z in the venting pane. In the file
editor, Ctrl+Z and Ctrl+Y provide normal editing undo and redo; saving that pane
does not apply bulk autocorrection to existing text.

In terminals supporting bracketed paste, pasted newlines stay in the draft;
press Enter yourself to submit the whole pasted thought. Tabs become spaces.
Empty or whitespace-only submissions are ignored. Normal Enter submits; there
is no separate save action for the venting pane. Enter inserts ordinary newlines
in the file editor, where Ctrl+S saves.

## Files and privacy

- Files are ordinary **UTF-8 plain text**. Each submission ends with a newline;
  a missing newline on existing content is added before the next thought.
- Each submission is written immediately and flushed to disk with `fsync`
  before the draft is cleared. A failed save keeps the draft visible for retry.
- New files use owner-only permissions (`0600`), subject to your operating
  system. Existing permissions are preserved.
- File editing saves through a temporary file in the destination directory,
  syncs it, and atomically replaces the original. Existing permissions, ownership,
  and extended attributes are retained. Symlinks continue pointing to their
  edited target. Uniform CRLF line endings and a UTF-8 BOM are preserved by the
  editor; mixed line endings normalize to LF. Venting appends use LF.
- Venting does not make network requests unless summaries are enabled. Its
  summary client connects directly to the local Ollama server without a proxy.
  Venting does not keep an input history or write logs or automatic draft
  backups. Pane and autocorrect choices last for this run.
- The hidden pane keeps saved content out of the display; files remain plain
  text. Unsubmitted drafts live only in memory and are lost if the process or
  computer is forcibly stopped.
- Multiple Venting processes coordinate appends with advisory file locks. Avoid
  simultaneously editing the file in software that ignores those locks. If an
  editor replaces or removes the open file, Venting protects unsaved changes.
  Atomic replacement requires write permission on the file's parent directory.

## Fish alias

From the extracted `venting` directory, run once:

```fish
alias --save venting "python3 '$PWD/run'"
```

You can then run `venting` from any directory. Keep this project folder in the
same location. An older `letgo` alias continues to refer to the older project
until you remove or update it.

## Working on it

This is a regular Python project with separate UI, editor, storage, and
autocorrect modules. See [DEVELOPING.md](DEVELOPING.md) for the layout, tests,
and design choices. No internet access is needed to run the app or its tests.
Contributions are covered by [CONTRIBUTING.md](CONTRIBUTING.md); please read its
privacy rules before attaching diagnostics. Release maintainers can follow
[docs/GITHUB_RELEASE.md](docs/GITHUB_RELEASE.md) and
[docs/RELEASING.md](docs/RELEASING.md).

```sh
python3 -m unittest discover -s tests -v
```

Code: MIT license. Dictionary provenance and included notices:
[THIRD_PARTY.md](THIRD_PARTY.md).
