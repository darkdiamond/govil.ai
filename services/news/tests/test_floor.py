"""The daily floor: explainers fill a day event news left short."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from services.news import features, gates, run
from services.news.publish_news import write_news
from services.news.store import LocalArticles
from services.news.tests.test_llm_pipeline import (
    MORT,
    RATE,
    FakeLLM,
    _draft,
    _fetcher,
    _world,
)
from services.shared.states import ArticleKind


class FloorLLM(FakeLLM):
    """FakeLLM plus the features editor; the writer's first turn also reads a
    series, so a brief with no seeded signals still has fact f1."""

    def __init__(self, drafts, critic=("pass",), feature_leads=((MORT, RATE),)):
        super().__init__(drafts, critic)
        self.feature_leads, self.feature_calls, self.critic_bodies = feature_leads, [], []
        self.offered: list[set] = []
        self.web = True

    def chat_json(self, messages, **kw):
        sys_ = messages[0]["content"]
        if sys_.startswith("You are the features editor"):
            self.feature_calls.append(json.loads(messages[1]["content"]))
            return {"briefs": [{"dataset_ids": list(ds), "angle_he": "כמה משכנתאות נלקחות",
                                "why_now_he": "עונת רכישות", "questions": []}
                               for ds in self.feature_leads]}
        if not sys_.startswith("You are the news editor"):
            self.critic_bodies.append(messages[1]["content"])
        return super().chat_json(messages, **kw)

    def chat(self, messages, tools=None, **kw):
        names = {t["function"]["name"] for t in tools or []}
        self.offered.append(names)
        # Drafts are written without a fetched source when web tools are off
        # (explainers), so they don't cite s1. Decided per brief, at its first
        # writer turn (its first user message is the brief).
        if len(messages) == 2:
            self.web = "fetch_url" in names
        if not self.web and self.drafts and self.drafts[0].get("sources"):
            self.drafts[0] = _no_source(self.drafts[0])
        if self.turn == 0:
            self.turn = 1
            self.writer_msgs = messages
            calls = [{"id": "g1", "type": "function", "function": {
                "name": "get_series", "arguments": json.dumps({"dataset_id": MORT,
                                                                "series_path": "volume.y", "last": 1})}}]
            if self.web:
                calls.append({"id": "t1", "type": "function", "function": {
                    "name": "fetch_url", "arguments": json.dumps({"url": "https://www.boi.org.il/r"})}})
            return {"role": "assistant", "content": "", "tool_calls": calls}
        return super().chat(messages, tools=tools, **kw)


def _no_source(d: dict) -> dict:
    d = json.loads(json.dumps(d))
    for b in d["blocks"]:
        if "text" in b:
            b["text"] = b["text"].replace("[[לפי הודעת הריבית|s1]]", "לפי הודעת הריבית")
    d["sources"] = []
    return d


DEMAND = {MORT: {"impressions": 500}, RATE: {"impressions": 50}}


def _day(tmp_path, llm, *, ranked=(), seed=None, **kw):
    series, models, sig, cat = _world()
    store = LocalArticles(tmp_path, seed=seed)
    out = run.write_day(llm, ranked=list(ranked) or [], series_by_ds=series, models=models,
                        catalog=cat, vocab={"משכנתאות", "ריבית"}, store=store,
                        today=date(2026, 11, 9), run_id="r1", fetcher=_fetcher,
                        demand_by_id=DEMAND, images=False, **kw)
    return out, sig


def _doc(tmp_path, slug):
    return json.loads((tmp_path / slug / "article.json").read_text(encoding="utf-8"))


def test_no_floor_by_default(tmp_path):
    llm = FloorLLM([_draft()])
    out, _ = _day(tmp_path, llm)
    assert out["published"] == [] and "fill" not in out and llm.feature_calls == []


def test_empty_day_is_filled_with_an_explainer(tmp_path):
    llm = FloorLLM([_draft()])
    out, _ = _day(tmp_path, llm, min_per_day=1)
    assert out["fill"]["published"] == 1 and out["fill"]["attempts"] == 1, out
    doc = _doc(tmp_path, out["published"][0])
    assert doc["kind"] == ArticleKind.FEATURE and doc["signal_keys"] == ["feature:" + MORT + ":2026-11"]
    # the editor saw the demand-ranked candidates; the writer and critic saw the kind
    assert [c["dataset_id"] for c in llm.feature_calls[0]["candidates"]] == [MORT, RATE]
    assert json.loads(llm.writer_msgs[1]["content"])["kind"] == "feature"
    assert llm.critic_bodies[-1].startswith("KIND: feature")
    # an explainer is written from our data alone: no web tools offered
    assert all(not ({"web_search", "fetch_url"} & names) for names in llm.offered)
    # the next run that day: the floor is met, nothing more is written
    llm2 = FloorLLM([_draft()])
    out2, _ = _day(tmp_path, llm2, min_per_day=1)
    assert "fill" not in out2 and llm2.feature_calls == []


def test_event_story_meets_the_floor(tmp_path):
    sig = _world()[2]
    llm = FloorLLM([_draft()])
    out, _ = _day(tmp_path, llm, ranked=[sig], min_per_day=1)
    assert len(out["published"]) == 1 and "fill" not in out
    assert _doc(tmp_path, out["published"][0])["kind"] == ArticleKind.NEWS


def test_article_earlier_today_meets_the_floor(tmp_path):
    seed = [{"slug": "x", "headline": "h", "dataset_ids": ["other"], "signal_keys": ["k"],
             "published_at": datetime.now(UTC).isoformat()}]
    llm = FloorLLM([_draft()])
    out, _ = _day(tmp_path, llm, seed=seed, min_per_day=1)
    assert "fill" not in out and llm.feature_calls == []


def test_fill_attempts_are_capped_and_rejections_recorded(tmp_path):
    llm = FloorLLM([_draft()] * 4, critic=("kill",) * 4, feature_leads=((MORT,), (RATE,), ("unknown",)))
    out, _ = _day(tmp_path, llm, min_per_day=1, fill_attempts=2)
    assert out["published"] == [] and out["fill"] == {
        "kind": "feature", "need": 1, "candidates": 2, "briefs": 2, "attempts": 2, "published": 0}
    assert {r["kind"] for r in out["rejected"]} == {"feature"} and len(out["rejected"]) == 2
    assert len(list((tmp_path / "_rejected").glob("*.json"))) == 2
    # the next day's fill leaves both rejected leads out instead of retrying them
    llm2 = FloorLLM([_draft()])
    out2, _ = _day(tmp_path, llm2, min_per_day=1)
    assert out2["fill"]["candidates"] == 0 and llm2.feature_calls == []


def test_fill_does_not_repeat_this_runs_event_dataset(tmp_path):
    sig = _world()[2]   # the event story draws on MORT and RATE, our only two datasets
    llm = FloorLLM([_draft()] * 2, feature_leads=((MORT,), (RATE,)))
    out, _ = _day(tmp_path, llm, ranked=[sig], min_per_day=2)
    assert len(out["published"]) == 1 and out["fill"]["need"] == 1
    assert out["fill"]["candidates"] == 0 and llm.feature_calls == []


def test_unpublished_article_does_not_meet_the_floor(tmp_path):
    seed = [{"slug": "x", "status": "unpublished", "dataset_ids": ["other"], "signal_keys": ["k"],
             "published_at": datetime.now(UTC).isoformat()}]
    out, _ = _day(tmp_path, FloorLLM([_draft()]), seed=seed, min_per_day=1)
    assert out["fill"]["published"] == 1


def test_only_news_articles_start_a_dataset_cooldown():
    from services.news.editor import eligible

    sig = _world()[2]
    now = datetime.now(UTC).isoformat()
    for kind, kept in (("feature", True), ("digest", True), ("news", False), (None, False)):
        recent = [{"kind": kind, "dataset_ids": [sig.dataset_id], "signal_keys": [], "published_at": now}]
        assert bool(eligible([sig], recent, cooldown_days=21)) is kept, kind


def test_floor_respects_max_per_day(tmp_path):
    llm = FloorLLM([_draft()])
    out, _ = _day(tmp_path, llm, min_per_day=5, max_per_day=0)
    assert "fill" not in out


def test_published_today_uses_the_israel_date():
    late = datetime(2026, 11, 10, 22, 30, tzinfo=UTC)   # 00:30 on 11-11 in Israel
    assert run.published_today([{"published_at": late.isoformat()}], date(2026, 11, 11)) == 1
    assert run.published_today([{"published_at": late.isoformat()}], date(2026, 11, 10)) == 0
    assert run.published_today([{"published_at": "garbage"}, {}], date(2026, 11, 11)) == 0


# ── candidates ──────────────────────────────────────────────────────────

def test_candidates_rank_by_demand_and_skip_cooldown_and_empty():
    series, models, _sig, cat = _world()
    models = dict(models) | {"bare": {"charts": {}}, "uncatalogued": {"kpis": {"a": {"value": 1}}}}
    cat = dict(cat) | {"bare": {"title": "ריק"}}
    now = datetime(2026, 11, 9, tzinfo=UTC)
    out = features.candidates(catalog=cat, models=models, series=series, demand_by_id=DEMAND,
                              recent=[], cooldown_days=60, now=now)
    assert [c["dataset_id"] for c in out] == [MORT, RATE]
    assert out[0]["impressions_28d"] == 500 and out[0]["series"][0]["latest"]["period"]
    recent = [{"dataset_ids": [MORT], "published_at": (now - timedelta(days=59)).isoformat()},
              {"dataset_ids": [RATE], "published_at": (now - timedelta(days=61)).isoformat()}]
    out = features.candidates(catalog=cat, models=models, series=series, demand_by_id=DEMAND,
                              recent=recent, cooldown_days=60, now=now)
    assert [c["dataset_id"] for c in out] == [RATE]


def test_critique_defaults_to_news_kind():
    seen = []

    class L:
        def chat_json(self, messages, **kw):
            seen.append(messages[1]["content"])
            return {"verdict": "kill", "scores": {}, "issues": [], "fixes": []}

    core = {"headline": "h", "dek": "d", "blocks": [], "charts": [], "sources": []}
    gates.critique(L(), core)
    assert seen[0].startswith("KIND: news")


def test_publisher_carries_kind(tmp_path):
    base = {"status": "published", "headline": "h", "dek": "d", "published_at": "2026-11-09T06:00:00+00:00",
            "updated_at": "2026-11-09T06:00:00+00:00", "blocks": [], "charts": [], "sources": []}
    write_news(tmp_path, [base | {"slug": "a", "kind": "feature"}, base | {"slug": "b"}], datasets={})
    idx = {a["slug"]: a for a in json.loads((tmp_path / "news" / "index.json").read_text())["articles"]}
    assert idx["a"]["kind"] == "feature" and idx["b"]["kind"] == "news"
    assert json.loads((tmp_path / "news" / "a" / "article.json").read_text())["kind"] == "feature"


def test_explainers_get_their_own_tool_budget(tmp_path, monkeypatch):
    seen = []
    real = run.write

    def spy(llm, tb, brief, **kw):
        seen.append((brief["kind"], kw["max_tool_calls"]))
        return real(llm, tb, brief, **kw)

    monkeypatch.setattr(run, "write", spy)
    sig = _world()[2]
    _day(tmp_path, FloorLLM([_draft()] * 3, critic=("kill",) * 3), ranked=[sig], min_per_day=2,
         max_tool_calls=25, feature_tool_calls=35, fill_attempts=1)
    assert seen[0] == ("news", 25) and seen[1] == ("feature", 35)
