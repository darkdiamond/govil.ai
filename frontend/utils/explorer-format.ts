// How DatasetExplorer displays a datastore column's header and cells.
import { publicResourceUrl } from "~/utils/resource-url";

export interface Col {
  id: string;
  numeric: boolean;
  date: boolean;
  /** CKAN Data Dictionary (fields[].info) — publisher-curated Hebrew
   *  label/explanation. Present on ~15% of data.gov.il resources. */
  label?: string;
  notes?: string;
  /** Every non-empty cell on the first page was a URL: rendered as links
   *  and placed first. Set by withLinkCols. */
  link?: boolean;
}

const GENERIC_LINK_ID = /^(?:links?|urls?|href)$/i;

// Display label for a column: publisher's Data Dictionary label when
// present, otherwise the raw field id prettified — underscores→spaces,
// camelCase split (operator_nm → "operator nm", WinnersMeshapryDiur →
// "Winners Meshapry Diur"). Hebrew ids pass through unchanged. Sorting
// always uses the raw id.
export function colLabel(col: Col): string {
  if (col.label) return col.label;
  // A bare "link" / "url" id says nothing to a Hebrew reader. Any other id
  // ("doc_url", "gis_url", "קישור לתוכנית") is kept: it tells two link
  // columns apart, and it still fits if later pages hold text, not URLs.
  if (col.link && GENERIC_LINK_ID.test(col.id.trim())) return "קישור";
  return col.id
    .replace(/_/g, " ")
    .replace(/([a-z\d])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim();
}

// Many CKAN columns store dates as text — "2027-04-06 00:00:00.000".
// Trim the redundant midnight time for display; non-midnight times are
// meaningful and kept verbatim.
const MIDNIGHT_RE = /^(\d{4}-\d{2}-\d{2})[T ]00:00:00(?:\.0+)?$/;

export function cellText(v: unknown, col: Col): string {
  if (v === null || v === undefined || v === "") return "—";
  const s = String(v);
  if (col.date) return s.slice(0, 10);
  const m = s.match(MIDNIGHT_RE);
  if (m) return m[1]!;
  return s;
}

// A cell whose whole value is an absolute http(s) URL renders as a link
// (decision PDFs, permit documents, …): plain text cut at 28ch with no
// href helped nobody. publicResourceUrl drops javascript:/data: and
// rewrites the OAuth-walled e.data.gov.il hosts; "" = not a link.
const URL_CELL_RE = /^https?:\/\/\S+$/i;

export function cellLink(v: unknown): string {
  if (typeof v !== "string") return "";
  const s = v.trim();
  if (!URL_CELL_RE.test(s)) return "";
  return publicResourceUrl(s);
}

// Columns whose non-empty cells on the sample page are all links. Decided
// once per resource, from its first page, so columns don't jump around
// between pages or searches.
export function linkColumnIds(
  rows: Record<string, unknown>[],
  cols: Col[]
): Set<string> {
  const out = new Set<string>();
  for (const col of cols) {
    if (col.numeric || col.date) continue;
    let seen = 0;
    let ok = true;
    for (const row of rows) {
      const v = row[col.id];
      if (v === null || v === undefined || v === "") continue;
      seen++;
      if (!cellLink(v)) {
        ok = false;
        break;
      }
    }
    if (ok && seen) out.add(col.id);
  }
  return out;
}

// Link columns first (RTL: the rightmost, visible without scrolling); the
// rest keep CKAN's order.
export function withLinkCols(cols: Col[], linkIds: Set<string>): Col[] {
  const mark = (c: Col): Col => ({ ...c, link: linkIds.has(c.id) });
  return [
    ...cols.filter((c) => linkIds.has(c.id)).map(mark),
    ...cols.filter((c) => !linkIds.has(c.id)).map(mark),
  ];
}
