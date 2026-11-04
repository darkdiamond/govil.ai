"""Host-side page contract shared by the recipe refresh and local authoring.

1. `fetch_resource_preview` / `fetch_resource_export` — CKAN datastore
   schema probe and full-data CSV export (with the 403 restriction gate,
   `ResourceRestrictedError`): `datastore_search` pages, or for an input
   bigger than one page, the uploaded CSV in one download, normalized to
   the datastore's shape.
2. `sanitize_content_html` — belt-and-braces cleanup for recurring
   page-body failure modes (CDN script tags, fabricated SRI hashes,
   unclosed <script>/<style>, raw control chars in JS strings). Runs on
   every body before it can reach GCS.
3. `run_host_check` — agent/skills/check.py on the sanitized body, the
   final gate before anything is staged.

(Named for the retired agent builder, whose output contract the recipe
pages still satisfy.)
"""
from __future__ import annotations

import csv
import io
import json
import hashlib
import logging
import os
import re
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT_PATH = REPO_ROOT / "agent" / "skills" / "check.py"


def run_host_check(
    content_html: str, agent_data_json: str, workdir: Path, *, recipe: bool = False
) -> None:
    """Run agent/skills/check.py on the sanitized outputs; raise on non-zero.

    The sanitizer may have rewritten the body, so this runs on its output —
    the authoritative gate. Used by the recipe refresh before anything
    reaches GCS/Firestore and by `author verify`, so a recipe passes the
    exact same bar locally as in production.

    Trust boundary: this always runs the IMAGE's check.py
    (`CHECK_SCRIPT_PATH`, root-owned under /app) — never a copy inside a
    sandbox workdir, which sandboxed code could rewrite. `workdir` must be
    a HOST-owned directory, not the sandbox workdir: the sandbox user owns
    that tree and could pre-plant a symlink at validated-content.html that
    this (root) process would write through.
    `-I` keeps PYTHONPATH/user-site/cwd out of check.py's import path.
    """
    c = workdir / "validated-content.html"
    a = workdir / "validated-agent_data.json"
    c.write_text(content_html, encoding="utf-8")
    a.write_text(agent_data_json, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-I", str(CHECK_SCRIPT_PATH), *(["--recipe"] if recipe else []),
         str(c), str(a)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"host self-check failed (exit {proc.returncode}): "
            f"{(proc.stdout or proc.stderr).strip()[:500]}"
        )


class ResourceRestrictedError(Exception):
    """The primary resource's CKAN datastore returns a 403 Authorization
    Error — the dataset's data is access-restricted upstream (private /
    de-listed). A build can't produce a real data page, and the 403 is
    deterministic (retrying won't help), so the caller marks the source
    `restricted` instead of burning an agent session or counting it as a
    transient failure."""


# CKAN schema prefetch — skip the agent's first 5–10 schema-discovery curls
# by inlining `fields + total + sample_rows` into the user message. The WAF
# 403s requests without a browser User-Agent (see scanner notes), and the
# CKAN response can be ~50 MB without `limit`, so we hardcode limit=5 and a
# tight wall-clock budget. On any error we return None and the agent falls
# back to its existing curl flow — never block the build on prefetch.
_CKAN_DATASTORE_URL = "https://data.gov.il/api/3/action/datastore_search"
# The WAF passes this UA on the API and on file downloads (2026-10-31: a bare
# `Mozilla/5.0`, curl's and python-requests' UAs all 403). CKAN_USER_AGENT
# overrides it, so a WAF change is a job env fix, not a redeploy.
_CKAN_BROWSER_UA = (
    os.environ.get("CKAN_USER_AGENT", "").strip()
    or "Mozilla/5.0 (compatible; govdata-builder/1.0)"
)
_PREFETCH_TIMEOUT_S = 4.0
_PREFETCH_SAMPLE_LIMIT = 5
_PREFETCH_VALUE_TRUNC = 80
_PREFETCH_JSON_CAP = 2048

