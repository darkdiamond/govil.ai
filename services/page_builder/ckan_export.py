"""CKAN datastore schema probe and full-data CSV export.

`fetch_resource_preview` / `fetch_resource_export` (with the 403 restriction
gate, `ResourceRestrictedError`): `datastore_search` pages, or for an input
bigger than one page, the uploaded CSV in one download, normalized to the
datastore's shape. `fetch_resource_file` downloads a map file.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode

from services.shared.ckan import EXACT_TOTAL_THRESHOLD, is_authorization_error

log = logging.getLogger(__name__)


class ResourceRestrictedError(Exception):
    """The primary resource's CKAN datastore returns a 403 Authorization
    Error — the dataset's data is access-restricted upstream (private /
    de-listed). A build can't produce a real data page, and the 403 is
    deterministic (retrying won't help), so the caller marks the source
    `restricted` instead of burning an agent session or counting it as a
    transient failure."""


# CKAN schema preview — `fields + total + sample_rows` for one resource. The
# refresh resolves inputs against it, and its sample rows (as truncated and
# capped below) feed precheck fingerprint A and the export cross-check
# (`_matches_sample`), so changing these limits moves both. The WAF 403s
# requests without a browser User-Agent (see scanner notes), and the CKAN
# response can be ~50 MB without `limit`, so we hardcode limit=5 and a tight
# wall-clock budget. On any error the preview returns None.
_CKAN_DATASTORE_URL = "https://data.gov.il/api/3/action/datastore_search"
# The WAF passes this UA on the API and on file downloads (2026-10-31: a bare
# `Mozilla/5.0`, curl's and python-requests' UAs all 403). CKAN_USER_AGENT
# overrides it, so a WAF change is a job env fix, not a redeploy.
_CKAN_BROWSER_UA = (
    os.environ.get("CKAN_USER_AGENT", "").strip()
    or "Mozilla/5.0 (compatible; govdata-builder/1.0)"
)
# The preview asks for an exact count (EXACT_TOTAL_THRESHOLD), a count(*)
# that takes ~1.2s on a 4.2M-row table even when CKAN is idle. Keep headroom:
# a preview that times out twice is a strike that escalates to schema_changed.
_PREFETCH_TIMEOUT_S = 10.0
_PREFETCH_SAMPLE_LIMIT = 5
_PREFETCH_VALUE_TRUNC = 80
_PREFETCH_JSON_CAP = 2048

def _truncate_value(v: Any) -> Any:
    if isinstance(v, str) and len(v) > _PREFETCH_VALUE_TRUNC:
        return v[: _PREFETCH_VALUE_TRUNC - 1] + "…"
    return v


def _http_403_is_restriction(e: urllib_error.HTTPError) -> bool:
    """Decide whether a 403 from datastore_search is an access restriction.

    We send a browser User-Agent, so the gov.il WAF won't 403 us — a 403 here
    is the CKAN datastore Authorization Error. Confirm via the JSON body when
    it parses; if it doesn't, treat a bare 403 as a restriction anyway
    (rate-limiting is 429/503, never 403).
    """
    try:
        body = json.loads(e.read().decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return True
    return is_authorization_error(body)


def fetch_resource_preview(resource_id: str) -> dict | None:
    """Fetch fields + total + 5 sample rows for a CKAN resource.

    Returns ``{"fields": [{id,type}], "total": int, "sample_rows": [...]}``
    on success; ``None`` on any error (timeout, HTTP 4xx/5xx, JSON parse
    failure, missing keys); the caller treats that as no preview.
    """
    if not resource_id:
        return None
    qs = urlencode(
        {
            "resource_id": resource_id,
            "limit": _PREFETCH_SAMPLE_LIMIT,
            "include_total": "true",
            "total_estimation_threshold": EXACT_TOTAL_THRESHOLD,
        }
    )
    url = f"{_CKAN_DATASTORE_URL}?{qs}"
    req = urllib_request.Request(url, headers={"User-Agent": _CKAN_BROWSER_UA})
    last_err: BaseException | None = None
    payload: dict | None = None
    for attempt in (1, 2):
        try:
            with urllib_request.urlopen(req, timeout=_PREFETCH_TIMEOUT_S) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            break
        except urllib_error.HTTPError as e:
            # A 403 here is a CKAN datastore Authorization Error — the data is
            # access-restricted upstream. Deterministic, so don't retry: signal
            # the caller to mark the source `restricted` rather than fall through
            # to an agent session that will only 403 again.
            if e.code == 403 and _http_403_is_restriction(e):
                raise ResourceRestrictedError(
                    f"CKAN datastore 403 (Authorization Error) for resource {resource_id}"
                ) from e
            last_err = e
            if attempt == 1:
                continue
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            if attempt == 1:
                continue
    else:
        log.warning(
            "ckan prefetch %s failed after retry: %s", resource_id[:8], last_err
        )
        return None
    if not payload or not payload.get("success"):
        # A 200 carrying the same Authorization Error is the restriction
        # surfaced differently — treat it identically to the 403 path.
        if payload and is_authorization_error(payload):
            raise ResourceRestrictedError(
                f"CKAN datastore Authorization Error for resource {resource_id}"
            )
        log.warning("ckan prefetch %s success=false", resource_id[:8])
        return None
    result = payload.get("result") or {}
    if result.get("total_was_estimated"):
        # CKAN ignored the threshold: this total can be stale, and the export
        # is checked against it (a shrunk table then fails as cut off).
        log.warning("ckan prefetch %s: total %s is an estimate despite "
                    "total_estimation_threshold", resource_id[:8], result.get("total"))
    fields = [
        {"id": f.get("id"), "type": f.get("type")}
        for f in (result.get("fields") or [])
        if f.get("id")
    ]
    rows = []
    for row in (result.get("records") or [])[: _PREFETCH_SAMPLE_LIMIT]:
        rows.append({k: _truncate_value(v) for k, v in row.items() if k != "_id"})
    preview = {
        "fields": fields,
        "total": int(result.get("total") or 0),
        "sample_rows": rows,
    }
    # Hard cap the serialized size so a wide table stays small (this preview
    # is part of precheck fingerprint A, so the cap is load-bearing).
    serialized = json.dumps(preview, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > _PREFETCH_JSON_CAP:
        # Drop sample rows progressively until we fit; keep fields + total.
        while preview["sample_rows"] and len(
            json.dumps(preview, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ) > _PREFETCH_JSON_CAP:
            preview["sample_rows"].pop()
    return preview

@dataclass
class FetchOutcome:
    rows: int
    bytes: int
    via: str | None = None        # "file" | "datastore" (fetch_resource_export)


# Sequential export paging (`fetch_resource_records_to_file`): the first page
# is the old fixed size, later ones aim at about this much CSV, between
# _MIN_PAGE_ROWS and the caller's `page_size`.
_FIRST_PAGE_ROWS = 25_000
_PAGE_TARGET_BYTES = 32_000_000
_MIN_PAGE_ROWS = 1_000


class _ByteCapExceeded(Exception):
    pass


class _WallBudgetExceeded(Exception):
    pass


FetchLimit = Literal["bytes", "wall_budget"]


class FetchLimitExceeded(Exception):
    """A fetch stopped at a limit, not on an error: `limit` is "bytes" (a
    byte cap) or "wall_budget" (the deadline). Raised by the full-or-nothing
    CKAN export and by provider fetchers. A byte overrun means the dataset
    outgrew its cap, which a retry won't fix."""

    def __init__(self, limit: FetchLimit, message: str):
        if limit not in ("bytes", "wall_budget"):
            raise ValueError(f"unknown fetch limit {limit!r}")
        super().__init__(message)
        self.limit = limit


def _fetch_page(
    resource_id: str,
    offset: int,
    limit: int,
    timeout: float,
    fields: list[str] | None = None,
) -> tuple[list[str], list[dict]]:
    """One datastore_search page → (field ids sans _id, records). Raises on
    any HTTP/parse/success=false problem — callers decide the fallback.
    `fields` asks CKAN for only those columns, in that order."""
    params: dict = {"resource_id": resource_id, "limit": limit, "offset": offset}
    if fields:
        # Repeated, not comma-joined: CKAN splits a joined string on commas,
        # and Hebrew column names can contain one.
        params["fields"] = list(fields)
    qs = urlencode(params, doseq=True)
    req = urllib_request.Request(
        f"{_CKAN_DATASTORE_URL}?{qs}", headers={"User-Agent": _CKAN_BROWSER_UA}
    )
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not payload.get("success"):
        raise RuntimeError("datastore_search success=false")
    result = payload.get("result") or {}
    fields = [
        f["id"] for f in (result.get("fields") or [])
        if f.get("id") and f["id"] != "_id"
    ]
    return fields, (result.get("records") or [])


class _CsvStreamWriter:
    """Streams datastore pages into an open binary file as UTF-8 CSV,
    enforcing a byte cap as it writes (peak RAM ≈ one page)."""

    def __init__(self, f, max_bytes: int):
        self._f = f
        self._max = max_bytes
        self.bytes = 0
        self.rows = 0
        self._fields: list[str] | None = None

    def write_page(self, fields: list[str], records: list[dict]) -> None:
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=self._fields or fields, extrasaction="ignore", restval=""
        )
        if self._fields is None:
            if not fields:
                raise RuntimeError("datastore_search returned no fields")
            self._fields = fields
            writer.fieldnames = fields
            writer.writeheader()
        for r in records:
            writer.writerow({k: ("" if v is None else v) for k, v in r.items()})
        data = buf.getvalue().encode("utf-8")
        if self.bytes + len(data) > self._max:
            raise _ByteCapExceeded()
        self._f.write(data)
        self.bytes += len(data)
        self.rows += len(records)


