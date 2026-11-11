"""Builder pipeline — what one job execution (06:00 or 14:00 tick) does.

Cloud Scheduler, 06:00 + 14:00 Asia/Jerusalem: scan CKAN → refresh every recipe'd
source CKAN moved past (deterministic, no LLM — services/page_builder/
refresh.py) → queue every new or changed source that has no recipe for
authoring (one `needs-authoring` GitHub issue each, solved by the daily
local Claude Code routine) → if ≥1 page re-rendered (or an earlier run's
dispatch failed), trigger the publisher.

No model runs here. A recipe merged to main is picked up on the next run
(the refresh reads recipes/ straight from git).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import UTC, datetime

from services.scanner.config import ScannerSettings
from services.scanner.main import Scanner
from services.shared import github
from services.shared.firestore import FirestoreStateStore
from services.shared.states import NO_DATA_STATUSES, AuthoringReason, RunStatus

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
    twice a day, and one sweep a week is enough. A marker read failure
    answers False, so the sweep runs rather than being skipped."""
    try:
        return store.get_job_marker("reconcile").get("last_date") == now.date().isoformat()
    except Exception:
        log.warning("reconcile: couldn't read the last-sweep marker", exc_info=True)
        return False


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


async def run_pipeline(
    *,
    mode: str = "scheduled",
    override_id: str | None = None,
    dry_run: bool = False,
    skip_publish: bool = False,
) -> dict:
    """The one entry point the job (CLI) uses."""
    store = FirestoreStateStore()
    config = ScannerSettings()

    # SCAN_LIMIT bounds how many CKAN datasets (sorted metadata_modified
    # desc) the daily scan ingests into Firestore. The authoring queue can
    # only see what's been scanned, so this must cover the eligible window:
    # 2026 (~433) + 2025 (~92) → 800 with headroom. Raise it in lockstep
    # when MIN_MODIFIED_FLOOR drops to admit an older year.
    scan_limit = int(os.environ.get("SCAN_LIMIT", "800"))
    # New issues opened per run — a fuse against a scan anomaly flooding the
    # tracker. Already-notified sources don't count (the selector skips them).
    notify_cap = int(os.environ.get("AUTHORING_NOTIFY_CAP", "100"))
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
    max_age_env = os.environ.get("MAX_AGE_DAYS", "").strip()
    if max_age_env:
        selector_gates["max_age_days"] = int(max_age_env)
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

    if not dry_run and not staging_bucket:
        raise RuntimeError(
            "GCS_STAGING_BUCKET must be set for a real pipeline run"
        )

    # [0] weekly reconcile — probe already-published sources and flag those
    # removed upstream (they vanish from CKAN's list, so the scan below
    # never revisits them). Gated by RECONCILE_ENABLED + RECONCILE_WEEKDAY
    # (Asia/Jerusalem), default off / Sunday. Full sweep, no cursor.
    reconcile_summary = None
    reconcile_failed = False
    reconcile_enabled = os.environ.get("RECONCILE_ENABLED", "false").lower() in (
        "true", "1", "yes",
    )
    try:
        reconcile_weekday = int(os.environ.get("RECONCILE_WEEKDAY", "6"))
    except ValueError:
        log.warning("invalid RECONCILE_WEEKDAY=%r — defaulting to 6 (Sunday)",
                    os.environ.get("RECONCILE_WEEKDAY"))
        reconcile_weekday = 6
    try:
        from zoneinfo import ZoneInfo
        il_now = datetime.now(ZoneInfo("Asia/Jerusalem"))
    except Exception:  # noqa: BLE001
        il_now = datetime.now(UTC)
    if not dry_run and not override_id and _reconcile_due(
        il_now, enabled=reconcile_enabled, weekday=reconcile_weekday
    ) and not _reconciled_today(store, il_now):
        from services.scanner.client import CKANClient

        from . import reconcile as _reconcile
        log.info("reconcile: due (weekday=%s) — running sweep", reconcile_weekday)
        try:
            async with CKANClient(config=config) as _ckan:
                reconcile_summary = await _reconcile.reconcile_sources(store, _ckan)
            log.info("reconcile: %s", reconcile_summary)
            if reconcile_summary.get("aborted"):
                # No marker: the next run today sweeps again.
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
            scan_summary = await scanner.scan(limit=scan_limit, mode=mode)
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
                notify_cap,
                exclude_ids=recipe_ids,
                **selector_gates,
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
                staging_bucket=staging_bucket,
                only_ids=only_ids,
                # A manual single-dataset run means "render it now", even
                # when the page is already up to date.
                force=bool(override_id),
            )
            refresh_broken = bool(summary["refresh"].get("staging_down"))
        except Exception:
            log.exception("recipe refresh failed — continuing with the authoring queue")
            refresh_broken = True
    refreshed_ids = list((summary["refresh"] or {}).get("refreshed") or [])

    # [5] authoring queue: one issue per source, idempotent. A failure here
    # (selector query, Firestore, GitHub) must not cost the publish below.
    authoring_broken = False
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
        publish_via, publish_repo, publish_workflow, publish_branch,
        project_id, trigger_id, publish_region,
    )
    publish_failed = publish_due and bool(publish_via) and summary["build_id"] is None
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
    return {
        "sources_seen": s.datasets_scanned,
        "new": s.datasets_new,
        "updated": s.datasets_updated,
        "unchanged": s.datasets_unchanged,
        "errors": list(s.errors or []),
        "error_count": s.error_count,
    }


def summarize_for_log(summary: dict) -> list[str]:
    """The run summary as compact one-line JSON records: a headline, then one
    line per refresh outcome that did something. The whole summary as one
    indented block was ~4,000 lines stamped in the same millisecond, which
    Cloud Logging reordered and partly dropped (2026-10-31). Up-to-date skips,
    most of every run, only count in the headline."""
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
        if o.get("status") == "skipped" and o.get("reason") == "up_to_date":
            continue
        kept = {k: v for k, v in o.items() if v is not None and v != {} and v != []}
        lines.append(line({"refresh_outcome": kept}))
    return lines


def _cli() -> None:
    p = argparse.ArgumentParser(description="Run the daily refresh pipeline locally.")
    p.add_argument("--source",
                   help="One dataset_id: refresh it if it has a recipe, else queue "
                        "it for authoring (skips scan)")
    p.add_argument("--dry-run", action="store_true",
                   help="Scan + list the authoring queue; refresh and open nothing")
    p.add_argument("--no-trigger-publish", action="store_true",
                   help="Skip the publish trigger after a refresh")
    # `--mode scheduled` is what the Cloud Run job passes, so its scan_runs
    # bookkeeping reads as the production daily run, not a local debug run.
    p.add_argument("--mode", default="manual", choices=("manual", "scheduled"),
                   help="Run mode recorded on the scan_runs doc")
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
