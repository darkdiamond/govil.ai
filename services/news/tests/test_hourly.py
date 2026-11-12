"""Hourly news runs: the quiet window and the lease, the cheap idle probe, the
per-run / per-day budgets, once-a-day duties and no re-rolls of rejected stories."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar

import pytest

from services.news import llm as llm_mod
from services.news import run
from services.news import store as store_mod
from services.news.editor import eligible, rejected_signal_keys
from services.news.store import LocalArticles
from services.news.tests.test_digest import _day as _digest_day
from services.news.tests.test_floor import DEMAND, FloorLLM
from services.news.tests.test_llm_pipeline import _draft, _fetcher, _world
from services.news.tests.test_window import _Db, _transact

CURSOR = (datetime.now(UTC) - timedelta(hours=3)).strftime("%Y%m%dT%H%M%SZ")


def _boom(what):
    def f(*_a, **_k):
        raise AssertionError(f"{what} must not be called")
    return f


class _Articles:
    """The live article store, in memory and shared across instances."""
    cursor: str | None = None
    daily: ClassVar[dict] = {}
    recent_docs: ClassVar[list] = []
    reads: ClassVar[list] = []
    constructed = 0

    def __init__(self, **_kw):
        _Articles.constructed += 1
        self.db = object()

    def read_cursor(self):
        _Articles.reads.append("cursor")
        return _Articles.cursor

    def advance_cursor(self, upto, *, run_id):
        _Articles.cursor = upto
        return True

    def recent(self, days=90):
        _Articles.reads.append("recent")
        return list(_Articles.recent_docs)

    def read_daily(self):
        _Articles.reads.append("daily")
        return dict(_Articles.daily)

    def mark_duty(self, duty, il_date, *, run_id):
        _Articles.daily[f"{duty}_attempt"] = il_date


@pytest.fixture
def live(monkeypatch):
    _Articles.cursor, _Articles.daily, _Articles.recent_docs = CURSOR, {}, []
    _Articles.reads, _Articles.constructed = [], 0
    for k in ("QUIET_WINDOW", "NEWS_MIN_PER_DAY", "NEWS_DIGEST_WEEKDAY", "NEWS_DIGEST_HOUR",
              "NEWS_FLOOR_HOUR", "NEWS_FLOOR_HOUR_FRIDAY", "NEWS_DAY_BUDGET", "NEWS_MAX_PER_RUN",
              "NEWS_MAX_PER_DAY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEWS_PUBLISH", "live")
    monkeypatch.setattr(store_mod, "FirestoreArticles", _Articles)
    lease = {"acquire": True, "calls": []}

    def acquire(client, path, holder, ttl):
        lease["calls"].append(("acquire", path, ttl))
        if isinstance(lease["acquire"], Exception):
            raise lease["acquire"]
        return lease["acquire"]

    monkeypatch.setattr(run.lease, "acquire", acquire)
    monkeypatch.setattr(run.lease, "release", lambda c, path, h: lease["calls"].append(("release", path)))
    # Nothing past the gates may run unless a test allows it.
    monkeypatch.setattr(run, "GcsSnapshots", _boom("GCS"))
    monkeypatch.setattr(run.catalog_mod, "load_catalog", _boom("the catalog"))
    monkeypatch.setattr(run.demand_mod, "fetch_page_rows", _boom("Search Console"))
    monkeypatch.setattr(llm_mod, "OpenRouter", _boom("the model client"))
    monkeypatch.setattr(run, "write_day", _boom("write_day"))
    probes = []
    monkeypatch.setattr(run, "_renders_since", lambda since: probes.append(since) or False)
    return lease, probes


def _full_path(monkeypatch, tmp_path):
    """Let a run past the probe: local snapshots, a quiet model, an empty day."""
    from services.news.snapshots import LocalSnapshots

    monkeypatch.setattr(run, "GcsSnapshots", lambda *_a: LocalSnapshots(tmp_path))
    monkeypatch.setattr(llm_mod, "OpenRouter", lambda: type("L", (), {"cost_usd": 0, "calls": 0})())
    seen = []
    monkeypatch.setattr(run, "write_day", lambda *_a, **k: seen.append(k) or {
        "published": [], "candidates": 0, "briefs": 0, "rejected": [], "skipped": []})
    return seen


def _summary(capsys):
    return json.loads(capsys.readouterr().out.splitlines()[-1])


# ── quiet window + lease ────────────────────────────────────────────────

def test_quiet_window_touches_nothing(live, monkeypatch, capsys):
    lease, probes = live
    monkeypatch.setattr(run.schedule, "in_quiet_window", lambda *_a, **_k: True)
    assert run.main([]) == 0
    assert _summary(capsys) == {"type": "news_summary", "status": "skipped_quiet"}
    assert _Articles.constructed == 0 and lease["calls"] == [] and probes == []
    assert _Articles.cursor == CURSOR


def test_quiet_window_reads_the_env(live, monkeypatch, capsys):
    il = datetime.now(UTC).astimezone(run.IL_TZ)
    days = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    monkeypatch.setenv("QUIET_WINDOW", f"{days[il.weekday()]}0-{days[(il.weekday() + 1) % 7]}0")
    assert run.main([]) == 0
    assert _summary(capsys)["status"] == "skipped_quiet"


def test_held_lock_skips_and_reads_nothing(live, capsys):
    lease, probes = live
    lease["acquire"] = False
    assert run.main([]) == 0
    assert _summary(capsys) == {"type": "news_summary", "status": "skipped_overlap"}
    assert _Articles.reads == [] and probes == [] and _Articles.cursor == CURSOR
    assert lease["calls"] == [("acquire", "news_state/lock", 3900.0)]   # not released: not ours


def test_lease_is_released_and_its_ttl_comes_from_env(live, monkeypatch, capsys):
    lease, _ = live
    monkeypatch.setenv("NEWS_LEASE_TTL_S", "120")
    assert run.main([]) == 0
    assert _summary(capsys)["lease"] == "held"
    assert lease["calls"] == [("acquire", "news_state/lock", 120.0), ("release", "news_state/lock")]


def test_lease_released_when_the_run_crashes(live, monkeypatch, tmp_path, capsys):
    lease, _ = live
    _full_path(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "_renders_since", lambda _s: True)
    monkeypatch.setattr(run, "write_day", _boom("crash"))
    assert run.main(["--no-catalog", "--no-tables"]) == 1
    assert lease["calls"][-1] == ("release", "news_state/lock")


def test_lease_error_runs_without_it(live, capsys):
    lease, _ = live
    lease["acquire"] = RuntimeError("firestore down")
    assert run.main([]) == 0
    s = _summary(capsys)
    assert s["status"] == "idle" and s["lease"] == "error"
    assert [c[0] for c in lease["calls"]] == ["acquire"]


@pytest.mark.parametrize("extra", [["--dataset", "A"], ["--since-hours", "3"]])
def test_partial_runs_take_no_lease(live, monkeypatch, tmp_path, capsys, extra):
    lease, probes = live
    monkeypatch.setattr(run.schedule, "in_quiet_window", lambda *_a, **_k: True)
    _full_path(monkeypatch, tmp_path)
    assert run.main(["--no-catalog", "--no-tables", *extra]) == 0
    assert lease["calls"] == [] and probes == []   # and the quiet window doesn't apply


# ── the cursor transaction ──────────────────────────────────────────────

def test_cursor_advance_is_one_transaction_and_never_goes_back(monkeypatch):
    calls = []

    def spy(self, fn):
        calls.append(fn)
        return _transact(self, fn)

    monkeypatch.setattr(store_mod.FirestoreArticles, "_transact", spy)
    db = _Db()
    st = store_mod.FirestoreArticles(client=db)
    db.data["news_state/cursor"] = {"upto": "20260110T000000Z"}   # a later run already closed it
    assert st.advance_cursor("20260109T000000Z", run_id="slow") is False
    assert db.data["news_state/cursor"] == {"upto": "20260110T000000Z"}
    assert st.advance_cursor("20260111T000000Z", run_id="next") is True
    assert db.data["news_state/cursor"]["upto"] == "20260111T000000Z" and len(calls) == 2


def test_daily_markers_merge():
    db = _Db()
    st = store_mod.FirestoreArticles(client=db)
    assert st.read_daily() == {}
    st.mark_duty("digest", "2026-11-13", run_id="r1")
    st.mark_duty("floor", "2026-11-13", run_id="r2")
    d = st.read_daily()
    assert d["digest_attempt"] == d["floor_attempt"] == "2026-11-13" and d["floor_run_id"] == "r2"


# ── the idle probe ──────────────────────────────────────────────────────

def test_idle_probe_without_renders_makes_no_expensive_call(live, capsys):
    _, probes = live
    assert run.main([]) == 0   # catalog, demand, tables, images all on: none may be touched
    s = _summary(capsys)
    assert s["status"] == "idle" and s["probe"] == "no_renders" and s["cursor_advanced"] is True
    assert _Articles.cursor == s["window"]["upto"] and s["window"]["cutoff"] == CURSOR
    cutoff = datetime.strptime(CURSOR, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    assert probes == [cutoff - run.SETTLE]


def test_probe_seeing_renders_takes_the_full_path(live, monkeypatch, tmp_path, capsys):
    seen = _full_path(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "_renders_since", lambda _s: True)
    assert run.main(["--no-catalog", "--no-tables"]) == 0
    s = _summary(capsys)
    assert len(seen) == 1 and s["probe"] == "renders" and s["cursor_advanced"] is True


def test_probe_error_falls_through(live, monkeypatch, tmp_path, capsys):
    seen = _full_path(monkeypatch, tmp_path)

    def down(_since):
        raise RuntimeError("default database unreachable")
    monkeypatch.setattr(run, "_renders_since", down)
    assert run.main(["--no-catalog", "--no-tables"]) == 0
    assert len(seen) == 1 and _summary(capsys)["probe"] == "error"


def test_daily_state_error_falls_through(live, monkeypatch, tmp_path, capsys):
    seen = _full_path(monkeypatch, tmp_path)
    monkeypatch.setattr(_Articles, "read_daily", _boom("read_daily"))
    assert run.main(["--no-catalog", "--no-tables"]) == 0
    assert len(seen) == 1 and _summary(capsys)["probe"] == "error"


def test_due_floor_takes_the_full_path_without_renders(live, monkeypatch, tmp_path, capsys):
    _, probes = live
    seen = _full_path(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWS_MIN_PER_DAY", "1")   # an empty day, no floor hour: due now
    assert run.main(["--no-catalog", "--no-tables"]) == 0
    s = _summary(capsys)
    assert len(seen) == 1 and s["probe"] == "duty_due" and probes == []


@pytest.mark.parametrize("extra", [["--dataset", "A"], ["--since-hours", "3"], ["--models-dir", "M"]])
def test_probe_skipped_for_partial_runs(live, monkeypatch, tmp_path, capsys, extra):
    _, probes = live
    seen = _full_path(monkeypatch, tmp_path)
    if extra[0] == "--models-dir":
        extra = ["--models-dir", str(tmp_path)]
    assert run.main(["--no-catalog", "--no-tables", *extra]) == 0
    assert probes == [] and len(seen) == 1 and "probe" not in _summary(capsys)


def test_probe_skipped_without_a_cursor(live, monkeypatch, tmp_path, capsys):
    _, probes = live
    _Articles.cursor = None
    seen = _full_path(monkeypatch, tmp_path)
    assert run.main(["--no-catalog", "--no-tables"]) == 0
    assert probes == [] and len(seen) == 1 and _summary(capsys)["window"]["from"] == "bootstrap"


def test_probe_skipped_for_dry_and_signals_only_runs(live, monkeypatch, tmp_path, capsys):
    _, probes = live
    _full_path(monkeypatch, tmp_path)
    assert run.main(["--signals-only", "--no-catalog"]) == 0
    monkeypatch.setattr(store_mod, "LocalArticles", lambda *_a, **_k: object())
    assert run.main(["--dry-run", "--out", str(tmp_path / "out"), "--no-catalog", "--no-tables"]) == 0
    assert probes == []


def test_budget_flags_reach_write_day(live, monkeypatch, tmp_path, capsys):
    seen = _full_path(monkeypatch, tmp_path)
    monkeypatch.setattr(run, "_renders_since", lambda _s: True)
    assert run.main(["--no-catalog", "--no-tables"]) == 0
    assert seen[-1]["max_per_run"] == 3 and seen[-1]["day_ceiling"] is None   # unset: as before
    monkeypatch.setenv("NEWS_MAX_PER_DAY", "5")
    monkeypatch.setenv("NEWS_MAX_PER_RUN", "1")
    monkeypatch.setenv("NEWS_DAY_BUDGET", "true")
    monkeypatch.setenv("NEWS_DIGEST_HOUR", "9")
    assert run.main(["--no-catalog", "--no-tables"]) == 0
    k = seen[-1]
    assert (k["max_per_run"], k["day_ceiling"], k["digest_hour"], k["floor_hour"]) == (1, 5, 9, None)


# ── budgets ─────────────────────────────────────────────────────────────

class _EditorLLM(FloorLLM):
    """FloorLLM that records every news-editor call's input."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.editor_calls = []

    def chat_json(self, messages, **kw):
        if messages[0]["content"].startswith("You are the news editor"):
            self.editor_calls.append(json.loads(messages[1]["content"]))
        return super().chat_json(messages, **kw)


