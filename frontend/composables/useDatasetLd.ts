// Shared Schema.org Dataset JSON-LD builders.
//
// Two entry points:
//   buildDatasetLd        — full Dataset for the detail page <script type="application/ld+json">
//   buildDatasetLdSummary — compact-but-Google-valid Dataset for CollectionPage.hasPart arrays
//
// Both emit every field Google Search Console flagged (description, license,
// creator, publisher) so collection pages stop tripping the Dataset validator
// on their `hasPart` children.

import type { ManifestEntry, SeoMeta, SlimEntry } from "~/types/manifest";
import { buildLicenseLd, type LicenseLd } from "~/utils/dataset-license";
import { datasetPath, SITE_URL } from "~/utils/paths";
import { publicResourceUrl, resourceFormat } from "~/utils/resource-url";

// Summary builders accept the slim search-index shape (collection pages no
// longer carry full ManifestEntry objects). ManifestEntry is structurally
// assignable to this, so detail-page callers don't change. `notes` is absent
// from SlimEntry — summary_he is near-universal, and the rare gap falls back
// to the title.
type LdSource = SlimEntry & { notes?: string; seo?: SeoMeta };

const GOV_IL = "https://www.gov.il";

// "Organization", not the more precise "GovernmentOrganization": Google's
// Dataset validator accepts only Person or Organization for creator and
// publisher and flags a subtype as "Invalid object type" (Search Console,
// 2026-11-10). The ministry page's own JSON-LD keeps GovernmentOrganization.
interface OrgLd {
  "@type": "Organization";
  name: string;
  url: string;
}

interface DistributionLd {
  "@type": "DataDownload";
  contentUrl: string;
  encodingFormat?: string;
  name?: string;
  contentSize?: string;
}

export interface DatasetLd {
  "@context": "https://schema.org";
  "@type": "Dataset";
  name: string;
  alternateName?: string[];
  description: string;
  url: string;
  license: LicenseLd;
  creator: OrgLd;
  publisher: OrgLd;
  identifier?: string;
  inLanguage?: string;
  isAccessibleForFree?: boolean;
  isBasedOn?: string;
  keywords?: string[];
  dateModified?: string;
  datePublished?: string;
  version?: number;
  temporalCoverage?: string;
  spatialCoverage?: string;
  distribution?: DistributionLd[];
}

export type DatasetLdSummary = Pick<
  DatasetLd,
  "@type" | "name" | "url" | "description" | "license" | "creator"
>;

// CKAN's `notes` is free-text prose, often 1KB+. Trim at the last word break
// before `max` chars so search snippets don't show a half-token ellipsis
// (Hebrew has no spaces inside words, so a hard slice can chop mid-token).
function trimToWord(s: string, max: number): string {
  if (s.length <= max) return s;
  const cut = s.slice(0, max);
  const lastBreak = Math.max(
    cut.lastIndexOf(" "),
    cut.lastIndexOf("."),
    cut.lastIndexOf("׃"),
    cut.lastIndexOf("—")
  );
  return (
    (lastBreak > max * 0.6 ? cut.slice(0, lastBreak) : cut).trimEnd() + "…"
  );
}

// Description precedence: the recipe's search snippet (agent_data.seo, dataset
// page only), then the short summary_he, then trimmed CKAN notes, then the
// title as last resort (summary_he is almost always present).
export function datasetDescription(entry: LdSource): string {
  if (entry.seo?.description) return entry.seo.description;
  if (entry.summary_he) return entry.summary_he;
  if (entry.notes) return trimToWord(entry.notes, 200);
  return entry.title;
}

// creator/publisher = the producing/publishing ministry. Google Dataset Search
// ranks on both being present, so we emit both even when they reference the
// same entity. When CKAN omits the organization, fall back to a State-of-Israel
// stub so the field is never missing.
export function datasetCreator(entry: LdSource): OrgLd {
  if (!entry.organization) {
    return {
      "@type": "Organization",
      name: "מדינת ישראל",
      url: GOV_IL,
    };
  }
  const url = entry.organization_slug
    ? `${SITE_URL}/ministries/${entry.organization_slug}/`
    : GOV_IL;
  return { "@type": "Organization", name: entry.organization, url };
}

// The page <title>. Google truncates titles around 60 chars in Hebrew SERPs.
// useSeo no longer auto-appends " — govil.ai" (the brand goes through
// og:site_name instead), so the full 60 are ours. A recipe's seo.title
// (agent_data.seo, ≤60 chars) is used verbatim. Otherwise append the ministry
// to the CKAN title with a thin separator only when the result still fits.
export function datasetSeoTitle(entry: LdSource): string {
  if (entry.seo?.title) return entry.seo.title;
  const t = entry.title;
  const org = entry.organization;
  const withOrg = org ? `${t} · ${org}` : t;
  return withOrg.length <= 60 ? withOrg : t;
}

// The name people search for: the recipe's seo.name (its h1), else the CKAN
// title. Used by the JSON-LD and the breadcrumb, so they agree.
export function datasetName(entry: LdSource): string {
  return entry.seo?.name || entry.title;
}

// The other names of the dataset: the CKAN title when the recipe renamed it,
// then the recipe's spelling variants. Never repeats `name`.
export function datasetAlternateNames(entry: LdSource): string[] {
  const name = datasetName(entry);
  const out: string[] = [];
  for (const n of [entry.title, ...(entry.seo?.alternate_names ?? [])]) {
    if (n && n !== name && !out.includes(n)) out.push(n);
  }
  return out;
}

export function buildDatasetLd(
  entry: ManifestEntry,
  opts: { canonical: string }
): DatasetLd {
  const creator = datasetCreator(entry);
  const alternateName = datasetAlternateNames(entry);
  const ld: DatasetLd = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: datasetName(entry),
    ...(alternateName.length ? { alternateName } : {}),
    description: datasetDescription(entry),
    url: opts.canonical,
    license: buildLicenseLd(entry.license, entry.source?.terms_url),
    creator,
    publisher: creator,
    identifier: entry.id,
    inLanguage: "he",
    isAccessibleForFree: true,
    isBasedOn:
      entry.source?.source_url ||
      entry.source?.home_url ||
      "https://data.gov.il",
  };
  if (entry.tags?.length) ld.keywords = entry.tags;
  if (entry.metadata_modified) {
    ld.dateModified = entry.metadata_modified;
    // We don't track CKAN's metadata_created separately; metadata_modified is
    // a safe proxy (it equals creation time for sources that never change,
    // and the latest revision otherwise).
    ld.datePublished = entry.metadata_modified;
  }
  if (entry.version) ld.version = entry.version;
  if (entry.temporal_coverage) ld.temporalCoverage = entry.temporal_coverage;
  if (entry.spatial_coverage) ld.spatialCoverage = entry.spatial_coverage;
  if (entry.resources?.length) {
    ld.distribution = entry.resources.map((r) => {
      const dist: DistributionLd = {
        "@type": "DataDownload",
        contentUrl: publicResourceUrl(r.url),
      };
      const format = resourceFormat(r);
      if (format) dist.encodingFormat = format;
      if (r.name) dist.name = r.name;
      if (r.size_bytes) dist.contentSize = String(r.size_bytes);
      return dist;
    });
  }
  return ld;
}

export function buildDatasetLdSummary(entry: LdSource): DatasetLdSummary {
  return {
    "@type": "Dataset",
    name: entry.title,
    url: `${SITE_URL}${datasetPath(entry)}`,
    description: datasetDescription(entry),
    license: buildLicenseLd(entry.license),
    creator: datasetCreator(entry),
  };
}
