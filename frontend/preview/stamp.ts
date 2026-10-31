import { readFile } from "node:fs/promises";
import { join } from "node:path";

// Local recipe preview only (registered in nuxt.config.ts when
// NUXT_PREVIEW_ROOT is set): the stamp the preview CLI bumps on every
// render, polled by preview/reload.client.ts.
export default defineEventHandler(async (event) => {
  setHeader(event, "cache-control", "no-store");
  try {
    return (
      await readFile(join(process.env.NUXT_PREVIEW_ROOT!, "stamp"), "utf-8")
    ).trim();
  } catch {
    return "";
  }
});
