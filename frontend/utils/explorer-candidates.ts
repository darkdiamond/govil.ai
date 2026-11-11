// Which of a dataset's resources DatasetExplorer offers as tabs. Pure: the
// component calls it from a computed over its props.
import type { ResourceEntry } from "~/types/manifest";
import { resourceFormat } from "~/utils/resource-url";

export interface Candidate {
  rid: string;
  name: string;
  format: string;
  url: string;
  /** Legacy data.json has no datastore_active flags — the runtime
   *  limit=0 probe decides whether the section stays. */
  verified: boolean;
}

const RESOURCE_URL_RE =
  /\/resource\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\//;

export function resourceId(r: ResourceEntry): string | null {
  return r.id ?? r.url.match(RESOURCE_URL_RE)?.[1] ?? null;
}

export function explorerCandidates(
  resources: ResourceEntry[] | undefined,
  primaryResourceId: string | undefined
): Candidate[] {
  resources = resources ?? [];
  const hasFlags = resources.some(
    (r) => typeof r.datastore_active === "boolean"
  );
  const out: Candidate[] = [];
  const seen = new Set<string>();

  if (hasFlags) {
    for (const r of resources) {
      const rid = resourceId(r);
      if (!rid || seen.has(rid) || r.datastore_active !== true) continue;
      seen.add(rid);
      out.push({
        rid,
        name: r.name || resourceFormat(r) || "קובץ",
        format: resourceFormat(r),
        url: r.url,
        verified: true,
      });
    }
    // Primary resource first — it's the file the page's content is based on.
    out.sort(
      (a, b) =>
        Number(b.rid === primaryResourceId) -
        Number(a.rid === primaryResourceId)
    );
    return out;
  }

  // Legacy data.json (no flags anywhere): expose only the primary resource,
  // unverified — the schema probe collapses the section if it isn't
  // datastore-backed. Probing every resource per page view would be too
  // chatty for a question whose answer is static.
  const primary =
    resources.find((r) => resourceId(r) === primaryResourceId) ??
    resources.find((r) => resourceId(r) !== null);
  const rid = primary ? resourceId(primary) : null;
  if (primary && rid) {
    out.push({
      rid,
      name: primary.name || resourceFormat(primary) || "קובץ",
      format: resourceFormat(primary),
      url: primary.url,
      verified: false,
    });
  }
  return out;
}
