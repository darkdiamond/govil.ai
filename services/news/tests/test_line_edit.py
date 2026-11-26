"""The delete-only line edit: cuts only, and never at the cost of a story."""
from __future__ import annotations

import json

import pytest

from services.news import line_edit
from services.news.tests.test_llm_pipeline import FILLER, FakeLLM, _day, _draft


@pytest.mark.parametrize("old, new, ok", [
    ("הלינות זינקו ב-{f1}, הגבוה מאז 2019, ורוב הגידול מתיירים.", "הלינות זינקו ב-{f1}, הגבוה מאז 2019.", True),
    ("הלינות זינקו ב-{f1}, הגבוה מאז 2019, ורוב הגידול מתיירים.", "רוב הגידול מתיירים.", True),   # a dropped ו
    ("הלינות זינקו ב-{f1}.", "", True),                                       # the paragraph goes
    ("הלינות זינקו ב-{f1}.", "הלינות זינקו ב-{f2}.", False),                   # a swapped number
    ("הלינות זינקו ב-{f1}.", "הלינות קפצו ב-{f1}.", False),                    # a reworded verb
    ("הלינות זינקו ב-{f1} בגלל החג.", "בגלל החג הלינות זינקו ב-{f1}.", False),  # reordered
    ("הלינות זינקו ב-{f1}.", "הלינות זינקו ב-{f1} בגלל החג.", False),          # an added claim
    ("לפי [[נתוני הלמ\"ס|ds:x]] הלינות זינקו.", "לפי [[נתוני הלמ\"ס|ds:x]] הלינות זינקו.", True),
])
def test_is_cut(old, new, ok):
    assert line_edit.is_cut(old, new) is ok


class _Editor:
    def __init__(self, reply):
        self.reply = reply

    def chat_json(self, messages, **kw):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


DRAFT = {"headline": "כותרת", "dek": "תקציר", "blocks": [
    {"type": "p", "text": "הלינות זינקו ב-{f1}. הנתונים הבאים יאפשרו לבחון אם המגמה נמשכת."},
    {"type": "stat", "fact": "f1"},
    {"type": "p", "text": "הישראלים לנו פחות."},
]}


def _ok_check(d):
    return {"blocks": d["blocks"]}, []


def _pass(core):
    return {"verdict": "pass"}


def test_a_cut_that_passes_the_gates_and_the_critic_is_applied():
    llm = _Editor({"edits": [{"block": 0, "text": "הלינות זינקו ב-{f1}."}]})
    core, info = line_edit.edit(llm, DRAFT, check=_ok_check, critique=_pass)
    assert core["blocks"][0]["text"] == "הלינות זינקו ב-{f1}." and core["blocks"][1]["type"] == "stat"
    assert info["status"] == "applied" and info["words_after"] < info["words_before"]


def test_an_emptied_paragraph_is_removed():
    llm = _Editor({"edits": [{"block": 2, "text": ""}]})
    core, _ = line_edit.edit(llm, DRAFT, check=_ok_check, critique=_pass)
    assert [b["type"] for b in core["blocks"]] == ["p", "stat"]


@pytest.mark.parametrize("reply, status", [
    ({"edits": [{"block": 0, "text": "הלינות קפצו ב-{f1}."}]}, "unchanged"),   # a rewrite is refused
    ({"edits": [{"block": 1, "text": ""}]}, "unchanged"),                     # the stat block isn't prose
    ({"edits": []}, "unchanged"),
    ({"nope": 1}, "malformed"),
    (ValueError("no JSON"), "error"),
])
def test_nothing_usable_keeps_the_original(reply, status):
    core, info = line_edit.edit(_Editor(reply), DRAFT, check=_ok_check, critique=_pass)
    assert core is None and info["status"] == status


def test_a_cut_the_gates_or_the_critic_refuse_keeps_the_original():
    llm = _Editor({"edits": [{"block": 0, "text": "הלינות זינקו."}]})
    core, info = line_edit.edit(llm, DRAFT, check=lambda d: ({}, ["body length 12 words"]), critique=_pass)
    assert core is None and info["status"] == "gates"
    core, info = line_edit.edit(llm, DRAFT, check=_ok_check,
                                critique=lambda c: {"verdict": "revise", "issues": ["חסר בסיס השוואה"]})
    assert core is None and info["status"] == "critic"


class _EditingLLM(FakeLLM):
    """The pipeline's fake, plus a line editor that cuts one FILLER sentence."""

    def chat_json(self, messages, **kw):
        if messages[0]["content"].startswith("You are the line editor"):
            paras = json.loads(messages[1]["content"])["paragraphs"]
            last = paras[-1]
            return {"edits": [{"block": last["block"], "text": last["text"].replace(FILLER, "", 1)}]}
        return super().chat_json(messages, **kw)


def test_the_line_edit_runs_only_when_switched_on(tmp_path, monkeypatch):
    monkeypatch.delenv("NEWS_LINE_EDIT", raising=False)
    llm = _EditingLLM([_draft()], critic=("pass",))
    out, _, _ = _day(tmp_path / "off", llm)
    doc = json.loads((tmp_path / "off" / out["published"][0] / "article.json").read_text(encoding="utf-8"))
    assert "line_edit" not in doc and len(llm.critic_msgs) == 1

    monkeypatch.setenv("NEWS_LINE_EDIT", "on")
    llm = _EditingLLM([_draft()], critic=("pass", "pass"))
    out, _, _ = _day(tmp_path / "on", llm)
    doc = json.loads((tmp_path / "on" / out["published"][0] / "article.json").read_text(encoding="utf-8"))
    assert doc["line_edit"]["status"] == "applied" and len(llm.critic_msgs) == 2
    assert doc["line_edit"]["words_after"] < doc["line_edit"]["words_before"]
