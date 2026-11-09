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

- Work in a worktree off up-to-date `origin/main` (CLAUDE.md, "Work in a worktree"), on a
  branch like `recipe/<id8>`; never switch branches in the main checkout. Under
  `/solve-authoring-issues` the batch worktree is already set up.
- `source .venv/bin/activate` (a built-in worktree has a `.venv` symlink to the main
  checkout's).
- Firestore read access (ADC) is needed for `prepare` only.

## 1. Prepare

```bash
python -m services.page_builder.author prepare <dataset_id>
```

Fetches every datastore resource IN FULL into `tmp/authoring/<id>/data/` and
writes `tmp/authoring/<id>/BRIEF.md` (facts, columns, samples, the current
page's agent_data, the tag vocabulary and how same-ministry datasets are
tagged). Read the brief. If
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

### Provider sources (not data.gov.il)

A dataset from another source (Bank of Israel, ids `boi-*`; CBS press
releases, ids `cbs-*`; CBS price indices, ids `cbs-index-*`) is declared by `recipes/<id>/source.json`, written
**before** `prepare`: `provider`, `title` (the H1 people search), `notes`,
`tags`, `update_frequency`, `source_url`, and the provider's `config` (for
`boi_sdmx`: `resources: [{id, name, dataflow, key?, startperiod?}]`).
The id must start with the provider's prefix. `prepare` then needs no
Firestore and fetches from the source. BRIEF.md ends with the provider's
**Source rules**: follow them. Key points: no live explorer under the page,
so every chart gets its own `<details><table>`; no GovExplorer/GovMap; no
data.gov.il links. `recipe.json` `by_id` is the resource `id` from
source.json. Commit `source.json` with the recipe.

**CBS (`cbs_releases`)**: one page per recurring CBS report (monthly visitor
arrivals, average wage, …). Find the report with
`python -m services.providers.cbs catalog` (count, interval, file chapter,
suggested `title_regex`, the last edition's table stems). Config:

```json
"config": {
  "report": {"title_regex": "^כניסות של מבקרים לישראל ב(?!שנת)",
             "chapter": "28", "interval": "חודשי"},
  "history_releases": 1,
  "resources": [
    {"id": "t1", "name": "כניסות מבקרים לפי דרך כניסה", "table": "t1"},
    {"id": "releases", "name": "פרסומי הלמ\"ס", "kind": "releases"}
  ]
}
```

Check the regex against the catalog's titles: special editions (a yearly
summary, a holiday collection) often share the prefix and carry the same
interval label, so exclude them with a lookahead. Each table resource is a
grid (`RELEASE_NO, RELEASE_DATE, SHEET_NO, SHEET, ROW, C01..`): read it with
`from govlib import cbs` (header lookups by label that raise when a label is
gone, period rows found by content) and follow BRIEF.md's Source rules.
`history_releases` > 1 only when a table shows just the current period. The
`releases` resource gives the latest edition's headline and links (pick it
with `cbs.latest_release(...)`). A table only some editions carry gets
`"optional": true` (it may arrive as an empty grid: check `.empty` first);
lettered sub-tables are stems like `t3a`. The release list reaches ~3 years
back, so yearly reports have 2–3 editions to test compute against. Worked
examples: `recipes/cbs-visitor-arrivals/`, `recipes/cbs-average-wage/`.

**CBS price indices (`cbs_index`)**: CPI, housing prices, producer and input
price indices, from the CBS Index API. Ids start `cbs-index-`. Choose codes
with `python -m services.providers.cbs_index catalog [--chapter a]`
(chapter → subject → codes). Config:

```json
"config": {
  "resources": [
    {"id": "cpi", "name": "מדד המחירים לצרכן וקבוצות ראשיות",
     "codes": [120010, 120020, 110040], "start": "01-2000", "frequency": "month"}
  ]
}
```

