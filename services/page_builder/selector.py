"""Pick which source(s) the builder should process on this tick.

Priority (first non-empty track wins):
    1. `analysis_status == "never"`, then `analysis_status == "failed"`
       with `failed_attempts < 3` (transient-failure auto-retry on
       subsequent daily runs; after 3 whole-run failures a source is
       parked until manually reset). Ordered by `metadata_modified` DESC.
    2. `change_status in {new, updated}` AND
       `metadata_modified` newer than `analyzed_metadata_modified`
       (null marker = legacy doc, treated as eligible) AND
       CKAN's `metadata_modified` is more than `reanalyze_gap_days` past
       `analyzed_metadata_modified` (falling back to `last_analyzed_at`
       when the version marker is null; both null = eligible).
       Ordered by CKAN `metadata_modified` DESC.

The `analyzed_metadata_modified` guard exists because `change_status` is
sticky: the scanner only writes it on NEW/UPDATED and nothing resets it
after a successful analysis, so without the guard every source ever
flagged `updated` would burn an agent run every cooldown period forever.

Both tracks are gated by an effective cutoff = `max(min_modified_floor,
now - max_age_days)`. A source is only eligible if its CKAN
`metadata_modified` is on/after that cutoff.

Two gates compose:
  - **Fixed floor** (`min_modified_floor`, default 2026-01-01): we don't
    publish pages for datasets last touched before this date, period.
    Anchors the corpus to the current era of gov.il data.
  - **Rolling window** (`max_age_days`, default 365): a source untouched
    for over a year is usually archival/abandoned, expensive to analyze,
    and unlikely to interest readers.

Both are overridable per run — the pipeline reads `MIN_MODIFIED_FLOOR`
(ISO date) and `MAX_AGE_DAYS` from the environment and passes them in, so
widening coverage one year at a time is a `gcloud run` env change rather
than a code redeploy. The defaults below are the fallback when unset.
Prod currently runs `MIN_MODIFIED_FLOOR=2025-01-01` with `MAX_AGE_DAYS`
set large enough to disable the rolling window, making the floor the sole
gate while we expand coverage incrementally.

With the default floor the floor wins (2026-01-01 is more recent than
now-365d). As time moves on, the rolling window would eventually overtake
the floor and become the binding constraint — at which point pages from
early 2026 start aging out naturally (unless the env overrides change the
calculus, as they do today).

Backlog of (recent) never-analyzed sources is drained first — re-analyzing
already-published pages because CKAN flagged them as `updated` waits
until every recent source has at least one page.

The re-analysis gap applies ONLY to Track 2 (already-analyzed sources
that CKAN just re-flagged as `updated`). A rebuild happens when the data
moved on meaningfully past the VERSION the page was built from: CKAN's
`metadata_modified` is more than `reanalyze_gap_days` (default 30) past
`analyzed_metadata_modified`. The baseline is the data version, not the
wall-clock time of our run — a page built today from January data
refreshes as soon as any newer version lands (the version jump is
months), while daily-append datasets self-limit to roughly one rebuild
per gap period (each rebuild resets the analyzed version to that day's
data).

The gap does NOT apply to:
  - Never-analyzed sources (Track 1): always eligible (within cutoff),
    no matter how recently their CKAN row changed.
  - Sources with a null `analyzed_metadata_modified`: legacy docs fall
    back to `last_analyzed_at`; null on both = always eligible.

Sources flagged `analysis_status == "unavailable"` by the reconcile sweep
are never re-selected in Track 2: their page is preserved as-is, and
re-running the agent against a removed/unreadable datastore resource
would just 403 and drop it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from services.shared.firestore import FirestoreStateStore, SourceRecord

log = logging.getLogger(__name__)

DEFAULT_REANALYZE_GAP_DAYS = 30
DEFAULT_MAX_AGE_DAYS = 365
MAX_FAILED_ATTEMPTS = 3
DEFAULT_MIN_MODIFIED_FLOOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
# Runaway guard for the Track-2 scan. `change_status` is sticky, so the
# candidate stream can approach the whole corpus; the DESC-order age_cutoff
# break is the real terminator, this only bounds a pathological run (e.g. a
# floor set so low nothing breaks). Well above the live corpus (~1.2k docs).
TRACK2_SCAN_CAP = 5000


def pick_next(
    store: FirestoreStateStore,
    n: int = 1,
    reanalyze_gap_days: int = DEFAULT_REANALYZE_GAP_DAYS,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    min_modified_floor: datetime = DEFAULT_MIN_MODIFIED_FLOOR,
    reanalyze: bool = True,
) -> list[SourceRecord]:
    now = datetime.now(timezone.utc)
    reanalyze_gap = timedelta(days=reanalyze_gap_days)
    age_cutoff = max(now - timedelta(days=max_age_days), _as_utc(min_modified_floor))
    picks: list[SourceRecord] = []
    seen: set[str] = set()

    # Track 1 — never analyzed AND `metadata_modified >= age_cutoff`.
    # Rows are ordered by `metadata_modified` DESC; once we hit one past
    # `age_cutoff` every remaining row is also too old, so we break. No
    # client-side skip filter exists in this track, so `limit=n` is exact.
    for src in store.list_never_analyzed(limit=n):
        if src.metadata_modified is None or _as_utc(src.metadata_modified) < age_cutoff:
            break
        picks.append(src)
        seen.add(src.id)
        if len(picks) >= n:
            return picks

    # Track 1b — failed sources still under the retry budget (transient
    # API flakes self-heal on the next daily run; 3 whole-run failures
    # park the source). Same age cutoff and ordering as Track 1.
    if len(picks) < n:
        for src in store.list_failed_retryable(limit=n - len(picks)):
            if src.id in seen:
                continue
            if src.metadata_modified is None or _as_utc(src.metadata_modified) < age_cutoff:
                break
            picks.append(src)
            seen.add(src.id)
            if len(picks) >= n:
                return picks

    # Track 2 — already analyzed, CKAN-updated well past our analysis
    # (update-vs-analysis gap > reanalyze_gap_days), within max_age.
    # `reanalyze=False` (env REANALYZE_ENABLED) pauses this track: until
    # structural-vs-additive change gating exists, datasets that append rows
    # daily re-qualify every cooldown period — a full agent run each, for a
    # page that barely changes. Track 1 (never analyzed) is unaffected.
    if reanalyze and len(picks) < n:
        # Stream (not a fixed window): a day's daily-appender updates —
        # recently rebuilt, so under the reanalyze gap — sort ahead of an
        # older-gap eligible source by `metadata_modified` DESC. A small
        # `limit` would fill entirely with those ineligible rows and starve
        # the eligible tail below them. `iter_changed_sources` pages lazily;
        # the `age_cutoff` break below (DESC order) is the natural terminator,
        # with TRACK2_SCAN_CAP as a pathological-run backstop.
        scanned = 0
        for src in store.iter_changed_sources():
            scanned += 1
            if scanned > TRACK2_SCAN_CAP:
                log.warning(
                    "track2 scan hit cap (%d) without filling quota "
                    "(%d/%d picked) — stopping",
                    TRACK2_SCAN_CAP, len(picks), n,
                )
                break
            if src.id in seen:
                continue
            # A source removed upstream (reconcile flagged it `unavailable`)
            # keeps its preserved snapshot page. Re-selecting it would run an
            # agent session whose prefetch 403s → `restricted` → the page is
            # dropped, undoing the preservation. Never rebuild it here; the
            # reconcile self-heal path returns it to `succeeded` if it comes
            # back.
            if src.analysis_status == "unavailable":
                continue
            if src.metadata_modified is None or _as_utc(src.metadata_modified) < age_cutoff:
                break
            # Failed rebuilds of a published page keep it `succeeded` (so the
            # page survives) but count against the retry budget; park it at 3
            # like Track 1b does, or it would burn an agent run every day.
            if src.failed_attempts >= MAX_FAILED_ATTEMPTS:
                continue
            # `change_status` is sticky — the scanner only writes it on
            # NEW/UPDATED and nothing resets it after analysis. Without
            # this guard, every source ever flagged `updated` would be
            # re-analyzed every cooldown period forever, even when CKAN
            # hasn't changed since the page was built. Legacy docs with
            # a null marker can't be compared — keep them eligible.
            if src.analyzed_metadata_modified is not None and _as_utc(
                src.metadata_modified
            ) <= _as_utc(src.analyzed_metadata_modified):
                continue
            # Rebuild only when the data moved on meaningfully past the
            # VERSION the page was built from: the new CKAN version is
            # > reanalyze_gap past `analyzed_metadata_modified`. The
            # baseline is the data version, not `last_analyzed_at` (when
            # we ran) — a page built today from January data must refresh
            # as soon as a newer version lands, not 30 days from the run.
            # Daily-append datasets still self-limit to ~one rebuild per
            # gap period (each rebuild resets the analyzed version).
            # Legacy docs missing the version marker fall back to
            # last_analyzed_at; missing both = always eligible.
            baseline = src.analyzed_metadata_modified or src.last_analyzed_at
            if baseline is None or (
                _as_utc(src.metadata_modified) - _as_utc(baseline)
                > reanalyze_gap
            ):
                picks.append(src)
                seen.add(src.id)
                if len(picks) >= n:
                    break

    return picks


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
