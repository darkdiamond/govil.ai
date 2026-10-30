import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { parse } from "@vue/compiler-sfc";
import { compile } from "@vue/compiler-ssr";
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";

// Render the actual page template (not a copied condition), with a minimal
// payload so this regression stays offline and independent of generated data.
const filename = new URL("../pages/datasets/[slug].vue", import.meta.url);
const { descriptor } = parse(readFileSync(filename, "utf8"));
const { code } = compile(descriptor.template.content);
const ssrRender = new Function("require", code)(createRequire(import.meta.url));
const resource = {
  url: "https://data.gov.il/dataset/a698417e-e51d-43cd-b82f-356d8cf9de0e/resource/example/download/example.csv",
  format: "CSV",
  name: "example.csv",
};

const boiSource = {
  provider: "boi_sdmx",
  source_name_he: "בנק ישראל",
  home_url: "https://www.boi.org.il/",
  source_url: "https://www.boi.org.il/roles/monetarypolicy/",
  terms_url: "https://www.boi.org.il/website_terms/",
  attribution_he: "מקור הנתונים: בנק ישראל",
  download_label_he: "הורדת CSV מבנק ישראל",
  explorer: false,
};

async function renderPage(
  source_status,
  resources = [resource],
  source = undefined
) {
  const app = createSSRApp({
    ssrRender,
    setup: () => ({
      entry: {
        id: "a698417e-e51d-43cd-b82f-356d8cf9de0e",
        title: "מאגר",
        source_status,
        resources,
        source,
      },
      // Same derivation as the page's computeds (no source = data.gov.il defaults).
      sourceInfo: source ?? null,
      sourceName: source?.source_name_he ?? "data.gov.il",
      hasExplorer: source?.explorer ?? true,
      sourceHref: source?.source_url || source?.home_url || "",
      termsHref: source?.terms_url || "",
      body: "<h1>Archived analysis</h1>",
      unavailableSinceHe: "",
      datasetUrl: "https://govil.ai/datasets/example/",
      hasMeta: Boolean(source),
      dataVintage: null,
      related: [],
      allTags: [],
      publicResourceUrl: (url) => url,
      formatClass: () => "fmt-csv",
      formatBytes: String,
    }),
  });
  for (const name of ["NuxtLink", "AdSlot", "ReportIssue"]) {
    app.component(name, { render: () => null });
  }
  app.component("DatasetExplorer", {
    render: () => h("div", { id: "explorer-stub" }),
  });
  return renderToString(app);
}

test("unavailable dataset preserves archive but does not offer broken downloads", async () => {
  const html = await renderPage("unavailable");
  assert.match(html, /unavailable-banner/);
  assert.match(html, /Archived analysis/);
  assert.doesNotMatch(html, /קבצים להורדה/);
  assert.doesNotMatch(html, /<a\b[^>]*\bdownload\b/);
  assert.ok(!html.includes(resource.url));
});

for (const status of ["available", undefined]) {
  test(`available or legacy dataset (${status}) retains downloads`, async () => {
    const html = await renderPage(status);
    assert.match(html, /קבצים להורדה/);
    assert.match(html, /<a\b[^>]*\bdownload\b/);
    assert.ok(html.includes(resource.url));
    assert.doesNotMatch(html, /unavailable-banner/);
  });
}

test("dataset without resources has no download section", async () => {
  const html = await renderPage("available", []);
  assert.doesNotMatch(html, /קבצים להורדה/);
  assert.doesNotMatch(html, /<a\b[^>]*\bdownload\b/);
});

test("data.gov.il dataset keeps the live explorer and the default labels", async () => {
  const html = await renderPage("available");
  assert.match(html, /explorer-stub/);
  assert.match(html, />הורדה</);
  assert.doesNotMatch(html, /גוף מפרסם/);
});

test("provider dataset credits its source and has no CKAN explorer", async () => {
  const html = await renderPage("available", [resource], boiSource);
  assert.doesNotMatch(html, /explorer-stub/);
  assert.match(html, /הורדת CSV מבנק ישראל/);
  assert.match(html, /מקור הנתונים: בנק ישראל/);
  assert.ok(html.includes(boiSource.source_url));
});

test("removed provider dataset names its own source in the banner", async () => {
  const html = await renderPage("unavailable", [resource], boiSource);
  assert.match(html, /הוסר ממקור הנתונים \(בנק ישראל\)/);
  assert.doesNotMatch(html, /data\.gov\.il\)/);
});