`start` (`MM-YYYY`) is optional (default: full history); `frequency` is
`month`, `quarter` or `both` (default). Rows: `CODE, NAME_HE, FREQ,
TIME_PERIOD, DATE, YEAR, PERIOD, VALUE, BASE_DESC, PERCENT, PERCENT_YEAR,
VALUE_CHAINED, CHAIN_BASE`. Chart `VALUE_CHAINED` (one base for the whole
series), never `VALUE` across bases; quote `PERCENT` / `PERCENT_YEAR` as
published.

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

Design rules are the retired cloud agent's rules, kept as a design reference
— read these sections of `agent/system-prompt.md` (no longer shipped or run;
the repo copy is canonical) and follow them: WRAPPER CONTRACT, DESIGN TOKENS,
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

**Single-row datasets** (a registry that currently lists one clinic, one
office): a fact card of the row's fields, not charts. Still compute
everything from the frame (count, names, places), so the page stays true
when a second row appears. Insights state what the data holds ("the
registry lists one clinic, in Netanya"). Write them so they still read
naturally at n ≥ 2. A 0-row input can't be authored: the fetch fails
"has no rows", so block it.

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
  — rows get a `_resource_name` column naming their file. For a dataset that
  publishes each **full snapshot** as a new resource ("נכון ליום …"), use
  `{"name": "...", "by_schema": [...], "pick": "latest"}` (no `concat`): only
  the matching resource with the newest CKAN `last_modified` is read, so the
  page follows new snapshots instead of staying pinned `by_id` to one.
- `required_columns`: every column `compute` reads. A missing one fails the
  refresh as `schema_changed` (page kept, issue opened) instead of crashing.
- `columns` (optional): fetch only these columns. The refresh asks CKAN for
  them alone (`datastore_search fields=`), so a wide table exports a fraction
  of its bytes: 2 of the 20 columns of the vehicle registry cut a page from
  14MB to 1.6MB. `compute` sees exactly these columns, in this order. Must
  include every `required_columns` entry. Use it whenever the page reads
  well under all of a big table's columns; `coverage.json` still lists the
  rest as `skip:`.
- `limits` (optional, top level, for datasets over the default caps only):
  `{"max_records", "max_bytes", "total_bytes", "wall_budget_s",
"compute_timeout_s", "compute_memory_mb"}` override the job's `REFRESH_*`
  defaults (2M rows, `REFRESH_MAX_BYTES` per resource, 600MB per dataset,
  900s fetch, 300s compute, 3072MB compute heap). Try `columns` and
  `pick: "latest"` first. A recipe with `limits` is **heavy**: it runs after
  every other recipe, and its compute dies alone (`MemoryError`) rather than
  taking the night's job with it. The job has 4Gi in total, and on Cloud Run
  the exported CSVs sit in memory (`/tmp` is RAM) next to compute's
  footprint (about 2.5× the CSV size in pandas), so keep
  `total_bytes` + `compute_memory_mb` under about 3.5GB. Set only the
  limits the data needs, with headroom for growth, and say why in the PR.
  Once the recipe is committed, `prepare` and `verify` apply its `limits`
  and fetch only its inputs' `columns`, as the refresh does (`prepare
--all-columns` to see the rest for a redesign). Before that
  (first exploration), run `prepare` with the caps raised:
  `REFRESH_MAX_RECORDS=… REFRESH_MAX_BYTES=… python -m services.page_builder.author prepare <id>`.
- `map` / `snapshot` (map geometry that exists only in an uploaded file):
  see **Map files** below.
- `min_insights`: below this many surviving insights the refresh fails for a
  human look. Set it to what a good page needs, usually 2–4.

### Map files: geometry that only exists in a file

Many GIS layers (transport plans, boundaries, routes) put their shapes only
in an uploaded SHP/KMZ zip or GeoJSON. The datastore holds just the
attribute table, sometimes empty or one row. `prepare` downloads every such
file and BRIEF.md summarises it under **Map files** (features, geometry
types, source CRS, property columns), or says why it failed.

1. **Add a `map` input** (the default):
   `{"name": "geo", "by_id": "<resource_id>", "map": true, "required_columns": [...]}`.
   The nightly refresh downloads the file on every run (a UA data.gov.il's
   WAF accepts), reads GeoJSON, KML, KMZ or a zipped shapefile, reprojects
   ITM to WGS84, rounds to ~1 m and simplifies only as far as 150 KB needs
   (`"map_max_kb"` raises it, up to 50000). That caps the table `compute`
   reads, not the page: for a big layer, `compute` must aggregate or subset
   the geometry to page size. A new upload re-renders the page like any data
   bump. A file that won't parse fails `schema_changed`; a download the WAF
   blocks 3 runs in a row opens a `download_blocked` issue.
2. `compute` gets `frames["<name>"]` like any table: one row per feature,
   properties as strings, plus `__geometry` (the feature's geometry as JSON;
   `json.loads` it). Compute the analysis from the properties and the
   geometry (counts and lengths per type, areas, bounds), and pass the
   features to the template in the model. Feature order is not guaranteed
   across uploads: sort explicitly (verify shuffles them).
3. Draw it with Leaflet (`L` is a page global), styled by a property. Encode
   and pack the geometry with `govlib.geo` (below), never a local copy:
   `o = geo.origin(lons, lats)`, `geo.encode(rings, o, tol=1.5)` per feature,
   `geo.pack(features)` into chunks; put `o` and `geo.SCALE` in the model and
   each chunk in `<script type="application/json" id="map-s-{{ loop.index0 }}">`.
   On the page, `GovMap.islands("map-s")` returns the features,
   `GovMap.ring(flat, origin, scale)` a Leaflet `[[lat, lng], ...]` and
   `GovMap.popup(title, [[label, value], ...])` safe popup content. Split a
   long line into pieces in `compute` so no single feature outgrows an island
   (`pack` raises if one does). `recipes/5ecf0587-21e6-411a-8f04-9f4f44a43956/`
   is the worked example (lines, coloured by type, popups built with
   `textContent`). Escape every string that goes into a popup or tooltip. Map
   `<name>.__geometry` in `coverage.json` (`map-<id>`).

**Fallback: a committed snapshot**, only for a file BRIEF.md lists as
FAILED to download. Ask the user to download it in a browser (in an
unattended run, label the dataset `authoring-blocked` and comment with the
URL and these steps), then
`python -m services.page_builder.author snapshot <id> <file> --resource <resource_id> [--name geo]`
writes `recipes/<id>/<name>.geojson` and prints a `snapshot` + `snapshot_of`
input. Commit the `.geojson`. The snapshot is fixed: when CKAN's size/hash
for the resource moves past `snapshot_of`, the refresh fails
`geometry_stale` (page kept, issue opened).

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
    "temporal_coverage": "2019/2026",   # computed, optional
    "spatial_coverage": "...",          # optional
    "seo": {                 # search metadata; title + description required by verify
      "title": "...",        # ≤60, the <title>, verbatim
      "description": "...",  # 80-150 (verify), the snippet; computed numbers welcome
      "name": "...",         # ≤80, the h1 name (JSON-LD name + breadcrumb)
      "alternate_names": ["..."],  # ≤5 variants (JSON-LD alternateName)
    },
  },
  "kpis": {"total": {"value": 1695, "display": "1,695", "tone": "brand"}, ...},
  "charts": {"by_year": {"x": [...], "y": [...]}, ...},
  "insights": [{"id": "trend", "text_he": "..."}, ...],
  # anything else the template needs: "labels" (aria-labels, chart ledes),
  # "tables" (DATA-TABLE FALLBACK rows), flags for optional sections, ...
}
```

**Shared helpers: `govlib`.** `from govlib import fmt, frame, geo`
(`services/page_builder/recipe_lib/govlib/`, copied into the sandbox). Use
them instead of writing a local copy:

- `fmt`: `int_he` (rounds half up; `int(v)` truncates a median of 2.5 to 2),
  `num_he`, `pct(fraction)`, `pct_of(value_0_100)`, `signed_pct` (U+2212
  minus), `d_he` / `month_he`, `MONTHS_HE` / `MONTHS_SHORT_HE`, `join_he` and
  `vav` (`ו-` before digits and Latin), `LRI` / `PDI` / `isolate`.
- `frame`: `ranked` (value_counts with a deterministic tie order),
  `top_other(counts, n)` → `(labels, values)` with an "אחר" bucket, `clean` /
  `clean_series`, `num` (parses `1,234`, `₪`, `%`, U+2212 minus).
- `geo`: `quantize`, `simplify`, `origin`, `encode`, `pack`, `rendered_len`,
  `haversine_km` (see Map files above).

A helper's output never changes once published. When you need different
behaviour, add a keyword or a new function to `govlib` in the same PR. A PR
that adds to `govlib` (or `gov.j2`) must be merged and the job redeployed
before a recipe that uses the addition merges: recipes are read from main at
run time, and the old image fails the import as `recipe_failed`.

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

### KPI cards — match the published look

```html
<div class="card p-4 text-center">
  <div
    class="text-3xl font-bold text-{{ model.kpis.level.tone }} mb-1"
    dir="ltr"
  >
    {{ model.kpis.level.display }}
  </div>
  <div class="text-sm text-subtle">{{ model.labels.level_kpi }}</div>
</div>
```

- **`display` is a bare number:** `1,695`, `−213.72` (minus sign U+2212,
  never `-`), `45.2%`, `2014–2026`, `432.9 מ׳`. Units and context go in the
  label: "סך העיצומים (מיליון ₪)", "מפלס נוכחי, מ' מתחת לפני הים (22.10.2026)".
  No `₪`/unit words and no bidi-isolate characters in the value; `dir="ltr"`
  on the value box handles direction. `verify` enforces this (KPI-FORMAT).
- **`tone` carries meaning, computed from the data** — `brand` for neutral
  counts/sizes; `ok` for a good state (recovering, above a target, record
  high where high is good); `warn` for caution (approaching a threshold,
  partial/degrading); `danger` for a bad state (below a red line, a sharp
  fall, a record low where low is bad); `info` for notable-but-neutral
  context. Because it is computed, the colour flips when the data does
  (Kinneret's level turns `danger` below the lower red line and `ok` once
  it recovers). Aim for colour where the KPI has a direction — the published
  pages colour roughly a third of their KPIs; a page of four neutral counts
  stays all `brand`.

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
- Shared blocks: `{% import "gov.j2" as gov %}`
  (`services/page_builder/recipe_lib/macros/gov.j2`) gives
  `gov.head(icon, title)`, `gov.lede(text)`, `gov.kpi(model.kpis.x, label)`,
  `gov.insights(model.insights)`, `gov.chart(id, aria)` and
  `gov.table(caption, cols, rows, ltr=(...))` (the "הצג כטבלה" details
  table). Prefer them over writing the markup again: the same elements and
  classes, only the whitespace differs.
- The `<h1>` is the dataset's searched name (`seo.name`, see "Search (SEO)"); insights section, cards, icon headers etc.
  exactly per BODY SKELETON (check.py enforces them).

### No em dash in user-facing text

Don't put an em dash (U+2014) in anything a visitor reads: insights, ledes, labels,
headings, `summary_he`, tooltips or aria-labels. Rewrite the sentence instead,
using a colon, a comma, parentheses or a new sentence. `verify` fails on an em
dash in any `compute.py` string literal or in the template (comments and
docstrings are exempt; so is an escaped `"\u2014"`, for code that has to match
one inside the data). An empty-value placeholder is a lone en dash ("–").

Write a numeric range in Hebrew text, tooltips and ECharts labels with an ASCII
hyphen (2016-2025), or as "2016 עד 2025" in prose. An en dash between digits
renders reversed in RTL ("2025–2016"). The one exception is a KPI `display`
value: its box is `dir="ltr"`, so `2014–2026` is fine there.

### Search (SEO): write for what people type

Most organic traffic is _lookup_ intent ("איתור מספר רישיון רופא", "איתור
שותפות", "בדיקת קבלן רשום"), and the page competes with the ministry's own
search on the SERP. Search Console (2026-10) showed pages ranking at position
2–7 with 1–2% CTR because neither the snippet nor the top of the page offered
the lookup.

The recipe owns its search metadata through `agent_data.seo` (`SeoMeta` in
`services/page_builder/schema.py`; the refresh rejects a page whose `seo`
breaks a limit, and `verify` fails without `title` and `description` and
prints them with their lengths). The shell builds every head tag from it, so
the template still never writes `<title>` or `<meta>`:

- **`seo.title`** (≤60 chars) is the `<title>`, og:title and twitter:title,
  used verbatim: no brand or ministry is appended. Lead with the searcher's
  task or the name they type ("איתור רופא לפי מספר רישיון | פנקס הרופאים"),
  not the CKAN title's bureaucratic form. No `data.gov.il` (the brand is
  govil.ai; the schema rejects it). Write `title` and `name` as fixed
  strings: numbers and data values (a top city, a count) belong in the
  description, whose length `verify` checks with room to move. A title or
  name built from the data can cross its limit on a later refresh and fail
  the page.
- **`seo.description`** (70-160 chars; `verify` wants 80-150, so the
  computed numbers and names in it can change length on new data without
  failing a refresh) is the meta, og and JSON-LD description. Lead with the task the searcher has, using their words
  ("איתור … לפי שם, מספר רישיון או יישוב"), then one or two computed numbers.
  Don't write a stats blurb. It may differ from `summary_he`, which stays the
  blurb on cards, the related sidebar and site search.
- **`seo.name`** (≤80) is the name people search, which is not always the
  CKAN title (e.g. "מאגר שומות מכריעות", not "מאגר נתוני שמאות מכריעה").
  Render it as the heading, `<h1>{{ model.agent_data.seo.name }}</h1>`
  (`verify` fails when the h1 text differs): `name` becomes the JSON-LD
  Dataset `name` and the breadcrumb, and the CKAN title moves to `alternateName`.
- **`seo.alternate_names`** (≤5) holds the other names and spellings people
  type (כח/כוח, בניה/בנייה, "רשם …"/"פנקס …"), emitted as JSON-LD
  `alternateName`. Also work the most common variant into the lede or an H2
  naturally. Never add a keyword block to the page.
- **Registry/list datasets get a lookup callout** right after the lede card,
  linking to the shell's explorer (`#data-explorer`, a live full-text search
  over every record). Name the fields the explorer can actually search, and
  check them against the resource's columns:

  ```html
  <a
    href="#data-explorer"
    class="card p-4 mb-6 flex items-center gap-3 no-underline"
  >
    <img src="/icons/search.svg" alt="" class="w-5 h-5 shrink-0" />
    <span>
      <span class="block font-semibold text-ink-deep"
        >איתור רופא לפי שם או מספר רישיון ←</span
      >
      <span class="block text-sm text-subtle"
        >חיפוש חי בכל רשומות המאגר: שם פרטי, שם משפחה, …</span
      >
    </span>
  </a>
  ```

