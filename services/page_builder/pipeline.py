"""Builder pipeline — what one job execution (one Cloud Scheduler tick) does.

Each tick (Asia/Jerusalem; see infra/ for the schedule): scan CKAN → refresh
every recipe'd source CKAN moved past (deterministic, no LLM —
services/page_builder/refresh.py) → queue every new or changed source that has
no recipe for authoring (one `needs-authoring` GitHub issue each, solved by
the daily local Claude Code routine) → if ≥1 page re-rendered (or an earlier
run's dispatch failed), trigger the publisher.

A scheduled run (not dry, no `--source`) first checks QUIET_WINDOW (ends
`skipped_quiet`) and then takes the `job_state/run` lease (ends
`skipped_overlap` while another execution holds it), so frequent ticks never
overlap. AUTHORING_QUEUE_HOURS limits the authoring queue to listed Israel
hours. Every knob unset = run every step on every tick.

No model runs here. A recipe merged to main is picked up on the next run
(the refresh reads recipes/ straight from git).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from services.scanner.config import ScannerSettings
from services.scanner.main import Scanner
from services.shared import github, lease, schedule
from services.shared.env import env_float, env_int
from services.shared.firestore import FirestoreStateStore
from services.shared.states import (
    NO_DATA_STATUSES,
    AuthoringReason,
    OutcomeStatus,
    RunStatus,
    UnchangedReason,
)

from . import refresh as _refresh
from . import selector

log = logging.getLogger("page_builder.pipeline")

# Run outcomes that must surface as a failed job execution rather than a
# green one. `idle` is deliberately absent — a day with nothing to refresh
# is a normal, healthy outcome. The refresh is the only way a page changes,
# so a refresh that couldn't run (no recipe list, crash, staging down) is a
# dead run even if the authoring queue still went out, and so is a run whose
# re-rendered pages never got a publish dispatch (they stay staged, not live).
# A broken authoring queue is red too: nobody would learn of new datasets.
# So is a scan that failed (the rest of the run went ahead on yesterday's
# Firestore data) and a reconcile sweep that crashed or aborted (see
# reconcile.reconcile_sources).
FAILED_RUN_STATUSES = frozenset({
    RunStatus.REFRESH_UNAVAILABLE, RunStatus.REFRESH_FAILED, RunStatus.PUBLISH_FAILED,
    RunStatus.SCAN_FAILED, RunStatus.AUTHORING_FAILED, RunStatus.RECONCILE_FAILED,
})

# The run lease (services/shared/lease.py): one scheduled execution at a time.
# A heartbeat renews it while the run works, so its TTL (RUN_LEASE_TTL_S) is
# short: it only bounds how long a run that died without releasing (task
# timeout, OOM) keeps later ticks out.
RUN_LEASE_DOC = "job_state/run"
RUN_LEASE_TTL_DEFAULT_S = 900.0
# Reconcile sweeps started per IL date (RECONCILE_MAX_ATTEMPTS): an aborted or
# crashed sweep is retried by later runs that day, up to this many in all.
RECONCILE_MAX_ATTEMPTS_DEFAULT = 2


def _env_int_warn(name: str, default: int) -> int:
    """`env_int`, with a warning when a set value isn't an integer (a typo
    then costs the knob, not the run)."""
    raw = os.environ.get(name, "").strip()
    if raw:
        try:
            int(raw)
        except ValueError:
            log.warning("invalid %s=%r — using the default, %d", name, raw, default)
    return env_int(name, default)


def _run_status(*, refresh_broken: bool, scan_failed: bool, authoring_broken: bool,
                reconcile_failed: bool, refreshed: bool,
                publish_failed: bool = False, published: bool = False) -> RunStatus:
    """One status per run; the first failure in this order wins. `published`:
    a dispatch went out (e.g. for an earlier run's pages) even though this
    run re-rendered nothing; that run did something, so it is `ok`."""
    if refresh_broken:
        return RunStatus.REFRESH_FAILED
    if publish_failed:
        return RunStatus.PUBLISH_FAILED
    if scan_failed:
        return RunStatus.SCAN_FAILED
    if authoring_broken:
        return RunStatus.AUTHORING_FAILED
    if reconcile_failed:
        return RunStatus.RECONCILE_FAILED
    return RunStatus.OK if refreshed or published else RunStatus.IDLE


def _reconcile_due(now: datetime, *, enabled: bool, weekday: int) -> bool:
    """Weekly reconcile runs only when enabled AND today matches the
    configured weekday (Python Monday=0 .. Sunday=6)."""
    return enabled and now.weekday() == weekday


def _reconciled_today(store, now: datetime) -> bool:
    """Whether a sweep already finished on `now`'s (IL) date: the job runs
    several times a day, and one sweep a week is enough. A marker read failure
    answers False, so the sweep runs rather than being skipped."""
    try:
        return store.get_job_marker("reconcile").get("last_date") == now.date().isoformat()
    except Exception:
        log.warning("reconcile: couldn't read the last-sweep marker", exc_info=True)
        return False


def _claim_reconcile_attempt(store, now: datetime, max_attempts: int) -> bool:
    """Count one more sweep attempt for `now`'s IL date in `job_state/reconcile`
    (`attempt_date`, `attempts`), before the sweep starts, so a sweep that
    crashes or is killed still counts. False (no sweep) once `max_attempts`
    were made that date. A marker read or write failure answers True: the
    sweep runs, as it did before attempts were counted."""
    today = now.date().isoformat()
    try:
        marker = store.get_job_marker("reconcile")
    except Exception:
        log.warning("reconcile: couldn't read the attempts marker", exc_info=True)
        return True
    made = int(marker.get("attempts") or 0) if marker.get("attempt_date") == today else 0
    if made >= max_attempts:
        log.warning("reconcile: %d sweep attempt(s) already made on %s "
                    "(RECONCILE_MAX_ATTEMPTS=%d); not sweeping again today",
                    made, today, max_attempts)
        return False
    try:
        store.set_job_marker("reconcile", {"attempt_date": today, "attempts": made + 1})
    except Exception:
        log.warning("reconcile: couldn't record the sweep attempt", exc_info=True)
    return True


def _publish_pending(store) -> bool | None:
    """Whether an earlier run's dispatch failed and its staged pages still
    wait to go live (`job_state/publish`). None when the marker can't be read:
    the run goes on, and a set marker stays for the next run."""
    try:
        return bool(store.get_job_marker("publish").get("pending"))
    except Exception:
        log.warning("publish: couldn't read the pending-publish marker", exc_info=True)
        return None


def _set_publish_pending(store, pending: bool) -> None:
    """Record (or clear) a failed dispatch; a write failure only logs."""
    try:
        store.set_job_marker("publish", {"pending": pending})
    except Exception:
        log.warning("publish: couldn't %s the pending-publish marker",
                    "set" if pending else "clear", exc_info=True)


async def _trigger_publish_github(repo: str, workflow: str, branch: str) -> str | None:
    """Fire the GitHub Actions publish workflow (workflow_dispatch) off the
    event loop; see `shared.github.dispatch_workflow`. A thin wrapper so tests
    can patch the dispatch."""
    try:
        return await asyncio.to_thread(github.dispatch_workflow, repo, workflow, branch)
    except Exception:
        log.exception("trigger_publish (github) failed")
        return None


async def _trigger_publish(
    project_id: str, trigger_id: str, branch: str, region: str = "me-west1"
) -> str | None:
    """Fire the Cloud Build publisher (fallback path, PUBLISH_VIA=cloudbuild).

    Fire-and-forget — don't wait for the build. Uses the regional Cloud
    Build endpoint; triggers created with `--region=me-west1` are not
    reachable via the global endpoint.
    """

    def _run() -> str | None:
        from google.api_core.client_options import ClientOptions
        from google.cloud.devtools import cloudbuild_v1
        from google.cloud.devtools.cloudbuild_v1.types import (
            RepoSource,
            RunBuildTriggerRequest,
        )

        client = cloudbuild_v1.CloudBuildClient(
            client_options=ClientOptions(
                api_endpoint=f"{region}-cloudbuild.googleapis.com"
            )
        )
        request = RunBuildTriggerRequest(
            name=f"projects/{project_id}/locations/{region}/triggers/{trigger_id}",
            project_id=project_id,
            trigger_id=trigger_id,
            source=RepoSource(branch_name=branch),
        )
        operation = client.run_build_trigger(request=request)
        meta = getattr(operation, "metadata", None)
        build = getattr(meta, "build", None)
        return getattr(build, "id", None) if build else None

    try:
        return await asyncio.to_thread(_run)
    except Exception:
        log.exception("trigger_publish failed")
        return None


async def _dispatch_publish(
    should: bool,
    publish_via: str,
    repo: str,
    workflow: str,
    branch: str,
    project_id: str,
    trigger_id: str,
    region: str,
) -> str | None:
    if not should:
        return None
    if publish_via == "github":
        return await _trigger_publish_github(repo, workflow, branch)
    if publish_via == "cloudbuild" and trigger_id:
        return await _trigger_publish(project_id, trigger_id, branch, region=region)
    if publish_via:
        log.error("unknown PUBLISH_VIA=%r — publish skipped", publish_via)
    return None


@dataclass(frozen=True)
class PipelineSettings:
    """The job's env knobs, read once per run by `run_pipeline` (`from_env`)."""
    scan_limit: int
    notify_cap: int
    selector_gates: dict
    staging_bucket: str
    project_id: str
    publish_via: str
    publish_repo: str
    publish_workflow: str
    trigger_id: str
    publish_branch: str
    publish_region: str
    reconcile_enabled: bool
    reconcile_weekday: int
    reconcile_max_attempts: int = RECONCILE_MAX_ATTEMPTS_DEFAULT

    @classmethod
    def from_env(cls, *, require_staging_bucket: bool) -> PipelineSettings:
        """A malformed SCAN_LIMIT / AUTHORING_NOTIFY_CAP / MAX_AGE_DAYS /
        RECONCILE_WEEKDAY warns and uses its default; a malformed
        MIN_MODIFIED_FLOOR raises (the run fails: a wrong floor silently
        widens or narrows the authoring queue). `require_staging_bucket` (a real run) raises
        when GCS_STAGING_BUCKET is unset, before the reconcile knobs are read."""
        # SCAN_LIMIT bounds how many CKAN datasets (sorted metadata_modified
        # desc) each scan ingests into Firestore. The authoring queue can
        # only see what's been scanned, so this must cover the eligible window:
        # 2026 (~433) + 2025 (~92) → 800 with headroom. Raise it in lockstep
        # when MIN_MODIFIED_FLOOR drops to admit an older year.
        scan_limit = _env_int_warn("SCAN_LIMIT", 800)
        # New issues opened per run — a fuse against a scan anomaly flooding the
        # tracker. Already-notified sources don't count (the selector skips them).
        notify_cap = _env_int_warn("AUTHORING_NOTIFY_CAP", 100)
        # Selection date gates, env-overridable so widening coverage one year
        # at a time is a `gcloud run` env change, not a redeploy. Unset →
        # selector.DEFAULT_* (floor 2026-01-01, rolling window 365d).
        selector_gates: dict = {}
        floor_env = os.environ.get("MIN_MODIFIED_FLOOR", "").strip()
        if floor_env:
            floor_dt = datetime.fromisoformat(floor_env)
            if floor_dt.tzinfo is None:
                floor_dt = floor_dt.replace(tzinfo=UTC)
            selector_gates["min_modified_floor"] = floor_dt
        if os.environ.get("MAX_AGE_DAYS", "").strip():
            selector_gates["max_age_days"] = _env_int_warn(
                "MAX_AGE_DAYS", selector.DEFAULT_MAX_AGE_DAYS)
        staging_bucket = os.environ.get("GCS_STAGING_BUCKET", "")
        project_id = (
            os.environ.get("FIREBASE_PROJECT")
            or os.environ.get("GOOGLE_CLOUD_PROJECT")
            or "govdata-il"
        )
        # Publish mechanism: "github" (Actions workflow_dispatch, default),
        # "cloudbuild" (legacy trigger, fallback), or "" to disable publishing.
        publish_via = os.environ.get("PUBLISH_VIA", "github").strip().lower()
        publish_repo = github.default_repo()
        publish_workflow = os.environ.get("PUBLISH_GITHUB_WORKFLOW", "publish.yml")
        trigger_id = os.environ.get("PUBLISH_TRIGGER_ID", "govdata-publish")
        publish_branch = os.environ.get("PUBLISH_BRANCH", "main")
        publish_region = os.environ.get("PUBLISH_REGION", "me-west1")

        if require_staging_bucket and not staging_bucket:
            raise RuntimeError(
                "GCS_STAGING_BUCKET must be set for a real pipeline run"
            )

        # Weekly reconcile gates: RECONCILE_ENABLED + RECONCILE_WEEKDAY
        # (Asia/Jerusalem), default off / Sunday.
        reconcile_enabled = os.environ.get("RECONCILE_ENABLED", "false").lower() in (
            "true", "1", "yes",
        )
        reconcile_weekday = _env_int_warn("RECONCILE_WEEKDAY", 6)
        reconcile_max_attempts = env_int("RECONCILE_MAX_ATTEMPTS",
                                         RECONCILE_MAX_ATTEMPTS_DEFAULT)
        return cls(
            scan_limit=scan_limit,
            notify_cap=notify_cap,
            selector_gates=selector_gates,
            staging_bucket=staging_bucket,
            project_id=project_id,
            publish_via=publish_via,
            publish_repo=publish_repo,
            publish_workflow=publish_workflow,
            trigger_id=trigger_id,
            publish_branch=publish_branch,
            publish_region=publish_region,
            reconcile_enabled=reconcile_enabled,
            reconcile_weekday=reconcile_weekday,
            reconcile_max_attempts=reconcile_max_attempts,
        )


def _clear_provider_caches() -> None:
    """Drop the providers' per-run downloads (every provider dataset's CSV,
    held since the sync). Nothing after the refresh reads them; never fails
    the run."""
    try:
        from services.providers import enabled_providers

        for p in enabled_providers().values():
            p.clear_cache()
    except Exception:
        log.warning("clearing the provider caches failed", exc_info=True)


def _il_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        il_now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    except Exception:  # noqa: BLE001
        il_now = datetime.now(UTC)
    return il_now


async def _reconcile_sweep(store, config, il_now: datetime) -> tuple[dict | None, bool]:
    """Run the reconcile sweep; (its summary, whether the run must end
    `reconcile_failed`). Records the IL date marker only after a full sweep."""
    reconcile_summary = None
    reconcile_failed = False
    from services.scanner.client import CKANClient

    from . import reconcile as _reconcile
    try:
        async with CKANClient(config=config) as _ckan:
            reconcile_summary = await _reconcile.reconcile_sources(store, _ckan)
        log.info("reconcile: %s", reconcile_summary)
        if reconcile_summary.get("aborted"):
            # No last_date: a later run today sweeps again (attempts allowing).
            reconcile_failed = True
        else:
            try:
                store.set_job_marker("reconcile", {"last_date": il_now.date().isoformat()})
            except Exception:
                log.warning("reconcile: couldn't record the sweep; the next run today "
                            "repeats it", exc_info=True)
    except Exception:
        log.exception("reconcile sweep failed — continuing with scan/refresh")
        reconcile_failed = True
    return reconcile_summary, reconcile_failed


def _lease_holder() -> str:
    """A per-process unique lease holder id (the Cloud Run execution name
    when there is one, for the logs)."""
    execution = os.environ.get("CLOUD_RUN_EXECUTION", "local")
    return f"{execution}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _acquire_run_lease(store, holder: str, ttl_s: float) -> bool | None:
    """True: the lease is ours. False: another execution holds it. None: the
    lease couldn't be read or written (Firestore error); logged at error
    level, and the run goes on without it (a Firestore outage would fail the
    run's own reads anyway, and skipping would hide it behind a green exit)."""
    try:
        return lease.acquire(store.client, RUN_LEASE_DOC, holder, ttl_s)
    except Exception:
        log.exception("run lease: couldn't acquire %s; running WITHOUT the lease "
                      "(an overlapping execution is not excluded)", RUN_LEASE_DOC)
        return None


def _release_run_lease(store, holder: str) -> None:
    try:
        lease.release(store.client, RUN_LEASE_DOC, holder)
    except Exception:
        log.exception("run lease: couldn't release %s; it expires on its own "
                      "(RUN_LEASE_TTL_S)", RUN_LEASE_DOC)


async def run_pipeline(
    *,
    mode: str = "scheduled",
    override_id: str | None = None,
    dry_run: bool = False,
    skip_publish: bool = False,
) -> dict:
    """The one entry point the job (CLI) uses. A scheduled run (not dry, no
    override) is gated by QUIET_WINDOW and then by the run lease; the summary
    always carries `started_at` (UTC ISO) and `duration_s`."""
    started_at = datetime.now(UTC)
    t0 = time.monotonic()
    gated = mode == "scheduled" and not dry_run and not override_id

    def _finish(summary: dict) -> dict:
        summary["started_at"] = started_at.isoformat()
        summary["duration_s"] = round(time.monotonic() - t0, 1)
        return summary

    def _skipped(status: RunStatus) -> dict:
        return _finish({"mode": mode, "dry_run": dry_run, "status": status})

    if gated and schedule.in_quiet_window("QUIET_WINDOW"):
        log.info("inside QUIET_WINDOW=%s — nothing to do this tick",
                 os.environ.get("QUIET_WINDOW"))
        return _skipped(RunStatus.SKIPPED_QUIET)

    store = FirestoreStateStore()
    if not gated:
        return _finish(await _run_pipeline_body(
            store, mode=mode, override_id=override_id, dry_run=dry_run,
            skip_publish=skip_publish))

    holder = _lease_holder()
    ttl_s = env_float("RUN_LEASE_TTL_S", RUN_LEASE_TTL_DEFAULT_S)
    acquired = _acquire_run_lease(store, holder, ttl_s)
    if acquired is False:
        log.warning("run lease %s is held by another execution — skipping this tick",
                    RUN_LEASE_DOC)
        return _skipped(RunStatus.SKIPPED_OVERLAP)
    beat = lease.Heartbeat(store.client, RUN_LEASE_DOC, holder, ttl_s).start() if acquired else None
    try:
        summary = await _run_pipeline_body(
            store, mode=mode, override_id=override_id, dry_run=dry_run,
            skip_publish=skip_publish)
    finally:
        if beat:
            beat.stop()
        if acquired:
            _release_run_lease(store, holder)
    summary["lease"] = "held" if acquired else "error"
    return _finish(summary)


async def _run_pipeline_body(
    store,
    *,
    mode: str,
    override_id: str | None,
    dry_run: bool,
    skip_publish: bool,
) -> dict:
    """The run itself, once the gates in `run_pipeline` let it through."""
    config = ScannerSettings()
    settings = PipelineSettings.from_env(require_staging_bucket=not dry_run)

    # [0] weekly reconcile — probe already-published sources and flag those
    # removed upstream (they vanish from CKAN's list, so the scan below
    # never revisits them). Gated by RECONCILE_ENABLED + RECONCILE_WEEKDAY
    # (Asia/Jerusalem), default off / Sunday. Full sweep, no cursor. Once a
    # sweep finished that IL date, no more; an aborted or crashed one is
    # retried by later runs, RECONCILE_MAX_ATTEMPTS sweeps per date in all.
    reconcile_summary = None
    reconcile_failed = False
    il_now = _il_now()
    if not dry_run and not override_id and _reconcile_due(
        il_now, enabled=settings.reconcile_enabled, weekday=settings.reconcile_weekday
    ) and not _reconciled_today(store, il_now) and _claim_reconcile_attempt(
        store, il_now, settings.reconcile_max_attempts
    ):
        log.info("reconcile: due (weekday=%s) — running sweep", settings.reconcile_weekday)
        reconcile_summary, reconcile_failed = await _reconcile_sweep(store, config, il_now)

    # [1] scan — unless override_id is set (manual single-source run)
    # A failed scan doesn't stop the run: provider sync, refresh and the
    # authoring queue work from the Firestore docs earlier scans wrote, and
    # the run ends red (`scan_failed`). The scanner records per-dataset
    # failures itself and closes its scan_runs doc either way.
    scan_summary = None
    scan_error: str | None = None
    if not override_id:
        scanner = Scanner(config=config, store=store)
        try:
            scan_summary = await scanner.scan(limit=settings.scan_limit, mode=mode)
        except Exception as e:
            log.exception("scan failed — continuing on the existing Firestore data")
            scan_error = f"{type(e).__name__}: {e}"[:500]
    scan_failed = bool(scan_error) or bool(scan_summary and scan_summary.error_count)

    summary: dict = {
        "mode": mode,
        "dry_run": dry_run,
        "scan": (_scan_summary_dict(scan_summary) if scan_summary
                 else {"error": scan_error} if scan_error else None),
        "reconcile": reconcile_summary,
        "refresh": None,
        "authoring_queued": [],
        "build_id": None,
    }

    # [2] recipe list. Without it we can't tell which sources a recipe owns,
    # so nothing below may run: queueing would open issues for datasets
    # that already have a recipe. A failed run, not an idle one.
    try:
        repo = _refresh.recipe_repo_from_env()
        recipe_ids = frozenset(await asyncio.to_thread(repo.list_ids))
    except Exception:
        log.exception("recipe list unavailable — nothing refreshed or queued")
        summary["status"] = RunStatus.REFRESH_UNAVAILABLE
        return summary

    # [2.5] provider sources (services/providers): recipes with a
    # source.json are non-CKAN datasets (Bank of Israel, …). Their doc and
    # version come from this step, the way the scan above feeds CKAN ones.
    # A provider outage only leaves those pages last-good; never fatal. A dry
    # run skips it: it downloads every provider dataset and writes their docs,
    # and the authoring queue it lists never includes provider datasets.
    from services.providers.sync import sync_provider_sources

    summary["providers"] = None
    if not dry_run:
        try:
            summary["providers"] = await asyncio.to_thread(
                sync_provider_sources, store, repo,
                only_ids=[override_id] if override_id else None,
            )
            if summary["providers"]["failed"]:
                log.warning("provider sync failures: %s", summary["providers"]["failed"])
            if summary["providers"].get("escalated"):
                await asyncio.to_thread(
                    queue_provider_escalations, store, summary["providers"]["escalated"])
        except Exception:
            log.exception("provider sync failed — provider pages stay last-good this run")

    # [3] what to refresh: the override if it has a recipe, else everything
    # (run_refresh decides per source).
    only_ids: list[str] | None = None
    override_src = None
    if override_id:
        override_src = await asyncio.to_thread(store.get_source, override_id)
        if override_src is None:
            raise RuntimeError(f"override source {override_id} not found in Firestore")
        only_ids = [override_id] if override_id in recipe_ids else []

    async def _authoring_candidates() -> list:
        if override_src is None:
            return await asyncio.to_thread(
                selector.pick_authoring_candidates,
                store,
                settings.notify_cap,
                exclude_ids=recipe_ids,
                **settings.selector_gates,
            )
        if only_ids or override_src.analysis_status in NO_DATA_STATUSES:
            return []
        return [(override_src, AuthoringReason.LEGACY_UPDATED if override_src.page_path
                 else AuthoringReason.NEW)]

    if dry_run:
        summary["selected_for_authoring"] = [s.id for s, _ in await _authoring_candidates()]
        # A dry run is how a deploy is smoke-tested: a broken scan must show.
        summary["status"] = RunStatus.SCAN_FAILED if scan_failed else RunStatus.DRY_RUN
        return summary

    # [4] refresh — deterministic re-render of recipe'd sources. First, and
    # nothing between it and the publish dispatch may raise: its output is
    # the only way a page changes.
    refresh_broken = False
    if only_ids is None or only_ids:
        try:
            summary["refresh"] = await asyncio.to_thread(
                _refresh.run_refresh,
                store,
                repo,
                staging_bucket=settings.staging_bucket,
                only_ids=only_ids,
                # A manual single-dataset run means "render it now", even
                # when the page is already up to date.
                force=bool(override_id),
            )
            refresh_broken = bool(summary["refresh"].get("staging_down"))
            if summary["refresh"].get("all_errored"):
                log.error("recipe refresh: every attempted source failed with `error` — "
                          "a code bug, not the data")
                refresh_broken = True
        except Exception:
            log.exception("recipe refresh failed — continuing with the authoring queue")
            refresh_broken = True
        _clear_provider_caches()
    refreshed_ids = list((summary["refresh"] or {}).get("refreshed") or [])

    # [5] authoring queue: one issue per source, idempotent. A failure here
    # (selector query, Firestore, GitHub) must not cost the publish below.
    # AUTHORING_QUEUE_HOURS (Israel hours; unset = every run) gates it on
    # scheduled runs; a skipped queue is not a failure. `--source` ignores it.
    authoring_broken = False
    if not override_id and not schedule.due_this_hour("AUTHORING_QUEUE_HOURS"):
        log.info("authoring queue: not due this hour (AUTHORING_QUEUE_HOURS=%s)",
                 os.environ.get("AUTHORING_QUEUE_HOURS"))
        summary["authoring_skipped"] = "not_due_this_hour"
        to_queue = []
    else:
        try:
            to_queue = await _authoring_candidates()
        except Exception:
            log.exception("authoring selector failed — no issues queued this run")
            to_queue, authoring_broken = [], True
    summary["selected_for_authoring"] = [s.id for s, _ in to_queue]
    # queue_authoring answers None only when it tried to open an issue and
    # couldn't. Without a token (a local run) that is expected; with one it
    # is a GitHub error, and the source would wait silently.
    have_token = bool(github.token())
    for src, reason in to_queue:
        try:
            issue = await asyncio.to_thread(_refresh.queue_authoring, store, src, reason)
        except Exception:
            log.exception("queueing %s for authoring failed", src.id[:8])
            issue, authoring_broken = None, True
        else:
            if issue is None and have_token:
                log.error("authoring issue for %s could not be opened", src.id[:8])
                authoring_broken = True
        summary["authoring_queued"].append({"id": src.id, "reason": reason, "issue": issue})

    # [6] publish whatever re-rendered. A due dispatch that came back empty
    # (no token, GitHub refused it, Cloud Build error, unknown PUBLISH_VIA)
    # leaves the pages staged but not live: a failed run. Those pages are
    # already marked refreshed, so the next run wouldn't re-render them; the
    # `job_state/publish` marker makes it dispatch anyway, until one succeeds.
    # `--no-trigger-publish` neither reads, sets nor clears it.
    pending = None if skip_publish else _publish_pending(store)
    publish_due = (bool(refreshed_ids) or bool(pending)) and not skip_publish
    summary["build_id"] = await _dispatch_publish(
        publish_due,
        settings.publish_via, settings.publish_repo, settings.publish_workflow,
        settings.publish_branch, settings.project_id, settings.trigger_id, settings.publish_region,
    )
    publish_failed = publish_due and bool(settings.publish_via) and summary["build_id"] is None
    if publish_failed:
        _set_publish_pending(store, True)
    elif summary["build_id"] is not None and pending is not False:
        _set_publish_pending(store, False)  # set, or unknown (the read failed)
    # Pages that did refresh before a breakdown still publish (above); the
    # run is red either way.
    summary["status"] = _run_status(
        refresh_broken=refresh_broken, scan_failed=scan_failed,
        authoring_broken=authoring_broken, reconcile_failed=reconcile_failed,
        refreshed=bool(refreshed_ids), publish_failed=publish_failed,
        published=summary["build_id"] is not None,
    )
    return summary


def _scan_summary_dict(s) -> dict:
    out = {
        "sources_seen": s.datasets_scanned,
        "new": s.datasets_new,
        "updated": s.datasets_updated,
        "unchanged": s.datasets_unchanged,
        "errors": list(s.errors or []),
        "error_count": s.error_count,
    }
    since = getattr(s, "incremental_since", None)
    if since is not None:  # SCAN_INCREMENTAL: where the listing could stop
        out["incremental_since"] = since.isoformat()
    return out


def summarize_for_log(summary: dict) -> list[str]:
    """The run summary as compact one-line JSON records: a headline, then one
    line per refresh outcome that did something. The whole summary as one
    indented block was ~4,000 lines stamped in the same millisecond, which
    Cloud Logging reordered and partly dropped (2026-10-31). Up-to-date skips,
    most of every run, only count in the headline. One whose missing authoring
    issue this run opened (`issue`, see `run_refresh`) keeps its line."""
    import json
    from collections import Counter

    def line(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)

    head = dict(summary)
    outcomes = []
    if summary.get("refresh"):
        refresh = dict(summary["refresh"])
        outcomes = refresh.pop("outcomes", None) or []
        refresh["counts"] = dict(sorted(Counter(
            f"{o.get('status')}:{o.get('reason')}" if o.get("reason") else o.get("status")
            for o in outcomes
        ).items()))
        head["refresh"] = refresh
    lines = [line({"pipeline_summary": head})]
    for o in outcomes:
        if (o.get("status") == "skipped" and o.get("reason") == "up_to_date"
                and o.get("issue") is None):
            continue
        # A pending no-op bump inside REFRESH_REPROBE_MIN_HOURS: nothing was
        # fetched or written, and hourly runs would repeat the line all day.
        if (o.get("status") == OutcomeStatus.UNCHANGED
                and o.get("reason") == UnchangedReason.RECENTLY_PROBED
                and o.get("issue") is None):
            continue
        kept = {k: v for k, v in o.items() if v is not None and v != {} and v != []}
        lines.append(line({"refresh_outcome": kept}))
    return lines


def queue_provider_escalations(store, escalated: list[dict]) -> None:
    """Open the needs-authoring issue of each provider dataset whose sync kept
    failing (`sync_provider_sources`' `escalated`). Its page is frozen
    last-good and the refresh never runs for it, so nothing else would. Same
    path as a refresh failure (`queue_authoring`: an open issue is reused).
    Writes the issue number into each entry; one dataset's error never stops
    the others."""
    for item in escalated:
        try:
            src = store.get_source(item["id"])
        except Exception:
            log.exception("provider sync %s: reading the source doc failed", item["id"])
            continue
        if src is None:
            continue
        item["issue"] = _refresh._queue_authoring_safely(
            store, src, AuthoringReason.SCHEMA_CHANGED,
            detail=f"provider sync failed {item['strikes']} runs in a row: {item['error']}",
        )


def _cli() -> None:
    p = argparse.ArgumentParser(description="Run the refresh pipeline locally.")
    p.add_argument("--source",
                   help="One dataset_id: refresh it if it has a recipe, else queue "
                        "it for authoring (skips scan)")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan + list the authoring queue; refresh and open nothing")
    p.add_argument("--no-trigger-publish", action="store_true",
                   help="Skip the publish trigger after a refresh")
    # `--mode scheduled` is what the Cloud Run job passes, so its scan_runs
    # bookkeeping reads as a production run, not a local debug run.
    p.add_argument("--mode", default="manual", choices=("manual", "scheduled"),
                   help="Run mode recorded on the scan_runs doc. `scheduled` also "
                        "lets SCAN_INCREMENTAL apply, and (not dry, no --source) "
                        "QUIET_WINDOW and the run lease")
    args = p.parse_args()

    summary = asyncio.run(
        run_pipeline(
            mode=args.mode,
            override_id=args.source,
            dry_run=args.dry_run,
            skip_publish=args.no_trigger_publish,
        )
    )
    for line in summarize_for_log(summary):
        print(line, flush=True)

    # A run whose refresh couldn't run or broke down: exit non-zero so the
    # job execution shows up FAILED instead of green (a silently dead batch
    # froze the site for 18 days in 2026-08). An `idle` day is a legitimate
    # success and stays 0.
    if summary.get("status") in FAILED_RUN_STATUSES:
        log.error(
            "pipeline finished with status=%s — exiting non-zero so the job "
            "execution is reported as FAILED",
            summary["status"],
        )
        raise SystemExit(1)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    _cli()
