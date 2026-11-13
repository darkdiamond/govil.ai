#!/usr/bin/env bash
# Apply infra/artifact-cleanup.json to the project's Docker repos in Artifact Registry.
#
# Every deploy pushes a new image and nothing deleted the old ones (16 GB by
# 2026-11-13, ~$1.5/month). The policy deletes versions older than 14 days,
# but per package it always keeps the 5 most recent versions and anything
# tagged `latest`. Cloud Run jobs pin their image by digest, and the newest
# version is the deployed one, so the running jobs' images (and a few
# rollback targets) survive. Keep rules override delete rules. AR applies
# policies in the background, about once a day.
#
#   ./infra/artifact-cleanup.setup.sh            # apply
#   ./infra/artifact-cleanup.setup.sh --dry-run  # log what would go, delete nothing
set -euo pipefail

PROJECT=${PROJECT:-govdata-il}
AR_LOCATION=${AR_LOCATION:-me-west1}
REPOS=${AR_CLEANUP_REPOS:-"cloud-run-source-deploy publisher"}
POLICY="$(dirname "$0")/artifact-cleanup.json"

MODE=--no-dry-run
[[ "${1:-}" == "--dry-run" ]] && MODE=--dry-run

for repo in $REPOS; do
  if ! gcloud artifacts repositories describe "$repo" --location="$AR_LOCATION" --project "$PROJECT" >/dev/null 2>&1; then
    echo "==> skipping '$repo' (no such repo in $AR_LOCATION)"
    continue
  fi
  echo "==> cleanup policy on '$repo' ($MODE)"
  gcloud artifacts repositories set-cleanup-policies "$repo" \
    --location="$AR_LOCATION" --project "$PROJECT" \
    --policy="$POLICY" "$MODE" >/dev/null
done
