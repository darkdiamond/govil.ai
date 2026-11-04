"""The reconcile gate: env knob + weekday must both pass."""
from __future__ import annotations

from datetime import UTC, datetime

from services.page_builder.pipeline import _reconcile_due


def test_disabled_never_runs():
    # Sunday (weekday()==6) but knob off.
    sunday = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
    assert _reconcile_due(sunday, enabled=False, weekday=6) is False


def test_enabled_and_matching_weekday_runs():
    sunday = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)  # a Sunday
    assert sunday.weekday() == 6
    assert _reconcile_due(sunday, enabled=True, weekday=6) is True


def test_enabled_wrong_weekday_skips():
    monday = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)  # a Monday
    assert monday.weekday() == 0
    assert _reconcile_due(monday, enabled=True, weekday=6) is False
