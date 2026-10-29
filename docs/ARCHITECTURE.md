# Architecture

This document explains how govil.ai turns raw
[data.gov.il](https://data.gov.il) datasets into connected, Hebrew-RTL
landing pages. For repository conventions and the detailed
"do / don't" rules, see [`CLAUDE.md`](../CLAUDE.md).

## The big picture

```
Cloud Scheduler (daily 06:00 Asia/Jerusalem)
        │
        ▼
Cloud Run job: govdata-builder-job  (1 task, no LLM)
        │
        ├─ 1. Scanner   — poll CKAN, upsert sources/* into Firestore
        ├─ 2. Refresh   — re-run every recipe whose dataset CKAN moved past
        │        content.html → GCS staging
        │        agent_data + refresh state → Firestore sources/<id>
        ├─ 3. Authoring queue — one `needs-authoring` GitHub issue per new
        │        or changed dataset that has no recipe yet
        │
        └─ ≥1 page re-rendered → dispatch the GitHub Actions publish workflow
                            │
                            ▼
                  4. Publisher — rebuild artifacts from Firestore,
                     nuxt generate, firebase deploy

Local Claude Code routine (daily 07:00 Asia/Jerusalem)
        └─ /solve-authoring-issues — author recipes for open issues,
           open ONE pull request; a human merges; the next job renders them
```

The whole system is built around **deterministic recipes** producing
every page and **one Firestore document per dataset** holding the truth.
No model runs in production: models are used once per dataset, locally,
to write the recipe. The job is a single Cloud Run task that refreshes
recipes sequentially, never Cloud Run autoscaling.

## The layers

### 1. Scanner (`services/scanner/`)

Polls the CKAN API on data.gov.il and upserts per-dataset state into
Firestore under `sources/{id}`. It owns the **factual** fields: title,
slug, license, resources, formats, record count, organization, and
`metadata_modified`. It also normalizes resource URLs from
`e.data.gov.il` (which sits behind Google IAP) to the public
`data.gov.il` host. Runs inside the builder container and is also usable
as a standalone CLI for debugging.

### 2. Builder / pipeline (`services/page_builder/pipeline.py`)

The orchestrator, run daily as a Cloud Run job:

1. **Reconcile** (weekly) and **scan** CKAN into Firestore.
2. **Load the recipe list** from git `main` (`recipes/<id>/`). If it
   can't be read, the run fails loudly — nothing is refreshed or queued.
3. **Refresh** every recipe'd source whose CKAN version (or recipe
   version) moved past what was last rendered (`refresh.py`, below).
4. **Queue authoring** for sources without a recipe (`selector.py` +
   `notify.py`, below).
5. **Trigger** the publisher if at least one page re-rendered.

Nothing re-rendered means no build — the run goes idle and skips the
publish trigger.

### 3. Recipe refresh (`services/page_builder/refresh.py`)

A recipe is three files in `recipes/<id>/`: `recipe.json` (inputs and
version), a pure-pandas `compute.py` that turns the full CKAN data into a
page model, and a Jinja `template.html.j2` that carries only layout and
fixed copy. Every number, chart series and insight sentence is computed.
A refresh runs, with no LLM: full CKAN export → `compute()` in a
sandboxed subprocess (unprivileged user, scrubbed env, timeout) → page
model validation → template render → sanitizer → `agent/skills/check.py`
(exit 0 required). Successful output is:

- `content.html` (body content only) → uploaded to GCS staging
- `agent_data` + refresh state → written to `sources/<id>`

A failure keeps the last-good page live and, when a human has to act,
opens a `needs-authoring` issue. A precheck (`REFRESH_PRECHECK`) skips
CKAN version bumps whose data didn't actually change.

### 4. Authoring (local, Claude Code)

`selector.pick_authoring_candidates` lists sources that need a recipe:
**new** datasets with no page, and **legacy** pages (built by the
retired cloud agent) whose data has moved on. Each gets one
`needs-authoring` GitHub issue; a recorded issue is never re-opened
while it is open or was closed as not planned.

