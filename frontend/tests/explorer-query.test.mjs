// utils/explorer-query.ts: the explorer's free-text box → CKAN tsquery.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/explorer-query.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { buildTsQuery } = mod.exports;

test("plain words become ANDed prefix terms", () => {
  assert.equal(buildTsQuery("הרצל"), "הרצל:*");
  assert.equal(buildTsQuery("תל-אביב"), "תל:* & אביב:*");
  assert.equal(buildTsQuery("  רחוב   הרצל "), "רחוב:* & הרצל:*");
  assert.equal(buildTsQuery("abc 123"), "abc:* & 123:*");
});

test("niqqud and cantillation marks do not split a word", () => {
  assert.equal(buildTsQuery("שָׁלוֹם"), "שלום:*");
  assert.equal(buildTsQuery("בְּרֵאשִׁ֖ית"), "בראשית:*");
  // precomposed presentation form (U+FB2A shin with shin dot)
  assert.equal(buildTsQuery("שׁלום"), "שלום:*");
  // maqaf still separates
  assert.equal(buildTsQuery("בית־ספר"), "בית:* & ספר:*");
});

test("an inner geresh or gershayim keeps the word whole", () => {
  assert.equal(buildTsQuery('צה"ל'), "צהל:*");
  assert.equal(buildTsQuery("צה״ל"), "צהל:*");
  assert.equal(buildTsQuery("ג'ורג'"), "גורג:*");
  assert.equal(buildTsQuery("ג׳ורג׳"), "גורג:*");
  assert.equal(buildTsQuery('"שלום"'), "שלום:*");
});

test("Latin accents survive", () => {
  assert.equal(buildTsQuery("résumé"), "résumé:*");
  assert.equal(buildTsQuery("résumé"), "résumé:*");
});

test("tsquery operators are neutralized", () => {
  assert.equal(
    buildTsQuery("a & b | !c (d) :* 'e' \"f\""),
    "a:* & b:* & c:* & d:* & e:* & f:*"
  );
  assert.equal(buildTsQuery("x<->y"), "x:* & y:*");
  assert.equal(buildTsQuery("צה\"ל'&|!"), "צהל:*");
  assert.equal(buildTsQuery("&|!():*'\""), null);
  assert.equal(buildTsQuery(""), null);
  for (const raw of ['צה"ל & !x', "ש'|ם", "a\"b'c(d)"]) {
    const q = buildTsQuery(raw);
    for (const term of q.split(" & "))
      assert.match(term, /^[\p{L}\p{N}]+:\*$/u, `${raw} → ${q}`);
  }
});

test("at most six terms", () => {
  assert.equal(
    buildTsQuery("a b c d e f g h"),
    "a:* & b:* & c:* & d:* & e:* & f:*"
  );
});
