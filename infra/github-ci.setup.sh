#!/usr/bin/env bash
# One-time setup for the GitHub Actions publish path (.github/workflows/publish.yml).
#
# Creates:
#   - a Workload Identity Federation pool + GitHub OIDC provider scoped to
#     this repository (keyless auth — no service-account keys anywhere)
#   - the govdata-ci service account with the minimal roles the publish
#     workflow needs: read Firestore, read the staging bucket, deploy
#     Firebase Hosting
#   - the GitHub repo variables the workflow reads
#
# Requires: gcloud authed with project owner perms; gh authed on the repo.
#
# NOT created here (manual, needs your GitHub account):
#   the fine-grained PAT (this repo only, Actions: read+write) used by the
#   builder to fire workflow_dispatch — store it as the
#   `github-dispatch-token` secret:
#     printf '%s' 'github_pat_...' | gcloud secrets create github-dispatch-token \
#       --data-file=- --project=govdata-il
#     gcloud secrets add-iam-policy-binding github-dispatch-token \
#       --member="serviceAccount:govdata-builder@govdata-il.iam.gserviceaccount.com" \
#       --role=roles/secretmanager.secretAccessor --project=govdata-il

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REPO=${GITHUB_REPO:-darkdiamond/govil.ai}
POOL=${WIF_POOL:-github-pool}
PROVIDER=${WIF_PROVIDER:-github-provider}
CI_SA_NAME=${CI_SA_NAME:-govdata-ci}
STAGING_BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
CI_SA="${CI_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

echo "==> WIF pool"
gcloud iam workload-identity-pools describe "$POOL" --location=global --project="$PROJECT" >/dev/null 2>&1 || \
gcloud iam workload-identity-pools create "$POOL" \
  --location=global --project="$PROJECT" \
  --display-name="GitHub Actions"

# Trust only the publish workflow running on main of THIS repo. Scoping by
# repository name alone let any workflow on any branch (a pushed feature
# branch, a compromised PAT) mint a token for govdata-ci, which can deploy
# Firebase Hosting. repository_id is immutable — the name has changed once
# already (govdata → govil.ai), and a deleted name can be re-registered.
REPO_ID=$(gh api "repos/${REPO}" --jq .id)
WIF_CONDITION="assertion.repository_id=='${REPO_ID}' && assertion.ref=='refs/heads/main' && assertion.workflow_ref.startsWith('${REPO}/.github/workflows/publish.yml@')"
WIF_MAPPING="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref"

echo "==> WIF OIDC provider (scoped to $REPO main / publish.yml)"
if gcloud iam workload-identity-pools providers describe "$PROVIDER" \
  --workload-identity-pool="$POOL" --location=global --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global --project="$PROJECT" \
    --attribute-mapping="$WIF_MAPPING" \
    --attribute-condition="$WIF_CONDITION" >/dev/null
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --workload-identity-pool="$POOL" --location=global --project="$PROJECT" \
    --display-name="GitHub OIDC" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="$WIF_MAPPING" \
    --attribute-condition="$WIF_CONDITION"
fi

echo "==> CI service account"
gcloud iam service-accounts describe "$CI_SA" --project="$PROJECT" >/dev/null 2>&1 || \
gcloud iam service-accounts create "$CI_SA_NAME" \
  --project="$PROJECT" --display-name="GitHub Actions publish CI"

echo "==> roles (Firestore read, staging-bucket read, Hosting deploy)"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$CI_SA" --role=roles/datastore.viewer --condition=None --quiet >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://${STAGING_BUCKET}" \
  --member="serviceAccount:$CI_SA" --role=roles/storage.objectViewer --quiet >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$CI_SA" --role=roles/firebasehosting.admin --condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$CI_SA" --role=roles/firebase.viewer --condition=None --quiet >/dev/null
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:$CI_SA" --role=roles/serviceusage.serviceUsageConsumer --condition=None --quiet >/dev/null

echo "==> allow the repo's workflows to impersonate $CI_SA"
gcloud iam service-accounts add-iam-policy-binding "$CI_SA" \
  --project="$PROJECT" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  --quiet >/dev/null

WIP="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"

echo "==> GitHub repo variables"
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo "$REPO" --body "$WIP"
gh variable set GCP_CI_SA --repo "$REPO" --body "$CI_SA"
gh variable set FIREBASE_PROJECT --repo "$REPO" --body "$PROJECT"
gh variable set GCS_STAGING_BUCKET --repo "$REPO" --body "$STAGING_BUCKET"

echo
echo "==> done. provider: $WIP"
echo "    sa:       $CI_SA"
