# TODO

Follow-ups that are known but deliberately not in the PR that found them. Add an item when you
defer something; delete it (in the PR that fixes it) when it is done. Keep each item to what is
wrong, why it matters, and what would fix it, and end it with the date it was added.

This repo is public: describe a security gap by what to change, never by how to exploit it.

## Recipes and refresh

- **The scanner's CKAN client ignores `CKAN_USER_AGENT`.** `services/scanner/client.py` sends a
  hardcoded Chrome User-Agent, while the builder's fetches (`services.shared.ckan.user_agent()`) use
  `govdata-builder/1.0` or the env override. A WAF change then needs a code change for the scan and
  the reconcile probes. Fix: have the scanner call `shared.ckan.user_agent()` too, after checking
  from Cloud Run that the builder UA passes the CKAN API for the scan's calls. (2026-11-10)

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

- **Two live pages for the "חברה ורווחה" journal.** 1ba21c94 (legacy agent page) and e4c3e3d0
  (recipe) are both active on data.gov.il and split the "חברה ורווחה" impressions (56 vs 14 a
  week, both at position 7.3). Neither can 301 to the other while both exist upstream. Fix: if
  the CSVs turn out to be the same journal index, give 1ba21c94 a recipe that points readers to
  the other page, or add a successor entry once one of them is removed. (2026-11-06)
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
- **59d2e891 and df60d73b compete for "אזורי חיוג".** Batch 3 gave df60d73b (numbering plan,
  which has the geographic codes) a title for "אזורי חיוג בארץ" / "קידומת טלפון ישראל", but
  59d2e891 (service numbers, no geographic codes) still has "קידומות ואזורי חיוג" in its title
  and holds those queries at ~position 8.7. Fix: once GSC shows where df60d73b lands (~4 weeks
  after #368), drop "אזורי חיוג" from 59d2e891's title if df60d73b ranks at least as well.
  (2026-11-06)
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
- **Top-100 legacy map pages that the snapshot path can't serve.** חלקות (dff8a168, 667MB SHP)
  is a national layer far over the 100MB download cap; it would need a pre-aggregation step
  (the גושים/תצ"ר recipes reduce each polygon to a centroid in compute, but the file must still
  download and convert). הגבולות המשטרתיים (d01a5ee3) and קדסטר במבנה חדש (bd74ce49) ship an Esri FileGDB, which
  `read_map_file` can't read and there is no GDAL locally. (2026-10-31)
- **Three new recipes can go quietly wrong as their data moves.** 4eef54bc's `recent` input
  matches files by `קוד`; a new yearly file named like the 2019 one (`קוד_מיפוי`) is silently
  skipped, so the page stays on 2024 with no issue (match both names, or fail when the newest
  CKAN resource isn't read). 4eef54bc also joins authorities across years by name only, so a
  renamed authority splits in two. ab746a13 uses `pick: "latest"` by `last_modified`: a
  re-upload of a closed year flips the page to that year (pick by the year in the resource
  name instead). (2026-10-31)
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
- **65dafbb0's map input sits near the 50MB `map_max_kb` ceiling.** The תצ"ר layer converts to
  49.2MB at tolerance 2e-5, and its floor is 37.6MB (at 2e-4; coarser steps grow again as small
  rings fall back to full detail). About a third more plans and it fails `too_large`. Most of
  the bytes it can't shed are properties the recipe never reads (TALAR_COMM, the ITM bounding
  box, dates): let a `map` input take `columns` to drop properties before sizing (a recipe.py
  change, so it folds into every recipe's hash; redeploy before a recipe uses it). (2026-11-06)

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

- **A failed rollback can leave GCS and Firestore describing different renders.** When the
  upload lands, `mark_refreshed` fails and the rollback can't run (the previous body couldn't be
  read, or the restore write failed), GCS holds the new body while Firestore keeps the old
  `agent_data` and hashes. `staging_suspect` blocks only the content-hash skip, and only while the
  latest status is that failure; a later A∧A′ or B skip that matches the old hashes leaves the
  mismatch in place. Fix: when the mark fails with no rollback, also clear the stored
  fingerprints and hashes in the `mark_refresh_failed` call, then drop `staging_suspect`.
  (2026-11-11)

- **The builder SA's grants reach too far.** Recipe compute no longer reaches the metadata
  server (netguard's seccomp filter), but the builder SA's grants still cover the
  dispatch-token secret, project-wide Firestore (the `news` database too) and the whole
  staging bucket (`news/`, `models/`), and the publisher SA has `datastore.user` where it only
  reads. Fix: condition the builder's `roles/datastore.user` to the `(default)` database, give
  the publisher `roles/datastore.viewer`, and optionally condition the bucket grant to exclude
  `news/`. (2026-11-11)

- **The sandbox's straggler reaper is narrow.** `_reap_stragglers` kills only processes whose
  environment still holds the session's `HOME`, and every compute shares one uid. (Failing
  closed inside the job without the `sandbox` user and the 0711 `SESSIONS_ROOT` are done.)
  Fix: after each compute kill every process with the sandbox uid, and set a low
  `RLIMIT_NPROC`. Local authoring keeps today's behaviour. (2026-11-11)

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

## Shared recipe code (govlib, gov.j2, page libs)

- **Tooltip escaping still has gaps the runtime belt can't close.** The gov-echarts.js belt
  escapes the params' label fields and, deeply, `data`, `value` and the tree path arrays, but
  a string nested past its depth cap is returned unescaped, a `tooltip` set under a tree
  node's `children` or a series' `levels` is not wrapped (no recipe sets one today), and it
  can't reach strings a formatter reads from its own closure (the heatmap formatters'
  `h.y[p.value[1]]`). Fix: escape past the cap instead of passing through, wrap tooltips under
  `children`/`levels`, and for closure strings export an escape helper from gov-echarts.js, use
  it in the formatters that append a model string (about 26 templates) and make that an
  authoring rule. (2026-11-01)

