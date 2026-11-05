"""רכישות בכרטיסי אשראי על ידי צרכנים פרטיים: CBS's monthly release.

The release covers a rolling three-month window (e.g. July-September) and
publishes value indices of private consumers' credit card purchases at
CONSTANT prices (deflated), base 2002 = 100. Inputs are CBS grid tables from
the newest edition:
  t1   total purchases: annual rows (one a year since 2010, original index
       and its % change) and monthly rows for about three years (original,
       seasonally adjusted and trend index, each with a % change)
  t2   other goods and services   } the same layout as t1,
  t3   food and beverages         } one table per main purchase group
  t4   industrial goods           }
  t5   services                   }
  t6   chart data: 15 sub-sectors plus the group totals, monthly since
       January of the previous year (trend / SA / original index)
  releases  the edition list (number, date, headline, link)

Header rows and columns are found by their labels (govlib.cbs) and raise
when missing; data rows are found by pattern, so a missing one only shortens
a series. "Latest month" is t1's newest monthly row.
"""
import re

import pandas as pd
from govlib import cbs, fmt

TOTAL_MARKS = ("סך הכל", "סה\"כ")
RECENT_MONTHS = 13
WINDOW = 3  # the release's rolling window, in months
SHOCK = -0.15  # a month this far below its trend counts as a shock
HEBREW = re.compile("[א-ת]")


# ── tables ───────────────────────────────────────────────────────────────


def _index_table(rows, name):
    """t1-t5: {"name", "base", "years": {year: (index, pct)},
    "months": {(y, m): {"orig", "sa", "trend"}}}."""
    h = cbs.row_with(rows, "Trend", name=name)
    trend = cbs.col_after(rows[h], "Trend")
    sa = cbs.col_after(rows[h], "Seasonally adjusted")
    orig = cbs.col_after(rows[h], "Original data")
    ih = cbs.row_with(rows, "Index", h, name=name)
    ti = cbs.col_after(rows[ih], "Index", trend)
    si = cbs.col_after(rows[ih], "Index", sa)
    oi = cbs.col_after(rows[ih], "Index", orig)
    op = cbs.col_after(rows[ih], "% Change", orig)
    hm = cbs.row_with(rows, "מגמה", name=name)
    label = next((cbs.cell(rows[i], trend) for i in range(hm - 1, -1, -1)
                  if HEBREW.search(cbs.cell(rows[i], trend))), "")
    if not label:
        raise ValueError(f"{name}: group name above column {trend} not found")
    base = next((m.group(1) for r in rows[:h] for c in r
                 for m in [re.search(r"BASE:\s*(?:average\s*)?((?:19|20)\d\d)", c, re.IGNORECASE)] if m),
                None)
    years, last_annual = {}, None
    for i in range(ih + 1, len(rows)):
        r = rows[i]
        if "שנת" not in r:
            continue
        y = next((int(c) for c in r if cbs.YEAR.match(c)), None)
        v = cbs.val(r, oi)
        if y is not None and v is not None:
            years[y] = (v, cbs.val(r, op))
            last_annual = i
    start = (last_annual if last_annual is not None else ih) + 1
    months = {}
    for i, y, m, end in cbs.periods(rows, start, len(rows)):
        if m is None or end:
            continue
        v = {"orig": cbs.val(rows[i], oi), "sa": cbs.val(rows[i], si),
             "trend": cbs.val(rows[i], ti)}
        if v["orig"] is not None:
            months[(y, m)] = v
    if label in TOTAL_MARKS:
        label = "סך כל הרכישות"
    return {"name": label, "base": base, "years": years, "months": months}


