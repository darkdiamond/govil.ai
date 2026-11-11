#!/usr/bin/env bash
# Publish govil.ai from your local machine — the same steps as
# .github/workflows/publish.yml (the primary path) and cloudbuild-publish.yaml,
# just running here. services/page_builder/tests/test_publish_paths.py checks
# all three for each step.
#
#   1. rsync  gs://${GCS_STAGING_BUCKET}/datasets/  ->  frontend/public/datasets/
#      (only content.html survives — data.json + agent_data.json are
#      regenerated from Firestore in step 2 to keep the two paths in sync)
#      and gs://${GCS_STAGING_BUCKET}/news/ -> frontend/public/news/ (images)
#   2. publish from Firestore: write
#        frontend/public/data/manifest.json
#        frontend/public/datasets/<id>/data.json
#        frontend/public/datasets/<id>/agent_data.json
#        frontend/public/news/ (article JSON)
#   3. nuxt generate (+ sitemap), with NUXT_PUBLIC_GTAG_ID /
#      NUXT_PUBLIC_ADSENSE_ID / NUXT_PUBLIC_CLARITY_ID from your environment
#      or frontend/.env (unset → the site ships without GA/AdSense/Clarity)
#   4. regenerate firebase.json redirects, firebase deploy --only hosting
#   5. IndexNow ping (never fails the run)
#
# Or pass --serve to skip steps 4-5 and serve the byte-identical static
# output at http://localhost:${PORT:-3000} for review.
#
# Usage:
#   ./infra/publish-local.sh                     # full publish to Firebase
#   ./infra/publish-local.sh --serve             # local preview, no deploy
#   ./infra/publish-local.sh --dry-run           # build but don't deploy
#   ./infra/publish-local.sh --skip-sync         # reuse on-disk datasets
#   ./infra/publish-local.sh --skip-manifest     # reuse on-disk manifest
#   ./infra/publish-local.sh --skip-generate     # reuse on-disk .output
#
# Env overrides:
#   FIREBASE_PROJECT      (default: govdata-il)
#   GCS_STAGING_BUCKET    (default: govdata-il-staging)
#   PORT                  (default: 3000, --serve only)
#   NUXT_PUBLIC_GTAG_ID, NUXT_PUBLIC_ADSENSE_ID, NUXT_PUBLIC_CLARITY_ID
#                         analytics/ads IDs (the GitHub repo variables)
#
# Requires: gcloud (with ADC), gsutil, node, npm, python3, firebase
# CLI on PATH; venv activated for the manifest builder.

set -euo pipefail

PROJECT="${FIREBASE_PROJECT:-govdata-il}"
BUCKET="${GCS_STAGING_BUCKET:-govdata-il-staging}"
PORT="${PORT:-3000}"

SERVE=0
DRY_RUN=0
SKIP_SYNC=0
SKIP_MANIFEST=0
SKIP_GENERATE=0

for arg in "$@"; do
  case "$arg" in
    --serve)         SERVE=1 ;;
    --dry-run)       DRY_RUN=1 ;;
    --skip-sync)     SKIP_SYNC=1 ;;
    --skip-manifest) SKIP_MANIFEST=1 ;;
    --skip-generate) SKIP_GENERATE=1 ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown flag: $arg" >&2
      exit 2
      ;;
  esac
done

if (( SERVE && DRY_RUN )); then
  echo "--serve and --dry-run are mutually exclusive" >&2
  exit 2
fi

cd "$(dirname "$0")/.."

step_started=0
step_started_at=0
step_name=""

step_begin() {
  step_name="$1"
  step_started_at=$(date +%s)
  step_started=1
  echo
  echo "==> [$(date +%H:%M:%S)] $step_name"
}

step_end() {
  if (( step_started )); then
    local now elapsed
    now=$(date +%s)
    elapsed=$(( now - step_started_at ))
    echo "==> [$(date +%H:%M:%S)] done ($step_name, ${elapsed}s)"
    step_started=0
  fi
}

run_started_at=$(date +%s)

# ---------------------------------------------------------------- preflight
step_begin "preflight"

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing on PATH: $1" >&2; exit 1; }
}
need gcloud
need gsutil
need node
need npm
need python3
need firebase

if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  echo "no application-default credentials; run:" >&2
  echo "  gcloud auth application-default login" >&2
  exit 1
fi

if ! firebase projects:list 2>/dev/null | grep -qw "$PROJECT"; then
  echo "firebase CLI cannot see project '$PROJECT'; run:" >&2
  echo "  firebase login" >&2
  exit 1
fi

if ! python3 -c 'import services.page_builder.publish' >/dev/null 2>&1; then
  echo "python can't import services.page_builder.publish;" >&2
  echo "activate the project venv first:" >&2
  echo "  source .venv/bin/activate" >&2
  exit 1
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "frontend/node_modules missing — running npm ci"
  ( cd frontend && npm ci --prefer-offline --no-audit )
