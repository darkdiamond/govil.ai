"""Characteristics of education institutions supervised by the Ministry of Education.

One row = one institution (סמל מוסד) in one year: its authority, locality,
sector, supervision stream, legal status, district, framework type, grade
span, founding year, student count and a few program/eligibility flags. The
file is a multi-year panel (2011-2015 when authored); a new year flows
through every chart, and a latest year with far fewer institutions than the
year before is treated as partial (shown, labelled, kept out of comparisons).

Student counts are reported for kindergartens and schools only, so every
student figure covers those two frameworks.

The XLSX export leaves CSV quoting in some values ('"מ""מ"', '"חמ""ד'):
`_unquote` strips it and turns the doubled quote into a gershayim.
"""
import itertools

import numpy as np
import pandas as pd
from govlib import fmt
from govlib.frame import ranked, top_other

KG = "גן ילדים"
SCHOOL = "בית ספר"
GROUP_KG, GROUP_SCHOOL, GROUP_OTHER = "גני ילדים", "בתי ספר", "מסגרות אחרות"
NONE = "לא צוין"
PARTIAL_RATIO = 0.8        # latest year below 80% of the year before = partial
GROWTH_MIN_STUDENTS = 10000  # authorities ranked by growth: at least this many in the base year
TOP_AUTH = 15
TOP_GROWTH = 10
LOW_GROWTH = 5
TOP_SPAN = 7
TOP_LARGEST = 10
BULK_FOUNDING_SHARE = 0.15  # one founding year holding >=15% of institutions = bulk registration
FOUNDING_WINDOW = 25
TREND_PCT = 0.02
SHARE_PP = 0.5

SUPERVISION = {"מ״מ": "ממלכתי", "חמ״ד": "ממלכתי-דתי", "חרדי": "חרדי"}
SUP_ORDER = ["ממלכתי", "ממלכתי-דתי", "חרדי"]
LEGAL = {"ת. י": "תרבותי ייחודי"}
LEGAL_ORDER = ["רשמי", "מוכר", "פטור", "תרבותי ייחודי"]
FRAMEWORK = {
    "מוסד תרב": "מוסד תרבות",
    "השלמת הש": "השלמת השכלה",
    "פנימיה": "פנימייה",
    "מרכז העש": "מרכז העשרה",
    "מוסד ספו": "מוסד ספורט",
    "אוניברסי": "אוניברסיטה",
}
AUTHORITY = {
    "מודיעין מכבים ר": "מודיעין-מכבים-רעות",
    "בנימינה גבעת עד": "בנימינה-גבעת עדה",
}
LOCALITY = {"מודיעין-מכבים-": "מודיעין-מכבים-רעות", "בנימינה-גבעת ע": "בנימינה-גבעת עדה"}
GRADE = {0: "גן", 1: "א", 2: "ב", 3: "ג", 4: "ד", 5: "ה", 6: "ו", 7: "ז", 8: "ח",
         9: "ט", 10: "י", 11: "י״א", 12: "י״ב", 13: "י״ג", 14: "י״ד"}
KG_BINS = [(1, 9, "1-9"), (10, 14, "10-14"), (15, 19, "15-19"), (20, 24, "20-24"),
           (25, 29, "25-29"), (30, 34, "30-34"), (35, 35, "35"), (36, None, "36 ומעלה")]
KG_CAP = 35
PROGRAMS = [
    ("זכאי תשלום בגין מקיף", "תשלום בגין מקיף"),
    ("זכאי שיקום שכונות", "שיקום שכונות"),
    ("זכאי רווחה", "זכאות רווחה"),
    ("זכאי לשכר לימוד", "זכאות לשכר לימוד"),
    ("מגיש לבגרות", "מגיש לבגרות"),
]
NO_YOHA = "ללא יוח״א"


def _unquote(v):
    s = str(v).strip()
    if s.startswith('"'):
        s = s[1:]
        if s.endswith('"') and not s.endswith('""'):
            s = s[:-1]
    return s.replace('""', "״").replace('"', "״").strip()


def _clean(series, mapping=None):
    uniq = {u: _unquote(u) for u in series.unique()}
    if mapping:
        uniq = {k: mapping.get(v, v) for k, v in uniq.items()}
    return series.map(uniq)


def _n(n, one, many):
    """'מוסד אחד' / '1,234 מוסדות'."""
    return one if n == 1 else f"{fmt.int_he(n)} {many}"


def _order(present, known):
    """Known codes first in their fixed order, then any new value by name."""
    return [k for k in known if k in present] + sorted(v for v in present if v not in known)


def _flag(series):
    v = pd.to_numeric(series, errors="coerce")
    return v


def _grade(v):
    if pd.isna(v):
        return None
    i = int(v)
    return GRADE.get(i, str(i))


