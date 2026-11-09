"""Cross-dataset links, GSC demand mapping, snapshot reading and the
--signals-only CLI end to end on local snapshots."""
from __future__ import annotations

import gzip
import json
import math
from datetime import date

from services.news import demand, run
from services.news.links import Edge, attach_links, load_edges
from services.news.series import extract_series
from services.news.signals import Signal
from services.news.snapshots import LocalSnapshots


def _months(n, start_year=2018):
    return [f"{start_year + i // 12}-{i % 12 + 1:02d}" for i in range(n)]


def _wave(n, phase=0.0):
    return [100 + 10 * math.sin((i + phase) / 4) + i * 0.1 for i in range(n)]


def test_correlated_neighbour_is_linked_and_noise_is_not():
    n = 72
    a = {"charts": {"c": {"x": _months(n), "y": _wave(n)}}}
    b = {"charts": {"c": {"x": _months(n), "lagged": _wave(n, phase=-2),
                          "noise": [100 + ((i * 7919) % 13) for i in range(n)]}}}
    sa = extract_series(a, "A", date(2030, 1, 1))
    sb = extract_series(b, "B", date(2030, 1, 1))
    sig = Signal("A", "c.y", "y", "M", "x", "2023-12-31", 1.0, ["unusual_change"], 1.0, {})
    attach_links([sig], {"A": sa, "B": sb}, [Edge("A", "B", (0, 4), "why", "curated")])
    assert len(sig.links) == 1
    link = sig.links[0]
    assert link["series_path"] == "c.lagged" and link["r"] > 0.9 and link["lag"] == 2


def test_load_edges_curated_and_tags(tmp_path):
    lp = tmp_path / "links.json"
    lp.write_text(json.dumps({"edges": [{"a": "A", "b": "B", "lag_months": [0, 1], "why_he": "w"},
                                        {"a": "A", "b": "Z", "lag_months": [0, 1], "why_he": "w"}]}))
    tp = tmp_path / "tags.json"
    tp.write_text(json.dumps({"C": ["משכנתאות", "נדל\"ן", "x"], "D": ["משכנתאות", "נדל\"ן"],
                              "A": ["x"]}), encoding="utf-8")
    edges = load_edges({"A", "B", "C", "D"}, links_path=lp, tags_path=tp)
    assert {(e.a, e.b, e.source) for e in edges} == {("A", "B", "curated"), ("C", "D", "tags")}


def test_repo_links_json_names_real_recipes():
    from pathlib import Path

    from services.news.links import LINKS_PATH

    recipes = Path(__file__).resolve().parents[3] / "recipes"
    for e in json.loads(LINKS_PATH.read_text(encoding="utf-8"))["edges"]:
        for k in ("a", "b"):
            assert (recipes / e[k] / "recipe.json").is_file(), e[k]
        lo, hi = e["lag_months"]
        assert 0 <= lo <= hi and e["why_he"]


def test_dataset_demand_maps_page_urls():
    cat = {"id1": {"page_slug": "eggs"}, "id2": {"page_slug": "id2"}}
    rows = [{"page": "https://govil.ai/datasets/eggs/", "impressions": 100, "clicks": 3},
            {"page": "https://govil.ai/datasets/eggs", "impressions": 5, "clicks": 0},
            {"page": "https://govil.ai/datasets/id2/", "impressions": 7, "clicks": 1},
            {"page": "https://govil.ai/tags/%D7%90/", "impressions": 50, "clicks": 9}]
    d = demand.dataset_demand(rows, cat)
    assert d == {"id1": {"impressions": 105, "clicks": 3}, "id2": {"impressions": 7, "clicks": 1}}
    assert demand.multiplier(0) == 1.0 and 1.7 < demand.multiplier(1000) < 1.8


def test_demand_fails_soft():
    class Boom:
        def __init__(self):
            self.headers = {}

        def post(self, *a, **k):
            raise OSError("no network")

    assert demand.fetch_page_rows(session=Boom()) == []


def _snap(path, ds, ts, vals, rv=1):
    doc = {"dataset_id": ds, "rendered_at": ts, "recipe_version": rv,
           "metadata_modified": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T00:00:00+00:00",
           "model": {"charts": {"c": {"x": _months(len(vals)), "y": vals}}}}
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{ts}.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))
    # a stale latest copy the reader must ignore
    (path / "latest.json.gz").write_bytes(gzip.compress(json.dumps(doc | {"model": {}}).encode()))


def test_signals_only_end_to_end(tmp_path, capsys):
    base = [100 + 5 * math.sin(i * 1.7) for i in range(48)]
    # 2022-01 + 48 months → Jan 2026; the spike lands in 2026-01.
    _snap(tmp_path / "A", "A", "20260101T040000Z", [*base[:-1]])
    _snap(tmp_path / "A", "A", "20260210T040000Z", [*base[:-1], 190.0])
    # Same data in both snapshots: nothing new, no signal.
    _snap(tmp_path / "B", "B", "20260101T040000Z", base)
    _snap(tmp_path / "B", "B", "20260210T040000Z", base)
    rc = run.main(["--signals-only", "--models-dir", str(tmp_path), "--today", "2026-06-01",
                   "--no-catalog", "--json"])
    assert rc == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    head, sigs = lines[0], lines[1:]
    assert head["type"] == "news_signals" and head["with_history"] == 2
    assert [s["dataset_id"] for s in sigs] == ["A"]
    assert sigs[0]["new_since_previous"] is True and "record_high" in sigs[0]["flags"]


def test_local_snapshots_reads_bare_dumps(tmp_path):
    (tmp_path / "X.json").write_text(json.dumps({"charts": {}}))
    st = LocalSnapshots(tmp_path)
    assert st.ids() == ["X"]
    (snap,) = st.recent("X")
    assert snap.model == {"charts": {}} and snap.data_as_of is None