## Tags, related datasets and list pages

- **Firebase Hosting redirect count is unverified.** `gen-redirects.mjs` now writes ~550 tag
  redirects next to ~560 dataset ones. The docs state no cap; confirm on a preview channel deploy
  that ~1,100 rules are accepted before relying on growth beyond that. (2026-10-30)
- **Stale Firestore fields.** `sources/<id>.embedding` (Voyage, removed) is still on the docs
  that had it; nothing reads it. A one-off cleanup would shrink the docs. (2026-10-30)

## Frontend

- **The shared `node_modules` lacks `vue-tsc`.** `npm run typecheck` fails locally ("A type
  checker is required") although `package.json` lists it; the main checkout's install predates
  it. Fix: `npm ci` in the main checkout's `frontend/` (not in a worktree). (2026-11-10)

- **Enter in the header search opens the first hit, though the footer says all results.**
  `HeaderSearch.vue` highlights the first result whenever there is one, so Enter goes to that
  dataset; the "/datasets/?q=" list opens only when nothing matched, while the footer reads
  "הקשה על Enter תפתח את כל התוצאות". Fix: start the highlight at -1 (Enter opens the full list,
  ArrowDown picks a hit), or change the footer text. A product choice. (2026-11-11)

- **Header search shows "אין תוצאות" while the index loads or after it failed.** A failed load is
  retried on the next open, but there is no loading or retry hint, and the hub pages' 503 path for
  a failed index fetch has no automated test (it lives in an SFC). Fix: a loading state and a
  "try again" line in `HeaderSearch.vue`, and move the hub's fetch-failure branch somewhere the
  `node --test` suite can reach. (2026-11-11)

## Dependencies

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

## News

- **The writer's `fetch_url` gets HTTP 403 from www.gov.il pages.** In the 2026-11-11 explainer
  dry run, all 4 gov.il fetches (contractor classification pages, the doctors' registry service
  page) were refused, so an article can't cite or quote an official gov.il page and the attempts
  waste tool calls (one draft ran out of its budget). boi.org.il was not tested. Fix: find out
  what the site accepts for an identified, polite client (the builder's data.gov.il UA was
  user-approved, see CLAUDE.md layer 5), get the user's approval for that client, and until then
  tell the writer in `prompts/writer.md` that gov.il fetches fail. (2026-11-11)

- **The number gate refuses proper names that hold a digit.** `כביש 6` or `קו 480` in prose or a
  chart label reads as a typed number and fails the draft, so the writer has to talk around it.
  Fix: an allowlist of name patterns (road, line, route numbers) the number check skips, or a
  writer-side way to mark a proper name. (2026-11-11)

- **`fetch.py` bounds slow response headers only per read.** The fetch's total deadline is
  checked between operations, so a very slow response header or TLS handshake is bounded only
  by the per-read timeout, not by the 60s total. That needs a server on an allowlisted site, and
  the job's task timeout caps it. Fix: a per-hop timeout of
  `min(TIMEOUT, remaining)`, or a watchdog that closes the connection at the deadline.
  (2026-11-11)

- **The news kill switch lives in the job's env.** The deploy scripts now keep a live
  `NEWS_PUBLISH` (and the builder's `CKAN_USER_AGENT`) unless one is exported, but
  `gcloud run jobs deploy` from anywhere else still resets it. Fix: move the kill switch to a
  Firestore flag (the `news` database) that a deploy can't touch. (2026-11-11)

- **The `news` database's security rules aren't in the repo.** `firebase.json` deploys
  `firestore.rules` (deny all) to `(default)` only; the `news` database, created by
  `infra/news-iam.setup.sh`, keeps whatever rules it was created with. Fix: list both databases
  in `firebase.json`'s `firestore` config with the same rules file and deploy them with
  `firebase deploy --only firestore:rules`. (2026-11-11)

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
