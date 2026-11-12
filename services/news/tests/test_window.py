"""The news run's render window: [cursor, now − SETTLE), so the job can run at
any time (late, twice, after a skipped day) and every render is new to exactly
one live run."""
from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from services.news import llm as llm_mod
from services.news import run
from services.news import store as store_mod
from services.news.snapshots import LocalSnapshots, latest_and_baseline

NOW = datetime(2026, 1, 9, 8, 0, tzinfo=UTC)


def test_window_runs_from_the_cursor_to_just_before_now():
    w = run.news_window(NOW, cursor="20260108T075000Z")
    assert w == {"cutoff": "20260108T075000Z", "upto": "20260109T075000Z", "from": "cursor"}


def test_window_after_a_skipped_day_still_starts_at_the_cursor():
    w = run.news_window(NOW, cursor="20260106T075000Z")
    assert w["cutoff"] == "20260106T075000Z" and w["from"] == "cursor"


def test_window_is_capped_after_a_long_stop():
    w = run.news_window(NOW, cursor="20251201T000000Z", max_lookback_hours=168)
    assert w == {"cutoff": "20260102T075000Z", "upto": "20260109T075000Z", "from": "capped"}


def test_first_run_bootstraps_a_day():
    w = run.news_window(NOW, cursor=None)
    assert w == {"cutoff": "20260108T075000Z", "upto": "20260109T075000Z", "from": "bootstrap"}


def test_a_rerun_right_after_a_run_has_an_empty_window():
    w = run.news_window(NOW, cursor="20260109T075000Z")
    assert w["cutoff"] == w["upto"]


@pytest.mark.parametrize("hours, cutoff", [(3, "20260109T050000Z"), (0, None)])
def test_explicit_since_hours_is_open_ended_and_ignores_the_cursor(hours, cutoff):
    w = run.news_window(NOW, cursor="20260101T000000Z", since_hours=hours)
    assert w == {"cutoff": cutoff, "upto": None, "from": "since_hours"}