### Tags — `taxonomy/dataset-tags.json`, not the recipe

A page's tags (the chips under the H1, its /tags/ pages, and half of the
related-datasets score) come from the curated vocabulary in
`taxonomy/tags.json`, not from `compute()`. Pick 3–6 canonical tags from
BRIEF.md § Tags: the topic's broad tag first when it has one (תחבורה, מים,
…), then the specific subjects the data is ABOUT (not its publisher). Line up
with how the same ministry's datasets are tagged. Then:

```bash
python -m services.page_builder.tags assign <dataset_id> <tag> <tag> <tag> ...
```

It refuses non-canonical tags and names the canonical one for an alias. A
genuinely new subject that recurs (or will) gets a new canonical tag in
`taxonomy/tags.json` in the same PR (normal form, a `topic`, `aliases` for
its spellings), never a near-variant of an existing tag. Under
`/solve-authoring-issues`, write the list to `tmp/authoring/<id>/tags.json`
instead (a JSON array); the orchestrator merges the batch. Related datasets
are computed by the publisher (`services/page_builder/related.py`); a recipe
never lists them, and `suggested_tags` / `related_ids` in `agent_data` are
deprecated and ignored.

## 5. Verify (loop until PASS)

```bash
python -m services.page_builder.author verify <dataset_id>
```

