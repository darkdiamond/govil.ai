# CLAUDE.md — repository conventions for Claude Code sessions

This file is loaded automatically. Read it before touching code.

## What this project is

A pipeline that turns data.gov.il datasets into connected, Hebrew-RTL
landing pages. Four layers:

1. **Scanner** — `services/scanner/`. Polls CKAN, upserts per-source
   state into **Firestore** (`sources/*`). Runs inside the builder
   container; also usable as a local CLI for debugging.
2. **Builder** — `services/page_builder/`. **Cloud Run job**
   (`govdata-builder-job`), executed by Cloud Scheduler **daily at 07:00
   Asia/Jerusalem** via the Admin API's `:run` method:
   - `pipeline.run_pipeline` drives scan → reap orphaned `pending` →
     select every never-analyzed (or retryable-failed) source up to
     `DAILY_CAP` → concurrent agent sessions (`asyncio.gather` +
     `Semaphore(MAX_CONCURRENT)`) → mark Firestore → trigger the
     publisher. **No new datasets → no build** (`status: idle`, publish
     trigger skipped).
   - **A job, not a service, because the batch outgrew the 3600s request
     timeout.** From 2026-08-01 every scheduler tick 504'd at exactly
     3600.000s. Since the publish dispatch is the last step of
     `run_pipeline` (after `gather` over all sources), whether the site
     updated became a race between the batch finishing and Cloud Run
     reaping the container — lost 5 days straight, so 11 pages sat built,
     staged and marked `succeeded` while the site stayed frozen. A job
     execution has no request semantics: `--task-timeout` (6h) is the
     only bound. `infra/builder-job.deploy.sh`.
   - The `govdata-builder` **service still exists** for manual
     single-dataset invokes (`{"dataset_id": "..."}`) and as instant
     rollback: `TARGET=service ./infra/scheduler.setup.sh`. Its env must
     be kept in lockstep with the job's — both scripts use
     `--set-env-vars`, which replaces the whole set.
   - One container, one task (`--tasks=1 --parallelism=1
     --max-retries=0`). Per-source parallelism lives inside that
     container, never Cloud Run autoscaling. `--max-retries=0` is
     deliberate: a retried batch would re-bill sessions that already
     succeeded.
3. **Agent runtime** — PydanticAI agent loop
   (`services/page_builder/model_harness.py::run_agent_session`)
   calling **OpenRouter** (`OPENROUTER_MODEL`, default
   `tencent/hy3`). Tools: bash + code_execution (subprocess in a
   private per-session workdir via `local_sandbox.LocalSandbox`),
   web_fetch (httpx), web_search (DDG). System prompt:
   `agent/system-prompt.md` (canonical, hand-edited). Host-side
   prefetch (`agent_contract.prefetch_dataset`, once per source):
   every datastore-active resource (format twins deduped;
   **all resources by default** — `DATA_PREFETCH_MULTI=true` is now the
   code default so multi-file datasets get every file; set it `false`
   to restrict to the primary) is streamed into
   the session workdir as CSV — full up to
   `DATA_PREFETCH_MAX_RECORDS`/`_MAX_BYTES` (per-dataset
   `_TOTAL_BYTES` budget), deterministic strided sample above them
   (`DATA_PREFETCH_SAMPLE_ROWS`; 0 = legacy all-or-nothing skip) —
   and advertised via a `pre_fetched_files` manifest in the user
   message; the prompt is pandas-first on those files, CKAN API as
   fallback/spot-check only. Each session self-validates before
   anything persists: AgentData schema → sanitizer → host-side
   `agent/skills/check.py` exit 0, with `SESSION_ATTEMPTS` (3)
   in-run retries on fresh workdirs
   (`agent_runner.run_production_session`); `RETRY_FEEDBACK=true`
   feeds a validation failure's diagnostic into the next attempt's
   user message (API flakes stay hintless). Outputs: `content.html`
   → GCS staging, `agent_data` + usage/cost telemetry → Firestore.
