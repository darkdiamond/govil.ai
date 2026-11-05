# TODO

Follow-ups that are known but deliberately not in the PR that found them. Add an item when you
defer something; delete it (in the PR that fixes it) when it is done. Keep each item to what is
wrong, why it matters, and what would fix it, and end it with the date it was added.

This repo is public: describe a security gap by what to change, never by how to exploit it.

## Recipes and refresh

- **Most recipes still don't set `agent_data.seo`.** Batch 1 (the 21 recipes with the most
  GSC clicks lost to low CTR, 90 days to 2026-11-03) has it; the other ~296 keep their CKAN
  titles (some over 60 chars, 45 summaries over 160) and a " · ministry" suffix. Fix: next
  batches in the same order (missed clicks = impressions × (expected CTR at position − actual
  CTR)), starting with 688d7791, 35c791ca, 669b2652, 15c65f47, 14f2521f, 7a6cbf55, 3de0e7f0
  (the import sibling of 3e4e79f7), f4a5cdab, 023b7883; bump each `recipe_version`. Compare
  batch 1's CTR in GSC about 4 weeks after it ships before spending on the long tail.
  (2026-11-04)
- **The map reader can't open a zip of zips.** ee626064 (משרד הבינוי והשיכון GIS layers)
  ships its fourth layer, מחיר למשתכן (`gis_dira.zip`, 9.2MB), as a zip holding
  `Lots_view.zip`, `Plans_view.zip`, `Projects_view.zip` and `Settelments_Centroid_view.zip`.
  `geo_snapshot` reads only top-level shapefiles, so the recipe skips that layer and says so in
  fixed copy. Fix: let `geo_snapshot` descend one level into nested zips (with the same size
  caps), then add a `mehir` map input to ee626064 and bump its `recipe_version`. (2026-11-04)
- **`author verify` doesn't check the h1 against `seo.name`.** It only prints the h1 next to
  the SERP preview, so a recipe whose template hardcodes a different h1 passes, and the
  JSON-LD name / breadcrumb then disagree with the visible heading. Batch-1 templates render
  `{{ model.agent_data.seo.name }}`; older and future recipes can still drift. Fix: make verify
  fail when the rendered h1 text differs from `seo.name`. (2026-11-04)
- **`author prepare` ignores a recipe's `limits`.** It caps rows and bytes from the env only
  (`REFRESH_MAX_RECORDS` / `REFRESH_MAX_BYTES`), so a heavy recipe like 273c5e33
  (`limits.max_records` 12M, 5.5M rows) prepares 0 rows unless the author knows to export the
  env vars, and `verify` then fails as too_large or empty. Fix: have `prepare` and `verify` read
  the recipe's `limits` the way the refresh does. (2026-11-04)
- **131 of 307 committed recipes fail `author verify`'s em-dash lint.** The rule (#124) came after
  they were authored and only runs at authoring time; the daily refresh doesn't enforce it, so
  the pages render fine. But any edit to one of these recipes, even a one-line template fix,
  makes `verify` report FAIL on text the edit didn't touch, which hides real failures. Fix: a
  one-off sweep that rewrites the em dashes per the rule (colon, comma, parentheses or a new
  sentence), bumping each `recipe_version`. (2026-11-04)
- **One broken datastore resource blocks every `by_schema` input of its dataset.**
  `resolve_inputs` raises `PreviewUnavailable` when any datastore-active resource's preview fails,
  even one that never had the input's columns. A resource whose datastore answers
  `success: false` for good (it used to be skipped) now fails the page and, after
  `REFRESH_TRANSIENT_STRIKES` runs, opens a `schema_changed` issue that re-authoring with
  `by_schema` can't clear. Fix: let a recipe exclude resource ids from `by_schema` matching,
  or ignore an unanswered resource whose CKAN name/format can't be a match. Also, `author
