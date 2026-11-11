// utils/body-scripts.ts: pages/datasets/[slug].vue re-runs a dataset body's
// scripts on mount (Vue's hydration re-sets the v-html article, leaving its
// scripts inert). A hand-made DOM stand-in, enough for what the function
// touches: data blocks must stay as they are (PR #272 wrapped a JSON block in
// the IIFE and blanked a map), every JavaScript type must be re-created.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/body-scripts.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { EXECUTABLE_SCRIPT_TYPES, executeBodyScripts, awaitDatasetLibs } =
  mod.exports;

class FakeScript {
  constructor(attrs = {}, text = "") {
    this.attrs = new Map(Object.entries(attrs));
    this.textContent = text;
    this.text = "";
    this.parentNode = null;
    this.onload = null;
    this.onerror = null;
  }
  get type() {
    return this.attrs.get("type") ?? "";
  }
  get src() {
    const raw = this.getAttribute("src");
    return raw === null ? "" : new URL(raw, location.href).href;
  }
  get attributes() {
    return [...this.attrs].map(([name, value]) => ({ name, value }));
  }
  getAttribute(name) {
    return this.attrs.has(name) ? this.attrs.get(name) : null;
  }
  setAttribute(name, value) {
    this.attrs.set(name, String(value));
  }
}

// A container whose replaceChild "executes" the new script the way a browser
// would: inline text runs at once, a src loads asynchronously.
function setup({
  readyState = "complete",
  scripts = [],
  charts = [],
  maps = [],
} = {}) {
  const log = [];
  const docListeners = [];
  const winListeners = [];
  globalThis.location = new URL("https://govil.ai/datasets/x/");
  globalThis.document = {
    readyState,
    addEventListener(type, l) {
      docListeners.push([type, l]);
    },
    createElement: () => new FakeScript(),
  };
  globalThis.window = {
    addEventListener(type, l) {
      winListeners.push([type, l]);
    },
    log,
  };
  const container = {
    nodes: [],
    querySelectorAll(sel) {
      if (sel === "script")
        return this.nodes.filter((n) => n instanceof FakeScript);
      if (sel === "[id^=chart]") return charts;
      if (sel === "[id^=map], #map, .leaflet-container") return maps;
      throw new Error(`unexpected selector ${sel}`);
    },
    replaceChild(neu, old) {
      const i = this.nodes.indexOf(old);
      assert.ok(i >= 0);
      this.nodes[i] = neu;
      neu.parentNode = this;
      old.parentNode = null;
      if (neu.getAttribute("src") !== null) {
        log.push(`load-start ${neu.getAttribute("src")}`);
        setTimeout(() => {
          log.push(`load-end ${neu.getAttribute("src")}`);
          neu.onload?.();
        }, 5);
      } else {
        new Function(neu.text)();
      }
    },
    removeChild(old) {
      this.nodes.splice(this.nodes.indexOf(old), 1);
      old.parentNode = null;
    },
  };
  for (const s of scripts) {
    s.parentNode = container;
    container.nodes.push(s);
  }
  return { container, log, docListeners, winListeners };
}

test("the executable set is the HTML spec's JavaScript types, nothing else", () => {
  for (const t of [
    "",
    "module",
    "text/javascript",
    "application/javascript",
    "text/ecmascript",
  ])
    assert.ok(EXECUTABLE_SCRIPT_TYPES.has(t), t);
  for (const t of [
    "application/json",
    "application/ld+json",
    "text/template",
    "importmap",
    "text/plain",
  ])
    assert.ok(!EXECUTABLE_SCRIPT_TYPES.has(t), t);
});

test("data blocks are left untouched; every JS type is re-created", async () => {
  const json = new FakeScript(
    { type: "application/json", id: "d" },
    '{"a":[1,2]}'
  );
  const ld = new FakeScript({ type: "application/ld+json" }, "{}");
  const classic = new FakeScript({}, "window.log.push('classic');");
  const typed = new FakeScript(
    { type: " Text/JavaScript ", "data-x": "1" },
    "window.log.push('typed');"
  );
  const mjs = new FakeScript({ type: "module" }, "window.log.push('module');");
  const { container, log } = setup({
    scripts: [json, ld, classic, typed, mjs],
  });

  await executeBodyScripts(container);

  assert.equal(container.nodes[0], json);
  assert.equal(json.textContent, '{"a":[1,2]}');
  assert.equal(container.nodes[1], ld);
  for (const i of [2, 3, 4])
    assert.notEqual(container.nodes[i], [json, ld, classic, typed, mjs][i]);
  assert.deepEqual(log, ["classic", "typed", "module"]);
  // Classic scripts are wrapped (top-level const/let can't collide across
  // visits); modules have their own scope and are not.
  assert.equal(
    container.nodes[2].text,
    "(()=>{\nwindow.log.push('classic');\n})();"
  );
  assert.equal(
    container.nodes[3].text,
    "(()=>{\nwindow.log.push('typed');\n})();"
  );
  assert.equal(container.nodes[3].getAttribute("data-x"), "1");
  assert.equal(container.nodes[4].text, "window.log.push('module');");
});

