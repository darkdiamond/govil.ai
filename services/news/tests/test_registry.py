"""Registry signals (NEWS_REGISTRY_SIGNALS): snapshot diffs of lists of entities
and monthly KPI history; and the breaking-news exception to the cooldown."""
from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from services.news import registry, run
from services.news.editor import eligible, is_breaking
from services.news.ledger import Ledger
from services.news.registry import (
    categories,
    detect_registry,
    kpi_history_series,
    month_picks,
    pick_ref,
)
from services.news.signals import Signal
from services.news.snapshots import LocalSnapshots
from services.news.writer import seed_facts

CITIES = ["חיפה", "ירושלים", "באר שבע", "נתניה", "אשדוד"]


def _model(names=CITIES, values=(50, 40, 30, 20, 10), kpis=None, **charts):
    return {"charts": {"cities": {"names": list(names), "values": list(values)}} | charts,
            "kpis": kpis or {}, "labels": {"cities_caption": "רישיונות לפי עיר"}}


def _flags(sigs):
    return sorted(f for s in sigs for f in s.flags)


# ── categories ──────────────────────────────────────────────────────────

def test_categories_reads_the_common_shapes():
    assert categories({"names": ["א", "ב", "ג"], "values": [3, 2, 1]}) == ({"א": 3, "ב": 2, "ג": 1}, False)
    assert categories([{"name": "א", "value": 1}, {"name": "ב", "value": 2},
                       {"name": "ג", "value": 3}])[0] == {"א": 1, "ב": 2, "ג": 3}
    stacked = {"names": ["א", "ב", "ג"], "series": [{"name": "s1", "data": [1, 2, 3]},
                                                   {"name": "s2", "data": [1, 1, 1]}]}
    assert categories(stacked)[0] == {"א": 2, "ב": 3, "ג": 4}
    # several measures: names only
    assert categories({"names": ["א", "ב", "ג"], "area": [1, 2, 3], "count": [3, 2, 1]})[0] == \
        {"א": None, "ב": None, "ג": None}


def test_categories_refuses_bins_dates_months_and_flags_top_n():
    assert categories({"names": ["0-10", "10-20", "20-30"], "values": [1, 2, 3]}) is None
    assert categories({"names": ["2024-01", "2024-02", "2024-03"], "values": [1, 2, 3]}) is None
    assert categories({"names": ["ינואר", "פברואר", "מרץ"], "values": [1, 2, 3]}) is None
    assert categories({"names": ["א (12)", "ב (5)", "ג (3)"], "values": [12, 5, 3]}) is None
    names, capped = categories({"names": ["א", "ב", "ג", "אחר"], "values": [4, 3, 2, 9]})
    assert capped and "אחר" not in names


def test_a_100pct_stack_has_no_ranking():
    c = categories({"names": ["א", "ב", "ג"], "series": [{"name": "x", "data": [60, 30.1, 50]},
                                                        {"name": "y", "data": [40, 70, 50]}]})
    assert set(c[0].values()) == {None}


# ── snapshot diffs ──────────────────────────────────────────────────────

def test_new_entrant_and_exit_in_a_complete_list():
    base = _model()
    latest = _model(names=CITIES + ["אילת"], values=(50, 40, 30, 20, 10, 1))
    [new] = detect_registry("ds", latest, "20261117T080000Z", base, "20261116T080000Z")
    assert new.flags == ["new_entrant"]
    assert new.facts["entrants"][0]["name"] == "אילת"   # small, but a new entity in a full list
    assert new.period == "2026-11-17" and new.facts["compared_to"] == "2026-11-16"
    assert new.key == "ds|chart:cities:new|2026-11-17"
    [gone] = detect_registry("ds", _model(names=CITIES[:4], values=(50, 40, 30, 20)), "t", base, "x")
    assert gone.flags == ["exit"] and gone.facts["exits"] == [{"name": "אשדוד", "value_then": 10}]


def test_a_name_climbing_into_a_top_n_list_is_not_news():
    base = _model(names=CITIES + ["אחר"], values=(50, 40, 30, 20, 10, 99))
    latest = _model(names=["חיפה", "ירושלים", "באר שבע", "נתניה", "אילת", "אחר"],
                    values=(50, 40, 30, 20, 11, 99))
    assert detect_registry("ds", latest, "20261117T080000Z", base, "20261116T080000Z") == []
    # same-length list with a swap: treated as a top-N cut too
    latest = _model(names=["חיפה", "ירושלים", "באר שבע", "נתניה", "אילת"], values=(50, 40, 30, 20, 11))
    assert detect_registry("ds", latest, "20261117T080000Z", _model(), "20261116T080000Z") == []