Runs the recipe exactly as the nightly refresh will (same input resolution,
sandboxed compute, sanitizer, `check.py`), then:

- **determinism** — two runs byte-identical;
- **robustness** — re-runs on the first 70% of rows (must still pass
  `min_insights` and produce _different_ numbers — proof they're computed)
  and on shuffled rows (must produce the _same_ model). When every input
  has ≤1 row, the 70% cut drops nothing, so verify skips the 70% run
  (shuffle and every other check still run) and prints `robustness skipped`;
- template numeric-literal lint, PII grep;
- `ruff check` on the recipe's Python (`RUFF:` lines; repo `ruff.toml`, the
  same check CI runs). Fix the finding; a deliberate exception gets a
  `# noqa: <code>` with the reason;
- a chart-fallback check per chart section, and `coverage.json` completeness
  (every `"<input>.<column>"` mapped to element ids on the page or to
  `skip: <reason>`).

`coverage.json` is authoring documentation only: the nightly refresh never
reads it, so updating it can't break a live page.

It also stages the page in `tmp/preview/datasets/<id>/{content.html,agent_data.json,model.json}`
(an open preview, §6, reloads with it).
Read `model.json` and the truncated-run insight sentences it prints: do the
insights still read naturally and truthfully on the smaller data? Verify the
key numbers independently (a separate pandas one-off) — CHART-DATA
PROVENANCE is now "compute computed it", so check compute is right.

