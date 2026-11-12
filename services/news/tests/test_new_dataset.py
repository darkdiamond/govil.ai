"""New datasets (NEWS_NEW_DATASET_SIGNALS): a first render ever of a dataset its
source created recently signals `new_dataset`; a chosen one is written as an
explainer."""
from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from services.news import digest, run
from services.news.editor import NEW_DATASET_NOTE, choose, eligible
from services.news.signals import Signal, is_new_dataset, new_dataset_signal, rank
from services.news.snapshots import LocalSnapshots, history
from services.news.store import LocalArticles
from services.news.tests.test_floor import DEMAND, FloorLLM
from services.news.tests.test_llm_pipeline import MORT, RATE, _draft, _fetcher, _world
from services.shared.states import ArticleKind

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)
CUTOFF, UPTO = "20261112T070000Z", "20261112T085000Z"
IN_WINDOW, BEFORE = "20261112T080000Z", "20261110T080000Z"
FIX = Path(__file__).parent / "fixtures" / "models"


def _snap(root: Path, ds: str, ts: str, version: int = 1, model: dict | None = None):
    d = root / ds
    d.mkdir(parents=True, exist_ok=True)
    doc = {"dataset_id": ds, "rendered_at": ts, "recipe_version": version, "metadata_modified": None,
           "model": model or {"charts": {"c": {"x": ["2025-01"], "y": [1]}}}}
    (d / f"{ts}.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))


def _source(created_days_ago: float | None, **extra) -> dict:
    doc = {"title": "רישיונות לגידול דבורים", "organization": {"title": "משרד החקלאות"}} | extra
    if created_days_ago is not None:
        doc["metadata_created"] = NOW - timedelta(days=created_days_ago)
    return doc


class _Lookup:
    def __init__(self, docs: dict):
        self.docs, self.calls = docs, []

    def __call__(self, ds):
        self.calls.append(ds)
        v = self.docs.get(ds)
        if isinstance(v, Exception):
            raise v
        return v


def _find(root, lookup=None, **kw):
    return run.find_signals(LocalSnapshots(root), today=NOW.date(), cutoff=CUTOFF, upto=UPTO,
                            source_lookup=lookup, now=NOW, workers=2, **kw)


def _new(sigs):
    return [s for s in sigs if is_new_dataset(s)]


# ── snapshots ───────────────────────────────────────────────────────────

def test_history_tells_a_first_render_from_a_recipe_change(tmp_path):
    _snap(tmp_path, "new", IN_WINDOW)
    _snap(tmp_path, "new2", "20261112T073000Z")
    _snap(tmp_path, "new2", IN_WINDOW)              # two renders, both in this window
    _snap(tmp_path, "recipe", BEFORE, version=1)
    _snap(tmp_path, "recipe", IN_WINDOW, version=2)
    _snap(tmp_path, "late", "20261112T085500Z")     # after upto: the next run's
    st = LocalSnapshots(tmp_path)
    assert history(st, "new", CUTOFF, UPTO).first is True
    assert history(st, "new2", CUTOFF, UPTO).first is True
    h = history(st, "recipe", CUTOFF, UPTO)
    assert h.fresh and h.first is False and h.base.recipe_version == 1
    assert history(st, "late", CUTOFF, UPTO).latest is None
    assert history(st, "new", None).first is True and history(st, "recipe", None).first is False


# ── find_signals ────────────────────────────────────────────────────────

def test_flag_off_looks_nothing_up_and_changes_nothing(tmp_path):
    _snap(tmp_path, "new", IN_WINDOW)
    for d in (MORT, RATE):   # real series, so there are signals to compare
        model = json.loads((FIX / f"{d}.json").read_text(encoding="utf-8"))
        _snap(tmp_path, d, IN_WINDOW, model=model)
    lookup = _Lookup({"new": _source(1)})
    base_sigs, base_stats = run.find_signals(LocalSnapshots(tmp_path), today=NOW.date(),
                                             cutoff=CUTOFF, upto=UPTO, workers=2)
    sigs, stats = _find(tmp_path, lookup)                 # new_datasets defaults to off
    assert lookup.calls == [] and _new(sigs) == []
    assert [s.key for s in sigs] == [s.key for s in base_sigs] and stats == base_stats
    assert "new_datasets" not in stats


def test_first_render_of_a_recent_dataset_signals_once_below_a_release(tmp_path):
    _snap(tmp_path, "new", "20261112T073000Z")
    _snap(tmp_path, "new", IN_WINDOW)
    ctx: dict = {}
    lookup = _Lookup({"new": _source(3, page_slug_suffix=None)})
    sigs, stats = _find(tmp_path, lookup, new_datasets=True, context=ctx)
    [s] = _new(sigs)
    assert lookup.calls == ["new"] and stats["new_datasets"] == 1
    assert s.key == f"new|new_dataset|{(NOW - timedelta(days=3)).date().isoformat()}"
    assert s.facts["title"] == "רישיונות לגידול דבורים" and s.facts["publisher"] == "משרד החקלאות"
    assert s.facts["created_from"] == "metadata_created" and s.facts["first_rendered"] == IN_WINDOW
    assert ctx["new_datasets"]["new"]["title"] == "רישיונות לגידול דבורים"
    # weaker than the weakest release, and demand can't lift it over one
    weakest = Signal("cbs-x", "c.y", "y", "M", "2026-10", "2026-10-31", 1.0, ["new_release"],
                     0.45, {})
    s.demand = 3.0
    assert s.surprise < weakest.surprise
    ranked = rank([s, weakest], per_dataset=1)
    assert [x.dataset_id for x in ranked] == ["cbs-x", "new"]


def test_new_dataset_survives_the_per_dataset_cap(tmp_path):
    nd = new_dataset_signal("d", date(2026, 11, 10))
    series = [Signal("d", f"c.{i}", "y", "M", "2026-10", "2026-10-31", 1.0, ["record_high"], 3.0, {})
              for i in range(4)]
    ranked = rank(series + [nd], per_dataset=3)
    assert len(ranked) == 4 and ranked[-1] is nd


def test_first_render_of_an_old_dataset_does_not_signal(tmp_path):
    _snap(tmp_path, "legacy", IN_WINDOW)
    sigs, stats = _find(tmp_path, _Lookup({"legacy": _source(400)}), new_datasets=True)
    assert _new(sigs) == [] and stats["first_renders"] == 1 and stats["new_datasets"] == 0


def test_second_render_and_recipe_change_do_not_signal(tmp_path):
    _snap(tmp_path, "again", BEFORE)
    _snap(tmp_path, "again", IN_WINDOW)
    _snap(tmp_path, "recipe", BEFORE, version=1)
    _snap(tmp_path, "recipe", IN_WINDOW, version=2)
    lookup = _Lookup({"again": _source(1), "recipe": _source(1)})
    sigs, stats = _find(tmp_path, lookup, new_datasets=True)
    assert _new(sigs) == [] and lookup.calls == [] and stats["first_renders"] == 0


def test_lookup_failure_or_no_date_does_not_signal_and_the_run_goes_on(tmp_path):
    for ds in ("boom", "nodoc", "nodate", "ok"):
        _snap(tmp_path, ds, IN_WINDOW)
    lookup = _Lookup({"boom": RuntimeError("firestore down"), "nodoc": None,
                      "nodate": _source(None), "ok": _source(2)})
    sigs, stats = _find(tmp_path, lookup, new_datasets=True)
    assert [s.dataset_id for s in _new(sigs)] == ["ok"]
    assert stats["new_dataset_lookup_errors"] == 1 and sorted(lookup.calls) == ["boom", "nodate",
                                                                               "nodoc", "ok"]


def test_first_seen_is_the_fallback_date_for_a_provider_source(tmp_path):
    _snap(tmp_path, "cbs-new-report", IN_WINDOW)
    doc = {"title": "דוח חדש", "organization": {"title": "הלשכה המרכזית לסטטיסטיקה"},
           "page_slug_suffix": "new-report", "first_seen_at": (NOW - timedelta(days=5)).isoformat()}
    ctx: dict = {}
    sigs, _ = _find(tmp_path, _Lookup({"cbs-new-report": doc}), new_datasets=True, context=ctx)
    [s] = _new(sigs)
    assert s.facts["created_from"] == "first_seen_at"
    assert ctx["new_datasets"]["cbs-new-report"]["page_slug"] == "דוח-חדש-new-report"


def test_catalog_entry_slug_follows_the_publisher():
    from services.news.catalog import entry_from_source

    e = entry_from_source("0b3e1f2a-1111-2222-3333-444455556666", {"title": "רישיונות עסק",
                                                                    "organization": "עירייה"})
    assert e["page_slug"] == "רישיונות-עסק-0b3e1f2a" and e["organization"] == "עירייה"


def test_new_dataset_days_comes_from_env(tmp_path, monkeypatch):
    _snap(tmp_path, "new", IN_WINDOW)
    sigs, _ = _find(tmp_path, _Lookup({"new": _source(20)}), new_datasets=True, new_dataset_days=10)
    assert _new(sigs) == []
    sigs, _ = _find(tmp_path, _Lookup({"new": _source(20)}), new_datasets=True)
    assert len(_new(sigs)) == 1


# ── the editor ──────────────────────────────────────────────────────────

class _Editor:
    def __init__(self, briefs):
        self.briefs, self.payloads = briefs, []

    def chat_json(self, messages, **kw):
        self.payloads.append(json.loads(messages[1]["content"]))
        return {"briefs": self.briefs, "skipped": []}


def test_choose_turns_a_new_dataset_brief_into_one_explainer():
    nd = new_dataset_signal("new", date(2026, 11, 10), title="t")
    nd2 = new_dataset_signal("new2", date(2026, 11, 10), title="t2")
    ev = _world()[2]
    cat = {"new": {"title": "מאגר חדש", "organization": "משרד"}, "new2": {"title": "x"}}
    llm = _Editor([{"signal_keys": [nd.key], "dataset_ids": ["new"], "angle_he": "a", "questions": ["q"]},
                   {"signal_keys": [nd2.key], "dataset_ids": ["new2"], "angle_he": "b"},
                   {"signal_keys": [ev.key, nd2.key], "dataset_ids": [MORT], "angle_he": "c"}])
    todays = {"count": 1, "news_count": 1, "stories": [{"title": "h", "kind": "news", "lead_dataset": RATE}]}
    briefs, _ = choose(llm, [ev, nd, nd2], cat, [], max_briefs=5, today="2026-11-12",
                       published_today=todays)
    assert len(briefs) == 2   # the second new-dataset brief is dropped: one per call
    feat, news = briefs
    assert feat["kind"] == ArticleKind.FEATURE and feat["signals"] == []
    assert feat["signal_keys"] == [nd.key, "feature:new:2026-11"] and feat["dataset_ids"] == ["new"]
    assert feat["questions"] == [NEW_DATASET_NOTE, "q"]
    assert news["kind"] == ArticleKind.NEWS and news["signal_keys"] == [ev.key]
    payload = llm.payloads[0]
    assert payload["published_today"] == todays
    row = next(r for r in payload["signals"] if r["key"] == nd.key)
    assert row["dataset"] == "מאגר חדש" and row["publisher"] == "משרד" and row["flags"] == ["new_dataset"]


def test_editor_prompt_covers_the_hourly_desk():
    text = (Path(run.__file__).with_name("prompts") / "editor.md").read_text(encoding="utf-8")
    assert "published_today" in text and "new_dataset" in text and "Each morning" not in text
    assert "—" not in text and "–" not in text


# ── writing it ──────────────────────────────────────────────────────────

def _day(tmp_path, llm, ranked, **kw):
    series, models, _sig, cat = _world()
    store = LocalArticles(tmp_path)
    kw = {"max_per_run": 3, "today": date(2026, 11, 12)} | kw
    out = run.write_day(llm, ranked=ranked, series_by_ds=series, models=models, catalog=cat,
                        vocab={"משכנתאות", "ריבית"}, store=store, run_id="r1", fetcher=_fetcher,
                        demand_by_id=DEMAND, images=False, **kw)
    return out, store


def _nd(created=date(2026, 11, 10)):
    return new_dataset_signal(MORT, created, title="משכנתאות")


def test_chosen_new_dataset_is_written_as_an_explainer(tmp_path):
    nd = _nd()
    llm = FloorLLM([_draft()])
    out, store = _day(tmp_path, llm, [nd], min_per_day=2, max_per_run=1)
    assert len(out["published"]) == 1, out
    doc = json.loads((tmp_path / out["published"][0] / "article.json").read_text(encoding="utf-8"))
    assert doc["kind"] == ArticleKind.FEATURE
    assert doc["signal_keys"] == [nd.key, f"feature:{MORT}:2026-11"]
    writer_in = json.loads(llm.writer_msgs[1]["content"])
    assert writer_in["kind"] == "feature" and writer_in["signals"] == []
    assert writer_in["brief"]["questions"][0] == NEW_DATASET_NOTE
    assert all(not ({"web_search", "fetch_url"} & names) for names in llm.offered)
    # it took the run's only slot: the floor's fill has no room left
    assert "fill" not in out
    # no event cooldown: the dataset's next real move is still eligible
    ev = _world()[2]
    assert eligible([ev], store.recent(90), cooldown_days=21) == [ev]
    # not offered again: its key is used, and a later new-dataset signal for
    # the same dataset sits out the explainers' 60-day cooldown
    llm2 = FloorLLM([_draft()])
    out2, _ = _day(tmp_path, llm2, [nd, _nd(date(2026, 11, 11))])
    assert out2["candidates"] == 0 and out2["published"] == []


def test_new_dataset_counts_toward_the_floor_on_a_busy_day(tmp_path):
    out, _ = _day(tmp_path, FloorLLM([_draft()]), [_nd()], min_per_day=1)
    assert len(out["published"]) == 1 and "fill" not in out


def test_rejected_new_dataset_explainer_sits_out_seven_days(tmp_path):
    out, _ = _day(tmp_path, FloorLLM([_draft()] * 3, critic=("kill",)), [_nd()])
    assert out["published"] == [] and out["rejected"][0]["kind"] == ArticleKind.FEATURE
    out2, _ = _day(tmp_path, FloorLLM([_draft()]), [_nd(date(2026, 11, 11))])
    assert out2["candidates"] == 0


def test_new_dataset_passes_a_reached_news_ceiling(tmp_path):
    seed_now = datetime.now(UTC).isoformat()
    series, models, _sig, cat = _world()
    store = LocalArticles(tmp_path, seed=[{"slug": "x", "headline": "h", "kind": "news",
                                           "dataset_ids": ["other"], "signal_keys": ["k"],
                                           "published_at": seed_now}])
    llm = FloorLLM([_draft()])
    out = run.write_day(llm, ranked=[_world()[2], _nd()], series_by_ds=series, models=models,
                        catalog=cat, vocab={"משכנתאות", "ריבית"}, store=store, run_id="r1",
                        fetcher=_fetcher, images=False, today=date(2026, 11, 12),
                        max_per_run=3, day_ceiling=1)
    assert out["news_budget"]["max_briefs"] == 0 and len(out["published"]) == 1
    doc = json.loads((tmp_path / out["published"][0] / "article.json").read_text(encoding="utf-8"))
    assert doc["kind"] == ArticleKind.FEATURE


class _SkipAll(FloorLLM):
    def chat_json(self, messages, **kw):
        if messages[0]["content"].startswith("You are the news editor"):
            self.editor_in = json.loads(messages[1]["content"])
            return {"briefs": [], "skipped": []}
        return super().chat_json(messages, **kw)


def test_new_dataset_never_reaches_the_digest(tmp_path):
    ev, nd = _world()[2], _nd()
    llm = _SkipAll([])
    _day(tmp_path, llm, [ev, nd])
    assert "published_today" in llm.editor_in
    pooled = LocalArticles(tmp_path).read_pool(7)
    assert [p["signal"]["key"] for p in pooled] == [ev.key]
    # even if one were pooled, the digest would not use it
    series = _world()[0]
    item = {"signal": nd.to_dict(), "run_id": "r", "skip_reason": None}
    assert digest.brief([item] * 5, [], today=date(2026, 11, 13), cooldown_days=21,
                        series_by_ds=series, catalog={}) is None


# ── the run ─────────────────────────────────────────────────────────────

@pytest.fixture
def clean_env(monkeypatch):
    for k in ("NEWS_NEW_DATASET_SIGNALS", "NEWS_NEW_DATASET_DAYS", "NEWS_RELEASE_SIGNALS"):
        monkeypatch.delenv(k, raising=False)


def test_signals_only_off_does_no_lookup(tmp_path, monkeypatch, capsys, clean_env):
    ts = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
    _snap(tmp_path, "new", ts)
    monkeypatch.setattr(run, "_read_source", lambda ds: pytest.fail("looked up with the flag off"))
    assert run.main(["--signals-only", "--models-dir", str(tmp_path), "--no-catalog", "--json"]) == 0
    head = json.loads(capsys.readouterr().out.splitlines()[0])
    assert "new_datasets" not in head


def test_run_puts_a_catalog_missing_new_dataset_in_the_catalog(tmp_path, monkeypatch, capsys,
                                                               clean_env):
    from services.news import llm as llm_mod
    from services.news import store as store_mod
    from services.news.tests.test_hourly import _Articles

    ts = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
    ds = "9f1c2d3e-aaaa-bbbb-cccc-ddddeeeeffff"
    _snap(tmp_path, ds, ts)
    monkeypatch.setenv("NEWS_NEW_DATASET_SIGNALS", "true")
    monkeypatch.setenv("NEWS_PUBLISH", "live")
    monkeypatch.setattr(run, "_read_source", lambda i: {
        "title": "מאגר חדש לגמרי", "organization": {"title": "משרד הבריאות"},
        "metadata_created": datetime.now(UTC) - timedelta(days=2)})
    monkeypatch.setattr(run.catalog_mod, "load_catalog", dict)
    monkeypatch.setattr(store_mod, "FirestoreArticles", _Articles)
    monkeypatch.setattr(llm_mod, "OpenRouter", lambda: type("L", (), {"cost_usd": 0, "calls": 0})())
    _Articles.cursor, _Articles.recent_docs = None, []
    seen = []
    monkeypatch.setattr(run, "write_day", lambda *_a, **k: seen.append(k) or {
        "published": [], "candidates": 0, "briefs": 0, "rejected": [], "skipped": []})
    assert run.main(["--models-dir", str(tmp_path), "--no-tables", "--no-demand"]) == 0
    k = seen[0]
    assert k["catalog"][ds]["title"] == "מאגר חדש לגמרי"
    assert k["catalog"][ds]["page_slug"] == "מאגר-חדש-לגמרי-9f1c2d3e"
    assert [s.flags for s in k["ranked"]] == [["new_dataset"]]
    # the editor keeps it (its dataset is in the catalog now) and sees its title
    llm = _Editor([{"signal_keys": [k["ranked"][0].key], "dataset_ids": [ds], "angle_he": "a"}])
    briefs, _ = choose(llm, k["ranked"], k["catalog"], [], max_briefs=1, today="2026-11-12")
    assert briefs[0]["dataset_ids"] == [ds] and briefs[0]["kind"] == ArticleKind.FEATURE
    assert llm.payloads[0]["signals"][0]["publisher"] == "משרד הבריאות"
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["signals"]["new_datasets"] == 1


def test_the_top_cut_never_drops_a_new_dataset():
    from datetime import date

    from services.news.signals import Signal, is_new_dataset, new_dataset_signal, rank

    nd = new_dataset_signal("fresh-ds", date(2026, 11, 1), title="t", publisher="p",
                            created_from="metadata_created", rendered_at="2026-11-12")
    assert isinstance(nd, Signal)
    kept = rank([nd], top=0) + rank([nd], top=1)
    assert all(is_new_dataset(s) for s in kept) and len(kept) == 2