def _truncate_value(v: Any) -> Any:
    if isinstance(v, str) and len(v) > _PREFETCH_VALUE_TRUNC:
        return v[: _PREFETCH_VALUE_TRUNC - 1] + "…"
    return v


def _payload_is_authorization_error(payload: dict) -> bool:
    """True when a CKAN JSON envelope carries an Authorization Error.

    CKAN reports a restricted resource as `{"success": false, "error":
    {"__type": "Authorization Error", …}}` — surfaced either with HTTP 403
    or (rarely) HTTP 200.
    """
    err = payload.get("error") or {}
    return "Authorization" in str(err.get("__type") or "")


def _http_403_is_restriction(e: urllib_error.HTTPError) -> bool:
    """Decide whether a 403 from datastore_search is an access restriction.

    We send a browser User-Agent, so the gov.il WAF won't 403 us — a 403 here
    is the CKAN datastore Authorization Error. Confirm via the JSON body when
    it parses; if it doesn't, treat a bare 403 as a restriction anyway
    (rate-limiting is 429/503, never 403).
    """
    try:
        body = json.loads(e.read().decode("utf-8", errors="replace"))
    except Exception:
        return True
    return _payload_is_authorization_error(body)


def fetch_resource_preview(resource_id: str) -> Optional[dict]:
    """Fetch fields + total + 5 sample rows for a CKAN resource.

    Returns ``{"fields": [{id,type}], "total": int, "sample_rows": [...]}``
    on success; ``None`` on any error (timeout, HTTP 4xx/5xx, JSON parse
    failure, missing keys). The agent's prompt accepts the absence
    silently and falls back to its current schema-discovery flow.
    """
    if not resource_id:
        return None
    qs = urlencode(
        {
            "resource_id": resource_id,
            "limit": _PREFETCH_SAMPLE_LIMIT,
            "include_total": "true",
        }
    )
    url = f"{_CKAN_DATASTORE_URL}?{qs}"
    req = urllib_request.Request(url, headers={"User-Agent": _CKAN_BROWSER_UA})
    last_err: Optional[BaseException] = None
    payload: Optional[dict] = None
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
        if payload and _payload_is_authorization_error(payload):
            raise ResourceRestrictedError(
                f"CKAN datastore Authorization Error for resource {resource_id}"
            )
        log.warning("ckan prefetch %s success=false", resource_id[:8])
        return None
    result = payload.get("result") or {}
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
    # Hard cap the serialized size so a wide table doesn't bloat the prompt.
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
    mode: str                        # "full" | "sample"
    sample_note: Optional[str] = None
    via: Optional[str] = None        # "file" | "datastore" (fetch_resource_export)


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
    byte cap) or "wall_budget" (the deadline). Raised by a full-or-nothing
    CKAN export (`sample_target_rows=0`) and by provider fetchers. A byte
    overrun means the dataset outgrew its cap, which a retry won't fix."""

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
    fields: Optional[list[str]] = None,
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
        self._fields: Optional[list[str]] = None

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
    sample_target_rows: int,
    prefer_sample: bool = False,
    fields: Optional[list[str]] = None,
) -> Optional[FetchOutcome]:
    """Datastore export for one resource, streamed to `dest` as UTF-8 CSV.

    Pages datastore_search host-side (same source of truth the agent would
    query); `_id` is dropped, field order follows the datastore schema, or
    `fields` (only those columns, in that order) when given.
    A full export that crosses `max_bytes` mid-stream retries in sample
    mode instead of discarding everything. Sampling (when
    `sample_target_rows` > 0) fetches deterministic contiguous blocks:
    the head page plus pages at fixed strides — verbatim datastore output,
    recipe recorded in `sample_note`. Returns None when nothing could or
    should be written (dest is removed). Without sampling
    (`sample_target_rows=0`), crossing `max_bytes` or `deadline` raises
    FetchLimitExceeded instead (dest removed), so the caller can tell an
    outgrown dataset from a network error.
    """
    if not resource_id or total <= 0 or max_bytes <= 0:
        return None

    def _walk(offsets: list[int], sequential: bool) -> tuple[int, int]:
        with open(dest, "wb") as f:
            w = _CsvStreamWriter(f, max_bytes)
            if sequential:
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
            else:
                for offset in offsets:
                    if time.monotonic() > deadline:
                        raise _WallBudgetExceeded()
                    page_fields, records = _fetch_page(
                        resource_id, offset, page_size, page_timeout_s, fields
                    )
                    if records:
                        w.write_page(page_fields, records)
            if w.rows == 0:
                raise RuntimeError("no records returned")
            return w.rows, w.bytes

    started = time.monotonic()
    if not prefer_sample:
        try:
            rows, nbytes = _walk([], sequential=True)
            log.info(
                "data prefetch %s: full, %d rows, %d bytes in %.1fs",
                resource_id[:8], rows, nbytes, time.monotonic() - started,
            )
            return FetchOutcome(rows=rows, bytes=nbytes, mode="full")
        except _ByteCapExceeded:
            if sample_target_rows <= 0:
                dest.unlink(missing_ok=True)
                raise FetchLimitExceeded(
                    "bytes", f"export of {resource_id[:8]} crossed the {max_bytes:,}-byte cap"
                ) from None
            log.info(
                "data prefetch %s: byte cap crossed mid-fetch — retrying as sample",
                resource_id[:8],
            )
        except _WallBudgetExceeded:
            dest.unlink(missing_ok=True)
            if sample_target_rows <= 0:
                raise FetchLimitExceeded(
                    "wall_budget", f"export of {resource_id[:8]} ran out of wall budget"
                ) from None
            log.warning("data prefetch %s (full) failed: wall budget exceeded", resource_id[:8])
            return None
        except Exception as e:
            log.warning("data prefetch %s (full) failed: %s", resource_id[:8], e)
            dest.unlink(missing_ok=True)
            return None

    if sample_target_rows > 0 and total > 0:
        n_blocks = max(1, -(-sample_target_rows // page_size))  # ceil div
        stride = max(total // n_blocks, page_size)
        offsets = list(range(0, total, stride))[:n_blocks]
        note = (
            f"{len(offsets)} contiguous blocks of up to {page_size:,} rows, "
            f"starting at offsets 0, {stride:,}, {2 * stride:,}, …"
        )
        try:
            rows, nbytes = _walk(offsets, sequential=False)
            log.info(
                "data prefetch %s: sample, %d of %d rows, %d bytes in %.1fs",
                resource_id[:8], rows, total, nbytes, time.monotonic() - started,
            )
            return FetchOutcome(
                rows=rows, bytes=nbytes, mode="sample", sample_note=note
            )
        except Exception as e:
            log.warning("data prefetch %s (sample) failed: %s", resource_id[:8], e)

    dest.unlink(missing_ok=True)
    return None


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
    user_agent: Optional[str] = None,
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


def _file_rows(raw: Path, columns: list[str], encoding: str):
    """(header, iterator of non-blank data rows) of the raw file. The
    datastore loader trims headers; a column with no header must be empty.
    A wrong `encoding` raises UnicodeDecodeError while iterating."""
    f = open(raw, encoding=encoding, newline="")
    reader = csv.reader(f)
    try:
        header = [h.strip() for h in next(reader, None) or []]
    except BaseException:
        f.close()
        raise
    if not header:
        f.close()
        raise _FileMismatch("empty file")
    if [h for h in header if h != ""] != columns:
        f.close()
        raise _FileMismatch("header differs from the datastore's columns")
    blank = [i for i, h in enumerate(header) if h == ""]

    def rows():
        with f:
            n = 0
            for row in reader:
                if not any(row):
                    continue
                n += 1
                if any(row[len(header):]) or any(i < len(row) and row[i] for i in blank):
                    raise _FileMismatch(f"row {n} has data outside the named columns")
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
                   fields: Optional[list[str]], max_bytes: int,
                   probe: Callable[[int, str], Any], deadline: float) -> int:
    """Rewrite the downloaded CSV `raw` as the datastore export → `dest`:
    UTF-8 (BOM stripped), else Windows-1255. Returns the row count; raises
    _FileMismatch when it can't match. `probe(offset, column)` reads one
    datastore cell (see _float_columns)."""
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
                                 max_bytes, probe, deadline)
        except UnicodeDecodeError:
            continue
    raise _FileMismatch("neither UTF-8 nor Windows-1255")


def _normalize_as(raw: Path, encoding: str, dest: Path, types: dict, cols: list[str],
                  preview: dict, total: int, max_bytes: int,
                  probe: Callable[[int, str], Any], deadline: float) -> int:
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
    with closing(reader), open(dest, "w", encoding="utf-8", newline="") as out:
        w = csv.writer(out)
        w.writerow(cols)
        for row in reader:
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
    if dest.stat().st_size > max_bytes:
        raise FetchLimitExceeded("bytes", "normalized file crossed the byte cap")
    return rows


def fetch_resource_csv(
    resource: dict,
    preview: Optional[dict],
    total: int,
    dest: Path,
    *,
    max_bytes: int,
    deadline: float,
    fields: Optional[list[str]] = None,
) -> Optional[FetchOutcome]:
    """The resource's uploaded CSV → `dest`, normalized to exactly what the
    datastore export would have written. None when the file can't stand in
    for the export (not a CSV, no preview to check it against, blocked for
    both UAs, too big, or any difference the gate sees): the caller falls
    back to datastore_search. A wall-budget overrun raises
    FetchLimitExceeded, as the datastore path does."""
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
                fetch_resource_file(url, raw, max_bytes=max_bytes, timeout_s=_FILE_TIMEOUT_S,
                                    deadline=deadline, user_agent=ua)
                break
            except DownloadBlocked as e:
                if ua == _BROWSER_FALLBACK_UA:
                    raise
                log.info("fetch %s: file blocked for the builder UA (%s), trying a browser UA", rid, e)
        def probe(offset: int, column: str) -> Any:
            _, records = _fetch_page(resource["id"], offset, 1, _FILE_PROBE_TIMEOUT_S, [column])
            return records[0].get(column) if records else None

        rows = _normalize_csv(raw, dest, preview, total, fields, max_bytes, probe, deadline)
    except FetchLimitExceeded as e:
        dest.unlink(missing_ok=True)
        if e.limit == "wall_budget":
            raise
        log.info("fetch %s: file unusable (%s), using datastore", rid, e)
        return None
    except Exception as e:
        dest.unlink(missing_ok=True)
        log.info("fetch %s: file unusable (%s), using datastore", rid, e)
        return None
    finally:
        raw.unlink(missing_ok=True)
    nbytes = dest.stat().st_size
    log.info("data prefetch %s: file, %d rows, %d bytes in %.1fs",
             rid, rows, nbytes, time.monotonic() - started)
    return FetchOutcome(rows=rows, bytes=nbytes, mode="full", via="file")


def fetch_resource_export(
    resource_id: str,
    total: int,
    dest: Path,
    *,
    resource: Optional[dict] = None,
    preview: Optional[dict] = None,
    max_bytes: int,
    deadline: float,
    fields: Optional[list[str]] = None,
    page_size: int,
    **datastore_kw,
) -> Optional[FetchOutcome]:
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
                                 deadline=deadline, fields=fields)
        if out is not None:
            return out
    out = fetch_resource_records_to_file(resource_id, total, dest, max_bytes=max_bytes,
                                         deadline=deadline, fields=fields,
                                         page_size=page_size, **datastore_kw)
    if out is not None:
        out.via = "datastore"
    return out


