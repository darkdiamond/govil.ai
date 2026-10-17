"""The page-builder agent's I/O contract — shared by production and the
local test harness.

Three concerns live here:

1. `build_user_message` — the first (and only) user message an agent
   session receives: dataset facts + the per-session OUTPUTS_DIR and
   CHECK_SCRIPT paths the system prompt (agent/system-prompt.md)
   references symbolically. Keeping per-session paths out of the system
   prompt keeps the prompt byte-identical across sessions, which is
   what lets providers serve it from prefix cache.
2. `fetch_resource_preview` — host-side CKAN schema prefetch that
   saves the agent its first 5-10 discovery calls.
3. `sanitize_content_html` — belt-and-braces cleanup for recurring
   LLM output failure modes (CDN script tags, fabricated SRI hashes,
   unclosed <script>/<style>, raw control chars in JS strings). Runs
   on every body before it can reach GCS.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT_PATH = REPO_ROOT / "agent" / "skills" / "check.py"


def run_host_check(content_html: str, agent_data_json: str, workdir: Path) -> None:
    """Run agent/skills/check.py on the sanitized outputs; raise on non-zero.

    The agent already self-checked in its sandbox, but the sanitizer may
    have rewritten the body since — this is the authoritative gate. Used
    by production (`agent_runner`) before anything reaches GCS/Firestore
    and by the local test harness (`model_harness.run_test_session`) so
    eval runs pass the exact same bar.

    Trust boundary: this always runs the IMAGE's check.py
    (`CHECK_SCRIPT_PATH`, root-owned under /app) — never the per-session
    copy the agent self-checks with, which the session can rewrite.
    `workdir` must be a HOST-owned directory, not the sandbox workdir: the
    sandbox user owns that tree and could pre-plant a symlink at
    validated-content.html that this (root) process would write through.
    `-I` keeps PYTHONPATH/user-site/cwd out of check.py's import path.
    """
    c = workdir / "validated-content.html"
    a = workdir / "validated-agent_data.json"
    c.write_text(content_html, encoding="utf-8")
    a.write_text(agent_data_json, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-I", str(CHECK_SCRIPT_PATH), str(c), str(a)],
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
_CKAN_BROWSER_UA = "Mozilla/5.0 (compatible; govdata-builder/1.0)"
_PREFETCH_TIMEOUT_S = 4.0
_PREFETCH_SAMPLE_LIMIT = 5
_PREFETCH_VALUE_TRUNC = 80
_PREFETCH_JSON_CAP = 2048

# Full-data prefetch (host-side datastore export → CSV files in the session
# workdir). Every model burned most of its tool rounds paginating
# datastore_search; shipping the data into the sandbox up front cuts
# requests, wall-clock, and CKAN/WAF flake exposure. All knobs are
# env-overridable; any failure degrades to "no file for that resource"
# and the session falls
# back to the normal curl flow — prefetch must never block a build.
#
#   DATA_PREFETCH_MAX_RECORDS   coarse record gate; above it a resource is
#                               sampled (if enabled) instead of fetched in
#                               full. 0 disables all data prefetch.
#   DATA_PREFETCH_MAX_BYTES     per-resource CSV cap, enforced while
#                               streaming.
#   DATA_PREFETCH_TOTAL_BYTES   per-dataset aggregate cap across all files.
#   DATA_PREFETCH_SAMPLE_ROWS   over-cap fallback: deterministic sample of
#                               ~this many rows. 0 = all-or-nothing (legacy).
#   DATA_PREFETCH_MULTI         prefetch every datastore-active resource
#                               (deduped). Default TRUE — multi-resource
#                               datasets get all their files; set =false to
#                               restrict to the primary resource only.
#   DATA_PREFETCH_PAGE_SIZE / DATA_PREFETCH_WALL_BUDGET_S  paging knobs.
_DATA_PREFETCH_DEFAULT_MAX_RECORDS = 50_000
_DATA_PREFETCH_DEFAULT_PAGE_SIZE = 25_000
_DATA_PREFETCH_PAGE_TIMEOUT_S = 60.0
_DATA_PREFETCH_DEFAULT_WALL_BUDGET_S = 120.0
_DATA_PREFETCH_DEFAULT_MAX_BYTES = 30_000_000
_DATA_PREFETCH_DEFAULT_TOTAL_BYTES = 60_000_000
_DATA_PREFETCH_DEFAULT_SAMPLE_ROWS = 0
# Cap on the serialized per-file schemas block in the user message.
_SCHEMAS_BLOCK_CAP = 10_240


def _env_int(name: str, default: int) -> int:
    try:
        raw = os.environ.get(name)
        return int(raw) if raw is not None and raw != "" else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name)
        return float(raw) if raw is not None and raw != "" else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


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

def data_prefetch_max_records() -> int:
    """Record gate for the full-data prefetch (0 disables all prefetch)."""
    return _env_int("DATA_PREFETCH_MAX_RECORDS", _DATA_PREFETCH_DEFAULT_MAX_RECORDS)


@dataclass
class PrefetchedResource:
    """One datastore resource as presented to the agent session.

    ``host_path`` is set when a CSV was actually exported (``mode`` is
    ``full`` or ``sample``); ``mode == "unfetched"`` means the resource is
    listed for awareness only and the agent queries it via the API.
    """
    resource_id: str
    name: str
    format: str
    total: int
    schema: Optional[dict]
    sandbox_filename: Optional[str] = None
    host_path: Optional[Path] = None
    rows: int = 0
    mode: str = "unfetched"          # "full" | "sample" | "unfetched"
    sample_note: Optional[str] = None


@dataclass
class FetchOutcome:
    rows: int
    bytes: int
    mode: str                        # "full" | "sample"
    sample_note: Optional[str] = None


class _ByteCapExceeded(Exception):
    pass


def _fetch_page(
    resource_id: str, offset: int, limit: int, timeout: float
) -> tuple[list[str], list[dict]]:
    """One datastore_search page → (field ids sans _id, records). Raises on
    any HTTP/parse/success=false problem — callers decide the fallback."""
    qs = urlencode({"resource_id": resource_id, "limit": limit, "offset": offset})
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


def _estimate_bytes_per_row(preview: Optional[dict]) -> Optional[float]:
    """CSV bytes/row estimated from the schema preview's sample rows,
    with the survey's ~1.06 metadata calibration rounded up to 1.1."""
    rows = (preview or {}).get("sample_rows") or []
    if not rows:
        return None
    buf = io.StringIO()
    writer = csv.writer(buf)
    for r in rows:
        writer.writerow(["" if v is None else v for v in r.values()])
    per_row = len(buf.getvalue().encode("utf-8")) / len(rows)
    return per_row * 1.1


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
) -> Optional[FetchOutcome]:
    """Datastore export for one resource, streamed to `dest` as UTF-8 CSV.

    Pages datastore_search host-side (same source of truth the agent would
    query); `_id` is dropped, field order follows the datastore schema.
    A full export that crosses `max_bytes` mid-stream retries in sample
    mode instead of discarding everything. Sampling (when
    `sample_target_rows` > 0) fetches deterministic contiguous blocks:
    the head page plus pages at fixed strides — verbatim datastore output,
    recipe recorded in `sample_note`. Returns None when nothing could or
    should be written (dest is removed); callers treat None as "run the
    session the old way".
    """
    if not resource_id or total <= 0 or max_bytes <= 0:
        return None

    def _walk(offsets: list[int], sequential: bool) -> tuple[int, int]:
        with open(dest, "wb") as f:
            w = _CsvStreamWriter(f, max_bytes)
            if sequential:
                offset = 0
                while offset < total:
                    if time.monotonic() > deadline:
                        raise TimeoutError("prefetch wall budget exceeded")
                    fields, records = _fetch_page(
                        resource_id, offset, page_size, page_timeout_s
                    )
                    if not records:
                        break
                    w.write_page(fields, records)
                    offset += len(records)
            else:
                for offset in offsets:
                    if time.monotonic() > deadline:
                        raise TimeoutError("prefetch wall budget exceeded")
                    fields, records = _fetch_page(
                        resource_id, offset, page_size, page_timeout_s
                    )
                    if records:
                        w.write_page(fields, records)
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
            log.info(
                "data prefetch %s: byte cap crossed mid-fetch — retrying as sample",
                resource_id[:8],
            )
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


