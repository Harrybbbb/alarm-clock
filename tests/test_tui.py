"""Key handling, exercised without a terminal.

Every interaction happens through ``_dispatch``, so feeding it keys
covers the whole decision tree.
"""

import io
from datetime import datetime, time

from rich.console import Console

from alarm_clock.clock import FakeClock
from alarm_clock.scheduler import AlarmScheduler
from alarm_clock.tui import AlarmClockApp

NOW = datetime(2026, 9, 23, 8, 0)


class ScriptedApp(AlarmClockApp):
    """An app driven by keypresses, with no terminal attached."""

    def __init__(self):
        clock = FakeClock(NOW)
        super().__init__(
            AlarmScheduler(clock),
            clock,
            console=Console(file=io.StringIO(), width=80),
        )

    def press(self, *keys):
        for key in keys:
            self._dispatch(key)
        return self

    def type(self, text):
        """Type ``text`` into the inline box and press Enter."""
        return self.press(*text, "\r")

    def add(self, when, label=""):
        return self.press("a").type(when).type(label)

    def screen(self):
        console = Console(width=100, height=40, record=True, file=io.StringIO())
        console.print(self._render())
        return console.export_text()

    @property
    def scheduler(self):
        return self._scheduler

    @property
    def message(self):
        return self._message

    @property
    def clock(self):
        return self._clock

    def labels(self):
        return [alarm.label for alarm in self.scheduler.list()]


# -- adding ---------------------------------------------------------------

def test_a_adds_an_alarm_with_a_label():
    app = ScriptedApp().add("09:30", "standup")
    alarm = app.scheduler.list()[0]
    assert (alarm.fire_at, alarm.label) == (datetime(2026, 9, 23, 9, 30), "standup")
    assert "Alarm #1 set" in app.message
    assert "in 1h 30m" in app.message


def test_a_accepts_an_empty_label():
    app = ScriptedApp().add("09:30", "")
    assert app.scheduler.list()[0].label == ""


def test_labels_can_contain_spaces_and_the_letters_used_as_keys():
    app = ScriptedApp().add("9:30", "quit doing stuff")
    assert app.labels() == ["quit doing stuff"]
    assert app._running is True


def test_relaxed_time_formats_are_accepted():
    app = ScriptedApp().add("7pm").add("730").add("+15")
    times = sorted(alarm.fire_at for alarm in app.scheduler.list())
    assert times == [
        datetime(2026, 9, 23, 8, 15),
        datetime(2026, 9, 23, 19, 0),
        datetime(2026, 9, 24, 7, 30),
    ]


def test_a_bad_time_keeps_the_box_open_with_an_error():
    app = ScriptedApp().press("a").type("99:99")
    assert app.scheduler.has_alarms() is False
    assert app._mode == "time"
    assert "Couldn't read" in app.screen()


def test_the_time_box_previews_when_the_alarm_will_ring():
    app = ScriptedApp().press("a", *"9:30")
    assert "Rings today at 09:30" in app.screen()


def test_backspace_edits_what_was_typed():
    app = ScriptedApp().press("a", *"9:45", "\x7f", "\x7f", *"30", "\r", "\r")
    assert app.scheduler.list()[0].fire_at == datetime(2026, 9, 23, 9, 30)


def test_escape_cancels_adding():
    app = ScriptedApp().press("a", *"9:30", "esc")
    assert app.scheduler.has_alarms() is False
    assert app._mode == "normal"


def test_escape_at_the_label_step_also_cancels():
    app = ScriptedApp().press("a").type("9:30").press("esc")
    assert app.scheduler.has_alarms() is False


# -- selecting, toggling, deleting ----------------------------------------

def test_arrow_keys_move_the_selection():
    app = ScriptedApp().add("9:00", "a").add("10:00", "b").add("11:00", "c")
    app.press("up", "up", "up")
    assert app._selected_alarm().label == "a"
    app.press("down", "down", "down", "down")
    assert app._selected_alarm().label == "c"


def test_space_toggles_the_selected_alarm():
    app = ScriptedApp().add("9:00", "a").add("10:00", "b").press("up", " ")
    assert [alarm.enabled for alarm in app.scheduler.list()] == [False, True]
    assert "turned off" in app.message
    app.press(" ")
    assert app.scheduler.list()[0].enabled is True


def test_d_deletes_the_selected_alarm_and_u_undoes_it():
    app = ScriptedApp().add("9:00", "a").add("10:00", "b").press("up", "d")
    assert app.labels() == ["b"]
    assert "Press U to undo" in app.message
    app.press("u")
    assert app.labels() == ["a", "b"]


def test_delete_with_no_alarms_says_so():
    app = ScriptedApp().press("d")
    assert "No alarms yet" in app.message


