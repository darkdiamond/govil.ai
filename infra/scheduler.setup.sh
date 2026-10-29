#!/usr/bin/env bash
# Create the Cloud Scheduler job that runs govdata-builder-job daily. A new
# scheduler job is created PAUSED — resume it explicitly once a manual
# execution looks good:
#
#   gcloud scheduler jobs resume govdata-pipeline-daily --location=me-west1
#
# SCHEDULE defaults to 06:00 Asia/Jerusalem (Cloud Scheduler applies DST, so
# it stays 06:00 local year-round). The local Claude Code authoring routine
# runs an hour later and works through the issues this run opened.
# (Until 2026-10 it was 23:00 UTC, for an LLM provider's off-peak discount;
# no model runs in the job any more.)
#
# Ticks start a job execution via the Admin API's :run method.
#
# Requires: infra/bootstrap.sh and infra/builder-job.deploy.sh already run.

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
RUN_JOB=${CLOUD_RUN_JOB:-govdata-builder-job}
JOB_NAME=${SCHEDULER_JOB:-govdata-pipeline-daily}
SCHEDULE=${SCHEDULE:-"0 6 * * *"}
TIMEZONE=${SCHEDULE_TZ:-"Asia/Jerusalem"}

SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

if ! gcloud run jobs describe "$RUN_JOB" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  echo "Cloud Run job $RUN_JOB not found in $REGION. Run infra/builder-job.deploy.sh first." >&2
  exit 2
fi
# Executions start via the Admin API's :run method, so the tick carries an
# OAuth token for googleapis.com (not an OIDC token for a Run URL). The
# call returns as soon as the execution is created — the scheduler is not
# holding the run open, so its 180s attemptDeadline is irrelevant.
URL="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${RUN_JOB}:run"
AUTH_ARGS=(
  --oauth-service-account-email="$SCHEDULER_SA"
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
)

echo "==> target: $URL"

EXISTED=false
if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  EXISTED=true
  echo "==> updating existing scheduler job $JOB_NAME"
  gcloud scheduler jobs update http "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="$URL" \
    --http-method=POST \
    --update-headers="Content-Type=application/json" \
    --message-body='{}' \
    "${AUTH_ARGS[@]}"
else
  # NOTE: `create http` takes --headers, `update http` takes --update-headers.
  # Same flag, different name per subcommand — keep both spellings in sync.
  echo "==> creating scheduler job $JOB_NAME"
  gcloud scheduler jobs create http "$JOB_NAME" \
    --location="$REGION" \
    --project="$PROJECT" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="$URL" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body='{}' \
    "${AUTH_ARGS[@]}"
fi

# Only a FRESH job gets paused (first-time setup: verify by manual invoke
# before letting it fire on its own). Re-running this on the live daily tick
# to retarget it must not silently stop the daily build.
if [[ "$EXISTED" == "false" ]]; then
  echo "==> pausing $JOB_NAME (testing via manual invoke until we flip the switch)"
  gcloud scheduler jobs pause "$JOB_NAME" --location="$REGION" --project="$PROJECT"
  echo
  echo "Resume when ready with:"
  echo "  gcloud scheduler jobs resume $JOB_NAME --location=$REGION --project=$PROJECT"
else
  echo "==> left $JOB_NAME in its existing state (not pausing an already-live tick)"
fi

echo
echo "==> scheduler job:"
gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" --project="$PROJECT" \
  --format="value(name,state,schedule,timeZone,httpTarget.uri)"