def _t6(rows):
    """{label: {(y, m): {"orig", "sa", "trend"}}} for every column block of
    the chart-data table, in sheet order."""
    h = cbs.row_with(rows, "Trend", name="t6")
    hs = max(i for i in range(h) if "Seasonally" in rows[i]) if any(
        "Seasonally" in rows[i] for i in range(h)) else None
    if hs is None:
        raise ValueError("t6: header label 'Seasonally' not found")
    hm = cbs.row_with(rows, "מגמה", name="t6")
    top = cbs.row_with(rows, "Original data, seasonally", name="t6", contains=True)
    tcols = [j for j, c in enumerate(rows[h]) if c == "Trend"]
    if not tcols:
        raise ValueError("t6: no Trend columns")
    ps = cbs.periods(rows, h + 1, len(rows))
    out = {}
    for k, j in enumerate(tcols):
        stop = tcols[k + 1] if k + 1 < len(tcols) else len(rows[h]) + 1
        try:
            sa = cbs.col_after(rows[hs], "Seasonally", j)
            orig = cbs.col_after(rows[hs], "Original", j)
        except ValueError:
            continue
        if sa >= stop or orig >= stop:
            continue
        label = next((cbs.cell(rows[i], j) for i in range(top + 1, hm)
                      if HEBREW.search(cbs.cell(rows[i], j))), "")
        if not label:
            continue
        ser = {}
        for i, y, m, end in ps:
            if m is None or end:
                continue
            v = {"orig": cbs.val(rows[i], orig), "sa": cbs.val(rows[i], sa),
                 "trend": cbs.val(rows[i], j)}
            if v["orig"] is not None:
                ser[(y, m)] = v
        if ser:
            out[label] = ser
    return out


def _is_total(label):
    return any(t in label for t in TOTAL_MARKS)


def _display(label):
    """CBS spells שירותי two ways in the chart table; show one."""
    return label.replace("שרותי", "שירותי").strip()


def _short(label):
    """A name without its parenthetical, for running text."""
    return re.sub(r"\s*\([^)]*\)", "", label).strip()


# ── formatting ───────────────────────────────────────────────────────────


def _mname(t):
    return f"{fmt.MONTHS_HE[t[1] - 1]} {t[0]}"


def _mshort(t):
    return f"{fmt.MONTHS_SHORT_HE[t[1] - 1]} {t[0]}"


