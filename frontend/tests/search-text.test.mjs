// utils/search-text.ts: spelling folds and the wrong-keyboard-layout re-read
// the header search and /datasets/ match against.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/search-text.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const {
  normalizeSearchText,
  queryVariants,
  searchHaystack,
  toHebrewLayout,
  toLatinLayout,
} = mod.exports;

const texts = (q) => queryVariants(q).map((v) => v.text);
const converted = (q) =>
  queryVariants(q).find((v) => v.converted)?.text ?? null;

test("Hebrew typed with the keyboard on English", () => {
  assert.equal(toHebrewLayout("akuo"), "שלום");
  assert.equal(converted("akuo"), normalizeSearchText("שלום"));
  assert.equal(converted("rfc"), "רכב");
  // , . ; are Hebrew letters on that layout: map before normalizing
  assert.equal(toHebrewLayout("ch,"), "בית");
  assert.equal(converted("cn,"), "במת");
  assert.equal(converted("RFC"), "רכב");
  assert.equal(converted("rfc pryh"), "רכב פרטי");
});

test("the display form keeps final letters and quotes", () => {
  const v = queryVariants('eupu, jukho vkn"x ').find((x) => x.converted);
  assert.equal(v.display, 'קופות חולים הלמ"ס');
  assert.equal(v.text, "קופות חולימ הלמס");
});

test("an English name typed with the keyboard on Hebrew", () => {
  assert.equal(toLatinLayout("עאכד"), "gtfs");
  assert.equal(converted("עאכד"), "gtfs");
});

test("the query as typed always comes first", () => {
  assert.deepEqual(queryVariants("GTFS")[0], {
    text: "gtfs",
    display: "GTFS",
    converted: false,
  });
  assert.equal(queryVariants("רכב")[0].text, "רכב");
  assert.equal(queryVariants("")[0], undefined);
});

test("mixed-script queries are not re-read", () => {
  assert.equal(converted("covid קורונה"), null);
  assert.deepEqual(texts("covid קורונה"), ["covid קורונה"]);
});

test("digits alone are not re-read", () => {
  assert.equal(converted("2024"), null);
});

test("re-reads shorter than three letters are dropped", () => {
  // "ab" → "שנ", "co" → "במ": common Hebrew prefixes that match everything
  assert.equal(converted("ab"), null);
  assert.equal(converted("co"), null);
  assert.equal(converted("t"), null);
  assert.deepEqual(texts("ab"), ["ab"]);
  assert.equal(converted("של"), null);
  assert.equal(converted("rfc"), "רכב");
});

test("the haystack folds every searchable field", () => {
  const hay = searchHaystack({
    title: 'נתוני צה"ל',
    summary_he: "תל-אביב",
    organization: "משרד הביטחון",
    tags: ["ביטחון"],
  });
  assert.ok(hay.includes("צהל"));
  assert.ok(hay.includes("תל אביב"));
  assert.ok(hay.includes("משרד הביטחונ"));
  assert.equal(searchHaystack({ title: "GTFS" }), "gtfs");
});

test("spelling folds", () => {
  const same = (a, b) =>
    assert.equal(normalizeSearchText(a), normalizeSearchText(b));
  same('צה"ל', "צהל");
  same("צה״ל", "צהל");
  same("צ'יפס", "ציפס");
  same("שלום", "שלומ");
  same("עֲבוֹדָה", "עבודה");
  same("תל-אביב", "תל אביב");
  same("תל־אביב", "תל אביב");
  same("  Tel   Aviv ", "tel aviv");
});
