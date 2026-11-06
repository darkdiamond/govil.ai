import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

// --- gov-map.js: shapes encoded by govlib.geo (recipe_lib/govlib/geo.py) ---

function loadGovMap(nodes = {}) {
  const el = () => {
    const e = { children: [], style: {}, className: "", textContent: "" };
    e.appendChild = (c) => {
      e.children.push(c);
      return c;
    };
    return e;
  };
  const head = el();
  const document = {
    getElementById: (id) =>
      nodes[id] || head.children.find((c) => c.id === id) || null,
    createElement: el,
    head,
  };
  const window = {};
  vm.runInNewContext(
    readFileSync(new URL("../scripts/gov-map.js", import.meta.url), "utf8"),
    { window, document }
  );
  return window.GovMap;
}

test("GovMap.ring decodes govlib.geo.encode output", () => {
  // python: geo.encode([ring], geo.origin(...)) for the ring below
  const origin = [3478123, 3208011];
  const flat = [0, 0, 78, 2, -2, 89, -76, -91];
  const ring = [
    [34.78123, 32.08011],
    [34.78201, 32.08013],
    [34.78199, 32.08102],
    [34.78123, 32.08011],
  ];
  const got = loadGovMap().ring(flat, origin, 100000);
  assert.equal(got.length, ring.length);
  got.forEach(([lat, lng], i) => {
    assert.ok(
      Math.abs(lng - ring[i][0]) < 1e-9 && Math.abs(lat - ring[i][1]) < 1e-9,
      `${i}: ${lat},${lng}`
    );
  });
});

test("GovMap.islands concatenates numbered islands in order and stops at a gap", () => {
  const GovMap = loadGovMap({
    "m-0": { textContent: "[1, 2]" },
    "m-1": { textContent: "[3]" },
    "m-3": { textContent: "[99]" },
  });
  assert.deepEqual([...GovMap.islands("m")], [1, 2, 3]);
  assert.deepEqual([...GovMap.islands("none")], []);
});

test("GovMap.popup writes dataset strings as text and skips empty rows", () => {
  const div = loadGovMap().popup("<b>כותרת</b>", [
    ["שם", "<img src=x>"],
    ["ריק", ""],
    ["קומות", 0],
    ["", "בלי תווית"],
  ]);
  const [title, dl] = div.children;
  assert.equal(title.textContent, "<b>כותרת</b>");
  assert.equal(dl.children.length, 3);
  assert.equal(dl.children[0].children[1].textContent, "<img src=x>");
  assert.equal(dl.children[1].children[1].textContent, "0");
  assert.notEqual(
    dl.children[2].children[0].textContent,
    "f3",
    "no internal key as a label"
  );
});

test("GovMap.popup injects the popup CSS once, for raw-Leaflet pages", () => {
  const styles = [];
  const el = () => {
    const e = { children: [], style: {}, className: "", textContent: "" };
    e.appendChild = (c) => {
      e.children.push(c);
      return c;
    };
    return e;
  };
  const document = {
    getElementById: (id) => styles.find((s) => s.id === id) || null,
    createElement: el,
    head: { appendChild: (s) => styles.push(s) },
  };
  const window = {};
  vm.runInNewContext(
    readFileSync(new URL("../scripts/gov-map.js", import.meta.url), "utf8"),
    { window, document }
  );
  window.GovMap.popup("א", [["ב", "ג"]]);
  window.GovMap.popup("ד", [["ה", "ו"]]);
  assert.equal(styles.length, 1);
  assert.match(styles[0].textContent, /\.gov-map-popup\{/);
});

// --- Ctrl/⌘ + wheel zoom gate ---

function loadWithLeaflet() {
  const hooks = [];
  const listeners = [];
  const L = { Map: { addInitHook: (fn) => hooks.push(fn) } };
  const el = () => {
    const e = {
      children: [],
      style: {},
      className: "",
      textContent: "",
      attrs: {},
    };
    e.appendChild = (c) => {
      e.children.push(c);
      return c;
    };
    e.setAttribute = (k, v) => (e.attrs[k] = v);
    e.removeAttribute = (k) => delete e.attrs[k];
    return e;
  };
  const head = el();
  const document = {
    getElementById: (id) => head.children.find((c) => c.id === id) || null,
    createElement: el,
    head,
  };
  const window = {
    L,
    addEventListener: (type, fn, opts) => listeners.push({ type, fn, opts }),
  };
  vm.runInNewContext(
    readFileSync(new URL("../scripts/gov-map.js", import.meta.url), "utf8"),
    { window, document, L, setTimeout: () => 0, clearTimeout: () => {} }
  );
  // A map created with scrollWheelZoom: false, as recipe templates do.
  const container = el();
  const classes = new Set();
  container.classList = { add: (c) => classes.add(c) };
  container.querySelector = () =>
    container.children.find((c) => c.className === "gov-wheel-hint") || null;
  let enabled = false;
  const map = {
    getContainer: () => container,
    scrollWheelZoom: { enable: () => (enabled = true) },
  };
  hooks.forEach((h) => h.call(map));
  const target = {
    closest: (sel) =>
      sel === ".gov-wheel-gated" && classes.has("gov-wheel-gated")
        ? container
        : null,
  };
  return { hooks, listeners, container, enabled: () => enabled, target };
}

test("wheel gate: every Leaflet map gets wheel zoom, behind one capture listener", () => {
  const { hooks, listeners, enabled } = loadWithLeaflet();
  assert.equal(hooks.length, 1);
  assert.ok(enabled(), "scrollWheelZoom re-enabled despite the page's false");
  assert.equal(listeners.length, 1);
  assert.equal(listeners[0].type, "wheel");
  assert.equal(listeners[0].opts.capture, true);
  assert.equal(listeners[0].opts.passive, true, "never blocks page scrolling");
});

test("wheel gate: a plain wheel over a map stops Leaflet and shows the hint; Ctrl/⌘ passes", () => {
  const { listeners, container, target } = loadWithLeaflet();
  const onWheel = listeners[0].fn;
  const fire = (t, mods) => {
    let stopped = false;
    onWheel({
      target: t,
      ctrlKey: false,
      metaKey: false,
      ...mods,
      stopPropagation: () => (stopped = true),
    });
    return stopped;
  };
  assert.equal(fire(target, {}), true, "plain wheel never reaches Leaflet");
  const hint = container.children.find((c) => c.className === "gov-wheel-hint");
  assert.ok(hint && "data-show" in hint.attrs);
  assert.match(hint.textContent, /Ctrl|⌘/);
  assert.equal(fire(target, { ctrlKey: true }), false);
  assert.equal(fire(target, { metaKey: true }), false);
  assert.equal(
    fire({ closest: () => null }, {}),
    false,
    "off the map: untouched"
  );
});

test("wheel gate: no Leaflet on the page → nothing installed, no throw", () => {
  assert.ok(loadGovMap().ring);
});
