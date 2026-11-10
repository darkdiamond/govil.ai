"""Tests for the file export of inputs bigger than one datastore page
(ckan_export.fetch_resource_export / fetch_resource_csv): the uploaded CSV,
normalized to exactly what the datastore export writes, and the fallback to
datastore_search on any doubt."""
from __future__ import annotations

import io
import threading
import time
import urllib.error as urllib_error

import pytest

from services.page_builder import ckan_export as ac
from services.page_builder.ckan_export import FetchLimitExceeded, FetchOutcome

URL = "https://e.data.gov.il/dataset/d/resource/r1/download/r1.csv"
RES = {"id": "r1-0000000", "format": "CSV", "url": URL}
FIELDS = [{"id": "_id", "type": "int"}, {"id": "שם", "type": "text"},
          {"id": "ערך", "type": "numeric"}, {"id": "קוד", "type": "text"}]


class _Resp:
    def __init__(self, body: bytes, ctype: str = "text/csv"):
        self._buf, self.headers = io.BytesIO(body), {"Content-Type": ctype}

    def read(self, n=-1):
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _serve(monkeypatch, body: bytes, *, blocked_uas=(), ctype="text/csv"):
    """Fake the file download; returns the UAs it was asked with."""
    seen = []

    def fake(req, timeout=None):
        ua = req.get_header("User-agent")
        seen.append(ua)
        if ua in blocked_uas:
            raise urllib_error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        return _Resp(body, ctype)

    monkeypatch.setattr(ac, "_open_file", fake)
    return seen


def _datastore(monkeypatch):
    """Fake the datastore fallback; returns its calls."""
    calls = []

    def fake(rid, total, dest, **kw):
        calls.append(kw)
        dest.write_text("שם,ערך,קוד\r\n", encoding="utf-8")
        return FetchOutcome(rows=total, bytes=10)

    monkeypatch.setattr(ac, "fetch_resource_records_to_file", fake)
    return calls


def _probe(monkeypatch, value):
    """Fake the one-cell datastore read that settles `2` vs `2.0`; returns
    its (offset, column) calls."""
    calls = []

    def fake(rid, offset, limit, timeout, fields=None):
        assert limit == 1 and len(fields) == 1
        calls.append((offset, fields[0]))
        return fields, [{"_id": offset + 1, fields[0]: value}]

    monkeypatch.setattr(ac, "_fetch_page", fake)
    return calls


@pytest.fixture(autouse=True)
def probes(monkeypatch):
    """By default the datastore holds whole numbers as ints."""
    return _probe(monkeypatch, 2)


def _preview(samples=(), total=2, fields=FIELDS):
    return {"fields": fields, "total": total, "sample_rows": list(samples)}


def _export(tmp_path, preview, total=2, fields=None, resource=RES, max_bytes=1_000_000,
            page_size=1):
    dest = tmp_path / "main__1.csv"
    out = ac.fetch_resource_export(
        resource["id"], total, dest, resource=resource, preview=preview,
        max_bytes=max_bytes, deadline=time.monotonic() + 60, fields=fields,
        page_size=page_size, page_timeout_s=5.0,
    )
    return out, dest


GOOD = "﻿שם,ערך,קוד,,\r\n  חיפה ,1.50,007,,\r\nתל אביב,2,,,\r\n,,,,\r\n".encode()
EXPORT = "שם,ערך,קוד\r\nחיפה,1.5,007\r\nתל אביב,2,\r\n"


def test_file_normalizes_to_the_datastore_export(monkeypatch, tmp_path, probes):
    seen = _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    samples = [{"_id": 1, "שם": "חיפה", "ערך": 1.5, "קוד": "007"}]
    out, dest = _export(tmp_path, _preview(samples))
    assert out.via == "file" and out.rows == 2
    # BOM, empty trailing columns, blank rows and edge whitespace gone;
    # numbers as the datastore JSON writes them; text kept verbatim.
    assert dest.read_bytes().decode("utf-8") == EXPORT
    # 1.5 doesn't say whether whole numbers are `2` or `2.0`: one datastore
    # cell is read, at the first row whose value is whole (offset 1).
    assert probes == [(1, "ערך")]
    assert not ds
    assert seen == [ac._CKAN_BROWSER_UA]
    assert not dest.with_suffix(".raw").exists()


