"""FirestoreStateStore.mark/clear_source_unavailable payloads + SourceRecord."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from google.cloud import firestore

from services.shared.firestore import FirestoreStateStore, SourceRecord


def _store_with_existing(existing: dict) -> tuple[FirestoreStateStore, MagicMock]:
    client = MagicMock()
    doc_ref = client.collection.return_value.document.return_value
    snap = MagicMock()
    snap.exists = bool(existing)
    snap.to_dict.return_value = existing
    doc_ref.get.return_value = snap
    store = FirestoreStateStore(client=client)
    return store, doc_ref


def test_mark_unavailable_stamps_since_when_absent():
    store, doc_ref = _store_with_existing({})
    store.mark_source_unavailable("id1", "403 gone")
    payload = doc_ref.set.call_args.args[0]
    assert payload["analysis_status"] == "unavailable"
    assert payload["last_error"] == "403 gone"
    assert isinstance(payload["unavailable_since"], datetime)


def test_mark_unavailable_preserves_existing_since():
    ts = datetime(2026, 7, 1, tzinfo=UTC)
    store, doc_ref = _store_with_existing({"unavailable_since": ts})
    store.mark_source_unavailable("id1", "still gone")
    payload = doc_ref.set.call_args.args[0]
    assert "unavailable_since" not in payload  # not re-stamped


def test_clear_unavailable_restores_succeeded_and_deletes_since():
    store, doc_ref = _store_with_existing({"analysis_status": "unavailable"})
    store.clear_source_unavailable("id1")
    payload = doc_ref.set.call_args.args[0]
    assert payload["analysis_status"] == "succeeded"
    assert payload["unavailable_since"] is firestore.DELETE_FIELD


def test_source_record_reads_unavailable_since():
    ts = datetime(2026, 7, 20, tzinfo=UTC)
    doc = MagicMock()
    doc.id = "id1"
    doc.to_dict.return_value = {"analysis_status": "unavailable", "unavailable_since": ts}
    rec = SourceRecord.from_doc(doc)
    assert rec.unavailable_since == ts
