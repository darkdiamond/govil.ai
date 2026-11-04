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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

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
    name: str | None = None
    size_bytes: int | None = None
    description: str | None = None

    # CKAN resource id — drives the shell's data-explorer section
    # (DatasetExplorer.vue queries /api/3/action/datastore_search with it).
    id: str | None = None
    # True/False from CKAN's `datastore_active`. None = unknown (legacy
    # Firestore doc ingested before the flag existed) — omitted from
    # data.json via exclude_none, and the frontend falls back to probing
    # the primary resource at runtime.
    datastore_active: bool | None = None


class SourceInfo(BaseModel):
    """Where a non-CKAN dataset comes from and how the page credits it —
    the provider's `SourcePresentation` (services/providers/base.py) plus
    the dataset's own source page. None on data.gov.il datasets: the
    frontend's defaults (data.gov.il, live explorer) apply."""
    model_config = ConfigDict(extra="ignore")

    provider: str
    source_name_he: str
    home_url: str
    source_url: str | None = None
    terms_url: str | None = None
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
    organization: str | None = None           # human-readable ministry title
    organization_slug: str | None = None      # stable key for /ministries/<slug>/
    tags_he: list[str] = Field(default_factory=list)
    primary_resource_id: str | None = None
    formats: list[str] = Field(default_factory=list)
    metadata_modified: datetime | None = None

    license: str | None = None
    record_count: int | None = None
    resources: list[ResourceEntry] = Field(default_factory=list)

    # CKAN's free-text description. Captured by the scanner so the dataset
    # page can fall back to it for SEO meta-description when the agent's
    # short summary_he is missing (rare — selector gates publish on agent
    # success, but this guarantees a non-empty description even on a
    # transient agent_data.json read failure).
    notes: str | None = None

    # When the agent last (re)built the page for this dataset. Rendered as
    # "הדף נוצר ב-" in the sidebar.
    last_analyzed_at: datetime | None = None

    # Source's `metadata_modified` snapshotted at the moment the agent
    # ran — i.e. the vintage of the data the page's content is based on.
    # Distinct from the live `metadata_modified` above, which the scanner
    # overwrites on every poll. Rendered as "המידע נכון ל-" in the sidebar
    # when present; legacy sources (analyzed before this field existed)
    # leave it None and the frontend falls back to `last_analyzed_at`.
    analyzed_metadata_modified: datetime | None = None

    # Availability of the upstream source at data.gov.il. "available" (the
    # default) or "unavailable" — set by the weekly reconcile sweep when a
    # previously-published dataset is made private/removed upstream. The page
    # is preserved (this snapshot); the frontend renders an archive banner
    # and the explorer its gone-state.
    source_status: str = "available"
    # UTC timestamp when the source was first detected as unavailable.
    unavailable_since: datetime | None = None

    # Non-CKAN sources only (services/providers): the credit block, and the
    # readable id part of page_slug (CKAN uses 8 chars of its UUID).
    source: SourceInfo | None = None
    page_slug_suffix: str | None = None

    version: int = 1


# Limits for the recipe-owned search metadata (AgentData.seo). Google cuts a
# title at ~60 chars and a snippet at ~155-160. agent/skills/check.py mirrors
# these (it is standalone, so the numbers are repeated there).
SEO_TITLE_MAX = 60
SEO_DESCRIPTION_MIN = 70
SEO_DESCRIPTION_MAX = 160
SEO_NAME_MAX = 80
SEO_ALTERNATE_NAMES_MAX = 5
# `author verify` wants this much slack inside the description bounds: the
# text usually quotes computed numbers and names, so its length moves with the
# data, and a refresh that crosses a bound fails the page as recipe_invalid.
SEO_DESCRIPTION_HEADROOM = 10


def _seo_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        # ValueError, not TypeError: pydantic turns only ValueError into a
        # ValidationError.
        raise ValueError(f"seo.{field} must be a string")  # noqa: TRY004
    value = value.strip()
    if not value:
        raise ValueError(f"seo.{field} is empty")
    if "\n" in value or "\r" in value:
        raise ValueError(f"seo.{field} must be one line")
    return value


