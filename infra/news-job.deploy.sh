#!/usr/bin/env bash
# Deploy govdata-news-job — the hourly News run (services/news/run.py):
# signals from the page-model history → editor → writer agent → gates +
# critic → image → Firestore articles/ + gs://<staging>/news/ → publish
# dispatch when ≥1 article was accepted. The ONLY job that calls a model
# (OpenRouter: GPT-6.1 Terra at high effort for text, Nano Banana for the illustration).
#
# Same image as the builder (Dockerfile), different command and its own,
# minimal service account (infra/news-iam.setup.sh — run that first).
# Scheduled hourly at :25 (06:25-21:25 Asia/Jerusalem), 25 minutes after each
# builder tick; infra/scheduler.setup.sh owns the schedule. A run with nothing
# rendered since its cursor and no daily duty due ends `idle` after one
# Firestore query, with no GCS or model call.
#
# Spending is capped outside the code: the openrouter-news-key's own limit
# in the OpenRouter dashboard, plus a GCP budget alert. A refused key ends
# the run `llm_unavailable` (non-zero exit), pages untouched.
#
# Kill switch without a redeploy:
#   gcloud run jobs update govdata-news-job --region=me-west1 --update-env-vars NEWS_PUBLISH=off
#
# --set-env-vars REPLACES the whole set: diff against the live job first.
set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
JOB=${NEWS_JOB:-govdata-news-job}
STAGING_BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
# A run longer than an hour makes the next tick end `skipped_overlap` (the
# news_state/lock lease; a heartbeat renews it, so NEWS_LEASE_TTL_S, code
# default 900 s, only bounds how long a dead run keeps later ticks out).
TASK_TIMEOUT=${TASK_TIMEOUT:-3600s}
# Scheduled runs inside this weekly window (Israel time) end `skipped_quiet`:
# Friday 15:00 to Saturday 21:00. Empty = never quiet.
QUIET_WINDOW=${QUIET_WINDOW-fri15-sat21}

NEWS_PUBLISH=${NEWS_PUBLISH:-live}
NEWS_MODEL=${NEWS_MODEL:-openai/gpt-6.1-terra}
NEWS_REASONING_EFFORT=${NEWS_REASONING_EFFORT:-high}
NEWS_IMAGE_MODEL=${NEWS_IMAGE_MODEL:-google/gemini-3.1-flash-image}
NEWS_SEARCH_ENGINE=${NEWS_SEARCH_ENGINE:-exa}
# Event stories per run, and (NEWS_DAY_BUDGET) a ceiling on news articles per
# Israel date across all runs. Explainers and the digest don't count.
NEWS_MAX_PER_RUN=${NEWS_MAX_PER_RUN:-3}
NEWS_DAY_BUDGET=${NEWS_DAY_BUDGET:-true}
NEWS_MAX_PER_DAY=${NEWS_MAX_PER_DAY:-10}
NEWS_DATASET_COOLDOWN_DAYS=${NEWS_DATASET_COOLDOWN_DAYS:-21}
NEWS_MAX_TOOL_CALLS=${NEWS_MAX_TOOL_CALLS:-100}
# The daily floor: when event news leaves an Israel day with fewer articles,
# explainers on high-demand datasets fill it (services/news/features.py).
NEWS_MIN_PER_DAY=${NEWS_MIN_PER_DAY:-1}
NEWS_FEATURE_COOLDOWN_DAYS=${NEWS_FEATURE_COOLDOWN_DAYS:-60}
NEWS_FILL_ATTEMPTS=${NEWS_FILL_ATTEMPTS:-3}
NEWS_FEATURE_MAX_TOOL_CALLS=${NEWS_FEATURE_MAX_TOOL_CALLS:-35}
# The floor is checked once a day, by the first run at/after this Israel hour
# (13 on Friday, before the quiet window); news_state/daily records the attempt.
NEWS_FLOOR_HOUR=${NEWS_FLOOR_HOUR-20}
NEWS_FLOOR_HOUR_FRIDAY=${NEWS_FLOOR_HOUR_FRIDAY-13}
# A new period of a CBS or BoI release signals even when nothing is unusual.
NEWS_RELEASE_SIGNALS=${NEWS_RELEASE_SIGNALS:-true}
# The weekly digest of pooled small moves: Python weekday, 4 = Friday; empty = off.
NEWS_DIGEST_WEEKDAY=${NEWS_DIGEST_WEEKDAY-4}
# …written once that day, by the first run at/after this Israel hour.
NEWS_DIGEST_HOUR=${NEWS_DIGEST_HOUR-7}
# A dataset's first render, created at its source in the last
# NEWS_NEW_DATASET_DAYS (code default 30), signals `new_dataset` (an explainer).
NEWS_NEW_DATASET_SIGNALS=${NEWS_NEW_DATASET_SIGNALS:-true}
PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO:-darkdiamond/govil.ai}
PUBLISH_BRANCH=${PUBLISH_BRANCH:-main}

