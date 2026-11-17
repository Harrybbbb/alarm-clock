"""Forgiving time input for the live display.

The classic prompt keeps strict ``HH:MM``; the live display accepts the
ways people actually type a time — ``7:30``, ``730``, ``7pm``,
``19.45`` — plus relative times like ``+15`` or ``+2h``.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

HINT = "e.g. 7:30 · 19:45 · 7pm · 6:15am · +15 (minutes) · +2h"

_RELATIVE = re.compile(
    r"\+\s*(\d{1,4})\s*(h|hr|hrs|hours?|m|min|mins|minutes?)?",
)
_CLOCK = re.compile(r"(\d{1,2})(?:[:.]?(\d{2}))?(am|pm|a|p)?")


def _fail(text: str) -> ValueError:
    return ValueError(f"Couldn't read '{text}' as a time — try 7:30, 19:45, 7pm or +15")


def parse_alarm_time(text: str, now: datetime) -> time:
    """Turn what the user typed into a time of day.

    Relative input (``+15``, ``+2h``) is measured from ``now``. Raises
    ``ValueError`` with a friendly message for anything unreadable.
    """
    raw = text.strip()
    compact = raw.lower().replace(" ", "")
    if not compact:
        raise _fail(raw)

    relative = _RELATIVE.fullmatch(compact)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2) or "m"
        minutes = amount * 60 if unit.startswith("h") else amount
        if minutes <= 0 or minutes >= 24 * 60:
            raise ValueError("Relative alarms must be between +1 minute and +23h.")
        target = now + timedelta(minutes=minutes)
        return target.time().replace(microsecond=0)

    match = _CLOCK.fullmatch(compact)
    if not match:
        raise _fail(raw)
    # The optional separator means "730" and "1945" read as 7:30 and
    # 19:45, and a lone "7" as 7:00.
    hour_text, minute_text, meridiem = match.groups()
    hour = int(hour_text)
    minute = int(minute_text) if minute_text else 0

    if meridiem:
        if not 1 <= hour <= 12:
            raise _fail(raw)
        hour = hour % 12 + (12 if meridiem.startswith("p") else 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise _fail(raw)
    return time(hour, minute)
