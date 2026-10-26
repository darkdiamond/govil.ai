"""הליכי בתי הדין ברשות הפטנטים — proceedings before the Patent Office tribunal.

One row per (proceeding, file). A proceeding usually has one "header" row with
no file number plus one row per patent / trademark / design file it concerns;
department, procedure type, status and status date are identical on all rows
of a proceeding (checked when authored), so the recipe works at proceeding
level: one record per `מספר הליך`.

The proceeding number is `<department>-<sequence>-<year>`; the year is the
year the proceeding was opened, and is the only opening date in the data.
`תאריך סטטוס` is the date of the current status — for a closed proceeding,
when it closed; for a merged one, when it was merged. There is no history of
earlier statuses, so "resolved in year Y" means "currently closed or merged
with a status date in Y".

The latest year is partial unless the latest status date in the data is in
December; partial years are labelled and kept out of trend rules.

Names on the page: only the proceeding's own title (a trademark, an
invention or a design title) in the largest-proceedings table, and only for
the trademark, patent and design departments — the compensation-committee
and service-invention titles name individual employees, so those
departments never contribute titles.
"""
import pandas as pd

MAX_YEARS = 16          # years shown individually; earlier ones collapse
TOP_DEPTS = 4           # departments named in stacked charts
TOP_TYPES = 8           # procedure types named in the type chart
MIX_TYPES = 4           # types named in the largest department's mix chart
TOP_FILES = 10          # largest proceedings table
DUR_MIN_CLOSED = 30     # department needs this many closed cohort procs
DUR_SETTLE = 2          # duration cohorts end this many years before last full year
TREND_THRESH = 0.10
CLEAR_OK = 1.0
CLEAR_WARN = 0.8
SHIFT_MIN_PP = 5.0
SEASON_LOW = 0.85

DEPT_HE = {
    "סימן מסחר": "סימני מסחר",
    "פטנט": "פטנטים",
    "מדגם": "מדגמים",
    "עיצוב": "עיצובים",
    "ועדת פיצויים ותמלוגים": "ועדת פיצויים ותמלוגים",
    "אמצאת שירות": "אמצאת שירות",
}
NAMED_DEPTS = {"סימן מסחר", "פטנט", "מדגם", "עיצוב"}
OTHER = "אחר"
NO_TYPE = "לא צוין"
CLOSED = "סגור"
MERGED = "עבר איחוד"
MONTHS = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט",
          "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
LAG_LABELS = ["באותה שנה", "שנה", "שנתיים", "3 שנים", "4 שנים", "5 שנים ומעלה"]
FILE_BUCKETS = [(0, 0, "0"), (1, 1, "1"), (2, 2, "2"), (3, 3, "3"),
                (4, 4, "4"), (5, 9, "5 עד 9"), (10, 10**9, "10 ומעלה")]
# chart axis labels: digits only — ECharts draws axis text without bidi
# reordering, so mixed Hebrew/number labels would read backwards
FILE_AXIS = ["0", "1", "2", "3", "4", "5-9", "10+"]
STATUS_COLOR = {CLOSED: "#6c757d", MERGED: "#c3cfe7"}


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=1):
    return f"{x * 100:.{d}f}%"


def _clean_name(s):
    return s.replace("''", "״").replace("~", "״").strip()


