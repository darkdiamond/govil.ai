# TODO

Follow-ups that are known but deliberately not in the PR that found them. Add an item when you
defer something; delete it (in the PR that fixes it) when it is done. Keep each item to what is
wrong, why it matters, and what would fix it, and end it with the date it was added.

This repo is public: describe a security gap by what to change, never by how to exploit it.

## Recipes and refresh

- **`public_resource_url` raises on a malformed bracketed host.** `urlsplit` throws
  `ValueError` for a resource URL like `https://[::1/x`, so `Dataset.from_ckan_response` fails
  for the whole dataset instead of blanking that one URL (the frontend mirror just returns it).
  Fix: catch `ValueError` around `urlsplit` in `services/shared/ckan.py` and return "", with
  a Python-only test (the shared vectors can't hold it unless `resource-url.ts` rejects it too).
  (2026-11-10)

- **The scanner's CKAN client ignores `CKAN_USER_AGENT`.** `services/scanner/client.py` sends a
  hardcoded Chrome User-Agent, while the builder's fetches (`services.shared.ckan.user_agent()`) use
  `govdata-builder/1.0` or the env override. A WAF change then needs a code change for the scan and
  the reconcile probes. Fix: have the scanner call `shared.ckan.user_agent()` too, after checking
  from Cloud Run that the builder UA passes the CKAN API for the scan's calls. (2026-11-10)

- **Blank CKAN resource formats are inferred only at render time.** Some resources have an
  empty `format` (02789da8 and d6b5032b .docx docs, 0180a8e4 .rar on 2026-11-10); the frontend's
  `resourceFormat()` (`frontend/utils/resource-url.ts`) falls back to the URL extension for the
  download badge, explorer and JSON-LD `encodingFormat`, but Firestore and the manifest's
  `formats` stay blank. Fix: the same fallback in the scanner (`services/scanner/models.py`, next
  `Dataset.from_ckan_response`), keeping the frontend helper as its mirror. (2026-11-10)

- **Raster map layers have no input type.** 022552b2 (מפות מפלסים ומליחות באקוויפרים, a top
  no-recipe page by search clicks) ships only zips of yearly GeoTIFFs: coastal-aquifer water
  level 1954-2023 (70 files, 85MB) and chloride 1977-2020 (35 files, 38MB), 527×1250 float32
  cells in ITM. `geo_snapshot` reads vector formats only, so no recipe can read it. Fix: a
  `raster: true` input that turns each GeoTIFF in a zip into a per-year summary table (mean,
  percentiles, cells over a threshold) plus an optional coarse grid. Pillow opens these files;
  ship a TIFF reader in the builder image and redeploy before authoring. (2026-11-09)

- **Sources ingested before `datastore_active` existed can't be authored.** Their Firestore
  `resources[]` has no `datastore_active` key, and the scanner rewrites a source only when
  `metadata_modified` moves, so `author prepare` selects nothing and a `by_id` recipe would fail
  `schema_changed`. `backfill_datastore_active --dry-run` listed 23 such sources on 2026-11-09;
  ebe5ec6f was fixed by hand on 2026-11-10 (one `set_resource_datastore_flags` call), leaving 22.
  Fix: run the backfill with `--write` (without it, it only lists them; with it, it writes prod
  Firestore) before authoring any of them. Its write (`set_resource_datastore_flags`) reads the
  doc and writes it back outside a transaction, so a scan landing in between can be overwritten:
  run it when no job is running, or move the write into a Firestore transaction. (2026-11-09)

- **The preview's Tailwind misses classes added after the dev server started.** A chart height
  like `h-[30rem]` that no page had when `preview` started renders at 0px until
  `preview stop` and a restart. Production builds are unaffected (they scan every body at
  once), but authors waste fix rounds on it. Fix: have `preview` restart the dev server, or
  touch the Tailwind config, when a newly rendered body adds unseen classes. (2026-11-09)

- **A long resource name widens the page on mobile.** The data explorer's resource pill
  (`.explorer-pill`, `frontend/public/lib/gov-explorer.js`) doesn't wrap or truncate, so on
  7a6d0673 ("מדינות מאוחד (קוד בינלאומי, שם…") the page scrolls sideways by 40px at 375px.
  Fix: `max-width: 100%` with ellipsis (or wrapping) on the pill label. (2026-11-09)

- **The sanitizer's tag counter misreads some literal shapes, and a miscount fails the render.**
  `_balance_raw_text_tag` (`services/page_builder/sanitize.py`) counts `<script>`/`<style>`
  openers and closers by regex after removing `<!--…-->` across the whole body, and refuses the
  page when they differ. Inside a script `<!--` is plain text, so a JS string holding `"<!--"`
  with a later `-->` hides every tag in between; `<script`/`<style` text inside a JS string, an
  attribute value or a `<textarea>`/`<title>` counts as a tag; so does a custom element named
  `<script-…>`. No template or rendered body has these, and data can't produce them (autoescape,
  `tojson`), so they would show up at `author verify`, except behind a data-dependent `{% if %}`.
  The legacy body 5beb2241 (ends `</script></script>`) would fail if it were ever sanitized
  again. Fix: scan tags in order as the tokenizer does (no comment stripping inside raw-text
  blocks, no tags inside attribute values or RCDATA), and require `[\s/>]` after the tag name in
  `_OPEN_SCRIPT`/`_OPEN_STYLE`. (2026-11-08)

- **Two live pages for the "חברה ורווחה" journal.** 1ba21c94 (legacy agent page) and e4c3e3d0
  (recipe) are both active on data.gov.il and split the "חברה ורווחה" impressions (56 vs 14 a
  week, both at position 7.3). Neither can 301 to the other while both exist upstream. Fix: if
  the CSVs turn out to be the same journal index, give 1ba21c94 a recipe that points readers to
  the other page, or add a successor entry once one of them is removed. (2026-11-06)
- **Legacy pages with search traffic and no recipe** (GSC, 7 days to 2026-11-05): dff8a168
  (13 clicks), 51227f7b, 945b3682, 41c2db9f, 2987efb0, 3a4c012f, 8b3d9aa2 (1d2d0ec1 and
  65dafbb0 got recipes 2026-11-06: compare their CTR at the same check). The selector never queues them while their data stays put.
  A recipe is not sure to win more clicks for pages that already rank, so these wait for the
  batch 1-2 CTR check (~2026-12-02); then open `gsc_traffic` issues as for #338-#344.
  (2026-11-06)