test("a body script can read the data block it sits next to", async () => {
  const json = new FakeScript({ type: "application/json" }, '{"n":3}');
  const reader = new FakeScript({}, "");
  const { container, log } = setup({ scripts: [json, reader] });
  globalThis.window.block = json;
  reader.textContent =
    "window.log.push(JSON.parse(window.block.textContent).n);";
  await executeBodyScripts(container);
  assert.deepEqual(log, [3]);
});

test("cross-origin src is dropped; same-origin src is awaited in order", async () => {
  const evil = new FakeScript({ src: "https://evil.example/x.js" });
  const local = new FakeScript({ src: "/lib/x.js" });
  const after = new FakeScript({}, "window.log.push('inline');");
  const { container, log } = setup({ scripts: [evil, local, after] });
  await executeBodyScripts(container);
  assert.ok(!container.nodes.includes(evil));
  assert.equal(container.nodes.length, 2);
  assert.deepEqual(log, [
    "load-start /lib/x.js",
    "load-end /lib/x.js",
    "inline",
  ]);
});

test("DOMContentLoaded / load handlers registered after the fact run once, at the end", async () => {
  const s = new FakeScript(
    {},
    `document.addEventListener("DOMContentLoaded", () => window.log.push("dcl"));
     window.addEventListener("load", () => window.log.push("load"));
     window.addEventListener("resize", () => window.log.push("resize"));
     window.log.push("body");`
  );
  const { container, log, docListeners, winListeners } = setup({
    scripts: [s],
  });
  const origDoc = document.addEventListener;
  await executeBodyScripts(container);
  assert.deepEqual(log, ["body", "dcl", "load"]);
  assert.deepEqual(docListeners, []);
  assert.deepEqual(
    winListeners.map(([t]) => t),
    ["resize"]
  );
  // Restored afterwards: a later registration is not intercepted.
  assert.notEqual(document.addEventListener, origDoc);
  document.addEventListener("DOMContentLoaded", () => {});
  assert.equal(docListeners.length, 1);
});

test("while the document is still loading, handlers go to the real listener", async () => {
  const s = new FakeScript(
    {},
    `document.addEventListener("DOMContentLoaded", () => window.log.push("dcl"));
     window.addEventListener("load", () => window.log.push("load"));`
  );
  const { container, log, docListeners, winListeners } = setup({
    readyState: "loading",
    scripts: [s],
  });
  await executeBodyScripts(container);
  assert.deepEqual(log, []);
  assert.deepEqual(
    docListeners.map(([t]) => t),
    ["DOMContentLoaded"]
  );
  assert.deepEqual(
    winListeners.map(([t]) => t),
    ["load"]
  );
});

test("a throwing deferred handler is reported and the rest still run", async () => {
  const s = new FakeScript(
    {},
    `document.addEventListener("DOMContentLoaded", () => { throw new Error("x"); });
     document.addEventListener("DOMContentLoaded", { handleEvent: () => window.log.push("obj") });`
  );
  const { container, log } = setup({ scripts: [s] });
  const errors = [];
  const orig = console.error;
  console.error = (...a) => errors.push(a);
  try {
    await executeBodyScripts(container);
  } finally {
    console.error = orig;
  }
  assert.deepEqual(log, ["obj"]);
  assert.equal(errors.length, 1);
});

test("existing chart and map instances in the container are cleared first", async () => {
  const disposed = [];
  const chartEl = { id: "chart-1" };
  const mapEl = { _leaflet_id: 7, innerHTML: "<div>tiles</div>" };
  const freshMap = { innerHTML: "keep" };
  const { container } = setup({ charts: [chartEl], maps: [mapEl, freshMap] });
  window.echarts = {
    getInstanceByDom: (el) => ({ dispose: () => disposed.push(el) }),
  };
  await executeBodyScripts(container);
  assert.deepEqual(disposed, [chartEl]);
  assert.equal(mapEl._leaflet_id, null);
  assert.equal(mapEl.innerHTML, "");
  assert.equal(freshMap.innerHTML, "keep");
});

test("awaitDatasetLibs returns at once when the page needs no libs", async () => {
  setup();
  await awaitDatasetLibs({ charts: false, map: false, explorer: false });
});

test("awaitDatasetLibs waits until the needed globals exist", async () => {
  setup();
  setTimeout(() => {
    window.echarts = {};
    window.GovEcharts = { option: () => ({}) };
  }, 50);
  const t0 = Date.now();
  await awaitDatasetLibs({ charts: true, map: false, explorer: false });
  assert.ok(Date.now() - t0 >= 40);
  assert.equal(typeof window.GovEcharts.option, "function");
});

test("awaitDatasetLibs gives up after the timeout with a warning", async () => {
  setup();
  const warnings = [];
  const orig = console.warn;
  console.warn = (...a) => warnings.push(a);
  try {
    await awaitDatasetLibs({ charts: false, map: true, explorer: false }, 60);
  } finally {
    console.warn = orig;
  }
  assert.equal(warnings.length, 1);
});
