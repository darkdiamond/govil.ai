"""Interior Ministry payments to local authorities: one row per payment line
(request > milestone > payment). Amounts in NIS; the page shows millions /
billions. Everything here is computed from the frame."""
import re

import pandas as pd
from govlib import fmt, frame

MAX_YEARS = 8          # heatmap / pace / budget-year charts keep the latest N years
TOP_PROGRAMS = 10
TOP_DEPTS = 8
TOP_RECIP = 15
STACK_PROGRAMS = 3

C_PAID = "שולם בפועל"
C_REG = "נרשם לתש"
C_PAY_DATE = "ת. התאמה"
C_ELIG = "ת.זכאות"
C_REQ = "מספר בקשה"
C_TOT = "סך מעודכן"
C_WBS = "שנת WBS"
C_WHO = "מגיש הבקשה"
C_PROG = "תאור התקנה"
C_CODE = "תקנה"
C_DEPT = "שם מחלקה"
C_STATUS = "סטאטוס"

TYPE_ORDER = ["עיריות", "מועצות מקומיות", "מועצות אזוריות", "איגודי ערים ואשכולות", "גופים אחרים"]
TYPE_RULES = [
    (re.compile(r"^עירי(?:י)?ת"), "עיריות"),
    (re.compile(r"^(?:מ\.\s*מ\.|מועצה מקומית)"), "מועצות מקומיות"),
    (re.compile(r"^(?:מ\.\s*א\.|מועצה אזורית)"), "מועצות אזוריות"),
    (re.compile(r"^(?:איגוד ערים|א\.\s*ערים)"), "איגודי ערים ואשכולות"),
]

SIZE_BINS = [0, 10_000, 100_000, 1_000_000, 10_000_000, float("inf")]
SIZE_LABELS = ["עד 10 אלף", "10-100 אלף", "100 אלף עד מיליון", "1-10 מיליון", "מעל 10 מיליון"]

LAG_BINS = [-1, 0, 7, 30, 90, 365, float("inf")]
LAG_LABELS = ["באותו יום", "1-7 ימים", "8-30 ימים", "31-90 ימים", "91-365 ימים", "מעל שנה"]


def _type(name: str) -> str:
    for rx, t in TYPE_RULES:
        if rx.match(name):
            return t
    return "גופים אחרים"


def _m(v) -> float:
    """NIS to millions, one decimal."""
    return round(float(v) / 1e6, 1)


def _bn(v) -> str:
    return fmt.num_he(float(v) / 1e9, 2)


def _mn(v) -> str:
    return fmt.int_he(float(v) / 1e6)


