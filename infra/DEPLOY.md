# Deployment

Three one-time setups, then the runtime flow is: Cloud Scheduler (daily
23:00 UTC — inside OpenRouter's off-peak discount window for hy3's
Tencent endpoint) → Cloud Run builder (scan CKAN → concurrent
self-validating agent sessions via OpenRouter → stage to GCS +
Firestore) → Cloud Build publisher (generate Nuxt site → deploy to
Firebase Hosting), which fires only when ≥1 new page succeeded.

Container count is pinned to **one** (`--max-instances=1 --concurrency=1`).
Per-source parallelism lives inside that container via `asyncio.gather`
bounded by `MAX_CONCURRENT`; the per-run volume fuse is `DAILY_CAP`.

## 1. Project bootstrap — `infra/bootstrap.sh`

Creates the Firebase project (GCP project with the same ID is created
automatically), enables APIs, provisions Firestore + the GCS staging bucket
(lifecycle policy from `infra/staging-lifecycle.json` — deletes only
`build-cache/` objects after 14 days; `datasets/` never expires),
creates the three service accounts, and reserves the Secret Manager secret.

Re-running `bootstrap.sh` re-applies the lifecycle policy. To tweak the
retention window without a full bootstrap:

```sh
gcloud storage buckets update gs://govdata-il-staging \
  --lifecycle-file=infra/staging-lifecycle.json --project=govdata-il
```

Prereqs:

- `firebase login` (interactive, one-time)
- `gcloud auth login` (interactive, one-time)

```sh
bash infra/bootstrap.sh
# populate the OpenRouter API key secret (one-time)
gcloud secrets create openrouter-api-key --data-file=$HOME/.config/openrouter/key \
  --project=govdata-il 2>/dev/null || \
  gcloud secrets versions add openrouter-api-key --data-file=$HOME/.config/openrouter/key \
    --project=govdata-il
gcloud secrets add-iam-policy-binding openrouter-api-key \
  --member="serviceAccount:govdata-builder@govdata-il.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor --project=govdata-il
```

The script prints the service account emails it created and ends with
instructions for registering the Cloud Build trigger (needs a connected
repo — either a GitHub 2nd-gen connection or a Cloud Source Repositories
mirror).

## 2. Cloud Run builder — `infra/builder.deploy.sh`

Builds the Docker image from the repo root and deploys the service. The
agent runtime ships inside the image: `agent/system-prompt.md` (system
prompt), `agent/skills/check.py` (self-check), and the PydanticAI loop
calling OpenRouter.

```sh
bash infra/builder.deploy.sh
# model/scale knobs (defaults shown):
#   OPENROUTER_MODEL=minimax/minimax-m3 DAILY_CAP=50 MAX_CONCURRENT=8 \
#   SESSION_ATTEMPTS=3 bash infra/builder.deploy.sh
```

Notable flags (see script for the full list):

| Flag                | Value                                    |
| ------------------- | ---------------------------------------- |
| `--max-instances`   | 1 (never more than one container)        |
| `--concurrency`     | 1 (one request in flight; no queueing)   |
| `--cpu / --memory`  | 2 / 1Gi (bump memory if `MAX_CONCURRENT > 16`) |
| `--timeout`         | 3600 s (bounds the whole daily batch)    |
| `--no-allow-unauthenticated` | Scheduler SA + your own ID token only |

Manual smoke after deploy:

```sh
URL=$(gcloud run services describe govdata-builder --region=me-west1 --format='value(status.url)')
TOKEN=$(gcloud auth print-identity-token)

# Dry run: scan + select but don't fire the agent.
curl -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'

# Full run on a specific dataset (bypass selector).
curl -X POST "$URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "<ckan-id>"}'
```

## 3. Cloud Scheduler — `infra/scheduler.setup.sh`

Creates the scheduler job **PAUSED**. Enable it only after the manual
invokes have produced real pages.

```sh
bash infra/scheduler.setup.sh
# ... when ready to flip on:
gcloud scheduler jobs resume govdata-pipeline-daily --location=me-west1
```