def _event_day(tmp_path, llm, **kw):
    series, models, sig, cat = _world()
    store = LocalArticles(tmp_path)
    out = run.write_day(llm, ranked=[sig], series_by_ds=series, models=models, catalog=cat,
                        vocab={"משכנתאות", "ריבית"}, store=store, today=date.today(), run_id="r1",
                        fetcher=_fetcher, demand_by_id=DEMAND, images=False, **kw)
    return out, sig


def test_day_ceiling_across_two_runs(tmp_path):
    llm = _EditorLLM([_draft()])
    out, _ = _event_day(tmp_path, llm, max_per_run=3, day_ceiling=1)
    assert len(out["published"]) == 1 and out["news_budget"]["max_briefs"] == 1
    assert llm.editor_calls[0]["published_today"] == {"count": 0, "news_count": 0, "stories": []}
    # the second run that Israel date: the ceiling is reached, no editor call
    llm2 = _EditorLLM([_draft()])
    out2, _ = _event_day(tmp_path, llm2, max_per_run=3, day_ceiling=1)
    assert llm2.editor_calls == [] and out2["briefs"] == 0
    assert out2["news_budget"] == {"per_run": 3, "day_ceiling": 1, "news_today": 1, "max_briefs": 0}


def _seed_today(tmp_path, kinds):
    now = datetime.now(UTC).isoformat()
    return [{"slug": f"s{i}", "headline": f"כותרת {i}", "kind": k, "dataset_ids": [f"d{i}"],
             "signal_keys": [f"k{i}"], "published_at": now} for i, k in enumerate(kinds)]


