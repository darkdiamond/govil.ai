"""What a misbehaving model must not be able to do: spin forever, crash the
day with malformed JSON, or misalign a chart."""
from __future__ import annotations

import json
from datetime import date

from services.news import charts
from services.news.ledger import Ledger
from services.news.series import extract_series
from services.news.tests.test_llm_pipeline import FakeLLM, _day, _draft
from services.news.writer import MAX_TURNS


class LoopingLLM(FakeLLM):
    """Never makes progress: bad JSON in every submission."""

    def chat(self, messages, tools=None, **kw):
        self.calls += 1
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "x", "type": "function",
                "function": {"name": "submit_article", "arguments": "{not json"}}]}


def test_writer_turn_limit_ends_a_spinning_session(tmp_path):
    llm = LoopingLLM([])
    out, _store, _ = _day(tmp_path, llm)
    assert out["rejected"][0]["reason"] == "turn_limit"
    assert llm.calls == MAX_TURNS


class OverBudgetLLM(FakeLLM):
    """Keeps calling a data tool after only submit_article is offered."""

    def chat(self, messages, tools=None, **kw):
        self.calls += 1
        self.offered = [t["function"]["name"] for t in tools]
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "x", "type": "function",
                "function": {"name": "get_series", "arguments": json.dumps(
                    {"dataset_id": "boi-mortgage-rates", "series_path": "volume.y"})}}]}


def test_tools_not_offered_are_not_run(tmp_path):
    llm = OverBudgetLLM([])
    out, _store, _ = _day(tmp_path, llm, max_tool_calls=2)
    assert out["rejected"][0]["reason"] == "turn_limit"
    assert llm.offered == ["submit_article"]


def test_malformed_draft_is_a_problem_not_a_crash(tmp_path):
    bad = _draft() | {"charts": ["c1"], "tags": [{"x": 1}], "blocks": ["just text"]}
    out, _store, _ = _day(tmp_path, FakeLLM([bad] * 3))
    assert out["rejected"][0]["reason"] == "gates"
    rej = json.loads(next((tmp_path / "_rejected").glob("*.json")).read_text(encoding="utf-8"))
    assert any("must be an object" in p for p in rej["problems"])


def test_one_story_crashing_does_not_stop_the_day(tmp_path, monkeypatch):
    import services.news.run as run_mod

    def boom(*a, **k):
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(run_mod, "write", boom)
    out, _store, _ = _day(tmp_path, FakeLLM([]))
    assert out["rejected"][0]["reason"] == "error" and out["published"] == []


def test_bar_axis_includes_zero_and_line_legend_at_bottom():
    led = Ledger()
    fs = [led.add(v, label=str(v), provenance=f"p{v}").id for v in (62.7, 54.8, 54.2)]
    bar = charts.resolve({"id": "b", "type": "bar", "title": "t",
                          "bars": [{"label": "x", "fact": f} for f in fs]}, {}, led)
    assert bar["option"]["yAxis"]["min"] == 0 and "scale" not in bar["option"]["yAxis"]
    neg = [led.add(v, label=str(v), provenance=f"n{v}").id for v in (-3.0, -5.0)]
    bar2 = charts.resolve({"id": "b2", "type": "bar", "title": "t",
                           "bars": [{"label": "x", "fact": f} for f in neg]}, {}, led)
    assert bar2["option"]["yAxis"]["max"] == 0
    a = extract_series({"charts": {"c": {"x": [f"2026-{m:02d}" for m in range(1, 8)],
                                         "y": [1, 2, 3, 4, 5, 6, 7], "z": [7, 6, 5, 4, 3, 2, 1]}}},
                       "A", date(2026, 11, 1))
    line = charts.resolve({"id": "l", "type": "line", "title": "t", "series": [
        {"dataset_id": "A", "series_path": "c.y"}, {"dataset_id": "A", "series_path": "c.z"}]},
        {"A": a}, Ledger())
    assert line["option"]["legend"]["bottom"] == 0


def test_chart_aligns_periods_with_different_labels():
    a = extract_series({"charts": {"c": {"x": [f"2026-{m:02d}" for m in range(1, 8)],
                                         "y": [1, 2, 3, 4, 5, 6, 7]}}}, "A", date(2026, 11, 1))
    months = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי"]
    b = extract_series({"charts": {"c": {"x": [f"{m} 2026" for m in months],
                                         "y": [7, 6, 5, 4, 3, 2, 1]}}}, "B", date(2026, 11, 1))
    out = charts.resolve({"id": "c1", "type": "line", "title": "t", "series": [
        {"dataset_id": "A", "series_path": "c.y"}, {"dataset_id": "B", "series_path": "c.y"}]},
        {"A": a, "B": b}, Ledger())
    assert len(out["option"]["xAxis"]["data"]) == 7
    assert [s["data"][0] for s in out["option"]["series"]] == [1, 7]


class ParallelCallsLLM:
    """One turn asking for many tool calls at once, then gives up."""

    def __init__(self, n):
        self.n, self.turn, self.messages = n, 0, []

    def chat(self, messages, tools=None, **kw):
        self.turn += 1
        self.messages = messages
        if self.turn == 1:
            return {"role": "assistant", "content": "", "tool_calls": [
                {"id": str(i), "type": "function", "function": {
                    "name": "calc", "arguments": json.dumps({"op": "abs", "a": "f1"})}}
                for i in range(self.n)]}
        return {"role": "assistant", "content": "done"}


def test_tool_budget_holds_within_one_turn():
    from services.news.tools import Toolbox
    from services.news.writer import write

    tb = Toolbox(ledger=Ledger(), series={}, models={}, catalog={})
    tb.ledger.add(1, label="x", provenance="p")
    llm = ParallelCallsLLM(50)
    out = write(llm, tb, {"signals": [], "angle_he": "", "why_now_he": "", "questions": [],
                          "dataset_ids": []}, catalog={}, vocab=set(), today="2026-11-10",
                max_tool_calls=5)
    assert len(tb.log) == 5 and out.tool_calls == 5
    assert out.reason == "tool_budget"
    # every call still got an answer, so the transcript stays well-formed
    tool_msgs = [m for m in llm.messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == [str(i) for i in range(50)]
    assert all("tool budget used up" in m["content"] for m in tool_msgs[5:])
