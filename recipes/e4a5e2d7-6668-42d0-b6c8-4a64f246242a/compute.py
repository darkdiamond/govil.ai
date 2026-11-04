"""תכנון וביצוע אוטובוסים: monthly planned vs performed bus trips per line.

One row = one line (OfficeLineId) of one operator in one cluster in one
month: rishui (licensed/planned trips), eibizua (not performed), hakdama
(early), eihurim (late), takin (on time), loberishui (trips run outside the
licence). rishui ≈ eibizua + hakdama + eihurim + takin, so every share is a
share of rishui. A new yearly file is added every year and the current
year's file is re-uploaded monthly (with a ~3 month lag), so the "current"
view is the latest 12 months present in the data, never the calendar.
"""
import calendar

import pandas as pd
from govlib import fmt, frame

NUMS = ["rishui", "eibizua", "hakdama", "eihurim", "takin", "loberishui"]
STATUS = [
    ("takin", "בזמן"),
    ("eihurim", "באיחור"),
    ("hakdama", "בהקדמה"),
    ("eibizua", "לא בוצעו"),
]
TREND_PP = 0.5          # on-time change (percentage points) that counts as a move
MISS_PP = 0.3          # missed-share change that counts as a move
OP_STATUS_MIN = 0.01    # operator share of window trips to enter the status chart
OP_GAP_MIN = 0.02       # operator share to enter the best/worst comparison
CLUSTER_MIN_SHARE = 0.003
CLUSTER_MIN_TRIPS = 20000
LINE_MIN_TRIPS = 100
DIP_RATIO = 0.7         # a month below 70% of the median month is a dip
LINE_BANDS = [
    (1.0, 1.0001, "100%"),
    (0.98, 1.0, "98% עד 99.9%"),
    (0.95, 0.98, "95% עד 98%"),
    (0.90, 0.95, "90% עד 95%"),
    (0.80, 0.90, "80% עד 90%"),
    (-1.0, 0.80, "פחות מ-80%"),
]


def _ym_label(ym: int) -> str:
    return f"{fmt.MONTHS_HE[ym % 12]} {ym // 12}"


def _ym_axis(ym: int) -> str:
    return f"{ym // 12}-{ym % 12 + 1:02d}"


def _p1(v: float) -> float:
    return round(float(v) * 100, 2)


def _shares(s) -> dict:
    r = float(s["rishui"])
    if r <= 0:
        return {"ontime": 0.0, "late": 0.0, "early": 0.0, "miss": 0.0, "lob": 0.0}
    return {
        "ontime": float(s["takin"]) / r,
        "late": float(s["eihurim"]) / r,
        "early": float(s["hakdama"]) / r,
        "miss": float(s["eibizua"]) / r,
        "lob": float(s["loberishui"]) / r,
    }


def _latest_name(df: pd.DataFrame, key: str, name: str) -> dict:
    """Latest-month spelling per id (ties: most rows, then name)."""
    g = df.groupby([key, name]).agg(last=("ym", "max"), n=("ym", "size")).reset_index()
    g = g.sort_values([key, "last", "n", name], ascending=[True, False, False, True], kind="stable")
    return {k: v for k, v in zip(g.drop_duplicates(key)[key], g.drop_duplicates(key)[name])}


