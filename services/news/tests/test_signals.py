"""Detectors on synthetic series with known answers, plus freshness and the
incomplete-period guard."""
from __future__ import annotations

import math
from datetime import date

from services.news.series import extract_series
from services.news.signals import detect, detect_all, rank


def _monthly(vals, start=(2022, 1)):
    y, m = start
    x = []
    for _ in vals:
        x.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return x


def _noise(n, base=100.0, amp=5.0):
    """Deterministic seasonal-ish wiggle, no trend."""
    return [base + amp * math.sin(i * 1.7) + amp * 0.5 * math.cos(i * 0.9) for i in range(n)]


def _series(vals, x=None, key="y", ds="d"):
    m = {"charts": {"c": {"x": x or _monthly(vals), key: vals}}}
    return extract_series(m, ds, as_of=date(2030, 1, 1))[0]


def _after(s, days=10):
    end = s.complete[-1][0].end
    return date.fromordinal(end.toordinal() + days)


def test_flat_noise_gives_no_signal():
    s = _series(_noise(48))
    assert detect(s, _after(s)) is None


def test_spike_is_unusual_and_a_record():
    vals = _noise(48) + [180.0]
    s = _series(vals)
    sig = detect(s, _after(s))
    assert sig and "record_high" in sig.flags and "unusual_change" in sig.flags
    assert sig.facts["rank_high"] == 1 and sig.facts["yoy_pct"] > 50
    assert sig.period == s.complete[-1][0].label


def test_high_since_names_the_period():
    vals = [100.0] * 6 + [300.0] + [100 + (i % 5) for i in range(80)] + [250.0]
    s = _series(vals)
    sig = detect(s, _after(s))
    assert "high_since" in sig.flags and sig.facts["high_since"] == s.points[6][0].label


def test_stale_period_is_not_news():
    s = _series(_noise(48) + [180.0])
    assert detect(s, _after(s, days=200)) is None


def test_previous_snapshot_decides_newness():
    vals = _noise(48) + [180.0]
    s = _series(vals)
    same = _series(vals)
    assert detect(s, _after(s, 400), previous=same) is None          # nothing new since
    older = _series(vals[:-1], x=_monthly(vals)[:-1])
    sig = detect(s, _after(s, 400), previous=older)                  # new, even if old by date
    assert sig and sig.new_since_previous is True


def test_streak_down():
    vals = _noise(40) + [99, 97, 95, 93, 91, 89, 87]
    s = _series(vals)
    sig = detect(s, _after(s))
    assert sig and "streak_down" in sig.flags and sig.facts["streak"] <= -6


def test_running_totals_never_set_records():
    vals = [float(i * 10) for i in range(1, 40)]
    s = _series(vals)
    assert s.cumulative
    sig = detect(s, _after(s))
    assert sig is None or not {"record_high", "streak_up"} & set(sig.flags)


def test_half_loaded_month_is_suspect_and_taints_siblings():
    base = [float(round(v)) for v in _noise(36)]  # a count
    x = _monthly(base + [10.0])
    roll = [sum((base + [10.0])[max(0, i - 11):i + 1]) / min(i + 1, 12) for i in range(37)]
    m = {"charts": {"c": {"x": x, "y": base + [10.0], "roll": roll}}}
    ss = extract_series(m, "d", as_of=date(2030, 1, 1))
    sigs = detect_all(ss, _after(ss[0]))
    assert sigs and all(s.facts.get("suspect_incomplete") for s in sigs)
    full = detect(_series(_noise(36) + [180.0]), _after(ss[0]))
    assert max(s.surprise for s in sigs) < full.surprise


def test_year_closed_flag():
    vals = [100.0 + (i % 3) for i in range(12)]
    s = _series(vals, x=[str(y) for y in range(2014, 2026)])
    sig = detect(s, date(2026, 1, 20))
    assert sig and "year_closed" in sig.flags


