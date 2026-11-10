"""CKAN API settings shared by the scanner and the builder."""
from __future__ import annotations

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
