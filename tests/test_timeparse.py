"""The live display's forgiving time input."""

from datetime import datetime, time

import pytest

from alarm_clock.keyboard import decode_escape
from alarm_clock.timeparse import parse_alarm_time

NOW = datetime(2026, 9, 23, 8, 0, 30)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("07:30", time(7, 30)),
        ("7:30", time(7, 30)),
        ("730", time(7, 30)),
        ("0730", time(7, 30)),
        ("1945", time(19, 45)),
        ("19.45", time(19, 45)),
        ("7", time(7, 0)),
        ("7pm", time(19, 0)),
        ("7 PM", time(19, 0)),
        ("6:15am", time(6, 15)),
        ("12am", time(0, 0)),
        ("12pm", time(12, 0)),
        ("12:30a", time(0, 30)),
        ("  9:05  ", time(9, 5)),
    ],
)
def test_clock_times(text, expected):
    assert parse_alarm_time(text, NOW) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("+15", time(8, 15, 30)),
        ("+15m", time(8, 15, 30)),
        ("+ 15 min", time(8, 15, 30)),
        ("+2h", time(10, 0, 30)),
        ("+1 hour", time(9, 0, 30)),
    ],
)
def test_relative_times_count_from_now(text, expected):
    assert parse_alarm_time(text, NOW) == expected


@pytest.mark.parametrize(
    "text", ["", "abc", "25:00", "7:60", "13pm", "0am", "7:5", "+0", "+24h", "12345"]
)
def test_rejects_nonsense_with_a_friendly_message(text):
    with pytest.raises(ValueError):
        parse_alarm_time(text, NOW)


@pytest.mark.parametrize(
    "data, name",
    [
        (b"\x1b", "esc"),
        (b"\x1b[A", "up"),
        (b"\x1bOA", "up"),
        (b"\x1b[B", "down"),
        (b"\x1b[3~", "delete"),
        (b"\x1b[Z", "unknown"),
    ],
)
def test_escape_sequences_are_named(data, name):
    assert decode_escape(data) == name