4. **Publisher** — GitHub Actions workflow
   `.github/workflows/publish.yml` ($0 — free-tier minutes; keyless GCP
   auth via WIF, `infra/github-ci.setup.sh`). Fired two ways: the
   builder's `workflow_dispatch` after ≥1 page succeeded
   (`PUBLISH_VIA=github` + `github-dispatch-token` secret), and
   **push-to-deploy** — any push to main touching `frontend/**` or the
   publisher code auto-deploys, with rapid pushes collapsing to one run
   (`concurrency: cancel-in-progress`). Steps: rsync staged pages from
   GCS (delta via actions/cache) → regenerate artifacts + manifest from
   Firestore → `nuxt generate` → `firebase deploy`. Fallbacks: Cloud
   Build trigger `govdata-publish` (`PUBLISH_VIA=cloudbuild`) and
   `infra/publish-local.sh` (same steps, your machine).

State: Firestore `sources/{id}` (per-dataset), `scan_runs/{run_id}`
(per invocation). No SQLite. No Anthropic Managed
Agents (migrated to OpenRouter 2026-06-12; sources that fail a whole
run auto-retry on subsequent days via `failed_attempts`, parked at 3).

## Critical conventions

- **Hebrew-first, RTL everywhere.** `<html dir="rtl" lang="he">`. Body
  line-height `1.5` (gov.il standard). Tailwind logical properties
  (`ps-*`/`pe-*`) when using Tailwind.
- **Model**: `OPENROUTER_MODEL` env on the builder (code default
  `tencent/hy3`; **prod runs the paid `tencent/hy3` at
  `OPENROUTER_REASONING_EFFORT=max` since 2026-07-21** — moved off the
  `tencent/hy3:free` tier when OpenRouter discontinued it; the model was
  validated over a 477-session backlog drain on the free tier before the
  switch; MiniMax (`minimax/minimax-m3`) remains an available fallback,
  one redeploy away). Legacy free-tier caveats (from the `:free` era):
  upstream congestion waves drove `RATE_LIMIT_BACKOFF_S` between-attempt
  backoff and `MAX_CONCURRENT=2` (not 8) — both may be revisited now that
  prod is on the paid tier. Do not change the production model without
  asking.
  Candidate models are evaluated first through the local harness
  (`cli/model_test.py`) per `docs/MODEL_EVAL.md` — comparison snapshots
  live in `services/page_builder/harness-comparison/`, which is
  **local-only and gitignored** (agent output embeds raw dataset content,
  incl. personal contact details). Includes numeric validation of chart
  data vs CKAN (MiniMax once fabricated a chart; the prompt's CHART-DATA
  PROVENANCE rule + that validation are the guard).
- **Design tokens** (aligned with www.gov.il — mirrored across
  `frontend/tailwind.config.ts`,
  `services/page_builder/templates/dataset_page.html.j2`, and
  `agent/system-prompt.md`):
  primary `#0068f5` (hover `#0053c4`), ink `#0c3058`, ink-deep `#0b3668`,
  surface `#f1f7ff`, surface-alt `#f0f4fa`, rule `#c3cfe7`, subtle
  `#6c757d`. Semantic: ok `#198754`, warn `#ffc107`, danger `#dc3545`,
  info `#0dcaf0`. Header gradient `#025fdb → #0b3668`. Font: **Rubik
  only** (no Heebo). Radii: `rounded-gov` = 0.5rem (cards/buttons),
  `rounded-gov-sm` = 0.2rem (badges), `rounded-gov-pill` = 50rem
  (chips). Container `max-w-gov` = 1400px. Icons: Lucide SVGs committed
  to `frontend/public/icons/`.
- **Pre-loaded dataset-page globals** (head scripts; see
  `frontend/utils/dataset-libs.ts` and `awaitDatasetLibs()` in
  `frontend/pages/datasets/[id].vue`): `echarts`, `L`,
  `L.markerClusterGroup`, and `GovExplorer` (in-house;
  `frontend/public/lib/gov-explorer.js`). Agent bodies use them as
  globals and must NOT include `<script src=>` for any of them.
