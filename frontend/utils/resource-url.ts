// Rewrites a CKAN resource URL into one an anonymous browser can download.
// Mirrors services/scanner/models.py::_public_resource_url — the scanner
// normalizes on ingest; this is the render-time belt for docs scanned before
// a rule existed.
//
//   - e.data.gov.il / aws-e.data.gov.il sit behind an OAuth wall (Google IAP,
//     AWS ALB); the same path on data.gov.il is public.
//   - A /he/ or /en/ locale prefix before /dataset/ is routed to the new
//     data.gov.il frontend, which answers with its "page not found" screen
//     instead of the file. The bare /dataset/... path downloads.
//   - Only http(s) URLs are rendered as links. CKAN resource URLs are
//     publisher-supplied; a `javascript:`/`data:` URL would otherwise become a
//     clickable script link on govil.ai. Anything else collapses to "".
const GATED_HOST = /^https?:\/\/(?:aws-)?e\.data\.gov\.il\//;
const LOCALE_PREFIX = /^https:\/\/data\.gov\.il\/(?:he|en)\/(?=dataset\/)/;

const SAFE_SCHEME = /^https?:\/\//i;

export function publicResourceUrl(url: string | null | undefined): string {
  if (!url) return "";
  const trimmed = url.trim();
  if (!SAFE_SCHEME.test(trimmed)) return "";
  return trimmed
    .replace(GATED_HOST, "https://data.gov.il/")
    .replace(LOCALE_PREFIX, "https://data.gov.il/");
}

// The file type shown on the download badge and emitted as the JSON-LD
// DataDownload's encodingFormat (Google flags a distribution without one).
// CKAN's `format` is publisher-supplied and sometimes blank; the URL's file
// extension (".../download/report.docx") then names the type. Upper-case,
// "" when neither says. Only the path's last segment counts (a bare host's TLD
// is not a format), and web-page extensions are not file formats.
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