def prefetch_dataset(
    resources: Optional[list], cache_dir: Path
) -> list[PrefetchedResource]:
    """Host-side prefetch for a whole dataset: schema previews + data files.

    Selects the datastore-active resources (primary first, format twins
    deduped — `services.shared.resources.select_prefetch_resources`),
    all such resources by default (DATA_PREFETCH_MULTI, default true;
    set it false to restrict to the primary), and
    exports each under a shared wall deadline and a per-dataset
    DATA_PREFETCH_TOTAL_BYTES budget. Runs once per source; callers reuse
    the returned files across every session attempt.

    `ResourceRestrictedError` propagates only for the PRIMARY resource
    (the dataset genuinely has no accessible data → mark `restricted`);
    a 403 on a secondary resource just drops that resource.
    """
    from services.shared.resources import select_prefetch_resources

    selected = select_prefetch_resources(resources or [])
    if not selected:
        return []
    if not _env_bool("DATA_PREFETCH_MULTI", True):
        selected = selected[:1]

    cap_records = data_prefetch_max_records()
    max_bytes = _env_int("DATA_PREFETCH_MAX_BYTES", _DATA_PREFETCH_DEFAULT_MAX_BYTES)
    budget = _env_int("DATA_PREFETCH_TOTAL_BYTES", _DATA_PREFETCH_DEFAULT_TOTAL_BYTES)
    page_size = _env_int("DATA_PREFETCH_PAGE_SIZE", _DATA_PREFETCH_DEFAULT_PAGE_SIZE)
    sample_rows = _env_int(
        "DATA_PREFETCH_SAMPLE_ROWS", _DATA_PREFETCH_DEFAULT_SAMPLE_ROWS
    )
    wall = _env_float(
        "DATA_PREFETCH_WALL_BUDGET_S", _DATA_PREFETCH_DEFAULT_WALL_BUDGET_S
    )
    deadline = time.monotonic() + wall

    cache_dir.mkdir(parents=True, exist_ok=True)
    out: list[PrefetchedResource] = []
    remaining = budget
    for i, res in enumerate(selected):
        rid = res["id"]
        is_primary = i == 0
        try:
            preview = fetch_resource_preview(rid)
        except ResourceRestrictedError:
            if is_primary:
                raise
            log.warning(
                "prefetch: secondary resource %s is restricted — skipping", rid[:8]
            )
            continue
        if preview is None:
            continue
        total = int(preview.get("total") or 0)
        entry = PrefetchedResource(
            resource_id=rid,
            name=res.get("name") or "",
            format=res.get("format") or "",
            total=total,
            schema=preview,
        )
        if cap_records <= 0 or total <= 0 or remaining <= 0:
            out.append(entry)
            continue
        res_max_bytes = min(max_bytes, remaining)
        est = _estimate_bytes_per_row(preview)
        prefer_sample = total > cap_records or (
            est is not None and est * total > res_max_bytes
        )
        fname = f"data_{len(out) + 1}.csv"
        outcome = fetch_resource_records_to_file(
            rid,
            total,
            cache_dir / fname,
            max_bytes=res_max_bytes,
            page_size=page_size,
            page_timeout_s=_DATA_PREFETCH_PAGE_TIMEOUT_S,
            deadline=deadline,
            sample_target_rows=sample_rows,
            prefer_sample=prefer_sample,
        )
        if outcome is not None:
            entry.sandbox_filename = fname
            entry.host_path = cache_dir / fname
            entry.rows = outcome.rows
            entry.mode = outcome.mode
            entry.sample_note = outcome.sample_note
            remaining -= outcome.bytes
        out.append(entry)
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