# Belt-and-braces cleanup for agent-emitted body fragments. The agent
# prompt forbids `<script src=>` / `<link>` / `integrity=` / `<\/script>`,
# but LLM hallucinations recur (one dataset shipped with both a fabricated
# SRI hash on Leaflet AND `<\/script>` JSON-escape in every script-end tag,
# silently breaking all viz). These regexes catch the same classes of bug
# at the staging boundary so a regression on the prompt side never reaches
# production. Each rule logs a WARNING when it fires.
_SCRIPT_END_ESCAPED = re.compile(r"<\\/script(\s*)>", re.IGNORECASE)
_INTEGRITY_ATTR = re.compile(r'\s+integrity\s*=\s*"[^"]*"', re.IGNORECASE)
_CROSSORIGIN_ATTR = re.compile(r'\s+crossorigin(?:\s*=\s*"[^"]*")?', re.IGNORECASE)
_CDN_HOSTS = r"(?:[\w-]+\.)*(?:unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com)"
_SCRIPT_CDN_TAG = re.compile(
    rf'<script\b[^>]*\bsrc\s*=\s*"https?://{_CDN_HOSTS}[^"]*"[^>]*>\s*(?:</script>)?',
    re.IGNORECASE,
)
_LINK_CDN_TAG = re.compile(
    rf'<link\b[^>]*\bhref\s*=\s*"https?://{_CDN_HOSTS}[^"]*"[^>]*/?>',
    re.IGNORECASE,
)
# Cloudflare "Email Address Obfuscation": when the agent web_fetches a
# gov.il page that sits behind Cloudflare with that feature on, the source
# HTML has real mailto:s rewritten to `<a href="/cdn-cgi/l/email-protection
# #HEX"><span class="__cf_email__" data-cfemail="HEX">[email protected]</span></a>`
# (a client-side JS on Cloudflare decodes it). govil.ai is NOT behind
# Cloudflare, so any such link the agent copies verbatim 404s on click and
# the address never renders. The real address is XOR-encoded in the HEX
# (first byte = key). Decode it back to a plain mailto: link on ingest.
_CF_EMAIL_ANCHOR = re.compile(
    r"<a\b[^>]*?/cdn-cgi/l/email-protection[^>]*>.*?</a>", re.IGNORECASE | re.DOTALL
)
_CF_EMAIL_HEX = re.compile(r'data-cfemail="([0-9a-fA-F]{4,})"', re.IGNORECASE)
_CF_SCRIPT_TAG = re.compile(
    r'<script\b[^>]*\bsrc\s*=\s*"[^"]*cdn-cgi[^"]*"[^>]*>\s*(?:</script>)?',
    re.IGNORECASE,
)


