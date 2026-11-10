"""Weekly reconcile sweep — detect datasets removed upstream (data.gov.il,
or a provider source's own origin).

Dead datasets vanish from CKAN's public list, so the scanner's
`iter_all_packages` never revisits them. This sweep actively probes every
already-published source (succeeded + unavailable) and flips its flag:

  - probe "gone" (HTTP 403 with CKAN's Authorization Error body) + currently
    succeeded → mark `unavailable` (page preserved, archive banner).
    Already-unavailable stays put.
  - probe "alive" + currently unavailable → self-heal to `succeeded`.
  - probe "blocked" (any other 403: the WAF) or "unknown" (404 / 5xx /
    transient) → leave unchanged.

Every source is probed before anything is written, and a sweep that would
mark more than RECONCILE_MAX_FLIPS pages removed (or saw that many blocked
probes) writes no removals at all: see `reconcile_sources`.

Scheduling (the weekday gate + env knob) lives in the pipeline caller, not
here — this function just does one full sweep when invoked.
"""
from __future__ import annotations

import asyncio
import logging
import os

from services.providers import provider_for_key
from services.shared.firestore import FirestoreStateStore, SourceRecord
from services.shared.resources import pick_primary_resource_id
from services.shared.states import AnalysisStatus

log = logging.getLogger("page_builder.reconcile")

# Most live pages one sweep may mark removed (RECONCILE_MAX_FLIPS overrides).
# Also the number of "blocked" probes that aborts the sweep.
DEFAULT_MAX_FLIPS = 20


async def probe_one(client, src: SourceRecord, providers=None) -> str:
    """Resolve one source to "gone"|"alive"|"blocked"|"unknown". Prefers the
    primary datastore resource; falls back to the package probe when there's
    no primary resource id or the resource probe is inconclusive ("unknown").
    "blocked" (a 403 that isn't CKAN's own Authorization Error, see
    `CKANClient._probe`) is returned as is: the package probe would only be
    blocked the same way.

    A provider source (services/providers) is asked of its own provider —
    never of CKAN, whose 403 would wrongly mark it removed. A disabled
    provider is "unknown" (no change)."""
    if src.provider:
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


def max_flips_from_env() -> int:
    try:
        return max(0, int(os.environ.get("RECONCILE_MAX_FLIPS", "") or DEFAULT_MAX_FLIPS))
    except ValueError:
        return DEFAULT_MAX_FLIPS


async def reconcile_sources(
    store: FirestoreStateStore,
    client,
    *,
    concurrency: int = 4,
    providers=None,
    max_flips: int | None = None,
) -> dict:
    """Probe every publishable source, then apply the flips.

    Two phases, so a sweep that looks wrong can stop before it writes: if
    more than `max_flips` live pages would be marked removed, or `max_flips`
    probes came back "blocked", nothing is marked (recoveries still apply)
    and the summary carries `aborted`; so does a sweep where `max_flips`
    probes raised. Real removals arrive a few a week; a
    burst means CKAN or its WAF is misbehaving, not that the site is gone.
    A probe that raises counts as "unknown" (and in `errors`)."""
    max_flips = max_flips_from_env() if max_flips is None else max_flips
    sources = list(store.iter_publishable_sources())
    log.info("reconcile: probing %d publishable source(s)", len(sources))
    sem = asyncio.Semaphore(concurrency)

    async def _probe(src: SourceRecord) -> str:
        async with sem:
            return await probe_one(client, src, providers)

    results = await asyncio.gather(*[_probe(s) for s in sources], return_exceptions=True)
    statuses: list[str] = []
    errors = 0
    for src, r in zip(sources, results, strict=True):
        if isinstance(r, BaseException):
            log.warning("reconcile: probing %s raised %r — unknown", src.id[:8], r)
            errors += 1
            r = "unknown"
        statuses.append(r)

    gone = [s for s, st in zip(sources, statuses, strict=True)
            if st == "gone" and s.analysis_status == AnalysisStatus.SUCCEEDED]
    back = [s for s, st in zip(sources, statuses, strict=True)
            if st == "alive" and s.analysis_status == AnalysisStatus.UNAVAILABLE]
    blocked = statuses.count("blocked")
    aborted = None
    if len(gone) > max_flips:
        aborted = "too_many_gone"
    elif max_flips and blocked >= max_flips:
        aborted = "too_many_blocked"
    elif max_flips and errors >= max_flips:
        # A probe that raises is a bug, not an answer: in bulk it must show
        # (a red run), not pass as a quiet sweep of "unknown"s.
        aborted = "too_many_errors"
    if aborted:
        log.error(
            "reconcile: aborted (%s) — %d would be marked removed, %d blocked, "
            "%d raised (RECONCILE_MAX_FLIPS=%d); nothing marked",
            aborted, len(gone), blocked, errors, max_flips,
        )
        gone = []

    marked: list[str] = []
    for src in gone:
        await asyncio.to_thread(
            store.mark_source_unavailable, src.id, "reconcile: datastore probe returned gone",
        )
        marked.append(src.id)
        log.warning("reconcile: %s removed upstream → unavailable", src.id)
    recovered: list[str] = []
    for src in back:
        await asyncio.to_thread(store.clear_source_unavailable, src.id)
        recovered.append(src.id)
        log.info("reconcile: %s reachable again → succeeded", src.id)
    return {
        "checked": len(sources),
        "marked_unavailable": marked,
        "recovered": recovered,
        "unknown": statuses.count("unknown"),
        "blocked": blocked,
        "errors": errors,
        "aborted": aborted,
    }
