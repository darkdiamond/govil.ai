# govil.ai — Landing pages for Israeli open data

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Nuxt 3](https://img.shields.io/badge/Nuxt-3-00DC82.svg)](https://nuxt.com/)

Each week the Israeli government publishes new datasets on
[data.gov.il](https://data.gov.il). This repo turns each dataset into a
polished Hebrew, right-to-left landing page with a summary and insights
computed from the data, real visualizations, and navigation that connects related datasets across
ministries and topics. The live site is [govil.ai](https://govil.ai).

**Docs:** [Architecture](docs/ARCHITECTURE.md) ·
[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) ·
[Code of Conduct](CODE_OF_CONDUCT.md) · [Conventions](CLAUDE.md)

## How it works

```
Cloud Scheduler (daily 06:00 Asia/Jerusalem)
        │
        ▼
Cloud Run job: govdata-builder-job (1 task, no LLM)
  pipeline.run_pipeline
    scan CKAN → Firestore sources/*            (scanner)
    load recipe list from git main (recipes/<id>/)
    refresh every recipe'd source CKAN moved past
        │  full CKAN export → compute.py in a sandboxed subprocess →
        │  Jinja template → sanitizer → check.py; failure keeps the
        │  last-good page
        ▼
    content.html → gs://<staging>/datasets/<id>/
    agent_data + refresh state → Firestore sources/<id>
    new/changed datasets without a recipe → one `needs-authoring` issue each
    ≥1 page re-rendered → dispatch GitHub Actions publish workflow
                   rsync GCS → publish.py (data.json, agent_data.json,
                   manifest.json from Firestore) → nuxt generate →
                   firebase deploy        (nothing re-rendered → no build)
    (the same workflow also runs on every push to main touching
     frontend/** — push-to-deploy, bursts collapse to one run)

Local Claude Code routine (daily 07:00 Asia/Jerusalem)
    /solve-authoring-issues: open needs-authoring issues → author a recipe
    per dataset (/author-dataset workflow) → review → ONE pull request
    → a human merges → the next daily job renders the new pages
```

A recipe is written once per dataset (`recipe.json` + a pure-pandas
`compute.py` + a Jinja `template.html.j2`); every number and insight
sentence is computed from the data, so the page re-renders unattended on
every upstream update. The Nuxt shell wraps each body with the shared
chrome (header, breadcrumb, metadata sidebar, related datasets, data
explorer, footer) at `nuxt generate` time. Nuxt also generates the home
and category pages (`/ministries/<slug>/`, `/tags/<slug>/`,
`/kinds/<kind>/`) from the manifest. Pages built by the earlier cloud
agent (retired 2026-10) stay live until a recipe replaces them.

## Layout

```
recipes/<id>/                  one recipe per dataset (the refresh list = git main)
services/
  scanner/                     CKAN scanner → Firestore sources/*
  page_builder/                daily pipeline + recipe refresh + publisher
    pipeline.py                  scan → refresh → authoring queue → publish trigger
    refresh.py                   deterministic recipe refresh (no LLM)
    recipe.py / recipe_exec.py   recipe contract + in-sandbox compute driver
    selector.py                  which sources need a recipe authored
    notify.py                    needs-authoring GitHub issues
    author.py                    local authoring kit (prepare / verify)
    agent_contract.py            CKAN fetch + output sanitizer + check.py gate
    local_sandbox.py             compute sandbox (subprocess, private workdir)
    podman_sandbox.py            shared sandbox result types (no longer a runtime sandbox)
    publish.py                   Firestore → data.json/agent_data.json/manifest.json
    related.py / embeddings.py   related-dataset scoring (Voyage optional)
    cli/preview.py               preview an authoring build in the prod shell
agent/
  system-prompt.md             design reference for authoring (retired agent prompt)
  skills/check.py              static page gate enforcing the hard rules
.claude/skills/
  author-dataset/              author one recipe (Claude Code skill)
  solve-authoring-issues/      daily batch over open needs-authoring issues
infra/
  builder-job.deploy.sh        Cloud Run job deploy (env: SCAN_LIMIT, REFRESH_PRECHECK, …)
  scheduler.setup.sh           Cloud Scheduler (0 6 * * *, Asia/Jerusalem)
  publish-local.sh             manual publish path (same steps as CI)
  DEPLOY.md                    full runbook
frontend/                      Nuxt 3 (shell + home + category pages)
```

## Quick start

Prereqs: Python 3.12, Node 22, and optionally a `VOYAGE_API_KEY` for
embedding-driven relatedness. Authoring a recipe uses
[Claude Code](https://claude.com/claude-code); refreshing one needs no
model at all.

```sh
# 1. Python env
python3 -m venv .venv && source .venv/bin/activate
pip install -r services/page_builder/requirements.txt

# 2. Scan into the Firestore emulator (needs a Java 8+ JRE on PATH)
gcloud emulators firestore start --host-port=localhost:8080 &
export FIRESTORE_EMULATOR_HOST=localhost:8080 FIRESTORE_PROJECT_ID=local-dev
python -m services.scanner.main scan --limit 20

# 3. Render one recipe'd dataset (no LLM; preview target, prod untouched)
export GCS_STAGING_BUCKET=<your-staging-bucket>
python -m services.page_builder.refresh run --source <dataset_id> --no-publish

# 4. Frontend (reads manifest.json at build time)
python -m services.page_builder.publish --from-firestore \
  --out frontend/public/
cd frontend && npm install && npm run generate
npx serve .output/public
```

## Runtime ingredients

- **Recipes** produce every page (`recipes/<id>/`), re-run by the daily
  job with no LLM — the run's cost is CKAN bandwidth and a few CPU
  minutes. Models run only at authoring time, locally, in Claude Code.
- **Voyage** (optional, `VOYAGE_ENABLED`) computes a 1024-dim embedding
  from title + summary + org + tags. Used by `related.py` to catch
  semantically-similar datasets that don't share a literal tag.
- **Firebase Hosting** serves everything. Nuxt-generated shell + home +
  category pages wrap the recipe-rendered bodies at generate time.
- **Cloud Run job** runs the daily builder (`--task-timeout` 6h bounds
  the run; each recipe's `compute()` is capped at 300s).

## Configuration / self-hosting

The defaults baked into the infra scripts (GCP project `govdata-il`,
staging bucket `govdata-il-staging`, region `me-west1`, publish target
`darkdiamond/govil.ai`) are **just defaults** — none are secrets. To run
your own instance, override them via environment variables. Copy
[`.env.example`](.env.example) to `.env` and set the ones you need:

| Variable                            | Purpose                                                      |
| ----------------------------------- | ------------------------------------------------------------ |
| `FIRESTORE_PROJECT_ID`              | Firestore project (or use `FIRESTORE_EMULATOR_HOST` locally) |
| `GCS_STAGING_BUCKET`                | Bucket each rendered `content.html` lands in                 |
| `FIREBASE_PROJECT`                  | Firebase Hosting / GCP project for deploys                   |
| `PUBLISH_GITHUB_REPO`               | `owner/repo` for publish dispatch, recipes and issues        |
| `GITHUB_DISPATCH_TOKEN`             | PAT: workflow dispatch + Issues:write + recipe reads         |
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

The site can be published two ways — both run identical steps (rsync page
bodies from GCS → rebuild `manifest.json` from Firestore → `nuxt generate`
→ `firebase deploy --only hosting`):

- **GitHub Actions** (default) — [`.github/workflows/publish.yml`](.github/workflows/publish.yml)
  runs on every push to `main` touching the frontend/publisher, and is
  dispatched by the daily builder job after any page re-rendered. Auth is
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

## Authoring a recipe

Recipes are authored locally with Claude Code — once per dataset:

```sh
# in Claude Code
/author-dataset <dataset_id>          # one dataset, end to end
/solve-authoring-issues               # the daily batch: open issues → one PR

# the host-side helpers the skill drives
python -m services.page_builder.author prepare <dataset_id>   # full data + BRIEF.md
python -m services.page_builder.author verify <dataset_id>    # run as the refresh will,
                                                              # + determinism/robustness
```

`verify` writes the rendered page to `tmp/model_test/<id>/` (gitignored;
the directory name is historical). Two ways to see it through the real
dataset shell:

```sh
# Offline — splices the body into a fetched copy of the live govil.ai
# page, strips Nuxt hydration so the splice survives, rewrites root-relative
# URLs to absolute. Open the printed file:// URL.
python -m services.page_builder.cli.preview render <id>

# Full Nuxt-shell — backs up frontend/public/datasets/<id>/{content.html,
# agent_data.json}, drops the build in their place, then `npm run dev`
# serves it at localhost:3000. Restores the prod files when you're done.
python -m services.page_builder.cli.preview swap <id>
cd frontend && npm run dev
# http://localhost:3000/datasets/<id>  vs  https://govil.ai/datasets/<id>
python -m services.page_builder.cli.preview restore <id>

python -m services.page_builder.cli.preview status   # what's swapped right now
```

`tmp/` holds raw dataset rows (which can include personal contact
details) and is never committed; only `recipes/<id>/` is.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for
dev setup, tests, and the PR process, and please follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Report security issues privately
per [SECURITY.md](SECURITY.md).

## License

Released under the [MIT License](LICENSE).
