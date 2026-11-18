"""News from datasets that are lists of entities, not time series — deterministic, no LLM.

A registry (licensed contractors, a vaccine catalog, industrial zones) has no
"newest period": its page shows the current state, and the news is how that
state moved. The page-model history (`models/<id>/<ts>.json.gz`, every render
kept, `tables` dropped) holds its KPIs and its rankings by city, maker, type…,
so two kinds of signal come from it (NEWS_REGISTRY_SIGNALS):

1. Snapshot diffs (`detect_registry`), the latest render against the one the
   last news run saw (`base`), so each change signals once:

       new_entrant     a named category appeared in a ranking (a new maker, city)
       exit            a named category left it
       leader_change   a ranking has a new top entry
       kpi_move        a headline KPI moved past a threshold against `ref`, the
                       newest render at least REF_DAYS older (fires on the run
                       that crosses it, not every run after)

   Weaker than any record or anomaly on purpose (the editor says no to niche
   registries, and the writer checks every claim with SQL).

2. KPI history (`kpi_history_series`): each KPI's value at the last render of
   every calendar month, as a monthly `Series` the ordinary detectors run on
   ("active licences at a record"). History began 2026-11-09, so this needs
   MIN_HISTORY months before it can say anything.

Pure functions, no I/O: run.py loads the snapshots.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from services.shared import model_history

from .series import (
    MONTHS_HE,
    Period,
    Series,
    _month_end,
    _num,
    kpi_values,
    parse_period,
)
from .signals import Signal

NEW_ENTRANT, EXIT, LEADER_CHANGE, KPI_MOVE = "new_entrant", "exit", "leader_change", "kpi_move"
REGISTRY_FLAGS = {NEW_ENTRANT, EXIT, LEADER_CHANGE, KPI_MOVE}
WEIGHTS = {NEW_ENTRANT: 1.2, EXIT: 1.0, LEADER_CHANGE: 1.5}
KPI_MAX_WEIGHT = 2.2

REF_DAYS = 28          # kpi_move compares with a render at least this much older…
REF_MIN_DAYS = 7       # …or, while history is young, the oldest one this old
KPI_MIN_PCT = 10.0     # a count must move ≥ this %…
KPI_MIN_ABS = 5        # …and by at least this many units
KPI_MIN_PP = 3.0       # a percentage must move ≥ this many points
MIN_CATEGORIES = 3
MAX_CHURN = 0.3        # more than this share of names changed: an unstable axis (bins, labels with counts)

# KPIs over a rolling window or measured from today move on their own; their
# move says nothing about the registry. Matched per word of the key (`last30`,
# `avg_age`, `d7`), never inside one: `wage`, `managers`, `vintage` are KPIs.
_ROLLING_WORD = re.compile(r"^(?:(?:ytd|last|change|chg|delta|diff|yoy|mom|age|lag|days?|trend|recent)"
                           r"\d*[a-z]?|d\d+|\d+d)$")
_OTHER = {"אחר", "אחרים", "שונות", "other", "others", "לא צוין", "לא ידוע", "ללא", "unknown"}
_WEEKDAYS = {"ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"}
_SEASONAL = set(MONTHS_HE) | {m[:3] + "׳" for m in MONTHS_HE} | {m[:3] + "'" for m in MONTHS_HE} | _WEEKDAYS
_NUMERIC = re.compile(r"^[\d\s.,:/%\-–+<>≥≤()]+$")
_COUNT_IN_LABEL = re.compile(r"\(\s*[\d,.]+")


def _rolling(key: str) -> bool:
    words = re.split(r"[^0-9a-z]+", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower())
    return any(_ROLLING_WORD.match(w) for w in words if w)


def _named(label: str) -> bool:
    """A category that is an entity (a maker, a city, a type), not a bin, a date or a count."""
    s = label.strip()
    return bool(s) and not _NUMERIC.match(s) and parse_period(s) is None \
        and not _COUNT_IN_LABEL.search(s) and s not in _SEASONAL


def categories(chart) -> tuple[dict[str, float | None], bool] | None:
    """A categorical chart → ({name: value}, capped), or None when it isn't one.
    Shapes: [{name, value}], {data: [{name, value}]}, {names|labels|x: [...]}
    with `values` or one numeric column, or a stacked `series: [{name, data}]`
    (summed). Several measures per name (area, count, …): the names alone,
    each value None (entrants and exits, no ranking). `capped`: a top-N list
    (it has an "other" bucket or says so), where a new name may only be a
    rank change."""
    capped = isinstance(chart, dict) and bool(chart.get("capped"))
    if isinstance(chart, dict) and isinstance(chart.get("data"), list):
        chart = chart["data"]
    pairs: list[tuple[str, float | None]] = []
    if isinstance(chart, list):
        for e in chart:
            if not (isinstance(e, dict) and "name" in e and (v := _num(e.get("value"))) is not None):
                return None
            pairs.append((str(e["name"]), v))
    elif isinstance(chart, dict):
        keys = ("names", "labels", "x")
        xs = next((chart[k] for k in keys if isinstance(chart.get(k), list)), None)
        if not xs:
            return None
        n = len(xs)

        def numeric(col):
            return isinstance(col, list) and len(col) == n and all(_num(a) is not None for a in col)

        cols = [v for k, v in chart.items() if k not in keys and numeric(v)]
        stack = chart.get("series")
        if numeric(chart.get("values")):
            col = chart["values"]
        elif len(cols) == 1:
            col = cols[0]
        elif (isinstance(stack, list) and stack
              and all(isinstance(e, dict) and numeric(e.get("data")) for e in stack)):
            col = [sum(_num(e["data"][i]) for e in stack) for i in range(n)]
        else:
            col = [None] * n
        vals = [_num(v) for v in col if v is not None]
        if vals and max(vals) - min(vals) <= 0.01 * max(abs(v) for v in vals):
            col = [None] * n   # every row the same size (a 100% stack): names only
        pairs = [(str(x), None if v is None else _num(v)) for x, v in zip(xs, col, strict=True)]
    else:
        return None
    if len(pairs) < MIN_CATEGORIES:
        return None
    names = [n for n, _ in pairs]
    if len(set(names)) != len(names):
        return None
    if sum(_named(n) for n in names) < 0.8 * len(names):
        return None  # mostly bins, dates, months or counts
    capped = capped or any(n.strip().lower() in _OTHER for n in names)
    return {n: v for n, v in pairs if n.strip().lower() not in _OTHER}, capped


def _seen(history: list[dict]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Per chart: every name and every leader in the earlier snapshots."""
    names: dict[str, set[str]] = {}
    leaders: dict[str, set[str]] = {}
    for model in history:
        for key, chart in (model.get("charts") or {}).items():
            if c := categories(chart):
                names.setdefault(key, set()).update(c[0])
                if c[0] and None not in c[0].values():
                    leaders.setdefault(key, set()).add(max(c[0], key=c[0].get))
    return names, leaders