def _render_schemas_block(files: list[PrefetchedResource]) -> str:
    """Compact per-file schema JSON, capped at _SCHEMAS_BLOCK_CAP bytes by
    progressively dropping sample rows (fields + total always survive)."""
    schemas = {}
    for p in files:
        if not p.schema:
            continue
        s = dict(p.schema)
        # The CSV drops _id — keep the advertised fields in sync.
        s["fields"] = [f for f in (s.get("fields") or []) if f.get("id") != "_id"]
        schemas[p.sandbox_filename] = s

    def _dump() -> str:
        return json.dumps(schemas, ensure_ascii=False, separators=(",", ":"))

    serialized = _dump()
    while len(serialized.encode("utf-8")) > _SCHEMAS_BLOCK_CAP:
        victim = max(
            schemas.values(), key=lambda s: len(s.get("sample_rows") or [])
        )
        if not victim.get("sample_rows"):
            break
        victim["sample_rows"] = victim["sample_rows"][:-1]
        serialized = _dump()
    return serialized


def _render_prefetch_blocks(
    prefetched: Sequence[PrefetchedResource],
    data_dir: Optional[str],
    pre_fetched_schema: Optional[dict],
) -> str:
    """The pre_fetched_files manifest (or the legacy schema block when no
    file was provisioned)."""
    files = [p for p in prefetched if p.host_path and p.sandbox_filename]
    listed_only = [p for p in prefetched if not p.host_path]

    if not files:
        # Legacy path: schema-only prefetch (or nothing).
        schema = pre_fetched_schema or (
            prefetched[0].schema if prefetched else None
        )
        if not schema:
            return ""
        schema_json = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        return (
            "\n\npre_fetched_schema (already retrieved host-side from "
            "datastore_search; SKIP package_show + the schema-discovery "
            "datastore_search call — go straight to aggregations):\n"
            f"```json\n{schema_json}\n```"
        )

    dd = (data_dir or "").rstrip("/")
    lines: list[str] = []
    for n, p in enumerate(files, 1):
        label = ", primary" if n == 1 else ""
        if p.mode == "full":
            lines.append(
                f"  {n}. {p.sandbox_filename} — \"{p.name or p.resource_id}\" "
                f"(resource {p.resource_id}{label}) — FULL, {p.rows:,} rows"
            )
        else:
            lines.append(
                f"  {n}. {p.sandbox_filename} — \"{p.name or p.resource_id}\" "
                f"(resource {p.resource_id}{label}) — SAMPLE: {p.rows:,} of "
                f"{p.total:,} rows (deterministic; {p.sample_note}). The TRUE "
                f"total is {p.total:,} — cite that, never the sample row "
                "count. Any figure aggregated from this sample must disclose "
                "the sampling in Hebrew on the chart/text, or be verified "
                "with exact filtered limit=0 datastore_search counts."
            )
    for p in listed_only:
        lines.append(
            f"  -  \"{p.name or p.resource_id}\" (resource {p.resource_id}) — "
            f"NOT provisioned ({p.total:,} rows); query it via "
            "datastore_search with filters/limits if it matters to the page."
        )
    manifest = "\n".join(lines)
    return (
        f"\n\npre_fetched_files: the datastore exports below are already "
        f"saved under {dd}/ (UTF-8 CSV, header row, verbatim "
        "datastore_search output — CHART-DATA PROVENANCE is satisfied by "
        "aggregating these files). Analyze ALL of them locally with python — "
        "pandas is preinstalled, no pip install needed — and do NOT "
        "re-download or paginate datastore_search for resources marked "
        "FULL. Query CKAN only for spot-checks, exact sample verifications, "
        "or resources not provisioned here.\n"
        f"{manifest}\n"
        "per-file schemas (fields, true total, sample rows):\n"
        f"```json\n{_render_schemas_block(files)}\n```"
    )


