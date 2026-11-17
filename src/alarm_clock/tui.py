"""The live, full-screen alarm clock interface.

Loop-and-dispatch only: every pixel comes from ``ui.py`` and every
decision about time comes from the injected clock via the scheduler.

Everything happens on one screen. Questions ("what time?") are typed
into an inline box rather than a prompt that drops out of the display,
and alarms are picked with the arrow keys rather than by typing an id.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Callable, List, Optional

from rich.console import Console, RenderableType
from rich.live import Live

from alarm_clock import ui
from alarm_clock.clock import Clock
from alarm_clock.keyboard import KeyReader
from alarm_clock.models import Alarm, next_occurrence
from alarm_clock.sound import AlarmSound
from alarm_clock.scheduler import DEFAULT_SNOOZE_MINUTES, AlarmScheduler
from alarm_clock.timeparse import HINT, parse_alarm_time

#: How long to wait for a keypress before redrawing anyway. Four
#: redraws a second keeps the seconds digit honest without busy-looping.
TICK_SECONDS = 0.25

#: Longest thing worth typing into the time or label box.
MAX_INPUT = 40

NORMAL = "normal"
ENTER_TIME = "time"
ENTER_LABEL = "label"
CONFIRM_CLEAR = "confirm-clear"
SETTINGS = "settings"

TIME_FORMATS = ("24-hour", "12-hour")
CLOCK_STYLES = (ui.DIGITAL, ui.ANALOG)

_KEY_NAMES = {
    "\r": "enter",
    "\n": "enter",
    "\x7f": "backspace",
    "\b": "backspace",
    "\x1b": "esc",
    " ": "space",
}


def normalize(key: str) -> str:
    return _KEY_NAMES.get(key, key)


class AlarmClockApp:
    def __init__(
        self,
        scheduler: AlarmScheduler,
        clock: Clock,
        console: Optional[Console] = None,
        sound: Optional[AlarmSound] = None,
        h12: bool = False,
        clock_style: str = ui.DIGITAL,
    ) -> None:
        self._h12 = h12
        self._clock_style = clock_style
        self._setting_index = 0
        self._scheduler = scheduler
        self._clock = clock
        self._console = console if console is not None else Console()
        self._sound = sound if sound is not None else AlarmSound()
        self._message = ""
        self._tone = "info"
        self._running = True
        self._last_bell_second = -1

        self._mode = NORMAL
        self._buffer = ""
        self._input_error = ""
        self._pending_time: Optional[time] = None
        self._selected_id: Optional[int] = None
        self._undo: List[Alarm] = []

    # -- main loop --------------------------------------------------------

    def run(self) -> None:
        """Draw and dispatch until the user quits or interrupts."""
        with KeyReader() as keys:
            with Live(
                self._render(),
                console=self._console,
                screen=True,
                refresh_per_second=8,
                transient=False,
            ) as live:
                while self._running:
                    try:
                        live.update(self._render())
                        key = keys.read(TICK_SECONDS)
                        if key is not None:
                            self._dispatch(key)
                    except KeyboardInterrupt:
                        self._running = False
        self._sound.stop()
        self._console.print(ui.status_line("Goodbye.", style=ui.ACCENT))

    def _render(self) -> RenderableType:
        now = self._clock.now()
        ringing = self._scheduler.due_now()
        self._alert(ringing, now)
        alarms = self._scheduler.list()
        return ui.dashboard(
            alarms=alarms,
            now=now,
            next_alarm=self._scheduler.next_due(),
            ringing=ringing,
            # A leftover status line ("Alarm set...") is noise next to a
            # ringing alarm; say what the keys do instead.
            message="Snooze for 5 minutes, or dismiss it." if ringing else self._message,
            tone="warn" if ringing else self._tone,
            selected=self._selected_index(alarms),
            prompt=self._prompt(now),
            height=self._console.size.height,
            h12=self._h12,
            clock_style=self._clock_style,
            settings=self._settings() if self._mode == SETTINGS else None,
            settings_selected=self._setting_index,
        )

    def _alert(self, ringing: List[Alarm], now: datetime) -> None:
        """Make noise while an alarm is ringing, and stop when none is.

        A sound file rings continuously; the terminal bell is only the
        fallback for machines with no player or no file, since most
        terminals render it silently if at all.
        """
        if not ringing:
            self._sound.stop()
            return
        if self._sound.available:
            self._sound.ensure_playing()
        else:
            self._ring_bell(now.second)

    def _ring_bell(self, second: int) -> None:
        """Emit the terminal bell at most once a second while ringing."""
        if second != self._last_bell_second:
            self._last_bell_second = second
            self._console.bell()

    # -- what's on screen -------------------------------------------------

    def _selected_index(self, alarms: List[Alarm]) -> Optional[int]:
        if not alarms:
            return None
        for index, alarm in enumerate(alarms):
            if alarm.id == self._selected_id:
                return index
        self._selected_id = alarms[0].id
        return 0

    def _selected_alarm(self) -> Optional[Alarm]:
        alarms = self._scheduler.list()
        index = self._selected_index(alarms)
        return None if index is None else alarms[index]

    def _prompt(self, now: datetime) -> Optional[ui.Prompt]:
        if self._mode == ENTER_TIME:
            preview, error = self._time_preview(now)
            return ui.Prompt(
                title="New alarm · 1 of 2",
                label="What time?",
                value=self._buffer,
                hint=HINT,
                preview=preview,
                error=error,
            )
        if self._mode == ENTER_LABEL:
            assert self._pending_time is not None
            fire_at = next_occurrence(self._pending_time, now)
            return ui.Prompt(
                title="New alarm · 2 of 2",
                label="Label?",
                value=self._buffer,
                hint="Optional — just press Enter to skip.",
                preview=f"✓ {self._describe(fire_at, now)}",
                keys=(("Enter", "Save alarm"), ("Esc", "Cancel")),
            )
        if self._mode == CONFIRM_CLEAR:
            count = len(self._scheduler.list())
            return ui.Prompt(
                title="Clear all",
                label=f"Delete all {count} alarms?",
                value=None,
                hint="You can press U afterwards to bring them back.",
                keys=(("Y", "Yes, delete"), ("N / Esc", "Keep them")),
            )
        return None

    def _time_preview(self, now: datetime) -> tuple[str, bool]:
        if self._input_error:
            return f"✗ {self._input_error}", True
        if not self._buffer.strip():
            return "", False
        try:
            alarm_time = parse_alarm_time(self._buffer, now)
        except ValueError:
            return "", False
        return f"✓ {self._describe(next_occurrence(alarm_time, now), now)}", False

    def _fmt(self, moment: datetime) -> str:
        return ui.format_time(moment, self._h12)

    def _describe(self, fire_at: datetime, now: datetime) -> str:
        day = ui.describe_when(fire_at, now)
        wait = ui.format_countdown((fire_at - now).total_seconds())
        return f"Rings {day} at {self._fmt(fire_at)} — in {wait}"

    def _say(self, message: str, tone: str = "info") -> None:
        self._message, self._tone = message, tone

    # -- input ------------------------------------------------------------

    def _dispatch(self, raw_key: str) -> None:
        key = normalize(raw_key)
        ringing = self._scheduler.due_now()

        if ringing:
            # Whatever was being typed is abandoned: the only sensible
            # verbs now are "stop it" and "not yet", and a stray keypress
            # must not silently reconfigure anything.
            self._mode, self._buffer = NORMAL, ""
            lower = key.lower()
            if lower == "q":
                self._running = False
            elif lower == "s":
                self._snooze_all(ringing)
            elif lower in ("d", "enter", "space"):
                self._dismiss_all(ringing)
            return

        if self._mode in (ENTER_TIME, ENTER_LABEL):
            self._type(key)
        elif self._mode == CONFIRM_CLEAR:
            self._confirm_clear(key)
        elif self._mode == SETTINGS:
            self._settings_key(key)
        else:
            self._normal(key)

    def _normal(self, key: str) -> None:
        lower = key.lower()
        if lower == "q":
            self._running = False
        elif lower in ("a", "n", "+"):
            self._mode, self._buffer, self._input_error = ENTER_TIME, "", ""
            self._say("")
        elif lower in ("up", "k"):
            self._move(-1)
        elif lower in ("down", "j"):
            self._move(1)
        elif lower in ("space", "t", "enter"):
            self._toggle()
        elif lower in ("d", "x", "delete", "backspace"):
            self._delete()
        elif lower == "s":
            self._snooze_next()
        elif lower == "u":
            self._undo_last()
        elif lower in ("o", ","):
            self._mode = SETTINGS
            self._say("")
        elif lower == "h":
            self._toggle_time_format()
        elif lower == "v":
            self._toggle_clock_style()
        elif lower == "c":
            if self._scheduler.has_alarms():
                self._mode = CONFIRM_CLEAR
            else:
                self._say("Nothing to clear.")

    # -- settings ---------------------------------------------------------

    def _settings(self) -> List[ui.Setting]:
        return [
            ui.Setting("Time format", TIME_FORMATS, 1 if self._h12 else 0),
            ui.Setting(
                "Clock type",
                tuple(style.capitalize() for style in CLOCK_STYLES),
                CLOCK_STYLES.index(self._clock_style),
            ),
        ]

    def _settings_key(self, key: str) -> None:
        lower = key.lower()
        count = len(self._settings())
        if lower in ("up", "k"):
            self._setting_index = (self._setting_index - 1) % count
        elif lower in ("down", "j"):
            self._setting_index = (self._setting_index + 1) % count
        elif lower in ("left", "right", "space", "h", "l"):
            # Every setting has two choices, so any of these flips it.
            if self._setting_index == 0:
                self._toggle_time_format()
            else:
                self._toggle_clock_style()
        elif lower in ("enter", "esc", "o", ",", "q"):
            self._mode = NORMAL
            self._say("Settings saved.", "ok")

    def _toggle_time_format(self) -> None:
        self._h12 = not self._h12
        self._say("Showing 12-hour time (AM/PM)." if self._h12 else "Showing 24-hour time.", "ok")

    def _toggle_clock_style(self) -> None:
        index = CLOCK_STYLES.index(self._clock_style)
        self._clock_style = CLOCK_STYLES[(index + 1) % len(CLOCK_STYLES)]
        self._say(f"Showing the {self._clock_style} clock.", "ok")

    def _type(self, key: str) -> None:
        if key == "esc":
            self._mode, self._buffer = NORMAL, ""
            self._say("Cancelled.")
        elif key == "backspace":
            self._buffer = self._buffer[:-1]
            self._input_error = ""
        elif key == "enter":
            self._submit()
        elif key == "space":
            if len(self._buffer) < MAX_INPUT:
                self._buffer += " "
        elif len(key) == 1 and key.isprintable() and len(self._buffer) < MAX_INPUT:
            self._buffer += key
            self._input_error = ""

    def _submit(self) -> None:
        now = self._clock.now()
        if self._mode == ENTER_TIME:
            if not self._buffer.strip():
                self._input_error = "Type a time first, or press Esc to cancel."
                return
            try:
                self._pending_time = parse_alarm_time(self._buffer, now)
            except ValueError as exc:
                self._input_error = str(exc)
                return
            self._mode, self._buffer = ENTER_LABEL, ""
            return

        assert self._pending_time is not None
        alarm = self._scheduler.add(self._pending_time, self._buffer.strip())
        self._mode, self._buffer, self._pending_time = NORMAL, "", None
        self._selected_id = alarm.id
        self._say(f"✓ Alarm #{alarm.id} set. {self._describe(alarm.fire_at, now)}.", "ok")

    def _confirm_clear(self, key: str) -> None:
        self._mode = NORMAL
        if key.lower() not in ("y", "enter"):
            self._say("Cancelled — nothing was deleted.")
            return
        removed = [self._scheduler.remove(alarm.id) for alarm in self._scheduler.list()]
        self._undo = removed
        self._say(f"Cleared {len(removed)} alarms. Press U to undo.", "warn")

    # -- actions ----------------------------------------------------------

    def _move(self, step: int) -> None:
        alarms = self._scheduler.list()
        index = self._selected_index(alarms)
        if index is None:
            return
        self._selected_id = alarms[max(0, min(len(alarms) - 1, index + step))].id

    def _toggle(self) -> None:
        alarm = self._selected_alarm()
        if alarm is None:
            self._say("No alarms yet — press A to add one.")
            return
        updated = self._scheduler.toggle(alarm.id)
        state = "on" if updated.enabled else "off"
        self._say(f"Alarm #{updated.id} ({self._fmt(updated.fire_at)}) turned {state}.", "ok")

    def _delete(self) -> None:
        alarms = self._scheduler.list()
        index = self._selected_index(alarms)
        if index is None:
            self._say("No alarms yet — press A to add one.")
            return
        alarm = self._scheduler.remove(alarms[index].id)
        self._undo = [alarm]
        remaining = self._scheduler.list()
        if remaining:
            self._selected_id = remaining[min(index, len(remaining) - 1)].id
        self._say(f"Deleted alarm #{alarm.id} ({self._fmt(alarm.fire_at)}). Press U to undo.", "warn")

    def _undo_last(self) -> None:
        if not self._undo:
            self._say("Nothing to undo.")
            return
        for alarm in self._undo:
            self._scheduler.restore(alarm)
        count = len(self._undo)
        self._selected_id = self._undo[0].id
        self._undo = []
        self._say("Restored 1 alarm." if count == 1 else f"Restored {count} alarms.", "ok")

    def _snooze_next(self) -> None:
        alarm = self._scheduler.next_due()
        if alarm is None:
            self._say("Nothing armed to snooze.")
            return
        updated = self._scheduler.snooze(alarm.id, DEFAULT_SNOOZE_MINUTES)
        self._say(f"Snoozed #{updated.id} to {self._fmt(updated.fire_at)}.", "ok")

    def _snooze_all(self, ringing: List[Alarm]) -> None:
        self._sound.stop()
        for alarm in ringing:
            self._scheduler.snooze(alarm.id, DEFAULT_SNOOZE_MINUTES)
        self._say(f"Snoozed for {DEFAULT_SNOOZE_MINUTES} minutes.", "ok")

    def _dismiss_all(self, ringing: List[Alarm]) -> None:
        self._sound.stop()
        for alarm in ringing:
            self._scheduler.remove(alarm.id)
        self._say("Dismissed." if len(ringing) == 1 else f"Dismissed {len(ringing)} alarms.", "ok")


def run_tui(
    scheduler: AlarmScheduler,
    clock: Clock,
    sound: Optional[AlarmSound] = None,
    console_factory: Callable[[], Console] = Console,
    h12: bool = False,
    clock_style: str = ui.DIGITAL,
) -> None:
    AlarmClockApp(
        scheduler, clock, console_factory(), sound, h12=h12, clock_style=clock_style
    ).run()
