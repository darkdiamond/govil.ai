"""Tests for CKANClient.datastore_total."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services.scanner.client import CKANClient


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


@pytest.mark.asyncio
async def test_returns_none_on_transport_error():
    client = CKANClient.__new__(CKANClient)
    client._client = MagicMock()
    client._client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    client._last_request_time = 0
    from services.scanner.config import settings as cfg
    client.config = cfg

    assert await client.datastore_total("rid") is None


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