def _decode_cfemail(hex_str: str) -> Optional[str]:
    """Decode a Cloudflare `data-cfemail` hex string to a plain address."""
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError:
        return None
    if len(raw) < 2:
        return None
    key = raw[0]
    email = "".join(chr(b ^ key) for b in raw[1:])
    return email if "@" in email else None


def _deobfuscate_cf_email(match: re.Match) -> str:
    anchor = match.group(0)
    hex_match = _CF_EMAIL_HEX.search(anchor)
    email = _decode_cfemail(hex_match.group(1)) if hex_match else None
    if email:
        return f'<a href="mailto:{email}">{email}</a>'
    # No decodable address: neutralize the dead link, keep whatever text is
    # there rather than dropping content.
    inner = re.sub(r"<[^>]+>", "", anchor)
    return inner or ""


_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPEN_SCRIPT = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_CLOSE_SCRIPT = re.compile(r"</script\s*>", re.IGNORECASE)
_OPEN_STYLE = re.compile(r"<style\b[^>]*>", re.IGNORECASE)
_CLOSE_STYLE = re.compile(r"</style\s*>", re.IGNORECASE)
_SCRIPT_BLOCK = re.compile(
    r"(<script\b[^>]*>)(.*?)(</script\s*>)", re.IGNORECASE | re.DOTALL
)
_SCRIPT_DATA_TYPE = re.compile(
    r'\btype\s*=\s*"(?:application/(?:[a-z0-9-]+\+)?json|text/[a-z0-9-]+)"',
    re.IGNORECASE,
)
# Above this many missing closers the body is structurally broken in
# ways a string-append can't safely fix — fail loudly instead.
_MAX_AUTO_REPAIR = 5