- **Agent outputs** are a contract (written to the per-session
  OUTPUTS_DIR the user message provides — see
  `services/page_builder/agent_contract.py`):
  - `content.html` — body content only. No
    `<html>`/`<head>`/`<body>`. Inline `<style>` and `<script>` tags OK.
  - `agent_data.json` — an `AgentData`
    (`services/page_builder/schema.py`). Holds ONLY interpretive fields
    (`summary_he`, `dataset_kind`, optional `related_ids`). Scanner
    facts (id, title, slug, license, resources, formats, record_count,
    metadata_modified) are not the agent's responsibility — `data.json`
    is owned by the publisher and rebuilt from Firestore.
- **Source of truth** for everything the frontend renders is the
  Firestore `sources/<id>` document. Two writers feed it:
  scanner (CKAN facts: title, slug, license, resources, record_count,
  formats, organization, metadata_modified) and builder (agent's
  `agent_data` field). On every deploy, `services.page_builder.publish`
  rematerializes from that single doc:
    `frontend/public/data/manifest.json`        — merged ManifestEntry list
    `frontend/public/datasets/<id>/data.json`   — DatasetMeta (scanner)
    `frontend/public/datasets/<id>/agent_data.json` — AgentData (agent)
  GCS staging carries only `content.html`. Don't reintroduce a path that
  rsyncs `data.json` from GCS — single writer per file is the whole point.
- **Selection priority** (`services/page_builder/selector.py`):
  Both tracks are gated by an effective cutoff =
  `max(min_modified_floor, now - max_age_days)`. A source is only
  eligible if its CKAN `metadata_modified` is on/after that cutoff. Both
  bounds are **env-overridable** (the pipeline reads `MIN_MODIFIED_FLOOR`
  (ISO date) and `MAX_AGE_DAYS` and passes them to `pick_next`); code
  defaults when unset are `min_modified_floor = 2026-01-01 UTC`,
  `max_age_days = 365`. We're expanding coverage backward one year at a
  time: **prod currently runs `MIN_MODIFIED_FLOOR=2025-01-01` with
  `MAX_AGE_DAYS` set large enough to disable the rolling window**, so the
  floor is the sole gate (otherwise `now - 365d` would clip early-2025).
  `SCAN_LIMIT` (default 800) must stay ≥ the count of datasets at/after
  the floor so the scanner actually ingests them — bump it in lockstep
  when the floor drops to admit an older year. gov.il still has ~660
  pre-2025 archival/abandoned datasets we're deliberately leaving out for
  now.
  1. `analysis_status == "never"` AND `metadata_modified >= cutoff` —
     ordered by `metadata_modified` DESC. Then (Track 1b) failed
     sources with `failed_attempts < 3` — transient failures self-heal
     on later daily runs; 3 whole-run failures park the source.
  2. `change_status in {new, updated}` AND `metadata_modified >= cutoff`
     AND CKAN advanced past our build (`metadata_modified >
     analyzed_metadata_modified`) AND the new version is more than
     `REANALYZE_GAP_DAYS` past the version we built from:
     `metadata_modified - analyzed_metadata_modified > gap` (legacy null
     marker falls back to `last_analyzed_at`; both null = eligible) —
     ordered by `metadata_modified` DESC.
  The (recent) never-analyzed backlog is drained first; re-analysis of
  already-published pages waits until every recent source has at least
  one page. The gap gate (replaced the now-based COOLDOWN_DAYS on
  2026-07-15) applies only to Track 2 and is measured against the DATA
  VERSION, not the run time: a page built today from January data
  refreshes as soon as any newer version lands (months-long version
  jump), while daily-append datasets self-limit to ~one rebuild per gap
  period since each rebuild resets `analyzed_metadata_modified` to that
  day's version. **Prod: Track 2 is ON
  (`REANALYZE_ENABLED=true`) with `REANALYZE_GAP_DAYS=30`.** Both are
  env-overridable (pipeline reads them; code defaults `reanalyze=true`,
  `DEFAULT_REANALYZE_GAP_DAYS=30`).
