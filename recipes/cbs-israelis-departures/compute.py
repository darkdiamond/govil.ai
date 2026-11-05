"""יציאות ישראלים לחו"ל: CBS's monthly release on Israelis' departures abroad.

Inputs are CBS grid tables (one row per sheet row, cells C01..Cnn) from the
newest edition of the release:
  t1  departures (total and by air): yearly since 2015, year to date, and
      monthly since two years back with seasonally adjusted and trend data
  t2  departures by age group, with the share of men: yearly and monthly
  t3  departures, and those of Israelis living abroad ("homeland visits"):
      yearly since 2019 and monthly
  t4  departures by route and border crossing, year to date, three years
  t5  departures by air, monthly since 2018 (chart data)
  releases  the edition list (number, date, headline, link)

Header rows are found by their labels and raise when missing, so a
redesigned table fails the refresh as recipe_failed and keeps the last
page. Data rows (years, months, age groups, crossings) are found by
pattern: a missing one only shortens a series. Values are thousands.
"""
import re

import pandas as pd
from govlib import cbs, fmt

MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
_EN_RANGE = re.compile(rf"^({'|'.join(MONTHS_EN)})-({'|'.join(MONTHS_EN)})$")
_AGE = re.compile(r"^(\d+)(\+|-\d+)$")
MODES = ("דרך האוויר", "דרך היבשה", "דרך הים")
SHOCK_DROP = 0.3          # a month this far below the same month a year earlier
AGE_MOVE = 0.05           # an age group's year-to-date change worth a sentence


def _stop(rows, start, text):
    return next((i for i in range(start, len(rows)) if any(text in c for c in rows[i])),
                len(rows))


# ── tables ───────────────────────────────────────────────────────────────


def _t1(rows):
    """Yearly totals, year-to-date pairs and the monthly series."""
    e = cbs.row_with(rows, "change in trend", name="t1")
    head = cbs.row_with(rows, "Total", name="t1")
    sub = rows[e]

    def block(start):
        pct = cbs.col_after(sub, "change in trend", start)
        return {"pct": pct, "trend": cbs.col_after(sub, "Trend", pct),
                "sa": cbs.col_after(sub, "adjusted", pct), "orig": cbs.col_after(sub, "data", pct)}

    tot = block(cbs.col_after(rows[head], "Total", 0))
    air = block(cbs.col_after(rows[head], "Thereof: By air", 0))
    stop = _stop(rows, e, "% change on the same period")
    years, ytd, monthly = [], [], []
    for i, y, m, end in cbs.periods(rows, e + 1, stop):
        r = rows[i]
        v = cbs.val(r, tot["orig"])
        if v is None:
            continue
        rec = {"year": y, "total": v, "air": cbs.val(r, air["orig"])}
        if m is None:
            years.append(rec)
        elif m == 1 and end:
            ytd.append({**rec, "end": end})
        elif not end:
            monthly.append({"t": (y, m), "orig": v, "sa": cbs.val(r, tot["sa"]),
                            "trend": cbs.val(r, tot["trend"]), "pct": cbs.val(r, tot["pct"]),
                            "air": cbs.val(r, air["orig"])})
    for lst, key in ((years, "year"), (ytd, "year"), (monthly, "t")):
        lst.sort(key=lambda r, k=key: r[k])
    return years, ytd, monthly


def _age_key(label):
    return int(_AGE.match(label).group(1))


def _age_he(label):
    m = _AGE.match(label)
    return f"{m.group(1)} ומעלה" if m.group(2) == "+" else label


