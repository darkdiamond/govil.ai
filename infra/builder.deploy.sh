#!/usr/bin/env bash
# Deploy the govdata-builder Cloud Run service.
#
# Single container, pinned to one instance, concurrency=1. Parallelism across
# sources lives entirely in asyncio.gather (bounded by MAX_CONCURRENT) inside
# the container — see services/page_builder/pipeline.py. Agent sessions call
# OpenRouter (OPENROUTER_MODEL); switching production model = redeploy with a
# different env var.
#
# Requires:
#   - infra/bootstrap.sh already run (project, SAs, staging bucket exist)
#   - the openrouter-api-key secret created once:
#       gcloud secrets create openrouter-api-key --data-file=<keyfile> --project=<proj>
#       gcloud secrets add-iam-policy-binding openrouter-api-key \
#         --member="serviceAccount:govdata-builder@<proj>.iam.gserviceaccount.com" \
#         --role=roles/secretmanager.secretAccessor --project=<proj>

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
SERVICE=${CLOUD_RUN_SERVICE:-govdata-builder}
STAGING_BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
# Publish path: "github" (Actions, free tier) or "cloudbuild" (legacy
# trigger fallback). github needs the github-dispatch-token secret.
PUBLISH_VIA=${PUBLISH_VIA:-github}
TRIGGER_ID=${PUBLISH_TRIGGER_ID:-govdata-publish}
PUBLISH_BRANCH=${PUBLISH_BRANCH:-main}
# GitHub repo the workflow_dispatch targets. Pinned to the CURRENT name:
# the 2026 govdata→govil.ai rename made GitHub 307-redirect the old path and
# the dispatch silently failed. Keep in lockstep with the actual repo name.
PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO:-darkdiamond/govil.ai}
# Production model (2026-07-21): tencent/hy3 — the PAID tier. Moved off
# tencent/hy3:free when OpenRouter discontinued that free tier (the model
# itself was validated across 477 free-tier drain sessions, 100% self-check
# pass, before the switch). Fallback: minimax/minimax-m3 (~$0.03-0.08/page)
# — one redeploy away. Reasoning effort max matches the eval that chose it.
OPENROUTER_MODEL=${OPENROUTER_MODEL:-tencent/hy3}
OPENROUTER_REASONING_EFFORT=${OPENROUTER_REASONING_EFFORT:-max}
# Backoff + low concurrency below were tuned for the free tier's shared-pool
# 429 congestion. Kept conservative through the paid cutover; safe to relax
# (higher MAX_CONCURRENT, lower RATE_LIMIT_BACKOFF_S) now that the pool isn't
# shared — revisit against paid-tier rate limits before bumping.
RATE_LIMIT_BACKOFF_S=${RATE_LIMIT_BACKOFF_S:-90}
DAILY_CAP=${DAILY_CAP:-10}
MAX_CONCURRENT=${MAX_CONCURRENT:-2}
SESSION_ATTEMPTS=${SESSION_ATTEMPTS:-3}
SCAN_LIMIT=${SCAN_LIMIT:-800}
# Selection date gates (services/page_builder/selector.py). We're expanding
# coverage below the original 2026-01-01 floor one year at a time. Floor at
# 2025-01-01 with a huge max-age disables the rolling window so the floor is
# the sole gate (else now-365d would clip early-2025). SCAN_LIMIT must stay
# >= the count of datasets at/after the floor — bump both in lockstep when
# admitting an older year (2026≈433, +2025≈92, +2024≈101, +2023≈567).
MIN_MODIFIED_FLOOR=${MIN_MODIFIED_FLOOR:-2025-01-01}
MAX_AGE_DAYS=${MAX_AGE_DAYS:-100000}
# Track 2 re-analysis: rebuild a published page when CKAN has re-flagged
# it updated AND the new version is more than REANALYZE_GAP_DAYS past the
# version the page was built from (metadata_modified -
# analyzed_metadata_modified > gap). The baseline is the data version, not
# our run time — a page built today from months-old data refreshes as soon
# as a newer version lands; daily-append datasets self-limit to ~one
# rebuild per gap. Replaced the now-based COOLDOWN_DAYS on 2026-07-15.
REANALYZE_ENABLED=${REANALYZE_ENABLED:-true}
REANALYZE_GAP_DAYS=${REANALYZE_GAP_DAYS:-30}
# Full-data prefetch (services/page_builder/agent_contract.py). Resources
# up to MAX_RECORDS/MAX_BYTES get the whole datastore export streamed
# host-side into the session workdir (saves the agent its pagination tool
# rounds); larger ones fall back to a deterministic SAMPLE_ROWS sample.
# MULTI=true prefetches every datastore-active resource (format twins
# deduped) under the per-dataset TOTAL_BYTES budget. MAX_RECORDS=0 is the
# kill switch. Rollout: stage A = caps below (single resource), stage B =
# MULTI=true, stage C = RETRY_FEEDBACK=true. Survey 2026-07-10: 150MB
# covers ~96% of in-scope datasets in full.
DATA_PREFETCH_MAX_RECORDS=${DATA_PREFETCH_MAX_RECORDS:-2000000}
DATA_PREFETCH_MAX_BYTES=${DATA_PREFETCH_MAX_BYTES:-150000000}
DATA_PREFETCH_TOTAL_BYTES=${DATA_PREFETCH_TOTAL_BYTES:-200000000}
DATA_PREFETCH_WALL_BUDGET_S=${DATA_PREFETCH_WALL_BUDGET_S:-300}
DATA_PREFETCH_SAMPLE_ROWS=${DATA_PREFETCH_SAMPLE_ROWS:-150000}
DATA_PREFETCH_MULTI=${DATA_PREFETCH_MULTI:-true}
# Feed a failed attempt's validation diagnostic into the next attempt's
# user message (fresh workdir/history either way; API flakes stay hintless).
# Default true since 2026-07-15 — every hinted retry in the 477-session
# hy3 drain validated on the next attempt.
RETRY_FEEDBACK=${RETRY_FEEDBACK:-true}
# Weekly reconcile sweep (services/page_builder/pipeline.py): probe already-
# published sources and flag those removed upstream. Enabled in prod since
# rev 00052 (2026-07-21). MUST live here: the deploy uses --set-env-vars,
# which REPLACES the whole env set, so any var not listed is dropped on
# redeploy — omitting this silently reverted reconcile to off. Weekday
# defaults to code (6 = Sunday, Asia/Jerusalem).
RECONCILE_ENABLED=${RECONCILE_ENABLED:-true}
# Recipe refresh — kept in lockstep with infra/builder-job.deploy.sh.
REFRESH_ENABLED=${REFRESH_ENABLED:-false}
AUTHORING_MODE=${AUTHORING_MODE:-cloud}

