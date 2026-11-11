// The site's origin and the paths of its dataset and tag pages, in one place
// for the app code (.vue/.ts). The build scripts (scripts/build-sitemap.mjs,
// scripts/gen-redirects.mjs) run under plain node and keep their own copies
// of the same forms; nuxt.config.ts lists prerender routes decoded, not
// encoded, so it builds its own.

/** Absolute origin for canonical URLs, breadcrumbs and JSON-LD. */
export const SITE_URL = "https://govil.ai";

/** `/datasets/<page_slug>/`, percent-encoded for the wire (page_slug is a
 *  Hebrew title slug + id slice). A legacy entry without a page_slug falls
 *  back to its CKAN id. */
export function datasetPath(entry: {
  id: string;
  page_slug?: string | null;
}): string {
  return `/datasets/${encodeURI(entry.page_slug || entry.id)}/`;
}

/** `/tags/<slug>/`, percent-encoded (tag slugs keep their Hebrew letters). */
export function tagPath(slug: string): string {
  return `/tags/${encodeURI(slug)}/`;
}