def _plural(n, one, many):
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def compute(frames):
    raw = frames["main"]
    df = pd.DataFrame({
        "paid": frame.num(raw[C_PAID]),
        "reg": frame.num(raw[C_REG]),
        "tot": frame.num(raw[C_TOT]),
        "date": pd.to_datetime(raw[C_PAY_DATE].str.slice(0, 10), errors="coerce", format="%Y-%m-%d"),
        "elig": pd.to_datetime(raw[C_ELIG].str.slice(0, 10), errors="coerce", format="%Y-%m-%d"),
        "req": frame.clean_series(raw[C_REQ]),
        "wbs": pd.to_numeric(raw[C_WBS], errors="coerce"),
        "who": frame.clean_series(raw[C_WHO]),
        "prog": frame.clean_series(raw[C_PROG]),
        "code": frame.clean_series(raw[C_CODE]),
        "dept": frame.clean_series(raw[C_DEPT]),
        "status": frame.clean_series(raw[C_STATUS]),
    })
    df.loc[df["prog"] == "", "prog"] = "ללא תיאור"
    df.loc[df["dept"] == "", "dept"] = "ללא מחלקה"

    paid = df[df["paid"].notna() & df["date"].notna()].copy()
    pending = df[df["paid"].isna()]
    if paid.empty:
        raise ValueError("no paid rows")
    paid["year"] = paid["date"].dt.year.astype(int)
    paid["month"] = paid["date"].dt.month.astype(int)
    total = float(paid["paid"].sum())
    n_pay = len(paid)
    first, last = paid["date"].min(), paid["date"].max()

    # ---------- years, partial-year detection ----------
    years_all = sorted(paid["year"].unique().tolist())
    months_by_year = paid.groupby("year")["month"].agg(lambda s: set(s.tolist()))
    full = {y: (1 in months_by_year[y] and 12 in months_by_year[y]) for y in years_all}
    last_year = years_all[-1]
    last_partial = not full[last_year]
    full_years = [y for y in years_all if full[y]]

    def ylabel(y):
        if y == last_year and last_partial:
            return f"{y} (עד {fmt.MONTHS_SHORT_HE[last.month - 1]})"
        if not full[y]:
            return f"{y} (חלקית)"
        return str(y)

    # ---------- programs ----------
    prog_sum = paid.groupby("prog")["paid"].sum().sort_index().sort_values(ascending=False, kind="stable")
    prog_reqs = paid.groupby("prog")["req"].nunique()
    prog_code = (paid.groupby(["prog", "code"]).size().reset_index(name="n")
                 .sort_values(["prog", "n", "code"], ascending=[True, False, True])
                 .drop_duplicates("prog").set_index("prog")["code"])
    p_labels, p_values = frame.top_other(prog_sum, TOP_PROGRAMS)
    programs = {"labels": p_labels, "values": [_m(v) for v in p_values]}
    prog_rows = []
    for lab, v in zip(p_labels, p_values):
        if lab in prog_sum.index:
            prog_rows.append([lab, prog_code.get(lab, ""), _mn(v), fmt.pct(v / total),
                              fmt.int_he(prog_reqs[lab])])
        else:
            rest = prog_sum.index[TOP_PROGRAMS:]
            prog_rows.append([lab, "", _mn(v), fmt.pct(v / total),
                              fmt.int_he(paid[paid["prog"].isin(rest)]["req"].nunique())])

    # ---------- yearly, stacked by top programs ----------
    stack_progs = [p for p in prog_sum.index[:STACK_PROGRAMS]]
    yp = paid.assign(g=paid["prog"].where(paid["prog"].isin(stack_progs), "אחר"))
    piv = yp.pivot_table(index="year", columns="g", values="paid", aggfunc="sum", fill_value=0.0)
    series_names = stack_progs + (["אחר"] if "אחר" in piv.columns else [])
    yearly = {
        "x": [ylabel(y).replace(" (", "\n(") for y in years_all],
        "series": [{"name": s, "data": [_m(piv.at[y, s]) if s in piv.columns else 0.0 for y in years_all]}
                   for s in series_names],
        "totals": [_m(paid.loc[paid["year"] == y, "paid"].sum()) for y in years_all],
    }
    year_tot = paid.groupby("year")["paid"].sum()
    year_cnt = paid.groupby("year").size()
    yearly_rows = [[ylabel(y), _mn(year_tot[y]), fmt.int_he(year_cnt[y]),
                    fmt.pct(piv.at[y, stack_progs[0]] / year_tot[y]) if year_tot[y] else "0.0%"]
                   for y in years_all]

    # ---------- month x year heatmap + cumulative pace ----------
    hy = years_all[-MAX_YEARS:]
    mon = paid[paid["year"].isin(hy)].groupby(["year", "month"])["paid"].sum()
    cells, heat_rows = [], []
    hmax = 0.0
    for mi in range(1, 13):
        row = [fmt.MONTHS_HE[mi - 1]]
        for xi, y in enumerate(hy):
            observed = mi in months_by_year[y]
            v = float(mon.get((y, mi), 0.0))
            if observed:
                cells.append([xi, mi - 1, _m(v)])
                hmax = max(hmax, _m(v))
                row.append(_mn(v))
            else:
                row.append("")
        heat_rows.append(row)
    heat = {"years": [str(y) for y in hy], "months": fmt.MONTHS_SHORT_HE, "cells": cells, "max": hmax}

    pace_series, pace_rows = [], []
    cum = {}
    for y in hy:
        acc, vals = 0.0, []
        for mi in range(1, 13):
            if y == last_year and last_partial and mi > last.month:
                vals.append(None)
                continue
            acc += float(mon.get((y, mi), 0.0))
            vals.append(round(acc / 1e9, 2))
        cum[y] = vals
        pace_series.append({"name": str(y), "data": vals})
    for mi in range(12):
        pace_rows.append([fmt.MONTHS_HE[mi]] + [("" if cum[y][mi] is None else fmt.num_he(cum[y][mi], 2)) for y in hy])
    pace = {"months": fmt.MONTHS_SHORT_HE, "series": pace_series}

    # ---------- departments ----------
    dept_sum = paid.groupby("dept")["paid"].sum().sort_index().sort_values(ascending=False, kind="stable")
    d_labels, d_values = frame.top_other(dept_sum, TOP_DEPTS)
    dept_progs = paid.groupby("dept")["prog"].nunique()
    depts = {"labels": d_labels, "values": [_m(v) for v in d_values]}
    dept_rows = [[lab, _mn(v), fmt.pct(v / total),
                  fmt.int_he(dept_progs[lab]) if lab in dept_progs.index else ""]
                 for lab, v in zip(d_labels, d_values)]

    # ---------- recipients ----------
    who_sum = paid.groupby("who")["paid"].sum().sort_index().sort_values(ascending=False, kind="stable")
    n_who = int(paid.loc[paid["who"] != "", "who"].nunique())  # bodies actually paid
    top_who = who_sum.iloc[:TOP_RECIP]
    who_top_prog = {}
    for w in top_who.index:
        s = paid[paid["who"] == w].groupby("prog")["paid"].sum().sort_index().sort_values(ascending=False, kind="stable")
        who_top_prog[w] = (s.index[0], float(s.iloc[0]))
    recipients = {"labels": list(top_who.index), "values": [_m(v) for v in top_who]}
    recip_rows = [[w, _mn(v), fmt.pct(v / total), who_top_prog[w][0]] for w, v in top_who.items()]
    top_n_share = float(top_who.sum()) / total

    # ---------- recipient types ----------
    paid["type"] = paid["who"].map(_type)
    t_sum = paid.groupby("type")["paid"].sum()
    t_bodies = paid[paid["who"] != ""].groupby("type")["who"].nunique()
    types_present = [t for t in TYPE_ORDER if t in t_sum.index]
    type_lead = max(types_present, key=lambda t: (float(t_sum[t]), -TYPE_ORDER.index(t)))
    types = {"labels": types_present, "values": [_m(t_sum[t]) for t in types_present],
             "bodies": [int(t_bodies.get(t, 0)) for t in types_present]}
    type_rows = []
    for t in types_present:
        b = int(t_bodies.get(t, 0))
        type_rows.append([t, _mn(t_sum[t]), fmt.pct(t_sum[t] / total), fmt.int_he(b),
                          fmt.num_he(t_sum[t] / b / 1e6, 1) if b else ""])

    # ---------- budget (WBS) year: paid same year / later / remaining ----------
    reqs = df[df["req"] != ""].groupby("req").agg(wbs=("wbs", "first"), tot=("tot", "first"),
                                                  status=("status", "first"))
    reqs = reqs[reqs["wbs"].notna()]
    reqs["wbs"] = reqs["wbs"].astype(int)
    pw = paid[paid["wbs"].notna()].copy()
    pw["wbs"] = pw["wbs"].astype(int)
    by = sorted(reqs["wbs"].unique().tolist())[-MAX_YEARS:]
    same, later, remain, bud_rows, approved_l = [], [], [], [], []
    bud_stats = {}
    for w in by:
        appr = float(reqs.loc[reqs["wbs"] == w, "tot"].sum())
        sub = pw[pw["wbs"] == w]
        s_same = float(sub.loc[sub["year"] <= w, "paid"].sum())
        s_late = float(sub.loc[sub["year"] > w, "paid"].sum())
        rem = max(appr - s_same - s_late, 0.0)
        nreq = int((reqs["wbs"] == w).sum())
        same.append(_m(s_same)); later.append(_m(s_late)); remain.append(_m(rem)); approved_l.append(_m(appr))
        bud_stats[w] = {"appr": appr, "same": s_same, "late": s_late, "rem": rem, "n": nreq}
        bud_rows.append([str(w), _mn(appr), _mn(s_same), _mn(s_late), _mn(rem),
                         fmt.int_he(nreq), fmt.num_he(appr / nreq / 1e6, 1) if nreq else ""])
    budget = {"x": [str(w) for w in by], "same": same, "later": later, "remain": remain}

    # ---------- payment size ----------
    sz = pd.cut(paid["paid"], SIZE_BINS, labels=SIZE_LABELS, right=True, include_lowest=True)
    sz_cnt = sz.value_counts().reindex(SIZE_LABELS, fill_value=0)
    sz_sum = paid.groupby(sz, observed=False)["paid"].sum().reindex(SIZE_LABELS, fill_value=0.0)
    sizes = {"labels": SIZE_LABELS,
             "count_share": [round(float(c) / n_pay * 100, 1) for c in sz_cnt],
             "sum_share": [round(float(s) / total * 100, 1) for s in sz_sum]}
    size_rows = [[lab, fmt.int_he(sz_cnt[lab]), fmt.pct(sz_cnt[lab] / n_pay), _mn(sz_sum[lab]),
                  fmt.pct(sz_sum[lab] / total)] for lab in SIZE_LABELS]
    median_pay = float(paid["paid"].median())
    big = paid[paid["paid"] > 10_000_000]
    big1 = paid[paid["paid"] > 1_000_000]
    big1_cnt, big1_sum = len(big1) / n_pay, float(big1["paid"].sum()) / total

    # ---------- lag eligibility -> payment ----------
    lagdf = paid[paid["elig"].notna()].copy()
    lagdf["lag"] = (lagdf["date"] - lagdf["elig"]).dt.days
    lagdf = lagdf[lagdf["lag"] >= 0]
    lag = None
    lag_rows = []
    lag_stats = None
    if len(lagdf) >= 20:
        lb = pd.cut(lagdf["lag"], LAG_BINS, labels=LAG_LABELS, right=True)
        l_cnt = lb.value_counts().reindex(LAG_LABELS, fill_value=0)
        l_sum = lagdf.groupby(lb, observed=False)["paid"].sum().reindex(LAG_LABELS, fill_value=0.0)
        nl, sl = len(lagdf), float(lagdf["paid"].sum())
        lag = {"labels": LAG_LABELS,
               "count_share": [round(float(c) / nl * 100, 1) for c in l_cnt],
               "sum_share": [round(float(s) / sl * 100, 1) for s in l_sum]}
        lag_rows = [[lab, fmt.int_he(l_cnt[lab]), fmt.pct(l_cnt[lab] / nl), fmt.pct(l_sum[lab] / sl)]
                    for lab in LAG_LABELS]
        lag_stats = {"n": nl, "median": float(lagdf["lag"].median()),
                     "week": float((lagdf["lag"] <= 7).mean()),
                     "over90": float((lagdf["lag"] > 90).mean())}

    # ---------- KPIs ----------
    n_req = int(reqs.shape[0])
    pend_sum = float(pending["reg"].sum())
    top_prog_share = float(prog_sum.iloc[0]) / total
    kpis = {
        "total": {"value": round(total / 1e9, 2), "display": _bn(total), "tone": "brand"},
        "payments": {"value": n_pay, "display": fmt.int_he(n_pay), "tone": "brand"},
        "recipients": {"value": n_who, "display": fmt.int_he(n_who), "tone": "brand"},
        "requests": {"value": n_req, "display": fmt.int_he(n_req), "tone": "brand"},
        "top_prog": {"value": round(top_prog_share * 100, 1), "display": fmt.pct(top_prog_share), "tone": "info"},
        "pending": {"value": round(pend_sum / 1e6, 1), "display": fmt.num_he(pend_sum / 1e6, 1),
                    "tone": "warn" if len(pending) else "ok"},
    }

    # ---------- insights ----------
    insights = []

    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    # top recipient concentration
    tw, tv = top_who.index[0], float(top_who.iloc[0])
    if tv / total >= 0.05 and len(top_who) >= 2 and float(top_who.iloc[1]) > 0:
        tp, tpv = who_top_prog[tw]
        add("top_recipient",
            f"ל{tw} הועברו {_mn(tv)} מיליון ש\"ח, {fmt.pct(tv / total)} מכל התשלומים במאגר, "
            f"פי {fmt.num_he(tv / float(top_who.iloc[1]), 1)} מהגוף השני ברשימה ({top_who.index[1]}). "
            f"עיקר הסכום ({fmt.pct(tpv / tv)}) הגיע מתקנת \"{tp}\".")

    # dominant program
    if top_prog_share >= 0.3:
        add("top_program",
            f"תקנת \"{prog_sum.index[0]}\" לבדה אחראית ל-{fmt.pct(top_prog_share)} מהכסף ששולם "
            f"({_bn(prog_sum.iloc[0])} מיליארד ש\"ח), והגיעה ל-{fmt.int_he(paid.loc[paid['prog'] == prog_sum.index[0], 'who'].nunique())} גופים שונים.")

    # full-year change
    if len(full_years) >= 2:
        a, b = full_years[-2], full_years[-1]
        ch = float(year_tot[b]) / float(year_tot[a]) - 1
        if abs(ch) < 0.03:
            add("yoy", f"היקף התשלומים ב-{b} ({_bn(year_tot[b])} מיליארד ש\"ח) היה כמעט זהה לזה של {a} ({fmt.signed_pct(ch)}).")
        else:
            word = "עלה" if ch > 0 else "ירד"
            add("yoy", f"היקף התשלומים {word} מ-{_bn(year_tot[a])} מיליארד ש\"ח ב-{a} "
                       f"ל-{_bn(year_tot[b])} מיליארד ב-{b} ({fmt.signed_pct(ch)}).")

    # year-to-date pace
    if last_partial and (last_year - 1) in months_by_year.index and full.get(last_year - 1):
        prev = last_year - 1
        cut_prev = pd.Timestamp(year=prev, month=last.month, day=min(last.day, 28) if last.month == 2 else last.day)
        ytd = float(year_tot[last_year])
        ytd_prev = float(paid.loc[(paid["year"] == prev) & (paid["date"] <= cut_prev), "paid"].sum())
        if ytd_prev > 0:
            ch = ytd / ytd_prev - 1
            if abs(ch) < 0.03:
                trend = "קצב דומה לתקופה המקבילה"
            else:
                trend = f"{fmt.signed_pct(ch)} לעומת התקופה המקבילה"
            add("ytd", f"מתחילת {last_year} ועד {fmt.d_he(last)} שולמו {_bn(ytd)} מיליארד ש\"ח, "
                       f"{trend} ב-{prev} ({_bn(ytd_prev)} מיליארד).")

    # December spike
    if full_years:
        dec = float(paid.loc[paid["year"].isin(full_years) & (paid["month"] == 12), "paid"].sum())
        fy_tot = float(paid.loc[paid["year"].isin(full_years), "paid"].sum())
        dshare = dec / fy_tot if fy_tot else 0
        if dshare >= 1.5 / 12:
            yrs = f"{full_years[0]}-{full_years[-1]}" if len(full_years) > 1 else str(full_years[0])
            add("december", f"בשנים המלאות ({yrs}) שולמו בחודש דצמבר {fmt.pct(dshare)} מהכסף, "
                            f"פי {fmt.num_he(dshare * 12, 1)} מחודש ממוצע: חלק ניכר מהתשלומים מועבר בסוף שנת התקציב.")

    # carry-over to later years (closed budget years only)
    closed = [w for w in by if w < last_year]
    if closed:
        late = sum(bud_stats[w]["late"] for w in closed)
        allp = sum(bud_stats[w]["same"] + bud_stats[w]["late"] for w in closed)
        if allp and late / allp >= 0.05:
            yrs = f"{closed[0]}-{closed[-1]}" if len(closed) > 1 else str(closed[0])
            add("carry", f"מהכסף ששולם לבקשות משנות התקציב {yrs}, {fmt.pct(late / allp)} ({_bn(late)} מיליארד ש\"ח) "
                         f"הועבר רק אחרי תום שנת התקציב של הבקשה.")

    # fewer, larger requests
    if len(closed) >= 2:
        a, b = closed[0], closed[-1]
        na, nb = bud_stats[a]["n"], bud_stats[b]["n"]
        if na and nb:
            avg_a, avg_b = bud_stats[a]["appr"] / na, bud_stats[b]["appr"] / nb
            if nb / na - 1 <= -0.2 and avg_b / avg_a - 1 >= 0.2:
                add("requests", f"מספר הבקשות שקיבלו תשלום ירד מ-{fmt.int_he(na)} בשנת התקציב {a} ל-{fmt.int_he(nb)} בשנת התקציב {b}, "
                                f"אבל הבקשה הממוצעת גדלה מ-{fmt.num_he(avg_a / 1e6, 1)} ל-{fmt.num_he(avg_b / 1e6, 1)} מיליון ש\"ח: פחות בקשות, גדולות יותר.")

    # payment size concentration
    if len(big):
        bshare = float(big["paid"].sum()) / total
        add("sizes", f"רק {_plural(len(big), 'תשלום אחד', 'תשלומים')} מעל 10 מיליון ש\"ח "
                     f"({fmt.pct(len(big) / n_pay)} מהתשלומים) מרכזים {fmt.pct(bshare)} מהכסף, "
                     f"בעוד שהתשלום החציוני הוא {fmt.int_he(median_pay)} ש\"ח.")

    # lag
    if lag_stats and lag_stats["week"] >= 0.5:
        add("lag", f"{fmt.pct(lag_stats['week'])} מהתשלומים הועברו בתוך שבוע ממועד הזכאות "
                   f"(חציון: {_plural(round(lag_stats['median']), 'יום אחד', 'ימים') if round(lag_stats['median']) else 'באותו יום'}), "
                   f"ו-{fmt.pct(lag_stats['over90'])} המתינו יותר מ-90 יום.")

    # pending
    if len(pending):
        add("pending", f"{_plural(len(pending), 'תשלום אחד', 'תשלומים')} בסך {fmt.num_he(pend_sum / 1e6, 1)} מיליון ש\"ח "
                       f"נרשמו לתשלום אך טרם שולמו בפועל.")

    # status
    st = frame.ranked(reqs.loc[reqs["status"] != "", "status"])
    if len(st) >= 2 and n_req:
        s1, s2 = st.index[0], st.index[1]
        add("status", f"{fmt.pct(st.iloc[0] / n_req)} מהבקשות בסטטוס \"{s1}\" "
                      f"ו-{fmt.pct(st.iloc[1] / n_req)} בסטטוס \"{s2}\""
                      + (f"; {_plural(int(st.iloc[2:].sum()), 'בקשה אחת', 'בקשות')} בסטטוסים אחרים." if len(st) > 2 else "."))

    # ---------- labels ----------
    span = f"{first.year}-{last.year}" if first.year != last.year else str(first.year)
    lede = (f"המאגר מפרט {fmt.int_he(n_pay)} תשלומים שמשרד הפנים העביר ל-{fmt.int_he(n_who)} רשויות מקומיות, "
            f"איגודי ערים ותאגידים מוניציפליים בין {fmt.d_he(first)} ל-{fmt.d_he(last)}, בסך {_bn(total)} מיליארד ש\"ח. "
            f"כל שורה היא תשלום על אבן דרך בבקשה ({fmt.int_he(n_req)} בקשות), עם התקנה התקציבית, המחלקה האחראית ותאריך ההעברה.")
    summary = (f"איתור תשלומי משרד הפנים לרשות מקומית לפי שם הרשות, תקנה או מחלקה: "
               f"{_bn(total)} מיליארד ש\"ח ב-{fmt.int_he(n_pay)} תשלומים, {span}.")
    if len(summary) > 155:
        summary = f"תשלומי משרד הפנים לרשויות המקומיות: {_bn(total)} מיליארד ש\"ח ב-{fmt.int_he(n_pay)} תשלומים, {span}."

    peak_y = max(years_all, key=lambda y: (float(year_tot[y]), -y))
    labels = {
        "lede": lede,
        "notes": ("לרשויות מקומיות/תאגידים מוניציפאלים 8 שנים אחורה עד היום.\n"
                  "מידע מפורט בדבר תשלומי משרד הפנים שהועברו לרשויות המקומיות, מכיל סוגים סטטוסים ותאריכים"),
        "total_kpi": "סך התשלומים ששולמו (מיליארד ש\"ח)",
        "payments_kpi": "תשלומים",
        "recipients_kpi": "רשויות וגופים שקיבלו תשלום",
        "requests_kpi": "בקשות",
        "top_prog_kpi": f"משקל \"{prog_sum.index[0]}\" בסך התשלומים",
        "pending_kpi": "נרשמו וטרם שולמו (מיליון ש\"ח)",
        "yearly_lede": (f"סכומים במיליוני ש\"ח. השנה עם הסכום הגבוה ביותר: {peak_y} ({_bn(year_tot[peak_y])} מיליארד ש\"ח). "
                        f"השנה מחושבת לפי תאריך ההעברה בפועל."
                        + (f" {last_year} חלקית: הנתונים מגיעים עד {fmt.d_he(last)}." if last_partial else "")),
        "yearly_aria": (f"גרף עמודות מוערמות: סכום התשלומים לפי שנה ותקנה, {span}. "
                        f"השיא ב-{peak_y} עם {_bn(year_tot[peak_y])} מיליארד ש\"ח."),
        "pace_lede": ("סכום מצטבר (מיליארד ש\"ח) מתחילת כל שנה, חודש אחר חודש, כדי להשוות את קצב ההעברות בין השנים"
                      + (f"; קו {last_year} נעצר בחודש האחרון שיש בו נתונים." if last_partial else ".")),
        "pace_aria": f"גרף קווים: סכום מצטבר של תשלומים מתחילת השנה לפי חודש, לכל שנה בין {hy[0]} ל-{hy[-1]} (מיליארד ש\"ח).",
        "heat_lede": "כל משבצת היא סכום התשלומים בחודש אחד (מיליון ש\"ח). משבצת כהה מסמנת חודש של העברות גדולות.",
        "heat_aria": f"מפת חום: סכום התשלומים לפי חודש ושנה, {hy[0]}-{hy[-1]}, במיליוני ש\"ח.",
        "programs_lede": (f"{len(prog_sum)} תקנות תקציביות שונות. "
                          f"{fmt.int_he(min(TOP_PROGRAMS, len(prog_sum)))} הגדולות מרכזות "
                          f"{fmt.pct(float(prog_sum.iloc[:TOP_PROGRAMS].sum()) / total)} מהכסף. שמות התקנות קטועים במקור."),
        "programs_aria": (f"גרף עמודות אופקי: סכום התשלומים לפי תקנה. המובילה: {prog_sum.index[0]} "
                          f"עם {_bn(prog_sum.iloc[0])} מיליארד ש\"ח."),
        "depts_lede": (f"המחלקה האחראית לתשלום במשרד הפנים. דרך {dept_sum.index[0]} עברו "
                       f"{fmt.pct(float(dept_sum.iloc[0]) / total)} מהסכום."),
        "depts_aria": f"גרף עמודות אופקי: סכום התשלומים לפי מחלקה אחראית. המובילה: {dept_sum.index[0]}.",
        "recip_lede": (f"{fmt.int_he(len(top_who))} הגופים שקיבלו הכי הרבה כסף מרכזים {fmt.pct(top_n_share)} מסך התשלומים."),
        "recip_aria": f"גרף עמודות אופקי: הגופים שקיבלו את הסכום הגבוה ביותר. בראש: {tw} עם {_mn(tv)} מיליון ש\"ח.",
        "types_lede": ("סוג הגוף נקבע לפי תחילת שמו במאגר (עירייה, מ. מ., מ. א., איגוד ערים). "
                       "גופים ששמם אינו מציין סוג, כמו ועדי וקף, עמותות וכמה רשויות שנרשמו בשם היישוב בלבד, נכללים ב\"גופים אחרים\"."),
        "types_aria": (f"גרף עמודות: סכום התשלומים לפי סוג הגוף המקבל. "
                       f"המובילות: {type_lead} עם {fmt.pct(float(t_sum[type_lead]) / total)} מהסכום."),
        "budget_lede": ("לכל בקשה יש שנת תקציב. כל עמודה (מיליון ש\"ח) מחלקת את הסכום שאושר לבקשות של אותה שנה: "
                        "מה ששולם עד סוף שנת התקציב, מה ששולם בשנים שאחריה, ומה שנותר. "
                        "הסכום המאושר נספר רק לבקשות שיש להן לפחות תשלום אחד במאגר."),
        "budget_aria": f"גרף עמודות מוערמות: סכום מאושר לפי שנת תקציב, מחולק לשולם באותה שנה, שולם מאוחר יותר ויתרה, {by[0]}-{by[-1]}." if by else "",
        "sizes_lede": (f"התשלום החציוני: {fmt.int_he(median_pay)} ש\"ח. "
                       f"תשלומים של מיליון ש\"ח ומעלה הם {fmt.pct(big1_cnt)} ממספר התשלומים "
                       f"ו-{fmt.pct(big1_sum)} מהכסף."),
        "sizes_aria": "גרף עמודות: התפלגות התשלומים לפי גודל, אחוז ממספר התשלומים לעומת אחוז מהסכום.",
        "lag_lede": (f"הזמן מתאריך הזכאות ועד ההעברה בפועל. חציון: "
                     f"{_plural(round(lag_stats['median']), 'יום אחד', 'ימים') if lag_stats and round(lag_stats['median']) else 'באותו יום'}."
                     if lag_stats else ""),
        "lag_aria": "גרף עמודות: התפלגות הזמן ממועד הזכאות ועד התשלום, אחוז מהתשלומים ואחוז מהסכום." if lag_stats else "",
    }

    tables = {
        "yearly": yearly_rows, "pace": pace_rows, "heat": heat_rows, "programs": prog_rows,
        "depts": dept_rows, "recipients": recip_rows, "types": type_rows, "budget": bud_rows,
        "sizes": size_rows, "lag": lag_rows,
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{first.year}/{last.year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": yearly, "pace": pace, "heat": heat, "programs": programs, "depts": depts,
            "recipients": recipients, "types": types, "budget": budget, "sizes": sizes, "lag": lag,
        },
        "insights": insights,
        "labels": labels,
        "tables": tables,
        "pace_years": [str(y) for y in hy],
        "first_prog": prog_sum.index[0],
    }
