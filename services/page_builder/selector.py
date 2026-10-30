"""Pick which sources need a recipe authored (the daily authoring queue).

Pages are produced only by recipes (services/page_builder/refresh.py). A
source without one is queued for authoring — a `needs-authoring` GitHub
issue, solved by the daily local Claude Code routine — when:

    `new`             it has no page yet: `analysis_status` is `never`, or
                      `failed` (a legacy agent build that never landed).
    `legacy_updated`  it has a legacy (agent-built) page and CKAN advanced
                      past the version that page was built from:
                      `metadata_modified > analyzed_metadata_modified`
                      (legacy docs missing the marker fall back to
                      `last_analyzed_at`; both null = eligible). No gap:
                      any newer version means the page is stale, and only
                      a recipe can refresh it now.

Never queued: sources a recipe owns (`exclude_ids`), sources whose issue is
already recorded (`authoring_status == "notified"`), and `restricted` /
`unavailable` sources (no readable data to author against).

Both kinds are gated by an effective cutoff = `max(min_modified_floor,
now - max_age_days)`: a source is only eligible if its CKAN
`metadata_modified` is on/after it.
  - **Fixed floor** (`min_modified_floor`, default 2026-01-01): we don't
    publish pages for datasets last touched before this date, period.
  - **Rolling window** (`max_age_days`, default 365): a source untouched
    for over a year is usually archival/abandoned.
The pipeline reads `MIN_MODIFIED_FLOOR` (ISO date) and `MAX_AGE_DAYS` from
the environment and passes them in. Prod runs `MIN_MODIFIED_FLOOR=2025-01-01`
with `MAX_AGE_DAYS` large enough to disable the rolling window.

`change_status` is sticky (the scanner only writes it on NEW/UPDATED and
nothing resets it), so the `legacy_updated` stream compares versions rather
than trusting the flag.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from services.shared.firestore import FirestoreStateStore, SourceRecord

log = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 365
DEFAULT_MIN_MODIFIED_FLOOR = datetime(2026, 1, 1, tzinfo=timezone.utc)
# Runaway guard for every candidate scan. `change_status` is sticky, so the
# changed stream can approach the whole corpus; the DESC-order age_cutoff
# break is the real terminator, this only bounds a pathological run (e.g. a
# floor set so low nothing breaks). Well above the live corpus (~1.2k docs).
SCAN_CAP = 5000
# `failed` docs are a closed legacy set (nothing writes `failed` any more);
# listed with no attempt budget so parked ones get a recipe too.
_ANY_ATTEMPTS = 1 << 30
_NO_DATA_STATUSES = ("restricted", "unavailable")


def pick_authoring_candidates(
    store: FirestoreStateStore,
    n: int,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    min_modified_floor: datetime = DEFAULT_MIN_MODIFIED_FLOOR,
    exclude_ids: frozenset[str] = frozenset(),
) -> list[tuple[SourceRecord, str]]:
    """Up to `n` `(source, reason)` pairs, `new` first, newest CKAN
    change first within each kind."""
    now = datetime.now(timezone.utc)
    age_cutoff = max(now - timedelta(days=max_age_days), _as_utc(min_modified_floor))
    picks: list[tuple[SourceRecord, str]] = []
    seen: set[str] = set()

    def _skip(src: SourceRecord) -> bool:
        return (
            src.id in seen
            or src.id in exclude_ids
            or src.authoring_status == "notified"
            or src.analysis_status in _NO_DATA_STATUSES
            # Provider docs exist only for a recipe (sync reads source.json);
            # one whose recipe was deleted has nothing to author from.
            or bool(getattr(src, "provider", None))
        )

    def _too_old(src: SourceRecord) -> bool:
        return src.metadata_modified is None or _as_utc(src.metadata_modified) < age_cutoff

    # New: no page yet. Rows are ordered by `metadata_modified` DESC, so the
    # first one past the cutoff ends each list. Not a `n`-sized window:
    # notified sources (an open issue the routine hasn't solved yet) pile up
    # ahead of unnotified ones and would fill it.
    for rows in (
        store.list_never_analyzed(limit=SCAN_CAP),
        store.list_failed_retryable(limit=SCAN_CAP, max_attempts=_ANY_ATTEMPTS),
    ):
        for src in rows:
            if _skip(src):
                continue
            if _too_old(src):
                break
            picks.append((src, "new"))
            seen.add(src.id)
            if len(picks) >= n:
                return picks

    # Legacy pages whose data moved on. Streamed (not a fixed window): the
    # newest rows are mostly recipe'd daily-appenders, which a small `limit`
    # would fill with and starve the eligible tail below them.
    scanned = 0
    for src in store.iter_changed_sources():
        scanned += 1
        if scanned > SCAN_CAP:
            log.warning(
                "authoring scan hit cap (%d) without filling quota (%d/%d) — stopping",
                SCAN_CAP, len(picks), n,
            )
            break
        if _skip(src) or not src.page_path:
            continue
        if _too_old(src):
            break
        baseline = src.analyzed_metadata_modified or src.last_analyzed_at
        if baseline is not None and _as_utc(src.metadata_modified) <= _as_utc(baseline):
            continue
        picks.append((src, "legacy_updated"))
        seen.add(src.id)
        if len(picks) >= n:
            break

    return picks


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
