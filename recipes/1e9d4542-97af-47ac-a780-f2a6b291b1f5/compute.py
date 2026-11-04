"""Public-transport validations (תיקופי מסלקה) per station, time window and day.

One row = station x time window x month, with 31 day columns holding that
day's validation count. The recipe reads the newest yearly resource
(`pick: "latest"`) and aggregates it column by column (never a full numeric
matrix), so a full year (~2M rows) stays well inside the compute heap.
"""
import calendar
import datetime as dt
import re

import numpy as np
import pandas as pd

from govlib import fmt

DAY_COLS = [f"day_{i}" for i in range(1, 32)]
UNDEFINED_ID = "-1"
WEEKDAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
TOP_N = 15
SKEW_POOL = 100
SKEW_SIDE = 8
WIN_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*-\s*(.+?)\s*$")
BUCKETS = [  # (low, high_exclusive, label)
    (1, 100, "1-99"),
    (100, 1000, "100-999"),
    (1000, 10000, "1,000-9,999"),
    (10000, 100000, "10,000-99,999"),
    (100000, 1000000, "100,000-999,999"),
    (1000000, None, "1,000,000 ומעלה"),
]
CURVE_POINTS = [10, 50, 100, 500, 1000, 5000, 10000, 20000]


def _plural(n, one, many):
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def _mil(v, digits=1):
    return fmt.num_he(v / 1e6, digits)


def _parse_window(label):
    m = WIN_RE.match(label)
    if not m:
        return {"label": label, "start": 99, "hours": None, "name": label, "range": ""}
    h1, m1, h2, m2, name = m.groups()
    start, end = int(h1), int(h2)
    hours = end - start + 1 if end >= start else None
    return {
        "label": label,
        "start": start,
        "hours": hours,
        "name": name,
        "range": f"{h1.zfill(2)}:{m1}-{h2.zfill(2)}:{m2}",
    }


