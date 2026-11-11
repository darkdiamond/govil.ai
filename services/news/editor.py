"""Stage 3: which of today's signals, if any, become articles.

Deterministic filters first (cooldown: a dataset written about in the last
`cooldown_days`; a signal key already published), then the model as editor
(prompts/editor.md) picks ≤ `max_briefs` stories, bundling related signals
across datasets. Its output is validated against the input: unknown keys are
dropped, a brief's datasets always include its signals' datasets.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from services.shared.states import ArticleKind

from .signals import Signal
from .store import published_at

log = logging.getLogger(__name__)
PROMPT = Path(__file__).with_name("prompts") / "editor.md"
FEATURES_PROMPT = Path(__file__).with_name("prompts") / "features.md"


def eligible(signals: list[Signal], recent: list[dict], *, cooldown_days: int,
             now: datetime | None = None) -> list[Signal]:
    """Signals whose dataset isn't in cooldown and whose key isn't used yet.
    Only news articles start a cooldown: an explainer or a digest line about a
    dataset must not keep its next real move off the page (their signal keys
    still count as used)."""
    now = now or datetime.now(UTC)
    used = {k for a in recent for k in a.get("signal_keys") or []}
    cool = set()
    for a in recent:
        if (a.get("kind") or ArticleKind.NEWS) != ArticleKind.NEWS:
            continue
        ts = published_at(a)
        if ts and now - ts < timedelta(days=cooldown_days):
            cool.update(a.get("dataset_ids") or [])
    return [s for s in signals if s.key not in used and s.dataset_id not in cool]


def _compact(s: Signal, catalog: dict) -> dict:
    cat = catalog.get(s.dataset_id, {})
    facts = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.facts.items()}
    return {
        "key": s.key, "dataset_id": s.dataset_id, "dataset": cat.get("title"),
        "publisher": cat.get("organization"), "series": s.label or s.series_path,
        "series_path": s.series_path, "period": s.period, "value": s.value, "flags": s.flags,
        "facts": facts, "demand": s.demand, "score": s.score,
        "linked": [{"dataset_id": lk["dataset_id"],
                    "dataset": (catalog.get(lk["dataset_id"]) or {}).get("title"),
                    "series": lk.get("label") or lk["series_path"], "r": lk["r"], "lag": lk["lag"],
                    "lag_unit": lk["lag_unit"], "why": lk.get("why_he")} for lk in s.links],
    }


def choose(llm, signals: list[Signal], catalog: dict, recent: list[dict], *,
           max_briefs: int, today: str) -> tuple[list[dict], list[dict]]:
    """(briefs, skipped). Each brief: signal_keys, dataset_ids, angle_he, why_now_he, questions, signals."""
    if not signals or max_briefs <= 0:
        return [], []
    by_key = {s.key: s for s in signals}
    system = PROMPT.read_text(encoding="utf-8").replace("{max_briefs}", str(max_briefs))
    user = {
        "today": today,
        "signals": [_compact(s, catalog) for s in signals],
        "recent_articles": [{"headline": a.get("headline"), "dataset_ids": a.get("dataset_ids"),
                             "published_at": str(a.get("published_at"))[:10]} for a in recent[:40]],
    }
    import json

    out = llm.chat_json([{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)}],
                        temperature=0.3)
    briefs, seen_ds = [], set()
    for b in out.get("briefs") or []:
        keys = [k for k in b.get("signal_keys") or [] if k in by_key]
        if not keys:
            continue
        ds = list(dict.fromkeys([by_key[k].dataset_id for k in keys] +
                                [d for d in b.get("dataset_ids") or [] if d in catalog]))
        if seen_ds & set(ds[:1]):
            continue  # one story per lead dataset per day
        seen_ds.update(ds[:1])
        briefs.append({"kind": ArticleKind.NEWS, "signal_keys": keys, "dataset_ids": ds,
                       "angle_he": str(b.get("angle_he") or ""), "why_now_he": str(b.get("why_now_he") or ""),
                       "questions": [str(q) for q in b.get("questions") or []][:6],
                       "signals": [by_key[k] for k in keys]})
        if len(briefs) >= max_briefs:
            break
    return briefs, [s for s in out.get("skipped") or [] if isinstance(s, dict)]


def choose_features(llm, candidates: list[dict], recent: list[dict], *, max_briefs: int,
                    today: str) -> list[dict]:
    """Explainer briefs (strongest first) from `features.candidates`. Each brief's
    lead dataset is a candidate; extra datasets must be candidates too. Its
    signal key `feature:<lead>:<YYYY-MM>` makes the used-key dedup cover it."""
    if not candidates or max_briefs <= 0:
        return []
    import json

    known = {c["dataset_id"] for c in candidates}
    system = FEATURES_PROMPT.read_text(encoding="utf-8").replace("{max_briefs}", str(max_briefs))
    user = {
        "today": today,
        "candidates": candidates,
        "recent_articles": [{"headline": a.get("headline"), "dataset_ids": a.get("dataset_ids"),
                             "kind": a.get("kind") or "news",
                             "published_at": str(a.get("published_at"))[:10]} for a in recent[:40]],
    }
    out = llm.chat_json([{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)}],
                        temperature=0.5)
    briefs, leads = [], set()
    for b in out.get("briefs") or []:
        ds = list(dict.fromkeys(d for d in b.get("dataset_ids") or [] if d in known))
        if not ds or ds[0] in leads:
            continue
        leads.add(ds[0])
        briefs.append({"kind": ArticleKind.FEATURE, "signal_keys": [f"feature:{ds[0]}:{today[:7]}"],
                       "dataset_ids": ds, "angle_he": str(b.get("angle_he") or ""),
                       "why_now_he": str(b.get("why_now_he") or ""),
                       "questions": [str(q) for q in b.get("questions") or []][:6], "signals": []})
        if len(briefs) >= max_briefs:
            break
    return briefs
