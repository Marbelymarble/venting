"""Small Kitty graphics-protocol renderer with no third-party dependencies."""

import base64
import fcntl
import glob
import math
import os
from pathlib import Path
import re
import sys
import struct
import termios

from .topicmap import TopicGraph


IMAGE_ID = 741928


def supported() -> bool:
    return sys.stdout.isatty() and bool(
        os.environ.get("KITTY_WINDOW_ID") or os.environ.get("KITTY_PID"))


def cell_size() -> tuple[int, int]:
    """Use physical cell pixels so Kitty never stretches circles into ovals."""
    try:
        rows, columns, width, height = struct.unpack(
            "HHHH", fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
        if rows and columns and width and height:
            return max(1, round(width / columns)), max(1, round(height / rows))
    except (OSError, ValueError, AttributeError):
        pass
    return 9, 18


def _parse_color(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    value = value.strip().split()[0] if value.strip() else ""
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))  # type: ignore[return-value]
    if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
        return tuple(int(value[index] * 2, 16) for index in (1, 2, 3))  # type: ignore[return-value]
    return fallback


def kitty_palette() -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """Read Kitty's included config files; DMS rewrites these on palette changes."""
    foreground, background, accent = (220, 225, 230), (18, 20, 24), (90, 190, 210)
    kitty_directory = os.environ.get("KITTY_CONFIG_DIRECTORY")
    if kitty_directory:
        root = Path(kitty_directory) / "kitty.conf"
    else:
        config_root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        root = config_root / "kitty/kitty.conf"
    pending, visited = [root], set()
    values: dict[str, str] = {}
    while pending:
        path = pending.pop(0)
        try:
            resolved = path.expanduser().resolve()
            if resolved in visited:
                continue
            visited.add(resolved)
            lines = resolved.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(maxsplit=1)
            key, value = (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")
            if key in ("include", "globinclude"):
                pattern = str((resolved.parent / value).expanduser())
                pending.extend(Path(item) for item in glob.glob(pattern))
            elif key in ("foreground", "background", "color4", "color6"):
                values[key] = value
    foreground = _parse_color(values.get("foreground", ""), foreground)
    background = _parse_color(values.get("background", ""), background)
    accent = _parse_color(values.get("color6", values.get("color4", "")), accent)
    return foreground, background, accent


def _blend(buffer: bytearray, width: int, x: int, y: int,
           color: tuple[int, int, int], alpha: float) -> None:
    if x < 0 or y < 0 or x >= width or alpha <= 0:
        return
    offset = (y * width + x) * 4
    if offset + 3 >= len(buffer):
        return
    old_alpha = buffer[offset + 3] / 255
    new_alpha = max(0.0, min(1.0, alpha))
    combined = new_alpha + old_alpha * (1 - new_alpha)
    if combined <= 0:
        return
    for channel in range(3):
        buffer[offset + channel] = round(
            (color[channel] * new_alpha + buffer[offset + channel] * old_alpha * (1 - new_alpha)) /
            combined)
    buffer[offset + 3] = round(combined * 255)


def _line(buffer: bytearray, width: int, height: int, start: tuple[float, float],
          end: tuple[float, float], color: tuple[int, int, int], thickness: float,
          opacity: float) -> None:
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    # Walk the major axis, touching each pixel once. Opacity stays uniform
    # regardless of stroke direction or length, including very shallow edges.
    steep = abs(dy) > abs(dx)
    if steep:
        x1, y1, x2, y2 = y1, x1, y2, x2
    if x1 > x2:
        x1, y1, x2, y2 = x2, y2, x1, y1
    dx, dy = x2 - x1, y2 - y1
    length2 = dx * dx + dy * dy
    margin = thickness / 2 + 1
    major_limit, minor_limit = (height, width) if steep else (width, height)
    for major in range(max(0, math.floor(x1 - margin)),
                       min(major_limit, math.ceil(x2 + margin) + 1)):
        t = max(0.0, min(1.0, (major + .5 - x1) / dx)) if dx else 0
        center = y1 + t * dy
        for minor in range(max(0, math.floor(center - margin * 1.5)),
                           min(minor_limit, math.ceil(center + margin * 1.5) + 1)):
            px, py = major + .5, minor + .5
            along = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length2)) if length2 else 0
            distance = math.hypot(px - x1 - along * dx, py - y1 - along * dy)
            coverage = max(0.0, min(1.0, thickness / 2 + .5 - distance))
            x, y = (minor, major) if steep else (major, minor)
            _blend(buffer, width, x, y, color, opacity * coverage)


