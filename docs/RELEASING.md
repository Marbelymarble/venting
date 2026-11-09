# Release process

## 1. Prepare

- Move completed entries from `CHANGELOG.md` into a versioned section with the
  release date.
- Update the version in both `pyproject.toml` and `venting/__init__.py`.
- Confirm README installation, privacy, shortcut, and Ollama instructions.
- Confirm the worktree contains no local settings, vents, summary cache, or
  generated distribution files.

## 2. Validate

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q venting
python3 -m venting --help
python3 -m venting --version
python3 -m pip wheel --no-deps --no-build-isolation . -w dist
```

Install the wheel into a fresh virtual environment and smoke-test `venting
--help`, direct file creation, append, full-file saving, recent selection, and a
clean quit. Summary generation is optional for the general smoke test; if it is
tested, use synthetic content and a local model.

Inspect both archive types before publishing. They must include package data,
licenses, README, and no personal data.

## 3. Tag and publish

Commit the release metadata, create a signed annotated tag such as `v0.6.0`,
and push the commit and tag. Draft the GitHub release from the corresponding
changelog section. Attach artifacts only after checking their contents and
hashes.

Publishing to PyPI is intentionally not automated yet. Add trusted publishing
only after the package owner, repository URL, release cadence, and recovery
process have been decided. Never store a long-lived PyPI token in the repository.

## 4. Verify

Install from the published artifact in a clean environment, confirm the version,
and verify that the GitHub release, tag, and changelog agree. Then restore an
`Unreleased` section for the next cycle.

