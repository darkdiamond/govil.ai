"""services/shared/schedule: hour lists and the weekly quiet window, in
Israel time (IDT = UTC+3 in summer, IST = UTC+2 in winter)."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from services.shared.schedule import due_this_hour, in_quiet_window

# 2026-11-13 is a Friday in winter (IST, UTC+2); 2026-07-17 is a Friday in
# summer (IDT, UTC+3).
WINTER_FRI = (2026, 11, 13)
WINTER_SAT = (2026, 11, 14)
SUMMER_FRI = (2026, 7, 17)
SUMMER_SAT = (2026, 7, 18)


def _il(ymd, hh, mm, offset):
    """An Israel wall-clock time as the UTC instant (offset = hours ahead of UTC)."""
    return datetime(*ymd, hh, mm, tzinfo=UTC) - timedelta(hours=offset)


@pytest.mark.parametrize("fri, sat, offset", [(WINTER_FRI, WINTER_SAT, 2),
                                              (SUMMER_FRI, SUMMER_SAT, 3)])
def test_quiet_window_edges(monkeypatch, fri, sat, offset):
    monkeypatch.setenv("QUIET_WINDOW", "fri15-sat21")
    assert in_quiet_window(now=_il(fri, 14, 59, offset)) is False
    assert in_quiet_window(now=_il(fri, 15, 0, offset)) is True
    assert in_quiet_window(now=_il(sat, 20, 59, offset)) is True
    assert in_quiet_window(now=_il(sat, 21, 0, offset)) is False


def test_quiet_window_uses_israel_time_not_utc(monkeypatch):
    monkeypatch.setenv("QUIET_WINDOW", "fri15-sat21")
    # 13:30 UTC on a summer Friday is 16:30 in Israel: quiet.
    assert in_quiet_window(now=datetime(2026, 7, 17, 13, 30, tzinfo=UTC)) is True
    # 12:30 UTC is 15:30 IDT too; 11:59 UTC is 14:59 IDT: not yet.
    assert in_quiet_window(now=datetime(2026, 7, 17, 11, 59, tzinfo=UTC)) is False


def test_quiet_window_may_wrap_the_week(monkeypatch):
    monkeypatch.setenv("QUIET_WINDOW", "sat22-mon2")
    sun_noon_il = datetime(2026, 11, 15, 10, 0, tzinfo=UTC)  # Sunday 12:00 IST
    mon_3_il = datetime(2026, 11, 16, 1, 0, tzinfo=UTC)      # Monday 03:00 IST
    assert in_quiet_window(now=sun_noon_il) is True
    assert in_quiet_window(now=mon_3_il) is False


def test_quiet_window_unset_and_malformed(monkeypatch, caplog):
    now = _il(WINTER_SAT, 12, 0, 2)
    monkeypatch.delenv("QUIET_WINDOW", raising=False)
    assert in_quiet_window(now=now) is False
    for bad in ("friday-saturday", "fri25-sat21", "fri15", "fri15-fri15"):
        monkeypatch.setenv("QUIET_WINDOW", bad)
        with caplog.at_level(logging.WARNING, logger="shared.schedule"):
            caplog.clear()
            assert in_quiet_window(now=now) is False
            assert "QUIET_WINDOW" in caplog.text


def test_quiet_window_custom_env_name(monkeypatch):
    monkeypatch.setenv("NEWS_QUIET", "FRI15-SAT21")
    assert in_quiet_window("NEWS_QUIET", now=_il(WINTER_SAT, 12, 0, 2)) is True


def test_due_this_hour_unset_is_always_due(monkeypatch):
    monkeypatch.delenv("X_HOURS", raising=False)
    assert due_this_hour("X_HOURS", now=_il(WINTER_FRI, 3, 0, 2)) is True
    monkeypatch.setenv("X_HOURS", "  ")
    assert due_this_hour("X_HOURS", now=_il(WINTER_FRI, 3, 0, 2)) is True


@pytest.mark.parametrize("offset, ymd", [(2, WINTER_FRI), (3, SUMMER_FRI)])
def test_due_this_hour_reads_israel_hours(monkeypatch, offset, ymd):
    monkeypatch.setenv("X_HOURS", "6, 11,16")
    assert due_this_hour("X_HOURS", now=_il(ymd, 6, 0, offset)) is True
    assert due_this_hour("X_HOURS", now=_il(ymd, 11, 59, offset)) is True
    assert due_this_hour("X_HOURS", now=_il(ymd, 7, 0, offset)) is False
    assert due_this_hour("X_HOURS", now=_il(ymd, 16, 25, offset)) is True


@pytest.mark.parametrize("bad", ["six", "6;11", "24", "-1", ","])
def test_due_this_hour_malformed_is_due_with_a_warning(monkeypatch, caplog, bad):
    monkeypatch.setenv("X_HOURS", bad)
    with caplog.at_level(logging.WARNING, logger="shared.schedule"):
        assert due_this_hour("X_HOURS", now=_il(WINTER_FRI, 3, 0, 2)) is True
    assert "X_HOURS" in caplog.text
