"""Orphaned `pending` sources are recycled into retryable failures.

`mark_analysis_pending` is written when a session starts and nothing clears it
if the container dies mid-session (the Cloud Run request timeout did exactly
this every day from 2026-08-01). No selector track matches `pending`, so an
orphan would sit unbuilt forever — hence the reaper.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from services.shared.firestore import FirestoreStateStore


def _doc(doc_id: str, data: dict) -> MagicMock:
    d = MagicMock()
    d.id = doc_id
    d.to_dict.return_value = data
    return d


def _store(docs: list[MagicMock]) -> tuple[FirestoreStateStore, MagicMock]:
    client = MagicMock()
    client.collection.return_value.where.return_value.stream.return_value = iter(docs)
    return FirestoreStateStore(client=client), client


def test_mark_pending_stamps_started_at():
    """Without a timestamp there is no way to tell an orphan from a live run."""
    client = MagicMock()
    store = FirestoreStateStore(client=client)
    store.mark_analysis_pending("id1")
    payload = client.collection.return_value.document.return_value.set.call_args.args[0]
    assert payload["analysis_status"] == "pending"
    assert isinstance(payload["analysis_started_at"], datetime)


def test_reaps_pending_older_than_cutoff():
    old = datetime.now(timezone.utc) - timedelta(hours=9)
    store, client = _store([_doc("stale1", {"analysis_started_at": old})])

    reaped = store.reap_stale_pending(older_than_minutes=120)

    assert reaped == ["stale1"]
    payload = client.collection.return_value.document.return_value.set.call_args.args[0]
    assert payload["analysis_status"] == "failed"
    assert "interrupted" in payload["last_error"]


def test_spares_pending_inside_cutoff():
    """A live session's own pending marker must survive."""
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)
    store, client = _store([_doc("live1", {"analysis_started_at": fresh})])

    assert store.reap_stale_pending(older_than_minutes=120) == []
    client.collection.return_value.document.return_value.set.assert_not_called()


def test_reaps_pending_with_no_timestamp():
    """Docs stranded before `analysis_started_at` existed are stale by definition."""
    store, _ = _store([_doc("legacy1", {})])
    assert store.reap_stale_pending(older_than_minutes=120) == ["legacy1"]


def test_reaps_naive_timestamp_without_crashing():
    """A naive datetime must not raise on comparison against an aware cutoff."""
    naive = datetime.now() - timedelta(hours=9)  # noqa: DTZ005 — deliberate
    store, _ = _store([_doc("naive1", {"analysis_started_at": naive})])
    assert store.reap_stale_pending(older_than_minutes=120) == ["naive1"]


def test_reaped_sources_burn_retry_budget():
    """Recycling as `failed` reuses Track 1b, so 3 interruptions park the
    source instead of it being retried nightly forever."""
    old = datetime.now(timezone.utc) - timedelta(hours=9)
    store, client = _store([_doc("stale1", {"analysis_started_at": old})])
    store.reap_stale_pending(older_than_minutes=120)
    payload = client.collection.return_value.document.return_value.set.call_args.args[0]
    assert "failed_attempts" in payload
