"""Command-line entry point. Run with python3 -m venting."""

import argparse
import locale
import os
from pathlib import Path
import sys

from . import __version__


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="venting", description="Terminal app for appending to and editing text files."
    )
    parser.add_argument("file", nargs="?", help="append to an existing UTF-8 text file")
    parser.add_argument("--new", metavar="FILE", help="create a new file; never overwrite")
    parser.add_argument("--show", action="store_true", help="start with the file editor visible; Tab focuses it")
    parser.add_argument("--autocorrect", action="store_true",
                        help="start with the configured offline autocorrect language on")
    parser.add_argument("--no-color", action="store_true", help="use a monochrome interface")
    parser.add_argument("--config", type=Path, metavar="FILE", help="use a different settings JSON file")
    parser.add_argument("--summaries", action="store_true", help="enable summaries using local Ollama")
    parser.add_argument("--version", action="version", version=f"venting {__version__}")
    args = parser.parse_args()
    if args.file and args.new:
        parser.error("choose either an existing file or --new FILE")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.exit(2, "venting needs an interactive terminal. Try: python3 -m venting\n")
    if os.environ.get("TERM", "dumb") in ("dumb", "unknown", ""):
        parser.exit(2, "venting needs a terminal with curses support (check TERM).\n")

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    try:
        import curses
        from .app import App
    except ImportError:
        parser.exit(2, "venting needs Python's curses module. Use your Linux or macOS Python.\n")

    app = App(show_preview=args.show, no_color=args.no_color or "NO_COLOR" in os.environ,
              config_path=args.config, enable_summaries=args.summaries)
    try:
        if args.new:
            app.open_path(args.new, create=True)
        elif args.file:
            app.open_path(args.file, create=False)
        if args.autocorrect:
            app.toggle_autocorrect()
        curses.wrapper(app.run)
    except (OSError, ValueError, curses.error) as error:
        # Never print the draft or file content in an error report.
        print(f"venting: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
