"""The reconcile gate: env knob + weekday must both pass."""
from __future__ import annotations

from datetime import UTC, datetime

from services.page_builder.pipeline import _last_reconcile_date, _reconcile_due


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


def test_second_run_the_same_day_skips():
    sunday = datetime(2026, 7, 19, 14, 0, tzinfo=UTC)
    assert _reconcile_due(sunday, enabled=True, weekday=6, last_date="2026-07-19") is False
    # Last week's sweep doesn't block this week's.
    assert _reconcile_due(sunday, enabled=True, weekday=6, last_date="2026-07-12") is True


def test_marker_read_failure_runs_the_sweep():
    class Broken:
        def get_job_marker(self, name):
            raise RuntimeError("firestore down")
    assert _last_reconcile_date(Broken()) is None
