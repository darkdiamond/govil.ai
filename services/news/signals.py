"""What is new and unusual in a series — deterministic, no LLM.

A signal is about the latest complete period of one series, and only when
that period is NEW: it appeared since the previous model snapshot, or (with
no history yet) it ended recently enough to still be news (`FRESH_DAYS`).
Old data is never a story, however odd.

Each fresh period gets facts (value, change, year-over-year, rank, "highest
since") and zero or more flags, each with a surprise weight:

    record_high / record_low     beyond every earlier value (not for running totals)
    high_since / low_since       highest/lowest in ≥ 5 years
    unusual_change               robust z (median/MAD) of the change ≥ Z_MIN
    streak_up / streak_down      N periods in a row the same way
    yoy_turn                     year-over-year sign flipped after a long run
    event_change                 a step series moved (e.g. a rate decision)
    pivot                        …and in the opposite direction to the last move
    year_closed                  a calendar year completed (always worth a look)

surprise = strongest flag + a quarter of the rest. Ranking multiplies in
search demand (`demand.py`) and cross-dataset links (`links.py`).
"""
from __future__ import annotations

import itertools
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date

from .series import Series, _index

# How long after a period ends its first appearance can still be news, when
# there's no earlier snapshot to tell exactly. Generous: publishers lag (CBS
# monthly ~6 weeks, annual registries months).
FRESH_DAYS = {"D": 10, "W": 21, "M": 75, "Q": 150, "Y": 150, "E": 14}
# Minimum complete history before anything can be "unusual".
MIN_HISTORY = {"D": 60, "W": 52, "M": 24, "Q": 12, "Y": 8, "E": 8}
SEASON_LAG = {"M": 12, "Q": 4, "W": 52}
STREAK_MIN = {"D": 10, "W": 8, "M": 6, "Q": 4, "Y": 4}
YOY_TURN_RUN = {"M": 12, "Q": 4, "W": 26}
Z_MIN = 2.5
SINCE_MIN_YEARS = 5


@dataclass
class Signal:
    dataset_id: str
    series_path: str
    label: str
    freq: str
    period: str
    period_end: str
    value: float
    flags: list[str]
    surprise: float
    facts: dict
    new_since_previous: bool | None = None   # None = no earlier snapshot to compare
    demand: float = 1.0
    links: list[dict] = field(default_factory=list)
    score: float = 0.0

    @property
    def key(self) -> str:
        """Identity for dedup: one story per series per period."""
        return f"{self.dataset_id}|{self.series_path}|{self.period}"

    def to_dict(self) -> dict:
        return asdict(self) | {"key": self.key}


def _robust_z(history: list[float], x: float) -> float | None:
    if len(history) < 8:
        return None
    med = statistics.median(history)
    mad = statistics.median(abs(h - med) for h in history)
    if mad == 0:
        return None  # flat history (a held rate): z says nothing
    return (x - med) / (1.4826 * mad)


def _pct(a: float, b: float) -> float | None:
    return (a - b) / abs(b) * 100 if b else None


def _changes(pts: list[tuple], freq: str) -> tuple[list[float], str] | None:
    """The change series the z-score runs on: year-over-year where the
    frequency is seasonal (in % when the series is positive, else in units),
    period-over-period otherwise."""
    vals = [v for _, v in pts]
    lag = SEASON_LAG.get(freq)
    by_idx = {_index(p): v for p, v in pts}
    positive = all(v > 0 for v in vals)
    if lag and len(pts) > lag + MIN_HISTORY.get(freq, 8):
        out = []
        for p, v in pts:
            prev = by_idx.get(_index(p) - lag)
            if prev is not None:
                out.append(_pct(v, prev) if positive else v - prev)
        return [c for c in out if c is not None], "yoy"
    if len(vals) < 3:
        return None
    out = [(_pct(b, a) if positive else b - a) for a, b in itertools.pairwise(vals)]
    return [c for c in out if c is not None], "pop"


def _since(pts: list[tuple], higher: bool) -> str | None:
    """Label of the latest earlier period that matched or beat the last value
    (None when nothing did — a record)."""
    last = pts[-1][1]
    for p, v in reversed(pts[:-1]):
        if (v >= last) if higher else (v <= last):
            return p.label
    return None


def _streak(vals: list[float]) -> int:
    """Signed length of the run of same-direction moves ending at the last value."""
    n, sign = 0, 0
    for a, b in zip(reversed(vals[:-1]), reversed(vals[1:]), strict=False):
        s = (b > a) - (b < a)
        if s == 0 or (sign and s != sign):
            break
        sign, n = s, n + 1
    return n * sign


SUSPECT_DROP = 0.35   # newest value below this share of the recent median
SUSPECT_FACTOR = 0.3


def _suspect_incomplete(vals: list[float]) -> bool:
    recent = vals[-13:-1]
    if len(recent) < 6 or any(v < 0 for v in vals):
        return False
    med = statistics.median(recent)
    return med > 0 and vals[-1] < SUSPECT_DROP * med