- **Most recipes still don't set `agent_data.seo`.** Batches 1 and 2 (the 41 recipes with the
  most GSC clicks lost to low CTR, 90 days to 2026-11-03) have it; the other ~276 keep their CKAN
  titles (some over 60 chars, 45 summaries over 160) and a " · ministry" suffix. Fix: next
  batches in the same order (missed clicks = impressions × (expected CTR at position − actual
  CTR)). Batch 3 (21 recipes, 2026-11-06) took ranks 1-20 of the 90 days to 2026-11-05 plus
  df60d73b. Batch 4 (11 recipes, 2026-11-06) took the 10 ids batch 3 named plus 246d949c
  (רשם החברות). Re-ranked over the same 90 days with a page-level curve (expected CTR
  28/15/11/8/6.5/5/4/3.2/2.7/2.4% at positions 1-10, interpolated), the next are b72acc9a,
  0b160f8a, a63133ab, e3f2eab4, e9b65317, 27b4b40e, b87ef422, dcd96625, 6397d78e, 83372c35;
  bump each `recipe_version`. Batch 4 pages each missed only ~4-7 clicks per 90 days, so
  compare batches 1-4's CTR in GSC (~2026-12-02) before spending on the long tail. (2026-11-06)
- **59d2e891 and df60d73b compete for "אזורי חיוג".** Batch 3 gave df60d73b (numbering plan,
  which has the geographic codes) a title for "אזורי חיוג בארץ" / "קידומת טלפון ישראל", but
  59d2e891 (service numbers, no geographic codes) still has "קידומות ואזורי חיוג" in its title
  and holds those queries at ~position 8.7. Fix: once GSC shows where df60d73b lands (~4 weeks
  after #368), drop "אזורי חיוג" from 59d2e891's title if df60d73b ranks at least as well.
  (2026-11-06)
- **`author verify`'s dash lint misses dashes built in f-strings.** An en dash between two
  interpolated numbers (`f"{a}–{b}"`) in Hebrew text renders reversed in RTL, but the lint only
  sees literal text. Batch 2 found several by hand (7a6cbf55's bucket labels and periods). Fix:
  lint the rendered page model's strings (outside `dir="ltr"` spans) instead of the source.
  (2026-11-05)
- **Some registry pages have no lookup callout to `#data-explorer`.** 14f2521f (missions abroad),
  d08d4a17 (notaries) and 35c791ca (licensed garages) are lookup-intent pages whose searchers
  want one row, but the page doesn't point them at the explorer. Fix: add the callout the #124
  pass added to the other lookup pages, and bump `recipe_version`. (2026-11-05)
- **The map reader can't open a zip of zips.** ee626064 (משרד הבינוי והשיכון GIS layers)
  ships its fourth layer, מחיר למשתכן (`gis_dira.zip`, 9.2MB), as a zip holding
  `Lots_view.zip`, `Plans_view.zip`, `Projects_view.zip` and `Settelments_Centroid_view.zip`.
  `geo_snapshot` reads only top-level shapefiles, so the recipe skips that layer and says so in
  fixed copy. Fix: let `geo_snapshot` descend one level into nested zips (with the same size
  caps), then add a `mehir` map input to ee626064 and bump its `recipe_version`. (2026-11-04)
- **One broken datastore resource blocks every `by_schema` input of its dataset.**
  `resolve_inputs` raises `PreviewUnavailable` when any datastore-active resource's preview fails,
  even one that never had the input's columns. A resource whose datastore answers
  `success: false` for good (it used to be skipped) now fails the page and, after
  `REFRESH_TRANSIENT_STRIKES` runs, opens a `schema_changed` issue that re-authoring with
  `by_schema` can't clear. Fix: let a recipe exclude resource ids from `by_schema` matching,
  or ignore an unanswered resource whose CKAN name/format can't be a match. (2026-11-02)
- **`sandbox_failed` never escalates.** It opens no issue and keeps no strike count, so a spawn
  abort that turns deterministic (an image that loses `GRPC_ENABLE_FORK_SUPPORT=0`) freezes
  every page with only log lines. Fix: raise `_SpawnFlake` as a `refresh.StrikeError`
  (`strike="sandbox_failed"`, an `escalate_to` reason added to `AUTHORING_REASONS` and
  `notify.REASON_TEXT`); the `transient_strikes` counter does the rest. (2026-10-31)
- **Top-100 legacy map pages that the snapshot path can't serve.** חלקות (dff8a168, 667MB SHP)
  is a national layer far over the 100MB download cap; it would need a pre-aggregation step
  (the גושים/תצ"ר recipes reduce each polygon to a centroid in compute, but the file must still
  download and convert). הגבולות המשטרתיים (d01a5ee3) and קדסטר במבנה חדש (bd74ce49) ship an Esri FileGDB, which
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
  and `selector._skip` each branch on `src.provider`. A new CKAN-shaped path that
  forgets the branch treats a provider doc as CKAN. Add a `CkanProvider` adapter around the
  existing CKAN fetch/probe functions and one `provider_for(src)` that always returns a provider,
  so those paths dispatch instead of branching. (2026-10-30)
- **`news/data.py` re-implements the refresh's provider branch and compute input spec.**
  `DatasetTables._load` calls `refresh.fetch_inputs` and then rebuilds the provider
  dispatch and the `load_frames` spec by hand, so a refresh change to either can drift from what
  the news job's SQL tables hold. It is also the last `news → page_builder` dependency that
  keeps the two packages in an import cycle with `publish.py → news.publish_news` (with
  `news/run.py`'s `recipe_repo_from_env` and `news/ledger.py`'s `govlib.fmt`). Fix: one
  `refresh.load_input_frames(recipe, src, …)` both call, and move `recipe_repo_from_env`'s repo
  classes and `govlib.fmt` somewhere both packages may import. (2026-11-10)
- **Two writers build `sources/<id>.resources[]` by hand.** `FirestoreStateStore.save_dataset`
  (CKAN) and `providers/sync.py` (provider docs) each assemble the resource dicts, so a field
  added to one (a new CKAN fact, a renamed key) silently goes missing from the other. Fix: one
  resource-doc builder in `services/shared` both call, with a golden-dict test per source kind.
  (2026-11-10)
- **`mark_refreshed` still writes the legacy `analysis_*` fields.** `analysis_status`,
  `last_analyzed_at`, `analyzed_metadata_modified` and `last_analyzed_version` are agent-builder
  names that the selector and publisher still read as "this source has a live page and its data
  vintage". Fix: move those readers to `refresh_status` / `refreshed_metadata_modified` (legacy
  pages keep their old fields), then stop writing the `analysis_*` copies. (2026-11-10)
- **`SourceRecord` holds some refresh fields twice.** `authoring_status`, `authoring_issue` and
  `agent_data` are top-level `SourceRecord` fields (the selector and publisher read them) and also
  in `src.refresh`; `get_refresh_state` still returns a raw dict that `queue_authoring` wraps in
  `RefreshState`. Fix: move those readers to `src.refresh`, drop the top-level copies, and have
  `get_refresh_state` return a `RefreshState` (the test `FakeStore`s follow). (2026-11-10)
- **`record_count` means different things per source kind.** The scanner stores the primary
  resource's datastore total (CKAN), provider sync stores the sum over all series. Pages and the
  manifest show both as "records". Fix: pick one meaning (or store both, named), and say it in
  `schema.DatasetMeta`. (2026-11-10)

- **65dafbb0's map input sits near the 50MB `map_max_kb` ceiling.** The תצ"ר layer converts to
  49.2MB at tolerance 2e-5, and its floor is 37.6MB (at 2e-4; coarser steps grow again as small
  rings fall back to full detail). About a third more plans and it fails `too_large`. Most of
  the bytes it can't shed are properties the recipe never reads (TALAR_COMM, the ITM bounding
  box, dates): let a `map` input take `columns` to drop properties before sizing (a recipe.py
  change, so it folds into every recipe's hash; redeploy before a recipe uses it). (2026-11-06)

- **More recipes carry their own map chunking or simplification.** 1745d2f8, 2a795952, 4eef54bc,
  5ecf0587, 12fb4671, 6910f861, 1de95a22, 3ce41381, 4acf8b98, 8f2becb2, a98fbabc, 0b3bd728,
  3c6d4061, 6cd898c4, 7cac04c9, d9b1e04c, fc549bf6, 1d2d0ec1 and 65dafbb0 define their own island chunking, DP or
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

- **Failures that repeat every run but count as transient never escalate.** Only `StrikeError`
  and wall-budget overruns keep a strike count. A plain `fetch_failed` (a required resource that
  "has no rows", an export that comes back short every run, a table that grows during every
  multi-page walk so the export always "moved during the export") and a generic exception
  recorded as `error` open no issue and set no lock: the page stays last-good with only log
  lines, and every run repeats the full export and compute. (A check.py timeout is the opposite
  case: it fails as `recipe_failed` and locks on the first timeout, so a page that flaps around
  the 60s limit would also be better served by a strike count.) Fix: count them in `transient_strikes` (one strike key per kind, reset when
  `failed_version_key` moves) and escalate after `REFRESH_TRANSIENT_STRIKES` runs
  (`schema_changed` or `too_large` for a fetch, `recipe_failed` for an error). (2026-11-11)

- **A code bug that fails every source can end the run green.** `run_refresh` turns an
  exception from `needs_refresh` or `refresh_one`'s set-up into that source's `FAILED`/`error`
  outcome, so a bug that hits every source ends the run `ok`/`idle` (exit 0) instead of
  `refresh_failed`. Fix: end the run `refresh_failed` when every attempted source failed with
  `error` (or above a share of them). (2026-11-11)

- **A GCS-only outage can hide behind `unchanged` outcomes.** `_count_staging` resets the
  `staging_down` streak on any `refreshed` or `unchanged` outcome, and an `unchanged` one writes
  Firestore but uploads nothing. On a day of mostly no-op bumps, upload failures between them
  never reach 3 in a row: the failed pages stay last-good and retry, but the run ends green.
  Fix: count upload failures apart from Firestore writes, and reset that streak only on a
  successful upload. (2026-11-11)

- **A persistent WAF block on a preview escalates as `schema_changed`.** A 403 without CKAN's
  Authorization Error body is a failed preview, counted as a `preview_unavailable` strike, so
  after `REFRESH_TRANSIENT_STRIKES` runs the issue says the schema changed and sends the author
  looking for a column that never moved. Fix: a strike key for 403-blocked previews that
  escalates to `download_blocked`. (2026-11-11)

- **The export's closing re-preview ignores the fetch deadline.** `_check_unchanged`
  (`ckan_export.py`) runs one more `fetch_resource_preview` after a multi-page walk without
  checking `deadline`, so a walk that finished just in time can overrun the wall budget by up to
  ~20s. Negligible today; check the deadline first if budgets get tight. (2026-11-11)

- **A failed rollback can leave GCS and Firestore describing different renders.** When the
  upload lands, `mark_refreshed` fails and the rollback can't run (the previous body couldn't be
  read, or the restore write failed), GCS holds the new body while Firestore keeps the old
  `agent_data` and hashes. `staging_suspect` blocks only the content-hash skip, and only while the
  latest status is that failure; a later A∧A′ or B skip that matches the old hashes leaves the
  mismatch in place. Fix: when the mark fails with no rollback, also clear the stored
  fingerprints and hashes in the `mark_refresh_failed` call, then drop `staging_suspect`.
  (2026-11-11)

