// utils/site-search.ts: the search-as-you-type logic the header popover and
// the homepage box share (composables/useSiteSearch.ts).
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));

async function load(entry) {
  const { outputFiles } = await build({
    entryPoints: [`${root}utils/${entry}`],
    bundle: true,
    write: false,
    format: "cjs",
    platform: "node",
  });
  const mod = { exports: {} };
  new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
  return mod.exports;
}

const {
  matchTags,
  highlightSegments,
  flattenOptions,
  searchDatasets,
  buildSearchDocs,
  resultsAnnouncement,
  ministryList,
  matchNames,
  countMatches,
  snippetAround,
  previewEntry,
  tagList,
  idleTags,
  idleTagCount,
  WIDE_QUERY,
} = await load("site-search.ts");
const { recentDatasets } = await load("home.ts");
const { submitTarget } = await load("header-search.ts");

const TAGS = {
  "תחבורה ציבורית": {
    slug: "תחבורה-ציבורית",
    count: 12,
    ministries: [],
    related: [],
  },
  תחבורה: { slug: "תחבורה", count: 30, ministries: [], related: [] },
  רכב: { slug: "רכב", count: 20, ministries: [], related: [] },
  "בטיחות בדרכים ותחבורה": {
    slug: "בטיחות",
    count: 50,
    ministries: [],
    related: [],
  },
  חינוך: { slug: "חינוך", count: 25, ministries: [], related: [] },
  ירושלים: { slug: "ירושלים", count: 40, ministries: [], related: [] },
  gtfs: { slug: "gtfs", count: 3, ministries: [], related: [] },
};

const names = (hits) => hits.map((h) => h.name);

test("matchTags: word-start matches first, then by count", () => {
  assert.deepEqual(names(matchTags(TAGS, "תחבורה", 5)), [
    "תחבורה",
    "תחבורה ציבורית",
    "בטיחות בדרכים ותחבורה",
  ]);
});

test("matchTags: a match inside a word ranks after word starts", () => {
  // "ותחבורה" holds "תחבורה" mid-word: after both word-start matches even
  // though it is the biggest tag.
  const hits = names(matchTags(TAGS, "תחבורה", 5));
  assert.equal(hits[hits.length - 1], "בטיחות בדרכים ותחבורה");
  assert.equal(hits[0], "תחבורה");
});

test("matchTags: caps at the limit and ignores short queries", () => {
  assert.equal(matchTags(TAGS, "תחבורה", 2).length, 2);
  assert.deepEqual(matchTags(TAGS, "ת"), []);
  assert.deepEqual(matchTags(undefined, "רכב"), []);
});

test("matchTags: final letters fold (חינוכ finds חינוך)", () => {
  assert.deepEqual(names(matchTags(TAGS, "חינוכ")), ["חינוך"]);
});

test("matchTags: keyboard-layout re-read (rfc → רכב, עאכד → gtfs)", () => {
  assert.deepEqual(names(matchTags(TAGS, "rfc")), ["רכב"]);
  assert.deepEqual(names(matchTags(TAGS, "עאכד")), ["gtfs"]);
});

test("matchTags: a typed city name finds its tag", () => {
  assert.deepEqual(names(matchTags(TAGS, "ירושלים")), ["ירושלים"]);
});

test("idleTags: biggest first, city tags left out", () => {
  const all = tagList(TAGS);
  assert.equal(all[0].name, "בטיחות בדרכים ותחבורה");
  assert.ok(all.some((t) => t.name === "ירושלים"));
  assert.deepEqual(names(idleTags(all, 3)), [
    "בטיחות בדרכים ותחבורה",
    "תחבורה",
    "חינוך",
  ]);
});

test("idleTagCount: 3 chips on a phone, 6 from sm up", () => {
  assert.equal(idleTagCount(false), 3);
  assert.equal(idleTagCount(true), 6);
  assert.equal(WIDE_QUERY, "(min-width: 640px)");
});

