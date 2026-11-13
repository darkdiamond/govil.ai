"""What a misbehaving model must not be able to do: spin forever, crash the
day with malformed JSON, or misalign a chart."""
from __future__ import annotations

import json
from datetime import date

import pytest

from services.news import charts
from services.news.ledger import Ledger
from services.news.series import extract_series
from services.news.tests.test_llm_pipeline import FakeLLM, _day, _draft
from services.news.writer import GATE_REVISIONS, MAX_TURNS


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
    out, _store, _ = _day(tmp_path, FakeLLM([bad] * (GATE_REVISIONS + 1)))
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


class _FlakyStore:
    """LocalArticles whose publish fails on the listed calls (1-based)."""

    def __init__(self, inner, fail_on):
        self.inner, self.fail_on, self.calls = inner, set(fail_on), 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def publish(self, doc, files):
        self.calls += 1
        if self.calls in self.fail_on:
            raise RuntimeError("gcs upload failed")
        self.inner.publish(doc, files)


class _PerStoryLLM(FakeLLM):
    """FakeLLM whose writer script restarts with each story."""

    def chat(self, messages, tools=None, **kw):
        if len(messages) <= 2:
            self.turn = 0
        return super().chat(messages, tools=tools, **kw)


def _two_story_day(tmp_path, fail_on, monkeypatch):
    import services.news.run as run_mod
    from services.news.store import LocalArticles
    from services.news.tests.test_llm_pipeline import _fetcher, _world

    series, models, sig, cat = _world()
    briefs = [{"signal_keys": [s.key], "dataset_ids": [s.dataset_id], "angle_he": "a",
               "why_now_he": "b", "questions": [], "signals": [s]} for s in (sig, sig)]
    monkeypatch.setattr(run_mod, "choose", lambda *a, **k: (briefs, []))
    store = _FlakyStore(LocalArticles(tmp_path), fail_on)
    llm = _PerStoryLLM([_draft(), _draft()], critic=("pass", "pass"))
    out = run_mod.write_day(llm, ranked=[sig], series_by_ds=series, models=models, catalog=cat,
                            vocab={"משכנתאות", "ריבית"}, store=store,
                            today=date(2026, 11, 9), run_id="r1", fetcher=_fetcher, images=False)
    return out, store


def test_store_failure_fails_only_that_story(tmp_path, monkeypatch):
    out, store = _two_story_day(tmp_path, {1}, monkeypatch)
    assert store.calls == 2
    assert len(out["published"]) == 1
    assert out["store_errors"] == 1 and out["model_errors"] == 0
    assert out["rejected"][0]["reason"] == "error"


def test_store_failure_after_a_stored_story_keeps_it(tmp_path, monkeypatch):
    out, store = _two_story_day(tmp_path, {2}, monkeypatch)
    assert store.calls == 2
    assert out["published"] == ["mortgage-volume-september"] and out["store_errors"] == 1


class _RejectDownStore(_FlakyStore):
    """LocalArticles whose reject write always fails (Firestore down, or a doc too large)."""

    def reject(self, doc):
        raise RuntimeError("firestore: document too large")


def test_failed_reject_write_does_not_cost_the_day(tmp_path, monkeypatch):
    import services.news.run as run_mod
    from services.news.store import LocalArticles
    from services.news.tests.test_llm_pipeline import _fetcher, _world

    series, models, sig, cat = _world()
    briefs = [{"signal_keys": [s.key], "dataset_ids": [s.dataset_id], "angle_he": "a",
               "why_now_he": "b", "questions": [], "signals": [s]} for s in (sig, sig)]
    monkeypatch.setattr(run_mod, "choose", lambda *a, **k: (briefs, []))
    store = _RejectDownStore(LocalArticles(tmp_path), set())
    llm = _PerStoryLLM([_draft(), _draft()], critic=("kill", "pass"))
    out = run_mod.write_day(llm, ranked=[sig], series_by_ds=series, models=models, catalog=cat,
                            vocab={"משכנתאות", "ריבית"}, store=store,
                            today=date(2026, 11, 9), run_id="r1", fetcher=_fetcher, images=False)
    assert out["rejected"][0]["reason"] == "critic_kill"
    assert out["published"] == ["mortgage-volume-september"]


def _editor_signal():
    from services.news.tests.test_llm_pipeline import _world

    _series, _models, sig, cat = _world()
    return sig, cat


class _ReplyLLM:
    def __init__(self, reply):
        self.reply = reply

    def chat_json(self, messages, **kw):
        return self.reply


def test_editor_skips_wrong_shaped_briefs():
    from services.news.editor import choose

    sig, cat = _editor_signal()
    reply = {"briefs": ["a string", None, 3,
                        {"signal_keys": [["nested"], {"k": 1}, sig.key], "dataset_ids": [["x"], {}, 5],
                         "angle_he": "זווית"}],
             "skipped": []}
    briefs, _ = choose(_ReplyLLM(reply), [sig], cat, [], max_briefs=3, today="2026-11-09")
    assert len(briefs) == 1 and briefs[0]["signal_keys"] == [sig.key]
    assert briefs[0]["dataset_ids"] == [sig.dataset_id]


def test_features_editor_skips_wrong_shaped_briefs():
    from services.news.editor import choose_features

    cands = [{"dataset_id": "A"}, {"dataset_id": "B"}]
    reply = {"briefs": ["text", [1], {"dataset_ids": [["A"], {"B": 1}, "B", "A"]}]}
    briefs = choose_features(_ReplyLLM(reply), cands, [], max_briefs=3, today="2026-11-09")
    assert [b["dataset_ids"] for b in briefs] == [["B", "A"]]


def _gate(mutate):
    from services.news import gates
    from services.news.tests.test_ledger_gates import _draft as gate_draft
    from services.news.tests.test_ledger_gates import _setup

    series, led, cat, f1 = _setup()
    d = gate_draft(f1)
    mutate(d)
    _, problems = gates.check(d, ledger=led, series_by_ds=series, catalog=cat, vocab={"משכנתאות"})
    return problems


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.__setitem__("slug_en", 12345678), "slug_en"),
    (lambda d: d.__setitem__("slug_en", ["mortgage-volume"]), "slug_en"),
    (lambda d: d.__setitem__("dataset_ids", "boi-mortgage-rates"), "dataset_ids: must be a list"),
    (lambda d: d.__setitem__("dataset_ids", 7), "dataset_ids: must be a list"),
    (lambda d: d["blocks"][4].__setitem__("fact", ["f1"]), "block 4"),
    (lambda d: d["blocks"][4].__setitem__("fact", {"id": "f1"}), "block 4"),
    (lambda d: d["blocks"][1].__setitem__("chart", {"id": "c1"}), "block 1"),
    (lambda d: d["sources"][0].__setitem__("id", ["s1"]), "sources"),
    (lambda d: d["charts"].append(dict(d["charts"][0], title="עוד גרף")), "duplicate chart id"),
])
def test_wrong_typed_draft_fields_are_problems_not_crashes(mutate, needle):
    problems = _gate(mutate)
    assert any(needle in p for p in problems), problems
