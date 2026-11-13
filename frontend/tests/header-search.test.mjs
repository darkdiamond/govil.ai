// utils/header-search.ts: the header search's key handling and panel state
// (components/HeaderSearch.vue), and utils/hub-page.ts: the error a hub page
// throws after its data fetch.
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

const { moveHighlight, submitTarget, panelState, NO_HIGHLIGHT } =
  await load("header-search.ts");
const { hubPageError } = await load("hub-page.ts");

test("nothing is highlighted to start with", () => {
  assert.equal(NO_HIGHLIGHT, -1);
});

test("Enter with nothing highlighted opens the full results list", () => {
  assert.deepEqual(submitTarget("  משכנתאות ", -1, 6), {
    kind: "list",
    q: "משכנתאות",
  });
  // also when nothing matched
  assert.deepEqual(submitTarget("xyz", -1, 0), { kind: "list", q: "xyz" });
});

test("ArrowDown then Enter opens the first hit", () => {
  const h = moveHighlight("ArrowDown", -1, 6);
  assert.equal(h, 0);
  assert.deepEqual(submitTarget("משכנתאות", h, 6), { kind: "hit", index: 0 });
});

test("Enter on an empty query does nothing", () => {
  assert.equal(submitTarget("   ", -1, 0), null);
});

test("a stale highlight past the results falls back to the list", () => {
  assert.deepEqual(submitTarget("ab", 4, 2), { kind: "list", q: "ab" });
});

test("the arrows cycle through the hits and back to no highlight", () => {
  const down = [];
  let h = -1;
  for (let i = 0; i < 4; i++) down.push((h = moveHighlight("ArrowDown", h, 3)));
  assert.deepEqual(down, [0, 1, 2, -1]);
  const up = [];
  h = -1;
  for (let i = 0; i < 4; i++) up.push((h = moveHighlight("ArrowUp", h, 3)));
  assert.deepEqual(up, [2, 1, 0, -1]);
  assert.equal(moveHighlight("ArrowDown", 0, 0), -1);
  assert.equal(moveHighlight("ArrowDown", 7, 3), 0);
});

test("the panel says loading or failed instead of 'no results'", () => {
  assert.equal(panelState("מש", "loading", 0), "loading");
  assert.equal(panelState("מש", "idle", 0), "loading");
  assert.equal(panelState("מש", "failed", 0), "failed");
  assert.equal(panelState("מש", "ready", 0), "empty");
  assert.equal(panelState("מש", "ready", 3), "results");
  assert.equal(panelState("מ", "failed", 0), "prompt");
  assert.equal(panelState(" ", "loading", 0), "prompt");
});

test("hub page: a failed fetch is 503, nothing found is 404", () => {
  assert.deepEqual(hubPageError(new Error("offline"), false, "Tag"), {
    statusCode: 503,
    statusMessage: "Tag unavailable",
  });
  // a failure wins even if stale data is present
  assert.equal(hubPageError(new Error("x"), true, "Kind").statusCode, 503);
  assert.deepEqual(hubPageError(null, false, "Ministry"), {
    statusCode: 404,
    statusMessage: "Ministry not found",
  });
  assert.equal(hubPageError(undefined, true, "Article"), null);
});
