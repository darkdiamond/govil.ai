"""Tests for the full-data export (agent_contract.fetch_resource_records_to_file)
and resource selection — what the recipe refresh and `author prepare` fetch.

The fetcher pages datastore_search host-side and streams one CSV per
resource; every failure/gate path must degrade to "no file". Over-cap
resources fall back to a deterministic sample when sampling is requested;
without sampling, a crossed byte cap or wall budget raises FetchLimitExceeded.
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.error as urllib_error
from typing import Self
from urllib.parse import parse_qs, urlparse

import pytest

from services.page_builder import agent_contract
from services.page_builder.agent_contract import (
    FetchLimitExceeded,
    fetch_resource_records_to_file,
)
from services.shared.resources import select_prefetch_resources


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


_FIELDS = [{"id": "_id", "type": "int"}, {"id": "שם", "type": "text"}, {"id": "ערך", "type": "numeric"}]


def _paged_urlopen(monkeypatch, records: list[dict], page_size_expected: int):
    """Serve `records` through a fake datastore_search honoring offset/limit."""
    calls = []

    def fake(req, timeout=None):
        q = parse_qs(urlparse(req.full_url).query)
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q["limit"][0])
        assert limit == page_size_expected
        calls.append(offset)
        body = {
            "success": True,
            "result": {"fields": _FIELDS, "records": records[offset : offset + limit]},
        }
        return _Resp(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", fake)
    return calls


def _make_records(n: int) -> list[dict]:
    return [{"_id": i + 1, "שם": f"רשומה {i}", "ערך": i * 1.5 if i % 3 else None} for i in range(n)]


def _fetch(dest, total, *, max_bytes=10_000_000, page_size=4, resource_id="res-1",
           deadline=None):
    return fetch_resource_records_to_file(
        resource_id,
        total,
        dest,
        max_bytes=max_bytes,
        page_size=page_size,
        page_timeout_s=5.0,
        deadline=time.monotonic() + 60 if deadline is None else deadline,
    )


def test_full_export_pages_and_normalizes(monkeypatch, tmp_path):
    records = _make_records(10)
    calls = _paged_urlopen(monkeypatch, records, page_size_expected=4)
    dest = tmp_path / "data_1.csv"

    outcome = _fetch(dest, total=10)
    assert outcome is not None
    assert outcome.rows == 10
    assert calls == [0, 4, 8]

    rows = list(csv.DictReader(io.StringIO(dest.read_text(encoding="utf-8"))))
    assert len(rows) == 10
    # _id dropped, Hebrew fields preserved, None → empty string
    assert set(rows[0].keys()) == {"שם", "ערך"}
    assert rows[0]["שם"] == "רשומה 0"
    assert rows[0]["ערך"] == ""  # i=0 → None
    assert rows[1]["ערך"] == "1.5"
    assert outcome.bytes == dest.stat().st_size


def test_gates_return_none(monkeypatch, tmp_path):
    def boom(*_a, **_k):  # urlopen must not be reached when gated
        raise AssertionError("network touched despite gate")

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", boom)
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=10, resource_id="") is None
    assert _fetch(dest, total=0) is None
    assert _fetch(dest, total=10, max_bytes=0) is None


def test_pages_after_the_first_are_sized_by_row_width(monkeypatch, tmp_path):
    """The builder holds a whole page in memory: after the first page, wide
    rows get smaller pages, never more rows than `page_size`."""
    monkeypatch.setattr(agent_contract, "_FIRST_PAGE_ROWS", 4)
    monkeypatch.setattr(agent_contract, "_PAGE_TARGET_BYTES", 220)
    monkeypatch.setattr(agent_contract, "_MIN_PAGE_ROWS", 1)
    records = [{"_id": i + 1, "שם": "x" * 100, "ערך": i} for i in range(10)]
    limits = []

    def fake(req, timeout=None):
        q = parse_qs(urlparse(req.full_url).query)
        offset, limit = int(q.get("offset", ["0"])[0]), int(q["limit"][0])
        limits.append(limit)
        body = {"success": True,
                "result": {"fields": _FIELDS, "records": records[offset: offset + limit]}}
        return _Resp(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", fake)
    dest = tmp_path / "d.csv"
    outcome = _fetch(dest, total=10, page_size=10)
    assert outcome.rows == 10
    # ~105 bytes a row against a 220-byte target: 2 rows a page after the first.
    assert limits == [4, 2, 2, 2]


def test_an_empty_page_before_total_is_a_failed_export(monkeypatch, tmp_path):
    """The datastore answered an empty page mid-export (it was reloading the
    resource): the 8 rows it gave are not the 10 it promised."""
    _paged_urlopen(monkeypatch, _make_records(8), page_size_expected=4)
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=10) is None
    assert not dest.exists()


def test_http_error_returns_none_and_removes_file(monkeypatch, tmp_path):
    def fake(req, timeout=None):
        raise urllib_error.HTTPError("http://x", 500, "err", None, io.BytesIO(b""))

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", fake)
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=10) is None
    assert not dest.exists()


def test_byte_cap_raises(monkeypatch, tmp_path):
    _paged_urlopen(monkeypatch, _make_records(100), page_size_expected=4)
    dest = tmp_path / "d.csv"
    with pytest.raises(FetchLimitExceeded) as e:
        _fetch(dest, total=100, max_bytes=600)
    assert e.value.limit == "bytes"
    assert not dest.exists()


def test_wall_budget_raises(monkeypatch, tmp_path):
    _paged_urlopen(monkeypatch, _make_records(100), page_size_expected=4)
    dest = tmp_path / "d.csv"
    with pytest.raises(FetchLimitExceeded) as e:
        _fetch(dest, total=100, deadline=time.monotonic() - 1)
    assert e.value.limit == "wall_budget"
    assert not dest.exists()


# ---- resource selection -------------------------------------------------


def _res(id, name, fmt, active=True):
    return {"id": id, "name": name, "format": fmt, "datastore_active": active}


def test_select_keeps_primary_first_and_dedupes_format_twins():
    resources = [
        _res("r-xlsx", "שמות רחובות XLSX", "XLSX"),
        _res("r-csv", "שמות רחובות csv", "CSV"),
        _res("r-other", "מדדים לפי שנה", "CSV"),
        _res("r-doc", "מילון נתונים", "PDF", active=False),
    ]
    picked = select_prefetch_resources(resources)
    # primary (CSV wins format priority) first; XLSX twin deduped; PDF dropped
    assert [r["id"] for r in picked] == ["r-csv", "r-other"]


def test_select_no_datastore_resources():
    assert select_prefetch_resources([_res("r1", "קובץ", "PDF", active=False)]) == []


def test_select_distinct_tables_survive():
    resources = [
        _res("r1", "סניפים 2023", "CSV"),
        _res("r2", "סניפים 2024", "CSV"),
        _res("r3", "סניפים 2025", "CSV"),
    ]
    assert len(select_prefetch_resources(resources)) == 3