fi

step_end

# ---------------------------------------------------- step 1: sync datasets
if (( SKIP_SYNC )); then
  echo
  echo "==> [$(date +%H:%M:%S)] skipping sync (--skip-sync)"
else
  step_begin "syncing gs://$BUCKET/datasets/ -> frontend/public/datasets/"
  GCS_STAGING_BUCKET="$BUCKET" bash infra/sync-datasets.sh --apply
  step_end

  # News images (services/news); the publisher then writes the article JSON
  # next to them and removes directories of articles not live. A failed rsync
  # stops the publish (no images → broken articles). rsync errors on a source
  # prefix with no objects, so a bucket with no news/ yet (a fork, a fresh
  # project) is skipped by listing the bucket root; a failed listing stops it
  # too (set -e on the assignment).
  step_begin "syncing gs://$BUCKET/news/ -> frontend/public/news/"
  mkdir -p frontend/public/news
  top="$(gsutil ls "gs://$BUCKET/")"
  if grep -qxF "gs://$BUCKET/news/" <<<"$top"; then
    gsutil -m rsync -r -d \
      -x '.*\.json$|.*/index\.html$' \
      "gs://$BUCKET/news/" frontend/public/news/
  else
    echo "no gs://$BUCKET/news/ yet; no news images to fetch"
  fi
  step_end
fi

# ---------------------------------------------- step 2: publish from Firestore
if (( SKIP_MANIFEST )); then
  echo
  echo "==> [$(date +%H:%M:%S)] skipping publish step (--skip-manifest)"
else
  step_begin "publishing per-dataset + manifest artifacts from Firestore (project=$PROJECT)"
  # publish writes:
  #   frontend/public/data/manifest.json
  #   frontend/public/datasets/<id>/data.json
  #   frontend/public/datasets/<id>/agent_data.json
  FIRESTORE_PROJECT_ID="$PROJECT" \
  GOOGLE_CLOUD_PROJECT="$PROJECT" \
    python3 -m services.page_builder.publish \
      --from-firestore \
      --out frontend/public/
  echo "wrote $(wc -c < frontend/public/data/manifest.json) bytes to frontend/public/data/manifest.json"
  step_end
fi

# ----------------------------------------------------- step 3: nuxt generate
if (( SKIP_GENERATE )); then
  echo
  echo "==> [$(date +%H:%M:%S)] skipping nuxt generate (--skip-generate)"
else
  step_begin "nuxt generate (frontend/)"
  # nuxt.config.ts reads the analytics IDs from the environment this script
  # inherited, or from frontend/.env (nuxi loads it). Warn when neither has one.
  for var in NUXT_PUBLIC_GTAG_ID NUXT_PUBLIC_ADSENSE_ID NUXT_PUBLIC_CLARITY_ID; do
    if [[ -z "${!var:-}" ]] && ! grep -qs "^${var}=." frontend/.env; then
      echo "WARNING: $var is unset (env and frontend/.env); the site ships without it" >&2
    fi
  done
  ( cd frontend && npm run generate )
  step_end
fi

if [[ ! -d frontend/.output/public ]]; then
  echo "frontend/.output/public is missing — refusing to deploy/serve nothing" >&2
  exit 1
fi

du_size=$(du -sh frontend/.output/public | awk '{print $1}')
echo "==> static output: $du_size in frontend/.output/public"

# ------------------------------------------------- step 4 / 5: deploy or serve
if (( SERVE )); then
  if (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | awk '{print $4}' | grep -Eq "[:.]${PORT}$"; then
    echo "port $PORT is already in use; either stop the listener or rerun with PORT=<other> $0 --serve" >&2
    holder=$(ss -ltnp 2>/dev/null | awk -v p=":$PORT$" '$4 ~ p {print $0; exit}')
    [[ -n "$holder" ]] && echo "  current listener: $holder" >&2
    exit 1
  fi
  step_begin "serving frontend/.output/public on http://localhost:$PORT"
  echo "Ctrl+C to stop."
  exec npx --yes serve frontend/.output/public -l "$PORT"
fi

if (( DRY_RUN )); then
  echo
  echo "==> [$(date +%H:%M:%S)] dry-run: skipping firebase deploy"
else
  step_begin "regenerate firebase.json redirects from manifest"
  node frontend/scripts/gen-redirects.mjs
  step_end

  step_begin "firebase deploy --only hosting (project=$PROJECT)"
  firebase deploy \
    --only hosting \
    --project "$PROJECT" \
    --non-interactive
  step_end

  # Tell Bing/Yandex/etc. about every URL right after deploy (IndexNow).
  step_begin "IndexNow ping"
  node frontend/scripts/indexnow-ping.mjs || echo "IndexNow ping failed (non-fatal)"
  step_end
fi

run_total=$(( $(date +%s) - run_started_at ))
echo
echo "==> finished in ${run_total}s"
