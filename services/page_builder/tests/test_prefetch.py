"""Tests for agent_contract.fetch_resource_preview's 403-restriction gate.

A 403 Authorization Error from CKAN datastore_search means the dataset's data
is access-restricted upstream — `fetch_resource_preview` must raise
`ResourceRestrictedError` (so the pipeline parks the source as `restricted`
instead of running an agent that would only 403 again). Every other failure
mode keeps the existing silent `None` fallback.
"""
from __future__ import annotations

import io
import json
import urllib.error as urllib_error
from typing import Self

import pytest

from services.page_builder import agent_contract
from services.page_builder.agent_contract import (
    ResourceRestrictedError,
    fetch_resource_preview,
)

_AUTH_BODY = {
    "success": False,
    "error": {"__type": "Authorization Error", "message": "אין הרשאה"},
}


class _Resp:
    """Minimal context-manager stand-in for an urlopen() success."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _http_error(code: int, body: dict | None) -> urllib_error.HTTPError:
    payload = (
        json.dumps(body).encode("utf-8")
        if body is not None
        else b"<html>blocked by something non-JSON</html>"
    )
    return urllib_error.HTTPError(
        url="http://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(payload)
    )


def _patch_urlopen(monkeypatch, behaviour):
    def fake(_req, timeout=None):
        return behaviour()

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", fake)


def test_403_authorization_error_raises(monkeypatch):
    _patch_urlopen(monkeypatch, lambda: (_ for _ in ()).throw(_http_error(403, _AUTH_BODY)))
    with pytest.raises(ResourceRestrictedError):
        fetch_resource_preview("rid-restricted")


def test_403_unparseable_body_still_raises(monkeypatch):
    # We send a browser UA, so a 403 here is the CKAN auth error even if the
    # body isn't JSON. Rate-limiting would be 429/503, never 403.
    _patch_urlopen(monkeypatch, lambda: (_ for _ in ()).throw(_http_error(403, None)))
    with pytest.raises(ResourceRestrictedError):
        fetch_resource_preview("rid-restricted")


def test_200_authorization_error_raises(monkeypatch):
    _patch_urlopen(monkeypatch, lambda: _Resp(json.dumps(_AUTH_BODY).encode("utf-8")))
    with pytest.raises(ResourceRestrictedError):
        fetch_resource_preview("rid-restricted")


def test_404_returns_none(monkeypatch):
    _patch_urlopen(monkeypatch, lambda: (_ for _ in ()).throw(_http_error(404, {"success": False})))
    assert fetch_resource_preview("rid-missing") is None


def test_timeout_returns_none(monkeypatch):
    _patch_urlopen(monkeypatch, lambda: (_ for _ in ()).throw(TimeoutError("slow")))
    assert fetch_resource_preview("rid") is None


def test_success_returns_preview(monkeypatch):
    body = {
        "success": True,
        "result": {
            "total": 36,
            "fields": [{"id": "office", "type": "text"}, {"id": "_id", "type": "int"}],
            "records": [{"_id": 1, "office": "צפון"}],
        },
    }
    _patch_urlopen(monkeypatch, lambda: _Resp(json.dumps(body).encode("utf-8")))
    preview = fetch_resource_preview("rid-ok")
    assert preview is not None
    assert preview["total"] == 36
    assert {"id": "office", "type": "text"} in preview["fields"]
    # _id is stripped from sample rows.
    assert preview["sample_rows"] == [{"office": "צפון"}]


def test_empty_resource_id_returns_none():
    assert fetch_resource_preview("") is None
