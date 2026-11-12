"""The provider "scanner": `recipes/<id>/source.json` → `sources/<id>`.

Runs in the daily job after the recipe list loads and before the refresh.
For every recipe whose dir carries a source.json, the provider downloads the
data (cached for the refresh that follows), hashes it, and upserts the
source doc. `metadata_modified` moves only when a resource's content hash
changed — that is the version the refresh's `needs_refresh` compares, the
same field the CKAN scanner writes.

A provider with a cheap `listing_key()` (CBS) skips all of that while the key
matches the one its last full sync stored and that sync is younger than
`listing_recheck_days`: the doc is left as it is, with no download.

`PROVIDER_<KEY>_SYNC_HOURS` (Israel-time hours, e.g. `6,12,18`) limits a
provider's sync to those hourly ticks: in any other hour its datasets are
skipped before the healthcheck (no network call, docs untouched), so their
`metadata_modified` holds and the refresh has nothing new to fetch. Unset =
every run. A run for chosen ids (`--source`) ignores it.

Never raises for one dataset: a bad config or a failed download leaves that
doc untouched (its last-good page stays live) and is reported in the summary.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from services.shared.schedule import due_this_hour
from services.shared.slug import slugify

from .base import ProviderError, SourceProvider
from .registry import enabled_providers

log = logging.getLogger("providers.sync")


def sync_provider_sources(
    store,
    repo,
    *,
    providers: Mapping[str, SourceProvider] | None = None,
    only_ids: list[str] | None = None,
) -> dict:
    providers = enabled_providers() if providers is None else providers
    summary: dict = {"synced": [], "changed": [], "skipped": [], "failed": []}
    if not providers:
        return summary  # nothing enabled: no repo reads, no downloads
    ids = repo.provider_source_ids()
    if only_ids is not None:
        ids = [i for i in ids if i in set(only_ids)]
    due: dict[str, bool] = {}  # provider key → due this hour (asked once a run)
    for dataset_id in ids:
        try:
            source = repo.source_config(dataset_id)
            if source is None:
                raise FileNotFoundError("source.json disappeared since the recipe list was read")
        except Exception as e:  # noqa: BLE001
            log.warning("provider sync %s: invalid source.json: %s", dataset_id, e)
            summary["failed"].append({"id": dataset_id, "reason": "invalid_config", "error": str(e)[:300]})
            continue
        p = providers.get(source.provider)
        if p is None:
            summary["skipped"].append({"id": dataset_id, "reason": f"provider_disabled:{source.provider}"})
            continue
        if only_ids is None and not due.setdefault(p.key, _sync_due(p.key)):
            summary["skipped"].append({"id": dataset_id, "reason": f"provider_gated:{p.key}"})
            continue
        if not p.healthy():
            summary["skipped"].append({"id": dataset_id, "reason": f"provider_unhealthy:{p.key}"})
            continue
        try:
            cfg = p.parse_config(dataset_id, source)
            key = _listing_key(p, dataset_id, source, cfg)
            if key is not None and _trusted(store, dataset_id, key, p.settings.listing_recheck_days):
                summary["synced"].append(dataset_id)
                log.info("provider sync %s (%s): unchanged (listing key), no download",
                         dataset_id, p.key)
                continue
            facts = p.facts(dataset_id, source, cfg)
            resources = []
            for res in facts.resources:
                d = res.model_dump()
                v = p.version(d)
                resources.append({
                    "id": res.id, "name": res.name, "format": res.format, "url": res.url,
                    "size": v.size, "last_modified": None, "description": None,
                    # Firestore/data.json keep false: the browser explorer
                    # reads the CKAN datastore. The refresh treats provider
                    # resources as fetchable on its own (fetchable_resources).
                    "datastore_active": False,
                    "hash": v.hash, "rows": v.rows, "params": res.params,
                })
        except Exception as e:  # one dataset's failure never stops the others  # noqa: BLE001
            expected = isinstance(e, (ProviderError, ValueError))  # ValidationError is a ValueError
            (log.warning if expected else log.exception)("provider sync %s failed: %s", dataset_id, e)
            summary["failed"].append({"id": dataset_id, "reason": "provider_error", "error": str(e)[:300]})
            continue
        payload = {
            "title": facts.title,
            "name": dataset_id,
            "slug": slugify(facts.title, fallback=dataset_id),
            "notes": facts.notes,
            "organization": facts.organization,
            "license_title": facts.license_title,
            "update_frequency": facts.update_frequency,
            "tags": facts.tags,
            "resources": resources,
            "record_count": sum(r["rows"] for r in resources),
            "provider": p.key,
            "source_url": facts.source_url,
            "presentation": p.presentation().model_dump(),
            "page_slug_suffix": p.page_slug_suffix(dataset_id),
            "provider_listing_key": key,
            "provider_verified_at": datetime.now(UTC),
        }
        try:
            changed = store.save_provider_source(dataset_id, payload)
        except Exception as e:
            log.exception("provider sync %s: Firestore write failed", dataset_id)
            summary["failed"].append({"id": dataset_id, "reason": "store_error", "error": str(e)[:300]})
            continue
        summary["synced"].append(dataset_id)
        if changed:
            summary["changed"].append(dataset_id)
        log.info("provider sync %s (%s): %s, %d rows", dataset_id, p.key,
                 "changed" if changed else "unchanged", payload["record_count"])
    return summary


def sync_hours_env(key: str) -> str:
    return f"PROVIDER_{key.upper()}_SYNC_HOURS"


def _sync_due(key: str) -> bool:
    ok = due_this_hour(sync_hours_env(key))
    if not ok:
        log.info("provider sync: %s gated this hour (%s) — docs left as they are",
                 key, sync_hours_env(key))
    return ok


def _listing_key(p: SourceProvider, dataset_id: str, source, cfg) -> str | None:
    """The provider's key folded with everything else the doc is built from:
    source.json (title, tags, config…) and the provider's presentation."""
    k = p.listing_key(dataset_id, source, cfg)
    if k is None:
        return None
    extra = json.dumps([source.model_dump(mode="json"), p.presentation().model_dump(mode="json"),
                        p.page_slug_suffix(dataset_id)], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{p.key}\n{k}\n{extra}".encode()).hexdigest()


def _trusted(store, dataset_id: str, key: str, recheck_days: float) -> bool:
    """Whether the stored doc's last full sync used this key, recently enough."""
    if recheck_days <= 0:
        return False
    state = store.get_provider_sync_state(dataset_id)
    if not state or state.get("provider_listing_key") != key or not state.get("resources"):
        return False
    at = state.get("provider_verified_at")
    return isinstance(at, datetime) and datetime.now(UTC) - at < timedelta(days=recheck_days)
