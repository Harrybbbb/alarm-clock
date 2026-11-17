"""The render layer is pure, so it can be checked by reading the output."""

import io
from datetime import datetime

import pytest
from rich.align import Align
from rich.console import Console

from alarm_clock import ui
from alarm_clock.models import Alarm

NOW = datetime(2026, 9, 23, 7, 42, 18)
CREATED = datetime(2026, 9, 23, 7, 0)


def make_alarm(hour, minute, label="", enabled=True, snoozes=0, alarm_id=1):
    return Alarm(
        id=alarm_id,
        fire_at=datetime(2026, 9, 23, hour, minute),
        created_at=CREATED,
        label=label,
        enabled=enabled,
        snoozes=snoozes,
    )


def render(renderable, width=80):
    console = Console(width=width, record=True, force_terminal=False, legacy_windows=False)
    console.print(renderable)
    return console.export_text()


# -- big digits -----------------------------------------------------------

def test_big_text_is_five_rows_tall():
    assert len(ui.big_text("12:34").plain.split("\n")) == ui.GLYPH_HEIGHT


def test_big_text_renders_every_digit_and_the_colon():
    plain = ui.big_text("0123456789:").plain
    assert "█" in plain
    assert plain.count("\n") == ui.GLYPH_HEIGHT - 1


def test_big_text_rows_are_all_the_same_width():
    rows = ui.big_text("07:42:18").plain.split("\n")
    assert len({len(row) for row in rows}) == 1


def test_big_text_does_not_crash_on_unknown_characters():
    """A stray character must never take the whole display down."""
    assert "?" not in ui.big_text("1?2").plain


# -- countdown formatting -------------------------------------------------

@pytest.mark.parametrize(
    "seconds, expected",
    [
        (-5, "now"),
        (0, "now"),
        (42, "42 sec"),
        (60, "1 min"),
        (18 * 60, "18 min"),
        (59 * 60, "59 min"),
        (60 * 60, "1h 00m"),
        (2 * 3600 + 5 * 60, "2h 05m"),
        (25 * 3600, "1d 1h"),
    ],
)
def test_format_countdown(seconds, expected):
    assert ui.format_countdown(seconds) == expected


# -- progress bar ---------------------------------------------------------

@pytest.mark.parametrize("fraction, filled", [(0.0, 0), (0.5, 12), (1.0, 24)])
def test_progress_bar_fills_proportionally(fraction, filled):
    assert ui.progress_bar(fraction, width=24).plain.count("█") == filled


def test_progress_bar_is_always_its_full_width():
    for fraction in (-1.0, 0.0, 0.33, 1.0, 2.0):
        assert len(ui.progress_bar(fraction, width=24).plain) == 24


# -- day labelling --------------------------------------------------------

def test_describe_when():
    assert ui.describe_when(datetime(2026, 9, 23, 9, 0), NOW) == "today"
    assert ui.describe_when(datetime(2026, 9, 24, 6, 0), NOW) == "tomorrow"
    assert ui.describe_when(datetime(2026, 9, 23, 7, 0), NOW) == "overdue"


# -- panels ---------------------------------------------------------------

def test_clock_panel_shows_the_next_alarm_and_its_countdown():
    output = render(ui.clock_panel(NOW, make_alarm(8, 0, "Morning")))
    assert "08:00" in output
    assert "Morning" in output
    assert "17 min" in output


def test_clock_panel_says_so_when_nothing_is_armed():
    assert "No alarms set" in render(ui.clock_panel(NOW, None))


def test_alarm_table_marks_enabled_disabled_and_overdue():
    alarms = [
        make_alarm(8, 0, "Morning", alarm_id=1),
        make_alarm(22, 0, "Sleep", enabled=False, alarm_id=2),
        make_alarm(7, 0, "Missed", alarm_id=3),
    ]
    output = render(ui.alarm_table(alarms, NOW))
    assert "ON" in output and "OFF" in output and "DUE" in output
    assert "ringing now" in output


def test_alarm_table_shows_the_snooze_count():
    output = render(ui.alarm_table([make_alarm(8, 0, "Morning", snoozes=3)], NOW))
    assert "snoozed ×3" in output


def test_alarm_table_prompts_when_empty():
    assert "to add one" in render(ui.alarm_table([], NOW))