def _prepare(raw):
    df = raw.apply(lambda c: c.str.strip())
    parts = df["מספר הליך"].str.extract(r"^(.*?)-(\d+)-(\d{4})$")
    df = df.assign(prefix=parts[0], fy=pd.to_numeric(parts[2], errors="coerce"),
                   d=pd.to_datetime(df["תאריך סטטוס"], format="%d/%m/%Y", errors="coerce"))
    dropped = int((df["fy"].isna() | df["d"].isna()).sum())
    df = df[df["fy"].notna() & df["d"].notna()].copy()
    df["fy"] = df["fy"].astype(int)
    df["dept"] = df["סוג תיק"].where(df["סוג תיק"] != "", df["prefix"])
    df = df.sort_values(["מספר הליך", "מספר תיק", "שם הליך", "הליכים קשורים", "תאריך סטטוס"],
                        kind="stable")
    g = df.groupby("מספר הליך", sort=True)
    procs = g.agg(dept=("dept", "first"), fy=("fy", "first"), typ=("סוג הליך", "first"),
                  st=("סטטוס", "first"), d=("d", "max")).reset_index()
    files = df[df["מספר תיק"] != ""].groupby("מספר הליך")["מספר תיק"].nunique()
    linked = df[df["הליכים קשורים"] != ""].groupby("מספר הליך").size()
    procs["files"] = procs["מספר הליך"].map(files).fillna(0).astype(int)
    procs["linked"] = procs["מספר הליך"].isin(linked.index)
    procs["typ"] = procs["typ"].where(procs["typ"] != "", NO_TYPE)
    procs["dept_he"] = procs["dept"].map(lambda x: DEPT_HE.get(x, x))
    names = df[(df["שם הליך"] != "") & df["dept"].isin(NAMED_DEPTS)]
    nc = names.groupby(["מספר הליך", "שם הליך"]).size().rename("n").reset_index()
    nc = nc.sort_values(["מספר הליך", "n", "שם הליך"], ascending=[True, False, True], kind="stable")
    top_name = nc.drop_duplicates("מספר הליך").set_index("מספר הליך")["שם הליך"]
    procs["name"] = procs["מספר הליך"].map(top_name).fillna("")
    return procs, dropped, len(df)