test("matchTags: returns name, slug and count only", () => {
  assert.deepEqual(matchTags(TAGS, "רכב"), [
    { name: "רכב", slug: "רכב", count: 20 },
  ]);
});

const marked = (segs) => segs.filter((s) => s.match).map((s) => s.text);

test("highlightSegments: marks the literal match and keeps the text whole", () => {
  const segs = highlightSegments("כלי רכב פרטיים", "רכב");
  assert.equal(segs.map((s) => s.text).join(""), "כלי רכב פרטיים");
  assert.deepEqual(marked(segs), ["רכב"]);
});

test("highlightSegments: final letters fold onto the original letters", () => {
  // The query's כ matches the title's final ך.
  assert.deepEqual(marked(highlightSegments("משרד החינוך", "חינוכ")), [
    "חינוך",
  ]);
});

test("highlightSegments: niqqud and quotes inside the match stay covered", () => {
  assert.deepEqual(marked(highlightSegments('נתוני צה"ל', "צהל")), ['צה"ל']);
  assert.deepEqual(marked(highlightSegments("שָׁלוֹם עולם", "שלום")), [
    "שָׁלוֹם",
  ]);
});

test("highlightSegments: Latin is case-insensitive; every occurrence marks", () => {
  assert.deepEqual(marked(highlightSegments("GTFS and gtfs", "gtfs")), [
    "GTFS",
    "gtfs",
  ]);
});

test("highlightSegments: hyphen and space match each other", () => {
  assert.deepEqual(marked(highlightSegments("תל-אביב יפו", "תל אביב")), [
    "תל-אביב",
  ]);
});

test("highlightSegments: the keyboard re-read marks too", () => {
  assert.deepEqual(marked(highlightSegments("כלי רכב", "rfc")), ["רכב"]);
});

test("highlightSegments: a fuzzy hit with no literal match is one plain run", () => {
  assert.deepEqual(highlightSegments("כלי רכב", "רקב"), [
    { text: "כלי רכב", match: false },
  ]);
  assert.deepEqual(highlightSegments("כלי רכב", "ר"), [
    { text: "כלי רכב", match: false },
  ]);
  assert.deepEqual(highlightSegments("", "רכב"), []);
});

test("flattenOptions: topics first, then datasets", () => {
  const opts = flattenOptions(
    [{ id: "a", title: "A", formats: [] }],
    [{ name: "רכב", slug: "רכב", count: 2 }]
  );
  assert.deepEqual(
    opts.map((o) => o.kind),
    ["tag", "dataset"]
  );
});

test("submitTarget picks a topic option by its flattened index", () => {
  const opts = flattenOptions(
    [{ id: "a", title: "A", formats: [] }],
    [{ name: "רכב", slug: "רכב", count: 2 }]
  );
  assert.deepEqual(submitTarget("רכב", 0, opts.length), {
    kind: "hit",
    index: 0,
  });
  assert.equal(opts[0].kind, "tag");
});

test("searchDatasets: converted variants count only on a literal hit", () => {
  const docs = buildSearchDocs([
    { id: "1", title: "כלי רכב", formats: [] },
    { id: "2", title: "רכבת", formats: [] },
  ]);
  // A fake Fuse: returns every doc whose title shares a letter.
  const fuse = {
    search: (text) =>
      docs
        .filter((d) => [...text].some((c) => d.title.includes(c)))
        .map((item, i) => ({ item, score: 0.1 * (i + 1) })),
  };
  const r = searchDatasets(fuse, "rfc");
  assert.deepEqual(
    r.items.map((e) => e.id),
    ["1", "2"]
  );
  assert.equal(r.convertedText, "רכב");
  assert.equal(r.rawHits, false);
  assert.deepEqual(searchDatasets(fuse, "r").items, []);
});

test("resultsAnnouncement says what is showing", () => {
  assert.equal(resultsAnnouncement("results", 6, 2), "6 מאגרים, 2 נושאים");
  assert.equal(resultsAnnouncement("results", 1, 0), "מאגר אחד");
  assert.equal(resultsAnnouncement("results", 0, 1), "נושא אחד");
  assert.equal(resultsAnnouncement("empty", 0, 0), "אין תוצאות");
  assert.equal(resultsAnnouncement("prompt", 0, 0), "");
});

