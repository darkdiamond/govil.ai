// Save the currently live sitemap.xml to a file, as the baseline that
// indexnow-ping.mjs diffs the new build against (only new URLs and URLs whose
// <lastmod> moved are submitted). Every publish path runs it right BEFORE
// `firebase deploy` (.github/workflows/publish.yml, cloudbuild-publish.yaml,
// infra/publish-local.sh) and passes the file as `--previous <file>`.
//
// Fail-soft: it always exits 0. On any error the output file is left absent,
// and indexnow-ping.mjs then submits every URL (the old behaviour).
//
//   node frontend/scripts/fetch-live-sitemap.mjs <out-file>
import { rmSync, writeFileSync } from "node:fs";

// Same site as build-sitemap.mjs's SITE and indexnow-ping.mjs's HOST.
const SITE = "https://govil.ai";

const out = process.argv[2];
if (!out) {
  console.warn(
    "[live-sitemap] usage: fetch-live-sitemap.mjs <out-file>; skipping"
  );
  process.exit(0);
}

// A leftover from an earlier run must never stand in for today's live copy.
rmSync(out, { force: true });

try {
  // The query string only bypasses any cache in front of the origin; Hosting
  // serves the static file regardless.
  const res = await fetch(`${SITE}/sitemap.xml?baseline=${Date.now()}`, {
    headers: { "Cache-Control": "no-cache" },
    signal: AbortSignal.timeout(30_000),
  });
  if (!res.ok) {
    console.warn(
      `[live-sitemap] HTTP ${res.status}; IndexNow will submit every URL`
    );
  } else {
    const body = await res.text();
    writeFileSync(out, body, "utf-8");
    console.log(`[live-sitemap] saved ${body.length} bytes to ${out}`);
  }
} catch (err) {
  rmSync(out, { force: true });
  console.warn(
    "[live-sitemap] fetch failed (non-fatal); IndexNow will submit every URL:",
    err.message
  );
}