def test_file_honors_the_fields_projection(monkeypatch, tmp_path):
    _serve(monkeypatch, GOOD)
    _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview(), fields=["קוד", "שם"])
    assert out.via == "file"
    assert dest.read_bytes().decode("utf-8") == "קוד,שם\r\n007,חיפה\r\n,תל אביב\r\n"


def _export_capped(tmp_path, max_bytes, file_max_bytes, fields):
    dest = tmp_path / "main__1.csv"
    out = ac.fetch_resource_export(
        RES["id"], 2, dest, resource=RES, preview=_preview(), max_bytes=max_bytes,
        file_max_bytes=file_max_bytes, deadline=time.monotonic() + 60, fields=fields,
        page_size=1, page_timeout_s=5.0,
    )
    return out, dest


def test_a_file_over_the_export_cap_still_downloads_when_its_columns_fit(monkeypatch, tmp_path):
    # The raw file (all columns) is over the export cap; the projected export is not.
    export = "קוד\r\n007\r\n\"\"\r\n".encode()
    assert len(export) < 20 < len(GOOD)
    _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    out, dest = _export_capped(tmp_path, max_bytes=20, file_max_bytes=1_000, fields=["קוד"])
    assert out.via == "file" and not ds
    assert dest.read_bytes() == export


@pytest.mark.parametrize("file_max_bytes", [None, 30])
def test_the_download_cap_never_drops_below_the_export_cap(monkeypatch, tmp_path, file_max_bytes):
    _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    out, _ = _export_capped(tmp_path, max_bytes=1_000, file_max_bytes=file_max_bytes, fields=None)
    assert out.via == "file" and not ds


def test_a_file_over_the_download_cap_falls_back(monkeypatch, tmp_path):
    _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    out, dest = _export_capped(tmp_path, max_bytes=20, file_max_bytes=30, fields=["קוד"])
    assert out.via == "datastore" and len(ds) == 1
    assert not dest.with_suffix(".raw").exists()


def test_the_normalized_file_still_obeys_the_export_cap(monkeypatch, tmp_path):
    _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    out, _ = _export_capped(tmp_path, max_bytes=20, file_max_bytes=1_000, fields=None)
    assert out.via == "datastore" and len(ds) == 1


@pytest.mark.parametrize("delimiter", ["|", ";", "\t"])
def test_a_file_with_another_delimiter(monkeypatch, tmp_path, delimiter):
    _serve(monkeypatch, GOOD.decode("utf-8").replace(",", delimiter).encode())
    ds = _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview())
    assert out.via == "file" and not ds
    assert dest.read_bytes().decode("utf-8") == EXPORT


def test_a_quoted_pipe_file(monkeypatch, tmp_path):
    # The vehicle registry's shape: every value quoted, `|` between them.
    body = '"שם"|"ערך"|"קוד"\r\n"חיפה"|"1.50"|"007"\r\n"תל אביב"|"2"|""\r\n'.encode()
    _serve(monkeypatch, body)
    _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview())
    assert out.via == "file"
    assert dest.read_bytes().decode("utf-8") == EXPORT


def test_windows_1255_file(monkeypatch, tmp_path):
    _serve(monkeypatch, "שם,ערך,קוד\r\nחיפה,3,א\r\n".encode("cp1255"))
    _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview(), total=1, page_size=0)
    assert out.via == "file"
    assert dest.read_bytes().decode("utf-8") == "שם,ערך,קוד\r\nחיפה,3,א\r\n"


