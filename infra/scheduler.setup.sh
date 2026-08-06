#!/usr/bin/env bash
# Create the Cloud Scheduler job for govdata-builder. The job is created
# PAUSED — resume it explicitly once the manual invokes look good:
#
#   gcloud scheduler jobs resume govdata-pipeline-daily --location=me-west1
#
# TARGET picks what the daily tick invokes:
#   job     (default) — the govdata-builder-job Cloud Run JOB. Use this. A
#                       job execution has no request timeout, so the batch
#                       runs to its own end and fires the publish dispatch.
#   service           — the govdata-builder HTTP service. Rollback only: a
#                       service request is capped at 3600s, which the batch
#                       outgrew on 2026-08-01 (504 daily, publish never fired).
#
#   TARGET=service ./infra/scheduler.setup.sh   # revert
#
# Requires:
#   - infra/bootstrap.sh already run
#   - TARGET=job     → infra/builder-job.deploy.sh already run
#     TARGET=service → infra/builder.deploy.sh already run (URL must exist)

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
SERVICE=${CLOUD_RUN_SERVICE:-govdata-builder}
RUN_JOB=${CLOUD_RUN_JOB:-govdata-builder-job}
JOB_NAME=${SCHEDULER_JOB:-govdata-pipeline-daily}
SCHEDULE=${SCHEDULE:-"0 7 * * *"}
TIMEZONE=${SCHEDULE_TZ:-"Asia/Jerusalem"}
TARGET=${TARGET:-job}

SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

case "$TARGET" in
  job)
    if ! gcloud run jobs describe "$RUN_JOB" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
      echo "Cloud Run job $RUN_JOB not found in $REGION. Run infra/builder-job.deploy.sh first." >&2
      exit 2
    fi
    # Executions start via the Admin API's :run method, so the tick carries an
    # OAuth token for googleapis.com (not an OIDC token for a Run URL). The
    # call returns as soon as the execution is created — the scheduler is not
    # holding the batch open, so its 180s attemptDeadline is irrelevant.
    URL="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${RUN_JOB}:run"
    AUTH_ARGS=(
      --oauth-service-account-email="$SCHEDULER_SA"
      --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
    )
    ;;
  service)
    URL=$(gcloud run services describe "$SERVICE" \
      --region="$REGION" --project="$PROJECT" --format='value(status.url)')
    if [[ -z "$URL" ]]; then
      echo "Cloud Run service $SERVICE not found in $REGION. Deploy it first." >&2
      exit 2
    fi
    AUTH_ARGS=(
      --oidc-service-account-email="$SCHEDULER_SA"
      --oidc-token-audience="$URL"
    )
    ;;
  *)
    echo "TARGET must be 'job' or 'service' (got: $TARGET)" >&2
    exit 2
    ;;
esac

echo "==> target: $TARGET → $URL"

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
