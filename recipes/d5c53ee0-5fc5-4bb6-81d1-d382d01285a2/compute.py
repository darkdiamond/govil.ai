"""רשם הירושה: requests filed with the Israeli Registrar of Inheritance
(the registrar for inheritance matters, in operation since 1998).

One row per request: filing date, request type, district, a constant
"represented" flag, current status, newspaper publication (date + paper),
the registrar's decision (+ date) and the closing reason (+ date).

PRIVACY: the export carries no names, ID numbers or case numbers. The page
aggregates only (counts, shares, durations).

"Now" is the latest filing date in the data, never the wall clock. A year
is "full" when it has filings in all twelve months and, for the latest
year, its last filing is in late December. Trend rules compare full years
only; the latest partial year is compared year-to-date against the same
calendar span one year earlier. Rows without a parsable filing date
(about 1%) are excluded from every time chart, which the ledes say.

Durations (filing to closing) use closed requests only and keep 0 to 3,650
days (negative or decade-plus gaps are data-entry errors); recent filing
years are biased short because their slow cases are still open, so the
duration and court-transfer rules compare full years at least two years
back from the latest one where it matters, and the ledes disclose it.
"""
import pandas as pd

C_SUB = "תאריך הגשת בקשה"
C_TYPE = "סוג בקשה"
C_DIST = "מחוז"
C_STATUS = "סטטוס בקשה"
C_PUB = "תאריך פרסום"
C_PAPER = "עיתון מפרסם"
C_DEC = "החלטת רשם"
C_DEC_D = "תאריך החלטת רשם"
C_CLOSE = "סיבת סגירה"
C_CLOSE_D = "תאריך סגירה"

T_INH = "לצו ירושה"
T_WILL = "לצו קיום צוואה"
T_COPY = "בקשה לקבלת העתק צו"
T_OBJ = "התנגדות"
CORE = (T_INH, T_WILL)
DONE = "הטיפול בבקשה הסתיים"
GRANTED = "ניתן צו"
COURT = "העברה לבימ~ש"

TOP_TYPES = 12
TOP_REASONS = 6
TOP_DECISIONS = 7
TOP_STATUS = 8
MAX_DAYS = 3650
LOOKBACK = 10
SEASON_YEARS = 10

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
DAYS_HE = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
LRI, PDI = "⁦", "⁩"
YTD_MIN_DAYS = 45  # year-to-date comparison only once the new year has this many days
MINUS = "−"