def test_a_windows_1255_byte_with_no_character_reads_as_the_datastore_stores_it(
        monkeypatch, tmp_path):
    # 0x9F is undefined in Windows-1255; CKAN's loader stored it as U+FFFD.
    _serve(monkeypatch, "שם,ערך,קוד\r\nחיפה,3,".encode("cp1255") + b"CB\x9f\r\n")
    _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview(), total=1, page_size=0)
    assert out.via == "file"
    assert dest.read_bytes().decode("utf-8") == "שם,ערך,קוד\r\nחיפה,3,CB\ufffd\r\n"


def test_a_broken_utf8_file_does_not_pass_as_windows_1255(monkeypatch, tmp_path, caplog):
    # One invalid byte fails UTF-8; read as Windows-1255 instead, its Hebrew
    # letters are mostly undefined bytes, far over the replacement cap.
    # (An ASCII header, so it is the cap that refuses it, not the header.)
    rows = "".join(f"שלום עולם,{i},x\r\n" for i in range(40))  # 4 undefined per row
    body = ("name,v,code\r\n" + rows).encode() + b"\xff,1,x\r\n"
    _serve(monkeypatch, body)
    ds = _datastore(monkeypatch)
    fields = [{"id": "name", "type": "text"}, {"id": "v", "type": "numeric"},
              {"id": "code", "type": "text"}]
    caplog.set_level("INFO", logger=ac.log.name)
    out, _ = _export(tmp_path, _preview(fields=fields), total=41, page_size=0)
    assert out.via == "datastore" and len(ds) == 1
    assert "undefined in Windows-1255" in caplog.text


def test_an_8_bit_file_that_is_not_hebrew_falls_back(monkeypatch, tmp_path):
    """Windows-1255 decodes almost any bytes: a Latin-1 file reads as Hebrew
    vowel points, so a non-UTF-8 file with no Hebrew letter uses the datastore."""
    _serve(monkeypatch, "name,v,code\r\nÀÁ,3,x\r\n".encode("latin-1"))
    ds = _datastore(monkeypatch)
    fields = [{"id": "name", "type": "text"}, {"id": "v", "type": "numeric"},
              {"id": "code", "type": "text"}]
    out, _ = _export(tmp_path, _preview(fields=fields), total=1, page_size=0)
    assert out.via == "datastore" and len(ds) == 1


def test_normalizing_past_the_deadline_is_a_wall_budget_overrun(monkeypatch, tmp_path):
    _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    real = ac._check_deadline
    monkeypatch.setattr(ac, "_check_deadline",
                        lambda deadline: real(time.monotonic() - 1))
    with pytest.raises(FetchLimitExceeded) as e:
        _export(tmp_path, _preview())
    assert e.value.limit == "wall_budget" and not ds


def test_blocked_builder_ua_retries_with_a_browser_ua(monkeypatch, tmp_path):
    seen = _serve(monkeypatch, GOOD, blocked_uas={ac._CKAN_BROWSER_UA})
    _datastore(monkeypatch)
    out, _ = _export(tmp_path, _preview())
    assert out.via == "file"
    assert seen == [ac._CKAN_BROWSER_UA, ac._BROWSER_FALLBACK_UA]


@pytest.mark.parametrize("case", [
    "both_uas_blocked", "html_page", "row_count", "header", "sample_row",
    "timestamp_column", "bad_number", "xlsx", "no_preview", "too_big",
])
def test_anything_doubtful_falls_back_to_the_datastore(monkeypatch, tmp_path, case):
    body, preview, total, resource = GOOD, _preview(), 2, RES
    blocked, ctype, max_bytes = (), "text/csv", 1_000_000
    if case == "both_uas_blocked":
        blocked = {ac._CKAN_BROWSER_UA, ac._BROWSER_FALLBACK_UA}
    elif case == "html_page":
        body, ctype = b"<!doctype html><html></html>", "text/html"
    elif case == "row_count":
        total = 3
    elif case == "header":
        body = "שם,ערך,קוד אחר\r\nא,1,ב\r\nג,2,ד\r\n".encode()
    elif case == "sample_row":
        preview = _preview([{"שם": "חיפה", "ערך": 1.5, "קוד": "7"}])
    elif case == "timestamp_column":
        preview = _preview(fields=FIELDS[:3] + [{"id": "קוד", "type": "timestamp"}])
    elif case == "bad_number":
        body = "שם,ערך,קוד\r\nא,\"1,000\",ב\r\nג,2,ד\r\n".encode()
    elif case == "xlsx":
        resource = {**RES, "format": "XLSX"}
    elif case == "no_preview":
        preview = None
    elif case == "too_big":
        max_bytes = 20
    _serve(monkeypatch, body, blocked_uas=blocked, ctype=ctype)
    ds = _datastore(monkeypatch)
    out, dest = _export(tmp_path, preview, total=total, resource=resource, max_bytes=max_bytes)
    assert out.via == "datastore"
    assert len(ds) == 1 and ds[0]["page_size"] == 1
    assert not dest.with_suffix(".raw").exists()