def _balance_raw_text_tag(
    body: str,
    opener: re.Pattern,
    closer: re.Pattern,
    name: str,
    *,
    tag: str,
) -> str:
    # `<script>` and `<style>` put the parser in a raw-text state until
    # the matching `</…>`; an unclosed opener swallows the rest of the
    # document, breaks the inline JS, and (for the agent body) blocks
    # Nuxt hydration. Auto-repair: if opens > closes, append the missing
    # closers so the parser can exit raw-text state cleanly.
    counted = _HTML_COMMENT.sub("", body)
    opens = len(opener.findall(counted))
    closes = len(closer.findall(counted))
    delta = opens - closes
    if delta == 0:
        return body
    if delta < 0:
        log.warning(
            "%ssanitizer: %d stray </%s> than <%s> — leaving as-is",
            tag, -delta, name, name,
        )
        return body
    if delta > _MAX_AUTO_REPAIR:
        raise ValueError(
            f"{tag}sanitizer: {delta} unclosed <{name}> tags exceeds "
            f"auto-repair cap ({_MAX_AUTO_REPAIR}); refusing to publish"
        )
    log.warning("%ssanitizer: appended %d missing </%s> tag(s)", tag, delta, name)
    sep = "" if body.endswith("\n") else "\n"
    return body + sep + (f"</{name}>\n" * delta)


