// Shared Schema.org Dataset JSON-LD builders.
//
// Two entry points:
//   buildDatasetLd        — full Dataset for the detail page <script type="application/ld+json">
//   buildDatasetLdSummary — compact-but-Google-valid Dataset for CollectionPage.hasPart arrays
//
// Both emit every field Google Search Console flagged (description, license,
// creator, publisher) so collection pages stop tripping the Dataset validator
// on their `hasPart` children.

import type { ManifestEntry, SlimEntry } from "~/types/manifest";
import { buildLicenseLd, type LicenseLd } from "~/utils/dataset-license";
import { publicResourceUrl } from "~/utils/resource-url";

// Summary builders accept the slim search-index shape (collection pages no
// longer carry full ManifestEntry objects). ManifestEntry is structurally
// assignable to this, so detail-page callers don't change. `notes` is absent
// from SlimEntry — summary_he is near-universal, and the rare gap falls back
// to the title.
type LdSource = SlimEntry & { notes?: string };

const SITE_URL = "https://govil.ai";
const GOV_IL = "https://www.gov.il";

interface OrgLd {
  "@type": "GovernmentOrganization";
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

// Description precedence: agent's short summary_he, then trimmed CKAN notes,
// then the title as last resort (selector gates publish on agent success, so
// summary_he is almost always present).
export function datasetDescription(entry: LdSource): string {
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
      "@type": "GovernmentOrganization",
      name: "מדינת ישראל",
      url: GOV_IL,
    };
  }
  const url = entry.organization_slug
    ? `${SITE_URL}/ministries/${entry.organization_slug}/`
    : GOV_IL;
  return { "@type": "GovernmentOrganization", name: entry.organization, url };
}

export function buildDatasetLd(
  entry: ManifestEntry,
  opts: { canonical: string }
): DatasetLd {
  const creator = datasetCreator(entry);
  const ld: DatasetLd = {
    "@context": "https://schema.org",
    "@type": "Dataset",
    name: entry.title,
    description: datasetDescription(entry),
    url: opts.canonical,
    license: buildLicenseLd(entry.license),
    creator,
    publisher: creator,
    identifier: entry.id,
    inLanguage: "he",
    isAccessibleForFree: true,
    isBasedOn: "https://data.gov.il",
  };
  if (entry.tags_he?.length) ld.keywords = entry.tags_he;
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
      if (r.format) dist.encodingFormat = r.format;
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
    url: `${SITE_URL}/datasets/${encodeURI(entry.page_slug || entry.id)}/`,
    description: datasetDescription(entry),
    license: buildLicenseLd(entry.license),
    creator: datasetCreator(entry),
  };
}
