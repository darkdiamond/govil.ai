// utils/contact-topics.ts: /contact/?topic= preselects the form's topic only
// when it names one of the options; links into the form use those names.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/contact-topics.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { CONTACT_TOPICS, topicFromQuery } = mod.exports;

test("a query topic that names an option is selected", () => {
  assert.equal(topicFromQuery("נגישות האתר"), "נגישות האתר");
  assert.equal(topicFromQuery(["נגישות האתר", "אחר"]), "נגישות האתר");
});

test("anything else selects nothing", () => {
  assert.equal(topicFromQuery("נגישות"), "");
  assert.equal(topicFromQuery("<script>"), "");
  assert.equal(topicFromQuery(""), "");
  assert.equal(topicFromQuery(undefined), "");
  assert.equal(topicFromQuery(null), "");
  assert.equal(topicFromQuery([]), "");
  assert.equal(topicFromQuery(" נגישות האתר"), "");
});

test("every /contact/?topic= link in the pages names an option", () => {
  const pages = ["accessibility.vue"];
  let seen = 0;
  for (const p of pages) {
    const src = readFileSync(`${root}pages/${p}`, "utf8");
    for (const m of src.matchAll(/\/contact\/\?topic=([^"&]+)/g)) {
      seen++;
      assert.ok(
        CONTACT_TOPICS.includes(decodeURIComponent(m[1])),
        `${p}: ${m[1]} is not a contact topic`
      );
    }
  }
  assert.ok(seen > 0);
});

test("the contact form renders its options from the shared list", () => {
  const src = readFileSync(`${root}pages/contact.vue`, "utf8");
  assert.match(src, /v-for="t in CONTACT_TOPICS"/);
});
