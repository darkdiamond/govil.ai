"""OpenRouter client (mock transport) and the whole day — editor → writer →
gates → critic → image → store — with a scripted fake model."""
from __future__ import annotations

import base64
import io
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from PIL import Image

from services.news import run
from services.news.fetch import Page
from services.news.llm import LLMError, LLMUnavailable, OpenRouter, parse_json
from services.news.series import extract_series
from services.news.signals import Signal
from services.news.store import LocalArticles, join, split

FIX = Path(__file__).parent / "fixtures" / "models"


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://or.test")


def _ok(message, cost=0.01):
    return httpx.Response(200, json={"choices": [{"message": message}], "usage": {"cost": cost}})


def test_retries_then_succeeds_and_sums_cost():
    calls = []

    def h(req):
        calls.append(json.loads(req.content))
        return httpx.Response(503) if len(calls) < 3 else _ok({"role": "assistant", "content": "שלום"}, 0.02)

    llm = OpenRouter("k", client=_client(h), sleep=lambda s: None)
    assert llm.chat([{"role": "user", "content": "x"}])["content"] == "שלום"
    assert len(calls) == 3 and llm.cost_usd == pytest.approx(0.02) and calls[0]["usage"] == {"include": True}


def test_reasoning_effort_sent_on_chat_not_on_image():
    bodies = []

    def h(req):
        bodies.append(json.loads(req.content))
        if "modalities" in bodies[-1]:
            return _ok({"images": [{"image_url": {"url": "data:image/png;base64,AA=="}}]})
        return _ok({"role": "assistant", "content": "x"})

    llm = OpenRouter("k", client=_client(h), sleep=lambda s: None)
    llm.chat([{"role": "user", "content": "x"}], reasoning_effort="high")
    llm.chat([{"role": "user", "content": "x"}], reasoning_effort=None)
    llm.image("p")
    assert bodies[0]["reasoning"] == {"effort": "high"}
    assert "reasoning" not in bodies[1] and "reasoning" not in bodies[2]


@pytest.mark.parametrize("status", [401, 402, 403])
def test_refused_key_is_unavailable_not_retried(status):
    n = []
    llm = OpenRouter("k", client=_client(lambda r: n.append(1) or httpx.Response(status, text="limit")),
                     sleep=lambda s: None)
    with pytest.raises(LLMUnavailable):
        llm.chat([{"role": "user", "content": "x"}])
    assert len(n) == 1


def test_gives_up_after_retries():
    llm = OpenRouter("k", client=_client(lambda r: httpx.Response(500)), sleep=lambda s: None)
    with pytest.raises(LLMError):
        llm.chat([{"role": "user", "content": "x"}])


def test_image_and_web_search():
    png = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(png, "PNG")
    data_url = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()

    def h(req):
        body = json.loads(req.content)
        if body.get("modalities"):
            assert body["image_config"] == {"aspect_ratio": "16:9"}
            return _ok({"role": "assistant", "images": [{"image_url": {"url": data_url}}]})
        assert body["plugins"][0]["id"] == "web"
        return _ok({"role": "assistant", "content": "…", "annotations": [
            {"type": "url_citation", "url_citation": {"url": "https://a.example/x", "title": "A", "content": "c"}},
            {"type": "url_citation", "url_citation": {"url": "https://a.example/x", "title": "A"}}]})

    llm = OpenRouter("k", client=_client(h))
    assert llm.image("a house") == png.getvalue()
    assert llm.web_search("q") == [{"url": "https://a.example/x", "title": "A", "snippet": "c"}]


def test_parse_json_tolerates_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_store_split_join_roundtrip():
    doc = {"slug": "s", "status": "published", "headline": "h", "blocks": [{"type": "p"}],
           "charts": [{"table": [["a", 1], ["b", 2]]}], "sources": [], "ledger": {"facts": []}}
    stored = split(doc)
    assert "charts" not in stored and json.loads(stored["body_json"])["charts"][0]["table"][1] == ["b", 2]
    assert join(stored) == doc


# ── the whole day, scripted ─────────────────────────────────────────────

