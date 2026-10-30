# TODO

Follow-ups that are known but deliberately not in the PR that found them. Add an item when you
defer something; delete it (in the PR that fixes it) when it is done. Keep each item to what is
wrong, why it matters, and what would fix it, and end it with the date it was added.

This repo is public: describe a security gap by what to change, never by how to exploit it.

## Security and operations

- **CSP allowlist is still report-only.** `firebase.json` sends the full allowlist as
  `Content-Security-Policy-Report-Only`; the soak after PR #93 showed no violations and the
  planned promotion (around 2026-10-24) has not happened. Check a clean console on live dataset
  pages with ads filling, then move the allowlist to the enforced header (CLAUDE.md, "CSP is two
  headers"). (2026-10-30)
- **Sandbox uid not confirmed in prod.** Recipe `compute.py` is meant to run as the `sandbox`
  user (uid 10001, `local_sandbox.py`), but setuid inside the Cloud Run job was never checked on a
  live run. Confirm it in a job execution's logs or with a one-off `--args` probe. (2026-10-30)
- **Authoring routine cron is UTC.** The 07:00 Israel routine runs on `0 5 * * *` UTC, which is
  right only in winter time. Move it to `0 4 * * *` on 2027-03-26 (Israel switches to summer
  time), and back in October. (2026-10-30)

## Recipes and refresh

- **`author prepare` ignores `REFRESH_MAX_BYTES`.** `services/page_builder/author.py` passes
  `_DEFAULT_MAX_BYTES` (300MB) to the fetch, while prod runs `REFRESH_MAX_BYTES=450000000`. A
  dataset between the two caps refreshes in prod but cannot be prepared locally. Read the env var
  the way `max_records` already does. (2026-10-30)
- **No "latest snapshot" input mode.** Datasets that publish each snapshot as a new resource
  (e.g. `f0b71d2d…`, 41 monthly CSVs) can only be pinned `by_id`, so the page silently stays on
  that snapshot. Add a `recipe.py` input mode that picks the newest matching resource.
  (2026-10-30)
- **`273c5e33…` (vehicle history) is blocked by `REFRESH_MAX_RECORDS`.** Its two resources hold
  2.5M and 5.55M rows, over the 2M default. Raise `REFRESH_MAX_RECORDS` on the job if memory and
  the fetch caps allow, otherwise it stays a legacy page. (2026-10-30)

## Dependencies

- **ECharts 6 migration.** The moderate ECharts advisory is fixed only in 6.x, a major bump for
  the runtime every page body uses. No published page uses the affected series type, so this is a
  planned migration, not an urgent fix: do it with a corpus-wide visual check. (2026-10-30)
- **esbuild override.** `frontend/package.json` pins `esbuild` to 0.28.1 via `overrides`, outside
  vite's declared range. Drop the override once vite/nuxt depend on esbuild ^0.28. (2026-10-30)