def _label(model: dict, key: str, kind: str) -> str:
    labels = model.get("labels") or {}
    for k in ((f"{key}_kpi",) if kind == "kpi" else (f"{key}_caption", f"{key}_title", f"{key}_aria")):
        if isinstance(labels.get(k), str) and labels[k].strip():
            return labels[k].strip()[:120]
    return key


def _is_pct(model: dict, key: str) -> bool:
    disp = ((model.get("kpis") or {}).get(key) or {}).get("display")
    return isinstance(disp, str) and disp.strip().endswith("%")


def _pp(model: dict, key: str, v: float) -> float | None:
    """A percentage KPI's value in points: some recipes keep the fraction (0.07
    for "7.0%"). None when the value isn't the percentage shown (a count
    under a "53.2%" display): nothing safe to compare."""
    disp = ((model.get("kpis") or {}).get(key) or {}).get("display") or ""
    shown = _num(disp.strip().rstrip("%"))
    if shown is None:
        return None
    if abs(shown - v) <= 0.6:
        return v
    return round(v * 100, 9) if abs(v) <= 1 and abs(shown - v * 100) <= 0.6 else None


def ts_date(ts: str | None) -> date | None:
    """A snapshot stamp's (UTC) date, or None."""
    try:
        return datetime.strptime(ts or "", model_history.TS_FORMAT).date()
    except ValueError:
        return None


