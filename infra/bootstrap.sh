#!/usr/bin/env bash
# One-time bootstrap for govdata-il Firebase + GCP project.
#
# Creates the Firebase project (GCP project with the same ID is created
# automatically), enables APIs, provisions Firestore + GCS + IAM service
# accounts, and creates a Cloud Build trigger for the publisher.
#
# Requires:
#   - firebase CLI        (https://firebase.google.com/docs/cli)
#   - gcloud CLI          (https://cloud.google.com/sdk/docs/install)
#   - `firebase login`    (run once interactively before this script)
#   - `gcloud auth login` (run once interactively before this script)
#
# Safe to re-run — each step is idempotent.

set -euo pipefail

PROJECT=${FIREBASE_PROJECT:-govdata-il}
REGION=${REGION:-me-west1}
STAGING_BUCKET=${GCS_STAGING_BUCKET:-${PROJECT}-staging}
TRIGGER_ID=${PUBLISH_TRIGGER_ID:-govdata-publish}
IMAGE_TRIGGER_ID=${PUBLISHER_IMAGE_TRIGGER_ID:-govdata-publisher-image}
PUBLISH_BRANCH=${PUBLISH_BRANCH:-main}
REPO_NAME=${CSR_REPO_NAME:-govdata-il}
AR_LOCATION=${AR_LOCATION:-$REGION}
AR_REPO=${AR_REPO:-publisher}

cd "$(dirname "$0")/.."

echo "==> Project: $PROJECT   Region: $REGION"

# ---- 1. Firebase / GCP project ---------------------------------------------
if gcloud projects describe "$PROJECT" --format='value(projectId)' >/dev/null 2>&1; then
  echo "==> GCP project $PROJECT already exists — ensuring Firebase is attached"
  firebase projects:addfirebase "$PROJECT" >/dev/null 2>&1 || true
else
  echo "==> creating Firebase project $PROJECT"
  firebase projects:create "$PROJECT" --display-name "GovData IL"
fi

gcloud config set project "$PROJECT"

# ---- 2. Enable APIs --------------------------------------------------------
echo "==> enabling required APIs"
gcloud services enable \
  firestore.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  firebasehosting.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project "$PROJECT"

# ---- 3. Firestore (Native mode) --------------------------------------------
if ! gcloud firestore databases describe --project "$PROJECT" >/dev/null 2>&1; then
  echo "==> creating Firestore database (Native, $REGION)"
  gcloud firestore databases create --location="$REGION" --type=firestore-native --project "$PROJECT"
else
  echo "==> Firestore database already exists"
fi

# ---- 4. GCS staging bucket -------------------------------------------------
if ! gcloud storage buckets describe "gs://$STAGING_BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  echo "==> creating staging bucket gs://$STAGING_BUCKET"
  gcloud storage buckets create "gs://$STAGING_BUCKET" \
    --location="$REGION" \
    --uniform-bucket-level-access \
    --project "$PROJECT"
else
  echo "==> staging bucket gs://$STAGING_BUCKET already exists"
fi

# Lifecycle: prune the Nuxt build cache after 14 days. Datasets/content.html
# are NOT pruned: a dataset that CKAN never re-flags as updated would never
# be re-staged, so a catch-all delete would silently strip the body from the
# next publish.
echo "==> applying lifecycle policy to gs://$STAGING_BUCKET"
gcloud storage buckets update "gs://$STAGING_BUCKET" \
  --lifecycle-file="$(dirname "$0")/staging-lifecycle.json" \
  --project "$PROJECT" >/dev/null

# ---- 5. Service accounts ---------------------------------------------------
create_sa() {
  local name=$1 display=$2
  if ! gcloud iam service-accounts describe "${name}@${PROJECT}.iam.gserviceaccount.com" --project "$PROJECT" >/dev/null 2>&1; then
    echo "==> creating SA ${name}"
    gcloud iam service-accounts create "$name" --display-name "$display" --project "$PROJECT"
  else
    echo "==> SA ${name} already exists"
  fi
}
create_sa "govdata-builder"   "GovData Cloud Run builder"
create_sa "govdata-publisher" "GovData Cloud Build publisher"
create_sa "govdata-scheduler" "GovData Cloud Scheduler caller"

