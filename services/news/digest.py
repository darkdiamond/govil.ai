"""The weekly digest: one article bundling the week's small moves.

Each live run pools the signals the editor saw but didn't write about
(`store.pool`: `signal_pool/` in the news database). On the digest weekday
(`NEWS_DIGEST_WEEKDAY`, Python weekday, 4 = Friday), `brief` picks the
strongest of the last 7 days' pooled signals: not suspect-incomplete, not
revised or gone from today's series since pooled, not already used, dataset
not in cooldown, one per dataset, at most MAX_ITEMS.
Fewer than MIN_ITEMS means no digest that week. Deterministic, no LLM: the
writer gets the items as seeded signals, like any event brief.
"""
from __future__ import annotations

import dataclasses
from datetime import date

from services.shared.states import ArticleKind

from .editor import eligible
from .signals import Signal

MIN_ITEMS, MAX_ITEMS = 4, 6
_FIELDS = {f.name for f in dataclasses.fields(Signal)}


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"digest:{y}-W{w:02d}"


def pool_items(cands: list[Signal], published_keys: set[str], skipped: list[dict],
               run_id: str) -> list[dict]:
    """The editor's candidates no published article used, with its skip
    reason when given. A brief the critic rejected stays in: "not worth an
    article" can still be worth a line."""
    why = {s.get("key"): str(s.get("reason") or "")[:300] for s in skipped}
    return [{"signal": s.to_dict(), "run_id": run_id, "skip_reason": why.get(s.key)}
            for s in cands if s.key not in published_keys]


def _signal(d: dict) -> Signal | None:
    try:
        return Signal(**{k: v for k, v in d.items() if k in _FIELDS})
    except TypeError:
        return None


def _still_current(s: Signal, series_by_ds: dict) -> bool:
    """Whether today's series still holds every point the pooled signal was
    computed from (its period, the previous and year-ago ones) with the same
    value. The writer seeds the period values from today's series but the
    changes from the pooled facts: a value revised since (CBS revises) would
    print beside a change computed from the old one. Values round-trip
    exactly through JSON and Firestore (doubles), so equality is exact."""
    ser = next((x for x in series_by_ds.get(s.dataset_id) or [] if x.path == s.series_path), None)
    if ser is None:
        return False
    now = {p.label: v for p, v in ser.points}
    recorded = [(s.period, s.value)] + [
        (ref.get("period"), ref.get("value")) for ref in (s.facts.get("previous"), s.facts.get("year_ago"))
        if isinstance(ref, dict)]
    return all(lbl in now and now[lbl] == v for lbl, v in recorded)


def brief(pool: list[dict], recent: list[dict], *, today: date, cooldown_days: int,
          series_by_ds: dict, catalog: dict) -> dict | None:
    """This week's digest brief, or None (already written, or too few items)."""
    wk = week_key(today)
    if any(wk in (a.get("signal_keys") or []) for a in recent):
        return None
    best: dict[str, Signal] = {}
    for it in pool:
        s = _signal(it.get("signal") or {})
        if s is None or s.facts.get("suspect_incomplete") or not _still_current(s, series_by_ds):
            continue
        if s.flags == ["new_release"]:
            continue  # "nothing unusual" is not a move worth a line in a roundup
        if s.key not in best or s.score > best[s.key].score:
            best[s.key] = s
    sigs = eligible(sorted(best.values(), key=lambda s: (-s.score, s.key)), recent,
                    cooldown_days=cooldown_days)
    items, seen = [], set()
    for s in sigs:
        if s.dataset_id in seen:
            continue
        seen.add(s.dataset_id)
        items.append(s)
        if len(items) >= MAX_ITEMS:
            break
    if len(items) < MIN_ITEMS:
        return None
    titles = [(catalog.get(s.dataset_id) or {}).get("title") or s.dataset_id for s in items]
    return {"kind": ArticleKind.DIGEST, "signal_keys": [s.key for s in items] + [wk],
            "dataset_ids": [s.dataset_id for s in items],
            "angle_he": "סיכום השבוע בנתונים: " + ", ".join(titles),
            "why_now_he": "שינויים קטנים מהשבוע שלא קיבלו כתבה משלהם, כל אחד במשפט או שניים.",
            "questions": [], "signals": items}
