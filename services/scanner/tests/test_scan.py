"""Scanner.scan: one dataset's failure never ends the scan, the limit holds
after a failure, a run of failures stops it, and the scan_runs doc is closed
whatever happens (it used to stay open forever after any exception)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from services.scanner import main as scanner_main
from services.scanner.config import settings
from services.scanner.models import Dataset

MOD = datetime(2026, 11, 1, tzinfo=UTC)


def _datasets(n: int) -> list[Dataset]:
    return [Dataset(id=f"{i:08d}-0000-0000-0000-000000000000", name=f"d{i}", title=f"D {i}",
                    metadata_modified=MOD) for i in range(n)]


def _fake_client(datasets: list[Dataset], *, listing_error_at: int | None = None):
    class FakeClient:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_package_count(self):
            return len(datasets)

        async def iter_all_packages(self, limit):
            for i, d in enumerate(datasets[:limit]):
                if i == listing_error_at:
                    raise RuntimeError("CKAN listing broke")
                yield d

        async def datastore_total(self, rid):
            return 1

    return FakeClient


def _db(*, save_fails: set[int] | None = None, fail_all: bool = False):
    db = MagicMock()
    db.start_scan.return_value = "scan-1"
    db.get_scan_state.return_value = (None, None)  # every dataset is NEW
    calls = {"n": 0}

    def save(dataset, status):
        i = calls["n"]
        calls["n"] += 1
        if fail_all or (save_fails and i in save_fails):
            raise RuntimeError("firestore unavailable")

    db.save_dataset.side_effect = save
    return db


def _scanner(monkeypatch, client_cls, db):
    monkeypatch.setattr(scanner_main, "CKANClient", client_cls)
    return scanner_main.Scanner(config=settings, db=db)


@pytest.mark.asyncio
async def test_one_failure_is_recorded_and_the_scan_goes_on(monkeypatch):
    db = _db(save_fails={1})
    s = _scanner(monkeypatch, _fake_client(_datasets(4)), db)
    summary = await s.scan(limit=4)
    assert summary.datasets_scanned == 3  # the failed save isn't counted
    assert summary.error_count == 1 and "firestore unavailable" in summary.errors[0]
    assert db.save_dataset.call_count == 4
    kw = db.complete_scan.call_args.kwargs
    assert kw["sources_seen"] == 3 and kw["errors"] == summary.errors


@pytest.mark.asyncio
async def test_limit_holds_after_a_failure(monkeypatch):
    # The limit-th dataset fails: the scan must still stop there, not walk
    # the rest of the listing (limit * 3).
    db = _db(save_fails={1})
    s = _scanner(monkeypatch, _fake_client(_datasets(6)), db)
    await s.scan(limit=2)
    assert db.save_dataset.call_count == 2


@pytest.mark.asyncio
async def test_a_run_of_failures_stops_the_scan(monkeypatch):
    n = scanner_main.SCAN_MAX_CONSECUTIVE_ERRORS
    db = _db(fail_all=True)
    s = _scanner(monkeypatch, _fake_client(_datasets(n + 10)), db)
    with pytest.raises(RuntimeError, match="in a row"):
        await s.scan(limit=n + 10)
    assert db.save_dataset.call_count == n
    kw = db.complete_scan.call_args.kwargs
    assert kw["errors"][-1].startswith("scan aborted")


@pytest.mark.asyncio
async def test_listing_failure_closes_the_scan_doc_and_raises(monkeypatch):
    db = _db()
    s = _scanner(monkeypatch, _fake_client(_datasets(5), listing_error_at=2), db)
    with pytest.raises(RuntimeError, match="listing broke"):
        await s.scan(limit=5)
    db.complete_scan.assert_called_once()
    kw = db.complete_scan.call_args.kwargs
    assert kw["sources_seen"] == 2
    assert "CKAN listing broke" in kw["errors"][-1]


@pytest.mark.asyncio
async def test_error_list_is_capped(monkeypatch):
    monkeypatch.setattr(scanner_main, "MAX_ERRORS_KEPT", 3)
    # Alternate failures so the consecutive-error stop never trips.
    db = _db(save_fails={0, 2, 4, 6, 8})
    s = _scanner(monkeypatch, _fake_client(_datasets(10)), db)
    summary = await s.scan(limit=10)
    assert summary.error_count == 5 and len(summary.errors) == 3
