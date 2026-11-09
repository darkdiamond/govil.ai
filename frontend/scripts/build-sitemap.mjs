#!/usr/bin/env node
// Generates sitemap.xml from public/data/manifest.json after `nuxt generate`
// completes. Always writes public/sitemap.xml (gitignored; keeps the dev
// server serving a current sitemap) and, when the build output exists,
// .output/public/sitemap.xml — the copy that actually ships. Listed URLs: the
// static routes, every /ministries/<slug>/, /tags/<encoded-tag>/,
// /kinds/<kind>/, and every agent-authored /datasets/<page_slug>/. Each URL
// gets <priority>, <changefreq>, and (where known) <lastmod>.

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const SITE = "https://govil.ai";

const manifestPath = resolve(ROOT, "public/data/manifest.json");
const publicSitemapPath = resolve(ROOT, "public/sitemap.xml");
const outPath = resolve(ROOT, ".output/public/sitemap.xml");

let manifest = { datasets: [], generated_at: undefined };
try {
  manifest = JSON.parse(readFileSync(manifestPath, "utf-8"));
} catch {
  console.warn(
    "[build-sitemap] no manifest.json, emitting static-only sitemap"
  );
}

const today = new Date().toISOString().slice(0, 10);
const manifestLastmod = (manifest.generated_at ?? "").slice(0, 10) || today;

/** @type {Map<string, { priority: string, changefreq: string, lastmod?: string }>} */
const urls = new Map();

function add(path, priority, changefreq, lastmod) {
  if (!urls.has(path)) urls.set(path, { priority, changefreq, lastmod });
}

// Static / hub routes
add("/", "1.0", "daily", manifestLastmod);
add("/datasets/", "0.9", "daily", manifestLastmod);
add("/ministries/", "0.7", "weekly", manifestLastmod);
add("/tags/", "0.7", "weekly", manifestLastmod);
add("/kinds/", "0.6", "weekly", manifestLastmod);
add("/about/", "0.5", "monthly");
add("/how-it-works/", "0.5", "monthly");
add("/faq/", "0.5", "monthly");
add("/contact/", "0.5", "monthly");
add("/disclaimer/", "0.4", "monthly");
add("/accessibility/", "0.3", "monthly");
add("/privacy/", "0.3", "monthly");
add("/terms/", "0.3", "monthly");

// Dynamic dataset + category routes
// Every paged tag (publisher's tag_index) — the same set nuxt.config.ts
// prerenders, so the sitemap never lists a page that doesn't exist.
for (const t of Object.values(manifest.tag_index ?? {})) {
  add(`/tags/${encodeURI(t.slug)}/`, "0.5", "weekly", manifestLastmod);
}
for (const d of manifest.datasets ?? []) {
  const pageSlug = d.page_slug || d.id;
  if (pageSlug) {
    const lastmod =
      (d.last_analyzed_at ?? d.metadata_modified ?? "").slice(0, 10) ||
      undefined;
    add(`/datasets/${encodeURI(pageSlug)}/`, "0.8", "weekly", lastmod);
  }
  if (d.organization_slug) {
    add(
      `/ministries/${d.organization_slug}/`,
      "0.6",
      "weekly",
      manifestLastmod
    );
  }
  if (d.dataset_kind) {
    add(`/kinds/${d.dataset_kind}/`, "0.5", "weekly", manifestLastmod);
  }
}

// News (services/news/publish_news.py → public/news/index.json).
let newsArticles = [];
try {
  newsArticles =
    JSON.parse(readFileSync(resolve(ROOT, "public/news/index.json"), "utf-8"))
      .articles ?? [];
} catch {
  newsArticles = [];
}
const newsLastmod =
  (newsArticles[0]?.updated_at ?? "").slice(0, 10) || undefined;
add("/news/", "0.8", "daily", newsLastmod);
add("/news/about/", "0.4", "monthly");
for (const a of newsArticles) {
  add(
    `/news/${a.slug}/`,
    "0.7",
    "monthly",
    (a.updated_at ?? "").slice(0, 10) || undefined
  );
}

const sorted = [...urls.entries()].sort(([a], [b]) => a.localeCompare(b));

const body = sorted
  .map(([path, { priority, changefreq, lastmod }]) => {
    const lines = [`    <loc>${SITE}${path}</loc>`];
    if (lastmod) lines.push(`    <lastmod>${lastmod}</lastmod>`);
    lines.push(`    <changefreq>${changefreq}</changefreq>`);
    lines.push(`    <priority>${priority}</priority>`);
    return `  <url>\n${lines.join("\n")}\n  </url>`;
  })
  .join("\n");

const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${body}
</urlset>
`;

writeFileSync(publicSitemapPath, xml, "utf-8");
console.log(`[build-sitemap] wrote ${urls.size} URLs to ${publicSitemapPath}`);

if (existsSync(dirname(outPath))) {
  writeFileSync(outPath, xml, "utf-8");
  console.log(`[build-sitemap] wrote ${urls.size} URLs to ${outPath}`);
}

// ── Google News sitemap + RSS ─────────────────────────────────────────────
// news-sitemap.xml lists only articles from the last 2 days (Google News
// ignores older entries); feed.xml carries the latest 30.
const esc = (s) =>
  String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
const twoDaysAgo = Date.now() - 2 * 24 * 3600 * 1000;
const fresh = newsArticles.filter(
  (a) => Date.parse(a.published_at) >= twoDaysAgo
);
const newsXml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
${fresh
  .map(
    (a) => `  <url>
    <loc>${SITE}/news/${a.slug}/</loc>
    <news:news>
      <news:publication><news:name>govil.ai</news:name><news:language>he</news:language></news:publication>
      <news:publication_date>${esc(a.published_at)}</news:publication_date>
      <news:title>${esc(a.headline)}</news:title>
    </news:news>
  </url>`
  )
  .join("\n")}
</urlset>
`;
const rssXml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>חדשות govil.ai</title>
    <link>${SITE}/news/</link>
    <atom:link href="${SITE}/news/feed.xml" rel="self" type="application/rss+xml" />
    <description>מה השתנה במאגרי המידע הממשלתיים, ולמה זה חשוב.</description>
    <language>he</language>
${newsArticles
  .slice(0, 30)
  .map(
    (a) => `    <item>
      <title>${esc(a.headline)}</title>
      <link>${SITE}/news/${a.slug}/</link>
      <guid isPermaLink="true">${SITE}/news/${a.slug}/</guid>
      <pubDate>${new Date(a.published_at).toUTCString()}</pubDate>
      <description>${esc(a.dek)}</description>${
        a.hero
          ? `\n      <media:content url="${SITE}${esc(a.hero)}" medium="image" />`
          : ""
      }
    </item>`
  )
  .join("\n")}
  </channel>
</rss>
`;
for (const dir of [resolve(ROOT, "public"), resolve(ROOT, ".output/public")]) {
  if (!existsSync(dir)) continue;
  writeFileSync(resolve(dir, "news-sitemap.xml"), newsXml, "utf-8");
  if (existsSync(resolve(dir, "news")))
    writeFileSync(resolve(dir, "news/feed.xml"), rssXml, "utf-8");
}
console.log(
  `[build-sitemap] news: ${newsArticles.length} article(s), ${fresh.length} in news-sitemap`
);
