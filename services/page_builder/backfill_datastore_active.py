"""One-shot CLI: backfill `datastore_active` onto each source's resources.

The scanner now captures CKAN's per-resource `datastore_active` flag on
every upsert, but sources ingested before that change carry resources
without the key. The frontend's DatasetExplorer reads the flag from
data.json to decide which resources to expose in the shell's search/
data-exploration section. This CLI fetches each succeeded source's
current `package_show` from CKAN (one rate-limited request per source via
the existing `CKANClient`) and merges `{resource_id: datastore_active}`
into the Firestore doc. Re-runs are safe: sources whose resources all
already carry the key are skipped.

It only lists the pending sources unless given `--write`, which calls CKAN
and writes the (production) Firestore docs. `--dry-run` is still accepted
and is the default.

Usage:
    source venv/bin/activate
    python -m services.page_builder.backfill_datastore_active
    python -m services.page_builder.backfill_datastore_active --write --limit 3
    python -m services.page_builder.backfill_datastore_active --write
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging

from services.scanner.client import CKANClient
from services.shared.firestore import FirestoreStateStore, SourceRecord

log = logging.getLogger(__name__)


def _needs_backfill(src: SourceRecord) -> bool:
    """True if any resource on the doc is missing the datastore_active key."""
    resources = src.resources or []
    if not resources:
        return False
    return any("datastore_active" not in r for r in resources)


async def backfill(*, dry_run: bool = False, limit: int | None = None,
                   store: FirestoreStateStore | None = None) -> dict:
    store = store or FirestoreStateStore()
    succeeded = list(store.iter_succeeded_sources())
    pending = [r for r in succeeded if _needs_backfill(r)]
    if limit is not None:
        pending = pending[:limit]

    log.info(
        "backfill: %d succeeded, %d pending%s",
        len(succeeded), len(pending), " (dry-run)" if dry_run else "",
    )
    for r in pending:
        log.info("  pending: %s — %s", r.id, r.title)

    if dry_run or not pending:
        return {"succeeded": len(succeeded), "pending": len(pending),
                "updated": 0, "skipped": 0, "failed": 0}

    updated = 0
    skipped = 0
    failed = 0
    async with CKANClient() as client:
        for src in pending:
            try:
                dataset = await client.get_package(src.id)
            except Exception as e:  # noqa: BLE001 — CKANError / 404s on deleted datasets
                failed += 1
                log.warning("  fetch failed: %s — %s", src.id, e)
                continue
            flags = {r.id: r.datastore_active for r in dataset.resources if r.id}
            if store.set_resource_datastore_flags(src.id, flags):
                updated += 1
                log.info("  updated: %s (%d resource(s), %d datastore-active)",
                         src.id, len(flags), sum(flags.values()))
            else:
                skipped += 1
                log.info("  unchanged: %s", src.id)

    return {"succeeded": len(succeeded), "pending": len(pending),
            "updated": updated, "skipped": skipped, "failed": failed}


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="Call CKAN and write the flags to Firestore (default: list only).")
    mode.add_argument("--dry-run", action="store_true",
                      help="List sources that need the flag; don't call CKAN or write "
                           "Firestore. The default; kept so older command lines still run.")
    p.add_argument("--limit", type=int, default=None,
                   help="Backfill at most N sources (smoke-test).")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    summary = asyncio.run(backfill(dry_run=not args.write, limit=args.limit))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    _cli()
