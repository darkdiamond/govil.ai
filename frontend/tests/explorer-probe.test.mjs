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
const { explorerFailureKind, probeFailureKind, abortAfter } = mod.exports;

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

// data.gov.il's edge answers CKAN's error replies (a missing table's 404
// included) with an HTML page that has no CORS header, so in the browser they
// are a bare TypeError, the same as a network failure.
test("a hidden reply drops an unverified candidate, not a verified one", () => {
  const hidden = new TypeError("Failed to fetch");
  assert.equal(probeFailureKind(hidden, false), "absent");
  assert.equal(probeFailureKind(hidden, true), "transient");
});

test("verified or not, every other failure reads as explorerFailureKind", () => {
  const timeout = new DOMException("timed out", "TimeoutError");
  const abort = new DOMException("aborted", "AbortError");
  for (const verified of [true, false]) {
    assert.equal(probeFailureKind(http(403), verified), "gone");
    assert.equal(probeFailureKind(http(404), verified), "absent");
    assert.equal(probeFailureKind(http(503), verified), "transient");
    assert.equal(probeFailureKind(timeout, verified), "transient");
    assert.equal(probeFailureKind(abort, verified), "transient");
    assert.equal(
      probeFailureKind(new SyntaxError("Unexpected token <"), verified),
      "transient"
    );
  }
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

// Safari < 15.4 and Chrome < 98 drop abort's reason: the fetch rejects with a
// plain AbortError, as a superseded request does. onTimeout is how the caller
// still knows it was the timeout.
test("abortAfter reports the timeout before it aborts", async () => {
  const calls = [];
  const ctrl = { abort: () => calls.push("abort") }; // ignores the reason
  const clear = abortAfter(ctrl, 5, () => calls.push("timeout"));
  await new Promise((r) => setTimeout(r, 30));
  clear();
  assert.deepEqual(calls, ["timeout", "abort"]);
});

test("a cleared abortAfter never reports a timeout", async () => {
  let timedOut = false;
  abortAfter(new AbortController(), 5, () => {
    timedOut = true;
  })();
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(timedOut, false);
});