def test_alarm_table_does_not_lose_an_unlabelled_alarm():
    assert "08:00" in render(ui.alarm_table([make_alarm(8, 0)], NOW))


def test_footer_swaps_to_ringing_keys():
    assert "Dismiss" in render(ui.footer(ringing=True))
    assert "Add" in render(ui.footer(ringing=False))


def test_banner_names_every_ringing_alarm():
    output = render(ui.banner([make_alarm(8, 0, "Morning", alarm_id=1),
                               make_alarm(8, 0, "Standup", alarm_id=2)]))
    assert "Morning" in output and "Standup" in output
    assert "2 ALARMS RINGING" in output


def test_alarm_table_marks_the_selected_row():
    alarms = [make_alarm(8, 0, "Morning", alarm_id=1), make_alarm(9, 0, "Gym", alarm_id=2)]
    lines = render(ui.alarm_table(alarms, NOW, selected=1)).split("\n")
    gym = next(line for line in lines if "Gym" in line)
    morning = next(line for line in lines if "Morning" in line)
    assert "❯" in gym and "❯" not in morning


def test_alarm_table_shows_how_long_until_each_alarm():
    assert "in 17 min" in render(ui.alarm_table([make_alarm(8, 0, "Morning")], NOW))


def test_prompt_panel_shows_what_was_typed_and_the_preview():
    prompt = ui.Prompt(title="New alarm", label="What time?", value="7:3", preview="✓ Rings")
    output = render(ui.prompt_panel(prompt))
    assert "7:3" in output and "✓ Rings" in output and "Esc" in output


def test_dashboard_swaps_key_hints_for_an_open_prompt():
    prompt = ui.Prompt(title="New alarm", label="What time?")
    output = render(ui.dashboard([], NOW, None, prompt=prompt))
    assert "What time?" in output
    assert "Clear all" not in output


def test_dashboard_stays_a_centred_column_on_a_wide_terminal():
    output = render(ui.dashboard([make_alarm(8, 0, "Morning")], NOW, None), width=200)
    widest = max(len(line.strip()) for line in output.split("\n"))
    assert widest <= ui.APP_WIDTH


def test_big_clock_doubles_up_when_there_is_room():
    wide = render(ui.BigClock("08:08:08"), width=80).split("\n")
    narrow = render(ui.BigClock("08:08:08"), width=40).split("\n")
    assert max(len(line.strip()) for line in wide) == ui.big_text_width("08:08:08", 2)
    assert max(len(line.strip()) for line in narrow) <= 40


def test_banner_is_singular_for_one_alarm():
    assert "ALARM RINGING" in render(ui.banner([make_alarm(8, 0, "Morning")]))


# -- the whole screen -----------------------------------------------------

def test_dashboard_draws_clock_alarms_and_keys():
    alarms = [make_alarm(8, 0, "Morning")]
    output = render(ui.dashboard(alarms, NOW, alarms[0], message="Added alarm #1"))
    assert "ALARM CLOCK" in output
    assert "Morning" in output
    assert "Added alarm #1" in output
    assert "Quit" in output


def test_dashboard_shows_the_alert_only_while_ringing():
    alarms = [make_alarm(7, 0, "Missed")]
    calm = render(ui.dashboard(alarms, NOW, alarms[0]))
    loud = render(ui.dashboard(alarms, NOW, alarms[0], ringing=alarms))
    assert "RINGING" not in calm
    assert "RINGING" in loud


def test_dashboard_fits_a_narrow_terminal_without_wrapping():
    """80 columns is the floor we promise to render in."""
    alarms = [make_alarm(8, 0, "A fairly long alarm label here")]
    for line in render(ui.dashboard(alarms, NOW, alarms[0]), width=80).split("\n"):
        assert len(line) <= 80


# -- regression: the big clock must not wobble as the digits change -------

def rendered_rows(renderable, width=90):
    """Exact rendered lines with padding kept.

    ``export_text`` strips trailing whitespace, which is the very thing
    that broke the clock — so alignment has to be measured through
    ``render_lines``, which doesn't.
    """
    console = Console(width=width, file=io.StringIO(), force_terminal=True)
    return [
        "".join(segment.text for segment in line)
        for line in console.render_lines(renderable, pad=True)
    ]


