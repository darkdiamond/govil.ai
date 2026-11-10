"""
Change detection — compares CKAN dataset metadata against Firestore state.

It only answers "is this dataset new / updated / unchanged?" (the recipe
refresh fetches resource data itself).
"""

from .models import Dataset, DatasetStatus
from .state import StateDB


class ChangeDetector:
    def __init__(self, db: StateDB):
        self.db = db

    def detect_status(self, dataset: Dataset, force: bool = False) -> DatasetStatus:
        stored_modified, stored_status = self.db.get_scan_state(dataset.id)

        if stored_modified is None:
            return DatasetStatus.NEW
        if force:
            return DatasetStatus.UPDATED
        # A previously access-restricted source (datastore 403) that we're
        # scanning again means it's back in CKAN's public search — give it
        # another chance. Force UPDATED so the scanner re-saves it; that upsert
        # resets `restricted` → `never` (FirestoreStateStore.save_dataset), so
        # the selector re-picks it. Needed because an unchanged metadata_modified
        # would otherwise be UNCHANGED and skip the save entirely.
        if stored_status == "restricted":
            return DatasetStatus.UPDATED

        api_modified = dataset.metadata_modified
        if api_modified is None:
            return DatasetStatus.UNCHANGED
        if api_modified > stored_modified:
            return DatasetStatus.UPDATED
        return DatasetStatus.UNCHANGED