def test_new_alarms_become_selected():
    app = ScriptedApp().add("11:00", "late").add("9:00", "early")
    assert app._selected_alarm().label == "early"


# -- snooze ---------------------------------------------------------------

def test_s_snoozes_the_next_alarm():
    app = ScriptedApp().add("09:30", "standup").press("s")
    alarm = app.scheduler.list()[0]
    assert alarm.fire_at == datetime(2026, 9, 23, 8, 5)  # five minutes from now
    assert alarm.snoozes == 1


def test_s_with_nothing_armed_says_so():
    app = ScriptedApp().press("s")
    assert "Nothing armed" in app.message


# -- clear ----------------------------------------------------------------

def test_c_clears_everything_after_confirmation_and_can_be_undone():
    app = ScriptedApp().add("09:30", "a").add("10:30", "b").press("c", "y")
    assert app.scheduler.has_alarms() is False
    assert "Cleared 2 alarms" in app.message
    app.press("u")
    assert app.labels() == ["a", "b"]


def test_c_keeps_everything_when_not_confirmed():
    app = ScriptedApp().add("09:30", "a").press("c", "n")
    assert app.scheduler.has_alarms() is True
    assert "Cancelled" in app.message


def test_c_with_no_alarms_does_not_ask():
    app = ScriptedApp().press("c")
    assert app._mode == "normal"


# -- quitting -------------------------------------------------------------

def test_q_stops_the_loop():
    app = ScriptedApp()
    assert app._running is True
    app.press("q")
    assert app._running is False


def test_keys_are_case_insensitive():
    app = ScriptedApp().press("A").type("9:30").type("")
    assert app.scheduler.has_alarms() is True


def test_an_unrecognised_key_is_ignored():
    app = ScriptedApp().press("z", "7", "!")
    assert app.message == ""
    assert app._running is True


# -- while an alarm is ringing --------------------------------------------

def ringing_app():
    app = ScriptedApp().add("09:00", "wake up")
    app.clock.advance(seconds=3600)  # 09:00 — the alarm is now due
    assert app.scheduler.due_now(), "expected the alarm to be ringing"
    return app


def test_ringing_s_snoozes_and_stops_the_alert():
    app = ringing_app().press("s")
    assert app.scheduler.due_now() == []
    assert app.scheduler.list()[0].fire_at == datetime(2026, 9, 23, 9, 5)


def test_ringing_d_dismisses_the_alarm_for_good():
    app = ringing_app().press("d")
    assert app.scheduler.has_alarms() is False
    assert "Dismissed" in app.message


def test_ringing_enter_also_dismisses():
    assert ringing_app().press("\r").scheduler.has_alarms() is False


def test_ringing_ignores_keys_that_would_reconfigure_the_alarm():
    """A stray 'a' or 'c' must not quietly change things mid-alert."""
    app = ringing_app().press("a", "c", "t")
    assert app._mode == "normal"
    assert app.scheduler.has_alarms() is True
    assert app.scheduler.due_now() != []


def test_ringing_interrupts_a_half_typed_alarm():
    app = ScriptedApp().add("09:00", "wake up").press("a", *"10")
    app.clock.advance(seconds=3600)
    app.press("s")
    assert app._mode == "normal"
    assert app.scheduler.list()[0].snoozes == 1


def test_ringing_q_still_quits():
    app = ringing_app().press("q")
    assert app._running is False


def test_two_alarms_due_at_once_are_dismissed_together():
    app = ScriptedApp().add("09:00", "one").add("09:00", "two")
    app.clock.advance(seconds=3600)
    assert len(app.scheduler.due_now()) == 2
    app.press("d")
    assert app.scheduler.has_alarms() is False
    assert "Dismissed 2 alarms" in app.message


# -- the bell -------------------------------------------------------------

class CountingConsole(Console):
    bells = 0

    def bell(self):
        CountingConsole.bells += 1


def test_the_bell_rings_once_per_second_not_once_per_frame():
    CountingConsole.bells = 0
    clock = FakeClock(NOW)
    app = AlarmClockApp(
        AlarmScheduler(clock), clock, console=CountingConsole(file=io.StringIO())
    )
    app._scheduler.add(time(9, 0))
    clock.advance(seconds=3600)  # due

    for _ in range(8):  # eight frames inside the same second
        app._render()
    assert CountingConsole.bells == 1

    clock.advance(seconds=1)
    app._render()
    assert CountingConsole.bells == 2


def test_no_bell_when_nothing_is_ringing():
    CountingConsole.bells = 0
    clock = FakeClock(NOW)
    app = AlarmClockApp(
        AlarmScheduler(clock), clock, console=CountingConsole(file=io.StringIO())
    )
    app._scheduler.add(time(9, 0))
    for _ in range(8):
        app._render()
    assert CountingConsole.bells == 0