def _axis_min(ontime_pcts) -> int:
    """Lower bound for a stacked on-time axis: 5 below the lowest on-time
    share, rounded down to a multiple of 5 (never below 0)."""
    vals = [v for v in ontime_pcts if v is not None]
    if not vals:
        return 0
    return max(0, int((min(vals) - 5) // 5 * 5))


def _pp(v: float) -> str:
    return fmt.num_he(abs(v) * 100, 1)


def compute(frames):
    df = frames["trips"].copy()
    for c in NUMS:
        df[c] = frame.num(df[c]).fillna(0.0)
    df["y"] = pd.to_numeric(df["trip_year"], errors="coerce")
    df["m"] = pd.to_numeric(df["trip_month"], errors="coerce")
    df = df[df["y"].between(2000, 2100) & df["m"].between(1, 12)].copy()
    df["y"] = df["y"].astype(int)
    df["m"] = df["m"].astype(int)
    df["ym"] = df["y"] * 12 + df["m"] - 1
    for c in ["OperatorId", "ClusterId", "OfficeLineId", "OperatorLineId"]:
        df[c] = frame.clean_series(df[c])
    df["operator_nm"] = frame.clean_series(df["operator_nm"])
    df["cluster_nm"] = frame.clean_series(df["cluster_nm"])
    df = df[(df["OperatorId"] != "") & (df["OfficeLineId"] != "")]

    op_name = _latest_name(df, "OperatorId", "operator_nm")
    cl_name = _latest_name(df, "ClusterId", "cluster_nm")

    # ---------- monthly ----------
    mon = df.groupby("ym")[NUMS].sum().sort_index()
    lines_m = df[df["rishui"] > 0].groupby("ym")["OfficeLineId"].nunique()
    yms = [int(v) for v in mon.index]
    first_ym, last_ym = yms[0], yms[-1]
    monthly = {
        "x": [_ym_axis(v) for v in yms],
        "label": [_ym_label(v) for v in yms],
        "rishui": [int(v) for v in mon["rishui"]],
        "lines": [int(lines_m.get(v, 0)) for v in yms],
        "ontime": [], "late": [], "early": [], "miss": [],
    }
    for v in yms:
        s = _shares(mon.loc[v])
        for k in ["ontime", "late", "early", "miss"]:
            monthly[k].append(_p1(s[k]))

    # ---------- windows ----------
    win_lo = last_ym - 11
    w = df[df["ym"] >= win_lo]
    win_months = int(w["ym"].nunique())
    wsum = w[NUMS].sum()
    wsh = _shares(wsum)
    prev = df[(df["ym"] >= last_ym - 23) & (df["ym"] < win_lo)]
    has_prev = prev["ym"].nunique() == 12 and win_months == 12
    psh = _shares(prev[NUMS].sum()) if has_prev else None
    win_label = f"{_ym_label(win_lo)} עד {_ym_label(last_ym)}"
    win_days = sum(calendar.monthrange(v // 12, v % 12 + 1)[1] for v in sorted(w["ym"].unique()))

    # ---------- yearly ----------
    yr = df.groupby("y")[NUMS].sum().sort_index()
    yr_months = df.groupby("y")["ym"].nunique()
    years = [int(v) for v in yr.index]
    yearly = {"x": [str(v) for v in years], "series": [], "lob": []}
    for col, name in STATUS:
        yearly["series"].append({"name": name, "data": [_p1(float(yr.loc[y, col]) / float(yr.loc[y, "rishui"])) if yr.loc[y, "rishui"] > 0 else 0 for y in years]})
    year_rows, lob_rows = [], []
    full_years = []
    for y in years:
        s = _shares(yr.loc[y])
        nm = int(yr_months[y])
        label = str(y) if nm == 12 else f"{y} ({nm} חודשים)"
        if nm == 12:
            full_years.append((y, s))
        yearly["lob"].append(_p1(s["lob"]))
        year_rows.append([label, fmt.int_he(yr.loc[y, "rishui"]), fmt.num_he(s["ontime"] * 100), fmt.num_he(s["late"] * 100), fmt.num_he(s["early"] * 100), fmt.num_he(s["miss"] * 100)])
        lob_rows.append([label, fmt.int_he(yr.loc[y, "loberishui"]), fmt.num_he(s["lob"] * 100, 2)])
    yearly["labels"] = [r[0] for r in year_rows]
    yearly["axis_min"] = _axis_min(yearly["series"][0]["data"])

    # ---------- heatmap year x month ----------
    cells = []
    for i, y in enumerate(years):
        for m in range(12):
            v = y * 12 + m
            if v in mon.index and mon.loc[v, "rishui"] > 0:
                cells.append([m, i, _p1(float(mon.loc[v, "takin"]) / float(mon.loc[v, "rishui"]))])
    heat_vals = [c[2] for c in cells]
    heat = {"x": fmt.MONTHS_SHORT_HE, "y": [str(y) for y in years], "cells": cells,
            "min": float(min(heat_vals)) if heat_vals else 0.0, "max": float(max(heat_vals)) if heat_vals else 100.0}

    # ---------- operators (window) ----------
    ops = w.groupby("OperatorId")[NUMS].sum()
    ops["name"] = [op_name[k] for k in ops.index]
    ops = ops[ops["rishui"] > 0].sort_values(["rishui", "name"], ascending=[False, True], kind="stable")
    total_w = float(wsum["rishui"])
    vol_series = pd.Series(ops["rishui"].values, index=ops["name"].values)
    vol_labels, vol_vals = frame.top_other(vol_series, 12)
    op_volume = {"x": vol_labels, "y": [int(v) for v in vol_vals],
                 "share": [_p1(float(v) / total_w) for v in vol_vals]}
    op_rows_vol = [[lbl, fmt.int_he(v), fmt.num_he(float(v) / total_w * 100)] for lbl, v in zip(vol_labels, vol_vals)]

    big = ops[ops["rishui"] / total_w >= OP_STATUS_MIN].copy()
    big["ontime"] = big["takin"] / big["rishui"]
    big = big.sort_values(["ontime", "name"], ascending=[False, True], kind="stable").head(16)
    op_status = {"x": [str(n) for n in big["name"]], "series": []}
    for col, name in STATUS:
        op_status["series"].append({"name": name, "data": [_p1(float(r[col]) / float(r["rishui"])) for _, r in big.iterrows()]})
    op_status["axis_min"] = _axis_min(op_status["series"][0]["data"])
    op_status_rows = []
    for _, r in big.iterrows():
        s = _shares(r)
        op_status_rows.append([r["name"], fmt.int_he(r["rishui"]), fmt.num_he(s["ontime"] * 100), fmt.num_he(s["late"] * 100), fmt.num_he(s["early"] * 100), fmt.num_he(s["miss"] * 100)])

    # ---------- operator trend by year (top 6 in window) ----------
    top6 = list(ops.index[:6])
    oy = df[df["OperatorId"].isin(top6)].groupby(["OperatorId", "y"])[NUMS].sum()
    op_trend = {"x": [str(y) for y in years], "series": []}
    trend_years = years[-6:]
    op_trend_rows = []
    for k in top6:
        data = []
        for y in years:
            if (k, y) in oy.index and oy.loc[(k, y), "rishui"] >= 1000:
                data.append(_p1(float(oy.loc[(k, y), "takin"]) / float(oy.loc[(k, y), "rishui"])))
            else:
                data.append(None)
        op_trend["series"].append({"name": op_name[k], "data": data})
        op_trend_rows.append([op_name[k]] + ["" if data[years.index(y)] is None else fmt.num_he(data[years.index(y)]) for y in trend_years])
    op_trend_cols = ["מפעיל"] + [str(y) for y in trend_years]

    # ---------- clusters (window) ----------
    cl = w[w["ClusterId"] != "-1"].groupby("ClusterId")[NUMS].sum()
    cl_min = max(CLUSTER_MIN_TRIPS, total_w * CLUSTER_MIN_SHARE)
    cl = cl[cl["rishui"] >= cl_min].copy()
    cl["miss_r"] = cl["eibizua"] / cl["rishui"]
    cl["name"] = [cl_name[k] for k in cl.index]
    dom = w.groupby(["ClusterId", "OperatorId"])["rishui"].sum().reset_index()
    dom = dom.sort_values(["ClusterId", "rishui", "OperatorId"], ascending=[True, False, True], kind="stable").drop_duplicates("ClusterId")
    dom_op = {c: op_name[o] for c, o in zip(dom["ClusterId"], dom["OperatorId"])}
    cl = cl.sort_values(["miss_r", "name"], ascending=[False, True], kind="stable")
    cl_top = cl.head(12)
    clusters = {"x": [f"{n} ({dom_op[k]})" for k, n in zip(cl_top.index, cl_top["name"])],
                "miss": [_p1(v) for v in cl_top["miss_r"]],
                "late": [_p1(float(r["eihurim"]) / float(r["rishui"])) for _, r in cl_top.iterrows()],
                "avg": _p1(wsh["miss"])}
    cluster_rows = [[n, dom_op[k], fmt.int_he(r["rishui"]), fmt.int_he(r["eibizua"]), fmt.num_he(r["miss_r"] * 100), fmt.num_he(float(r["eihurim"]) / float(r["rishui"]) * 100)]
                    for k, n, (_, r) in zip(cl_top.index, cl_top["name"], cl_top.iterrows())]
    n_clusters_ranked = len(cl)

    # ---------- lines (window) ----------
    ln = w.groupby(["OperatorId", "OfficeLineId"])[NUMS].sum()
    ln = ln[ln["rishui"] >= LINE_MIN_TRIPS].copy()
    # takin can exceed rishui by a few trips (rishui only ≈ the status sum),
    # so cap at 100% to keep every line inside a band.
    ln["ontime"] = (ln["takin"] / ln["rishui"]).clip(upper=1.0)
    band_counts = []
    for lo, hi, lbl in LINE_BANDS:
        band_counts.append((lbl, int(((ln["ontime"] >= lo) & (ln["ontime"] < hi)).sum())))
    n_lines = len(ln)
    line_dist = {"x": [b[0] for b in band_counts], "y": [b[1] for b in band_counts],
                 "share": [_p1(b[1] / n_lines) if n_lines else 0 for b in band_counts]}
    line_dist_rows = [[b[0], fmt.int_he(b[1]), fmt.num_he(b[1] / n_lines * 100) if n_lines else "0"] for b in band_counts]

    # line labels: latest non-empty line number and cluster per (operator, office line)
    lw = w[["OperatorId", "OfficeLineId", "OperatorLineId", "ClusterId", "ym", "rishui"]].copy()
    lw = lw.sort_values(["OperatorId", "OfficeLineId", "ym", "rishui", "OperatorLineId", "ClusterId"],
                        ascending=[True, True, False, False, False, True], kind="stable")
    num_lw = lw[lw["OperatorLineId"] != ""].drop_duplicates(["OperatorId", "OfficeLineId"])
    line_no = {(a, b): c for a, b, c in zip(num_lw["OperatorId"], num_lw["OfficeLineId"], num_lw["OperatorLineId"])}
    cl_lw = lw.drop_duplicates(["OperatorId", "OfficeLineId"])
    line_cl = {(a, b): c for a, b, c in zip(cl_lw["OperatorId"], cl_lw["OfficeLineId"], cl_lw["ClusterId"])}
    worst = ln.reset_index().sort_values(["eibizua", "rishui", "OperatorId", "OfficeLineId"],
                                         ascending=[False, False, True, True], kind="stable").head(10)
    worst_rows = []
    for _, r in worst.iterrows():
        key = (r["OperatorId"], r["OfficeLineId"])
        worst_rows.append([line_no.get(key, "") or "ללא", op_name[r["OperatorId"]], cl_name.get(line_cl.get(key, ""), ""),
                           r["OfficeLineId"], fmt.int_he(r["rishui"]), fmt.int_he(r["eibizua"]),
                           fmt.num_he(float(r["eibizua"]) / float(r["rishui"]) * 100)])
    lines_last = int(lines_m.get(last_ym, 0))

    # ---------- insights ----------
    insights = []
    if has_prev:
        d = wsh["ontime"] - psh["ontime"]
        if d >= TREND_PP / 100:
            trend = f"שיפור של {_pp(d)} נקודות אחוז"
        elif d <= -TREND_PP / 100:
            trend = f"ירידה של {_pp(d)} נקודות אחוז"
        else:
            trend = "כמעט ללא שינוי"
        insights.append({"id": "trend", "text_he": f"בשנים-עשר החודשים האחרונים בנתונים ({win_label}) יצאו בזמן {fmt.pct(wsh['ontime'])} מהנסיעות המתוכננות, לעומת {fmt.pct(psh['ontime'])} בשנה שקדמה להם: {trend}."})
    per_day = float(wsum["eibizua"]) / win_days if win_days else 0
    if wsum["eibizua"] > 0:
        insights.append({"id": "missed", "text_he": f"{fmt.int_he(wsum['eibizua'])} נסיעות מתוכננות לא בוצעו כלל ב-{win_months} החודשים האחרונים ({fmt.pct(wsh['miss'])} מהמתוכנן), כ-{fmt.int_he(per_day)} נסיעות ביום בממוצע."})
    if len(full_years) >= 3:
        best = min(full_years, key=lambda t: (-t[1]["ontime"], t[0]))
        worst_y = min(full_years, key=lambda t: (t[1]["ontime"], t[0]))
        if best[1]["ontime"] - worst_y[1]["ontime"] >= 0.005:
            insights.append({"id": "years", "text_he": f"מבין השנים המלאות, שיעור העמידה בזמנים היה הגבוה ביותר ב-{best[0]} ({fmt.pct(best[1]['ontime'])}) והנמוך ביותר ב-{worst_y[0]} ({fmt.pct(worst_y[1]['ontime'])})."})
    if len(yms) >= 12:
        med = float(mon["rishui"].median())
        # The latest month can be an incomplete upload, so it is never a dip.
        cand = mon.loc[mon.index != last_ym, "rishui"]
        low_ym = int(cand.sort_values(kind="stable").index[0])
        low_v = float(mon.loc[low_ym, "rishui"])
        if med > 0 and low_v < DIP_RATIO * med:
            insights.append({"id": "dip", "text_he": f"החודש עם הכי מעט נסיעות מתוכננות היה {_ym_label(low_ym)}: {fmt.int_he(low_v)} נסיעות, {fmt.pct(1 - low_v / med, 0)} פחות מהחודש החציוני ({fmt.int_he(med)})."})
    if len(ops):
        lead = ops.iloc[0]
        lead_sh = float(lead["rishui"]) / total_w
        if lead_sh >= 0.15:
            insights.append({"id": "leader", "text_he": f"{lead['name']} הוא המפעיל הגדול ביותר: {fmt.pct(lead_sh)} מהנסיעות המתוכננות ב-{win_months} החודשים האחרונים, מתוך {len(ops)} מפעילים."})
    gap = ops[ops["rishui"] / total_w >= OP_GAP_MIN].copy()
    if len(gap) >= 3:
        gap["ontime"] = gap["takin"] / gap["rishui"]
        g = gap.sort_values(["ontime", "name"], ascending=[False, True], kind="stable")
        hi, lo = g.iloc[0], g.iloc[-1]
        if hi["ontime"] - lo["ontime"] >= 0.02:
            insights.append({"id": "op_gap", "text_he": f"בין המפעילים הגדולים (לפחות {fmt.pct(OP_GAP_MIN, 0)} מהנסיעות), {hi['name']} הוביל בעמידה בזמנים עם {fmt.pct(hi['ontime'])}, ו{lo['name']} היה האחרון עם {fmt.pct(lo['ontime'])}."})
    if len(cl) and wsh["miss"] > 0:
        top_c = cl.iloc[0]
        ratio = float(top_c["miss_r"]) / wsh["miss"]
        if ratio >= 2:
            insights.append({"id": "cluster", "text_he": f"באשכול {top_c['name']} ({dom_op[cl.index[0]]}) לא בוצעו {fmt.pct(top_c['miss_r'])} מהנסיעות, פי {fmt.num_he(ratio, 1)} מהממוצע הארצי ({fmt.pct(wsh['miss'])})."})
    if wsh["early"] > 0 and wsh["late"] >= 2 * wsh["early"]:
        insights.append({"id": "late_early", "text_he": f"איחור נפוץ הרבה יותר מהקדמה: {fmt.pct(wsh['late'])} מהנסיעות יצאו באיחור לעומת {fmt.pct(wsh['early'], 2)} שיצאו מוקדם מהמתוכנן."})
    if n_lines >= 20:
        perfect = band_counts[0][1] + band_counts[1][1]
        low = band_counts[-1][1]
        if low == 0:
            tail = "ואף קו לא ירד מתחת ל-80% נסיעות בזמן."
        elif low == 1:
            tail = "וקו אחד בלבד יצא בזמן בפחות מ-80% מהנסיעות."
        else:
            tail = f"ו-{fmt.int_he(low)} קווים יצאו בזמן בפחות מ-80% מהנסיעות."
        insights.append({"id": "lines", "text_he": f"מתוך {fmt.int_he(n_lines)} קווים עם {LINE_MIN_TRIPS} נסיעות מתוכננות לפחות, {fmt.int_he(perfect)} ({fmt.pct(perfect / n_lines, 0)}) יצאו בזמן ב-98% מהנסיעות או יותר, {tail}"})

    # ---------- KPIs ----------
    def tone_up(d, th):
        if d is None:
            return "brand"
        return "ok" if d >= th else ("danger" if d <= -th else "brand")

    d_on = (wsh["ontime"] - psh["ontime"]) if has_prev else None
    d_miss = (psh["miss"] - wsh["miss"]) if has_prev else None
    kpis = {
        "planned": {"value": int(wsum["rishui"]), "display": fmt.int_he(wsum["rishui"]), "tone": "brand"},
        "ontime": {"value": _p1(wsh["ontime"]), "display": fmt.pct(wsh["ontime"]), "tone": tone_up(d_on, TREND_PP / 100)},
        "miss": {"value": _p1(wsh["miss"]), "display": fmt.pct(wsh["miss"]), "tone": tone_up(d_miss, MISS_PP / 100)},
        "late": {"value": _p1(wsh["late"]), "display": fmt.pct(wsh["late"]), "tone": "brand"},
        "lines": {"value": lines_last, "display": fmt.int_he(lines_last), "tone": "brand"},
        "operators": {"value": len(ops), "display": str(len(ops)), "tone": "brand"},
        "span": {"value": first_ym // 12, "display": f"{first_ym // 12}–{last_ym // 12}", "tone": "info"},
    }
    if has_prev:
        sign = "+" if d_on > 0.00005 else ("−" if d_on < -0.00005 else "")
        kpis["ontime_delta"] = {"value": round(d_on * 100, 2), "display": f"{sign}{_pp(d_on)}", "tone": tone_up(d_on, TREND_PP / 100)}

    last_year = years[-1]
    partial = int(yr_months[last_year]) < 12
    lede = (f"המאגר של משרד התחבורה מתעד בכל חודש, לכל קו אוטובוס, כמה נסיעות אושרו ברישוי וכמה מהן יצאו בזמן, באיחור, בהקדמה או לא בוצעו כלל. "
            f"הנתונים משתרעים מ{_ym_label(first_ym)} עד {_ym_label(last_ym)}: {fmt.int_he(df['rishui'].sum())} נסיעות מתוכננות של {len(op_name)} מפעילים. "
            f"בשנים-עשר החודשים האחרונים יצאו בזמן {fmt.pct(wsh['ontime'])} מהנסיעות ולא בוצעו {fmt.pct(wsh['miss'])}.")
    if partial:
        lede += f" נתוני {last_year} חלקיים ({int(yr_months[last_year])} חודשים); המאגר מתעדכן בפיגור של כמה חודשים."

    summary = (f"ביצוע נסיעות האוטובוסים בתחבורה הציבורית לפי מפעיל, אשכול וקו, מ{_ym_label(first_ym)} עד {_ym_label(last_ym)}: "
               f"בשנה האחרונה יצאו בזמן {fmt.pct(wsh['ontime'])} מ-{fmt.int_he(wsum['rishui'])} הנסיעות המתוכננות ולא בוצעו {fmt.pct(wsh['miss'])}.")
    desc = (f"בדיקת ביצוע קווי אוטובוס: נסיעות בזמן, באיחור ושלא בוצעו לפי מפעיל, אשכול וקו. בשנה האחרונה {fmt.pct(wsh['ontime'])} בזמן, {fmt.pct(wsh['miss'])} לא בוצעו.")

    lead_name = str(ops.iloc[0]["name"]) if len(ops) else ""
    labels = {
        "lede": lede,
        "win": win_label,
        "kpi_planned": f"נסיעות מתוכננות ברישוי ({win_label})",
        "kpi_ontime": "שיעור הנסיעות שיצאו בזמן, שנה אחרונה",
        "kpi_miss": "שיעור הנסיעות שלא בוצעו, שנה אחרונה",
        "kpi_late": "שיעור הנסיעות שיצאו באיחור, שנה אחרונה",
        "kpi_lines": f"קווים פעילים ב{_ym_label(last_ym)}",
        "kpi_operators": "מפעילים בשנה האחרונה",
        "kpi_span": "שנות נתונים",
        "kpi_ontime_delta": "שינוי בעמידה בזמנים מול השנה הקודמת (נקודות אחוז)",
        "monthly_note": f"שיעור הנסיעות שיצאו בזמן ושיעור הנסיעות שלא בוצעו, מתוך הנסיעות המתוכננות בכל חודש. בחודש האחרון ({_ym_label(last_ym)}): {fmt.pct_of(monthly['ontime'][-1])} בזמן ו-{fmt.pct_of(monthly['miss'][-1])} לא בוצעו.",
        "monthly_aria": f"תרשים קווי חודשי של שיעור הנסיעות בזמן ושלא בוצעו, {_ym_label(first_ym)} עד {_ym_label(last_ym)}; בחודש האחרון {fmt.pct_of(monthly['ontime'][-1])} בזמן",
        "volume_note": f"היקף הנסיעות המתוכננות בכל חודש ומספר הקווים שפעלו בו. בחודש האחרון תוכננו {fmt.int_he(monthly['rishui'][-1])} נסיעות ב-{fmt.int_he(lines_last)} קווים.",
        "volume_aria": f"תרשים עמודות של הנסיעות המתוכננות בכל חודש וקו של מספר הקווים הפעילים; בחודש האחרון {fmt.int_he(monthly['rishui'][-1])} נסיעות",
        "yearly_note": "פילוח הנסיעות המתוכננות בכל שנה לפי אופן הביצוע: בזמן, באיחור, בהקדמה או לא בוצעו. שנה חלקית מסומנת במספר החודשים שבה.",
        "yearly_aria": f"תרשים עמודות מוערמות של אופן ביצוע הנסיעות לפי שנה, {years[0]} עד {years[-1]}",
        "yearly_caption": "אופן ביצוע הנסיעות לפי שנה",
        "heat_note": "שיעור הנסיעות שיצאו בזמן בכל חודש, שנה מול חודש: גוון כהה יותר הוא עמידה טובה יותר בזמנים.",
        "heat_aria": f"מפת חום של שיעור הנסיעות בזמן לפי שנה וחודש, בין {fmt.pct_of(heat['min'])} ל-{fmt.pct_of(heat['max'])}",
        "opvol_note": f"חלקו של כל מפעיל בנסיעות המתוכננות ב-{win_months} החודשים האחרונים ({win_label}). {lead_name} מוביל עם {fmt.pct_of(op_volume['share'][0]) if op_volume['share'] else ''}.",
        "opvol_aria": f"תרשים עמודות אופקי של הנסיעות המתוכננות לפי מפעיל בשנה האחרונה; המוביל {lead_name}",
        "opvol_caption": "נסיעות מתוכננות לפי מפעיל",
        "opstat_note": f"אופן ביצוע הנסיעות אצל כל מפעיל שהפעיל לפחות {fmt.pct(OP_STATUS_MIN, 0)} מהנסיעות בשנה האחרונה, מהעמידה הטובה ביותר בזמנים לפחות טובה.",
        "opstat_aria": f"תרשים עמודות מוערמות של אופן ביצוע הנסיעות לפי מפעיל; הגבוה בעמידה בזמנים {op_status['x'][0] if op_status['x'] else ''}",
        "opstat_caption": "אופן ביצוע הנסיעות לפי מפעיל",
        "optrend_note": "שיעור הנסיעות שיצאו בזמן בכל שנה אצל ששת המפעילים הגדולים בשנה האחרונה. שנה שבה המפעיל כמעט לא פעל מושמטת.",
        "optrend_aria": "תרשים קווי של שיעור הנסיעות בזמן לפי שנה אצל המפעילים הגדולים",
        "optrend_caption": "שיעור הנסיעות בזמן לפי מפעיל ושנה (אחוז)",
        "cluster_note": f"האשכולות (אזורי ההפעלה שבמכרז) עם השיעור הגבוה ביותר של נסיעות שלא בוצעו בשנה האחרונה, מתוך {n_clusters_ranked} אשכולות עם {fmt.int_he(cl_min)} נסיעות מתוכננות לפחות. הקו המקווקו הוא הממוצע הארצי ({fmt.pct(wsh['miss'])}).",
        "cluster_aria": f"תרשים עמודות אופקי של האשכולות עם שיעור אי הביצוע הגבוה ביותר; בראש {clusters['x'][0] if clusters['x'] else ''}",
        "cluster_caption": "אשכולות עם שיעור אי ביצוע גבוה",
        "dist_note": f"התפלגות {fmt.int_he(n_lines)} הקווים שתוכננו בהם {LINE_MIN_TRIPS} נסיעות לפחות בשנה האחרונה, לפי שיעור הנסיעות שיצאו בזמן.",
        "dist_aria": f"תרשים עמודות של מספר הקווים לפי שיעור העמידה בזמנים, מתוך {fmt.int_he(n_lines)} קווים",
        "dist_caption": "קווים לפי שיעור הנסיעות בזמן",
        "lob_note": "נסיעות שהמפעיל ביצע מחוץ לרישוי (לא היו בתכנון המאושר), כשיעור מהנסיעות המתוכננות בכל שנה.",
        "lob_aria": f"תרשים עמודות של שיעור הנסיעות מחוץ לרישוי לפי שנה, {years[0]} עד {years[-1]}",
        "lob_caption": "נסיעות מחוץ לרישוי לפי שנה",
        "worst_note": f"עשרת הקווים עם הכי הרבה נסיעות שלא בוצעו ב-{win_months} החודשים האחרונים ({win_label}). מספר הקו הוא המספר שעל השלט; מק\"ט הקו הוא הקוד במשרד התחבורה.",
        "worst_caption": "הקווים עם הכי הרבה נסיעות שלא בוצעו",
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_ym // 12}/{last_ym // 12}",
            "spatial_coverage": "ישראל",
            "seo": {
                "title": "ביצוע קווי אוטובוס: איחורים ונסיעות שלא בוצעו",
                "description": desc,
                "name": "תכנון וביצוע נסיעות אוטובוסים בתחבורה הציבורית",
                "alternate_names": ["תכנון וביצוע אוטובוסים", "מאגר תכנון וביצוע אוטובוסים", "אי ביצוע נסיעות אוטובוס", "איחורי אוטובוסים לפי מפעיל"],
            },
        },
        "kpis": kpis,
        "charts": {
            "monthly": monthly,
            "yearly": yearly,
            "heat": heat,
            "op_volume": op_volume,
            "op_status": op_status,
            "op_trend": op_trend,
            "clusters": clusters,
            "line_dist": line_dist,
        },
        "tables": {
            "years": year_rows,
            "lob": lob_rows,
            "op_volume": op_rows_vol,
            "op_status": op_status_rows,
            "op_trend": op_trend_rows,
            "op_trend_cols": op_trend_cols,
            "clusters": cluster_rows,
            "line_dist": line_dist_rows,
            "worst": worst_rows,
        },
        "flags": {
            "prev": bool(has_prev),
            "clusters": bool(len(cl_top)),
            "lines": n_lines > 0,
            "op_trend": len(top6) > 0,
        },
        "insights": insights,
        "labels": labels,
    }
