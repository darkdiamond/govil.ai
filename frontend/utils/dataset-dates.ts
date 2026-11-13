// Dates on dataset pages and cards. Pages are prerendered on a UTC build
// machine and hydrated in the visitor's browser, so the prerendered text must
// depend on neither the build machine's timezone nor its clock.
import { relativeTimeHe } from "~/composables/useRelativeTime";
import { newsDate } from "~/utils/news";

/** Long Hebrew date on the Israel calendar day ("10 בנובמבר 2026"). */
export function datasetDate(iso?: string | null): string {
  return newsDate(iso);
}

/** A card's "updated" line: the absolute date until the component is mounted
 * (prerender and hydration agree), then the relative time on the visitor's
 * clock. */
export function cardDateLabel(
  iso: string | null | undefined,
  mounted: boolean
): string {
  if (mounted) return `עודכן ${relativeTimeHe(iso)}`;
  const date = datasetDate(iso);
  return date ? `עודכן ב-${date}` : "עודכן —";
}

// en-CA formats a date as YYYY-MM-DD, which sorts and compares as text.
const IL_DAY = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Jerusalem",
});

/** The Israel calendar day of a timestamp as "YYYY-MM-DD", or "" if invalid. */
export function israelDay(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : IL_DAY.format(d);
}

/** True when `live` falls on a later Israel calendar day than `snap` (the
 * "updated since the analysis" icon). Missing or invalid stamps are false. */
export function laterIsraelDay(
  live?: string | null,
  snap?: string | null
): boolean {
  const a = israelDay(live);
  const b = israelDay(snap);
  return !!a && !!b && a > b;
}
