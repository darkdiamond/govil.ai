---
name: author-dataset
description: Author (or re-author) the deterministic recipe for one data.gov.il dataset — explore the full data, design a rich Hebrew-RTL page, and write recipes/<id>/{recipe.json,compute.py,template.html.j2} that the nightly job re-runs with no LLM on every data update. Use when given a dataset id or a `needs-authoring` GitHub issue.
---

# /author-dataset `<dataset_id>` [issue #N]

You are writing a program, not a page. The page you design will be re-rendered
by `services/page_builder/refresh.py` every time CKAN publishes a new version of
this dataset — for months, unattended, with no model in the loop. Every
number, chart series and insight sentence must therefore be **computed from the
data** by `compute.py`; the template carries only layout and fixed copy.

This is the one time a strong model looks at this dataset. Spend it: profile
every file, find the real story, and build a deep page — more and richer views
than the old cloud agent produced (see "Ambition" below). Then make it robust.

## 0. Setup

- Work on a branch: `git switch -c recipe/<id8>` (from up-to-date `main`).
- `source .venv/bin/activate` (from the main checkout if in a worktree).
- Firestore read access (ADC) is needed for `prepare` only.

## 1. Prepare

```bash
python -m services.page_builder.author prepare <dataset_id>
```

Fetches every datastore resource IN FULL into `tmp/authoring/<id>/data/` and
writes `tmp/authoring/<id>/BRIEF.md` (facts, columns, samples, the current
page's agent_data, same-ministry `related_ids` candidates). Read the brief. If
the dataset has a live page (`https://govil.ai/datasets/<slug>`), look at it —
it's the floor, not the ceiling.

`tmp/authoring/` holds raw rows; it is gitignored — never commit it or paste
raw rows into a recipe.

**Naming people on the page.** The data is public, and every row (names
included) is already in the shell's explorer under the page. What the page
itself writes is search-indexed and regenerated unattended, so:

- **Name freely** people in a public, professional or commercial capacity
  when it adds something — officials, directors, office holders, licensed
  professionals (brokers, appraisers, accountants, notaries, attorneys),
  arbitrators/decision-makers, inventors and applicants on public filings,
  sole traders and businesses (incl. ones named after their owner). Top-N
  rankings and "who leads" insights are fine.
- **Never put on the page** lookup/tracking identifiers (licence plates,
  personal ID numbers, an individual's registration number), private
  contact details (home address, private phone/email), or a person tied to
  sensitive circumstances (health/disability, custody/detention,
  personal-status cases, victims) — aggregate those.
- Otherwise use judgment: be open when naming informs, aggregate when it
  only exposes.

## 2. Explore

Write scratch scripts in `tmp/authoring/<id>/` and run them with pandas
(`dtype=str, keep_default_na=False` — the same frames `compute()` will get).
Profile every file: column semantics, units, cardinalities, date span and
granularity, null/garbage values, duplicate rows, how the files relate (one
table split per year? a lookup table? different tables?). Find what is
genuinely interesting: trends, seasonality, concentration, outliers, regional
contrasts, breaks in series, before/after events.

Also ask: **how will this data grow?** Daily appends, a new yearly file, revised
history? New categories appearing? The recipe must keep producing a correct,
under-cap page as it does.

## 3. Design the page

Design rules are the cloud agent's rules — read these sections of
`agent/system-prompt.md` and follow them: WRAPPER CONTRACT, DESIGN TOKENS,
CHART COLOR PALETTE, ECHARTS: RTL + Rubik preset, MOBILE-FIRST LAYOUT, LIVE MAP
(GovMap), DATA EXPLORER (don't build one), BODY SKELETON, STRUCTURE,
DATA-TABLE FALLBACK, COLOR AND CONTRAST, REDUCED MOTION, and HARD CONSTRAINTS.
Ignore everything about OUTPUTS_DIR, CHECK_SCRIPT, curl/CKAN fetching and the
agent WORKFLOW — that machinery is replaced by this skill. The reference
example of a working recipe is
`services/page_builder/tests/fixtures/recipes/11111111-2222-3333-4444-555555555555/`.

### Ambition

You are a much stronger analyst than the model that wrote most current pages,
and the cost is paid once. Go deeper:

- 5–10 chart sections where the data supports it (don't pad thin data — a
  registry with two useful columns gets two honest charts).
- Use the right form, not the default bar: small multiples per region/category,
  calendar or month×year heatmaps for seasonality, stacked/100% area for mix
  shifts, dual views (absolute + per-capita/share), slope or dumbbell charts
  for before/after, treemap/sunburst for hierarchies, boxplot/percentile bands
  for distributions, scatter for relationships, GovMap for point sets.
- A short computed lede per chart section (what to notice, with numbers).
- 4–8 insights across the page, each a real finding with numbers.
- Interactivity ECharts gives for free (dataZoom on long series, legend
  toggles, tooltips with units) — no custom JS frameworks, no network calls.

**Depth bar — coverage, not a chart quota.** Before designing, list every
column of every input and the questions it can answer alone and in
combination (by time, by place, by category, distribution, cross-tab,
concentration, change). A page that stops at 5–6 safe charts while
dimensions sit unused is too thin. Every column ends up in
`recipes/<id>/coverage.json` — mapped to the chart id(s) / `kpi:` /
`insight:` / `table:` / `map:` that use it, or to `skip: <reason>`
(identifier, free text, constant, >80% empty, sensitive personal data, …).
`verify` fails on an unaccounted column. Value format:
`"chart-a, kpi:total, insight:trend — optional free note"` (references
first, comma-separated; anything after `—` is a note and may contain
commas and numbers), or `"skip: <reason>"`. A prepared resource that no
input reads (a translated twin, a lookup table) needs its own entry,
`"resource:<resource_id>": "skip: <reason>"`. `kpi:<name>` must name a KPI
the model produces, and entries for columns the recipe doesn't read fail
as stale. Expect roughly 6–10 charts on a
dataset with several meaningful dimensions; fewer only when the coverage
file shows the data genuinely doesn't carry more.

**Every chart has a fallback** — `verify` enforces it per chart section:
a `<details><table>` of the chart's own numbers when they fit in ~20 rows
(top-N lists, yearly series, category splits — rendered from the same model
arrays). A genuinely large series (daily history, a heatmap, a scatter) is
instead marked `data-fallback="explorer"` on the chart element: the shell's
data explorer and download section under every page are its tabular view.
**No links to data.gov.il** — not per chart, not at the bottom: the shell
already renders the downloads, and `verify` rejects them.

Constraints that don't move: every `<script>` block < 50KB (aggregate in
`compute`, never ship rows; one IIFE per chart keeps blocks small), mobile at
375px, RTL, Hebrew-only text, design tokens, `check.py` must pass.

## 4. Write the recipe — `recipes/<dataset_id>/`

### `recipe.json`

```json
{
  "contract_version": 1,
  "dataset_id": "<id>",
  "recipe_version": 1,
  "authored_at": "<now, ISO-8601 UTC>",
  "authored_against": {
    "metadata_modified": "<from BRIEF>",
    "rows": { "<input>": 0 }
  },
  "inputs": [
    { "name": "main", "by_id": "<resource_id>", "required_columns": ["..."] }
  ],
  "min_insights": 3,
  "lint_allow_numbers": []
}
```

- `by_id` for a single stable resource. For a dataset that adds a file per
  period use `{"name": "...", "by_schema": [cols every file has], "concat": true}`
  — rows get a `_resource_name` column naming their file.
- `required_columns`: every column `compute` reads. A missing one fails the
  refresh as `schema_changed` (page kept, issue opened) instead of crashing.
- `min_insights`: below this many surviving insights the refresh fails for a
  human look. Set it to what a good page needs, usually 2–4.
- Re-authoring an existing recipe: **bump `recipe_version`**.

### `compute.py` — `compute(frames: dict[str, DataFrame]) -> dict`

Pure function: no network, no file I/O, no clock (`datetime.now()` is
banned — "latest" means latest in the data), no randomness. Every column
arrives as `str`; coerce explicitly (`pd.to_numeric(..., errors="coerce")`,
`pd.to_datetime(..., errors="coerce", format=...)`), strip thousands
separators, then drop/handle what didn't parse.

Return:

```python
{
  "agent_data": {            # validated as AgentData (services/page_builder/schema.py)
    "summary_he": "...",     # computed — it quotes numbers
    "dataset_kind": "timeseries|map|registry|rankings|misc",
    "suggested_tags": ["..."],          # 1–8 short Hebrew topic labels
    "related_ids": ["..."],             # ≤5, from BRIEF candidates (static is fine)
    "temporal_coverage": "2019/2026",   # computed, optional
    "spatial_coverage": "...",          # optional
  },
  "kpis": {"total": {"value": 1695, "display": "1,695"}, ...},
  "charts": {"by_year": {"x": [...], "y": [...]}, ...},
  "insights": [{"id": "trend", "text_he": "..."}, ...],
  # anything else the template needs: "labels" (aria-labels, chart ledes),
  # "tables" (DATA-TABLE FALLBACK rows), flags for optional sections, ...
}
```

**Insight rules — the heart of the recipe.** Each insight is a small function
that inspects the data and returns a Hebrew sentence or `None`:

- Choose wording from the data's state: direction (עלייה/ירידה/יציבות with a
  threshold), which category leads, whether a gap widened or narrowed, whether
  the latest period is partial (compare its row/month count to full periods —
  never to today's date).
- Return `None` when the premise doesn't hold (no clear leader, too few
  periods, a share below a meaningful threshold). A dropped insight is fine; a
  false one is not.
- Format every number from the data (`f"{v:,}"`, `f"{share*100:.1f}%"`). Years,
  months and names come from the data too.
- Disclosed filtering still applies: if the rule excludes anything, the
  sentence says so.

**Growth-proofing:**

- Cap category axes: top-N + "אחר" bucket, N chosen for mobile.
- Long time series: pick granularity from the span in `compute` (e.g. daily
  → weekly → monthly as the span grows) so blocks stay < 50KB forever.
- Partial last period: detect and label it (or exclude it from trend rules,
  disclosed).
- New categories must flow through (no hardcoded category lists, except for
  ordering/mapping known codes — with a fallback for unknown ones).
- Explicit, total sorts (stable sort with full tie-break keys): `verify`
  shuffles the rows and requires identical output.

### `template.html.j2`

Jinja2, sandboxed, `StrictUndefined`, autoescaped. The context is `model`
(what `compute` returned) and `inputs` (`inputs.<name>[i].id` — e.g. a
GovMap `resourceId`).

- **No numeric literals** in prose, KPI labels or `aria-label`s — `verify`
  lints for it. Put every number in the model. (Fixed strings with digits that
  are not data, like "24/7", go in `lint_allow_numbers`.)
- Data into scripts only as `const d = {{ model.charts.x | tojson }};` — never
  hand-built JS literals, never `| safe` on anything data-derived.
- Optional sections: `{% if model.charts.map %}…{% endif %}` driven by
  flags `compute` sets from the data.
- The `<h1>` is the dataset title; insights section, cards, icon headers etc.
  exactly per BODY SKELETON (check.py enforces them).

## 5. Verify (loop until PASS)

```bash
python -m services.page_builder.author verify <dataset_id>
```

Runs the recipe exactly as the nightly refresh will (same input resolution,
sandboxed compute, sanitizer, `check.py`), then:

- **determinism** — two runs byte-identical;
- **robustness** — re-runs on the first 70% of rows (must still pass
  `min_insights` and produce _different_ numbers — proof they're computed)
  and on shuffled rows (must produce the _same_ model);
- template numeric-literal lint, PII grep;
- a chart-fallback check per chart section, and `coverage.json` completeness
  (every `"<input>.<column>"` mapped to element ids on the page or to
  `skip: <reason>`).

`coverage.json` is authoring documentation only: the nightly refresh never
reads it, so updating it can't break a live page.

It also writes `tmp/model_test/<id>/{content.html,agent_data.json,model.json}`.
Read `model.json` and the truncated-run insight sentences it prints: do the
insights still read naturally and truthfully on the smaller data? Verify the
key numbers independently (a separate pandas one-off) — CHART-DATA
PROVENANCE is now "compute computed it", so check compute is right.

Chart heights: prefer the corpus's existing pairs (`h-64 md:h-80`,
`h-72 md:h-96`, `h-72 md:h-[420px]`, `h-80 md:h-[460px]`). Tailwind
compiles classes from published bodies at build time, so a new arbitrary
value (`h-[520px]`) works on the site but is missing from the live CSS that
`preview render` borrows — the chart then collapses to 0px in the preview.

Heatmap cells with extra fields (`[x, y, value, count]`): set
`visualMap.dimension: 2`. ECharts otherwise colours by the LAST element,
so a count column silently drives the colour scale.

## 6. Look at it

```bash
python -m services.page_builder.cli.preview render <dataset_id>   # existing pages
```

or `preview swap <id>` + `cd frontend && npm run dev` (pages with a local
`frontend/public/datasets/<id>/data.json`). Open it with Playwright at 375px
and desktop width; charts must render on a normal load, console clean. Fix
and re-verify.

## 7. Ship

- Commit only `recipes/<dataset_id>/` — the three contract files plus
  `coverage.json` (never `tmp/`).
- PR title `recipe: <short Hebrew/English title> (<id8>)`; body: what the page
  shows, the insight rules and their thresholds, how it handles growth, the
  `verify` output. Add `Closes #N` when authoring from an issue.
- Demo lane (before prod refresh is enabled): after merging or on request,
  `./infra/refresh-preview.deploy.sh sync-recipes` uploads recipes to the
  preview prefix; the next preview run renders them to the `recipes-demo`
  channel.
