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


def _html(status: int) -> httpx.Response:
    return httpx.Response(status, text='<!DOCTYPE html><html dir="rtl">…</html>',
                          headers={"content-type": "text/html"},
                          request=httpx.Request("GET", URL))


@pytest.mark.asyncio
async def test_an_html_404_is_retried(client):
    # data.gov.il's edge answers with its HTML 404 page, which can hide an
    # origin error (a CKAN 409 arrived that way on 2026-11-11).
    client._client.get = AsyncMock(side_effect=[
        _html(404), _resp(200, {"success": True, "result": {"id": "x"}})])
    assert await client._request(URL, {"id": "x"}) == {"id": "x"}
    assert client._client.get.await_count == 2


@pytest.mark.asyncio
async def test_a_persistent_html_404_is_bounded_and_surfaces(client):
    client._client.get = AsyncMock(return_value=_html(404))
    with pytest.raises(httpx.HTTPStatusError, match="404"):
        await client._request(URL, {"id": "x"})
    assert client._client.get.await_count == 3


@pytest.mark.asyncio
async def test_an_html_403_is_still_attempted_once(client):
    client._client.get = AsyncMock(return_value=_html(403))
    with pytest.raises(httpx.HTTPStatusError):
        await client._request(URL, {"id": "x"})
    assert client._client.get.await_count == 1


@pytest.mark.asyncio
async def test_the_client_sends_the_shared_user_agent(monkeypatch):
    monkeypatch.setenv("CKAN_USER_AGENT", "Mozilla/5.0 (compatible; test-ua/1.0)")
    async with CKANClient(cfg) as c:
        assert c._client.headers["User-Agent"] == "Mozilla/5.0 (compatible; test-ua/1.0)"
    monkeypatch.delenv("CKAN_USER_AGENT")
    async with CKANClient(cfg) as c:
        assert "govdata-builder/1.0" in c._client.headers["User-Agent"]