def test_a_name_seen_before_is_a_flap_not_an_entrant():
    base = _model()
    latest = _model(names=CITIES + ["אילת"], values=(50, 40, 30, 20, 10, 5))
    older = _model(names=CITIES + ["אילת"], values=(50, 40, 30, 20, 10, 4))
    assert _flags(detect_registry("ds", latest, "20261117T080000Z", base, "x")) == ["new_entrant"]
    assert detect_registry("ds", latest, "20261117T080000Z", base, "x", history=[older]) == []


def test_leader_change_needs_a_real_overtake_and_a_new_leader():
    base = _model()
    latest = _model(values=(50, 60, 30, 20, 10))
    [s] = detect_registry("ds", latest, "20261117T080000Z", base, "x")
    assert s.flags == ["leader_change"] and s.facts["leader"]["name"] == "ירושלים"
    assert s.facts["previous_leader"] == {"name": "חיפה", "value_now": 50, "value_then": 50}
    was = _model(values=(10, 60, 30, 20, 5))   # ירושלים led before: a flap
    assert detect_registry("ds", latest, "20261117T080000Z", base, "x", history=[was]) == []


def test_unstable_axes_are_skipped():
    base = _model()
    latest = _model(names=["א", "ב", "ג", "ד", "ה"])
    assert detect_registry("ds", latest, "t", base, "x") == []


def test_kpi_move_fires_once_when_it_crosses():
    ref = _model(kpis={"active": {"value": 100, "display": "100"}})
    base = _model(kpis={"active": {"value": 95, "display": "95"}})
    latest = _model(kpis={"active": {"value": 85, "display": "85"}})
    [s] = detect_registry("ds", latest, "20261117T080000Z", base, "20261116T080000Z", ref,
                          "20261020T080000Z")
    assert s.flags == ["kpi_move"] and s.value == 85
    assert s.facts["previous"] == {"period": "2026-10-20", "value": 100} and s.facts["change_pct"] == -15
    # the last run already saw it past the line: no repeat
    assert detect_registry("ds", latest, "t", latest, "t", ref, "r") == []
    # small moves and rolling-window KPIs never fire
    small = _model(kpis={"active": {"value": 97, "display": "97"}})
    assert detect_registry("ds", small, "t", base, "t", ref, "r") == []
    roll = {"ytd": {"value": 10, "display": "10"}}
    assert detect_registry("ds", _model(kpis={"ytd": {"value": 50, "display": "50"}}), "t",
                           _model(kpis=roll), "t", _model(kpis=roll), "r") == []


def test_kpi_percentages_move_in_points_and_mismatches_are_skipped():
    ref = _model(kpis={"exp": {"value": 0.10, "display": "10.0%"}})
    base = _model(kpis={"exp": {"value": 0.11, "display": "11.0%"}})
    latest = _model(kpis={"exp": {"value": 0.14, "display": "14.0%"}})
    [s] = detect_registry("ds", latest, "t", base, "t", ref, "r")
    assert s.value == 14.0 and s.facts["previous"]["value"] == 10.0 and s.facts["change_pp"] == 4.0
    # a count under a percent display: nothing safe to compare
    bad = {"n": {"value": 3341, "display": "53.2%"}}
    assert detect_registry("ds", _model(kpis={"n": {"value": 3395, "display": "54.0%"}}), "t",
                           _model(kpis=bad), "t", _model(kpis=bad), "r") == []


def test_pick_ref_and_month_picks():
    names = [("20261118T080000Z", "a"), ("20261115T080000Z", "b"), ("20261110T080000Z", "c"),
             ("20261020T080000Z", "d"), ("20261001T080000Z", "e")]
    assert pick_ref(names, "20261118T080000Z") == ("20261020T080000Z", "d")
    assert pick_ref(names[:3], "20261118T080000Z") == ("20261110T080000Z", "c")   # young history
    assert pick_ref(names[:2], "20261118T080000Z") is None
    assert month_picks(names) == [("20261118T080000Z", "a"), ("20261020T080000Z", "d")]


def test_kpi_history_series_is_monthly_with_a_partial_last_month():
    monthly = [(f"2026{m:02d}28T080000Z", {"kpis": {"active": {"value": 100 + m, "display": "x"},
                                                     "ytd": {"value": m, "display": "x"}}})
               for m in range(1, 12)]
    [s] = kpi_history_series("ds", monthly, date(2026, 11, 18))
    assert s.path == "kpi_history.active" and s.freq == "M" and len(s.points) == 11
    assert s.partial_last and s.complete[-1][0].label == "2026-10"


# ── run integration ─────────────────────────────────────────────────────

def _snap(root: Path, ds: str, ts: str, model: dict, version: int = 1):
    d = root / ds
    d.mkdir(parents=True, exist_ok=True)
    doc = {"dataset_id": ds, "rendered_at": ts, "recipe_version": version, "metadata_modified": None,
           "model": model}
    (d / f"{ts}.json.gz").write_bytes(gzip.compress(json.dumps(doc).encode()))


