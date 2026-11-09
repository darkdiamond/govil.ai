#!/usr/bin/env bash
# One-time IAM for govdata-news-job (services/news): its own service account,
# kept minimal. The news job runs an LLM agent that reads the open web, so it
# gets nothing it doesn't use (and it is NOT the builder SA).
#
#   Firestore                 roles/datastore.user (read sources/, write articles/ + article_rejects/)
#   staging bucket, read      roles/storage.objectViewer (models/ history, recipes; nothing secret)
#   staging bucket, write     roles/storage.objectAdmin ONLY on objects under news/ (IAM condition)
#   secrets                   secretAccessor on openrouter-news-key + github-dispatch-token
#
# Manual steps this script can't do:
#   1. The OpenRouter key (with its monthly limit set in the OpenRouter
#      dashboard — the job has no budget logic) goes into Secret Manager:
#        printf '%s' "$KEY" | gcloud secrets create openrouter-news-key \
#          --data-file=- --replication-policy=automatic --project=govdata-il
#   2. Search Console: add govdata-news@<project>.iam.gserviceaccount.com as a
#      user (Restricted) on sc-domain:govil.ai, so demand.py can read it
#      (without it demand is neutral — the job still runs).
#
# Idempotent: re-running only re-applies bindings.
set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
SA_NAME=govdata-news
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SA" --project="$PROJECT" >/dev/null 2>&1; then
  echo "==> creating service account $SA"
  gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT" \
    --display-name="govil.ai news job (LLM writer)"
fi

echo "==> Firestore"
gcloud projects add-iam-policy-binding "$PROJECT" --quiet >/dev/null \
  --member="serviceAccount:$SA" --role=roles/datastore.user --condition=None

echo "==> staging bucket: read all, write news/ only"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --quiet >/dev/null \
  --member="serviceAccount:$SA" --role=roles/storage.objectViewer
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --quiet >/dev/null \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin \
  --condition="expression=resource.name.startsWith(\"projects/_/buckets/${BUCKET}/objects/news/\"),title=news-prefix-only,description=Write only article images under news/"

echo "==> secrets"
for s in openrouter-news-key github-dispatch-token; do
  if gcloud secrets describe "$s" --project="$PROJECT" >/dev/null 2>&1; then
    gcloud secrets add-iam-policy-binding "$s" --project="$PROJECT" --quiet >/dev/null \
      --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
  else
    echo "   !! secret $s does not exist yet — create it, then re-run this script" >&2
  fi
done

echo "==> done: $SA"
echo "   Remember: add it as a Restricted user on Search Console (sc-domain:govil.ai)."
