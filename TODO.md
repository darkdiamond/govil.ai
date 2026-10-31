# TODO

Follow-ups that are known but deliberately not in the PR that found them. Add an item when you
defer something; delete it (in the PR that fixes it) when it is done. Keep each item to what is
wrong, why it matters, and what would fix it, and end it with the date it was added.

This repo is public: describe a security gap by what to change, never by how to exploit it.

## Recipes and refresh

- **`sandbox_failed` never escalates.** It opens no issue and keeps no strike count, so a spawn
  abort that turns deterministic (an image that loses `GRPC_ENABLE_FORK_SUPPORT=0`) freezes
  every page with only log lines. Fix: count consecutive `sandbox_failed` runs like
  `wall_budget_strikes` and open an issue (or fail the run) past a threshold. (2026-10-31)
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
- **`preview render` shows blank charts/maps when the live page didn't use those libraries.**
  It borrows the prod page's `<head>`, which loads echarts/Leaflet only if the legacy body
  referenced them (`detectDatasetLibs`). A recipe that adds charts to a map-only page (or a map
  to a chart page) looks broken in preview but is fine on the site. Fix: have the preview inject
  the libs from `detectDatasetLibs(new body)`. (2026-10-31)
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
  bump with the same size as "re-check by hand" (a note in the issue, not a failure). (2026-10-30)
- **Transport/Ayalon GIS layers could get maps.** 30cc4889, 5f6d04bf, 7fb47ed4, cdd75af3,
  e74cc3c7, ee1265d8, 360fb8b4, 00dfc38e, 03092ac8 and the existing recipe a98fbabc (Jerusalem
  metro lines, no map today) ship their shapes only in SHP/KMZ zips next to a small attribute
  table. Each needs a browser download, then `author snapshot`. (2026-10-30)
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

## Tags, related datasets and list pages

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