BUILDER_SA="govdata-builder@${PROJECT}.iam.gserviceaccount.com"
PUBLISHER_SA="govdata-publisher@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_SA="govdata-scheduler@${PROJECT}.iam.gserviceaccount.com"

echo "==> granting IAM roles"
# Builder: Firestore r/w, GCS r/w on staging, write logs.
#
# The agent's tool subprocesses can reach the metadata server and mint this
# SA's token (accepted risk, see CLAUDE.md), so every role here is reachable
# by a prompt-injected session. Cloud Build rights are therefore opt-in:
# `cloudbuild.builds.editor` + actAs on the publisher SA let a token holder
# run an arbitrary build as govdata-publisher (firebasehosting.admin) —
# i.e. deploy anything to govil.ai. Prod publishes via GitHub Actions
# (PUBLISH_VIA=github), which needs neither. Set ENABLE_CLOUDBUILD_PUBLISH=1
# only if you switch the builder to PUBLISH_VIA=cloudbuild.
ENABLE_CLOUDBUILD_PUBLISH=${ENABLE_CLOUDBUILD_PUBLISH:-0}
for role in roles/datastore.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$BUILDER_SA" --role="$role" --condition=None --quiet >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$STAGING_BUCKET" \
  --member="serviceAccount:$BUILDER_SA" --role=roles/storage.objectAdmin --quiet >/dev/null

# Publisher: read+write Firestore (writes back voyage embedding cache on
# sources/<id>.embedding), read staging GCS, deploy Firebase Hosting.
# AR access is granted on the publisher repo below (writer covers the
# image-build trigger's push + the publish trigger's pull).
for role in roles/datastore.user roles/logging.logWriter roles/firebasehosting.admin; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$PUBLISHER_SA" --role="$role" --condition=None --quiet >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$STAGING_BUCKET" \
  --member="serviceAccount:$PUBLISHER_SA" --role=roles/storage.objectViewer --quiet >/dev/null

# Cloud Build publish fallback only: the builder must be able to fire the
# trigger and impersonate the publisher SA it runs as.
if [[ "$ENABLE_CLOUDBUILD_PUBLISH" == "1" ]]; then
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$BUILDER_SA" --role=roles/cloudbuild.builds.editor --condition=None --quiet >/dev/null
  gcloud iam service-accounts add-iam-policy-binding "$PUBLISHER_SA" \
    --member="serviceAccount:$BUILDER_SA" --role=roles/iam.serviceAccountUser \
    --project "$PROJECT" --quiet >/dev/null
fi

# Scheduler: may invoke the Cloud Run builder.
# (The run.invoker binding is attached to the job after deploy; see builder-job.deploy.sh.)

# ---- 5b. Artifact Registry (pre-baked publisher image) ---------------------
if ! gcloud artifacts repositories describe "$AR_REPO" --location="$AR_LOCATION" --project "$PROJECT" >/dev/null 2>&1; then
  echo "==> creating Artifact Registry repo '$AR_REPO' in $AR_LOCATION"
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$AR_LOCATION" \
    --project "$PROJECT" >/dev/null
else
  echo "==> Artifact Registry repo '$AR_REPO' already exists"
fi
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" \
  --location="$AR_LOCATION" --project "$PROJECT" \
  --member="serviceAccount:$PUBLISHER_SA" \
  --role=roles/artifactregistry.writer --quiet >/dev/null

# ---- 6. Secret Manager -----------------------------------------------------
if ! gcloud secrets describe voyage-api-key --project "$PROJECT" >/dev/null 2>&1; then
  echo "==> creating Secret Manager secret 'voyage-api-key' (empty; populate via: "
  echo "    printf '%s' \"\$VOYAGE_API_KEY\" | gcloud secrets versions add voyage-api-key --data-file=-)"
  gcloud secrets create voyage-api-key --replication-policy=automatic --project "$PROJECT" >/dev/null
