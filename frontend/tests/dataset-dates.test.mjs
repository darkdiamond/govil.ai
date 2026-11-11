// utils/dataset-dates.ts: dates on dataset pages and cards are prerendered on
// a UTC build machine and hydrated in the visitor's browser, so the static
// text must not depend on the build machine's timezone or clock.
process.env.TZ = "UTC";

import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/dataset-dates.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
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
const { datasetDate, cardDateLabel } = mod.exports;

function withClock(iso, fn) {
  const real = Date.now;
  Date.now = () => Date.parse(iso);
  try {
    return fn();
  } finally {
    Date.now = real;
  }
}

test("a late-evening UTC stamp shows the Israel calendar day", () => {
  assert.equal(datasetDate("2026-11-09T22:30:00Z"), "10 בנובמבר 2026");
  assert.equal(datasetDate("2026-11-09T12:00:00Z"), "9 בנובמבר 2026");
});

test("missing or invalid stamps format as empty", () => {
  assert.equal(datasetDate(null), "");
  assert.equal(datasetDate(undefined), "");
  assert.equal(datasetDate("not a date"), "");
});

test("the card's prerendered label does not depend on the clock", () => {
  const iso = "2026-11-09T22:30:00Z";
  const a = withClock("2026-11-10T08:00:00Z", () => cardDateLabel(iso, false));
  const b = withClock("2026-11-13T08:00:00Z", () => cardDateLabel(iso, false));
  assert.equal(a, b);
  assert.equal(a, "עודכן ב-10 בנובמבר 2026");
});

test("after mount the card shows the relative time", () => {
  const iso = "2026-11-09T22:30:00Z";
  assert.equal(
    withClock("2026-11-10T08:00:00Z", () => cardDateLabel(iso, true)),
    "עודכן היום"
  );
  assert.equal(
    withClock("2026-11-13T08:00:00Z", () => cardDateLabel(iso, true)),
    "עודכן לפני 3 ימים"
  );
});