def compute(frames):
    raw = frames["main"]
    year = pd.to_numeric(raw["שנה"], errors="coerce")
    raw = raw[year.notna().to_numpy()].copy()
    raw["_year"] = year[year.notna()].astype(int).to_numpy()
    # one row per institution-year (the export repeats a handful); sort on
    # every column first so which twin survives never depends on row order
    raw = raw.sort_values(list(raw.columns), kind="stable")
    raw = raw.drop_duplicates(subset=["_year", "סמל מוסד"], keep="first")
    raw = raw.sort_values(["_year", "סמל מוסד"], kind="stable").reset_index(drop=True)

    d = pd.DataFrame({
        "year": raw["_year"].to_numpy(),
        "code": raw["סמל מוסד"].str.strip().to_numpy(),
        "name": _clean(raw["שם מוסד"]).to_numpy(),
        "students": pd.to_numeric(raw["סהכ תלמידים במוסד"], errors="coerce").to_numpy(),
        "authority": _clean(raw["שם רשות"], AUTHORITY).replace("", NONE).to_numpy(),
        "locality": _clean(raw["שם ישוב"], LOCALITY).replace("", NONE).to_numpy(),
        "sector": _clean(raw["מגזר"]).replace("", NONE).to_numpy(),
        "sup": _clean(raw["פיקוח"], SUPERVISION).replace("", NONE).to_numpy(),
        "legal": _clean(raw["מעמד משפטי"], LEGAL).replace("", NONE).to_numpy(),
        "district": _clean(raw["מחוז גאוגרפי"]).replace("", NONE).to_numpy(),
        "edtype": _clean(raw["סוג חינוך מוסד"]).to_numpy(),
        "frame": _clean(raw["סוג מסגרת אירגונית"], FRAMEWORK).replace("", NONE).to_numpy(),
        "itype": _clean(raw["סוג מוסד"]).replace("", NONE).to_numpy(),
        "lo": pd.to_numeric(raw["משכבה"], errors="coerce").to_numpy(),
        "hi": pd.to_numeric(raw["עד שכבה"], errors="coerce").to_numpy(),
        "founded": pd.to_numeric(raw["שנת יסוד"], errors="coerce").to_numpy(),
        "yoha": _clean(raw["תאור יוחא"]).to_numpy(),
        "gmul": _clean(raw["גמול הכנה לבגרות"]).to_numpy(),
        "hakara": _clean(raw["הכרה בציון שנתי"]).to_numpy(),
        "track": _clean(raw["חינוך לבגרות"]).to_numpy(),
    })
    for col, _ in PROGRAMS:
        d[col] = _flag(raw[col]).to_numpy()
    d["group"] = np.where(d["frame"] == KG, GROUP_KG,
                          np.where(d["frame"] == SCHOOL, GROUP_SCHOOL, GROUP_OTHER))
    d["formal"] = d["frame"].isin([KG, SCHOOL])

    years = sorted(int(y) for y in d["year"].unique())
    if not years:
        raise ValueError("no rows with a year")
    count_by_year = d.groupby("year").size()
    partial = (len(years) >= 2
               and count_by_year[years[-1]] < PARTIAL_RATIO * count_by_year[years[-2]])
    complete = years[:-1] if partial else years
    ref = complete[-1]
    y0 = years[0]
    has_trend = len(complete) >= 2
    ylab = [f"{y} (חלקי)" if (partial and y == years[-1]) else str(y) for y in years]

    R = d[d["year"] == ref]
    F = d[d["formal"]]
    RF = R[R["formal"]]
    n_ref = len(R)
    n_y0 = int(count_by_year[y0])

    # ---- 1. institutions per year by framework group ----------------------
    groups = [GROUP_KG, GROUP_SCHOOL, GROUP_OTHER]
    gy = d.groupby(["year", "group"]).size().unstack(fill_value=0).reindex(
        index=years, columns=groups, fill_value=0)
    trend = {"x": ylab, "series": [{"name": g, "data": [int(v) for v in gy[g]]} for g in groups],
             "total": [int(v) for v in gy.sum(axis=1)]}
    trend_rows = [[ylab[i]] + [fmt.int_he(gy.iloc[i][g]) for g in groups]
                  + [fmt.int_he(trend["total"][i])] for i in range(len(years))]

    # ---- 2. students per year: kindergartens vs schools -------------------
    sy = F.groupby(["year", "frame"])["students"].sum().unstack(fill_value=0).reindex(
        index=years, columns=[KG, SCHOOL], fill_value=0)
    miss = F[F["students"].isna()].groupby("year").size().reindex(years, fill_value=0)
    students = {"x": ylab, "kg": [int(v) for v in sy[KG]], "school": [int(v) for v in sy[SCHOOL]]}
    stud_rows = [[ylab[i], fmt.int_he(sy.iloc[i][KG]), fmt.int_he(sy.iloc[i][SCHOOL]),
                  fmt.int_he(sy.iloc[i].sum()), fmt.int_he(miss.iloc[i])] for i in range(len(years))]
    st_ref = float(sy.loc[ref].sum())
    st_y0 = float(sy.loc[y0].sum())
    miss_ref = int(miss.loc[ref])

    # ---- 3. supervision share of students ---------------------------------
    sup_present = set(F.loc[F["students"].fillna(0) > 0, "sup"])
    sup_cats = _order(sup_present, SUP_ORDER + [NONE])
    sp = F.groupby(["year", "sup"])["students"].sum().unstack(fill_value=0).reindex(
        index=years, columns=sup_cats, fill_value=0)
    sp_tot = sp.sum(axis=1).replace(0, np.nan)
    sp_share = sp.div(sp_tot, axis=0).fillna(0)
    supervision = {"x": ylab, "series": [
        {"name": c, "share": [round(float(v) * 100, 1) for v in sp_share[c]],
         "count": [int(v) for v in sp[c]]} for c in sup_cats]}
    sup_rows = [[ylab[i]] + [f"{fmt.int_he(sp.iloc[i][c])} ({fmt.pct(sp_share.iloc[i][c])})"
                             for c in sup_cats] for i in range(len(years))]

    # ---- 4. sector --------------------------------------------------------
    sec_ref = RF.groupby("sector")["students"].sum()
    sec_ref = sec_ref[sec_ref > 0]
    sec_order = list(sec_ref.sort_index().sort_values(ascending=False, kind="stable").index)
    sec_y0 = F[F["year"] == y0].groupby("sector")["students"].sum()
    sec_inst = RF.groupby("sector").size()
    sector = {"names": sec_order, "ref": [int(sec_ref[s]) for s in sec_order],
              "base": [int(sec_y0.get(s, 0)) for s in sec_order]}
    sec_growth = {}
    for s in sec_order:
        b = float(sec_y0.get(s, 0))
        sec_growth[s] = (float(sec_ref[s]) / b - 1) if b > 0 else None
    sector["growth"] = [None if sec_growth[s] is None else round(sec_growth[s] * 100, 1)
                        for s in sec_order]
    sec_rows = [[s, fmt.int_he(sec_inst.get(s, 0)), fmt.int_he(sec_ref[s]),
                 fmt.pct(sec_ref[s] / sec_ref.sum()),
                 (fmt.signed_pct(sec_growth[s]) if (has_trend and sec_growth[s] is not None) else "")]
                for s in sec_order]

    # ---- 5. district x sector --------------------------------------------
    dist_st = RF.groupby("district")["students"].sum()
    dist_st = dist_st[dist_st > 0]
    dist_order = list(dist_st.sort_index().sort_values(ascending=False, kind="stable").index)
    ds = RF.groupby(["district", "sector"])["students"].sum().unstack(fill_value=0).reindex(
        index=dist_order, columns=sec_order, fill_value=0)
    dist_inst = R.groupby("district").size()
    district = {"names": dist_order,
                "series": [{"name": s, "data": [int(v) for v in ds[s]]} for s in sec_order]}
    dist_rows = [[n, fmt.int_he(dist_inst.get(n, 0)), fmt.int_he(dist_st[n]),
                  fmt.pct(dist_st[n] / dist_st.sum())] for n in dist_order]

    # ---- 6. authorities ---------------------------------------------------
    au_ref = RF.groupby("authority")["students"].sum()
    au_ref = au_ref[(au_ref > 0) & (au_ref.index != NONE)]
    au_top = au_ref.sort_index().sort_values(ascending=False, kind="stable").head(TOP_AUTH)
    au_y0 = F[F["year"] == y0].groupby("authority")["students"].sum()
    au_inst = RF.groupby("authority").size()
    authorities = {"names": list(au_top.index), "values": [int(v) for v in au_top]}
    au_rows = []
    for a in au_top.index:
        b = float(au_y0.get(a, 0))
        g = fmt.signed_pct(au_top[a] / b - 1) if (has_trend and b > 0) else ""
        au_rows.append([a, fmt.int_he(au_inst.get(a, 0)), fmt.int_he(au_top[a]), g])

    # ---- 7. authority growth ---------------------------------------------
    growth = None
    growth_rows = []
    gtab = None
    if has_trend:
        base = au_y0[(au_y0 >= GROWTH_MIN_STUDENTS) & (au_y0.index != NONE)]
        both = [a for a in base.index if a in au_ref.index]
        if len(both) >= 3:
            gtab = pd.DataFrame({"base": [float(base[a]) for a in both],
                                 "ref": [float(au_ref[a]) for a in both]}, index=both)
            gtab["g"] = gtab["ref"] / gtab["base"] - 1
            gtab = gtab.sort_index().sort_values("g", ascending=False, kind="stable")
            top = gtab.head(TOP_GROWTH)
            rest = gtab.iloc[TOP_GROWTH:]
            low = rest.tail(LOW_GROWTH) if len(rest) else rest.iloc[0:0]
            shown = pd.concat([top, low])
            growth = {"names": list(shown.index), "values": [round(float(v) * 100, 1) for v in shown["g"]],
                      "n_pool": len(gtab)}
            growth_rows = [[a, fmt.int_he(r["base"]), fmt.int_he(r["ref"]), fmt.signed_pct(r["g"])]
                           for a, r in shown.iterrows()]

    # ---- 8. school grade span --------------------------------------------
    RS = R[R["frame"] == SCHOOL]
    spans = []
    for lo, hi in zip(RS["lo"], RS["hi"]):
        gl, gh = _grade(lo), _grade(hi)
        if gl is None or gh is None:
            spans.append(NONE)
        elif gl == gh:
            spans.append(f"כיתה {gl}")
        else:
            spans.append(f"{gl}-{gh}")
    span_counts = ranked(pd.Series(spans, dtype=object)) if spans else pd.Series(dtype=int)
    span_l, span_v = top_other(span_counts, TOP_SPAN) if len(span_counts) else ([], [])
    span = {"names": span_l, "values": [int(v) for v in span_v]}
    span_rows = [[l, fmt.int_he(v), fmt.pct(v / max(1, len(RS)))] for l, v in zip(span_l, span_v)]

    # ---- 9. school size by supervision (boxplot) --------------------------
    size = {"names": [], "box": [], "n": []}
    size_rows = []
    RSn = RS[RS["students"] > 0]
    for c in _order(set(RSn["sup"]), SUP_ORDER + [NONE]):
        v = RSn.loc[RSn["sup"] == c, "students"].to_numpy(dtype=float)
        if len(v) < 5:
            continue
        q = np.percentile(v, [5, 25, 50, 75, 95])
        size["names"].append(c)
        size["box"].append([round(float(x), 1) for x in q])
        size["n"].append(len(v))
        size_rows.append([c, fmt.int_he(len(v)), fmt.int_he(q[1]), fmt.int_he(q[2]), fmt.int_he(q[3])])
    school_zero = int(len(RS) - len(RSn))

    # ---- 10. kindergarten size -------------------------------------------
    RK = R[R["frame"] == KG]
    kv = RK["students"]
    kpos = kv[kv > 0]
    kg_bins = []
    for lo, hi, lab in KG_BINS:
        m = (kpos >= lo) if hi is None else ((kpos >= lo) & (kpos <= hi))
        kg_bins.append([lab, int(m.sum())])
    kg_size = {"names": [b[0] for b in kg_bins], "values": [b[1] for b in kg_bins]}
    kg_rows = [[b[0], fmt.int_he(b[1]), fmt.pct(b[1] / max(1, len(kpos)))] for b in kg_bins]
    kg_excluded = int(len(RK) - len(kpos))
    kg_median = float(np.median(kpos)) if len(kpos) else None
    kg_at_cap = int((kpos >= KG_CAP).sum())

    # ---- 11. legal status by supervision ---------------------------------
    leg_cats = _order(set(RF["legal"]) - {NONE}, LEGAL_ORDER)
    lsup_cats = _order(set(RF["sup"]) - {NONE}, SUP_ORDER)
    ls = RF.groupby(["sup", "legal"]).size().unstack(fill_value=0).reindex(
        index=lsup_cats, columns=leg_cats, fill_value=0)
    legal = {"names": lsup_cats, "series": [{"name": c, "data": [int(v) for v in ls[c]]} for c in leg_cats]}
    legal_rows = [[s] + [fmt.int_he(ls.loc[s, c]) for c in leg_cats] for s in lsup_cats]

    # ---- 12. special education -------------------------------------------
    sp_y = F[F["edtype"] == "מיוחד"].groupby("year").size().reindex(years, fill_value=0)
    all_y = F[F["edtype"] != ""].groupby("year").size().reindex(years, fill_value=0)
    sp_share_y = (sp_y / all_y.replace(0, np.nan)).fillna(0)
    sp_st = F[F["edtype"] == "מיוחד"].groupby("year")["students"].sum().reindex(years, fill_value=0)
    special = {"x": ylab, "count": [int(v) for v in sp_y],
               "share": [round(float(v) * 100, 2) for v in sp_share_y]}
    special_rows = [[ylab[i], fmt.int_he(sp_y.iloc[i]), fmt.pct(sp_share_y.iloc[i]),
                     fmt.int_he(sp_st.iloc[i])] for i in range(len(years))]

    # ---- 13. programs among schools --------------------------------------
    prog = []
    yo = RS["yoha"]
    yo_known = yo[yo != ""]
    if len(yo_known):
        k = int((yo_known != NO_YOHA).sum())
        prog.append(["יום חינוך ארוך (יוח״א)", k, len(yo_known)])
    for col, lab in PROGRAMS:
        v = RS[col].dropna()
        if len(v):
            prog.append([lab, int((v == 1).sum()), len(v)])
    prog.sort(key=lambda p: (-p[1], p[0]))
    programs = {"names": [p[0] for p in prog],
                "share": [round(p[1] / p[2] * 100, 1) for p in prog],
                "count": [p[1] for p in prog]}
    prog_rows = [[p[0], fmt.int_he(p[1]), fmt.int_he(p[2]), fmt.pct(p[1] / p[2])] for p in prog]
    yoha_types = ranked(yo_known[yo_known != NO_YOHA]) if len(yo_known) else pd.Series(dtype=int)
    yoha_rows = [[str(k), fmt.int_he(v)] for k, v in yoha_types.items()]

    # ---- 14. bagrut track -------------------------------------------------
    tr = ranked(R.loc[R["track"] != "", "track"])
    track = {"names": [str(k) for k in tr.index], "values": [int(v) for v in tr]}
    track_rows = [[str(k), fmt.int_he(v)] for k, v in tr.items()]
    gm = ranked(R.loc[R["gmul"] != "", "gmul"])
    gmul_rows = [[str(k), fmt.int_he(v)] for k, v in gm.items()]
    hk = ranked(R.loc[R["hakara"] != "", "hakara"])
    hakara_rows = [[str(k), fmt.int_he(v)] for k, v in hk.items()]

    # ---- 15. founding years ----------------------------------------------
    fy = R["founded"].dropna().astype(int)
    founding = None
    founding_rows = []
    bulk = None
    if len(fy):
        fc = fy.value_counts().sort_index()
        top_year = int(fc.sort_values(ascending=False, kind="stable").index[0])
        if fc[top_year] / len(fy) >= BULK_FOUNDING_SHARE:
            bulk = {"year": top_year, "n": int(fc[top_year]), "share": float(fc[top_year] / len(fy))}
        fmax = int(fc.index.max())
        start = (bulk["year"] + 1) if bulk else fmax - FOUNDING_WINDOW + 1
        start = max(start, fmax - FOUNDING_WINDOW + 1)
        early = int(fc[fc.index < start].sum())
        xs = [f"עד {start - 1}"] + [str(y) for y in range(start, fmax + 1)]
        vs = [early] + [int(fc.get(y, 0)) for y in range(start, fmax + 1)]
        founding = {"x": xs, "values": vs}
        founding_rows = [[x, fmt.int_he(v)] for x, v in zip(xs, vs)]
    founded_missing = int(len(R) - len(fy))

    # ---- 16. openings and closings ---------------------------------------
    sets = {y: set(d.loc[d["year"] == y, "code"]) for y in years}
    churn = {"x": [], "new": [], "gone": [], "pairs": []}
    churn_rows = []
    for a, b in itertools.pairwise(years):
        lab = f"{a}-{b}" + (" (חלקי)" if partial and b == years[-1] else "")
        nw, gn = len(sets[b] - sets[a]), len(sets[a] - sets[b])
        churn["x"].append(lab)
        churn["pairs"].append([a, b])
        churn["new"].append(nw)
        churn["gone"].append(-gn)
        churn_rows.append([lab, fmt.int_he(nw), fmt.int_he(gn), f"{nw - gn:+,}".replace("-", "−")])

    # ---- 17. other frameworks (treemap) ----------------------------------
    RO = R[~R["formal"]]
    fr_counts = ranked(RO["frame"])
    tree = []
    for fname, cnt in fr_counts.items():
        sub = ranked(RO.loc[RO["frame"] == fname, "itype"])
        tree.append({"name": str(fname), "value": int(cnt),
                     "children": [{"name": str(k), "value": int(v)} for k, v in sub.items()]})
    frame_rows = [[str(k), fmt.int_he(v)] for k, v in fr_counts.items()]

    # ---- 18. largest schools ---------------------------------------------
    big = RS[RS["students"] > 0].sort_values(["students", "code"], ascending=[False, True],
                                             kind="stable").head(TOP_LARGEST)
    largest_rows = [[r["name"], r["code"], r["locality"], r["sup"], fmt.int_he(r["students"])]
                    for _, r in big.iterrows()]

    # ---- KPIs -------------------------------------------------------------
    n_kg_ref = int((R["frame"] == KG).sum())
    n_sc_ref = int((R["frame"] == SCHOOL).sum())
    inst_g = (n_ref / n_y0 - 1) if (has_trend and n_y0) else None
    n_auth = int(R.loc[R["authority"] != NONE, "authority"].nunique())
    kpis = {
        "inst": {"value": n_ref, "display": fmt.int_he(n_ref), "tone": "brand"},
        "students": {"value": int(st_ref), "display": fmt.int_he(st_ref), "tone": "brand"},
        "kg": {"value": n_kg_ref, "display": fmt.int_he(n_kg_ref), "tone": "brand"},
        "schools": {"value": n_sc_ref, "display": fmt.int_he(n_sc_ref), "tone": "brand"},
        "auth": {"value": n_auth, "display": fmt.int_he(n_auth), "tone": "brand"},
    }
    if inst_g is not None:
        kpis["growth"] = {"value": round(inst_g * 100, 1), "display": fmt.signed_pct(inst_g),
                          "tone": "ok" if inst_g > TREND_PCT else ("danger" if inst_g < -TREND_PCT else "info")}

    # ---- insights ---------------------------------------------------------
    ins = []

    def add(i, t):
        if t:
            ins.append({"id": i, "text_he": t})

    partial_note = (f" שנת {years[-1]} נראית חלקית ({_n(int(count_by_year[years[-1]]), 'מוסד אחד', 'מוסדות')} בלבד)"
                    f" ולכן אינה נכללת בהשוואה." if partial else "")

    def i_growth():
        if inst_g is None:
            return None
        if abs(inst_g) < TREND_PCT:
            return (f"מספר המוסדות בפיקוח המשרד נותר כמעט יציב: {fmt.int_he(n_y0)} ב-{y0} "
                    f"ו-{fmt.int_he(n_ref)} ב-{ref}.{partial_note}")
        w = "עלה" if inst_g > 0 else "ירד"
        return (f"מספר המוסדות בפיקוח המשרד {w} מ-{fmt.int_he(n_y0)} ב-{y0} ל-{fmt.int_he(n_ref)} ב-{ref} "
                f"({fmt.signed_pct(inst_g)}).{partial_note}")
    add("growth", i_growth())

    def i_kg_vs_school():
        if not has_trend:
            return None
        k0, k1 = int(gy.loc[y0, GROUP_KG]), int(gy.loc[ref, GROUP_KG])
        s0, s1 = int(gy.loc[y0, GROUP_SCHOOL]), int(gy.loc[ref, GROUP_SCHOOL])
        if not (k0 and s0):
            return None
        gk, gs = k1 / k0 - 1, s1 / s0 - 1
        if abs(gk - gs) < TREND_PCT:
            return None
        if gk > gs:
            return (f"גני הילדים הם עיקר הגידול: בין {y0} ל-{ref} מספרם השתנה מ-{fmt.int_he(k0)} "
                    f"ל-{fmt.int_he(k1)} ({fmt.signed_pct(gk)}), לעומת {fmt.signed_pct(gs)} בבתי הספר "
                    f"({fmt.int_he(s0)} ל-{fmt.int_he(s1)}).")
        return (f"בתי הספר גדלו מהר יותר מגני הילדים: בין {y0} ל-{ref} מספרם השתנה מ-{fmt.int_he(s0)} "
                f"ל-{fmt.int_he(s1)} ({fmt.signed_pct(gs)}), לעומת {fmt.signed_pct(gk)} בגני הילדים.")
    add("kg_vs_school", i_kg_vs_school())

    def i_students():
        if not has_trend or st_y0 <= 0:
            return None
        g = st_ref / st_y0 - 1
        w = "גדל" if g > 0 else "קטן"
        return (f"בגני הילדים ובבתי הספר רשומים {fmt.int_he(st_ref)} תלמידים ב-{ref}. "
                f"המספר {w} ב-{fmt.pct(abs(g))} מאז {y0} ({fmt.int_he(st_y0)}).")
    add("students", i_students())

    def i_haredi():
        c = "חרדי"
        if not has_trend or c not in sp_share.columns:
            return None
        a, b = float(sp_share.loc[y0, c]) * 100, float(sp_share.loc[ref, c]) * 100
        diff = b - a
        if abs(diff) < SHARE_PP:
            return (f"חלקו של הפיקוח החרדי בתלמידי הגנים ובתי הספר יציב: {fmt.pct_of(a)} ב-{y0} "
                    f"ו-{fmt.pct_of(b)} ב-{ref}.")
        w = "עלה" if diff > 0 else "ירד"
        return (f"חלקו של הפיקוח החרדי בתלמידי הגנים ובתי הספר {w} מ-{fmt.pct_of(a)} ב-{y0} "
                f"ל-{fmt.pct_of(b)} ב-{ref} ({fmt.int_he(sp.loc[ref, c])} תלמידים).")
    add("haredi", i_haredi())

    def i_fast_auth():
        if gtab is None or gtab.empty:
            return None
        a = gtab.index[0]
        r = gtab.iloc[0]
        if r["g"] <= TREND_PCT:
            return None
        txt = (f"מבין {_n(len(gtab), 'רשות אחת', 'רשויות')} עם {fmt.int_he(GROWTH_MIN_STUDENTS)} תלמידים "
               f"לפחות ב-{y0}, הגידול המהיר ביותר נרשם ב{a}: {fmt.signed_pct(r['g'])} "
               f"({fmt.int_he(r['base'])} ל-{fmt.int_he(r['ref'])} תלמידים).")
        neg = gtab[gtab["g"] < 0]
        if len(neg):
            names = fmt.join_he(list(neg.sort_values("g", kind="stable").index[:3]))
            txt += (f" ירידה נרשמה ב-{fmt.int_he(len(neg))} רשויות" + (": " if len(neg) <= 3 else ", בהן ")
                    + f"{names}.") if len(neg) > 1 else \
                f" ירידה נרשמה רק ב{neg.index[0]} ({fmt.signed_pct(neg['g'].iloc[0])})."
        return txt
    add("fast_auth", i_fast_auth())

    def i_special():
        if not has_trend:
            return None
        a, b = int(sp_y.loc[y0]), int(sp_y.loc[ref])
        if a == 0:
            return None
        g = b / a - 1
        reg0 = int(all_y.loc[y0]) - a
        reg1 = int(all_y.loc[ref]) - b
        if reg0 <= 0:
            return None
        gr = reg1 / reg0 - 1
        if g - gr < TREND_PCT:
            return None
        return (f"מוסדות החינוך המיוחד גדלו מהר יותר מהחינוך הרגיל: {fmt.int_he(a)} ב-{y0} ו-{fmt.int_he(b)} "
                f"ב-{ref} ({fmt.signed_pct(g)}), לעומת {fmt.signed_pct(gr)} במוסדות הרגילים.")
    add("special", i_special())

    def i_district():
        if not dist_order:
            return None
        top = dist_order[0]
        sh = float(dist_st[top] / dist_st.sum())
        if sh < 0.15:
            return None
        return (f"מחוז {top} מוביל במספר התלמידים: {fmt.int_he(dist_st[top])} ב-{ref}, "
                f"{fmt.pct(sh)} מכלל תלמידי הגנים ובתי הספר.")
    add("district", i_district())

    def i_kg_cap():
        if not len(kpos) or kg_median is None:
            return None
        sh = kg_at_cap / len(kpos)
        if sh < 0.05:
            return None
        return (f"בגן ילדים טיפוסי רשומים {fmt.int_he(kg_median)} ילדים (חציון, {ref}), "
                f"ו-{fmt.int_he(kg_at_cap)} גנים ({fmt.pct(sh)}) מדווחים על {fmt.int_he(KG_CAP)} ילדים או יותר.")
    add("kg_cap", i_kg_cap())

    def i_churn():
        if not churn["x"]:
            return None
        i = len(churn["x"]) - (2 if partial and len(churn["x"]) >= 2 else 1)
        if partial and len(churn["x"]) < 2:
            return None
        nw, gn = churn["new"][i], -churn["gone"][i]
        return (f"בין {churn['pairs'][i][0]} ל-{churn['pairs'][i][1]} נוספו {fmt.int_he(nw)} סמלי מוסד חדשים ו-{fmt.int_he(gn)} "
                f"סמלים לא הופיעו עוד, תוספת נטו של {fmt.int_he(nw - gn)} מוסדות.") if nw >= gn else (
                f"בין {churn['pairs'][i][0]} ל-{churn['pairs'][i][1]} נוספו {fmt.int_he(nw)} סמלי מוסד חדשים ו-{fmt.int_he(gn)} "
                f"סמלים לא הופיעו עוד, ירידה נטו של {fmt.int_he(gn - nw)} מוסדות.")
    add("churn", i_churn())

    # ---- labels -----------------------------------------------------------
    top_sector = sec_order[0] if sec_order else None
    # sectors whose students sit (>=90%) under state supervision, other than the Jewish one
    st_sup = RF.groupby(["sector", "sup"])["students"].sum()
    under_state = []
    for sct in sec_order:
        if sct in ("יהודי", NONE) or sec_ref[sct] <= 0:
            continue
        if float(st_sup.get((sct, "ממלכתי"), 0)) / float(sec_ref[sct]) >= 0.9:
            under_state.append(sct)
    state_note = (f" בפיקוח הממלכתי נמצאים גם רוב תלמידי המגזרים {fmt.join_he(under_state)}."
                  if len(under_state) > 1 else
                  (f" בפיקוח הממלכתי נמצאים גם רוב תלמידי המגזר ה{under_state[0]}." if under_state else ""))
    sup_last = {c: float(sp_share.loc[ref, c]) for c in sup_cats}
    sup_lead = max(sup_cats, key=lambda c: (sup_last[c], c)) if sup_cats else None
    labels = {
        "trend_lede": (f"ב-{ref} פעלו {fmt.int_he(n_ref)} מוסדות: {fmt.int_he(n_kg_ref)} גני ילדים, "
                       f"{fmt.int_he(n_sc_ref)} בתי ספר ו-{fmt.int_he(n_ref - n_kg_ref - n_sc_ref)} מסגרות אחרות "
                       f"(השלמת השכלה, פנימיות, מוסדות תרבות וספורט ועוד)."
                       + (f" שנת {years[-1]} מסומנת כחלקית." if partial else "")),
        "trend_aria": f"גרף עמודות מוערמות: מספר מוסדות החינוך לפי סוג מסגרת בשנים {y0}-{years[-1]}. ב-{ref}: {fmt.int_he(n_ref)} מוסדות.",
        "students_lede": (f"מספר התלמידים מדווח לגני ילדים ולבתי ספר בלבד. ב-{ref} נמנו {fmt.int_he(st_ref)} תלמידים"
                          + (f"; ל-{_n(miss_ref, 'מוסד אחד', 'מוסדות')} מהם לא דווח מספר תלמידים." if miss_ref else ".")),
        "students_aria": f"גרף עמודות מוערמות: תלמידים בגני ילדים ובבתי ספר לפי שנה. ב-{ref}: {fmt.int_he(st_ref)} תלמידים.",
        "sup_lede": (f"חלוקת התלמידים בין זרמי הפיקוח. ב-{ref} הזרם הגדול: {sup_lead} "
                     f"({fmt.pct(sup_last[sup_lead])})." + state_note
                     if sup_lead else ""),
        "sup_aria": f"גרף עמודות 100%: חלוקת התלמידים לפי זרם פיקוח בכל שנה, {y0}-{years[-1]}.",
        "sector_lede": (f"תלמידי הגנים ובתי הספר ב-{ref} לפי מגזר. המגזר הגדול: {top_sector} "
                        f"({fmt.pct(sec_ref[top_sector] / sec_ref.sum())} מהתלמידים)"
                        + (f"; לצד כל עמודה מוצג השינוי מאז {y0}." if has_trend else ".")) if top_sector else "",
        "sector_aria": f"גרף עמודות: תלמידים לפי מגזר ב-{ref}.",
        "district_lede": f"תלמידי הגנים ובתי הספר בכל מחוז גאוגרפי ב-{ref}, בחלוקה לפי מגזר.",
        "district_aria": f"גרף עמודות אופקיות מוערמות: תלמידים לפי מחוז ומגזר ב-{ref}.",
        "auth_lede": (f"{fmt.int_he(len(au_top))} הרשויות המקומיות עם מספר התלמידים הגבוה ביותר ב-{ref}, "
                      f"מתוך {fmt.int_he(n_auth)} רשויות במאגר."),
        "auth_aria": (f"גרף עמודות אופקיות: {fmt.int_he(len(au_top))} הרשויות עם הכי הרבה תלמידים ב-{ref}. "
                      f"בראש: {au_top.index[0]} עם {fmt.int_he(au_top.iloc[0])}." if len(au_top) else ""),
        "growth_lede": (f"שינוי במספר התלמידים בין {y0} ל-{ref}, ברשויות שהיו בהן {fmt.int_he(GROWTH_MIN_STUDENTS)} "
                        f"תלמידים לפחות ב-{y0} ({_n(growth['n_pool'], 'רשות אחת', 'רשויות')}). מוצגות "
                        f"{fmt.int_he(min(TOP_GROWTH, growth['n_pool']))} הרשויות שגדלו הכי מהר"
                        + (f" ו-{fmt.int_he(len(growth['names']) - min(TOP_GROWTH, growth['n_pool']))} שגדלו הכי לאט."
                           if len(growth["names"]) > TOP_GROWTH else ".")) if growth else "",
        "growth_aria": (f"גרף עמודות אופקיות: שינוי באחוזים במספר התלמידים ברשויות הגדולות, {y0}-{ref}. "
                        f"הגידול המהיר ביותר: {growth['names'][0]}." if growth else ""),
        "span_lede": (f"טווח הכיתות של {fmt.int_he(len(RS))} בתי הספר ב-{ref}. "
                      f"המבנה הנפוץ: {span_l[0]} ({fmt.pct(span_v[0] / max(1, len(RS)))})."
                      if span_l else ""),
        "span_aria": f"גרף עמודות: בתי ספר לפי טווח כיתות ב-{ref}.",
        "size_lede": (f"התפלגות מספר התלמידים בבית ספר לפי זרם פיקוח ב-{ref}: הקופסה מאחוזון 25 עד אחוזון 75, "
                      f"הקו בחציון, השפמים מאחוזון 5 עד אחוזון 95."
                      + (f" לא נכללו {_n(school_zero, 'בית ספר אחד', 'בתי ספר')} בלי תלמידים מדווחים." if school_zero else "")),
        "size_aria": f"תרשים קופסה: גודל בתי הספר לפי זרם פיקוח ב-{ref}.",
        "kg_lede": (f"מספר הילדים בגן ב-{ref}, ב-{_n(len(kpos), 'גן אחד', 'גנים')}. החציון: {fmt.int_he(kg_median)} ילדים."
                    + (f" לא נכללו {_n(kg_excluded, 'גן אחד', 'גנים')} בלי ילדים מדווחים." if kg_excluded else ""))
                   if kg_median is not None else "",
        "kg_aria": f"היסטוגרמה: גני ילדים לפי מספר הילדים בגן ב-{ref}.",
        "legal_lede": (f"מעמדם המשפטי של גני הילדים ובתי הספר ב-{ref} בכל זרם פיקוח: מוסד רשמי של המדינה "
                       f"או הרשות, מוכר שאינו רשמי, פטור, או מוסד תרבותי ייחודי."),
        "legal_aria": f"גרף עמודות מוערמות: גני ילדים ובתי ספר לפי זרם פיקוח ומעמד משפטי ב-{ref}.",
        "special_lede": (f"גני ילדים ובתי ספר של החינוך המיוחד. ב-{ref}: {fmt.int_he(sp_y.loc[ref])} מוסדות, "
                         f"{fmt.pct(sp_share_y.loc[ref])} מהגנים ובתי הספר."),
        "special_aria": f"גרף עמודות וקו: מוסדות החינוך המיוחד ושיעורם לפי שנה, {y0}-{years[-1]}.",
        "prog_lede": (f"שיעור בתי הספר ב-{ref} שמשתתפים בכל תכנית או זכאים לה, מתוך בתי הספר שעבורם יש נתון."),
        "prog_aria": f"גרף עמודות אופקיות: שיעור בתי הספר בתכניות ובזכאויות ב-{ref}.",
        "track_lede": (f"{_n(int(sum(track['values'])), 'מוסד אחד', 'מוסדות')} ב-{ref} מסווגים לפי מסלול החינוך לבגרות."
                       if track["values"] else ""),
        "track_aria": f"גרף עמודות: מוסדות לפי מסלול החינוך לבגרות ב-{ref}.",
        "found_lede": ((f"שנת היסוד של המוסדות שפעלו ב-{ref}. "
                        + (f"שנת {bulk['year']} רשומה כשנת היסוד של {fmt.int_he(bulk['n'])} מוסדות "
                           f"({fmt.pct(bulk['share'])}), ולכן היא מוצגת יחד עם השנים שלפניה." if bulk else "")
                        + (f" ל-{_n(founded_missing, 'מוסד אחד', 'מוסדות')} לא צוינה שנת יסוד." if founded_missing else ""))
                       if founding else ""),
        "found_aria": f"גרף עמודות: מוסדות שפעלו ב-{ref} לפי שנת יסוד.",
        "churn_lede": "בכל מעבר בין שנים: סמלי מוסד שהופיעו לראשונה, וסמלים שהופיעו בשנה הקודמת ולא בשנה שאחריה.",
        "churn_aria": "גרף עמודות: מוסדות חדשים ומוסדות שיצאו מהמאגר בכל מעבר בין שנים.",
        "tree_lede": (f"{_n(len(RO), 'מסגרת אחת', 'מסגרות')} ב-{ref} אינן גני ילדים או בתי ספר: "
                      f"מוסדות תרבות וספורט, השלמת השכלה, פנימיות, מרכזי העשרה ועוד. "
                      f"השמות מוצגים כפי שהם במאגר, ולעתים מקוצרים בו."),
        "tree_aria": f"מפת עצים: מסגרות שאינן גני ילדים או בתי ספר ב-{ref}, לפי סוג מסגרת וסוג מוסד.",
        "largest_caption": f"{fmt.int_he(len(largest_rows))} בתי הספר הגדולים ב-{ref} לפי מספר התלמידים",
        "ref": str(ref),
        "y0": str(y0),
    }

    summary = (f"איתור מוסד חינוך לפי סמל מוסד, שם או יישוב: {fmt.int_he(n_ref)} מוסדות בפיקוח משרד החינוך "
               f"ב-{ref}, ובהם {fmt.int_he(st_ref)} תלמידים בגנים ובבתי ספר.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "temporal_coverage": f"{y0}/{years[-1]}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "trend": trend, "students": students, "supervision": supervision, "sector": sector,
            "district": district, "authorities": authorities, "growth": growth, "span": span,
            "size": size, "kg_size": kg_size, "legal": legal, "special": special,
            "programs": programs, "track": track, "founding": founding, "churn": churn,
            "tree": tree,
        },
        "tables": {
            "trend": trend_rows, "students": stud_rows, "supervision": sup_rows, "sector": sec_rows,
            "district": dist_rows, "authorities": au_rows, "growth": growth_rows, "span": span_rows,
            "size": size_rows, "kg_size": kg_rows, "legal": legal_rows, "special": special_rows,
            "programs": prog_rows, "yoha": yoha_rows, "track": track_rows, "gmul": gmul_rows,
            "hakara": hakara_rows, "founding": founding_rows, "churn": churn_rows,
            "frames": frame_rows, "largest": largest_rows,
        },
        "cols": {
            "trend": ["שנה"] + groups + ["סך הכול"],
            "supervision": ["שנה"] + sup_cats,
            "legal": ["זרם פיקוח"] + leg_cats,
        },
        "flags": {"has_trend": has_trend, "partial": bool(partial)},
        "insights": ins,
        "labels": labels,
    }
