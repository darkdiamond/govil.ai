// utils/news-front.ts: which story goes in which section of the /news/ front.
process.env.TZ = "UTC";

import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/news-front.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
  plugins: [
    {
      name: "nuxt-tilde",
      setup(b) {
        b.onResolve({ filter: /^~\// }, (a) => ({
          path: `${root}${a.path.slice(2)}.ts`,
        }));
      },
    },
  ],
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { buildFront, editionLine, ilDateKey, thumbOf, monthKey, monthLabel } =
  mod.exports;

// Newest first, as publish_news writes index.json; one story every 6 hours.
const T0 = Date.parse("2026-11-12T06:00:00Z");
let n = 0;
function story(kind, topic = null, extra = {}) {
  const i = n++;
  return {
    slug: `s${i}`,
    headline: `h${i}`,
    dek: "d",
    published_at: new Date(T0 - i * 6 * 3600_000).toISOString(),
    updated_at: "",
    tags: [],
    status: "published",
    kind,
    dataset_ids: [],
    topic: topic ? { id: topic, label: topic } : null,
    ...extra,
  };
}
const many = (count, kind, topic) =>
  Array.from({ length: count }, () => story(kind, topic));

function slugsOf(front) {
  return [
    front.lead,
    ...front.side,
    front.digest,
    ...front.news,
    ...front.analyses,
    ...front.desks.flatMap((d) => d.items),
  ]
    .filter(Boolean)
    .map((a) => a.slug);
}

test("empty and one-story inputs", () => {
  n = 0;
  const empty = buildFront([]);
  assert.equal(empty.lead, null);
  assert.deepEqual(empty.archive, []);
  const one = buildFront([story("news")]);
  assert.equal(one.lead.slug, "s0");
  assert.deepEqual(one.side, []);
  assert.deepEqual(one.archive, []);
});

test("today's 8 live stories: edition 4, news 2, analyses 2, no archive", () => {
  n = 0;
  const live = [
    story("news"),
    ...many(5, "feature"),
    story("news"),
    story("news"),
  ];
  const f = buildFront(live);
  assert.equal(f.lead.slug, "s0");
  assert.deepEqual(
    f.side.map((a) => a.slug),
    ["s1", "s2", "s3"]
  );
  assert.deepEqual(
    f.news.map((a) => a.slug),
    ["s6", "s7"]
  );
  assert.deepEqual(
    f.analyses.map((a) => a.slug),
    ["s4", "s5"]
  );
  assert.deepEqual(f.archive, []);
});

test("every story appears once, and the archive holds exactly the rest", () => {
  n = 0;
  const all = [
    ...many(20, "news", "economy"),
    ...many(20, "feature", "health"),
    story("digest"),
    ...many(20, "news"),
  ];
  const f = buildFront(all);
  const front = slugsOf(f);
  assert.equal(new Set(front).size, front.length);
  const archived = new Set(f.archive.map((a) => a.slug));
  for (const s of front) assert.ok(!archived.has(s));
  assert.equal(front.length + f.archive.length, all.length);
  assert.equal(f.news.length, 6);
  assert.equal(f.analyses.length, 4);
});

test("a section under its minimum hands its story to the archive", () => {
  n = 0;
  const f = buildFront([...many(4, "news"), story("feature"), story("news")]);
  assert.deepEqual(f.analyses, []);
  assert.deepEqual(f.news, []);
  assert.equal(f.archive.length, 2);
});

test("the newest fresh digest gets the band and stays out of the edition", () => {
  n = 0;
  const older = story("digest");
  const list = [story("news"), story("digest"), ...many(4, "news"), older];
  const f = buildFront(list);
  assert.equal(f.digest.slug, list[1].slug);
  assert.ok(!f.side.some((a) => a.kind === "digest"));
  assert.ok(f.archive.some((a) => a.slug === older.slug));
});

test("a stale digest leaves the band", () => {
  n = 0;
  const stale = story("digest", null, {
    published_at: new Date(T0 - 9 * 86_400_000).toISOString(),
  });
  const f = buildFront([story("news"), ...many(3, "news"), stale]);
  assert.equal(f.digest, null);
  assert.ok(f.archive.some((a) => a.slug === stale.slug));
});

test("topic desks need three leftover stories in the topic", () => {
  n = 0;
  const list = [
    ...many(4, "news"),
    ...many(6, "news"), // the news section
    ...many(4, "feature"), // the analyses section
    ...many(3, "news", "economy"),
    ...many(2, "news", "health"),
  ];
  const f = buildFront(list);
  assert.deepEqual(
    f.desks.map((d) => d.topic.id),
    ["economy"]
  );
  assert.equal(f.desks[0].items.length, 3);
  assert.equal(f.archive.length, 2);
});

test("undated stories go to the archive only", () => {
  n = 0;
  const bad = story("news", null, { published_at: "not a date" });
  const f = buildFront([bad, ...many(4, "news")]);
  assert.notEqual(f.lead.slug, bad.slug);
  assert.deepEqual(
    f.archive.map((a) => a.slug),
    [bad.slug]
  );
});

test("the edition line uses the Israel date and needs a clock for 'today'", () => {
  n = 0;
  const late = "2026-11-11T22:30:00Z"; // already the 12th in Israel
  assert.equal(ilDateKey(late), "2026-11-12");
  const pre = editionLine(late, null);
  assert.equal(pre.today, false);
  assert.match(pre.date, /12 בנובמבר 2026/);
  assert.equal(editionLine(late, new Date("2026-11-12T10:00:00Z")).today, true);
  assert.equal(
    editionLine(late, new Date("2026-11-13T10:00:00Z")).today,
    false
  );
  assert.equal(editionLine(undefined, null), null);
  assert.equal(editionLine("x", null), null);
});

test("thumb falls back to the hero, and month helpers", () => {
  n = 0;
  assert.equal(thumbOf({ hero: "/a.jpg", hero_thumb: "/t.jpg" }), "/t.jpg");
  assert.equal(thumbOf({ hero: "/a.jpg" }), "/a.jpg");
  assert.equal(thumbOf({}), null);
  assert.equal(monthKey("2026-11-30T23:00:00Z"), "2026-12");
  assert.equal(monthLabel("2026-13"), "ללא תאריך");
});

test("news fills whole rows of three", () => {
  n = 0;
  const f = buildFront([...many(4, "feature"), ...many(5, "news")]);
  assert.equal(f.news.length, 3);
  assert.equal(f.archive.length, 2);
});
