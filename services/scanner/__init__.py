"""
GovData Scanner Service

Scans Israeli government datasets from data.gov.il CKAN API, writes per-source
state to Firestore, and exposes CLI + programmatic entry points.

Intentionally thin re-exports to avoid importing `main` at package-import
time (which shadows `python -m services.scanner.main`).
"""

from .client import CKANClient
from .config import ScannerSettings, settings
from .detector import ChangeDetector
from .filters import DatasetFilter, create_filter
from .models import Dataset, DatasetStatus, Resource, ScanResult, ScanSummary
from .state import StateDB

__all__ = [
    "CKANClient",
    "ChangeDetector",
    "Dataset",
    "DatasetFilter",
    "DatasetStatus",
    "Resource",
    "ScanResult",
    "ScanSummary",
    "ScannerSettings",
    "StateDB",
    "create_filter",
    "settings",
]
