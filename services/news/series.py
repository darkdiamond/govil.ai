"""Time series out of a recipe page model.

Recipe models are free-form (`charts` is whatever the template needs), but a
few shapes cover nearly every time chart in the corpus (surveyed 2026-11-09
over 29 real models):

    {"x": [periods], "<key>": [numbers], …}          one series per numeric key
    {"x": [periods], "series": [{"name", "data"}]}  one series per entry
    [[date, value], …]                               an event/step series
    {"<key>": [[date, value], …], …}                 one event series per key

A period label is a year ("2024"), a month ("2024-11"), a quarter
("2024-Q3", "Q3 2024"), a date ("2024-11-03", "3.11.2024") or a Hebrew
"month year" ("מאי 1994"). Charts whose x doesn't parse as one consistent,
strictly increasing calendar (categories, month-of-year seasonality,
"1978-1979" spans) are not series and are skipped.

Pure functions, no I/O.
"""
from __future__ import annotations

import itertools
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

# Hebrew month names (govlib.fmt.MONTHS_HE spelling, kept local: govlib is a
# sandbox lib whose outputs are frozen; this module only needs to read them).
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
             "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
_MONTH_IDX = {m: i + 1 for i, m in enumerate(MONTHS_HE)} | {"מרס": 3}

MIN_POINTS = 6  # shorter runs carry no history to be surprising against


@dataclass(frozen=True, order=True)
class Period:
    start: date
    end: date            # inclusive
    freq: str            # D | W | M | Q | Y (W is inferred from D labels)
    label: str = field(compare=False)


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)


_RE_YEAR = re.compile(r"^(1[89]\d\d|20\d\d)$")
_RE_MONTH = re.compile(r"^(1[89]\d\d|20\d\d)-(0[1-9]|1[0-2])$")
_RE_DATE = re.compile(r"^(1[89]\d\d|20\d\d)-(\d\d)-(\d\d)(?:[T ].*)?$")
_RE_DMY = re.compile(r"^(\d{1,2})[./](\d{1,2})[./](1[89]\d\d|20\d\d)$")
_RE_QUARTER = re.compile(r"^(?:(1[89]\d\d|20\d\d)[- ]?Q([1-4])|Q([1-4])[- ]?(1[89]\d\d|20\d\d))$", re.IGNORECASE)
_RE_HE_MONTH = re.compile(r"^(\S+)\s+(1[89]\d\d|20\d\d)$")


def parse_period(label) -> Period | None:
    """One x label → its calendar period, or None when it isn't one."""
    if not isinstance(label, str | int) or isinstance(label, bool):
        return None
    s = str(label).strip()
    if m := _RE_YEAR.match(s):
        y = int(m[1])
        return Period(date(y, 1, 1), date(y, 12, 31), "Y", s)
    if m := _RE_MONTH.match(s):
        y, mo = int(m[1]), int(m[2])
        return Period(date(y, mo, 1), _month_end(y, mo), "M", s)
    if m := _RE_QUARTER.match(s):
        y, q = (int(m[1]), int(m[2])) if m[1] else (int(m[4]), int(m[3]))
        return Period(date(y, 3 * q - 2, 1), _month_end(y, 3 * q), "Q", s)
    try:
        if m := _RE_DATE.match(s):
            d = date(int(m[1]), int(m[2]), int(m[3]))
            return Period(d, d, "D", s)
        if m := _RE_DMY.match(s):
            d = date(int(m[3]), int(m[2]), int(m[1]))
            return Period(d, d, "D", s)
    except ValueError:
        return None
    if (m := _RE_HE_MONTH.match(s)) and m[1] in _MONTH_IDX:
        y, mo = int(m[2]), _MONTH_IDX[m[1]]
        return Period(date(y, mo, 1), _month_end(y, mo), "M", s)
    return None


def _num(v) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        f = float(v)
    elif isinstance(v, str):
        try:
            f = float(v.replace(",", "").strip())
        except ValueError:
            return None
    else:
        return None
    return f if math.isfinite(f) else None


@dataclass
class Series:
    dataset_id: str
    path: str                        # e.g. "volume.sa", "rates.series[קבועה לא צמודה]"
    freq: str                        # D | W | M | Q | Y | E (irregular events)
    points: list[tuple[Period, float]]
    label: str = ""
    partial_last: bool = False       # the last point is a period still in progress

    @property
    def complete(self) -> list[tuple[Period, float]]:
        return self.points[:-1] if self.partial_last else self.points

    @property
    def cumulative(self) -> bool:
        """A running total (never falls): its every new point is a "record"."""
        vals = [v for _, v in self.points]
        if len(vals) < MIN_POINTS:
            return False
        diffs = [b - a for a, b in itertools.pairwise(vals)]
        return sum(d >= 0 for d in diffs) >= 0.97 * len(diffs) and vals[-1] > vals[0]


