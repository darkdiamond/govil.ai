// utils/dataset-route.ts: which client-side navigations the dataset-document
// middleware turns into a document load (browser Back into a dataset page).
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/dataset-route.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { isDatasetPagePath, isSamePagePath } = mod.exports;

const HEB = "מחירי-דירות";
const HEB_ENC = encodeURIComponent(HEB);

test("dataset pages match, with or without a trailing slash", () => {
  assert.equal(isDatasetPagePath("/datasets/car-accidents/"), true);
  assert.equal(isDatasetPagePath("/datasets/car-accidents"), true);
  assert.equal(isDatasetPagePath("/datasets/car-accidents/?q=x#data"), true);
});

test("Hebrew slugs match decoded and percent-encoded", () => {
  assert.equal(isDatasetPagePath(`/datasets/${HEB}/`), true);
  assert.equal(isDatasetPagePath(`/datasets/${HEB_ENC}/`), true);
  assert.equal(isDatasetPagePath(`/datasets/${HEB_ENC.toLowerCase()}/`), true);
});

test("the index and other routes do not match", () => {
  assert.equal(isDatasetPagePath("/datasets/"), false);
  assert.equal(isDatasetPagePath("/datasets"), false);
  assert.equal(isDatasetPagePath("/datasets/?q=בתי+ספר"), false);
  assert.equal(isDatasetPagePath("/datasets/a/b/"), false);
  assert.equal(isDatasetPagePath("/tags/תחבורה/"), false);
  assert.equal(isDatasetPagePath("/news/some-article/"), false);
  assert.equal(isDatasetPagePath("/"), false);
  assert.equal(isDatasetPagePath("/x/datasets/a/"), false);
});

test("same page ignores encoding, trailing slash, query and hash", () => {
  assert.equal(
    isSamePagePath(`/datasets/${HEB}/`, `/datasets/${HEB_ENC}/`),
    true
  );
  assert.equal(
    isSamePagePath(
      `/datasets/${HEB_ENC.toLowerCase()}`,
      `/datasets/${HEB_ENC}/`
    ),
    true
  );
  assert.equal(
    isSamePagePath("/datasets/a/#data-explorer", "/datasets/a/"),
    true
  );
  assert.equal(isSamePagePath("/datasets/a/", "/datasets/b/"), false);
  assert.equal(isSamePagePath("/tags/x/", "/datasets/x/"), false);
});

test("a malformed escape is compared as given, not thrown", () => {
  assert.equal(isSamePagePath("/datasets/%E0%A4/", "/datasets/%E0%A4/"), true);
  assert.equal(isSamePagePath("/datasets/%E0%A4/", "/datasets/x/"), false);
});
