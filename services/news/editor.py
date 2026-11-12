"""Stage 3: which of today's signals, if any, become articles.

Deterministic filters first (cooldown: a dataset written about in the last
`cooldown_days`; a signal key already published), then the model as editor
(prompts/editor.md) picks ≤ `max_briefs` stories, bundling related signals
across datasets. Its output is validated against the input: unknown keys are
dropped, a brief's datasets always include its signals' datasets. A brief on
a `new_dataset` signal alone becomes an explainer brief (`kind: feature`, at
most one per call); bundled with real signals, that key is dropped.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from services.shared.states import ArticleKind

from .signals import Signal, is_new_dataset
from .store import published_at

log = logging.getLogger(__name__)
PROMPT = Path(__file__).with_name("prompts") / "editor.md"
FEATURES_PROMPT = Path(__file__).with_name("prompts") / "features.md"


# An event story the gates or the critic rejected stays off the editor's list
# this long (`rejected_signal_keys`), so hourly runs don't re-roll the critic.
REJECT_DAYS = 7


def rejected_signal_keys(rejects: list[dict]) -> set[str]:
    """Signal keys of recently rejected event stories (`store.recent_rejects`).
    A story lost to an error (the model service, a crash: reason "error") was
    never judged, so its keys stay eligible; explainer and digest rejects have
    their own rules (features.rejected_leads, the digest's week key)."""
    out: set[str] = set()
    for r in rejects:
        if (r.get("kind") or ArticleKind.NEWS) != ArticleKind.NEWS or r.get("reason") == "error":
            continue
        out.update(_strs((r.get("brief") or {}).get("signal_keys")))
    return out


def eligible(signals: list[Signal], recent: list[dict], *, cooldown_days: int,
             now: datetime | None = None, rejected_keys: set[str] = frozenset()) -> list[Signal]:
    """Signals whose dataset isn't in cooldown and whose key isn't used yet
    (nor in `rejected_keys`, see `rejected_signal_keys`).
    Only news articles start a cooldown: an explainer or a digest line about a
    dataset must not keep its next real move off the page (their signal keys
    still count as used)."""
    now = now or datetime.now(UTC)
    used = {k for a in recent for k in a.get("signal_keys") or []} | set(rejected_keys)
    cool = set()
    for a in recent:
        if (a.get("kind") or ArticleKind.NEWS) != ArticleKind.NEWS:
            continue
        ts = published_at(a)
        if ts and now - ts < timedelta(days=cooldown_days):
            cool.update(a.get("dataset_ids") or [])
    return [s for s in signals if s.key not in used and s.dataset_id not in cool]


def _strs(x) -> list[str]:
    """The string entries of a model-given list (a nested list or object is skipped)."""
    return [i for i in x if isinstance(i, str)] if isinstance(x, list) else []


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
           max_briefs: int, today: str,
           published_today: dict | None = None) -> tuple[list[dict], list[dict]]:
    """(briefs, skipped). Each brief: signal_keys, dataset_ids, angle_he, why_now_he, questions, signals.
    `published_today` ({count, news_count, stories: [{title, kind, lead_dataset}]},
    run.py `todays_stories`) goes to the editor as `published_today`: what
    earlier runs already printed on this Israel date."""
    if not signals or max_briefs <= 0:
        return [], []
    by_key = {s.key: s for s in signals}
    system = PROMPT.read_text(encoding="utf-8").replace("{max_briefs}", str(max_briefs))
    user = {
        "today": today,
        "signals": [_compact(s, catalog) for s in signals],
        "recent_articles": [{"headline": a.get("headline"), "dataset_ids": a.get("dataset_ids"),
                             "published_at": str(a.get("published_at"))[:10]} for a in recent[:40]],
        "published_today": published_today or {"count": 0, "news_count": 0, "stories": []},
    }
    import json

    out = llm.chat_json([{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)}],
                        temperature=0.3)
    briefs, seen_ds, new_ds = [], set(), False
    for b in out.get("briefs") or []:
        if not isinstance(b, dict):
            continue
        keys = [k for k in _strs(b.get("signal_keys")) if k in by_key]
        # A new dataset is its own story (an explainer): bundled with real
        # signals, the brief is their event story and the new-dataset key drops.
        event_keys = [k for k in keys if not is_new_dataset(by_key[k])]
        keys = event_keys or keys[:1]
        if not keys:
            continue
        ds = list(dict.fromkeys([by_key[k].dataset_id for k in keys] +
                                [d for d in _strs(b.get("dataset_ids")) if d in catalog]))
        if seen_ds & set(ds[:1]):
            continue  # one story per lead dataset per day
        if not event_keys:
            if new_ds:
                continue  # at most one new-dataset story per call
            new_ds = True
        seen_ds.update(ds[:1])
        questions = [str(q) for q in b.get("questions") or []][:6]
        if event_keys:
            briefs.append({"kind": ArticleKind.NEWS, "signal_keys": keys, "dataset_ids": ds,
                           "angle_he": str(b.get("angle_he") or ""),
                           "why_now_he": str(b.get("why_now_he") or ""),
                           "questions": questions, "signals": [by_key[k] for k in keys]})
        else:
            # Written as an explainer from our data alone (no seeded series);
            # the feature key makes the explainers' used-key dedup cover it.
            briefs.append({"kind": ArticleKind.FEATURE, "new_dataset": True,
                           "signal_keys": keys + [f"feature:{ds[0]}:{today[:7]}"],
                           "dataset_ids": ds, "angle_he": str(b.get("angle_he") or ""),
                           "why_now_he": str(b.get("why_now_he") or ""),
                           "questions": [NEW_DATASET_NOTE, *questions][:6], "signals": []})
        if len(briefs) >= max_briefs:
            break
    return briefs, [s for s in out.get("skipped") or [] if isinstance(s, dict)]


# The writer's first question on a new-dataset explainer: nobody has seen this
# dataset before, so the article introduces it before any finding.
NEW_DATASET_NOTE = ("זהו מאגר חדש שטרם הוצג באתר: לפתוח במה הוא מכיל ומי מפרסם אותו, "
                    "ואז להראות מה הקורא יכול לבדוק בו עכשיו")


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
        if not isinstance(b, dict):
            continue
        ds = list(dict.fromkeys(d for d in _strs(b.get("dataset_ids")) if d in known))
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