A daily local Claude Code routine runs `/solve-authoring-issues`: it
works through the open issues (trusting only the dataset id in each),
authors each recipe with the `/author-dataset` workflow
(`services/page_builder/author.py prepare|verify`; design rules from
`agent/system-prompt.md`), reviews the batch, and opens one pull request
that closes the issues. Once a human merges it, the next daily job
renders the pages.

### 5. Publisher (`.github/workflows/publish.yml`)

A GitHub Actions workflow (free-tier minutes, keyless GCP auth via
Workload Identity Federation). It runs on two triggers:

- the builder dispatches it after ≥1 page re-rendered, and
- any push to `main` touching `frontend/**` or the publisher code
  (push-to-deploy; rapid pushes collapse to a single run).

Its steps: rsync staged `content.html` from GCS → rematerialize all
artifacts from Firestore (`publish.py`) → `nuxt generate` →
`firebase deploy`. Fallback paths exist via Cloud Build and a local
script (`infra/publish-local.sh`).

## Data model: one document, two writers

The source of truth for everything the frontend renders is the Firestore
`sources/<id>` document. Exactly **two writers** feed it:

- the **scanner** writes CKAN facts, and
- the **builder** writes the recipe's interpretive `agent_data` (legacy
  pages keep the retired agent's).

On every deploy, `services/page_builder/publish.py` rematerializes the
frontend artifacts from that single document:

| Artifact                                        | Owner                          | Contents                    |
| ----------------------------------------------- | ------------------------------ | --------------------------- |
| `frontend/public/data/manifest.json`            | publisher                      | merged list of all datasets |
| `frontend/public/datasets/<id>/data.json`       | publisher (from scanner facts) | `DatasetMeta`               |
| `frontend/public/datasets/<id>/agent_data.json` | publisher (from recipe fields) | `AgentData`                 |

GCS staging carries only `content.html`. Keeping a single writer per
file is deliberate — it prevents the two-writer drift class of bugs. The
schemas live in `services/page_builder/schema.py`.

## The page output contract

Every recipe render produces exactly two things:

- **`content.html`** — body content only (no `<html>`/`<head>`/`<body>`;
  inline `<style>`/`<script>` allowed). The Nuxt shell
  (`frontend/layouts/default.vue` + `pages/datasets/[slug].vue`) wraps it
  with shared chrome at generate time. Pre-loaded globals (ECharts,
  Leaflet, an in-house `GovExplorer`) mean the body must _not_ include
  `<script src=>` for them.
- **`agent_data`** — interpretive fields only (`summary_he`,
  `dataset_kind`, optional `related_ids`). Factual fields are the
  scanner's job, not the recipe's. (The name predates recipes.)

A key guardrail is **chart-data provenance**: every chart's numbers are
computed by `compute.py` from the full CKAN data, and `author verify`
proves it — re-running on a truncated copy must change the numbers, and
re-running on shuffled rows must not.

## Selection and relatedness

**Authoring selection** (`selector.py`) queues new datasets first, then
legacy pages whose data moved on, newest CKAN change first. Both are
gated by an effective recency cutoff (`MIN_MODIFIED_FLOOR` /
`MAX_AGE_DAYS`) so long-abandoned datasets don't get queued.

**Related datasets** (`related.py`) are scored deterministically,
content first:

```
1.5·same_ministry + 2·min(shared_tags, 6) + 8·cosine(embedding) + 6·agent_suggested
```

Embedding similarity (optional, via Voyage) dominates; same-ministry is
a tiebreaker. Top 5 per page. When embeddings are disabled, the score
falls back to ministry + shared-tag + agent-suggested signals.

## Tech stack

| Layer                         | Stack                                                             |
| ----------------------------- | ----------------------------------------------------------------- |
| Scanner / builder / publisher | Python 3.12, google-cloud-firestore, pandas, Jinja2               |
| Authoring                     | Claude Code (local only), `.claude/skills/`                       |
| Frontend                      | Nuxt 3 (SSG), Vue 3, TypeScript, Tailwind, ECharts, Leaflet       |
| State                         | Firestore (`sources/{id}`, `scan_runs/{run_id}`)                  |
| Hosting                       | Firebase Hosting (GCS is internal staging only)                   |
| Compute                       | Cloud Run job (builder), GitHub Actions / Cloud Build (publisher) |
