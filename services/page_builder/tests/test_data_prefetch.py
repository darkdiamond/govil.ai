"""Tests for the full-data export (agent_contract.fetch_resource_records_to_file)
and resource selection — what the recipe refresh and `author prepare` fetch.

The fetcher pages datastore_search host-side and streams one CSV per
resource; every failure/gate path must degrade to "no file". Over-cap
resources fall back to a deterministic sample when sampling is requested.
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.error as urllib_error
from urllib.parse import parse_qs, urlparse


from services.page_builder import agent_contract
from services.page_builder.agent_contract import fetch_resource_records_to_file
from services.shared.resources import select_prefetch_resources


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_a) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


_FIELDS = [{"id": "_id", "type": "int"}, {"id": "שם", "type": "text"}, {"id": "ערך", "type": "numeric"}]


def _paged_urlopen(monkeypatch, records: list[dict], page_size_expected: int):
    """Serve `records` through a fake datastore_search honoring offset/limit."""
    calls = []

    def fake(req, timeout=None):  # noqa: ANN001
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


def _fetch(dest, total, *, max_bytes=10_000_000, page_size=4, sample_rows=0,
           prefer_sample=False, resource_id="res-1"):
    return fetch_resource_records_to_file(
        resource_id,
        total,
        dest,
        max_bytes=max_bytes,
        page_size=page_size,
        page_timeout_s=5.0,
        deadline=time.monotonic() + 60,
        sample_target_rows=sample_rows,
        prefer_sample=prefer_sample,
    )


def test_full_export_pages_and_normalizes(monkeypatch, tmp_path):
    records = _make_records(10)
    calls = _paged_urlopen(monkeypatch, records, page_size_expected=4)
    dest = tmp_path / "data_1.csv"

    outcome = _fetch(dest, total=10)
    assert outcome is not None
    assert outcome.mode == "full"
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
    # prefer_sample with sampling disabled: no full fetch, no sample → None
    assert _fetch(dest, total=10, prefer_sample=True, sample_rows=0) is None


def test_http_error_returns_none_and_removes_file(monkeypatch, tmp_path):
    def fake(req, timeout=None):  # noqa: ANN001
        raise urllib_error.HTTPError("http://x", 500, "err", None, io.BytesIO(b""))

    monkeypatch.setattr(agent_contract.urllib_request, "urlopen", fake)
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=10) is None
    assert not dest.exists()


def test_byte_cap_falls_back_to_sample(monkeypatch, tmp_path):
    records = _make_records(100)
    calls = _paged_urlopen(monkeypatch, records, page_size_expected=4)
    dest = tmp_path / "d.csv"

    # Cap far below the full CSV: full fetch aborts mid-stream, sample of
    # ~2 blocks (8 rows) fits.
    outcome = _fetch(dest, total=100, max_bytes=600, sample_rows=8)
    assert outcome is not None
    assert outcome.mode == "sample"
    assert outcome.rows == 8
    assert "blocks" in outcome.sample_note
    # Sample offsets restart from 0 with stride 50 after the aborted walk.
    assert calls[-2:] == [0, 50]


def test_byte_cap_without_sampling_returns_none(monkeypatch, tmp_path):
    _paged_urlopen(monkeypatch, _make_records(100), page_size_expected=4)
    dest = tmp_path / "d.csv"
    assert _fetch(dest, total=100, max_bytes=600, sample_rows=0) is None
    assert not dest.exists()


def test_sample_offsets_are_deterministic(monkeypatch, tmp_path):
    records = _make_records(100)
    calls = _paged_urlopen(monkeypatch, records, page_size_expected=4)
    dest = tmp_path / "d.csv"

    outcome = _fetch(dest, total=100, sample_rows=8, prefer_sample=True)
    assert outcome is not None
    assert outcome.mode == "sample"
    # ceil(8/4)=2 blocks, stride max(100//2, 4)=50 → offsets 0, 50
    assert calls == [0, 50]
    rows = list(csv.DictReader(io.StringIO(dest.read_text(encoding="utf-8"))))
    assert [r["שם"] for r in rows[:2]] == ["רשומה 0", "רשומה 1"]
    assert rows[4]["שם"] == "רשומה 50"


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