def _t2(rows):
    """Departures and % men by age group: (ages, yearly, monthly)."""
    a = next((i for i, r in enumerate(rows) if sum(bool(_AGE.match(c)) for c in r) >= 2), None)
    if a is None:
        raise ValueError("t2: age-group header row not found")
    lab = cbs.row_with(rows, "Total Departures", a, name="t2", contains=True)
    ages = []
    for j, c in enumerate(rows[a]):
        if _AGE.match(c):
            ages.append({"label": c,
                         "male": cbs.col_after(rows[lab], "מזה: % הזכרים", j),
                         "total": cbs.col_after(rows[lab], "Total Departures", j, contains=True)})
    ages.sort(key=lambda g: _age_key(g["label"]))
    stop = _stop(rows, lab, "% change on the same period")
    yearly, monthly = [], []
    for i, y, m, end in cbs.periods(rows, lab + 1, stop):
        r = rows[i]
        vals = {g["label"]: (cbs.val(r, g["total"]), cbs.val(r, g["male"])) for g in ages}
        if all(v[0] is None for v in vals.values()):
            continue
        if m is None:
            yearly.append({"year": y, "ages": vals})
        elif not end:
            monthly.append({"t": (y, m), "ages": vals})
    yearly.sort(key=lambda r: r["year"])
    monthly.sort(key=lambda r: r["t"])
    return [g["label"] for g in ages], yearly, monthly


def _t3(rows):
    """Departures and those of Israelis living abroad: (yearly, monthly)."""
    h = cbs.row_with(rows, 'סה"כ', name="t3")
    tot = cbs.col_after(rows[h], 'סה"כ', 0)
    abroad = cbs.col_after(rows[h], "מזה: של", 0)
    unit = cbs.row_with(rows, "אלפים", h, name="t3")
    yearly, monthly = [], []
    for i, y, m, end in cbs.periods(rows, unit + 1, len(rows)):
        r = rows[i]
        t, ab = cbs.val(r, tot), cbs.val(r, abroad)
        if t is None or ab is None or not t:
            continue
        rec = {"total": t, "abroad": ab, "share": ab / t}
        if m is None:
            yearly.append({**rec, "year": y})
        elif not end:
            monthly.append({**rec, "t": (y, m)})
    yearly.sort(key=lambda r: r["year"])
    monthly.sort(key=lambda r: r["t"])
    return yearly, monthly


def _t4(rows):
    """Departures by route and crossing, year to date, for three years:
    (years, end month of the period, rows)."""
    yrow = next((i for i, r in enumerate(rows) if sum(bool(cbs.YEAR.match(c)) for c in r) >= 4),
                None)
    if yrow is None:
        raise ValueError("t4: year header row not found")
    # Runs of ascending years in adjacent columns: the year-to-date block,
    # then the month block (a stray year cell elsewhere starts its own run).
    runs, cur = [], []
    for j, c in enumerate(rows[yrow]):
        if cbs.YEAR.match(c):
            if cur and j == cur[-1] + 1 and int(c) > int(rows[yrow][cur[-1]]):
                cur.append(j)
            else:
                if cur:
                    runs.append(cur)
                cur = [j]
    if cur:
        runs.append(cur)
    runs = [r for r in runs if len(r) >= 2]
    if not runs:
        raise ValueError("t4: no block of years found")
    ycols = runs[0]
    years = [int(rows[yrow][j]) for j in ycols]
    # The English block labels ("January-October", "October") say which
    # block is which; the range must be the left one. In January both read
    # "January" (year to date = the month).
    lrow = next((rows[i] for i in range(yrow - 1, -1, -1)
                 if any(c in MONTHS_EN or _EN_RANGE.match(c) for c in rows[i])), None)
    if lrow is None:
        raise ValueError("t4: block label row (January-…) not found")
    ranges = [(j, c) for j, c in enumerate(lrow) if _EN_RANGE.match(c)]
    singles = [(j, c) for j, c in enumerate(lrow) if c in MONTHS_EN]
    if ranges and singles and ranges[0][0] > singles[0][0]:
        raise ValueError("t4: the year-to-date block (January-…) must come first")
    if ranges:
        end = MONTHS_EN.index(_EN_RANGE.match(ranges[0][1]).group(2)) + 1
    elif singles:
        end = MONTHS_EN.index(singles[0][1]) + 1
    else:
        raise ValueError("t4: no month label in the block label row")
    name_col = cbs.col_after(rows[cbs.row_with(rows, "דרך מעבר", name="t4")], "דרך מעבר", 0)
    mode, out = None, []
    for r in rows[yrow + 1:]:
        name = cbs.cell(r, name_col)
        vals = [cbs.val(r, j) for j in ycols]
        if not name or all(v is None for v in vals):
            continue
        if name == "סך הכל":
            kind = "grand"
        elif name in MODES:
            kind, mode = "mode", name
        elif name.startswith("סך הכל"):
            kind = "subtotal"
        else:
            kind = "leaf"
        out.append({"name": name, "kind": kind, "mode": mode if kind != "grand" else None,
                    "ytd": vals})
    return years, end, out