def _snap(d, ts, y):
    d.mkdir(parents=True, exist_ok=True)
    doc = {"dataset_id": d.name, "rendered_at": ts, "recipe_version": 1,
           "metadata_modified": None, "model": {"charts": {"c": {"x": ["2025-01"], "y": [y]}}}}
    (d / f"{ts}.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))


def test_renders_at_or_after_upto_belong_to_the_next_run(tmp_path):
    _snap(tmp_path / "A", "20260108T060000Z", 1)
    _snap(tmp_path / "A", "20260109T060000Z", 2)   # in this window
    _snap(tmp_path / "A", "20260109T075500Z", 3)   # landed while this run was starting
    st = LocalSnapshots(tmp_path)
    latest, base, fresh = latest_and_baseline(st, "A", "20260108T075000Z", "20260109T075000Z")
    assert fresh and latest.rendered_at == "20260109T060000Z"
    assert base.rendered_at == "20260108T060000Z"
    # The next run (cursor moved to this upto) sees the late one, diffed
    # against what this run already covered.
    latest, base, fresh = latest_and_baseline(st, "A", "20260109T075000Z", "20260110T075000Z")
    assert fresh and latest.rendered_at == "20260109T075500Z"
    assert base.rendered_at == "20260109T060000Z"


def test_only_snapshots_after_upto_reads_as_no_history(tmp_path):
    _snap(tmp_path / "A", "20260109T075500Z", 1)
    st = LocalSnapshots(tmp_path)
    assert latest_and_baseline(st, "A", "20260108T075000Z", "20260109T075000Z") == (None, None, False)


class _Doc:
    def __init__(self, data, name):
        self._data, self._name = data, name

    def get(self, transaction=None):
        d = self._data.get(self._name)
        return type("S", (), {"exists": d is not None, "to_dict": lambda _s: d})()

    def set(self, v, merge=False):
        self._data[self._name] = (self._data.get(self._name) or {}) | v if merge else v


class _Txn:
    """A fake transaction: writes are buffered and applied at commit."""

    def __init__(self):
        self.writes = []

    def set(self, ref, v):
        self.writes.append((ref, v))


def _transact(_self, fn):
    txn = _Txn()
    out = fn(txn)
    for ref, v in txn.writes:
        ref.set(v)
    return out


class _Db:
    def __init__(self):
        self.data: dict = {}

    def collection(self, name):
        return type("C", (), {"document": lambda _c, doc: _Doc(self.data, f"{name}/{doc}")})()


def test_cursor_only_moves_forward(monkeypatch):
    monkeypatch.setattr(store_mod.FirestoreArticles, "_transact", _transact)
    st = store_mod.FirestoreArticles(client=_Db())
    assert st.read_cursor() is None
    assert st.advance_cursor("20260109T075000Z", run_id="r1")
    assert not st.advance_cursor("20260108T075000Z", run_id="r0")   # a slower, older run
    assert st.read_cursor() == "20260109T075000Z"
    assert st.advance_cursor("20260110T075000Z", run_id="r2")
    assert st.read_cursor() == "20260110T075000Z"


class _FakeArticles:
    """FirestoreArticles with the cursor in memory (shared across instances,
    like the real database) and no articles."""
    cursor: str | None = None
    fail_read = False

    def __init__(self, **_kw):
        pass

    def read_cursor(self):
        if _FakeArticles.fail_read:
            raise RuntimeError("firestore down")
        return _FakeArticles.cursor

    def advance_cursor(self, upto, *, run_id):
        _FakeArticles.cursor = upto
        return True


# The live tests run on the real clock: a cursor two days back is in reach.
CURSOR = (datetime.now(UTC) - timedelta(days=2)).strftime("%Y%m%dT%H%M%SZ")


@pytest.fixture
def live(monkeypatch, tmp_path):
    _FakeArticles.cursor, _FakeArticles.fail_read = CURSOR, False
    monkeypatch.setenv("NEWS_PUBLISH", "live")
    monkeypatch.delenv("QUIET_WINDOW", raising=False)
    # The scheduled-run gates (services/news/tests/test_hourly.py): no lease
    # contention, and the idle probe always sees renders, so these tests take
    # the full path as before.
    monkeypatch.setattr(run.lease, "acquire", lambda *_a, **_k: True)
    monkeypatch.setattr(run.lease, "release", lambda *_a, **_k: None)
    monkeypatch.setattr(run, "_renders_since", lambda _since: True)
    monkeypatch.setattr(store_mod, "FirestoreArticles", _FakeArticles)
    monkeypatch.setattr(run, "GcsSnapshots", lambda *_a: LocalSnapshots(tmp_path))
    monkeypatch.setattr(llm_mod, "OpenRouter", lambda: type("L", (), {"cost_usd": 0, "calls": 0})())
    day = {"published": [], "candidates": 0, "briefs": 0, "rejected": [], "skipped": []}
    monkeypatch.setattr(run, "write_day", lambda *_a, **_k: day)
    return ["--no-catalog", "--no-tables", "--no-images"]


def _summary(capsys):
    return json.loads(capsys.readouterr().out.splitlines()[-1])


def test_live_run_reads_and_advances_the_cursor(live, capsys):
    assert run.main(live) == 0
    s = _summary(capsys)
    assert s["status"] == "idle" and s["cursor_advanced"] is True
    assert s["window"]["from"] == "cursor" and s["window"]["cutoff"] == CURSOR
    assert _FakeArticles.cursor == s["window"]["upto"]


def test_failed_live_run_keeps_the_cursor(live, monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("writer exploded")
    monkeypatch.setattr(run, "write_day", boom)
    assert run.main(live) == 1
    assert _summary(capsys)["status"] == "failed"
    assert _FakeArticles.cursor == CURSOR


def test_model_error_in_a_story_keeps_the_cursor(live, monkeypatch, capsys):
    day = {"published": [], "candidates": 1, "briefs": 1, "skipped": [], "model_errors": 1,
           "rejected": [{"signal_keys": ["k"], "reason": "error", "headline": None}]}
    monkeypatch.setattr(run, "write_day", lambda *_a, **_k: day)
    assert run.main(live) == 0
    s = _summary(capsys)
    assert s["status"] == "idle" and s["cursor_advanced"] is False
    assert _FakeArticles.cursor == CURSOR


def test_store_error_dispatches_the_stored_stories_and_keeps_the_cursor(live, monkeypatch, capsys):
    day = {"published": ["a-story-slug"], "candidates": 2, "briefs": 2, "skipped": [],
           "model_errors": 0, "store_errors": 1,
           "rejected": [{"signal_keys": ["k"], "reason": "error", "headline": "h"}]}
    monkeypatch.setattr(run, "write_day", lambda *_a, **_k: day)
    dispatched = []
    monkeypatch.setattr(run, "_dispatch_publish", lambda: dispatched.append(1) or "ok")
    # The stored story goes out, but a store that fails every day must turn the job red.
    assert run.main(live) == 1
    s = _summary(capsys)
    assert s["status"] == "store_failed" and s["publish_dispatch"] == "ok" and dispatched == [1]
    assert s["cursor_advanced"] is False
    assert _FakeArticles.cursor == CURSOR


@pytest.mark.parametrize("part", [{"fill": {"published": 0, "store_errors": 1}},
                                  {"digest": {"status": "store_error"}}])
def test_store_error_in_a_fill_or_digest_fails_the_run_but_closes_the_window(live, monkeypatch,
                                                                              capsys, part):
    day = {"published": [], "candidates": 0, "briefs": 0, "skipped": [], "rejected": [],
           "model_errors": 0, "store_errors": 0} | part
    monkeypatch.setattr(run, "write_day", lambda *_a, **_k: day)
    assert run.main(live) == 1
    s = _summary(capsys)
    assert s["status"] == "store_failed" and s["cursor_advanced"] is True


@pytest.mark.parametrize("exc", [llm_mod.LLMUnavailable("key refused"), RuntimeError("boom")])
def test_crash_after_a_stored_story_still_dispatches(live, monkeypatch, capsys, exc):
    def partial(*_a, stored, **_k):
        stored.append("a-story-slug")
        raise exc
    monkeypatch.setattr(run, "write_day", partial)
    dispatched = []
    monkeypatch.setattr(run, "_dispatch_publish", lambda: dispatched.append(1) or "ok")
    assert run.main(live) == 1
    s = _summary(capsys)
    assert s["status"] in ("llm_unavailable", "failed") and s["publish_dispatch"] == "ok"
    assert s["published"] == ["a-story-slug"] and dispatched == [1]
    assert _FakeArticles.cursor == CURSOR


@pytest.mark.parametrize("extra", [["--since-hours", "3"], ["--dataset", "A"]])
def test_partial_live_runs_keep_the_cursor(live, capsys, extra):
    assert run.main(live + extra) == 0
    assert "cursor_advanced" not in _summary(capsys)
    assert _FakeArticles.cursor == CURSOR


def test_live_run_without_its_cursor_fails(live, capsys):
    _FakeArticles.fail_read = True
    assert run.main(live) == 1
    assert _summary(capsys)["status"] == "failed"


def test_signals_only_reads_but_never_moves_the_cursor(live, capsys):
    assert run.main(["--signals-only", "--no-catalog"]) == 0
    head = json.loads(capsys.readouterr().out.splitlines()[0])
    assert head["window"]["cutoff"] == CURSOR
    assert _FakeArticles.cursor == CURSOR


def test_signals_only_without_the_cursor_falls_back_to_bootstrap(live, capsys):
    _FakeArticles.fail_read = True
    assert run.main(["--signals-only", "--no-catalog"]) == 0
    assert json.loads(capsys.readouterr().out.splitlines()[0])["window"]["from"] == "bootstrap"


def test_cursor_write_failure_keeps_the_run_ok(live, monkeypatch, capsys):
    def boom(self, upto, *, run_id):
        raise RuntimeError("firestore down")
    monkeypatch.setattr(_FakeArticles, "advance_cursor", boom)
    assert run.main(live) == 0
    s = _summary(capsys)
    assert s["status"] == "idle" and s["cursor_advanced"] is False and "cursor_error" in s
    assert _FakeArticles.cursor == CURSOR


def test_non_positive_lookback_is_refused(live):
    with pytest.raises(SystemExit):
        run.main([*live, "--max-lookback-hours", "0"])
