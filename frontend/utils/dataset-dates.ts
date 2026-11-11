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
