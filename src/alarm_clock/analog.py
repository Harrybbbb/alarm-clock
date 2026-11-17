"""An analog clock face drawn with braille characters.

Each terminal cell holds a 2×4 grid of braille dots. Cells are about
twice as tall as they are wide, so those dots come out roughly square,
and a face ``rows`` cells tall and ``2 * rows`` cells wide is round.

Pure: a time in, a ``Text`` out.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Tuple

from rich.text import Text

# Bit for each dot position (column 0–1, row 0–3) in a braille cell.
_BRAILLE_BITS = {
    (0, 0): 0x01, (0, 1): 0x02, (0, 2): 0x04, (0, 3): 0x40,
    (1, 0): 0x08, (1, 1): 0x10, (1, 2): 0x20, (1, 3): 0x80,
}


@dataclass(frozen=True)
class FaceColors:
    rim: str
    ticks: str
    numerals: str
    hour: str
    minute: str
    second: str
    hub: str


# Layers, lowest first: a cell takes the colour of the top layer in it.
RIM, TICK, HOUR, MINUTE, SECOND, HUB = range(6)


class _Canvas:
    def __init__(self, rows: int) -> None:
        self.rows = rows
        self.cols = rows * 2
        self.width = self.cols * 2  # in dots
        self.height = rows * 4
        self.dots: Dict[Tuple[int, int], int] = {}

    def plot(self, x: float, y: float, layer: int) -> None:
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < self.width and 0 <= iy < self.height:
            key = (ix, iy)
            self.dots[key] = max(layer, self.dots.get(key, -1))

    def line(self, x0: float, y0: float, x1: float, y1: float, layer: int) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 1
        for step in range(steps + 1):
            t = step / steps
            self.plot(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, layer)


def _point(cx: float, cy: float, radius: float, turns: float) -> Tuple[float, float]:
    """A point ``radius`` from the centre, ``turns`` of the way round from 12."""
    angle = turns * 2 * math.pi
    return cx + radius * math.sin(angle), cy - radius * math.cos(angle)


def analog_clock(now: datetime, rows: int, colors: FaceColors) -> Text:
    """Draw a clock face ``rows`` cells tall showing ``now``."""
    rows = max(7, rows)
    canvas = _Canvas(rows)
    cx, cy = (canvas.width - 1) / 2, (canvas.height - 1) / 2
    radius = min(cx, cy)

    # Rim.
    circumference = int(2 * math.pi * radius * 2)
    for step in range(circumference):
        canvas.plot(*_point(cx, cy, radius, step / circumference), RIM)

    # Ticks: a long one at each hour, longer still at 12, 3, 6 and 9.
    for hour in range(12):
        length = 0.16 if hour % 3 == 0 else 0.08
        outer = _point(cx, cy, radius * 0.94, hour / 12)
        inner = _point(cx, cy, radius * (0.94 - length), hour / 12)
        canvas.line(*inner, *outer, TICK)

    seconds = now.second
    minutes = now.minute + seconds / 60
    hours = now.hour % 12 + minutes / 60

    # Hour hand: short and drawn three dots thick so it reads as heavier.
    tip = _point(cx, cy, radius * 0.5, hours / 12)
    for dx, dy in ((0, 0), (1, 0), (0, 1), (-1, 0), (0, -1)):
        canvas.line(cx + dx, cy + dy, tip[0] + dx * 0.5, tip[1] + dy * 0.5, HOUR)
    # Minute hand: long, two dots thick.
    tip = _point(cx, cy, radius * 0.78, minutes / 60)
    for dx, dy in ((0, 0), (1, 0), (0, 1)):
        canvas.line(cx + dx, cy + dy, tip[0] + dx * 0.5, tip[1] + dy * 0.5, MINUTE)
    # Second hand: thin, with a short tail past the centre.
    tip = _point(cx, cy, radius * 0.86, seconds / 60)
    tail = _point(cx, cy, radius * 0.15, seconds / 60 + 0.5)
    canvas.line(*tail, *tip, SECOND)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            canvas.plot(cx + dx, cy + dy, HUB)

    # Numerals at 12, 3, 6 and 9, placed just inside the long ticks.
    numerals: Dict[Tuple[int, int], str] = {}
    for hour, label in ((0, "12"), (3, "3"), (6, "6"), (9, "9")):
        x, y = _point(cx, cy, radius * 0.62, hour / 12)
        col = int(round((x - 0.5) / 2 - (len(label) - 1) / 2))
        row = int(y // 4)
        for offset, char in enumerate(label):
            numerals[(col + offset, row)] = char

    layer_style = {
        RIM: colors.rim,
        TICK: colors.ticks,
        HOUR: colors.hour,
        MINUTE: colors.minute,
        SECOND: colors.second,
        HUB: colors.hub,
    }

    text = Text(no_wrap=True, end="")
    for row in range(canvas.rows):
        for col in range(canvas.cols):
            bits = 0
            top = -1
            for (dx, dy), bit in _BRAILLE_BITS.items():
                layer = canvas.dots.get((col * 2 + dx, row * 4 + dy))
                if layer is not None:
                    bits |= bit
                    top = max(top, layer)
            # A hand passing over a numeral wins; otherwise show the numeral.
            if (col, row) in numerals and top < HOUR:
                text.append(numerals[(col, row)], style=f"bold {colors.numerals}")
            elif bits:
                text.append(chr(0x2800 + bits), style=layer_style[top])
            else:
                text.append(" ")
        if row != canvas.rows - 1:
            text.append("\n")
    return text
