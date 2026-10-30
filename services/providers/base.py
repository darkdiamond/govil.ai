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
                 change signal
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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ClassVar, Literal, Mapping, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field

from services.page_builder.agent_contract import FetchOutcome

log = logging.getLogger("providers")

SOURCE_CONFIG_FILENAME = "source.json"
PREVIEW_SAMPLE_ROWS = 5


class ProviderError(Exception):
    """A provider couldn't produce what was asked (config, network, data)."""


class ProviderSettings(BaseModel):
    """Per-provider knobs. Code defaults live on the class
    (`SourceProvider.default_settings`); env `PROVIDER_<KEY>_<FIELD>`
    overrides any field, e.g. `PROVIDER_BOI_SDMX_ENABLED=true`."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    base_url: str = ""
    timeout_s: float = 60.0
    retries: int = 2
    min_interval_s: float = 0.0
    max_bytes: int = 300_000_000
    # Name of the env var holding the source's API key, if it needs one. Read
    # on the host only; the compute sandbox's env is scrubbed regardless.
    secret_env: Optional[str] = None
    user_agent: str = "govil.ai-builder (+https://govil.ai)"

    @classmethod
    def from_env(
        cls, key: str, defaults: "ProviderSettings", environ: Mapping[str, str] = os.environ
    ) -> "ProviderSettings":
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
    terms_url: Optional[str] = None
    attribution_he: str
    download_label_he: str = "הורדה"
    # The shell's live data explorer reads the CKAN datastore — CKAN only.
    explorer: bool = False
    # Hosts a page fetches from in the browser (both CSP headers in
    # firebase.json must list them). Empty when pages embed their data.
    csp_connect_hosts: list[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    """`recipes/<id>/source.json`. Facts common to every provider; `config`
    is the provider's own block, validated by its `DatasetConfig`."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    title: str = Field(min_length=1)
    notes: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    update_frequency: Optional[str] = None
    # Rendered as a link on the page: https only (no javascript:, data:, …).
    source_url: Optional[str] = Field(None, pattern=r"^https://[^\s\"'<>]+$")
    config: dict = Field(default_factory=dict)


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
    notes: Optional[str] = None
    organization: dict
    license_title: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    update_frequency: Optional[str] = None
    source_url: Optional[str] = None
    resources: list[ProviderResource] = Field(min_length=1)


@dataclass(frozen=True)
class ResourceVersion:
    hash: str
    size: int
    rows: int


Availability = Literal["alive", "gone", "unknown"]


def normalize_csv(data: bytes, sort_keys: tuple[str, ...] = ()) -> bytes:
    """UTF-8 (no BOM), `\\n` line ends, rows sorted by `sort_keys` (then the
    whole row) — so the same data always hashes the same (check B)."""
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
    return out.getvalue().encode("utf-8")


def _csv_rows(data: bytes) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
    return (rows[0], rows[1:]) if rows else ([], [])


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
        self._cache: dict[str, bytes] = {}  # url → normalized CSV, for one run
        self._last_request = 0.0
        self._healthy: Optional[bool] = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "SourceProvider":
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

    def csv_bytes(self, resource: dict) -> bytes:
        """Normalized CSV, downloaded once per run: the sync step's version
        probe and the refresh share it."""
        url = resource["url"]
        if url not in self._cache:
            data = normalize_csv(self.download(resource), self.sort_keys)
            if len(data) > self.settings.max_bytes:
                raise ProviderError(
                    f"{resource['id']}: {len(data):,} bytes > max_bytes "
                    f"{self.settings.max_bytes:,}"
                )
            self._cache[url] = data
        return self._cache[url]

    def clear_cache(self) -> None:
        self._cache.clear()

    def version(self, resource: dict) -> ResourceVersion:
        data = self.csv_bytes(resource)
        _, body = _csv_rows(data)
        return ResourceVersion(hashlib.sha256(data).hexdigest(), len(data), len(body))

    def preview(self, resource: dict) -> Optional[dict]:
        try:
            header, body = _csv_rows(self.csv_bytes(resource))
        except ProviderError as e:
            log.warning("%s preview %s failed: %s", self.key, resource["id"], e)
            return None
        return {
            "fields": [{"id": c, "type": "text"} for c in header],
            "total": len(body),
            "sample_rows": [dict(zip(header, r, strict=False)) for r in body[:PREVIEW_SAMPLE_ROWS]],
        }

    def fetch_to_file(self, resource: dict, dest: Path, *, max_bytes: int) -> Optional[FetchOutcome]:
        try:
            data = self.csv_bytes(resource)
        except ProviderError as e:
            log.warning("%s fetch %s failed: %s", self.key, resource["id"], e)
            return None
        if len(data) > max_bytes:
            log.warning("%s fetch %s: %d bytes > cap %d", self.key, resource["id"],
                        len(data), max_bytes)
            return None
        Path(dest).write_bytes(data)
        _, body = _csv_rows(data)
        return FetchOutcome(rows=len(body), bytes=len(data), mode="full")

    def fetch_fns(self, resources: list[dict]) -> tuple[Callable, Callable]:
        """`(preview_fn, fetch_fn)` with the signatures `refresh.fetch_inputs`
        takes, bound to a source doc's resources (resource id → params)."""
        by_id = {r["id"]: r for r in resources}

        def preview_fn(rid: str) -> Optional[dict]:
            return self.preview(by_id[rid]) if rid in by_id else None

        def fetch_fn(rid, total, dest, *, max_bytes, **_kw) -> Optional[FetchOutcome]:
            return self.fetch_to_file(by_id[rid], dest, max_bytes=max_bytes) if rid in by_id else None

        return preview_fn, fetch_fn

    # ── liveness ─────────────────────────────────────────────────────────

    def healthcheck(self) -> bool:
        """Is the source answering at all? Checked once per run before any
        dataset is synced or probed. Default: assume yes."""
        return True

    def healthy(self) -> bool:
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

    def auth_headers(self) -> dict[str, str]:
        return {}

    def secret(self) -> Optional[str]:
        env = self.settings.secret_env
        return (os.environ.get(env) or "").strip() or None if env else None

    def http_get(self, url: str, *, params: Optional[dict] = None,
                 ok: tuple[int, ...] = (200,),
                 headers: Optional[dict] = None) -> httpx.Response:
        """GET with the provider's timeout, politeness interval and retries
        (on transport errors and 5xx/429). A status outside `ok` that isn't
        retryable comes back to the caller as is."""
        headers = {"User-Agent": self.settings.user_agent, **self.auth_headers(),
                   **(headers or {})}
        last: Optional[Exception] = None
        for attempt in range(self.settings.retries + 1):
            wait = self.settings.min_interval_s - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                r = httpx.get(url, params=params, headers=headers,
                              timeout=self.settings.timeout_s, follow_redirects=True)
            except httpx.HTTPError as e:
                last = e
            else:
                if r.status_code in ok or not (r.status_code >= 500 or r.status_code == 429):
                    return r
                last = ProviderError(f"HTTP {r.status_code}")
            if attempt < self.settings.retries:
                time.sleep(2 ** attempt)
        raise ProviderError(f"GET {url} failed after {self.settings.retries + 1} attempts: {last}")