def compute(frames):
    procs, dropped, n_rows = _prepare(frames["proceedings"])
    n = len(procs)
    last_date = procs["d"].max()
    year_last = int(max(last_date.year, procs["fy"].max()))
    partial = last_date.year == year_last and last_date.month < 12
    last_full = year_last - 1 if partial else year_last
    date_disp = last_date.strftime("%d.%m.%Y")

    procs["resolved"] = procs["st"].isin([CLOSED, MERGED])
    procs["active"] = ~procs["resolved"]
    procs["ry"] = procs["d"].dt.year

    # ---------------- departments ----------------
    dc = procs.groupby("dept_he").size().reset_index(name="n")
    dc = dc.sort_values(["n", "dept_he"], ascending=[False, True], kind="stable")
    dept_order = dc["dept_he"].tolist()
    named = dept_order[:TOP_DEPTS] if len(dept_order) > TOP_DEPTS + 1 else dept_order
    procs["dgrp"] = procs["dept_he"].where(procs["dept_he"].isin(named), OTHER)
    grp_order = named + ([OTHER] if (procs["dgrp"] == OTHER).any() else [])
    act_by_dept = procs[procs["active"]].groupby("dept_he").size()
    dept_rows = [{"name": r.dept_he, "n": _int(r.n), "share": f"{r.n / n * 100:.1f}",
                  "active": _int(act_by_dept.get(r.dept_he, 0))} for r in dc.itertuples()]
    dept_chart = {"names": dc["dept_he"].tolist(), "values": [int(v) for v in dc["n"]]}
    lead_dept = dept_order[0]
    lead_raw = procs.loc[procs["dept_he"] == lead_dept, "dept"].iloc[0]

    # ---------------- years ----------------
    all_years = list(range(int(procs["fy"].min()), year_last + 1))
    shown = all_years[-MAX_YEARS:]
    first_shown = shown[0]
    has_early = all_years[0] < first_shown
    ykeys = ([first_shown - 1] if has_early else []) + shown
    procs["fyk"] = procs["fy"].where(procs["fy"] >= first_shown, first_shown - 1)
    procs["ryk"] = procs["ry"].clip(lower=all_years[0])
    procs["ryk"] = procs["ryk"].where(procs["ryk"] >= first_shown, first_shown - 1)

    def ylabel(y):
        if y == first_shown - 1:
            return f"עד {first_shown - 1}"
        return f"{y} (חלקי)" if (partial and y == year_last) else str(y)
    ylabels = [ylabel(y) for y in ykeys]

    opened = procs.groupby("fyk").size()
    resolved = procs[procs["resolved"]].groupby("ryk").size()
    opened_l = [int(opened.get(y, 0)) for y in ykeys]
    resolved_l = [int(resolved.get(y, 0)) for y in ykeys]
    by_dy = procs.groupby(["fyk", "dgrp"]).size()
    years_chart = {"x": ylabels, "series": [
        {"name": d, "data": [int(by_dy.get((y, d), 0)) for y in ykeys]} for d in grp_order]}
    years_rows = [{"year": lab, "vals": [_int(by_dy.get((y, d), 0)) for d in grp_order],
                   "total": _int(opened.get(y, 0))} for lab, y in zip(ylabels, ykeys)]
    flow_chart = {"x": ylabels, "opened": opened_l, "resolved": resolved_l}
    flow_rows = [{"year": lab, "opened": _int(o), "resolved": _int(r),
                  "net": (f"{o - r:+,}".replace("-", "−") if o != r else "0")}
                 for lab, o, r in zip(ylabels, opened_l, resolved_l)]

    full_years = [y for y in shown if y <= last_full]
    op_last = int(opened.get(last_full, 0))
    res_last = int(resolved.get(last_full, 0))
    clearance = res_last / op_last if op_last else None

    # ---------------- procedure types ----------------
    tc = procs.groupby("typ").size().reset_index(name="n")
    tc = tc.sort_values(["n", "typ"], ascending=[False, True], kind="stable")
    tnamed = tc["typ"].tolist()[:TOP_TYPES] if len(tc) > TOP_TYPES + 1 else tc["typ"].tolist()
    procs["tgrp"] = procs["typ"].where(procs["typ"].isin(tnamed), OTHER)
    t_order = tnamed + ([OTHER] if (procs["tgrp"] == OTHER).any() else [])
    by_td = procs.groupby(["tgrp", "dgrp"]).size()
    by_t = procs.groupby("tgrp").size()
    types_chart = {"names": t_order, "series": [
        {"name": d, "data": [int(by_td.get((t, d), 0)) for t in t_order]} for d in grp_order]}
    types_rows = [{"name": t, "n": _int(by_t.get(t, 0)), "share": f"{by_t.get(t, 0) / n * 100:.1f}",
                   "vals": [_int(by_td.get((t, d), 0)) for d in grp_order]} for t in t_order]
    top_type = tc["typ"].iloc[0]
    top_type_n = int(tc["n"].iloc[0])

    # ---------------- lead department's type mix ----------------
    lp = procs[procs["dept_he"] == lead_dept]
    lc = lp.groupby("typ").size().reset_index(name="n")
    lc = lc.sort_values(["n", "typ"], ascending=[False, True], kind="stable")
    mnamed = lc["typ"].tolist()[:MIX_TYPES] if len(lc) > MIX_TYPES + 1 else lc["typ"].tolist()
    lp = lp.assign(mg=lp["typ"].where(lp["typ"].isin(mnamed), OTHER))
    m_order = mnamed + ([OTHER] if (lp["mg"] == OTHER).any() else [])
    m_cnt = lp.groupby(["fyk", "mg"]).size()
    m_tot = lp.groupby("fyk").size()

    def mshare(y, t):
        tot = int(m_tot.get(y, 0))
        return round(int(m_cnt.get((y, t), 0)) / tot * 100, 1) if tot else 0.0
    mix_chart = {"x": ylabels, "series": [{"name": t, "data": [mshare(y, t) for y in ykeys]}
                                          for t in m_order]}
    mix_rows = [{"year": lab, "vals": [f"{mshare(y, t):.1f}" for t in m_order]}
                for lab, y in zip(ylabels, ykeys)]

    # ---------------- status ----------------
    sc = procs.groupby("st").size().reset_index(name="n")
    sc = sc.sort_values(["n", "st"], ascending=[False, True], kind="stable")
    status_chart = {"names": sc["st"].tolist(), "values": [int(v) for v in sc["n"]],
                    "colors": [STATUS_COLOR.get(s, "#0068f5") for s in sc["st"]]}
    status_rows = [{"name": r.st, "n": _int(r.n), "share": f"{r.n / n * 100:.1f}"}
                   for r in sc.itertuples()]
    n_active = int(procs["active"].sum())
    n_merged = int((procs["st"] == MERGED).sum())
    n_closed = int((procs["st"] == CLOSED).sum())

    # ---------------- active backlog by opening year ----------------
    act = procs[procs["active"]]
    a_years = sorted(act["fy"].unique().tolist())
    by_ady = act.groupby(["fy", "dgrp"]).size()
    a_grps = [d for d in grp_order if (act["dgrp"] == d).any()]
    backlog_chart = {"x": [ylabel(y) if y >= first_shown else str(y) for y in a_years], "series": [
        {"name": d, "data": [int(by_ady.get((y, d), 0)) for y in a_years]} for d in a_grps]}
    act_y = act.groupby("fy").size()
    backlog_rows = [{"year": str(y), "n": _int(act_y.get(y, 0)),
                     "vals": [_int(by_ady.get((y, d), 0)) for d in a_grps]} for y in a_years]
    act_st = act.groupby("st").size().reset_index(name="n").sort_values(
        ["n", "st"], ascending=[False, True], kind="stable")

    # ---------------- time to close ----------------
    cohort_end = last_full - DUR_SETTLE
    cl = procs[(procs["st"] == CLOSED) & (procs["fy"] <= cohort_end)].copy()
    cl["lag"] = (cl["ry"] - cl["fy"]).clip(lower=0, upper=len(LAG_LABELS) - 1)
    cohort = procs[procs["fy"] <= cohort_end]
    dur_depts = [d for d in dept_order if (cl["dept_he"] == d).sum() >= DUR_MIN_CLOSED]
    dur_series, dur_rows, dur_med = [], [], {}
    lag_cnt = cl.groupby(["dept_he", "lag"]).size()
    for d in dur_depts:
        sub = cl[cl["dept_he"] == d]
        tot = len(sub)
        shares = [round(int(lag_cnt.get((d, k), 0)) / tot * 100, 1) for k in range(len(LAG_LABELS))]
        dur_series.append({"name": d, "data": shares})
        med = float(sub["lag"].median())
        dur_med[d] = med
        still = int(cohort[(cohort["dept_he"] == d)]["active"].sum())
        dur_rows.append({"name": d, "n": _int(tot), "vals": [f"{s:.1f}" for s in shares],
                         "within1": f"{sum(shares[:2]):.1f}", "still": _int(still)})
    dur_chart = {"x": LAG_LABELS, "series": dur_series}
    cl_within1 = float((cl["lag"] <= 1).mean()) if len(cl) else 0.0

    # ---------------- files per proceeding ----------------
    f_counts = [int(((procs["files"] >= lo) & (procs["files"] <= hi)).sum()) for lo, hi, _ in FILE_BUCKETS]
    files_chart = {"names": FILE_AXIS, "values": f_counts}
    files_rows = [{"name": b[2], "n": _int(c), "share": f"{c / n * 100:.1f}"}
                  for b, c in zip(FILE_BUCKETS, f_counts)]
    big = procs[procs["dept"].isin(NAMED_DEPTS) & (procs["files"] >= 2)]
    big = big.sort_values(["files", "fy", "מספר הליך"], ascending=[False, True, True], kind="stable")
    big = big.head(TOP_FILES)
    top_rows = [{"id": r["מספר הליך"], "name": _clean_name(r["name"]) or "—", "dept": r["dept_he"],
                 "typ": r["typ"], "files": _int(r["files"]), "st": r["st"]} for _, r in big.iterrows()]
    multi = int((procs["files"] >= 2).sum())
    n_linked = int(procs["linked"].sum())

    # ---------------- closures month x year ----------------
    cm = procs[procs["st"] == CLOSED]
    cm = cm[cm["ry"] >= first_shown]
    hm_years = sorted(cm["ry"].unique().tolist())
    hm_cnt = cm.groupby([cm["ry"], cm["d"].dt.month]).size()
    cells, hmax = [], 0
    for yi, y in enumerate(hm_years):
        for m in range(1, 13):
            if y == last_date.year and m > last_date.month:
                continue
            v = int(hm_cnt.get((y, m), 0))
            hmax = max(hmax, v)
            cells.append([m - 1, yi, v])
    heat_chart = {"months": MONTHS, "years": [str(y) for y in hm_years], "cells": cells, "max": hmax}
    # full calendar years only: not the partial latest year, and not the first
    # year (the register starts mid-year, so its early months are empty)
    full_cm = cm[(cm["ry"] <= last_full) & (cm["ry"] > all_years[0])]
    month_tot = full_cm.groupby(full_cm["d"].dt.month).size().reindex(range(1, 13), fill_value=0)

    # ---------------- insights ----------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_dept():
        share = int(dc["n"].iloc[0]) / n
        if share < 0.4 or len(dc) < 2:
            return None
        second = dc.iloc[1]
        return (f"מחלקת {lead_dept} היא הזירה העיקרית: {_int(dc['n'].iloc[0])} מתוך {_int(n)} ההליכים "
                f"({_pct(share)}), לעומת {_int(second.n)} ב{second.dept_he} ({_pct(second.n / n)}).")

    def ins_type():
        share = top_type_n / n
        if share < 0.3 or top_type == NO_TYPE:
            return None
        lead_share = float((lp["typ"] == top_type).mean())
        return (f"ההליך הנפוץ ביותר הוא {top_type}: {_int(top_type_n)} הליכים, {_pct(share)} מכלל ההליכים "
                f"ו-{_pct(lead_share)} מההליכים במחלקת {lead_dept}.")

    def ins_trend():
        prev = [y for y in full_years if y < last_full][-3:]
        if len(prev) < 3 or op_last == 0:
            return None
        base = sum(int(opened.get(y, 0)) for y in prev) / len(prev)
        if base == 0:
            return None
        ch = op_last / base - 1
        span = f"{prev[0]} עד {prev[-1]}"
        tail = f" (נתוני {year_last} חלקיים ואינם נכללים בהשוואה)" if partial else ""
        if ch >= TREND_THRESH:
            word = f"עלייה של {_pct(ch, 0)}"
        elif ch <= -TREND_THRESH:
            word = f"ירידה של {_pct(-ch, 0)}"
        else:
            return (f"היקף ההליכים החדשים יציב: ב-{last_full} נפתחו {_int(op_last)} הליכים, "
                    f"בדומה לממוצע של {base:,.0f} בשנים {span}{tail}.")
        return (f"ב-{last_full} נפתחו {_int(op_last)} הליכים — {word} לעומת הממוצע של {base:,.0f} "
                f"בשנים {span}{tail}.")

    def ins_clear():
        if clearance is None:
            return None
        if clearance >= CLEAR_OK + 0.03:
            verdict = "בית הדין סגר יותר הליכים משנפתחו"
        elif clearance >= CLEAR_OK - 0.03:
            verdict = "מספר ההליכים שנסגרו היה כמעט זהה למספר ההליכים שנפתחו"
        elif clearance >= CLEAR_WARN:
            verdict = "מספר ההליכים שנסגרו היה קרוב למספר ההליכים שנפתחו"
        else:
            verdict = "נסגרו פחות הליכים משנפתחו, והמלאי הפתוח גדל"
        return (f"ב-{last_full} {verdict}: {_int(res_last)} הליכים נסגרו או אוחדו מול {_int(op_last)} "
                f"שנפתחו (שיעור סגירה {_pct(clearance, 0)}; לפי תאריך הסטטוס הנוכחי).")

    def ins_backlog():
        if n_active == 0:
            return None
        recent = int(act[act["fy"] >= year_last - 1]["fy"].count())
        oldest = int(act["fy"].min())
        n_old = int((act["fy"] == oldest).sum())
        top_st = act_st.iloc[0]
        return (f"{_int(n_active)} הליכים פעילים כיום ({_pct(n_active / n)} מהמאגר); "
                f"{_int(recent)} מהם ({_pct(recent / n_active, 0)}) נפתחו ב-{year_last - 1} או ב-{year_last}. "
                f"הוותיק ביותר נפתח ב-{oldest} ({'הליך אחד' if n_old == 1 else _int(n_old) + ' הליכים'}), והסטטוס הנפוץ בין הפעילים הוא "
                f"\"{top_st.st}\" ({_int(top_st.n)}).")

    def ins_dur():
        if len(dur_depts) < 2:
            return None
        a, b = dur_depts[0], dur_depts[1]
        ra = next(r for r in dur_rows if r["name"] == a)
        rb = next(r for r in dur_rows if r["name"] == b)
        wa, wb = float(ra["within1"]), float(rb["within1"])
        if abs(wa - wb) < 5:
            return None
        fast, slow = (a, b) if wa > wb else (b, a)
        wf, ws = max(wa, wb), min(wa, wb)
        return (f"הליכי {fast} מסתיימים מהר יותר: {wf:.0f}% מהסגורים נסגרו בשנת הפתיחה או בשנה שאחריה, "
                f"לעומת {ws:.0f}% ב{slow} (הליכים שנפתחו עד {cohort_end}).")

    def ins_multi():
        if multi == 0 or not top_rows:
            return None
        t = top_rows[0]
        nm = f" (\"{t['name']}\")" if t["name"] != "—" else ""
        return (f"{_int(multi)} הליכים ({_pct(multi / n)}) עוסקים ביותר מתיק אחד. הגדול שבהם, {t['id']}{nm}, "
                f"הוא {t['typ']} במחלקת {t['dept']} שכולל {t['files']} תיקים.")

    def ins_linked():
        if n_merged + n_linked == 0:
            return None
        return (f"{_int(n_merged)} הליכים ({_pct(n_merged / n)}) אוחדו לתוך הליך אחר, "
                f"ו-{_int(n_linked)} הליכים מפנים להליכים קשורים, כמו התנגדויות הדדיות שמתנהלות במקביל.")

    def ins_shift():
        fy_l = [y for y in full_years]
        if len(fy_l) < 6:
            return None
        early, late = fy_l[:3], fy_l[-3:]

        def share(ys, t):
            sub = lp[lp["fy"].isin(ys)]
            return float((sub["mg"] == t).mean() * 100) if len(sub) else 0.0
        best = None
        for t in m_order:
            if t == OTHER:
                continue
            e, l = share(early, t), share(late, t)
            if best is None or abs(l - e) > abs(best[2] - best[1]) + 1e-9:
                best = (t, e, l)
        if best is None or abs(best[2] - best[1]) < SHIFT_MIN_PP:
            return None
        t, e, l = best
        word = "עלה" if l > e else "ירד"
        return (f"במחלקת {lead_dept} חלקם של הליכי \"{t}\" {word} מ-{e:.1f}% בשנים {early[0]} עד {early[-1]} "
                f"ל-{l:.1f}% בשנים {late[0]} עד {late[-1]}.")

    def ins_season():
        if month_tot.sum() < 240:
            return None
        mean = float(month_tot.mean())
        mmin = int(month_tot.sort_values(kind="stable").index[0])
        vmin = int(month_tot[mmin])
        if vmin > SEASON_LOW * mean:
            return None
        return (f"חודש {MONTHS[mmin - 1]} הוא החלש בסגירת הליכים: {_int(vmin)} סגירות בשנים {all_years[0] + 1} עד {last_full}, "
                f"{_pct(1 - vmin / mean, 0)} פחות מהממוצע החודשי ({mean:,.0f}).")

    def ins_design():
        old = procs[procs["dept"] == "מדגם"]
        new = procs[procs["dept"] == "עיצוב"]
        if len(old) == 0 or len(new) == 0:
            return None
        first_new = int(new["fy"].min())
        since = procs[procs["dept"].isin(["מדגם", "עיצוב"]) & (procs["fy"] >= first_new)]
        sh = float((since["dept"] == "עיצוב").mean())
        if sh < 0.5:
            return None
        return (f"הליכי העיצובים עברו לסיווג חדש: הליכי \"עיצוב\" מופיעים מ-{first_new}, ומאז הם "
                f"{_int(int((since['dept'] == 'עיצוב').sum()))} מתוך {_int(len(since))} הליכי העיצובים והמדגמים "
                f"({_pct(sh, 0)}).")

    for iid, fn in [("dept", ins_dept), ("type", ins_type), ("trend", ins_trend), ("clear", ins_clear),
                    ("backlog", ins_backlog), ("dur", ins_dur), ("multi", ins_multi), ("shift", ins_shift),
                    ("season", ins_season), ("linked", ins_linked), ("design", ins_design)]:
        add(iid, fn())

    # ---------------- KPIs ----------------
    if clearance is None:
        c_tone, c_disp, c_val = "brand", "—", None
    else:
        c_tone = "ok" if clearance >= CLEAR_OK else ("warn" if clearance >= CLEAR_WARN else "danger")
        c_disp, c_val = f"{clearance * 100:.0f}%", round(clearance * 100, 1)
    kpis = {
        "procs": {"value": n, "display": _int(n), "tone": "brand"},
        "active": {"value": n_active, "display": _int(n_active), "tone": "info"},
        "opened": {"value": op_last, "display": _int(op_last), "tone": "brand"},
        "clearance": {"value": c_val, "display": c_disp, "tone": c_tone},
    }

    span = f"{all_years[0]} עד {year_last}"
    lede = (f"המאגר מתעד {_int(n)} הליכים שנפתחו בבתי הדין של רשות הפטנטים בשנים {span} "
            f"({_int(n_rows)} רשומות, שורה לכל תיק בהליך). {_int(n_closed)} הליכים נסגרו, {_int(n_merged)} אוחדו "
            f"ו-{_int(n_active)} עדיין פעילים. מחלקת {lead_dept} מובילה עם {_pct(int(dc['n'].iloc[0]) / n, 0)} "
            f"מההליכים, וההליך הנפוץ הוא {top_type}. הנתונים מעודכנים עד {date_disp}.")
    summary = (f"{_int(n)} הליכים בבתי הדין של רשות הפטנטים ({span}): {_int(n_active)} פעילים, "
               f"{_pct(int(dc['n'].iloc[0]) / n, 0)} בסימני מסחר; פילוח לפי מחלקה, סוג הליך, סטטוס ומשך טיפול."
               if lead_raw == "סימן מסחר" else
               f"{_int(n)} הליכים בבתי הדין של רשות הפטנטים ({span}): {_int(n_active)} פעילים; "
               f"פילוח לפי מחלקה, סוג הליך, סטטוס ומשך טיפול.")

    yr_partial_note = f" שנת {year_last} חלקית (עד {date_disp})." if partial else ""
    labels = {
        "lede": lede,
        "active_kpi": f"הליכים פעילים ({date_disp})",
        "opened_kpi": f"הליכים שנפתחו ב-{last_full}",
        "clearance_kpi": f"שיעור סגירה ב-{last_full} (נסגרו מול נפתחו)",
        "years_note": (f"לפי שנת הפתיחה שבמספר ההליך. בשיא, {max(opened_l):,} הליכים בשנה "
                       f"({ylabels[opened_l.index(max(opened_l))]}).{yr_partial_note}"),
        "years_aria": f"הליכים שנפתחו בכל שנה לפי מחלקה, {span}",
        "flow_note": (f"נפתחו לפי שנת הפתיחה; נסגרו או אוחדו לפי שנת תאריך הסטטוס הנוכחי. "
                      f"ב-{last_full}: {_int(op_last)} נפתחו ו-{_int(res_last)} נסגרו או אוחדו.{yr_partial_note}"),
        "flow_aria": f"הליכים שנפתחו מול הליכים שנסגרו בכל שנה, {span}",
        "dept_note": (f"{len(dc)} מחלקות. {lead_dept}: {_int(dc['n'].iloc[0])} הליכים, "
                      f"מהם {_int(act_by_dept.get(lead_dept, 0))} פעילים."),
        "dept_aria": "מספר ההליכים בכל מחלקה",
        "types_note": (f"{len(tc)} סוגי הליכים. {top_type}: {_int(top_type_n)} הליכים "
                       f"({_pct(top_type_n / n)})."),
        "types_aria": "סוגי ההליכים לפי מחלקה",
        "mix_note": (f"חלקו של כל סוג הליך מכלל ההליכים שנפתחו בכל שנה במחלקת {lead_dept} "
                     f"({_int(len(lp))} הליכים)."),
        "mix_aria": f"תמהיל סוגי ההליכים לפי שנה במחלקת {lead_dept}",
        "status_note": (f"{_int(n_closed)} סגורים ({_pct(n_closed / n)}), {_int(n_merged)} אוחדו, "
                        f"{_int(n_active)} בטיפול."),
        "status_aria": "ההליכים לפי סטטוס נוכחי",
        "backlog_note": (f"{_int(n_active)} ההליכים שאינם סגורים או מאוחדים, לפי שנת פתיחה. "
                         f"הוותיק ביותר נפתח ב-{int(act['fy'].min()) if n_active else year_last}."),
        "backlog_aria": "הליכים פעילים לפי שנת פתיחה ומחלקה",
        "dur_note": (f"שנים קלנדריות מפתיחת ההליך ועד סגירתו, להליכים שנפתחו עד {cohort_end} ונסגרו "
                     f"({_int(len(cl))} הליכים); {_pct(cl_within1, 0)} נסגרו בשנת הפתיחה או בשנה שאחריה."),
        "dur_aria": "משך הטיפול בהליכים שנסגרו, לפי מחלקה",
        "files_note": (f"{_int(multi)} הליכים ({_pct(multi / n)}) עוסקים ביותר מתיק אחד — "
                       f"לרוב התנגדויות הדדיות ובקשות מתחרות על כמה סימנים."),
        "files_aria": "מספר התיקים בכל הליך",
        "top_note": "ההליכים שכוללים את מספר התיקים הגדול ביותר, במחלקות סימני המסחר, הפטנטים והעיצובים.",
        "heat_note": (f"סגירות הליכים בכל חודש, {hm_years[0] if hm_years else year_last} עד "
                      f"{hm_years[-1] if hm_years else year_last}. חודשים כהים יותר — יותר סגירות."),
        "heat_aria": "סגירות הליכים לפי חודש ושנה",
    }

    tables = {
        "years": years_rows, "years_heads": grp_order, "flow": flow_rows, "dept": dept_rows,
        "types": types_rows, "types_heads": grp_order, "mix": mix_rows, "mix_heads": m_order,
        "status": status_rows, "backlog": backlog_rows, "backlog_heads": a_grps,
        "dur": dur_rows, "files": files_rows, "top": top_rows,
    }
    charts = {
        "years": years_chart, "flow": flow_chart, "dept": dept_chart, "types": types_chart,
        "mix": mix_chart, "status": status_chart, "backlog": backlog_chart, "dur": dur_chart,
        "files": files_chart, "heat": heat_chart,
    }
    flags = {"backlog": n_active > 0, "dur": len(dur_depts) > 0, "top": len(top_rows) > 0,
             "heat": len(cells) > 0}

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["רשות הפטנטים", "קניין רוחני", "סימני מסחר", "פטנטים", "עיצובים",
                               "התנגדויות", "בתי דין"],
            "related_ids": ["656f6e4c-ec04-40a5-b3bc-c556b2b127e0",
                            "029b6747-551b-47ad-9a05-ef7f7868fcd0",
                            "0a374a70-87e9-41d1-a710-d8a81dc61144",
                            "1806c96c-9cc4-47bf-98b3-80a18f061f98",
                            "247efc75-31f2-4b19-bd4e-e670b1bf2783"],
            "temporal_coverage": f"{all_years[0]}/{year_last}",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "labels": labels,
        "flags": flags,
        "insights": insights,
        "meta": {"dropped_rows": dropped},
    }