- **Related-datasets scoring** (deterministic, content-first):
  `1.5·same_ministry + 2·min(shared_tag_count, 6) + 8·cosine(embedding) + 6·agent_suggested`.
  Embedding similarity dominates; same-ministry is a tiebreaker only.
  Top 5 per page. Defined in `services/page_builder/related.py`.

## Key files to read before editing

| Area | File | Why |
|------|------|-----|
| Pipeline orchestration | `services/page_builder/pipeline.py` | scan → select → asyncio.gather → mark → trigger publish |
| Source selection | `services/page_builder/selector.py` | Cooldown + priority query |
| Firestore layer | `services/shared/firestore.py` | `FirestoreStateStore`, schema, queries |
| Production session runner | `services/page_builder/agent_runner.py` | Attempt loop (SESSION_ATTEMPTS) → validate (schema + sanitizer + check.py) → upload content.html to GCS + agent_data/usage to Firestore |
| Agent loop (shared) | `services/page_builder/model_harness.py` | PydanticAI agent + tools + OpenRouter routing + actual-cost extraction; `run_agent_session` used by prod and the test CLI |
| Agent I/O contract | `services/page_builder/agent_contract.py` | build_user_message (OUTPUTS_DIR/CHECK_SCRIPT), CKAN prefetch, output sanitizer |
| Prod sandbox | `services/page_builder/local_sandbox.py` | Per-session subprocess workdir, scrubbed env, command timeouts |
| Publisher | `services/page_builder/publish.py` | Reads each succeeded `sources/<id>` and writes data.json, agent_data.json, manifest.json (single source of truth) |
| Agent behavior | `agent/system-prompt.md` | Canonical system prompt — design tokens, output contract, chart palette, data-fetching rules (incl. CHART-DATA PROVENANCE, no-spline, distinct-cap traps), RTL snippets, mobile rules. Hand-edit directly; ships in the builder image; byte-identical across sessions so providers serve it from prefix cache. |
| Self-check | `agent/skills/check.py` | Enforces prompt rules statically; runs in-session (agent) AND host-side (agent_runner) on the sanitized body |
| Dataset page shell | `frontend/pages/datasets/[id].vue` | Reads data.json + agent_data.json + content.html, merges into one entry, wraps in default layout |
| Page chrome | `frontend/layouts/default.vue` | Header/footer — sole source of truth, inherited by every page including datasets |
| Schema | `services/page_builder/schema.py` | `DatasetMeta` (scanner) + `AgentData` (agent) + merged `ManifestEntry` — split contract |
| Slug helper | `services/shared/slug.py` | Deterministic Hebrew→Latin slug used by the scanner |
| Cloud Build pipeline | `cloudbuild-publish.yaml` | rsync content.html only → run publisher (writes data.json + agent_data.json + manifest.json from Firestore) → `nuxt generate` → Firebase deploy |
| Hosting config | `firebase.json`, `.firebaserc` | Firebase Hosting target + project binding |

## Conventions you will be tempted to violate (don't)

- **Don't restore SQLite or add a fallback store.** Firestore is the
  only state store. `FIRESTORE_EMULATOR_HOST` for local/test is fine.
- **Don't autoscale the builder.** `--tasks=1 --parallelism=1` on the job
  is deliberate. Parallelism across sources lives in `asyncio.gather`
  inside the single container. If N_PER_RUN grows past ~20, bump
  `--memory` on that one container, not task count.
- **Don't move the daily batch back onto the HTTP service.** A Cloud Run
  service caps request timeout at 3600s and the batch outgrew it (see
  layer 2 above). The service is for single-dataset invokes and rollback.
- **Don't `--source=.` deploy without checking `.gcloudignore`.** It is
  what keeps the upload at ~18MB instead of 1.8GB, and it is the only
  thing (alongside `.dockerignore`) keeping
  `services/page_builder/harness-comparison/` — gitignored, PII-bearing
  model-eval output — out of the builder image. The two filters do
  different jobs: `.gcloudignore` gates the UPLOAD, `.dockerignore` gates
  the IMAGE. Anything the Dockerfile COPYs must survive both.
