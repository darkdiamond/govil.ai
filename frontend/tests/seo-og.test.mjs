// utils/seo-og.ts (the og:image tags) and the feed autodiscovery link.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/seo-og.ts`],
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
const { ogImageMeta, DEFAULT_OG_SIZE } = mod.exports;

const tag = (meta, key) =>
  meta.find((m) => m.property === key || m.name === key)?.content;

test("the default image carries its real size and no alt", () => {
  const { url, meta } = ogImageMeta({});
  assert.equal(url, "https://govil.ai/og-default.png");
  assert.equal(tag(meta, "og:image"), url);
  assert.equal(tag(meta, "twitter:image"), url);
  assert.equal(tag(meta, "og:image:width"), String(DEFAULT_OG_SIZE.width));
  assert.equal(tag(meta, "og:image:height"), String(DEFAULT_OG_SIZE.height));
  assert.equal(tag(meta, "og:image:alt"), undefined);
});

test("the default size matches public/og-default.png", async () => {
  const { readFile } = await import("node:fs/promises");
  const png = await readFile(`${root}public/og-default.png`);
  assert.equal(png.readUInt32BE(16), DEFAULT_OG_SIZE.width);
  assert.equal(png.readUInt32BE(20), DEFAULT_OG_SIZE.height);
});

test("a page image gets its size and alt", () => {
  const { url, meta } = ogImageMeta({
    path: "/news/a/hero-16x9-1.jpg",
    width: 1600,
    height: 900,
    alt: " איור ",
  });
  assert.equal(url, "https://govil.ai/news/a/hero-16x9-1.jpg");
  assert.equal(tag(meta, "og:image:width"), "1600");
  assert.equal(tag(meta, "og:image:height"), "900");
  assert.equal(tag(meta, "og:image:alt"), "איור");
  assert.equal(tag(meta, "twitter:image:alt"), "איור");
});

test("a page image of unknown size emits no size tags", () => {
  const { meta } = ogImageMeta({ path: "/x.jpg", width: 1600 });
  assert.equal(tag(meta, "og:image:width"), undefined);
  assert.equal(tag(meta, "og:image:height"), undefined);
});

test("every page links the news feed for autodiscovery", async () => {
  Object.assign(globalThis, { defineNuxtConfig: (config) => config });
  const { default: config } = await import("../nuxt.config.ts");
  const feed = config.app.head.link.find(
    (l) => l.rel === "alternate" && l.type === "application/rss+xml"
  );
  assert.equal(feed?.href, "/news/feed.xml");
});
