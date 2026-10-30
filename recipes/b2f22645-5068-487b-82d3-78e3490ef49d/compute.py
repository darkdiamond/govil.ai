"""Fuel excise (בלו) rates on fuel products, Israel, 2015 onward.

One table: each row is the excise rate of one product in effect from a date
(`תאריך`), in shekels per unit (`יחידות`: kiloliter or metric ton). Dates are
mostly the 1st of each month, plus mid-month rows when a rate was changed by
order (e.g. a temporary gasoline cut); a mid-month row may carry only the
products that changed.

Every number and sentence on the page is computed here. Products are not
hardcoded: gasoline / diesel / LPG are found by name pattern, and every rule
that needs one of them returns None when it is missing.
"""
import math
import re

import pandas as pd

KILOLITER = "קילו ליטר"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]

STABLE_PCT = 0.5     # |change| below this % reads as "no change"
NOTABLE_GAP = 5.0    # % below the peak that counts as a real reduction
BREAK_UP = 3.0       # one update >= +200%: structural break
BREAK_DOWN = 1 / 3   # one update <= -67%: structural break
MAX_SERIES = 9       # series per chart before the rest are dropped (disclosed)


# ---------------------------------------------------------------- helpers

def _num(v, d=2):
    s = f"{abs(v):,.{d}f}"
    return ("−" + s) if v < 0 and round(abs(v), d) != 0 else s


def _pct(v, d=1, sign=True):
    s = f"{abs(v):.{d}f}%"
    if not sign or round(abs(v), d) == 0:
        return s
    return ("+" if v > 0 else "−") + s


