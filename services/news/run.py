"""The news run: signals → editor → writer → gates → image → article store.

    python -m services.news.run --signals-only                 # rank signals, write nothing
    python -m services.news.run --signals-only --models-dir D  # …from local snapshots/dumps
    python -m services.news.run --dry-run --out tmp/news/      # the whole day, written to a dir
    python -m services.news.run                                # live (needs NEWS_PUBLISH=live)

Live writes `articles/<slug>` (Firestore) + `gs://<staging>/news/<slug>/`
(images) and dispatches the publish workflow when ≥1 article was accepted.
A dry run reads the same inputs (models, catalog, GSC, prod's recent
articles for cooldown, full tables) and calls the same models, but writes
only to `--out`. Every mode prints one `news_summary` (or `news_signals`)
JSON line. Exit status: 0 on ok/idle, 1 when the model key was refused or
the run crashed.

What counts as new is the render window [cursor, now − SETTLE): the cursor
(`news_state/cursor`) is where the last successful live run's window ended,
so the job can run at any time, late, twice, or after a skipped day, and
every render is covered by exactly one live run (`news_window`). A dry run or
--signals-only reads the cursor but never moves it; --since-hours N is an
ad-hoc fixed window that neither reads nor moves it.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from services.shared import model_history

from . import catalog as catalog_mod
from . import demand as demand_mod
from . import images as images_mod
from .editor import choose, eligible
from .ledger import Ledger
from .links import attach_links, load_edges
from .llm import LLMError, LLMUnavailable
from .series import Series, extract_series
from .signals import Signal, detect_all, rank
from .snapshots import GcsSnapshots, LocalSnapshots, Snapshot, latest_and_baseline
from .tools import Toolbox
from .writer import Outcome, write

log = logging.getLogger("services.news.run")
TAGS_PATH = Path(__file__).resolve().parents[2] / "taxonomy" / "tags.json"
BYLINE = "מערכת govil.ai"


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# A render is stamped just before its model is uploaded: the window stops
# this far short of now, so a stamp inside it is already listable in GCS.
SETTLE = timedelta(minutes=10)
BOOTSTRAP_HOURS = 24   # the first run, before any cursor exists
MAX_LOOKBACK_HOURS = 168


def news_window(now: datetime, *, cursor: str | None, since_hours: float | None = None,
                max_lookback_hours: float = MAX_LOOKBACK_HOURS) -> dict:
    """{cutoff, upto, from}: renders stamped in [cutoff, upto) are new.

    from = "cursor" (the last live run's end), "capped" (the cursor is older
    than `max_lookback_hours`: a long-stopped job resumes on recent data, not
    weeks-old news), "bootstrap" (no cursor yet), or "since_hours" (explicit
    ad-hoc window, open-ended, the cursor untouched; 0 = no cutoff at all, diff
    each dataset's latest render against its previous one)."""
    fmt = model_history.TS_FORMAT
    if since_hours is not None:
        cutoff = (now - timedelta(hours=since_hours)).strftime(fmt) if since_hours > 0 else None
        return {"cutoff": cutoff, "upto": None, "from": "since_hours"}
    upto_dt = now - SETTLE
    upto = upto_dt.strftime(fmt)
    if not cursor:
        return {"cutoff": (upto_dt - timedelta(hours=BOOTSTRAP_HOURS)).strftime(fmt),
                "upto": upto, "from": "bootstrap"}
    floor = (upto_dt - timedelta(hours=max_lookback_hours)).strftime(fmt)
    if cursor < floor:
        return {"cutoff": floor, "upto": upto, "from": "capped"}
    return {"cutoff": min(cursor, upto), "upto": upto, "from": "cursor"}


def _series_of(snap: Snapshot, today: date) -> list[Series]:
    # No data date (a bare local dump): the run date still marks the
    # in-progress period as partial.
    return extract_series(snap.model, snap.dataset_id, as_of=snap.data_as_of or today)


def find_signals(store, *, today: date, cutoff: str | None = None, upto: str | None = None,
                 catalog: dict[str, dict] | None = None,
                 demand_by_id: dict[str, dict] | None = None, workers: int = 16,
                 ids: list[str] | None = None,
                 context: dict | None = None) -> tuple[list[Signal], dict]:
    """Every dataset's signals, linked and scored (unranked). `cutoff`
    (a `YYYYmmddTHHMMSSZ` stamp, normally the last news run): only datasets
    re-rendered since then can signal, and only with what is new since.
    `context`, when given, receives `series` and `models` per dataset (the
    writer's tools read them). `upto` (exclusive) closes the window: later
    renders belong to the next run."""
    ids = ids if ids is not None else store.ids()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        pairs = dict(zip(ids, ex.map(lambda i: _safe_pair(store, i, cutoff, upto), ids),
                         strict=True))

    series_by_ds: dict[str, list[Series]] = {}
    models: dict[str, dict] = {}
    signals: list[Signal] = []
    with_history = rendered = 0
    for ds, (latest, base, fresh) in pairs.items():
        if latest is None:
            continue
        cur = _series_of(latest, today)
        series_by_ds[ds] = cur   # link context even when it didn't re-render
        models[ds] = latest.model
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
    if context is not None:
        context["series"], context["models"] = series_by_ds, models
    stats = {"datasets": len(ids), "with_snapshot": len(series_by_ds),
             "rendered_since_cutoff": rendered, "with_history": with_history,
             "series": sum(len(v) for v in series_by_ds.values()), "signals": len(signals),
             "linked": sum(bool(s.links) for s in signals),
             "catalog": len(catalog or {}), "demand_datasets": len(demand_by_id or {})}
    return signals, stats


def _safe_pair(store, ds: str, cutoff: str | None, upto: str | None = None):
    try:
        return latest_and_baseline(store, ds, cutoff, upto)
    except Exception:
        log.warning("news: reading snapshots of %s failed", ds, exc_info=True)
        return None, None, False


def load_vocab(path: Path = TAGS_PATH) -> set[str]:
    try:
        return set(json.loads(path.read_text(encoding="utf-8"))["tags"])
    except (OSError, ValueError, KeyError):
        return set()


def _unique_slug(store, slug: str, today: date) -> str:
    if not store.slug_taken(slug):
        return slug
    dated = f"{slug}-{today:%Y-%m}"
    if not store.slug_taken(dated):
        return dated
    n = 2
    while store.slug_taken(f"{dated}-{n}"):
        n += 1
    return f"{dated}-{n}"


def write_day(llm, *, ranked: list[Signal], series_by_ds: dict, models: dict, catalog: dict,
              vocab: set[str], store, tables=None, today: date, run_id: str,
              max_per_day: int = 3, cooldown_days: int = 21, editor_candidates: int = 15,
              max_tool_calls: int = 25, images: bool = True, fetcher=None) -> dict:
    """One day's editorial pass. Returns the summary (also what main prints)."""
    recent = store.recent(90)
    cands = eligible(ranked, recent, cooldown_days=cooldown_days)[:editor_candidates]
    briefs, skipped = choose(llm, cands, catalog, recent, max_briefs=max_per_day,
                             today=today.isoformat())
    published, rejected = [], []
    model_errors = 0  # stories lost to the model service, not to an editorial decision
    for brief in briefs:
        ledger = Ledger()
        kw = {"fetcher": fetcher} if fetcher else {}
        tb = Toolbox(ledger=ledger, series=series_by_ds, models=models, catalog=catalog,
                     tables=tables, llm=llm, **kw)
        try:
            out = write(llm, tb, brief, catalog=catalog, vocab=vocab, today=today.isoformat(),
                        max_tool_calls=max_tool_calls)
        except LLMUnavailable:
            raise  # the key is refused: no point writing the next story
        except LLMError as e:  # still failing after retries: the story was never judged
            log.exception("news: writing %s failed on the model service", brief["signal_keys"])
            model_errors += 1
            out = Outcome("rejected", reason="error", problems=[f"{type(e).__name__}: {str(e)[:300]}"])
        except Exception as e:  # one story's crash must not cost the day's others
            log.exception("news: writing %s crashed", brief["signal_keys"])
            out = Outcome("rejected", reason="error", problems=[f"{type(e).__name__}: {str(e)[:300]}"])
        finally:
            tb.close()
        keys = brief["signal_keys"]
        if out.status != "accepted":
            rejected.append({"signal_keys": keys, "reason": out.reason,
                             "headline": (out.core or {}).get("headline")})
            store.reject({"run_id": run_id, "at": datetime.now(UTC).isoformat(), "brief":
                          {k: brief[k] for k in ("signal_keys", "dataset_ids", "angle_he")},
                          "reason": out.reason, "problems": out.problems, "critic": out.critic,
                          "core": out.core, "tool_calls": out.tool_calls, "tools": tb.log,
                          "ledger": ledger.dump()})
            continue
        core = out.core
        slug = _unique_slug(store, core["slug"], today)
        line = next((c for c in core["charts"] if c["type"] == "line"), None)
        fallback = [v for v in (line["option"]["series"][0]["data"] if line else []) if v is not None]
        hero, files = images_mod.hero(llm if images else None, core["image_brief"], fallback)
        now = datetime.now(UTC).isoformat()
        doc = {
            "slug": slug, "status": "published", "headline": core["headline"], "dek": core["dek"],
            "published_at": now, "updated_at": now, "byline": BYLINE,
            "dataset_ids": core["dataset_ids"], "tags": core["tags"], "signal_keys": keys,
            "hero": hero | {"alt": core["image_alt"] or core["headline"],
                            "caption": "איור" if hero["kind"] == "illustration" else None},
            "blocks": core["blocks"], "charts": core["charts"], "sources": core["sources"],
            "ledger": ledger.dump(), "words": core["words"], "run_id": run_id,
            "critic_scores": (out.critic or {}).get("scores"),
            "models": {"text": os.environ.get("NEWS_MODEL", "google/gemini-3.8-flash"),
                       "image": os.environ.get("NEWS_IMAGE_MODEL", "google/gemini-3.1-flash-image")
                       if hero["kind"] == "illustration" else None},
        }
        store.publish(doc, files)
        published.append(slug)
    return {"candidates": len(cands), "briefs": len(briefs), "published": published,
            "rejected": rejected, "skipped": skipped[:20], "model_errors": model_errors}


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


def _dispatch_publish() -> str | None:
    from services.shared import github

    try:
        return github.dispatch_workflow(github.default_repo(), "publish.yml",
                                        os.environ.get("PUBLISH_BRANCH", "main"))
    except Exception:
        log.exception("news: publish dispatch failed")
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m services.news.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--signals-only", action="store_true", help="rank signals; write nothing")
    mode.add_argument("--dry-run", action="store_true", help="the whole day, written to --out only")
    ap.add_argument("--out", type=Path, help="output dir for --dry-run")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--models-dir", type=Path, help="local snapshots instead of GCS")
    src.add_argument("--bucket", default=os.environ.get("GCS_STAGING_BUCKET", "govdata-il-staging"))
    ap.add_argument("--prefix", default=model_history.PREFIX + "/")
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--since-hours", type=float, default=None,
                    help="ad-hoc window: renders after now minus this, ignoring and keeping the "
                         "cursor; 0 = diff against the previous render. Default: since the cursor")
    ap.add_argument("--max-lookback-hours", type=float,
                    default=_env_int("NEWS_MAX_LOOKBACK_HOURS", MAX_LOOKBACK_HOURS))
    ap.add_argument("--dataset", action="append", help="limit to these dataset ids (repeatable)")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--per-dataset", type=int, default=3)
    ap.add_argument("--max-articles", type=int, default=_env_int("NEWS_MAX_PER_DAY", 3))
    ap.add_argument("--no-catalog", action="store_true")
    ap.add_argument("--no-demand", action="store_true")
    ap.add_argument("--no-tables", action="store_true", help="no full-table SQL (faster dry runs)")
    ap.add_argument("--no-images", action="store_true", help="chart-card heroes, no image model")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.max_lookback_hours <= 0:  # would cap every window to empty, silently
        ap.error("--max-lookback-hours / NEWS_MAX_LOOKBACK_HOURS must be > 0")
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(levelname)s %(name)s: %(message)s")

    live = not (a.signals_only or a.dry_run)
    if a.dry_run and not a.out:
        ap.error("--dry-run needs --out")
    if live and os.environ.get("NEWS_PUBLISH", "off").strip().lower() != "live":
        print(json.dumps({"type": "news_summary", "status": "disabled",
                          "reason": "NEWS_PUBLISH is not 'live'"}))
        return 0

    now = datetime.now(UTC)
    today = a.today or now.date()
    cursor = articles = None
    if a.since_hours is None and not a.models_dir:
        try:
            from .store import FirestoreArticles
            articles = FirestoreArticles(bucket=a.bucket)
            cursor = articles.read_cursor()
        except Exception as e:
            if live:  # a live run that can't see its cursor can't know what is new
                log.exception("news: reading the cursor failed")
                print(json.dumps({"type": "news_summary", "status": "failed",
                                  "error": f"cursor: {type(e).__name__}: {str(e)[:300]}"}))
                return 1
            log.warning("news: cursor unreadable — using the bootstrap window", exc_info=True)
    window = news_window(now, cursor=cursor, since_hours=a.since_hours,
                         max_lookback_hours=a.max_lookback_hours)
    snaps = LocalSnapshots(a.models_dir) if a.models_dir else GcsSnapshots(a.bucket, a.prefix)
    cat = {} if a.no_catalog else catalog_mod.load_catalog()
    dem = {} if (a.no_demand or not cat) else demand_mod.dataset_demand(
        demand_mod.fetch_page_rows(today=today), cat)
    ctx: dict = {}
    signals, stats = find_signals(snaps, today=today, cutoff=window["cutoff"],
                                  upto=window["upto"], catalog=cat,
                                  demand_by_id=dem, ids=a.dataset, context=ctx)
    ranked = rank(signals, per_dataset=a.per_dataset, top=a.top)

    if a.signals_only:
        print(json.dumps({"type": "news_signals", "today": today.isoformat(), "window": window,
                          **stats, "top": [s.key for s in ranked[:5]]}, ensure_ascii=False))
        for s in ranked:
            print(json.dumps(s.to_dict() | {"title": (cat.get(s.dataset_id) or {}).get("title")},
                             ensure_ascii=False, default=str) if a.json else _row(s, cat))
        return 0

    from .llm import OpenRouter
    from .store import FirestoreArticles, LocalArticles

    run_id = f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    summary: dict = {"type": "news_summary", "run_id": run_id, "mode": "live" if live else "dry_run",
                     "today": today.isoformat(), "window": window, "signals": stats}
    tables = llm = None
    try:
        llm = OpenRouter()
        if live:
            store = articles or FirestoreArticles(bucket=a.bucket)
        else:
            try:  # cooldown against what is really on the site
                seed = FirestoreArticles().recent(90)
            except Exception:
                log.warning("news: prod articles unreadable — dry run without cooldown", exc_info=True)
                seed = []
            store = LocalArticles(a.out, seed=seed)
        if not a.no_tables:
            from services.page_builder.refresh import recipe_repo_from_env
            from services.shared.firestore import FirestoreStateStore

            from .data import DatasetTables
            tables = DatasetTables(FirestoreStateStore(), recipe_repo_from_env())
        day = write_day(llm, ranked=ranked, series_by_ds=ctx["series"], models=ctx["models"],
                        catalog=cat, vocab=load_vocab(), store=store, tables=tables, today=today,
                        run_id=run_id, max_per_day=a.max_articles,
                        cooldown_days=_env_int("NEWS_DATASET_COOLDOWN_DAYS", 21),
                        max_tool_calls=_env_int("NEWS_MAX_TOOL_CALLS", 25), images=not a.no_images)
        summary |= day | {"status": "ok" if day["published"] else "idle"}
        if live and day["published"]:
            summary["publish_dispatch"] = _dispatch_publish()
        if live and window["upto"] and not (a.dataset or a.models_dir) and day.get("model_errors"):
            # A story the model service never let us finish is not a story
            # judged: keep the window so the next run sees its signals again.
            summary["cursor_advanced"] = False
        elif live and window["upto"] and not (a.dataset or a.models_dir):
            # Only a full run that got this far closes its window; a failed
            # one leaves it for the next run (cooldown + used signal keys stop
            # a story it did publish from being written twice). A --dataset
            # run saw only some datasets, so it leaves the cursor alone.
            try:
                summary["cursor_advanced"] = store.advance_cursor(window["upto"], run_id=run_id)
            except Exception as e:
                # The day's articles are out; a cursor left behind only makes
                # the next run re-read this window (cooldown + used keys hold).
                log.exception("news: advancing the cursor failed")
                summary |= {"cursor_advanced": False,
                            "cursor_error": f"{type(e).__name__}: {str(e)[:300]}"}
        rc = 0
    except LLMUnavailable as e:
        summary |= {"status": "llm_unavailable", "error": str(e)[:300]}
        rc = 1
    except Exception as e:
        log.exception("news run crashed")
        summary |= {"status": "failed", "error": f"{type(e).__name__}: {str(e)[:300]}"}
        rc = 1
    finally:
        if tables is not None:
            tables.close()
    if llm is not None:
        summary["cost_usd"], summary["llm_calls"] = round(llm.cost_usd, 4), llm.calls
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