SERIES = [("inh", "צו ירושה"), ("will", "צו קיום צוואה"),
          ("copy", "העתק צו"), ("other", "בקשות אחרות")]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_plain(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def signed_pct(v, digits=1):
    s = f"{abs(v) * 100:.{digits}f}%"
    if round(v * 100, digits) > 0:
        return "+" + s
    if round(v * 100, digits) < 0:
        return MINUS + s
    return s


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def clean(s):
    return " ".join(str(s).replace("~", "״").split())


def _vc(s):
    """Value counts, count DESC then label ASC (total, shuffle-proof)."""
    vc = s.value_counts()
    df = pd.DataFrame({"k": vc.index.astype(str), "v": vc.values})
    df = df.sort_values(["v", "k"], ascending=[False, True], kind="mergesort")
    return list(zip(df["k"], df["v"].astype(int)))


def _top(pairs, k, other="אחר"):
    head = pairs[:k]
    rest = sum(v for _, v in pairs[k:])
    out = [(clean(a), int(v)) for a, v in head]
    if rest:
        out.append((other, int(rest)))
    return out


def _date(s):
    return pd.to_datetime(s.str.strip(), format="%d/%m/%Y", errors="coerce")


def _same_day_prev_year(ts):
    try:
        return ts.replace(year=ts.year - 1)
    except ValueError:  # 29 February
        return ts.replace(year=ts.year - 1, day=28)


def compute(frames):
    df = frames["main"]
    typ = df[C_TYPE].str.strip()
    dist = df[C_DIST].str.strip()
    status = df[C_STATUS].str.strip()
    paper = df[C_PAPER].str.strip()
    decision = df[C_DEC].str.strip()
    reason = df[C_CLOSE].str.strip()
    sub = _date(df[C_SUB])
    pub = _date(df[C_PUB])
    dec_d = _date(df[C_DEC_D])
    clo = _date(df[C_CLOSE_D])

    total = int(len(df))
    dated = sub.notna()
    n_dated = int(dated.sum())
    n_undated = total - n_dated
    year = sub.dt.year
    month = sub.dt.month
    last_date = sub.max()
    first_date = sub.min()
    last_year = int(last_date.year)
    first_year = int(first_date.year)
    years = list(range(first_year, last_year + 1))

    months_per_year = month[dated].groupby(year[dated]).nunique()
    full_years = []
    for y in years:
        if int(months_per_year.get(y, 0)) < 12:
            continue
        if y == last_year and not (last_date.month == 12 and last_date.day >= 25):
            continue
        full_years.append(y)
    partial_last = last_year not in full_years
    last_full = full_years[-1] if full_years else None
    first_full = full_years[0] if full_years else None

    is_core = typ.isin(CORE)
    grp = pd.Series("other", index=df.index)
    grp[typ == T_INH] = "inh"
    grp[typ == T_WILL] = "will"
    grp[typ == T_COPY] = "copy"

    # ---- yearly by type group -------------------------------------------
    ct = pd.crosstab(year[dated].astype(int), grp[dated])
    ct = ct.reindex(index=years, columns=[k for k, _ in SERIES], fill_value=0)
    yearly_tot = ct.sum(axis=1)
    yearly = {
        "x": [str(y) for y in years],
        "series": [{"name": name, "data": [int(v) for v in ct[k]]} for k, name in SERIES],
        "total": [int(v) for v in yearly_tot],
        "partial_index": len(years) - 1 if partial_last else -1,
    }
    yearly_rows = [{
        "year": str(y) + (" (חלקית)" if (partial_last and y == last_year) or y not in full_years and y == first_year else ""),
        "total": n(yearly_tot[y]),
        "inh": n(ct.at[y, "inh"]), "will": n(ct.at[y, "will"]),
        "copies": n(ct.at[y, "copy"]), "other": n(ct.at[y, "other"]),
    } for y in reversed(years)]

    # ---- wills share among core order requests ---------------------------
    core_ct = ct[["inh", "will"]]
    will_share = {}
    for y in full_years:
        s = int(core_ct.loc[y].sum())
        if s:
            will_share[y] = float(core_ct.at[y, "will"]) / s
    share_chart = {"x": [str(y) for y in will_share],
                   "y": [round(v * 100, 1) for v in will_share.values()]}
    share_rows = [{"year": str(y), "core": n(core_ct.loc[y].sum()),
                   "will": n(core_ct.at[y, "will"]), "share": pct_plain(v)}
                  for y, v in reversed(list(will_share.items()))]

    # ---- YTD -------------------------------------------------------------
    ytd = None
    ytd_days = (last_date - pd.Timestamp(year=last_year, month=1, day=1)).days + 1
    if last_year - 1 in years and ytd_days >= YTD_MIN_DAYS:
        prev_cut = _same_day_prev_year(last_date)
        cur = int(((year == last_year) & (sub <= last_date)).sum())
        prev = int(((year == last_year - 1) & (sub <= prev_cut)).sum())
        if prev:
            ytd = {"cur": cur, "prev": prev, "chg": cur / prev - 1}

    # ---- month x year heatmap (all dated filings) ------------------------
    my = pd.crosstab(year[dated].astype(int), month[dated].astype(int))
    my = my.reindex(index=years, columns=range(1, 13), fill_value=0)
    cells = []
    for yi, y in enumerate(years):
        for m in range(1, 13):
            if y == last_year and m > last_date.month:
                continue
            if y == first_year and m < first_date.month:
                continue
            cells.append([yi, m - 1, int(my.at[y, m])])
    heat = {"months": MONTHS_HE, "years": [str(y) for y in years], "cells": cells,
            "max": int(my.values.max()) if my.size else 0,
            "last_month": int(last_date.month), "last_year": str(last_year)}
    season_years = full_years[-SEASON_YEARS:]
    season = None
    if len(season_years) >= 3:
        sub_my = my.loc[season_years]
        idx = (sub_my.div(sub_my.mean(axis=1), axis=0)).mean(axis=0)
        lo_m = int(idx.sort_values(kind="mergesort").index[0])
        hi_m = int(idx.sort_values(ascending=False, kind="mergesort").index[0])
        season = {"lo": lo_m, "lo_v": float(idx[lo_m]), "hi": hi_m,
                  "hi_v": float(idx[hi_m]), "y0": season_years[0], "y1": season_years[-1]}

    # ---- weekday ----------------------------------------------------------
    dow = ((sub[dated].dt.dayofweek + 1) % 7).astype(int)  # 0 = Sunday
    dow_c = dow.value_counts().reindex(range(7), fill_value=0)
    weekday = {"x": DAYS_HE, "y": [int(v) for v in dow_c]}
    weekday_rows = [{"day": DAYS_HE[i], "n": n(dow_c[i]),
                     "share": pct_plain(dow_c[i] / n_dated if n_dated else 0)} for i in range(7)]
    workweek_share = float(dow_c[0:5].sum()) / n_dated if n_dated else 0.0

    # ---- districts --------------------------------------------------------
    dist_ok = dist != ""
    dist_pairs = _vc(dist[dist_ok])
    dist_names = [k for k, _ in dist_pairs]
    dct = pd.crosstab(year[dated & dist_ok].astype(int), dist[dated & dist_ok])
    dct = dct.reindex(index=years, columns=dist_names, fill_value=0)
    ref_year = None
    if last_full is not None:
        cands = [y for y in full_years if y <= last_full - LOOKBACK]
        ref_year = cands[-1] if cands else (full_years[0] if len(full_years) > 1 else None)
    district_chart = None
    district_rows = []
    dist_share = {}
    if last_full is not None:
        ly = dct.loc[last_full]
        order = sorted(dist_names, key=lambda d: (-int(ly[d]), d))
        district_chart = {"names": order, "y": [int(ly[d]) for d in order],
                          "year": str(last_full),
                          "ref_year": str(ref_year) if ref_year else "",
                          "ref": [int(dct.at[ref_year, d]) if ref_year else 0 for d in order]}
        tot_ly = float(ly.sum())
        for d in order:
            r = {"name": d, "n": n(ly[d]), "share": pct_plain(ly[d] / tot_ly if tot_ly else 0)}
            if ref_year:
                rv = int(dct.at[ref_year, d])
                r["ref"] = n(rv)
                r["chg"] = signed_pct(ly[d] / rv - 1) if rv else ""
            district_rows.append(r)
        for y in full_years:
            t = float(dct.loc[y].sum())
            if t:
                dist_share[y] = {d: float(dct.at[y, d]) / t for d in dist_names}
    share_lines = {"x": [str(y) for y in dist_share],
                   "series": [{"name": d, "data": [round(dist_share[y][d] * 100, 1) for y in dist_share]}
                              for d in dist_names]}

    # ---- request types ----------------------------------------------------
    type_pairs = _vc(typ[typ != ""])
    types_top = _top(type_pairs, TOP_TYPES)
    type_ly = {}
    if last_full is not None:
        type_ly = dict(_vc(typ[(year == last_full) & (typ != "")]))
    raw_top = [k for k, _ in type_pairs[:TOP_TYPES]]
    other_ly = sum(v for k, v in type_ly.items() if k not in raw_top)
    types_chart = {"names": [a for a, _ in types_top], "y": [v for _, v in types_top]}
    types_rows = []
    for i, (a, v) in enumerate(types_top):
        lyv = type_ly.get(raw_top[i], 0) if i < len(raw_top) else other_ly
        types_rows.append({"name": a, "n": n(v), "share": pct_plain(v / total), "ly": n(lyv)})
    n_types = len(type_pairs)
    top_type_ly = None
    if type_ly:
        tl = sorted(type_ly.items(), key=lambda kv: (-kv[1], kv[0]))
        tot_ly = sum(type_ly.values())
        top_type_ly = {"name": clean(tl[0][0]), "n": tl[0][1], "share": tl[0][1] / tot_ly,
                       "is_copy": tl[0][0] == T_COPY}
        copy_first = years[[i for i, v in enumerate(ct["copy"]) if v > 0][0]] if ct["copy"].sum() else None
        top_type_ly["copy_first"] = copy_first

    # ---- outcomes of core order requests ---------------------------------
    closed_core = is_core & (reason != "")
    reason_all = _vc(reason[closed_core])
    reason_keys = [k for k, _ in reason_all[:TOP_REASONS]]
    outcome = {"cats": [clean(k) for k in reason_keys] + (["אחר"] if len(reason_all) > TOP_REASONS else []),
               "types": [], "series": []}
    outcome_rows = []
    per_type = {}
    for t in CORE:
        m = closed_core & (typ == t)
        cnt = reason[m].value_counts()
        tt = float(cnt.sum())
        vals = [float(cnt.get(k, 0)) for k in reason_keys]
        if len(reason_all) > TOP_REASONS:
            vals.append(tt - sum(vals))
        per_type[t] = {"n": int(tt), "vals": vals,
                       "granted": float(cnt.get(GRANTED, 0)) / tt if tt else 0.0,
                       "court": float(cnt.get(COURT, 0)) / tt if tt else 0.0}
    outcome["types"] = [clean(t) for t in CORE]
    for ci, cat in enumerate(outcome["cats"]):
        outcome["series"].append({"name": cat, "data": [
            round(per_type[t]["vals"][ci] / per_type[t]["n"] * 100, 1) if per_type[t]["n"] else 0
            for t in CORE]})
        outcome_rows.append({"name": cat, "vals": [
            pct_plain(per_type[t]["vals"][ci] / per_type[t]["n"]) if per_type[t]["n"] else "" for t in CORE]})

    # ---- court transfers + objections by year ----------------------------
    court_rate = {}
    for y in years:
        m = closed_core & (year == y)
        c = int(m.sum())
        if c:
            court_rate[y] = float((reason[m] == COURT).sum()) / c
    obj_y = (typ[dated] == T_OBJ).groupby(year[dated].astype(int)).sum().reindex(years, fill_value=0)
    court_chart = {"x": [str(y) for y in years],
                   "rate": [round(court_rate.get(y, 0) * 100, 1) if y in court_rate else None for y in years],
                   "obj": [int(v) for v in obj_y]}
    court_rows = [{"year": str(y), "rate": pct_plain(court_rate[y]) if y in court_rate else "",
                   "obj": n(obj_y[y])} for y in reversed(years)]

    # ---- processing time --------------------------------------------------
    days = (clo - sub).dt.days
    dur_ok = is_core & days.notna() & (days >= 0) & (days <= MAX_DAYS)
    n_dur_excl = int((is_core & days.notna()).sum() - dur_ok.sum())
    dur_y = days[dur_ok].groupby(year[dur_ok].astype(int))
    q = dur_y.quantile([0.25, 0.5, 0.75, 0.9]).unstack()
    dur_years = [y for y in years if y in q.index]
    dur_chart = {"x": [str(y) for y in dur_years],
                 "p25": [int(round(q.at[y, 0.25])) for y in dur_years],
                 "p50": [int(round(q.at[y, 0.5])) for y in dur_years],
                 "p75": [int(round(q.at[y, 0.75])) for y in dur_years],
                 "p90": [int(round(q.at[y, 0.9])) for y in dur_years]}
    dur_rows = [{"year": str(y), "p50": n(round(q.at[y, 0.5])), "p75": n(round(q.at[y, 0.75])),
                 "p90": n(round(q.at[y, 0.9]))} for y in reversed(dur_years)]
    med = {y: float(q.at[y, 0.5]) for y in dur_years}

    # by district, recent full years (boxplot)
    box_years = full_years[-3:]
    box = None
    box_rows = []
    if box_years:
        mb = dur_ok & year.isin(box_years) & dist_ok
        qq = days[mb].groupby(dist[mb]).quantile([0.1, 0.25, 0.5, 0.75, 0.9]).unstack()
        cnt_b = days[mb].groupby(dist[mb]).size()
        order = sorted(qq.index, key=lambda d: (float(qq.at[d, 0.5]), d))
        box = {"names": list(order),
               "data": [[int(round(qq.at[d, p])) for p in (0.1, 0.25, 0.5, 0.75, 0.9)] for d in order],
               "y0": str(box_years[0]), "y1": str(box_years[-1])}
        box_rows = [{"name": d, "p25": n(round(qq.at[d, 0.25])), "p50": n(round(qq.at[d, 0.5])),
                     "p75": n(round(qq.at[d, 0.75])), "p90": n(round(qq.at[d, 0.9])),
                     "n": n(cnt_b[d])} for d in order]

    # decision time (filing to registrar decision), core
    ddays = (dec_d - sub).dt.days
    ddec_ok = is_core & ddays.notna() & (ddays >= 0) & (ddays <= MAX_DAYS)

    # ---- registrar decisions ---------------------------------------------
    dec_pairs = _vc(decision[decision != ""])
    dec_top = _top(dec_pairs, TOP_DECISIONS)
    n_dec = int((decision != "").sum())
    dec_chart = {"names": [a for a, _ in dec_top], "y": [v for _, v in dec_top]}
    dec_rows = [{"name": a, "n": n(v), "share": pct_plain(v / n_dec if n_dec else 0)} for a, v in dec_top]

    # ---- newspaper publication -------------------------------------------
    paper_names = [k for k, _ in _vc(paper[paper != ""])]
    pct_paper = pd.crosstab(year[dated].astype(int), paper[dated]).reindex(index=years, fill_value=0)
    has_pub = pub.notna()
    pub_core = has_pub[is_core & dated].groupby(year[is_core & dated].astype(int)).mean().reindex(years)
    paper_series = []
    for p in paper_names:
        col = pct_paper[p] if p in pct_paper.columns else pd.Series(0, index=years)
        paper_series.append({"name": p, "data": [int(col[y]) for y in years]})
    none_col = pct_paper[""] if "" in pct_paper.columns else pd.Series(0, index=years)
    paper_series.append({"name": "ללא עיתון רשום", "data": [int(none_col[y]) for y in years]})
    paper_chart = {"x": [str(y) for y in years], "series": paper_series,
                   "pub": [round(float(v) * 100, 1) if pd.notna(v) else None for v in pub_core]}
    paper_rows = []
    for y in reversed(years):
        t = int(pct_paper.loc[y].sum())
        r = {"year": str(y), "vals": [], "pub": pct_plain(pub_core[y]) if pd.notna(pub_core[y]) else ""}
        for s in paper_series:
            v = s["data"][years.index(y)]
            r["vals"].append(pct_plain(v / t) if t else "")
        paper_rows.append(r)
    with_paper_years = [y for y in years if int(pct_paper.loc[y].sum() - none_col[y]) > 0]
    last_paper_year = with_paper_years[-1] if with_paper_years else None

    # ---- pending statuses -------------------------------------------------
    open_m = (status != DONE) & (status != "")
    n_open = int(open_m.sum())
    st_top = _top(_vc(status[open_m]), TOP_STATUS)
    status_chart = {"names": [a for a, _ in st_top], "y": [v for _, v in st_top]}
    status_rows = [{"name": a, "n": n(v), "share": pct_plain(v / n_open if n_open else 0)} for a, v in st_top]
    recent_cut = _same_day_prev_year(last_date)
    open_recent = int((open_m & (sub > recent_cut)).sum())
    open_with_close = int((open_m & clo.notna()).sum())

    # ======================================================================
    # KPIs
    kpis = {"total": {"value": total, "display": n(total), "tone": "brand"}}
    labels = {}
    if last_full is not None:
        v = int(yearly_tot[last_full])
        kpis["last_full"] = {"value": v, "display": n(v), "tone": "brand"}
        labels["last_full_kpi"] = f"בקשות שהוגשו בשנת {last_full}"
    if ytd:
        tone = "info" if abs(ytd["chg"]) >= 0.03 else "brand"
        kpis["ytd"] = {"value": round(ytd["chg"] * 100, 1), "display": signed_pct(ytd["chg"]), "tone": tone}
        labels["ytd_kpi"] = (f"שינוי בבקשות מתחילת {last_year} (עד {last_date.day}.{last_date.month}) "
                             f"לעומת התקופה המקבילה ב-{last_year - 1}")
    med_ly = None
    if last_full is not None and last_full in med:
        med_ly = med[last_full]
        base = [y for y in dur_years if y in full_years and y <= last_full - 5]
        tone = "brand"
        if base:
            b = med[base[-1]]
            if b and med_ly <= b * 0.9:
                tone = "ok"
            elif b and med_ly >= b * 1.1:
                tone = "warn"
        kpis["median_days"] = {"value": int(round(med_ly)), "display": n(round(med_ly)), "tone": tone}
        labels["median_days_kpi"] = f"ימים (חציון) מהגשה ועד סגירה, צו ירושה וקיום צוואה, {last_full}"
    if last_full is not None:
        m = closed_core & (year == last_full)
        c = int(m.sum())
        if c:
            g = float((reason[m] == GRANTED).sum()) / c
            kpis["granted"] = {"value": round(g * 100, 1), "display": pct_plain(g), "tone": "brand"}
            labels["granted_kpi"] = f"מהבקשות לצו שנסגרו הסתיימו במתן צו ({last_full})"
    kpi_order = [k for k in ("total", "last_full", "ytd", "median_days", "granted") if k in kpis]
    labels["total_kpi"] = f"בקשות במאגר ({first_year} עד {last_year})"

    # ======================================================================
    # insights
    insights = []

    def add(i, text):
        if text:
            insights.append({"id": i, "text_he": text})

    def ins_growth():
        if last_full is None or ref_year is None or ref_year == last_full:
            return None
        a, b = int(yearly_tot[ref_year]), int(yearly_tot[last_full])
        if not a:
            return None
        r = b / a
        if r >= 1.5:
            return (f"היקף הבקשות גדל פי {LRI}{r:.1f}{PDI} בתוך {last_full - ref_year} שנים: "
                    f"מ-{n(a)} בקשות ב-{ref_year} ל-{n(b)} ב-{last_full}.")
        ch = r - 1
        if abs(ch) < 0.05:
            return f"היקף הבקשות ב-{last_full} ({n(b)}) דומה לזה של {ref_year} ({n(a)})."
        word = "עלה" if ch > 0 else "ירד"
        return f"היקף הבקשות {word} ב-{pct(abs(ch))} בין {ref_year} ({n(a)}) ל-{last_full} ({n(b)})."

    def ins_ytd():
        if not ytd or not partial_last:
            return None
        ch = ytd["chg"]
        span = f"מתחילת {last_year} ועד {d_he(last_date)}"
        if abs(ch) < 0.03:
            return (f"{span} הוגשו {n(ytd['cur'])} בקשות, בדומה לתקופה המקבילה ב-{last_year - 1} "
                    f"({n(ytd['prev'])}).")
        word = "עלייה" if ch > 0 else "ירידה"
        return (f"{span} הוגשו {n(ytd['cur'])} בקשות, {word} של {pct(abs(ch))} לעומת התקופה המקבילה "
                f"ב-{last_year - 1} ({n(ytd['prev'])}).")

    def ins_top_type():
        if not top_type_ly:
            return None
        t = top_type_ly
        if t["is_copy"] and t["copy_first"]:
            return (f"בקשות לקבלת העתק צו, שמופיעות במאגר מאז {t['copy_first']}, הן סוג הבקשה הנפוץ ביותר "
                    f"ב-{last_full}: {n(t['n'])} בקשות ({pct(t['share'])} מכלל הבקשות).")
        return (f"סוג הבקשה הנפוץ ביותר ב-{last_full} הוא \"{t['name']}\": {n(t['n'])} בקשות "
                f"({pct(t['share'])}).")

    def ins_wills():
        if len(will_share) < 2:
            return None
        y0, y1 = list(will_share)[0], list(will_share)[-1]
        a, b = will_share[y0], will_share[y1]
        if abs(b - a) < 0.02:
            return (f"היחס בין בקשות לצו ירושה (ללא צוואה) לבקשות לצו קיום צוואה ב-{y1} דומה לזה של {y0}: "
                    f"הצוואות הן {pct(b)} מהבקשות לצו ב-{y1}, לעומת {pct(a)} ב-{y0}.")
        word = "עלה" if b > a else "ירד"
        return (f"שיעור הבקשות לצו קיום צוואה מתוך הבקשות לצו {word} מ-{pct(a)} ב-{y0} ל-{pct(b)} ב-{y1}; "
                f"השאר הן בקשות לצו ירושה, כשאין צוואה.")

    def ins_district():
        if len(dist_share) < 2 or not dist_names:
            return None
        y0, y1 = list(dist_share)[0], list(dist_share)[-1]
        ranked = sorted(dist_names, key=lambda d: (-dist_share[y1][d], d))
        lead = ranked[0]
        a, b = dist_share[y0][lead], dist_share[y1][lead]
        second = dist_share[y1][ranked[1]] if len(ranked) > 1 else 0.0
        if b < 0.3 or b == second:
            return None
        if abs(b - a) < 0.02:
            head = "מוביל בפער" if b >= 1.5 * second else "מוביל"
            return f"מחוז {lead} {head}: {pct(b)} מהבקשות ב-{y1}, בדומה ל-{y0} ({pct(a)})."
        word = "ירד" if b < a else "עלה"
        lead0, lead1 = int(dct.at[y0, lead]), int(dct.at[y1, lead])
        rest0 = int(dct.loc[y0].sum()) - lead0
        rest1 = int(dct.loc[y1].sum()) - lead1
        tail = ""
        if rest1 > rest0 and lead1 > lead0:
            # both grew; the share moved because one side grew faster
            tail = f", כשהבקשות בשאר המחוזות צמחו {'מהר' if b < a else 'לאט'} יותר"
        return (f"מחוז {lead} מקבל {pct(b)} מהבקשות ב-{y1}, אך חלקו {word} מ-{pct(a)} ב-{y0}"
                f"{tail}.")

    def ins_duration():
        if med_ly is None:
            return None
        cands = [y for y in dur_years if y in full_years and y <= last_full - 5]
        if not cands:
            return None
        peak_pool = [y for y in cands if y >= last_full - LOOKBACK]
        y0 = max(peak_pool, key=lambda y: (med[y], y)) if peak_pool else cands[-1]
        a = med[y0]
        if not a:
            return None
        ch = med_ly / a - 1
        if abs(ch) < 0.1:
            return (f"זמן הטיפול החציוני בבקשה לצו יציב: {n(round(med_ly))} ימים ב-{last_full}, "
                    f"לעומת {n(round(a))} ב-{y0} (בקשות שנסגרו בלבד).")
        word = "התקצר" if ch < 0 else "התארך"
        frm = "משיא של" if (ch < 0 and peak_pool and y0 in peak_pool) else "מ-"
        frm = frm + " " if frm != "מ-" else frm
        return (f"זמן הטיפול החציוני בבקשה לצו {word} {frm}{n(round(a))} ימים ב-{y0} ל-{n(round(med_ly))} "
                f"ב-{last_full} (מהגשה ועד סגירה, בקשות שנסגרו בלבד).")

    def ins_court():
        if last_full is None:
            return None
        y1 = last_full - 2 if (last_full - 2) in court_rate else None
        cands = [y for y in full_years if y in court_rate and y1 is not None and y <= y1 - LOOKBACK + 2]
        if y1 is None or not cands:
            return None
        y0 = cands[-1]
        a, b = court_rate[y0], court_rate[y1]
        if a < 0.01 or abs(b - a) < 0.01:
            return None
        word = "ירד" if b < a else "עלה"
        return (f"שיעור הבקשות לצו שהועברו לבית המשפט (למשל לאחר התנגדות) {word} מ-{pct(a)} "
                f"מהבקשות שהוגשו ב-{y0} ל-{pct(b)} ב-{y1}.")

    def ins_season():
        if not season or season["lo_v"] > 0.92:
            return None
        return (f"עונתיות ברורה: ב-{season['y0']} עד {season['y1']} הוגשו ב{MONTHS_HE[season['lo'] - 1]} "
                f"{pct(1 - season['lo_v'], 0)} פחות בקשות מהחודש הממוצע, וב{MONTHS_HE[season['hi'] - 1]} "
                f"{pct(season['hi_v'] - 1, 0)} יותר.")

    def ins_paper():
        if last_paper_year is None or last_full is None or last_paper_year >= last_full:
            return None
        since = dated & (year > last_paper_year)
        pub_share = float(has_pub[since].mean()) if since.any() else 0.0
        tail = ", אף שתאריך פרסום עדיין מופיע ברובן" if pub_share > 0.5 else ""
        return (f"עד {last_paper_year} נרשם לרוב העיתון שבו פורסמה הודעה על הבקשה; מאז {last_paper_year + 1} "
                f"השדה ריק בכל הבקשות{tail}.")

    def ins_weekday():
        if n_dated < 1000 or workweek_share < 0.85:
            return None
        return (f"{pct(workweek_share)} מהבקשות הוגשו בימים ראשון עד חמישי; ביום ראשון לבדו "
                f"{pct(dow_c[0] / n_dated)}.")

    for i, f in [("growth", ins_growth), ("ytd", ins_ytd), ("top_type", ins_top_type),
                 ("wills", ins_wills), ("district", ins_district), ("duration", ins_duration),
                 ("court", ins_court), ("season", ins_season), ("paper", ins_paper),
                 ("weekday", ins_weekday)]:
        add(i, f())

    # ======================================================================
    # labels / ledes
    lf = last_full if last_full is not None else last_year
    undated_note = (f" {n(n_undated)} בקשות ללא תאריך הגשה תקין אינן נכללות." if n_undated else "")
    partial_note = (f" שנת {last_year} חלקית (עד {d_he(last_date)})." if partial_last else "")
    labels.update({
        "lede": (f"המאגר כולל {n(total)} בקשות שהוגשו לרשם לענייני ירושה של משרד המשפטים מאז {first_year}: "
                 f"בקשות לצו ירושה (כשאין צוואה), לצו קיום צוואה, להעתקי צווים, התנגדויות ובקשות נוספות, "
                 f"עם המחוז, סטטוס הטיפול, החלטת הרשם וסיבת הסגירה. אין במאגר שמות או מספרי זהות."),
        "yearly_note": (f"מספר הבקשות לפי שנת הגשה וסוג.{partial_note}{undated_note}"),
        "yearly_aria": (f"גרף עמודות מוערמות: בקשות לרשם הירושה לפי שנה וסוג, {first_year} עד {last_year}. "
                        f"ב-{lf} הוגשו {n(yearly_tot[lf])} בקשות."),
        "share_note": ("שיעור הבקשות לצו קיום צוואה מתוך כלל הבקשות לצו (צו ירושה וצו קיום צוואה), "
                       "בשנים מלאות בלבד."),
        "share_aria": ("גרף קו: שיעור הבקשות לצו קיום צוואה מתוך הבקשות לצו לפי שנה"
                       + (f", {share_chart['y'][-1]}% ב-{share_chart['x'][-1]}." if share_chart["x"] else ".")),
        "heat_note": (f"בקשות לפי חודש ושנת הגשה; צבע כהה יותר מציין יותר בקשות."
                      + (f" ב-{season['y0']} עד {season['y1']} החודש החלש ביותר הוא {MONTHS_HE[season['lo'] - 1]} "
                         f"והחזק ביותר {MONTHS_HE[season['hi'] - 1]}." if season else "") + partial_note),
        "heat_aria": f"מפת חום: בקשות לרשם הירושה לפי חודש ושנה, {first_year} עד {last_year}.",
        "weekday_note": (f"התפלגות הבקשות לפי יום בשבוע של תאריך ההגשה. {pct(workweek_share)} הוגשו בימים "
                         f"ראשון עד חמישי."),
        "weekday_aria": f"גרף עמודות: בקשות לפי יום בשבוע. {pct_plain(workweek_share)} בימים ראשון עד חמישי.",
        "types_note": (f"{n_types} סוגי בקשות במאגר; {TOP_TYPES if n_types > TOP_TYPES else n_types} "
                       f"הנפוצים מוצגים בנפרד, השאר מקובצים ב\"אחר\"."),
        "types_aria": (f"גרף עמודות אופקי: סוגי הבקשות הנפוצים. המוביל: {types_chart['names'][0]} "
                       f"עם {n(types_chart['y'][0])} בקשות." if types_chart["names"] else "גרף עמודות אופקי: סוגי הבקשות."),
        "outcome_note": (f"סיבת הסגירה של בקשות לצו שנסגרו ({n(per_type[T_INH]['n'])} בקשות לצו ירושה, "
                         f"{n(per_type[T_WILL]['n'])} לצו קיום צוואה), באחוזים."),
        "outcome_aria": (f"גרף עמודות מוערמות: סיבות סגירה של בקשות לצו. צו ניתן ב-{pct_plain(per_type[T_INH]['granted'])} "
                         f"מהבקשות לצו ירושה וב-{pct_plain(per_type[T_WILL]['granted'])} מהבקשות לצו קיום צוואה."),
        "court_note": ("הקו: שיעור הבקשות לצו (ירושה וקיום צוואה) שנסגרו בהעברה לבית המשפט, לפי שנת הגשה. "
                       "העמודות: מספר ההתנגדויות שהוגשו. בשנים האחרונות חלק מהבקשות עדיין פתוחות, "
                       "ולכן השיעור בהן עשוי לעלות."),
        "court_aria": "גרף משולב: שיעור ההעברות לבית המשפט ומספר ההתנגדויות לפי שנה.",
        "dur_note": (f"ימים מהגשת בקשה לצו ועד סגירתה, לפי שנת הגשה: חציון, רבעון עליון ועשירון עליון. "
                     f"בקשות שנסגרו בלבד, בטווח של עד {n(MAX_DAYS)} ימים"
                     + (f" ({n(n_dur_excl)} רשומות עם תאריכים שגויים לא נכללו)" if n_dur_excl else "")
                     + ". בשנים האחרונות הבקשות האיטיות עדיין פתוחות, ולכן הזמנים בהן מוטים כלפי מטה."),
        "dur_aria": (f"גרף קווים: זמן הטיפול בבקשה לצו לפי שנה. חציון של {n(round(med_ly))} ימים ב-{last_full}."
                     if med_ly is not None else "גרף קווים: זמן הטיפול בבקשה לצו לפי שנה."),
        "box_note": (f"פיזור ימי הטיפול בבקשות לצו לפי מחוז, בקשות שהוגשו ב-{box['y0']} עד {box['y1']} ונסגרו. "
                     f"התיבה: רבעון תחתון עד עליון; הקו: חציון; השפמים: עשירון תחתון ועליון." if box else ""),
        "box_aria": (f"תרשים קופסה: זמן הטיפול בבקשה לצו לפי מחוז. החציון הקצר ביותר במחוז {box['names'][0]} "
                     f"({n(box['data'][0][2])} ימים)." if box else ""),
        "dec_note": (f"החלטות הרשם שנרשמו ({n(n_dec)} בקשות עם החלטה, מכל הסוגים)."
                     + (f" חציון הימים מהגשת בקשה לצו ועד החלטת רשם: {n(round(ddays[ddec_ok].median()))}."
                        if ddec_ok.any() else "")),
        "dec_aria": (f"גרף עמודות אופקי: החלטות הרשם. הנפוצה: {dec_chart['names'][0]} ({n(dec_chart['y'][0])})."
                     if dec_chart["names"] else "גרף עמודות אופקי: החלטות הרשם."),
        "paper_note": ("העיתון שנרשם לפרסום ההודעה על הבקשה, לפי שנת הגשה (מספר בקשות). הקו: שיעור הבקשות לצו "
                       "שיש להן תאריך פרסום."
                       + (f" מאז {last_paper_year + 1} לא נרשם עיתון." if last_paper_year and last_paper_year < last_year else "")),
        "paper_aria": "גרף עמודות מוערמות: עיתון הפרסום לפי שנה, עם קו של שיעור הבקשות שפורסמו.",
        "status_note": (f"{n(n_open)} בקשות במאגר אינן בסטטוס \"הטיפול בבקשה הסתיים\"; "
                        f"{n(open_recent)} מהן הוגשו בשנה האחרונה (עד {d_he(last_date)}). "
                        + (f"ל-{n(open_with_close)} מהן כבר רשום תאריך סגירה, כך שהסטטוס אינו תמיד מעודכן."
                         if open_with_close else "")),
        "status_aria": (f"גרף עמודות אופקי: הבקשות שטרם הסתיים הטיפול בהן לפי סטטוס. הנפוץ: "
                        f"{status_chart['names'][0]}." if status_chart["names"] else "גרף עמודות אופקי: סטטוסים."),
        "district_note": (f"בקשות לפי מחוז בשנת {last_full}"
                          + (f", לעומת {ref_year}" if ref_year else "") + "."
                          if last_full is not None else ""),
        "district_aria": (f"גרף עמודות: בקשות לפי מחוז ב-{last_full}. מוביל: מחוז {district_chart['names'][0]} "
                          f"עם {n(district_chart['y'][0])}." if district_chart else ""),
        "dshare_note": "חלקו של כל מחוז מכלל הבקשות בכל שנה מלאה (באחוזים).",
        "dshare_aria": "גרף קווים: חלקם של המחוזות מכלל הבקשות לפי שנה.",
        "ref_year": str(ref_year) if ref_year else "",
        "last_full": str(last_full) if last_full is not None else "",
        "paper_cols": [s["name"] for s in paper_series],
    })

    summary = (f"איתור נתוני בקשות לצו ירושה ולצו קיום צוואה לפי סוג, מחוז וסטטוס: {n(total)} בקשות "
               f"לרשם הירושה מאז {first_year}"
               + (f", {n(yearly_tot[last_full])} ב-{last_full}." if last_full is not None else "."))

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["ירושה", "צוואה", "צו ירושה", "צו קיום צוואה", "רשם הירושה", "עיזבון"],
            "related_ids": ["3111ae54-790a-4d02-9750-d51e1134b405", "13449cdd-9d02-44cf-b298-82f598369cd7",
                            "246d949c-a253-4811-8a11-41a137d3d613"],
            "temporal_coverage": f"{first_year}/{last_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": kpi_order,
        "charts": {
            "yearly": yearly, "share": share_chart, "heat": heat, "weekday": weekday,
            "district": district_chart, "dshare": share_lines, "types": types_chart,
            "outcome": outcome, "court": court_chart, "dur": dur_chart, "box": box,
            "dec": dec_chart, "paper": paper_chart, "status": status_chart,
        },
        "tables": {
            "yearly": yearly_rows, "share": share_rows, "weekday": weekday_rows,
            "district": district_rows, "types": types_rows, "outcome": outcome_rows,
            "court": court_rows, "dur": dur_rows, "box": box_rows, "dec": dec_rows,
            "paper": paper_rows, "status": status_rows,
        },
        "flags": {"district": district_chart is not None, "box": box is not None,
                  "dshare": len(dist_share) >= 2, "share": len(will_share) >= 2,
                  "has_ref": bool(ref_year)},
        "labels": labels,
        "insights": insights,
    }