FILLER = ("הנתון החודשי מראה שינוי בהיקף הפעילות לעומת התקופה המקבילה אשתקד ולעומת החודש הקודם, "
          "והוא מצטרף למגמה שנמשכת כבר כמה חודשים בשוק המשכנתאות בישראל. ")
QUOTE = "הוועדה המוניטרית החליטה להותיר את הריבית ללא שינוי"
MORT, RATE = "boi-mortgage-rates", "boi-interest-rate"


def _draft(typed_number=False):
    extra = " נרשמו 1,200 עסקאות." if typed_number else ""
    return {
        "headline": "היקף המשכנתאות בספטמבר עמד על {f1:num2} מיליארד שקל",
        "dek": "נתוני בנק ישראל מראים שינוי לעומת החודש הקודם ולעומת השנה שעברה.",
        "slug_en": "mortgage-volume-september", "dataset_ids": [MORT, RATE],
        "tags": ["משכנתאות"], "image_brief": "a house and a key", "image_alt_he": "איור של בית",
        "blocks": [
            {"type": "p", "text": "לפי [[נתוני בנק ישראל|ds:" + MORT + "]] נלקחו משכנתאות בהיקף של "
                                  "{f1:num2} מיליארד שקל." + extra + " " + FILLER * 3},
            {"type": "chart", "chart": "c1"},
            {"type": "h2", "text": "ההקשר"},
            {"type": "p", "text": "[[לפי הודעת הריבית|s1]] הוועדה לא שינתה את [[הריבית|ds:" + RATE + "]]. "
                                  + FILLER * 10},
        ],
        "charts": [{"id": "c1", "type": "line", "title": "היקף משכנתאות", "unit": "מיליארדי ש\"ח",
                    "series": [{"dataset_id": MORT, "series_path": "volume.y", "name": "היקף"}]}],
        "sources": [{"id": "s1", "quote": QUOTE}],
    }


class FakeLLM:
    """Scripted by role: editor / writer turns / critic / image."""

    def __init__(self, drafts, critic=("pass",)):
        self.drafts, self.critic = list(drafts), list(critic)
        self.cost_usd, self.calls, self.writer_msgs = 0.0, 0, []
        self.turn = 0

    def chat_json(self, messages, **kw):
        sys_ = messages[0]["content"]
        if sys_.startswith("You are the news editor"):
            keys = [s["key"] for s in json.loads(messages[1]["content"])["signals"]]
            return {"briefs": [{"signal_keys": keys[:1], "dataset_ids": [MORT, RATE],
                                "angle_he": "היקף המשכנתאות", "why_now_he": "נתון חדש",
                                "questions": []}], "skipped": []}
        v = self.critic.pop(0)
        return {"verdict": v, "scores": {k: 5 if v == "pass" else 2 for k in
                                         ("news", "framing", "voice", "risk_free", "sourcing")},
                "issues": ["ניסוח כללי"] if v != "pass" else [], "fixes": []}

    def chat(self, messages, tools=None, **kw):
        self.writer_msgs = messages
        self.turn += 1
        if self.turn == 1:
            return {"role": "assistant", "content": "", "reasoning_details": [{"sig": "x"}],
                    "tool_calls": [{"id": "t1", "type": "function", "function": {
                        "name": "fetch_url", "arguments": json.dumps({"url": "https://www.boi.org.il/r"})}}]}
        d = self.drafts.pop(0)
        return {"role": "assistant", "content": "", "tool_calls": [{"id": f"t{self.turn}", "type": "function",
                "function": {"name": "submit_article", "arguments": json.dumps({"article": d}, ensure_ascii=False)}}]}

    def image(self, prompt, **kw):
        buf = io.BytesIO()
        Image.new("RGB", (1600, 900), "#0b3668").save(buf, "PNG")
        return buf.getvalue()

    def web_search(self, q):
        return []


def _fetcher(url):
    return Page(url, "הודעת הריבית", "פתיח ארוך. " * 30 + QUOTE + " בשלב זה. " + "סוף. " * 20)