def detect(series: Series, as_of: date, previous: Series | None = None) -> Signal | None:
    """The signal for the series' latest complete period, or None."""
    pts = series.complete
    if len(pts) < MIN_HISTORY.get(series.freq, 8):
        return None
    last_p, last_v = pts[-1]
    new: bool | None = None
    if previous is not None:
        seen = {p.start for p, _ in previous.complete}
        new = last_p.start not in seen
        if not new:
            return None
    elif (as_of - last_p.end).days > FRESH_DAYS.get(series.freq, 30):
        return None

    prev_p, prev_v = pts[-2]
    facts: dict = {"previous": {"period": prev_p.label, "value": prev_v},
                   "change": last_v - prev_v, "change_pct": _pct(last_v, prev_v)}
    vals = [v for _, v in pts]
    flags: dict[str, float] = {}

    if series.freq == "E":
        if last_v == prev_v:
            return None
        flags["event_change"] = 2.5
        if len(pts) >= 3:
            before = prev_v - pts[-3][1]
            if before and (before > 0) != (last_v > prev_v):
                flags["pivot"] = 1.0
        facts["since_previous_days"] = (last_p.start - prev_p.start).days
    else:
        lag = SEASON_LAG.get(series.freq)
        if lag:
            by_idx = {_index(p): (p, v) for p, v in pts}
            ly = by_idx.get(_index(last_p) - lag)
            if ly:
                facts["year_ago"] = {"period": ly[0].label, "value": ly[1]}
                facts["yoy"] = last_v - ly[1]
                facts["yoy_pct"] = _pct(last_v, ly[1])
        rank_hi = 1 + sum(v > last_v for v in vals[:-1])
        facts["rank_high"], facts["rank_low"], facts["n_periods"] = (
            rank_hi, 1 + sum(v < last_v for v in vals[:-1]), len(vals))
        facts["first_period"] = pts[0][0].label

        if not series.cumulative:
            for higher, rec, since in ((True, "record_high", "high_since"),
                                       (False, "record_low", "low_since")):
                lbl = _since(pts, higher)
                if lbl is None:
                    flags[rec] = 3.0
                    facts[rec] = True
                else:
                    sp = next(p for p, _ in pts if p.label == lbl)
                    years = (last_p.start - sp.start).days / 365.25
                    if years >= SINCE_MIN_YEARS:
                        flags[since] = min(1.5 + 0.1 * (years - SINCE_MIN_YEARS), 2.5)
                        facts[since] = lbl

        ch = _changes(pts, series.freq)
        if ch and len(ch[0]) >= 9:
            hist, basis = ch
            z = _robust_z(hist[:-1], hist[-1])
            if z is not None:
                facts["change_z"], facts["change_basis"] = round(z, 2), basis
                if abs(z) >= Z_MIN:
                    flags["unusual_change"] = min(abs(z) / 2, 3.5)

        if not series.cumulative:
            st = _streak(vals)
            thr = STREAK_MIN.get(series.freq)
            if thr and abs(st) >= thr:
                flags["streak_up" if st > 0 else "streak_down"] = min(1 + 0.1 * (abs(st) - thr), 2.0)
                facts["streak"] = st

        run = YOY_TURN_RUN.get(series.freq)
        if run and ch and ch[1] == "yoy" and len(ch[0]) > run:
            h = ch[0]
            if h[-1] and all(c and (c > 0) != (h[-1] > 0) for c in h[-run - 1:-1]):
                flags["yoy_turn"] = 1.5

        if series.freq == "Y":
            flags["year_closed"] = 0.8

    if not flags:
        return None
    ws = sorted(flags.values(), reverse=True)
    surprise = ws[0] + 0.25 * sum(ws[1:])
    if series.freq != "E" and _suspect_incomplete(vals):
        # A count that fell off a cliff in its newest period is usually a
        # period loaded halfway (published mid-month), not news. Keep it, but
        # far down the list and marked, so the writer checks before trusting.
        facts["suspect_incomplete"] = True
        surprise *= SUSPECT_FACTOR
    surprise = round(surprise, 3)
    return Signal(series.dataset_id, series.path, series.label, series.freq, last_p.label,
                  last_p.end.isoformat(), last_v, sorted(flags, key=flags.get, reverse=True),
                  surprise, facts, new)


def detect_all(series: list[Series], as_of: date,
               previous: dict[str, Series] | None = None) -> list[Signal]:
    """`previous`: path → the same series in the previous snapshot."""
    out = []
    for s in series:
        sig = detect(s, as_of, (previous or {}).get(s.path) if previous is not None else None)
        if sig:
            out.append(sig)
    # A half-loaded period taints every series drawn from it: a chart's
    # rolling average or share line over the same period is just as suspect.
    tainted = {(_chart(s.series_path), s.period) for s in out if s.facts.get("suspect_incomplete")}
    for s in out:
        if (_chart(s.series_path), s.period) in tainted and not s.facts.get("suspect_incomplete"):
            s.facts["suspect_incomplete"] = True
            s.surprise = round(s.surprise * SUSPECT_FACTOR, 3)
    return out


def _chart(path: str) -> str:
    return path.split(".", 1)[0]


def rank(signals: list[Signal], *, per_dataset: int = 3, top: int | None = None) -> list[Signal]:
    """Score (surprise × demand × link bonus) and keep the strongest few per
    dataset, so one dataset's dozen near-identical series can't crowd the list."""
    for s in signals:
        link_bonus = 1 + 0.15 * min(len(s.links), 3)
        s.score = round(s.surprise * s.demand * link_bonus, 3)
    out, per = [], {}
    for s in sorted(signals, key=lambda s: (-s.score, s.key)):
        if per.get(s.dataset_id, 0) >= per_dataset:
            continue
        per[s.dataset_id] = per.get(s.dataset_id, 0) + 1
        out.append(s)
    return out[:top] if top else out
