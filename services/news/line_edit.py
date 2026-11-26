"""A delete-only line edit after the copy chief passes a draft.

Expert edits of AI prose are mostly cuts (the LAMP study behind "AI-Slop to
AI-Polish", arXiv 2504.07532). The editor (prompts/line_edit.md) may only
delete words from the writer's paragraphs, so it can't add a claim or a
number: `is_cut` checks that every paragraph it returns is the old one with
words removed (a dangling "ו" and the punctuation at a cut excepted). The
edited draft then goes through `gates.check` and the copy chief again; if
either finds anything, or the editor's reply is unusable, the original
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

log = logging.getLogger(__name__)
PROMPTS = Path(__file__).with_name("prompts")
_EDGE = ",.;:"


def enabled() -> bool:
    return os.environ.get("NEWS_LINE_EDIT", "").strip().lower() in ("1", "true", "yes", "on")


def _words(text: str) -> list[str]:
    return [w.strip(_EDGE) for w in str(text).split() if w.strip(_EDGE)]


def is_cut(old: str, new: str) -> bool:
    """`new` is `old` with words deleted: its words are a subsequence of
    old's, compared without the punctuation at their edges, where a word may
    also have lost a leading "ו" (the next clause's conjunction, once the
    clause before it is gone)."""
    ow, nw = _words(old), _words(new)
    i = 0
    for w in nw:
        while i < len(ow) and not (ow[i] == w or ow[i] == "ו" + w):
            i += 1
        if i == len(ow):
            return False
        i += 1
    return True


def _n(text: str) -> int:
    return len(re.findall(r"\S+", text))


def edit(llm, draft: dict, *, check, critique) -> tuple[dict | None, dict]:
    """(the edited core, or None to keep the original; a record of what
    happened). `check(draft)` → (core, problems) and `critique(core)` → the
    copy chief's verdict, both bound by the caller to the story's context."""
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
        return None, info | {"status": "error"}
    edits = reply.get("edits") if isinstance(reply, dict) else None
    if not isinstance(edits, list):
        return None, info | {"status": "malformed"}
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
        return None, info | {"status": "unchanged"}
    edited = {**draft, "blocks": [b for b in new_blocks if b is not None]}
    info["words_after"] = sum(_n(b["text"]) for b in edited["blocks"]
                              if isinstance(b, dict) and b.get("type") == "p")
    core, problems = check(edited)
    if problems:
        return None, info | {"status": "gates", "problems": problems[:5]}
    verdict = critique(core)
    if verdict.get("verdict") != "pass":
        return None, info | {"status": "critic", "issues": (verdict.get("issues") or [])[:5]}
    return core, info | {"status": "applied"}
