// utils/home.ts: what the homepage (and /tags/) bake from the search index.
process.env.TZ = "UTC";

import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/home.ts`],
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
const {
  buildHome,
  topicGroups,
  UPDATED_CAP,
  CHIPS_CAP,
  PLACE_TAGS,
  MINISTRIES_CAP,
  TOPICS_CAP,
} = mod.exports;

const ds = (id, extra = {}) => ({
  id,
  title: `t-${id}`,
  formats: [],
  ...extra,
});

const INDEX = {
  version: 1,
  generated_at: "2026-11-16T08:00:00Z",
  datasets: [
    ds("a", {
      last_analyzed_at: "2026-11-10T00:00:00Z",
      organization: "משרד התחבורה",
      organization_slug: "mot",
      tags: ["רכב", "תחבורה ציבורית"],
    }),
    ds("b", {
      last_analyzed_at: "2026-11-15T00:00:00Z",
      organization: "משרד התחבורה",
      organization_slug: "mot",
      tags: ["רכב"],
    }),
    ds("c", {
      last_analyzed_at: "2026-11-15T00:00:00Z",
      organization: "משרד הבריאות",
      organization_slug: "moh",
      tags: ["רופאים"],
    }),
    ds("d", { tags: ["תג-בודד"] }), // never rendered
    ds("e", { last_analyzed_at: "not a date" }),
    ds("f", {
      last_analyzed_at: "2026-11-16T00:00:00Z",
      source_status: "unavailable",
    }),
  ],
  tag_index: {
    רכב: {
      slug: "רכב",
      topic: "transport",
      count: 2,
      ministries: {},
      related: [],
    },
    "תחבורה ציבורית": {
      slug: "תחבורה-ציבורית",
      topic: "transport",
      count: 1,
      ministries: {},
      related: [],
    },
    רופאים: {
      slug: "רופאים",
      topic: "health",
      count: 1,
      ministries: {},
      related: [],
    },
    יתום: {
      slug: "יתום",
      topic: "gone",
      count: 3,
      ministries: {},
      related: [],
    },
  },
  topics: [
    { id: "health", label_he: "בריאות" },
    { id: "transport", label_he: "תחבורה" },
    { id: "empty", label_he: "ריק" },
  ],
};

test("updated: newest render first, ties on id, undated, invalid and archived left out", () => {
  const h = buildHome(INDEX);
  assert.deepEqual(
    h.updated.map((r) => r.id),
    ["b", "c", "a"]
  );
  assert.deepEqual(Object.keys(h.updated[0]).sort(), [
    "id",
    "last_analyzed_at",
    "organization",
    "page_slug",
    "title",
  ]);
});

test("updated is capped", () => {
  const many = Array.from({ length: UPDATED_CAP + 5 }, (_, i) =>
    ds(`x${String(i).padStart(2, "0")}`, {
      last_analyzed_at: new Date(Date.UTC(2026, 0, 1 + i)).toISOString(),
    })
  );
  const h = buildHome({ ...INDEX, datasets: many });
  assert.equal(h.updated.length, UPDATED_CAP);
  assert.equal(h.updated[0].id, `x${UPDATED_CAP + 4}`);
});

test("chips: only paged tags, count DESC, one per topic, capped", () => {
  const h = buildHome(INDEX);
  // תחבורה ציבורית shares רכב's topic, so only the bigger one shows.
  assert.deepEqual(
    h.chips.map((c) => c.name),
    ["יתום", "רכב", "רופאים"]
  );
  assert.deepEqual(Object.keys(h.chips[0]).sort(), ["count", "name", "slug"]);
  assert.ok(!h.chips.some((c) => c.name === "תג-בודד"));
  const tag_index = Object.fromEntries(
    Array.from({ length: CHIPS_CAP + 3 }, (_, i) => [
      `t${i}`,
      { slug: `t${i}`, count: i, ministries: {}, related: [] },
    ])
  );
  assert.equal(buildHome({ ...INDEX, tag_index }).chips.length, CHIPS_CAP);
  // Dedup runs before the cap: a crowd of one topic's tags doesn't eat the
  // tiles. Two tags of a topic missing from the vocabulary both stay.
  const crowded = {
    ...tag_index,
    ...Object.fromEntries(
      Array.from({ length: CHIPS_CAP }, (_, i) => [
        `big${i}`,
        {
          slug: `big${i}`,
          topic: "health",
          count: 100 + i,
          ministries: {},
          related: [],
        },
      ])
    ),
    stale1: {
      slug: "stale1",
      topic: "gone",
      count: 90,
      ministries: {},
      related: [],
    },
    stale2: {
      slug: "stale2",
      topic: "gone",
      count: 80,
      ministries: {},
      related: [],
    },
  };
  const c = buildHome({ ...INDEX, tag_index: crowded }).chips;
  assert.equal(c.length, CHIPS_CAP);
  assert.deepEqual(
    c.slice(0, 3).map((x) => x.name),
    [`big${CHIPS_CAP - 1}`, "stale1", "stale2"]
  );
});

test("chips: city tags never get a tile; the topic's next tag does", () => {
  const tag_index = {
    ...INDEX.tag_index,
    "באר שבע": {
      slug: "באר-שבע",
      topic: "localities",
      count: 50,
      ministries: {},
      related: [],
    },
    "רשויות מקומיות": {
      slug: "רשויות-מקומיות",
      topic: "localities",
      count: 40,
      ministries: {},
      related: [],
    },
  };
  const topics = [...INDEX.topics, { id: "localities", label_he: "יישובים" }];
  assert.ok(PLACE_TAGS.has("באר שבע"));
  const names = buildHome({ ...INDEX, tag_index, topics }).chips.map(
    (c) => c.name
  );
  assert.ok(!names.includes("באר שבע"));
  assert.equal(names[0], "רשויות מקומיות");
});

test("topics: biggest first, distinct datasets per topic, no 'other', no empty", () => {
  const h = buildHome(INDEX);
  assert.deepEqual(
    h.topics.map((t) => [t.id, t.count]),
    [
      ["transport", 2], // a carries two transport tags but counts once
      ["health", 1],
    ]
  );
  assert.deepEqual(
    h.topics[0].tags.map((t) => t.slug),
    ["רכב", "תחבורה-ציבורית"]
  );
});

test("topics are capped", () => {
  const n = TOPICS_CAP + 4;
  const topics = Array.from({ length: n }, (_, i) => ({
    id: `p${i}`,
    label_he: `נ${i}`,
  }));
  const tag_index = Object.fromEntries(
    topics.map((t, i) => [
      `tag${i}`,
      { slug: `tag${i}`, topic: t.id, count: 1, ministries: {}, related: [] },
    ])
  );
  const datasets = topics.map((_, i) => ds(`d${i}`, { tags: [`tag${i}`] }));
  const h = buildHome({
    version: 1,
    generated_at: "",
    datasets,
    tag_index,
    topics,
  });
  assert.equal(h.topics.length, TOPICS_CAP);
});

test("counts and ministries", () => {
  const h = buildHome(INDEX);
  assert.equal(h.datasetCount, 6);
  assert.equal(h.ministryCount, 2);
  assert.deepEqual(
    h.ministries.map((m) => [m.slug, m.count]),
    [
      ["mot", 2],
      ["moh", 1],
    ]
  );
  assert.ok(MINISTRIES_CAP >= 2);
});

test("an empty index gives empty sections", () => {
  const h = buildHome({ version: 1, generated_at: "", datasets: [] });
  assert.equal(h.datasetCount, 0);
  assert.deepEqual(h.updated, []);
  assert.deepEqual(h.chips, []);
  assert.deepEqual(h.topics, []);
  assert.deepEqual(h.ministries, []);
});

test("topicGroups (the /tags/ page): topics in order, unknown topic under 'other'", () => {
  const g = topicGroups(INDEX);
  assert.deepEqual(
    g.map((x) => [x.id, x.tags.map((t) => t.name)]),
    [
      ["health", ["רופאים"]],
      ["transport", ["רכב", "תחבורה ציבורית"]],
      ["other", ["יתום"]],
    ]
  );
  assert.equal(g[2].label, "נושאים נוספים");
});
