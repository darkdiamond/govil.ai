"""Scanner state — now backed by Firestore.

This module keeps the `StateDB` name so existing callers (`detector.py`,
`main.py`) don't change. It delegates to `services.shared.firestore`.
"""
from __future__ import annotations

from datetime import datetime

from services.shared.firestore import FirestoreStateStore

from .models import Dataset, DatasetStatus


class StateDB:
    """Firestore-backed state store for the scanner.

    Accepts an optional pre-built `FirestoreStateStore` (for tests / emulator
    usage). If omitted, constructs one from `FIRESTORE_PROJECT_ID` /
    `GOOGLE_CLOUD_PROJECT`.
    """

    def __init__(self, store: FirestoreStateStore | None = None):
        self.store = store or FirestoreStateStore()

    # Combined read (metadata_modified + analysis_status) for the change
    # detector — lets it also notice a `restricted` doc reappearing in CKAN.
    def get_scan_state(
        self, dataset_id: str
    ) -> tuple[datetime | None, str | None]:
        return self.store.get_scan_state(dataset_id)

    def save_dataset(self, dataset: Dataset, status: DatasetStatus) -> None:
        """Upsert a source document and record its detected `change_status`."""
        self.store.save_dataset(dataset, change_status=str(status.value if hasattr(status, "value") else status))

    def start_scan(self, mode: str = "manual") -> str:
        return self.store.start_scan(mode=mode)

    def complete_scan(
        self,
        scan_id: str,
        *,
        sources_seen: int,
        new: int,
        updated: int,
        unchanged: int,
        errors: list[str] | None = None,
        started_at: datetime | None = None,
    ) -> None:
        self.store.complete_scan(
            scan_id,
            sources_seen=sources_seen,
            new=new,
            updated=updated,
            unchanged=unchanged,
            errors=errors,
            started_at=started_at,
        )

    def get_stats(self) -> dict:
        return self.store.get_stats()

    def get_scan_history(self, limit: int = 10) -> list[dict]:
        return self.store.get_scan_history(limit=limit)
