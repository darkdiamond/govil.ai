"""The desk's stock phrases: word runs many of our recent articles share.

A phrase that is fine in one article reads as a template across the site
("אחד ההסברים האפשריים" opened a hedge in 13 of 28 live articles,
2026-11-26). Each run lists the 2-4 word phrases that at least `min_docs`
articles and `min_share` of the recent ones use, minus names (a publisher, a
dataset title, a unit) and phrases that start or end on a function word. The
writer is told to vary them, and `gates.check` allows each one once.

Pure and deterministic: articles in, phrases out. `run` reads the articles
(`store.recent_bodies`) and fails soft to no list.
"""
from __future__ import annotations

import re
from collections import Counter

from services.page_builder.recipe_lib.govlib import fmt

_TOKEN = re.compile(r"[א-ת][א-ת\"״'׳]*|\S")
_HEB = re.compile(r"[א-ת]")
# A phrase may not start or end on one of these: "עלייה של", "עמד על" are
# grammar, not voice.
FUNCTION = frozenset((
    "של", "על", "את", "עם", "אל", "או", "גם", "עד", "כל", "כי", "אם", "לא", "זה", "זו", "זאת",
    "הם", "הן", "היה", "היו", "הייתה", "אשר", "ב", "ל", "מ", "ה", "ו", "ש", "כ", "בין", "לפי",
    "מול", "אחרי", "לפני", "מתוך", "אך", "רק", "כמו", "יותר", "פחות", "כך", "הוא", "היא",
))
# Names and units the desk must repeat: a publisher, a unit of measure. The
# text is cut at each one before counting, so no phrase holds or straddles a
# name ("נתוני הלשכה" is the publisher's name, not a voice), and a phrase
# inside one (part of a title written short) is dropped.
NAMES = ("הלשכה המרכזית לסטטיסטיקה", "בנק ישראל", "נקודות אחוז", "נקודת אחוז", "מנוכה עונתיות",
         "מנוכי עונתיות", "מנוכה העונתיות", "מנוכי העונתיות", "מיליון שקל", "מיליארד שקל",
         "מיליוני שקלים", "מיליארדי שקלים")
_MONTH = re.compile(rf"^[ובלמה]{{0,2}}(?:{'|'.join(fmt.MONTHS_HE + ['מרס'])})$")


def article_text(a: dict) -> list[str]:
    """An article's prose, one string per paragraph or subhead."""
    out = []
    for b in a.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "p":
            out.append("".join(str(r.get("v") or "") for r in b.get("runs") or [] if isinstance(r, dict)))
        elif b.get("type") == "h2":
            out.append(str(b.get("text") or ""))
    return out


def _runs(text: str, names: list[str]) -> list[list[str]]:
    """Runs of Hebrew words: a number, a punctuation mark, a Latin word or a
    name ends a run, so no phrase crosses a figure, a sentence break or a name."""
    text = " ".join(text.split())
    for n in names:
        text = text.replace(n, " | ")
    runs, cur = [], []
    for t in _TOKEN.findall(text):
        if _HEB.match(t):
            cur.append(t)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _ok(gram: tuple[str, ...]) -> bool:
    return (gram[0] not in FUNCTION and gram[-1] not in FUNCTION
            and not any(_MONTH.match(w) for w in gram))


def stock_phrases(articles: list[dict], *, names=(), min_docs: int = 4, min_share: float = 0.3,
                  limit: int = 15) -> list[str]:
    """The phrases (2-4 words) that at least `min_docs` articles, and at least
    `min_share` of them, use; most shared first. A shorter phrase inside a
    chosen longer one with no more articles of its own is dropped. `names`:
    titles and publishers that may repeat (the catalog's)."""
    docs = [art for art in articles if isinstance(art, dict)]
    if len(docs) < min_docs:
        return []
    need = max(min_docs, int(min_share * len(docs) + 0.999))
    # longest first: a title that holds a shorter name is cut whole
    skip = sorted({" ".join(n.split()) for n in (*NAMES, *names) if n and n.strip()},
                  key=len, reverse=True)
    df: Counter = Counter()
    for a in docs:
        grams = set()
        for para in article_text(a):
            for run in _runs(para, skip):
                for n in (2, 3, 4):
                    grams.update(tuple(run[i:i + n]) for i in range(len(run) - n + 1))
        df.update(g for g in grams if _ok(g))
    picked: list[tuple[str, int]] = []
    for gram, k in sorted(df.items(), key=lambda x: (-x[1], -len(x[0]), x[0])):
        if k < need:
            break
        phrase = " ".join(gram)
        if any(phrase in n for n in skip):
            continue
        if any(phrase in p and k <= pk for p, pk in picked):
            continue
        picked.append((phrase, k))
    return [p for p, _ in picked[:limit]]
