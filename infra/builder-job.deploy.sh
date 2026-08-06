#!/usr/bin/env bash
# Deploy the govdata-builder-job Cloud Run JOB — the daily agent batch.
#
# WHY A JOB AND NOT THE SERVICE
# -----------------------------
# The batch used to run inside one HTTP request on the govdata-builder
# service. A Cloud Run *service* caps request timeout at 3600s, and from
# 2026-08-01 the batch outgrew it: every scheduler tick returned 504 at
# exactly 3600.000s. Because the publish dispatch is the LAST step of
# run_pipeline (after asyncio.gather over every source), the container was
# killed before it ever fired — so pages were built, staged to GCS and marked
# succeeded in Firestore, but the site sat frozen for 5 days while OpenRouter
# billed for the work. A Cloud Run job has no request semantics and takes
# --task-timeout up to 24h, so the run reaches its own end and publishes.
#
# Shape: one execution invokes all the agent sessions; when they finish, the
# run dispatches the GitHub Actions publisher itself (PUBLISH_VIA=github).
#
# The govdata-builder SERVICE stays deployed on purpose:
#   - manual single-dataset invokes ({"dataset_id": "..."}) still work
#   - instant rollback — repoint the scheduler at the service URL
#
# Env + secrets below are kept byte-identical to infra/builder.deploy.sh.
# Both use --set-env-vars, which REPLACES the whole set: a var missing here is
# silently dropped on deploy (that is how RECONCILE_ENABLED once reverted to
# off). When you change one script, change the other.

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
JOB=${CLOUD_RUN_JOB:-govdata-builder-job}
STAGING_BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
# Wall-clock ceiling for the whole daily batch. 6h at DAILY_CAP=10 /
# MAX_CONCURRENT=2 leaves generous headroom over the slowest observed session
# (4324s on 2026-08-05). Max allowed is 24h. --max-retries=0: a partially
# built batch must not restart from scratch and re-bill the sessions that
# already succeeded — the next daily run picks up the remainder.
TASK_TIMEOUT=${TASK_TIMEOUT:-21600s}
MAX_RETRIES=${MAX_RETRIES:-0}

PUBLISH_VIA=${PUBLISH_VIA:-github}
TRIGGER_ID=${PUBLISH_TRIGGER_ID:-govdata-publish}
PUBLISH_BRANCH=${PUBLISH_BRANCH:-main}
PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO:-darkdiamond/govil.ai}
OPENROUTER_MODEL=${OPENROUTER_MODEL:-tencent/hy3}
OPENROUTER_REASONING_EFFORT=${OPENROUTER_REASONING_EFFORT:-max}
RATE_LIMIT_BACKOFF_S=${RATE_LIMIT_BACKOFF_S:-90}
DAILY_CAP=${DAILY_CAP:-10}
MAX_CONCURRENT=${MAX_CONCURRENT:-2}
SESSION_ATTEMPTS=${SESSION_ATTEMPTS:-3}
SCAN_LIMIT=${SCAN_LIMIT:-800}
MIN_MODIFIED_FLOOR=${MIN_MODIFIED_FLOOR:-2025-01-01}
MAX_AGE_DAYS=${MAX_AGE_DAYS:-100000}
REANALYZE_ENABLED=${REANALYZE_ENABLED:-true}
REANALYZE_GAP_DAYS=${REANALYZE_GAP_DAYS:-30}
DATA_PREFETCH_MAX_RECORDS=${DATA_PREFETCH_MAX_RECORDS:-2000000}
DATA_PREFETCH_MAX_BYTES=${DATA_PREFETCH_MAX_BYTES:-150000000}
DATA_PREFETCH_TOTAL_BYTES=${DATA_PREFETCH_TOTAL_BYTES:-200000000}
DATA_PREFETCH_WALL_BUDGET_S=${DATA_PREFETCH_WALL_BUDGET_S:-300}
DATA_PREFETCH_SAMPLE_ROWS=${DATA_PREFETCH_SAMPLE_ROWS:-150000}
DATA_PREFETCH_MULTI=${DATA_PREFETCH_MULTI:-true}
RETRY_FEEDBACK=${RETRY_FEEDBACK:-true}
RECONCILE_ENABLED=${RECONCILE_ENABLED:-true}
# Orphaned `pending` markers older than this are recycled as retryable
# failures at the start of a run (services/shared/firestore.py::
# reap_stale_pending). Keep it above the slowest expected session so a
# manual run overlapping the scheduled one can't reap its live sessions.
PENDING_REAP_MINUTES=${PENDING_REAP_MINUTES:-120}

