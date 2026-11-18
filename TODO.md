# TODO

Follow-ups that are known but deliberately not in the PR that found them. Add an item when you
defer something; delete it (in the PR that fixes it) when it is done. Keep each item to what is
wrong, why it matters, and what would fix it, and end it with the date it was added.

This repo is public: describe a security gap by what to change, never by how to exploit it.

## Recipes and refresh

- **Author 022552b2 with the new `raster` input.** 022552b2 (מפות מפלסים ומליחות באקוויפרים, a
  top no-recipe page by search clicks) ships only zips of yearly GeoTIFFs: coastal-aquifer water
  level 1954-2023 (`wl_tiff.zip`, 70 files, 85MB) and chloride 1977-2020 (`cl_tiff.zip`, 35
  files, 38MB). The `raster: true` input reads both (per-year mean/percentiles, plus
  `raster_grid` cells; 0.8-1.7s locally). Redeploy the builder first (new recipe.json field and
  Pillow in the image), then author it. `wl_tiff.zip` is 85% of `REFRESH_MAP_MAX_BYTES`: a few
  more yearly files and it needs a recipe `limits` or a higher cap. (2026-11-09)

- **Check the "חברה ורווחה" GSC split around 2026-12-15.** 1ba21c94 and e4c3e3d0 split the
  query's impressions (56 vs 14 a week, both at position 7.3). They hold different data:
  1ba21c94's CSV is the English edition (English titles, authors and abstract PDFs, 2021 on),
  e4c3e3d0 the full Hebrew index, so no successor or redirect. On 2026-11-17 1ba21c94 got a
  recipe positioned as the English edition ("Society and Welfare: תקצירים באנגלית"), linking to
  e4c3e3d0, which now links back. If the two still share the Hebrew query at the same position,
  rethink the English page's title. (2026-11-17)
- **Legacy pages with search traffic and no recipe** (GSC, 7 days to 2026-11-05): 945b3682,
  2987efb0, 3a4c012f, 8b3d9aa2 (dff8a168, 13 clicks, waits on its 667MB SHP: see the top-100
  map pages item). 1d2d0ec1 and 65dafbb0 got recipes 2026-11-06, 51227f7b in #381 (2026-11-09) and
  41c2db9f in #460 (2026-11-13): compare their CTR at the same check. The selector never queues
  the rest while their data stays put. A recipe is not sure to win more clicks for pages that
  already rank, so these wait for the batch 1-2 CTR check (~2026-12-02); then open `gsc_traffic`
  issues as for #338-#344. (2026-11-06)
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
- **פנקס הקבלנים (a545d0ba): measure the 2026-11-15 title change, then decide on a Q&A
  block.** The head query "פנקס הקבלנים" is ~60% of the page's impressions and sat at 1.0% CTR,
  position ~6, both before and after the 2026-11-04 title (navigational intent: people want the
  official registry). The 2026-11-15 PR changed the title to "פנקס הקבלנים של משרד הבינוי
  והשיכון: בדיקת קבלן רשום", put the lookup callout first and linked the page from bddf37d6,
  c0beab05, 90b08091 and 005fe7c5. Fix: ~2026-12-01, compare 14 days before/after for that query
  alone and for the rest. Then consider a short static Q&A (how to check a contractor, what
  a classification such as ג5 allows, רשום vs מוכר) for queries at position 9-10 with no clicks
  ("מאגר קבלנים מוכרים", "בדיקת סיווג קבלנים", "חיפוש קבלן רשום לפי שם"), and a link to the
  official gov.il lookup once its URL is confirmed (gov.il's WAF blocked the check). (2026-11-15)
- **מאגר סימני מסחר (656f6e4c): measure the 2026-11-16 SEO change.** The head query "מאגר
  סימני מסחר" (~50% of impressions) sat at position ~5.5 with 0 clicks in 25 days, before and
  after the 2026-11-04 title (0.2% CTR on the page either way); "רשם סימני המסחר" at ~11 and the
  "רישום סימן מסחר" cluster at 23-50. The 2026-11-16 PR changed the title to "מאגר סימני מסחר
  של רשות הפטנטים: חיפוש סימן מסחר רשום", added a computed Q&A section (check, time to
  register, term and renewal, Madrid, how to file, with official links) and linked the page
  from 556634fd, 025c3e07, 9859abec, 5a2d2f62 and 0a374a70. Fix: 14 days after the render goes
  live (~2026-12-01), compare those three query groups before/after in GSC and organic sessions
  in GA4. (2026-11-16)