- **Don't add mock analyzers or silent model fallbacks.** Production
  uses one model (`OPENROUTER_MODEL`); every page is produced by a real
  agent session that passed self-validation. (OpenRouter-level provider
  failover for the SAME model is fine.)
- **Don't resurrect the viz taxonomy.** The agent picks libraries per
  dataset. Any code that hardcodes `VizType` / `VizSpec` is obsolete.
- **Agent output is body-only.** The agent writes `content.html` (no
  `<html>/<head>/<body>/<header>/<footer>`) and `agent_data.json`
  (interpretive fields only). `content.html` is staged to GCS and
  rsynced into `frontend/public/datasets/<id>/`; `agent_data.json` is
  not — its content goes through Firestore (`sources/<id>.agent_data`)
  and the publisher writes the per-dataset `agent_data.json` from there.
  `frontend/pages/datasets/[id].vue` reads all three artifacts at
  `nuxt generate` time and wraps them in the default layout via
  `v-html`. In SSG the `<script>` tags inside the body land in the
  static HTML and execute on browser load before Vue hydrates, so
  ECharts/Leaflet still work. **Don't restore a Jinja wrapper** or
  hand-roll chrome in agent output — `layouts/default.vue` is the
  single source of truth.
- **Don't reintroduce GCS-as-data.json.** Per-dataset `data.json` and
  `agent_data.json` are *only* written by `services.page_builder.publish`
  from Firestore. If they show up in `gs://<staging>/datasets/<id>/`,
  the rsync step in `cloudbuild-publish.yaml` deletes them after sync —
  by design, so the two-writer drift class can't recur.
- **Resource URLs use `data.gov.il` (no `e.`).** CKAN publishes resource
  URLs on `e.data.gov.il`, which sits behind Google IAP and redirects
  anonymous visitors to an OAuth consent screen. The scanner normalizes
  on ingest (`services/scanner/models.py::_public_resource_url`), the
  agent's HARD CONSTRAINTS + self-check enforce it on output, and the
  Nuxt route regex-rewrites the body as a final belt. Don't skip any of
  those layers — defense in depth.
- **Don't add a session wall-clock timeout.** The agent loop runs until
  the model goes idle; per-tool-command timeouts (120s in LocalSandbox)
  and the Cloud Run timeout (3600s for the whole daily batch) are the
  only bounds.
- **Firebase Hosting is the sole deploy target; GCS is staging only.**
  Don't deploy pages to Cloudflare Pages or serve them from GCS-as-CDN.
  Note: the `govil.ai` domain is proxied through **Cloudflare** (DNS/CDN) in
  front of the Firebase origin — live responses carry `cf-nel` / `x-cache`,
  and HTML is edge-cached `s-maxage=3600`. To debug origin vs. edge, hit the
  Firebase origin directly at `https://govdata-il.web.app/…` (bypasses the
  Cloudflare cache). Keep Cloudflare's Scrape Shield → **Email Address
  Obfuscation OFF**: with it on, Cloudflare rewrites plain-text emails in the
  clean origin HTML into `/cdn-cgi/l/email-protection` links that 404 on this
  zone — it broke every dataset-page contact email until disabled 2026-07-20.
  The agent-output sanitizer + `check.py` also strip `/cdn-cgi/` defensively
  (an agent can copy that markup from a Cloudflare-fronted gov.il page it
  fetches), but that guards the corpus, not this edge behaviour.
