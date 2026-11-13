"""Shared fakes for the provider sync tests (BoI and CBS)."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from services.page_builder import refresh as rf


class FakeStore:
    """The save_provider_source contract, in memory (mirrors firestore.py)."""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.clock = datetime(2026, 10, 29, tzinfo=UTC)

    def save_provider_source(self, dataset_id, payload):
        old = self.docs.get(dataset_id)
        hashes = lambda rs: {r["id"]: r["hash"] for r in rs or []}
        changed = old is None or hashes(old["resources"]) != hashes(payload["resources"])
        doc = dict(old or {"analysis_status": "never"})
        doc.update(payload, metadata_modified=self.clock if changed else old["metadata_modified"])
        self.docs[dataset_id] = doc
        return changed

    def get_provider_sync_state(self, dataset_id):
        return dict(self.docs.get(dataset_id) or {})

    def set_provider_sync_strikes(self, dataset_id, strikes, since):
        doc = self.docs[dataset_id]  # Firestore's update(): no stub doc for a missing one
        doc.update(provider_sync_strikes=strikes or None,
                   provider_sync_strikes_since=since if strikes else None)


def make_repo(tmp_path, sources: dict[str, dict]):
    for i, s in sources.items():
        d = tmp_path / i
        d.mkdir()
        (d / "recipe.json").write_text("{}")
        (d / "source.json").write_text(json.dumps(s, ensure_ascii=False))
    (tmp_path / "11111111-ckan").mkdir()
    (tmp_path / "11111111-ckan" / "recipe.json").write_text("{}")
    return rf.LocalRecipeRepo(tmp_path)
