"""Tests for services.page_builder.selector.pick_next.

Regression for the sticky `change_status` bug: the scanner only writes
`change_status` on NEW/UPDATED and nothing ever resets it after a
successful analysis, so a source flagged `updated` once stays in the
Track 2 candidate set forever. Track 2 must therefore skip sources whose
live CKAN `metadata_modified` hasn't advanced past the version already
analyzed (`analyzed_metadata_modified`) — otherwise every published page
gets a full agent re-run every cooldown period, forever.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from services.page_builder.selector import pick_next
from services.shared.firestore import SourceRecord

# Past the 2026-01-01 floor so the age gate never interferes.
MODIFIED = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _track2_src(
    dataset_id: str,
    *,
    metadata_modified: datetime = MODIFIED,
    analyzed_metadata_modified: datetime | None = None,
    last_analyzed_days_ago: int = 60,
) -> SourceRecord:
    return SourceRecord(
        id=dataset_id,
        title="מאגר לדוגמה",
        metadata_modified=metadata_modified,
        analyzed_metadata_modified=analyzed_metadata_modified,
        # Pinned relative to MODIFIED (not "now"): the Track 2 gate
        # compares metadata_modified against last_analyzed_at directly.
        last_analyzed_at=MODIFIED - timedelta(days=last_analyzed_days_ago),
        analysis_status="succeeded",
        change_status="updated",
    )


def _store(track2: list[SourceRecord]) -> MagicMock:
    store = MagicMock()
    store.list_never_analyzed.return_value = []
    store.list_failed_retryable.return_value = []
    store.list_changed_sources.return_value = track2
    store.iter_changed_sources.side_effect = lambda *a, **k: iter(track2)
    return store


class _FakeStore:
    """Store fake that honours `limit` and DESC ordering on the changed
    query — a MagicMock returning a fixed list regardless of `limit`
    can't expose the Track-2 window-truncation bug."""

    def __init__(self, changed: list[SourceRecord]):
        self._changed = sorted(
            changed, key=lambda s: s.metadata_modified, reverse=True
        )

    def list_never_analyzed(self, limit: int = 50) -> list[SourceRecord]:
        return []

    def list_failed_retryable(
        self, limit: int = 50, max_attempts: int = 3
    ) -> list[SourceRecord]:
        return []

    def list_changed_sources(self, limit: int = 50) -> list[SourceRecord]:
        return self._changed[:limit]

    def iter_changed_sources(self, batch_size: int = 200):
        yield from self._changed


def _changed_src(
    dataset_id: str, *, modified: datetime, gap_days: int
) -> SourceRecord:
    """A Track-2 candidate whose CKAN version (`modified`) sits `gap_days`
    past the version its page was built from."""
    return SourceRecord(
        id=dataset_id,
        title="מאגר לדוגמה",
        metadata_modified=modified,
        analyzed_metadata_modified=modified - timedelta(days=gap_days),
        last_analyzed_at=modified - timedelta(days=gap_days),
        analysis_status="succeeded",
        change_status="updated",
    )


def test_track2_finds_eligible_behind_many_ineligible_recent_updates():
    """A day's daily-appender updates (recently rebuilt → small gap →
    ineligible) sort ahead of an older-gap eligible source. The eligible
    one must still be selected even though it falls outside the old fixed
    Track-2 fetch window."""
    base = datetime(2026, 7, 21, 19, 0, tzinfo=timezone.utc)
    appenders = [
        _changed_src(f"appender-{i}", modified=base + timedelta(seconds=i), gap_days=9)
        for i in range(60)
    ]
    # More recent appenders sort first; the eligible source sits below the
    # 60-row run, past the (n*4)=20-row window the old code fetched.
    eligible = _changed_src(
        "eligible-old-gap", modified=base - timedelta(hours=1), gap_days=200
    )
    store = _FakeStore(appenders + [eligible])
    picks = pick_next(
        store, n=5, min_modified_floor=FLOOR_2025, max_age_days=100000
    )
    assert [s.id for s in picks] == ["eligible-old-gap"]


def test_track2_skips_source_already_analyzed_at_current_version():
    """metadata_modified == analyzed_metadata_modified ⇒ nothing changed
    since the page was built; the sticky `updated` flag must not trigger
    another agent run."""
    src = _track2_src("stale-flag", analyzed_metadata_modified=MODIFIED)
    assert pick_next(_store([src]), n=5) == []


def test_track2_picks_source_when_ckan_advanced_past_analysis():
    src = _track2_src(
        "really-updated",
        metadata_modified=MODIFIED + timedelta(days=40),
        analyzed_metadata_modified=MODIFIED,
    )
    picks = pick_next(_store([src]), n=5)
    assert [s.id for s in picks] == ["really-updated"]


def test_track2_legacy_source_without_analyzed_marker_stays_eligible():
    """Docs analyzed before `analyzed_metadata_modified` existed have it
    as None — we can't tell whether they changed, so keep old behavior."""
    src = _track2_src("legacy", analyzed_metadata_modified=None)
    picks = pick_next(_store([src]), n=5)
    assert [s.id for s in picks] == ["legacy"]


def test_reanalyze_false_pauses_track2_entirely():
    """REANALYZE_ENABLED=false stopgap: until structural-vs-additive change
    gating exists, daily-append datasets re-qualify every cooldown period;
    the knob lets us pause all Track 2 re-runs without touching Track 1."""
    src = _track2_src(
        "would-be-picked",
        metadata_modified=MODIFIED + timedelta(days=3),
        analyzed_metadata_modified=MODIFIED,
    )
    store = _store([src])
    assert pick_next(store, n=5, reanalyze=False) == []
    store.iter_changed_sources.assert_not_called()