cd "$(dirname "$0")/.."

BUILDER_SA="govdata-builder@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

echo "==> deploying $SERVICE to Cloud Run ($REGION, project $PROJECT)"
gcloud run deploy "$SERVICE" \
  --source=. \
  --region="$REGION" \
  --service-account="$BUILDER_SA" \
  --cpu=2 \
  --memory=4Gi \
  --max-instances=1 \
  --concurrency=1 \
  --timeout=3600 \
  --no-allow-unauthenticated \
  --set-env-vars="FIRESTORE_PROJECT_ID=${PROJECT},GOOGLE_CLOUD_PROJECT=${PROJECT},FIREBASE_PROJECT=${PROJECT},GCS_STAGING_BUCKET=${STAGING_BUCKET},PUBLISH_VIA=${PUBLISH_VIA},PUBLISH_TRIGGER_ID=${TRIGGER_ID},PUBLISH_BRANCH=${PUBLISH_BRANCH},PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO},OPENROUTER_MODEL=${OPENROUTER_MODEL},OPENROUTER_REASONING_EFFORT=${OPENROUTER_REASONING_EFFORT},RATE_LIMIT_BACKOFF_S=${RATE_LIMIT_BACKOFF_S},DAILY_CAP=${DAILY_CAP},MAX_CONCURRENT=${MAX_CONCURRENT},SESSION_ATTEMPTS=${SESSION_ATTEMPTS},SCAN_LIMIT=${SCAN_LIMIT},MIN_MODIFIED_FLOOR=${MIN_MODIFIED_FLOOR},MAX_AGE_DAYS=${MAX_AGE_DAYS},REANALYZE_ENABLED=${REANALYZE_ENABLED},REANALYZE_GAP_DAYS=${REANALYZE_GAP_DAYS},DATA_PREFETCH_MAX_RECORDS=${DATA_PREFETCH_MAX_RECORDS},DATA_PREFETCH_MAX_BYTES=${DATA_PREFETCH_MAX_BYTES},DATA_PREFETCH_TOTAL_BYTES=${DATA_PREFETCH_TOTAL_BYTES},DATA_PREFETCH_WALL_BUDGET_S=${DATA_PREFETCH_WALL_BUDGET_S},DATA_PREFETCH_SAMPLE_ROWS=${DATA_PREFETCH_SAMPLE_ROWS},DATA_PREFETCH_MULTI=${DATA_PREFETCH_MULTI},RETRY_FEEDBACK=${RETRY_FEEDBACK},RECONCILE_ENABLED=${RECONCILE_ENABLED},REFRESH_ENABLED=${REFRESH_ENABLED},AUTHORING_MODE=${AUTHORING_MODE}" \
  --set-secrets="OPENROUTER_API_KEY=openrouter-api-key:latest,GITHUB_DISPATCH_TOKEN=github-dispatch-token:latest,VOYAGE_API_KEY=voyage-api-key:latest" \
  --project="$PROJECT"

echo "==> granting Cloud Scheduler SA permission to invoke this service"
gcloud run services add-iam-policy-binding "$SERVICE" \
  --member="serviceAccount:$SCHEDULER_SA" \
  --role=roles/run.invoker \
  --region="$REGION" \
  --project="$PROJECT" \
  --quiet >/dev/null

URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT" --format='value(status.url)')
echo
echo "==> service deployed at: $URL"
echo
echo "Manual test:"
echo "  TOKEN=\$(gcloud auth print-identity-token)"
echo "  curl -X POST \"$URL\" -H \"Authorization: Bearer \$TOKEN\" -H 'Content-Type: application/json' -d '{\"dry_run\": true}'"
