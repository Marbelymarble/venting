"""Modern terminal key reporting, alongside ncurses' legacy key decoding."""

import curses

DOC_HOME, DOC_END = -1001, -1002
PASTE, CTRL_TAB = -1003, -1004


class KeyboardModes:
    def __init__(self):
        self.previous_xterm: int | None = None

    def enable(self) -> str:
        # Query before changing xterm's mode; Kitty uses a push/pop stack.
        return "\x1b[?4m\x1b[>4;2m\x1b[>1u\x1b[?2004h"

    def restore(self) -> str:
        previous = "" if self.previous_xterm is None else f";{self.previous_xterm}"
        return f"\x1b[?2004l\x1b[<u\x1b[>4{previous}m"

    def decode(self, sequence: str) -> str | int | None:
        """Decode one CSI body (without ESC[); ignore replies/unknown keys."""
        if sequence == "200~":
            return PASTE
        if sequence.startswith(">4;") and sequence.endswith("m"):
            try:
                level = int(sequence[3:-1])
                if 0 <= level <= 3 and self.previous_xterm is None:
                    self.previous_xterm = level
            except ValueError:
                pass
            return None
        try:
            parts = sequence[:-1].split(";")
            final = sequence[-1]
            modifier_parts = parts[1].split(":") if len(parts) > 1 else ["1"]
            modifiers = int(modifier_parts[0]) - 1
            if len(modifier_parts) > 1 and int(modifier_parts[1]) == 3:
                return None  # Key release, not another press.
            if modifiers < 0:
                return None
            code = int(parts[0].split(":")[0])
            if final == "u" or (final == "~" and code == 27 and len(parts) == 3):
                if final == "~":
                    code = int(parts[2])
                if modifiers & 4 and code == 9 and not modifiers & (2 | 8 | 16 | 32):
                    return CTRL_TAB
                if modifiers & (2 | 8 | 16 | 32):
                    return None  # Unbound Alt/Super/etc. must not insert text.
                if modifiers & 4:
                    if 65 <= code <= 90 or 97 <= code <= 122:
                        return chr(code & 31)
                    return None
                if code in (9, 13, 27, 127):
                    return chr(code)
                if len(parts) > 2 and final == "u" and parts[2]:
                    text = "".join(chr(int(value)) for value in parts[2].split(":"))
                    return text if len(text) == 1 and text.isprintable() else None
                char = chr(code)
                return char if char.isprintable() else None
            if final in "HF" and modifiers & 4:
                return DOC_HOME if final == "H" else DOC_END
            if final == "~":
                if modifiers & 4 and code in (1, 7, 4, 8):
                    return DOC_HOME if code in (1, 7) else DOC_END
                return {1: curses.KEY_HOME, 2: curses.KEY_IC, 3: curses.KEY_DC,
                        4: curses.KEY_END, 5: curses.KEY_PPAGE, 6: curses.KEY_NPAGE,
                        7: curses.KEY_HOME, 8: curses.KEY_END,
                        11: curses.KEY_F1, 12: curses.KEY_F2, 13: curses.KEY_F3,
                        14: curses.KEY_F4, 15: curses.KEY_F5, 17: curses.KEY_F6,
                        18: curses.KEY_F7, 19: curses.KEY_F8}.get(code)
            return {"A": curses.KEY_UP, "B": curses.KEY_DOWN,
                    "C": curses.KEY_RIGHT, "D": curses.KEY_LEFT,
                    "H": curses.KEY_HOME, "F": curses.KEY_END,
                    "P": curses.KEY_F1, "Q": curses.KEY_F2,
                    "R": curses.KEY_F3, "S": curses.KEY_F4}.get(final)
        except (ValueError, IndexError, OverflowError):
            return None
