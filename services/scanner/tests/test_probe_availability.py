"""Tests for CKANClient.probe_resource / probe_package: gone / alive / blocked / unknown."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services.scanner.client import CKANClient

# What CKAN answers for a restricted or removed resource/package.
_AUTH_BODY = {
    "success": False,
    "error": {"__type": "Authorization Error", "message": "אין הרשאה"},
}


def _resp(*, status: int, body: dict | None = None) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json = MagicMock(return_value=body) if body is not None else MagicMock(side_effect=ValueError)
    return r


def _client(get_mock) -> CKANClient:
    c = CKANClient.__new__(CKANClient)
    c._client = MagicMock()
    c._client.get = get_mock
    c._last_request_time = 0
    from services.scanner.config import settings as cfg
    c.config = cfg
    return c


@pytest.mark.asyncio
async def test_resource_gone_on_403():
    c = _client(AsyncMock(return_value=_resp(status=403, body=_AUTH_BODY)))
    assert await c.probe_resource("rid") == "gone"


@pytest.mark.asyncio
async def test_resource_alive_on_200_success():
    c = _client(AsyncMock(return_value=_resp(status=200, body={"success": True, "result": {"total": 5}})))
    assert await c.probe_resource("rid") == "alive"


@pytest.mark.asyncio
async def test_resource_unknown_on_404():
    c = _client(AsyncMock(return_value=_resp(status=404, body={"success": False})))
    assert await c.probe_resource("rid") == "unknown"


@pytest.mark.asyncio
async def test_resource_unknown_on_transport_error():
    c = _client(AsyncMock(side_effect=httpx.TimeoutException("t")))
    assert await c.probe_resource("rid") == "unknown"


@pytest.mark.asyncio
async def test_package_gone_on_403():
    c = _client(AsyncMock(return_value=_resp(status=403, body=_AUTH_BODY)))
    assert await c.probe_package("pid") == "gone"


@pytest.mark.asyncio
async def test_package_alive_on_200_success():
    c = _client(AsyncMock(return_value=_resp(status=200, body={"success": True, "result": {"id": "pid"}})))
    assert await c.probe_package("pid") == "alive"


# A 403 that isn't CKAN's own Authorization Error is the WAF refusing us (an
# HTML page), never proof that the data is gone: one such sweep would flip
# every published page.
@pytest.mark.asyncio
@pytest.mark.parametrize("body", [None, {"success": False}, {"error": "Forbidden"}])
async def test_resource_blocked_on_foreign_403(body):
    c = _client(AsyncMock(return_value=_resp(status=403, body=body)))
    assert await c.probe_resource("rid") == "blocked"


@pytest.mark.asyncio
async def test_package_blocked_on_html_403():
    c = _client(AsyncMock(return_value=_resp(status=403)))  # body doesn't parse
    assert await c.probe_package("pid") == "blocked"


@pytest.mark.asyncio
async def test_rate_limit_lock_created_lazily_and_spaces_requests(monkeypatch):
    """The client is built with __new__ here (no __init__); the lock appears
    on first use, and concurrent probes still go out one at a time."""
    import asyncio

    c = _client(AsyncMock(return_value=_resp(status=200, body={"success": True})))
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(d):
        sleeps.append(d)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    c.config = c.config.model_copy(update={"ckan_request_delay": 5.0})
    c._last_request_time = asyncio.get_running_loop().time()
    await asyncio.gather(c.probe_resource("a"), c.probe_resource("b"), c.probe_resource("c"))
    assert c._rate_lock is not None
    assert len(sleeps) == 3  # each waiter saw its predecessor's timestamp
