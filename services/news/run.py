"""News run — for now the deterministic half only: find and rank signals.

    python -m services.news.run --signals-only                 # GCS models/, live catalog, GSC
    python -m services.news.run --signals-only --models-dir D  # local snapshots/dumps
    python -m services.news.run --signals-only --json --top 50

Reads only: the staging bucket's models/ history (or a local dir), the live
site's search index, Search Console. Writes nothing. Prints one
`news_signals` JSON summary line (like the builder's `pipeline_summary`),
then the ranked list (a table, or JSON with --json).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import catalog as catalog_mod
from . import demand as demand_mod
from .links import attach_links, load_edges
from .series import Series, extract_series
from .signals import Signal, detect_all, rank
from .snapshots import GcsSnapshots, LocalSnapshots, Snapshot, latest_and_baseline

log = logging.getLogger("services.news.run")


def _series_of(snap: Snapshot, today: date) -> list[Series]:
    # No data date (a bare local dump): the run date still marks the
    # in-progress period as partial.
    return extract_series(snap.model, snap.dataset_id, as_of=snap.data_as_of or today)


def find_signals(store, *, today: date, cutoff: str | None = None,
                 catalog: dict[str, dict] | None = None,
                 demand_by_id: dict[str, dict] | None = None, workers: int = 16,
                 ids: list[str] | None = None) -> tuple[list[Signal], dict]:
    """Every dataset's signals, linked and scored (unranked). `cutoff`
    (a `YYYYmmddTHHMMSSZ` stamp, normally the last news run): only datasets
    re-rendered since then can signal, and only with what is new since."""
    ids = ids if ids is not None else store.ids()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        pairs = dict(zip(ids, ex.map(lambda i: _safe_pair(store, i, cutoff), ids), strict=True))

    series_by_ds: dict[str, list[Series]] = {}
    signals: list[Signal] = []
    with_history = rendered = 0
    for ds, (latest, base, fresh) in pairs.items():
        if latest is None:
            continue
        cur = _series_of(latest, today)
        series_by_ds[ds] = cur   # link context even when it didn't re-render
        if not fresh:
            continue
        rendered += 1
        prev_map = None
        if base is not None and base.recipe_version == latest.recipe_version:
            # A recipe change reshapes the model; only same-recipe history
            # can say what is new.
            prev_map = {s.path: s for s in _series_of(base, today)}
            with_history += 1
        signals += detect_all(cur, today, prev_map)

    attach_links(signals, series_by_ds, load_edges(set(series_by_ds)))
    for s in signals:
        d = (demand_by_id or {}).get(s.dataset_id)
        s.demand = demand_mod.multiplier(d["impressions"]) if d else 1.0
    stats = {"datasets": len(ids), "with_snapshot": len(series_by_ds),
             "rendered_since_cutoff": rendered, "with_history": with_history,
             "series": sum(len(v) for v in series_by_ds.values()), "signals": len(signals),
             "linked": sum(bool(s.links) for s in signals),
             "catalog": len(catalog or {}), "demand_datasets": len(demand_by_id or {})}
    return signals, stats


def _safe_pair(store, ds: str, cutoff: str | None):
    try:
        return latest_and_baseline(store, ds, cutoff)
    except Exception:
        log.warning("news: reading snapshots of %s failed", ds, exc_info=True)
        return None, None, False


def _row(s: Signal, cat: dict) -> str:
    title = (cat.get(s.dataset_id) or {}).get("title") or s.dataset_id
    f = s.facts
    yoy = f.get("yoy_pct")
    extra = f" yoy {yoy:+.1f}%" if isinstance(yoy, float) else ""
    if f.get("suspect_incomplete"):
        extra += " (suspect incomplete)"
    links = f" ↔ {len(s.links)}" if s.links else ""
    return (f"{s.score:5.2f}  {title[:40]:40}  {s.series_path[:34]:34}  {s.period:10}  "
            f"{s.value:>12.4g}  {','.join(s.flags)}{extra}{links}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.news.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signals-only", action="store_true", required=True,
                    help="find and rank signals; nothing is written (the only mode so far)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--models-dir", type=Path, help="local snapshots instead of GCS")
    src.add_argument("--bucket", default=os.environ.get("GCS_STAGING_BUCKET", "govdata-il-staging"))
    ap.add_argument("--prefix", default="models/")
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--since-hours", type=float, default=24,
                    help="what counts as new: renders after now minus this (the last daily run); "
                         "0 = diff against the previous render")
    ap.add_argument("--dataset", action="append", help="limit to these dataset ids (repeatable)")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--per-dataset", type=int, default=3)
    ap.add_argument("--no-catalog", action="store_true")
    ap.add_argument("--no-demand", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")

    now = datetime.now(UTC)
    today = a.today or now.date()
    cutoff = ((now - timedelta(hours=a.since_hours)).strftime("%Y%m%dT%H%M%SZ")
              if a.since_hours > 0 else None)
    store = LocalSnapshots(a.models_dir) if a.models_dir else GcsSnapshots(a.bucket, a.prefix)
    cat = {} if a.no_catalog else catalog_mod.load_catalog()
    dem = {} if (a.no_demand or not cat) else demand_mod.dataset_demand(
        demand_mod.fetch_page_rows(today=today), cat)
    signals, stats = find_signals(store, today=today, cutoff=cutoff, catalog=cat, demand_by_id=dem, ids=a.dataset)
    ranked = rank(signals, per_dataset=a.per_dataset, top=a.top)

    print(json.dumps({"type": "news_signals", "today": today.isoformat(), "cutoff": cutoff, **stats,
                      "top": [s.key for s in ranked[:5]]}, ensure_ascii=False))
    if a.json:
        for s in ranked:
            d = s.to_dict() | {"title": (cat.get(s.dataset_id) or {}).get("title")}
            print(json.dumps(d, ensure_ascii=False, default=str))
    else:
        for s in ranked:
            print(_row(s, cat))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
