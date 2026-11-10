"""Firestore state store — shared between scanner + builder.

Collections:
    sources/{dataset_id}   — per-dataset state (scanner's CKAN facts + the
                             builder's refresh / authoring state)
    scan_runs/{run_id}     — one document per scan

The client picks up credentials from `GOOGLE_APPLICATION_CREDENTIALS` or the
runtime's default service account. When `FIRESTORE_EMULATOR_HOST` is set,
the firestore SDK talks to the local emulator and the project ID can be any
string.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from services.shared.states import (
    AnalysisStatus,
    AuthoringStatus,
    RefreshState,
    RefreshStatus,
)

SOURCES_COLL = "sources"
SCAN_RUNS_COLL = "scan_runs"
# Small per-job markers, one doc each (`job_state/reconcile`: last sweep date).
JOB_STATE_COLL = "job_state"


def _count(query) -> int:
    """Run a Firestore .count() aggregation; return 0 on empty result."""
    result = query.count().get()
    if not result or not result[0]:
        return 0
    return int(result[0][0].value)


@dataclass
class SourceRecord:
    """In-memory view of a `sources/{id}` document."""

    id: str
    name: str = ""
    title: str = ""
    slug: str = ""
    notes: str | None = None
    organization: dict = field(default_factory=dict)
    license_title: str | None = None
    update_frequency: str | None = None
    tags: list[str] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    record_count: int | None = None
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None

    first_seen_at: datetime | None = None
    last_scanned_at: datetime | None = None
    change_status: str = "unchanged"

    last_analyzed_at: datetime | None = None
    # Source's metadata_modified at the last successful render — the data
    # vintage the live page is based on. Distinct from `metadata_modified`,
    # which is the *live* CKAN value and gets overwritten on every scan.
    # Written by `mark_refreshed` (legacy pages keep what the retired agent
    # builder wrote). The publisher falls back to
    # `min(metadata_modified, last_analyzed_at)` for legacy docs that
    # succeeded before this field existed.
    analyzed_metadata_modified: datetime | None = None
    last_analyzed_version: int = 0
    analysis_status: str = AnalysisStatus.NEVER
    last_error: str | None = None
    page_path: str | None = None
    # Failed builds of the retired agent builder (legacy; reset on a
    # restricted source re-enabling). `list_failed_retryable` filters on it.
    failed_attempts: int = 0

    # UTC timestamp the reconcile sweep first flagged the source as removed
    # upstream. Set by mark_source_unavailable, cleared by
    # clear_source_unavailable. None while the source is available.
    unavailable_since: datetime | None = None

    # Per-dataset interpretive fields (summary_he, dataset_kind, related_ids, …).
    # Written by a successful recipe refresh (legacy pages keep what the
    # retired agent builder wrote); consumed by the publisher to write
    # `agent_data.json`.
    agent_data: dict | None = None

    # Authoring queue (refresh state lives on the prod source doc):
    # `notified` = a needs-authoring issue is recorded, so the nightly
    # queue skips the source instead of re-asking every day.
    authoring_status: str | None = None
    authoring_issue: int | None = None

    # Non-CKAN sources (services/providers): the provider key, the page
    # shell's credit block (SourcePresentation) and the readable slug suffix.
    # All None for data.gov.il datasets.
    provider: str | None = None
    source_url: str | None = None
    presentation: dict | None = None
    page_slug_suffix: str | None = None

    # Titles CKAN renamed this dataset away from (save_dataset). Each one was
    # a page URL; the publisher redirects them to the current one.
    previous_titles: list[str] = field(default_factory=list)

    # The refresh state, from the same snapshot (one read per source).
    refresh: RefreshState = field(default_factory=RefreshState)

    @classmethod
    def from_doc(cls, doc) -> SourceRecord:
        data: dict[str, Any] = doc.to_dict() or {}
        return cls(
            id=doc.id,
            name=data.get("name", "") or "",
            title=data.get("title", "") or "",
            slug=data.get("slug", "") or "",
            notes=data.get("notes"),
            organization=data.get("organization") or {},
            license_title=data.get("license_title"),
            update_frequency=data.get("update_frequency"),
            tags=data.get("tags") or [],
            resources=data.get("resources") or [],
            record_count=data.get("record_count"),
            metadata_created=data.get("metadata_created"),
            metadata_modified=data.get("metadata_modified"),
            first_seen_at=data.get("first_seen_at"),
            last_scanned_at=data.get("last_scanned_at"),
            change_status=data.get("change_status", "unchanged"),
            last_analyzed_at=data.get("last_analyzed_at"),
            analyzed_metadata_modified=data.get("analyzed_metadata_modified"),
            last_analyzed_version=int(data.get("last_analyzed_version") or 0),
            analysis_status=data.get("analysis_status", AnalysisStatus.NEVER),
            last_error=data.get("last_error"),
            page_path=data.get("page_path"),
            failed_attempts=int(data.get("failed_attempts") or 0),
            agent_data=data.get("agent_data"),
            unavailable_since=data.get("unavailable_since"),
            authoring_status=data.get("authoring_status"),
            authoring_issue=data.get("authoring_issue"),
            provider=data.get("provider"),
            source_url=data.get("source_url"),
            presentation=data.get("presentation"),
            page_slug_suffix=data.get("page_slug_suffix"),
            previous_titles=data.get("previous_titles") or [],
            refresh=RefreshState.from_dict(data),
        )


class FirestoreStateStore:
    """Thin wrapper around `google.cloud.firestore.Client` with the methods
    the scanner + builder need. Prefer this over raw `firestore.Client()` so
    that collection names and field names stay in one place.
    """

    def __init__(
        self,
        project_id: str | None = None,
        database: str = "(default)",
        client: firestore.Client | None = None,
    ):
        self.project_id = (
            project_id
            or os.getenv("FIRESTORE_PROJECT_ID")
            or os.getenv("GOOGLE_CLOUD_PROJECT")
            or "govdata-il"
        )
        self.database = database
        self.client = client or firestore.Client(project=self.project_id, database=database)

    # ---- Scanner surface -------------------------------------------------

    def get_scan_state(
        self, dataset_id: str
    ) -> tuple[datetime | None, str | None]:
        """Return `(metadata_modified, analysis_status)` in a single read.

        Used by the scanner's ChangeDetector so it can both decide
        new/updated/unchanged AND notice a `restricted` doc that has
        reappeared in CKAN search — without a second Firestore read per
        dataset. A missing doc returns `(None, None)`.
        """
        snap = self.client.collection(SOURCES_COLL).document(dataset_id).get()
        if not snap.exists:
            return None, None
        data = snap.to_dict() or {}
        return data.get("metadata_modified"), data.get("analysis_status")

    def save_dataset(self, dataset, change_status: str) -> None:
        """Upsert a `sources/{id}` document. Preserves analyzer fields."""
        now = datetime.now(UTC)
        ref = self.client.collection(SOURCES_COLL).document(dataset.id)
        snap = ref.get()

        resources = [
            {
                "id": r.id,
                "name": r.name,
                "format": r.format,
                "url": r.url,
                "size": r.size,
                "last_modified": r.last_modified,
                "description": r.description,
                "datastore_active": getattr(r, "datastore_active", False),
                "hash": getattr(r, "hash", None),
            }
            for r in dataset.resources
        ]

        org: dict | None = None
        if dataset.organization:
            org = {
                "id": dataset.organization.id,
                "name": dataset.organization.name,
                "title": dataset.organization.title,
                "logo_url": dataset.organization.logo_url,
            }

        payload: dict[str, Any] = {
            "id": dataset.id,
            "name": dataset.name,
            "title": dataset.title,
            "slug": getattr(dataset, "slug", "") or "",
            "notes": dataset.notes,
            "organization": org,
            "license_title": dataset.license_title,
            "update_frequency": dataset.update_frequency,
            "tags": dataset.tags,
            "resources": resources,
            "record_count": getattr(dataset, "record_count", None),
            "metadata_created": dataset.metadata_created,
            "metadata_modified": dataset.metadata_modified,
            "last_scanned_at": now,
            "change_status": change_status,
        }

        # The scanner leaves record_count unassigned when it couldn't ask CKAN
        # (a transient failure); keep the stored count instead of nulling it.
        fields_set = getattr(dataset, "model_fields_set", None)
        if snap.exists and fields_set is not None and "record_count" not in fields_set:
            del payload["record_count"]

        old = (snap.to_dict() or {}) if snap.exists else {}
        # The page URL is built from the title (publish._build_page_slugs), so
        # a CKAN rename moves the page. Keep every old title: the publisher
        # 301s each one's URL to the current page (publish.dataset_slug_redirects).
        if old.get("title") and old["title"] != dataset.title:
            payload["previous_titles"] = firestore.ArrayUnion([old["title"]])

        if not snap.exists:
            payload["first_seen_at"] = now
            payload["analysis_status"] = AnalysisStatus.NEVER
            payload["last_analyzed_version"] = 0
            payload["last_analyzed_at"] = None
            payload["last_error"] = None
            payload["page_path"] = None
        elif old.get("analysis_status") == AnalysisStatus.RESTRICTED:
            # The dataset is back in CKAN's public search after having been
            # access-restricted (a datastore 403 parked it, in the retired
            # agent builder). Re-enable it: clear the exclusion so the
            # authoring queue sees it again. The scanner's change detector forces a re-save
            # for restricted docs (see ChangeDetector.detect_status), so this
            # branch fires even when CKAN's metadata_modified is unchanged.
            payload["analysis_status"] = AnalysisStatus.NEVER
            payload["last_error"] = None
            payload["failed_attempts"] = 0
        # Deliberately no analogous branch for `analysis_status == "unavailable"`
        # here: CKAN re-listing the package only means it's back in the public
        # search results, not that its datastore resource is readable again.
        # `unavailable` is set exclusively by the reconcile probe (which
        # actually checks datastore readability) and self-heals via
        # `clear_source_unavailable`. Flipping it on scan-reappearance could
        # clear the "removed" banner while the explorer still gets a 403.

        ref.set(payload, merge=True)

    def get_provider_sync_state(self, dataset_id: str) -> dict:
        """The fields the provider sync's listing-key skip reads (empty when
        the doc doesn't exist)."""
        snap = self.client.collection(SOURCES_COLL).document(dataset_id).get(
            field_paths=["provider_listing_key", "provider_verified_at", "resources"])
        return (snap.to_dict() or {}) if snap.exists else {}

    def save_provider_source(self, dataset_id: str, payload: dict) -> bool:
        """Upsert a provider dataset's `sources/{id}` doc (services/providers/
        sync.py) — the counterpart of `save_dataset` for non-CKAN sources.

        `metadata_modified` is the version the refresh compares, and no
        provider supplies one, so it moves to now only when a resource's
        content hash changed (or a resource came or went). Returns whether it
        moved. Analyzer/refresh fields are preserved, as in `save_dataset`.
        """
        now = datetime.now(UTC)
        ref = self.client.collection(SOURCES_COLL).document(dataset_id)
        snap = ref.get()
        old = (snap.to_dict() or {}) if snap.exists else {}

        def _hashes(resources) -> dict:
            return {r.get("id"): r.get("hash") for r in resources or []}

        changed = not snap.exists or _hashes(old.get("resources")) != _hashes(payload["resources"])
        doc: dict[str, Any] = {
            **payload,
            "id": dataset_id,
            "last_scanned_at": now,
            "change_status": ("new" if not snap.exists else "updated") if changed else "unchanged",
            "metadata_modified": now if changed else old.get("metadata_modified"),
        }
        # Same as save_dataset: a renamed source.json title moves the page URL.
        if old.get("title") and old["title"] != payload.get("title"):
            doc["previous_titles"] = firestore.ArrayUnion([old["title"]])
        if not snap.exists:
            doc.update(
                metadata_created=now,
                first_seen_at=now,
                analysis_status=AnalysisStatus.NEVER,
                last_analyzed_version=0,
                last_analyzed_at=None,
                last_error=None,
                page_path=None,
            )
        ref.set(doc, merge=True)
        return changed

    # ---- job_state -------------------------------------------------------

    def get_job_marker(self, name: str) -> dict:
        snap = self.client.collection(JOB_STATE_COLL).document(name).get()
        return (snap.to_dict() or {}) if snap.exists else {}

    def set_job_marker(self, name: str, fields: dict) -> None:
        self.client.collection(JOB_STATE_COLL).document(name).set(
            {**fields, "updated_at": datetime.now(UTC)}, merge=True)

    # ---- scan_runs -------------------------------------------------------

    def start_scan(self, mode: str = "scheduled") -> str:
        now = datetime.now(UTC)
        ref = self.client.collection(SCAN_RUNS_COLL).document()
        ref.set(
            {
                "started_at": now,
                "mode": mode,
                "sources_seen": 0,
                "new": 0,
                "updated": 0,
                "unchanged": 0,
                "processed_source_ids": [],
                "processed_statuses": {},
            }
        )
        return ref.id

    def complete_scan(
        self,
        scan_id: str,
        *,
        sources_seen: int,
        new: int,
        updated: int,
        unchanged: int,
        processed_source_ids: list[str] | None = None,
        processed_statuses: dict[str, str] | None = None,
        errors: list[str] | None = None,
        started_at: datetime | None = None,
    ) -> None:
        now = datetime.now(UTC)
        ref = self.client.collection(SCAN_RUNS_COLL).document(scan_id)
        if started_at is None:
            snap = ref.get()
            started_at = (
                (snap.to_dict() or {}).get("started_at") if snap.exists else None
            )
        duration_ms = (
            int((now - started_at).total_seconds() * 1000) if started_at else 0
        )
        ref.set(
            {
                "completed_at": now,
                "sources_seen": sources_seen,
                "new": new,
                "updated": updated,
                "unchanged": unchanged,
                "processed_source_ids": processed_source_ids or [],
                "processed_statuses": processed_statuses or {},
                "error": "\n".join(errors) if errors else None,
                "duration_ms": duration_ms,
            },
            merge=True,
        )

    def get_scan_history(self, limit: int = 10) -> list[dict]:
        query = (
            self.client.collection(SCAN_RUNS_COLL)
            .order_by("started_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [{"id": d.id, **(d.to_dict() or {})} for d in query.stream()]

    # ---- Builder surface -------------------------------------------------

    def get_source(self, dataset_id: str) -> SourceRecord | None:
        snap = self.client.collection(SOURCES_COLL).document(dataset_id).get()
        if not snap.exists:
            return None
        return SourceRecord.from_doc(snap)

    def iter_changed_sources(self) -> Iterator[SourceRecord]:
        """Stream changed sources (change_status in {new, updated}), newest
        CKAN changes first. There is no fixed
        limit: `stream()` pages lazily, so a caller can scan past a long run
        of ineligible recent updates (e.g. daily-appender datasets rebuilt
        within the reanalyze gap) without a small window truncating the
        eligible tail below them. `change_status` is sticky so the set can be
        large; callers terminate early — once they pass an age floor or fill
        their quota — and the DESC order makes that safe."""
        query = (
            self.client.collection(SOURCES_COLL)
            .where(filter=FieldFilter("change_status", "in", ["new", "updated"]))
            .order_by("metadata_modified", direction=firestore.Query.DESCENDING)
        )
        for d in query.stream():
            yield SourceRecord.from_doc(d)

    def list_never_analyzed(self, limit: int = 50) -> list[SourceRecord]:
        query = (
            self.client.collection(SOURCES_COLL)
            .where(filter=FieldFilter("analysis_status", "==", AnalysisStatus.NEVER))
            .order_by("metadata_modified", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [SourceRecord.from_doc(d) for d in query.stream()]

    def list_failed_retryable(
        self, limit: int = 50, max_attempts: int = 3
    ) -> list[SourceRecord]:
        """Failed sources still under the daily-retry budget, newest first.

        `failed_attempts < max_attempts` is filtered client-side: the field
        was introduced 2026-06 and older failed docs may lack it (treated
        as 1 — they failed at least once).
        """
        query = (
            self.client.collection(SOURCES_COLL)
            .where(filter=FieldFilter("analysis_status", "==", AnalysisStatus.FAILED))
            .order_by("metadata_modified", direction=firestore.Query.DESCENDING)
        )
        # Streamed, not a fixed window: parked docs (attempts >= max) can sort
        # ahead of retryable ones, and a `limit * 2` fetch would fill entirely
        # with them and starve the eligible tail.
        out: list[SourceRecord] = []
        for d in query.stream():
            attempts = (d.to_dict() or {}).get("failed_attempts")
            if int(attempts if attempts is not None else 1) < max_attempts:
                out.append(SourceRecord.from_doc(d))
                if len(out) >= limit:
                    break
        return out

    def list_org_sources(
        self, org_name: str, exclude_id: str = "", limit: int = 15
    ) -> list[SourceRecord]:
        """Same-ministry sources, for the sibling list in an authoring
        BRIEF.md (`author prepare`).

        Single-field filter, sorted client-side (already-published sources
        first, then newest) — no composite index needed.
        """
        if not org_name:
            return []
        query = (
            self.client.collection(SOURCES_COLL)
            .where(filter=FieldFilter("organization.name", "==", org_name))
            .limit(max(limit * 3, 30))
        )
        out = [
            SourceRecord.from_doc(d) for d in query.stream() if d.id != exclude_id
        ]
        out.sort(
            key=lambda s: (
                s.analysis_status != AnalysisStatus.SUCCEEDED,
                -(s.metadata_modified.timestamp() if s.metadata_modified else 0),
            )
        )
        return out[:limit]

    def iter_succeeded_sources(self) -> Iterator[SourceRecord]:
        query = self.client.collection(SOURCES_COLL).where(
            filter=FieldFilter("analysis_status", "==", AnalysisStatus.SUCCEEDED)
        )
        for d in query.stream():
            yield SourceRecord.from_doc(d)

    def set_resource_datastore_flags(
        self, source_id: str, flags: dict[str, bool]
    ) -> bool:
        """Merge `datastore_active` flags into the doc's `resources` array,
        matched by resource id. Used by the one-shot backfill; the scanner
        writes the flag on every regular upsert going forward. Returns True
        if the doc was modified."""
        ref = self.client.collection(SOURCES_COLL).document(source_id)
        snap = ref.get()
        if not snap.exists:
            return False
        resources = (snap.to_dict() or {}).get("resources") or []
        changed = False
        for r in resources:
            rid = r.get("id")
            if rid in flags and r.get("datastore_active") != flags[rid]:
                r["datastore_active"] = flags[rid]
                changed = True
        if changed:
            ref.set({"resources": resources}, merge=True)
        return changed

    def mark_source_unavailable(self, dataset_id: str, error: str) -> None:
        """Flag a *previously-succeeded* source as removed upstream.

        Unlike a `restricted` source (never-succeeded 403 → no page), this
        PRESERVES the page: the publisher still emits it
        (see `iter_publishable_sources`) with an archive banner. Stamps
        `unavailable_since` only on the first transition so the displayed
        date is the true first-detection time. Does not bump
        `failed_attempts`.
        """
        ref = self.client.collection(SOURCES_COLL).document(dataset_id)
        snap = ref.get()
        already = (snap.to_dict() or {}).get("unavailable_since") if snap.exists else None
        payload: dict = {
            "analysis_status": AnalysisStatus.UNAVAILABLE,
            "last_error": (error or "")[:1000],
        }
        if not already:
            payload["unavailable_since"] = datetime.now(UTC)
        ref.set(payload, merge=True)

    def clear_source_unavailable(self, dataset_id: str) -> None:
        """Self-heal: the source is reachable again. Flip back to
        `succeeded` (NOT `never` — that would drop the live page until a
        fresh build) and clear `unavailable_since`. Any genuine data
        change while it was gone is picked up by the recipe refresh (or,
        for a legacy page, the authoring queue) once CKAN's
        metadata_modified advances.
        """
        self.client.collection(SOURCES_COLL).document(dataset_id).set(
            {
                "analysis_status": AnalysisStatus.SUCCEEDED,
                "unavailable_since": firestore.DELETE_FIELD,
                "last_error": None,
            },
            merge=True,
        )

    def iter_publishable_sources(self) -> Iterator[SourceRecord]:
        """Sources the publisher should emit: succeeded + unavailable.

        `unavailable` docs keep their frozen snapshot (content.html in GCS,
        scanner facts + agent_data in the doc) so the page is preserved with
        an archive banner.
        """
        query = self.client.collection(SOURCES_COLL).where(
            filter=FieldFilter("analysis_status", "in", [AnalysisStatus.SUCCEEDED, AnalysisStatus.UNAVAILABLE])
        )
        for d in query.stream():
            yield SourceRecord.from_doc(d)

    # ---- Recipe refresh --------------------------------------------------
    #
    # A recipe'd page is re-rendered deterministically (no LLM) whenever
    # CKAN advances past the version it was last rendered from. Refresh
    # state lives on the source doc itself (`sources/<id>`).

    def _source_ref(self, dataset_id: str):
        return self.client.collection(SOURCES_COLL).document(dataset_id)

    def get_refresh_state(self, dataset_id: str) -> dict:
        snap = self._source_ref(dataset_id).get()
        return (snap.to_dict() or {}) if snap.exists else {}

    def mark_refreshed(
        self,
        dataset_id: str,
        *,
        metadata_modified: datetime | None,
        recipe_version: int,
        agent_data: dict,
        page_path: str,
        snapshot: dict | None = None,
        input_fingerprint: str | None = None,
        inputs_hash: str | None = None,
        content_hash: str | None = None,
        file_fingerprint: str | None = None,
        inputs_hash_unordered: str | None = None,
    ) -> None:
        """Record a successful recipe refresh.

        `snapshot` (row counts, KPI displays, insight sentences) is what the
        next refresh diffs against to report what moved.

        The five hashes (REFRESH_PRECHECK) describe the render just staged.
        Always written — None when the precheck was off — so a stale hash from
        an earlier render can never vouch for a page it didn't produce.

        Also writes the analysis fields the retired agent builder wrote on a
        success (the authoring selector still reads them) — the page's data
        vintage is now the version just rendered — plus agent_data, in one
        merged write.
        """
        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "agent_data": agent_data,
            "recipe_version": recipe_version,
            "refreshed_metadata_modified": metadata_modified,
            "last_refreshed_at": now,
            "refresh_status": RefreshStatus.SUCCEEDED,
            "refresh_error": None,
            "refresh_failed_version": None,
            "authoring_status": AuthoringStatus.DONE,
            "authoring_reason": None,
            "authoring_issue": None,
            "last_snapshot": snapshot,
            "input_fingerprint": input_fingerprint,
            "inputs_hash": inputs_hash,
            "content_hash": content_hash,
            "file_fingerprint": file_fingerprint,
            "inputs_hash_unordered": inputs_hash_unordered,
            "wall_budget_strikes": None,
            "transient_strikes": None,
            "analysis_status": AnalysisStatus.SUCCEEDED,
            "last_analyzed_at": now,
            "analyzed_metadata_modified": metadata_modified,
            "last_analyzed_version": firestore.Increment(1),
            "page_path": page_path,
            "last_error": None,
            "failed_attempts": 0,
        }
        self._source_ref(dataset_id).set(payload, merge=True)

    def mark_refresh_unchanged(
        self,
        dataset_id: str,
        *,
        metadata_modified: datetime | None,
        input_fingerprint: str,
        inputs_hash: str | None = None,
        inputs_hash_unordered: str | None = None,
        file_fingerprint: str | None = None,
        reason: str,
        advance_version: bool,
        transient_strikes: dict[str, int] | None = None,
    ) -> None:
        """Record that CKAN bumped the version but the precheck found the
        recipe's inputs — or, for `content_hash`, the rendered page —
        unchanged since the last render, so the live page stands.

        `advance_version` (exact input-hash or content-hash match only): the
        page's data vintage equals this version. Advance the version markers
        so the next run doesn't re-check this bump, and settle any earlier
        failure or authoring flag the same way `mark_refreshed` would. A
        fingerprint match isn't proof, so the bump stays pending.

        Leaves `last_refreshed_at`, `agent_data`, `last_snapshot` and
        `content_hash` alone. They describe the last render that actually
        changed the page (`content_hash` is equal by definition after a
        `content_hash` skip). That skip was a full render, so it stamps
        `last_verified_at`, which the max-age safety net also counts.
        `inputs_hash` is None after a fingerprint skip (nothing was fetched);
        the stored one still holds. `transient_strikes`, when given, replaces
        the stored map after a fingerprint skip (the previews answered, so a
        run of `preview_unavailable` strikes restarts).
        """
        payload: dict[str, Any] = {
            "last_unchanged_at": datetime.now(UTC),
            "unchanged_reason": reason,
            "input_fingerprint": input_fingerprint,
            "file_fingerprint": file_fingerprint,
        }
        if inputs_hash is not None:
            payload["inputs_hash"] = inputs_hash
            payload["inputs_hash_unordered"] = inputs_hash_unordered
            payload["wall_budget_strikes"] = None  # the full fetch completed
            payload["transient_strikes"] = None  # …downloads included
        elif transient_strikes is not None:
            payload["transient_strikes"] = transient_strikes or None
        if reason == "content_hash":
            payload["last_verified_at"] = payload["last_unchanged_at"]
        if advance_version:
            payload.update(
                {
                    "refreshed_metadata_modified": metadata_modified,
                    "refresh_status": RefreshStatus.SUCCEEDED,
                    "refresh_error": None,
                    "refresh_failed_version": None,
                    "authoring_status": AuthoringStatus.DONE,
                    "authoring_reason": None,
                    "authoring_issue": None,
                    "analyzed_metadata_modified": metadata_modified,
                }
            )
        # merge= field paths: `transient_strikes` is replaced whole (merge=True
        # would deep-merge the map and keep a popped key).
        self._source_ref(dataset_id).set(payload, merge=list(payload))

    def mark_refresh_failed(
        self,
        dataset_id: str,
        *,
        error: str,
        reason: str,
        failed_version: str,
        wall_budget_strikes: int | None = None,
        transient_strikes: dict[str, int] | None = None,
    ) -> None:
        """Record a failed refresh. Never touches `analysis_status`: the
        last-good page stays live. `failed_version`
        (`refresh.failed_version_key`: metadata_modified + recipe_version +
        a hash of the recipe files, builder code and library versions) lets the next run skip
        a deterministic re-failure until the data, the recipe or the
        deployed builder moves. `wall_budget_strikes`
        (wall-budget overruns since the last full fetch) and
        `transient_strikes` (consecutive runs per refresh `StrikeError`
        kind) are written only when given; other failures leave them alone."""
        payload: dict[str, Any] = {
            "refresh_status": RefreshStatus.FAILED,
            "refresh_error": (error or "")[:1000],
            "refresh_reason": reason,
            "refresh_failed_version": failed_version,
            "last_refresh_attempt_at": datetime.now(UTC),
        }
        if wall_budget_strikes is not None:
            payload["wall_budget_strikes"] = wall_budget_strikes
        if transient_strikes is not None:
            payload["transient_strikes"] = transient_strikes or None
        # merge= field paths, not merge=True: each listed field is replaced
        # whole, so a key popped from `transient_strikes` is really gone
        # (merge=True deep-merges maps). Unlisted fields are left alone.
        self._source_ref(dataset_id).set(payload, merge=list(payload))

    def mark_authoring_needed(self, dataset_id: str, reason: str) -> None:
        self._source_ref(dataset_id).set(
            {"authoring_status": AuthoringStatus.NEEDED, "authoring_reason": reason},
            merge=True,
        )

    def set_authoring_issue(self, dataset_id: str, issue_number: int) -> None:
        self._source_ref(dataset_id).set(
            {"authoring_status": AuthoringStatus.NOTIFIED, "authoring_issue": issue_number},
            merge=True,
        )

    def iter_authoring_queue(self) -> Iterator[tuple[str, dict]]:
        """Prod sources waiting for a locally-authored recipe."""
        query = self.client.collection(SOURCES_COLL).where(
            filter=FieldFilter("authoring_status", "in", [AuthoringStatus.NEEDED, AuthoringStatus.NOTIFIED])
        )
        for d in query.stream():
            yield d.id, (d.to_dict() or {})

    # ---- Ops helpers -----------------------------------------------------

    def get_stats(self) -> dict[str, int]:
        coll = self.client.collection(SOURCES_COLL)
        counts: dict[str, int] = {"total": _count(coll)}
        for status in AnalysisStatus:
            counts[status] = _count(
                coll.where(filter=FieldFilter("analysis_status", "==", status))
            )
        return counts