- **Sandbox boundary (accepted risk, know it before touching it):** the
  agent's bash/python tools run as subprocesses in the builder container
  (Cloud Run can't nest containers). Tool processes get a scrubbed env
  (no key vars), private workdirs, and 120s timeouts — but they CAN
  reach the GCP metadata server, i.e. the builder SA token. Keep that SA
  minimal (Firestore + staging bucket + publish-trigger only) and never
  widen its roles for convenience. The local test harness keeps the
  stronger Podman isolation.

## Gotchas + open issues

- **Hebrew tag URLs need `experimental.payloadExtraction: false`**.
  Tag URLs are Hebrew (`/tags/אבטחה/`, `/tags/אגף-תכנון/` for multi-word
  tags); the publisher's `tag_slugs` map normalizes whitespace +
  URL-reserved chars to `-` and keeps the Hebrew letters. The
  `payloadExtraction: false` flag in `frontend/nuxt.config.ts` is
  load-bearing: with it on, Nuxt 3.21's renderer puts the raw decoded
  URL into an `x-nitro-prerender` HTTP header to hint payload
  prerender, and HTTP header values are Latin-1 only — any Hebrew
  character throws `Cannot convert argument to a ByteString` and the
  whole route returns 500. Don't re-enable payload extraction without a
  Nuxt fix.
- **Voyage embeddings are gated by `VOYAGE_ENABLED` (default off).**
  Currently disabled for cost. The secret binding (`VOYAGE_API_KEY`
  from Secret Manager) and call sites stay wired so re-enabling is a
  one-line toggle: `gcloud run services update govdata-builder
  --region=me-west1 --update-env-vars=VOYAGE_ENABLED=true`. While off,
  `embed()` short-circuits to `None` and `related.py` falls back to
  ministry + shared-tag (CKAN ∪ agent `suggested_tags`) + agent-suggested
  scoring. Existing embeddings already cached on `sources/<id>.embedding`
  keep contributing for those docs at zero new cost. Model defaults to
  `voyage-4` (1024-dim), overridable via `VOYAGE_MODEL`. To retro-fill
  embeddings on already-published sources (requires re-enable), run
  `python -m services.page_builder.backfill_embeddings`.
- **Cloud Build trigger connection** is a manual step in `bootstrap.sh`.
  Cloud Build can't check out arbitrary filesystems — it needs either a
  GitHub 2nd-gen connection or a Cloud Source Repositories mirror.
  `infra/bootstrap.sh` prints the exact `gcloud builds triggers create
  manual` command after the connection exists.
- **MiniMax M3 API flakes** (~1 in 3 sessions historically): malformed
  tool-call JSON (400 on history replay) and `finish_reason: "error"`
  (HTTP 200, server-side generation error). Both are absorbed by
  `SESSION_ATTEMPTS` in-run retries + the daily `failed_attempts`
  retry; if a model's flake rate grows, switch `OPENROUTER_MODEL` or
  add `openrouter_models` fallback routing in `model_harness`.

## Running things locally

```sh
source .venv/bin/activate

# Firestore emulator (so nothing hits prod)
gcloud emulators firestore start --host-port=localhost:8080 &
export FIRESTORE_EMULATOR_HOST=localhost:8080 FIRESTORE_PROJECT_ID=local-dev

# Seed a few sources via the scanner CLI
python -m services.scanner.main scan --limit 5

# Check selector output (no agent run)
python -m services.page_builder.pipeline --dry-run

# Full pipeline for a specific dataset (requires OPENROUTER_API_KEY + GCS_STAGING_BUCKET)
python -m services.page_builder.pipeline --source <dataset_id> --no-trigger-publish

# Rebuild publisher artifacts (manifest.json + per-dataset json) from the emulator
python -m services.page_builder.publish --from-firestore \
  --out frontend/public/

# Frontend
cd frontend && npm run generate && npx serve .output/public
```

## Publishing

Automatic, two paths into one GitHub Actions workflow (free tier):
the daily builder run dispatches it after any successful analysis
(no new pages → no dispatch), and pushing frontend/publisher changes
to main deploys them (bursts collapse to one run). For
manual/emergency deploys from your machine:

```sh
source .venv/bin/activate            # publish.py must be importable
./infra/publish-local.sh            # sync GCS → Firestore artifacts → nuxt generate → firebase deploy
./infra/publish-local.sh --serve    # same build, preview at localhost:3000 instead of deploying
./infra/publish-local.sh --dry-run  # build everything, skip deploy
```

Needs `gcloud auth application-default login` + `firebase login` once.

For cloud smoke + deploy, see `infra/DEPLOY.md`.
