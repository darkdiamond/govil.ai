"""FirestoreStateStore.save_provider_source: the provider docs' version rule.

`metadata_modified` is what the refresh compares, so it must move only when
a resource's content hash changes. Mocked client, as in test_firestore_status.
"""
from __future__ import annotations

from datetime import datetime, timezone

from services.shared.tests.test_firestore_status import _store_with_existing

OLD = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _payload(h="sha-1", rid="boi-br"):
    return {"title": "ריבית בנק ישראל", "provider": "boi_sdmx",
            "resources": [{"id": rid, "hash": h, "datastore_active": False}]}


def _written(ref) -> dict:
    (doc,), kw = ref.set.call_args
    assert kw == {"merge": True}
    return doc


def test_first_insert_is_new_and_never_built():
    store, ref = _store_with_existing(None)
    assert store.save_provider_source("boi-x", _payload()) is True
    doc = _written(ref)
    assert doc["analysis_status"] == "never" and doc["change_status"] == "new"
    assert doc["metadata_modified"] == doc["metadata_created"] == doc["first_seen_at"]


def test_same_content_keeps_the_version_and_the_analysis_state():
    store, ref = _store_with_existing({"resources": _payload()["resources"],
                                       "metadata_modified": OLD, "analysis_status": "succeeded"})
    assert store.save_provider_source("boi-x", _payload()) is False
    doc = _written(ref)
    assert doc["metadata_modified"] == OLD and doc["change_status"] == "unchanged"
    assert "analysis_status" not in doc  # merge write leaves the refresh's state alone


def test_new_content_or_a_new_resource_moves_the_version():
    for payload in (_payload(h="sha-2"), _payload(rid="boi-other")):
        store, ref = _store_with_existing({"resources": _payload()["resources"],
                                           "metadata_modified": OLD})
        assert store.save_provider_source("boi-x", payload) is True
        doc = _written(ref)
        assert doc["metadata_modified"] > OLD and doc["change_status"] == "updated"
