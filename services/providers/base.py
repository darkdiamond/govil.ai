"""The provider contract — how a non-CKAN source becomes a recipe'd dataset.

data.gov.il (CKAN) is the default and needs no provider: the scanner writes
its `sources/<id>` docs and the refresh reads its datastore. Every other
source is a `SourceProvider` subclass, instantiated once per job from its
own `ProviderSettings` (env `PROVIDER_<KEY>_*`). A provider owns everything
that differs between sources:

    ids          `id_prefix` — every dataset id it owns starts with it
    config       `DatasetConfig` — validates `recipes/<id>/source.json`["config"]
    facts        title / org / license / resources the scanner writes for CKAN
    presentation how the page shell credits it (`SourcePresentation`)
    data         `download()` one resource as normalized CSV bytes
    versions     `version()` — content hash, unless the source has a cheaper
                 change signal; `listing_key()` lets the sync skip even that
    liveness     `probe_available()` for the weekly reconcile sweep
    authoring    `brief_section()` / `authoring_notes()` for BRIEF.md

Downstream of the CSV everything is shared: compute() sandbox, page-model
validation, template, sanitizer, check.py, staging, publisher, frontend.
"""
from __future__ import annotations

import abc
import csv
import hashlib
import io
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.shared.fetch_types import FetchLimitExceeded, FetchOutcome

log = logging.getLogger("providers")

SOURCE_CONFIG_FILENAME = "source.json"
PREVIEW_SAMPLE_ROWS = 5
_WIRE_HEADERS = frozenset({"content-encoding", "content-length", "transfer-encoding"})


class ProviderError(Exception):
    """A provider couldn't produce what was asked (config, network, data)."""


class ProviderUnavailable(ProviderError):
    """The provider's healthcheck failed this run: the source is down, so
    nothing is fetched from it. Raised by `fetch_fns`; the refresh records the
    source as skipped (no state write, no strike), as the sync does."""


class ProviderTooLarge(FetchLimitExceeded, ProviderError):
    """A series over the provider's own `max_bytes`, raised by preview and
    fetch (not by `version`, so the sync still moves the doc). The refresh
    maps it to `too_large`, like a CKAN export over its cap; it is also a
    ProviderError for callers that handle any provider failure."""

    def __init__(self, message: str):
        super().__init__("bytes", message)


class ProviderSettings(BaseModel):
    """Per-provider knobs. Code defaults live on the class
    (`SourceProvider.default_settings`); env `PROVIDER_<KEY>_<FIELD>`
    overrides any field, e.g. `PROVIDER_BOI_SDMX_ENABLED=true`."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    base_url: str = ""
    timeout_s: float = 60.0
    retries: int = 2
    # TCP connect only. From Cloud Run, SYNs to some hosts are dropped at
    # random (BoI 2026-11: ~half of connects stalled, up to ~135s, before the
    # kernel's retransmit got through). A short connect timeout plus a fresh
    # connect beats waiting out the backoff. `connect_retries` covers those
    # stalls and pooled sockets the server dropped, and doesn't spend `retries`.
    connect_timeout_s: float = 10.0
    connect_retries: int = 5
    min_interval_s: float = 0.0
    max_bytes: int = 300_000_000
    # How long the sync may trust `listing_key()` (see there) before it
    # downloads and hashes everything again anyway. 0 = always download.
    listing_recheck_days: float = 7.0
    user_agent: str = "govil.ai-builder (+https://govil.ai)"

    @classmethod
    def from_env(
        cls, key: str, defaults: ProviderSettings, environ: Mapping[str, str] = os.environ
    ) -> ProviderSettings:
        prefix = f"PROVIDER_{key.upper()}_"
        values = defaults.model_dump()
        for name in cls.model_fields:
            raw = environ.get(prefix + name.upper())
            if raw is not None and raw.strip() != "":
                values[name] = raw.strip()
        return cls.model_validate(values)


class SourcePresentation(BaseModel):
    """How the page shell credits the source. Stored on the source doc and
    copied into data.json, so the publisher and frontend need no provider code."""

    model_config = ConfigDict(extra="forbid")

    source_name_he: str
    home_url: str
    terms_url: str | None = None
    attribution_he: str
    download_label_he: str = "הורדה"
    # The shell's live data explorer reads the CKAN datastore — CKAN only.
    explorer: bool = False


class SourceConfig(BaseModel):
    """`recipes/<id>/source.json`. Facts common to every provider; `config`
    is the provider's own block, validated by its `DatasetConfig`."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    title: str = Field(min_length=1)
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)
    update_frequency: str | None = None
    # Rendered as a link on the page: https only (no javascript:, data:, …).
    source_url: str | None = Field(None, pattern=r"^https://[^\s\"'<>]+$")
    config: dict = Field(default_factory=dict)