def _seeded_day(tmp_path, llm, seed, **kw):
    series, models, sig, cat = _world()
    store = LocalArticles(tmp_path, seed=seed)
    return run.write_day(llm, ranked=[sig], series_by_ds=series, models=models, catalog=cat,
                         vocab={"משכנתאות"}, store=store, today=date.today(), run_id="r2",
                         fetcher=_fetcher, images=False, **kw)


def test_second_run_gets_the_remainder_and_sees_todays_stories(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(run, "choose", lambda *a, max_briefs, **k: asked.append((max_briefs, k)) or ([], []))
    seed = _seed_today(tmp_path, ["news", "feature", None])
    _seeded_day(tmp_path, FloorLLM([]), seed, max_per_run=2, day_ceiling=3)
    assert asked[0][0] == 1   # 3 − 2 news (the feature doesn't count), under the per-run 2
    pt = asked[0][1]["published_today"]
    assert pt["count"] == 3 and pt["news_count"] == 2
    assert pt["stories"][1] == {"title": "כותרת 1", "kind": "feature", "lead_dataset": "d1"}
    assert pt["stories"][2]["kind"] == "news"


def test_unset_day_budget_keeps_the_per_run_cap(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(run, "choose", lambda *a, max_briefs, **k: asked.append(max_briefs) or ([], []))
    out = _seeded_day(tmp_path, FloorLLM([]), _seed_today(tmp_path, ["news"] * 5), max_per_run=3)
    assert asked == [3] and "news_budget" not in out


# ── once-a-day duties ───────────────────────────────────────────────────

FRIDAY_08 = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)    # 08:00 Israel time
THURSDAY_08 = FRIDAY_08 - timedelta(days=1)


def test_digest_waits_for_its_hour(tmp_path):
    out, store = _digest_day(tmp_path, FloorLLM([_draft()]), FRIDAY_08, digest_weekday=4, digest_hour=9)
    assert "digest" not in out and store.read_daily() == {}


def test_digest_runs_once_at_its_hour_even_when_rejected(tmp_path):
    out, store = _digest_day(tmp_path, FloorLLM([_draft()], critic=("kill",)), FRIDAY_08,
                             digest_weekday=4, digest_hour=8)
    assert out["digest"]["status"] == "rejected"
    assert store.read_daily()["digest_attempt"] == "2026-11-13"
    llm2 = FloorLLM([_draft()])
    out2, _ = _digest_day(tmp_path, llm2, FRIDAY_08 + timedelta(hours=3), digest_weekday=4,
                          digest_hour=8)
    assert "digest" not in out2 and llm2.turn == 0   # not retried the same day


def test_digest_unrecorded_attempt_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(LocalArticles, "mark_duty", _boom("x"))
    out, _ = _digest_day(tmp_path, FloorLLM([_draft()]), FRIDAY_08, digest_weekday=4, digest_hour=8)
    assert out["digest"] == {"status": "skipped", "reason": "attempt_unrecorded"}


def _floor_day(tmp_path, llm, now, *, seed=None, **kw):
    series, models, _sig, cat = _world()
    store = LocalArticles(tmp_path, seed=seed)
    out = run.write_day(llm, ranked=[], series_by_ds=series, models=models, catalog=cat,
                        vocab={"משכנתאות", "ריבית"}, store=store, today=now.date(), run_id="r1",
                        fetcher=_fetcher, demand_by_id=DEMAND, images=False, now=now,
                        min_per_day=1, **kw)
    return out, store


def test_floor_waits_for_its_hour(tmp_path):
    llm = FloorLLM([_draft()])
    out, store = _floor_day(tmp_path, llm, THURSDAY_08, floor_hour=12)
    assert "fill" not in out and llm.feature_calls == [] and store.read_daily() == {}


def test_floor_runs_once_at_its_hour(tmp_path):
    llm = FloorLLM([_draft()], critic=("kill",) * 4)
    out, store = _floor_day(tmp_path, llm, THURSDAY_08 + timedelta(hours=4), floor_hour=12)
    assert out["fill"]["attempts"] >= 1 and out["fill"]["published"] == 0
    assert store.read_daily()["floor_attempt"] == "2026-11-12"
    llm2 = FloorLLM([_draft()])
    out2, _ = _floor_day(tmp_path, llm2, THURSDAY_08 + timedelta(hours=6), floor_hour=12)
    assert "fill" not in out2 and llm2.feature_calls == []   # the day stays short; no retry


def test_floor_friday_override(tmp_path):
    out, _ = _floor_day(tmp_path / "fri", FloorLLM([_draft()]), FRIDAY_08, floor_hour=12,
                        floor_hour_friday=8)
    assert out["fill"]["published"] == 1
    out, _ = _floor_day(tmp_path / "thu", FloorLLM([_draft()]), THURSDAY_08, floor_hour=12,
                        floor_hour_friday=8)
    assert "fill" not in out


def test_floor_met_records_no_attempt(tmp_path):
    seed = [{"slug": "x", "headline": "h", "dataset_ids": ["other"], "signal_keys": ["k"],
             "published_at": THURSDAY_08.isoformat()}]
    llm = FloorLLM([_draft()])
    out, store = _floor_day(tmp_path, llm, THURSDAY_08 + timedelta(hours=4), seed=seed, floor_hour=12)
    assert "fill" not in out and llm.feature_calls == [] and store.read_daily() == {}


def test_duties_due():
    fri = FRIDAY_08 + timedelta(hours=2)   # 10:00 Israel time
    kw = {"recent": [], "min_per_day": 1, "max_per_run": 3}
    # hours unset: every run (today's behaviour)
    assert run.duties_due(fri, daily={}, digest_weekday=4, **kw) == {"digest": True, "floor": True}
    assert run.duties_due(fri, daily={"digest_attempt": "2026-11-13", "floor_attempt": "2026-11-13"},
                          digest_weekday=4, **kw) == {"digest": True, "floor": True}
    # hours set: at/after the hour, not attempted today
    assert run.duties_due(fri, daily={}, digest_weekday=4, digest_hour=11, floor_hour=11,
                          **kw) == {"digest": False, "floor": False}
    assert run.duties_due(fri, daily={}, digest_weekday=4, digest_hour=10, floor_hour=11,
                          floor_hour_friday=9, **kw) == {"digest": True, "floor": True}
    assert run.duties_due(fri, daily={"digest_attempt": "2026-11-13", "floor_attempt": "2026-11-13"},
                          digest_weekday=4, digest_hour=10, floor_hour=9,
                          **kw) == {"digest": False, "floor": False}
    # yesterday's attempt doesn't count; a met floor or another weekday isn't due
    assert run.duties_due(fri, daily={"floor_attempt": "2026-11-12"}, floor_hour=9, **kw)["floor"]
    met = [{"published_at": FRIDAY_08.isoformat()}]
    assert run.duties_due(fri, daily={}, digest_weekday=3, recent=met, min_per_day=1,
                          max_per_run=3) == {"digest": False, "floor": False}


def test_malformed_hour_env_is_unset(monkeypatch):
    monkeypatch.setenv("NEWS_FLOOR_HOUR", "noon")
    monkeypatch.setenv("NEWS_DIGEST_HOUR", "24")
    monkeypatch.setenv("NEWS_FLOOR_HOUR_FRIDAY", "9")
    h = run.duty_hours()
    assert h["floor_hour"] is None and h["digest_hour"] is None and h["floor_hour_friday"] == 9


# ── no re-rolls ─────────────────────────────────────────────────────────

def test_rejected_story_is_not_offered_again(tmp_path):
    llm = _EditorLLM([_draft()], critic=("kill",))
    out, _ = _event_day(tmp_path, llm)
    assert out["published"] == [] and len(llm.editor_calls) == 1
    llm2 = _EditorLLM([_draft()])
    out2, _ = _event_day(tmp_path, llm2)
    assert out2["candidates"] == 0 and llm2.editor_calls == []
    # after REJECT_DAYS it is eligible again
    p = next((tmp_path / "_rejected").glob("*.json"))
    doc = json.loads(p.read_text(encoding="utf-8"))
    doc["at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    llm3 = _EditorLLM([_draft()])
    out3, _ = _event_day(tmp_path, llm3)
    assert out3["candidates"] == 1 and len(llm3.editor_calls) == 1


def test_rejected_signal_keys_rules():
    sig = _world()[2]
    rejects = [{"kind": "news", "reason": "critic_kill", "brief": {"signal_keys": ["a", sig.key]}},
               {"kind": None, "reason": "gates", "brief": {"signal_keys": ["b"]}},
               {"kind": "news", "reason": "error", "brief": {"signal_keys": ["c"]}},     # never judged
               {"kind": "feature", "reason": "critic_kill", "brief": {"signal_keys": ["d"]}},
               {"kind": "digest", "reason": "critic_kill", "brief": {"signal_keys": ["e"]}},
               {"kind": "news", "reason": "gates", "brief": None}]
    assert rejected_signal_keys(rejects) == {"a", sig.key, "b"}
    assert eligible([sig], [], cooldown_days=21, rejected_keys={sig.key}) == []
    assert eligible([sig], [], cooldown_days=21) == [sig]

