# Contributing to Venting

Thanks for helping improve Venting. Small, focused changes with tests are the
easiest to review.

## Privacy first

Never commit or paste real vent content, personal filenames, local settings,
summary metadata, terminal scrollback containing thoughts, or private filesystem
paths. Reproduce issues with newly written synthetic text in a temporary
directory. Before attaching logs or screenshots, inspect every visible line.

The ignored `vents/`, `venting.json`, and `.venting-summaries/` paths are local
data, not fixtures. Tests must create their own temporary files.

## Development

Use Python 3.10 or newer on a POSIX system with curses:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q venting
```

The suite uses a fake loopback Ollama server; it does not require a model or
internet access. See [DEVELOPING.md](DEVELOPING.md) for architecture and
behavioral invariants.

## Pull requests

- Explain the user-visible problem and the chosen behavior.
- Add or adjust unit tests; use a PTY test when terminal decoding or rendered
  interaction is part of the change.
- Run the complete suite and mention any platform-specific test you could not
  run.
- Update README and changelog entries when behavior changes.
- Keep third-party code and data out unless its license and provenance are
  documented in `THIRD_PARTY.md`.

Report vulnerabilities through the private process in
[SECURITY.md](SECURITY.md), not a public issue.

