"""תיקופי מסלקה בתחבורה ציבורית: recipe compute.

One row per (operator, cluster, line, direction, hour, month) with the day of
the month spread across columns D1..D31. The input is the newest yearly file
(`pick: "latest"`), so the page follows the current calendar year.
"""

from __future__ import annotations

import calendar
import datetime as dt
import re

import numpy as np
import pandas as pd

DAY_COLS = [f"D{i}" for i in range(1, 32)]
MONTHS_HE = [
    "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]
# Sunday-first (Israeli week). Python weekday(): Mon=0 .. Sun=6.
DOW_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]

MODE_RAIL = "רכבת ישראל"
MODE_LRT = "רכבת קלה"
MODE_BUS = "אוטובוסים ושירותים אחרים"
MODE_ORDER = [MODE_BUS, MODE_RAIL, MODE_LRT]
LRT_RE = re.compile(r"רכבת קלה|^קו (אדום|סגול|ירוק)")

TOP_OPERATORS = 12
TOP_CLUSTERS = 15
TOP_LINES = 15
LOW_DAY_FRAC = 0.6       # a weekday below 60% of the median weekday is "weak"
LOW_STREAK_MIN = 5       # a run of >=5 weak weekdays is reported
TREND_STABLE = 0.03      # +-3% month over month reads as stable
SHARP_DROP = 0.10        # a month-over-month fall of 10%+ is shown as danger
TRIM_FRAC = 0.01        # edge days under 1% of the median day = not reported yet