def _t5(rows):
    """Departures by air, monthly: [{t: (year, month), orig, trend}]."""
    h = cbs.row_with(rows, "Original data", name="t5")
    orig = cbs.col_after(rows[h], "Original data", 0)
    trend = cbs.col_after(rows[h], "Trend", orig)
    return [{"t": (y, m), "orig": cbs.val(rows[i], orig), "trend": cbs.val(rows[i], trend)}
            for i, y, m in cbs.monthly_runs(rows, h + 1, len(rows), orig)]


# ── formatting ───────────────────────────────────────────────────────────


def _k(v):
    """Thousands, one decimal: 152.4; empty for a missing value."""
    return "" if v is None else fmt.num_he(v, 1)


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _range(end, year):
    if end == 1:
        return f"ינואר {year}"
    return f"ינואר עד {fmt.MONTHS_HE[end - 1]} {year}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _word(c, up="עלייה", down="ירידה"):
    return up if c > 0 else down


def _tone(c, band=0.02):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


def _spct(c):
    return "" if c is None else fmt.signed_pct(c)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"].copy()
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    years, ytd, monthly = _t1(cbs.grid(frames["t1"], "t1"))
    ages, age_years, age_months = _t2(cbs.grid(frames["t2"], "t2"))
    ab_years, ab_months = _t3(cbs.grid(frames["t3"], "t3"))
    t4_years, t4_end, routes = _t4(cbs.grid(frames["t4"], "t4"))
    air = _t5(cbs.grid(frames["t5"], "t5"))
    if not monthly:
        raise ValueError("t1: no monthly rows")
    if not years:
        raise ValueError("t1: no yearly rows")

    by_t = {m["t"]: m for m in monthly}
    last = monthly[-1]
    lt = last["t"]
    prev = by_t.get((lt[0] - 1, lt[1]))
    month_chg = _chg(last["orig"], prev["orig"]) if prev else None

    ytd_now = ytd[-1] if ytd else None
    ytd_prev = next((y for y in reversed(ytd[:-1]) if ytd_now and y["end"] == ytd_now["end"]
                     and y["year"] == ytd_now["year"] - 1), None)
    ytd_chg = _chg(ytd_now["total"], ytd_prev["total"]) if ytd_prev else None

    peak = max(years, key=lambda y: (y["total"], y["year"]))
    last_year = years[-1]

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    kpis["month"] = {"value": last["orig"], "display": _k(last["orig"]),
                     "tone": _tone(month_chg)}
    labels["month_kpi"] = f"יציאות לחו\"ל ב{_mname(lt)} (אלפים)"
    if month_chg is not None:
        kpis["month_chg"] = {"value": round(month_chg, 4), "display": fmt.signed_pct(month_chg),
                             "tone": _tone(month_chg)}
        labels["month_chg_kpi"] = f"שינוי לעומת {_mname((lt[0] - 1, lt[1]))}"
    if ytd_now:
        kpis["ytd"] = {"value": ytd_now["total"], "display": _k(ytd_now["total"]),
                       "tone": _tone(ytd_chg)}
        labels["ytd_kpi"] = (f"יציאות מתחילת השנה, {_range(ytd_now['end'], ytd_now['year'])} "
                             f"(אלפים)")
    if ytd_chg is not None:
        kpis["ytd_chg"] = {"value": round(ytd_chg, 4), "display": fmt.signed_pct(ytd_chg),
                           "tone": _tone(ytd_chg)}
        labels["ytd_chg_kpi"] = f"שינוי לעומת התקופה המקבילה ב-{ytd_prev['year']}"
    kpis["peak"] = {"value": peak["total"], "display": _k(peak["total"]),
                    "tone": "ok" if peak["year"] == last_year["year"] else "info"}
    labels["peak_kpi"] = f"יציאות בשנת השיא, {peak['year']} (אלפים)"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables, flags = {}, {}, {}

    def other(y):
        return round(y["total"] - y["air"], 1) if y["air"] is not None else None

    charts["years"] = {"x": [str(y["year"]) for y in years],
                       "air": [y["air"] for y in years], "other": [other(y) for y in years]}
    tables["years"] = []
    for k, y in enumerate(years):
        p = years[k - 1] if k and years[k - 1]["year"] == y["year"] - 1 else None
        tables["years"].append([str(y["year"]), _k(y["total"]), _k(y["air"]), _k(other(y)),
                                _spct(_chg(y["total"], p["total"]) if p else None)])

    charts["recent"] = {"x": [_mshort(m["t"]) for m in monthly],
                        "orig": [m["orig"] for m in monthly], "sa": [m["sa"] for m in monthly],
                        "trend": [m["trend"] for m in monthly]}
    tables["recent"] = []
    for m in reversed(monthly):
        p = by_t.get((m["t"][0] - 1, m["t"][1]))
        tables["recent"].append([_mname(m["t"]), _k(m["orig"]), _k(m["sa"]), _k(m["trend"]),
                                 _spct(_chg(m["orig"], p["orig"]) if p else None)])

    air = [a for a in air if a["orig"] is not None]
    flags["heat"] = bool(air)
    if air:
        air_by_t = {a["t"]: a for a in air}
        air_years = sorted({a["t"][0] for a in air})
        charts["heat"] = {"years": [str(y) for y in air_years],
                          "months": list(fmt.MONTHS_SHORT_HE),
                          "cells": [[a["t"][1] - 1, air_years.index(a["t"][0]), a["orig"]]
                                    for a in air],
                          "max": max(a["orig"] for a in air)}
        tables["heat"] = [[str(y)] + [_k(air_by_t[(y, m)]["orig"]) if (y, m) in air_by_t else ""
                                      for m in range(1, 13)] for y in air_years]

    # Age groups.
    age_he = [_age_he(a) for a in ages]
    flags["ages"] = bool(age_years) and bool(ages)
    if flags["ages"]:
        charts["ages"] = {"x": [str(y["year"]) for y in age_years], "names": age_he,
                          "series": [[y["ages"][a][0] for y in age_years] for a in ages]}
        tables["ages"] = [[str(y["year"])] + [_k(y["ages"][a][0]) for a in ages]
                          for y in age_years]
    ay = age_years[-1] if age_years else None
    male = []
    if ay:
        for a, h in zip(ages, age_he):
            t, mp = ay["ages"][a]
            if t is not None and mp is not None:
                male.append({"label": h, "total": t, "male": mp})
    tot_m = sum(m["total"] for m in male)
    male_all = sum(m["total"] * m["male"] for m in male) / tot_m / 100 if tot_m else None
    flags["male"] = len(male) >= 2
    if flags["male"]:
        charts["male"] = {"names": [m["label"] for m in male],
                          "male": [round(m["male"], 1) for m in male],
                          "female": [round(100 - m["male"], 1) for m in male]}
        tables["male"] = [[m["label"], _k(m["total"]), fmt.pct_of(m["male"]),
                           fmt.pct_of(100 - m["male"])] for m in male]

    # Age groups, year to date against the same months a year earlier.
    age_ytd, age_ytd_span = [], None
    if age_months:
        cy = age_months[-1]["t"][0]
        cur_m = sorted(m["t"][1] for m in age_months if m["t"][0] == cy)
        am = {m["t"]: m for m in age_months}
        if cur_m == list(range(1, len(cur_m) + 1)) and all((cy - 1, k) in am for k in cur_m):
            for a, h in zip(ages, age_he):
                c = [am[(cy, k)]["ages"][a][0] for k in cur_m]
                p = [am[(cy - 1, k)]["ages"][a][0] for k in cur_m]
                if None in c or None in p:
                    continue
                age_ytd.append({"label": h, "cur": sum(c), "prev": sum(p),
                                "chg": _chg(sum(c), sum(p))})
            age_ytd_span = (cy, cur_m[-1])
    flags["age_ytd"] = len(age_ytd) >= 2
    if flags["age_ytd"]:
        charts["age_ytd"] = {"names": [a["label"] for a in age_ytd],
                             "years": [str(age_ytd_span[0] - 1), str(age_ytd_span[0])],
                             "prev": [round(a["prev"], 1) for a in age_ytd],
                             "cur": [round(a["cur"], 1) for a in age_ytd]}
        tables["age_ytd"] = [[a["label"], _k(a["prev"]), _k(a["cur"]), _spct(a["chg"])]
                             for a in age_ytd]

    # Israelis living abroad.
    flags["abroad"] = bool(ab_months)
    if ab_months:
        charts["abroad"] = {"x": [_mshort(m["t"]) for m in ab_months],
                            "abroad": [m["abroad"] for m in ab_months],
                            "share": [round(m["share"] * 100, 1) for m in ab_months]}
        tables["abroad"] = [[_mname(m["t"]), _k(m["total"]), _k(m["abroad"]),
                             fmt.pct(m["share"])] for m in reversed(ab_months)]
        tables["abroad_years"] = [[str(y["year"]), _k(y["total"]), _k(y["abroad"]),
                                   fmt.pct(y["share"])] for y in reversed(ab_years)]

    # Routes and crossings.
    grand4 = next((r for r in routes if r["kind"] == "grand"), None)
    if grand4 is None or grand4["ytd"][-1] is None:
        raise ValueError("t4: grand total row (סך הכל) not found")
    g_now = grand4["ytd"][-1]
    modes = [r for r in routes if r["kind"] == "mode" and r["ytd"][-1] is not None]
    crossings = [r for r in routes if r["kind"] == "leaf" and r["mode"] != "דרך האוויר"
                 and any(v for v in r["ytd"] if v)]
    crossings.sort(key=lambda r: (-(r["ytd"][-1] or 0), r["name"]))
    flags["crossings"] = bool(crossings)
    if crossings:
        charts["crossings"] = {"names": [r["name"] for r in crossings],
                               "years": [str(y) for y in t4_years],
                               "series": [[r["ytd"][k] for r in crossings]
                                          for k in range(len(t4_years))]}
    tables["routes"] = [[r["name"]] + [_k(v) for v in r["ytd"]]
                        + [_spct(_chg(r["ytd"][-1], r["ytd"][-2]))] for r in routes]
    air_mode = next((r for r in modes if r["name"] == "דרך האוויר"), None)
    flags["modes"] = bool(modes)
    if modes:
        charts["modes"] = [{"name": r["name"], "value": r["ytd"][-1]} for r in modes]
        tables["modes"] = [[r["name"], _k(r["ytd"][-1]), fmt.pct(r["ytd"][-1] / g_now)
                            if g_now else ""] for r in modes]
        labels["modes_caption"] = f"יציאות לפי דרך היציאה, {_range(t4_end, t4_years[-1])} (אלפים)"

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if month_chg is not None:
        add("month", f"ב{_mname(lt)} יצאו ישראלים לחו\"ל {_k(last['orig'])} אלף פעמים, "
                     f"{_word(month_chg)} של {fmt.pct(abs(month_chg))} לעומת "
                     f"{_mname(prev['t'])} ({_k(prev['orig'])} אלף).")
    if ytd_chg is not None:
        add("ytd", f"מתחילת השנה ({_range(ytd_now['end'], ytd_now['year'])}) נרשמו "
                   f"{_k(ytd_now['total'])} אלף יציאות, {_word(ytd_chg)} של "
                   f"{fmt.pct(abs(ytd_chg))} לעומת התקופה המקבילה ב-{ytd_prev['year']} "
                   f"({_k(ytd_prev['total'])} אלף).")
    if len(years) >= 3:
        if peak["year"] == last_year["year"]:
            p = next((y for y in years if y["year"] == last_year["year"] - 1), None)
            add("peak", f"{peak['year']} הייתה שנת השיא בנתונים: {_k(peak['total'])} אלף "
                        f"יציאות לחו\"ל"
                        + (f", {_word(_chg(peak['total'], p['total']))} של "
                           f"{fmt.pct(abs(_chg(peak['total'], p['total'])))} לעומת {p['year']}"
                           if p and p["total"] else "") + ".")
        else:
            gap = _chg(last_year["total"], peak["total"])
            add("peak", f"שנת השיא בנתונים היא {peak['year']}, עם {_k(peak['total'])} אלף "
                        f"יציאות. ב-{last_year['year']} נרשמו {_k(last_year['total'])} אלף, "
                        f"{fmt.pct(abs(gap))} פחות.")
    # The sharpest fall against the same month a year earlier (war months).
    drops = [(_chg(m["orig"], by_t[(m["t"][0] - 1, m["t"][1])]["orig"]), m) for m in monthly
             if (m["t"][0] - 1, m["t"][1]) in by_t]
    drops = [d for d in drops if d[0] is not None]
    if drops:
        worst = min(drops, key=lambda d: (d[0], d[1]["t"]))
        if worst[0] <= -SHOCK_DROP:
            pm = by_t[(worst[1]["t"][0] - 1, worst[1]["t"][1])]
            add("shock", f"החודש החריג ביותר מאז {_mname(monthly[0]['t'])} היה {_mname(worst[1]['t'])}: "
                         f"{_k(worst[1]['orig'])} אלף יציאות בלבד, {fmt.pct(abs(worst[0]))} "
                         f"פחות מאשר ב{_mname(pm['t'])} ({_k(pm['orig'])} אלף).")
    run = 0
    for m in reversed(monthly):
        if m["pct"] is None or m["pct"] == 0:
            break
        if run and (m["pct"] > 0) != (last["pct"] > 0):
            break
        run += 1
    if run >= 3 and last["pct"] is not None:
        add("trend", f"מגמת היציאות לחו\"ל {'עולה' if last['pct'] > 0 else 'יורדת'} זה "
                     f"{run} חודשים ברציפות ({fmt.pct_of(abs(last['pct']))} ב{_mname(lt)}, "
                     f"בנתוני המגמה של הלמ\"ס).")
    if flags["age_ytd"]:
        moves = [a for a in age_ytd if a["chg"] is not None and abs(a["chg"]) >= AGE_MOVE]
        if moves:
            hi = max(moves, key=lambda a: (a["chg"], a["label"]))
            lo = min(moves, key=lambda a: (a["chg"], a["label"]))
            span = _range(age_ytd_span[1], age_ytd_span[0])
            text = (f"לפי גיל, השינוי הגדול ביותר מתחילת השנה ({span}) הוא בקבוצת "
                    f"הגיל {hi['label']}: {_word(hi['chg'])} של {fmt.pct(abs(hi['chg']))}")
            if lo is not hi and (lo["chg"] < 0) != (hi["chg"] < 0):
                text += (f", ואילו בקבוצת הגיל {lo['label']} נרשמה {_word(lo['chg'])} של "
                         f"{fmt.pct(abs(lo['chg']))}")
            add("ages", text + ".")
    if flags["male"] and male_all is not None:
        fem = [m for m in male if m["male"] < 50]
        add("male", f"{fmt.pct(male_all)} מהיציאות לחו\"ל ב-{ay['year']} היו של גברים. "
                    + (f"הנשים הן רוב רק בקבוצת הגיל {fem[0]['label']} "
                       f"({fmt.pct_of(100 - fem[0]['male'])})." if len(fem) == 1 else
                       f"הנשים הן רוב בקבוצות הגיל {fmt.join_he(m['label'] for m in fem)}."
                       if fem else "הגברים הם רוב בכל קבוצות הגיל."))
    if ab_months and ab_years:
        lm, ly = ab_months[-1], ab_years[-1]
        add("abroad", f"ישראלים המתגוררים בחו\"ל ובאו לביקור יצאו {_k(lm['abroad'])} אלף פעמים "
                      f"ב{_mname(lm['t'])}: {fmt.pct(lm['share'])} מכלל היציאות, לעומת "
                      f"{fmt.pct(ly['share'])} בכל שנת {ly['year']}.")
    land = next((r for r in modes if r["name"] == "דרך היבשה"), None)
    if land and land["ytd"][-1] and g_now:
        lc = _chg(land["ytd"][-1], land["ytd"][-2])
        if lc is not None and abs(lc) >= AGE_MOVE:
            add("land", f"{fmt.pct(land['ytd'][-1] / g_now)} מהיציאות מתחילת "
                        f"{t4_years[-1]} היו דרך מעברי היבשה ({_k(land['ytd'][-1])} אלף), "
                        f"{_word(lc)} של {fmt.pct(abs(lc))} לעומת התקופה המקבילה "
                        f"ב-{t4_years[-2]}.")

    # ── text ─────────────────────────────────────────────────────────────
    rel_date = pd.Timestamp(latest_rel["RELEASE_DATE"])
    release = {"no": latest_rel["RELEASE_NO"], "date": fmt.d_he(rel_date),
               "title": latest_rel["TITLE"], "headline": latest_rel["HEADLINE"],
               "url": latest_rel["PAGE_URL"], "pdf": latest_rel["REPORT_PDF_URL"]}
    t4_span = _range(t4_end, t4_years[-1]).replace(f" {t4_years[-1]}", "")
    labels.update({
        "lede": (f"כמה פעמים יוצאים ישראלים לחו\"ל בכל חודש, באיזה גיל ודרך אילו מעברי "
                 f"גבול. הנתונים מתוך ההודעה החודשית של הלשכה המרכזית לסטטיסטיקה "
                 f"(הלמ\"ס), ומתעדכנים עם כל הודעה חדשה. הנתון האחרון הוא ל{_mname(lt)}: "
                 f"{_k(last['orig'])} אלף יציאות."),
        "years_note": (f"יציאות ישראלים לחו\"ל בכל שנה מאז {years[0]['year']}, בדרך האוויר "
                       f"ובדרכי היבשה והים. השיא: {peak['year']}, {_k(peak['total'])} אלף."),
        "years_aria": f"יציאות לחו\"ל לפי שנה, {years[0]['year']} עד {years[-1]['year']}",
        "years_caption": "יציאות ישראלים לחו\"ל לפי שנה (אלפים)",
        "recent_note": (f"יציאות לחו\"ל בכל חודש מאז {_mname(monthly[0]['t'])}: הנתון המקורי, "
                        f"הנתון המנוכה עונתיות וקו המגמה של הלמ\"ס."),
        "recent_aria": f"יציאות לחו\"ל לפי חודש, {_mname(monthly[0]['t'])} עד {_mname(lt)}",
        "recent_caption": "יציאות ישראלים לחו\"ל לפי חודש (אלפים)",
        "routes_caption": f"יציאות לפי דרך ומעבר גבול, {t4_span} (אלפים)",
        "routes_chg_col": f"שינוי {t4_years[-2]} עד {t4_years[-1]}",
        "crossings_note": (f"יציאות דרך מעברי היבשה והים בחודשים {t4_span} של "
                           f"{fmt.join_he(str(y) for y in t4_years)}."
                           + (f" נמלי התעופה ({_k(air_mode['ytd'][-1])} אלף ב-{t4_years[-1]}) "
                              f"מופיעים רק בטבלה, כדי שמעברי היבשה ייראו בתרשים."
                              if air_mode else "")),
        "crossings_aria": f"יציאות לפי מעבר גבול ביבשה ובים, {t4_span}, שלוש שנים",
        "modes_aria": f"יציאות לפי דרך היציאה, {t4_span} {t4_years[-1]}",
        "span": f"{years[0]['year']}-{lt[0]}",
    })
    if air:
        labels.update({
            "heat_note": (f"יציאות בדרך האוויר בכל חודש מאז {_mname(air[0]['t'])}. כל שורה היא "
                          f"שנה וכל עמודה חודש; צבע כהה יותר הוא יותר יציאות. רואים את "
                          f"עונת הקיץ ואת החודשים שבהם השמיים נסגרו."),
            "heat_aria": (f"מפת חום של יציאות בדרך האוויר לפי שנה וחודש, "
                          f"{_mname(air[0]['t'])} עד {_mname(air[-1]['t'])}"),
            "heat_caption": "יציאות בדרך האוויר לפי שנה וחודש (אלפים)",
        })
    if flags["ages"]:
        big = max(range(len(ages)), key=lambda k: (age_years[-1]["ages"][ages[k]][0] or 0, -k))
        big_age = age_he[big]
        labels.update({
            "ages_note": (f"יציאות לחו\"ל בכל שנה לפי קבוצת גיל, {age_years[0]['year']} עד "
                          f"{age_years[-1]['year']}. קבוצת הגיל {big_age} היא הגדולה, ואפשר "
                          f"להסתיר אותה במקרא כדי לראות את השאר."),
            "ages_aria": "יציאות לחו\"ל לפי שנה וקבוצת גיל",
            "ages_caption": "יציאות לחו\"ל לפי שנה וקבוצת גיל (אלפים)",
            "age_cols": ["שנה"] + age_he,
        })
    if flags["male"]:
        labels.update({
            "male_note": (f"שיעור הגברים והנשים מהיציאות בכל קבוצת גיל ב-{ay['year']}. "
                          f"בסך הכול {fmt.pct(male_all)} מהיציאות היו של גברים."),
            "male_aria": f"גברים ונשים מהיציאות לחו\"ל לפי קבוצת גיל, {ay['year']}",
            "male_caption": f"יציאות לפי קבוצת גיל ומין, {ay['year']}",
        })
    if flags["age_ytd"]:
        labels.update({
            "age_ytd_note": (f"יציאות לחו\"ל לפי קבוצת גיל ב{_range(age_ytd_span[1], age_ytd_span[0])}, "
                             f"לעומת אותם חודשים ב-{age_ytd_span[0] - 1}."),
            "age_ytd_aria": f"יציאות לפי קבוצת גיל מתחילת השנה, {age_ytd_span[0] - 1} ו-{age_ytd_span[0]}",
            "age_ytd_caption": "יציאות לפי קבוצת גיל מתחילת השנה (אלפים)",
            "age_ytd_prev": f"מתחילת {age_ytd_span[0] - 1}",
            "age_ytd_cur": f"מתחילת {age_ytd_span[0]}",
        })
    if ab_months:
        labels.update({
            "abroad_note": (f"יציאות של ישראלים המתגוררים בחו\"ל ובאו לביקור בארץ (\"ביקורי "
                            f"מולדת\"), בכל חודש מאז {_mname(ab_months[0]['t'])}: מספר היציאות "
                            f"ושיעורן מכלל היציאות."),
            "abroad_aria": (f"יציאות של ישראלים המתגוררים בחו\"ל לפי חודש, "
                            f"{_mname(ab_months[0]['t'])} עד {_mname(ab_months[-1]['t'])}"),
            "abroad_caption": "יציאות של ישראלים המתגוררים בחו\"ל לפי חודש (אלפים)",
            "abroad_years_caption": "יציאות של ישראלים המתגוררים בחו\"ל לפי שנה (אלפים)",
        })

    summary = (f"יציאות ישראלים לחו\"ל לפי חודש, גיל ומעבר גבול, מנתוני הלמ\"ס. "
               f"ב{_mname(lt)} נרשמו {_k(last['orig'])} אלף יציאות"
               + (f" ({fmt.signed_pct(month_chg)} בשנה)" if month_chg is not None else "")
               + ".")
    desc = (f"כמה ישראלים טסים לחו\"ל: {_k(last['orig'])} אלף יציאות ב{_mname(lt)}"
            + (f", {_k(ytd_now['total'])} אלף מתחילת השנה" if ytd_now else "")
            + ". נתונים חודשיים לפי גיל ומעבר גבול.")
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{years[0]['year']}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "יציאות ישראלים לחו\"ל: נתונים חודשיים | הלמ\"ס",
                "description": desc,
                "name": "יציאות ישראלים לחו\"ל",
                "alternate_names": ["כמה ישראלים טסים לחו\"ל", "נסיעות ישראלים לחו\"ל",
                                    "יציאות לחו\"ל של ישראלים", "תיירות יוצאת מישראל"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": flags,
    }
