"""CKANClient._request's retry policy: which failures are retried, and that
the real error (not tenacity's RetryError) reaches the caller and so
scan_runs.error."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from tenacity import wait_none

from services.scanner.client import CKANClient
from services.scanner.config import settings as cfg

URL = "https://data.gov.il/api/3/action/package_show"


def _resp(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {},
                          request=httpx.Request("GET", URL))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(CKANClient._request.retry, "wait", wait_none())
    c = CKANClient.__new__(CKANClient)
    c._client = MagicMock()
    c._last_request_time = 0
    c.config = cfg
    return c


@pytest.mark.asyncio
async def test_persistent_connect_error_surfaces_as_the_httpx_error(client):
    client._client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(httpx.ConnectError, match="connection refused"):
        await client._request(URL, {"id": "x"})
    assert client._client.get.await_count == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_a_4xx_is_attempted_once(client, status):
    client._client.get = AsyncMock(return_value=_resp(status, {"success": False}))
    with pytest.raises(httpx.HTTPStatusError):
        await client._request(URL, {"id": "x"})
    assert client._client.get.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [503, 500, 429, 408])
async def test_5xx_408_429_are_retried(client, status):
    client._client.get = AsyncMock(side_effect=[
        _resp(status), _resp(200, {"success": True, "result": {"id": "x"}})])
    assert await client._request(URL, {"id": "x"}) == {"id": "x"}
    assert client._client.get.await_count == 2


@pytest.mark.asyncio
async def test_persistent_503_surfaces_as_the_status_error(client):
    client._client.get = AsyncMock(return_value=_resp(503))
    with pytest.raises(httpx.HTTPStatusError, match="503"):
        await client._request(URL, {"id": "x"})
    assert client._client.get.await_count == 3
