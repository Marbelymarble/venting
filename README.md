# Venting

> **AI development disclosure:** This app was built entirely using AI coding.

## Why this exists

Sometimes you just want to dump a thought somewhere and move on. Venting makes
that quick: type, press **Enter**, and the thought is saved to a plain-text file
while the input clears for the next one.

It works for complaints, rough ideas, notes, or anything else that does not need
to become a polished document. No account, feed, or cloud is required.

## Quick start

Venting requires Python 3.10+ with curses on Linux or macOS.

```sh
python3 -m venting
```

You can also run `./run` from the project directory. Choose **Create new** or
**Open existing**, select a text file, and start typing. New vents go in `vents/`
by default.

To install a `venting` command with pipx:

```sh
pipx install .
venting
```

Open a file directly when you already know where you want to write:

```sh
venting --new ~/thoughts.txt   # create a new file
venting ~/thoughts.txt         # append to an existing file
```

## What it does

- Appends each submitted thought immediately to an ordinary UTF-8 text file.
- Keeps saved text out of sight while you continue writing.
- Includes a full-file editor when you want to review or revise.
- Offers optional offline English and German autocorrect.
- Lists recent vents and lets you rename, edit, copy, or delete them.
- Can generate short summaries with a local Ollama model.
- Builds an interactive, graphical topic map from recent vents in Kitty.
- Has no Python package dependencies.

## Essential keys

| Key | Action |
| --- | --- |
| Enter | Save the current thought and clear the input |
| Ctrl+O | Open the program menu |
| Ctrl+G | Open or close the graphical topic map |
| Ctrl+N / Ctrl+F | Create a file / open a file |
| Ctrl+P | Show or hide the full-file editor |
| Ctrl+S | Save edits in the file editor |
| Ctrl+T | Toggle autocorrect |
| Tab | Switch between the visible fields or lists |
| Esc | Save and return to file selection |
| F1 | Open help |
| Ctrl+Q / Ctrl+C | Quit |

The program menu also provides settings, recent vents, copying, shortcut
customization, and the saved-file editor.

## Graphical topic map (Kitty)

With a local Ollama model configured, press **Ctrl+G** from either the file
browser or venting view (or use **Ctrl+O → Topic map**). Venting asks
the local model to extract concrete topics from each vent, then combines matching
topics across vents while keeping their source passages. Topics that occur once
are included. Bubble area reflects the number of distinct supporting passages;
duplicate and overlapping quotes count once. The reference panel shows passage
and vent counts. Topic extraction still depends on what the local model finds.
Venting renders
the result as a real raster graph through Kitty's graphics protocol. Stronger
relationships have heavier, brighter edges. Click a topic to see exact excerpts
from the source texts; click a source and press **Enter** to open that passage in
the saved-file editor.

Press **T** to cycle through the last 7, 30, or 90 days and all time. The choice
is remembered. **R** rebuilds the map, Tab switches between topics and sources,
and the arrow keys provide a mouse-free alternative. Ctrl+G or Esc closes the
map. The shortcut can be changed in the keyboard-shortcut editor. Outside
Kitty, the topic
and reference browser remains available but the graphical canvas is disabled.

Graph colors are derived from Kitty's active foreground, background, and ANSI
accent configuration. This lets palette generators such as DMS's wallpaper
color picker update the view without a separate Venting theme.

## Optional local summaries

Install [Ollama](https://ollama.com/download), start it with cloud features
disabled, and download a small model:

```sh
env OLLAMA_NO_CLOUD=1 ollama serve
ollama pull gemma3:1b
./run --summaries
```

Summaries and topic analysis run locally and are stored as separate cache files;
they never alter the original vent. Set the model in **Ctrl+O → Default path &
settings** to enable them on every launch. Summaries you write yourself stay in
place when a vent changes. Pressing R to redo a manual summary asks for
confirmation before replacing it with an LLM-generated summary.

## Privacy

Venting does not make network requests unless local AI features are enabled,
and those connect directly to Ollama on your machine. Topic references are
accepted only when their quoted text exists in the named vent. New vent files
use owner-only permissions. Drafts are not logged or uploaded.

Vent files are deliberately excluded from this Git repository: everything in
`vents/` is ignored except the empty `.gitkeep` placeholder.

## Working on it

Run the test suite with:

```sh
python3 -m unittest discover -s tests -v
```

See [DEVELOPING.md](DEVELOPING.md) and [CONTRIBUTING.md](CONTRIBUTING.md) for
project details. Venting is MIT licensed; bundled dictionary notices are in
[THIRD_PARTY.md](THIRD_PARTY.md).
