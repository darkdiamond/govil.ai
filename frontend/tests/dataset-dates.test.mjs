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
const { datasetDate, cardDateLabel, israelDay, laterIsraelDay } = mod.exports;

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

test("israelDay is the Israel calendar day, not the UTC one", () => {
  assert.equal(israelDay("2026-11-09T22:30:00Z"), "2026-11-10");
  assert.equal(israelDay("2026-07-09T21:30:00Z"), "2026-07-10"); // IDT, +3
  assert.equal(israelDay("2026-07-09T20:30:00Z"), "2026-07-09");
  assert.equal(israelDay("bad"), "");
  assert.equal(israelDay(null), "");
});

test("laterIsraelDay compares Israel days across UTC midnight", () => {
  // Same Israel day (10 Nov), different UTC days: no icon.
  assert.equal(
    laterIsraelDay("2026-11-10T08:00:00Z", "2026-11-09T22:30:00Z"),
    false
  );
  // Same UTC day (9 Nov), different Israel days: icon.
  assert.equal(
    laterIsraelDay("2026-11-09T22:30:00Z", "2026-11-09T08:00:00Z"),
    true
  );
  assert.equal(
    laterIsraelDay("2026-11-09T08:00:00Z", "2026-11-09T22:30:00Z"),
    false
  );
  assert.equal(laterIsraelDay("2026-11-10T08:00:00Z", null), false);
  assert.equal(laterIsraelDay(undefined, "2026-11-10T08:00:00Z"), false);
});
