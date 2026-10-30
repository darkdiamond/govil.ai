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
- **Builder job redeploy for providers (after PR #238 merges).** The image must contain
  `services/providers` (`Dockerfile`) and the job needs `PROVIDER_BOI_SDMX_ENABLED=true`
  (`infra/builder-job.deploy.sh`). Until then the three `boi-*` recipes are skipped as
  `no_source_doc`. The script uses `--set-env-vars`: diff against the live job first. Same for
  `infra/refresh-preview.deploy.sh`. (2026-10-30)

## Recipes and refresh

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
- **A fetch over its byte cap or wall budget is retried forever, silently.**
  `fetch_resource_records_to_file` returns None for a network error, a crossed byte cap and an
  exhausted wall budget alike, so `refresh.fetch_inputs` reports all three as transient
  `fetch_failed`: no issue opens, and a dataset that outgrew its cap (or a heavy recipe's
  `limits`) goes stale without anyone being told. CLAUDE.md says outgrowing the cap opens an
  issue. Have the fetcher report why it stopped, and map cap/budget overruns to `too_large`.
  (2026-10-30)
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

## Dependencies

- **ECharts 6 migration.** The moderate ECharts advisory is fixed only in 6.x, a major bump for
  the runtime every page body uses. No published page uses the affected series type, so this is a
  planned migration, not an urgent fix: do it with a corpus-wide visual check. (2026-10-30)
- **esbuild override.** `frontend/package.json` pins `esbuild` to 0.28.1 via `overrides`, outside
  vite's declared range. Drop the override once vite/nuxt depend on esbuild ^0.28. (2026-10-30)
- **No frontend type checker.** `npx nuxi typecheck` needs `typescript` and `vue-tsc`, which are
  not in `frontend/package.json`, so `.vue`/`.ts` type errors are caught only at runtime. Add them
  as dev dependencies and run the check in CI. (2026-10-30)
