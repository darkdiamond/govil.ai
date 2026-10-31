import { readFile } from "node:fs/promises";
import { join, normalize } from "node:path";

// Local recipe preview only (registered in nuxt.config.ts when
// NUXT_PREVIEW_ROOT is set): serve the overlay's /data/*.json (the
// search index list pages fetch client-side) ahead of public/, which a
// worktree doesn't even have.
export default defineEventHandler(async (event) => {
  const path = event.path.split("?")[0];
  if (!path.startsWith("/data/") || !path.endsWith(".json")) return;
  const rel = normalize(decodeURIComponent(path)).replace(/^\/+/, "");
  if (!rel.startsWith("data/")) return;
  const body = await readFile(
    join(process.env.NUXT_PREVIEW_ROOT!, rel),
    "utf-8"
  ).catch(() => null);
  if (body === null) return;
  setHeader(event, "content-type", "application/json");
  setHeader(event, "cache-control", "no-store");
  return body;
});
