"""Undo the source-level damage from a provider account-limit outage.

Context — the 2026-08-11 outage: the OpenRouter key hit its $10 total spend
cap. Every agent session 403'd with "Key limit exceeded", but the pipeline
treated that as an ordinary per-dataset failure, so for 18 days it marked
each selected source `failed` and incremented `failed_attempts`. Two kinds
of damage accumulated, neither of which fixing the key undoes:

  1. **Parked sources.** The selector stops re-picking a source at
     `failed_attempts >= 3`, so sources that did nothing wrong became
     permanently invisible to the daily run.
  2. **Pages about to disappear.** `iter_publishable_sources` emits only
     `succeeded` + `unavailable`. Sources that were live and published in
     July, then re-picked by Track 2 during the outage and marked `failed`,
     are still on the site *only because no publish has run since*. The next
     successful publish would drop them from the manifest.

This script restores each affected source to the state it was in before the
outage touched it:

  * previously published (has `page_path`/`last_analyzed_at`)
        → `succeeded`, keeping its page and its analyzed-version markers so
          Track 2 re-analyzes it normally when the data actually moves on.
  * never published
        → `never`, putting it back at the front of the Track 1 backlog.

Both get `failed_attempts` zeroed and `last_error` cleared. Nothing else is
touched: `last_analyzed_at`, `analyzed_metadata_modified` and `page_path`
are left exactly as they are, because they still describe a real build.

Only sources whose recorded `last_error` matches the outage signature are
touched (`--error-contains`, default "403"), so genuinely broken sources
keep their parking.

Dry run by default — prints the plan and writes nothing:

    python scripts/reset_account_limit_failures.py
    python scripts/reset_account_limit_failures.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "govdata-il")
os.environ.setdefault("FIRESTORE_PROJECT_ID", "govdata-il")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from services.shared.firestore import SOURCES_COLL, FirestoreStateStore  # noqa: E402


def plan_reset(doc: dict) -> str:
    """Which status this source should go back to.

    A source that has ever been published keeps its page: `succeeded` is the
    only status the publisher emits, so anything else silently deletes a
    live page. One that never built goes back to `never` and re-enters the
    Track 1 backlog.
    """
    was_published = bool(doc.get("page_path")) or bool(doc.get("last_analyzed_at"))
    return "succeeded" if was_published else "never"


def collect(store: FirestoreStateStore, error_contains: str, min_attempts: int):
    out = []
    for d in store.client.collection(SOURCES_COLL).stream():
        r = d.to_dict() or {}
        if r.get("analysis_status") != "failed":
            continue
        attempts = r.get("failed_attempts")
        attempts = int(attempts) if attempts is not None else 1
        if attempts < min_attempts:
            continue
        if error_contains and error_contains not in (r.get("last_error") or ""):
            continue
        out.append((d.id, r, attempts, plan_reset(r)))
    return sorted(out, key=lambda x: x[3])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="Write the changes (default: dry run)")
    p.add_argument("--error-contains", default="403",
                   help="Only reset sources whose last_error contains this "
                        "(default '403'; pass '' to match every failure)")
    p.add_argument("--min-attempts", type=int, default=1,
                   help="Only reset sources with at least this many "
                        "failed_attempts (default 1 = every failure)")
    args = p.parse_args()

    store = FirestoreStateStore()
    rows = collect(store, args.error_contains, args.min_attempts)
    if not rows:
        print("nothing to reset")
        return

    restored_pages = sum(1 for *_, target in rows if target == "succeeded")
    requeued = len(rows) - restored_pages
    parked = sum(1 for *_, a, _ in rows if a >= 3)

    print(f"{len(rows)} failed source(s) match "
          f"(last_error contains {args.error_contains!r}, "
          f"failed_attempts >= {args.min_attempts})\n")
    for sid, r, attempts, target in rows:
        note = "restore live page" if target == "succeeded" else "back to backlog"
        print(f"  {sid[:8]}  attempts={attempts:<3} failed → {target:<9} "
              f"({note})  {str(r.get('title'))[:42]}")

    print(f"\n  {restored_pages} previously-published page(s) → succeeded "
          f"(these would otherwise vanish from the next publish)")
    print(f"  {requeued} never-built source(s) → never (re-enter Track 1)")
    print(f"  {parked} of them were parked at failed_attempts >= 3 "
          f"(invisible to the selector until now)")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
        return

    for sid, _r, _attempts, target in rows:
        store.client.collection(SOURCES_COLL).document(sid).set(
            {
                "analysis_status": target,
                "failed_attempts": 0,
                "last_error": None,
                "analysis_started_at": None,
            },
            merge=True,
        )
    print(f"\napplied to {len(rows)} source(s).")


if __name__ == "__main__":
    main()
