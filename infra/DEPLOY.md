# Deployment

Three one-time setups, then the runtime flow is: Cloud Scheduler (hourly,
06:00–21:00 Asia/Jerusalem) → Cloud Run **job** `govdata-builder-job` (scan
CKAN → re-render every recipe'd page whose data moved, no LLM → open a
`needs-authoring` GitHub issue per new/changed dataset without a recipe →
stage to GCS + Firestore) → GitHub Actions publisher (generate Nuxt site →
deploy to Firebase Hosting), which fires only when ≥1 page re-rendered.
Recipes are authored locally with Claude Code (a routine at 07:00, 12:00
and 17:00 works the open issues into one PR per run); merging that PR is
the deploy — the job reads `recipes/` from git `main` at run time. The news
job (`infra/news-job.deploy.sh`) ticks at :25 each hour.

One execution, one task (`--tasks=1 --parallelism=1 --max-retries=0`);
recipes refresh sequentially inside it. A scheduled run takes the
`job_state/run` Firestore lease first, so a tick that finds a run still
going ends `skipped_overlap`; inside `QUIET_WINDOW` (Friday 15:00 to
Saturday 21:00) it ends `skipped_quiet`. Both exit 0. `AUTHORING_NOTIFY_CAP`
(30) is the per-run fuse on new issues; the queue runs only in
`AUTHORING_QUEUE_HOURS` (6, 11, 16).

## 1. Project bootstrap — `infra/bootstrap.sh`

Creates the Firebase project (GCP project with the same ID is created
automatically), enables APIs, provisions Firestore + the GCS staging bucket
(lifecycle policy from `infra/staging-lifecycle.json` — deletes
`build-cache/` objects after 14 days and `models/` (page-model history) after
400 days; `datasets/` never expires),
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
```

The builder job also needs the `github-dispatch-token` secret — a
fine-grained PAT on this repo with Actions read+write (publish dispatch)
and Issues read+write (authoring issues); see the `infra/github-ci.setup.sh`
header for how to store it and grant the builder SA access.

The script prints the service account emails it created and ends with
instructions for registering the Cloud Build trigger (needs a connected
repo — either a GitHub 2nd-gen connection or a Cloud Source Repositories
mirror).

## 2. Cloud Run builder job — `infra/builder-job.deploy.sh`

Builds the Docker image from the repo root (`--source=.`, filtered by
`.gcloudignore`/`.dockerignore`) and deploys the job. The image carries
the scanner, `services/page_builder/` and the host-side page gate
`agent/skills/check.py` — no model client, no system prompt. Recipes are
not baked in: each run lists and loads them from git `main`
(`RECIPES_SOURCE`, default `github:$PUBLISH_GITHUB_REPO@main`).

```sh
bash infra/builder-job.deploy.sh
# knobs (defaults shown; see the script for the full list):
#   SCAN_LIMIT=800 MIN_MODIFIED_FLOOR=2025-01-01 MAX_AGE_DAYS=100000 \
#   AUTHORING_NOTIFY_CAP=30 REFRESH_PRECHECK=full bash infra/builder-job.deploy.sh
```

`--set-env-vars` **replaces** the job's whole env: a var you set by hand
on the live job and that isn't in the script is dropped on the next
deploy. Diff against `gcloud run jobs describe` first.

| Flag                        | Value                                            |
| --------------------------- | ------------------------------------------------ |
| `--tasks` / `--parallelism` | 1 / 1 (one container per execution)              |
| `--max-retries`             | 0 (a failed run is retried by the next tick)     |
| `--cpu / --memory`          | 2 / 4Gi (full CKAN exports are held in memory)   |
| `--task-timeout`            | 7200 s (2 h; the run lease is heartbeat-renewed) |

Manual runs after deploy:

```sh
# Dry run: scan + list the authoring queue; nothing refreshed, opened or published.
gcloud run jobs execute govdata-builder-job --region=me-west1 \
  --args=-m,services.page_builder.pipeline,--dry-run --wait

# One dataset (no scan): force-render it if it has a recipe, else queue it.
gcloud run jobs execute govdata-builder-job --region=me-west1 \
  --args=-m,services.page_builder.pipeline,--source,<ckan-id> --wait
