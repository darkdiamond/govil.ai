"""The status vocabulary of `sources/<id>` and of a pipeline run, as StrEnums,
plus a typed view of a source's refresh state.

A StrEnum member *is* its string value: it compares, hashes, formats and
JSON/Firestore-encodes as the plain string, so stored documents, logs and run
summaries are byte-identical to the literals they replace, and tests can keep
comparing to strings. Light at import (stdlib only).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class AnalysisStatus(StrEnum):
    """`analysis_status`: whether the source has a live page (legacy name,
    from the retired agent builder; `mark_refreshed` still writes it)."""
    NEVER = "never"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"  # legacy; nothing writes it any more
    RESTRICTED = "restricted"  # CKAN datastore 403s: data access-restricted
    UNAVAILABLE = "unavailable"  # removed upstream (reconcile sweep)


# A source whose data can't be read: never refreshed, never queued.
NO_DATA_STATUSES = frozenset({AnalysisStatus.RESTRICTED, AnalysisStatus.UNAVAILABLE})


class AuthoringStatus(StrEnum):
    """`authoring_status`: the needs-authoring queue."""
    NEEDED = "needed"
    NOTIFIED = "notified"  # an issue is recorded; the daily queue skips it
    DONE = "done"


class RefreshStatus(StrEnum):
    """`refresh_status`: the last recipe refresh."""
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OutcomeStatus(StrEnum):
    """`RefreshOutcome.status`: what one refresh did this run."""
    REFRESHED = "refreshed"
    UNCHANGED = "unchanged"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY_LATER = "retry_later"


class SkipReason(StrEnum):
    """A skipped `RefreshOutcome.reason` (the provider ones carry the
    provider's key: `provider_disabled:boi_sdmx`)."""
    PROVIDER_DISABLED = "provider_disabled"    # not enabled for this run
    PROVIDER_INVALID = "provider_invalid"      # enabled, but its settings don't validate
    PROVIDER_UNHEALTHY = "provider_unhealthy"  # its healthcheck failed this run


class UnchangedReason(StrEnum):
    """`unchanged_reason` / an unchanged `RefreshOutcome.reason`: which
    precheck found the data bump a no-op (REFRESH_PRECHECK)."""
    FINGERPRINT = "fingerprint"      # A ∧ A′: no export, the bump stays pending
    INPUTS_HASH = "inputs_hash"      # B: exported inputs byte-identical
    CONTENT_HASH = "content_hash"    # C: rendered page byte-identical
    # A pending fingerprint-skipped bump not re-probed this run: same
    # metadata_modified, probed less than REFRESH_REPROBE_MIN_HOURS ago.
    # Outcome only (nothing is written, so never stored).
    RECENTLY_PROBED = "recently_probed"


class FailReason(StrEnum):
    """`refresh_reason` / a failed `RefreshOutcome.reason`."""
    RECIPE_FAILED = "recipe_failed"
    SCHEMA_CHANGED = "schema_changed"
    TOO_LARGE = "too_large"
    GEOMETRY_STALE = "geometry_stale"
    DOWNLOAD_BLOCKED = "download_blocked"
    FETCH_FAILED = "fetch_failed"
    SANDBOX_FAILED = "sandbox_failed"
    # `sandbox_failed` repeated REFRESH_TRANSIENT_STRIKES runs: the platform
    # (image, seccomp, fork) is broken, not the recipe. Opens an issue.
    SANDBOX_BROKEN = "sandbox_broken"
    RESTRICTED = "restricted"
    ERROR = "error"
    STAGE_FAILED = "stage_failed"
    RECIPE_INVALID = "recipe_invalid"


class AuthoringReason(StrEnum):
    """`authoring_reason`: why a needs-authoring issue was opened."""
    RECIPE_FAILED = "recipe_failed"
    SCHEMA_CHANGED = "schema_changed"
    TOO_LARGE = "too_large"
    GEOMETRY_STALE = "geometry_stale"
    DOWNLOAD_BLOCKED = "download_blocked"
    SANDBOX_BROKEN = "sandbox_broken"
    NEW = "new"  # no page yet
    LEGACY_UPDATED = "legacy_updated"  # an agent-built page whose data moved on
    GSC_TRAFFIC = "gsc_traffic"  # a legacy page with search traffic (by hand)
    MAP_AVAILABLE = "map_available"  # map_backfill: a downloadable map file


class RunStatus(StrEnum):
    """`pipeline_summary.status`."""
    OK = "ok"
    IDLE = "idle"
    DRY_RUN = "dry_run"
    REFRESH_UNAVAILABLE = "refresh_unavailable"
    REFRESH_FAILED = "refresh_failed"
    PUBLISH_FAILED = "publish_failed"
    SCAN_FAILED = "scan_failed"
    AUTHORING_FAILED = "authoring_failed"
    RECONCILE_FAILED = "reconcile_failed"
    SKIPPED_OVERLAP = "skipped_overlap"  # another execution holds the run lease
    SKIPPED_QUIET = "skipped_quiet"      # inside QUIET_WINDOW (e.g. Shabbat)


class NewsRunStatus(StrEnum):
    """`news_summary.status` (services/news/run.py). All but OK/IDLE/DISABLED and
    the two SKIPPED_* exit non-zero."""
    OK = "ok"
    IDLE = "idle"
    DISABLED = "disabled"                # NEWS_PUBLISH or news_state/control is not "live"
    SKIPPED_QUIET = "skipped_quiet"      # inside QUIET_WINDOW: nothing read or written
    SKIPPED_OVERLAP = "skipped_overlap"  # another run holds news_state/lock
    FAILED = "failed"
    LLM_UNAVAILABLE = "llm_unavailable"  # the model key was refused
    STORE_FAILED = "store_failed"        # an accepted story the store failed to save


class ArticleKind(StrEnum):
    """News `articles/<slug>.kind` (missing = NEWS: every article before kinds)."""
    NEWS = "news"          # a fresh period that moved (signals → editor)
    FEATURE = "feature"    # an explainer on a high-demand dataset (the daily floor's fill)
    DIGEST = "digest"      # the weekly roundup of small moves


class StoryResult(StrEnum):
    """What became of one news brief (`run._Day.write_one`)."""
    PUBLISHED = "published"
    REJECTED = "rejected"        # gates or critic said no: an editorial decision
    MODEL_ERROR = "model_error"  # the model service failed after retries: never judged
    STORE_ERROR = "store_error"  # accepted, but the store failed to save it
    # the weekly digest only (`news_summary.digest.status`)
    DIGEST_SKIPPED = "skipped"            # already written this week, or too few items
    POOL_UNREADABLE = "pool_unreadable"   # the signal pool couldn't be read


@dataclass
class RefreshState:
    """The refresh fields of a `sources/<id>` doc (all optional; absent = None).

    Read from the same snapshot as the rest of the `SourceRecord`, so the
    refresh needs one Firestore read per source. Values are the stored ones,
    unconverted (statuses stay plain strings).
    """
    refresh_status: str | None = None
    refresh_reason: str | None = None
    refresh_error: str | None = None
    refresh_failed_version: str | None = None
    unchanged_reason: str | None = None
    authoring_status: str | None = None
    authoring_reason: str | None = None
    input_fingerprint: str | None = None
    file_fingerprint: str | None = None
    inputs_hash: str | None = None
    inputs_hash_unordered: str | None = None
    content_hash: str | None = None
    recipe_version: int | None = None
    wall_budget_strikes: int | None = None
    # When the current run of wall-budget strikes started (REFRESH_STRIKE_MIN_HOURS).
    wall_budget_strikes_since: datetime | None = None
    authoring_issue: int | None = None
    transient_strikes: dict | None = None
    # Per `transient_strikes` key: when that run of strikes started.
    transient_strikes_since: dict | None = None
    # The last fingerprint skip's probe (REFRESH_REPROBE_MIN_HOURS): when, the
    # source version it probed, and a key of the recipe + resources it saw.
    probed_at: datetime | None = None
    probed_metadata_modified: datetime | None = None
    probed_key: str | None = None
    last_snapshot: dict | None = None
    agent_data: dict | None = None
    refreshed_metadata_modified: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_verified_at: datetime | None = None
    last_unchanged_at: datetime | None = None
    last_refresh_attempt_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RefreshState:
        """From a source doc's fields; other keys are ignored."""
        data = data or {}
        return cls(**{f.name: data.get(f.name) for f in dataclasses.fields(cls)})
