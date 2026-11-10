"""CKAN API settings shared by the scanner and the builder."""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

# data.gov.il's CKAN answers `include_total` on a large table with Postgres's
# planner estimate (`total_was_estimated: true`), which goes stale when a
# re-upload shrinks the table: 2026-11-05, 36bf1404 reported 161,025 rows
# while it held 125,718, so the file (125,718) was rejected as short and the
# datastore export failed as cut off at the same row. Above this
# `total_estimation_threshold` CKAN estimates; set past any table we read, it
# counts exactly (`count(*)`: +0.6s on a 4.2M-row table).
EXACT_TOTAL_THRESHOLD = 1_000_000_000


def is_authorization_error(payload: object) -> bool:
    """True when a CKAN JSON envelope carries an Authorization Error.

    CKAN reports a restricted or removed resource/package as `{"success":
    false, "error": {"__type": "Authorization Error", …}}`, usually with HTTP
    403 (rarely 200). A 403 without that body is something else: data.gov.il's
    WAF answers a refused User-Agent with its own HTML page.
    """
    if not isinstance(payload, dict):
        return False
    err = payload.get("error") or {}
    return isinstance(err, dict) and "Authorization" in str(err.get("__type") or "")


DATASTORE_SEARCH_URL = "https://data.gov.il/api/3/action/datastore_search"

# The WAF passes this UA on the API and on file downloads (2026-10-31: a bare
# `Mozilla/5.0`, curl's and python-requests' UAs all 403).
_BUILDER_UA = "Mozilla/5.0 (compatible; govdata-builder/1.0)"
# Tried on a file download when the WAF refuses the builder UA.
BROWSER_FALLBACK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def user_agent() -> str:
    """The User-Agent the builder sends to data.gov.il: `CKAN_USER_AGENT`, else
    the builder UA. Read on every call, so a WAF change is a job env fix, not a
    redeploy (and a test can set the env var without reloading a module)."""
    return os.environ.get("CKAN_USER_AGENT", "").strip() or _BUILDER_UA


_URL_IGNORED_CHARS_RE = re.compile(r"[\x00-\x20\x7f]")
_GATED_HOST_RE = re.compile(r"^https?://(?:aws-)?e\.data\.gov\.il/")
_LOCALE_PREFIX_RE = re.compile(r"^https://data\.gov\.il/(?:he|en)/(?=dataset/)")


def public_resource_url(url: str) -> str:
    """CKAN publishes resource URLs on `e.data.gov.il` / `aws-e.data.gov.il`,
    which sit behind an OAuth wall (Google IAP / AWS ALB) and redirect
    anonymous clients to a login screen. The same path on `data.gov.il` (no
    `e.` prefix) is publicly downloadable. Some URLs also carry a `/he/` or
    `/en/` locale prefix before `/dataset/`; data.gov.il routes those to its
    frontend's "page not found" screen, so drop it. Rewrite on ingest so any
    consumer of the Firestore `resources[]` list sees a URL that actually
    works in a browser. Mirrored by frontend/utils/resource-url.ts.

    Anything that isn't an absolute http(s) URL (`javascript:`, `data:`,
    `file:`, relative junk) becomes "" — CKAN fields are publisher-supplied,
    the URL lands in every download button's href, and the publisher
    already drops resources with an empty url. The scheme is judged with
    whitespace/control chars removed, as a browser would (`java\tscript:`).
    """
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    probe = _URL_IGNORED_CHARS_RE.sub("", url)
    parts = urlsplit(probe)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""
    url = _GATED_HOST_RE.sub("https://data.gov.il/", url)
    return _LOCALE_PREFIX_RE.sub("https://data.gov.il/", url)


def parse_ckan_datetime(value: str | None) -> datetime | None:
    """Parse datetime string from CKAN API. Always returns tz-aware UTC —
    CKAN frequently returns naive ISO timestamps (e.g. `2024-01-15T10:30:00`)
    that would be silently stored as UTC by Firestore and then come back
    tz-aware, breaking naive/aware comparisons on the next scan."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt
