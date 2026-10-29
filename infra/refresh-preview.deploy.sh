#!/usr/bin/env bash
# Recipe-refresh DEMO lane — prove deterministic refresh for a few days on
# up to ~10 datasets before any of it touches the live site.
#
# What it deploys:
#   - Cloud Run job govdata-refresh-preview: same image as the builder, runs
#     `python -m services.page_builder.refresh run --target preview`. No LLM.
#     Reads `sources/*` (the prod scanner keeps it fresh),
#     writes ONLY `preview_sources/*` + gs://<staging>/preview/datasets/.
#   - Cloud Scheduler job govdata-refresh-preview-daily: 00:00 UTC (it reads
#     whatever the prod job's last scan wrote; the prod job runs 06:00
#     Asia/Jerusalem).
#   - On ≥1 refresh it dispatches publish.yml with target=preview, which
#     deploys the `recipes-demo` Hosting preview channel (never live).
#
# Recipes for the demo are NOT read from git/main: upload them with
#   ./infra/refresh-preview.deploy.sh sync-recipes
# (gs://<staging>/preview/recipes/), so the demo can run before any recipe
# is merged. The prod job ignores that prefix (it reads recipes from git main).
#
# Usage:
#   ./infra/refresh-preview.deploy.sh              # deploy job + scheduler (paused)
#   ./infra/refresh-preview.deploy.sh sync-recipes # upload recipes/ → preview prefix
#   gcloud run jobs execute govdata-refresh-preview --region=me-west1 --wait
#   gcloud scheduler jobs resume govdata-refresh-preview-daily --location=me-west1
#
# Teardown after go-live: delete both jobs, the preview/ prefix, the
# preview_sources + preview_runs collections, and the recipes-demo channel.

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
JOB=${PREVIEW_JOB:-govdata-refresh-preview}
SCHED=${PREVIEW_SCHEDULER_JOB:-govdata-refresh-preview-daily}
SCHEDULE=${SCHEDULE:-"0 0 * * *"}
STAGING_BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO:-darkdiamond/govil.ai}

cd "$(dirname "$0")/.."

if [ "${1:-}" = "sync-recipes" ]; then
  echo "==> uploading recipes/ → gs://${STAGING_BUCKET}/preview/recipes/"
  gcloud storage rsync recipes/ "gs://${STAGING_BUCKET}/preview/recipes/" \
    --recursive --delete-unmatched-destination-objects --project="$PROJECT"
  exit 0
fi

BUILDER_SA="govdata-builder@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

# Per-resource refresh export cap, kept in lockstep with builder-job.deploy.sh
# (trademarks 656f6e4c exports at ~368MB, over the 300MB code default).
REFRESH_MAX_BYTES=${REFRESH_MAX_BYTES:-450000000}
ENV_VARS="FIRESTORE_PROJECT_ID=${PROJECT},GOOGLE_CLOUD_PROJECT=${PROJECT},GCS_STAGING_BUCKET=${STAGING_BUCKET},REFRESH_TARGET=preview,RECIPES_SOURCE=gs://${STAGING_BUCKET}/preview/recipes/,PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO},PUBLISH_GITHUB_WORKFLOW=publish.yml,PUBLISH_BRANCH=main,REFRESH_MAX_BYTES=${REFRESH_MAX_BYTES}"
# Only the GitHub token: publish dispatch + needs-authoring issues.
SECRETS="GITHUB_DISPATCH_TOKEN=github-dispatch-token:latest"

echo "==> deploying job $JOB ($REGION, project $PROJECT)"
gcloud run jobs deploy "$JOB" \
  --source=. \
  --region="$REGION" \
  --service-account="$BUILDER_SA" \
  --cpu=2 \
  --memory=4Gi \
  --task-timeout=3600s \
  --max-retries=0 \
  --parallelism=1 \
  --tasks=1 \
  --command=python \
  --args="-m,services.page_builder.refresh,run,--target,preview" \
  --set-env-vars="$ENV_VARS" \
  --set-secrets="$SECRETS" \
  --project="$PROJECT"

gcloud run jobs add-iam-policy-binding "$JOB" \
  --member="serviceAccount:$SCHEDULER_SA" \
  --role=roles/run.invoker \
  --region="$REGION" --project="$PROJECT" --quiet >/dev/null

URL="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${JOB}:run"
if gcloud scheduler jobs describe "$SCHED" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  echo "==> scheduler $SCHED exists — leaving it as is"
else
  echo "==> creating scheduler $SCHED (PAUSED) — $SCHEDULE UTC"
  gcloud scheduler jobs create http "$SCHED" \
    --location="$REGION" --project="$PROJECT" \
    --schedule="$SCHEDULE" --time-zone=UTC \
    --uri="$URL" --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA" \
    --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
  gcloud scheduler jobs pause "$SCHED" --location="$REGION" --project="$PROJECT"
fi

echo
echo "Next:"
echo "  ./infra/refresh-preview.deploy.sh sync-recipes"
echo "  gcloud run jobs execute $JOB --region=$REGION --project=$PROJECT --wait"
echo "  gcloud scheduler jobs resume $SCHED --location=$REGION --project=$PROJECT"
