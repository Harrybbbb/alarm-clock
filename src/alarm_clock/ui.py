"""Rendering: turns scheduler state into Rich renderables.

Every function here is pure — state in, renderable out, no I/O and no
clock access. That keeps the look of the app testable with a recording
console, and keeps ``tui.py`` down to loop-and-dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence, Tuple

from rich.align import Align
from rich.box import HEAVY, ROUNDED, SIMPLE_HEAD
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.constrain import Constrain
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from alarm_clock.analog import FaceColors, analog_clock
from alarm_clock.models import Alarm

# -- palette --------------------------------------------------------------
# Named once, used everywhere, so the whole app recolors from one place.

ACCENT = "#22d3ee"
MUTED = "#64748b"
SOFT = "#94a3b8"
ON = "#4ade80"
OFF = "#64748b"
WARN = "#fbbf24"
RING = "#f87171"
SELECT_BG = "#1e3a5f"
KEYCAP = "bold #0f172a on #22d3ee"

TONES = {"info": SOFT, "ok": ON, "error": RING, "warn": WARN}

#: The whole app is drawn at most this wide and centred, so it stays a
#: tidy block on a big terminal instead of stretching edge to edge.
APP_WIDTH = 74

#: Vertical gradient for the big clock, bright at the top like a display.
CLOCK_RAMP = ("#67e8f9", "#22d3ee", "#38bdf8", "#60a5fa", "#818cf8")
RINGING_RAMP = ("#fecaca", "#fca5a5", "#f87171", "#ef4444", "#dc2626")

FACE = FaceColors(
    rim="#38bdf8", ticks="#475569", numerals="#e2e8f0",
    hour="#e2e8f0", minute="#22d3ee", second=WARN, hub=WARN,
)
RINGING_FACE = FaceColors(
    rim=RING, ticks="#7f1d1d", numerals="#fecaca",
    hour="#fecaca", minute=RING, second="white", hub="white",
)

DIGITAL = "digital"
ANALOG = "analog"

#: Tallest and shortest analog face, in terminal rows.
ANALOG_MAX_ROWS = 17
ANALOG_MIN_ROWS = 9

# -- seven-segment digits -------------------------------------------------

_GLYPHS = {
    "0": ("███", "█ █", "█ █", "█ █", "███"),
    "1": ("  █", "  █", "  █", "  █", "  █"),
    "2": ("███", "  █", "███", "█  ", "███"),
    "3": ("███", "  █", "███", "  █", "███"),
    "4": ("█ █", "█ █", "███", "  █", "  █"),
    "5": ("███", "█  ", "███", "  █", "███"),
    "6": ("███", "█  ", "███", "█ █", "███"),
    "7": ("███", "  █", "  █", "  █", "  █"),
    "8": ("███", "█ █", "███", "█ █", "███"),
    "9": ("███", "█ █", "███", "  █", "███"),
    ":": ("   ", " █ ", "   ", " █ ", "   "),
    " ": ("   ", "   ", "   ", "   ", "   "),
}

GLYPH_HEIGHT = 5


def big_text(text: str, ramp: tuple[str, ...] = CLOCK_RAMP, scale: int = 1) -> Text:
    """Render ``text`` as seven-segment blocks, shaded top to bottom.

    ``scale`` widens every pixel. Terminal cells are about twice as tall
    as they are wide, so ``scale=2`` gives square pixels and much more
    legible digits; ``scale=1`` is the compact fallback.

    Deliberately *not* centred here. Some glyph rows end in a space,
    and Rich strips trailing whitespace from a line before applying
    ``justify``, so a per-line centre would shift exactly those rows and
    visibly break the digits. Wrap the result in ``Align.center``
    instead: it pads every row by the same amount.

    Characters with no glyph are rendered as blanks rather than raising,
    so a caller can never crash the display over a stray character.
    """
    gap = " " * scale
    rendered = Text(no_wrap=True, end="")
    for row in range(GLYPH_HEIGHT):
        cells = (_GLYPHS.get(char, _GLYPHS[" "])[row] for char in text)
        line = gap.join("".join(pixel * scale for pixel in cell) for cell in cells)
        rendered.append(line, style=ramp[row % len(ramp)])
        if row != GLYPH_HEIGHT - 1:
            rendered.append("\n")
    return rendered


def big_text_width(text: str, scale: int) -> int:
    return len(text) * 3 * scale + (len(text) - 1) * scale


class BigClock:
    """Big digits that pick the largest size the space allows."""

    def __init__(self, text: str, ramp: tuple[str, ...] = CLOCK_RAMP) -> None:
        self.text = text
        self.ramp = ramp

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        scale = 2 if options.max_width >= big_text_width(self.text, 2) else 1
        yield Align.center(big_text(self.text, self.ramp, scale))


# -- formatting helpers ---------------------------------------------------


def format_time(moment: datetime, h12: bool = False) -> str:
    """A time of day: '19:30' on a 24-hour clock, '7:30 PM' on a 12-hour one."""
    if not h12:
        return moment.strftime("%H:%M")
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def clock_digits(moment: datetime, h12: bool = False) -> str:
    """What the big clock shows: 'HH:MM:SS', with a 1–12 hour in 12-hour mode."""
    if not h12:
        return moment.strftime("%H:%M:%S")
    return f"{moment.hour % 12 or 12}:{moment.minute:02d}:{moment.second:02d}"


def format_countdown(delta_seconds: float) -> str:
    """A compact, human countdown: '2h 05m', '18 min', '42 sec', 'now'."""
    seconds = int(delta_seconds)
    if seconds <= 0:
        return "now"
    if seconds < 60:
        return f"{seconds} sec"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def describe_when(fire_at: datetime, now: datetime) -> str:
    """Say which day an alarm falls on, relative to ``now``."""
    if fire_at <= now:
        return "overdue"
    if fire_at.date() == now.date():
        return "today"
    return "tomorrow"


def progress_bar(fraction: float, width: int = 24) -> Text:
    """A filled/unfilled bar, drawn with block characters."""
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    bar = Text()
    bar.append("█" * filled, style=ACCENT)
    bar.append("░" * (width - filled), style="#334155")
    return bar


def keycap(key: str, action: str, action_style: str = SOFT) -> Text:
    hint = Text()
    hint.append(f" {key} ", style=KEYCAP)
    hint.append(f" {action}", style=action_style)
    return hint


def _key_grid(keys: Sequence[Tuple[str, str]], columns: int) -> Table:
    """Key hints in a grid, so every row lines up with the one above."""
    grid = Table.grid(padding=(0, 3))
    for _ in range(min(columns, len(keys))):
        grid.add_column()
    for start in range(0, len(keys), columns):
        row = [keycap(key, action) for key, action in keys[start : start + columns]]
        grid.add_row(*row)
    return grid


# -- panels ---------------------------------------------------------------


def clock_panel(
    now: datetime,
    next_alarm: Alarm | None,
    ringing: bool = False,
    h12: bool = False,
    style: str = DIGITAL,
    analog_rows: int = ANALOG_MAX_ROWS,
) -> Panel:
    """The hero panel: the current time, date, and the next deadline."""
    if style == ANALOG:
        face = analog_clock(now, analog_rows, RINGING_FACE if ringing else FACE)
        body: list[RenderableType] = [
            Align.center(face),
            Text(""),
            Align.center(_time_and_date_line(now, h12, ringing)),
            Text(""),
        ]
    else:
        ramp = RINGING_RAMP if ringing else CLOCK_RAMP
        body = [
            BigClock(clock_digits(now, h12), ramp),
            Text(""),
            Align.center(_date_line(now, h12, ringing)),
            Text(""),
        ]

    if next_alarm is None:
        body.append(Align.center(Text("No alarms set — press A to add one", style=f"italic {MUTED}")))
    else:
        remaining = (next_alarm.fire_at - now).total_seconds()
        headline = Text()
        headline.append("Next  ", style=MUTED)
        headline.append(format_time(next_alarm.fire_at, h12), style=f"bold {ACCENT}")
        if next_alarm.label:
            headline.append(f"  {next_alarm.label}", style="bold white")
        if remaining > 0:
            headline.append("  ·  in ", style=MUTED)
            headline.append(format_countdown(remaining), style=f"bold {WARN}")
            body.append(Align.center(headline))
            body.append(Align.center(progress_bar(next_alarm.progress(now), width=40)))
        else:
            headline.append("  ·  ringing now", style=f"bold {RING}")
            body.append(Align.center(headline))

    return Panel(
        Group(*body),
        title=Text(" ⏰  ALARM CLOCK ", style=f"bold {RING if ringing else ACCENT}"),
        box=ROUNDED,
        border_style=RING if ringing else ACCENT,
        padding=(1, 2),
    )


def _date_line(now: datetime, h12: bool, ringing: bool) -> Text:
    line = Text()
    if h12:
        # The big digits can't say AM or PM, so the date line does.
        line.append(" AM " if now.hour < 12 else " PM ", style=f"bold #0f172a on {RING if ringing else ACCENT}")
        line.append("  ")
    line.append(now.strftime("%A, %d %B %Y"), style=f"bold {SOFT}")
    return line


def _time_and_date_line(now: datetime, h12: bool, ringing: bool) -> Text:
    """Under an analog face: the exact time in words a hand can't give."""
    line = Text()
    seconds = f":{now.second:02d}"
    shown = format_time(now, h12)
    if h12:
        shown = shown.replace(" ", f"{seconds} ")
    else:
        shown += seconds
    line.append(shown, style=f"bold {RING if ringing else ACCENT}")
    line.append("   ·   ", style=MUTED)
    line.append(now.strftime("%A, %d %B %Y"), style=f"bold {SOFT}")
    return line