- **The file export holds the raw download and two normalized copies on tmpfs at once.**
  `fetch_resource_csv` keeps the raw file (up to `REFRESH_FILE_MAX_BYTES`, 1.5GB) until its
  `finally`, through normalization and `_patch_rows`, which writes a full `.patch` copy of the
  output. With a recipe's earlier inputs that peaks near 3GB of RAM-backed `/tmp` in the 4Gi job
  (largest file today: 879MB, so this is headroom, not a failure). Fix: unlink the raw file as
  soon as normalization has read it, before `_patch_rows`. (2026-11-11)

- **The sanitizer's JS string walker has no regex-literal state.** `_escape_js_string_controls`
  (`sanitize.py`) reads a quote inside a regex literal (`/'/g`) as the start of a string and
  rewrites the newlines up to the next quote as `\n`, which breaks valid JS (check.py then
  reports JS-SYNTAX for code that is correct in the template). `_SCRIPT_DATA_TYPE` also treats
  `type="text/javascript"` as a data block, so that script skips the repair while check.py
  parses it as JS. No template has either today. Fix: limit `_SCRIPT_DATA_TYPE` to JSON types,
  and walk strings with the esprima tokenizer (or escape only U+2028/U+2029). (2026-11-11)

- **The refresh ignores a provider's failed healthcheck.** The sync skips an unhealthy provider,
  but `fetch_fns`/`preview` never ask `healthy()`, so a provider source with a pending refresh is
  fetched during the outage, records `preview_unavailable` strikes, and after
  `REFRESH_TRANSIENT_STRIKES` runs (about 3 days) opens a `schema_changed` issue and locks until
  the data version moves (weeks for the monthly CBS pages). Fix: when `healthy()` is false, have
  `fetch_fns` raise a dedicated transient error that `refresh_one` records as skipped with no
  strike. (2026-11-11)

- **Recipe error tails go verbatim into public GitHub issues.** A failing compute's last 1,500
  characters of stderr go into the `needs-authoring` issue, and pandas/Python errors quote the
  failing cell value, which can be personal data from a registry. Fix: keep the full stderr in
  the `refresh_outcome` log line only, and put just the exception type and the recipe's own frame
  lines in the issue. (2026-11-11)

- **Status strings are still written as literals outside `states.py`.** `RecipeError`'s default
  reasons and call sites in `recipe.py`, `author.py` and `refresh.py` use `"recipe_failed"`,
  `"schema_changed"`, `"geometry_stale"`, `"preview_unavailable"` and friends as plain strings;
  `staging_down` and the strike keys have no member at all. Same bytes today, but a member rename
  would leave them behind. Fix: use the `FailReason` members, and add members for
  `staging_down` and the strike keys. (2026-11-11)