def _circle(buffer: bytearray, width: int, height: int, center: tuple[float, float],
            radius: float, fill: tuple[int, int, int], outline: tuple[int, int, int],
            selected: bool) -> None:
    cx, cy = center
    ring_radius = radius + 3.5
    outer = radius + (8 if selected else 1)
    for y in range(max(0, int(cy - outer - 1)), min(height, int(cy + outer + 2))):
        for x in range(max(0, int(cx - outer - 1)), min(width, int(cx + outer + 2))):
            distance = math.hypot(x + .5 - cx, y + .5 - cy)
            if selected:
                halo = .14 * math.exp(-((distance - radius) / 4) ** 2)
                _blend(buffer, width, x, y, fill, halo)
                ring = max(0.0, min(1.0, 1.1 - abs(distance - ring_radius)))
                _blend(buffer, width, x, y, fill, ring * .8)
            coverage = max(0.0, min(1.0, radius + .5 - distance))
            _blend(buffer, width, x, y, fill, coverage * (.95 if selected else .65))
            # A fine inset rim replaces the heavy white outline.
            rim = max(0.0, min(1.0, .8 - abs(distance - (radius - .6))))
            _blend(buffer, width, x, y, outline, rim * (.35 if selected else .15))


def render_graph(graph: TopicGraph, positions: list[tuple[int, int]], columns: int, rows: int,
                 selected: int, *, cell_width: int = 9, cell_height: int = 18,
                 palette: tuple[tuple[int, int, int], tuple[int, int, int],
                                tuple[int, int, int]] | None = None) -> bytes:
    """Render transparent RGBA pixels sized for a terminal-cell placement."""
    pixel_width, pixel_height = max(1, columns * cell_width), max(1, rows * cell_height)
    buffer = bytearray(pixel_width * pixel_height * 4)
    foreground, _, accent = palette or kitty_palette()
    centers = [((x + .5) * cell_width, (y + .5) * cell_height) for x, y in positions]
    scale = cell_height / 18
    maximum = max((topic.frequency for topic in graph.topics), default=1)
    radius_unit = min(5.0, 13.0 / math.sqrt(max(1, maximum))) * scale
    for edge in sorted(graph.edges, key=lambda item: item.strength):
        active = selected in (edge.source, edge.target)
        _line(buffer, pixel_width, pixel_height, centers[edge.source], centers[edge.target],
              accent if active else foreground, (0.6 + edge.strength * 1.2) * scale,
              (0.2 + edge.strength * .3) if active else (.08 + edge.strength * .12))
    for index, topic in enumerate(graph.topics):
        # Circle area tracks occurrence count, using one shared scale.
        radius = max(2.5 * scale, radius_unit * math.sqrt(max(1, topic.frequency)))
        _circle(buffer, pixel_width, pixel_height, centers[index], radius, accent, foreground,
                index == selected)
    return bytes(buffer)


def _write(command: str, payload: bytes = b"") -> None:
    encoded = base64.b64encode(payload).decode("ascii")
    if not encoded:
        sys.stdout.write(f"\x1b_G{command}\x1b\\")
        return
    chunks = [encoded[index:index + 4096] for index in range(0, len(encoded), 4096)]
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        prefix = command if index == 0 else f"m={more}"
        if index == 0:
            prefix += f",m={more}"
        sys.stdout.write(f"\x1b_G{prefix};{chunk}\x1b\\")


def display_rgba(pixels: bytes, pixel_width: int, pixel_height: int,
                 y: int, x: int, rows: int, columns: int) -> None:
    if not supported():
        return
    # Save cursor, place the image at the requested cell, and restore the curses cursor.
    sys.stdout.write(f"\x1b7\x1b[{y + 1};{x + 1}H")
    _write(f"a=T,t=d,f=32,s={pixel_width},v={pixel_height},i={IMAGE_ID},p=1,"
           f"q=2,z=-1,c={columns},r={rows}", pixels)
    sys.stdout.write("\x1b8")
    sys.stdout.flush()


def clear() -> None:
    if supported():
        _write(f"a=d,d=i,i={IMAGE_ID},q=2")
        sys.stdout.flush()
