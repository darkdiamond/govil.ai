import type {
  Manifest,
  ManifestEntry,
  SearchIndex,
  SlimEntry,
} from "~/types/manifest";

// Dual-mode loaders for the site's data artifacts. The full manifest.json
// (1.7MB) must never reach a client bundle — pages either bake what they
// need into their prerender payload (useAsyncData + node:fs, server only)
// or fetch the slim /data/search-index.json on demand at runtime.
//
// Both loaders memoize at module level: the data is static per build, so
// during `nuxt generate` each Nitro worker parses the file once instead of
// once per prerendered route, and in the browser repeated SPA navs reuse
// the first fetch.

let searchIndexCache: Promise<SearchIndex> | null = null;
let fullManifestCache: Promise<Manifest> | null = null;

/** Field projection mirroring publish.py::_SEARCH_INDEX_FIELDS — used only
 *  by the server-side fallback when search-index.json hasn't been written
 *  yet (dev checkouts that predate the publisher change). */
function slimEntry(e: ManifestEntry): SlimEntry {
  return {
    id: e.id,
    title: e.title,
    organization: e.organization,
    organization_slug: e.organization_slug,
    summary_he: e.summary_he,
    dataset_kind: e.dataset_kind,
    formats: e.formats,
    tags: e.tags,
    record_count: e.record_count,
    spatial_coverage: e.spatial_coverage,
    license: e.license,
    metadata_modified: e.metadata_modified,
    last_analyzed_at: e.last_analyzed_at,
    page_slug: e.page_slug,
    source_status: e.source_status,
    unavailable_since: e.unavailable_since,
  };
}

async function readPublicJson<T>(rel: string): Promise<T> {
  // Guard the node imports so Vite's client bundler can tree-shake them out —
  // same pattern as pages/datasets/[slug].vue's server-only fetcher.
  const fs = await import("node:fs/promises");
  const path = await import("node:path");
  // Local recipe preview (nuxt.config.ts PREVIEW_ROOT): its overlay first.
  const overlay = process.env.NUXT_PREVIEW_ROOT;
  if (overlay) {
    const body = await fs
      .readFile(path.join(overlay, rel), "utf-8")
      .catch(() => null);
    if (body !== null) return JSON.parse(body) as T;
  }
  const p = path.resolve(process.cwd(), "public", rel);
  return JSON.parse(await fs.readFile(p, "utf-8")) as T;
}

/** Full manifest — SERVER ONLY (prerender/SSR). Throws if called client-side. */
export function loadFullManifestServer(): Promise<Manifest> {
  if (!import.meta.server) {
    return Promise.reject(new Error("loadFullManifestServer is server-only"));
  }
  // A preview's overlay manifest changes under the running server: re-read it.
  if (!fullManifestCache || process.env.NUXT_PREVIEW_ROOT) {
    fullManifestCache = readPublicJson<Manifest>("data/manifest.json");
  }
  return fullManifestCache;
}

/** Slim index. Server: read from public/ (falling back to slimming the full
 *  manifest). Client: one on-demand fetch of /data/search-index.json. */
export function loadSearchIndex(): Promise<SearchIndex> {
  if (!searchIndexCache) {
    searchIndexCache = import.meta.server
      ? readPublicJson<SearchIndex>("data/search-index.json").catch(
          async () => {
            const m = await loadFullManifestServer();
            return {
              version: m.version,
              generated_at: m.generated_at,
              datasets: m.datasets.map(slimEntry),
              tag_index: m.tag_index,
              topics: m.topics,
            } satisfies SearchIndex;
          }
        )
      : $fetch<SearchIndex>("/data/search-index.json");
  }
  return searchIndexCache;
}