- **59d2e891 and df60d73b compete for "אזורי חיוג".** Batch 3 gave df60d73b (numbering plan,
  which has the geographic codes) a title for "אזורי חיוג בארץ" / "קידומת טלפון ישראל", but
  59d2e891 (service numbers, no geographic codes) still has "קידומות ואזורי חיוג" in its title
  and holds those queries at ~position 8.7. Fix: once GSC shows where df60d73b lands (~4 weeks
  after #368), drop "אזורי חיוג" from 59d2e891's title if df60d73b ranks at least as well.
  (2026-11-06)
- **Check whether ad4e7cbf visitors now reach the decision PDFs (~2026-11-29, last 14 days).**
  Before the explorer link columns (#489) and recipe v5, GA4 showed 0 clicks to
  free-justice.openapi.gov.il and 34 full-CSV `file_download`s by 29 of ~171 users (90 days),
  and GSC showed page CTR 2.93% at position 5.1 (2026-11-05..13), "החלטות שמאי מכריע" 0.5% at
  6.4. Compare GA4 `click` events with `linkDomain` free-justice.openapi.gov.il (enhanced
  measurement), full-CSV downloads, the engaged-session rate (64%), and GSC CTR for those
  queries. If links get clicked, find other datasets with URL columns worth the same card.
  (2026-11-15)
- **Add the מחיר למשתכן layer to ee626064.** Its fourth layer (`gis_dira.zip`, 9.2MB) is a zip
  of `Lots_view.zip`, `Plans_view.zip`, `Projects_view.zip` and `Settelments_Centroid_view.zip`,
  which `geo_snapshot` now opens one level down. Add a `mehir` map input (with `map_member`
  naming the layer to read), drop the fixed copy that says the layer is skipped, and bump
  `recipe_version`, after the builder redeploy. (2026-11-04)
- **Top-100 legacy map pages that the snapshot path can't serve.** חלקות (dff8a168, 667MB SHP)
  is a national layer far over the 100MB download cap; it would need a pre-aggregation step
  (the גושים/תצ"ר recipes reduce each polygon to a centroid in compute, but the file must still
  download and convert). הגבולות המשטרתיים (d01a5ee3) and קדסטר במבנה חדש (bd74ce49) ship an Esri FileGDB, which
  `read_map_file` can't read and there is no GDAL locally. (2026-10-31)
- **Switch ab746a13 to `pick: "latest_year"`.** It picks by `last_modified`, so a re-upload of a
  closed year flips the page to that year. `latest_year` exists now (concat of its 5 matching
  years is ~4.3M rows, too big); switch and bump `recipe_version` after the builder redeploy.
  (2026-10-31)
- **4eef54bc still joins authorities by name.** Its authority-code columns (`קוד_רשות`,
  `קוד_למס`) swap meaning between report years, so compute joins years on the name, folded for
  quote, hyphen and space drift. A real rename (a new spelling, a merger) still splits an
  authority in two. A yearly file whose code column has a third name (the 2018 file's
  `קודמיפוי`) matches neither input and is skipped silently. Fix: map the two code columns to
  one authority code per report year, then join on it. (2026-11-17)
- **GIS layers with no recipe could get maps now.** `map: true` reads their SHP/KMZ zips
  directly, but they have no recipe and no open issue, so nothing queues them:
  `python -m services.page_builder.map_backfill list` reports them as `no_recipe` (63 on
  2026-10-31; the transport/Ayalon family 30cc4889, 5f6d04bf, 7fb47ed4, cdd75af3, e74cc3c7,
  ee1265d8, 360fb8b4 among them). Open `new`-style issues for the ones worth a page (the
  backfill only files issues for recipe'd pages). (2026-10-31)
- **Long tail of identical re-renders.** B′ data (2026-11-10..17: 356 `False` vs 67 `True`, 0
  FALSE-SKIP) favoured `columns` over a B′ skip; the top recipes declare it now. Fix: add
  `columns` to others that recur in the `refresh precheck` logs. (2026-11-17)
- **Heavy recipes share the job's 4Gi.** A recipe with `limits` runs last and its compute is
  heap-capped (`REFRESH_COMPUTE_MEMORY_MB`, 3072 by default) and first in line for the OOM
  killer, but its exported CSVs sit in the same memory (`/tmp` is RAM on Cloud Run). If heavy
  recipes multiply, give them their own job execution with more memory (filter on
  `manifest.heavy`) rather than raising the shared job's `--memory`. (2026-10-30)
- **Give 65dafbb0's map input `columns`.** The תצ"ר layer converts to 49.2MB at tolerance 2e-5,
  near the 50MB `map_max_kb` ceiling (its floor is 37.6MB), and about a third more plans fails it
  `too_large`. Most of the bytes are properties the recipe never reads (TALAR_COMM, the ITM
  bounding box, dates). A map input now takes `columns`, which drop properties before sizing:
  list the ones the recipe reads, after the builder redeploy. (2026-11-06)

- **The local permission allowlist is broad for an unattended routine.** The gitignored
  `.claude/settings.local.json`, copied into every worktree by `.worktreeinclude`, pre-approves
  broad wildcard rules for the GitHub, cloud and HTTP CLIs and for inline Python, while the
  07:00 routine reads untrusted issue text. The checked-in `.claude/settings.json` now has a
  `permissions.deny` list (credential output, merges outside the guard, mutating GitHub API
  calls, force pushes, uploads, bucket deletes) that wins over those allows; deploys and IAM
  role bindings are deliberately not denied (the user approves Claude deploying). On
  2026-11-13 `settings.local.json` lost inline Python, every `rtk` rule (the wrapper is no
  longer used), `r.jina.ai`, `gh auth *` and stale one-off curls. Left: `gcloud storage *`,
  `gcloud scheduler *`, `gh run *` and `gh workflow *` are still wildcards; narrow them once
  the routine's actual commands are logged, and consider not copying the file into worktrees.
  (2026-11-11)

## CBS reports (cbs_releases provider)

- **`cbs-road-accidents` `_first_reports` still sorts `RELEASE_NO` as a string** ("99/2026"
  beats "100/2026"). Its latest edition comes from `cbs.latest_release`, but `rel`'s order still
  drives the `order` / "later" count and which of two same-month editions wins. Order by govlib's
  release key, as `cbs.latest_release` does, in a recipe PR. (2026-11-17)

## Shared recipe code (govlib, gov.j2, page libs)

- **b2370286 still appends tooltip closure strings raw.** Its heatmap tooltip (`h.y` / `h.x`,
  template ~line 219) skips `echarts.format.encodeHTML`. It was left out of the 2026-11-17/18
  sweeps because its export flips (see its item), so `author verify` can't run. Fix: the same
  wrapping plus a `recipe_version` bump once it verifies. (2026-11-01, narrowed 2026-11-18)
- **No mechanical check for unescaped closure strings in tooltip formatters.** Two hand sweeps
  missed some, and only a scripted audit (2026-11-18) found the rest. A check.py or automerge
  guard lint that flags a closure lookup appended in a tooltip formatter outside
  `encodeHTML`/a local escape helper would keep new recipes from regressing. (2026-11-18)

## Tags, related datasets and list pages

- **Dataset pages share one generic share image, so Discover can't show them as large cards.**
  Every dataset page (and `/`, tag and ministry pages) uses `og-default.png`; Discover wants a
  large, representative image and skips logo-like ones. News pages got their own images on
  2026-11-16; the user deferred datasets. Design worked out then: the builder draws a 1600×900
  JPEG chart card (no text; Pillow is already in the image) from the page model at refresh time,
  choosing the series with `services/news/series.extract_series` (moved to `services/shared/`)
  in the `services/news/images.chart_card` look, stages it as `datasets/<id>/og.jpg` (it rides
  the existing rsync in all three publish paths), and records its hash in `sources/<id>`. The
  publisher emits `og_image` into data.json only when the rsynced file's hash matches, so a
  missing card falls back to the default, never a 404. Rollout: an `OG_CARDS=off|observe|on`
  knob, a backfill from `models/<id>/latest.json.gz`, and no changes to `_RENDER_CODE_FILES` or
  `schema.py`. (2026-11-16)

## News

- **The writer's `fetch_url` gets HTTP 403 from www.gov.il pages.** In the 2026-11-11 explainer
  dry run, all 4 gov.il fetches (contractor classification pages, the doctors' registry service
  page) were refused, so an article can't cite or quote an official gov.il page and the attempts
  waste tool calls (one draft ran out of its budget). Tested 2026-11-13: www.gov.il sits behind
  Cloudflare and answers every identified UA tried (`govdata-news/1.0` and `govil.ai-news/1.0`
  with the `+https://govil.ai/news/about/` link, `govdata-builder/1.0`, a non-Mozilla
  `govil.ai-news/1.0`), with or without browser Accept headers, with its "Sorry, you have been
  blocked" 403 page, from a home connection (all four) and from Cloud Run (the two news UAs);
  only `/robots.txt` is served. boi.org.il and www.cbs.gov.il answer 200. The writer prompt
  now says www.gov.il fetches fail. Fix: ask gov.il (the digital office) to allow an identified client, or find an official
  API or feed for the pages we want to cite. (2026-11-11)

- **`fetch.py` can still pass its 60s total within one hop.** Each hop's httpx timeout is
  `min(TIMEOUT, remaining)` taken when the hop starts, but httpx applies it to every operation
  separately (connect, TLS, header read, each body read), and DNS resolution in `_check_url` is
  not bounded at all, so one slow hop can still run several timeouts past the deadline (the
  first hop exactly as before the cap). The job's task timeout caps it. Fix: a watchdog that
  closes the connection at the deadline, and a bounded resolver. (2026-11-18)

- **Watch the stricter number gate's reject rate.** Since 2026-11-11 the gate also fails
  quantities in words ("חמש מאות דירות", "פי שלושה", "חצי מהתושבים", a bare "מיליון שקלים") and
  thresholds or clock times in words. Compare `admin list --rejected` for the two weeks after
  the deploy with the two before; if stories die on phrasing the writer can't tokenize,
  loosen that rule in `ledger.spelled_numbers`. (2026-11-11)

- **Measure the softer editor and the critic's memory.** From 2026-11-16 the editor treats
  each release's headline number as a story by default and has no "each story must be
  stronger" ratchet. From its second round the critic checks its previous review before
  raising new points, and on the last round a "revise" scoring ≥4 everywhere with no blocking
  issue (style notes only) passes. For two weeks after the deploy, compare per day: briefs,
  published, rejected by reason, and how many articles carry `critic_final_round`. Read every
  release story that runs; if routine-release copy turns formulaic, tighten the editor's
  headline list. (2026-11-16)

## Site copy

- **Legal and accessibility pages still say an AI agent writes every dataset page.** Since
  2026-10-29 dataset pages are deterministic recipe renders; only news articles are AI-written.
  The rest of the site's copy is fixed (`faq.vue` and `datasets/index.vue` on 2026-11-17), but
  these still carry the old claim: `terms.vue:45,50,73`, `accessibility.vue:38,142,145`,
  `disclaimer.vue:93`. Terms and disclaimer are legal text, so rewrite them deliberately rather
  than by search-and-replace. Leave `news/about.vue` alone (accurate). (2026-11-16)
