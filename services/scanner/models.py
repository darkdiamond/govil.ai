"""
Pydantic models for the Scanner Service.

These models represent datasets, resources, and scan results
as returned from the CKAN API and stored locally.
"""

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

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
    logo_url: Optional[str] = None


class Resource(BaseModel):
    """A single resource (file) within a dataset."""
    id: str
    name: str
    format: str = ""
    url: str
    size: Optional[int] = None
    last_modified: Optional[datetime] = None
    description: Optional[str] = None
    # Whether the resource is queryable via /api/3/action/datastore_search.
    # Drives the shell's data-explorer section on the dataset page.
    datastore_active: bool = False
    
    # Local tracking fields (not from CKAN)
    file_hash: Optional[str] = None
    storage_path: Optional[str] = None
    download_status: DownloadStatus = DownloadStatus.PENDING

    class Config:
        use_enum_values = True


class Dataset(BaseModel):
    """A dataset (package) from the CKAN API."""
    id: str
    name: str
    title: str
    slug: str = ""                                # deterministic Hebrew→Latin slug from title
    notes: Optional[str] = Field(default=None, description="Dataset description")
    organization: Optional[Organization] = None
    license_title: Optional[str] = None
    update_frequency: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    record_count: Optional[int] = None             # populated by Scanner.scan via datastore_search
    metadata_created: Optional[datetime] = None
    metadata_modified: Optional[datetime] = None

    # Local tracking fields
    last_scanned_at: Optional[datetime] = None
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
    error: Optional[str] = None

    class Config:
        use_enum_values = True


class ScanSummary(BaseModel):
    """Summary of a complete scan run."""
    started_at: datetime
    completed_at: Optional[datetime] = None
    datasets_scanned: int = 0
    datasets_new: int = 0
    datasets_updated: int = 0
    datasets_unchanged: int = 0
    errors: list[str] = Field(default_factory=list)
    results: list[ScanResult] = Field(default_factory=list)


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
    works in a browser. Mirrored by frontend/utils/resource-url.ts."""
    if not url:
        return url
    url = _GATED_HOST_RE.sub("https://data.gov.il/", url)
    return _LOCALE_PREFIX_RE.sub("https://data.gov.il/", url)


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse datetime string from CKAN API. Always returns tz-aware UTC —
    CKAN frequently returns naive ISO timestamps (e.g. `2024-01-15T10:30:00`)
    that would be silently stored as UTC by Firestore and then come back
    tz-aware, breaking naive/aware comparisons on the next scan."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

