"""Time-of-day gates for hourly job ticks, read in Israel time.

Two env-driven questions a run asks before doing a sub-step:
- `due_this_hour(env)`: is this Israel-time hour in the env's comma list
  (`6,11,16`)? Unset/empty = every run (today's behaviour).
- `in_quiet_window(env)`: is now inside a weekly window like `fri15-sat21`
  (start inclusive, end exclusive, may wrap the week)? Unset = never.

A malformed value never stops a run: it logs a warning and answers the
default (due / not quiet). Stdlib only, so every layer can use it.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

log = logging.getLogger("shared.schedule")

IL_TZ = ZoneInfo("Asia/Jerusalem")
_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")  # Python weekday order
_WINDOW = re.compile(r"^(mon|tue|wed|thu|fri|sat|sun)(\d{1,2})-(mon|tue|wed|thu|fri|sat|sun)(\d{1,2})$")


def _il(now: datetime | None) -> datetime:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(IL_TZ)


def due_this_hour(env_name: str, now: datetime | None = None) -> bool:
    """Whether the current Israel-time hour is listed in env `env_name`
    (comma list of hours 0-23). Unset or empty: True. Malformed: True + warning."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return True
    try:
        hours = {int(p) for p in raw.split(",") if p.strip()}
    except ValueError:
        hours = set()
    if not hours or any(h < 0 or h > 23 for h in hours):
        log.warning("malformed %s=%r (want a comma list of hours 0-23); treating as due",
                    env_name, raw)
        return True
    return _il(now).hour in hours


def in_quiet_window(env_name: str = "QUIET_WINDOW", now: datetime | None = None) -> bool:
    """Whether now (Israel time) falls in the weekly window in env `env_name`,
    e.g. `fri15-sat21`: from Friday 15:00 (inclusive) to Saturday 21:00
    (exclusive). The window may wrap the week (`sat22-mon2`). Unset or empty:
    False. Malformed (or an empty window): False + warning."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return False
    m = _WINDOW.match(raw.lower())
    if m:
        start_h, end_h = int(m.group(2)), int(m.group(4))
        if start_h <= 23 and end_h <= 24:
            start = _DAYS.index(m.group(1)) * 24 + start_h
            end = _DAYS.index(m.group(3)) * 24 + end_h
            week = 7 * 24
            start, end = start % week, end % week
            if start != end:
                il = _il(now)
                t = il.weekday() * 24 + il.hour + il.minute / 60 + il.second / 3600
                if start < end:
                    return start <= t < end
                return t >= start or t < end
    log.warning("malformed %s=%r (want e.g. fri15-sat21); treating as not quiet",
                env_name, raw)
    return False