def _periods(xs: list) -> list[Period] | None:
    """The x axis as one consistent, strictly increasing calendar, or None."""
    if not isinstance(xs, list) or len(xs) < MIN_POINTS:
        return None
    ps = [parse_period(x) for x in xs]
    if any(p is None for p in ps):
        return None
    freqs = {p.freq for p in ps}
    if len(freqs) != 1:
        return None
    if any(b.start <= a.start for a, b in itertools.pairwise(ps)):
        return None
    if ps[0].freq == "D":  # daily labels: weekly or daily by spacing
        gaps = [(b.start - a.start).days for a, b in itertools.pairwise(ps)]
        g = statistics.median(gaps)
        freq = "W" if 6 <= g <= 8 else "M" if 27 <= g <= 32 else "D" if g <= 2 else None
        if freq is None:
            return None
        ps = [Period(p.start, p.end, freq, p.label) for p in ps]
    else:
        # Evenly stepped, one period at a time (a few missing periods are
        # fine): rules out decade labels ("1990","2000") and irregular event
        # starts ("מאי 1994", "ינואר 2001") posing as a calendar.
        steps = [_index(b) - _index(a) for a, b in itertools.pairwise(ps)]
        if sum(s == 1 for s in steps) < 0.8 * len(steps):
            return None
    return ps


def _index(p: Period) -> int:
    """A period's ordinal in its own frequency's units."""
    if p.freq == "Y":
        return p.start.year
    if p.freq == "Q":
        return p.start.year * 4 + (p.start.month - 1) // 3
    if p.freq == "M":
        return p.start.year * 12 + p.start.month - 1
    return p.start.toordinal()


def _is_partial(chart: dict, last: Period, as_of: date | None) -> bool:
    if chart.get("partial"):
        return True
    if as_of is None or last.freq in ("D", "W"):
        return False
    return last.end >= as_of  # the period hasn't ended yet


def _regular(dataset_id: str, name: str, chart: dict, as_of: date | None) -> list[Series]:
    xs = chart.get("x")
    ps = _periods(xs)
    if ps is None:
        return []
    if as_of is not None and ps[-1].start > as_of:
        return []  # future-dated axis: expiry years or projections, not history
    n = len(ps)
    partial = _is_partial(chart, ps[-1], as_of)
    found: list[tuple[str, str, list]] = []
    for key, vals in chart.items():
        if key in ("x", "partial"):
            continue
        if key == "series" and isinstance(vals, list):
            for s in vals:
                if isinstance(s, dict) and isinstance(s.get("data"), list):
                    nm = str(s.get("name") or "")
                    found.append((f"{name}.series[{nm}]", nm, s["data"]))
        elif isinstance(vals, list) and len(vals) == n:
            found.append((f"{name}.{key}", key, vals))
    out = []
    for path, label, vals in found:
        if len(vals) != n:
            continue
        nums = [_num(v) for v in vals]
        # A numeric series, not labels: most entries numbers, no stray strings.
        if sum(v is not None for v in nums) < MIN_POINTS:
            continue
        if any(isinstance(v, str) and _num(v) is None for v in vals):
            continue
        pts = [(p, v) for p, v in zip(ps, nums, strict=True) if v is not None]
        out.append(Series(dataset_id, path, ps[0].freq, pts, label,
                          partial_last=partial and pts[-1][0] == ps[-1]))
    return out


def _pairs(dataset_id: str, path: str, pairs, label: str) -> Series | None:
    if not isinstance(pairs, list) or len(pairs) < MIN_POINTS:
        return None
    pts = []
    for pr in pairs:
        if not (isinstance(pr, list | tuple) and len(pr) == 2):
            return None
        p, v = parse_period(pr[0]), _num(pr[1])
        if p is None:
            return None
        if v is not None:
            pts.append((p, v))
    if len(pts) < MIN_POINTS or any(b[0].start <= a[0].start for a, b in itertools.pairwise(pts)):
        return None
    return Series(dataset_id, path, "E", pts, label)


def extract_series(model: dict, dataset_id: str, as_of: date | None = None) -> list[Series]:
    """Every time series in a page model's charts.

    `as_of` is the date the DATA describes (the snapshot's
    `metadata_modified`, falling back to its render date): a period that
    hadn't ended by then is partial, however long ago it ended now."""
    out: list[Series] = []
    for name, chart in (model.get("charts") or {}).items():
        if isinstance(chart, list):
            if s := _pairs(dataset_id, name, chart, name):
                out.append(s)
        elif isinstance(chart, dict):
            if "x" in chart:
                out += _regular(dataset_id, name, chart, as_of)
            else:
                for key, v in chart.items():
                    if s := _pairs(dataset_id, f"{name}.{key}", v, key):
                        out.append(s)
    return out


def kpi_values(model: dict) -> dict[str, float]:
    """Raw numeric KPI values (`kpis.<k>.value`)."""
    out = {}
    for k, v in (model.get("kpis") or {}).items():
        if isinstance(v, dict) and (f := _num(v.get("value"))) is not None:
            out[k] = f
    return out