## Publishing

Automatic via GitHub Actions (`.github/workflows/publish.yml`, $0 on
free-tier minutes):

- the builder dispatches it after any run with ≥1 successful page
  (`PUBLISH_VIA=github` + the `github-dispatch-token` secret); idle
  runs dispatch nothing.
- pushing to main with changes under `frontend/**` (or the publisher
  code) deploys automatically; rapid pushes cancel the in-flight run
  so a burst costs one build.

One-time setup: `infra/github-ci.setup.sh` (WIF + govdata-ci SA + repo
variables) plus a fine-grained PAT (this repo, Actions read+write)
stored as the `github-dispatch-token` secret — see the script header.

Fallback #1 — Cloud Build: the `govdata-publish` trigger
(`cloudbuild-publish.yaml`) stays registered; switch with
`PUBLISH_VIA=cloudbuild` on the builder.

Fallback #2 — manual, same four steps on your machine:

```sh
source .venv/bin/activate
./infra/publish-local.sh             # full publish
./infra/publish-local.sh --serve     # local preview, no deploy
```

To pause auto-publishing (e.g. while reworking the frontend):

```sh
gcloud run services update govdata-builder --region=me-west1 \
  --update-env-vars=PUBLISH_VIA=""
```

### Pre-baked publisher image

Every publish step runs on a pre-baked image built by
`cloudbuild-publisher-image.yaml` (Dockerfile at `infra/Dockerfile.publisher`).
The image carries:

- node 22 + a warm npm cache
- `frontend/node_modules` under `/opt/frontend-deps/` so `npm ci` is skipped
  on the fast path (falls back to `npm ci --prefer-offline` if
  `package-lock.json` has drifted from the image)
- python 3.12 + the `services/page_builder/requirements.txt` deps
- the Google Cloud SDK (provides `gsutil` for the rsync step)
- `firebase-tools` globally

Registered as a second Cloud Build trigger path-filtered to
`infra/Dockerfile.publisher`, `frontend/package-lock.json`, and
`services/page_builder/requirements.txt` — so the image only rebuilds when
something it bundles actually changes. `infra/bootstrap.sh` prints the
exact registration command alongside the publish-trigger command, plus a
`gcloud builds triggers run` invocation to populate the `:latest` tag the
first time.

If you change `package-lock.json` or `requirements.txt` and merge before
the image trigger fires, the publish build detects the drift and falls
back to running `npm ci` inline — correct but slower; trigger a rebuild
of the publisher image to restore the fast path.

## Local development

```sh
# Firestore emulator
gcloud emulators firestore start --host-port=localhost:8080 &
export FIRESTORE_EMULATOR_HOST=localhost:8080 FIRESTORE_PROJECT_ID=local-dev

# Seed a few sources
python -m services.scanner.main scan --limit 5

# Dry run the pipeline against the emulator
python -m services.page_builder.pipeline --dry-run

# Full pipeline for one source (needs OPENROUTER_API_KEY + GCS_STAGING_BUCKET)
python -m services.page_builder.pipeline --source <ckan-id> --no-trigger-publish
```

## Archiving agent output into git

The publisher rsyncs `gs://govdata-il-staging/datasets/` into the Cloud
Build workspace on every deploy, so git never sees the generated
pages. To keep a reviewable snapshot in the repo, pull the current
bucket contents into the working tree and commit by hand:

```sh
./infra/sync-datasets.sh            # dry run — shows what would copy
./infra/sync-datasets.sh --apply    # copies gs://.../datasets/ -> frontend/public/datasets/
git status frontend/public/datasets/
# review, then:
git add frontend/public/datasets/ && git commit -m "publish: sync agent output"
```

The sync mirrors deletions (`gsutil rsync -d`): a page pruned from the
staging bucket disappears from the working tree on the next `--apply`,
matching what a fresh Cloud Build checkout would deploy. It also scrubs
`data.json`/`agent_data.json` (publisher rebuilds them from Firestore)
and any pre-split-era `index.html`.
