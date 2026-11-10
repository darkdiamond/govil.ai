"""Fetch results and limit errors shared by the CKAN export
(`page_builder.ckan_export`), the source providers and the refresh.

One class object each: the refresh catches a provider's `ProviderTooLarge` as
`FetchLimitExceeded`, so providers must not define their own copy. Light at
import (stdlib only), so `services.providers` doesn't pull in page_builder.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


class ResourceRestrictedError(Exception):
    """The primary resource's CKAN datastore returns a 403 Authorization
    Error — the dataset's data is access-restricted upstream (private /
    de-listed). No real data page can be built, and the 403 is
    deterministic (retrying won't help), so the caller marks the source
    `restricted` instead of counting it as a transient failure."""


@dataclass
class FetchOutcome:
    rows: int
    bytes: int
    via: str | None = None        # "file" | "datastore" (fetch_resource_export)


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


class DownloadBlocked(Exception):
    """data.gov.il answered a file download with a 403 or an HTML page (the
    WAF's block page, or an OAuth login screen) instead of the file."""


@dataclass
class FileOutcome:
    bytes: int
    sha256: str
