"""
Dataset filtering logic for the Scanner Service.

Provides flexible filtering of datasets based on various criteria
like name, format, organization, and tags.
"""

import re
from dataclasses import dataclass, field

from .models import Dataset


@dataclass
class DatasetFilter:
    """
    Filter configuration for datasets.
    
    All filters are combined with AND logic - a dataset must match
    all specified filters to be included.
    """
    
    # Name filters
    name_contains: str | None = None
    name_regex: str | None = None
    
    # Resource format filters (e.g., CSV, JSON, XLSX)
    formats: list[str] = field(default_factory=list)
    
    # Organization filter
    organization: str | None = None
    
    # Tag filters
    tags: list[str] = field(default_factory=list)
    
    # Exclude patterns
    exclude_name_contains: str | None = None
    exclude_formats: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Normalize filter values."""
        # Normalize formats to uppercase
        self.formats = [f.upper() for f in self.formats]
        self.exclude_formats = [f.upper() for f in self.exclude_formats]
        
        # Compile regex if provided
        self._name_pattern = None
        if self.name_regex:
            self._name_pattern = re.compile(self.name_regex, re.IGNORECASE)
    
    def matches(self, dataset: Dataset) -> bool:
        """
        Check if a dataset matches all filter criteria.
        
        Args:
            dataset: Dataset to check.
        
        Returns:
            True if dataset matches all filters.
        """
        # Name contains filter
        if self.name_contains:
            needle = self.name_contains.lower()
            if needle not in dataset.name.lower() and needle not in dataset.title.lower():
                return False

        # Name regex filter
        if self._name_pattern and not (
            self._name_pattern.search(dataset.name) or self._name_pattern.search(dataset.title)
        ):
            return False

        # Exclude name contains
        if self.exclude_name_contains:
            needle = self.exclude_name_contains.lower()
            if needle in dataset.name.lower() or needle in dataset.title.lower():
                return False
        
        # Format filter - dataset must have at least one resource with matching format
        if self.formats:
            resource_formats = {r.format.upper() for r in dataset.resources}
            if not resource_formats.intersection(self.formats):
                return False
        
        # Exclude formats - skip if dataset has resources in excluded formats
        if self.exclude_formats:
            resource_formats = {r.format.upper() for r in dataset.resources}
            if resource_formats.intersection(self.exclude_formats):
                return False
        
        # Organization filter
        if self.organization:
            if not dataset.organization:
                return False
            org_match = (
                self.organization.lower() in dataset.organization.name.lower() or
                self.organization.lower() in dataset.organization.title.lower()
            )
            if not org_match:
                return False
        
        # Tags filter - dataset must have all specified tags
        if self.tags:
            dataset_tags = {t.lower() for t in dataset.tags}
            required_tags = {t.lower() for t in self.tags}
            if not required_tags.issubset(dataset_tags):
                return False
        
        return True


def create_filter(
    name_contains: str | None = None,
    name_regex: str | None = None,
    formats: str | None = None,
    organization: str | None = None,
    tags: str | None = None,
    exclude_name: str | None = None,
    exclude_formats: str | None = None,
) -> DatasetFilter:
    """
    Create a DatasetFilter from CLI-style arguments.
    
    Args:
        name_contains: Substring to find in dataset name/title.
        name_regex: Regex pattern to match dataset name/title.
        formats: Comma-separated list of formats (e.g., "csv,json").
        organization: Organization name substring.
        tags: Comma-separated list of required tags.
        exclude_name: Substring to exclude in dataset name/title.
        exclude_formats: Comma-separated list of formats to exclude.
    
    Returns:
        Configured DatasetFilter instance.
    """
    return DatasetFilter(
        name_contains=name_contains,
        name_regex=name_regex,
        formats=formats.split(",") if formats else [],
        organization=organization,
        tags=tags.split(",") if tags else [],
        exclude_name_contains=exclude_name,
        exclude_formats=exclude_formats.split(",") if exclude_formats else [],
    )