def test_wall_budget_overrun_is_not_a_fallback(monkeypatch, tmp_path):
    _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    with pytest.raises(FetchLimitExceeded) as e:
        ac.fetch_resource_export(
            RES["id"], 2, tmp_path / "m.csv", resource=RES, preview=_preview(),
            max_bytes=1_000_000, deadline=time.monotonic() - 1, page_size=1,
        )
    assert e.value.limit == "wall_budget" and not ds


def test_without_a_resource_only_the_datastore_runs(monkeypatch, tmp_path):
    seen = _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    out = ac.fetch_resource_export(RES["id"], 2, tmp_path / "m.csv", max_bytes=100, page_size=1,
                                   deadline=time.monotonic() + 60)
    assert out.via == "datastore" and len(ds) == 1 and not seen


def test_line_breaks_in_cells_become_spaces(monkeypatch, tmp_path):
    _serve(monkeypatch, 'שם,ערך,קוד\r\n"שורה\r\nשנייה",1,"a\nb\r\n\r\nc"\r\n'.encode())
    _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview(), total=1, page_size=0)
    assert out.via == "file"
    assert dest.read_bytes().decode("utf-8") == "שם,ערך,קוד\r\nשורה שנייה,1,a b  c\r\n"


FLOATY = "שם,ערך,קוד\r\nא,2.5,x\r\nב,2,y\r\n".encode()


def test_a_column_stored_as_floats_keeps_the_point(monkeypatch, tmp_path):
    """The datastore cell at the first whole number answers 2.0: the loader
    stored the column as floats, so whole values come out `2.0`."""
    _serve(monkeypatch, FLOATY)
    _datastore(monkeypatch)
    probes = _probe(monkeypatch, 2.0)
    samples = [{"שם": "א", "ערך": 2.5, "קוד": "x"}]
    out, dest = _export(tmp_path, _preview(samples), page_size=0)
    assert out.via == "file" and probes == [(1, "ערך")]
    assert dest.read_bytes().decode("utf-8") == "שם,ערך,קוד\r\nא,2.5,x\r\nב,2.0,y\r\n"


@pytest.mark.parametrize("samples,probe_answer,want,probed", [
    ([{"ערך": 4.0}], None, {"ערך"}, False),   # a whole float sample: floats
    ([{"ערך": 4}], None, set(), False),       # an int sample: ints
    ([{"ערך": 2.5}], 2, set(), True),         # undecided: the probe says int
    ([], 2.0, {"ערך"}, True),                 # no samples: the probe says float
])
def test_float_columns(tmp_path, samples, probe_answer, want, probed):
    raw = tmp_path / "f.raw"
    raw.write_bytes(FLOATY)
    calls = []

    def probe(offset, col):
        calls.append((offset, col))
        return probe_answer

    got = ac._float_columns(raw, "utf-8-sig", ["שם", "ערך", "קוד"], ["ערך"], samples, probe,
                            time.monotonic() + 60)
    assert got == want
    assert calls == ([(1, "ערך")] if probed else [])


