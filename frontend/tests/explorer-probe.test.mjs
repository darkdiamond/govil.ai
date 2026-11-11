// utils/explorer-probe.ts: which datastore failures drop an explorer tab
// (CKAN says there is no table) and which get the error state with a retry.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/explorer-probe.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { explorerFailureKind, abortAfter } = mod.exports;

const http = (status) => Object.assign(new Error(`http ${status}`), { status });

test("403 is the gone state", () => {
  assert.equal(explorerFailureKind(http(403)), "gone");
});

test("CKAN's no-table answers drop the tab", () => {
  assert.equal(explorerFailureKind(http(404)), "absent");
  assert.equal(explorerFailureKind(http(409)), "absent");
  assert.equal(explorerFailureKind(http(400)), "absent");
  assert.equal(
    explorerFailureKind(
      Object.assign(new Error("ckan reject"), { rejected: true })
    ),
    "absent"
  );
});

test("server errors, throttling and timeouts are transient", () => {
  for (const s of [500, 502, 503, 504, 429, 408]) {
    assert.equal(explorerFailureKind(http(s)), "transient", String(s));
  }
  assert.equal(
    explorerFailureKind(new DOMException("signal timed out", "TimeoutError")),
    "transient"
  );
});

test("network errors and unparseable replies are transient", () => {
  assert.equal(
    explorerFailureKind(new TypeError("Failed to fetch")),
    "transient"
  );
  assert.equal(
    explorerFailureKind(new SyntaxError("Unexpected token <")),
    "transient"
  );
  assert.equal(explorerFailureKind(undefined), "transient");
  assert.equal(explorerFailureKind("boom"), "transient");
});

// The fetch timeout: AbortController + setTimeout, not AbortSignal.timeout,
// which Safari/iOS < 16 and Chrome < 103 lack (it threw there, so the schema
// probe failed on every try).
test("abortAfter aborts the controller once the time is up", async () => {
  const ctrl = new AbortController();
  const clear = abortAfter(ctrl, 5);
  await new Promise((r) => setTimeout(r, 30));
  clear();
  assert.equal(ctrl.signal.aborted, true);
  assert.equal(explorerFailureKind(ctrl.signal.reason), "transient");
});

test("abortAfter's clear stops the timer", async () => {
  const ctrl = new AbortController();
  abortAfter(ctrl, 5)();
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(ctrl.signal.aborted, false);
});
