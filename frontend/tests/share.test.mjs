// Share links: every target carries the canonical URL exactly once, encoded
// once (Hebrew slugs arrive percent-encoded from the page), with utm tags.
import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = fileURLToPath(new URL("..", import.meta.url));
const { outputFiles } = await build({
  entryPoints: [`${root}utils/share.ts`],
  bundle: true,
  write: false,
  format: "cjs",
  platform: "node",
});
const mod = { exports: {} };
new Function("module", "exports", outputFiles[0].text)(mod, mod.exports);
const { buildShareLinks, withUtm } = mod.exports;

const url = `https://govil.ai/datasets/${encodeURI("רופאים-מורשים-abc123")}/`;
const title = "רופאים מורשים & מומחים";
const links = buildShareLinks({ url, title, text: "תקציר קצר" });
const byNet = Object.fromEntries(links.map((l) => [l.network, l]));

test("all six destinations, each with a Hebrew accessible name", () => {
  assert.deepEqual(Object.keys(byNet), [
    "whatsapp",
    "telegram",
    "x",
    "facebook",
    "linkedin",
    "email",
  ]);
  for (const l of links) assert.match(l.ariaLabel, /^שיתוף ב/);
});

test("withUtm keeps the encoded path and adds the network", () => {
  const u = withUtm(url, "x");
  assert.ok(u.startsWith(url + "?"), u);
  assert.ok(!u.includes("%25"), "no double encoding");
  const p = new URL(u).searchParams;
  assert.equal(p.get("utm_source"), "share");
  assert.equal(p.get("utm_medium"), "x");
});

test("url params decode back to canonical + utm, encoded once", () => {
  for (const net of ["telegram", "x"]) {
    const p = new URL(byNet[net].href).searchParams;
    assert.equal(p.get("url"), withUtm(url, net));
    assert.equal(p.get("text"), title);
  }
  assert.equal(
    new URL(byNet.facebook.href).searchParams.get("u"),
    withUtm(url, "facebook")
  );
  assert.equal(
    new URL(byNet.linkedin.href).searchParams.get("url"),
    withUtm(url, "linkedin")
  );
  assert.equal(
    new URL(byNet.whatsapp.href).searchParams.get("text"),
    `${title}\n${withUtm(url, "whatsapp")}`
  );
  for (const l of links) {
    const decodedOnce = decodeURIComponent(l.href);
    assert.ok(decodedOnce.includes(url), `${l.network} carries the URL`);
  }
});

test("mailto has subject + body with the description and link", () => {
  const h = byNet.email.href;
  assert.ok(h.startsWith("mailto:?subject="));
  const p = new URLSearchParams(h.slice("mailto:?".length));
  assert.equal(p.get("subject"), title);
  assert.equal(p.get("body"), `תקציר קצר\n\n${withUtm(url, "email")}`);
});

test("no text: email body is just the link", () => {
  const [email] = buildShareLinks({ url, title }).filter(
    (l) => l.network === "email"
  );
  const p = new URLSearchParams(email.href.slice("mailto:?".length));
  assert.equal(p.get("body"), withUtm(url, "email"));
});