def fetch_resource_records_to_file(
    resource_id: str,
    total: int,
    dest: Path,
    *,
    max_bytes: int,
    page_size: int,
    page_timeout_s: float,
    deadline: float,
    fields: list[str] | None = None,
) -> FetchOutcome | None:
    """Full datastore export for one resource, streamed to `dest` as UTF-8 CSV.

    Pages datastore_search host-side; `_id` is dropped, field order follows
    the datastore schema, or `fields` (only those columns, in that order)
    when given. Full or nothing: crossing `max_bytes` or `deadline` raises
    FetchLimitExceeded (dest removed), so the caller can tell an outgrown
    dataset from a network error. Any other failure returns None (dest
    removed).
    """
    if not resource_id or total <= 0 or max_bytes <= 0:
        return None

    def _walk() -> tuple[int, int]:
        with open(dest, "wb") as f:
            w = _CsvStreamWriter(f, max_bytes)
            offset = 0
            limit = min(page_size, _FIRST_PAGE_ROWS)
            while offset < total:
                if time.monotonic() > deadline:
                    raise _WallBudgetExceeded()
                page_fields, records = _fetch_page(
                    resource_id, offset, limit, page_timeout_s, fields
                )
                if not records:
                    break
                before = w.bytes
                w.write_page(page_fields, records)
                offset += len(records)
                # A whole page is decoded and held in the builder process,
                # which has no heap cap: size the next one by this one's
                # row width, so a wide table stays near _PAGE_TARGET_BYTES.
                per_row = max(1, (w.bytes - before) // len(records))
                limit = min(page_size, max(_MIN_PAGE_ROWS, _PAGE_TARGET_BYTES // per_row))
            if offset < total:
                # An empty page before `total` (seen 2026-11-03 while the
                # datastore reloaded a resource) is a cut-off export, not
                # the end of the data: fail it, never stage it as full.
                raise RuntimeError(f"datastore ran out at row {offset:,} of {total:,}")
            if w.rows == 0:
                raise RuntimeError("no records returned")
            return w.rows, w.bytes

    started = time.monotonic()
    try:
        rows, nbytes = _walk()
    except _ByteCapExceeded:
        dest.unlink(missing_ok=True)
        raise FetchLimitExceeded(
            "bytes", f"export of {resource_id[:8]} crossed the {max_bytes:,}-byte cap"
        ) from None
    except _WallBudgetExceeded:
        dest.unlink(missing_ok=True)
        raise FetchLimitExceeded(
            "wall_budget", f"export of {resource_id[:8]} ran out of wall budget"
        ) from None
    except Exception as e:  # noqa: BLE001
        log.warning("data prefetch %s (full) failed: %s", resource_id[:8], e)
        dest.unlink(missing_ok=True)
        return None
    log.info(
        "data prefetch %s: full, %d rows, %d bytes in %.1fs",
        resource_id[:8], rows, nbytes, time.monotonic() - started,
    )
    return FetchOutcome(rows=rows, bytes=nbytes)


class DownloadBlocked(Exception):
    """data.gov.il answered a file download with a 403 or an HTML page (the
    WAF's block page, or an OAuth login screen) instead of the file."""


@dataclass
class FileOutcome:
    bytes: int
    sha256: str


_DOWNLOAD_CHUNK = 1 << 16
_FILE_HOST = "https://data.gov.il/"


class _DataGovRedirects(urllib_request.HTTPRedirectHandler):
    """Follow a redirect only while it stays on data.gov.il over https: the
    host check on the first URL is worthless if a 30x can send the builder
    (which holds the builder SA's metadata access) anywhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith(_FILE_HOST):
            raise DownloadBlocked(f"redirected off data.gov.il (HTTP {code} → {newurl[:80]})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_FILE_OPENER = urllib_request.build_opener(_DataGovRedirects)


def _open_file(req, timeout: float):
    return _FILE_OPENER.open(req, timeout=timeout)


def fetch_resource_file(
    url: str,
    dest: Path,
    *,
    max_bytes: int,
    timeout_s: float,
    deadline: float,
    user_agent: str | None = None,
) -> FileOutcome:
    """Download a resource's uploaded file (a map file, say) to `dest`.

    The URL is rewritten to the public `data.gov.il` host first (`e.` and
    `aws-e.` sit behind OAuth walls); any other host is a ValueError, and a
    redirect off data.gov.il is DownloadBlocked. Raises DownloadBlocked on a
    403 or an HTML body, FetchLimitExceeded("bytes"/"wall_budget") past
    `max_bytes` or `deadline`, and lets a network error (URLError, timeout,
    a dropped connection) through after one retry. `dest` is removed on any
    failure.
    """
    import http.client

    from services.scanner.models import _public_resource_url

    url = _public_resource_url(url or "")
    # The URL is publisher-supplied: only ever fetch data.gov.il's own files.
    if not url.startswith(_FILE_HOST):
        raise ValueError(f"not a data.gov.il file URL ({url[:80]!r})")
    req = urllib_request.Request(url, headers={"User-Agent": user_agent or _CKAN_BROWSER_UA})
    for attempt in (1, 2):
        try:
            return _download(req, dest, max_bytes, timeout_s, deadline)
        except urllib_error.HTTPError as e:
            dest.unlink(missing_ok=True)
            if e.code in (401, 403):
                raise DownloadBlocked(f"HTTP {e.code} for {url}") from None
            if attempt == 2 or e.code < 500:
                raise
        except (urllib_error.URLError, TimeoutError, http.client.HTTPException):
            dest.unlink(missing_ok=True)
            if attempt == 2:
                raise
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    raise AssertionError("unreachable")


def _download(req, dest: Path, max_bytes: int, timeout_s: float, deadline: float) -> FileOutcome:
    h = hashlib.sha256()
    n = 0
    with _open_file(req, timeout=timeout_s) as resp:
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            raise DownloadBlocked(f"{req.full_url} answered with an HTML page ({ctype})")
        with open(dest, "wb") as f:
            while chunk := resp.read(_DOWNLOAD_CHUNK):
                if n == 0 and chunk.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
                    raise DownloadBlocked(f"{req.full_url} answered with an HTML page")
                n += len(chunk)
                if n > max_bytes:
                    raise FetchLimitExceeded(
                        "bytes", f"download crossed the {max_bytes:,}-byte cap"
                    )
                if time.monotonic() > deadline:
                    raise FetchLimitExceeded("wall_budget", "download ran out of wall budget")
                h.update(chunk)
                f.write(chunk)
    if n == 0:
        raise DownloadBlocked(f"{req.full_url} answered with an empty body")
    return FileOutcome(bytes=n, sha256=h.hexdigest())


# File export for inputs bigger than one datastore page (see
# `fetch_resource_export`). A resource's uploaded CSV comes down in one
# request, where the datastore needs one per page. It is not the datastore export byte
# for byte (a BOM, Windows-1255, empty trailing columns, numbers as the
# publisher typed them), and recipes and the precheck hashes assume the
# export's exact shape. So the file is rewritten as `_CsvStreamWriter` would
# have written the export, and any doubt (header, row count, a column type we
# can't reproduce, the preview's sample rows) falls back to datastore_search.

# Tried when the WAF refuses the builder UA.
_BROWSER_FALLBACK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
_FILE_TIMEOUT_S = 120.0
_FILE_PROBE_TIMEOUT_S = 30.0
# Datastore column types whose JSON → CSV form we reproduce from the file.
_NUMERIC_TYPES = {"numeric", "int", "int4", "int8", "integer", "bigint"}
_FLOAT_TYPES = {"float8", "float"}


class _FileMismatch(Exception):
    """The file doesn't normalize to the datastore's export."""


def _canonical_number(raw: str, float_only: bool) -> str:
    """A numeric cell as the datastore export writes it: integral values as
    ints, others as a float's repr, empty as ""."""
    from decimal import Decimal, InvalidOperation

    v = raw.strip()
    if not v:
        return ""
    try:
        d = Decimal(v)
    except InvalidOperation:
        raise _FileMismatch(f"non-numeric value {v[:20]!r} in a numeric column") from None
    if not d.is_finite():
        raise _FileMismatch(f"non-finite value {v[:20]!r}")
    # The file is publisher-supplied: `1e999999999` would make int() build a
    # billion-digit number. The datastore never holds such a value anyway.
    if abs(d.adjusted()) > 30:
        raise _FileMismatch(f"out-of-range value {v[:20]!r}")
    if not float_only and d == d.to_integral_value():
        return str(int(d))
    return str(float(d))


_ENCODINGS = ("utf-8-sig", "cp1255")
_HEBREW = re.compile("[א-ת]")


# CKAN's loader decodes a Windows-1255 file with replacement: a byte the
# code page leaves undefined is stored as U+FFFD (3 such bytes in the 879MB
# vehicle registry, 2026-11-04), and so is it here. A UTF-8 file misread as
# Windows-1255 would replace most Hebrew letters, so more than this many
# replacements is a mismatch.
_MAX_CP1255_REPLACED = 100

# Delimiters a data.gov.il CSV upload uses. The Ministry of Transport's
# vehicle files are `|`-separated (23 of 90 recipe inputs over 100k rows,
# 2026-11-04), and their datastore copies hold the split columns.
_DELIMITERS = (",", "|", ";", "\t")

# A row whose stray quotes split it past the named columns is read from the
# datastore instead (_Malformed). CKAN's loader read such quotes its own way
# (the trademarks registry: 122 of 364k rows, 2026-11-04); past this many
# the file is too far from the datastore to stand in for it.
_MAX_REFETCHED_ROWS = 1000
_REFETCH_WORKERS = 8


class _Malformed(list):
    """A file row with data outside the named columns."""


def _join_surrogates(s: str) -> str:
    """A surrogate pair written as two UTF-8 sequences (CESU-8, e.g. ED AF 80
    ED B0 83 in the trademarks registry) → its one character, which is what
    CKAN's loader stored. An unpaired surrogate raises UnicodeDecodeError."""
    return s.encode("utf-16", "surrogatepass").decode("utf-16")


# One physical line of a CSV is read at most this long. Lines end at "\n"
# only, so a file with bare-CR line ends (or none) would otherwise be read
# whole into memory; it pages the datastore instead.
_MAX_LINE_BYTES = 16 * 1024 * 1024


def _decoded_lines(f, encoding: str):
    """The binary file's lines, decoded. Only a line that fails the strict
    decode pays for the fallbacks: UTF-8 joins CESU-8 surrogate pairs,
    Windows-1255 replaces undefined bytes (counted against the cap)."""
    rest = "utf-8" if encoding == "utf-8-sig" else encoding
    enc = encoding  # the BOM can only lead the first line
    replaced = 0
    for line in iter(lambda: f.readline(_MAX_LINE_BYTES), b""):
        if len(line) == _MAX_LINE_BYTES and not line.endswith(b"\n"):
            raise _FileMismatch(
                f"a line longer than {_MAX_LINE_BYTES:,} bytes (bare-CR or no line ends?)")
        try:
            yield line.decode(enc)
        except UnicodeDecodeError:
            if enc == "cp1255":
                text = line.decode(enc, "replace")
                replaced += text.count("\ufffd")
                if replaced > _MAX_CP1255_REPLACED:
                    raise _FileMismatch(
                        f"over {_MAX_CP1255_REPLACED} bytes undefined in Windows-1255") from None
                yield text
            else:
                yield _join_surrogates(line.decode(enc, "surrogatepass"))
        enc = rest


def _file_rows(raw: Path, columns: list[str], encoding: str):
    """(header, iterator of non-blank data rows) of the raw file. The
    datastore loader trims headers; a column with no header must be empty.
    A row with data outside the named columns, or short of them with a quote
    in a cell (stray quotes the loader read another way), is a _Malformed.
    The delimiter is the one whose header reads exactly as the datastore's
    columns. A wrong `encoding` raises UnicodeDecodeError while iterating."""
    for delimiter in _DELIMITERS:
        f = open(raw, "rb")  # noqa: SIM115 — rows() owns and closes it
        reader = csv.reader(_decoded_lines(f, encoding), delimiter=delimiter)
        try:
            header = [h.strip() for h in next(reader, None) or []]
        except BaseException:
            f.close()
            raise
        if not header:
            f.close()
            raise _FileMismatch("empty file")
        if [h for h in header if h != ""] == columns:
            break
        f.close()
    else:
        raise _FileMismatch("header differs from the datastore's columns")
    blank = [i for i, h in enumerate(header) if h == ""]

    def rows():
        with f:
            for row in reader:
                if not any(row):
                    continue
                if (any(row[len(header):]) or any(i < len(row) and row[i] for i in blank)
                        # A stray quote can also swallow a delimiter (13 such
                        # rows in the trademarks registry); a short row with
                        # no quote is a plain short row, its tail empty.
                        or (len(row) < len(header) and any('"' in v for v in row))):
                    yield _Malformed(row)
                else:
                    yield row

    return header, rows()


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise FetchLimitExceeded("wall_budget", "normalizing the file ran out of wall budget")


def _float_columns(raw: Path, encoding: str, columns: list[str], numeric: list[str],
                   samples: list[dict], probe: Callable[[int, str], Any],
                   deadline: float) -> set[str]:
    """Which numeric columns the datastore writes as floats (`2.0`, not `2`).
    The loader decides per column and the schema type doesn't say. A sample
    value settles it when it is a JSON int (ints) or a whole float (floats).
    Otherwise `probe(offset, column)` reads the datastore cell at the first
    row whose file value is a whole number, one call per such column."""
    floats, open_ = set(), []
    for c in numeric:
        vals = [s.get(c) for s in samples]
        if any(isinstance(v, float) and v.is_integer() for v in vals):
            floats.add(c)
        elif not any(isinstance(v, int) and not isinstance(v, bool) for v in vals):
            open_.append(c)
    if not open_:
        return floats
    header, rows = _file_rows(raw, columns, encoding)
    pending = {c: header.index(c) for c in open_}
    first: dict[str, int] = {}
    with closing(rows):
        for n, row in enumerate(rows):
            if n % 10_000 == 0:
                _check_deadline(deadline)
            if isinstance(row, _Malformed):
                continue
            for c, i in list(pending.items()):
                if i < len(row) and _canonical_number(row[i], False).lstrip("-").isdigit():
                    first[c] = n
                    del pending[c]
            if not pending:
                break
    for c, offset in first.items():
        v = probe(offset, c)
        if isinstance(v, float):
            floats.add(c)
        elif not isinstance(v, int) or isinstance(v, bool):
            raise _FileMismatch(f"datastore row {offset + 1} column {c!r} is {v!r}, a whole number in the file")
    return floats


def _matches_sample(sample: Any, value: str) -> bool:
    """`value` (as the export writes it) against the preview's sample cell,
    which `fetch_resource_preview` passed through `_truncate_value`."""
    if sample is None:
        return value == ""
    if isinstance(sample, str):
        return _truncate_value(value) == sample
    return str(sample) == value


def _normalize_csv(raw: Path, dest: Path, preview: dict, total: int,
                   fields: list[str] | None, max_bytes: int,
                   probe: Callable[[int, str], Any], deadline: float,
                   fetch_rows: Callable[[list[int], list[str]], dict[int, dict]] | None = None,
                   ) -> int:
    """Rewrite the downloaded CSV `raw` as the datastore export → `dest`:
    UTF-8 (BOM stripped), else Windows-1255. Returns the row count; raises
    _FileMismatch when it can't match. `probe(offset, column)` reads one
    datastore cell (see _float_columns); `fetch_rows(offsets, columns)` reads
    whole datastore rows, for the file's malformed ones (None: a malformed
    row is a mismatch)."""
    types = {f["id"]: (f.get("type") or "") for f in preview.get("fields") or []
             if f.get("id") and f["id"] != "_id"}
    cols = list(fields) if fields else list(types)
    if not cols or any(c not in types for c in cols):
        raise _FileMismatch("requested columns not in the datastore schema")
    for c in cols:
        if types[c] != "text" and types[c] not in _NUMERIC_TYPES | _FLOAT_TYPES:
            raise _FileMismatch(f"column {c!r} is {types[c]!r}, which the file can't reproduce")
    for encoding in _ENCODINGS:
        try:
            return _normalize_as(raw, encoding, dest, types, cols, preview, total,
                                 max_bytes, probe, deadline, fetch_rows)
        except UnicodeDecodeError:
            continue
    raise _FileMismatch("neither UTF-8 nor Windows-1255")


def _normalize_as(raw: Path, encoding: str, dest: Path, types: dict, cols: list[str],
                  preview: dict, total: int, max_bytes: int,
                  probe: Callable[[int, str], Any], deadline: float,
                  fetch_rows: Callable[[list[int], list[str]], dict[int, dict]] | None,
                  ) -> int:
    samples = preview.get("sample_rows") or []
    floats = _float_columns(
        raw, encoding, list(types), [c for c in cols if types[c] in _NUMERIC_TYPES],
        samples, probe, deadline,
    ) | {c for c in cols if types[c] in _FLOAT_TYPES}
    header, reader = _file_rows(raw, list(types), encoding)
    # Windows-1255 decodes almost any bytes, so a file in another 8-bit
    # encoding would pass as garbled text: accept it only if it reads as Hebrew.
    hebrew = encoding != "cp1255" or any(_HEBREW.search(h) for h in header)
    # The datastore loader trims text cells and turns a line break inside a
    # cell into a space (parity sweeps, 2026-11-03).
    conv = [(header.index(c), types[c] != "text", c in floats) for c in cols]
    rows = 0
    malformed: dict[int, list[str]] = {}
    with closing(reader), open(dest, "w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(cols)
        for row in reader:
            if isinstance(row, _Malformed):
                if fetch_rows is None:
                    raise _FileMismatch(f"row {rows + 1} has data outside the named columns")
                if len(malformed) >= _MAX_REFETCHED_ROWS:
                    raise _FileMismatch(
                        f"over {_MAX_REFETCHED_ROWS:,} malformed rows to read from the datastore")
                # A one-line placeholder, replaced from the datastore below.
                malformed[rows] = row
                w.writerow([""] * len(cols))
                rows += 1
                if rows > total:
                    raise _FileMismatch(f"more rows than the datastore's {total:,}")
                continue
            vals = []
            for i, num, float_only in conv:
                v = row[i] if i < len(row) else ""
                vals.append(_canonical_number(v, float_only) if num else
                            v.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").strip())
            if not hebrew:
                hebrew = any(_HEBREW.search(v) for v in vals)
            if rows < len(samples):
                want = samples[rows]
                for c, v in zip(cols, vals):
                    if c in want and not _matches_sample(want[c], v):
                        raise _FileMismatch(f"row {rows + 1} column {c!r} differs from the datastore")
            w.writerow(vals)
            rows += 1
            if rows > total:
                raise _FileMismatch(f"more rows than the datastore's {total:,}")
            if rows % 10_000 == 0:
                _check_deadline(deadline)
                if out.tell() > max_bytes:
                    raise FetchLimitExceeded("bytes", "normalized file crossed the byte cap")
    if not hebrew:
        raise _FileMismatch("not UTF-8, and no Hebrew when read as Windows-1255")
    if rows != total:
        raise _FileMismatch(f"{rows:,} rows, the datastore has {total:,}")
    if malformed:
        _check_deadline(deadline)
        _patch_rows(dest, malformed, header, types, cols, fetch_rows)
    if dest.stat().st_size > max_bytes:
        raise FetchLimitExceeded("bytes", "normalized file crossed the byte cap")
    return rows


def _patch_rows(dest: Path, malformed: dict[int, list[str]], header: list[str],
                types: dict, cols: list[str],
                fetch_rows: Callable[[list[int], list[str]], dict[int, dict]]) -> None:
    """Replace the placeholder lines of `dest` (one physical line per row:
    the normalizer turns line breaks into spaces) with the datastore's rows
    at the same offsets. Each must agree with the file on its first named
    column, the check that the file and the datastore are still row-aligned."""
    key = next(h for h in header if h)
    ki = header.index(key)
    recs = fetch_rows(sorted(malformed), list(dict.fromkeys([*cols, key])))
    for offset, row in malformed.items():
        got = recs[offset].get(key)
        cell = row[ki].strip() if ki < len(row) else ""
        if types[key] == "text":
            same = (got or "") == cell
        else:
            same = got is not None and _canonical_number(cell, isinstance(got, float)) == str(got)
        if not same:
            raise _FileMismatch(f"row {offset + 1}: datastore {key!r} is {got!r}, the file has {cell!r}")
    patched = dest.with_suffix(".patch")
    try:
        with open(dest, "rb") as src, open(patched, "w", encoding="utf-8", newline="") as out:
            w = csv.writer(out)
            out.write(src.readline().decode("utf-8"))
            for i, line in enumerate(src):
                if i in malformed:
                    rec = recs[i]
                    w.writerow(["" if rec.get(c) is None else rec[c] for c in cols])
                else:
                    out.write(line.decode("utf-8"))
        patched.replace(dest)
    finally:
        patched.unlink(missing_ok=True)
    log.info("file: %d malformed row(s) read from the datastore", len(malformed))


def fetch_resource_csv(
    resource: dict,
    preview: dict | None,
    total: int,
    dest: Path,
    *,
    max_bytes: int,
    deadline: float,
    fields: list[str] | None = None,
    file_max_bytes: int | None = None,
) -> FetchOutcome | None:
    """The resource's uploaded CSV → `dest`, normalized to exactly what the
    datastore export would have written. None when the file can't stand in
    for the export (not a CSV, no preview to check it against, blocked for
    both UAs, too big, or any difference the gate sees): the caller falls
    back to datastore_search. A wall-budget overrun raises
    FetchLimitExceeded, as the datastore path does.

    `max_bytes` bounds the normalized output, like the datastore export.
    The download itself holds every column, not just `fields`, so it is
    bounded by `file_max_bytes` instead (never below `max_bytes`): a recipe
    reading 11 of 23 columns from an 879MB file exports ~400MB, and refusing
    the download at the export cap sent it to 42 datastore pages."""
    from services.scanner.models import _public_resource_url

    rid = (resource.get("id") or "")[:8]
    url = _public_resource_url(resource.get("url") or "")
    if (resource.get("format") or "").strip().upper() != "CSV" or not url.startswith(_FILE_HOST):
        return None
    if not preview or total <= 0:
        return None
    started = time.monotonic()
    raw = dest.with_suffix(".raw")
    try:
        for ua in (_CKAN_BROWSER_UA, _BROWSER_FALLBACK_UA):
            try:
                fetch_resource_file(url, raw, max_bytes=max(max_bytes, file_max_bytes or 0),
                                    timeout_s=_FILE_TIMEOUT_S, deadline=deadline,
                                    user_agent=ua)
                break
            except DownloadBlocked as e:
                if ua == _BROWSER_FALLBACK_UA:
                    raise
                log.info("fetch %s: file blocked for the builder UA (%s), trying a browser UA", rid, e)
        def probe(offset: int, column: str) -> Any:
            _, records = _fetch_page(resource["id"], offset, 1, _FILE_PROBE_TIMEOUT_S, [column])
            return records[0].get(column) if records else None

        def fetch_rows(offsets: list[int], columns: list[str]) -> dict[int, dict]:
            def one(offset: int) -> tuple[int, dict]:
                _check_deadline(deadline)
                _, records = _fetch_page(resource["id"], offset, 1, _FILE_PROBE_TIMEOUT_S, columns)
                if not records:
                    raise _FileMismatch(f"datastore has no row {offset + 1}")
                return offset, records[0]

            with ThreadPoolExecutor(_REFETCH_WORKERS) as pool:
                return dict(pool.map(one, offsets))

        rows = _normalize_csv(raw, dest, preview, total, fields, max_bytes, probe, deadline,
                              fetch_rows)
    except FetchLimitExceeded as e:
        dest.unlink(missing_ok=True)
        if e.limit == "wall_budget":
            raise
        log.info("fetch %s: file unusable (%s), using datastore", rid, e)
        return None
    except Exception as e:  # noqa: BLE001
        dest.unlink(missing_ok=True)
        log.info("fetch %s: file unusable (%s), using datastore", rid, e)
        return None
    finally:
        raw.unlink(missing_ok=True)
    nbytes = dest.stat().st_size
    log.info("data prefetch %s: file, %d rows, %d bytes in %.1fs",
             rid, rows, nbytes, time.monotonic() - started)
    return FetchOutcome(rows=rows, bytes=nbytes, via="file")


def fetch_resource_export(
    resource_id: str,
    total: int,
    dest: Path,
    *,
    resource: dict | None = None,
    preview: dict | None = None,
    max_bytes: int,
    deadline: float,
    fields: list[str] | None = None,
    page_size: int,
    file_max_bytes: int | None = None,
    **datastore_kw,
) -> FetchOutcome | None:
    """Full export of one resource, same contract as
    `fetch_resource_records_to_file`. An input that fits one datastore page
    is one datastore_search call. A bigger one tries its uploaded file first
    (`fetch_resource_csv`, given the CKAN `resource` dict and its datastore
    `preview`) and pages the datastore when the file can't stand in.

    Only above one page: the file and the datastore are separate copies that
    can differ in ways the gate can't see (rows re-uploaded or edited after
    the datastore load). Below ~100k rows one page is already one request
    and the file saved nothing (59-input sweep, 2026-11-03). Above it, over
    the 50 recipe inputs past 100k rows (2026-11-04), 29 used the file, 27
    matched the datastore byte for byte, 2 differed in a few hundred cells,
    and the whole set took 1,040s instead of 1,544s."""
    if resource is not None and total > page_size:
        out = fetch_resource_csv(resource, preview, total, dest, max_bytes=max_bytes,
                                 deadline=deadline, fields=fields,
                                 file_max_bytes=file_max_bytes)
        if out is not None:
            return out
    out = fetch_resource_records_to_file(resource_id, total, dest, max_bytes=max_bytes,
                                         deadline=deadline, fields=fields,
                                         page_size=page_size, **datastore_kw)
    if out is not None:
        out.via = "datastore"
    return out
