# Changelog

Notable user-facing changes are recorded here. This project follows Semantic
Versioning once public releases begin.

## Unreleased

### Added

- Recent vents use short local summaries as their labels.
- Summary generation can be retried or force-redone with Ollama.
- One edit sheet changes a vent's summary and filename or verifies deletion.
- The edit sheet previews the latest saved file text for identification.
- A navigable full program menu keeps secondary actions out of the everyday footer.
- Global shortcuts can be edited in place and are stored in private settings.
- The full command menu links directly to the default path and other settings.
- Conservative offline autocorrect supports English and German.
- Full-file editing, undo/redo, clipboard copy, and guarded reloads.

### Changed

- Tab switches directly between the path field and recent vents.
- Summaries appear in the recent selector and file editor, not the venting pane.
- The default shortcut presentation favors Ctrl keys; function keys remain
  available as configurable actions. Ctrl+O opens the program menu, Ctrl+F opens
  existing files, and low-frequency Settings/Copy actions default to menu-only.
- Field titles and helper text now describe their effects, and a divider
  separates status guidance from the shortcut footer.

### Security and privacy

- Summary requests are restricted to a loopback Ollama endpoint and bypass
  configured proxies.
- Thin inputs are withheld from Ollama; prompt echoes and instruction-like
  generated labels are rejected rather than cached.
- Settings, summary metadata, generated vent files, and local build artifacts
  are excluded from version control.