```

A run that can't read the recipe list ends `status: refresh_unavailable`;
one whose refresh crashed or hit 3 staging (GCS/Firestore) failures in a
row ends `status: refresh_failed`; one whose authoring queue broke
(selector/Firestore/GitHub) ends `status: authoring_failed`, after
publishing what refreshed. All three exit non-zero, so the execution
shows FAILED; an idle run (nothing re-rendered) is a success, and so are
`skipped_quiet` and `skipped_overlap`.

## 3. Cloud Scheduler — `infra/scheduler.setup.sh`

Owns both ticks: `govdata-pipeline-daily` (builder, `0 6-21 * * *`) and
`govdata-news-daily` (news, `25 6-21 * * *`), Asia/Jerusalem (Cloud
Scheduler applies DST). It creates a missing tick **PAUSED**, updates an
existing one in place (its state kept), and deletes the retired
`govdata-pipeline-cbs-release` / `govdata-news-cbs-release` ticks (the 19:00
and 19:25 hourly ticks see CBS's release evening). Each tick starts a job
execution via the Admin API's `:run` method. Enable a new tick only after a
manual execution looks good. `SCHEDULER_JOB=…` (with `CLOUD_RUN_JOB`,
`SCHEDULE`, `SCHEDULER_MESSAGE_BODY`) sets up one ad-hoc tick instead.

```sh
bash infra/scheduler.setup.sh
# ... when ready to flip on:
gcloud scheduler jobs resume govdata-pipeline-daily --location=me-west1
gcloud scheduler jobs resume govdata-news-daily --location=me-west1
```

## Publishing

Automatic via GitHub Actions (`.github/workflows/publish.yml`, $0 on
free-tier minutes):

- the builder dispatches it after any run with ≥1 re-rendered page
  (`PUBLISH_VIA=github` + the `github-dispatch-token` secret); idle
  runs dispatch nothing.
- pushing to main with changes under `frontend/**` (or the publisher
  code) deploys automatically; rapid pushes cancel the in-flight run
  so a burst costs one build.

After the deploy, IndexNow gets only the URLs that are new or whose
`<lastmod>` moved against the sitemap fetched from the live site just
before it (`frontend/scripts/fetch-live-sitemap.mjs`; no baseline → every
URL).

One-time setup: `infra/github-ci.setup.sh` (WIF + govdata-ci SA + repo
variables) plus a fine-grained PAT (this repo, Actions read+write)
stored as the `github-dispatch-token` secret — see the script header.
The same PAT needs Issues read+write for the authoring queue.

Fallback #1 — Cloud Build: the `govdata-publish` trigger
(`cloudbuild-publish.yaml`) stays registered; switch with
`PUBLISH_VIA=cloudbuild` on the builder job.

Fallback #2 — manual, same four steps on your machine:

```sh
source .venv/bin/activate
./infra/publish-local.sh             # full publish
./infra/publish-local.sh --serve     # local preview, no deploy
```

To pause auto-publishing (e.g. while reworking the frontend):

```sh
gcloud run jobs update govdata-builder-job --region=me-west1 \
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
- python 3.11 (Debian bookworm's python3) + the publisher's deps,
  `services/page_builder/requirements-publish.txt` (the file `publish.yml`
  installs too)
- the Google Cloud SDK (provides `gsutil` for the rsync step)
- `firebase-tools` globally

Registered as a second Cloud Build trigger path-filtered to
`infra/Dockerfile.publisher`, `frontend/package-lock.json`,
`services/page_builder/requirements-publish.txt` and `.dockerignore` — so
the image only rebuilds when something it bundles actually changes.
`infra/bootstrap.sh` prints the exact registration command alongside the
publish-trigger command, plus a `gcloud builds triggers run` invocation to
populate the `:latest` tag the first time. (A trigger created before
2026-11-11 still watches `services/page_builder/requirements.txt`: see
`TODO.md`.)

If you change `package-lock.json` and merge before the image trigger
fires, the publish build detects the drift and falls back to running
`npm ci` inline — correct but slower; trigger a rebuild of the publisher
image to restore the fast path. A change to `requirements-publish.txt` has
no such fallback: the Cloud Build path uses it once the image is rebuilt.

## Local development

```sh
# Firestore emulator
gcloud emulators firestore start --host-port=localhost:8080 &
export FIRESTORE_EMULATOR_HOST=localhost:8080 FIRESTORE_PROJECT_ID=local-dev

# Seed a few sources
python -m services.scanner.main scan --limit 5

# Dry run the pipeline against the emulator (scan + list the authoring queue)
python -m services.page_builder.pipeline --dry-run

# One source: refresh it if it has a recipe, else queue it for authoring
# (needs GCS_STAGING_BUCKET; queueing needs GITHUB_DISPATCH_TOKEN)
python -m services.page_builder.pipeline --source <ckan-id> --no-trigger-publish
```

## Archiving rendered pages into git

The publisher rsyncs `gs://govdata-il-staging/datasets/` into the Cloud
Build workspace on every deploy, so git never sees the generated
pages. To keep a reviewable snapshot in the repo, pull the current
bucket contents into the working tree and commit by hand:

```sh
./infra/sync-datasets.sh            # dry run — shows what would copy
./infra/sync-datasets.sh --apply    # copies gs://.../datasets/ -> frontend/public/datasets/
git status frontend/public/datasets/
# review, then:
git add frontend/public/datasets/ && git commit -m "publish: sync rendered pages"
```

The sync mirrors deletions (`gsutil rsync -d`): a page pruned from the
staging bucket disappears from the working tree on the next `--apply`,
matching what a fresh Cloud Build checkout would deploy. It also scrubs
`data.json`/`agent_data.json` (publisher rebuilds them from Firestore)
and any pre-split-era `index.html`.
