"""Tests for the restricted-status lifecycle in FirestoreStateStore.

Mocks the firestore client (no emulator, matching the rest of the suite).
Covers the two halves of the 403-restriction feature:
  - save_dataset resets a restricted doc back to `never` when the scanner sees
    the dataset again (re-enable on reappearance), but leaves other statuses
    untouched.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from services.scanner.models import Dataset
from services.shared.firestore import FirestoreStateStore


def _store_with_existing(existing: dict | None):
    store = FirestoreStateStore.__new__(FirestoreStateStore)
    client = MagicMock()
    snap = MagicMock()
    snap.exists = existing is not None
    snap.to_dict.return_value = existing or {}
    ref = MagicMock()
    ref.get.return_value = snap
    client.collection.return_value.document.return_value = ref
    store.client = client
    return store, ref


def _dataset() -> Dataset:
    return Dataset.from_ckan_response(
        {
            "id": "fa475dcc-5d80-41b0-af4c-142708bbc2bc",
            "name": "x",
            "title": "מאגר לדוגמה",
            "metadata_modified": "2026-05-01T00:00:00",
            "resources": [
                {
                    "id": "r1",
                    "name": "main",
                    "format": "csv",
                    "url": "https://data.gov.il/dataset/x/resource/r1/download/x.csv",
                }
            ],
        }
    )


def _payload(ref) -> dict:
    return ref.set.call_args[0][0]


def test_save_dataset_resets_restricted_to_never():
    store, ref = _store_with_existing({"analysis_status": "restricted"})
    store.save_dataset(_dataset(), change_status="updated")
    p = _payload(ref)
    assert p["analysis_status"] == "never"
    assert p["last_error"] is None
    assert p["failed_attempts"] == 0


def test_save_dataset_preserves_status_for_non_restricted_existing():
    store, ref = _store_with_existing({"analysis_status": "succeeded"})
    store.save_dataset(_dataset(), change_status="updated")
    # Existing-doc, non-restricted branch must not touch analyzer fields.
    assert "analysis_status" not in _payload(ref)


def test_save_dataset_new_doc_initializes_never():
    store, ref = _store_with_existing(None)
    store.save_dataset(_dataset(), change_status="new")
    p = _payload(ref)
    assert p["analysis_status"] == "never"
    assert p["first_seen_at"] is not None


def _unchanged(reason: str, **kw) -> dict:
    store, ref = _store_with_existing({})
    store.mark_refresh_unchanged(
        "ds", metadata_modified=None, input_fingerprint="fp", reason=reason, **kw
    )
    return _payload(ref)


def test_content_hash_unchanged_advances_and_stamps_verified():
    p = _unchanged("content_hash", inputs_hash="ih", inputs_hash_unordered="iu",
                   file_fingerprint="ff", advance_version=True)
    assert p["inputs_hash"] == "ih" and p["inputs_hash_unordered"] == "iu"
    assert p["last_verified_at"] == p["last_unchanged_at"]
    assert p["refresh_status"] == "succeeded" and "refreshed_metadata_modified" in p
    # the live page's render record stays as it was
    for k in ("last_refreshed_at", "agent_data", "last_snapshot", "content_hash"):
        assert k not in p


def test_fingerprint_unchanged_keeps_stored_input_hashes():
    p = _unchanged("fingerprint", advance_version=False)
    assert "inputs_hash" not in p and "inputs_hash_unordered" not in p
    assert "last_verified_at" not in p and "refreshed_metadata_modified" not in p
