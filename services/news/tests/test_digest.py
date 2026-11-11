"""The weekly digest: the editor's unused signals pooled, one roundup a week."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from services.news import digest, run
from services.news.signals import Signal
from services.news.store import LocalArticles
from services.news.tests.test_floor import FloorLLM
from services.news.tests.test_llm_pipeline import MORT, RATE, _draft, _fetcher, _world
from services.shared.states import ArticleKind

FRIDAY = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)   # 08:00 in Israel


def _point(period):
    """volume.y's value at `period` in the fixture every test dataset shares."""
    s = next(x for x in _world()[0][MORT] if x.path == "volume.y")
    return next(v for p, v in s.points if p.label == period)


def _sig(ds, score=1.0, period="2026-09", value=None, **facts):
    prev = f"2026-{int(period[-2:]) - 1:02d}"
    return Signal(ds, "volume.y", "y", "M", period, f"{period}-28",
                  _point(period) if value is None else value, ["streak_up"], score,
                  {"previous": {"period": prev, "value": _point(prev)}} | facts, score=score)


def _pool(*sigs):
    return [{"signal": s.to_dict(), "run_id": "r0", "skip_reason": "small"} for s in sigs]


def _world4():
    series, models, _sig0, cat = _world()
    series[RATE] = series[RATE] + series[MORT]   # every test dataset has volume.y
    for ds in ("d3", "d4"):
        series[ds], models[ds] = series[MORT], models[MORT]
        cat[ds] = {"title": f"מאגר {ds}", "page_slug": ds, "tags": [], "organization": "x"}
    return series, models, cat


def test_pool_items_keep_unpublished_candidates_with_reasons():
    a, b = _sig("a"), _sig("b")
    items = digest.pool_items([a, b], {a.key}, [{"key": b.key, "reason": "קטן"}], "r1")
    assert [i["signal"]["key"] for i in items] == [b.key] and items[0]["skip_reason"] == "קטן"


def test_rejected_event_brief_still_reaches_the_pool(tmp_path):
    series, models, sig, cat = _world()
    store = LocalArticles(tmp_path)
    run.write_day(FloorLLM([_draft()], critic=("kill",)), ranked=[sig], series_by_ds=series,
                  models=models, catalog=cat, vocab={"משכנתאות"}, store=store,
                  today=date(2026, 11, 9), run_id="r1", fetcher=_fetcher, images=False)
    assert [i["signal"]["key"] for i in store.read_pool(7)] == [sig.key]


def test_release_only_signals_stay_out_of_the_digest():
    series, _models, cat = _world4()
    quiet = [Signal(d, "volume.y", "y", "M", "2026-09", "2026-09-30", 1.0, ["new_release"], 0.6, {},
                    score=0.6) for d in (MORT, RATE, "d3", "d4")]
    assert digest.brief(_pool(*quiet), [], today=date(2026, 11, 13), cooldown_days=21,
                        series_by_ds=series, catalog=cat) is None


def test_brief_needs_enough_items_one_per_dataset():
    series, _models, cat = _world4()
    sigs = [_sig(MORT, 3), _sig(MORT, 2.9, period="2026-08"), _sig(RATE, 2), _sig("d3", 1.5)]
    assert digest.brief(_pool(*sigs), [], today=date(2026, 11, 13), cooldown_days=21,
                        series_by_ds=series, catalog=cat) is None   # 3 datasets < 4
    b = digest.brief(_pool(*sigs, _sig("d4", 1.0)), [], today=date(2026, 11, 13), cooldown_days=21,
                     series_by_ds=series, catalog=cat)
    assert b["kind"] == ArticleKind.DIGEST and b["dataset_ids"] == [MORT, RATE, "d3", "d4"]
    assert b["signal_keys"][-1] == "digest:2026-W46" and b["signals"][0].score == 3


def test_brief_skips_suspect_used_cooled_and_unknown_datasets():
    series, _models, cat = _world4()
    now = datetime.now(UTC)
    sigs = [_sig(MORT), _sig(RATE), _sig("d3"), _sig("d4", suspect_incomplete=True), _sig("gone")]
    recent = [{"dataset_ids": [MORT], "signal_keys": [], "published_at": (now - timedelta(days=3)).isoformat()}]
    assert digest.brief(_pool(*sigs), recent, today=date(2026, 11, 13), cooldown_days=21,
                        series_by_ds=series, catalog=cat) is None   # only RATE, d3 left


def test_one_digest_per_week():
    series, _models, cat = _world4()
    sigs = [_sig(d) for d in (MORT, RATE, "d3", "d4")]
    recent = [{"signal_keys": ["digest:2026-W46"], "dataset_ids": [], "published_at": "2026-11-13T06:00:00+00:00"}]
    assert digest.brief(_pool(*sigs), recent, today=date(2026, 11, 13), cooldown_days=0,
                        series_by_ds=series, catalog=cat) is None


def _day(tmp_path, llm, now, **kw):
    series, models, cat = _world4()
    store = LocalArticles(tmp_path)
    store.pool(_pool(*[_sig(d) for d in (MORT, RATE, "d3", "d4")]))
    return run.write_day(llm, ranked=[], series_by_ds=series, models=models, catalog=cat,
                         vocab={"משכנתאות", "ריבית"}, store=store, today=now.date(), run_id="r1",
                         fetcher=_fetcher, images=False, now=now, **kw), store