def alarm_table(
    alarms: list[Alarm], now: datetime, selected: Optional[int] = None, h12: bool = False
) -> RenderableType:
    """The alarm list, with the selected row highlighted."""
    table = Table(
        box=SIMPLE_HEAD,
        border_style=MUTED,
        header_style=f"bold {MUTED}",
        expand=True,
        pad_edge=False,
        padding=(0, 1),
        show_edge=False,
    )
    table.add_column("", width=1)
    table.add_column("TIME", width=8 if h12 else 5)
    table.add_column("LABEL", ratio=1, overflow="ellipsis", no_wrap=True)
    table.add_column("RINGS", width=22, no_wrap=True)
    table.add_column("", width=5, justify="right")

    title = Text()
    title.append("  Alarms", style=f"bold {ACCENT}")
    if alarms:
        armed = sum(1 for alarm in alarms if alarm.enabled)
        title.append(f"  {armed} on · {len(alarms) - armed} off", style=MUTED)

    if not alarms:
        empty = Text("\nNo alarms yet. Press ", style=f"italic {MUTED}")
        empty.append(" A ", style=KEYCAP)
        empty.append(" to add one — e.g. 7:30, 7pm or +15.\n", style=f"italic {MUTED}")
        return Group(title, Align.center(empty))

    for index, alarm in enumerate(alarms):
        when = describe_when(alarm.fire_at, now)
        if not alarm.enabled:
            status = Text("○ OFF", style=OFF)
            row_style = OFF
            rings = Text(f"{when} · paused", style=OFF)
        elif when == "overdue":
            status = Text("● DUE", style=f"bold {RING}")
            row_style = RING
            rings = Text("ringing now", style=f"bold {RING}")
        else:
            status = Text("● ON", style=ON)
            row_style = "white"
            rings = Text(f"{when} · ", style=MUTED)
            rings.append(f"in {format_countdown((alarm.fire_at - now).total_seconds())}", style=SOFT)

        label = Text(alarm.label or "Alarm", style=row_style if alarm.label else f"italic {MUTED}")
        if alarm.snoozes:
            label.append(f"  (snoozed ×{alarm.snoozes})", style=f"italic {WARN}")

        is_selected = index == selected
        table.add_row(
            Text("❯", style=f"bold {ACCENT}") if is_selected else Text(" "),
            Text(format_time(alarm.fire_at, h12), style=f"bold {row_style}"),
            label,
            rings,
            status,
            style=f"on {SELECT_BG}" if is_selected else None,
        )
    return Group(title, table)


