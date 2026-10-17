#!/usr/bin/env bash
# Remove the builder SA's Cloud Build escalation path on an existing project.
#
# The agent's tool subprocesses can reach the GCP metadata server and mint
# the builder SA's token (accepted risk, CLAUDE.md "Sandbox boundary"). With
# `roles/cloudbuild.builds.editor` + `iam.serviceAccountUser` on
# govdata-publisher, that token could submit a build running as the publisher
# SA (firebasehosting.admin) and deploy arbitrary content to govil.ai. Prod
# publishes via GitHub Actions (PUBLISH_VIA=github) and needs neither.
#
# bootstrap.sh no longer grants these unless ENABLE_CLOUDBUILD_PUBLISH=1;
# this script removes them where an older bootstrap already did. Idempotent.
# Re-grant (only if you move the builder to PUBLISH_VIA=cloudbuild):
#   ENABLE_CLOUDBUILD_PUBLISH=1 ./infra/bootstrap.sh
#
# WIF scoping (publish.yml on main only) is applied by re-running
# ./infra/github-ci.setup.sh, which now updates the existing provider.
#
# Usage: ./infra/iam-harden.sh [--dry-run]

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
BUILDER_SA="govdata-builder@${PROJECT}.iam.gserviceaccount.com"
PUBLISHER_SA="govdata-publisher@${PROJECT}.iam.gserviceaccount.com"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

run() {
  if (( DRY_RUN )); then echo "  would run: $*" >&2; else "$@"; fi
}

echo "==> builder SA project roles (before)"
gcloud projects get-iam-policy "$PROJECT" \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${BUILDER_SA}" \
  --format="value(bindings.role)"

if gcloud projects get-iam-policy "$PROJECT" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${BUILDER_SA} AND bindings.role:roles/cloudbuild.builds.editor" \
    --format="value(bindings.role)" | grep -q .; then
  echo "==> removing roles/cloudbuild.builds.editor from $BUILDER_SA"
  run gcloud projects remove-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$BUILDER_SA" --role=roles/cloudbuild.builds.editor \
    --condition=None --quiet >/dev/null
else
  echo "==> cloudbuild.builds.editor: not granted (ok)"
fi

if gcloud iam service-accounts get-iam-policy "$PUBLISHER_SA" --project "$PROJECT" \
    --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:${BUILDER_SA} AND bindings.role:roles/iam.serviceAccountUser" \
    --format="value(bindings.role)" 2>/dev/null | grep -q .; then
  echo "==> removing iam.serviceAccountUser on $PUBLISHER_SA from $BUILDER_SA"
  run gcloud iam service-accounts remove-iam-policy-binding "$PUBLISHER_SA" \
    --member="serviceAccount:$BUILDER_SA" --role=roles/iam.serviceAccountUser \
    --project "$PROJECT" --quiet >/dev/null
else
  echo "==> actAs on publisher SA: not granted (ok)"
fi

echo "==> builder SA project roles (after)"
gcloud projects get-iam-policy "$PROJECT" \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${BUILDER_SA}" \
  --format="value(bindings.role)"