def _dstr(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def _iso(ts):
    return f"{ts.year:04d}-{ts.month:02d}-{ts.day:02d}"


def _short(name):
    s = re.sub(r"\([^)]*\)", "", name)
    s = re.sub(r"^\s*בלו\s+", "", s)
    s = re.sub(r'\s+ק"ל\s*$', "", s.strip())
    s = re.sub(r"\s+", " ", s).strip()
    return s or name.strip()


# Spelling variants of the same product name, folded to one series
# (e.g. "דל גפרית" in 2015-2024 became "דל גופרית" from 2025).
_SPELLING = [("גפרית", "גופרית"), ("״", '"'), ("\u05f3", "'")]


def _canon(name):
    s = str(name)
    for a, b in _SPELLING:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _parse_dates(col):
    s = col.astype(str).str.strip()
    d = pd.to_datetime(s.str[:10], errors="coerce", format="%Y-%m-%d")
    alt = pd.to_datetime(s.str[:10], errors="coerce", format="%d/%m/%Y")
    return d.fillna(alt)


def _prepare(df):
    df = df.copy()
    df["date"] = _parse_dates(df["תאריך"])
    df["product"] = df["מוצר"].astype(str).map(_canon)
    df["unit"] = df["יחידות"].astype(str).str.strip()
    df["rate"] = pd.to_numeric(
        df["מחיר"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce")
    df = df.dropna(subset=["date", "rate"])
    df = df[(df["product"] != "") & (df["rate"] >= 0)]
    return df


def _scale(unit):
    """Per-kiloliter rates are shown per liter (÷1000); others as published."""
    return 1000.0 if unit == KILOLITER else 1.0


def _unit_label(unit):
    if unit == KILOLITER:
        return "₪ לליטר"
    if unit == "טון מטרי":
        return "₪ לטון"
    return f"₪ ל{unit}" if unit else "₪"


# ---------------------------------------------------------------- model

def _build(df):
    # One rate per (date, product): duplicates collapse to their mean.
    g = (df.groupby(["product", "date"])["rate"].mean().round(4)
         .reset_index().sort_values(["product", "date"], kind="stable"))
    units = {}
    for p, s in df.groupby("product")["unit"]:
        vc = s.value_counts()
        vc = vc[vc == vc.max()].sort_index()
        units[p] = vc.index[0]
    dates = sorted(g["date"].unique())
    latest = pd.Timestamp(dates[-1])
    per_date = g.groupby("date")["product"].nunique().sort_index()
    # Latest "full" snapshot: a date carrying at least half the usual products
    # (mid-month rows often list only the changed products).
    full = per_date[per_date >= max(1, per_date.max() / 2)]
    latest_full = pd.Timestamp(full.index.max())
    # A product counts as discontinued only once it is missing from the last
    # TWO full snapshots, so one short/partial snapshot never "drops" it.
    active_from = pd.Timestamp(full.index[-2]) if len(full) >= 2 else latest_full
    prods = {}
    for p, sub in g.groupby("product", sort=True):
        sub = sub.sort_values("date", kind="stable")
        sc = _scale(units[p])
        vals = [float(v) / sc for v in sub["rate"]]
        ds = [pd.Timestamp(d) for d in sub["date"]]
        changes = []  # (date, old, new)
        for i in range(1, len(vals)):
            if abs(vals[i] - vals[i - 1]) > 1e-9:
                changes.append((ds[i], vals[i - 1], vals[i]))
        prods[p] = {
            "name": p, "short": _short(p), "unit": units[p],
            "dates": ds, "vals": vals, "changes": changes,
            "first": ds[0], "last": ds[-1],
            "active": ds[-1] >= active_from,
            "current": vals[-1],
        }
    return prods, dates, latest, latest_full


def _find(prods, must, exclude=()):
    cands = [p for p in sorted(prods)
             if must in p and not any(x in p for x in exclude)]
    cands = [p for p in cands if prods[p]["active"]] or cands
    if not cands:
        return None
    # Most observations first, then name: the main product, not a niche twin.
    cands.sort(key=lambda p: (-len(prods[p]["dates"]), p))
    return cands[0]


def _value_at(pr, ts):
    """Rate in effect on ts (last observation on/before it), or None."""
    v = None
    for d, x in zip(pr["dates"], pr["vals"]):
        if d <= ts:
            v = x
        else:
            break
    return v


def _step_series(pr):
    pts = []
    prev = None
    for d, v in zip(pr["dates"], pr["vals"]):
        if prev is None or abs(v - prev) > 1e-9:
            pts.append([_iso(d), round(v, 4)])
        prev = v
    if pts and pts[-1][0] != _iso(pr["last"]):
        pts.append([_iso(pr["last"]), round(pr["vals"][-1], 4)])
    return pts


def _order(prods, keys):
    # Active first, then by current rate (desc), then name.
    return sorted(keys, key=lambda p: (not prods[p]["active"], -prods[p]["current"], p))


# ---------------------------------------------------------------- insights

def ins_latest_gas(pr):
    if pr is None or not pr["changes"]:
        return None
    d, old, new = pr["changes"][-1]
    ch = (new - old) / old * 100 if old else 0
    word = "הופחת" if new < old else "הועלה"
    return (f"בעדכון האחרון ({_dstr(d)}) {word} הבלו על {pr['short']} ל-{_num(new)} ₪ לליטר, "
            f"{'ירידה' if ch < 0 else 'עלייה'} של {_pct(ch, sign=False)} לעומת {_num(old)} ₪ לליטר.")


def ins_gas_peak(pr):
    if pr is None or len(pr["vals"]) < 2:
        return None
    peak = max(pr["vals"])
    i = pr["vals"].index(peak)
    pd_ = pr["dates"][i]
    cur = pr["current"]
    if cur >= peak - 1e-9:
        return (f"הבלו על {pr['short']} נמצא בשיא של כל התקופה: {_num(cur)} ₪ לליטר "
                f"(מאז {_dstr(pr['first'])}).")
    gap = (peak - cur) / peak * 100
    if gap < NOTABLE_GAP:
        return None
    return (f"הבלו הנוכחי על {pr['short']} ({_num(cur)} ₪ לליטר) נמוך ב-{gap:.1f}% "
            f"מהשיא של {_num(peak)} ₪ לליטר ({_dstr(pd_)}).")


def _gap_series(ga, di):
    """Gasoline minus diesel per liter on every date both are in effect."""
    ds = sorted(set(ga["dates"]) | set(di["dates"]))
    # Both still published: a rate stays in effect until the next row, so the
    # gap runs to the latest date of either; otherwise stop where one ends.
    end = (max(ga["last"], di["last"]) if ga["active"] and di["active"]
           else min(ga["last"], di["last"]))
    out = []
    for d in ds:
        if d < max(ga["first"], di["first"]) or d > end:
            continue
        a, b = _value_at(ga, d), _value_at(di, d)
        if a is None or b is None:
            continue
        out.append((d, a - b))
    return out


def ins_gap(ga, di, gap):
    if ga is None or di is None or len(gap) < 3:
        return None
    d_last, cur = gap[-1]
    n_above = sum(1 for _, v in gap if v > 1e-9)
    share = n_above / len(gap) * 100
    if abs(cur) < 0.005:
        state = f"הבלו על {ga['short']} ועל {di['short']} זהה כיום"
    elif cur > 0:
        state = f"הבלו על {ga['short']} גבוה כיום מהבלו על {di['short']} ב-{_num(cur)} ₪ לליטר"
    else:
        state = f"הבלו על {ga['short']} נמוך כיום מהבלו על {di['short']} ב-{_num(-cur)} ₪ לליטר"
    return (f"{state}. לאורך התקופה הבלו על {ga['short']} היה הגבוה מבין השניים "
            f"ב-{share:.0f}% מנקודות העדכון ({n_above:,} מתוך {len(gap):,}).")


def ins_diesel_year(pr):
    if pr is None:
        return None
    ref_d = pr["last"] - pd.Timedelta(days=365)
    if ref_d < pr["first"]:
        return None
    old = _value_at(pr, ref_d)
    if not old:
        return None
    ch = (pr["current"] - old) / old * 100
    if abs(ch) < STABLE_PCT:
        return (f"הבלו על {pr['short']} כמעט לא השתנה בשנה האחרונה: {_num(pr['current'])} ₪ לליטר "
                f"ב-{_dstr(pr['last'])} לעומת {_num(old)} ₪ לליטר שנה קודם לכן.")
    word = "עלה" if ch > 0 else "ירד"
    return (f"הבלו על {pr['short']} {word} ב-{_pct(ch, sign=False)} בשנה האחרונה: "
            f"מ-{_num(old)} ל-{_num(pr['current'])} ₪ לליטר (נכון ל-{_dstr(pr['last'])}).")


def ins_cumulative(cum):
    """Largest cumulative increase among active products with ≥3 years of data
    since their last structural break (see the cum block in compute)."""
    rows = [r for r in cum if r["years"] >= 3 and r["pct"] is not None]
    if len(rows) < 2:
        return None
    top = rows[0]
    low = rows[-1]
    if top["pct"] < 10:
        return None
    note = (f" (המוצר סווג מחדש ב-{top['break']}, והשינוי נמדד מאז)" if top["break"] else "")
    return (f"מבין המוצרים הפעילים, הבלו על {top['short']} עלה הכי הרבה: {_pct(top['pct'])} "
            f"מאז {top['since']} ({_num(top['from'])} עד {_num(top['to'])} {top['unit']}){note}, "
            f"לעומת {_pct(low['pct'])} ב{low['short']}.")


def ins_identical(prods, active):
    groups = {}
    for p in active:
        pr = prods[p]
        key = (pr["unit"], round(pr["current"], 4))
        groups.setdefault(key, []).append(pr["short"])
    multi = [(k, sorted(v)) for k, v in groups.items() if len(v) >= 3]
    if not multi:
        multi = [(k, sorted(v)) for k, v in groups.items() if len(v) >= 2]
    if not multi:
        return None
    multi.sort(key=lambda kv: (-len(kv[1]), kv[0][0], -kv[0][1]))
    (unit, val), names = multi[0]
    return (f"{len(names)} מוצרים חייבים כיום באותו שיעור בלו, {_num(val)} {_unit_label(unit)}: "
            f"{', '.join(names)}.")


def ins_turnover(prods, latest_full):
    gone = sorted(p for p in prods if not prods[p]["active"])
    if not gone:
        return None
    # Group discontinued items by their own last month.
    by_month = {}
    for p in gone:
        last = prods[p]["last"]
        by_month.setdefault((last.year, last.month), []).append(prods[p]["short"])
    parts = [f"{', '.join(sorted(names))} (לאחרונה ב{MONTHS_HE[m - 1]} {y})"
             for (y, m), names in sorted(by_month.items())]
    last_gone = max(prods[p]["last"] for p in gone)
    new = sorted(p for p in prods
                 if prods[p]["active"] and prods[p]["first"] > last_gone)
    head = "סעיף מוצר אחד אינו מופיע" if len(gone) == 1 else f"{len(gone)} סעיפי מוצר אינם מופיעים"
    msg = (f"{head} בעדכונים המלאים האחרונים "
           f"(עד {_dstr(latest_full)}): {'; '.join(parts)}")
    if new:
        n_names = ", ".join(f"{prods[p]['short']} ({_num(prods[p]['current'])} {_unit_label(prods[p]['unit'])} כיום)"
                            for p in new)
        first_new = min(prods[p]["first"] for p in new)
        added = "נוסף סעיף חדש" if len(new) == 1 else f"נוספו {len(new)} סעיפים חדשים"
        msg += f". מאז {_dstr(first_new)} {added}: {n_names}"
    return msg + "."


def ins_volatility(per_year, pr):
    if pr is None or len(per_year) < 3:
        return None
    full = per_year[:-1]  # the latest year may be partial
    if len(full) < 2:
        return None
    top = sorted(full, key=lambda r: (-r["gas"], r["year"]))[0]
    med = sorted(r["gas"] for r in full)[len(full) // 2]
    if top["gas"] < max(4, med * 2):
        return None
    return (f"שנת {top['year']} הייתה התנודתית ביותר בבלו על {pr['short']}: "
            f"{top['gas']} שינויי שיעור, לעומת חציון של {med} שינויים בשנה "
            f"בשנים {full[0]['year']}-{full[-1]['year']}.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = _prepare(frames["main"])
    prods, dates, latest, latest_full = _build(df)
    active = [p for p in prods if prods[p]["active"]]

    gas_k = _find(prods, "בנזין", exclude=("טיס",))
    die_k = _find(prods, "סולר")
    lpg_k = _find(prods, 'גפ"מ')
    ga = prods.get(gas_k) if gas_k else None
    di = prods.get(die_k) if die_k else None
    lpg = prods.get(lpg_k) if lpg_k else None
    if ga is not None and ga["unit"] != KILOLITER:
        ga = None
    if di is not None and di["unit"] != KILOLITER:
        di = None

    first_d = pd.Timestamp(dates[0])
    y0, y1 = first_d.year, latest.year

    # -- chart: per-liter products over time (step lines)
    liter_keys = _order(prods, [p for p in prods if prods[p]["unit"] == KILOLITER])
    other_keys = _order(prods, [p for p in prods if prods[p]["unit"] != KILOLITER])
    liter_dropped = max(0, len(liter_keys) - MAX_SERIES)
    other_dropped = max(0, len(other_keys) - MAX_SERIES)
    liter_keys = liter_keys[:MAX_SERIES]
    other_keys = other_keys[:MAX_SERIES]
    ch_liter = {"series": [{"name": prods[p]["short"], "data": _step_series(prods[p])}
                           for p in liter_keys]}
    ch_ton = {"series": [{"name": prods[p]["short"] + ("" if prods[p]["active"] else " (הופסק)"),
                          "data": _step_series(prods[p])} for p in other_keys],
              "unit": _unit_label(prods[other_keys[0]]["unit"]) if other_keys else "",
              "log": bool(other_keys) and (
                  max(prods[p]["current"] for p in other_keys) /
                  max(min(min(prods[p]["vals"]) for p in other_keys), 1e-9) > 20)}

    # -- current rates (active products)
    cur_rows = []
    for p in _order(prods, active):
        pr = prods[p]
        cur_rows.append({"name": pr["short"], "value": round(pr["current"], 4),
                         "display": _num(pr["current"]), "unit": _unit_label(pr["unit"]),
                         "date": _dstr(pr["last"]), "liter": pr["unit"] == KILOLITER})
    cur_liter = [r for r in cur_rows if r["liter"]]
    cur_other = [r for r in cur_rows if not r["liter"]]

    # -- gasoline minus diesel gap
    gap = _gap_series(ga, di) if (ga and di) else []
    gap_pts = []
    prev = None
    for d, v in gap:
        if prev is None or abs(v - prev) > 1e-9:
            gap_pts.append([_iso(d), round(v, 4)])
        prev = v
    if gap and gap_pts[-1][0] != _iso(gap[-1][0]):
        gap_pts.append([_iso(gap[-1][0]), round(gap[-1][1], 4)])

    # -- gasoline change events
    gas_events = []
    if ga:
        for d, old, new in ga["changes"]:
            gas_events.append({"date": _iso(d), "label": _dstr(d), "old": round(old, 4),
                               "new": round(new, 4), "pct": round((new - old) / old * 100, 2) if old else 0.0})
    biggest = sorted(gas_events, key=lambda e: (-abs(e["pct"]), e["date"]))[:10]
    biggest = sorted(biggest, key=lambda e: e["date"], reverse=True)
    biggest_rows = [{"date": e["label"], "old": _num(e["old"]), "new": _num(e["new"]),
                     "pct": _pct(e["pct"]), "down": e["pct"] < 0} for e in biggest]

    # -- changes per year (gasoline vs diesel)
    years = list(range(y0, y1 + 1))
    per_year = []
    for y in years:
        gc = sum(1 for d, _, _ in (ga["changes"] if ga else []) if d.year == y)
        dc = sum(1 for d, _, _ in (di["changes"] if di else []) if d.year == y)
        per_year.append({"year": y, "gas": gc, "die": dc})
    last_year_partial = latest_full.month < 12

    # -- annual % change heatmap (year-end rate vs previous year-end)
    heat_prods = _order(prods, list(prods))[:12]
    heat_cells = []
    raw_abs = []
    for yi, y in enumerate(years[1:]):
        for pi, p in enumerate(heat_prods):
            pr = prods[p]
            a = _value_at(pr, pd.Timestamp(year=y - 1, month=12, day=31))
            b_in_year = [v for d, v in zip(pr["dates"], pr["vals"]) if d.year == y]
            if a is None or not b_in_year or a == 0:
                continue
            if pr["first"].year > y - 1:
                continue
            ch = (b_in_year[-1] - a) / a * 100
            raw_abs.append(abs(ch))
            heat_cells.append([yi, pi, round(ch, 2)])
    cap = 30.0
    if raw_abs:
        s = sorted(raw_abs)
        cap = max(5.0, min(60.0, s[int(len(s) * 0.9)]))
    heat = {"years": [str(y) + (" (חלקית)" if (y == y1 and last_year_partial) else "") for y in years[1:]],
            "products": [prods[p]["short"] + ("" if prods[p]["active"] else " (הופסק)") for p in heat_prods],
            "cells": [[c[0], c[1], max(-cap, min(cap, c[2])), c[2]] for c in heat_cells],
            "cap": round(cap, 1)}

    # -- cumulative change since first rate (active products). A single
    # update of >= +200% or <= -67% is a structural break (reclassification,
    # a new tax base), not an ordinary rate change: measure from after the
    # LAST such break, and say so.
    cum = []
    for p in active:
        pr = prods[p]
        start = 0
        brk = None
        for i in range(1, len(pr["vals"])):
            a, b = pr["vals"][i - 1], pr["vals"][i]
            if a > 0 and (b / a >= BREAK_UP or b / a <= BREAK_DOWN):
                start, brk = i, pr["dates"][i]
        f, t = pr["vals"][start], pr["current"]
        since_d = pr["dates"][start]
        pct = (t - f) / f * 100 if f else None
        yrs = (pr["last"] - since_d).days / 365.25
        cum.append({"short": pr["short"], "pct": None if pct is None else round(pct, 2),
                    "from": f, "to": t, "since": _dstr(since_d), "years": yrs,
                    "unit": _unit_label(pr["unit"]),
                    "break": _dstr(brk) if brk is not None else None})
    cum.sort(key=lambda r: (-(r["pct"] if r["pct"] is not None else -1e9), r["short"]))
    cum_chart = {"names": [r["short"] for r in cum if r["pct"] is not None],
                 "values": [r["pct"] for r in cum if r["pct"] is not None],
                 "since": [r["since"] for r in cum if r["pct"] is not None]}
    cum_rows = [{"name": r["short"] + (" (סווג מחדש)" if r["break"] else ""),
                 "since": r["since"], "from": _num(r["from"]),
                 "to": _num(r["to"]), "unit": r["unit"], "pct": _pct(r["pct"])}
                for r in cum if r["pct"] is not None]

    # -- insights
    rules = [
        ("latest_gas", ins_latest_gas(ga)),
        ("gas_peak", ins_gas_peak(ga)),
        ("gap", ins_gap(ga, di, gap)),
        ("diesel_year", ins_diesel_year(di)),
        ("cumulative", ins_cumulative(cum)),
        ("identical", ins_identical(prods, active)),
        ("turnover", ins_turnover(prods, latest_full)),
        ("volatility", ins_volatility(per_year, ga)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # -- KPIs
    kpis = {}
    labels = {}
    if ga:
        kpis["gas"] = {"value": round(ga["current"], 4), "display": _num(ga["current"]), "tone": "brand"}
        labels["gas_kpi"] = f"בלו על ליטר {ga['short']} (₪, בתוקף מ-{_dstr(ga['changes'][-1][0] if ga['changes'] else ga['first'])})"
        if ga["changes"]:
            d, old, new = ga["changes"][-1]
            ch = (new - old) / old * 100 if old else 0
            tone = "ok" if ch < -STABLE_PCT else ("warn" if ch > STABLE_PCT else "brand")
            kpis["gas_last"] = {"value": round(ch, 2), "display": _pct(ch), "tone": tone}
            labels["gas_last_kpi"] = f"השינוי האחרון בבלו על {ga['short']} ({_dstr(d)})"
    if di:
        kpis["die"] = {"value": round(di["current"], 4), "display": _num(di["current"]), "tone": "brand"}
        labels["die_kpi"] = f"בלו על ליטר {di['short']} (₪, נכון ל-{_dstr(di['last'])})"
        ref = _value_at(di, di["last"] - pd.Timedelta(days=365))
        if ref and di["first"] <= di["last"] - pd.Timedelta(days=365):
            ch = (di["current"] - ref) / ref * 100
            tone = "warn" if ch > STABLE_PCT else ("ok" if ch < -STABLE_PCT else "brand")
            kpis["die_year"] = {"value": round(ch, 2), "display": _pct(ch), "tone": tone}
            labels["die_year_kpi"] = f"שינוי בבלו על {di['short']} בשנה האחרונה"
    if lpg and lpg["active"]:
        kpis["lpg"] = {"value": round(lpg["current"], 4), "display": _num(lpg["current"]), "tone": "brand"}
        labels["lpg_kpi"] = f"בלו על {lpg['short']} ({_unit_label(lpg['unit'])}, נכון ל-{_dstr(lpg['last'])})"
    kpis["span"] = {"value": [y0, y1], "display": f"{y0}–{y1}", "tone": "brand"}
    labels["span_kpi"] = f"שנות נתונים ({len(dates):,} מועדי עדכון)"

    # -- labels / ledes
    n_act = len(active)
    lede_bits = [f"שיעורי מס הבלו על {n_act} מוצרי דלק כפי שנקבעו בצו, מ-{_dstr(first_d)} ועד {_dstr(latest)}."]
    if ga and di:
        lede_bits.append(f"כיום הבלו על ליטר {ga['short']} עומד על {_num(ga['current'])} ₪, "
                         f"ועל ליטר {di['short']} על {_num(di['current'])} ₪.")
    labels["lede"] = " ".join(lede_bits)
    labels["liter_aria"] = (f"גרף מדרגות: הבלו בשקלים לליטר על {len(liter_keys)} מוצרי דלק נוזליים, "
                            f"{y0} עד {y1}" + (f". {ga['short']} כיום {_num(ga['current'])} ₪ לליטר." if ga else "."))
    labels["liter_note"] = (f"השיעור בשקלים לליטר (השיעור בצו הוא לקילו ליטר, חלקי 1,000). "
                            f"כל מדרגה היא שינוי בצו; גררו את הסרגל התחתון כדי להתמקד בתקופה."
                            + (f" מוצגים {MAX_SERIES} המוצרים העיקריים." if liter_dropped else ""))
    labels["ton_aria"] = (f"גרף מדרגות: הבלו על מוצרים הנמדדים בטון ({len(other_keys)} סעיפים), {y0} עד {y1}.")
    labels["ton_note"] = ("שיעורים לטון מטרי." + (" ציר לוגריתמי: השיעורים נבדלים זה מזה בסדרי גודל." if ch_ton["log"] else "")
                          + (f" מוצגים {MAX_SERIES} הסעיפים העיקריים." if other_dropped else ""))
    labels["current_aria"] = (f"תרשים עמודות: שיעור הבלו הנוכחי על {len(cur_liter)} מוצרים בשקלים לליטר"
                              + (f", הגבוה ביותר {cur_liter[0]['name']} עם {cur_liter[0]['display']} ₪." if cur_liter else "."))
    labels["current_other_aria"] = (f"תרשים עמודות: שיעור הבלו הנוכחי על {len(cur_other)} מוצרים בשקלים לטון"
                                    + (f", הגבוה ביותר {cur_other[0]['name']} עם {cur_other[0]['display']} ₪." if cur_other else "."))
    if gap:
        mn = min(gap, key=lambda t: (t[1], t[0]))
        mx = max(gap, key=lambda t: (t[1], -t[0].value))
        labels["gap_aria"] = (f"גרף מדרגות: הפער בין הבלו על {ga['short']} לבלו על {di['short']} בשקלים לליטר. "
                              f"הפער הנמוך ביותר {_num(mn[1])} ₪ ב-{_dstr(mn[0])}, הגבוה ביותר {_num(mx[1])} ₪ ב-{_dstr(mx[0])}.")
        labels["gap_note"] = (f"מעל האפס: הבלו על {ga['short']} גבוה מהבלו על {di['short']}. מתחת לאפס: נמוך ממנו. "
                              f"השפל: {_num(mn[1])} ₪ לליטר ב-{_dstr(mn[0])}.")
        labels["gap_title"] = f"{ga['short']} מול {di['short']}: הפער בבלו"
    if gas_events:
        n_down = sum(1 for e in gas_events if e["pct"] < 0)
        labels["events_aria"] = (f"תרשים עמודות: {len(gas_events)} שינויים בשיעור הבלו על {ga['short']} מאז {_dstr(ga['first'])}, "
                                 f"מהם {n_down} הפחתות.")
        labels["events_note"] = (f"כל עמודה היא שינוי בצו, באחוזים לעומת השיעור הקודם. "
                                 f"{len(gas_events)} שינויים, מהם {n_down} הפחתות (מסומנות בירוק). "
                                 f"הטבלה מציגה את {len(biggest_rows)} השינויים הגדולים ביותר.")
        labels["events_title"] = f"כל שינויי הבלו על {ga['short']}"
        labels["events_caption"] = f"{len(biggest_rows)} השינויים הגדולים ביותר בבלו על {ga['short']}, בשקלים לליטר"
    if ga or di:
        tot_g = sum(r["gas"] for r in per_year)
        tot_d = sum(r["die"] for r in per_year)
        labels["per_year_aria"] = (f"תרשים עמודות: מספר שינויי הבלו בכל שנה, {y0} עד {y1}"
                                   + (f". {ga['short']}: {tot_g} שינויים" if ga else "")
                                   + (f", {di['short']}: {tot_d} שינויים." if di else "."))
        labels["per_year_note"] = ("כמה פעמים השתנה השיעור בכל שנה (כל עדכון בצו נספר פעם אחת)."
                                   + (f" שנת {y1} חלקית, עד {_dstr(latest)}." if last_year_partial else ""))
    labels["heat_aria"] = (f"מפת חום: השינוי השנתי באחוזים בשיעור הבלו על {len(heat_prods)} מוצרים, "
                           f"{years[1] if len(years) > 1 else y0} עד {y1}.")
    labels["heat_note"] = (f"השיעור בסוף כל שנה לעומת סוף השנה הקודמת. כחול: ירידה, אדום: עלייה. "
                           f"הצבע רווי מעבר ל-{cap:.0f}% והערך המדויק מופיע בתא.")
    if cum_chart["names"]:
        labels["cum_aria"] = (f"תרשים עמודות: השינוי המצטבר בשיעור הבלו מאז תחילת הנתונים, {len(cum_chart['names'])} מוצרים פעילים. "
                              f"הגבוה ביותר {cum_chart['names'][0]} ({_pct(cum_chart['values'][0])}).")
        labels["cum_note"] = ("השיעור הנוכחי לעומת השיעור הראשון של כל מוצר במאגר. "
                              "מוצר שנוסף מאוחר יותר נמדד ממועד הופעתו הראשון.")
        breaks = [r for r in cum if r["break"] and r["pct"] is not None]
        if breaks:
            bits = ", ".join(f"{r['short']} ({r['break']})" for r in breaks)
            labels["cum_note"] += (f" מוצר שהשיעור שלו קפץ בעדכון יחיד פי {BREAK_UP:.0f} לפחות "
                                   f"(או ירד לשליש או פחות) סווג מחדש, ונמדד רק מאותו עדכון: {bits}.")

    flags = {
        "gas": ga is not None, "die": di is not None,
        "gap": len(gap_pts) >= 2, "events": len(gas_events) >= 2,
        "per_year": bool(ga or di), "ton": bool(other_keys),
        "heat": len(heat_cells) >= 4, "cum": len(cum_chart["names"]) >= 2,
        "cur_liter": bool(cur_liter), "cur_other": bool(cur_other),
    }

    summary = (f"כמה בלו משלמים על ליטר דלק? שיעורי מס הבלו על בנזין, סולר, גפ\"מ ומזוט "
               f"מ-{y0} עד {y1}")
    if ga:
        summary += f". בנזין כיום: {_num(ga['current'])} ₪ לליטר"
    if di:
        summary += f", סולר: {_num(di['current'])} ₪"
    summary += "."
    if len(summary) > 155:
        summary = f"שיעורי מס הבלו על מוצרי דלק בישראל, {y0} עד {y1}."

    tags = ["דלק", "בלו", "מסים", "מחירי דלק", "אנרגיה"]

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": tags,
            "related_ids": ["4dd3bb28-a4ef-4ab5-bb57-fd0bd0b79f8f",
                            "61dc38b6-803e-476e-a1ac-0679c354b2ef",
                            "09f0e9ee-5cef-48f7-84f6-10235e6dd9ed"],
            "temporal_coverage": f"{y0}/{y1}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "liter": ch_liter,
            "ton": ch_ton,
            "current_liter": {"names": [r["name"] for r in cur_liter],
                              "values": [r["value"] for r in cur_liter]},
            "current_other": {"names": [r["name"] for r in cur_other],
                              "values": [r["value"] for r in cur_other]},
            "gap": {"data": gap_pts},
            "events": {"data": [[e["date"], e["pct"], e["label"], e["old"], e["new"]] for e in gas_events]},
            "per_year": {"years": [str(r["year"]) for r in per_year],
                         "gas": [r["gas"] for r in per_year], "die": [r["die"] for r in per_year],
                         "gas_name": ga["short"] if ga else "", "die_name": di["short"] if di else ""},
            "heat": heat,
            "cum": cum_chart,
        },
        "tables": {
            "current": cur_rows,
            "biggest": biggest_rows,
            "per_year": [{"year": r["year"], "gas": r["gas"], "die": r["die"]} for r in reversed(per_year)],
            "cum": cum_rows,
        },
        "insights": insights,
        "labels": labels,
        "flags": flags,
        "names": {"gas": ga["short"] if ga else "", "die": di["short"] if di else ""},
    }
