"""SCAN_INCREMENTAL: a scheduled scan stops paging once a whole page is older
than the last successful scan's start minus 24h; the first scheduled scan of
each Israel date stays full; a failed scan never advances the mark; with the
flag off the request sequence is today's (minus the duplicate package count)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from services.scanner import main as scanner_main
from services.scanner.client import CKANClient
from services.scanner.config import settings


def _packages(n: int, newest: datetime) -> list[dict]:
    """n CKAN packages, one an hour apart, newest first (CKAN's sort)."""
    return [{"id": f"{i:08d}-0000-0000-0000-000000000000", "name": f"d{i}", "title": f"D {i}",
             "resources": [],
             "metadata_modified": (newest - timedelta(hours=i)).isoformat()}
            for i in range(n)]


@pytest.fixture
def ckan(monkeypatch):
    h = SimpleNamespace(packages=[], requests=[])

    async def search_packages(self, query=None, rows=100, start=0, sort="", fq=None):
        h.requests.append((rows, start))
        return {"count": len(h.packages), "results": h.packages[start:start + rows]}

    monkeypatch.setattr(CKANClient, "search_packages", search_packages)
    monkeypatch.setattr(CKANClient, "_rate_limit", lambda self: _noop())
    return h


async def _noop():
    return None


class _Store:
    def __init__(self, marker=None, *, read_fails=False, save_fails_at=None):
        self.markers = {"scan": dict(marker)} if marker is not None else {}
        self.read_fails, self.save_fails_at = read_fails, save_fails_at
        self.marker_reads = self.marker_writes = 0
        self.saves = 0

    def get_job_marker(self, name):
        self.marker_reads += 1
        if self.read_fails:
            raise RuntimeError("firestore down")
        return dict(self.markers.get(name, {}))

    def set_job_marker(self, name, fields):
        self.marker_writes += 1
        self.markers.setdefault(name, {}).update(fields)

    def start_scan(self, mode="manual"):
        return "scan-1"

    def complete_scan(self, *a, **kw):
        pass

    def get_scan_state(self, dataset_id):
        return (None, None)

    def save_dataset(self, dataset, change_status):
        i = self.saves
        self.saves += 1
        if self.save_fails_at is not None and i == self.save_fails_at:
            raise RuntimeError("save failed")


def _il_today() -> str:
    return datetime.now(UTC).astimezone(scanner_main.IL_TZ).date().isoformat()


async def _scan(store, *, mode="scheduled", limit=1000):
    return await scanner_main.Scanner(config=settings, store=store).scan(limit=limit, mode=mode)


@pytest.mark.asyncio
async def test_flag_off_keeps_the_request_sequence(ckan, monkeypatch):
    monkeypatch.delenv("SCAN_INCREMENTAL", raising=False)
    ckan.packages = _packages(350, datetime.now(UTC))
    store = _Store({"last_full_date": _il_today(),
                    "last_success_started_at": datetime.now(UTC)})
    s = await _scan(store)
    # One package count (it used to be asked twice), then every page.
    assert ckan.requests == [(0, 0), (100, 0), (100, 100), (100, 200), (50, 300)]
    assert s.datasets_scanned == 350 and s.incremental_since is None
    assert store.marker_reads == store.marker_writes == 0


@pytest.mark.asyncio
async def test_incremental_stops_after_a_whole_old_page(ckan, monkeypatch):
    monkeypatch.setenv("SCAN_INCREMENTAL", "true")
    now = datetime.now(UTC)
    ckan.packages = _packages(350, now)
    last = now - timedelta(hours=1)
    store = _Store({"last_full_date": _il_today(), "last_success_started_at": last})
    s = await _scan(store)
    # Cutoff = last − 24h: page 0 holds newer datasets, page 1 is all older,
    # so it is scanned and the listing stops there.
    assert ckan.requests == [(0, 0), (100, 0), (100, 100)]
    assert s.datasets_scanned == 200
    assert s.incremental_since == last - timedelta(hours=24)
    assert store.markers["scan"]["last_success_started_at"] == s.started_at
    assert store.markers["scan"]["last_full_date"] == _il_today()


@pytest.mark.asyncio
async def test_first_scan_of_the_israel_day_is_full(ckan, monkeypatch):
    monkeypatch.setenv("SCAN_INCREMENTAL", "1")
    now = datetime.now(UTC)
    ckan.packages = _packages(350, now)
    store = _Store({"last_full_date": "2000-01-01",
                    "last_success_started_at": now - timedelta(hours=1)})
    s = await _scan(store)
    assert len(ckan.requests) == 5 and s.datasets_scanned == 350
    assert s.incremental_since is None
    assert store.markers["scan"] == {"last_full_date": _il_today(),
                                     "last_success_started_at": s.started_at}


@pytest.mark.asyncio
async def test_no_marker_or_unreadable_marker_scans_in_full(ckan, monkeypatch):
    monkeypatch.setenv("SCAN_INCREMENTAL", "true")
    ckan.packages = _packages(350, datetime.now(UTC))
    s = await _scan(_Store())
    assert len(ckan.requests) == 5 and s.datasets_scanned == 350
    ckan.requests.clear()
    store = _Store(read_fails=True)
    s = await _scan(store)
    assert len(ckan.requests) == 5 and s.datasets_scanned == 350


@pytest.mark.asyncio
async def test_failed_scan_does_not_advance_the_mark(ckan, monkeypatch):
    monkeypatch.setenv("SCAN_INCREMENTAL", "true")
    now = datetime.now(UTC)
    ckan.packages = _packages(350, now)
    before = {"last_full_date": "2000-01-01", "last_success_started_at": now - timedelta(days=3)}
    store = _Store(before, save_fails_at=5)
    s = await _scan(store)
    assert s.error_count == 1
    assert store.marker_writes == 0 and store.markers["scan"] == before


@pytest.mark.asyncio
async def test_aborted_scan_does_not_advance_the_mark(ckan, monkeypatch):
    monkeypatch.setenv("SCAN_INCREMENTAL", "true")
    ckan.packages = _packages(50, datetime.now(UTC))

    async def broken(self, **kw):
        raise RuntimeError("CKAN down")

    monkeypatch.setattr(CKANClient, "search_packages", broken)
    store = _Store()
    with pytest.raises(RuntimeError):
        await _scan(store)
    assert store.marker_writes == 0


@pytest.mark.asyncio
async def test_manual_scan_ignores_the_flag(ckan, monkeypatch):
    monkeypatch.setenv("SCAN_INCREMENTAL", "true")
    now = datetime.now(UTC)
    ckan.packages = _packages(350, now)
    store = _Store({"last_full_date": _il_today(),
                    "last_success_started_at": now - timedelta(hours=1)})
    s = await _scan(store, mode="manual")
    assert len(ckan.requests) == 5 and s.datasets_scanned == 350
    assert store.marker_reads == store.marker_writes == 0


@pytest.mark.asyncio
async def test_listing_keeps_paging_past_an_undated_package(ckan):
    """A dataset without metadata_modified on an otherwise old page keeps the
    listing going (it can't be proved older)."""
    now = datetime.now(UTC)
    ckan.packages = _packages(250, now)
    ckan.packages[150]["metadata_modified"] = None
    c = CKANClient.__new__(CKANClient)
    got = [d async for d in c.iter_all_packages(stop_before=now - timedelta(hours=10),
                                                total_count=250)]
    assert len(got) == 250
    assert ckan.requests == [(100, 0), (100, 100), (50, 200)]
