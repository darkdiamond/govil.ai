// utils/search-index.ts: memoRetry, the memo HeaderSearch loads Fuse + the
// slim index through (a failed load must not be pinned for the session).
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/search-index.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
  // Browser branch of the dual-mode loaders; esbuild's cjs output has no import.meta.
  define: { "import.meta.server": "false" },
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { memoRetry } = mod.exports;

test("memoRetry: a rejected load is retried on the next call", async () => {
  let calls = 0;
  const load = memoRetry(async () => {
    calls += 1;
    if (calls === 1) throw new Error("offline");
    return "index";
  });
  await assert.rejects(load(), /offline/);
  assert.equal(await load(), "index");
  assert.equal(calls, 2);
});

test("memoRetry: a successful load is reused", async () => {
  let calls = 0;
  const load = memoRetry(async () => {
    calls += 1;
    return calls;
  });
  const first = load();
  assert.equal(load(), first, "concurrent callers share one in-flight load");
  assert.equal(await first, 1);
  assert.equal(await load(), 1);
  assert.equal(calls, 1);
});