def test_event_series_change_and_pivot():
    pairs = [["2024-01-01", "4.75"], ["2024-03-01", "4.5"], ["2024-06-01", "4.5"],
             ["2024-09-01", "4.25"], ["2025-01-01", "4.0"], ["2025-06-01", "4.0"],
             ["2025-10-01", "3.75"], ["2026-10-20", "4.0"]]
    s = extract_series({"charts": {"history": pairs}}, "r", as_of=date(2026, 11, 1))[0]
    sig = detect(s, date(2026, 10, 25))
    assert sig and sig.flags[0] == "event_change" and "pivot" in sig.flags
    assert sig.facts["change"] == 0.25


def test_event_series_without_a_move_is_quiet():
    pairs = [[f"2025-{m:02d}-01", "4.0"] for m in range(1, 10)]
    s = extract_series({"charts": {"history": pairs}}, "r", as_of=date(2025, 10, 1))[0]
    assert detect(s, date(2025, 9, 5)) is None


def test_rank_caps_per_dataset_and_applies_demand():
    vals = _noise(48) + [180.0]
    sigs = []
    for ds in ("a", "b"):
        for k in ("y1", "y2", "y3", "y4"):
            s = _series(vals, key=k, ds=ds)
            sigs.append(detect(s, _after(s)))
    for s in sigs:
        s.demand = 2.0 if s.dataset_id == "b" else 1.0
    out = rank(sigs, per_dataset=2)
    assert [s.dataset_id for s in out] == ["b", "b", "a", "a"]


def test_weekly_year_over_year_is_52_weeks_back():
    from datetime import timedelta

    start = date(2022, 1, 2)
    x = [(start + timedelta(weeks=i)).isoformat() for i in range(130)]
    vals = [100.0 + (i * 7919) % 11 for i in range(129)] + [160.0]
    s = extract_series({"charts": {"t": {"x": x, "y": vals}}}, "w", as_of=date(2030, 1, 1))[0]
    assert s.freq == "W"
    sig = detect(s, _after(s, 3))
    assert sig.facts["year_ago"]["period"] == x[-53]
    assert sig.facts["change_basis"] == "yoy" and "unusual_change" in sig.flags


def test_falling_share_is_not_suspect_incomplete():
    vals = [1.5 + 0.01 * (i % 3) for i in range(36)] + [0.4]
    s = _series(vals)
    sig = detect(s, _after(s))
    assert sig and not sig.facts.get("suspect_incomplete")


# ── release stories ─────────────────────────────────────────────────────

def test_quiet_release_period_signals_only_when_enabled():
    s = _series(_noise(48), ds="cbs-average-wage")
    assert detect(s, _after(s)) is None
    sig = detect(s, _after(s), releases=True)
    assert sig and sig.flags == ["new_release"] and sig.facts.get("yoy_pct") is not None
    # not for other datasets, and not for an old period
    other = _series(_noise(48), ds="9c64c522-aaaa")
    assert detect(other, _after(other), releases=True) is None
    assert detect(s, _after(s, days=400), releases=True) is None


def test_release_is_weaker_than_any_anomaly_and_sub_series_rank_below():
    quiet = _series(_noise(48), ds="cbs-cpi")
    spike = _series(_noise(48) + [180.0], ds="d")
    head = detect(quiet, _after(quiet), releases=True, order=0)
    sub = detect(quiet, _after(quiet), releases=True, order=5)
    anomaly = detect(spike, _after(spike), releases=True)
    assert anomaly.surprise > head.surprise > sub.surprise


def test_rank_keeps_one_release_story_per_dataset():
    sigs = []
    for i, k in enumerate(("headline", "food", "fuel")):
        s = _series(_noise(48), key=k, ds="cbs-cpi")
        sigs.append(detect(s, _after(s), releases=True, order=i))
    assert [s.series_path for s in rank(sigs)] == ["c.headline"]


def test_held_rate_is_a_release_not_silence():
    pairs = [[f"2025-{m:02d}-01", "4.0"] for m in range(1, 10)]
    s = extract_series({"charts": {"history": pairs}}, "boi-interest-rate", as_of=date(2025, 10, 1))[0]
    assert detect(s, date(2025, 9, 5)) is None
    sig = detect(s, date(2025, 9, 5), releases=True)
    assert sig and sig.flags == ["new_release"] and sig.facts["change"] == 0