_JS_CTRL_ESCAPES: dict[str, str] = {
    "\x08": "\\b",
    "\x09": "\\t",
    "\x0a": "\\n",
    "\x0b": "\\v",
    "\x0c": "\\f",
    "\x0d": "\\r",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}
for _i in list(range(0x00, 0x08)) + [0x0e, 0x0f] + list(range(0x10, 0x20)):
    _JS_CTRL_ESCAPES.setdefault(chr(_i), f"\\u{_i:04x}")


def _escape_js_string_controls(script_body: str) -> tuple[str, int]:
    # Walk the script body tracking comment/string state and replace any raw
    # control char or line terminator inside `"…"` / `'…'` literals with its
    # JS escape. CKAN address fields routinely carry embedded LFs; when the
    # agent inlines a row array as a JS literal those LFs land *unescaped*
    # inside the string and V8 aborts the whole <script> with "Invalid or
    # unexpected token" — taking every chart and the Leaflet map down with
    # it (b2370286-… exhibited exactly this).
    out: list[str] = []
    i = 0
    n = len(script_body)
    count = 0
    while i < n:
        c = script_body[i]
        # Line comment — preserve verbatim.
        if c == "/" and i + 1 < n and script_body[i + 1] == "/":
            j = script_body.find("\n", i)
            if j < 0:
                j = n
            out.append(script_body[i:j])
            i = j
            continue
        # Block comment — preserve verbatim.
        if c == "/" and i + 1 < n and script_body[i + 1] == "*":
            j = script_body.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(script_body[i:j])
            i = j
            continue
        # Template literal — raw newlines are legal here, leave as-is. We do
        # not try to parse `${…}` interpolation; for the purpose of this
        # sanitizer it's enough to skip to the matching backtick honouring
        # backslash escape.
        if c == "`":
            out.append(c)
            i += 1
            while i < n:
                ch = script_body[i]
                if ch == "\\" and i + 1 < n:
                    out.append(script_body[i:i + 2])
                    i += 2
                    continue
                out.append(ch)
                i += 1
                if ch == "`":
                    break
            continue
        # `'…'` / `"…"` string — the only place we actually escape.
        if c == '"' or c == "'":
            quote = c
            out.append(quote)
            i += 1
            while i < n:
                ch = script_body[i]
                if ch == "\\" and i + 1 < n:
                    out.append(script_body[i:i + 2])
                    i += 2
                    continue
                if ch == quote:
                    out.append(quote)
                    i += 1
                    break
                esc = _JS_CTRL_ESCAPES.get(ch)
                if esc is not None:
                    out.append(esc)
                    count += 1
                    i += 1
                    continue
                out.append(ch)
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out), count


