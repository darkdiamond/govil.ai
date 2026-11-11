// Dataset pages are SSG documents whose useAsyncData fetcher reads the
// artifacts with node:fs; with payloadExtraction off it re-runs in the
// browser on any client-side navigation and the page 404s. The global
// middleware (middleware/dataset-document.global.ts) uses these to turn
// every such navigation, browser Back included, into a document load.

/** `/datasets/<slug>/` (not the `/datasets/` index). The slug may arrive
 *  percent-encoded or decoded; neither form contains a `/`. */
const DATASET_PAGE_RE = /^\/datasets\/[^/]+\/?$/;

function pathOnly(url: string): string {
  return url.replace(/[?#].*$/, "");
}

export function isDatasetPagePath(url: string): boolean {
  return DATASET_PAGE_RE.test(pathOnly(url));
}

// Encoding-insensitive: the router and window.location may spell the same
// Hebrew path with different percent-encoding (or none), and a trailing
// slash is the same page.
function canonicalPath(url: string): string {
  let p = pathOnly(url);
  try {
    p = decodeURI(p);
  } catch {
    // Malformed escape: compare it as given.
  }
  return p.endsWith("/") ? p : `${p}/`;
}

export function isSamePagePath(a: string, b: string): boolean {
  return canonicalPath(a) === canonicalPath(b);
}
