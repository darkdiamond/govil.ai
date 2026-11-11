// pages/datasets/[slug].vue: Vue binds a lifecycle hook to the component only
// while setup runs synchronously. A hook registered inside another hook, or
// after an `await`, is dropped (the ResizeObserver cleanup never ran), so
// every lifecycle registrar in the page must be called at setup top level.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { babelParse, parse, walk } from "@vue/compiler-sfc";

const filename = new URL("../pages/datasets/[slug].vue", import.meta.url);
const { descriptor } = parse(readFileSync(filename, "utf8"));
const ast = babelParse(descriptor.scriptSetup.content, {
  sourceType: "module",
  plugins: ["typescript"],
});
const HOOKS =
  /^on(Before|)(Mount|Unmount|Update)(ed)?$|^on(Activated|Deactivated|ErrorCaptured)$/;
const FUNCTION = /Function|ArrowFunction|Method/;

function hookCalls() {
  const calls = [];
  const fnDepth = [];
  walk(ast, {
    enter(node) {
      if (FUNCTION.test(node.type)) fnDepth.push(node);
      if (
        node.type === "CallExpression" &&
        node.callee.type === "Identifier" &&
        HOOKS.test(node.callee.name)
      )
        calls.push({
          name: node.callee.name,
          line: node.loc.start.line,
          nested: fnDepth.length > 0,
        });
    },
    leave(node) {
      if (FUNCTION.test(node.type)) fnDepth.pop();
    },
  });
  return calls;
}

test("the page registers its unmount cleanup", () => {
  const names = hookCalls().map((c) => c.name);
  assert.ok(names.includes("onMounted"));
  assert.ok(names.includes("onBeforeUnmount"));
});

test("every lifecycle hook is registered at setup top level", () => {
  for (const c of hookCalls())
    assert.equal(
      c.nested,
      false,
      `${c.name} at script line ${c.line} is inside a function`
    );
});
