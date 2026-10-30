"""Weekly reconcile sweep — detect datasets removed upstream (data.gov.il,
or a provider source's own origin).

Dead datasets vanish from CKAN's public list, so the scanner's
`iter_all_packages` never revisits them. This sweep actively probes every
already-published source (succeeded + unavailable) and flips its flag:

  - probe "gone" (HTTP 403) + currently succeeded → mark `unavailable`
    (page preserved, archive banner). Already-unavailable stays put.
  - probe "alive" + currently unavailable → self-heal to `succeeded`.
  - probe "unknown" (404 / 5xx / transient) → leave unchanged.

Scheduling (the weekday gate + env knob) lives in the pipeline caller, not
here — this function just does one full sweep when invoked.
"""
from __future__ import annotations

import asyncio
import logging

from services.providers import provider_for_key
from services.shared.firestore import FirestoreStateStore, SourceRecord
from services.shared.resources import pick_primary_resource_id

log = logging.getLogger("page_builder.reconcile")


async def probe_one(client, src: SourceRecord, providers=None) -> str:
    """Resolve one source to "gone"|"alive"|"unknown". Prefers the primary
    datastore resource; falls back to the package probe when there's no
    primary resource id or the resource probe is inconclusive.

    A provider source (services/providers) is asked of its own provider —
    never of CKAN, whose 403 would wrongly mark it removed. A disabled
    provider is "unknown" (no change)."""
    if getattr(src, "provider", None):
        p = provider_for_key(src.provider, providers)
        if p is None:
            return "unknown"
        return await asyncio.to_thread(p.probe_available, src.resources)
    rid = pick_primary_resource_id(src.resources)
    if rid:
        status = await client.probe_resource(rid)
        if status != "unknown":
            return status
    return await client.probe_package(src.id)


async def reconcile_sources(
    store: FirestoreStateStore,
    client,
    *,
    concurrency: int = 4,
    providers=None,
) -> dict:
    sources = list(store.iter_publishable_sources())
    log.info("reconcile: probing %d publishable source(s)", len(sources))
    sem = asyncio.Semaphore(concurrency)
    marked: list[str] = []
    recovered: list[str] = []

    async def _check(src: SourceRecord) -> None:
        async with sem:
            status = await probe_one(client, src, providers)
        if status == "gone" and src.analysis_status == "succeeded":
            await asyncio.to_thread(
                store.mark_source_unavailable,
                src.id,
                "reconcile: datastore probe returned gone",
            )
            marked.append(src.id)
            log.warning("reconcile: %s removed upstream → unavailable", src.id)
        elif status == "alive" and src.analysis_status == "unavailable":
            await asyncio.to_thread(store.clear_source_unavailable, src.id)
            recovered.append(src.id)
            log.info("reconcile: %s reachable again → succeeded", src.id)

    await asyncio.gather(*[_check(s) for s in sources])
    return {
        "checked": len(sources),
        "marked_unavailable": marked,
        "recovered": recovered,
    }