cd "$(dirname "$0")/.."

BUILDER_SA="govdata-builder@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

ENV_VARS="FIRESTORE_PROJECT_ID=${PROJECT},GOOGLE_CLOUD_PROJECT=${PROJECT},FIREBASE_PROJECT=${PROJECT},GCS_STAGING_BUCKET=${STAGING_BUCKET},PUBLISH_VIA=${PUBLISH_VIA},PUBLISH_TRIGGER_ID=${TRIGGER_ID},PUBLISH_BRANCH=${PUBLISH_BRANCH},PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO},OPENROUTER_MODEL=${OPENROUTER_MODEL},OPENROUTER_REASONING_EFFORT=${OPENROUTER_REASONING_EFFORT},RATE_LIMIT_BACKOFF_S=${RATE_LIMIT_BACKOFF_S},DAILY_CAP=${DAILY_CAP},MAX_CONCURRENT=${MAX_CONCURRENT},SESSION_ATTEMPTS=${SESSION_ATTEMPTS},SCAN_LIMIT=${SCAN_LIMIT},MIN_MODIFIED_FLOOR=${MIN_MODIFIED_FLOOR},MAX_AGE_DAYS=${MAX_AGE_DAYS},REANALYZE_ENABLED=${REANALYZE_ENABLED},REANALYZE_GAP_DAYS=${REANALYZE_GAP_DAYS},DATA_PREFETCH_MAX_RECORDS=${DATA_PREFETCH_MAX_RECORDS},DATA_PREFETCH_MAX_BYTES=${DATA_PREFETCH_MAX_BYTES},DATA_PREFETCH_TOTAL_BYTES=${DATA_PREFETCH_TOTAL_BYTES},DATA_PREFETCH_WALL_BUDGET_S=${DATA_PREFETCH_WALL_BUDGET_S},DATA_PREFETCH_SAMPLE_ROWS=${DATA_PREFETCH_SAMPLE_ROWS},DATA_PREFETCH_MULTI=${DATA_PREFETCH_MULTI},RETRY_FEEDBACK=${RETRY_FEEDBACK},RECONCILE_ENABLED=${RECONCILE_ENABLED},PENDING_REAP_MINUTES=${PENDING_REAP_MINUTES}"
SECRETS="OPENROUTER_API_KEY=openrouter-api-key:latest,GITHUB_DISPATCH_TOKEN=github-dispatch-token:latest,VOYAGE_API_KEY=voyage-api-key:latest"
# The image CMD starts functions-framework for the HTTP service; a job must
# instead run the pipeline once and exit. Same module the CLI uses.
COMMAND="python"
CMD_ARGS="-m,services.page_builder.pipeline,--mode,scheduled"

echo "==> deploying job $JOB to Cloud Run ($REGION, project $PROJECT)"
gcloud run jobs deploy "$JOB" \
  --source=. \
  --region="$REGION" \
  --service-account="$BUILDER_SA" \
  --cpu=2 \
  --memory=4Gi \
  --task-timeout="$TASK_TIMEOUT" \
  --max-retries="$MAX_RETRIES" \
  --parallelism=1 \
  --tasks=1 \
  --command="$COMMAND" \
  --args="$CMD_ARGS" \
  --set-env-vars="$ENV_VARS" \
  --set-secrets="$SECRETS" \
  --project="$PROJECT"

echo "==> granting Cloud Scheduler SA permission to run this job"
gcloud run jobs add-iam-policy-binding "$JOB" \
  --member="serviceAccount:$SCHEDULER_SA" \
  --role=roles/run.invoker \
  --region="$REGION" \
  --project="$PROJECT" \
  --quiet >/dev/null

echo
echo "==> job deployed:"
gcloud run jobs describe "$JOB" --region="$REGION" --project="$PROJECT" \
  --format="value(name,spec.template.spec.taskCount,spec.template.spec.template.spec.timeoutSeconds)"
echo
echo "Manual test (dry run — scan + select, no agent sessions, no publish):"
echo "  gcloud run jobs execute $JOB --region=$REGION --project=$PROJECT \\"
echo "    --args=-m,services.page_builder.pipeline,--dry-run --wait"
echo
echo "Point the daily scheduler at it:"
echo "  ./infra/scheduler.setup.sh   # TARGET=job"
