// utils/paths.ts: the site origin and the dataset/tag page paths every link,
// canonical URL and JSON-LD node on the site is built from.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/paths.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { SITE_URL, datasetPath, tagPath } = mod.exports;

test("SITE_URL is the production origin, no trailing slash", () => {
  assert.equal(SITE_URL, "https://govil.ai");
});

test("datasetPath encodes the Hebrew page_slug with encodeURI", () => {
  assert.equal(
    datasetPath({ id: "aaaaaaaa-1111", page_slug: "מוסדות-חינוך-aaaaaaaa" }),
    "/datasets/%D7%9E%D7%95%D7%A1%D7%93%D7%95%D7%AA-%D7%97%D7%99%D7%A0%D7%95%D7%9A-aaaaaaaa/"
  );
});

test("datasetPath falls back to the id when page_slug is missing or empty", () => {
  const id = "f2949f90-ce4d-4a0a-81ee-d3b931cb7b9b";
  assert.equal(datasetPath({ id }), `/datasets/${id}/`);
  assert.equal(datasetPath({ id, page_slug: "" }), `/datasets/${id}/`);
  assert.equal(datasetPath({ id, page_slug: null }), `/datasets/${id}/`);
});

test("tagPath encodes like encodeURI (not encodeURIComponent)", () => {
  assert.equal(tagPath("חינוך"), "/tags/%D7%97%D7%99%D7%A0%D7%95%D7%9A/");
  assert.equal(tagPath("a-b"), "/tags/a-b/");
  // encodeURI leaves reserved characters alone; the publisher's slugs have
  // none, and changing this would move every tag URL.
  assert.equal(tagPath("a&b"), "/tags/a&b/");
});