def _escape_script_string_controls(body: str, *, tag: str) -> str:
    total = 0

    def handle(match: "re.Match[str]") -> str:
        nonlocal total
        opener, inner, closer = match.group(1), match.group(2), match.group(3)
        # Skip data blocks (JSON-LD, application/json, etc.) — those aren't
        # parsed as JS, raw newlines are fine and "fixing" them would break
        # the JSON.
        if _SCRIPT_DATA_TYPE.search(opener):
            return match.group(0)
        new_inner, n = _escape_js_string_controls(inner)
        total += n
        return opener + new_inner + closer

    new_body = _SCRIPT_BLOCK.sub(handle, body)
    if total:
        log.warning(
            "%ssanitizer: escaped %d raw control char(s) in JS string literal(s)",
            tag, total,
        )
    return new_body


def sanitize_content_html(body: str, *, dataset_id: str = "") -> str:
    """Strip agent-output failure modes that recur as LLM hallucinations.

    Drops `<script src=>` / `<link href=>` to known CDNs (unpkg, jsdelivr,
    cdnjs) — the Nuxt shell pre-loads ECharts/Leaflet/MarkerCluster
    same-origin and the agent contract forbids external resource refs.
    Strips `integrity=` / `crossorigin=` attributes (any SRI hash the
    agent emits is fabricated; same-origin loads don't need either).
    Replaces `<\\/script>` (JSON string-escape) with `</script>` so the
    HTML parser actually closes the tag. Auto-closes unclosed
    `<script>`/`<style>` tags (e4a5e2d7-… shipped without the trailing
    `</script>`, which let the parser swallow the page footer and the
    Nuxt config bootstrap, blanking every chart and breaking hydration).
    Escapes raw control chars (LF/CR/etc.) inside `"…"`/`'…'` JS string
    literals (b2370286-… inlined CKAN address fields containing embedded
    newlines as a JS array literal — V8 aborted the whole <script> on the
    first one, blanking 4 ECharts + the Leaflet map).

    Each transform logs a WARNING with a count and the dataset id so we
    can trace prompt regressions even when the sanitizer silently fixes
    them.
    """
    tag = f"[{dataset_id}] " if dataset_id else ""

    new_body, n = _SCRIPT_END_ESCAPED.subn(r"</script\1>", body)
    if n:
        log.warning("%ssanitizer: replaced %d <\\/script> -> </script>", tag, n)
    body = new_body

    new_body, n = _INTEGRITY_ATTR.subn("", body)
    if n:
        log.warning("%ssanitizer: stripped %d integrity= attribute(s)", tag, n)
    body = new_body

    new_body, n = _CROSSORIGIN_ATTR.subn("", body)
    if n:
        log.warning("%ssanitizer: stripped %d crossorigin attribute(s)", tag, n)
    body = new_body

    new_body, n = _SCRIPT_CDN_TAG.subn("", body)
    if n:
        log.warning("%ssanitizer: dropped %d <script src=CDN> tag(s)", tag, n)
    body = new_body

    new_body, n = _LINK_CDN_TAG.subn("", body)
    if n:
        log.warning("%ssanitizer: dropped %d <link href=CDN> tag(s)", tag, n)
    body = new_body

    new_body, n = _CF_EMAIL_ANCHOR.subn(_deobfuscate_cf_email, body)
    if n:
        log.warning("%ssanitizer: decoded %d Cloudflare email-protection link(s)", tag, n)
    body = new_body

    new_body, n = _CF_SCRIPT_TAG.subn("", body)
    if n:
        log.warning("%ssanitizer: dropped %d <script src=/cdn-cgi/> tag(s)", tag, n)
    body = new_body

    body = _balance_raw_text_tag(body, _OPEN_SCRIPT, _CLOSE_SCRIPT, "script", tag=tag)
    body = _balance_raw_text_tag(body, _OPEN_STYLE, _CLOSE_STYLE, "style", tag=tag)

    # Run after balancing so every <script> has a closer the regex can find.
    body = _escape_script_string_controls(body, tag=tag)

    return body
