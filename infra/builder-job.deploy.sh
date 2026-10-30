#!/usr/bin/env bash
# Deploy the govdata-builder-job Cloud Run JOB — the daily recipe refresh.
#
# One execution: scan CKAN → re-render every recipe'd page whose data moved
# (no LLM; recipes are read from git main at run time, so merging a recipe PR
# needs no redeploy) → open a needs-authoring GitHub issue for each new or
# changed dataset with no recipe → dispatch the GitHub Actions publisher
# (PUBLISH_VIA=github) if anything re-rendered.
#
# A job, not a service: a job execution has no request timeout, only
# --task-timeout. (The batch once outgrew Cloud Run's 3600s request cap and
# the publish dispatch lost the race for 5 days.)
#
# --set-env-vars REPLACES the whole set: a var missing here is silently
# dropped on deploy (that is how RECONCILE_ENABLED once reverted to off).
# Diff against the live job before redeploying.

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
JOB=${CLOUD_RUN_JOB:-govdata-builder-job}
STAGING_BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
# Wall-clock ceiling for one run. A full re-render of every recipe is
# CKAN-export-bound; 6h is generous headroom. --max-retries=0: a failed run
# is retried by the next day's tick, not re-run back to back.
TASK_TIMEOUT=${TASK_TIMEOUT:-21600s}
MAX_RETRIES=${MAX_RETRIES:-0}

PUBLISH_VIA=${PUBLISH_VIA:-github}
TRIGGER_ID=${PUBLISH_TRIGGER_ID:-govdata-publish}
PUBLISH_BRANCH=${PUBLISH_BRANCH:-main}
PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO:-darkdiamond/govil.ai}
SCAN_LIMIT=${SCAN_LIMIT:-800}
MIN_MODIFIED_FLOOR=${MIN_MODIFIED_FLOOR:-2025-01-01}
MAX_AGE_DAYS=${MAX_AGE_DAYS:-100000}
RECONCILE_ENABLED=${RECONCILE_ENABLED:-true}
# Orphaned `pending` markers (left by the retired agent builder) older than
# this are recycled as `failed`, which the authoring queue treats as new.
PENDING_REAP_MINUTES=${PENDING_REAP_MINUTES:-120}
# Fuse on NEW needs-authoring issues per run (already-notified sources
# don't count).
AUTHORING_NOTIFY_CAP=${AUTHORING_NOTIFY_CAP:-100}
# No-op precheck for recipe refresh — skips CKAN version bumps that changed
# nothing (services/page_builder/refresh.py). off | observe | inputs | full;
# `observe` only logs would-skip agreement, never skips. `inputs` skips on the
# exact CSV hash (0 false skips over the 10-26/27 observe nights). `full` also
# skips the CSV export when the preview AND CKAN's file md5 both match (the
# preview alone false-skipped 5/night). Page older than
# REFRESH_PRECHECK_MAX_AGE_DAYS always re-renders.
REFRESH_PRECHECK=${REFRESH_PRECHECK:-full}
REFRESH_PRECHECK_MAX_AGE_DAYS=${REFRESH_PRECHECK_MAX_AGE_DAYS:-14}
# Per-resource export cap for recipe refresh (code default 300MB). Raised for
# the trademarks registry (656f6e4c), whose main file exports at ~368MB;
# REFRESH_TOTAL_BYTES (600MB) still bounds a whole dataset.
REFRESH_MAX_BYTES=${REFRESH_MAX_BYTES:-450000000}
# Non-CKAN providers (services/providers): each is off unless enabled. A
# recipe dir with a source.json for a disabled provider just stays last-good.
PROVIDER_BOI_SDMX_ENABLED=${PROVIDER_BOI_SDMX_ENABLED:-true}

cd "$(dirname "$0")/.."

BUILDER_SA="govdata-builder@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

ENV_VARS="FIRESTORE_PROJECT_ID=${PROJECT},GOOGLE_CLOUD_PROJECT=${PROJECT},FIREBASE_PROJECT=${PROJECT},GCS_STAGING_BUCKET=${STAGING_BUCKET},PUBLISH_VIA=${PUBLISH_VIA},PUBLISH_TRIGGER_ID=${TRIGGER_ID},PUBLISH_BRANCH=${PUBLISH_BRANCH},PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO},SCAN_LIMIT=${SCAN_LIMIT},MIN_MODIFIED_FLOOR=${MIN_MODIFIED_FLOOR},MAX_AGE_DAYS=${MAX_AGE_DAYS},RECONCILE_ENABLED=${RECONCILE_ENABLED},PENDING_REAP_MINUTES=${PENDING_REAP_MINUTES},AUTHORING_NOTIFY_CAP=${AUTHORING_NOTIFY_CAP},REFRESH_PRECHECK=${REFRESH_PRECHECK},REFRESH_PRECHECK_MAX_AGE_DAYS=${REFRESH_PRECHECK_MAX_AGE_DAYS},REFRESH_MAX_BYTES=${REFRESH_MAX_BYTES},PROVIDER_BOI_SDMX_ENABLED=${PROVIDER_BOI_SDMX_ENABLED}"
SECRETS="GITHUB_DISPATCH_TOKEN=github-dispatch-token:latest,VOYAGE_API_KEY=voyage-api-key:latest"
# Same as the image CMD; explicit so a manual `--args` override (dry run)
# composes predictably.
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
echo "Manual test (dry run — scan + list the authoring queue; nothing refreshed, opened or published):"
echo "  gcloud run jobs execute $JOB --region=$REGION --project=$PROJECT \\"
echo "    --args=-m,services.page_builder.pipeline,--dry-run --wait"
echo
echo "Point the daily scheduler at it:"
echo "  ./infra/scheduler.setup.sh"
