// Google validates every schema.org Dataset node on a page and flags one
// without description / license / creator (Search Console, 2026-11-10: news
// articles' isBasedOn listed bare {name, url} Datasets). Only
// composables/useDatasetLd.ts builds Dataset nodes, and it always emits all
// three, so no other source file may write "@type": "Dataset".
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const DIRS = ["pages", "components", "composables", "layouts", "utils"];
const ALLOWED = new Set(["composables/useDatasetLd.ts"]);
const DATASET_TYPE = /["']@type["']\s*:\s*["']Dataset["']/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) yield* walk(p);
    else if (/\.(vue|ts|mjs|js)$/.test(name)) yield p;
  }
}

test("only useDatasetLd.ts emits Dataset JSON-LD nodes", () => {
  const offenders = [];
  for (const d of DIRS) {
    for (const file of walk(join(root, d))) {
      const rel = relative(root, file);
      if (!ALLOWED.has(rel) && DATASET_TYPE.test(readFileSync(file, "utf8")))
        offenders.push(rel);
    }
  }
  assert.deepEqual(offenders, []);
});

test("useDatasetLd.ts builders still emit the Google-required fields", () => {
  const src = readFileSync(join(root, "composables/useDatasetLd.ts"), "utf8");
  for (const field of ["description", "license", "creator"]) {
    assert.match(src, new RegExp(`\\b${field}:`), field);
  }
});