def test_a_probe_that_disagrees_falls_back(monkeypatch, tmp_path):
    _serve(monkeypatch, FLOATY)
    ds = _datastore(monkeypatch)
    _probe(monkeypatch, None)  # the datastore has no number where the file has 2
    out, _ = _export(tmp_path, _preview([{"שם": "א", "ערך": 2.5, "קוד": "x"}]), page_size=0)
    assert out.via == "datastore" and len(ds) == 1


def test_an_input_that_fits_one_page_never_downloads_the_file(monkeypatch, tmp_path):
    seen = _serve(monkeypatch, GOOD)
    ds = _datastore(monkeypatch)
    out, _ = _export(tmp_path, _preview(), total=2, page_size=2)
    assert out.via == "datastore" and len(ds) == 1 and not seen


@pytest.mark.parametrize("raw,float_only,want", [
    ("12", False, "12"), ("012", False, "12"), ("12.0", False, "12"), ("8.20", False, "8.2"),
    (" -3 ", False, "-3"), ("", False, ""), ("3", True, "3.0"), ("177214.273543", False, "177214.273543"),
])
def test_canonical_number(raw, float_only, want):
    assert ac._canonical_number(raw, float_only) == want


@pytest.mark.parametrize("raw", ["1e999999999", "1E-999999999", "abc", "1,000", "inf"])
def test_canonical_number_refuses(raw):
    # A huge exponent must be refused before int() expands it.
    with pytest.raises(ac._FileMismatch):
        ac._canonical_number(raw, False)


# ── malformed rows and CESU-8 ────────────────────────────────────────────

def _rows_datastore(monkeypatch, records):
    """Fake whole-row datastore reads: records[offset]; returns the offsets asked."""
    asked = []

    def fake(rid, offset, limit, timeout, fields=None):
        assert limit == 1 and fields
        asked.append(offset)
        rec = records.get(offset)
        return fields, ([{"_id": offset + 1, **{c: rec[c] for c in fields}}] if rec else [])

    monkeypatch.setattr(ac, "_fetch_page", fake)
    return asked


# Row 2's stray quotes push data past the named columns (the trademarks
# registry's ד"ר ... בע"מ); CKAN's loader kept it as one cell.
MALFORMED = ('שם,ערך,קוד\r\nחיפה,1.50,007\r\nצפת,2,"ד"ר כהן, בע"מ"\r\n'
             'עכו,3,y\r\n').encode()
# The datastore's row 3, which the float-column probe reads (`3` is whole).
ROW3 = {"שם": "עכו", "ערך": 3, "קוד": "y"}


def test_a_malformed_row_is_read_from_the_datastore(monkeypatch, tmp_path):
    _serve(monkeypatch, MALFORMED)
    ds = _datastore(monkeypatch)
    asked = _rows_datastore(monkeypatch, {1: {"שם": "צפת", "ערך": 2, "קוד": 'דר כהן, בע"מ"'},
                                          2: ROW3})
    out, dest = _export(tmp_path, _preview(), total=3)
    assert out.via == "file" and not ds and 1 in asked
    assert dest.read_bytes().decode("utf-8") == (
        'שם,ערך,קוד\r\nחיפה,1.5,007\r\nצפת,2,"דר כהן, בע""מ"""\r\nעכו,3,y\r\n')


def test_a_malformed_row_the_datastore_disagrees_with_falls_back(monkeypatch, tmp_path):
    # The first named column is the row-alignment check (the trademarks
    # registry's running number); a damaged one there also falls back.
    _serve(monkeypatch, MALFORMED)
    ds = _datastore(monkeypatch)
    _rows_datastore(monkeypatch, {1: {"שם": "אחר", "ערך": 2, "קוד": "x"}, 2: ROW3})
    out, _ = _export(tmp_path, _preview(), total=3)
    assert out.via == "datastore" and len(ds) == 1


def test_too_many_malformed_rows_fall_back(monkeypatch, tmp_path):
    monkeypatch.setattr(ac, "_MAX_REFETCHED_ROWS", 0)
    _serve(monkeypatch, MALFORMED)
    ds = _datastore(monkeypatch)
    asked = _rows_datastore(monkeypatch, {2: ROW3})
    out, _ = _export(tmp_path, _preview(), total=3)
    assert out.via == "datastore" and len(ds) == 1 and 1 not in asked