# -- audible alarm --------------------------------------------------------

class FakeSound:
    """Stands in for AlarmSound, recording what the app asked of it."""

    def __init__(self, available=True):
        self.available = available
        self.plays = 0
        self.stops = 0
        self.playing = False

    def ensure_playing(self):
        self.plays += 1
        self.playing = True

    def stop(self):
        self.stops += 1
        self.playing = False


def app_with_sound(sound, console=None):
    clock = FakeClock(NOW)
    app = AlarmClockApp(
        AlarmScheduler(clock),
        clock,
        console=console if console is not None else Console(file=io.StringIO()),
        sound=sound,
    )
    app._scheduler.add(time(9, 0), "wake up")
    return app, clock


def test_the_sound_starts_when_an_alarm_comes_due():
    sound = FakeSound()
    app, clock = app_with_sound(sound)
    app._render()
    assert sound.plays == 0  # nothing due yet

    clock.advance(seconds=3600)
    app._render()
    assert sound.playing is True


def test_the_sound_is_nudged_every_frame_so_a_short_clip_loops():
    sound = FakeSound()
    app, clock = app_with_sound(sound)
    clock.advance(seconds=3600)
    for _ in range(5):
        app._render()
    assert sound.plays == 5


def test_dismissing_silences_the_alarm_immediately():
    sound = FakeSound()
    app, clock = app_with_sound(sound)
    clock.advance(seconds=3600)
    app._render()
    app._dispatch("d")
    assert sound.playing is False
    assert sound.stops >= 1


def test_snoozing_silences_the_alarm_immediately():
    sound = FakeSound()
    app, clock = app_with_sound(sound)
    clock.advance(seconds=3600)
    app._render()
    app._dispatch("s")
    assert sound.playing is False


def test_the_sound_stops_once_nothing_is_ringing():
    sound = FakeSound()
    app, clock = app_with_sound(sound)
    clock.advance(seconds=3600)
    app._render()
    app._dispatch("d")
    app._render()
    assert sound.playing is False


def test_the_bell_is_only_used_when_no_sound_is_available():
    """With real audio there's no reason to also rattle the terminal."""
    CountingConsole.bells = 0
    audible = FakeSound(available=True)
    app, clock = app_with_sound(audible, console=CountingConsole(file=io.StringIO()))
    clock.advance(seconds=3600)
    for _ in range(4):
        app._render()
    assert CountingConsole.bells == 0
    assert audible.plays == 4

    CountingConsole.bells = 0
    silent = FakeSound(available=False)
    app, clock = app_with_sound(silent, console=CountingConsole(file=io.StringIO()))
    clock.advance(seconds=3600)
    for _ in range(4):
        app._render()
    assert CountingConsole.bells == 1  # once per second, not per frame
    assert silent.plays == 0


# -- 12/24-hour switch ----------------------------------------------------

def test_h_switches_between_12_and_24_hour():
    app = ScriptedApp().add("19:30", "dinner")
    assert "19:30" in app.screen()
    app.press("h")
    assert "7:30 PM" in app.screen()
    assert "12-hour" in app.message
    app.press("H")
    assert "19:30" in app.screen()
    assert "24-hour" in app.message


def test_messages_use_the_chosen_format():
    app = ScriptedApp().press("h").add("7pm", "dinner")
    assert "7:00 PM" in app.message


def test_h_is_just_a_letter_while_typing_a_label():
    app = ScriptedApp().add("9:00", "hello")
    assert app.labels() == ["hello"]
    assert app._h12 is False


# -- settings -------------------------------------------------------------

def test_o_opens_settings_and_escape_closes_them():
    app = ScriptedApp().press("o")
    assert "Time format" in app.screen()
    app.press("esc")
    assert app._mode == "normal"
    assert "Time format" not in app.screen()


def test_settings_change_the_time_format():
    app = ScriptedApp().add("19:30", "dinner").press("o", "right", "enter")
    assert "7:30 PM" in app.screen()


def test_settings_change_the_clock_type():
    app = ScriptedApp().press("o", "down", "space")
    assert app._clock_style == "analog"
    app.press("left")
    assert app._clock_style == "digital"


def test_the_selection_wraps_around_the_settings_list():
    app = ScriptedApp().press("o", "up", " ")
    assert app._clock_style == "analog"


def test_v_switches_the_clock_type_directly():
    app = ScriptedApp().press("v")
    assert app._clock_style == "analog"
    assert any("⠀" <= c <= "⣿" for c in app.screen())


def test_an_alarm_ringing_closes_the_settings():
    app = ScriptedApp().add("09:00", "wake up").press("o")
    app.clock.advance(seconds=3600)
    app.press("s")
    assert app._mode == "normal"
    assert app.scheduler.list()[0].snoozes == 1
