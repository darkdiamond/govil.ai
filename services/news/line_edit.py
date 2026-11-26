"""A delete-only line edit after the copy chief passes a draft.

Expert edits of AI prose are mostly cuts (the LAMP study behind "AI-Slop to
AI-Polish", arXiv 2504.07532). The editor (prompts/line_edit.md) may only
delete words from the writer's paragraphs, so it can't add a claim or a
number: `is_cut` checks that every paragraph it returns is the old one with
words removed (a dangling "ו" and the punctuation at a cut excepted). A cut
could still flip a claim by dropping only its "לא" or its "כנראה", so a
negation or a hedge may go only with its whole sentence. The edited draft
then goes through `gates.check` and the copy chief again; if either finds
anything, the editor's reply is unusable, or anything raises, the original
stands. Nothing about it can reject a story.

Off unless NEWS_LINE_EDIT is on: one or two more model calls per accepted
story.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from services.shared.states import LineEditStatus

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).with_name("prompts")
_EDGE = ",.;:"
_END = (".", "?", "!")
# A negation or a hedge: dropping one alone turns "לא עלה" into "עלה" or a
# likely reason into a stated cause.
PROTECTED = frozenset((
    "לא", "אין", "אינו", "אינה", "אינם", "אינן", "ללא", "בלי", "טרם", "מעולם",
    "ייתכן", "יתכן", "כנראה", "אולי", "ככל", "הנראה", "עשוי", "עשויה", "עשויים", "עשויות",
    "ספק", "משוער", "משוערת",
))
_PREFIX = "ובלמהשכ"


def enabled() -> bool:
    return os.environ.get("NEWS_LINE_EDIT", "").strip().lower() in ("1", "true", "yes", "on")


def _words(text: str) -> list[tuple[str, int]]:
    """(word without edge punctuation, its sentence number) for each word."""
    out, sent = [], 0
    for raw in str(text).split():
        w = raw.strip(_EDGE)
        if w:
            out.append((w, sent))
        if raw.rstrip("\"'״”)").endswith(_END):
            sent += 1
    return out


def _protected(w: str) -> bool:
    if w in PROTECTED:
        return True
    k = 0
    while k < 3 and k < len(w) - 1 and w[k] in _PREFIX:
        k += 1
        if w[k:] in PROTECTED:
            return True
    return False


def is_cut(old: str, new: str) -> bool:
    """`new` is `old` with words deleted: its words are a subsequence of
    old's, compared without the punctuation at their edges, where a word may
    also have lost a leading "ו" (the next clause's conjunction, once the
    clause before it is gone). A negation or hedge may be deleted only with
    every other word of its sentence."""
    ow, nw = _words(old), [w for w, _ in _words(new)]
    kept, i = set(), 0
    for w in nw:
        while i < len(ow) and not (ow[i][0] == w or ow[i][0] == "ו" + w):
            i += 1
        if i == len(ow):
            return False
        kept.add(i)
        i += 1
    alive = {ow[j][1] for j in kept}
    return not any(j not in kept and sent in alive and _protected(w)
                   for j, (w, sent) in enumerate(ow))


def _n(text: str) -> int:
    return len(re.findall(r"\S+", text))


def edit(llm, draft: dict, *, check, critique) -> tuple[dict | None, dict, dict | None]:
    """(the edited core, or None to keep the original; a record of what
    happened; the copy chief's verdict on the cut, when it passed).
    `check(draft)` → (core, problems) and `critique(core)` → the copy chief's
    verdict, both bound by the caller to the story's context. Never raises."""
    try:
        return _edit(llm, draft, check=check, critique=critique)
    except Exception as e:  # noqa: BLE001 - an edit is optional: any failure keeps the draft
        log.warning("news line edit failed: %s: %s", type(e).__name__, str(e)[:200])
        return None, {"status": LineEditStatus.ERROR, "error": type(e).__name__}, None


def _edit(llm, draft: dict, *, check, critique) -> tuple[dict | None, dict, dict | None]:
    blocks = draft.get("blocks") or []
    paras = [{"block": i, "text": str(b.get("text") or "")}
             for i, b in enumerate(blocks) if isinstance(b, dict) and b.get("type") == "p"]
    before = sum(_n(p["text"]) for p in paras)
    info: dict = {"words_before": before}
    try:
        reply = llm.chat_json(
            [{"role": "system", "content": (PROMPTS / "line_edit.md").read_text(encoding="utf-8")},
             {"role": "user", "content": json.dumps(
                 {"headline": draft.get("headline"), "dek": draft.get("dek"), "paragraphs": paras},
                 ensure_ascii=False)}], temperature=0.2)
    except Exception as e:  # noqa: BLE001 - an edit is optional: any failure keeps the draft
        log.warning("news line edit: model call failed: %s", e)
        return None, info | {"status": LineEditStatus.ERROR}, None
    edits = reply.get("edits") if isinstance(reply, dict) else None
    if not isinstance(edits, list):
        return None, info | {"status": LineEditStatus.MALFORMED}, None
    old = {p["block"]: p["text"] for p in paras}
    new_blocks, applied, refused = list(blocks), 0, 0
    for e in edits:
        i, text = (e.get("block"), e.get("text")) if isinstance(e, dict) else (None, None)
        if not isinstance(i, int) or i not in old or not isinstance(text, str):
            refused += 1
            continue
        if text == old[i]:
            continue
        if not is_cut(old[i], text):   # a reworded or added word: the whole edit is refused
            refused += 1
            continue
        new_blocks[i] = None if not text.strip() else {**blocks[i], "text": text}
        applied += 1
    info |= {"applied": applied, "refused": refused}
    if not applied:
        return None, info | {"status": LineEditStatus.UNCHANGED}, None
    edited = {**draft, "blocks": [b for b in new_blocks if b is not None]}
    info["words_after"] = sum(_n(str(b.get("text") or "")) for b in edited["blocks"]
                              if isinstance(b, dict) and b.get("type") == "p")
    core, problems = check(edited)
    if problems:
        return None, info | {"status": LineEditStatus.GATES, "problems": problems[:5]}, None
    verdict = critique(core)
    if verdict.get("verdict") != "pass":
        return None, info | {"status": LineEditStatus.CRITIC,
                             "issues": (verdict.get("issues") or [])[:5]}, None
    return core, info | {"status": LineEditStatus.APPLIED}, verdict
