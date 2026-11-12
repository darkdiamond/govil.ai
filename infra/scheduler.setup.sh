#!/usr/bin/env bash
# Create or update the Cloud Scheduler ticks that start the Cloud Run jobs.
# This script owns both schedules (Asia/Jerusalem; Cloud Scheduler applies DST,
# so the times stay local year-round):
#
#   govdata-pipeline-daily  → govdata-builder-job  0 6-21 * * *   (hourly, :00)
#   govdata-news-daily      → govdata-news-job     25 6-21 * * *  (hourly, :25)
#
# Hourly since 2026-11-12, so a data update is live within about an hour and
# an article can follow in the same hour. Both jobs skip Shabbat themselves
# (QUIET_WINDOW, in the deploy scripts, ends a run `skipped_quiet`), and each
# holds a Firestore lease (`job_state/run`, `news_state/lock`), so a slow run
# makes the next tick end `skipped_overlap` instead of overlapping it. The
# local Claude Code authoring routine runs at 07:00, 12:00 and 17:00 and works
# through the issues the runs opened. The scheduler job names keep their
# historical "-daily" suffix.
# (Until 2026-10 the builder ran at 23:00 UTC, for an LLM provider's off-peak
# discount; 06:00 + 14:00 from 2026-11-04; no model runs in the builder.)
#
# With no SCHEDULER_JOB set, the script sets up both ticks and deletes the
# retired CBS release-evening ticks (govdata-pipeline-cbs-release,
# govdata-news-cbs-release): the 19:00 and 19:25 hourly ticks see CBS's 18:30
# release. A new scheduler job is created PAUSED: resume it explicitly once a
# manual execution looks good:
#
#   gcloud scheduler jobs resume govdata-pipeline-daily --location=me-west1
#   gcloud scheduler jobs resume govdata-news-daily --location=me-west1
#
# An existing job is updated in place and keeps its state (never paused here).
#
# One ad-hoc tick instead: set SCHEDULER_JOB (plus CLOUD_RUN_JOB, SCHEDULE and
# SCHEDULER_MESSAGE_BODY as needed; defaults govdata-builder-job, the builder
# schedule, '{}'). Those three are refused without SCHEDULER_JOB, so a stray
# override can't land on both default ticks.
#
# Ticks start a job execution via the Admin API's :run method.
#
# SCHEDULER_MESSAGE_BODY is the :run request body. Pass it inline
# (VAR=… ./infra/scheduler.setup.sh), never `export` it: a leftover value would
# be stored on whatever tick the script retargets next. A body with
# `overrides` changes the execution's args; the scheduler SA then needs
# roles/run.jobsExecutorWithOverrides on that job (run.invoker is not enough).
# The default ticks need no args: each news run covers the renders since the
# last one's cursor, whenever it runs. Re-running this on a tick created with
# an old body (e.g. `--since-hours 3`) resets its body to '{}'.
#
# Requires: infra/bootstrap.sh, infra/builder-job.deploy.sh and (for the news
# tick) infra/news-job.deploy.sh already run.

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
TIMEZONE=${SCHEDULE_TZ:-"Asia/Jerusalem"}

BUILDER_SCHEDULE="0 6-21 * * *"
NEWS_SCHEDULE="25 6-21 * * *"
RETIRED_JOBS=(govdata-pipeline-cbs-release govdata-news-cbs-release)

SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

# Executions start via the Admin API's :run method, so the tick carries an
# OAuth token for googleapis.com (not an OIDC token for a Run URL). The
# call returns as soon as the execution is created — the scheduler is not
# holding the run open, so its 180s attemptDeadline is irrelevant.
AUTH_ARGS=(
  --oauth-service-account-email="$SCHEDULER_SA"
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform"
)

# setup_tick <scheduler job> <cloud run job> <schedule> <message body>
setup_tick() {
  local job_name=$1 run_job=$2 schedule=$3 message_body=$4

  if ! gcloud run jobs describe "$run_job" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    echo "Cloud Run job $run_job not found in $REGION. Run its infra/*-job.deploy.sh first." >&2
    exit 2
  fi
  local url="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/${run_job}:run"

  echo "==> $job_name: target $url, schedule '$schedule' ($TIMEZONE)"

  local existed=false
  if gcloud scheduler jobs describe "$job_name" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    existed=true
    echo "==> updating existing scheduler job $job_name"
    gcloud scheduler jobs update http "$job_name" \
      --location="$REGION" \
      --project="$PROJECT" \
      --schedule="$schedule" \
      --time-zone="$TIMEZONE" \
      --uri="$url" \
      --http-method=POST \
      --update-headers="Content-Type=application/json" \
      --message-body="$message_body" \
      "${AUTH_ARGS[@]}"
  else
    # NOTE: `create http` takes --headers, `update http` takes --update-headers.
    # Same flag, different name per subcommand — keep both spellings in sync.
    echo "==> creating scheduler job $job_name"
    gcloud scheduler jobs create http "$job_name" \
      --location="$REGION" \
      --project="$PROJECT" \
      --schedule="$schedule" \
      --time-zone="$TIMEZONE" \
      --uri="$url" \
      --http-method=POST \
      --headers="Content-Type=application/json" \
      --message-body="$message_body" \
      "${AUTH_ARGS[@]}"
  fi

  # Only a FRESH job gets paused (first-time setup: verify by manual invoke
  # before letting it fire on its own). Re-running this on a live tick to
  # retarget it must not silently stop the builds.
  if [[ "$existed" == "false" ]]; then
    echo "==> pausing $job_name (testing via manual invoke until we flip the switch)"
    gcloud scheduler jobs pause "$job_name" --location="$REGION" --project="$PROJECT"
    echo
    echo "Resume when ready with:"
    echo "  gcloud scheduler jobs resume $job_name --location=$REGION --project=$PROJECT"
  else
    echo "==> left $job_name in its existing state (not pausing an already-live tick)"
  fi

  echo
  echo "==> scheduler job:"
  gcloud scheduler jobs describe "$job_name" --location="$REGION" --project="$PROJECT" \
    --format="value(name,state,schedule,timeZone,httpTarget.uri)"
  echo
}

if [[ -n "${SCHEDULER_JOB:-}" ]]; then
  # One ad-hoc tick, as before the script owned both schedules.
  MESSAGE_BODY=${SCHEDULER_MESSAGE_BODY:-'{}'}
  setup_tick "$SCHEDULER_JOB" "${CLOUD_RUN_JOB:-govdata-builder-job}" \
    "${SCHEDULE:-$BUILDER_SCHEDULE}" "$MESSAGE_BODY"
  exit 0
fi

for var in CLOUD_RUN_JOB SCHEDULE SCHEDULER_MESSAGE_BODY; do
  if [[ -n "${!var:-}" ]]; then
    echo "$var is set but SCHEDULER_JOB is not: it would apply to both default ticks." >&2
    echo "Unset it, or name the one tick it is for with SCHEDULER_JOB=…" >&2
    exit 2
  fi
done

setup_tick govdata-pipeline-daily govdata-builder-job "$BUILDER_SCHEDULE" '{}'
setup_tick govdata-news-daily govdata-news-job "$NEWS_SCHEDULE" '{}'

# The hourly ticks cover CBS release evenings (19:00 builder, 19:25 news).
for job_name in "${RETIRED_JOBS[@]}"; do
  if gcloud scheduler jobs describe "$job_name" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    echo "==> deleting retired scheduler job $job_name"
    gcloud scheduler jobs delete "$job_name" --location="$REGION" --project="$PROJECT" --quiet
  else
    echo "==> retired scheduler job $job_name already gone"
  fi
done