fi
gcloud secrets add-iam-policy-binding voyage-api-key \
  --member="serviceAccount:$BUILDER_SA" --role=roles/secretmanager.secretAccessor --quiet >/dev/null || true

# ---- 7. Cloud Build triggers (publisher + publisher image) -----------------
echo "==> Cloud Build trigger '$TRIGGER_ID' (publisher — cloudbuild-publish.yaml)"
if ! gcloud builds triggers describe "$TRIGGER_ID" --region=global --project "$PROJECT" >/dev/null 2>&1; then
  echo "    NOTE: this trigger must be connected to the source repo manually."
  echo "          Options:"
  echo "            - GitHub via 2nd-gen connection: gcloud builds triggers create github ..."
  echo "            - Cloud Source Repositories mirror: connect via Console first, then:"
  echo "                gcloud source repos create $REPO_NAME --project $PROJECT"
  echo "                (push your git remote to https://source.developers.google.com/p/$PROJECT/r/$REPO_NAME)"
  echo
  echo "    Once connected, register the trigger with:"
  echo "      gcloud builds triggers create manual \\"
  echo "        --name=$TRIGGER_ID \\"
  echo "        --repo=projects/$PROJECT/locations/global/connections/<CONN>/repositories/<REPO> \\"
  echo "        --build-config=cloudbuild-publish.yaml \\"
  echo "        --branch=$PUBLISH_BRANCH \\"
  echo "        --service-account=projects/$PROJECT/serviceAccounts/$PUBLISHER_SA \\"
  echo "        --project=$PROJECT"
else
  echo "    trigger already configured"
fi

echo "==> Cloud Build trigger '$IMAGE_TRIGGER_ID' (publisher image — cloudbuild-publisher-image.yaml)"
if ! gcloud builds triggers describe "$IMAGE_TRIGGER_ID" --region="$REGION" --project "$PROJECT" >/dev/null 2>&1; then
  echo "    Register a push trigger path-filtered to the files that invalidate"
  echo "    the pre-baked publisher image:"
  echo "      - infra/Dockerfile.publisher"
  echo "      - frontend/package-lock.json"
  echo "      - services/page_builder/requirements.txt"
  echo "      - .dockerignore"
  echo
  echo "    With a GitHub 2nd-gen connection (replace <CONN>/<REPO>):"
  echo "      gcloud builds triggers create github \\"
  echo "        --name=$IMAGE_TRIGGER_ID \\"
  echo "        --region=$REGION \\"
  echo "        --repository=projects/$PROJECT/locations/$REGION/connections/<CONN>/repositories/<REPO> \\"
  echo "        --branch-pattern='^${PUBLISH_BRANCH}\$' \\"
  echo "        --included-files='infra/Dockerfile.publisher,frontend/package-lock.json,services/page_builder/requirements.txt,.dockerignore' \\"
  echo "        --build-config=cloudbuild-publisher-image.yaml \\"
  echo "        --service-account=projects/$PROJECT/serviceAccounts/$PUBLISHER_SA \\"
  echo "        --project=$PROJECT"
  echo
  echo "    (Run once manually after registering to populate :latest:"
  echo "      gcloud builds triggers run $IMAGE_TRIGGER_ID --branch=$PUBLISH_BRANCH --project=$PROJECT)"
else
  echo "    trigger already configured"
fi

echo
echo "==> Bootstrap done."
echo "    Builder SA:    $BUILDER_SA"
echo "    Publisher SA:  $PUBLISHER_SA"
echo "    Scheduler SA:  $SCHEDULER_SA"
echo "    Staging bucket: gs://$STAGING_BUCKET"
echo
echo "Next: store the github-dispatch-token secret (see infra/github-ci.setup.sh header), then:"
echo "  bash infra/builder-job.deploy.sh  # deploy the Cloud Run builder job"
echo "  bash infra/scheduler.setup.sh     # create the (paused) scheduler"
