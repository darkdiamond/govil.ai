"""Builder pipeline — what one daily job execution does.

Cloud Scheduler, 06:00 Asia/Jerusalem: scan CKAN → refresh every recipe'd
source CKAN moved past (deterministic, no LLM — services/page_builder/
refresh.py) → queue every new or changed source that has no recipe for
authoring (one `needs-authoring` GitHub issue each, solved by the daily
local Claude Code routine) → if ≥1 page re-rendered, trigger the publisher.

No model runs here. A recipe merged to main is picked up on the next run
(the refresh reads recipes/ straight from git).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from services.scanner.config import ScannerSettings
from services.scanner.main import Scanner
from services.scanner.state import StateDB
from services.shared.firestore import FirestoreStateStore

from . import refresh as _refresh
from . import selector

log = logging.getLogger("page_builder.pipeline")

# Run outcomes that must surface as a failed job execution rather than a
# green one. `idle` is deliberately absent — a day with nothing to refresh
# is a normal, healthy outcome. The refresh is the only way a page changes,
# so a refresh that couldn't run (no recipe list, crash, staging down) is a
# dead run even if the authoring queue still went out.
FAILED_RUN_STATUSES = ("refresh_unavailable", "refresh_failed")


def _reconcile_due(now: datetime, *, enabled: bool, weekday: int) -> bool:
    """Weekly reconcile runs only when enabled AND today matches the
    configured weekday (Python Monday=0 .. Sunday=6)."""
    return enabled and now.weekday() == weekday


async def _trigger_publish_github(
    repo: str, workflow: str, branch: str, inputs: Optional[dict] = None
) -> Optional[str]:
    """Fire the GitHub Actions publish workflow (workflow_dispatch).

    Fire-and-forget — the API returns 204 with no run id, so we return a
    synthetic marker for the summary. Needs GITHUB_DISPATCH_TOKEN (a
    fine-grained PAT with Actions:write on this repo, from Secret Manager).
    `inputs` are workflow_dispatch inputs (`{"target": "preview"}` deploys
    the recipe-refresh demo channel instead of live).
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
            json={"ref": branch, **({"inputs": inputs} if inputs else {})},
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


async def _dispatch_publish(
    should: bool,
    publish_via: str,
    repo: str,
    workflow: str,
    branch: str,
    project_id: str,
    trigger_id: str,
    region: str,
) -> Optional[str]:
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
    override_id: Optional[str] = None,
    dry_run: bool = False,
    skip_publish: bool = False,
) -> dict:
    """The one entry point the job (CLI) uses."""
    store = FirestoreStateStore()
    db = StateDB(store=store)
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
            floor_dt = floor_dt.replace(tzinfo=timezone.utc)
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
    publish_repo = os.environ.get("PUBLISH_GITHUB_REPO", "darkdiamond/govil.ai")
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
            log.exception("reconcile sweep failed — continuing with scan/refresh")

    # [1] scan — unless override_id is set (manual single-source run)
    scan_summary = None
    if not override_id:
        scanner = Scanner(config=config, db=db)
        scan_summary = await scanner.scan(limit=scan_limit, mode=mode)

    # [1.5] reap orphaned `pending` markers left by the retired agent
    # builder (a run that died mid-session). Recycled as `failed`, which the
    # authoring queue treats as `new`. Nothing writes `pending` any more, so
    # this only drains the legacy set.
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
            log.exception("pending reap failed — continuing")

    summary: dict = {
        "mode": mode,
        "dry_run": dry_run,
        "scan": _scan_summary_dict(scan_summary) if scan_summary else None,
        "reconcile": reconcile_summary,
        "reaped_pending": reaped,
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
        summary["status"] = "refresh_unavailable"
        return summary

    # [3] candidates: the override, or every recipe'd source CKAN moved
    # past (run_refresh decides) + the authoring queue.
    if override_id:
        src = await asyncio.to_thread(store.get_source, override_id)
        if src is None:
            raise RuntimeError(f"override source {override_id} not found in Firestore")
        only_ids = [override_id] if override_id in recipe_ids else []
        to_queue = [] if only_ids else [(src, "legacy_updated" if src.page_path else "new")]
    else:
        only_ids = None
        to_queue = await asyncio.to_thread(
            selector.pick_authoring_candidates,
            store,
            notify_cap,
            exclude_ids=recipe_ids,
            **selector_gates,
        )
    summary["selected_for_authoring"] = [s.id for s, _ in to_queue]
    if dry_run:
        summary["status"] = "dry_run"
        return summary

    # [4] refresh — deterministic re-render of recipe'd sources.
    refresh_broken = False
    if only_ids is None or only_ids:
        try:
            summary["refresh"] = await asyncio.to_thread(
                _refresh.run_refresh,
                store,
                repo,
                preview=False,
                staging_bucket=staging_bucket,
                only_ids=only_ids,
            )
            refresh_broken = bool(summary["refresh"].get("staging_down"))
        except Exception:
            log.exception("recipe refresh failed — continuing with the authoring queue")
            refresh_broken = True
    refreshed_ids = list((summary["refresh"] or {}).get("refreshed") or [])

    # [5] authoring queue: one issue per source, idempotent.
    for src, reason in to_queue:
        issue = await asyncio.to_thread(_refresh.queue_authoring, store, src, reason)
        summary["authoring_queued"].append({"id": src.id, "reason": reason, "issue": issue})

    # [6] publish whatever re-rendered.
    summary["build_id"] = await _dispatch_publish(
        bool(refreshed_ids) and not skip_publish,
        publish_via, publish_repo, publish_workflow, publish_branch,
        project_id, trigger_id, publish_region,
    )
    # Pages that did refresh before a breakdown still publish (above); the
    # run is red either way.
    if refresh_broken:
        summary["status"] = "refresh_failed"
    else:
        summary["status"] = "ok" if refreshed_ids else "idle"
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
    import json
    print(json.dumps(summary, indent=2, default=str))

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
