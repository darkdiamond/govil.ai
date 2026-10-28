# govil.ai — Landing pages for Israeli open data

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Nuxt 3](https://img.shields.io/badge/Nuxt-3-00DC82.svg)](https://nuxt.com/)

Each week the Israeli government publishes new datasets on
[data.gov.il](https://data.gov.il). This repo turns each dataset into a
polished Hebrew, right-to-left landing page with an AI-written summary,
real visualizations, and navigation that connects related datasets across
ministries and topics. The live site is [govil.ai](https://govil.ai).

**Docs:** [Architecture](docs/ARCHITECTURE.md) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[Code of Conduct](CODE_OF_CONDUCT.md) · [Conventions](CLAUDE.md)

## How it works

```
Cloud Scheduler (daily 07:00 Asia/Jerusalem)
        │
        ▼
Cloud Run: govdata-builder (1 container, concurrency=1)
  pipeline.run_pipeline
    scan CKAN → Firestore sources/*            (scanner)
    select all never-analyzed + retryable-failed (≤ DAILY_CAP)
    run sessions concurrently (Semaphore(MAX_CONCURRENT))
        │  each session: PydanticAI agent ← OpenRouter (OPENROUTER_MODEL,
        │  default minimax/minimax-m3); tools = bash + python in a private
        │  subprocess workdir, web_fetch, web_search; self-validates
        │  (schema → sanitizer → check.py) with up to SESSION_ATTEMPTS
        │  retries before anything persists
        ▼
    content.html → gs://<staging>/datasets/<id>/
    agent_data + usage/cost → Firestore sources/<id>
    ≥1 success → dispatch GitHub Actions publish workflow
                   rsync GCS → publish.py (data.json, agent_data.json,
                   manifest.json from Firestore) → nuxt generate →
                   firebase deploy        (no new pages → no build)
    (the same workflow also runs on every push to main touching
     frontend/** — push-to-deploy, bursts collapse to one run)
```

Each dataset page body is authored by the agent; the Nuxt shell wraps it
with the shared chrome (header, breadcrumb, metadata sidebar, related
datasets, data explorer, footer) at `nuxt generate` time. Nuxt also
generates the home and category pages (`/ministries/<slug>/`,
`/tags/<slug>/`, `/kinds/<kind>/`) from the manifest.

## Layout

```
services/
  scanner/                     CKAN scanner → Firestore sources/*
  page_builder/                daily pipeline + agent runtime + publisher
    main.py                      HTTP entrypoint (functions-framework)
    pipeline.py                  scan → select → concurrent sessions → publish trigger
    agent_runner.py              prod session: attempts + validation + GCS/Firestore
    model_harness.py             shared PydanticAI agent loop (OpenRouter routing)
    agent_contract.py            user-message builder + CKAN prefetch + output sanitizer
    local_sandbox.py             prod tool sandbox (subprocess, private workdir)
    podman_sandbox.py            shared sandbox result types (no longer a runtime sandbox)
    selector.py                  which sources to analyze (incl. failed-retry)
    publish.py                   Firestore → data.json/agent_data.json/manifest.json
    related.py / embeddings.py   related-dataset scoring (Voyage optional)
    cli/model_test.py            manual model A/B harness (see below)
    cli/preview.py               preview harness builds in the prod shell
agent/
  system-prompt.md             canonical agent system prompt (hand-edited)
  skills/check.py              self-check enforcing the prompt's hard rules
infra/
  builder.deploy.sh            Cloud Run deploy (env: OPENROUTER_MODEL, DAILY_CAP, …)
  scheduler.setup.sh           Cloud Scheduler (0 7 * * *, Asia/Jerusalem)
  publish-local.sh             manual publish path (same steps as Cloud Build)
  DEPLOY.md                    full runbook
frontend/                      Nuxt 3 (shell + home + category pages)
```

## Quick start

Prereqs: Python 3.12, Node 22, an OpenRouter API key
(https://openrouter.ai/settings/keys), and optionally a `VOYAGE_API_KEY`
for embedding-driven relatedness.

```sh
# 1. Python env
python3 -m venv .venv && source .venv/bin/activate
python -m pip install -U pip   # stock pip 24.x fails to resolve pydantic-ai's extras
pip install -r services/page_builder/requirements.txt

# 2. Scan into the Firestore emulator (needs a Java 8+ JRE on PATH)
gcloud emulators firestore start --host-port=localhost:8080 &
export FIRESTORE_EMULATOR_HOST=localhost:8080 FIRESTORE_PROJECT_ID=local-dev
python -m services.scanner.main scan --limit 20

# 3. Build one dataset end-to-end (agent session + validation)
export OPENROUTER_API_KEY=sk-or-...
export GCS_STAGING_BUCKET=<your-staging-bucket>
python -m services.page_builder.pipeline --source <dataset_id> --no-trigger-publish

# 4. Frontend (reads manifest.json at build time)
python -m services.page_builder.publish --from-firestore \
  --out frontend/public/
cd frontend && npm install && npm run generate
npx serve .output/public
```

## Runtime ingredients

- **MiniMax M3 via OpenRouter** drives the agent (`OPENROUTER_MODEL` —
  any OpenRouter model id is a redeploy away). Per-page cost is reported
  as actual billed USD (usage accounting) in `sources/<id>.last_usage`,
  typically $0.03–0.10.
- **Voyage** (optional, `VOYAGE_ENABLED`) computes a 1024-dim embedding
  from title + summary + org + tags. Used by `related.py` to catch
  semantically-similar datasets that don't share a literal tag.
- **Firebase Hosting** serves everything. Nuxt-generated shell + home +
  category pages wrap the agent-authored bodies at generate time.
- **Cloud Run** runs the daily builder (3600s timeout bounds the whole
  batch; per-tool commands are capped at 120s).

## Configuration / self-hosting

The defaults baked into the infra scripts (GCP project `govdata-il`,
staging bucket `govdata-il-staging`, region `me-west1`, publish target
`darkdiamond/govdata`) are **just defaults** — none are secrets. To run
your own instance, override them via environment variables. Copy
[`.env.example`](.env.example) to `.env` and set the ones you need:

| Variable                            | Purpose                                                      |
| ----------------------------------- | ------------------------------------------------------------ |
| `OPENROUTER_API_KEY`                | Drives the agent (required to build pages)                   |
| `OPENROUTER_MODEL`                  | Model id, e.g. `minimax/minimax-m3`                          |
| `FIRESTORE_PROJECT_ID`              | Firestore project (or use `FIRESTORE_EMULATOR_HOST` locally) |
| `GCS_STAGING_BUCKET`                | Bucket the agent's `content.html` lands in                   |
| `FIREBASE_PROJECT`                  | Firebase Hosting / GCP project for deploys                   |
| `PUBLISH_GITHUB_REPO`               | `owner/repo` the builder dispatches the publish workflow to  |
| `VOYAGE_API_KEY` / `VOYAGE_ENABLED` | Optional embedding-driven relatedness                        |

`.env` is gitignored — never commit secrets. See
[`infra/DEPLOY.md`](infra/DEPLOY.md) for the full provisioning runbook.

### Forking notes

A fork builds clean by default, but a few things are govil.ai-specific:

- **Analytics/ads are off unless you opt in.** GA4, AdSense, and
  Microsoft Clarity load only when `NUXT_PUBLIC_GTAG_ID` /
  `NUXT_PUBLIC_ADSENSE_ID` / `NUXT_PUBLIC_CLARITY_ID` are set at
  `nuxt generate` time (in CI they come from GitHub repo variables —
  see `.github/workflows/publish.yml`). `ads.txt` is generated from the
  AdSense ID, never committed.
- **Replace the site identity.** The canonical URL `https://govil.ai`
  is hardcoded in `frontend/composables/useSeo.ts`,
  `frontend/public/robots.txt`, `frontend/public/site.webmanifest`, and
  `frontend/scripts/build-sitemap.mjs`; the IndexNow key file
  (`frontend/public/d6ede06d….txt` + `frontend/scripts/indexnow-ping.mjs`)
  is bound to that domain — generate your own or delete the ping step.
- **Configure the publish workflow.** `publish.yml` needs the four repo
  variables provisioned by [`infra/github-ci.setup.sh`](infra/github-ci.setup.sh)
  (WIF provider, CI service account, Firebase project, staging bucket);
  until then pushes to `main` show a failed `publish` run — harmless.

## Publishing

The site can be published two ways — both run identical steps (rsync agent
output from GCS → rebuild `manifest.json` from Firestore → `nuxt generate`
→ `firebase deploy --only hosting`):

- **GitHub Actions** (default) — [`.github/workflows/publish.yml`](.github/workflows/publish.yml)
  runs on every push to `main` touching the frontend/publisher, and is
  dispatched by the daily builder after successful agent runs. Auth is
  keyless via Workload Identity Federation (`infra/github-ci.setup.sh`);
  a Cloud Build fallback exists in `cloudbuild-publish.yaml`.
- **Local** — `./infra/publish-local.sh` runs the same four steps from
  your machine. Useful when you want to push a fix without waiting on the
  trigger, or to preview the _exact_ static output before it goes live.

```sh
./infra/publish-local.sh --serve   # build, then serve at http://localhost:3000
./infra/publish-local.sh --dry-run # build only, skip firebase deploy
./infra/publish-local.sh           # full publish to Firebase Hosting
```

Prereqs for the local path: `gcloud auth application-default login`,
`firebase login`, and an active project venv. Other flags
(`--skip-sync`, `--skip-manifest`, `--skip-generate`) and env overrides
(`FIREBASE_PROJECT`, `GCS_STAGING_BUCKET`, `PORT`) are documented in
`./infra/publish-local.sh --help`.

See [`infra/DEPLOY.md`](infra/DEPLOY.md) for the full deployment runbook and
[`CLAUDE.md`](CLAUDE.md) for repository conventions.

## Manual-run model harness (any model via OpenRouter)

A local CLI lets you A/B page quality across models without touching the
live pipeline. Models route through **OpenRouter** — one
`OPENROUTER_API_KEY`, any `<vendor>/<model>` id from
https://openrouter.ai/models (`minimax/minimax-m3`,
`moonshotai/kimi-k2.6`, `x-ai/grok-4.3`, `anthropic/claude-sonnet-4-6`,
…). `--model anthropic:claude-…` bypasses OpenRouter for native-Anthropic
calibration runs. A benchmark run is production's own session path
(`agent_runner.run_validated_session`: prefetch, `LocalSandbox`, the
`SESSION_ATTEMPTS` retry loop, all four validation gates), executed inside
the production image under rootless Podman with the live job's env and
CPU/memory limits. Only persistence differs: results go to `tmp/model_test/`,
nothing to GCS or Firestore.

### Install (local-only)

The production builder + publisher images do **not** install these deps —
they live in a separate file, and `Dockerfile` / `infra/Dockerfile.publisher`
only `COPY services/page_builder/requirements.txt`. So the live images stay
byte-identical whether or not this harness is used.

```sh
sudo apt install podman                              # runs the production image
pip install -r services/page_builder/requirements.txt \
            -r services/page_builder/requirements-test.txt
```

Set `OPENROUTER_API_KEY` (or `ANTHROPIC_API_KEY` for the `anthropic:`
calibration path). For OpenRouter runs, `cost.json` reports the **actual
billed USD** from OpenRouter usage accounting — including provider-side
cache discounts that vendors' own compat endpoints often hide (MiniMax
direct under-reported by ~6×). The `anthropic:` path falls back to the
small static `PRICE_TABLE` in `services/page_builder/model_harness.py`.

### Run

```sh
# build one dataset (or --batch <id1> <id2> ...). Builds the production image,
# reads the job's live env via gcloud (or BENCH_ENV_FILE), runs the session in
# the container. Your Google credentials never enter it: Firestore is read on
# the host into a snapshot file.
infra/benchmark.sh --source <dataset_id> --model minimax/minimax-m3

# The CLI refuses to run agent tools directly on your machine (they are plain
# subprocesses, as in production). ALLOW_HOST_SANDBOX=1 overrides that; then
# model-written shell runs as you, with your credentials in reach.

# outputs land in tmp/model_test/<id>/
#   content.html       agent body
#   agent_data.json    summary_he, dataset_kind, related_ids
#   transcript.json    full message log
#   cost.json          tokens + USD breakdown
```

Verbose per-tool-call logging is on by default — each `bash`, `python`,
`web_fetch`, `web_search` call prints its arg preview, elapsed time, and
output size.

### Preview against the live prod page

Two ways to see a harness build rendered through the real dataset shell:

```sh
# Offline — splices the harness body into a fetched copy of the live govil.ai
# page, strips Nuxt hydration so the splice survives, rewrites root-relative
# URLs to absolute. Open the printed file:// URL.
python -m services.page_builder.cli.preview render <id>

# Full Nuxt-shell — backs up frontend/public/datasets/<id>/{content.html,
# agent_data.json}, drops the harness build in their place, then `npm run dev`
# serves it at localhost:3000. Restores the prod files when you're done.
python -m services.page_builder.cli.preview swap <id>
cd frontend && npm run dev
# http://localhost:3000/datasets/<id>  vs  https://govil.ai/datasets/<id>
python -m services.page_builder.cli.preview restore <id>

python -m services.page_builder.cli.preview status   # what's swapped right now
```

### Production isolation (what the harness does NOT touch)

- **No Cloud Run / Cloud Build image change.** Test-only deps live in
  `requirements-test.txt`, never copied by the production Dockerfiles.
- **No imports leak.** `model_harness` / `podman_sandbox` / `cli/*` are
  only referenced by themselves; `pipeline.py`, `publish.py`, `scanner/`,
  and `agent_runner.run_production_session` never load them.
- **No Firestore / GCS writes.** The harness reads source records from
  Firestore (so it picks up real CKAN metadata) but writes nothing back;
  outputs land under `tmp/model_test/`, which is gitignored.
- **No production page change.** `swap` backs up the prod files first;
  `restore` returns them byte-identical.

The full model-comparison methodology (dataset selection, what to check,
how to archive snapshots locally) is in
[`docs/MODEL_EVAL.md`](docs/MODEL_EVAL.md).

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for
dev setup, tests, and the PR process, and please follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately
per [SECURITY.md](SECURITY.md).

## License

Released under the [MIT License](LICENSE).
