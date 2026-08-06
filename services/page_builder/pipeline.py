"""Builder pipeline — what a single Cloud Run invocation does.

Daily batch (Cloud Scheduler, 07:00 Asia/Jerusalem): scan CKAN → select
every never-analyzed (or retryable-failed) source up to DAILY_CAP →
run all agent sessions concurrently (asyncio.gather bounded by
Semaphore(MAX_CONCURRENT)) → mark each source in Firestore → if ≥1 page
succeeded, trigger the Cloud Build publisher (no new pages → no build).

All parallelism is in-process. Cloud Run is pinned to one container
(`--max-instances=1 --concurrency=1`), so a scheduler tick produces
exactly one pipeline run; sessions are PydanticAI agent loops calling
OpenRouter (OPENROUTER_MODEL), with tool execution in per-session
subprocess sandboxes inside this same container.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

from services.scanner.config import ScannerSettings
from services.scanner.main import Scanner
from services.scanner.state import StateDB
from services.shared.firestore import FirestoreStateStore, SourceRecord

from . import selector
from .agent_contract import ResourceRestrictedError
from .agent_runner import run_production_session

log = logging.getLogger("page_builder.pipeline")


def _reconcile_due(now: datetime, *, enabled: bool, weekday: int) -> bool:
    """Weekly reconcile runs only when enabled AND today matches the
    configured weekday (Python Monday=0 .. Sunday=6)."""
    return enabled and now.weekday() == weekday


async def _build_one(
    src: SourceRecord,
    staging_bucket: str,
    store: FirestoreStateStore,
    sem: asyncio.Semaphore,
) -> dict:
    """Run one self-validating agent session. Updates Firestore either way."""
    async with sem:
        log.info("building %s — %s", src.id[:8], (src.title or "")[:60])
        # Capture the source's metadata_modified *before* the agent runs — this
        # is the data vintage the agent's content will be based on. Persisted on
        # success so the dataset page can show "המידע נכון ל-X" honestly even
        # after CKAN re-publishes a newer version.
        analyzed_metadata_modified = src.metadata_modified
        await asyncio.to_thread(store.mark_analysis_pending, src.id)

        try:
            result = await asyncio.to_thread(
                run_production_session,
                dataset_id=src.id,
                title=src.title,
                notes=src.notes or "",
                org_title=(src.organization or {}).get("title", "") or "",
                resources=src.resources,
                organization=src.organization,
                gcs_bucket=staging_bucket,
                store=store,
            )
        except ResourceRestrictedError as e:
            # The primary resource's data is 403-restricted upstream — raised
            # by the CKAN prefetch before any agent session ran (no model
            # cost). Park the source as `restricted` (a deliberate exclusion,
            # not a retryable failure): it's skipped by the selector and the
            # publisher until it reappears in CKAN search. `restricted` is
            # neither `succeeded` nor `failed`, so it won't trigger a publish
            # or burn the failed-retry budget.
            log.warning("build skipped for %s — data restricted: %s", src.id, e)
            await asyncio.to_thread(store.mark_analysis_restricted, src.id, str(e))
            return {"id": src.id, "status": "restricted", "error": str(e)}
        except Exception as e:
            log.exception("build failed for %s", src.id)
            await asyncio.to_thread(store.mark_analysis_failed, src.id, str(e))
            return {"id": src.id, "status": "failed", "error": str(e)}

        # run_production_session already wrote `sources/<id>.agent_data`.
        page_path = f"datasets/{src.id}/"
        await asyncio.to_thread(
            store.mark_analysis_succeeded,
            src.id,
            page_path,
            analyzed_metadata_modified,
        )
        return {
            "id": src.id,
            "status": "succeeded",
            "session_id": result.session_id,
            "attempts": result.attempts,
            "elapsed_seconds": result.elapsed_seconds,
            "usage": result.usage,
            "cost": result.cost,
            "written": result.written,
        }


async def _trigger_publish_github(repo: str, workflow: str, branch: str) -> Optional[str]:
    """Fire the GitHub Actions publish workflow (workflow_dispatch).

    Fire-and-forget — the API returns 204 with no run id, so we return a
    synthetic marker for the summary. Needs GITHUB_DISPATCH_TOKEN (a
    fine-grained PAT with Actions:write on this repo, from Secret Manager).
    """
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()
    if not token:
        log.error("PUBLISH_VIA=github but GITHUB_DISPATCH_TOKEN is not set")
        return None

    def _run() -> Optional[str]:
        import httpx

        # follow_redirects: GitHub answers a renamed repo with a 307 that
        # preserves the POST method + body. Without this a repo rename
        # silently breaks the daily publish dispatch (govdata→govil.ai did
        # exactly that — 307 → logged failure, pages built but not deployed).
        r = httpx.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
            json={"ref": branch},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            follow_redirects=True,
        )
        if r.status_code != 204:
            log.error(
                "github workflow_dispatch failed: %s %s", r.status_code, r.text[:300]
            )
            return None
        return f"gh-actions:{repo}/{workflow}@{branch}"

    try:
        return await asyncio.to_thread(_run)
    except Exception:
        log.exception("trigger_publish (github) failed")
        return None


async def _trigger_publish(
    project_id: str, trigger_id: str, branch: str, region: str = "me-west1"
) -> Optional[str]:
    """Fire the Cloud Build publisher (fallback path, PUBLISH_VIA=cloudbuild).

    Fire-and-forget — don't wait for the build. Uses the regional Cloud
    Build endpoint; triggers created with `--region=me-west1` are not
    reachable via the global endpoint.
    """

    def _run() -> Optional[str]:
        from google.api_core.client_options import ClientOptions
        from google.cloud.devtools import cloudbuild_v1
        from google.cloud.devtools.cloudbuild_v1.types import RunBuildTriggerRequest
        from google.cloud.devtools.cloudbuild_v1.types import RepoSource

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
    except Exception as e:
        log.exception("trigger_publish failed")
        return None


async def run_pipeline(
    *,
    mode: str = "scheduled",
    override_id: Optional[str] = None,
    dry_run: bool = False,
    n_per_run: Optional[int] = None,
    skip_publish: bool = False,
) -> dict:
    """The one entry point the HTTP handler and the CLI both use."""
    store = FirestoreStateStore()
    db = StateDB(store=store)
    config = ScannerSettings()

    # DAILY_CAP bounds "analyze everything new" — purely a cost fuse;
    # anything past the cap stays `never` and is picked up tomorrow.
    n = n_per_run if n_per_run is not None else int(os.environ.get("DAILY_CAP", "50"))
    max_concurrent = int(os.environ.get("MAX_CONCURRENT", "8"))
    # Stopgap knob: pause Track 2 re-analysis (sources CKAN re-flagged as
    # updated) until structural-change gating lands. Track 1 still runs.
    reanalyze = os.environ.get("REANALYZE_ENABLED", "true").lower() not in (
        "false",
        "0",
        "no",
    )
    # SCAN_LIMIT bounds how many CKAN datasets (sorted metadata_modified
    # desc) the daily scan ingests into Firestore. The selector can only
    # pick what's been scanned, so this must cover the eligible window:
    # 2026 (~433) + 2025 (~92) → 800 with headroom. Raise it in lockstep
    # when MIN_MODIFIED_FLOOR drops to admit an older year.
    scan_limit = int(os.environ.get("SCAN_LIMIT", "800"))
    # Selection date gates, env-overridable so widening coverage one year
    # at a time is a `gcloud run` env change, not a redeploy. Unset →
    # selector.DEFAULT_* (floor 2026-01-01, rolling window 365d).
    # Prod currently runs MIN_MODIFIED_FLOOR=2025-01-01 with MAX_AGE_DAYS
    # large enough to disable the rolling window, so the floor is the sole
    # gate while we expand coverage.
    selector_gates: dict = {}
    floor_env = os.environ.get("MIN_MODIFIED_FLOOR", "").strip()
    if floor_env:
        floor_dt = datetime.fromisoformat(floor_env)
        if floor_dt.tzinfo is None:
            floor_dt = floor_dt.replace(tzinfo=timezone.utc)
        selector_gates["min_modified_floor"] = floor_dt
    max_age_env = os.environ.get("MAX_AGE_DAYS", "").strip()
    if max_age_env:
        selector_gates["max_age_days"] = int(max_age_env)
    # Track 2 re-analysis gap: a CKAN-updated source is rebuilt only when
    # its update landed more than this many days after our last analysis
    # (metadata_modified - last_analyzed_at > gap). Env-overridable
    # (unset → selector.DEFAULT_REANALYZE_GAP_DAYS = 30). Replaces the
    # old now-based COOLDOWN_DAYS (2026-07-15): pages whose data moved on
    # 30+ days after we built them refresh on the next run; daily-append
    # datasets self-limit to ~monthly.
    gap_env = os.environ.get("REANALYZE_GAP_DAYS", "").strip()
    if gap_env:
        selector_gates["reanalyze_gap_days"] = int(gap_env)
    staging_bucket = os.environ.get("GCS_STAGING_BUCKET", "")
    project_id = (
        os.environ.get("FIREBASE_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or "govdata-il"
    )
    # Publish mechanism: "github" (Actions workflow_dispatch, default),
    # "cloudbuild" (legacy trigger, fallback), or "" to disable publishing.
    publish_via = os.environ.get("PUBLISH_VIA", "github").strip().lower()
    publish_repo = os.environ.get("PUBLISH_GITHUB_REPO", "darkdiamond/govil.ai")
    publish_workflow = os.environ.get("PUBLISH_GITHUB_WORKFLOW", "publish.yml")
    trigger_id = os.environ.get("PUBLISH_TRIGGER_ID", "govdata-publish")
    publish_branch = os.environ.get("PUBLISH_BRANCH", "main")
    publish_region = os.environ.get("PUBLISH_REGION", "me-west1")

    if not dry_run and not override_id and not staging_bucket:
        raise RuntimeError(
            "GCS_STAGING_BUCKET must be set for a real pipeline run"
        )

    # [0] weekly reconcile — probe already-published sources and flag those
    # removed upstream (they vanish from CKAN's list, so the scan below
    # never revisits them). Gated by RECONCILE_ENABLED + RECONCILE_WEEKDAY
    # (Asia/Jerusalem), default off / Sunday. Full sweep, no cursor.
    reconcile_summary = None
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
    except Exception:
        il_now = datetime.now(timezone.utc)
    if not dry_run and not override_id and _reconcile_due(
        il_now, enabled=reconcile_enabled, weekday=reconcile_weekday
    ):
        from services.scanner.client import CKANClient
        from . import reconcile as _reconcile
        log.info("reconcile: due (weekday=%s) — running sweep", reconcile_weekday)
        try:
            async with CKANClient(config=config) as _ckan:
                reconcile_summary = await _reconcile.reconcile_sources(store, _ckan)
            log.info("reconcile: %s", reconcile_summary)
        except Exception:
            log.exception("reconcile sweep failed — continuing with scan/build")

    # [1] scan — unless override_id is set (manual single-source invoke)
    scan_summary = None
    if not override_id:
        scanner = Scanner(config=config, db=db)
        scan_summary = await scanner.scan(limit=scan_limit, mode=mode)

    # [1.5] reap orphaned `pending` markers from a previous run that died
    # mid-session. No selector track matches `pending`, so without this every
    # interrupted session leaks one dataset permanently (7 had accumulated by
    # 2026-08-05, when the run started hitting the Cloud Run request timeout
    # daily). Recycled as `failed`, so Track 1b retries them and
    # `failed_attempts` parks the hopeless ones after 3 tries.
    reaped: list[str] = []
    if not override_id and not dry_run:
        reap_after = int(os.environ.get("PENDING_REAP_MINUTES", "120"))
        try:
            reaped = await asyncio.to_thread(
                store.reap_stale_pending, older_than_minutes=reap_after
            )
            if reaped:
                log.info(
                    "reaped %d orphaned pending source(s): %s",
                    len(reaped),
                    ", ".join(i[:8] for i in reaped),
                )
        except Exception:
            log.exception("pending reap failed — continuing with select")

    # [2] select
    if override_id:
        src = await asyncio.to_thread(store.get_source, override_id)
        if src is None:
            raise RuntimeError(f"override source {override_id} not found in Firestore")
        to_process = [src]
    else:
        to_process = await asyncio.to_thread(
            selector.pick_next, store, n, reanalyze=reanalyze, **selector_gates
        )

    summary: dict = {
        "mode": mode,
        "dry_run": dry_run,
        "selected": [s.id for s in to_process],
        "scan": _scan_summary_dict(scan_summary) if scan_summary else None,
        "reconcile": reconcile_summary,
        "reaped_pending": reaped,
    }

    if dry_run or not to_process:
        summary["processed"] = []
        summary["build_id"] = None
        summary["status"] = "idle" if not to_process else "dry_run"
        return summary

    # [3] fan-out agent sessions, bounded by MAX_CONCURRENT.
    # `_build_one` runs the sync agent loop via `asyncio.to_thread`, which
    # uses the event loop's default ThreadPoolExecutor. That executor's
    # default cap is `min(32, os.cpu_count() + 4)` — on a 2-CPU Cloud Run
    # container that's ~8, which would silently bottleneck below
    # MAX_CONCURRENT (plus the Firestore mark calls also ride this pool).
    # Widen it; the semaphore is the real concurrency control.
    loop = asyncio.get_running_loop()
    loop.set_default_executor(
        ThreadPoolExecutor(max_workers=max(max_concurrent * 2, 16))
    )
    sem = asyncio.Semaphore(max_concurrent)
    results = await asyncio.gather(
        *[_build_one(src, staging_bucket, store, sem) for src in to_process]
    )
    summary["processed"] = results
    succeeded_ids = [r["id"] for r in results if r.get("status") == "succeeded"]

    # [4] trigger publisher if any page was written
    build_id = None
    if succeeded_ids and not skip_publish:
        if publish_via == "github":
            build_id = await _trigger_publish_github(
                publish_repo, publish_workflow, publish_branch
            )
        elif publish_via == "cloudbuild" and trigger_id:
            build_id = await _trigger_publish(
                project_id, trigger_id, publish_branch, region=publish_region
            )
        elif publish_via:
            log.error("unknown PUBLISH_VIA=%r — publish skipped", publish_via)
    summary["build_id"] = build_id
    summary["status"] = "ok" if succeeded_ids else "all_failed"
    return summary


def _scan_summary_dict(s) -> dict:
    return {
        "sources_seen": s.datasets_scanned,
        "new": s.datasets_new,
        "updated": s.datasets_updated,
        "unchanged": s.datasets_unchanged,
        "errors": list(s.errors or []),
    }


def _cli() -> None:
    p = argparse.ArgumentParser(description="Run the builder pipeline locally.")
    p.add_argument("--source", help="Specific dataset_id to build (skip scan+select)")
    p.add_argument("--dry-run", action="store_true", help="Scan + select but don't build")
    p.add_argument("--n", type=int, default=None, help="Override DAILY_CAP")
    p.add_argument("--no-trigger-publish", action="store_true",
                   help="Skip Cloud Build trigger after successful builds")
    # `--mode scheduled` is what the Cloud Run *job* passes: a job execution is
    # the production daily batch, so its scan_runs bookkeeping must match what
    # the HTTP service recorded, not read as a local debug run. Default stays
    # `manual` so nothing changes for hand-run CLI invocations.
    p.add_argument("--mode", default="manual", choices=("manual", "scheduled"),
                   help="Run mode recorded on the scan_runs doc")
    args = p.parse_args()

    summary = asyncio.run(
        run_pipeline(
            mode=args.mode,
            override_id=args.source,
            dry_run=args.dry_run,
            n_per_run=args.n,
            skip_publish=args.no_trigger_publish,
        )
    )
    import json
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    _cli()
