"""The news run: signals → editor → writer → gates → image → article store,
then the daily floor (`--min-articles` / NEWS_MIN_PER_DAY): explainers on
high-demand datasets when event news left the Israel date short.

    python -m services.news.run --signals-only                 # rank signals, write nothing
    python -m services.news.run --signals-only --models-dir D  # …from local snapshots/dumps
    python -m services.news.run --dry-run --out tmp/news/      # the whole day, written to a dir
    python -m services.news.run                                # live (needs NEWS_PUBLISH=live)

Live writes `articles/<slug>` (Firestore) + `gs://<staging>/news/<slug>/`
(images) and dispatches the publish workflow when ≥1 article was accepted.
A dry run reads the same inputs (models, catalog, GSC, prod's recent
articles for cooldown, full tables) and calls the same models, but writes
only to `--out`. Every mode prints one `news_summary` (or `news_signals`)
JSON line. Exit status: 0 on ok/idle, 1 when the model key was refused, an
accepted story failed to store (`store_failed`, after the stored ones are
dispatched), or the run crashed.

What counts as new is the render window [cursor, now − SETTLE): the cursor
(`news_state/cursor`) is where the last successful live run's window ended,
so the job can run at any time, late, twice, or after a skipped day, and
every render is covered by exactly one live run (`news_window`). A dry run or
--signals-only reads the cursor but never moves it; --since-hours N is an
ad-hoc fixed window that neither reads nor moves it.

Hourly ticks. A scheduled run (live, no --dataset/--models-dir/--since-hours)
ends `skipped_quiet` inside QUIET_WINDOW and `skipped_overlap` while another
run holds the `news_state/lock` lease (NEWS_LEASE_TTL_S), both exit 0 with
nothing read or written. With a cursor it first asks the default database
whether any source was refreshed since the window's cutoff; with none, and no
daily duty due, it closes the window as `idle` with no GCS, catalog, Search
Console or model call. NEWS_MAX_PER_RUN caps event stories per run;
NEWS_DAY_BUDGET makes NEWS_MAX_PER_DAY a per-Israel-date ceiling on news
articles. NEWS_DIGEST_HOUR / NEWS_FLOOR_HOUR (NEWS_FLOOR_HOUR_FRIDAY) make the
digest and the floor fill once-a-day duties (`news_state/daily`).

New datasets (NEWS_NEW_DATASET_SIGNALS, off by default). A dataset whose first
render ever is in the window, and whose `sources/<id>` doc says it was created
within NEWS_NEW_DATASET_DAYS (30), signals `new_dataset`. If the editor picks
it, it is written as an explainer (`kind: feature`) in the event pass: it
shares the run's cap, meets the floor, starts no event cooldown, and keeps the
explainers' 60-day dataset cooldown and 7-day reject rule.
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
from zoneinfo import ZoneInfo

from services.shared import lease, model_history, schedule
from services.shared.env import env_int as _env_int
from services.shared.states import ArticleKind, NewsRunStatus, StoryResult

from . import catalog as catalog_mod
from . import demand as demand_mod
from . import digest as digest_mod
from . import features as features_mod
from . import images as images_mod
from . import llm as llm_mod
from .editor import REJECT_DAYS, choose, choose_features, eligible, rejected_signal_keys
from .ledger import Ledger
from .links import attach_links, load_edges
from .llm import LLMError, LLMUnavailable
from .series import Series, extract_series
from .signals import Signal, detect_all, is_new_dataset, new_dataset_signal, rank
from .snapshots import GcsSnapshots, History, LocalSnapshots, Snapshot, history
from .store import LIVE_STATUSES, LOCK_DOC, published_at
from .tools import Toolbox
from .writer import DATA_ONLY_KINDS, Outcome, write

log = logging.getLogger("services.news.run")
TAGS_PATH = Path(__file__).resolve().parents[2] / "taxonomy" / "tags.json"
BYLINE = "מערכת govil.ai"


def _digest_weekday() -> int | None:
    """NEWS_DIGEST_WEEKDAY: Python weekday 0-6 (4 = Friday); unset or bad = off."""
    v = os.environ.get("NEWS_DIGEST_WEEKDAY", "").strip()
    return int(v) if v.isdigit() and int(v) <= 6 else None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


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
                 context: dict | None = None, releases: bool = False,
                 new_datasets: bool = False, source_lookup=None,
                 new_dataset_days: int = 30, now: datetime | None = None) -> tuple[list[Signal], dict]:
    """Every dataset's signals, linked and scored (unranked). `cutoff`
    (a `YYYYmmddTHHMMSSZ` stamp, normally the last news run): only datasets
    re-rendered since then can signal, and only with what is new since.
    `context`, when given, receives `series` and `models` per dataset (the
    writer's tools read them), and with `new_datasets`, `new_datasets`: the
    catalog entries of new datasets built from their source docs (the
    deployed catalog may not list them yet). `upto` (exclusive) closes the
    window: later renders belong to the next run.

    `new_datasets` (NEWS_NEW_DATASET_SIGNALS): a dataset whose first render
    ever is in this window, created at its source within `new_dataset_days`
    of `now`, also signals `new_dataset`. The creation date comes from
    `source_lookup(id)` (the `sources/<id>` doc; default `_read_source`);
    off, nothing is looked up."""
    ids = ids if ids is not None else store.ids()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        pairs = dict(zip(ids, ex.map(lambda i: _safe_pair(store, i, cutoff, upto), ids),
                         strict=True))

    series_by_ds: dict[str, list[Series]] = {}
    models: dict[str, dict] = {}
    signals: list[Signal] = []
    firsts: list[tuple[str, Snapshot]] = []
    with_history = rendered = 0
    for ds, h in pairs.items():
        latest, base = h.latest, h.base
        if latest is None:
            continue
        cur = _series_of(latest, today)
        series_by_ds[ds] = cur   # link context even when it didn't re-render
        models[ds] = latest.model
        if not h.fresh:
            continue
        rendered += 1
        prev_map = None
        if base is not None and base.recipe_version == latest.recipe_version:
            # A recipe change reshapes the model; only same-recipe history
            # can say what is new.
            prev_map = {s.path: s for s in _series_of(base, today)}
            with_history += 1
        signals += detect_all(cur, today, prev_map, releases=releases)
        if h.first:
            firsts.append((ds, latest))

    new_stats: dict = {}
    if new_datasets:
        new_sigs, entries, new_stats = _new_dataset_signals(
            firsts, lookup=source_lookup or _read_source, days=new_dataset_days,
            now=now or datetime.now(UTC))
        signals += new_sigs
        if context is not None:
            context["new_datasets"] = entries

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
             "catalog": len(catalog or {}), "demand_datasets": len(demand_by_id or {})} | new_stats
    return signals, stats


def _safe_pair(store, ds: str, cutoff: str | None, upto: str | None = None) -> History:
    try:
        return history(store, ds, cutoff, upto)
    except Exception:
        log.warning("news: reading snapshots of %s failed", ds, exc_info=True)
        return History(None, None, False)


# ── new datasets (NEWS_NEW_DATASET_SIGNALS) ─────────────────────────────
# A first render alone is not news: a legacy page re-authored as a recipe, or
# an old dataset newly covered, renders for the first time too. Only a dataset
# its source created recently signals, by `metadata_created` (CKAN's creation
# date; a provider source's first sync), else the doc's `first_seen_at` (the
# scanner's first sighting).
SOURCE_FIELDS = ["title", "organization", "page_slug_suffix", "metadata_created",
                 "first_seen_at", "metadata_modified", "provider"]
DATASET_TAGS_PATH = Path(__file__).resolve().parents[2] / "taxonomy" / "dataset-tags.json"
_source_store = None


def _read_source(dataset_id: str) -> dict | None:
    """The DEFAULT database's `sources/<id>` doc (SOURCE_FIELDS), None when
    there is none. A seam: tests replace it."""
    global _source_store
    from services.shared.firestore import SOURCES_COLL, FirestoreStateStore

    if _source_store is None:
        _source_store = FirestoreStateStore()
    snap = (_source_store.client.collection(SOURCES_COLL).document(dataset_id)
            .get(field_paths=SOURCE_FIELDS))
    return (snap.to_dict() or {}) if snap.exists else None


def _as_utc(v) -> datetime | None:
    """A Firestore timestamp (datetime) or an ISO string, as aware UTC."""
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v)
        except ValueError:
            return None
    if not isinstance(v, datetime):
        return None
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


def source_created(doc: dict) -> tuple[datetime | None, str | None]:
    """(creation date, the field it came from): metadata_created, else first_seen_at."""
    for f in ("metadata_created", "first_seen_at"):
        if (d := _as_utc(doc.get(f))) is not None:
            return d, f
    return None, None


def _curated_tags() -> dict:
    try:
        return json.loads(DATASET_TAGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _new_dataset_signals(firsts: list[tuple[str, Snapshot]], *, lookup, days: int,
                         now: datetime) -> tuple[list[Signal], dict, dict]:
    """(signals, catalog entries by id, stats) for this window's first renders.
    A failed lookup, a missing doc or no usable date: no signal (logged)."""
    out, entries = [], {}
    stats = {"first_renders": len(firsts), "new_datasets": 0, "new_dataset_lookup_errors": 0}
    tags = _curated_tags() if firsts else {}
    for ds, latest in firsts:
        try:
            doc = lookup(ds)
        except Exception:
            log.warning("news: reading sources/%s failed; no new_dataset signal", ds, exc_info=True)
            stats["new_dataset_lookup_errors"] += 1
            continue
        if not doc:
            log.info("news: first render of %s but no sources doc; no new_dataset signal", ds)
            continue
        if doc.get("provider"):
            # A provider doc is created by our first sync, so its date says when
            # we added the page, not when the publication began (often decades ago).
            continue
        created, field_name = source_created(doc)
        if created is None:
            log.info("news: first render of %s with no creation date; no new_dataset signal", ds)
            continue
        if now - created > timedelta(days=days) or created > now + timedelta(days=1):
            continue  # an old dataset newly covered (a re-authored legacy page), not a new one
        entry = catalog_mod.entry_from_source(ds, doc, tags=tags.get(ds))
        entries[ds] = entry
        out.append(new_dataset_signal(ds, created.date(), title=entry["title"] or None,
                                      publisher=entry["organization"] or None,
                                      created_from=field_name, rendered_at=latest.rendered_at))
    stats["new_datasets"] = len(out)
    return out, entries, stats


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


IL_TZ = ZoneInfo("Asia/Jerusalem")
# A dataset whose explainer was rejected sits out the fill this long.
FEATURE_REJECT_DAYS = 7


def _published_on(recent: list[dict], today_il: date) -> list[dict]:
    out = []
    for a in recent:
        ts = published_at(a)
        if ts and (a.get("status") or "published") in LIVE_STATUSES and ts.astimezone(IL_TZ).date() == today_il:
            out.append(a)
    return out


def published_today(recent: list[dict], today_il: date, *, kind: str | None = None) -> int:
    """Live articles published on `today_il` (an Israel calendar date), of
    `kind` when given (a missing kind is news); an unpublished one doesn't
    meet the floor."""
    return sum(kind is None or (a.get("kind") or ArticleKind.NEWS) == kind
               for a in _published_on(recent, today_il))


def todays_stories(recent: list[dict], today_il: date) -> dict:
    """What earlier runs already published on `today_il`, for the editor's
    input (`published_today`): count, news_count, stories [{title, kind, lead_dataset}]."""
    arts = _published_on(recent, today_il)
    return {"count": len(arts),
            "news_count": sum((a.get("kind") or ArticleKind.NEWS) == ArticleKind.NEWS for a in arts),
            "stories": [{"title": a.get("headline"), "kind": a.get("kind") or ArticleKind.NEWS,
                         "lead_dataset": (a.get("dataset_ids") or [None])[0]} for a in arts]}


# ── once-a-day duties (the weekly digest, the floor fill) ───────────────
# With an hour env set (NEWS_DIGEST_HOUR, NEWS_FLOOR_HOUR[_FRIDAY]) a duty is
# tried by the first run at/after that Israel hour, once per Israel date (the
# attempt is recorded in `news_state/daily` before writing). Unset: every run
# may try it, as before hourly ticks.

def _env_hour(name: str) -> int | None:
    v = os.environ.get(name, "").strip()
    if not v:
        return None
    if v.isdigit() and int(v) <= 23:
        return int(v)
    log.warning("news: malformed %s=%r (want an hour 0-23); treating as unset", name, v)
    return None


def duty_hours() -> dict:
    """The duty schedule from env, as write_day / duties_due keywords."""
    return {"digest_weekday": _digest_weekday(), "digest_hour": _env_hour("NEWS_DIGEST_HOUR"),
            "floor_hour": _env_hour("NEWS_FLOOR_HOUR"),
            "floor_hour_friday": _env_hour("NEWS_FLOOR_HOUR_FRIDAY")}


def _floor_hour_on(il_day: date, floor_hour: int | None, floor_hour_friday: int | None) -> int | None:
    return floor_hour_friday if il_day.weekday() == 4 and floor_hour_friday is not None else floor_hour


def _duty_open(duty: str, hour: int | None, il_now: datetime, daily: dict) -> bool:
    """Whether this run may try `duty`: always without an hour (no markers);
    else at/after the hour and not yet attempted on this Israel date."""
    if hour is None:
        return True
    return il_now.hour >= hour and daily.get(f"{duty}_attempt") != il_now.date().isoformat()


def duties_due(now: datetime, *, daily: dict, recent: list[dict], min_per_day: int, max_per_run: int,
               digest_weekday: int | None = None, digest_hour: int | None = None,
               floor_hour: int | None = None, floor_hour_friday: int | None = None) -> dict:
    """{"digest": bool, "floor": bool}: which daily duty this run would try
    (the idle probe's question; `recent` = today's articles at least)."""
    il = now.astimezone(IL_TZ)
    digest = (digest_weekday is not None and il.weekday() == digest_weekday
              and _duty_open("digest", digest_hour, il, daily))
    short = min(min_per_day - published_today(recent, il.date()), max_per_run) > 0
    floor = short and _duty_open("floor", _floor_hour_on(il.date(), floor_hour, floor_hour_friday),
                                 il, daily)
    return {"digest": bool(digest), "floor": bool(floor)}


def _mark_duty(store, duty: str, il_day: date, run_id: str) -> bool:
    """Record the attempt first; unrecorded, the duty is skipped this run
    (later runs would otherwise re-roll it)."""
    try:
        store.mark_duty(duty, il_day.isoformat(), run_id=run_id)
        return True
    except Exception:
        log.exception("news: recording the %s attempt failed; skipping it this run", duty)
        return False


def _unmark_duty(store, duty: str, run_id: str) -> None:
    """Give the day's attempt back: the model key was refused before anything
    was judged or spent, so a later run today should try again."""
    try:
        store.mark_duty(duty, "", run_id=run_id)
    except Exception:
        log.exception("news: clearing the %s attempt failed; it stays used today", duty)


class _Day:
    """One run's writing state: every brief, event or fill, goes through
    `write_one`, so they share the store, reject and error accounting."""

    def __init__(self, llm, *, series_by_ds, models, catalog, vocab, store, tables, today, run_id,
                 max_tool_calls, images, fetcher, published, feature_tool_calls=None):
        self.llm, self.series_by_ds, self.models, self.catalog = llm, series_by_ds, models, catalog
        self.vocab, self.store, self.tables, self.today, self.run_id = vocab, store, tables, today, run_id
        self.max_tool_calls, self.images, self.fetcher = max_tool_calls, images, fetcher
        self.published, self.rejected = published, []
        # explainers do the data work themselves (no seeded signal facts)
        self.feature_tool_calls = feature_tool_calls or max_tool_calls

    def write_one(self, brief: dict) -> StoryResult:
        llm, store, today = self.llm, self.store, self.today
        kind = brief.get("kind") or ArticleKind.NEWS
        ledger = Ledger()
        kw = {"fetcher": self.fetcher} if self.fetcher else {}
        tb = Toolbox(ledger=ledger, series=self.series_by_ds, models=self.models, catalog=self.catalog,
                     tables=self.tables, llm=llm, **kw)
        status = None
        try:
            out = write(llm, tb, brief, catalog=self.catalog, vocab=self.vocab, today=today.isoformat(),
                        max_tool_calls=(self.feature_tool_calls if kind in DATA_ONLY_KINDS
                                        else self.max_tool_calls))
        except LLMUnavailable:
            raise  # the key is refused: no point writing the next story
        except LLMError as e:  # still failing after retries: the story was never judged
            log.exception("news: writing %s failed on the model service", brief["signal_keys"])
            status = StoryResult.MODEL_ERROR
            out = Outcome("rejected", reason="error", problems=[f"{type(e).__name__}: {str(e)[:300]}"])
        except Exception as e:  # one story's crash must not cost the day's others
            log.exception("news: writing %s crashed", brief["signal_keys"])
            out = Outcome("rejected", reason="error", problems=[f"{type(e).__name__}: {str(e)[:300]}"])
        finally:
            tb.close()
        keys = brief["signal_keys"]
        if out.status != "accepted":
            self.rejected.append({"signal_keys": keys, "kind": kind, "reason": out.reason,
                                  "headline": (out.core or {}).get("headline")})
            try:  # the record is for tuning: losing it must not cost the day's other stories
                store.reject({"run_id": self.run_id, "at": datetime.now(UTC).isoformat(), "kind": kind,
                              "brief": {k: brief[k] for k in ("signal_keys", "dataset_ids", "angle_he")},
                              "reason": out.reason, "problems": out.problems, "critic": out.critic,
                              "core": out.core, "tool_calls": out.tool_calls, "tools": tb.log,
                              "ledger": ledger.dump()})
            except Exception:
                log.exception("news: recording the rejection of %s failed", keys)
            return status or StoryResult.REJECTED
        core = out.core
        try:
            slug = _unique_slug(store, core["slug"], today)
            line = next((c for c in core["charts"] if c["type"] == "line"), None)
            fallback = [v for v in (line["option"]["series"][0]["data"] if line else []) if v is not None]
            hero, files = images_mod.hero(llm if self.images else None, core["image_brief"], fallback)
            now = datetime.now(UTC).isoformat()
            doc = {
                "slug": slug, "status": "published", "kind": kind,
                "headline": core["headline"], "dek": core["dek"],
                "published_at": now, "updated_at": now, "byline": BYLINE,
                "dataset_ids": core["dataset_ids"], "tags": core["tags"], "signal_keys": keys,
                "hero": hero | {"alt": core["image_alt"] or core["headline"],
                                "caption": "איור" if hero["kind"] == "illustration" else None},
                "blocks": core["blocks"], "charts": core["charts"], "sources": core["sources"],
                "ledger": ledger.dump(), "words": core["words"], "run_id": self.run_id,
                "critic_scores": (out.critic or {}).get("scores"),
                "models": {"text": llm_mod.TEXT_MODEL, "reasoning_effort": llm_mod.REASONING_EFFORT or None,
                           "image": llm_mod.IMAGE_MODEL if hero["kind"] == "illustration" else None},
            }
            store.publish(doc, files)
        except Exception:  # storage down for this story: retried next run, the others go on
            log.exception("news: storing %s failed", keys)
            self.rejected.append({"signal_keys": keys, "kind": kind, "reason": "error",
                                  "headline": core.get("headline")})
            return StoryResult.STORE_ERROR
        self.published.append(slug)
        return StoryResult.PUBLISHED


def _new_dataset_gate(cands: list[Signal], *, store, recent: list[dict], now: datetime,
                      feature_cooldown_days: int) -> list[Signal]:
    """A new dataset's story is an explainer, so the explainers' rules hold:
    no dataset an article drew on in the last `feature_cooldown_days`, none
    whose explainer was rejected in the last FEATURE_REJECT_DAYS."""
    try:
        rejects = store.recent_rejects(FEATURE_REJECT_DAYS)
    except Exception:
        log.warning("news: reading recent rejects failed", exc_info=True)
        rejects = []
    skip = (features_mod.covered(recent, days=feature_cooldown_days, now=now)
            | features_mod.rejected_leads(rejects))
    return [s for s in cands if not (is_new_dataset(s) and s.dataset_id in skip)]


def write_day(llm, *, ranked: list[Signal], series_by_ds: dict, models: dict, catalog: dict,
              vocab: set[str], store, tables=None, today: date, run_id: str,
              max_per_run: int = 3, day_ceiling: int | None = None,
              cooldown_days: int = 21, editor_candidates: int = 15,
              max_tool_calls: int = 25, images: bool = True, fetcher=None,
              stored: list | None = None, min_per_day: int = 0, demand_by_id: dict | None = None,
              feature_cooldown_days: int = 60, fill_attempts: int = 2,
              feature_tool_calls: int | None = None, digest_weekday: int | None = None,
              digest_hour: int | None = None, floor_hour: int | None = None,
              floor_hour_friday: int | None = None, now: datetime | None = None) -> dict:
    """One day's editorial pass. Returns the summary (also what main prints).
    `stored` (if given) collects the slugs stored so far, so a caller still
    sees them when the pass raises.

    Event news first (signals → editor); the candidates it didn't use go to
    the signal pool. On `digest_weekday` (Israel date, Python weekday), the
    weekly digest of pooled signals (`digest.py`). Then the floor: when fewer than
    `min_per_day` articles came out on this Israel date (this run's and earlier
    runs'), explainers fill the gap (`features.py` → `editor.choose_features`),
    up to `fill_attempts` briefs per missing article. A fill goes through the
    same gates and critic, so a day can still end short.

    Event briefs per run ≤ `max_per_run`; with `day_ceiling` (NEWS_DAY_BUDGET)
    also ≤ day_ceiling minus the news articles already out this Israel date
    (explainers and the digest don't count). Signal keys of event stories
    rejected in the last REJECT_DAYS stay off the editor's list. With
    `digest_hour` / `floor_hour` (+ `floor_hour_friday`) set, the digest and
    the fill are tried once per Israel date (`news_state/daily`)."""
    now = now or datetime.now(UTC)
    il_now = now.astimezone(IL_TZ)
    il_today = il_now.date()
    recent = store.recent(90)
    todays = todays_stories(recent, il_today)
    max_briefs = max_per_run
    if day_ceiling is not None:
        max_briefs = max(0, min(max_per_run, day_ceiling - todays["news_count"]))
    try:
        rejected_keys = rejected_signal_keys(store.recent_rejects(REJECT_DAYS))
    except Exception:
        log.warning("news: reading recent rejects failed", exc_info=True)
        rejected_keys = set()
    cands = eligible(ranked, recent, cooldown_days=cooldown_days,
                     rejected_keys=rejected_keys)
    if any(is_new_dataset(s) for s in cands):
        cands = _new_dataset_gate(cands, store=store, recent=recent, now=now,
                                  feature_cooldown_days=feature_cooldown_days)
    # Same rule as `rank`'s cut: new datasets ride along past the limit.
    series = [s for s in cands if not is_new_dataset(s)]
    cands = series[:editor_candidates] + [s for s in cands if is_new_dataset(s)]
    offer, room = cands, max_briefs
    if max_briefs <= 0 < max_per_run:
        # The day's news ceiling is reached, but a new dataset's explainer is
        # not news: it still has the run's room.
        offer = [s for s in cands if is_new_dataset(s)]
        room = 1 if offer else 0
    briefs, skipped = choose(llm, offer, catalog, recent, max_briefs=room,
                             today=today.isoformat(), published_today=todays)
    day = _Day(llm, series_by_ds=series_by_ds, models=models, catalog=catalog, vocab=vocab,
               store=store, tables=tables, today=today, run_id=run_id,
               max_tool_calls=max_tool_calls, images=images, fetcher=fetcher,
               published=stored if stored is not None else [], feature_tool_calls=feature_tool_calls)
    model_errors = 0  # event stories lost to the model service, not to an editorial decision
    store_errors = 0  # accepted stories the store failed to save
    published_keys: set[str] = set()   # a rejected brief's signals may still make the digest
    for brief in briefs:
        r = day.write_one(brief)
        model_errors += r == StoryResult.MODEL_ERROR
        store_errors += r == StoryResult.STORE_ERROR
        if r == StoryResult.PUBLISHED:
            published_keys.update(brief["signal_keys"])

    out = {"candidates": len(cands), "briefs": len(briefs), "published": day.published,
           "rejected": day.rejected, "skipped": skipped[:20], "model_errors": model_errors,
           "store_errors": store_errors}
    if day_ceiling is not None:
        out["news_budget"] = {"per_run": max_per_run, "day_ceiling": day_ceiling,
                              "news_today": todays["news_count"], "max_briefs": max_briefs}
    fl_hour = _floor_hour_on(il_today, floor_hour, floor_hour_friday)
    daily: dict | None = {}
    if digest_hour is not None or fl_hour is not None:
        try:
            daily = store.read_daily()
        except Exception:  # can't tell what was attempted: skip the gated duties this run
            log.exception("news: reading news_state/daily failed; skipping the scheduled duties")
            daily = None
    try:  # the digest's raw material; losing one run's worth costs little
        # A new dataset is an explainer's subject, never a line in the roundup.
        store.pool(digest_mod.pool_items([s for s in cands if not is_new_dataset(s)],
                                         published_keys, skipped, run_id))
    except Exception:
        log.warning("news: pooling the editor's unused signals failed", exc_info=True)
    if day.published:
        # What this run just published counts too: the digest and the fill
        # must not repeat its signal or dataset, and the floor counts it.
        recent = store.recent(90)
    if (digest_weekday is not None and il_today.weekday() == digest_weekday
            and (digest_hour is None or (daily is not None
                                         and _duty_open("digest", digest_hour, il_now, daily)))):
        # Its own weekly slot: a busy Friday (max_per_run reached) must not
        # silently cost the week its digest.
        on_attempt = (None if digest_hour is None
                      else lambda: _mark_duty(store, "digest", il_today, run_id))
        try:
            out["digest"] = _digest(day, recent=recent, today=il_today,
                                    cooldown_days=cooldown_days, on_attempt=on_attempt)
        except LLMUnavailable:
            if digest_hour is not None:
                _unmark_duty(store, "digest", run_id)
            raise
        if out["digest"].get("status") == StoryResult.PUBLISHED:
            recent = store.recent(90)
    today_count = published_today(recent, il_today)
    need = min(min_per_day - today_count, max_per_run - len(day.published))
    if need > 0 and (fl_hour is None or (daily is not None
                                         and _duty_open("floor", fl_hour, il_now, daily))):
        if fl_hour is not None and not _mark_duty(store, "floor", il_today, run_id):
            out["fill"] = {"kind": ArticleKind.FEATURE, "need": need, "skipped": "attempt_unrecorded"}
        else:
            try:
                out["fill"] = _fill(day, need=need, recent=recent, demand_by_id=demand_by_id or {},
                                    cooldown_days=feature_cooldown_days, attempts=fill_attempts,
                                    now=now)
            except LLMUnavailable:
                if fl_hour is not None:
                    _unmark_duty(store, "floor", run_id)
                raise
    return out


def _digest(day: _Day, *, recent: list[dict], today: date, cooldown_days: int,
            on_attempt=None) -> dict:
    """This week's digest, once (its `digest:<week>` key dedups later runs).
    `on_attempt` (scheduled digests) records the attempt once the pool is read,
    before writing; False (unrecorded) skips it this run."""
    try:
        pool = day.store.read_pool(7)
    except Exception:
        log.warning("news: reading the signal pool failed", exc_info=True)
        return {"status": StoryResult.POOL_UNREADABLE}
    if on_attempt is not None and not on_attempt():
        return {"status": StoryResult.DIGEST_SKIPPED, "reason": "attempt_unrecorded"}
    b = digest_mod.brief(pool, recent, today=today, cooldown_days=cooldown_days,
                         series_by_ds=day.series_by_ds, catalog=day.catalog)
    if b is None:
        return {"status": StoryResult.DIGEST_SKIPPED, "pooled": len(pool)}
    return {"status": day.write_one(b), "pooled": len(pool), "items": len(b["signals"])}


def _fill(day: _Day, *, need: int, recent: list[dict], demand_by_id: dict, cooldown_days: int,
          attempts: int, now: datetime) -> dict:
    """Explainers until `need` are published or the attempts run out. A fill's
    model or store error doesn't hold the cursor: explainers don't come from
    the render window, and the next run's floor tries again anyway."""
    try:
        rejects = day.store.recent_rejects(FEATURE_REJECT_DAYS)
    except Exception:
        log.warning("news: reading recent rejects failed", exc_info=True)
        rejects = []
    cands = features_mod.candidates(catalog=day.catalog, models=day.models, series=day.series_by_ds,
                                    demand_by_id=demand_by_id, recent=recent,
                                    cooldown_days=cooldown_days, now=now,
                                    exclude=features_mod.rejected_leads(rejects))
    used = {k for a in recent for k in a.get("signal_keys") or []}
    out = {"kind": ArticleKind.FEATURE, "need": need, "candidates": len(cands), "briefs": 0,
           "attempts": 0, "published": 0, "store_errors": 0}
    try:
        chosen = choose_features(day.llm, cands, recent, max_briefs=need * attempts,
                                 today=day.today.isoformat())
    except (LLMError, ValueError) as e:  # a refused key (LLMUnavailable) still ends the run
        log.exception("news: the features editor failed")
        return out | {"error": f"{type(e).__name__}: {str(e)[:300]}"}
    briefs = [b for b in chosen if not used & set(b["signal_keys"])]
    out["briefs"] = len(briefs)
    for brief in briefs:
        if out["published"] >= need:
            break
        out["attempts"] += 1
        r = day.write_one(brief)
        out["published"] += r == StoryResult.PUBLISHED
        out["store_errors"] += r == StoryResult.STORE_ERROR
    return out


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


# Renewed by a heartbeat while the run works (lease.Heartbeat), so the TTL only
# bounds how long a run that died without releasing keeps later ticks out.
LEASE_TTL_DEFAULT_S = 900


def _lease_holder() -> str:
    execution = os.environ.get("CLOUD_RUN_EXECUTION", "local")
    return f"{execution}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _lease_ttl_s() -> float:
    return float(_env_int("NEWS_LEASE_TTL_S", LEASE_TTL_DEFAULT_S))


def _acquire_lease(articles, holder: str) -> bool | None:
    """True: ours. False: another run holds it. None: Firestore error, logged
    at error level; the run goes on without it (as the builder does)."""
    try:
        return lease.acquire(articles.db, LOCK_DOC, holder, _lease_ttl_s())
    except Exception:
        log.exception("news: couldn't acquire %s; running WITHOUT the lease", LOCK_DOC)
        return None


def _release_lease(articles, holder: str) -> None:
    try:
        lease.release(articles.db, LOCK_DOC, holder)
    except Exception:
        log.exception("news: couldn't release %s; it expires on its own (NEWS_LEASE_TTL_S)", LOCK_DOC)


# A render's `last_refreshed_at` is written just before its model is stamped
# (refresh.py: mark_refreshed, then _stage_model_history), so the probe looks
# this far before the window's cutoff: a false "renders" only costs a full run.
PROBE_SLACK = SETTLE


def _renders_since(since: datetime) -> bool:
    """Whether any source in the DEFAULT database was refreshed at/after
    `since` (`sources.last_refreshed_at`, a Firestore timestamp written by
    `mark_refreshed`). A seam: tests replace it."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    from services.shared.firestore import SOURCES_COLL, FirestoreStateStore

    q = (FirestoreStateStore().client.collection(SOURCES_COLL)
         .where(filter=FieldFilter("last_refreshed_at", ">=", since)).limit(1))
    return any(True for _ in q.stream())


def _idle_probe(articles, *, window: dict, now: datetime, min_per_day: int, max_per_run: int,
                hours: dict) -> dict:
    """The cheap check of a scheduled run with a cursor, before any GCS,
    catalog, demand or model call: {"idle": bool, ...}. Idle = no daily duty
    due (news database reads) and no source refreshed since the window's
    cutoff (one default-database query). Any error → not idle."""
    try:
        recent = articles.recent(2)
        daily = articles.read_daily()
        due = duties_due(now, daily=daily, recent=recent, min_per_day=min_per_day,
                         max_per_run=max_per_run, **hours)
    except Exception:
        log.exception("news: idle probe: reading the daily state failed; taking the full path")
        return {"idle": False, "probe": "error"}
    if any(due.values()):
        return {"idle": False, "probe": "duty_due", "duties": due}
    since = (datetime.strptime(window["cutoff"], model_history.TS_FORMAT).replace(tzinfo=UTC)
             - PROBE_SLACK)
    try:
        renders = _renders_since(since)
    except Exception:
        log.exception("news: idle probe: the sources query failed; taking the full path")
        return {"idle": False, "probe": "error"}
    return {"idle": not renders, "probe": "renders" if renders else "no_renders"}


def _advance(store, window: dict, run_id: str) -> dict:
    """Close the window (the cursor moves only forward)."""
    try:
        return {"cursor_advanced": store.advance_cursor(window["upto"], run_id=run_id)}
    except Exception as e:
        # The day's articles are out; a cursor left behind only makes
        # the next run re-read this window (cooldown + used keys hold).
        log.exception("news: advancing the cursor failed")
        return {"cursor_advanced": False, "cursor_error": f"{type(e).__name__}: {str(e)[:300]}"}


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
    ap.add_argument("--max-articles", type=int, default=_env_int("NEWS_MAX_PER_DAY", 3),
                    help="NEWS_MAX_PER_DAY: the per-run cap on event stories, or with "
                         "NEWS_DAY_BUDGET set, a ceiling on news articles per Israel date")
    ap.add_argument("--max-per-run", type=int, default=None,
                    help="NEWS_MAX_PER_RUN: event stories per run (default: --max-articles)")
    ap.add_argument("--min-articles", type=int, default=_env_int("NEWS_MIN_PER_DAY", 0),
                    help="daily floor (Israel date): explainers fill up to this many when "
                         "event news falls short; still capped by --max-per-run")
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
        print(json.dumps({"type": "news_summary", "status": NewsRunStatus.DISABLED,
                          "reason": "NEWS_PUBLISH is not 'live'"}))
        return 0

    # A scheduled run (live, the full window): QUIET_WINDOW, then the lease.
    gated = live and a.since_hours is None and not (a.dataset or a.models_dir)
    if gated and schedule.in_quiet_window("QUIET_WINDOW"):
        log.info("news: inside QUIET_WINDOW=%s; nothing to do this tick", os.environ.get("QUIET_WINDOW"))
        print(json.dumps({"type": "news_summary", "status": NewsRunStatus.SKIPPED_QUIET}))
        return 0
    articles = holder = acquired = None
    if a.since_hours is None and not a.models_dir:
        try:
            from .store import FirestoreArticles
            articles = FirestoreArticles(bucket=a.bucket)
        except Exception as e:
            if live:
                log.exception("news: opening the article store failed")
                print(json.dumps({"type": "news_summary", "status": NewsRunStatus.FAILED,
                                  "error": f"cursor: {type(e).__name__}: {str(e)[:300]}"}))
                return 1
            log.warning("news: article store unavailable — using the bootstrap window", exc_info=True)
    if gated and articles is not None:
        holder = _lease_holder()
        acquired = _acquire_lease(articles, holder)
        if acquired is False:
            log.warning("news: %s is held by another run; skipping this tick", LOCK_DOC)
            print(json.dumps({"type": "news_summary", "status": NewsRunStatus.SKIPPED_OVERLAP}))
            return 0
    beat = (lease.Heartbeat(articles.db, LOCK_DOC, holder, _lease_ttl_s()).start()
            if acquired else None)
    try:
        return _run(a, live=live, gated=gated, articles=articles,
                    lease_state=None if not gated else "held" if acquired else "error")
    finally:
        if beat:
            beat.stop()
        if acquired:
            _release_lease(articles, holder)


def _run(a, *, live: bool, gated: bool, articles, lease_state: str | None) -> int:
    now = datetime.now(UTC)
    today = a.today or now.date()
    cursor = None
    if articles is not None:
        try:
            cursor = articles.read_cursor()
        except Exception as e:
            if live:  # a live run that can't see its cursor can't know what is new
                log.exception("news: reading the cursor failed")
                print(json.dumps({"type": "news_summary", "status": NewsRunStatus.FAILED,
                                  "error": f"cursor: {type(e).__name__}: {str(e)[:300]}"}))
                return 1
            log.warning("news: cursor unreadable — using the bootstrap window", exc_info=True)
    window = news_window(now, cursor=cursor, since_hours=a.since_hours,
                         max_lookback_hours=a.max_lookback_hours)
    max_per_run = (a.max_per_run if a.max_per_run is not None
                   else _env_int("NEWS_MAX_PER_RUN", a.max_articles))
    day_ceiling = a.max_articles if _env_flag("NEWS_DAY_BUDGET") else None
    hours = duty_hours()
    run_id = f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    lease_info = {"lease": lease_state} if lease_state else {}
    if gated and cursor and window["upto"]:
        probe = _idle_probe(articles, window=window, now=now, min_per_day=a.min_articles,
                            max_per_run=max_per_run, hours=hours)
        if probe["idle"]:
            # Nothing rendered since the cursor and no duty due: close the
            # window as an idle full run would, with no GCS/catalog/model call.
            summary = {"type": "news_summary", "run_id": run_id, "mode": "live",
                       "today": today.isoformat(), "window": window, **lease_info,
                       "status": NewsRunStatus.IDLE, "probe": probe["probe"]}
            summary |= _advance(articles, window, run_id)
            print(json.dumps(summary, ensure_ascii=False, default=str))
            return 0
        lease_info["probe"] = probe["probe"]
    snaps = LocalSnapshots(a.models_dir) if a.models_dir else GcsSnapshots(a.bucket, a.prefix)
    cat = {} if a.no_catalog else catalog_mod.load_catalog()
    dem = {} if (a.no_demand or not cat) else demand_mod.dataset_demand(
        demand_mod.fetch_page_rows(today=today), cat)
    ctx: dict = {}
    signals, stats = find_signals(snaps, today=today, cutoff=window["cutoff"],
                                  upto=window["upto"], catalog=cat,
                                  demand_by_id=dem, ids=a.dataset, context=ctx,
                                  releases=_env_flag("NEWS_RELEASE_SIGNALS"),
                                  new_datasets=_env_flag("NEWS_NEW_DATASET_SIGNALS"),
                                  new_dataset_days=_env_int("NEWS_NEW_DATASET_DAYS", 30), now=now)
    for ds, entry in (ctx.get("new_datasets") or {}).items():
        # The deployed catalog lags a first render: the source doc gives the
        # editor, the writer and the gates' link check its title and page.
        cat.setdefault(ds, entry)
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

    summary: dict = {"type": "news_summary", "run_id": run_id, "mode": "live" if live else "dry_run",
                     "today": today.isoformat(), "window": window, "signals": stats, **lease_info}
    tables = llm = None
    stored: list = []  # slugs stored so far, seen even if the day crashes
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
            from services.page_builder.recipe_repo import recipe_repo_from_env
            from services.shared.firestore import FirestoreStateStore

            from .data import DatasetTables
            tables = DatasetTables(FirestoreStateStore(), recipe_repo_from_env())
        day = write_day(llm, ranked=ranked, series_by_ds=ctx["series"], models=ctx["models"],
                        catalog=cat, vocab=load_vocab(), store=store, tables=tables, today=today,
                        run_id=run_id, max_per_run=max_per_run, day_ceiling=day_ceiling,
                        cooldown_days=_env_int("NEWS_DATASET_COOLDOWN_DAYS", 21),
                        max_tool_calls=_env_int("NEWS_MAX_TOOL_CALLS", 25), images=not a.no_images,
                        stored=stored, min_per_day=a.min_articles, demand_by_id=dem,
                        feature_cooldown_days=_env_int("NEWS_FEATURE_COOLDOWN_DAYS", 60),
                        fill_attempts=_env_int("NEWS_FILL_ATTEMPTS", 2),
                        feature_tool_calls=_env_int("NEWS_FEATURE_MAX_TOOL_CALLS", 35),
                        **hours)
        # An accepted story the store lost (event, digest or fill) turns the
        # job red: a store that fails every day must not look like a quiet one.
        store_failed = bool(day.get("store_errors") or (day.get("fill") or {}).get("store_errors")
                            or (day.get("digest") or {}).get("status") == StoryResult.STORE_ERROR)
        summary |= day | {"status": NewsRunStatus.STORE_FAILED if store_failed
                          else NewsRunStatus.OK if day["published"] else NewsRunStatus.IDLE}
        if live and day["published"]:
            summary["publish_dispatch"] = _dispatch_publish()
        if (live and window["upto"] and not (a.dataset or a.models_dir)
                and (day.get("model_errors") or day.get("store_errors"))):
            # A story the model service never let us finish, or the store
            # never saved, is not a story judged: keep the window so the next
            # run sees its signals again.
            summary["cursor_advanced"] = False
        elif live and window["upto"] and not (a.dataset or a.models_dir):
            # Only a full run that got this far closes its window; a failed
            # one leaves it for the next run (cooldown + used signal keys stop
            # a story it did publish from being written twice). A --dataset
            # run saw only some datasets, so it leaves the cursor alone.
            summary |= _advance(store, window, run_id)
        rc = 1 if store_failed else 0
    except LLMUnavailable as e:
        summary |= {"status": NewsRunStatus.LLM_UNAVAILABLE, "error": str(e)[:300]}
        rc = 1
    except Exception as e:
        log.exception("news run crashed")
        summary |= {"status": NewsRunStatus.FAILED, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        rc = 1
    finally:
        if tables is not None:
            tables.close()
    if rc and live and stored and "publish_dispatch" not in summary:
        # The day crashed after storing some stories: put those on the site now.
        summary |= {"published": stored, "publish_dispatch": _dispatch_publish()}
    if llm is not None:
        summary["cost_usd"], summary["llm_calls"] = round(llm.cost_usd, 4), llm.calls
    print(json.dumps(summary, ensure_ascii=False, default=str))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
