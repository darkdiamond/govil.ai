"""Tests for CKANClient.datastore_total."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services.scanner.client import CKANClient, CKANError


def _ckan_response(*, status: int, body: dict | None = None) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json = MagicMock(return_value=body) if body is not None else MagicMock(side_effect=ValueError)
    return r


@pytest.mark.asyncio
async def test_returns_total_on_success():
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(
        return_value=_ckan_response(
            status=200,
            body={"success": True, "result": {"total": 1455, "records": []}},
        )
    )
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    total = await client.datastore_total("rid-abc")
    assert total == 1455


@pytest.mark.asyncio
async def test_returns_none_on_4xx():
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(
        return_value=_ckan_response(status=404, body={"success": False})
    )
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    assert await client.datastore_total("missing-rid") is None


@pytest.mark.asyncio
async def test_returns_none_when_success_false():
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(
        return_value=_ckan_response(
            status=200,
            body={"success": False, "error": {"message": "no datastore"}},
        )
    )
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    assert await client.datastore_total("non-datastore-rid") is None


@pytest.fixture
def no_retry_wait(monkeypatch):
    from tenacity import wait_none
    monkeypatch.setattr(CKANClient._datastore_search.retry, "wait", wait_none())


@pytest.mark.asyncio
async def test_transport_error_is_retried_then_raises(no_retry_wait):
    # "Couldn't ask" is not "no count": the caller keeps the stored count.
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    with pytest.raises(CKANError):
        await client.datastore_total("rid")
    assert client._client.get.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [500, 503, 429, 408])
async def test_server_error_raises(no_retry_wait, status):
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(return_value=_ckan_response(status=status, body={}))
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    with pytest.raises(CKANError):
        await client.datastore_total("rid")


@pytest.mark.asyncio
async def test_unparseable_body_raises():
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(return_value=_ckan_response(status=200))
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    with pytest.raises(CKANError):
        await client.datastore_total("rid")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (403, None),                                        # WAF HTML page
    (404, None),                                        # proxy HTML page
    (403, {"success": False, "error": {"__type": "Not Found Error"}}),
    (404, {"message": "not a CKAN envelope"}),
])
async def test_4xx_without_ckan_error_body_raises(status, body):
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(return_value=_ckan_response(status=status, body=body))
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    with pytest.raises(CKANError):
        await client.datastore_total("rid")
    assert client._client.get.await_count == 1  # a 4xx is not retried


@pytest.mark.asyncio
async def test_403_authorization_error_is_a_definite_no_count():
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(return_value=_ckan_response(
        status=403,
        body={"success": False, "error": {"__type": "Authorization Error"}},
    ))
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    assert await client.datastore_total("rid") is None


@pytest.mark.asyncio
async def test_transient_failure_then_success_returns_total(no_retry_wait):
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(side_effect=[
        httpx.ConnectError("reset"),
        _ckan_response(status=200, body={"success": True, "result": {"total": 7}}),
    ])
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    assert await client.datastore_total("rid") == 7


@pytest.mark.asyncio
async def test_returns_none_on_unparseable_total():
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(
        return_value=_ckan_response(
            status=200,
            body={"success": True, "result": {"total": "not-a-number"}},
        )
    )
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    assert await client.datastore_total("rid") is None


@pytest.mark.asyncio
async def test_asks_for_an_exact_count():
    # Without a threshold, CKAN returns Postgres's planner estimate for a
    # large table, stale after a shrinking re-upload (36bf1404, 2026-11-05:
    # 161,025 estimated, 125,718 held).
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(
        return_value=_ckan_response(
            status=200,
            body={"success": True, "result": {"total": 125718, "total_was_estimated": False}},
        )
    )
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    assert await client.datastore_total("rid") == 125718
    params = client._client.get.call_args.kwargs["params"]
    assert params["total_estimation_threshold"] >= 10**9


# ----- through Scanner._scan_one into save_dataset ---------------------------

def _scan_with_stored(stored: dict, datastore_total):
    """Run `_scan_one` on an UPDATED dataset against a Firestore doc holding
    `stored`; return the doc after the merge write."""
    import asyncio
    from datetime import UTC, datetime

    from services.scanner.main import Scanner
    from services.scanner.models import Dataset, DatasetStatus, ScanSummary
    from services.shared.firestore import FirestoreStateStore

    doc = dict(stored)
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.side_effect = lambda: dict(doc)
    ref = MagicMock()
    ref.get.return_value = snap
    ref.set.side_effect = lambda payload, merge: doc.update(payload)
    store = FirestoreStateStore.__new__(FirestoreStateStore)
    store.client = MagicMock()
    store.client.collection.return_value.document.return_value = ref

    scanner = Scanner.__new__(Scanner)
    scanner.store = store
    detector = MagicMock()
    detector.detect_status.return_value = DatasetStatus.UPDATED
    client = MagicMock()
    client.datastore_total = datastore_total
    dataset = Dataset.from_ckan_response({
        "id": "fa475dcc-5d80-41b0-af4c-142708bbc2bc", "name": "x", "title": "t",
        "resources": [{"id": "r1", "format": "csv", "datastore_active": True,
                       "url": "https://data.gov.il/dataset/x/resource/r1/download/x.csv"}],
    })
    asyncio.run(scanner._scan_one(client, detector, dataset, ScanSummary(started_at=datetime.now(UTC)), force=False))
    return doc


def test_transient_failure_keeps_stored_count():
    doc = _scan_with_stored({"record_count": 1234},
                            AsyncMock(side_effect=CKANError("datastore_search unavailable")))
    assert doc["record_count"] == 1234


def test_definite_no_count_overwrites_stored_count():
    doc = _scan_with_stored({"record_count": 1234}, AsyncMock(return_value=None))
    assert doc["record_count"] is None


def test_fresh_count_overwrites_stored_count():
    doc = _scan_with_stored({"record_count": 1234}, AsyncMock(return_value=99))
    assert doc["record_count"] == 99
    # The scanner passes the enum's value: a plain string in the doc.
    assert doc["change_status"] == "updated" and type(doc["change_status"]) is str


@pytest.mark.parametrize("status", [403, 404])
def test_4xx_html_reply_keeps_stored_count(status):
    async def total(rid):
        client = CKANClient.__new__(CKANClient)
        client._client = MagicMock()
        client._client.get = AsyncMock(return_value=_ckan_response(status=status))
        client._last_request_time = 0
        from services.scanner.config import settings as cfg
        client.config = cfg
        return await client.datastore_total(rid)

    doc = _scan_with_stored({"record_count": 1234}, total)
    assert doc["record_count"] == 1234
