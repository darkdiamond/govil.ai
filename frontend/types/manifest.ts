// Mirror of services/page_builder/schema.py.
//
// Per-dataset structured data is split across two files:
//   datasets/<id>/data.json       → DatasetMeta (scanner-derived facts)
//   datasets/<id>/agent_data.json → AgentData   (agent-derived judgments)
//
// frontend/pages/datasets/[id].vue reads both at SSG time and merges
// them into a `ManifestEntry`-shaped object that all downstream
// rendering consumes. The aggregated data/manifest.json published from
// Firestore already contains the merged shape, so the home + category
// pages need only ManifestEntry.

export type DatasetKind =
  "map" | "timeseries" | "registry" | "rankings" | "misc";

export interface ResourceEntry {
  url: string;
  format: string;
  name?: string;
  size_bytes?: number;
  description?: string;
  /** CKAN resource id — drives the shell's DatasetExplorer (datastore_search).
   *  Present after the datastore_active backfill/republish. */
  id?: string;
  /** true/false from CKAN's `datastore_active`; absent = unknown (legacy
   *  data.json written before the flag was captured). */
  datastore_active?: boolean;
}

/** Where a non-CKAN dataset comes from (services/providers) and how the
 *  page credits it. Absent on data.gov.il datasets: the defaults apply
 *  (data.gov.il, live data explorer). Mirrors schema.py::SourceInfo. */
export interface SourceInfo {
  provider: string;
  source_name_he: string;
  home_url: string;
  source_url?: string;
  terms_url?: string;
  attribution_he: string;
  download_label_he: string;
  /** The shell's live explorer reads the CKAN datastore — CKAN only. */
  explorer: boolean;
}

/** Scanner-derived metadata. Single source of truth: Firestore `sources/<id>` */
export interface DatasetMeta {
  id: string;
  slug: string;
  /** URL segment for /datasets/<page_slug>/ — Hebrew title slug + id slice.
   *  Written by the publisher (_build_page_slugs). */
  page_slug?: string;
  title: string;
  organization?: string;
  organization_slug?: string;
  tags_he: string[];
  primary_resource_id?: string;
  formats: string[];
  metadata_modified?: string;
  license?: string;
  record_count?: number;
  resources?: ResourceEntry[];
  /** CKAN's free-text dataset description. Used as a fallback for the
   *  SEO meta-description when the agent's summary_he is missing. */
  notes?: string;
  last_analyzed_at?: string;
  /** Source's metadata_modified at the moment the agent ran — i.e. the
   *  vintage of the data this page's content is based on. Distinct from
   *  the live `metadata_modified` above. The publisher backfills this
   *  with min(metadata_modified, last_analyzed_at) for legacy sources. */
  analyzed_metadata_modified?: string;
  source_status?: string;
  unavailable_since?: string;
  source?: SourceInfo;
  version: number;
}

/** Agent-derived judgments. Single source of truth: Firestore `sources/<id>.agent_data` */
export interface AgentData {
  summary_he: string;
  dataset_kind: DatasetKind;
  related_ids?: string[];
  /** Optional Schema.org-aligned coverage hints; present only when the
   *  dataset clearly carries time/geo scope. Emitted into Dataset JSON-LD. */
  temporal_coverage?: string;
  spatial_coverage?: string;
  /** 3-5 short Hebrew topic labels chosen by the agent. The shell
   *  renders them as the chip row under the H1, linking to /tags/<slug>/. */
  suggested_tags?: string[];
  version: number;
  // `extra='allow'` on the pydantic side — future fields land here.
  [key: string]: unknown;
}

/** Merged view consumed by every rendering site (home, category pages, dataset page). */
export interface ManifestEntry {
  // DatasetMeta fields
  id: string;
  slug: string;
  page_slug?: string;
  title: string;
  organization?: string;
  organization_slug?: string;
  tags_he: string[];
  primary_resource_id?: string;
  formats: string[];
  metadata_modified?: string;
  license?: string;
  record_count?: number;
  resources?: ResourceEntry[];
  notes?: string;
  last_analyzed_at?: string;
  analyzed_metadata_modified?: string;

  // AgentData fields (optional — a scanned-but-never-analyzed source has none)
  summary_he?: string;
  dataset_kind?: DatasetKind;
  temporal_coverage?: string;
  spatial_coverage?: string;
  suggested_tags?: string[];

  // Publisher-computed
  related_ids: string[];
  embedding?: number[];
  source_status?: string;
  unavailable_since?: string;
  source?: SourceInfo;
  version: number;
}

/** Slim per-dataset projection served as /data/search-index.json.
 *  Written by services/page_builder/publish.py::_write_search_index —
 *  the field set there must stay in sync with this interface. Covers
 *  everything the list/search/home pages render; `ManifestEntry` is
 *  structurally assignable to `SlimEntry`. */
export interface SlimEntry {
  id: string;
  page_slug?: string;
  title: string;
  organization?: string;
  organization_slug?: string;
  summary_he?: string;
  dataset_kind?: DatasetKind;
  formats: string[];
  tags_he: string[];
  suggested_tags?: string[];
  record_count?: number;
  spatial_coverage?: string;
  license?: string;
  metadata_modified?: string;
  last_analyzed_at?: string;
  source_status?: string;
  unavailable_since?: string;
}

/** Shape of /data/search-index.json — the runtime-fetchable slim manifest. */
export interface SearchIndex {
  version: number;
  generated_at: string;
  datasets: SlimEntry[];
  tag_slugs?: Record<string, string>;
}

export interface Manifest {
  version: number;
  generated_at: string;
  datasets: ManifestEntry[];
  // Hebrew tag → URL-safe Hebrew slug (whitespace and URL-reserved chars
  // normalized to `-`). Built by services/page_builder/publish.py.
  tag_slugs?: Record<string, string>;
}
