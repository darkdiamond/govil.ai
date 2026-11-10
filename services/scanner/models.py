"""
Pydantic models for the Scanner Service.

These models represent datasets, resources, and scan results
as returned from the CKAN API and stored locally.
"""

import re
from datetime import UTC, datetime
from enum import Enum
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from services.shared.slug import slugify


class DatasetStatus(str, Enum):
    """Status of a dataset after change detection."""
    NEW = "new"              # Not in DB -> trigger new page flow
    UPDATED = "updated"      # metadata_modified changed -> trigger update flow
    UNCHANGED = "unchanged"  # No changes -> skip


class DownloadStatus(str, Enum):
    """Status of a resource download."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class Organization(BaseModel):
    """Government organization that publishes datasets."""
    id: str
    name: str
    title: str
    logo_url: str | None = None


class Resource(BaseModel):
    """A single resource (file) within a dataset."""
    id: str
    name: str
    format: str = ""
    url: str
    size: int | None = None
    last_modified: datetime | None = None
    description: str | None = None
    # Whether the resource is queryable via /api/3/action/datastore_search.
    # Drives the shell's data-explorer section on the dataset page.
    datastore_active: bool = False
    # CKAN's md5 of the uploaded file (empty for API-pushed resources).
    # Unlike last_modified it survives byte-identical re-uploads unchanged —
    # the recipe-refresh precheck's file fingerprint (check A′) keys on it.
    hash: str | None = None

    # Local tracking fields (not from CKAN)
    file_hash: str | None = None
    storage_path: str | None = None
    download_status: DownloadStatus = DownloadStatus.PENDING

    class Config:
        use_enum_values = True


class Dataset(BaseModel):
    """A dataset (package) from the CKAN API."""
    id: str
    name: str
    title: str
    slug: str = ""                                # deterministic Hebrew→Latin slug from title
    notes: str | None = Field(default=None, description="Dataset description")
    organization: Organization | None = None
    license_title: str | None = None
    update_frequency: str | None = None
    tags: list[str] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    record_count: int | None = None             # populated by Scanner.scan via datastore_search
    metadata_created: datetime | None = None
    metadata_modified: datetime | None = None

    # Local tracking fields
    last_scanned_at: datetime | None = None
    status: str = "active"

    @classmethod
    def from_ckan_response(cls, data: dict) -> "Dataset":
        """Create a Dataset from CKAN API response."""
        # Parse organization
        org_data = data.get("organization")
        organization = None
        if org_data:
            organization = Organization(
                id=org_data.get("id", ""),
                name=org_data.get("name", ""),
                title=org_data.get("title", ""),
                logo_url=org_data.get("image_url"),
            )
        
        # Parse tags
        tags = [tag.get("name", "") for tag in data.get("tags", [])]
        
        # Parse resources
        resources = []
        for res_data in data.get("resources", []):
            resource = Resource(
                id=res_data.get("id", ""),
                name=res_data.get("name", ""),
                format=res_data.get("format", "").upper(),
                url=_public_resource_url(res_data.get("url", "")),
                size=res_data.get("size"),
                last_modified=_parse_datetime(res_data.get("last_modified")),
                description=res_data.get("description"),
                datastore_active=bool(res_data.get("datastore_active")),
                hash=res_data.get("hash") or None,
            )
            resources.append(resource)
        
        dataset_id = data.get("id", "")
        title = data.get("title", "")
        return cls(
            id=dataset_id,
            name=data.get("name", ""),
            title=title,
            slug=slugify(title, fallback=dataset_id),
            notes=data.get("notes"),
            organization=organization,
            license_title=data.get("license_title"),
            update_frequency=data.get("update_frequency"),
            tags=tags,
            resources=resources,
            metadata_created=_parse_datetime(data.get("metadata_created")),
            metadata_modified=_parse_datetime(data.get("metadata_modified")),
        )


class ScanResult(BaseModel):
    """Result of scanning a single dataset."""
    dataset: Dataset
    status: DatasetStatus
    resources_downloaded: int = 0
    error: str | None = None

    class Config:
        use_enum_values = True


class ScanSummary(BaseModel):
    """Summary of a complete scan run."""
    started_at: datetime
    completed_at: datetime | None = None
    datasets_scanned: int = 0
    datasets_new: int = 0
    datasets_updated: int = 0
    datasets_unchanged: int = 0
    errors: list[str] = Field(default_factory=list)  # first MAX_ERRORS_KEPT only
    error_count: int = 0
    results: list[ScanResult] = Field(default_factory=list)


_URL_IGNORED_CHARS_RE = re.compile(r"[\x00-\x20\x7f]")
_GATED_HOST_RE = re.compile(r"^https?://(?:aws-)?e\.data\.gov\.il/")
_LOCALE_PREFIX_RE = re.compile(r"^https://data\.gov\.il/(?:he|en)/(?=dataset/)")


def _public_resource_url(url: str) -> str:
    """CKAN publishes resource URLs on `e.data.gov.il` / `aws-e.data.gov.il`,
    which sit behind an OAuth wall (Google IAP / AWS ALB) and redirect
    anonymous clients to a login screen. The same path on `data.gov.il` (no
    `e.` prefix) is publicly downloadable. Some URLs also carry a `/he/` or
    `/en/` locale prefix before `/dataset/`; data.gov.il routes those to its
    frontend's "page not found" screen, so drop it. Rewrite on ingest so any
    consumer of the Firestore `resources[]` list sees a URL that actually
    works in a browser. Mirrored by frontend/utils/resource-url.ts.

    Anything that isn't an absolute http(s) URL (`javascript:`, `data:`,
    `file:`, relative junk) becomes "" — CKAN fields are publisher-supplied,
    the URL lands in every download button's href, and the publisher
    already drops resources with an empty url. The scheme is judged with
    whitespace/control chars removed, as a browser would (`java\tscript:`).
    """
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    probe = _URL_IGNORED_CHARS_RE.sub("", url)
    parts = urlsplit(probe)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""
    url = _GATED_HOST_RE.sub("https://data.gov.il/", url)
    return _LOCALE_PREFIX_RE.sub("https://data.gov.il/", url)


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse datetime string from CKAN API. Always returns tz-aware UTC —
    CKAN frequently returns naive ISO timestamps (e.g. `2024-01-15T10:30:00`)
    that would be silently stored as UTC by Firestore and then come back
    tz-aware, breaking naive/aware comparisons on the next scan."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt

