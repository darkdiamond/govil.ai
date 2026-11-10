"""
Pydantic models for the Scanner Service.

These models represent datasets, resources, and scan results as returned
from the CKAN API; `FirestoreStateStore.save_dataset` persists them.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from services.shared.ckan import parse_ckan_datetime, public_resource_url
from services.shared.slug import slugify


class DatasetStatus(str, Enum):
    """Status of a dataset after change detection."""
    NEW = "new"              # Not in DB -> trigger new page flow
    UPDATED = "updated"      # metadata_modified changed -> trigger update flow
    UNCHANGED = "unchanged"  # No changes -> skip


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
                url=public_resource_url(res_data.get("url", "")),
                size=res_data.get("size"),
                last_modified=parse_ckan_datetime(res_data.get("last_modified")),
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
            metadata_created=parse_ckan_datetime(data.get("metadata_created")),
            metadata_modified=parse_ckan_datetime(data.get("metadata_modified")),
        )


class ScanResult(BaseModel):
    """Result of scanning a single dataset."""
    dataset: Dataset
    status: DatasetStatus
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
