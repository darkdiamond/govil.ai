"""Pydantic models for the artifacts the pipeline produces.

Per dataset, three artifacts land in `frontend/public/datasets/<id>/`:

    data.json         — DatasetMeta. Scanner-derived facts from CKAN
                        (license, resources, formats, …). Owned by the
                        publisher, sourced from Firestore `sources/<id>`.
    agent_data.json   — AgentData. Interpretive fields a recipe's compute()
                        produces (summary_he, dataset_kind, …).
                        Sourced from Firestore `sources/<id>.agent_data`.
    content.html      — The rendered page body. Synced via GCS.

`manifest.json` (consumed by home + category pages) is a merged view
(DatasetMeta + AgentData + publisher-computed `tags` + `related_ids`, plus
the corpus-wide `tag_index` / `topics` / `tag_redirects`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DatasetKind = Literal[
    "map",          # geographic entities (e.g., antennas, vaccination centers)
    "timeseries",   # time-indexed measurements
    "registry",     # entity list (e.g., NGOs, licensed professionals)
    "rankings",     # ordered/scored entities
    "misc",         # fallback
]


class ResourceEntry(BaseModel):
    """A downloadable file on the dataset page's resources card."""
    model_config = ConfigDict(extra="ignore")

    url: str
    format: str = ""
    name: Optional[str] = None
    size_bytes: Optional[int] = None
    description: Optional[str] = None

    # CKAN resource id — drives the shell's data-explorer section
    # (DatasetExplorer.vue queries /api/3/action/datastore_search with it).
    id: Optional[str] = None
    # True/False from CKAN's `datastore_active`. None = unknown (legacy
    # Firestore doc ingested before the flag existed) — omitted from
    # data.json via exclude_none, and the frontend falls back to probing
    # the primary resource at runtime.
    datastore_active: Optional[bool] = None


class SourceInfo(BaseModel):
    """Where a non-CKAN dataset comes from and how the page credits it —
    the provider's `SourcePresentation` (services/providers/base.py) plus
    the dataset's own source page. None on data.gov.il datasets: the
    frontend's defaults (data.gov.il, live explorer) apply."""
    model_config = ConfigDict(extra="ignore")

    provider: str
    source_name_he: str
    home_url: str
    source_url: Optional[str] = None
    terms_url: Optional[str] = None
    attribution_he: str
    download_label_he: str = "הורדה"
    explorer: bool = False


class DatasetMeta(BaseModel):
    """Scanner-derived per-dataset metadata. Written to `data.json` by the
    publisher from the Firestore `sources/<id>` document.
    """
    model_config = ConfigDict(extra="ignore")

    id: str
    slug: str                                    # deterministic Hebrew→Latin slug
    # URL segment for /datasets/<page_slug>/ — Hebrew title slug + a slice of
    # the CKAN id. Filled by the publisher (_build_page_slugs); empty until then.
    page_slug: str = ""
    title: str
    organization: Optional[str] = None           # human-readable ministry title
    organization_slug: Optional[str] = None      # stable key for /ministries/<slug>/
    tags_he: list[str] = Field(default_factory=list)
    primary_resource_id: Optional[str] = None
    formats: list[str] = Field(default_factory=list)
    metadata_modified: Optional[datetime] = None

    license: Optional[str] = None
    record_count: Optional[int] = None
    resources: list[ResourceEntry] = Field(default_factory=list)

    # CKAN's free-text description. Captured by the scanner so the dataset
    # page can fall back to it for SEO meta-description when the agent's
    # short summary_he is missing (rare — selector gates publish on agent
    # success, but this guarantees a non-empty description even on a
    # transient agent_data.json read failure).
    notes: Optional[str] = None

    # When the agent last (re)built the page for this dataset. Rendered as
    # "הדף נוצר ב-" in the sidebar.
    last_analyzed_at: Optional[datetime] = None

    # Source's `metadata_modified` snapshotted at the moment the agent
    # ran — i.e. the vintage of the data the page's content is based on.
    # Distinct from the live `metadata_modified` above, which the scanner
    # overwrites on every poll. Rendered as "המידע נכון ל-" in the sidebar
    # when present; legacy sources (analyzed before this field existed)
    # leave it None and the frontend falls back to `last_analyzed_at`.
    analyzed_metadata_modified: Optional[datetime] = None

    # Availability of the upstream source at data.gov.il. "available" (the
    # default) or "unavailable" — set by the weekly reconcile sweep when a
    # previously-published dataset is made private/removed upstream. The page
    # is preserved (this snapshot); the frontend renders an archive banner
    # and the explorer its gone-state.
    source_status: str = "available"
    # UTC timestamp when the source was first detected as unavailable.
    unavailable_since: Optional[datetime] = None

    # Non-CKAN sources only (services/providers): the credit block, and the
    # readable id part of page_slug (CKAN uses 8 chars of its UUID).
    source: Optional[SourceInfo] = None
    page_slug_suffix: Optional[str] = None

    version: int = 1