def _day(ts: str | None) -> str:
    d = ts_date(ts)
    return d.isoformat() if d else (ts or "")[:10]


def _crossed(model_a: dict, model_b: dict, key: str, a: float, b: float) -> tuple[bool, dict]:
    """Whether a KPI's move a → b passes the thresholds, and its facts."""
    if _is_pct(model_b, key):
        pa, pb = _pp(model_a, key, a), _pp(model_b, key, b)
        if pa is None or pb is None:
            return False, {}
        d = pb - pa
        return abs(d) >= KPI_MIN_PP, {"change_pp": round(d, 3), "unit": "pct_points"}
    if not a:
        return False, {}
    pct = (b - a) / abs(a) * 100
    return abs(pct) >= KPI_MIN_PCT and abs(b - a) >= KPI_MIN_ABS, {"change": b - a, "change_pct": pct}


def detect_registry(dataset_id: str, latest: dict, latest_ts: str | None, base: dict | None,
                    base_ts: str | None = None, ref: dict | None = None,
                    ref_ts: str | None = None, history: list[dict] = ()) -> list[Signal]:
    """Snapshot-diff signals for one dataset. `latest`/`base`/`ref` are page
    models (same recipe version); `base` is the newest render the last news
    run saw, `ref` the comparison point for KPI moves (`pick_ref`). `history`:
    earlier models still (month-ends, any order); a name or leader already
    seen there is a flap back, not news (a forecast level, a re-added row)."""
    if base is None:
        return []
    day = _day(latest_ts)
    out: list[Signal] = []

    def sig(path, label, value, flag, weight, facts, since=base_ts):
        # `compared_to`: the render this change is measured against (`ref` for a KPI move)
        out.append(Signal(dataset_id, path, label, "", day, day, float(value or 0), [flag], round(weight, 3),
                          facts | {"compared_to": _day(since)}, True))

    charts_b, charts_a = latest.get("charts") or {}, base.get("charts") or {}
    seen_names, seen_leaders = _seen(list(history) + ([ref] if ref is not None else []))
    told: dict[str, set[str]] = {NEW_ENTRANT: set(), EXIT: set()}   # one signal per name per dataset
    for key, chart in charts_b.items():
        now_c, then_c = categories(chart), categories(charts_a.get(key))
        if not now_c or not then_c:
            continue
        (cb, capped), (ca, capped_a) = now_c, then_c
        if not cb or not ca:
            continue  # nothing but "other" buckets
        capped = capped or capped_a or len(cb) == len(ca) and set(cb) != set(ca)
        new, gone = [n for n in cb if n not in ca], [n for n in ca if n not in cb]
        if (len(new) + len(gone)) > MAX_CHURN * max(len(cb), len(ca)):
            continue
        label = _label(latest, key, "chart")
        if "מצטבר" in label or "cumulative" in label.lower():
            continue  # a cumulative curve over its names, not a breakdown
        base_facts = {"chart": key, "n_categories": len(cb), "top_n_list": capped}
        ranked = None not in cb.values() and None not in ca.values()
        if ranked:
            lb, la = max(cb, key=cb.get), max(ca, key=ca.get)
            if (lb != la and la in cb and cb[lb] > cb[la]
                    and lb not in seen_leaders.get(key, set())):
                sig(f"chart:{key}", label, cb[lb], LEADER_CHANGE, WEIGHTS[LEADER_CHANGE], base_facts | {
                    "leader": {"name": lb, "value": cb[lb]},
                    "previous_leader": {"name": la, "value_now": cb[la], "value_then": ca[la]}})
        if capped:
            continue  # in a top-N list a new name may only have climbed in: not a new entity
        # A complete list: any named newcomer is a new entity, however small
        # (a new vaccine with one batch in a catalog of 1,400).
        earlier = seen_names.get(key, set())
        big = [n for n in new if _named(n) and (cb[n] is None or cb[n] > 0) and n not in earlier
               and n not in told[NEW_ENTRANT]]
        told[NEW_ENTRANT].update(big)
        if big:
            big.sort(key=lambda n: -(cb[n] or 0))
            total = sum(v for v in cb.values() if v and v > 0) if ranked else 0
            sig(f"chart:{key}:new", label, cb[big[0]], NEW_ENTRANT, WEIGHTS[NEW_ENTRANT], base_facts | {
                "entrants": [{"name": n, "value": cb[n]}
                             | ({"share_pct": round(cb[n] / total * 100, 2)} if total else {})
                             for n in big[:5]]})
        left = [n for n in gone if _named(n) and (ca[n] is None or ca[n] > 0) and n not in told[EXIT]]
        told[EXIT].update(left)
        if left:
            left.sort(key=lambda n: -(ca[n] or 0))
            sig(f"chart:{key}:exit", label, ca[left[0]], EXIT, WEIGHTS[EXIT], base_facts | {
                "exits": [{"name": n, "value_then": ca[n]} for n in left[:5]]})

    if ref is not None:
        kb, ka, kr = kpi_values(latest), kpi_values(base), kpi_values(ref)
        for key, v in kb.items():
            if _rolling(key) or key not in kr:
                continue
            hit, facts = _crossed(ref, latest, key, kr[key], v)
            if not hit or (key in ka and _crossed(ref, base, key, kr[key], ka[key])[0]):
                continue  # no move, or the last run already saw it past the line
            size = abs(facts.get("change_pct") or 0) / 25 or abs(facts.get("change_pp") or 0) / 5
            now_v, then_v = v, kr[key]
            if "change_pp" in facts:   # in points, as the page shows them
                now_v, then_v = _pp(latest, key, v), _pp(ref, key, kr[key])
            sig(f"kpi:{key}", _label(latest, key, "kpi"), now_v, KPI_MOVE, min(0.8 + size, KPI_MAX_WEIGHT),
                facts | {"kpi": key, "display": ((latest.get("kpis") or {}).get(key) or {}).get("display"),
                         "previous": {"period": _day(ref_ts), "value": then_v}}, since=ref_ts)
    return out


