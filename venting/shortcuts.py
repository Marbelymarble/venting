"""Validated global shortcuts that do not collide with text editing keys."""

import curses
from collections.abc import Mapping


ACTION_LABELS = {
    "commands": "Program menu",
    "files": "Open / switch file",
    "panes": "Show / hide file editor",
    "autocorrect": "Toggle autocorrect",
    "settings": "Default path & settings",
    "copy": "Copy saved file",
    "help": "Help",
}

DEFAULT_BINDINGS = {
    "commands": "ctrl+o",
    "files": "ctrl+f",
    "panes": "ctrl+p",
    "autocorrect": "ctrl+t",
    "settings": "none",
    "copy": "none",
    "help": "f1",
}

# Other control letters are editor operations, terminal aliases for Tab/Enter/
# Backspace, quit/save/reload, paste controls, or the verified delete action.
SAFE_CONTROL_LETTERS = frozenset("bfgkloptx")


def normalize_binding(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Shortcut bindings must be strings.")
    binding = value.strip().lower().replace("control+", "ctrl+")
    if binding in ("none", "menu only", "unbound"):
        return "none"
    if binding.startswith("ctrl+") and len(binding) == 6:
        if binding[-1] in SAFE_CONTROL_LETTERS:
            return binding
        raise ValueError("Use Ctrl+B/F/G/K/L/O/P/T/X, F1–F12, or 'none'.")
    if binding.startswith("f") and binding[1:].isdigit():
        number = int(binding[1:])
        if 1 <= number <= 12:
            return f"f{number}"
    raise ValueError("Use Ctrl+B/F/G/K/L/O/P/T/X, F1–F12, or 'none'.")


def validate_bindings(values: object) -> dict[str, str]:
    if values is None:
        return dict(DEFAULT_BINDINGS)
    if not isinstance(values, Mapping):
        raise ValueError("keybindings must be a JSON object.")
    unknown = set(values) - set(DEFAULT_BINDINGS)
    if unknown:
        raise ValueError("Unknown shortcut action: " + sorted(unknown)[0])
    bindings = dict(DEFAULT_BINDINGS)
    bindings.update({action: normalize_binding(value) for action, value in values.items()})
    if bindings["commands"] == "none":
        raise ValueError("The Program menu needs a keyboard shortcut.")
    assigned = [binding for binding in bindings.values() if binding != "none"]
    if len(set(assigned)) != len(assigned):
        raise ValueError("Each shortcut must use a different key.")
    return bindings


def key_for(binding: str) -> str | int | None:
    binding = normalize_binding(binding)
    if binding == "none":
        return None
    if binding.startswith("ctrl+"):
        return chr(ord(binding[-1]) - 96)
    return curses.KEY_F0 + int(binding[1:])


def binding_for_key(key: str | int | tuple[str, str]) -> str | None:
    if isinstance(key, str) and len(key) == 1:
        number = ord(key)
        if 1 <= number <= 26:
            letter = chr(number + 96)
            if letter in SAFE_CONTROL_LETTERS:
                return "ctrl+" + letter
    if isinstance(key, int):
        for number in range(1, 13):
            if key == curses.KEY_F0 + number:
                return f"f{number}"
    return None


def display_binding(binding: str) -> str:
    binding = normalize_binding(binding)
    if binding == "none":
        return "Menu only"
    return ("Ctrl+" + binding[-1].upper()) if binding.startswith("ctrl+") else binding.upper()
