"""Tests for services.page_builder.selector.pick_authoring_candidates.

Every new or changed source without a recipe is queued for authoring —
except those a recipe owns, those already notified, those with no readable
data, and those under the date floor. `change_status` is sticky, so a
legacy page is only queued when CKAN actually moved past the version it was
built from.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.page_builder.selector import pick_authoring_candidates
from services.shared.firestore import SourceRecord

# Past the 2026-01-01 default floor so the age gate never interferes.
MODIFIED = datetime(2026, 5, 1, tzinfo=timezone.utc)
FLOOR_2025 = datetime(2025, 1, 1, tzinfo=timezone.utc)


class _FakeStore:
    """Honours `limit` and DESC `metadata_modified` ordering, like the real
    Firestore queries."""

    def __init__(self, sources: list[SourceRecord]):
        self._all = sorted(sources, key=lambda s: s.metadata_modified, reverse=True)
        self.failed_max_attempts = None

    def list_never_analyzed(self, limit: int = 50):
        return [s for s in self._all if s.analysis_status == "never"][:limit]

    def list_failed_retryable(self, limit: int = 50, max_attempts: int = 3):
        self.failed_max_attempts = max_attempts
        return [s for s in self._all
                if s.analysis_status == "failed" and s.failed_attempts < max_attempts][:limit]

    def iter_changed_sources(self):
        yield from (s for s in self._all if s.change_status in ("new", "updated"))


def _new(dataset_id, *, modified=MODIFIED, **kw) -> SourceRecord:
    return SourceRecord(id=dataset_id, title="חדש", metadata_modified=modified,
                        analysis_status=kw.pop("analysis_status", "never"),
                        change_status="new", **kw)


def _legacy(dataset_id, *, modified=MODIFIED, built_days_before=1, **kw) -> SourceRecord:
    built = modified - timedelta(days=built_days_before)
    return SourceRecord(
        id=dataset_id, title="ישן", metadata_modified=modified,
        analyzed_metadata_modified=kw.pop("analyzed_metadata_modified", built),
        last_analyzed_at=built,
        analysis_status=kw.pop("analysis_status", "succeeded"),
        page_path=f"datasets/{dataset_id}/", change_status="updated", **kw,
    )


def _ids(picks):
    return [(s.id, r) for s, r in picks]


def test_new_first_then_changed_legacy_pages():
    store = _FakeStore([_legacy("old", modified=MODIFIED + timedelta(days=3)),
                        _new("fresh")])
    assert _ids(pick_authoring_candidates(store, 10)) == [
        ("fresh", "new"), ("old", "legacy_updated")]


def test_failed_legacy_builds_are_new_regardless_of_attempts():
    store = _FakeStore([_new("parked", analysis_status="failed", failed_attempts=9)])
    assert _ids(pick_authoring_candidates(store, 10)) == [("parked", "new")]
    assert store.failed_max_attempts > 9


def test_any_newer_version_queues_a_legacy_page_no_gap():
    """The retired Track 2 waited 30 days; a page with no recipe can't be
    refreshed any other way, so one day newer is enough."""
    store = _FakeStore([_legacy("daily", built_days_before=1)])
    assert _ids(pick_authoring_candidates(store, 10)) == [("daily", "legacy_updated")]


def test_sticky_change_status_without_new_version_is_skipped():
    store = _FakeStore([_legacy("same", analyzed_metadata_modified=MODIFIED)])
    assert pick_authoring_candidates(store, 10) == []


def test_legacy_without_version_marker_falls_back_to_last_analyzed_at():
    src = _legacy("legacy", analyzed_metadata_modified=None, built_days_before=2)
    assert _ids(pick_authoring_candidates(_FakeStore([src]), 10)) == [
        ("legacy", "legacy_updated")]


def test_skips_recipe_owned_notified_and_unreadable_sources():
    store = _FakeStore([
        _new("has-recipe"),
        _new("notified", authoring_status="notified", authoring_issue=3),
        _new("restricted", analysis_status="restricted"),
        _legacy("gone", analysis_status="unavailable"),
        _legacy("owned"),
        _new("ok"),
    ])
    picks = pick_authoring_candidates(store, 10, exclude_ids=frozenset({"has-recipe", "owned"}))
    assert _ids(picks) == [("ok", "new")]


def test_needed_but_not_yet_notified_is_retried():
    """`needed` = the issue couldn't be opened (no token / API error);
    the next run must try again."""
    store = _FakeStore([_new("retry", authoring_status="needed")])
    assert _ids(pick_authoring_candidates(store, 10)) == [("retry", "new")]


def test_cap_bounds_picks():
    store = _FakeStore([_new(f"n{i}", modified=MODIFIED + timedelta(hours=i)) for i in range(5)])
    assert len(pick_authoring_candidates(store, 3)) == 3


def test_floor_gates_both_kinds():
    old = datetime(2024, 6, 1, tzinfo=timezone.utc)
    store = _FakeStore([_new("old-new", modified=old), _legacy("old-page", modified=old),
                        _new("in-2025", modified=datetime(2025, 3, 1, tzinfo=timezone.utc))])
    assert pick_authoring_candidates(store, 10) == []  # default floor 2026-01-01
    picks = pick_authoring_candidates(store, 10, min_modified_floor=FLOOR_2025,
                                      max_age_days=100000)
    assert _ids(picks) == [("in-2025", "new")]


def test_eligible_legacy_page_behind_many_skipped_rows_is_found():
    """The newest changed rows are mostly recipe'd daily-appenders; the
    stream must scan past them to the eligible tail."""
    base = MODIFIED + timedelta(days=30)
    owned = [_legacy(f"r{i}", modified=base + timedelta(seconds=i)) for i in range(300)]
    store = _FakeStore(owned + [_legacy("tail")])
    picks = pick_authoring_candidates(store, 10, exclude_ids=frozenset(s.id for s in owned))
    assert _ids(picks) == [("tail", "legacy_updated")]


def test_notified_backlog_does_not_starve_unnotified_new_sources():
    """Issues pile up faster than the routine solves them; hundreds of
    notified sources sorting ahead must not hide one that still needs one."""
    backlog = [_new(f"b{i}", modified=MODIFIED + timedelta(hours=i + 1),
                    authoring_status="notified", authoring_issue=i) for i in range(300)]
    store = _FakeStore(backlog + [_new("waiting")])
    assert _ids(pick_authoring_candidates(store, 5)) == [("waiting", "new")]