def test_find_signals_adds_registry_signals_only_when_on(tmp_path):
    _snap(tmp_path, "reg", "20261020T080000Z", _model(kpis={"active": {"value": 100, "display": "100"}}))
    _snap(tmp_path, "reg", "20261116T080000Z", _model(kpis={"active": {"value": 99, "display": "99"}}))
    _snap(tmp_path, "reg", "20261117T090000Z", _model(names=CITIES + ["אילת"], values=(50, 40, 30, 20, 10, 2),
                                                     kpis={"active": {"value": 80, "display": "80"}}))
    _snap(tmp_path, "cbs-x", "20261116T080000Z", _model())
    _snap(tmp_path, "cbs-x", "20261117T090000Z", _model(names=CITIES + ["אילת"], values=(5, 4, 3, 2, 1, 1)))
    kw = {"today": date(2026, 11, 17), "cutoff": "20261117T000000Z", "workers": 2}
    off, _ = run.find_signals(LocalSnapshots(tmp_path), **kw)
    assert off == []
    on, stats = run.find_signals(LocalSnapshots(tmp_path), registries=True, **kw)
    assert {(s.dataset_id, s.flags[0]) for s in on} == {("reg", "new_entrant"), ("reg", "kpi_move")}
    assert stats["registry_signals"] == 2 and stats["registry_errors"] == 0
    kpi = next(s for s in on if s.flags == ["kpi_move"])
    assert kpi.facts["previous"] == {"period": "2026-10-20", "value": 100}


def test_writer_seeds_registry_facts():
    from types import SimpleNamespace

    tb = SimpleNamespace(series={}, ledger=Ledger())
    kpi = Signal("ds", "kpi:active", "רישיונות פעילים", "", "2026-11-17", "2026-11-17", 80.0, ["kpi_move"],
                 2.0, {"previous": {"period": "2026-10-20", "value": 100}, "change_pct": -20.0, "kpi": "active"})
    new = Signal("ds", "chart:c:new", "לפי עיר", "", "2026-11-17", "2026-11-17", 2.0, ["new_entrant"], 1.2,
                 {"entrants": [{"name": "אילת", "value": 2}, {"name": "ערד", "value": None}]})
    [k, n] = seed_facts(tb, {"signals": [kpi, new]})
    assert tb.ledger.facts[k["latest"]["fact"]].value == 80
    assert tb.ledger.facts[k["previous"]["fact"]].value == 100
    assert "fact" in k["change_pct"]
    assert tb.ledger.facts[n["entrants"][0]["fact"]].value == 2 and "fact" not in n["entrants"][1]


# ── breaking news beats the cooldown ────────────────────────────────────

def _sig(period="2026-10", flags=("record_high",), surprise=3.0, **facts):
    return Signal("ds", "s.y", "", "M", period, "2026-10-31", 1.0, list(flags), surprise, dict(facts))


def _article(period="2026-09", minutes_ago=60):
    return {"kind": "news", "headline": "כותרת קודמת", "dataset_ids": ["ds"],
            "signal_keys": [f"ds|s.y|{period}"],
            "published_at": (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()}


def test_a_breaking_signal_on_new_data_skips_the_cooldown():
    sig = _sig()
    assert eligible([sig], [_article()], cooldown_days=21) == []   # off: cooldown holds
    [out] = eligible([sig], [_article()], cooldown_days=21, breaking_surprise=2.5)
    assert out.facts["follows_article"]["headline"] == "כותרת קודמת"


def test_breaking_never_retells_a_covered_period_or_lifts_weak_signals():
    assert eligible([_sig(period="2026-09")], [_article()], cooldown_days=21, breaking_surprise=2.5) == []
    weak = _sig(surprise=1.2, flags=("streak_up",))
    assert eligible([weak], [_article()], cooldown_days=21, breaking_surprise=2.5) == []
    assert not is_breaking(_sig(suspect_incomplete=True), 2.5)
    assert not is_breaking(replace(_sig(), flags=["new_release"], surprise=9.0), 2.5)
    assert not is_breaking(replace(_sig(), flags=["kpi_move"], surprise=9.0), 2.5)


def test_env_float_parses_or_turns_off(monkeypatch):
    for raw, want in (("2.5", 2.5), ("", None), ("0", None), ("x", None)):
        monkeypatch.setenv("NEWS_BREAKING_SURPRISE", raw)
        assert run._env_float("NEWS_BREAKING_SURPRISE") == want
    assert registry.REGISTRY_FLAGS == {"new_entrant", "exit", "leader_change", "kpi_move"}
