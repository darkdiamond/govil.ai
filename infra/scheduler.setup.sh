#!/usr/bin/env bash
# Create or update a Cloud Scheduler job that starts a Cloud Run job. Defaults:
# govdata-pipeline-daily running govdata-builder-job twice a day; SCHEDULER_JOB,
# CLOUD_RUN_JOB, SCHEDULE and SCHEDULER_MESSAGE_BODY pick another tick (news,
# CBS release evenings: see below). A new scheduler job is created PAUSED — resume it explicitly once a manual
# execution looks good:
#
#   gcloud scheduler jobs resume govdata-pipeline-daily --location=me-west1
#
# SCHEDULE defaults to 06:00 and 14:00 Asia/Jerusalem (Cloud Scheduler applies
# DST, so the times stay local year-round). Twice a day since 2026-11-04, once
# a run took minutes, not an hour. The local Claude Code authoring routine runs
# at 07:00 and works through the issues the runs opened. The job name keeps its
# historical "-daily" suffix.
# (Until 2026-10 it was 23:00 UTC, for an LLM provider's off-peak discount;
# no model runs in the job any more.)
#
# Ticks start a job execution via the Admin API's :run method.
#
# SCHEDULER_MESSAGE_BODY (default '{}') is the :run request body. Pass it inline
# (VAR=… ./infra/scheduler.setup.sh), never `export` it: a leftover value would
# be stored on whatever tick the script retargets next. A body with
# `overrides` changes the execution's args; the scheduler SA then needs
# roles/run.jobsExecutorWithOverrides on that job (run.invoker is not enough).
#
# CBS release-evening ticks (CBS publishes its price indices on the 15th at
# 18:30; when the 15th is a Friday, Saturday or holiday, at 14:00 on that Friday
# or the holiday eve. The twice-daily ticks only see them the next morning):
#
#   SCHEDULER_JOB=govdata-pipeline-cbs-release SCHEDULE="0 19 13-15 * *" \
#     ./infra/scheduler.setup.sh
#   CLOUD_RUN_JOB=govdata-news-job SCHEDULER_JOB=govdata-news-cbs-release \
#     SCHEDULE="30 19 13-15 * *" SCHEDULER_MESSAGE_BODY="$(cat infra/news-cbs-release.body.json)" \
#     ./infra/scheduler.setup.sh
#
# Requires: infra/bootstrap.sh and infra/builder-job.deploy.sh already run.

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
RUN_JOB=${CLOUD_RUN_JOB:-govdata-builder-job}
JOB_NAME=${SCHEDULER_JOB:-govdata-pipeline-daily}
SCHEDULE=${SCHEDULE:-"0 6,14 * * *"}
TIMEZONE=${SCHEDULE_TZ:-"Asia/Jerusalem"}
MESSAGE_BODY=${SCHEDULER_MESSAGE_BODY:-'{}'}

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
    --message-body="$MESSAGE_BODY" \
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
    --message-body="$MESSAGE_BODY" \
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