const DS = [
  {
    id: "1",
    title: "כלי רכב פרטיים",
    organization: "משרד התחבורה",
    organization_slug: "mot",
    formats: [],
    last_analyzed_at: "2026-11-10T00:00:00Z",
  },
  {
    id: "2",
    title: "רופאים",
    organization: "משרד הבריאות",
    organization_slug: "moh",
    formats: [],
    last_analyzed_at: "2026-11-12T00:00:00Z",
  },
  {
    id: "3",
    title: "סוחרי רכב",
    organization: "משרד התחבורה",
    organization_slug: "mot",
    formats: [],
    tags: ["רכב"],
    last_analyzed_at: "2026-11-11T00:00:00Z",
    source_status: "unavailable",
  },
  {
    id: "4",
    title: "בתי ספר",
    organization: "משרד החינוך",
    organization_slug: "moe",
    formats: [],
  },
];

test("ministryList: one row per body, count DESC", () => {
  assert.deepEqual(ministryList(DS), [
    { name: "משרד התחבורה", slug: "mot", count: 2 },
    { name: "משרד הבריאות", slug: "moh", count: 1 },
    { name: "משרד החינוך", slug: "moe", count: 1 },
  ]);
});

test("matchNames: a word inside the name counts as a word start", () => {
  assert.deepEqual(
    matchNames(ministryList(DS), "תחבורה", 2).map((m) => m.slug),
    ["mot"]
  );
  // "החינוך" holds "חינוך" mid-word: still found, ranked after word starts.
  assert.deepEqual(
    matchNames(ministryList(DS), "חינוך", 2).map((m) => m.slug),
    ["moe"]
  );
});

test("countMatches: the substring rule /datasets/ uses, layout re-reads too", () => {
  const docs = buildSearchDocs(DS);
  assert.equal(countMatches(docs, "רכב"), 2);
  assert.equal(countMatches(docs, "rfc"), 2);
  assert.equal(countMatches(docs, "zzzz"), 0);
  assert.equal(countMatches(docs, ""), 0);
});

test("snippetAround: short text comes back whole", () => {
  assert.equal(snippetAround("  קצר  ", "קצר"), "קצר");
});

test("snippetAround: a late match is pulled into view, cut at words", () => {
  const text = `${"מילה ".repeat(80)}רכב ${"סוף ".repeat(40)}`;
  const s = snippetAround(text, "רכב", 120);
  assert.ok(s.startsWith("…"));
  assert.ok(s.endsWith("…"));
  assert.ok(s.includes("רכב"));
  assert.ok(s.length <= 122);
  assert.ok(!s.slice(1).startsWith(" "));
});

test("snippetAround: no match keeps the start", () => {
  const text = "א ".repeat(200);
  const s = snippetAround(text, "zzzz", 50);
  assert.ok(!s.startsWith("…"));
  assert.ok(s.endsWith("…"));
});

test("previewEntry: the highlighted dataset, else the first one", () => {
  const opts = flattenOptions(
    [DS[0], DS[1]],
    [{ name: "רכב", slug: "רכב", count: 2 }],
    [{ name: "משרד התחבורה", slug: "mot", count: 2 }]
  );
  assert.deepEqual(
    opts.map((o) => o.kind),
    ["tag", "ministry", "dataset", "dataset"]
  );
  assert.equal(previewEntry(opts, 3).id, "2");
  assert.equal(previewEntry(opts, 0).id, "1");
  assert.equal(previewEntry(opts, -1).id, "1");
  assert.equal(previewEntry([], -1), null);
});

test("recentDatasets: newest render first, removed datasets and undated left out", () => {
  assert.deepEqual(
    recentDatasets(DS, 5).map((d) => d.id),
    ["2", "1"]
  );
});
