// Rewrites a CKAN resource URL into one an anonymous browser can download.
// Mirrors services/shared/ckan.py::public_resource_url — the scanner
// normalizes on ingest; this is the render-time belt for docs scanned before
// a rule existed.
//
//   - e.data.gov.il / aws-e.data.gov.il sit behind an OAuth wall (Google IAP,
//     AWS ALB); the same path on data.gov.il is public.
//   - A /he/ or /en/ locale prefix before /dataset/ is routed to the new
//     data.gov.il frontend, which answers with its "page not found" screen
//     instead of the file. The bare /dataset/... path downloads.
//   - Only absolute http(s) URLs with a host are rendered as links. CKAN
//     resource URLs are publisher-supplied; a `javascript:`/`data:` URL would
//     otherwise become a clickable script link on govil.ai. The scheme is
//     judged with whitespace/control chars removed, as a browser would
//     (`java\tscript:`). Anything else collapses to "".
//
// Both sides run the shared vectors in
// frontend/tests/fixtures/resource-url-vectors.json.
const GATED_HOST = /^https?:\/\/(?:aws-)?e\.data\.gov\.il\//;
const LOCALE_PREFIX = /^https:\/\/data\.gov\.il\/(?:he|en)\/(?=dataset\/)/;

// Python: urlsplit(probe).scheme in (http, https) and a non-empty netloc.
const SAFE_SCHEME = /^https?:\/\/[^/?#]/i;
const IGNORED_CHARS = /[\x00-\x20\x7f]/g;

export function publicResourceUrl(url: string | null | undefined): string {
  if (!url) return "";
  const trimmed = url.trim();
  if (!SAFE_SCHEME.test(trimmed.replace(IGNORED_CHARS, ""))) return "";
  return trimmed
    .replace(GATED_HOST, "https://data.gov.il/")
    .replace(LOCALE_PREFIX, "https://data.gov.il/");
}

// The file type shown on the download badge and emitted as the JSON-LD
// DataDownload's encodingFormat (Google flags a distribution without one).
// CKAN's `format` is publisher-supplied and sometimes blank; the URL's file
// extension (".../download/report.docx") then names the type. Upper-case,
// "" when neither says. Only the path's last segment counts (a bare host's TLD
// is not a format), and web-page extensions are not file formats. Mirrored on
// ingest by services/scanner/models.py::resource_format (shared
// `format_vectors` in frontend/tests/fixtures/resource-url-vectors.json).
const URL_EXT = /\.([a-z0-9]{1,8})$/i;
const PAGE_EXTS = new Set(["ASPX", "ASP", "ASHX", "PHP", "HTM", "HTML", "JSP"]);

export function resourceFormat(r: {
  format?: string | null;
  url?: string | null;
}): string {
  const fmt = (r.format ?? "").trim();
  if (fmt) return fmt.toUpperCase();
  let path: string;
  try {
    path = new URL(r.url ?? "").pathname;
  } catch {
    return "";
  }
  const ext = (path.split("/").pop()?.match(URL_EXT)?.[1] ?? "").toUpperCase();
  return PAGE_EXTS.has(ext) ? "" : ext;
}