def test_a_cesu8_surrogate_pair_reads_as_its_character(monkeypatch, tmp_path):
    # U+100003 as two 3-byte surrogate sequences, as the trademarks registry
    # has it; the datastore stored the character.
    body = "שם,ערך,קוד\r\nחיפה,1,Ltd".encode() + b"\xed\xaf\x80\xed\xb0\x83" + b"\r\n"
    _serve(monkeypatch, body)
    _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview(), total=1, page_size=0)
    assert out.via == "file"
    assert dest.read_bytes().decode("utf-8") == "שם,ערך,קוד\r\nחיפה,1,Ltd\U00100003\r\n"


def test_an_unpaired_surrogate_falls_back(monkeypatch, tmp_path):
    _serve(monkeypatch, "שם,ערך,קוד\r\nחיפה,1,".encode() + b"\xed\xaf\x80\r\n")
    ds = _datastore(monkeypatch)
    out, _ = _export(tmp_path, _preview(), total=1, page_size=0)
    assert out.via == "datastore" and len(ds) == 1


def test_a_short_row_with_a_stray_quote_is_read_from_the_datastore(monkeypatch, tmp_path):
    # The quote swallowed a delimiter: two cells read as one, the row is short.
    body = ('שם,ערך,קוד\r\nחיפה,1.50,007\r\nצפת,"2,בע"מ"\r\nעכו,3,y\r\n').encode()
    _serve(monkeypatch, body)
    ds = _datastore(monkeypatch)
    asked = _rows_datastore(monkeypatch, {1: {"שם": "צפת", "ערך": 2, "קוד": 'בע"מ'}, 2: ROW3})
    out, dest = _export(tmp_path, _preview(), total=3)
    assert out.via == "file" and not ds and 1 in asked
    assert dest.read_bytes().decode("utf-8").splitlines()[2] == 'צפת,2,"בע""מ"'


def test_a_short_row_without_quotes_keeps_its_empty_tail(monkeypatch, tmp_path):
    _serve(monkeypatch, "שם,ערך,קוד\r\nחיפה,1.50\r\n".encode())
    _datastore(monkeypatch)
    out, dest = _export(tmp_path, _preview(), total=1, page_size=0)
    assert out.via == "file"
    assert dest.read_bytes().decode("utf-8") == "שם,ערך,קוד\r\nחיפה,1.5,\r\n"


def test_a_line_with_no_line_end_in_sight_falls_back(monkeypatch, tmp_path):
    # Bare-CR line ends: without the per-line cap the whole file is one line.
    monkeypatch.setattr(ac, "_MAX_LINE_BYTES", 32)
    _serve(monkeypatch, ("שם,ערך,קוד\r" + "חיפה,1,א\r" * 10).encode())
    ds = _datastore(monkeypatch)
    out, _ = _export(tmp_path, _preview(), total=10, page_size=0)
    assert out.via == "datastore" and len(ds) == 1


def test_the_refetch_respects_the_wall_budget(monkeypatch, tmp_path):
    _serve(monkeypatch, MALFORMED)
    ds = _datastore(monkeypatch)
    _rows_datastore(monkeypatch, {1: {"שם": "צפת", "ערך": 2, "קוד": "x"}, 2: ROW3})
    real = ac._check_deadline

    def deadline_after_the_normalize(deadline):
        # The refetch runs in pool threads; the normalize pass doesn't.
        if threading.current_thread() is not threading.main_thread():
            raise FetchLimitExceeded("wall_budget", "out of wall budget")
        return real(deadline)

    monkeypatch.setattr(ac, "_check_deadline", deadline_after_the_normalize)
    with pytest.raises(FetchLimitExceeded) as e:
        _export(tmp_path, _preview(), total=3)
    assert e.value.limit == "wall_budget" and not ds
    assert not list(tmp_path.glob("*.patch"))