def _world():
    series = {d: extract_series(json.loads((FIX / f"{d}.json").read_text(encoding="utf-8")), d,
                                date(2026, 11, 9)) for d in (MORT, RATE)}
    models = {d: json.loads((FIX / f"{d}.json").read_text(encoding="utf-8")) for d in (MORT, RATE)}
    s = next(x for x in series[MORT] if x.path == "volume.y")
    p, v = s.complete[-1]
    sig = Signal(MORT, "volume.y", "y", "M", p.label, p.end.isoformat(), v, ["unusual_change"], 2.0,
                 {"previous": {"period": s.complete[-2][0].label, "value": s.complete[-2][1]},
                  "yoy_pct": -9.1})
    cat = {MORT: {"title": "משכנתאות", "page_slug": MORT, "tags": ["משכנתאות"], "organization": "בנק ישראל"},
           RATE: {"title": "ריבית", "page_slug": RATE, "tags": ["ריבית"], "organization": "בנק ישראל"}}
    return series, models, sig, cat


def _day(tmp_path, llm, **kw):
    series, models, sig, cat = _world()
    store = LocalArticles(tmp_path)
    out = run.write_day(llm, ranked=[sig], series_by_ds=series, models=models, catalog=cat,
                        vocab={"משכנתאות", "ריבית"}, store=store, today=date(2026, 11, 9),
                        run_id="r1", fetcher=_fetcher, **kw)
    return out, store, sig


def test_day_publishes_a_two_dataset_article(tmp_path):
    llm = FakeLLM([_draft()])
    out, _store, sig = _day(tmp_path, llm)
    assert out["published"] == ["mortgage-volume-september"], out
    doc = json.loads((tmp_path / "mortgage-volume-september" / "article.json").read_text(encoding="utf-8"))
    assert doc["dataset_ids"] == [MORT, RATE] and doc["signal_keys"] == [sig.key]
    assert doc["byline"] == "מערכת govil.ai" and doc["hero"]["kind"] == "illustration"
    assert doc["hero"]["caption"] == "איור" and set(doc["hero"]["sizes"]) == {"16x9", "4x3", "1x1", "webp"}
    assert (tmp_path / "mortgage-volume-september" / doc["hero"]["sizes"]["16x9"]).stat().st_size > 1000
    assert doc["sources"][0]["quote"] == QUOTE and "{" not in doc["headline"]
    # the writer saw the seeded lead facts, and kept Gemini's thought signature
    assert "f1" in llm.writer_msgs[1]["content"]
    assert any(m.get("reasoning_details") for m in llm.writer_msgs if m["role"] == "assistant")
    # cooldown: the same signal is not written twice
    out2, _, _ = _day(tmp_path, FakeLLM([_draft()]))
    assert out2["candidates"] == 0 and out2["published"] == []


def test_gate_failure_gets_one_revision(tmp_path):
    out, _store, _ = _day(tmp_path, FakeLLM([_draft(typed_number=True), _draft()]))
    assert out["published"] == ["mortgage-volume-september"]


def test_twice_failing_draft_is_rejected_and_recorded(tmp_path):
    out, _store, _ = _day(tmp_path, FakeLLM([_draft(typed_number=True)] * 3))
    assert out["published"] == [] and out["rejected"][0]["reason"] == "gates"
    rej = json.loads(next((tmp_path / "_rejected").glob("*.json")).read_text(encoding="utf-8"))
    assert any("typed numbers" in p for p in rej["problems"])


def test_critic_kill_rejects(tmp_path):
    out, _, _ = _day(tmp_path, FakeLLM([_draft()], critic=("kill",)))
    assert out["published"] == [] and out["rejected"][0]["reason"] == "critic_kill"


def test_no_images_uses_chart_card(tmp_path):
    out, _, _ = _day(tmp_path, FakeLLM([_draft()]), images=False)
    doc = json.loads((tmp_path / out["published"][0] / "article.json").read_text(encoding="utf-8"))
    assert doc["hero"]["kind"] == "chart" and doc["hero"]["caption"] is None


def test_live_mode_is_off_unless_enabled(monkeypatch, capsys):
    monkeypatch.delenv("NEWS_PUBLISH", raising=False)
    assert run.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "disabled"