def _prev(t, k=1):
    y, m = t
    n = y * 12 + (m - 1) - k
    return (n // 12, n % 12 + 1)


def _window(t, n=WINDOW):
    return [_prev(t, k) for k in range(n - 1, -1, -1)]


def _wname(ts):
    a, b = ts[0], ts[-1]
    if a[0] == b[0]:
        return f"{fmt.MONTHS_HE[a[1] - 1]}-{fmt.MONTHS_HE[b[1] - 1]} {b[0]}"
    return f"{_mname(a)} עד {_mname(b)}"


def _chg(new, old):
    if new is None or not old:
        return None
    return new / old - 1


def _sum(series, ts, key="orig"):
    vals = [series.get(t, {}).get(key) for t in ts]
    return None if any(v is None for v in vals) else sum(vals)


def _word(c):
    return "עלייה" if c > 0 else "ירידה"


def _tone(c, band=0.005):
    if c is None:
        return "brand"
    return "ok" if c > band else "danger" if c < -band else "warn"


def _r1(v):
    return None if v is None else round(v, 1)


def _pct1(c):
    return "" if c is None else fmt.signed_pct(c)


# ── compute ──────────────────────────────────────────────────────────────


def compute(frames):
    rel = frames["releases"]
    rel = rel[rel["RELEASE_DATE"] != ""].sort_values(["RELEASE_DATE", "RELEASE_NO"],
                                                      kind="stable")
    if rel.empty:
        raise ValueError("releases: no edition listed")
    latest_rel = rel.iloc[-1]

    total = _index_table(cbs.grid(frames["t1"], "t1"), "t1")
    if not total["months"]:
        raise ValueError("t1: no monthly rows")
    groups = [_index_table(cbs.grid(frames[k], k), k) for k in ("t3", "t4", "t5", "t2")]
    groups = [g for g in groups if g["months"]]
    subs_raw = _t6(cbs.grid(frames["t6"], "t6"))
    leaves = {_display(k): v for k, v in subs_raw.items() if not _is_total(k)}

    tm = total["months"]
    lt = max(tm)
    last = tm[lt]
    win = _window(lt)
    win_prev = [(y - 1, m) for y, m in win]
    yoy3 = _chg(_sum(tm, win), _sum(tm, win_prev))
    yoy1 = _chg(last["orig"], tm.get((lt[0] - 1, lt[1]), {}).get("orig"))
    pm = tm.get(_prev(lt), {})
    sa_mom = _chg(last["sa"], pm.get("sa"))
    tr_mom = _chg(last["trend"], pm.get("trend"))
    years = sorted(total["years"])
    base = total["base"]
    base_txt = f" (בסיס: {base} = 100)" if base else ""

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis, labels = {}, {}
    if yoy3 is not None:
        kpis["yoy3"] = {"value": round(yoy3, 4), "display": fmt.signed_pct(yoy3),
                        "tone": _tone(yoy3)}
        labels["yoy3_kpi"] = f"{_wname(win)} לעומת התקופה המקבילה אשתקד (במחירים קבועים)"
    if sa_mom is not None:
        kpis["sa_mom"] = {"value": round(sa_mom, 4), "display": fmt.signed_pct(sa_mom),
                          "tone": _tone(sa_mom)}
        labels["sa_mom_kpi"] = f"שינוי חודשי ב{_mname(lt)}, נתון מנוכה עונתיות"
    if tr_mom is not None:
        kpis["trend"] = {"value": round(tr_mom, 4), "display": fmt.signed_pct(tr_mom, 2),
                         "tone": _tone(tr_mom, 0.001)}
        labels["trend_kpi"] = f"קצב השינוי החודשי של המגמה, {_mname(lt)}"
    if years and total["years"][years[-1]][1] is not None:
        c = total["years"][years[-1]][1] / 100
        kpis["annual"] = {"value": round(c, 4), "display": fmt.signed_pct(c),
                          "tone": _tone(c)}
        labels["annual_kpi"] = f"שינוי ריאלי בשנת {years[-1]} כולה לעומת {years[-1] - 1}"
    if last["sa"] is not None:
        kpis["index"] = {"value": round(last["sa"], 1), "display": fmt.num_he(last["sa"], 1),
                         "tone": "brand"}
        labels["index_kpi"] = f"מדד הרכישות מנוכה העונתיות, {_mname(lt)}{base_txt}"

    # ── charts + tables ──────────────────────────────────────────────────
    charts, tables = {}, {}
    mts = sorted(tm)
    charts["total"] = {"x": [_mshort(t) for t in mts],
                       "orig": [_r1(tm[t]["orig"]) for t in mts],
                       "sa": [_r1(tm[t]["sa"]) for t in mts],
                       "trend": [_r1(tm[t]["trend"]) for t in mts]}
    tables["total"] = []
    for t in reversed(mts[-RECENT_MONTHS:]):
        p = tm.get(_prev(t), {})
        tables["total"].append([_mname(t), fmt.num_he(tm[t]["orig"], 1),
                                fmt.num_he(tm[t]["sa"], 1) if tm[t]["sa"] else "",
                                fmt.num_he(tm[t]["trend"], 1) if tm[t]["trend"] else "",
                                _pct1(_chg(tm[t]["sa"], p.get("sa")))])

    # annual growth, total + groups
    charts["annual"] = {"x": [str(y) for y in years],
                        "pct": [_r1(total["years"][y][1]) for y in years]}
    pcts = [total["years"][y][1] for y in years if total["years"][y][1] is not None]
    avg_growth = sum(pcts) / len(pcts) if pcts else None
    charts["annual"]["avg"] = _r1(avg_growth)
    tables["annual"] = [[str(y), fmt.num_he(total["years"][y][0], 1),
                         _pct1(total["years"][y][1] / 100
                               if total["years"][y][1] is not None else None)]
                        for y in reversed(years)]

    # level since the base year, by group (index = growth since the base year)
    gyears = sorted({y for g in groups for y in g["years"]})
    charts["groups_long"] = {"x": [str(y) for y in gyears],
                             "names": [g["name"] for g in groups] + [total["name"]],
                             "series": [[_r1(g["years"].get(y, (None,))[0]) for y in gyears]
                                        for g in groups + [total]]}
    tables["groups_long"] = [[str(y)] + [fmt.num_he(g["years"][y][0], 1) if y in g["years"]
                                         else "" for g in groups + [total]]
                             for y in reversed(gyears)]
    labels["group_names"] = [g["name"] for g in groups]
    labels["total_name"] = total["name"]

    # monthly trend by group, rebased to the first month all groups share
    common = sorted(set.intersection(*[{t for t, v in g["months"].items() if v["trend"]}
                                       for g in groups])) if groups else []
    group_rows = []
    for g in groups:
        gm = g["months"]
        glt = max(gm)
        gp = gm.get(_prev(glt), {})
        group_rows.append({
            "name": g["name"],
            "win": _window(glt),
            "sa": gm[glt]["sa"],
            "mom": _chg(gm[glt]["sa"], gp.get("sa")),
            "yoy3": _chg(_sum(gm, _window(glt)), _sum(gm, [(y - 1, m) for y, m in _window(glt)])),
            "trend12": _chg(gm[glt]["trend"], gm.get((glt[0] - 1, glt[1]), {}).get("trend")),
        })
    if len(common) >= 6:
        b = common[0]
        charts["groups"] = {"x": [_mshort(t) for t in common],
                            "names": [g["name"] for g in groups],
                            "series": [[round(g["months"][t]["trend"] / g["months"][b]["trend"]
                                              * 100, 1) for t in common] for g in groups],
                            "base": _mname(b)}
    tables["groups"] = [[r["name"], fmt.num_he(r["sa"], 1) if r["sa"] else "",
                         _pct1(r["mom"]), _pct1(r["yoy3"]), _pct1(r["trend12"])]
                        for r in group_rows]

    # sub-sectors: the release window against the same months a year before
    sub = []
    for name, s in leaves.items():
        slt = max(s)
        sw = _window(slt)
        c = _chg(_sum(s, sw), _sum(s, [(y - 1, m) for y, m in sw]))
        if c is not None:
            sub.append({"name": name, "chg": c, "win": sw})
    sub.sort(key=lambda r: (-r["chg"], r["name"]))
    if sub:
        charts["subs"] = {"names": [r["name"] for r in sub],
                          "pct": [round(r["chg"] * 100, 1) for r in sub]}
        tables["subs"] = [[r["name"], fmt.signed_pct(r["chg"])] for r in sub]

    # shocks: seasonally adjusted index against the trend, per sub-sector
    sub_months = sorted({t for s in leaves.values() for t in s})
    shock_names = sorted(leaves, key=lambda n: n)
    cells, shock_rows, worst_all = [], [], None
    for yi, name in enumerate(shock_names):
        s = leaves[name]
        devs = {t: s[t]["sa"] / s[t]["trend"] - 1 for t in s
                if s[t]["sa"] is not None and s[t]["trend"]}
        for xi, t in enumerate(sub_months):
            if t in devs:
                cells.append([xi, yi, round(devs[t] * 100, 1)])
        if devs:
            wt = min(devs, key=lambda t: (devs[t], t))
            lt_s = max(devs)
            shock_rows.append([name, _mname(wt), fmt.signed_pct(devs[wt]),
                               fmt.signed_pct(devs[lt_s])])
            if worst_all is None or (devs[wt], name) < (worst_all[2], worst_all[0]):
                worst_all = (name, wt, devs[wt])
    if cells:
        lim = max(abs(c[2]) for c in cells)
        charts["shocks"] = {"x": [_mshort(t) for t in sub_months], "y": shock_names,
                            "cells": cells, "max": min(round(lim), 50)}
        tables["shocks"] = shock_rows
        labels["shock_span"] = f"{_mname(sub_months[0])} עד {_mname(sub_months[-1])}"

    # seasonality: original index, month by year
    syears = sorted({t[0] for t in mts})
    charts["seasons"] = {"x": fmt.MONTHS_SHORT_HE, "years": [str(y) for y in syears],
                         "series": [[_r1(tm[(y, m)]["orig"]) if (y, m) in tm else None
                                     for m in range(1, 13)] for y in syears]}
    tables["seasons"] = [[fmt.MONTHS_HE[m - 1]] + [fmt.num_he(tm[(y, m)]["orig"], 1)
                                                   if (y, m) in tm else "" for y in syears]
                         for m in range(1, 13)]
    labels["season_years"] = [str(y) for y in syears]

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    if yoy3 is not None:
        add("yoy3", f"ב{_wname(win)} היו הרכישות בכרטיסי אשראי, במחירים קבועים, "
                    f"{'גבוהות' if yoy3 > 0 else 'נמוכות'} ב-{fmt.pct(abs(yoy3))} "
                    f"מאשר בחודשים המקבילים אשתקד"
                    + (f" (ב{_mname(lt)} לבדו: {fmt.signed_pct(yoy1)})" if yoy1 is not None
                       else "") + ".")
    if tr_mom is not None and sa_mom is not None:
        if abs(tr_mom) < 0.001:
            trend_txt = "קו המגמה כמעט יציב"
        else:
            trend_txt = (f"קו המגמה {'עולה' if tr_mom > 0 else 'יורד'} בקצב של "
                         f"{fmt.pct(abs(tr_mom), 2)} בחודש")
        add("trend", f"ב{_mname(lt)} {'עלו' if sa_mom > 0 else 'ירדו'} הרכישות בנתון מנוכה "
                     f"העונתיות ב-{fmt.pct(abs(sa_mom))} לעומת החודש הקודם, ו{trend_txt}.")
    if len(years) >= 2 and total["years"][years[-1]][1] is not None and avg_growth is not None:
        c = total["years"][years[-1]][1] / 100
        add("annual", f"בשנת {years[-1]} כולה {'גדלו' if c > 0 else 'קטנו'} הרכישות בכרטיסי "
                      f"אשראי ב-{fmt.pct(abs(c))} במחירים קבועים. הממוצע השנתי מאז {years[0]}: "
                      f"{fmt.signed_pct(avg_growth / 100)}.")
    if len(sub) >= 4:
        hi, lo = sub[0], sub[-1]
        if hi["chg"] - lo["chg"] >= 0.05:
            add("subs", f"בין ענפי המשנה, ב{_wname(hi['win'])} לעומת אשתקד: הצמיחה החזקה "
                        f"ביותר ב{_short(hi['name'])} ({fmt.signed_pct(hi['chg'])}), והחלשה ביותר "
                        f"ב{_short(lo['name'])} ({fmt.signed_pct(lo['chg'])}).")
    if worst_all and worst_all[2] <= SHOCK:
        add("shock", f"הזעזוע החד ביותר מאז {_mname(sub_months[0])}: ב{_mname(worst_all[1])} "
                     f"היו הרכישות ב{_short(worst_all[0])} נמוכות ב-{fmt.pct(abs(worst_all[2]))} "
                     f"מקו המגמה שלהן (נתון מנוכה עונתיות).")
    if len(groups) >= 2 and gyears and base:
        ly = gyears[-1]
        lv = [(g["years"][ly][0], g["name"]) for g in groups if ly in g["years"]]
        if len(lv) >= 2:
            (vh, nh), (vl, nl) = max(lv), min(lv)
            if vh / vl >= 1.3:
                add("long", f"לפי מדד {ly}, מאז {base} הרכישות ב{_short(nh)} גדלו פי "
                            f"{fmt.num_he(vh / 100, 1)} במחירים קבועים, לעומת פי "
                            f"{fmt.num_he(vl / 100, 1)} ב{_short(nl)}.")
    if group_rows:
        gr = [r for r in group_rows if r["yoy3"] is not None]
        if len(gr) >= 2:
            top = max(gr, key=lambda r: (r["yoy3"], r["name"]))
            bot = min(gr, key=lambda r: (r["yoy3"], r["name"]))
            if top["yoy3"] - bot["yoy3"] >= 0.03:
                add("groups", f"בקבוצות הרכישה הראשיות, ב{_wname(top['win'])} לעומת החודשים המקבילים "
                              f"אשתקד, הצמיחה הגבוהה ביותר ב{_short(top['name'])} "
                              f"({fmt.signed_pct(top['yoy3'])}) והנמוכה ביותר ב{_short(bot['name'])} "
                              f"({fmt.signed_pct(bot['yoy3'])}).")

    # ── text ─────────────────────────────────────────────────────────────
    labels.update({
        "lede": (f"מדד הרכישות של צרכנים פרטיים בכרטיסי אשראי, מהודעה חודשית של הלשכה "
                 f"המרכזית לסטטיסטיקה (הלמ\"ס). המדד מחושב מנתוני כל חברות כרטיסי האשראי "
                 f"במחירים קבועים, כלומר בניכוי עליית המחירים, ומפולח לארבע קבוצות רכישה "
                 f"ול-{len(leaves)} ענפי משנה. הנתון האחרון הוא ל{_mname(lt)}."),
        "total_note": (f"מדד סך הרכישות בכל חודש מאז {_mname(mts[0])}: הנתון המקורי, "
                       f"המנוכה עונתיות וקו המגמה{base_txt}. אפשר לגרור כדי להתמקד בתקופה."),
        "total_aria": f"מדד רכישות בכרטיסי אשראי, {_mname(mts[0])} עד {_mname(lt)}",
        "total_caption": "מדד הרכישות לפי חודש, החודשים האחרונים",
        "annual_note": (f"השינוי הריאלי בסך הרכישות בכל שנה לעומת השנה הקודמת. הקו המקווקו "
                        f"הוא הממוצע מאז {years[0]}: {_pct1(avg_growth / 100)}."
                        if years and avg_growth is not None else ""),
        "annual_aria": "שינוי שנתי בסך הרכישות בכרטיסי אשראי",
        "annual_caption": "מדד הרכישות השנתי ושיעור השינוי",
        "groups_long_note": (f"מדד הרכישות השנתי בכל קבוצת רכישה. כל המדדים מתחילים מ-100 בשנת "
                             f"{base}, ולכן הגובה של כל קו הוא הצמיחה המצטברת מאז."
                             if base else "מדד הרכישות השנתי בכל קבוצת רכישה."),
        "groups_long_aria": "מדד רכישות שנתי לפי קבוצת רכישה",
        "groups_long_caption": "מדד רכישות שנתי לפי קבוצת רכישה",
        "groups_aria": "קו המגמה של כל קבוצת רכישה",
        "groups_caption": "קבוצות הרכישה: הנתון האחרון ושיעורי השינוי",
    })
    if "groups" in charts:
        labels["groups_note"] = (f"קו המגמה של כל אחת מארבע קבוצות הרכישה, כש-{_mname(common[0])} "
                                 f"= 100, כדי להשוות את קצב הצמיחה. בטבלה: הנתון האחרון "
                                 f"ושיעורי השינוי.")
    if sub:
        labels.update({
            "subs_note": (f"השינוי ברכישות בכל ענף משנה ב{_wname(sub[0]['win'])} לעומת אותם "
                          f"חודשים אשתקד, במחירים קבועים (נתונים מקוריים)."),
            "subs_aria": "שינוי שנתי ברכישות לפי ענף משנה",
            "subs_caption": "שינוי שנתי לפי ענף משנה",
        })
    if cells:
        labels.update({
            "shocks_note": ("כמה רחוק היה כל חודש מקו המגמה של הענף, בנתון מנוכה עונתיות. "
                            "אדום: חודש חלש מהמגמה, כחול: חזק ממנה. כך בולטים חודשי זעזוע, "
                            "כמו מלחמה או סגר, וענפים שנפגעו בהם יותר."),
            "shocks_aria": f"סטייה מקו המגמה לפי ענף וחודש, {labels['shock_span']}",
            "shocks_caption": "החודש החלש ביותר בכל ענף, והחודש האחרון",
        })
    labels.update({
        "seasons_note": ("מדד הרכישות המקורי בכל חודש, שנה מול שנה. החגים, החופשות ומספר "
                         "ימי העסקים בחודש מזיזים את הרכישות מחודש לחודש."),
        "seasons_aria": "מדד רכישות מקורי לפי חודש, שנה מול שנה",
        "seasons_caption": "מדד רכישות מקורי לפי חודש ושנה",
    })

    release = {"no": latest_rel["RELEASE_NO"], "title": latest_rel["TITLE"],
               "headline": latest_rel["HEADLINE"], "url": latest_rel["PAGE_URL"],
               "pdf": latest_rel["REPORT_PDF_URL"],
               "date": fmt.d_he(pd.Timestamp(latest_rel["RELEASE_DATE"]))}
    summary = ("מדד חודשי של רכישות צרכנים פרטיים בכרטיסי אשראי במחירים קבועים, לפי קבוצת "
               "רכישה וענף משנה, מנתוני הלמ\"ס"
               + (f". {_wname(win)}: {fmt.signed_pct(yoy3)} לעומת אשתקד" if yoy3 is not None
                  else "") + ".")
    desc = ("כמה מוציאים בכרטיסי אשראי, במחירים קבועים: מזון, מוצרי תעשייה, שירותים ו-"
            f"{len(leaves)} ענפי משנה"
            + (f". {_wname(win)}: {fmt.signed_pct(yoy3)} בשנה" if yoy3 is not None else "")
            + ".")
    first_year = min(years + [mts[0][0]])
    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_year}/{lt[0]}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "רכישות בכרטיסי אשראי לפי ענף, במחירים קבועים | הלמ\"ס",
                "description": desc,
                "name": "רכישות בכרטיסי אשראי של צרכנים פרטיים",
                "alternate_names": ["רכישות בכרטיסי אשראי על ידי צרכנים פרטיים",
                                    "מדד הרכישות בכרטיסי אשראי",
                                    "הוצאה בכרטיסי אשראי לפי ענף משנה",
                                    "צריכה פרטית בכרטיסי אשראי"],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "release": release,
        "flags": {"groups": "groups" in charts, "groups_long": len(gyears) >= 3 and bool(groups),
                  "annual": len(years) >= 3, "subs": bool(sub), "shocks": bool(cells)},
    }