cd "$(dirname "$0")/.."

NEWS_SA="govdata-news@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

# The provider flags and RECIPES_FETCH let the SQL tool load a dataset's
# full tables the way the refresh does (services/news/data.py).
ENV_PAIRS=(
  "FIRESTORE_PROJECT_ID=${PROJECT}"
  "GOOGLE_CLOUD_PROJECT=${PROJECT}"
  "NEWS_FIRESTORE_DATABASE=news"
  "GCS_STAGING_BUCKET=${STAGING_BUCKET}"
  "NEWS_PUBLISH=${NEWS_PUBLISH}"
  "NEWS_MODEL=${NEWS_MODEL}"
  "NEWS_REASONING_EFFORT=${NEWS_REASONING_EFFORT}"
  "NEWS_IMAGE_MODEL=${NEWS_IMAGE_MODEL}"
  "NEWS_SEARCH_ENGINE=${NEWS_SEARCH_ENGINE}"
  "NEWS_MAX_PER_RUN=${NEWS_MAX_PER_RUN}"
  "NEWS_DAY_BUDGET=${NEWS_DAY_BUDGET}"
  "NEWS_MAX_PER_DAY=${NEWS_MAX_PER_DAY}"
  "NEWS_DATASET_COOLDOWN_DAYS=${NEWS_DATASET_COOLDOWN_DAYS}"
  "NEWS_MAX_TOOL_CALLS=${NEWS_MAX_TOOL_CALLS}"
  "NEWS_MIN_PER_DAY=${NEWS_MIN_PER_DAY}"
  "NEWS_FEATURE_COOLDOWN_DAYS=${NEWS_FEATURE_COOLDOWN_DAYS}"
  "NEWS_FILL_ATTEMPTS=${NEWS_FILL_ATTEMPTS}"
  "NEWS_FEATURE_MAX_TOOL_CALLS=${NEWS_FEATURE_MAX_TOOL_CALLS}"
  "NEWS_FLOOR_HOUR=${NEWS_FLOOR_HOUR}"
  "NEWS_FLOOR_HOUR_FRIDAY=${NEWS_FLOOR_HOUR_FRIDAY}"
  "NEWS_RELEASE_SIGNALS=${NEWS_RELEASE_SIGNALS}"
  "NEWS_DIGEST_WEEKDAY=${NEWS_DIGEST_WEEKDAY}"
  "NEWS_DIGEST_HOUR=${NEWS_DIGEST_HOUR}"
  "NEWS_NEW_DATASET_SIGNALS=${NEWS_NEW_DATASET_SIGNALS}"
  "PUBLISH_GITHUB_REPO=${PUBLISH_GITHUB_REPO}"
  "PUBLISH_BRANCH=${PUBLISH_BRANCH}"
  "PROVIDER_BOI_SDMX_ENABLED=true"
  "PROVIDER_CBS_RELEASES_ENABLED=true"
  "PROVIDER_CBS_INDEX_ENABLED=true"
  "RECIPES_FETCH=tarball"
  "QUIET_WINDOW=${QUIET_WINDOW}"
)
# Joined with ';' (gcloud's `^;^` alternate delimiter) so a value may hold a comma.
ENV_VARS="^;^$(IFS=';'; echo "${ENV_PAIRS[*]}")"
# Its own dispatch PAT (Actions: write only), not the builder's token.
SECRETS="OPENROUTER_API_KEY=openrouter-news-key:latest,GITHUB_DISPATCH_TOKEN=github-news-dispatch-token:latest"

echo "==> deploying job $JOB ($REGION, project $PROJECT) as $NEWS_SA"
gcloud run jobs deploy "$JOB" \
  --source=. \
  --region="$REGION" \
  --service-account="$NEWS_SA" \
  --cpu=2 \
  --memory=4Gi \
  --task-timeout="$TASK_TIMEOUT" \
  --max-retries=0 \
  --parallelism=1 \
  --tasks=1 \
  --command=python \
  --args="-m,services.news.run" \
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
echo "Manual test, writes nothing (rank today's signals):"
echo "  gcloud run jobs execute $JOB --region=$REGION --project=$PROJECT --args=-m,services.news.run,--signals-only --wait"
echo "Schedule it (with the builder's tick; a new tick is paused until resumed after a good manual run):"
echo "  ./infra/scheduler.setup.sh"
