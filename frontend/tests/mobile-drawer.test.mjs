// utils/mobile-drawer.ts + components/MobileNavDrawer.vue: the drawer keeps
// focus inside itself while open, and every way of leaving it (a link to the
// current page, crossing the md breakpoint) releases the body scroll lock.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { parse } from "@vue/compiler-sfc";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/mobile-drawer.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { trapTabKey, onDesktopWidth } = mod.exports;

function fakeDom(n) {
  const doc = { activeElement: null };
  const items = Array.from({ length: n }, (_, i) => ({
    id: i,
    focus() {
      doc.activeElement = this;
    },
  }));
  const container = {
    querySelectorAll: () => items,
    contains: (el) => items.includes(el),
  };
  return { doc, items, container };
}
function key(k, shiftKey = false) {
  return {
    key: k,
    shiftKey,
    prevented: false,
    preventDefault() {
      this.prevented = true;
    },
  };
}

test("Tab on the last element wraps to the first", () => {
  const { doc, items, container } = fakeDom(3);
  items[2].focus();
  const e = key("Tab");
  trapTabKey(e, container, doc);
  assert.equal(doc.activeElement, items[0]);
  assert.ok(e.prevented);
});

test("Shift+Tab on the first element wraps to the last", () => {
  const { doc, items, container } = fakeDom(3);
  items[0].focus();
  const e = key("Tab", true);
  trapTabKey(e, container, doc);
  assert.equal(doc.activeElement, items[2]);
  assert.ok(e.prevented);
});

test("Tab in the middle moves natively", () => {
  const { doc, items, container } = fakeDom(3);
  items[1].focus();
  const e = key("Tab");
  trapTabKey(e, container, doc);
  assert.equal(doc.activeElement, items[1]);
  assert.ok(!e.prevented);
});

test("focus outside the drawer is pulled back in", () => {
  const { doc, items, container } = fakeDom(3);
  doc.activeElement = { id: "outside" };
  const e = key("Tab", true);
  trapTabKey(e, container, doc);
  assert.equal(doc.activeElement, items[2]);
  assert.ok(e.prevented);
});

test("other keys and a missing drawer are ignored", () => {
  const { doc, items, container } = fakeDom(3);
  items[2].focus();
  const e = key("Enter");
  trapTabKey(e, container, doc);
  assert.ok(!e.prevented);
  const t = key("Tab");
  trapTabKey(t, null, doc);
  assert.ok(!t.prevented);
});

test("crossing to desktop width calls back; cleanup removes the listener", () => {
  const listeners = new Set();
  const mql = {
    matches: false,
    addEventListener: (_t, fn) => listeners.add(fn),
    removeEventListener: (_t, fn) => listeners.delete(fn),
  };
  const queries = [];
  const win = {
    matchMedia: (q) => {
      queries.push(q);
      return mql;
    },
  };
  let calls = 0;
  const stop = onDesktopWidth(win, () => calls++);
  assert.deepEqual(queries, ["(min-width: 768px)"]);
  for (const fn of listeners) fn({ matches: false });
  assert.equal(calls, 0);
  for (const fn of listeners) fn({ matches: true });
  assert.equal(calls, 1);
  stop();
  assert.equal(listeners.size, 0);
});

test("every drawer link closes the drawer when tapped", () => {
  const src = readFileSync(`${root}components/MobileNavDrawer.vue`, "utf8");
  const { descriptor } = parse(src);
  const links = [];
  const visit = (node) => {
    if (node.type === 1 && node.tag === "NuxtLink") links.push(node);
    (node.children || []).forEach(visit);
  };
  visit(descriptor.template.ast);
  assert.ok(links.length > 0);
  for (const l of links) {
    const click = l.props.find(
      (p) => p.type === 7 && p.name === "on" && p.arg?.content === "click"
    );
    assert.equal(click?.exp?.content, "setOpen(false)");
  }
});

test("the drawer wires the trap, the breakpoint and the unmount release", () => {
  const src = readFileSync(`${root}components/MobileNavDrawer.vue`, "utf8");
  assert.match(src, /trapTabKey\(/);
  assert.match(src, /onDesktopWidth\(/);
  assert.match(
    src,
    /onBeforeUnmount\(\(\) => \{[^}]*document\.body\.style\.overflow = ""/
  );
});
