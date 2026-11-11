"""Tests for the full-data export (ckan_export.fetch_resource_records_to_file)
and resource selection — what the recipe refresh and `author prepare` fetch.

The fetcher pages datastore_search host-side and streams one CSV per
resource, full or nothing: every failure/gate path must degrade to "no file",
and a crossed byte cap or wall budget raises FetchLimitExceeded.
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

from services.page_builder import ckan_export
from services.page_builder.ckan_export import fetch_resource_records_to_file
from services.shared.fetch_types import FetchLimitExceeded
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


def _preview_body(records: list[dict]) -> bytes:
    """The preview request (include_total) for a table holding `records`."""
    body = {"success": True, "result": {"fields": _FIELDS, "total": len(records),
                                        "records": records[:5]}}
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _paged_urlopen(monkeypatch, records: list[dict], page_size_expected: int):
    """Serve `records` through a fake datastore_search honoring offset/limit;
    the end-of-export preview sees the same table."""
    calls = []

    def fake(req, timeout=None):
        q = parse_qs(urlparse(req.full_url).query)
        if "include_total" in q:
            return _Resp(_preview_body(records))
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q["limit"][0])
        # The last page is clipped to the rows left before `total`.
        assert limit <= page_size_expected
        calls.append(offset)
        body = {
            "success": True,
            "result": {"fields": _FIELDS, "records": records[offset : offset + limit]},
        }
        return _Resp(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", fake)
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

    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", boom)
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=10, resource_id="") is None
    assert _fetch(dest, total=0) is None
    assert _fetch(dest, total=10, max_bytes=0) is None


def test_pages_after_the_first_are_sized_by_row_width(monkeypatch, tmp_path):
    """The builder holds a whole page in memory: after the first page, wide
    rows get smaller pages, never more rows than `page_size`."""
    monkeypatch.setattr(ckan_export, "_FIRST_PAGE_ROWS", 4)
    monkeypatch.setattr(ckan_export, "_PAGE_TARGET_BYTES", 220)
    monkeypatch.setattr(ckan_export, "_MIN_PAGE_ROWS", 1)
    records = [{"_id": i + 1, "שם": "x" * 100, "ערך": i} for i in range(10)]
    limits = []

    def fake(req, timeout=None):
        q = parse_qs(urlparse(req.full_url).query)
        if "include_total" in q:
            return _Resp(_preview_body(records))
        offset, limit = int(q.get("offset", ["0"])[0]), int(q["limit"][0])
        limits.append(limit)
        body = {"success": True,
                "result": {"fields": _FIELDS, "records": records[offset: offset + limit]}}
        return _Resp(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", fake)
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


class _ReloadingTable:
    """A datastore whose table can be swapped between pages, and whose
    preview reads whatever the table is at that moment."""

    def __init__(self, records: list[dict]):
        self.records = records
        self.asked: list[tuple[int, int]] = []
        self.previews = 0
        self.on_page = None

    def page(self, _rid, offset, limit, _timeout, _fields=None):
        self.asked.append((offset, limit))
        rows = self.records[offset:offset + limit]
        if self.on_page:
            self.on_page(self)
        return ["שם", "ערך"], [{k: v for k, v in r.items() if k != "_id"} for r in rows]

    def preview(self, _rid):
        self.previews += 1
        return {"fields": _FIELDS, "total": len(self.records),
                "sample_rows": [{k: v for k, v in r.items() if k != "_id"}
                                for r in self.records[:5]]}


def _table(monkeypatch, records):
    t = _ReloadingTable(records)
    monkeypatch.setattr(ckan_export, "_fetch_page", t.page)
    monkeypatch.setattr(ckan_export, "fetch_resource_preview", t.preview)
    return t


def test_a_reload_between_pages_fails_the_export(monkeypatch, tmp_path):
    """The datastore was reloaded after the first page, same row count:
    half old rows, half new ones is not a full export."""
    t = _table(monkeypatch, _make_records(10))
    started_from = t.preview("res-1")
    new = [{"_id": i + 1, "שם": f"חדש {i}", "ערך": i} for i in range(10)]

    def reload(table):
        table.records, table.on_page = new, None

    t.on_page = reload
    dest = tmp_path / "d.csv"
    out = fetch_resource_records_to_file(
        "res-1", 10, dest, max_bytes=10_000_000, page_size=4, page_timeout_s=5.0,
        deadline=time.monotonic() + 60, preview=started_from,
    )
    assert out is None
    assert not dest.exists()


def test_a_table_that_grew_is_never_read_past_total(monkeypatch, tmp_path):
    """The preview said 10 rows; the table now holds 20. No page reads past
    row 10, and the export fails, since the table moved under it."""
    t = _table(monkeypatch, _make_records(20))
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=10) is None
    assert not dest.exists()
    assert t.asked == [(0, 4), (4, 4), (8, 2)]


def test_a_failed_end_preview_fails_the_export(monkeypatch, tmp_path):
    t = _table(monkeypatch, _make_records(10))
    monkeypatch.setattr(ckan_export, "fetch_resource_preview", lambda _rid: None)
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=10) is None
    assert not dest.exists()
    assert len(t.asked) == 3


def test_a_consistent_multi_page_export_takes_one_end_preview(monkeypatch, tmp_path):
    t = _table(monkeypatch, _make_records(10))
    started_from = t.preview("res-1")
    dest = tmp_path / "d.csv"
    out = fetch_resource_records_to_file(
        "res-1", 10, dest, max_bytes=10_000_000, page_size=4, page_timeout_s=5.0,
        deadline=time.monotonic() + 60, preview=started_from,
    )
    assert out is not None and out.rows == 10
    assert t.previews == 2  # the caller's, then the export's one


def test_a_single_page_export_takes_no_end_preview(monkeypatch, tmp_path):
    t = _table(monkeypatch, _make_records(3))
    out = _fetch(tmp_path / "d.csv", total=3)
    assert out is not None and out.rows == 3
    assert t.previews == 0 and t.asked == [(0, 3)]


def test_the_export_checks_against_the_callers_preview(monkeypatch, tmp_path):
    """fetch_resource_export hands its preview to the datastore walk."""
    t = _table(monkeypatch, _make_records(10))
    started_from = t.preview("res-1")
    started_from["sample_rows"] = started_from["sample_rows"][1:]  # an older table
    dest = tmp_path / "d.csv"
    out = ckan_export.fetch_resource_export(
        "res-1", 10, dest, preview=started_from, max_bytes=10_000_000, page_size=4,
        page_timeout_s=5.0, deadline=time.monotonic() + 60,
    )
    assert out is None
    assert not dest.exists()


def test_http_error_returns_none_and_removes_file(monkeypatch, tmp_path):
    def fake(req, timeout=None):
        raise urllib_error.HTTPError("http://x", 500, "err", None, io.BytesIO(b""))

    monkeypatch.setattr(ckan_export.urllib_request, "urlopen", fake)
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