- **Recipe compute can reach the builder SA's credentials, and those reach too far.** Compute
  runs as its own uid with a scrubbed env, but it can reach the metadata server, and the builder
  SA's grants cover the dispatch-token secret, project-wide Firestore (the `news` database too)
  and the whole staging bucket (`news/`, `models/`). The publisher SA has `datastore.user`
  where it only reads. Fix: condition the builder's `roles/datastore.user` to the `(default)`
  database, give the publisher `roles/datastore.viewer`, optionally condition the bucket grant
  to exclude `news/`, and run compute in a private network namespace so it can't reach the
  metadata server (it gets its inputs as files). Until then CLAUDE.md's sandbox paragraph should
  say what compute can reach. (2026-11-11)

- **The sandbox fails open without its user, and its straggler reaper is narrow.** With no
  `sandbox` user in the image and `SANDBOX_USER` unset, `_resolve_sandbox_identity` warns and runs
  recipe code as root. `_reap_stragglers` kills only processes whose environment still holds the
  session's `HOME`, every compute shares one uid, and `SESSIONS_ROOT` is created world-listable.
  Fix: fail closed inside the job (`CLOUD_RUN_JOB` set) when the default user is missing; after
  each compute kill every process with the sandbox uid; set a low `RLIMIT_NPROC`; create
  `SESSIONS_ROOT` mode 0711. Local authoring without the user keeps today's behaviour.
  (2026-11-11)

- **The local permission allowlist is broad for an unattended routine.** The gitignored
  `.claude/settings.local.json`, copied into every worktree by `.worktreeinclude`, pre-approves
  broad wildcard rules for the GitHub, cloud and HTTP CLIs and for inline Python, and the
  checked-in `.claude/settings.json` has no `deny` list, while the 07:00 routine reads untrusted
  issue text. Fix: a `permissions.deny` list in `.claude/settings.json` covering credential
  output, deploys and merges, raw GitHub API calls, force pushes, arbitrary outbound requests
  and writes to cloud resources; narrow the broad entries in `settings.local.json`; and consider
  not copying it into worktrees. (2026-11-11)

- **Provider brief sections reach BRIEF.md unfenced.** CBS `brief_section` prints sheet cells
  through `_md()`, which escapes only `|`; BoI `SERIES_NAME_HE` and CBS index `NAME_HE` go into
  markdown tables raw. They come from official feeds, not CKAN, but a multi-line Excel header
  cell breaks the table row or starts a line with `#`. Fix: collapse whitespace in every
  provider cell, or fence each provider section as a whole in `_brief`. (2026-11-11)

- **`author prepare`'s stray-file check misses a symlinked directory.** `_stray_file_findings`
  skips anything `is_dir()` (which follows symlinks) and `rglob` doesn't descend into it, so a
  symlink to a directory in `recipes/<id>/` isn't flagged and a hand-made PR could commit it.
  Fix: check `is_symlink()` before the directory skip. (2026-11-11)

- **A mistyped id in the routine's staging loop stages nothing, silently.** In
  solve-authoring-issues step 6, `jq` fails for a wrong id, the loop goes on, and that recipe
  stays untracked; the `git status` check doesn't flag `?? recipes/<id>/`, so the PR closes the
  issue without the recipe. Fix: after the loop, stop when any batch id has nothing staged
  (`git diff --cached --quiet -- "recipes/$id"`). (2026-11-11)

- **The routine's open-PR scan matches only `Closes #N`.** A same-repo PR that says
  `Fixes #N`, `Resolves #N` or `closes: #N` no longer keeps its issue out of the batch, so that
  dataset can be authored twice. Fix: match GitHub's closing keywords
  (`(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#([0-9]+)`). (2026-11-11)

- **`test_skills.py` checks only lines that start with `gh pr list`.** A PR read written as
  `gh pr view`, `gh api …/pulls`, `rtk gh pr list` or inline in prose would pass without the
  `isCrossRepository` filter. Fix: check every line matching
  `\bgh (pr (view|list|checks|diff)|api)\b`. (2026-11-11)

- **The CLI dataset-id check accepts a trailing newline and any length.** `_UUID_RE` and
  `_PROVIDER_ID_RE` (`author.py`) use `re.match` with `$`, which also matches before a final
  `\n`, and the provider form has no length cap (a 5,000-character id fails later with
  ENAMETOOLONG). Neither can leave the directory. Fix: `fullmatch` and a `{1,80}` cap.
  (2026-11-11)

- **`simplify_features` raises `IndexError` on over-deep coordinates nobody checked.** The
  belt in `geo_snapshot.simplify_features` catches `KeyError`/`TypeError`/`ValueError` only. The
  production path rejects such a geometry first (`_checked`: "bad position"), so only a direct
  caller can hit it. Fix: add `IndexError` to the tuple. (2026-11-11)

- **Providers read bodies through httpx's private `Response._content`.** The capped read in
  `services/providers/base.py` assigns `r._content`; an httpx upgrade that renames it breaks
  every provider read (the provider tests would catch it at once). Fix: return the bytes
  alongside the response instead of writing the private field. (2026-11-11)

- **The providers' per-run download cache is never cleared.** `SourceProvider._cache` keeps
  every provider dataset's normalized CSV in memory for the whole job run; nothing calls
  `clear_cache()`. Fix: clear each enabled provider's cache after `run_refresh`, or drop a
  source's entries once its refresh is done. (2026-11-11)

- **The datastore page walk has no per-page retry.** `fetch_resource_records_to_file`
  (`ckan_export.py`) calls `_fetch_page` once per page, so one transient error (a timeout, a reset,
  a 5xx) discards a whole multi-page export, and the end-of-run retry starts again from row 0.
  Fix: retry a failed page a bounded number of times (with a short backoff, inside the wall
  budget) before failing the export; the post-walk re-preview already catches a table that moved
  between pages. (2026-11-11)

- **Every GCS read or write builds a new `storage.Client()`.** `_write_gcs` and `_read_gcs`
  (`refresh.py`) create a client per call, about four per refreshed source (the previous body read
  for rollback, the body, two model-history objects), each with its own auth and connection setup. Fix: reuse one client per run,
  after checking it is safe across the sandbox spawns (the gRPC fork abort behind
  `sandbox_failed`, see CLAUDE.md layer 5). (2026-11-11)

- **A snapshot input's resource rename can still fingerprint-skip.** `input_fingerprint` and
  `file_fingerprint` add only `[name, by_id, "snapshot"]` for a snapshot input, not its CKAN
  resource name, so in `full` mode a bump that only renamed that resource (other inputs unchanged)
  skips until the 14-day max age forces a render. Rare, and bounded like check A's other blind
  spots. Fix: add the resolved resource's name for snapshot inputs too. (2026-11-11)

- **A provider lookup in `refresh_one` sits outside its `try`.** `provider_for_key` runs before
  the guarded block, so if it ever raised, the batch guard would record a bare `error` instead of
  a provider outcome; settings errors no longer reach it, so this is defence in depth. Also, a
  provider dropped for bad settings shows up downstream exactly like a disabled one
  (`provider_disabled:<key>`), with one ERROR log line as the only signal. Fix: move the lookup
  inside the `try`, and give a provider dropped for bad settings its own skip reason.
  (2026-11-11)