class AgentData(BaseModel):
    """Agent-derived per-dataset judgments. Written to `agent_data.json`
    by the publisher from the Firestore `sources/<id>.agent_data` field.

    `extra='allow'` so future agent fields can be added without breaking
    existing pages (e.g. `key_findings`, `quality_notes`).
    """
    model_config = ConfigDict(extra="allow")

    summary_he: str
    dataset_kind: DatasetKind

    # DEPRECATED — still accepted so existing recipes validate, but ignored:
    # related datasets are computed by the publisher (related.py), and a
    # dataset's tags come from taxonomy/dataset-tags.json (tags.py).
    # `suggested_tags` only feeds the fallback for a dataset not yet curated.
    related_ids: list[str] = Field(default_factory=list, max_length=5)
    suggested_tags: list[str] = Field(default_factory=list, max_length=8)

    # Optional Schema.org-aligned coverage hints. Populated only when the
    # dataset clearly carries time or geo scope (date columns, geographic
    # columns). Emitted into the Dataset JSON-LD as `temporalCoverage` /
    # `spatialCoverage` to help Google Dataset Search ranking. Older pages
    # leave these None and the JSON-LD just omits the fields.
    temporal_coverage: Optional[str] = None
    spatial_coverage: Optional[str] = None

    version: int = 1


class ManifestEntry(BaseModel):
    """Merged per-dataset entry in `manifest.json` (home + category pages).

    Built by the publisher by merging `DatasetMeta` (scanner) + `AgentData`
    (recipe) + publisher-computed `tags` + `related_ids`. Not stored —
    rebuilt on every publish.
    """
    model_config = ConfigDict(extra="ignore")

    # DatasetMeta fields
    id: str
    slug: str
    page_slug: str = ""
    title: str
    organization: Optional[str] = None
    organization_slug: Optional[str] = None
    tags_he: list[str] = Field(default_factory=list)
    primary_resource_id: Optional[str] = None
    formats: list[str] = Field(default_factory=list)
    metadata_modified: Optional[datetime] = None
    license: Optional[str] = None
    record_count: Optional[int] = None
    resources: list[ResourceEntry] = Field(default_factory=list)
    notes: Optional[str] = None
    last_analyzed_at: Optional[datetime] = None
    analyzed_metadata_modified: Optional[datetime] = None
    source: Optional[SourceInfo] = None
    page_slug_suffix: Optional[str] = None

    # AgentData fields (optional — a scanned-but-never-analyzed source has none)
    summary_he: Optional[str] = None
    dataset_kind: Optional[DatasetKind] = None
    temporal_coverage: Optional[str] = None
    spatial_coverage: Optional[str] = None
    suggested_tags: list[str] = Field(default_factory=list)

    # Publisher-computed: canonical display tags (tags.py) and related
    # datasets (related.py). `tags_he` / `suggested_tags` above stay raw.
    tags: list[str] = Field(default_factory=list)
    related_ids: list[str] = Field(default_factory=list, max_length=5)

    source_status: str = "available"
    unavailable_since: Optional[datetime] = None

    version: int = 1


class TagIndexEntry(BaseModel):
    """One paged tag (carried by ≥ TAG_PAGE_MIN datasets)."""
    slug: str
    topic: Optional[str] = None
    count: int
    intro_he: Optional[str] = None
    ministries: dict[str, int] = Field(default_factory=dict)
    related: list[str] = Field(default_factory=list)


class TopicEntry(BaseModel):
    id: str
    label_he: str
    intro_he: str = ""


class Manifest(BaseModel):
    """Aggregated manifest.json consumed by the Nuxt home + category pages."""
    version: int = 1
    generated_at: datetime
    datasets: list[ManifestEntry] = Field(default_factory=list)

    # Canonical tag → its page data, for paged tags only, count DESC
    # (tags.build_tag_index). Tags not in here render as plain chips.
    tag_index: dict[str, TagIndexEntry] = Field(default_factory=dict)
    topics: list[TopicEntry] = Field(default_factory=list)
    # Legacy /tags/<slug>/ segment → its canonical tag page (merged variants
    # only); frontend/scripts/gen-redirects.mjs turns these into Firebase 301s.
    tag_redirects: dict[str, str] = Field(default_factory=dict)