def pick_ref(names: list[tuple[str, str]], latest_ts: str) -> tuple[str, str] | None:
    """The (ts, ref) KPI moves compare against: the newest snapshot at least
    REF_DAYS before the latest, else (young history) the oldest one at least
    REF_MIN_DAYS before it. `names` newest first, as `store.names` gives them."""
    try:
        t0 = datetime.strptime(latest_ts, model_history.TS_FORMAT)
    except (TypeError, ValueError):
        return None
    aged = []
    for ts, ref in names:
        try:
            age = (t0 - datetime.strptime(ts, model_history.TS_FORMAT)).days
        except ValueError:
            continue
        if age >= REF_DAYS:
            return ts, ref
        if age >= REF_MIN_DAYS:
            aged.append((ts, ref))
    return aged[-1] if aged else None


def month_picks(names: list[tuple[str, str]], months: int = 25) -> list[tuple[str, str]]:
    """The last snapshot of each calendar month (UTC), newest month first, at most `months`."""
    seen, out = set(), []
    for ts, ref in names:   # newest first: the first one met in a month is its last render
        if len(ts) < 6 or ts[:6] in seen:
            continue
        seen.add(ts[:6])
        out.append((ts, ref))
        if len(out) >= months:
            break
    return out


def kpi_history_series(dataset_id: str, monthly: list[tuple[str, dict]], as_of: date) -> list[Series]:
    """Each KPI's month-end values as a monthly Series. `monthly`: (ts, model)
    for the last render of each month, any order, same recipe version. The
    month of `as_of` is still in progress (its last render isn't final)."""
    pts: dict[str, list[tuple[Period, float]]] = {}
    labels: dict[str, str] = {}
    for ts, model in sorted(monthly, key=lambda p: p[0]):
        y, m = int(ts[:4]), int(ts[4:6])
        p = Period(date(y, m, 1), _month_end(y, m), "M", f"{y}-{m:02d}")
        for key, v in kpi_values(model).items():
            if _rolling(key):
                continue
            val = _pp(model, key, v) if _is_pct(model, key) else v
            if val is not None:
                pts.setdefault(key, []).append((p, val))
            labels[key] = _label(model, key, "kpi")
    out = []
    for key, ps in pts.items():
        if len(ps) < 2:
            continue
        out.append(Series(dataset_id, f"kpi_history.{key}", "M", ps, labels[key],
                          partial_last=ps[-1][0].end >= as_of))
    return out
