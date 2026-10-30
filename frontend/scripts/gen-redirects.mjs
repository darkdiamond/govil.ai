#!/usr/bin/env node
// Regenerate hosting.redirects in firebase.json from the freshly published
// manifest (public/data/manifest.json), so old URLs keep 301-ing to their
// current location instead of 404-ing. Run on every deploy, after the
// publisher writes the manifest and before `firebase deploy` — the redirect
// set then never drifts from the live corpus.
//
// Two URL-scheme migrations produce durable old->new maps:
//
//   1. Dataset scheme change (commit e3c6ac7, 2026-06-23): pages moved from
//      /datasets/<CKAN-uuid>/ to /datasets/<hebrew-page_slug>/. Every current
//      dataset id -> its page_slug is a 301. Re-analysis can also change a
//      title (hence the slug), so regenerating from the live manifest — not a
//      one-time snapshot — is what keeps the 13-and-counting gaps from
//      recurring. Supersedes the manual snapshot from commit 1653950.
//
//   2. Tag taxonomy (taxonomy/tags.json): tags are now a curated vocabulary,
//      so every old raw-tag URL whose tag merged into a canonical tag (a
//      spelling variant or alias: /tags/מי-תהום-a6306f/ → /tags/מי-תהום/)
//      301s to it. The publisher computes that map as `manifest.tag_redirects`
//      (services/page_builder/tags.py::tag_redirects).
//
//   3. Tag slug normalization (older): the tag URL segment used to keep raw
//      spaces (/tags/סימני מסחר/); the finite set of old space-form URLs
//      Google still holds is listed below and 301s to wherever its dash-form
//      lives now.
//
// Deliberately NOT redirected: tags that no longer have a page (dropped, or
// carried by too few datasets) and the abandoned Latin-transliteration tag
// scheme (/tags/mym/, /tags/rkb/, …). They have no current equivalent, and
// mass-redirecting gone pages to an index is a soft-404 pattern search
// engines penalise — a real 404 is the correct signal.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const REPO = resolve(ROOT, "..");

const manifestPath = resolve(ROOT, "public/data/manifest.json");
const firebasePath = resolve(REPO, "firebase.json");

// Old space-form tag URLs Google indexed before whitespace was normalised to
// '-'. Historical/fixed — the scheme changed once. Each maps to the dash-form
// only if that tag still exists in the corpus (else it's left to 404).
const OLD_SPACE_TAGS = [
  "סימני מסחר",
  "אתרי בנייה שנסגרו",
  "שמאים מכריעים",
  "אתרי בנייה",
  "סיווגי CPC",
  "שינויים בחברות",
  "שינויים בתאגידים",
  "מנהל הטובין",
  "משרד המשפטים",
  "אתרי בנייה פעילים",
  "שמאי מקרקעין",
  "תקנים רשמיים",
  "עיצומים כספיים",
  "עורכי פטנטים",
  "משרד העבודה",
  "רשם החברות",
  "מידע גיאוגרפי",
  "רשות המים",
  "ממציאים לבקשות פטנט",
  "בקשות פטנטים",
  "ים המלח",
  "רשימת הנוטריונים",
  "תיקי פיקוח",
];

const manifest = JSON.parse(readFileSync(manifestPath, "utf-8"));
const datasets = manifest.datasets ?? [];
const liveTagSlugs = new Set(
  Object.values(manifest.tag_index ?? {}).map((t) => t.slug)
);
const tagRedirects = manifest.tag_redirects ?? {};

// Where an old dash-form tag segment lives now: itself, its canonical, or nowhere.
function tagTarget(segment) {
  if (liveTagSlugs.has(segment)) return `/tags/${encodeURI(segment)}/`;
  const to = tagRedirects[segment];
  return to ? encodeURI(to) : null;
}

const redirects = [];

// 1. Dataset uuid -> page_slug. Source is the bare id (no trailing slash, to
//    mirror the existing block); destination is percent-encoded with a
//    trailing slash, matching how the route is prerendered.
let dsCount = 0;
for (const d of datasets) {
  const slug = d.page_slug;
  if (!slug || slug === d.id) continue; // never exposed at a uuid URL
  redirects.push({
    source: `/datasets/${d.id}`,
    destination: `/datasets/${encodeURI(slug)}/`,
    type: 301,
  });
  dsCount++;
}

// 2-3. Old tag URLs -> canonical tag page. Firebase Hosting matches `source`
//    against the DECODED request path, so the source is the raw Hebrew
//    (literal space), NOT percent-encoded — an encoded source never matches.
//    The destination is a real URL, so it stays encoded.
let tagCount = 0;
const seenSources = new Set();
// Segments derive from CKAN tags; a source with Firebase glob syntax could
// capture live URLs. Allowlist plain characters only — tags.py::_SAFE_SEGMENT,
// which already filters these (belt and braces), plus the space the fixed
// OLD_SPACE_TAGS sources carry (not glob syntax).
const SAFE_SEGMENT = /^[\p{L}\p{N}_\-.,'"״׳ ]+$/u;
function addTag(source, destination) {
  if (!destination || seenSources.has(source)) return;
  if (!SAFE_SEGMENT.test(source.slice("/tags/".length, -1))) return;
  seenSources.add(source);
  redirects.push({ source, destination, type: 301 });
  tagCount++;
}
for (const [segment, to] of Object.entries(tagRedirects)) {
  addTag(`/tags/${segment}/`, encodeURI(to));
}
for (const t of OLD_SPACE_TAGS) {
  addTag(`/tags/${t}/`, tagTarget(t.replace(/\s+/g, "-")));
}

const firebase = JSON.parse(readFileSync(firebasePath, "utf-8"));
firebase.hosting.redirects = redirects;
writeFileSync(firebasePath, JSON.stringify(firebase, null, 2) + "\n", "utf-8");

console.log(
  `[gen-redirects] wrote ${redirects.length} redirects ` +
    `(${dsCount} dataset, ${tagCount} tag) to firebase.json`
);
