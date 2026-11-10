// agent_data.seo: the recipe's search metadata reaches the dataset page's
// description and Dataset JSON-LD, and a page without it keeps the old output.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}composables/useDatasetLd.ts`],
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
const {
  buildDatasetLd,
  buildDatasetLdSummary,
  datasetDescription,
  datasetName,
  datasetSeoTitle,
} = mod.exports;

const base = {
  id: "aaa",
  slug: "a",
  title: "מאגר נתוני רופאים",
  tags_he: [],
  formats: [],
  related_ids: [],
  version: 1,
  summary_he: "סיכום קצר",
  organization: "משרד הבריאות",
};
const opts = { canonical: "https://govil.ai/datasets/x/" };

test("without seo the page keeps the CKAN title and summary_he", () => {
  const ld = buildDatasetLd(base, opts);
  assert.equal(ld.name, "מאגר נתוני רופאים");
  assert.equal(ld.description, "סיכום קצר");
  assert.equal("alternateName" in ld, false);
  assert.equal(datasetName(base), "מאגר נתוני רופאים");
});

test("seo.name, description and alternate_names drive the Dataset JSON-LD", () => {
  const entry = {
    ...base,
    seo: {
      title: "איתור רופא לפי מספר רישיון",
      description: "חיפוש רופא לפי שם או מספר רישיון",
      name: "פנקס הרופאים",
      alternate_names: ["רשם הרופאים", "פנקס הרופאים", "מאגר נתוני רופאים"],
    },
  };
  const ld = buildDatasetLd(entry, opts);
  assert.equal(ld.name, "פנקס הרופאים");
  assert.deepEqual(ld.alternateName, ["מאגר נתוני רופאים", "רשם הרופאים"]);
  assert.equal(ld.description, "חיפוש רופא לפי שם או מספר רישיון");
  assert.equal(datasetDescription(entry), ld.description);
});

test("the title is seo.title verbatim, else the CKAN title + ministry when it fits", () => {
  assert.equal(
    datasetSeoTitle({ ...base, seo: { title: "איתור רופא" } }),
    "איתור רופא"
  );
  assert.equal(datasetSeoTitle(base), "מאגר נתוני רופאים · משרד הבריאות");
  const long = { ...base, title: "א".repeat(50) };
  assert.equal(datasetSeoTitle(long), long.title);
  assert.equal(
    datasetSeoTitle({ ...base, organization: undefined }),
    base.title
  );
});

test("a partial seo falls back per field", () => {
  const entry = { ...base, seo: { title: "כותרת" } };
  const ld = buildDatasetLd(entry, opts);
  assert.equal(ld.name, "מאגר נתוני רופאים");
  assert.equal(ld.description, "סיכום קצר");
  assert.equal("alternateName" in ld, false);
});

// Google's Dataset validator: description is critical, license and creator
// are flagged (Search Console, 2026-11-10). Both builders must emit all three
// even for a bare entry with no summary, license or organization.
test("both Dataset builders emit description, license and creator", () => {
  const bare = { id: "b", title: "מאגר", tags_he: [], formats: [] };
  for (const ld of [buildDatasetLd(bare, opts), buildDatasetLdSummary(bare)]) {
    assert.equal(ld["@type"], "Dataset");
    assert.ok(ld.description, "description");
    assert.ok(ld.license?.name, "license");
    assert.ok(ld.creator?.name, "creator");
  }
});

// Google accepts only Person or Organization for creator/publisher; a
// GovernmentOrganization was flagged "Invalid object type" on every page.
test("creator and publisher are typed Organization", () => {
  const ld = buildDatasetLd(base, opts);
  assert.equal(ld.creator["@type"], "Organization");
  assert.equal(ld.publisher["@type"], "Organization");
  assert.equal(buildDatasetLdSummary(base).creator["@type"], "Organization");
  const noOrg = { ...base, organization: undefined };
  assert.equal(buildDatasetLd(noOrg, opts).creator["@type"], "Organization");
});

// A CKAN resource with a blank format (02789da8's .docx files, 0180a8e4's
// .rar) still gets an encodingFormat, from its URL's extension.
test("distribution encodingFormat falls back to the URL extension", () => {
  const dl = "https://data.gov.il/dataset/x/resource/y/download";
  const entry = {
    ...base,
    resources: [
      { url: `${dl}/a.csv`, format: "csv", name: "a" },
      { url: `${dl}/.docx`, format: "", name: "methodology" },
      { url: `${dl}/raw-material-deposits.rar?x=1`, format: "" },
      { url: `${dl}/no-extension`, format: "" },
    ],
  };
  const formats = buildDatasetLd(entry, opts).distribution.map(
    (d) => d.encodingFormat
  );
  assert.deepEqual(formats, ["CSV", "DOCX", "RAR", undefined]);
});