class SeoMeta(BaseModel):
    """Search metadata a recipe chooses for its page. Every field is optional;
    the frontend falls back per field to what it showed before.

    - `title`: the page `<title>`, og:title and twitter:title, verbatim (no
      brand suffix is added). Fallback: CKAN title (+ ministry if it fits).
    - `description`: the meta / og / JSON-LD description. Fallback:
      `summary_he`, which stays the card / search blurb either way.
    - `name`: the name people search (the page's h1): the JSON-LD Dataset
      `name` and the breadcrumb. The CKAN title then becomes an
      `alternateName`.
    - `alternate_names`: spelling / naming variants (כח/כוח, רשם/פנקס), emitted
      as JSON-LD `alternateName` instead of a keyword block in the body.
    """
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=SEO_TITLE_MAX)
    description: str | None = Field(
        default=None, min_length=SEO_DESCRIPTION_MIN, max_length=SEO_DESCRIPTION_MAX
    )
    name: str | None = Field(default=None, max_length=SEO_NAME_MAX)
    alternate_names: list[str] = Field(
        default_factory=list, max_length=SEO_ALTERNATE_NAMES_MAX
    )

    @field_validator("title", "description", "name", mode="before")
    @classmethod
    def _one_line(cls, value: object, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        text = _seo_text(value, info.field_name)
        # The brand is govil.ai: the upstream portal is credited in the body
        # and the description, never in the title or the name.
        if info.field_name in ("title", "name") and "data.gov.il" in text.lower():
            raise ValueError(f"seo.{info.field_name} must not mention data.gov.il")
        return text

    @field_validator("alternate_names", mode="before")
    @classmethod
    def _names(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("seo.alternate_names must be a list")  # noqa: TRY004
        out: list[str] = []
        for item in value:
            text = _seo_text(item, "alternate_names")
            if len(text) > SEO_NAME_MAX:
                raise ValueError(
                    f"seo.alternate_names entry is longer than {SEO_NAME_MAX} chars"
                )
            if text not in out:
                out.append(text)
        return out


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
    temporal_coverage: str | None = None
    spatial_coverage: str | None = None

    # Recipe-owned search metadata. None on legacy pages and on recipes
    # written before it existed; the frontend then keeps its old head tags.
    seo: SeoMeta | None = None

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
    organization: str | None = None
    organization_slug: str | None = None
    tags_he: list[str] = Field(default_factory=list)
    primary_resource_id: str | None = None
    formats: list[str] = Field(default_factory=list)
    metadata_modified: datetime | None = None
    license: str | None = None
    record_count: int | None = None
    resources: list[ResourceEntry] = Field(default_factory=list)
    notes: str | None = None
    last_analyzed_at: datetime | None = None
    analyzed_metadata_modified: datetime | None = None
    source: SourceInfo | None = None
    page_slug_suffix: str | None = None

    # AgentData fields (optional — a scanned-but-never-analyzed source has none)
    summary_he: str | None = None
    dataset_kind: DatasetKind | None = None
    temporal_coverage: str | None = None
    spatial_coverage: str | None = None
    suggested_tags: list[str] = Field(default_factory=list)

    # Publisher-computed: canonical display tags (tags.py) and related
    # datasets (related.py). `tags_he` / `suggested_tags` above stay raw.
    tags: list[str] = Field(default_factory=list)
    related_ids: list[str] = Field(default_factory=list, max_length=5)

    source_status: str = "available"
    unavailable_since: datetime | None = None

    version: int = 1


class TagIndexEntry(BaseModel):
    """One paged tag (carried by ≥ TAG_PAGE_MIN datasets)."""
    slug: str
    topic: str | None = None
    count: int
    intro_he: str | None = None
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
    # Old /datasets/<page_slug>/ segment → the dataset's current page_slug
    # (publish.dataset_slug_redirects: CKAN renames + legacy_page_slugs.json);
    # gen-redirects.mjs turns these into Firebase 301s too.
    slug_redirects: dict[str, str] = Field(default_factory=dict)