- **check.py's SCRIPT-URL rule still fires on data in attribute values.** The security rules now
  skip string literals in code, but attribute values stay scanned, so a template that puts a data
  value in `title="{{ v }}"` fails when the value happens to read like a `javascript:` URL.
  Fix: decide whether attribute values written from autoescaped data can be exempted (for
  non-URL attributes only), or tell authors to keep data out of attributes. Separately,
  `test_check_security.py`'s `_DATA_TEMPLATE` puts autoescaped `{{ model.v }}` inside a JS
  template literal (autoescape doesn't touch a backtick or `${`): switch it to
  `{{ model.v|tojson }}` so the test doesn't model a pattern recipes must not copy. (2026-11-11)

- **check.py's non-recipe mode has no production caller.** Since the agent builder was retired,
  every caller passes `--recipe` (`refresh.py` via `page_gate.run_host_check(..., recipe=True)`),
  so `check_percent_consistency` (the one rule gated on `not recipe`), the `--recipe` flag and
  `run_host_check`'s `recipe=False` default are dead; only one test (`test_local_sandbox.py`)
  still runs that mode. Removing it is safe. check.py is folded into the failure-lock hash
  (`_builder_code_hash`, not the render-code hash), so it retries every locked source once after
  the deploy: do it in a builder-code change that moves that hash anyway. (2026-11-11)

- **`by_schema` drops same-named resources of the same format.** `select_prefetch_resources`
  (`services/shared/resources.py`) collapses resources whose normalized names match, meant for
  CSV/XLSX twins, but it also drops a second CSV with the same name: three monthly CSVs all named
  `דוח חודשי` resolve to one, with no error, and `author prepare` hides them the same way. Fix:
  collapse only when the formats differ. It can change what existing pages read, so first list
  the recipes whose match set would grow (needs the live `sources/*` docs). (2026-11-11)
- **`author prepare` fetches with different caps than the refresh.** `author.py` `prepare` passes
  `_DEFAULT_PAGE_SIZE` (ignores `REFRESH_PAGE_SIZE`), takes its wall budget from
  `_PREPARE_WALL_S` (not `REFRESH_WALL_BUDGET_S`) and applies no `REFRESH_TOTAL_BYTES` budget
  across inputs, so a recipe can pass authoring and fail `too_large` in the job. Fix: decide
  which differences are meant, and take the rest from `refresh.resolved_limits`. (2026-11-11)
- **A typo in `SCAN_LIMIT`, `AUTHORING_NOTIFY_CAP`, `MAX_AGE_DAYS` or `MIN_MODIFIED_FLOOR`
  crashes the run.** `PipelineSettings.from_env` (`pipeline.py`) parses them with bare `int()` /
  `fromisoformat`, while `RECONCILE_WEEKDAY` warns and uses its default. Fix: pick one behaviour
  (a loud failure is defensible for a floor date) and use `shared.env.env_int` where a default
  is safe. (2026-11-11)
- **`refresh_one`'s crash branch omits `elapsed_s`.** The generic `except Exception` outcomes
  (`STAGE_FAILED` and `ERROR`) don't set it; every other outcome does, so the `refresh_outcome`
  log line lacks the duration exactly for the runs worth timing. (2026-11-11)
- **The Hebrew maqaf glues words in slugs.** `services/shared/slug.py` strips U+0591-U+05C7 as
  niktud before the maqaf (U+05BE) rule can split on it, so "תל־אביב" becomes `תלאביב`. A fix
  changes `page_slug` for every title with a maqaf: count them in the manifest first and rely
  on the slug-redirect map. (2026-11-11)
- **`map_backfill open` comments again on every re-run.** An issue it opened is found on the
  next run, classified `comment`, and gets the same text posted again
  (`services/page_builder/map_backfill.py`). Fix: skip when the issue already holds the map
  details. (2026-11-11)
- **The live `govdata-publisher-image` trigger still watches the old requirements file.**
  `infra/Dockerfile.publisher` installs `requirements-publish.txt` since 2026-11-11 and
  `infra/bootstrap.sh` prints the matching `--included-files`, but the trigger that exists in
  GCP was created with `services/page_builder/requirements.txt`. Fix: update the trigger's
  included files (`gcloud builds triggers update`), or an edit to the publish requirements
  won't rebuild the image. (2026-11-11)

## CBS reports (cbs_releases provider)

- **Yearly CBS reports (~50) have no pages.** Run `catalog --months 38` to find the ones
  published in two or more years; skip holiday collections ("לרגל …"). The release-list window
  (`LIST_WINDOW`) is now 1500 items (~3 years), enough for 2–3 editions of each; deploy the job
  with it before merging a yearly recipe. (2026-11-05)
- **A CBS table dropped from the latest edition freezes its page silently.** `facts()` raises
  when the newest edition lacks a configured `table` stem, so the provider sync fails for that
  dataset every run; the refresh never runs, so no `needs-authoring` issue opens and the page
  stays last-good indefinitely (only the run summary's `provider sync … failed` shows it).
  Fix: have the sync open an issue (or record a strike that escalates like
  `REFRESH_TRANSIENT_STRIKES`) after N consecutive `provider_error`s for one dataset.
  A table marked `"optional": true` in source.json no longer fails the sync this way.
  (2026-11-05)
- **Year-end CBS editions with a different table set are skipped.** `cbs-visitor-arrivals`
  and `cbs-israelis-departures` skip the January "בשנת YYYY" edition, which replaces December's
  and adds tables. `cbs-labour-supply-demand` skips the Oct–Dec "ושנת" edition (90 files). Each
  page lags one period a year (the page says so). Fix: a second report config per recipe for
  the year-end edition (its own table map), or have compute read either layout.
  (2026-11-05)
- **`cbs-foreign-trade-by-country` lists t6 and t8 but never reads them.** They are the NIS
  twins of t5/t7, kept as downloads. Each is still fetched every run, and a missing stem fails
  the whole page's sync (item above). Drop them from `source.json` if the downloads aren't
  worth that, or mark them `"optional": true` (the flag exists now). (2026-11-05)
- **Existing CBS recipes don't use the new provider features yet.** Once the job runs a build
  with them: mark the chart sheets that come and go `"optional": true`
  (`cbs-dwelling-transactions` t8, `cbs-construction-starts` t8–t14, `cbs-labour-force-survey`
  t15–t22; compute must accept an empty grid). Add a by-district sales section to
  `cbs-dwelling-transactions` from `t3a`/`t3b`. Swap the 23 copies of the "latest release" sort
  (`RELEASE_DATE`, then `RELEASE_NO` as a string, so "99/2026" beats "100/2026") for
  `cbs.latest_release`. (2026-11-09)
- **Every run downloads every CBS table to version it.** ~0.1s a file now; with ~20 pages × ~5
  tables it costs about a minute a run. If it grows, give `version()` a cheap path that hashes
  the release number + file names and sizes from the folder listing, and download only when
  that moves. (2026-11-05)
- **An honestly sized oversized CBS file fails as a preview, not as `too_large`.** The table
  listing's pre-check (`f["Length"] > max_bytes` in `cbs.py`) raises a plain `ProviderError`,
  which `preview` turns into None, so the refresh records `preview_unavailable` and later
  `schema_changed`; a file whose listing understates its size gets `too_large` from the capped
  read. Fix: raise `ProviderTooLarge` from the pre-check too. (2026-11-11)

## Shared recipe code (govlib, gov.j2, page libs)

Recipes adopt the shared code as they're next touched. Each item below is a copy-pasted helper
family found in the corpus survey of 2026-11-01, with the behaviour it should converge on.

- **`GovEcharts.option` merges shallowly.** A page's own `tooltip` or `grid` object replaces
  the shared one whole, so the shared tooltip style (Rubik, white background, RTL) never applies:
  every chart page passes its own `tooltip`. Fix: deep-merge `tooltip` and `textStyle` in
  `option()`. It changes how every chart's tooltip looks, so check a sample of pages first.
  (2026-11-01)
- **Tooltip escaping still has gaps the runtime belt can't close.** The gov-echarts.js belt
  escapes the params' label fields and, deeply, `data`, `value` and the tree path arrays, but
  a string nested past its depth cap is returned unescaped, a `tooltip` set under a tree
  node's `children` or a series' `levels` is not wrapped (no recipe sets one today), and it
  can't reach strings a formatter reads from its own closure (the heatmap formatters'
  `h.y[p.value[1]]`). Fix: escape past the cap instead of passing through, wrap tooltips under
  `children`/`levels`, and for closure strings export an escape helper from gov-echarts.js, use
  it in the formatters that append a model string (about 26 templates) and make that an
  authoring rule. (2026-11-01)
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

## Frontend

- **Shared dataset links preview with the generic image.** Dataset pages set no `ogImage`, so
  every link shared from the new share button (`components/ShareButton.vue`) shows
  `/og-default.png` in WhatsApp/X/Facebook cards. News articles use their hero. Fix: a
  per-dataset og:image (e.g. a build-time card with the title and one headline number) passed
  to `useSeo` in `pages/datasets/[slug].vue`. (2026-11-10)

- **The shared `node_modules` lacks `vue-tsc`.** `npm run typecheck` fails locally ("A type
  checker is required") although `package.json` lists it; the main checkout's install predates
  it. Fix: `npm ci` in the main checkout's `frontend/` (not in a worktree). (2026-11-10)

- **First-pass chart and map instances leak on every dataset page.** The browser runs the SSG
  body's scripts once before Vue re-sets the article, and `executeBodyScripts` disposes only
  instances in the new container, so the first ECharts/Leaflet instances stay alive, held by the
  resize listeners the bodies register (GovMap's duplicate fetch loop now stops). Fix: have
  gov-echarts.js remember the instances its patched `echarts.init` creates, and dispose those
  whose `getDom().isConnected` is false. (2026-11-11)

- **GovMap stops on engines without `Node.isConnected`.** `gov-map.js` checks
  `!container.isConnected`, which is true on engines that lack the property (EdgeHTML 18 and
  older), so every map there stops after its first step. Fix: `container.isConnected === false`
  at both sites. (2026-11-11)

- **Enter in the header search opens the first hit, though the footer says all results.**
  `HeaderSearch.vue` highlights the first result whenever there is one, so Enter goes to that
  dataset; the "/datasets/?q=" list opens only when nothing matched, while the footer reads
  "הקשה על Enter תפתח את כל התוצאות". Fix: start the highlight at -1 (Enter opens the full list,
  ArrowDown picks a hit), or change the footer text. A product choice. (2026-11-11)

- **IndexNow resubmits every URL on every deploy.** `frontend/scripts/indexnow-ping.mjs` posts
  every `<loc>` in the sitemap (~1,100 URLs) after each deploy, two or three times a day plus
  every push-to-deploy, while the protocol asks for changed URLs only; engines throttle or
  discount mass resubmission. Fix: keep the last ping time (an actions/cache entry, or the live
  sitemap fetched before deploy) and submit only URLs whose `<lastmod>` is newer. (2026-11-11)

- **The publish cache can carry stale `index.html` and orphan dataset dirs.** `publish.yml`'s
  "Drop cached publisher JSON" step deletes only `data.json`/`agent_data.json`, while
  `infra/sync-datasets.sh` also deletes `index.html`; the rsync excludes `index.html`, so a cached
  one could linger under `public/datasets/<id>/`. A staged body whose dataset has no manifest
  entry is still copied into the deploy by `nuxt generate`. Fix: delete `index.html` in the same
  step, and have the publisher remove dataset dirs with no manifest entry. (2026-11-11)

- **Header search shows "אין תוצאות" while the index loads or after it failed.** A failed load is
  retried on the next open, but there is no loading or retry hint, and the hub pages' 503 path for
  a failed index fetch has no automated test (it lives in an SFC). Fix: a loading state and a
  "try again" line in `HeaderSearch.vue`, and move the hub's fetch-failure branch somewhere the
  `node --test` suite can reach. (2026-11-11)

- **Explorer search misses cells spelled without the geresh/gershayim.** `buildTsQuery`
  (`frontend/utils/explorer-query.ts`) turns `בע"מ` into the phrase `בע <-> מ:*`, which matches
  cells written with the mark, but not `בעמ`. Fix: emit `(בעמ:* | בע <-> מ:*)` for such words,
  after checking the live counts as for the phrase form. (2026-11-11)

- **The "updated since the analysis" icon compares UTC days.** `sourceUpdatedSinceAnalysis` in
  `pages/datasets/[slug].vue` reduces both dates to UTC calendar days, so near midnight Israel
  time a same-day update can show or hide the icon wrongly. Fix: compare Asia/Jerusalem days.
  (2026-11-11)

- **List pages ship every card twice.** `/datasets/` is 1.29MB of HTML (139KB brotli): 590
  server-rendered cards plus the 559KB slim index inlined as payload; `/kinds/registry/` is
  668KB. Hub payloads carry whole `SlimEntry` objects though `DatasetCard` reads a few fields.
  Fix, in rising effort: project hub payloads to card fields, render only the first ~60 cards
  with "show more", or make the card lists server-only components. Header search also fetches
  the index again on `/datasets/` (seed `searchIndexCache` from the page's data). (2026-11-11)
- **`firebase.json` commits ~2,800 lines of redirects that every deploy overwrites.**
  `gen-redirects.mjs` rewrites `hosting.redirects` from the manifest, and `publish-local.sh`
  leaves the tracked file modified in the main checkout. Fix: commit `"redirects": []` and
  deploy from a generated, untracked config (`firebase deploy --config`). (2026-11-11)
- **`gov-explorer.js` is ~300 lines behind a no-op.** `normalizeAgentBody` strips every legacy
  explorer section, so `GovExplorer.create` always returns at its missing-container check (15
  of 555 bodies call it, all stripped, on a 2026-10-30 corpus copy). Fix: re-check against the
  current GCS corpus, then replace the file with a stub `create`. (2026-11-11)
- **Small accessibility and markup gaps.** Header search: Escape and arrows work only while the
  input has focus, and the highlighted result isn't exposed (`aria-activedescendant`).
  `/datasets/` filter buttons lack `aria-pressed` and the search input has no label text. Every
  page's `WebSite` JSON-LD carries that page's description (`useSeo.ts`). (2026-11-11)
- **A failed manifest read sticks for the whole build.** `loadFullManifestServer` caches the
  rejected promise, so one transient read error fails every later page of the same
  `nuxt generate`. Fix: clear the cache on rejection. (2026-11-11)

## Dependencies

- **ECharts 6 migration.** The moderate ECharts advisory is fixed only in 6.x, a major bump for
  the runtime every page body uses. No published page uses the affected series type, so this is a
  planned migration, not an urgent fix: do it with a corpus-wide visual check. (2026-10-30)
- **Dependabot alerts with no fix to take.** deepmerge (GHSA-gcqx-w48m-w2h4, low, pulled in by
  nitropack's `@rollup/plugin-node-resolve`) has no patched release at all. `npm audit` also
  flags `@opentelemetry/core` <2.8.0 under firebase-tools' `@google-cloud/pubsub` (emulator
  only, not in the GitHub alerts); only a 2.x major fixes it, and overriding across that major
  under pubsub's 1.x pins is unsafe. Fix: take the upstream bumps when nitropack / firebase-tools
  ship them, then drop the matching entry here. (2026-11-08)
- **Pillow's lower bound admits releases with decoder advisories, and nothing pins what the
  images install.** `services/news/requirements.txt` says `pillow>=11`, and the 13.0.0 release
  fixes a long list of decoder advisories; the news job now opens model images with only the PNG,
  JPEG and WebP decoders, which narrows but doesn't remove the exposure. No requirements file has
  a lock, so each image gets whatever pip resolves on deploy day. Fix: `pillow>=13.0.0`, and a
  hashed lock file (`pip-compile --generate-hashes`) that the Dockerfiles and CI install from, so
  Dependabot sees the resolved versions. (2026-11-11)
- **The fallback publisher image runs Python 3.11, the primary path 3.12.** `infra/Dockerfile.publisher`
  installs Debian bookworm's `python3` (3.11), while `publish.yml` sets up 3.12, so the Cloud Build
  path runs `services.page_builder.publish` on a different interpreter than the one CI tests.
  Fix: install 3.12 in the image (e.g. copy it from `python:3.12-slim`, or `uv python install`).
  (2026-11-11)

- **Two unused frontend packages.** `lucide-vue-next` (icons are static SVGs in
  `public/icons/`) and `@types/leaflet` have no import. Remove both and refresh the lockfile
  from the main checkout. (2026-11-11)
- **The builder image still installs `curl`.** `Dockerfile` kept it from the retired agent
  runtime; no code under `services/` or `agent/` calls it, and it is one more binary the
  sandboxed `compute.py` can reach. Fix: drop it after checking no deploy or debug step relies
  on it. (2026-11-11)

## Validation speed

- **`author verify` runs its four compute passes one after another.** The determinism, truncated
  and shuffled passes depend only on the first (full) pass, so they could run concurrently and
  cut verify's wall time about in half. The catch is memory: each pass may use up to
  `REFRESH_COMPUTE_MEMORY_MB` (3GB), so a heavy recipe would need up to 3× that. Fix: a thread
  pool sized by a flag, defaulting to serial for recipes with `limits`. (2026-11-01)
- **The check.py literal-scan timing test has a tight bound.**
  `services/page_builder/tests/test_check_security.py` asserts the 30k-row scan finishes in under
  20s; it takes about 4-5s locally under `-n 4`, and the quadratic version it guards against took
  about 2 minutes. If it ever flakes on a slow CI runner, raise the bound to about 45s rather than
  dropping the test. (2026-11-11)

## News

- **The writer's `fetch_url` gets HTTP 403 from www.gov.il pages.** In the 2026-11-11 explainer
  dry run, all 4 gov.il fetches (contractor classification pages, the doctors' registry service
  page) were refused, so an article can't cite or quote an official gov.il page and the attempts
  waste tool calls (one draft ran out of its budget). boi.org.il was not tested. Fix: find out
  what the site accepts for an identified, polite client (the builder's data.gov.il UA was
  user-approved, see CLAUDE.md layer 5), get the user's approval for that client, and until then
  tell the writer in `prompts/writer.md` that gov.il fetches fail. (2026-11-11)

- **`FirestoreArticles.advance_cursor` is a read-then-write, not a transaction.** Two news runs
  that overlap (a manual execute during a scheduled one) can both read the old cursor, and the
  one with the earlier window can write last, moving the cursor backwards despite the docstring.
  Harmless for duplicates (cooldown + used signal keys) but it re-opens a closed window. Fix: do
  the compare-and-set in a Firestore transaction (`@firestore.transactional`) and teach
  `test_window.py`'s fake db a transaction. (2026-11-10)

- **A news run advances its cursor even when snapshot reads failed.** `run._safe_pair` swallows
  any GCS error per dataset as "no history", so a run during a GCS outage finds no signals, ends
  `idle` and closes its window: those renders never reach a later run. Fix: count read failures
  in `find_signals`' stats and skip `advance_cursor` above a threshold (not on any single failure,
  or one corrupt object would pin the cursor until the lookback cap). (2026-11-10)

- **Chart text skips the length and Hebrew checks.** The gate's number and punctuation checks
  now read chart titles, units, series and bar labels, but nothing caps their length (a
  5,000-character title passes) and the too-little-Hebrew ratio reads the prose only, so an
  all-English chart title passes. Fix: a length cap per chart field and the Hebrew ratio over
  chart text in `gates.check`. (2026-11-11)

- **The number gate refuses proper names that hold a digit.** `כביש 6` or `קו 480` in prose or a
  chart label reads as a typed number and fails the draft, so the writer has to talk around it.
  Fix: an allowlist of name patterns (road, line, route numbers) the number check skips, or a
  writer-side way to mark a proper name. (2026-11-11)

- **A chart year label may use Arabic-Indic digits.** `_YEAR_SPAN`/`_PERIOD_LABEL`
  (`gates.py`) use `\d`, which matches any Unicode digit, so `20٤٥` passes as a year label. It
  still reads as a year, so this is tidy-up: compile them with `re.ASCII`. (2026-11-11)

- **`Decimal` SQL results never become facts.** `tools._is_num` accepts only `int`/`float`, so a
  DuckDB `DECIMAL` (a `SUM` of decimals, a `::DECIMAL` cast) comes back as plain text with no
  fact token and the writer can't cite it. Fix: treat a finite `Decimal` as a number there.
  (2026-11-11)

- **`table_schema` has no total-size cap.** `t_table_schema` returns every column (fenced) plus
  3 sample rows for every table of the dataset, so a very wide table gives a very large tool
  result. `t_sql` stops at `SQL_RESULT_CHARS`; give `table_schema` the same kind of cap.
  (2026-11-11)

- **A rejected story can be rewritten on every run while the window is held.** Rejected drafts
  are not in `recent`, so while the cursor doesn't advance (a held window, an editor failure, a
  crash), the editor can pick a story the gates or the critic rejected (`critic_kill` included)
  again each run, re-rolling the stochastic critic until it passes. The mechanical gates still
  apply and spend per run doesn't grow. Fix: exclude signal keys with a `critic_kill`/gates
  rejection inside the current window. (2026-11-11)

- **A deterministic model error holds the news window open.** A non-retryable 4xx raised at once
  in `llm._post` (context overflow, the Gemini thought-signature 400) or "no message in response"
  holds the cursor like a transient outage, so one story that always fails keeps the window at
  the 168h clamp (a rolling 7 days): more snapshot reads, no duplicates. Fix: hold only on
  retry-exhausted transient errors, or cap the number of consecutive held runs. (2026-11-11)

- **One critic score still crashes `critique`.** `math.isfinite` raises `OverflowError` for an
  integer above ~1e308, which `json.loads` produces from a 309-digit literal; the story then
  falls to `write_day`'s generic `except` as `rejected/error` (nothing published). Fix: catch
  `OverflowError` there, or compare `float(...)` inside a `try`. (2026-11-11)

- **The hero image pixel cap leaves no room for 4K.** `MAX_HERO_PIXELS` (`images.py`) is
  4096×4096 (16.8M); a 4K 16:9 Gemini image (5504×3072, 16.9M) is just over it, so every article
  would silently get the chart card if the request ever asks for `image_size: "4K"`. Nothing does
  today. Fix: raise the cap to about 24M pixels or bound each side (6144) instead. (2026-11-11)

- **`fetch.py` bounds slow response headers only per read.** The fetch's total deadline is
  checked between operations, so a very slow response header or TLS handshake is bounded only
  by the per-read timeout, not by the 60s total. That needs a server on an allowlisted site, and
  the job's task timeout caps it. Fix: a per-hop timeout of
  `min(TIMEOUT, remaining)`, or a watchdog that closes the connection at the deadline.
  (2026-11-11)

- **The fetch address check should also refuse NAT64 and IPv4-compatible IPv6.** Python reports
  `64:ff9b::/96` and the deprecated `::/96` forms as global, so they pass `ip.is_global`.
  Cloud Run's IPv4-only egress can't reach them today. Fix: refuse both prefixes explicitly in
  `fetch.py`, and resolve the host only after `allowed_source` passes. (2026-11-11)

- **The writer can SQL any dataset, and loaded tables stay in memory for the run.**
  `t_sql`/`t_table_schema` accept any `dataset_id`, not only the brief's; each load is a full
  export held in pandas, copied again for typing and into DuckDB, and `DatasetTables._cache`
  keeps every dataset until the run ends in a 4GiB job. The scratch dir is named by the id's
  first 8 characters. Fix: pass the brief's `dataset_ids` to `Toolbox` and refuse others, add a
  row/byte cap for news loads, drop a dataset's frames once its DuckDB table exists, and use the
  full id for the scratch dir. (2026-11-11)

- **A scripted redeploy resets runtime toggles.** `infra/news-job.deploy.sh` defaults
  `NEWS_PUBLISH` to `live` and replaces the whole env set, so a kill switch thrown with
  `--update-env-vars NEWS_PUBLISH=off` turns back on at the next code deploy unless the operator
  exports `off`. `infra/builder-job.deploy.sh` likewise drops a `CKAN_USER_AGENT` override set on
  the live job. Fix: have both scripts keep the live job's value of these variables unless one is
  exported (read it with `gcloud run jobs describe`), or move the news kill switch to a Firestore
  flag a deploy can't touch. (2026-11-11)

- **The `news` database's security rules aren't in the repo.** `firebase.json` deploys
  `firestore.rules` (deny all) to `(default)` only; the `news` database, created by
  `infra/news-iam.setup.sh`, keeps whatever rules it was created with. Fix: list both databases
  in `firebase.json`'s `firestore` config with the same rules file and deploy them with
  `firebase deploy --only firestore:rules`. (2026-11-11)

- **An oversized article or reject document can't be stored.** `ledger.dump()` (every fact any
  tool call registered, not only the printed ones) goes into `body_json`; about 13 full SQL
  results reach Firestore's 1MiB document limit. Since 2026-11-11 a failed reject write no
  longer costs the day, but an accepted article that large fails every run
  (`status: store_failed`). Fix: store only the facts the article references (plus their
  `calc` ancestors), or cap the ledger and tools log by size. (2026-11-11)
- **A live run goes ahead with an empty catalog.** `catalog.py` fails soft to `{}`, so a live
  run then writes with no titles, publishers, demand or explainer candidates and still closes
  its window. Fix: in live mode treat an unreadable catalog as a failed run. (2026-11-11)
- **`calc` combines any two facts.** `ledger.py` `sum`/`diff`/`ratio` accept a count and a
  percent, or facts of two datasets, and the result is a valid token. Fix: refuse `sum`/`diff`
  across differing `unit` or `dataset_id`, and show calc provenance to the critic. (2026-11-11)
- **Watch the stricter number gate's reject rate.** Since 2026-11-11 the gate also fails
  quantities in words ("חמש מאות דירות", "פי שלושה", "חצי מהתושבים", a bare "מיליון שקלים") and
  thresholds or clock times in words. Compare `admin list --rejected` for the two weeks after
  the deploy with the two before; if stories die on phrasing the writer can't tokenize,
  loosen that rule in `ledger.spelled_numbers`. (2026-11-11)
- **"מאות אלפי" fails the number gate though the writer prompt allows vague magnitudes.**
  `_SPELLED` (`services/news/ledger.py`) reads "מאות אלפי נוסעים" and "מאות מיליוני שקלים" as a
  number word plus a unit, and "לכל מאה אלף תושבים" the same way, while the prompts say words
  like "עשרות" and "אלפי" are fine. Fix: decide whether these are vague (a lookahead in
  `_SPELLED`) or figures (say so in `prompts/writer.md` and `style_he.md`). (2026-11-11)
- **The scanner no longer retries a 4xx, and data.gov.il's edge can turn an origin error into
  a 404 page.** A CKAN 409 was seen arriving as an HTTP 404 HTML page on 2026-11-11. If an
  origin 5xx is rewritten the same way, `package_search` fails on the first try and the scan
  ends `scan_failed` (the next run retries). Fix: capture what a real origin 5xx looks like
  from Cloud Run; if it is masked, retry a 404 whose body is not CKAN JSON. (2026-11-11)