prepare` records a failed preview as `fields: []`, so verify reports "no resource has
  columns" where prod would report "no preview". (2026-11-02)
- **`sandbox_failed` never escalates.** It opens no issue and keeps no strike count, so a spawn
  abort that turns deterministic (an image that loses `GRPC_ENABLE_FORK_SUPPORT=0`) freezes
  every page with only log lines. Fix: raise `_SpawnFlake` as a `refresh.StrikeError`
  (`strike="sandbox_failed"`, an `escalate_to` reason added to `AUTHORING_REASONS` and
  `notify.REASON_TEXT`); the `transient_strikes` counter does the rest. (2026-10-31)
- **`author snapshot` keeps long float properties that trip verify's PII check.** Shapefile
  area/length fields (`Shape_STAr` 213.029377738) match the phone pattern. 1de95a22 got past it
  with a scratch step that rounds them to 0.1 before `snapshot`, so a re-snapshot after
  `geometry_stale` needs the same step. Fix: round numeric properties in `geo_snapshot`, or make
  the PII grep skip numeric GeoJSON values. (2026-10-31)
- **Top-100 legacy map pages that the snapshot path can't serve.** חלקות (dff8a168, 667MB SHP),
  גושים (1d2d0ec1, 65MB) and גבולות תצ"ר (65dafbb0, 84MB) are national layers far over a
  committable snapshot; they'd need a pre-aggregation step (centroids or per-region dissolve).
  הגבולות המשטרתיים (d01a5ee3) and קדסטר במבנה חדש (bd74ce49) ship an Esri FileGDB, which
  `read_map_file` can't read and there is no GDAL locally. (2026-10-31)
- **Removed registries still draw top-100 traffic.** 8152ebdf (קבלני כח אדם), bc0e0381 (קבלני
  שמירה וניקיון) and a698417e (לשכות תיווך) are `unavailable` upstream; the ministry merged them
  into 90b08091, which has a recipe. Their gone-state pages could link (or 301) to 90b08091 to
  keep the search traffic. (2026-10-31)
- **Three new recipes can go quietly wrong as their data moves.** 4eef54bc's `recent` input
  matches files by `קוד`; a new yearly file named like the 2019 one (`קוד_מיפוי`) is silently
  skipped, so the page stays on 2024 with no issue (match both names, or fail when the newest
  CKAN resource isn't read). 4eef54bc also joins authorities across years by name only, so a
  renamed authority splits in two. ab746a13 uses `pick: "latest"` by `last_modified`: a
  re-upload of a closed year flips the page to that year (pick by the year in the resource
  name instead). (2026-10-31)
- **Explorer resource pills overflow at 375px.** A long resource name pushes `.explorer-pill`
  past the viewport (85451410: 381px scroll width). Shell CSS, not the recipe: truncate or wrap
  the pill label. (2026-10-31)
- **A map snapshot misses a same-size edit when CKAN has no md5.** `snapshot_stale` compares
  CKAN's `hash` when both sides have one, else `size` (#184's GeoJSON has an empty `hash`), and
  ignores `last_modified` because CKAN bumps it on byte-identical re-uploads. An edit that keeps
  the byte count goes unnoticed. If that matters, also compare `last_modified` and treat a
  bump with the same size as "re-check by hand" (a note in the issue, not a failure). Only
  committed snapshots have this gap: a `map: true` input downloads the file on every bump and
  check B compares the converted rows exactly, so moving a snapshot recipe to `map` closes it.
  (2026-10-30)
- **GIS layers with no recipe could get maps now.** `map: true` reads their SHP/KMZ zips
  directly, but they have no recipe and no open issue, so nothing queues them:
  `python -m services.page_builder.map_backfill list` reports them as `no_recipe` (63 on
  2026-10-31; the transport/Ayalon family 30cc4889, 5f6d04bf, 7fb47ed4, cdd75af3, e74cc3c7,
  ee1265d8, 360fb8b4 among them). Open `new`-style issues for the ones worth a page (the
  backfill only files issues for recipe'd pages). (2026-10-31)
- **Decide the next precheck lever from a week of B′ data.** The content-hash skip
  (`unchanged … content_hash`) still pays the export and compute for a re-upload whose page
  doesn't change. Read the `refresh precheck` lines. If `inputs_same_unordered=True` dominates
  the identical renders (rows only reordered) and no `FALSE-SKIP candidate —
