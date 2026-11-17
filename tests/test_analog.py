"""The braille analog face."""

from datetime import datetime

import pytest

from alarm_clock import ui
from alarm_clock.analog import analog_clock

NOON = datetime(2026, 9, 23, 12, 0, 0)


@pytest.mark.parametrize("rows", [9, 11, 17])
def test_face_is_round_rows_tall_and_twice_as_wide(rows):
    lines = analog_clock(NOON, rows, ui.FACE).plain.split("\n")
    assert len(lines) == rows
    assert {len(line) for line in lines} == {rows * 2}


def test_face_shows_the_quarter_numerals():
    plain = analog_clock(datetime(2026, 9, 23, 4, 40, 20), 17, ui.FACE).plain
    for numeral in ("12", "3", "6", "9"):
        assert numeral in plain


def test_the_face_changes_as_time_passes():
    first = analog_clock(NOON, 17, ui.FACE).plain
    later = analog_clock(datetime(2026, 9, 23, 12, 0, 15), 17, ui.FACE).plain
    assert first != later


def test_a_tiny_size_is_clamped_instead_of_crashing():
    assert len(analog_clock(NOON, 2, ui.FACE).plain.split("\n")) == 7


def test_the_hands_point_the_right_way():
    """At 3:00:00 the hour hand points right, so the right half has more ink."""
    lines = analog_clock(datetime(2026, 9, 23, 3, 0, 0), 17, ui.FACE).plain.split("\n")
    middle = lines[8]
    left, right = middle[: len(middle) // 2], middle[len(middle) // 2 :]
    ink = lambda part: sum(1 for char in part if char not in " ")  # noqa: E731
    assert ink(right) > ink(left)
