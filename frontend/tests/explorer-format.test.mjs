// utils/explorer-candidates.ts + utils/explorer-format.ts: which resources
// DatasetExplorer offers as tabs, and how it labels columns and shows cells.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
async function load(entry) {
  const { outputFiles } = await build({
    entryPoints: [`${root}${entry}`],
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
  return mod.exports;
}
const { explorerCandidates, resourceId } = await load(
  "utils/explorer-candidates.ts"
);
const { colLabel, cellText } = await load("utils/explorer-format.ts");

const DS = "a698417e-e51d-43cd-b82f-356d8cf9de0e";
const R1 = "11111111-1111-4111-8111-111111111111";
const R2 = "22222222-2222-4222-8222-222222222222";
const R3 = "33333333-3333-4333-8333-333333333333";
const url = (rid, ext = "csv") =>
  `https://data.gov.il/dataset/${DS}/resource/${rid}/download/f.${ext}`;

test("resourceId prefers the id, else reads the resource URL", () => {
  assert.equal(resourceId({ id: R1, url: url(R2) }), R1);
  assert.equal(resourceId({ url: url(R2) }), R2);
  assert.equal(resourceId({ url: "https://example.com/x.csv" }), null);
});

test("flagged resources: only datastore-active ones, primary first, deduped", () => {
  const out = explorerCandidates(
    [
      {
        id: R1,
        url: url(R1),
        format: "CSV",
        name: "א",
        datastore_active: true,
      },
      {
        id: R2,
        url: url(R2),
        format: "CSV",
        name: "ב",
        datastore_active: true,
      },
      { id: R3, url: url(R3, "pdf"), format: "PDF", datastore_active: false },
      {
        id: R1,
        url: url(R1),
        format: "CSV",
        name: "dup",
        datastore_active: true,
      },
      // No flag on this one, but another resource has flags: not offered.
      { url: url("44444444-4444-4444-8444-444444444444"), format: "CSV" },
    ],
    R2
  );
  assert.deepEqual(out, [
    { rid: R2, name: "ב", format: "CSV", url: url(R2), verified: true },
    { rid: R1, name: "א", format: "CSV", url: url(R1), verified: true },
  ]);
});

test("flagged resources keep their order when the primary is not among them", () => {
  const out = explorerCandidates(
    [
      { id: R1, url: url(R1), format: "CSV", datastore_active: true },
      { id: R2, url: url(R2), format: "XLSX", datastore_active: true },
    ],
    R3
  );
  assert.deepEqual(
    out.map((c) => [c.rid, c.name]),
    [
      [R1, "CSV"],
      [R2, "XLSX"],
    ]
  );
});

test("legacy resources (no flags): the primary alone, unverified", () => {
  const out = explorerCandidates(
    [
      { url: url(R1), format: "CSV", name: "first" },
      { url: url(R2), format: "", name: "" },
    ],
    R2
  );
  // Blank format: resourceFormat falls back to the URL extension.
  assert.deepEqual(out, [
    { rid: R2, name: "CSV", format: "CSV", url: url(R2), verified: false },
  ]);
});

test("legacy resources: no primary match falls back to the first with an id", () => {
  const out = explorerCandidates(
    [
      { url: "https://example.com/x.csv", format: "CSV" },
      { url: url(R1), format: "CSV", name: "first" },
    ],
    undefined
  );
  assert.deepEqual(out, [
    { rid: R1, name: "first", format: "CSV", url: url(R1), verified: false },
  ]);
});

test("no resources, or none with an id: no candidates", () => {
  assert.deepEqual(explorerCandidates(undefined, undefined), []);
  assert.deepEqual(explorerCandidates([], R1), []);
  assert.deepEqual(
    explorerCandidates([{ url: "https://example.com/x", format: "" }], R1),
    []
  );
});

const col = (over = {}) => ({ id: "x", numeric: false, date: false, ...over });

test("colLabel: the dictionary label wins, else the id prettified", () => {
  assert.equal(colLabel(col({ id: "op_nm", label: "מפעיל" })), "מפעיל");
  assert.equal(colLabel(col({ id: "operator_nm" })), "operator nm");
  assert.equal(
    colLabel(col({ id: "WinnersMeshapryDiur" })),
    "Winners Meshapry Diur"
  );
  assert.equal(colLabel(col({ id: "__a__b__" })), "a b");
  assert.equal(colLabel(col({ id: "שם_יישוב" })), "שם יישוב");
  assert.equal(colLabel(col({ id: "Year2024Total" })), "Year2024 Total");
});

test("cellText: blanks become a dash, dates lose a midnight time", () => {
  assert.equal(cellText(null, col()), "—");
  assert.equal(cellText(undefined, col()), "—");
  assert.equal(cellText("", col()), "—");
  assert.equal(cellText(0, col()), "0");
  assert.equal(cellText(false, col()), "false");
  assert.equal(cellText("2027-04-06 00:00:00.000", col()), "2027-04-06");
  assert.equal(cellText("2027-04-06T00:00:00", col()), "2027-04-06");
  assert.equal(cellText("2027-04-06 13:45:00", col()), "2027-04-06 13:45:00");
  assert.equal(
    cellText("2027-04-06T13:45:00", col({ date: true })),
    "2027-04-06"
  );
  assert.equal(cellText("שלום", col()), "שלום");
});
