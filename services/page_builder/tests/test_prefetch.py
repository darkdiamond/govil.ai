"""Tests for ckan_export.fetch_resource_preview's 403-restriction gate.

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
from typing import ClassVar, Self
from urllib.parse import parse_qs, urlparse

import pytest

from services.page_builder import ckan_export
from services.page_builder.ckan_export import (
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

    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", fake)


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


class _EstimatingCkan:
    """datastore_search as data.gov.il answers it for a large table: with
    `include_total` alone, `total` is Postgres's planner estimate (stale here,
    larger than the table after a shrinking re-upload); with a
    `total_estimation_threshold` above that estimate, it is an exact count."""

    ROWS: ClassVar[list[dict]] = [{"_id": i + 1, "plate": f"{i:07d}"} for i in range(7)]
    ESTIMATE = 10

    def __init__(self):
        self.urls: list[str] = []

    def urlopen(self, req, timeout=None):
        self.urls.append(req.full_url)
        q = {k: v[0] for k, v in parse_qs(urlparse(req.full_url).query).items()}
        exact = int(q.get("total_estimation_threshold") or 0) >= self.ESTIMATE
        body = {
            "success": True,
            "result": {
                "total": len(self.ROWS) if exact else self.ESTIMATE,
                "total_was_estimated": not exact,
                "fields": [{"id": "_id", "type": "int"}, {"id": "plate", "type": "text"}],
                "records": self.ROWS[: int(q.get("limit", 0))],
            },
        }
        return _Resp(json.dumps(body).encode("utf-8"))

    def page(self, _rid, offset, limit, _timeout, _fields):
        rows = self.ROWS[offset:offset + limit]
        return ["plate"], [{k: v for k, v in r.items() if k != "_id"} for r in rows]


def test_preview_total_is_exact_not_the_planner_estimate(monkeypatch, tmp_path):
    # 2026-11-05, 9a7bd490: CKAN estimated 161,025 rows for a table holding
    # 125,718. The file was rejected as short and the datastore export failed
    # as "ran out at row 125,718 of 161,025", both checked against the estimate.
    ckan = _EstimatingCkan()
    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", ckan.urlopen)
    monkeypatch.setattr(ckan_export, "_fetch_page", ckan.page)

    preview = fetch_resource_preview("rid")
    assert preview is not None
    assert preview["total"] == 7
    assert "total_estimation_threshold=" in ckan.urls[0]
    # The export checks its row count against that total (its cut-off guard
    # is test_data_prefetch's test_an_empty_page_before_total_is_a_failed_export):
    # the whole table now exports as full.
    out = ckan_export.fetch_resource_records_to_file(
        "rid", preview["total"], tmp_path / "out.csv", max_bytes=1_000_000,
        page_size=100_000, page_timeout_s=5.0, deadline=float("inf"),
    )
    assert out is not None and out.rows == 7


def test_an_estimated_total_is_logged(monkeypatch, caplog):
    # A CKAN that ignores the threshold must not go back to silent estimates.
    ckan = _EstimatingCkan()
    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", ckan.urlopen)
    monkeypatch.setattr(ckan_export, "EXACT_TOTAL_THRESHOLD", 0)
    with caplog.at_level("WARNING", logger=ckan_export.log.name):
        preview = fetch_resource_preview("rid")
    assert preview is not None and preview["total"] == _EstimatingCkan.ESTIMATE
    assert "is an estimate" in caplog.text
