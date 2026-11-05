#!/usr/bin/env bash
# Mirror agent-generated dataset pages from the GCS staging bucket
# into the working tree, so they can be reviewed and committed to git
# by hand. GCS stays the publisher's source of truth — this just
# lets you archive a snapshot in the repo when you want one.
#
# Usage:
#   ./infra/sync-datasets.sh           # dry-run; prints what would change
#   ./infra/sync-datasets.sh --apply   # actually copy into working tree
#
# Requires: gsutil on PATH, gcloud ADC with read access to the bucket.

set -euo pipefail

BUCKET="${GCS_STAGING_BUCKET:-govdata-il-staging}"
DEST="frontend/public/datasets"
MODE="${1:-}"

mkdir -p "$DEST"

if [[ "$MODE" != "--apply" ]]; then
  echo "==> DRY RUN  gs://$BUCKET/datasets/  ->  $DEST/  (pass --apply to sync)"
  gsutil -m rsync -r -d -n "gs://$BUCKET/datasets/" "$DEST/"
  exit 0
fi

# -d mirrors deletions: a page removed from the staging bucket disappears
# locally too, matching Cloud Build's fresh-checkout behavior. It also
# removes the publisher-written data.json/agent_data.json (not in GCS by
# design) — fine, the publisher rebuilds them right after this step.
echo "==> Syncing  gs://$BUCKET/datasets/  ->  $DEST/"
gsutil -m rsync -r -d "gs://$BUCKET/datasets/" "$DEST/"

# Per-dataset data.json + agent_data.json are owned by the publisher
# (services.page_builder.publish) and rebuilt from Firestore. index.html
# is a pre-split-era artifact that would shadow the Nuxt-generated route.
# Drop any copies that came down from GCS — same exclusions as the
# Cloud Build rsync in cloudbuild-publish.yaml.
echo "==> Scrubbing data.json + agent_data.json + index.html (publisher/Nuxt rebuild them)"
find "$DEST" \( -name 'data.json' -o -name 'agent_data.json' -o -name 'index.html' \) -delete
find "$DEST" -mindepth 1 -type d -empty -delete

echo
echo "==> Files touched:"
git status --short -- "$DEST/" || true
echo
echo "Review, then:  git add $DEST/ && git commit -m 'publish: sync agent output'"