def _num(s: pd.Series) -> np.ndarray:
    v = pd.to_numeric(s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
    return v.fillna(0).to_numpy(dtype="float64", copy=True)


def _m(v: float, digits: int = 1) -> str:
    return f"{v / 1e6:,.{digits}f}"


def _pct(x: float, digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%"


def _signed_pct(x: float) -> str:
    s = f"{abs(x) * 100:.1f}%"
    return ("+" if x >= 0 else "−") + s


def _dow(d: dt.date) -> int:
    return (d.weekday() + 1) % 7  # Sunday=0


def _date_he(d: dt.date) -> str:
    return f"{d.day}.{d.month}.{d.year}"


def _date_long(d: dt.date) -> str:
    return f"{d.day} ב{MONTHS_HE[d.month - 1]} {d.year}"


def _mode(op: str, cl: str) -> str:
    if op.strip() == "רכבת ישראל":
        return MODE_RAIL
    if LRT_RE.search(cl.strip()):
        return MODE_LRT
    return MODE_BUS


def compute(frames):
    df = frames["main"]
    n_rows = int(len(df))

    year = pd.to_numeric(df["year_key"], errors="coerce")
    month = pd.to_numeric(df["month_key"], errors="coerce")
    hour = pd.to_numeric(df["hour_a"], errors="coerce")
    ok = year.between(2000, 2100) & month.between(1, 12) & hour.between(0, 23)

    vals = np.zeros((n_rows, 31), dtype="float64")
    for i, c in enumerate(DAY_COLS):
        col = _num(df[c])
        np.maximum(col, 0, out=col)
        vals[:, i] = col
    okm = ok.to_numpy()
    vals[~okm] = 0
    row_tot = vals.sum(axis=1)

    keys = pd.DataFrame({
        "y": year.fillna(0).astype("int64").to_numpy(),
        "mo": month.fillna(0).astype("int64").to_numpy(),
        "h": hour.fillna(0).astype("int64").to_numpy(),
        "op": df["operator_nm"].astype(str).str.strip().to_numpy(),
        "cl": df["cluster_nm"].astype(str).str.strip().to_numpy(),
        "ln": df["OperatorLineId"].astype(str).str.strip().to_numpy(),
        "tot": row_tot,
    })[okm].reset_index(drop=True)
    vals = vals[okm]
    keys.loc[keys["op"] == "", "op"] = "לא ידוע"
    keys.loc[keys["cl"] == "", "cl"] = "לא מוגדר"

    # ── per (date, hour) matrix ──────────────────────────────────────────
    ym_h = keys[["y", "mo", "h"]].copy()
    vf = pd.DataFrame(vals, columns=list(range(1, 32)))
    g = pd.concat([ym_h, vf], axis=1).groupby(["y", "mo", "h"], sort=True).sum()
    del vf
    long = g.stack()
    long.index.names = ["y", "mo", "h", "d"]
    long = long.reset_index(name="v")
    valid = [
        d <= calendar.monthrange(int(y), int(mo))[1]
        for y, mo, d in zip(long["y"], long["mo"], long["d"])
    ]
    long = long[np.array(valid, dtype=bool)]
    long["date"] = [dt.date(int(y), int(mo), int(d)) for y, mo, d in zip(long["y"], long["mo"], long["d"])]

    daily = long.groupby("date", sort=True)["v"].sum()
    nz = daily[daily > 0]
    if nz.empty:
        raise ValueError("no validations in the data")
    # Days at either end of the span with almost nothing recorded (under
    # TRIM_FRAC of the median day) are days not reported yet, not real quiet
    # days: the file is cut mid-day. They are left out of the daily views.
    floor = TRIM_FRAC * float(nz.median())
    sub = nz[nz >= floor]
    first_date, last_date = sub.index.min(), sub.index.max()
    trimmed_days = int(((nz.index < first_date) | (nz.index > last_date)).sum())
    daily = daily[(daily.index >= first_date) & (daily.index <= last_date)]
    # fill calendar gaps inside the span with 0
    span = [first_date + dt.timedelta(days=i) for i in range((last_date - first_date).days + 1)]
    daily = daily.reindex(span, fill_value=0.0)
    long = long[(long["date"] >= first_date) & (long["date"] <= last_date)]

    total = float(daily.sum())
    years = sorted({d.year for d in span})
    yr_label = str(years[-1]) if len(years) == 1 else f"{years[0]}-{years[-1]}"
    dows = np.array([_dow(d) for d in span])
    dvals = daily.to_numpy()
    weekday_mask = dows <= 4
    wk_vals = dvals[weekday_mask]
    med_wk = float(np.median(wk_vals)) if wk_vals.size else 0.0
    avg_wk = float(wk_vals.mean()) if wk_vals.size else 0.0

    # partial latest month
    last_month_days = calendar.monthrange(last_date.year, last_date.month)[1]
    partial = last_date.day < last_month_days

    # ── months ───────────────────────────────────────────────────────────
    mkeys = sorted({(d.year, d.month) for d in span})
    m_total, m_wkavg, m_labels, m_days = [], [], [], []
    for (y, mo) in mkeys:
        sel = np.array([(d.year == y and d.month == mo) for d in span])
        m_total.append(float(dvals[sel].sum()))
        wsel = sel & weekday_mask
        # median weekday: robust to a few holidays and to a partial month
        m_wkavg.append(float(np.median(dvals[wsel])) if wsel.any() else 0.0)
        m_labels.append(f"{MONTHS_HE[mo - 1]} {y}" if len(years) > 1 else MONTHS_HE[mo - 1])
        m_days.append(int(sel.sum()))
    last_partial_label = m_labels[-1] if partial else ""

    # ── day of week ─────────────────────────────────────────────────────
    dow_avg, dow_n = [], []
    for k in range(7):
        sel = dows == k
        dow_n.append(int(sel.sum()))
        dow_avg.append(float(dvals[sel].mean()) if sel.any() else 0.0)

    # ── hour profiles by day type ───────────────────────────────────────
    date_dow = {d: _dow(d) for d in span}
    long["dow"] = long["date"].map(date_dow)
    n_by_type = {"wk": int(weekday_mask.sum()), "fri": int((dows == 5).sum()), "sat": int((dows == 6).sum())}
    hp = {}
    for t, cond in (("wk", long["dow"] <= 4), ("fri", long["dow"] == 5), ("sat", long["dow"] == 6)):
        s = long[cond].groupby("h")["v"].sum().reindex(range(24), fill_value=0.0)
        n = max(n_by_type[t], 1)
        hp[t] = [round(float(x) / n) for x in s.to_numpy()]
    heat = long.groupby(["dow", "h"])["v"].sum()
    heat_cells = []
    heat_max = 0
    for k in range(7):
        n = max(dow_n[k], 1)
        for h in range(24):
            v = round(float(heat.get((k, h), 0.0)) / n)
            heat_max = max(heat_max, v)
            heat_cells.append([h, k, v])
    hours_lbl = [f"{h:02d}:00" for h in range(24)]
    wk_hours = hp["wk"]
    peak_h = int(np.argmax(wk_hours))
    am_h = int(np.argmax(wk_hours[:11]))
    pm_h = 11 + int(np.argmax(wk_hours[11:]))

    # ── operators / clusters / modes / lines ─────────────────────────────
    op_tot = keys.groupby("op")["tot"].sum()
    op_sorted = sorted(op_tot.items(), key=lambda kv: (-kv[1], kv[0]))
    op_sorted = [(k, float(v)) for k, v in op_sorted if v > 0]
    n_ops = len(op_sorted)
    top_ops = op_sorted[:TOP_OPERATORS]
    other_ops = sum(v for _, v in op_sorted[TOP_OPERATORS:])
    op_names = [k for k, _ in top_ops] + (["מפעילים אחרים"] if other_ops > 0 else [])
    op_vals = [round(v) for _, v in top_ops] + ([round(other_ops)] if other_ops > 0 else [])
    op_share = [v / total if total else 0 for v in op_vals]

    cl_tot = keys[keys["cl"] != "לא מוגדר"].groupby("cl")["tot"].sum()
    cl_sorted = [(k, float(v)) for k, v in sorted(cl_tot.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0]
    unassigned_cl = float(keys.loc[keys["cl"] == "לא מוגדר", "tot"].sum())
    top_cl = cl_sorted[:TOP_CLUSTERS]
    n_cl = len(cl_sorted)

    keys["mode"] = [_mode(o, c) for o, c in zip(keys["op"], keys["cl"])]
    mode_tot = keys.groupby("mode")["tot"].sum()
    mode_names = [m for m in MODE_ORDER if float(mode_tot.get(m, 0)) > 0]
    mode_vals = [round(float(mode_tot.get(m, 0))) for m in mode_names]
    mm = keys.groupby(["mode", "y", "mo"])["tot"].sum()
    mode_series = []
    for m in mode_names:
        mode_series.append({"name": m, "data": [round(float(mm.get((m, y, mo), 0.0))) for (y, mo) in mkeys]})
    mode_share_tbl = []
    for i, (y, mo) in enumerate(mkeys):
        row_t = sum(s["data"][i] for s in mode_series)
        mode_share_tbl.append({
            "label": m_labels[i],
            "vals": [s["data"][i] for s in mode_series],
            "shares": [(s["data"][i] / row_t if row_t else 0.0) for s in mode_series],
        })
    rail_share = sum(v for m, v in zip(mode_names, mode_vals) if m != MODE_BUS) / total if total else 0.0

    bus = keys[(keys["mode"] == MODE_BUS) & (~keys["ln"].isin(["", "-1", "0"]))]
    ln_tot = bus.groupby(["op", "cl", "ln"])["tot"].sum()
    ln_sorted = sorted(ln_tot.items(), key=lambda kv: (-kv[1], kv[0]))
    top_lines = []
    for (o, c, ln), v in ln_sorted[:TOP_LINES]:
        if v <= 0:
            continue
        top_lines.append({"line": ln, "op": o, "cl": c, "v": round(float(v)),
                          "label": f"קו {ln} ({o}, {c})", "short": f"קו {ln}, {c}"})
    n_lines = int((ln_tot > 0).sum())

    # ── busiest / weakest days, weak streak ──────────────────────────────
    best_i = int(np.argmax(dvals))
    best_day, best_v = span[best_i], float(dvals[best_i])
    weak = [(i, d) for i, d in enumerate(span) if dows[i] <= 4 and med_wk > 0 and dvals[i] < LOW_DAY_FRAC * med_wk]
    # longest run of consecutive weak weekdays (Fri/Sat between them don't break it)
    streak, best_streak = [], []
    wk_seq = [i for i in range(len(span)) if dows[i] <= 4]
    weak_set = {i for i, _ in weak}
    for i in wk_seq:
        if i in weak_set:
            streak.append(i)
            if len(streak) > len(best_streak):
                best_streak = list(streak)
        else:
            streak = []

    # ── daily chart (marks weak weekdays) ────────────────────────────────
    daily_x = [_date_he(d) for d in span]
    daily_y = [round(float(v)) for v in dvals]
    daily_flag = [1 if i in weak_set else 0 for i in range(len(span))]
    zoom_start = max(0, len(span) - 120)

    # ── insights ─────────────────────────────────────────────────────────
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # trend between the last two months (weekday average, robust to partial months)
    def trend():
        if len(mkeys) < 2 or m_wkavg[-1] <= 0 or m_wkavg[-2] <= 0:
            return None
        ch = m_wkavg[-1] / m_wkavg[-2] - 1
        tail = " (החודש האחרון חלקי, ההשוואה לפי חציון יום חול)" if partial else ""
        if abs(ch) < TREND_STABLE:
            return (f"חציון יום חול ב{m_labels[-1]} עמד על {_m(m_wkavg[-1], 2)} מיליון תיקופים, "
                    f"יציב לעומת {m_labels[-2]} ({_m(m_wkavg[-2], 2)} מיליון){tail}.")
        word = "עלייה" if ch > 0 else "ירידה"
        return (f"חציון יום חול ב{m_labels[-1]}: {_m(m_wkavg[-1], 2)} מיליון תיקופים, {word} של "
                f"{abs(ch) * 100:.1f}% לעומת {m_labels[-2]} ({_m(m_wkavg[-2], 2)} מיליון){tail}.")
    add("trend", trend())

    def leader():
        if n_ops < 2:
            return None
        s1 = op_sorted[0][1] / total
        s3 = sum(v for _, v in op_sorted[:3]) / total
        names3 = ", ".join(k for k, _ in op_sorted[:3])
        return (f"{op_sorted[0][0]} הוא המפעיל הגדול: {_pct(s1)} מהתיקופים ({_m(op_sorted[0][1])} מיליון). "
                f"שלושת הגדולים ({names3}) מחזיקים יחד {_pct(s3)} מתוך {n_ops:,} מפעילים.")
    add("leader", leader())

    def peaks():
        if sum(wk_hours) <= 0:
            return None
        share_peak = wk_hours[peak_h] / sum(wk_hours)
        return (f"ביום חול ממוצע יש שני שיאים: בוקר ב-{hours_lbl[am_h]} ({wk_hours[am_h] / 1e3:,.0f} אלף תיקופים) "
                f"ואחר הצהריים ב-{hours_lbl[pm_h]} ({wk_hours[pm_h] / 1e3:,.0f} אלף). "
                f"השעה העמוסה ביותר, {hours_lbl[peak_h]}, מרכזת {_pct(share_peak)} מתיקופי היום.")
    add("peaks", peaks())

    def weekend():
        if dow_n[6] == 0 or avg_wk <= 0:
            return None
        r_sat = dow_avg[6] / avg_wk
        r_fri = dow_avg[5] / avg_wk if dow_n[5] else None
        fri = f", ובשישי {_pct(r_fri, 0)}" if r_fri is not None else ""
        return (f"בשבת נרשמים בממוצע {dow_avg[6] / 1e3:,.0f} אלף תיקופים ביום, "
                f"{_pct(r_sat)} בלבד מיום חול ממוצע ({_m(avg_wk, 2)} מיליון){fri}.")
    add("weekend", weekend())

    def rail():
        if total <= 0 or len(mode_names) < 2:
            return None
        parts = [f"{m}: {_pct(v / total)}" for m, v in zip(mode_names, mode_vals) if m != MODE_BUS]
        if not parts:
            return None
        if len(parts) == 1:
            m = next(m for m in mode_names if m != MODE_BUS)
            return (f"{m}: {_pct(rail_share)} מהתיקופים. השאר באוטובוסים ובשירותים אחרים.")
        return (f"הרכבת והרכבת הקלה יחד אחראיות ל-{_pct(rail_share)} מהתיקופים ({'; '.join(parts)}), "
                f"והשאר באוטובוסים ובשירותים אחרים.")
    add("rail", rail())

    def streak_ins():
        if len(best_streak) < LOW_STREAK_MIN or med_wk <= 0:
            return None
        a, b = span[best_streak[0]], span[best_streak[-1]]
        avg_s = float(np.mean([dvals[i] for i in best_streak]))
        return (f"בין {_date_he(a)} ל-{_date_he(b)} נרשמו {len(best_streak):,} ימי חול רצופים מתחת ל-"
                f"{LOW_DAY_FRAC * 100:.0f}% מהחציון של יום חול, עם ממוצע של {_m(avg_s, 2)} מיליון תיקופים ביום "
                f"לעומת חציון של {_m(med_wk, 2)} מיליון. זו התקופה החלשה ביותר בנתונים.")
    add("streak", streak_ins())

    def busiest():
        return (f"היום העמוס ביותר: יום {DOW_HE[_dow(best_day)]}, {_date_he(best_day)}, "
                f"עם {_m(best_v, 2)} מיליון תיקופים.")
    add("busiest", busiest())

    def top_line():
        if not top_lines:
            return None
        t = top_lines[0]
        return (f"קו האוטובוס העמוס ביותר: {t['label']}, עם {_m(t['v'], 2)} מיליון תיקופים מתחילת התקופה "
                f"(מתוך {n_lines:,} קווים פעילים).")
    add("top_line", top_line())

    # ── KPIs ─────────────────────────────────────────────────────────────
    kpis = {
        "total": {"value": round(total), "display": _m(total), "tone": "brand"},
        "avg_weekday": {"value": round(avg_wk), "display": _m(avg_wk, 2), "tone": "brand"},
        "peak_hour": {"value": peak_h, "display": hours_lbl[peak_h], "tone": "info"},
        "rail_share": {"value": round(rail_share, 4), "display": _pct(rail_share), "tone": "brand"},
    }
    if len(mkeys) >= 2 and m_wkavg[-2] > 0:
        ch = m_wkavg[-1] / m_wkavg[-2] - 1
        if abs(ch) < TREND_STABLE:
            tone = "brand"
        elif ch > 0:
            tone = "ok"
        else:
            tone = "danger" if ch <= -SHARP_DROP else "warn"
        kpis["mom"] = {"value": round(ch, 4), "display": _signed_pct(ch), "tone": tone}

    # ── labels ───────────────────────────────────────────────────────────
    period = f"{_date_he(first_date)} עד {_date_he(last_date)}"
    labels = {
        "period": period,
        "year": yr_label,
        "total_kpi": f"תיקופים ב-{yr_label} (מיליונים)",
        "avg_weekday_kpi": "ממוצע ליום חול, א'-ה' (מיליונים)",
        "peak_hour_kpi": "שעת השיא ביום חול",
        "rail_share_kpi": "חלק הרכבת והרכבת הקלה",
        "mom_kpi": (f"שינוי בחציון יום חול, {m_labels[-1]} מול {m_labels[-2]}" if "mom" in kpis else ""),
        "partial_note": (
            (f"החודש האחרון ({last_partial_label}) חלקי: הנתונים מגיעים עד {_date_he(last_date)}." if partial else "")
            + (f" {trimmed_days:,} ימים בקצה התקופה עם רישום חלקי בלבד (פחות מ-{TRIM_FRAC * 100:.0f}% מיום רגיל) "
               f"אינם מוצגים בגרפים לפי יום ושעה." if trimmed_days else "")
        ).strip(),
        "lede": (f"הנתונים מכסים את התקופה {period}: {_m(total)} מיליון תיקופים, "
                 f"{n_ops:,} מפעילים ו-{n_lines:,} קווי אוטובוס פעילים."),
        "daily_lede": (f"ממוצע של {_m(avg_wk, 2)} מיליון תיקופים ביום חול (חציון {_m(med_wk, 2)} מיליון). "
                       + (f"ימי חול שירדו מתחת ל-{LOW_DAY_FRAC * 100:.0f}% מהחציון מסומנים באדום "
                          f"({len(weak):,} ימים בתקופה), למשל חגים או ימי שיבוש."
                          if weak else
                          f"אף יום חול בתקופה לא ירד מתחת ל-{LOW_DAY_FRAC * 100:.0f}% מהחציון.")),
        "daily_aria": (f"גרף קו של תיקופים יומיים מ-{_date_he(first_date)} עד {_date_he(last_date)}. "
                       f"השיא ב-{_date_he(best_day)} עם {_m(best_v, 2)} מיליון."),
        "monthly_lede": (f"סך התיקופים בכל חודש (עמודות) וחציון יום חול (קו), שכמעט אינו מושפע מחגים בודדים או מחודש חלקי."
                         + (f" {m_labels[-1]} חלקי." if partial else "")),
        "monthly_aria": (f"גרף עמודות של תיקופים חודשיים ב-{yr_label}, עם קו חציון יום חול. "
                         f"החודש העמוס: {m_labels[int(np.argmax(m_total))]}."),
        "dow_lede": (f"ממוצע תיקופים לפי יום בשבוע. יום {DOW_HE[int(np.argmax(dow_avg))]} הוא העמוס ביותר "
                     f"({_m(max(dow_avg), 2)} מיליון בממוצע), ובשבת {dow_avg[6] / 1e3:,.0f} אלף."),
        "dow_aria": f"גרף עמודות של ממוצע תיקופים יומי לפי יום בשבוע. העמוס: יום {DOW_HE[int(np.argmax(dow_avg))]}.",
        "hourly_lede": (f"ממוצע תיקופים בכל שעה, בנפרד ליום חול, לשישי ולשבת. ביום חול השיא ב-{hours_lbl[peak_h]}, "
                        f"שיא הבוקר ב-{hours_lbl[am_h]}."),
        "hourly_aria": f"גרף קווים של תיקופים לפי שעה ביום חול, שישי ושבת. שיא יום החול ב-{hours_lbl[peak_h]}.",
        "heat_lede": "עוצמת השימוש בכל שעה ובכל יום בשבוע (ממוצע ליום). כהה יותר פירושו יותר תיקופים.",
        "heat_aria": f"מפת חום של ממוצע תיקופים לפי שעה ויום בשבוע. השיא ביום חול ב-{hours_lbl[peak_h]}.",
        "ops_lede": (f"{n_ops:,} מפעילים. {op_sorted[0][0]} מוביל עם {_pct(op_sorted[0][1] / total)} מהתיקופים"
                     + (f"; מעבר ל-{TOP_OPERATORS} הגדולים, השאר מקובצים כ\"מפעילים אחרים\"." if other_ops > 0 else ".")),
        "ops_aria": f"גרף עמודות אופקי של תיקופים לפי מפעיל. המוביל: {op_sorted[0][0]}.",
        "mode_lede": (f"חלוקת התיקופים בכל חודש בין אוטובוסים, רכבת ישראל ורכבת קלה. "
                      f"המסילות אחראיות ל-{_pct(rail_share)} מהתיקופים בתקופה."),
        "mode_aria": f"גרף עמודות מוערמות של תיקופים חודשיים לפי סוג שירות. חלק המסילות: {_pct(rail_share)}.",
        "cl_lede": ((f"{TOP_CLUSTERS if n_cl > TOP_CLUSTERS else n_cl} האשכולות הגדולים מתוך {n_cl:,} (אשכול הוא אזור מכרז של קווים). "
                     + (f"{_m(unassigned_cl, 2)} מיליון תיקופים אינם משויכים לאשכול ואינם בגרף." if unassigned_cl > 0 else ""))
                    if top_cl else ""),
        "cl_aria": (f"גרף עמודות אופקי של תיקופים לפי אשכול. המוביל: {top_cl[0][0]}." if top_cl else ""),
        "lines_lede": ((f"{len(top_lines):,} קווי האוטובוס העמוסים ביותר, שני הכיוונים יחד. "
                        f"הרכבות וקווים ללא מספר קו אינם נכללים.") if top_lines else ""),
        "lines_aria": (f"גרף עמודות אופקי של קווי האוטובוס העמוסים. המוביל: {top_lines[0]['label']}." if top_lines else ""),
    }

    summary = (f"תיקופי רב-קו בתחבורה הציבורית לפי יום, שעה, מפעיל וקו ({period}): "
               f"{_m(total)} מיליון תיקופים, {_m(avg_wk, 2)} מיליון ביום חול ממוצע.")
    if len(summary) > 155:
        summary = f"תיקופי רב-קו בתחבורה הציבורית לפי יום, שעה, מפעיל וקו: {_m(total)} מיליון תיקופים ב-{yr_label}."

    charts = {
        "daily": {"x": daily_x, "y": daily_y, "flag": daily_flag, "zoom_start": zoom_start},
        "monthly": {"x": m_labels, "total": [round(v) for v in m_total], "wkavg": [round(v) for v in m_wkavg],
                    "days": m_days, "partial": bool(partial)},
        "dow": {"x": DOW_HE, "y": [round(v) for v in dow_avg], "n": dow_n},
        "hourly": {"x": hours_lbl, "wk": hp["wk"], "fri": hp["fri"], "sat": hp["sat"]},
        "heat": {"hours": hours_lbl, "days": DOW_HE, "cells": heat_cells, "max": heat_max},
        "operators": {"names": op_names, "vals": op_vals, "shares": op_share},
        "modes": {"x": m_labels, "series": mode_series, "names": mode_names, "totals": mode_vals,
                  "table": mode_share_tbl},
        "clusters": {"names": [k for k, _ in top_cl], "vals": [round(v) for _, v in top_cl],
                     "shares": [v / total if total else 0 for _, v in top_cl]},
        "lines": {"names": [t["short"] for t in top_lines], "labels": [t["label"] for t in top_lines],
                  "ops": [t["op"] for t in top_lines], "vals": [t["v"] for t in top_lines],
                  "line": [t["line"] for t in top_lines], "cl": [t["cl"] for t in top_lines]},
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first_date.isoformat()}/{last_date.isoformat()}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "labels": labels,
        "flags": {"clusters": bool(top_cl), "lines": bool(top_lines), "mom": "mom" in kpis,
                  "partial": bool(partial), "modes": len(mode_names) >= 2},
    }
