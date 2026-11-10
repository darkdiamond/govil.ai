import assert from "node:assert/strict";
import test from "node:test";

// nuxt.config.ts calls the auto-imported defineNuxtConfig; outside Nuxt it is
// the identity, so importing the file gives the config object Nuxt sees.
globalThis.defineNuxtConfig = (config) => config;
const { default: config } = await import("../nuxt.config.ts");

// A route that fails to prerender writes no file. If the build went on, the
// deploy would replace the live page with the 404 page while the sitemap and
// IndexNow still list it, so any failed route must fail `nuxt generate`.
test("a failed prerender route fails the build", () => {
  assert.equal(config.nitro.prerender.failOnError, true);
});