class ProviderDatasetConfig(BaseModel):
    """Base of every provider's `DatasetConfig`: no unknown keys, and the
    subclass's `resources` list holds unique ids."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [r.id for r in self.resources]
        if len(ids) != len(set(ids)):
            raise ValueError("resource ids must be unique")
        return self


class ProviderResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    format: str = "CSV"
    url: str  # public download URL — the page's download button
    params: dict = Field(default_factory=dict)  # what download() needs


class ProviderFacts(BaseModel):
    """What the scanner writes for a CKAN dataset, for a provider dataset."""

    model_config = ConfigDict(extra="forbid")

    title: str
    notes: str | None = None
    organization: dict
    license_title: str | None = None
    tags: list[str] = Field(default_factory=list)
    update_frequency: str | None = None
    source_url: str | None = None
    resources: list[ProviderResource] = Field(min_length=1)


@dataclass(frozen=True)
class ResourceVersion:
    hash: str
    size: int
    rows: int


Availability = Literal["alive", "gone", "unknown"]


def normalize_csv(data: bytes, sort_keys: tuple[str, ...] = (), *, count: bool = False):
    """UTF-8 (no BOM), `\\n` line ends, rows sorted by `sort_keys` (then the
    whole row) — so the same data always hashes the same (check B). With
    `count`, returns `(bytes, data row count)`."""
    text = data.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows:
        raise ProviderError("empty response (no CSV header)")
    header, body = rows[0], [r for r in rows[1:] if r]
    idx = [header.index(k) for k in sort_keys if k in header]
    body.sort(key=lambda r: (tuple(r[i] if i < len(r) else "" for i in idx), r))
    out = io.StringIO(newline="")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    w.writerows(body)
    encoded = out.getvalue().encode("utf-8")
    return (encoded, len(body)) if count else encoded


def _csv_head(data: bytes, n: int) -> tuple[list[str], list[list[str]]]:
    """Header and the first `n` rows, without parsing the rest."""
    reader = csv.reader(io.StringIO(data.decode("utf-8"), newline=""))
    header = next(reader, [])
    return header, [r for _, r in zip(range(n), reader, strict=False)]


class SourceProvider(abc.ABC):
    key: ClassVar[str]  # stored as sources/<id>.provider; env prefix
    id_prefix: ClassVar[str]  # every dataset id this provider owns starts with it
    label: ClassVar[str]  # human name (logs, BRIEF.md)
    DatasetConfig: ClassVar[type[BaseModel]]
    default_settings: ClassVar[ProviderSettings]
    # CSV columns that identify a row, for a stable sort (see normalize_csv).
    sort_keys: ClassVar[tuple[str, ...]] = ()

    def __init__(self, settings: ProviderSettings):
        self.settings = settings
        # _cache_key → (normalized CSV, data row count), for one run.
        self._cache: dict[str, tuple[bytes, int]] = {}
        self._last_request = 0.0
        self._healthy: bool | None = None
        # The reconcile sweep probes from several threads at once; politeness
        # spacing and the one-per-run healthcheck must hold across them.
        self._lock = threading.RLock()  # healthy() → healthcheck() → http_get()
        # One keep-alive pool for the run, so a run pays for a few TCP
        # connects instead of one per request. httpx.Client is thread-safe.
        self._client: httpx.Client | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> SourceProvider:
        return cls(ProviderSettings.from_env(cls.key, cls.default_settings, environ))

    # ── config + facts ───────────────────────────────────────────────────

    def parse_config(self, dataset_id: str, source: SourceConfig) -> BaseModel:
        if source.provider != self.key:
            raise ProviderError(f"{dataset_id}: source.json is for {source.provider!r}")
        if not dataset_id.startswith(self.id_prefix) or dataset_id == self.id_prefix:
            raise ProviderError(
                f"{dataset_id}: {self.key} dataset ids must start with {self.id_prefix!r}"
            )
        return self.DatasetConfig.model_validate(source.config)

    @abc.abstractmethod
    def facts(self, dataset_id: str, source: SourceConfig, cfg: BaseModel) -> ProviderFacts:
        ...

    @abc.abstractmethod
    def presentation(self) -> SourcePresentation:
        ...

    def page_slug_suffix(self, dataset_id: str) -> str:
        """The id part of /datasets/<hebrew-title>-<suffix>/ (CKAN uses 8 hex
        chars of its UUID; a readable suffix is unique within the prefix)."""
        return dataset_id[len(self.id_prefix):]

    # ── data ─────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def download(self, resource: dict) -> bytes:
        """One resource (a `ProviderResource` dict as stored on the source
        doc) in full, as raw CSV bytes. Raise ProviderError on failure."""

    def _cache_key(self, resource: dict) -> str:
        """What tells two resources' downloads apart (default: the URL). A
        provider whose URL doesn't carry every download parameter adds them."""
        return resource["url"]

    def _cached(self, resource: dict) -> tuple[bytes, int]:
        """Normalized CSV and its row count, downloaded once per run: the sync
        step's version probe and the refresh share it.

        A reply the parsing can't read (a null where a number goes, a string
        where an object goes, a non-UTF-8 byte, a missing key, a CSV the reader
        refuses) is a ProviderError like any other provider failure, so
        preview/fetch turn it into a strike that escalates instead of a bare
        exception the refresh only logs."""
        key = self._cache_key(resource)
        if key not in self._cache:
            try:
                self._cache[key] = normalize_csv(self.download(resource), self.sort_keys,
                                                 count=True)
            except (ValueError, KeyError, TypeError, IndexError,  # incl. UnicodeDecodeError
                    AttributeError, csv.Error) as e:
                raise ProviderError(f"{resource.get('id')}: unreadable answer from {self.key} "
                                    f"({type(e).__name__}: {e})") from e
        return self._cache[key]

    def _capped(self, resource: dict) -> tuple[bytes, int]:
        """`_cached`, refused over the provider's `max_bytes`. `version` reads
        uncapped, so a series that outgrew the cap still moves its version,
        and the refresh it triggers reports `too_large` instead of the page
        going stale unnoticed."""
        data, rows = self._cached(resource)
        if len(data) > self.settings.max_bytes:
            raise ProviderTooLarge(
                f"{resource['id']}: {len(data):,} bytes > max_bytes "
                f"{self.settings.max_bytes:,}"
            )
        return data, rows

    def clear_cache(self) -> None:
        self._cache.clear()

    def listing_key(self, dataset_id: str, source: SourceConfig, cfg: BaseModel) -> str | None:
        """A cheap fingerprint of everything the dataset's facts and CSVs are
        built from, or None (the default) when the source has none.

        When it equals the key stored by the last full sync, and that sync is
        younger than `settings.listing_recheck_days`, the sync skips `facts()`
        and every download: the stored resources and hashes stand. So the key
        must change whenever the output could, except for edits the source
        makes in place, which the periodic full check catches."""
        return None

    def version(self, resource: dict) -> ResourceVersion:
        data, rows = self._cached(resource)
        return ResourceVersion(hashlib.sha256(data).hexdigest(), len(data), rows)

    def preview(self, resource: dict) -> dict | None:
        """None on a failed download; ProviderTooLarge passes through."""
        try:
            data, rows = self._capped(resource)
        except ProviderTooLarge:
            raise
        except ProviderError as e:
            log.warning("%s preview %s failed: %s", self.key, resource["id"], e)
            return None
        header, sample = _csv_head(data, PREVIEW_SAMPLE_ROWS)
        return {
            "fields": [{"id": c, "type": "text"} for c in header],
            "total": rows,
            "sample_rows": [dict(zip(header, r, strict=False)) for r in sample],
        }

    def fetch_to_file(self, resource: dict, dest: Path, *, max_bytes: int) -> FetchOutcome | None:
        try:
            data, rows = self._capped(resource)
        except ProviderTooLarge:
            raise
        except ProviderError as e:
            log.warning("%s fetch %s failed: %s", self.key, resource["id"], e)
            return None
        if len(data) > max_bytes:
            raise ProviderTooLarge(f"{resource['id']}: {len(data):,} bytes > cap {max_bytes:,}")
        Path(dest).write_bytes(data)
        return FetchOutcome(rows=rows, bytes=len(data))

    def fetch_fns(self, resources: list[dict]) -> tuple[Callable, Callable]:
        """`(preview_fn, fetch_fn)` with the signatures `refresh.fetch_inputs`
        takes, bound to a source doc's resources (resource id → params).
        Raises ProviderUnavailable when the provider's healthcheck failed: a
        fetch during an outage would only count strikes toward a false
        `schema_changed` issue."""
        if not self.healthy():
            raise ProviderUnavailable(f"{self.key}: healthcheck failed this run")
        by_id = {r["id"]: r for r in resources}

        def preview_fn(rid: str) -> dict | None:
            return self.preview(by_id[rid]) if rid in by_id else None

        def fetch_fn(rid, total, dest, *, max_bytes, **_kw) -> FetchOutcome | None:
            return self.fetch_to_file(by_id[rid], dest, max_bytes=max_bytes) if rid in by_id else None

        return preview_fn, fetch_fn

    # ── liveness ─────────────────────────────────────────────────────────

    def healthcheck(self) -> bool:
        """Is the source answering at all? Checked once per run before any
        dataset is synced or probed. Default: assume yes."""
        return True

    def healthy(self) -> bool:
        with self._lock:
            if self._healthy is None:
                try:
                    self._healthy = bool(self.healthcheck())
                except Exception:
                    log.exception("%s healthcheck crashed", self.key)
                    self._healthy = False
                if not self._healthy:
                    log.warning("%s: healthcheck failed — provider skipped this run", self.key)
            return self._healthy

    def probe_available(self, resources: list[dict]) -> Availability:
        """For the reconcile sweep: "gone" only on a definite answer that the
        data was removed; anything uncertain is "unknown" (no change)."""
        return "unknown"

    # ── authoring ────────────────────────────────────────────────────────

    def brief_section(self, resource: dict, csv_path: Path) -> str:
        return ""

    def authoring_notes(self) -> str:
        return ""

    # ── HTTP ─────────────────────────────────────────────────────────────

    def http_get(self, url: str, *, params: dict | None = None,
                 headers: dict | None = None,
                 max_bytes: int | None = None) -> httpx.Response:
        """GET with the provider's timeout, politeness interval and retries
        (on transport errors and 5xx/429). Any other status comes back to the
        caller as is. A body past `max_bytes`
        (default twice `settings.max_bytes`, so a series just over the cap
        still downloads and `version` still moves) raises ProviderTooLarge."""
        headers = {"User-Agent": self.settings.user_agent, **(headers or {})}
        if max_bytes is None:
            max_bytes = 2 * self.settings.max_bytes
        last: Exception | None = None
        attempt = connect_stalls = 0
        while True:
            with self._lock:  # reserve the next slot, then sleep outside the lock
                slot = max(time.monotonic(), self._last_request + self.settings.min_interval_s)
                self._last_request = slot
            if slot > time.monotonic():
                time.sleep(slot - time.monotonic())
            try:
                r = self._send(url, params=params, headers=headers, max_bytes=max_bytes)
            # A stalled connect, or a pooled keep-alive socket the server closed
            # just as we reused it: reconnect at once, without backoff.
            except (httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                last = e
                if connect_stalls < self.settings.connect_retries:
                    connect_stalls += 1
                    log.info("provider %s: %s to %s (%s), reconnecting (%d/%d)",
                             self.key, type(e).__name__, httpx.URL(url).host, e,
                             connect_stalls, self.settings.connect_retries)
                    continue
            except httpx.HTTPError as e:
                last = e
            else:
                if not (r.status_code >= 500 or r.status_code == 429):
                    return r
                last = ProviderError(f"HTTP {r.status_code}")
            if attempt >= self.settings.retries:
                break
            time.sleep(2 ** attempt)
            attempt += 1
        raise ProviderError(f"GET {url} failed after {attempt + 1 + connect_stalls} "
                            f"attempts: {last}")

    def get_json(self, url: str, *, source: str, headers: dict | None = None):
        """`http_get` + JSON parse: a status other than 200 or a body that
        isn't JSON is a ProviderError naming `source` and the URL."""
        r = self.http_get(url, headers=headers)
        if r.status_code != 200:
            raise ProviderError(f"HTTP {r.status_code} from {source} for {url[:160]}")
        try:
            return r.json()
        except ValueError as e:
            raise ProviderError(f"{source} answered non-JSON for {url[:160]}: {e}") from e

    def _send(self, url: str, *, max_bytes: int, **kw) -> httpx.Response:
        """One GET on the shared client (the seam tests replace). The body is
        read in chunks and refused once it passes `max_bytes`, whatever the
        server says its length is. Returns a fresh, already-read Response
        holding the decoded body, so .content/.text/.json() work after the
        stream is closed (public httpx API only)."""
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    timeout=httpx.Timeout(self.settings.timeout_s,
                                          connect=self.settings.connect_timeout_s),
                    follow_redirects=True)
        with self._client.stream("GET", url, **kw) as r:
            chunks, size = [], 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ProviderTooLarge(
                        f"GET {httpx.URL(url).host}: body over {max_bytes:,} bytes")
                chunks.append(chunk)
        # iter_bytes() already undid any Content-Encoding: drop the headers
        # that describe the wire form, or the new Response would decode again.
        headers = [(k, v) for k, v in r.headers.multi_items()
                   if k.lower() not in _WIRE_HEADERS]
        return httpx.Response(r.status_code, headers=headers, content=b"".join(chunks),
                              request=r.request)
