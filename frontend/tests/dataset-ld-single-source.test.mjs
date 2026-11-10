// Google validates every schema.org Dataset node on a page and flags one
// without description / license / creator (Search Console, 2026-11-10: news
// articles' isBasedOn listed bare {name, url} Datasets). Only
// composables/useDatasetLd.ts builds Dataset nodes, and its builders always
// emit all three (dataset-seo.test.mjs), so no other source file may write a
// Dataset @type.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
// Generated or third-party trees, and the tests themselves.
const SKIP_DIRS = new Set(["node_modules", "public", "tests"]);
const ALLOWED = new Set(["composables/useDatasetLd.ts"]);
const DATASET_TYPE = /["']@type["']\s*:\s*["']Dataset["']/;

function* walk(dir) {
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    if (ent.name.startsWith(".") || SKIP_DIRS.has(ent.name)) continue;
    const p = join(dir, ent.name);
    if (ent.isDirectory()) yield* walk(p);
    else if (/\.(vue|ts|mjs|js)$/.test(ent.name)) yield p;
  }
}

test("only useDatasetLd.ts emits Dataset JSON-LD nodes", () => {
  const offenders = [];
  for (const file of walk(root)) {
    const rel = relative(root, file);
    if (!ALLOWED.has(rel) && DATASET_TYPE.test(readFileSync(file, "utf8")))
      offenders.push(rel);
  }
  assert.deepEqual(offenders, []);
});
