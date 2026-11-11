// How DatasetExplorer displays a datastore column's header and cells.

export interface Col {
  id: string;
  numeric: boolean;
  date: boolean;
  /** CKAN Data Dictionary (fields[].info) — publisher-curated Hebrew
   *  label/explanation. Present on ~15% of data.gov.il resources. */
  label?: string;
  notes?: string;
}

// Display label for a column: publisher's Data Dictionary label when
// present, otherwise the raw field id prettified — underscores→spaces,
// camelCase split (operator_nm → "operator nm", WinnersMeshapryDiur →
// "Winners Meshapry Diur"). Hebrew ids pass through unchanged. Sorting
// always uses the raw id.
export function colLabel(col: Col): string {
  if (col.label) return col.label;
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
