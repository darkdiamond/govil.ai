"""The provider "scanner": `recipes/<id>/source.json` → `sources/<id>`.

Runs in the daily job after the recipe list loads and before the refresh.
For every recipe whose dir carries a source.json, the provider downloads the
data (cached for the refresh that follows), hashes it, and upserts the
source doc. `metadata_modified` moves only when a resource's content hash
changed — that is the version the refresh's `needs_refresh` compares, the
same field the CKAN scanner writes.

Never raises for one dataset: a bad config or a failed download leaves that
doc untouched (its last-good page stays live) and is reported in the summary.
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional

from services.shared.slug import slugify

from .base import ProviderError, SourceProvider
from .registry import enabled_providers

log = logging.getLogger("providers.sync")


def sync_provider_sources(
    store,
    repo,
    *,
    providers: Optional[Mapping[str, SourceProvider]] = None,
    only_ids: Optional[list[str]] = None,
) -> dict:
    providers = enabled_providers() if providers is None else providers
    summary: dict = {"synced": [], "changed": [], "skipped": [], "failed": []}
    if not providers:
        return summary  # nothing enabled: no repo reads, no downloads
    ids = repo.provider_source_ids()
    if only_ids is not None:
        ids = [i for i in ids if i in set(only_ids)]
    for dataset_id in ids:
        try:
            source = repo.source_config(dataset_id)
        except Exception as e:
            log.warning("provider sync %s: invalid source.json: %s", dataset_id, e)
            summary["failed"].append({"id": dataset_id, "reason": "invalid_config", "error": str(e)[:300]})
            continue
        p = providers.get(source.provider)
        if p is None:
            summary["skipped"].append({"id": dataset_id, "reason": f"provider_disabled:{source.provider}"})
            continue
        if not p.healthy():
            summary["skipped"].append({"id": dataset_id, "reason": f"provider_unhealthy:{p.key}"})
            continue
        try:
            cfg = p.parse_config(dataset_id, source)
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
        except (ProviderError, ValueError) as e:  # pydantic ValidationError is a ValueError
            log.warning("provider sync %s failed: %s", dataset_id, e)
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
