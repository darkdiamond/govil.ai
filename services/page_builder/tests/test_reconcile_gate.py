"""The reconcile gate: env knob + weekday must both pass."""
from __future__ import annotations

from datetime import UTC, datetime

from services.page_builder.pipeline import _reconcile_due, _reconciled_today


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



class _Marker:
    def __init__(self, last_date=None, broken=False):
        self.last_date, self.broken = last_date, broken

    def get_job_marker(self, name):
        if self.broken:
            raise RuntimeError("firestore down")
        return {"last_date": self.last_date} if self.last_date else {}


def test_second_run_the_same_day_skips():
    sunday = datetime(2026, 7, 19, 14, 0, tzinfo=UTC)
    assert _reconciled_today(_Marker("2026-07-19"), sunday) is True
    # Last week's sweep (or none yet) doesn't block this week's.
    assert _reconciled_today(_Marker("2026-07-12"), sunday) is False
    assert _reconciled_today(_Marker(), sunday) is False


def test_marker_read_failure_runs_the_sweep():
    sunday = datetime(2026, 7, 19, 14, 0, tzinfo=UTC)
    assert _reconciled_today(_Marker(broken=True), sunday) is False
