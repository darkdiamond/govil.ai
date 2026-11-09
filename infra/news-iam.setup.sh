#!/usr/bin/env bash
# One-time IAM for govdata-news-job (services/news): its own service account,
# kept minimal. The news job runs an LLM agent that reads the open web, so it
# gets nothing it doesn't use (and it is NOT the builder SA).
#
#   Firestore, default db     roles/datastore.viewer (reads sources/ to load a dataset's tables)
#   Firestore, `news` db      roles/datastore.user, IAM-conditioned to that database only
#                             (articles/ + article_rejects/ — services/news/store.py). Firestore
#                             can't scope a grant to a collection; a separate database it can.
#   staging bucket, read      roles/storage.objectViewer (models/ history, recipes; nothing secret)
#   staging bucket, write     roles/storage.objectAdmin ONLY on objects under news/ (IAM condition)
#   secrets                   secretAccessor on openrouter-news-key + github-news-dispatch-token
#                             (its own PAT, not the builder's github-dispatch-token)
#
# Manual steps this script can't do:
#   1. The OpenRouter key (with its monthly limit set in the OpenRouter
#      dashboard — the job has no budget logic):
#        printf '%s' "$KEY" | gcloud secrets create openrouter-news-key \
#          --data-file=- --replication-policy=automatic --project=govdata-il
#   2. A NEW fine-grained GitHub PAT, scoped to darkdiamond/govil.ai with only
#      Actions: write (it only dispatches publish.yml; recipes are read from the
#      public repo without a token):
#        printf '%s' "$PAT" | gcloud secrets create github-news-dispatch-token \
#          --data-file=- --replication-policy=automatic --project=govdata-il
#   3. Search Console: add govdata-news@<project>.iam.gserviceaccount.com as a
#      Restricted user on sc-domain:govil.ai (without it demand is neutral).
#
# Idempotent: re-running only re-applies bindings.
set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
NEWS_DB=${NEWS_FIRESTORE_DATABASE:-news}
SA_NAME=govdata-news
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SA" --project="$PROJECT" >/dev/null 2>&1; then
  echo "==> creating service account $SA"
  gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT" \
    --display-name="govil.ai news job (LLM writer)"
fi

if ! gcloud firestore databases describe --database="$NEWS_DB" --project="$PROJECT" >/dev/null 2>&1; then
  echo "==> creating Firestore database $NEWS_DB ($REGION)"
  gcloud firestore databases create --database="$NEWS_DB" --location="$REGION" \
    --type=firestore-native --project="$PROJECT"
fi

echo "==> Firestore: read the default database, write only $NEWS_DB"
gcloud projects add-iam-policy-binding "$PROJECT" --quiet >/dev/null \
  --member="serviceAccount:$SA" --role=roles/datastore.viewer --condition=None
gcloud projects add-iam-policy-binding "$PROJECT" --quiet >/dev/null \
  --member="serviceAccount:$SA" --role=roles/datastore.user \
  --condition="expression=resource.name==\"projects/${PROJECT}/databases/${NEWS_DB}\",title=news-db-only,description=Write only the news Firestore database"

echo "==> staging bucket: read all, write news/ only"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --quiet >/dev/null \
  --member="serviceAccount:$SA" --role=roles/storage.objectViewer
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --quiet >/dev/null \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin \
  --condition="expression=resource.name.startsWith(\"projects/_/buckets/${BUCKET}/objects/news/\"),title=news-prefix-only,description=Write only article images under news/"

echo "==> secrets"
for s in openrouter-news-key github-news-dispatch-token; do
  if gcloud secrets describe "$s" --project="$PROJECT" >/dev/null 2>&1; then
    gcloud secrets add-iam-policy-binding "$s" --project="$PROJECT" --quiet >/dev/null \
      --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor
  else
    echo "   !! secret $s does not exist yet — create it (see the header), then re-run" >&2
  fi
done

echo "==> done: $SA"
echo "   Remember: add it as a Restricted user on Search Console (sc-domain:govil.ai)."