def compute(frames):
    df = frames["main"]
    year = pd.to_numeric(df["year_key"], errors="coerce")
    month = pd.to_numeric(df["month_key"], errors="coerce")
    ok = year.notna() & month.notna() & month.between(1, 12)
    if not ok.all():
        df = df[ok.to_numpy()]
        year, month = year[ok], month[ok]
    year = year.astype(int).to_numpy()
    month = month.astype(int).to_numpy()
    n = len(df)

    # ---- keys --------------------------------------------------------------
    ym_vals = sorted(set(zip(year.tolist(), month.tolist())))
    ym_index = {v: i for i, v in enumerate(ym_vals)}
    ym_code = np.array([ym_index[(y, m)] for y, m in zip(year, month)], dtype=np.int64)
    n_ym = len(ym_vals)

    win_labels = df["LowOrPeakDescFull"].str.strip().to_numpy()
    wins = sorted({_parse_window(w)["label"]: _parse_window(w) for w in set(win_labels)}.values(),
                  key=lambda w: (w["start"], w["label"]))
    win_index = {w["label"]: i for i, w in enumerate(wins)}
    win_code = np.array([win_index[w] for w in win_labels], dtype=np.int64)
    n_w = len(wins)

    sid = df["StationId"].str.strip().to_numpy()
    st_ids = sorted(set(sid.tolist()), key=lambda s: (len(s), s))
    st_index = {s: i for i, s in enumerate(st_ids)}
    st_code = np.array([st_index[s] for s in sid], dtype=np.int64)
    n_st = len(st_ids)
    names_raw = df["StationName"].str.strip().to_numpy()
    st_name = {}
    order = np.lexsort((names_raw, st_code))
    for i in order:
        st_name.setdefault(st_ids[st_code[i]], names_raw[i])

    # ---- aggregate column by column -----------------------------------------
    row_total = np.zeros(n)
    ymd = np.zeros((n_ym, 31))          # per (year-month, day)
    ymdw = np.zeros((n_ym, 31, n_w))    # per (year-month, day, window)
    key_yw = ym_code * n_w + win_code
    for d, col in enumerate(DAY_COLS):
        vals = np.array(pd.to_numeric(df[col], errors="coerce").fillna(0), dtype="float64")
        vals[vals < 0] = 0
        row_total += vals
        ymd[:, d] = np.bincount(ym_code, weights=vals, minlength=n_ym)
        ymdw[:, d, :] = np.bincount(key_yw, weights=vals, minlength=n_ym * n_w).reshape(n_ym, n_w)

    st_total = np.bincount(st_code, weights=row_total, minlength=n_st)
    st_win = np.bincount(st_code * n_w + win_code, weights=row_total,
                         minlength=n_st * n_w).reshape(n_st, n_w)
    st_rows_ym = np.zeros((n_ym, n_st), dtype=bool)
    pos = row_total > 0
    st_rows_ym[ym_code[pos], st_code[pos]] = True

    # ---- the daily calendar ---------------------------------------------------
    dates, daily, daily_w = [], [], []
    for i, (y, m) in enumerate(ym_vals):
        dim = calendar.monthrange(y, m)[1]
        for d in range(dim):
            dates.append(dt.date(y, m, d + 1))
            daily.append(ymd[i, d])
            daily_w.append(ymdw[i, d, :])
    daily = np.array(daily)
    daily_w = np.array(daily_w)
    nz = np.nonzero(daily > 0)[0]
    first, last = int(nz[0]), int(nz[-1])
    dates = dates[first:last + 1]
    daily = daily[first:last + 1]
    daily_w = daily_w[first:last + 1]
    d0, d1 = dates[0], dates[-1]
    grand = float(daily.sum())
    dow = np.array([(x.weekday() + 1) % 7 for x in dates])  # 0 = Sunday

    roll = [None] * len(daily)
    for i in range(6, len(daily)):
        roll[i] = int(round(daily[i - 6:i + 1].mean()))

    # ---- months ----------------------------------------------------------------
    multi_year = len({y for y, _ in ym_vals}) > 1
    months = []
    for i, (y, m) in enumerate(ym_vals):
        sel = [k for k, x in enumerate(dates) if x.year == y and x.month == m]
        if not sel:
            continue
        dim = calendar.monthrange(y, m)[1]
        tot = float(daily[sel].sum())
        partial = len(sel) < dim
        short = fmt.MONTHS_SHORT_HE[m - 1] + (f" {y}" if multi_year else "")
        months.append({
            "y": y, "m": m, "days": len(sel), "partial": partial,
            "label": short + (" (חלקי)" if partial else ""),
            "name": f"{fmt.MONTHS_HE[m - 1]} {y}",
            "total": tot, "per_day": tot / len(sel),
            "stations": int(st_rows_ym[i].sum() - (st_rows_ym[i, st_index[UNDEFINED_ID]]
                                                  if UNDEFINED_ID in st_index else 0)),
            "mix": [float(daily_w[sel][:, w].sum()) for w in range(n_w)],
        })
    full_months = [mo for mo in months if not mo["partial"]]

    # ---- weekday + window profiles --------------------------------------------
    dow_avg = [float(daily[dow == k].mean()) if (dow == k).any() else 0.0 for k in range(7)]
    win_tot = daily_w.sum(axis=0)
    n_days = len(daily)
    heat = []
    heat_rows = []
    for k in range(7):
        sel = dow == k
        row = []
        for w in range(n_w):
            v = float(daily_w[sel, w].mean()) if sel.any() else 0.0
            heat.append([w, k, int(round(v / 1000))])
            row.append(v)
        heat_rows.append(row)

    # ---- stations ----------------------------------------------------------------
    undef_total = float(st_total[st_index[UNDEFINED_ID]]) if UNDEFINED_ID in st_index else 0.0
    real = [i for i, s in enumerate(st_ids) if s != UNDEFINED_ID]
    name_ids = {}
    for i in real:
        name_ids.setdefault(st_name[st_ids[i]], set()).add(st_ids[i])

    def label(i):
        s = st_ids[i]
        nm = st_name[s] or s
        return f"{nm} ({s})" if len(name_ids.get(st_name[s], ())) > 1 else nm

    ranked = sorted(real, key=lambda i: (-st_total[i], len(st_ids[i]), st_ids[i]))
    active = [i for i in ranked if st_total[i] > 0]
    n_active = len(active)
    real_total = float(sum(st_total[i] for i in active))
    top = active[:TOP_N]
    cum = np.cumsum([st_total[i] for i in active]) / real_total if real_total else np.array([])
    half_n = int(np.searchsorted(cum, 0.5) + 1) if len(cum) else 0
    curve_x, curve_y = [], []
    for p in CURVE_POINTS:
        if p < n_active:
            curve_x.append(fmt.int_he(p))
            curve_y.append(round(float(cum[p - 1]) * 100, 1))
    if n_active:
        curve_x.append(fmt.int_he(n_active))
        curve_y.append(100.0)

    buckets = []
    for lo, hi, lab in BUCKETS:
        sel = [i for i in active if st_total[i] >= lo and (hi is None or st_total[i] < hi)]
        buckets.append({"label": lab, "count": len(sel),
                        "total": float(sum(st_total[i] for i in sel))})
    small = buckets[0]

    # morning vs evening peak, among the busiest stations
    am_w = [w for w, x in enumerate(wins) if "שיא" in x["name"] and x["start"] < 12]
    pm_w = [w for w, x in enumerate(wins) if "שיא" in x["name"] and 12 <= x["start"] < 24]
    skew = []
    if am_w and pm_w:
        for i in active[:SKEW_POOL]:
            a = float(st_win[i, am_w].sum())
            p = float(st_win[i, pm_w].sum())
            if a + p > 0:
                skew.append((a / (a + p), i))
        skew.sort(key=lambda t: (t[0], len(st_ids[t[1]]), st_ids[t[1]]))
        if len(skew) > 2 * SKEW_SIDE:
            skew = skew[:SKEW_SIDE] + skew[-SKEW_SIDE:]
    peak_w = [w for w, x in enumerate(wins) if "שיא" in x["name"]]
    peak_share = float(win_tot[peak_w].sum()) / grand if peak_w and grand else None

    # ---- period text ---------------------------------------------------------------
    if d0.year == d1.year:
        if d0.month == d1.month:
            period = f"{fmt.MONTHS_HE[d0.month - 1]} {d0.year}"
        else:
            period = f"{fmt.MONTHS_HE[d0.month - 1]}-{fmt.MONTHS_HE[d1.month - 1]} {d1.year}"
    else:
        period = f"{fmt.month_he(d0)} עד {fmt.month_he(d1)}"
    weekday_mask = dow <= 4
    weekday_avg = float(daily[weekday_mask].mean()) if weekday_mask.any() else 0.0

    # ---- KPIs -------------------------------------------------------------------------
    kpis = {
        "total": {"value": round(grand), "display": _mil(grand), "tone": "brand"},
        "weekday": {"value": round(weekday_avg), "display": _mil(weekday_avg, 2), "tone": "brand"},
        "stations": {"value": n_active, "display": fmt.int_he(n_active), "tone": "brand"},
        "half": {"value": half_n, "display": fmt.int_he(half_n), "tone": "info"},
    }
    labels = {
        "total_kpi": f"תיקופים, {period} (מיליון)",
        "weekday_kpi": "תיקופים ביום חול ממוצע, ראשון עד חמישי (מיליון)",
        "stations_kpi": "תחנות עם תיקופים בתקופה",
        "half_kpi": "תחנות שמרכזות מחצית מהתיקופים",
    }
    mom = None
    if len(full_months) >= 2:
        a, b = full_months[-2], full_months[-1]
        mom = b["per_day"] / a["per_day"] - 1 if a["per_day"] else None
        if mom is not None:
            tone = "ok" if mom >= 0.03 else "danger" if mom <= -0.10 else "warn" if mom <= -0.03 else "brand"
            kpis["mom"] = {"value": round(mom * 100, 1), "display": fmt.signed_pct(mom), "tone": tone}
            labels["mom_kpi"] = (f"שינוי בממוצע היומי, {fmt.MONTHS_HE[b['m'] - 1]} "
                                 f"לעומת {fmt.MONTHS_HE[a['m'] - 1]}")
    if peak_share is not None:
        kpis["peak"] = {"value": round(peak_share * 100, 1), "display": fmt.pct(peak_share), "tone": "brand"}
        labels["peak_kpi"] = "שיעור התיקופים בשעות השיא"

    # ---- insights ------------------------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # weekday rhythm
    if (dow == 6).any() and weekday_avg:
        sat, fri = dow_avg[6], dow_avg[5]
        add("week", (f"ביום חול נרשמים בממוצע {fmt.int_he(weekday_avg)} תיקופים. ביום שישי "
                     f"הממוצע יורד ל-{fmt.int_he(fri)} ({fmt.pct(fri / weekday_avg)} מיום חול), "
                     f"ובשבת ל-{fmt.int_he(sat)} בלבד ({fmt.pct(sat / weekday_avg)})."))

    # weakest full month vs the median full month
    if len(full_months) >= 4:
        med = float(np.median([mo["per_day"] for mo in full_months]))
        weak = min(full_months, key=lambda mo: (mo["per_day"], mo["y"], mo["m"]))
        if med and weak["per_day"] < 0.8 * med:
            add("weak_month", (f"{weak['name']} בולט בחולשתו: {fmt.int_he(weak['per_day'])} תיקופים "
                               f"ביום בממוצע, {fmt.pct(1 - weak['per_day'] / med)} מתחת לחציון "
                               f"החודשים המלאים ({fmt.int_he(med)})."))

    # latest full month vs the one before
    if mom is not None:
        a, b = full_months[-2], full_months[-1]
        if abs(mom) < 0.03:
            verb = "דומה לזה של"
        elif mom > 0:
            verb = f"גבוה ב-{fmt.pct(mom)} מזה של"
        else:
            verb = f"נמוך ב-{fmt.pct(-mom)} מזה של"
        add("mom", (f"הממוצע היומי ב{b['name']}, {fmt.int_he(b['per_day'])} תיקופים, "
                    f"{verb} {a['name']} ({fmt.int_he(a['per_day'])})."))
    if months and months[-1]["partial"]:
        lm = months[-1]
        add("partial", (f"{lm['name']} מופיע עד כה עם {_plural(lm['days'], 'יום אחד', 'ימים')} בלבד, "
                        f"ולכן אינו נכלל בהשוואות בין חודשים."))

    # busiest / quietest days (Sun-Thu)
    if weekday_mask.sum() >= 5:
        idx = np.nonzero(weekday_mask)[0]
        hi = int(idx[np.argmax(daily[idx])])
        lo = int(idx[np.argmin(daily[idx])])
        add("days", (f"יום החול העמוס בתקופה היה {fmt.d_he(dates[hi])} (יום {WEEKDAYS_HE[dow[hi]]}) "
                     f"עם {fmt.int_he(daily[hi])} תיקופים. יום החול השקט ביותר היה "
                     f"{fmt.d_he(dates[lo])} (יום {WEEKDAYS_HE[dow[lo]]}) עם {fmt.int_he(daily[lo])} בלבד."))

    # leading station
    if top and real_total:
        t0 = top[0]
        add("top", (f"התחנה העמוסה ביותר היא {label(t0)} עם {_mil(st_total[t0], 2)} מיליון תיקופים "
                    f"({fmt.pct(st_total[t0] / real_total)} מכלל התיקופים המשויכים לתחנה). "
                    f"{fmt.int_he(len(top))} התחנות המובילות מרכזות "
                    f"{fmt.pct(sum(st_total[i] for i in top) / real_total)}."))

    # concentration and the long tail
    if n_active >= 100 and half_n:
        add("conc", (f"התיקופים מרוכזים: {fmt.int_he(half_n)} תחנות ({fmt.pct(half_n / n_active)} "
                     f"מהתחנות) אחראיות למחצית מהם, ואילו {fmt.int_he(small['count'])} תחנות "
                     f"({fmt.pct(small['count'] / n_active)}) רשמו פחות ממאה תיקופים בכל התקופה."))

    # time windows: biggest total vs highest hourly rate
    rated = [(win_tot[w] / wins[w]["hours"], w) for w in range(n_w) if wins[w]["hours"]]
    if rated and grand:
        big = int(np.argmax(win_tot))
        rate_v, rate_w = max(rated, key=lambda t: (t[0], -t[1]))
        txt = (f"חלון {wins[big]['name']} ({wins[big]['range']}) מרכז את מירב התיקופים, "
               f"{fmt.pct(win_tot[big] / grand)} מהכלל.")
        if rate_w != big:
            txt += (f" בחישוב לשעה, דווקא חלון {wins[rate_w]['name']} ({wins[rate_w]['range']}) עמוס יותר: "
                    f"{fmt.int_he(rate_v / n_days)} תיקופים לשעה ביום ממוצע, לעומת "
                    f"{fmt.int_he(win_tot[big] / wins[big]['hours'] / n_days)}.")
        add("windows", txt)

    # commuter skew
    if len(skew) >= 4:
        lo_s, lo_i = skew[0]
        hi_s, hi_i = skew[-1]
        if hi_s >= 0.6 and lo_s <= 0.4:
            add("skew", (f"בקרב {fmt.int_he(min(SKEW_POOL, n_active))} התחנות העמוסות, ב{label(hi_i)} "
                         f"{fmt.pct(hi_s)} מתיקופי השיא נרשמים בבוקר (תחנת יציאה לעבודה), "
                         f"ואילו ב{label(lo_i)} רק {fmt.pct(lo_s)}: רוב תיקופי השיא בה נרשמים בערב (תחנת יעד)."))


    # ---- charts ----------------------------------------------------------------------------
    win_short = [w["name"] for w in wins]
    charts = {
        "daily": {
            "x": [x.isoformat() for x in dates],
            "y": [int(round(v)) for v in daily],
            "roll": roll,
        },
        "monthly": {
            "x": [mo["label"] for mo in months],
            "total": [round(mo["total"] / 1e6, 2) for mo in months],
            "per_day": [int(round(mo["per_day"])) for mo in months],
            "partial": [mo["partial"] for mo in months],
        },
        "dow": {"x": WEEKDAYS_HE, "y": [int(round(v)) for v in dow_avg]},
        "windows": {
            "x": [w["name"] for w in wins],
            "range": [w["range"] for w in wins],
            "total": [round(float(v) / 1e6, 2) for v in win_tot],
            "per_hour": [int(round(float(win_tot[k]) / wins[k]["hours"] / n_days)) if wins[k]["hours"] else None
                         for k in range(n_w)],
        },
        "heat": {"x": win_short, "y": WEEKDAYS_HE, "cells": heat,
                 "max": max([c[2] for c in heat] or [1])},
        "top": {"x": [label(i) for i in top][::-1],
                "y": [round(float(st_total[i]) / 1e6, 3) for i in top][::-1]},
        "skew": {"x": [label(i) for _, i in skew],
                 "y": [round(s * 100, 1) for s, _ in skew]},
        "buckets": {"x": [b["label"] for b in buckets], "y": [b["count"] for b in buckets]},
        "curve": {"x": curve_x, "y": curve_y},
        "mix": {
            "x": [mo["label"] for mo in months],
            "series": [{"name": wins[w]["name"],
                        "data": [round(mo["mix"][w] / mo["total"] * 100, 1) if mo["total"] else 0
                                 for mo in months]} for w in range(n_w)],
        },
    }

    # ---- tables -------------------------------------------------------------------------------
    tables = {
        "monthly": [[mo["label"], _mil(mo["total"], 2), fmt.int_he(mo["per_day"]),
                     fmt.int_he(mo["stations"])] for mo in months],
        "dow": [[WEEKDAYS_HE[k], fmt.int_he(dow_avg[k]), fmt.int_he((dow == k).sum())] for k in range(7)],
        "windows": [[w["label"], _mil(win_tot[k], 2), fmt.pct(win_tot[k] / grand) if grand else "",
                     fmt.int_he(win_tot[k] / w["hours"] / n_days) if w["hours"] else ""]
                    for k, w in enumerate(wins)],
        "heat": [[WEEKDAYS_HE[k]] + [fmt.int_he(v) for v in heat_rows[k]] for k in range(7)],
        "top": [[fmt.int_he(r + 1), label(i), st_ids[i], fmt.int_he(st_total[i]),
                 fmt.pct(st_total[i] / real_total)] for r, i in enumerate(top)],
        "skew": [[label(i), fmt.pct(s), fmt.int_he(st_total[i])] for s, i in skew],
        "buckets": [[b["label"], fmt.int_he(b["count"]),
                     fmt.pct(b["total"] / real_total) if real_total else ""] for b in buckets],
        "curve": [[x, fmt.pct_of(y)] for x, y in zip(curve_x, curve_y)],
        "mix": [[mo["label"]] + [fmt.pct(v / mo["total"]) if mo["total"] else "" for v in mo["mix"]]
                for mo in months],
        "win_cols": win_short,
    }

    # ---- ledes / aria ----------------------------------------------------------------------------
    pk = max(range(len(months)), key=lambda k: (months[k]["per_day"], -k)) if months else 0
    lo_day = int(np.argmin(daily))
    hi_day = int(np.argmax(daily))
    top_dow = max(range(5), key=lambda k: (dow_avg[k], -k))
    heat_max = max(((v, k, w) for k, row in enumerate(heat_rows) for w, v in enumerate(row)),
                   key=lambda t: (t[0], -t[1], -t[2]))
    sat_ratio = dow_avg[6] / weekday_avg if weekday_avg else 1.0
    if sat_ratio < 0.3:
        sat_txt = f"התחבורה הציבורית כמעט שובתת ({fmt.pct(sat_ratio, 0)} מיום חול)"
        sat_short = ", ובשבתות הקו צונח"
    else:
        sat_txt = f"הממוצע הוא {fmt.pct(sat_ratio, 0)} מיום חול"
        sat_short = ""
    undef_txt = (f" {_mil(undef_total, 2)} מיליון תיקופים ({fmt.pct(undef_total / grand)}) רשומים תחת "
                 f"\"לא מוגדר\" ואינם נכללים." if undef_total and grand else "")
    labels.update({
        "period": period,
        "lookup_fields": "שם התחנה, מספר התחנה, חלון השעות, שנה וחודש",
        "daily_lede": (f"סך התיקופים בכל יום, {period}, עם ממוצע נע של שבעה ימים. ימי חול נעים סביב "
                       f"{fmt.int_he(weekday_avg)}{sat_short}. היום העמוס ביותר: "
                       f"{fmt.d_he(dates[hi_day])}, עם {fmt.int_he(daily[hi_day])} תיקופים."),
        "daily_aria": (f"גרף קו: תיקופים יומיים, {period}. שיא של {fmt.int_he(daily[hi_day])} "
                       f"ב-{dates[hi_day].isoformat()}, שפל של {fmt.int_he(daily[lo_day])} "
                       f"ב-{dates[lo_day].isoformat()}."),
        "monthly_lede": (f"סך התיקופים בכל חודש (עמודות, מיליונים) והממוצע ליום (קו), שמנטרל את אורך החודש. "
                         f"הממוצע היומי הגבוה ביותר: {months[pk]['name']}, {fmt.int_he(months[pk]['per_day'])} "
                         f"תיקופים ביום." if months else ""),
        "monthly_aria": (f"גרף עמודות וקו: תיקופים לפי חודש, {period}. הממוצע היומי הגבוה ביותר "
                         f"ב{months[pk]['name']}." if months else ""),
        "dow_lede": (f"ממוצע התיקופים ביום לפי יום בשבוע. יום {WEEKDAYS_HE[top_dow]} מוביל מעט "
                     f"({fmt.int_he(dow_avg[top_dow])}), שישי יורד לכ-{fmt.pct(dow_avg[5] / weekday_avg if weekday_avg else 0, 0)} "
                     f"מיום חול, ובשבת {sat_txt}."),
        "dow_aria": (f"גרף עמודות: ממוצע תיקופים ביום לפי יום בשבוע. יום חול כ-{fmt.int_he(weekday_avg)}, "
                     f"שבת {fmt.int_he(dow_avg[6])}."),
        "windows_lede": ("סך התיקופים בכל חלון שעות (עמודות, מיליונים) וממוצע התיקופים לשעה ביום (קו). "
                         "החלונות שונים באורכם, ולכן הקו הוא ההשוואה ההוגנת בין שעות השיא לשעות השפל. "
                         "השעות קבועות ואינן משתנות בעונות או בחגים."),
        "windows_aria": (f"גרף עמודות וקו: תיקופים לפי חלון שעות. החלון הגדול ביותר: "
                         f"{wins[int(np.argmax(win_tot))]['name']}."),
        "heat_lede": (f"ממוצע התיקופים ביום (באלפים) לכל צירוף של יום בשבוע וחלון שעות. התא העמוס ביותר: "
                      f"יום {WEEKDAYS_HE[heat_max[1]]}, {wins[heat_max[2]]['name']}, כ-{fmt.int_he(heat_max[0])} "
                      f"תיקופים ביום."),
        "heat_aria": (f"מפת חום: ממוצע תיקופים לפי יום בשבוע וחלון שעות. השיא ביום {WEEKDAYS_HE[heat_max[1]]} "
                      f"ב{wins[heat_max[2]]['name']}."),
        "top_lede": (f"{fmt.int_he(len(top))} התחנות שרשמו הכי הרבה תיקופים ב{period}. תחנה ששמה משותף לכמה "
                     f"תחנות מוצגת עם מספר התחנה.{undef_txt}" if top else ""),
        "top_aria": (f"גרף עמודות אופקי: {fmt.int_he(len(top))} התחנות העמוסות. בראש: {label(top[0])}, "
                     f"{_mil(st_total[top[0]], 2)} מיליון תיקופים." if top else ""),
        "skew_lede": (f"מתוך {fmt.int_he(min(SKEW_POOL, n_active))} התחנות העמוסות: השיעור מתיקופי שעות השיא "
                      "שנרשם בשיא הבוקר. מעל מחצית: תחנה שממנה יוצאים לעבודה וללימודים. מתחת: יעד שממנו "
                      f"חוזרים בערב. מוצגות {fmt.int_he(min(SKEW_SIDE, len(skew)))} התחנות בכל קצה." if skew else ""),
        "skew_aria": (f"גרף עמודות אופקי: שיעור תיקופי שיא הבוקר מתוך תיקופי השיא, בתחנות העמוסות. "
                      f"הגבוה: {label(skew[-1][1])}, {fmt.pct(skew[-1][0])}." if skew else ""),
        "buckets_lede": (f"כמה תחנות רשמו כל היקף של תיקופים ב{period}. רוב התחנות קטנות מאוד: "
                         f"{fmt.int_he(small['count'])} מהן רשמו פחות ממאה תיקופים, ויחד הן "
                         f"{fmt.pct(small['total'] / real_total if real_total else 0, 2)} מהתיקופים."),
        "buckets_aria": (f"גרף עמודות: מספר התחנות לפי היקף התיקופים בתקופה. "
                         f"{fmt.int_he(small['count'])} תחנות רשמו פחות ממאה."),
        "curve_lede": (f"השיעור המצטבר מהתיקופים שמרכזות התחנות העמוסות ביותר, לפי מספר התחנות. "
                       f"{fmt.int_he(half_n)} תחנות מגיעות למחצית."),
        "curve_aria": (f"גרף קו: שיעור מצטבר של תיקופים לפי מספר התחנות העמוסות. "
                       f"{fmt.int_he(half_n)} תחנות מרכזות מחצית מהתיקופים."),
        "mix_lede": "חלוקת התיקופים בכל חודש בין חלונות השעות (באחוזים). שינוי בתמהיל מעיד על שינוי בדפוסי הנסיעה.",
        "mix_aria": "גרף עמודות מוערמות: חלוקת התיקופים לפי חלון שעות בכל חודש, באחוזים.",
    })

    summary = (f"תיקופי נסיעה בתחבורה הציבורית לפי תחנה, יום וחלון שעות: {_mil(grand)} מיליון תיקופים "
               f"ב-{fmt.int_he(n_active)} תחנות, {period}.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{d0.isoformat()}/{d1.isoformat()}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"skew": len(skew) >= 4, "mix": len(months) >= 2, "multi_month": len(months) >= 2},
    }
