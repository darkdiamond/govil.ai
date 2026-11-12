// Ping IndexNow (Bing/Yandex/Seznam/Naver) with the URLs of the generated
// sitemap that are new or whose <lastmod> changed since the previous deploy,
// so new and updated dataset pages get crawled within hours instead of weeks
// without resubmitting the whole site on every (hourly) publish.
// Runs as a post-deploy step in every publish path (.github/workflows/publish.yml,
// cloudbuild-publish.yaml, infra/publish-local.sh); never fails the deploy. The key file lives at frontend/public/<KEY>.txt (same KEY) —
// IndexNow verifies ownership by fetching it from the live site.
//
//   node frontend/scripts/indexnow-ping.mjs [--previous <file>] [--sitemap <file>] [--dry-run]
//
//   --previous <file>  the sitemap that was live before this deploy, saved by
//                      fetch-live-sitemap.mjs. Missing, empty or unparseable →
//                      every URL is submitted (the pre-delta behaviour).
//   --sitemap <file>   the new sitemap (default: frontend/.output/public/sitemap.xml)
//   --dry-run          print the URLs it would submit; no network call.
//                      INDEXNOW_DRY_RUN=1 does the same.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const KEY = "d6ede06d967d8c5ae326761d20ad54f3";
const HOST = "govil.ai";
const MAX_URLS = 10000; // protocol cap per request

function parseArgs(argv) {
  const opts = {
    previous: null,
    sitemap: fileURLToPath(
      new URL("../.output/public/sitemap.xml", import.meta.url)
    ),
    dryRun: ["1", "true"].includes(process.env.INDEXNOW_DRY_RUN ?? ""),
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--dry-run") opts.dryRun = true;
    else if (arg === "--previous") opts.previous = argv[++i] ?? null;
    else if (arg === "--sitemap") opts.sitemap = argv[++i] ?? opts.sitemap;
    else console.warn(`[indexnow] ignoring unknown argument: ${arg}`);
  }
  return opts;
}

/** <loc> → <lastmod> (or "" when the entry has none), in sitemap order. */
function parseSitemap(xml) {
  const entries = new Map();
  for (const block of xml.matchAll(/<url>([\s\S]*?)<\/url>/g)) {
    const loc = block[1].match(/<loc>\s*([^<]+?)\s*<\/loc>/);
    if (!loc) continue;
    const lastmod = block[1].match(/<lastmod>\s*([^<]+?)\s*<\/lastmod>/);
    entries.set(loc[1], lastmod ? lastmod[1] : "");
  }
  return entries;
}

const opts = parseArgs(process.argv.slice(2));

let current;
try {
  current = parseSitemap(readFileSync(opts.sitemap, "utf-8"));
} catch (err) {
  console.warn("[indexnow] no sitemap found, skipping:", err.message);
  process.exit(0);
}

if (current.size === 0) {
  console.warn("[indexnow] sitemap had no URLs, skipping");
  process.exit(0);
}

// The baseline: what was live before this deploy. Anything short of a sitemap
// with URLs in it means we can't tell what changed, so everything goes.
let previous = null;
let baselineNote = "";
if (!opts.previous) {
  baselineNote = "no previous sitemap given";
} else {
  try {
    const parsed = parseSitemap(readFileSync(opts.previous, "utf-8"));
    if (parsed.size > 0) previous = parsed;
    else baselineNote = `previous sitemap ${opts.previous} has no URLs`;
  } catch (err) {
    baselineNote = `previous sitemap unreadable (${err.message})`;
  }
}

let urls;
if (previous === null) {
  urls = [...current.keys()];
  console.log(`[indexnow] ${baselineNote}; submitting every URL`);
} else {
  let added = 0;
  let changed = 0;
  urls = [];
  for (const [loc, lastmod] of current) {
    if (!previous.has(loc)) added++;
    else if (previous.get(loc) !== lastmod) changed++;
    else continue;
    urls.push(loc);
  }
  console.log(
    `[indexnow] vs the previous sitemap (${previous.size} URLs): ${added} new, ${changed} with a new lastmod`
  );
}

const batch = urls.slice(0, MAX_URLS);
console.log(
  `[indexnow] submitting ${batch.length} of ${current.size} sitemap URLs` +
    (opts.dryRun ? " (dry run)" : "")
);

if (batch.length === 0) {
  console.log(
    "[indexnow] nothing new or changed since the previous sitemap; not pinging"
  );
  process.exit(0);
}

if (opts.dryRun) {
  for (const url of batch) console.log(url);
  process.exit(0);
}

// One retry after a pause: right after a deploy the key file can lag CDN
// propagation, and IndexNow answers 403 until it can fetch the key.
for (let attempt = 1; attempt <= 2; attempt++) {
  try {
    const res = await fetch("https://api.indexnow.org/indexnow", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({
        host: HOST,
        key: KEY,
        keyLocation: `https://${HOST}/${KEY}.txt`,
        urlList: batch,
      }),
    });
    console.log(
      `[indexnow] pinged ${batch.length} URLs -> HTTP ${res.status} (attempt ${attempt})`
    );
    if (res.ok || attempt === 2) break;
  } catch (err) {
    console.warn(
      `[indexnow] ping failed (attempt ${attempt}, non-fatal):`,
      err.message
    );
    if (attempt === 2) break;
  }
  await new Promise((r) => setTimeout(r, 30_000));
}