Chart heights: prefer the corpus's existing pairs (`h-64 md:h-80`,
`h-72 md:h-96`, `h-72 md:h-[420px]`, `h-80 md:h-[460px]`), so pages stay
consistent. Tailwind compiles classes from the page bodies at build time, so a
new arbitrary value still works, on the site and in the preview.

Heatmap cells with extra fields (`[x, y, value, count]`): set
`visualMap.dimension: 2`. ECharts otherwise colours by the LAST element,
so a count column silently drives the colour scale.

## 6. Look at it

```bash
python -m services.page_builder.cli.preview <dataset_id>   # prints local + prod URLs
```

This renders the recipe over the prepared data and serves it in the real
dataset shell through `nuxt dev`, which starts once per checkout in a few
seconds. It works for new datasets, provider sources and worktrees. Open the
printed `local:` URL with Playwright at 375px and at desktop width. Charts must
render on a normal load with a clean console. The `[Vue warn] onBeforeUnmount`
line is dev-mode noise from the shell, not the page. The open page reloads
itself after every `preview` or `verify`. While iterating on looks, run
`preview <id> --watch`: it re-renders on each save of `recipes/<id>/`, and a
broken edit prints `FAIL` and keeps the last good page. Fix and re-verify.
When done, `preview stop`. The previewed page also carries a small "תצוגה
מקדימה מקומית" badge, which the site does not show.

## 7. Ship

- **Invoked from `/solve-authoring-issues`?** Stop after §6: that batch
  skill owns the branch, commit, review and the single PR (one `Closes #N`
  per dataset). Skip the rest of this section.
- Commit only `recipes/<dataset_id>/` — the three contract files plus
  `coverage.json` — and `taxonomy/` (the dataset's tags line; never `tmp/`).
- PR title `recipe: <short Hebrew/English title> (<id8>)`; body: what the page
  shows, the insight rules and their thresholds, how it handles growth, the
  `verify` output. Add `Closes #N` when authoring from an issue.
- Once merged to `main`, the next daily job (`govdata-builder-job`, 06:00
  Israel time) reads the recipe straight from git and renders the page; no
  redeploy. Demo lane (optional, on request):
  `./infra/refresh-preview.deploy.sh sync-recipes` uploads recipes to the
  preview prefix; the next preview run renders them to the `recipes-demo`
  channel.