def _render_related_block(related_candidates: Sequence[dict]) -> str:
    """Same-ministry datasets from our own Firestore index, so the agent
    picks related_ids from a list instead of burning 3-5 CKAN
    package_search rounds rediscovering them."""
    if not related_candidates:
        return ""
    lines = []
    for c in related_candidates[:15]:
        tags = ", ".join((c.get("tags") or [])[:4])
        tag_part = f" [tags: {tags}]" if tags else ""
        lines.append(f"  {c['id']} — \"{(c.get('title') or '')[:80]}\"{tag_part}")
    return (
        "\n\nrelated_candidates (same ministry, from the project's own "
        "index; pick related_ids from these — do NOT query CKAN "
        "package_search for related datasets; return [] if none genuinely "
        "relate):\n" + "\n".join(lines)
    )


def build_user_message(
    *,
    dataset_id: str,
    title: str,
    notes: str,
    org_title: str,
    primary_resource_id: Optional[str],
    outputs_dir: str,
    check_script: str,
    pre_fetched_schema: Optional[dict] = None,
    prefetched: Sequence[PrefetchedResource] = (),
    data_dir: Optional[str] = None,
    previous_failure: Optional[str] = None,
    related_candidates: Sequence[dict] = (),
) -> str:
    resource_line = (
        f"primary_resource_id: {primary_resource_id}"
        if primary_resource_id
        else "primary_resource_id: (not pre-identified — pick one from package_show)"
    )
    od = outputs_dir.rstrip("/")
    data_block = _render_prefetch_blocks(prefetched, data_dir, pre_fetched_schema)
    related_block = _render_related_block(related_candidates)
    failure_block = ""
    if previous_failure:
        failure_block = (
            "\n\nprevious_attempt_failure: an earlier attempt for this "
            "dataset (fresh workdir; its outputs were discarded) failed "
            f"validation with:\n  {previous_failure.strip()}\n"
            "Avoid repeating that mistake."
        )
    return (
        "Build the landing page for this CKAN dataset. Write content.html "
        "(body fragment only — no <html>/<head>/<body>) and agent_data.json "
        f"to OUTPUTS_DIR, following the system prompt. All "
        "user-visible text in content.html must be Hebrew; your reasoning "
        "and bash commands can (and should) stay in English.\n\n"
        f"dataset_id: {dataset_id}\n"
        f"title (he): {title}\n"
        f"organization (he): {org_title or '(unknown)'}\n"
        f"description (he): {(notes or '(none)')[:1500]}\n"
        f"{resource_line}\n"
        f"OUTPUTS_DIR: {od}\n"
        f"CHECK_SCRIPT: {check_script}"
        f"{data_block}"
        f"{related_block}"
        f"{failure_block}\n\n"
        "Begin by investigating the dataset. Keep working until both "
        "files are written and the CHECK_SCRIPT self-check passes — only "
        "then end your turn, replying with a one-sentence summary of the "
        "page (never an empty message)."
    )