def test_digest_is_written_on_its_weekday_and_counts_toward_the_floor(tmp_path):
    # Real clock: articles are stamped with it, and the floor counts them by date.
    now = datetime.now(UTC)
    weekday = now.astimezone(run.IL_TZ).weekday()
    llm = FloorLLM([_draft()])
    out, _store = _day(tmp_path, llm, now, digest_weekday=weekday, min_per_day=1)
    assert out["digest"]["status"] == "published" and out["digest"]["items"] == 4, out
    assert "fill" not in out and llm.feature_calls == []
    doc = json.loads((tmp_path / out["published"][0] / "article.json").read_text(encoding="utf-8"))
    wk = digest.week_key(now.astimezone(run.IL_TZ).date())
    assert doc["kind"] == "digest" and wk in doc["signal_keys"]
    assert json.loads(llm.writer_msgs[1]["content"])["kind"] == "digest"
    assert all(not ({"web_search", "fetch_url"} & names) for names in llm.offered)
    # the same week again: no second digest
    out2, _ = _day(tmp_path, FloorLLM([_draft()]), now, digest_weekday=weekday)
    assert out2["digest"]["status"] == "skipped"


def test_busy_friday_still_gets_its_digest(tmp_path):
    out, _ = _day(tmp_path, FloorLLM([_draft()]), FRIDAY, digest_weekday=4, max_per_day=0)
    assert out["digest"]["status"] == "published"


def test_no_digest_on_other_days_or_when_off(tmp_path):
    out, _ = _day(tmp_path, FloorLLM([_draft()]), FRIDAY - timedelta(days=1), digest_weekday=4)
    assert "digest" not in out
    out, _ = _day(tmp_path, FloorLLM([_draft()]), FRIDAY)
    assert "digest" not in out


class _PoolDb:
    """Just enough Firestore for `signal_pool`: set, where(<, >=), stream, delete."""

    def __init__(self):
        self.docs: dict[str, dict] = {}

    def collection(self, name):
        db = self

        class Ref:
            def __init__(self, doc_id):
                self.id = doc_id

            def set(self, v):
                db.docs[self.id] = v

            def delete(self):
                db.docs.pop(self.id, None)

        class Snap:
            def __init__(self, doc_id):
                self.reference = Ref(doc_id)

            def to_dict(self):
                return dict(db.docs[self.reference.id])

        class Query:
            def __init__(self, f):
                self.f = f

            def stream(self):
                ops = {"<": lambda a, b: a < b, ">=": lambda a, b: a >= b}
                return [Snap(i) for i, d in list(db.docs.items())
                        if ops[self.f.op_string](d[self.f.field_path], self.f.value)]

        class Col:
            def document(self, doc_id):
                return Ref(doc_id)

            def where(self, *, filter):
                return Query(filter)

        return Col()


def test_firestore_pool_dedups_by_key_prunes_old_and_reads_the_week():
    from services.news.store import FirestoreArticles

    db = _PoolDb()
    st = FirestoreArticles(client=db)
    st.pool(_pool(_sig("a"), _sig("b")))
    st.pool(_pool(_sig("a")))                      # the same key again: one doc
    assert len(db.docs) == 2 and all("/" not in k for k in db.docs)
    stale = next(iter(db.docs))
    db.docs[stale]["pooled_at"] = datetime.now(UTC) - timedelta(days=10)
    assert len(st.read_pool(7)) == 1               # outside the week
    db.docs[stale]["pooled_at"] = datetime.now(UTC) - timedelta(days=15)
    st.pool([])                                    # every write prunes > 14 days
    assert len(db.docs) == 1


def test_local_pool_round_trip_and_window(tmp_path):
    store = LocalArticles(tmp_path)
    store.pool(_pool(_sig("a")))
    got = store.read_pool(7)
    assert got[0]["signal"]["key"] == _sig("a").key and got[0]["skip_reason"] == "small"
    p = next((tmp_path / "_pool").glob("*.json"))
    old = json.loads(p.read_text()) | {"pooled_at": (datetime.now(UTC) - timedelta(days=8)).isoformat()}
    p.write_text(json.dumps(old))
    assert store.read_pool(7) == []


def test_signal_revised_or_gone_since_it_was_pooled_stays_out():
    # The digest prints today's value beside the pooled change: a value the
    # source revised since (CBS does), or a series or period no longer there,
    # would put a stale change next to a fresh number.
    series, _models, cat = _world4()
    ok = [_sig(d) for d in (MORT, RATE, "d3", "d4")]
    b = digest.brief(_pool(*ok), [], today=date(2026, 11, 13), cooldown_days=21,
                     series_by_ds=series, catalog=cat)
    assert b is not None and len(b["signals"]) == 4
    revised = _sig("d4", value=_point("2026-09") + 0.5)
    prev_revised = _sig("d4", previous={"period": "2026-08", "value": _point("2026-08") - 1})
    gone_period = _sig("d4")
    gone_period.period = "2030-01"
    gone_series = _sig("d4")
    gone_series.series_path = "volume.nope"
    for bad in (revised, prev_revised, gone_period, gone_series):
        assert digest.brief(_pool(*ok[:3], bad), [], today=date(2026, 11, 13), cooldown_days=21,
                            series_by_ds=series, catalog=cat) is None, bad
