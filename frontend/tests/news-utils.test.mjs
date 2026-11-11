// utils/news.ts: safeHref, the scheme belt on every model-derived link on a
// news page (article body runs and the "official sources" list).
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/news.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
  // Browser branch of the dual-mode loaders; esbuild's cjs output has no import.meta.
  define: { "import.meta.server": "false" },
  plugins: [
    {
      name: "nuxt-tilde",
      setup(b) {
        b.onResolve({ filter: /^~\// }, (a) => ({
          path: `${root}${a.path.slice(2)}.ts`,
        }));
      },
    },
  ],
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { safeHref } = mod.exports;

test("safeHref refuses script and data schemes", () => {
  for (const href of [
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "JAVASCRIPT:alert(1)",
    " javascript:alert(1)",
    "\tjavascript:alert(1)",
    "\njavascript:alert(1)",
    "java\tscript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "DATA:text/html;base64,PHNjcmlwdD4=",
    "vbscript:msgbox(1)",
    "mailto:a@b.example",
  ]) {
    assert.equal(safeHref(href), null, JSON.stringify(href));
  }
});

test("safeHref refuses protocol-relative URLs", () => {
  for (const href of [
    "//evil.example/x",
    "/\\evil.example/x",
    "/\t/evil.example/x",
    "/\n/evil.example/x",
    "\\\\evil.example/x",
  ]) {
    assert.equal(safeHref(href), null, JSON.stringify(href));
  }
});

test("safeHref keeps https links and same-origin paths", () => {
  assert.equal(
    safeHref("https://www.gov.il/he/departments/news/x"),
    "https://www.gov.il/he/departments/news/x"
  );
  assert.equal(
    safeHref("HTTPS://www.boi.org.il/x"),
    "https://www.boi.org.il/x"
  );
  assert.equal(safeHref("http://www.cbs.gov.il/"), "http://www.cbs.gov.il/");
  assert.equal(safeHref("/datasets/x/"), "/datasets/x/");
});

test("safeHref refuses empty input", () => {
  assert.equal(safeHref(""), null);
  assert.equal(safeHref(null), null);
  assert.equal(safeHref(undefined), null);
});