def test_reanalyze_false_keeps_track1():
    never = SourceRecord(
        id="brand-new",
        title="חדש",
        metadata_modified=MODIFIED,
        analysis_status="never",
        change_status="new",
    )
    store = MagicMock()
    store.list_never_analyzed.return_value = [never]
    store.iter_changed_sources.side_effect = lambda *a, **k: iter([])
    picks = pick_next(store, n=5, reanalyze=False)
    assert [s.id for s in picks] == ["brand-new"]


def _gap_src(
    dataset_id: str, *, updated_days_after_analysis: int
) -> SourceRecord:
    """CKAN advanced past our build by the given number of days.

    `last_analyzed_at` is pinned relative to `metadata_modified` (not
    "now") — the gap gate compares the two directly.
    """
    analyzed_at = MODIFIED
    modified = analyzed_at + timedelta(days=updated_days_after_analysis)
    return SourceRecord(
        id=dataset_id,
        title="מאגר לדוגמה",
        metadata_modified=modified,
        analyzed_metadata_modified=analyzed_at,
        last_analyzed_at=analyzed_at,
        analysis_status="succeeded",
        change_status="updated",
    )


def test_track2_skips_update_soon_after_analysis():
    """Data updated 5 days after our build ⇒ page is still fresh enough;
    no rebuild (the gap gate, not a calendar cooldown, decides)."""
    src = _gap_src("small-gap", updated_days_after_analysis=5)
    assert pick_next(_store([src]), n=5) == []


def test_track2_picks_update_well_after_analysis():
    """Data moved on 40 days after our build ⇒ rebuild on the next run,
    regardless of how recently that update happened."""
    src = _gap_src("big-gap", updated_days_after_analysis=40)
    assert [s.id for s in pick_next(_store([src]), n=5)] == ["big-gap"]


def test_track2_gap_days_is_configurable():
    src = _gap_src("sixty-day-gap", updated_days_after_analysis=60)
    assert [s.id for s in pick_next(_store([src]), n=5)] == ["sixty-day-gap"]
    assert pick_next(_store([src]), n=5, reanalyze_gap_days=90) == []


def test_track2_gap_baseline_is_data_version_not_run_time():
    """Page built TODAY from January data: a new version landing days
    after our run must still trigger a rebuild — the gap is measured
    against the analyzed data version (months old), not against when we
    happened to run the analysis (days ago)."""
    analyzed_version = datetime(2026, 1, 10, tzinfo=timezone.utc)
    ran_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
    src = SourceRecord(
        id="backlog-page",
        title="מאגר לדוגמה",
        metadata_modified=ran_at + timedelta(days=5),  # new version, 5d after run
        analyzed_metadata_modified=analyzed_version,
        last_analyzed_at=ran_at,
        analysis_status="succeeded",
        change_status="updated",
    )
    assert [s.id for s in pick_next(_store([src]), n=5)] == ["backlog-page"]


def test_track2_gap_falls_back_to_run_time_for_legacy_docs():
    """No analyzed-version marker (legacy doc): the gap falls back to
    last_analyzed_at, so a fresh update right after a recent run waits."""
    ran_at = datetime(2026, 7, 15, tzinfo=timezone.utc)
    src = SourceRecord(
        id="legacy-fresh",
        title="מאגר לדוגמה",
        metadata_modified=ran_at + timedelta(days=5),
        analyzed_metadata_modified=None,
        last_analyzed_at=ran_at,
        analysis_status="succeeded",
        change_status="updated",
    )
    assert pick_next(_store([src]), n=5) == []


# The `min_modified_floor` / `max_age_days` gates are env-driven (the
# pipeline reads MIN_MODIFIED_FLOOR / MAX_AGE_DAYS and passes them in).
# These lock in the floor: a 2025 never-analyzed source is eligible once
# the floor drops to 2025-01-01, while a 2024 one stays excluded. A large
# max_age_days disables the rolling window so the floor is the sole gate
# (otherwise now-365d would clip early-2025 too).
FLOOR_2025 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _never_src(dataset_id: str, metadata_modified: datetime) -> SourceRecord:
    return SourceRecord(
        id=dataset_id,
        title="מאגר חדש",
        metadata_modified=metadata_modified,
        analysis_status="never",
        change_status="new",
    )


def test_floor_admits_2025_source_when_lowered():
    src = _never_src("y2025", datetime(2025, 3, 1, tzinfo=timezone.utc))
    store = MagicMock()
    store.list_never_analyzed.return_value = [src]
    store.list_failed_retryable.return_value = []
    store.iter_changed_sources.side_effect = lambda *a, **k: iter([])
    picks = pick_next(
        store, n=5, min_modified_floor=FLOOR_2025, max_age_days=100000
    )
    assert [s.id for s in picks] == ["y2025"]


def test_floor_still_excludes_2024_source():
    src = _never_src("y2024", datetime(2024, 12, 1, tzinfo=timezone.utc))
    store = MagicMock()
    store.list_never_analyzed.return_value = [src]
    store.list_failed_retryable.return_value = []
    store.iter_changed_sources.side_effect = lambda *a, **k: iter([])
    picks = pick_next(
        store, n=5, min_modified_floor=FLOOR_2025, max_age_days=100000
    )
    assert picks == []


def test_track2_skips_published_source_that_exhausted_retries():
    src = _changed_src("parked", modified=MODIFIED, gap_days=200)
    src.failed_attempts = 3
    store = _FakeStore([src])
    assert pick_next(store, n=5, min_modified_floor=FLOOR_2025, max_age_days=100000) == []