@pytest.mark.parametrize("second", range(60))
def test_big_clock_rows_stay_aligned_for_every_second(second):
    """Rich strips trailing spaces before justifying a line.

    Glyphs 2, 5 and 6 each have a row ending in a space, so centring
    each line individually shifted those rows one column left — the
    clock visibly broke 18 seconds out of every 60.
    """
    text = f"23:14:{second:02d}"
    drawn = [row for row in rendered_rows(Align.center(ui.big_text(text))) if "█" in row]
    assert len(drawn) == ui.GLYPH_HEIGHT

    offsets = set()
    for row_index, drawn_row in enumerate(drawn):
        glyph_row = " ".join(
            ui._GLYPHS.get(char, ui._GLYPHS[" "])[row_index] for char in text
        )
        indent = len(glyph_row) - len(glyph_row.lstrip(" "))
        offsets.add(drawn_row.index("█") - indent)
    assert len(offsets) == 1, f"rows drawn at different columns: {sorted(offsets)}"


@pytest.mark.parametrize("digit", "0123456789")
def test_every_digit_keeps_its_row_widths(digit):
    rows = ui._GLYPHS[digit]
    assert len({len(row) for row in rows}) == 1
    assert len(rows) == ui.GLYPH_HEIGHT


# -- 12/24-hour display ---------------------------------------------------

@pytest.mark.parametrize(
    "hour, minute, h24, h12",
    [
        (0, 5, "00:05", "12:05 AM"),
        (7, 30, "07:30", "7:30 AM"),
        (12, 0, "12:00", "12:00 PM"),
        (19, 45, "19:45", "7:45 PM"),
        (23, 59, "23:59", "11:59 PM"),
    ],
)
def test_format_time(hour, minute, h24, h12):
    moment = datetime(2026, 9, 23, hour, minute)
    assert ui.format_time(moment) == h24
    assert ui.format_time(moment, h12=True) == h12


def test_big_clock_digits_follow_the_format():
    moment = datetime(2026, 9, 23, 19, 5, 9)
    assert ui.clock_digits(moment) == "19:05:09"
    assert ui.clock_digits(moment, h12=True) == "7:05:09"
    assert ui.clock_digits(datetime(2026, 9, 23, 0, 0), h12=True) == "12:00:00"


def test_dashboard_in_12_hour_mode_shows_am_pm_everywhere():
    alarms = [make_alarm(19, 30, "Dinner")]
    output = render(ui.dashboard(alarms, NOW, alarms[0], h12=True))
    assert "7:30 PM" in output
    assert "AM" in output  # NOW is 07:42, shown beside the date
    assert "19:30" not in output


def test_dashboard_defaults_to_24_hour():
    alarms = [make_alarm(19, 30, "Dinner")]
    output = render(ui.dashboard(alarms, NOW, alarms[0]))
    assert "19:30" in output and "PM" not in output


# -- analog face and settings ---------------------------------------------

def test_analog_dashboard_shows_the_face_and_the_exact_time():
    output = render(ui.dashboard([], NOW, None, clock_style=ui.ANALOG))
    assert any("⠀" <= char <= "⣿" for char in output)
    assert "07:42:18" in output
    assert "Wednesday, 23 September 2026" in output


def test_analog_in_12_hour_mode_says_am_or_pm():
    output = render(ui.dashboard([], NOW, None, clock_style=ui.ANALOG, h12=True))
    assert "7:42:18 AM" in output


def test_analog_face_shrinks_on_a_short_terminal():
    tall = render(ui.dashboard([], NOW, None, clock_style=ui.ANALOG, height=60))
    short = render(ui.dashboard([], NOW, None, clock_style=ui.ANALOG, height=30))
    braille = lambda out: sum(  # noqa: E731
        1 for line in out.split("\n") if any("⠀" <= c <= "⣿" for c in line)
    )
    assert braille(short) < braille(tall)


def test_settings_panel_lists_each_setting_and_its_choices():
    settings = [
        ui.Setting("Time format", ("24-hour", "12-hour"), 0),
        ui.Setting("Clock type", ("Digital", "Analog"), 1),
    ]
    output = render(ui.dashboard([], NOW, None, settings=settings))
    for text in ("Settings", "Time format", "12-hour", "Clock type", "Analog"):
        assert text in output
    assert "Clear all" not in output  # replaces the key hints