@dataclass(frozen=True)
class Prompt:
    """An inline question drawn in place of the key hints.

    ``value`` is None for a yes/no question with nothing to type.
    """

    title: str
    label: str
    value: Optional[str] = ""
    hint: str = ""
    preview: str = ""
    error: bool = False
    keys: Tuple[Tuple[str, str], ...] = (("Enter", "Next"), ("Esc", "Cancel"))


def prompt_panel(prompt: Prompt) -> Panel:
    body: list[RenderableType] = []
    line = Text()
    line.append(f"{prompt.label} ", style="bold white")
    if prompt.value is not None:
        line.append("❯ ", style=ACCENT)
        line.append(prompt.value, style="bold white")
        line.append("▌", style=f"blink {ACCENT}")
    body.append(line)
    if prompt.preview:
        body.append(Text(prompt.preview, style=RING if prompt.error else ON))
    if prompt.hint:
        body.append(Text(prompt.hint, style=MUTED))
    body.append(Text(""))
    keys = Text()
    for index, (key, action) in enumerate(prompt.keys):
        if index:
            keys.append("    ")
        keys.append_text(keycap(key, action))
    body.append(keys)
    return Panel(
        Group(*body),
        title=Text(f" {prompt.title} ", style=f"bold {ACCENT}"),
        title_align="left",
        box=ROUNDED,
        border_style=ACCENT,
        padding=(0, 2),
    )


NORMAL_KEYS: Tuple[Tuple[str, str], ...] = (
    ("A", "Add"),
    ("↑↓", "Select"),
    ("Space", "On/off"),
    ("D", "Delete"),
    ("S", "Snooze next"),
    ("U", "Undo"),
    ("C", "Clear all"),
    ("O", "Settings"),
    ("Q", "Quit"),
)
RINGING_KEYS: Tuple[Tuple[str, str], ...] = (
    ("S", "Snooze 5 min"),
    ("D / Enter", "Dismiss"),
    ("Q", "Quit"),
)


