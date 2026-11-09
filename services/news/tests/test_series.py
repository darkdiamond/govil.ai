"""Series extraction — on real recipe models (fixtures/models, trimmed from
local renders on 2026-11-09) and on the shapes the corpus doesn't have yet."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from services.news.series import extract_series, kpi_values, parse_period

FIX = Path(__file__).parent / "fixtures" / "models"
TODAY = date(2026, 11, 9)


def _model(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("label, freq, start, end", [
    ("2024", "Y", date(2024, 1, 1), date(2024, 12, 31)),
    ("2024-02", "M", date(2024, 2, 1), date(2024, 2, 29)),
    ("2024-Q3", "Q", date(2024, 7, 1), date(2024, 9, 30)),
    ("Q4 2023", "Q", date(2023, 10, 1), date(2023, 12, 31)),
    ("2016-01-10", "D", date(2016, 1, 10), date(2016, 1, 10)),
    ("9.10.2022", "D", date(2022, 10, 9), date(2022, 10, 9)),
    ("מאי 1994", "M", date(1994, 5, 1), date(1994, 5, 31)),
    ("דצמבר 2025", "M", date(2025, 12, 1), date(2025, 12, 31)),
])
def test_parse_period(label, freq, start, end):
    p = parse_period(label)
    assert (p.freq, p.start, p.end) == (freq, start, end)


@pytest.mark.parametrize("label", ["ינואר", "1978-1979", "0-30 ימים", "תל אביב", "2024-13", "", None, True])
def test_non_periods(label):
    assert parse_period(label) is None


def test_boi_mortgage_series():
    ss = {s.path: s for s in extract_series(_model("boi-mortgage-rates"), "boi-mortgage-rates", TODAY)}
    assert ss["volume.y"].freq == "M" and len(ss["volume.y"].points) == 183
    assert ss["volume.sa"].points[-1][0].label == "2026-09"
    assert "rates.series[לא צמודה קבועה]" in ss
    # categorical charts (LTV / PTI buckets) are not series
    assert not any(p.startswith(("ltv.", "pti.")) for p in ss)


def test_boi_interest_rate_event_and_partial_year():
    ss = {s.path: s for s in extract_series(_model("boi-interest-rate"), "boi-interest-rate", TODAY)}
    assert ss["history"].freq == "E"
    assert ss["per_year.net"].freq == "Y" and ss["per_year.net"].partial_last  # 2026 in progress
    assert not any(p.startswith("cycles.") for p in ss)  # irregular cycle starts aren't a calendar


def test_weekly_from_daily_labels():
    ss = extract_series(_model("boi-card-spending"), "boi-card-spending", TODAY)
    assert [(s.path, s.freq) for s in ss] == [("total.y", "W")]


def test_registry_partial_flag_and_categories():
    ss = {s.path: s for s in extract_series(_model("e4c3e3d0-c4e4-497e-b2a5-43c533728624"), "e4", TODAY)}
    assert all(s.partial_last for s in ss.values())  # the chart says `partial`
    assert not any(p.startswith("types.") for p in ss)


def test_cumulative_detection():
    m = {"charts": {"c": {"x": [str(y) for y in range(2000, 2012)], "y": list(range(1, 13)),
                          "n": [5, 3, 6, 2, 7, 1, 8, 4, 9, 3, 6, 2]}}}
    ss = {s.path: s for s in extract_series(m, "d", TODAY)}
    assert ss["c.y"].cumulative and not ss["c.n"].cumulative


def test_decades_and_future_axes_are_not_series():
    m = {"charts": {
        "decades": {"x": ["1960", "1970", "1980", "1990", "2000", "2010", "2020"], "y": [1, 2, 3, 4, 5, 6, 7]},
        "expiry": {"x": [str(y) for y in range(2024, 2032)], "y": [1] * 8},
    }}
    assert extract_series(m, "d", TODAY) == []


def test_partial_judged_against_the_data_date():
    m = {"charts": {"m": {"x": [f"2026-{i:02d}" for i in range(1, 11)], "y": list(range(10))}}}
    # Data exported mid-October: October is partial even though it has ended now.
    (s,) = extract_series(m, "d", as_of=date(2026, 10, 15))
    assert s.partial_last and s.complete[-1][0].label == "2026-09"
    (s,) = extract_series(m, "d", as_of=date(2026, 11, 2))
    assert not s.partial_last


def test_nulls_and_label_arrays_skipped():
    x = [f"2025-{i:02d}" for i in range(1, 9)]
    m = {"charts": {"c": {"x": x, "y": [1, None, 3, 4, 5, 6, 7, 8], "names": ["a"] * 8,
                          "flag": [True] * 8}}}
    ss = {s.path: s for s in extract_series(m, "d", TODAY)}
    assert set(ss) == {"c.y"} and len(ss["c.y"].points) == 7


def test_kpi_values():
    k = kpi_values({"kpis": {"a": {"value": 3.25, "display": "3.25%"}, "b": {"display": "x"},
                             "c": {"value": "1,200"}}})
    assert k == {"a": 3.25, "c": 1200.0}