inputs_same_unordered` appears, skip on B′ in `inputs`/`full` (saves compute only). If it is
  mostly `False` (an edited column the page doesn't read), declare `columns` in those recipes:
  a smaller export, and B then only sees the columns the page uses. (2026-10-31)
- **Verify's robustness check is all-or-nothing across inputs.** It truncates every input and
  compares the whole model, so a ≤1-row input next to a large one is never perturbed. A value
  hardcoded from that small input passes, because the large input changes the model anyway.
  Fix: truncate one input at a time (pass the resource id into `_LocalCkan`'s transform) and
  require each multi-row input to move the model. (2026-10-30)

- **Recipes written for pandas 2 can still trip on pandas 3 dates.** pandas 3 parses to
  `datetime64[us]`, so junk dates far outside 1677–2262 now parse instead of becoming NaT.
  `a9d7da6b` nulls only years ≥ 2262, so a year-1412 value fails its `.astype("datetime64[ns]")`
  with OutOfBoundsDatetime (a clean `recipe_failed`, page kept); `e6ef4310` builds a ns Series the
  same way. A raw numpy ns buffer (as 6d8bf87d had) segfaults instead. Fix: bound both ends
  (`between(pd.Timestamp.min, pd.Timestamp.max)`) wherever a recipe casts to ns, or grep the
  corpus for `datetime64[ns]` and drop the cast. (2026-10-30)
- **`273c5e33…` (vehicle history) is not authored yet.** Its two resources hold 2.5M and 5.55M
  rows (167MB and 178MB), over the 2M `REFRESH_MAX_RECORDS` default. Recipes can now carry their
  own `limits` and fetch fewer `columns`, so it can be authored as a heavy recipe: measure the
  export with only the columns the page reads, and compute's peak RSS, before choosing limits.
  (2026-10-30)
- **Heavy recipes share the job's 4Gi.** A recipe with `limits` runs last and its compute is
  heap-capped (`REFRESH_COMPUTE_MEMORY_MB`, 3072 by default) and first in line for the OOM
  killer, but its exported CSVs sit in the same memory (`/tmp` is RAM on Cloud Run). If heavy
  recipes multiply, give them their own job execution with more memory (filter on
  `manifest.heavy`) rather than raising the shared job's `--memory`. (2026-10-30)
- **`pick: "latest"` trusts CKAN `last_modified`.** Re-uploading an old snapshot bumps its
  `last_modified`, and the page would switch to it. If that happens, order by the date in the
  resource name when it parses (snapshot datasets name their date), falling back to
  `last_modified`. (2026-10-30)
- **Provider checks are scattered over the CKAN paths.** `refresh_one`, `reconcile.probe_one`
  and `selector._skip` each branch on `getattr(src, "provider")`. A new CKAN-shaped path that
  forgets the branch treats a provider doc as CKAN. Add a `CkanProvider` adapter around the
  existing CKAN fetch/probe functions and one `provider_for(src)` that always returns a provider,
  so those paths dispatch instead of branching. (2026-10-30)
- **The preview lane cannot render a new provider recipe.** Provider sync runs only for the prod
  target (the preview lane reads unmerged recipes and must not write `sources/`), so a `boi-*`
  recipe can be previewed only once its prod doc exists. Let the sync write `preview_sources/`
  when the target is preview, and have the preview refresh read provider facts from there.
  (2026-10-30)

- **Big map layers convert in the builder's memory, uncapped.** `_fetch_map_input` holds the raw
  download, the feature list, each tolerance pass, the serialized body and a re-parsed copy
  (`json.loads(body)`) at once: ~25x the result in peak RSS (540 MB for the 22.7 MB roads layer).
  A layer near the 50 MB `map_max_kb` ceiling would take ~1.2 GB beside a 3 GB compute in the
  4Gi job. `build_snapshot` also re-serializes every feature per tolerance step (up to 8 passes).
  Fix: have `build_snapshot` return the simplified features with the bytes (no re-parse), pick
  the tolerance from a size estimate instead of the full ladder, and free the raw features
  before compute. (2026-11-01) The download cap is now 100MB (2026-11-04), for three layers
  with search traffic: 1d2d0ec1 (65MB), 65dafbb0 (84MB) and 022552b2 (85MB). `load_map` alone
  peaks at 1.35GB and 1.8GB RSS on the first two, so do this fix, or raise the job's
  `--memory`, before merging a recipe that reads any of them. (2026-11-04)

- **More recipes carry their own map chunking or simplification.** 1745d2f8, 2a795952, 4eef54bc,
  5ecf0587, 12fb4671, 6910f861, 1de95a22, 3ce41381, 4acf8b98, 8f2becb2, a98fbabc, 0b3bd728,
  3c6d4061, 6cd898c4, 7cac04c9, d9b1e04c and fc549bf6 define their own island chunking, DP or
  coordinate encoding (grep `CHUNK|_dp\(|def _encode`), each sized its own way. Move them onto
  `govlib.geo` + `GovMap.islands` / `ring` / `popup` as they're next touched, the way the six in
  the map-govlib PR were: keep the non-geometry model byte-identical and bump `recipe_version`.
  (2026-11-01)
- **Cloud Run → Bank of Israel connects still drop SYNs.** About half of the TCP connects to
  `edge.boi.org.il` from the job stall (up to ~135s); from outside GCP none do. The provider
  now reuses one connection and reconnects after `connect_timeout_s` (10s), which hides it but
  doesn't fix it. Check how often `reconnecting (n/5)` shows up in the job logs after the
  deploy. If it's frequent, or a sync fails after 5 reconnects, try a static egress IP (VPC +
  Cloud NAT) to tell whether BoI is filtering Google's shared egress range. (2026-11-04)

## CBS reports (cbs_releases provider)

- **Only 2 of ~22 recurring monthly/quarterly CBS reports have pages.** `cbs-visitor-arrivals`
  and `cbs-average-wage` drove the provider. The rest come from
  `python -m services.providers.cbs catalog` (labour force survey, foreign trade, credit-card
  spending, national accounts, …). Merge the labour-force "נתונים עיקריים" edition with the
  full one into one page. Author in PRs of 5–10. (2026-11-05)
- **Yearly CBS reports (~50) have no pages.** Run `catalog --months 24` to find the ones
  published in both years; skip holiday collections ("לרגל …"). The release-list window
  (`LIST_WINDOW`, newest 400 items, ~13 months) is too short for them: raise it, or query
  per report, before authoring one. (2026-11-05)
- **CPI and other price indices aren't press releases in this list.** They come from the CBS
  Index API (`api.cbs.gov.il/index/data/price?id=120010`), which needs its own provider.
  (2026-11-05)
- **A CBS table dropped from the latest edition freezes its page silently.** `facts()` raises
  when the newest edition lacks a configured `table` stem, so the provider sync fails for that
  dataset every run; the refresh never runs, so no `needs-authoring` issue opens and the page
  stays last-good indefinitely (only the run summary's `provider sync … failed` shows it).
  Fix: have the sync open an issue (or record a strike that escalates like
  `REFRESH_TRANSIENT_STRIKES`) after N consecutive `provider_error`s for one dataset.
  (2026-11-05)
- **Every run downloads every CBS table to version it.** ~0.1s a file now; with ~20 pages × ~5
  tables it costs about a minute a run. If it grows, give `version()` a cheap path that hashes
  the release number + file names and sizes from the folder listing, and download only when
  that moves. (2026-11-05)

## Shared recipe code (govlib, gov.j2, page libs)

Recipes adopt the shared code as they're next touched. Each item below is a copy-pasted helper
family found in the corpus survey of 2026-11-01, with the behaviour it should converge on.

- **`GovEcharts.option` merges shallowly.** A page's own `tooltip` or `grid` object replaces
  the shared one whole, so the shared tooltip style (Rubik, white background, RTL) never applies:
  every chart page passes its own `tooltip`. Fix: deep-merge `tooltip` and `textStyle` in
  `option()`. It changes how every chart's tooltip looks, so check a sample of pages first.
  (2026-11-01)
- **Widen tooltip escaping beyond the param label fields.** The gov-echarts.js belt escapes
  only the params' label fields, and some formatters add other dataset strings to their HTML.
  Fix: export an escape helper from gov-echarts.js, use it in every formatter that appends a
  string from the model (about 26 templates), and make that an authoring rule. (2026-11-01)
- **About 177 recipes format integers by truncating.** `_int`/`n` copies use `int(v)`, so a
  median or mean of x.5 shows x. Move them to `govlib.fmt.int_he` (half up). The builder's
  `fmt_int` filter uses `round()` (half to even), which differs at exact halves. (2026-11-01)
- **`pct` means two things.** 204 recipe copies take a fraction, 86 a 0–100 value, under the
  same names. Move them to `govlib.fmt.pct` / `pct_of`, whose names say the scale. (2026-11-01)
- **`join_he` glues ו to a number** ("ו2024") in 6cf0c0e3, 505aa85e and 09f0e9ee. Use
  `govlib.fmt.join_he`. (2026-11-01)
- **Chart mount boilerplate in 304 templates.** Each does `echarts.init` + a window resize
  listener. Most don't guard a missing element (`echarts.init(null)` throws and stops the rest of
  the script), and the listeners are never removed on SPA navigation. Fix: a
  `GovEcharts.mount(id, option)` that guards, uses one ResizeObserver and disposes with the page;
  then move templates onto it. (2026-11-01)
- **Template blocks repeated in every template** (section head, lede, KPI card, insights, the
  "הצג כטבלה" table: ~35k lines; 121 templates define their own local macros for them). Move
  them onto `gov.j2` as they're next touched. (2026-11-01)
- **`geo_snapshot.py` keeps its own Douglas-Peucker.** It and `govlib.geo.simplify` should be one
  implementation. Fold it in once a map input's converted table can be compared before and after.
  (2026-11-01)
- **`govlib.geo` can't encode points that are already quantized.** d8767745 and 4bee0109 quantize
  once, simplify per tolerance step, then divide back to floats only so `geo.encode` re-quantizes
  them (correct, since round(x / 1e5 * 1e5) recovers x, but a wasted round trip on every step).
  Add a `geo.deltas(points, origin)` for integer points, deploy the job, then call it from
  those two recipes. (2026-11-01)

## Tags, related datasets and list pages

- **A superseded dataset's `content.html` is still deployed.** `dataset_successors.json` 301s the
  page route, but the publish workflows still rsync its staged body from GCS, so the frozen
  snapshot stays reachable at `/datasets/<old-id>/content.html` (unlinked). Fix: skip superseded
  ids in the rsync step, or delete their GCS staging prefix when a successor entry is added.
  (2026-11-04)
- **Topic hub pages.** Topics exist only as sections of `/tags/` (and a broad tag per topic,
  like `/tags/תחבורה/`). A `/topics/<id>/` hub with the topic intro, its tags and its datasets
  would be a stronger landing page than the broad tag, which three topics (ביטחון והצלה,
  אוכלוסין והגירה, חינוך תיירות ופנאי) don't have. (2026-10-30)
- **Intros for the busiest tags.** `taxonomy/tags.json` supports a per-tag `intro_he`; none is
  written yet, so tag pages show their topic's intro. Write ~25 for the tags with the most
  datasets, the same way `hub-intros.json` was written. (2026-10-30)
- **`/datasets/` drops `?q=` (and now `?tag=`) from the URL after load.** The filter still
  applies, but the address bar loses it, so a filtered view can't be shared or bookmarked. Seen on
  the live site too, so it predates the tag filter. Find which watcher's `router.replace` runs on
  hydration with an empty value. (2026-10-30)
- **Firebase Hosting redirect count is unverified.** `gen-redirects.mjs` now writes ~550 tag
  redirects next to ~560 dataset ones. The docs state no cap; confirm on a preview channel deploy
  that ~1,100 rules are accepted before relying on growth beyond that. (2026-10-30)
- **Stale Firestore fields.** `sources/<id>.embedding` (Voyage, removed) is still on the docs
  that had it; nothing reads it. A one-off cleanup would shrink the docs. (2026-10-30)
- **`executeBodyScripts` has no test.** It lives inside `pages/datasets/[slug].vue`, out of
  reach of the `node --test` suite, so a change that re-wraps `<script type="application/json">`
  data blocks in the IIFE (PR #272's bug: blank map on d9b1e04c) would pass CI. Move the
  script-type check (or the whole function) to `frontend/utils/` and test that data blocks are
  left untouched and every JS type is re-created. (2026-10-31)

## Dependencies

- **ECharts 6 migration.** The moderate ECharts advisory is fixed only in 6.x, a major bump for
  the runtime every page body uses. No published page uses the affected series type, so this is a
  planned migration, not an urgent fix: do it with a corpus-wide visual check. (2026-10-30)

## Validation speed

- **Every `check.py` run spends ~0.2s importing esprima.** `esprima/character.py` builds its
  identifier tables by calling `unicodedata.category` on all 1.1M code points at import. That is
  ~40s per nightly job and ~1s per `author verify` (one check per render, four renders). Fix: a vendored
  esprima whose tables are precomputed literals or computed lazily, kept pinned in
  `services/page_builder/requirements.txt`. (2026-11-01)
- **`author verify` runs its four compute passes one after another.** The determinism, truncated
  and shuffled passes depend only on the first (full) pass, so they could run concurrently and
  cut verify's wall time about in half. The catch is memory: each pass may use up to
  `REFRESH_COMPUTE_MEMORY_MB` (3GB), so a heavy recipe would need up to 3× that. Fix: a thread
  pool sized by a flag, defaulting to serial for recipes with `limits`. (2026-11-01)