@dataclass(frozen=True)
class Setting:
    """One row of the settings panel: a name and its choices."""

    name: str
    choices: Tuple[str, ...]
    current: int


def settings_panel(settings: Sequence[Setting], selected: int) -> Panel:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=1)
    grid.add_column(min_width=12)
    grid.add_column()
    for index, setting in enumerate(settings):
        is_selected = index == selected
        choices = Text()
        for choice_index, choice in enumerate(setting.choices):
            if choice_index:
                choices.append("  ")
            if choice_index == setting.current:
                choices.append(f" {choice} ", style=KEYCAP if is_selected else f"bold white on {SELECT_BG}")
            else:
                choices.append(f" {choice} ", style=MUTED)
        grid.add_row(
            Text("❯", style=f"bold {ACCENT}") if is_selected else Text(" "),
            Text(setting.name, style="bold white" if is_selected else SOFT),
            choices,
        )
    keys = Text()
    for index, (key, action) in enumerate((("↑↓", "Choose"), ("←→ / Space", "Change"), ("Enter / Esc", "Done"))):
        if index:
            keys.append("    ")
        keys.append_text(keycap(key, action))
    return Panel(
        Group(grid, Text(""), keys),
        title=Text(" ⚙  Settings ", style=f"bold {ACCENT}"),
        title_align="left",
        box=ROUNDED,
        border_style=ACCENT,
        padding=(1, 2),
    )


def footer(ringing: bool = False) -> RenderableType:
    """The key hints along the bottom, in aligned columns."""
    if ringing:
        return Align.center(_key_grid(RINGING_KEYS, columns=3))
    return Align.center(_key_grid(NORMAL_KEYS, columns=3))


def banner(ringing: list[Alarm], h12: bool = False) -> Panel:
    """The full-width alert shown while one or more alarms are ringing."""
    body = Text(justify="center")
    body.append("\n")
    for alarm in ringing:
        body.append("⏰  ", style=RING)
        body.append(format_time(alarm.fire_at, h12), style=f"bold {RING}")
        if alarm.label:
            body.append(f"  —  {alarm.label}", style="bold white")
        body.append("\n")
    body.append("\n")
    body.append_text(keycap("S", "Snooze 5 min", "bold white"))
    body.append("      ")
    body.append_text(keycap("D", "Dismiss", "bold white"))
    body.append("\n")
    title = "ALARM" if len(ringing) == 1 else f"{len(ringing)} ALARMS"
    return Panel(
        body,
        title=Text(f" 🔔  {title} RINGING ", style=f"bold {RING}"),
        box=HEAVY,
        border_style=RING,
        padding=(0, 2),
    )


def status_line(message: str, style: str = SOFT) -> Text:
    return Text(message, style=style, justify="center")


def dashboard(
    alarms: list[Alarm],
    now: datetime,
    next_alarm: Alarm | None,
    ringing: list[Alarm] | None = None,
    message: str = "",
    tone: str = "info",
    selected: Optional[int] = None,
    prompt: Optional[Prompt] = None,
    height: Optional[int] = None,
    h12: bool = False,
    clock_style: str = DIGITAL,
    settings: Optional[Sequence[Setting]] = None,
    settings_selected: int = 0,
) -> RenderableType:
    """The whole screen: a centred column, vertically centred if ``height``."""
    ringing = ringing or []
    analog_rows = ANALOG_MAX_ROWS
    if height is not None:
        # Shrink the face on a short terminal so the alarm list still fits.
        room = height - 24 - len(alarms) - (8 if ringing else 0)
        analog_rows = max(ANALOG_MIN_ROWS, min(ANALOG_MAX_ROWS, room))
        analog_rows -= 1 - analog_rows % 2  # odd, so the hub sits on a row
    parts: list[RenderableType] = [
        clock_panel(
            now, next_alarm, ringing=bool(ringing), h12=h12,
            style=clock_style, analog_rows=analog_rows,
        )
    ]
    if ringing:
        parts.append(banner(ringing, h12))
    parts.append(Text(""))
    parts.append(alarm_table(alarms, now, None if ringing else selected, h12))
    parts.append(Text(""))
    if settings is not None and not ringing:
        parts.append(settings_panel(settings, settings_selected))
    elif prompt is not None and not ringing:
        parts.append(prompt_panel(prompt))
    else:
        parts.append(status_line(message or " ", TONES.get(tone, SOFT)))
        parts.append(Text(""))
        parts.append(footer(ringing=bool(ringing)))

    # One Align does both jobs: nesting a centred Align inside another
    # would let the outer one shrink-wrap it and undo the centring.
    column = Constrain(Group(*parts), width=APP_WIDTH)
    if height is None:
        return Align.center(column)
    return Align.center(column, vertical="middle", height=height)
