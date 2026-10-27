"""תושבים צעירים בישראל לפי ישובים — Population and Immigration Authority.

One row per locality (~1.3k): locality code and name, sub-district (נפה),
the Authority bureau (לשכת מנא) serving it, its regional council (code 0 /
empty = none), the total number of registered residents (סהכ) and the number
aged 18 to 34 (גיל 18_34). The whole table is republished on each update, so
the page is a snapshot of the current registry counts; there is no date column.

Handling
- The row with locality code 0 ("לא רשום") holds residents with no registered
  locality. It is not a locality: it is excluded from every per-locality view
  and disclosed (its counts are quoted in an insight).
- Counts are coerced to numbers. No small-cell suppression markers are present
  today (every count parses, zeros are real zeros); should a marker appear,
  the row is dropped from the counts and the number of dropped rows is
  disclosed in the method note.
- Shares of a locality's population are noisy for tiny places (a locality of 3
  residents can be 0% or 100% young), so share-based views use minimum sizes,
  stated on the page: MIN_POP_DIST for the distribution views and
  MIN_POP_RANK for the highest/lowest rankings.
- Districts (מחוז) come from the first digit of the sub-district code (the
  standard registry coding, 1 Jerusalem … 7 Judea and Samaria); an unknown
  digit falls into "אחר". Mirrored parentheses in names (")שבט(") are fixed.

Growth: new localities, councils, bureaus and sub-districts flow through; every
category axis is a top-N (+ "אחר") or a fixed band list; the scatter keeps the
MAX_SCATTER largest localities.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
MIN_POP_DIST = 500
MIN_POP_RANK = 1000
MIN_POP_SCATTER = 2000
MAX_SCATTER = 400
TOP_N = 15
TOP_EXT = 10
TOP_COUNCILS = 15
TOP_BUREAUS = 30
HIST_STEP = 5
HIST_MAX = 50
SIZE_BINS = [0, 500, 1000, 2000, 5000, 20000, 100000]
DISTRICT_GAP_PP = 2.0
SIZE_GAP_PP = 3.0
COUNCIL_GAP_PP = 0.5

DISTRICTS = {
    "1": "ירושלים",
    "2": "הצפון",
    "3": "חיפה",
    "4": "המרכז",
    "5": "תל אביב",
    "6": "הדרום",
    "7": "יהודה והשומרון",
}
OTHER = "אחר"
NO_COUNCIL = "ללא מועצה אזורית"
TRIBE_TAG = "(שבט)"
_FLIP = str.maketrans("()", ")(")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def r1(v):
    return round(float(v), 1)


def _clean(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    m = re.search(r"[()]", s)
    if m and m.group(0) == ")":
        s = s.translate(_FLIP)
    s = re.sub(r"(\S)\(", r"\1 (", s)
    return s


def _district_of(code):
    c = str(code).strip()
    return DISTRICTS.get(c[:1], OTHER) if c and c != "0" else OTHER


DISTRICT_ORDER = list(DISTRICTS.values()) + [OTHER]
D_IDX = {d: i for i, d in enumerate(DISTRICT_ORDER)}


def _num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def _ranked(s):
    return s.sort_index(kind="stable").sort_values(ascending=False, kind="stable")


def _prepare(raw):
    code = _num(raw["סמל_ישוב"])
    df = pd.DataFrame({
        "code": code.values,
        "name": raw["שם_ישוב"].map(_clean).values,
        "nafa_code": raw["סמל_נפה"].astype(str).str.strip().values,
        "nafa": raw["נפה"].map(_clean).values,
        "bureau": raw["לשכת_מנא"].map(_clean).values,
        "council_code": _num(raw["קוד_מועצה_אזורית"]).fillna(0).values,
        "council": raw["מועצה_אזורית"].map(_clean).values,
        "total": _num(raw["סהכ"]).values,
        "young": _num(raw["גיל 18_34"]).values,
    })
    placeholder = df[df["code"].fillna(-1) <= 0]
    ph = None
    if len(placeholder):
        ph = {"total": int(placeholder["total"].fillna(0).sum()),
              "young": int(placeholder["young"].fillna(0).sum())}
    df = df[df["code"].notna() & (df["code"] > 0) & (df["name"] != "")].copy()
    df["code"] = df["code"].astype(int)
    bad = df["total"].isna() | df["young"].isna() | (df["total"] <= 0) | (df["young"] > df["total"])
    n_bad = int(bad.sum())
    df = df[~bad].copy()
    df["total"] = df["total"].astype(int)
    df["young"] = df["young"].astype(int)
    df = df.sort_values("code", kind="stable").drop_duplicates("code").reset_index(drop=True)
    df["share"] = df["young"] / df["total"] * 100
    df["district"] = df["nafa_code"].map(_district_of)
    df.loc[df["nafa"] == "", "nafa"] = "לא ידוע"
    df.loc[df["bureau"] == "", "bureau"] = "לא ידוע"
    in_c = (df["council"] != "") & (df["council_code"] > 0)
    df["in_council"] = in_c
    df.loc[~in_c, "council"] = NO_COUNCIL
    df["tribe"] = df["name"].str.contains(TRIBE_TAG, regex=False)
    return df, ph, n_bad


def _pooled(sub):
    t = int(sub["total"].sum())
    y = int(sub["young"].sum())
    return t, y, (y / t * 100 if t else 0.0)


def _quantiles(vals):
    v = sorted(vals)
    if not v:
        return None
    s = pd.Series(v, dtype=float)
    return [r1(s.min()), r1(s.quantile(0.25)), r1(s.median()), r1(s.quantile(0.75)), r1(s.max())]


def _band_label(lo, hi):
    if lo == 0:
        return f"פחות מ-{hi:,}"
    if hi is None:
        return f"{lo:,} ומעלה"
    return f"{lo:,} עד {hi - 1:,}"


# ---------------------------------------------------------------- insights

def insight_leader(top_rows, nat_young):
    if len(top_rows) < 2 or top_rows[0]["young"] <= top_rows[1]["young"]:
        return None
    a, b = top_rows[0], top_rows[1]
    ratio = a["young"] / b["young"]
    rel = (f"פי {ratio:.1f} מ{b['name']} שבמקום השני ({n(b['young'])})" if ratio >= 1.5
           else f"לפני {b['name']} ({n(b['young'])})")
    return (f"{a['name']} מובילה במספר התושבים בגיל 18 עד 34 — {n(a['young'])}, "
            f"{pct(a['young'] / nat_young * 100)} מכלל הצעירים ברשימה, {rel}.")


def insight_conc(df, nat_total, nat_young):
    if len(df) < 20:
        return None
    by_y = df.sort_values(["young", "code"], ascending=[False, True], kind="stable")
    top = by_y.head(TOP_EXT)
    sy = top["young"].sum() / nat_young * 100
    st = top["total"].sum() / nat_total * 100
    if abs(sy - st) < 0.5:
        cmp_t = f"כמעט זהה לחלקם בכלל האוכלוסייה ({pct(st)})"
    elif sy > st:
        cmp_t = f"יותר מחלקם בכלל האוכלוסייה ({pct(st)}) — הצעירים מרוכזים בערים הגדולות"
    else:
        cmp_t = f"פחות מחלקם בכלל האוכלוסייה ({pct(st)})"
    return (f"{n(TOP_EXT)} הישובים עם מספר הצעירים הגדול ביותר מרכזים {pct(sy)} מהתושבים בגיל "
            f"18 עד 34 ברשימה, {cmp_t}.")


def _of(k, total):
    return f"כל {n(total)}" if k == total else f"{n(k)} מתוך {n(total)}"


def insight_high(high_rows, big_n):
    if len(high_rows) < 3:
        return None
    a = high_rows[0]
    tr = [r for r in high_rows if r["tribe"]]
    tail = ""
    if len(tr) * 3 >= len(high_rows):
        dists = sorted(set(r["district"] for r in tr))
        where = f" במחוז {dists[0]}" if len(dists) == 1 else ""
        tail = (f" {_of(len(tr), len(high_rows))} הישובים בראש הדירוג הם שבטים בדואיים{where}.")
    return (f"מבין {n(big_n)} הישובים שבהם {n(MIN_POP_RANK)} תושבים ומעלה, שיעור הצעירים הגבוה "
            f"ביותר נמצא בישוב {a['name']} — {pct(a['share_v'])} ({n(a['young'])} מתוך {n(a['total'])})."
            f"{tail}")


def insight_low(low_rows, nat_share):
    if len(low_rows) < 3:
        return None
    a = low_rows[0]
    in_c = sum(1 for r in low_rows if r["in_council"])
    tail = ""
    if in_c * 2 > len(low_rows):
        tail = (f" {_of(in_c, len(low_rows))} הישובים בתחתית הדירוג שייכים למועצות אזוריות.")
    if a["share_v"] * 2 < nat_share:
        head = (f"בקצה השני, בישוב {a['name']} רק {pct(a['share_v'])} מהתושבים הם בני 18 עד 34 — "
                f"פחות ממחצית השיעור ברשימה כולה ({pct(nat_share)}).")
    else:
        head = (f"בקצה השני, בישוב {a['name']} שיעור הצעירים הוא {pct(a['share_v'])}, לעומת "
                f"{pct(nat_share)} ברשימה כולה.")
    return head + tail


def insight_district(dist_rows):
    rows = [r for r in dist_rows if r["name"] != OTHER and r["total"] > 0]
    if len(rows) < 3:
        return None
    hi = sorted(rows, key=lambda r: (-r["share_v"], D_IDX[r["name"]]))[0]
    lo = sorted(rows, key=lambda r: (r["share_v"], D_IDX[r["name"]]))[0]
    gap = hi["share_v"] - lo["share_v"]
    if gap < DISTRICT_GAP_PP:
        return (f"שיעור הצעירים דומה בכל המחוזות — בין {pct(lo['share_v'])} במחוז {lo['name']} "
                f"ל-{pct(hi['share_v'])} במחוז {hi['name']}.")
    return (f"במחוז {hi['name']} שיעור הצעירים הגבוה ביותר ({pct(hi['share_v'])}), ובמחוז "
            f"{lo['name']} הנמוך ביותר ({pct(lo['share_v'])}) — פער של {gap:.1f} נקודות אחוז.")


def insight_size(size_rows):
    rows = [r for r in size_rows if r["count"] >= 10]
    if len(rows) < 3:
        return None
    hi = sorted(rows, key=lambda r: (-r["share_v"], r["i"]))[0]
    lo = sorted(rows, key=lambda r: (r["share_v"], r["i"]))[0]
    if hi["share_v"] - lo["share_v"] < SIZE_GAP_PP:
        return None
    return (f"לפי גודל הישוב: בישובים של {hi['label']} תושבים שיעור הצעירים הוא "
            f"{pct(hi['share_v'])}, ובישובים של {lo['label']} תושבים — {pct(lo['share_v'])} בלבד.")


def insight_council(df):
    c = df[df["in_council"]]
    o = df[~df["in_council"]]
    if len(c) < 10 or len(o) < 10:
        return None
    _, _, sc = _pooled(c)
    _, _, so = _pooled(o)
    if abs(sc - so) < COUNCIL_GAP_PP:
        return (f"בישובי המועצות האזוריות ({n(len(c))} ישובים) שיעור הצעירים ({pct(sc)}) כמעט זהה "
                f"לשיעור בשאר הישובים ({pct(so)}).")
    word = "נמוך" if sc < so else "גבוה"
    med_c = c["share"].median()
    return (f"בישובי המועצות האזוריות ({n(len(c))} ישובים) שיעור הצעירים {word} מבשאר הישובים: "
            f"{pct(sc)} לעומת {pct(so)}; בישוב החציוני במועצה אזורית השיעור הוא {pct(med_c)}.")


def insight_placeholder(ph, nat_total):
    if not ph or ph["total"] <= 0:
        return None
    return (f"{n(ph['total'])} תושבים רשומים ללא ישוב (שורת ״לא רשום״), ומתוכם רק "
            f"{n(ph['young'])} בני 18 עד 34 ({pct(ph['young'] / ph['total'] * 100)}). שורה זו "
            f"אינה נכללת בנתוני הישובים בעמוד.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df, ph, n_bad = _prepare(frames["main"])
    nat_total, nat_young, nat_share = _pooled(df)
    n_loc = len(df)
    order = [d for d in DISTRICT_ORDER if d in set(df["district"])]

    def row(r):
        return {"name": r["name"], "young": int(r["young"]), "total": int(r["total"]),
                "share_v": r1(r["share"]), "share": f"{r['share']:.1f}%",
                "tribe": bool(r["tribe"]), "in_council": bool(r["in_council"]),
                "district": r["district"]}

    # Top localities by number of young residents.
    by_y = df.sort_values(["young", "code"], ascending=[False, True], kind="stable")
    top_rows = [row(r) for _, r in by_y.head(TOP_N).iterrows()]
    top_chart = {"names": [r["name"] for r in top_rows], "young": [r["young"] for r in top_rows],
                 "share": [r["share_v"] for r in top_rows]}

    # Highest / lowest share among localities of MIN_POP_RANK+.
    big = df[df["total"] >= MIN_POP_RANK]
    hs = big.sort_values(["share", "total", "code"], ascending=[False, False, True], kind="stable")
    ls = big.sort_values(["share", "total", "code"], ascending=[True, False, True], kind="stable")
    high_rows = [row(r) for _, r in hs.head(TOP_EXT).iterrows()]
    low_rows = [row(r) for _, r in ls.head(TOP_EXT).iterrows()]

    def ext_chart(rows):
        return {"names": [r["name"] for r in rows], "share": [r["share_v"] for r in rows],
                "young": [r["young"] for r in rows], "total": [r["total"] for r in rows]}

    # Distribution of shares (localities of MIN_POP_DIST+).
    dist_df = df[df["total"] >= MIN_POP_DIST]
    edges = list(range(0, HIST_MAX + HIST_STEP, HIST_STEP))
    hist_rows = []
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else None
        m = dist_df["share"] >= lo
        if hi is not None:
            m &= dist_df["share"] < hi
        label = f"{lo}%+" if hi is None else f"{lo}–{hi}%"
        hist_rows.append({"label": label, "count": int(m.sum())})
    for i, r in enumerate(hist_rows):
        r["nat"] = edges[i] <= nat_share < (edges[i + 1] if i + 1 < len(edges) else float("inf"))
    while hist_rows and hist_rows[-1]["count"] == 0:
        hist_rows.pop()
    while hist_rows and hist_rows[0]["count"] == 0:
        hist_rows.pop(0)
    hist_chart = {"labels": [r["label"] for r in hist_rows],
                  "counts": [r["count"] for r in hist_rows],
                  "nat_bin": next((i for i, r in enumerate(hist_rows) if r["nat"]), -1)}
    med_share = float(dist_df["share"].median()) if len(dist_df) else 0.0
    q1 = float(dist_df["share"].quantile(0.25)) if len(dist_df) else 0.0
    q3 = float(dist_df["share"].quantile(0.75)) if len(dist_df) else 0.0

    # Size bands.
    size_rows = []
    for i, lo in enumerate(SIZE_BINS):
        hi = SIZE_BINS[i + 1] if i + 1 < len(SIZE_BINS) else None
        m = df["total"] >= lo
        if hi is not None:
            m &= df["total"] < hi
        sub = df[m]
        t, y, s = _pooled(sub)
        if len(sub) == 0:
            continue
        size_rows.append({"i": i, "label": _band_label(lo, hi), "count": int(len(sub)),
                          "young": y, "total": t, "share_v": r1(s), "share": f"{s:.1f}%",
                          "pop_share": f"{t / nat_total * 100:.1f}%"})
    size_chart = {"labels": [r["label"] for r in size_rows],
                  "share": [r["share_v"] for r in size_rows],
                  "count": [r["count"] for r in size_rows]}

    # Districts.
    dist_rows = []
    for d in order:
        sub = df[df["district"] == d]
        t, y, s = _pooled(sub)
        dist_rows.append({"name": d, "count": int(len(sub)), "young": y, "total": t,
                          "share_v": r1(s), "share": f"{s:.1f}%",
                          "young_share": f"{y / nat_young * 100:.1f}%"})
    districts_chart = {"names": [r["name"] for r in dist_rows],
                       "young": [r["young"] for r in dist_rows],
                       "old": [r["total"] - r["young"] for r in dist_rows],
                       "share": [r["share_v"] for r in dist_rows]}

    # Boxplot of locality shares per district (MIN_POP_DIST+).
    box_rows = []
    for d in order:
        q = _quantiles(dist_df.loc[dist_df["district"] == d, "share"].tolist())
        if q is None:
            continue
        box_rows.append({"name": d, "n": int((dist_df["district"] == d).sum()), "q": q,
                         "q_disp": [f"{v:.1f}%" for v in q]})
    box_chart = {"names": [r["name"] for r in box_rows], "data": [r["q"] for r in box_rows]}

    # Sub-districts by pooled share.
    nafa_rows = []
    for nf, sub in df.groupby("nafa", sort=True):
        t, y, s = _pooled(sub)
        nafa_rows.append({"name": nf, "district": sub["district"].iloc[0], "count": int(len(sub)),
                          "young": y, "total": t, "share_v": r1(s), "share": f"{s:.1f}%",
                          "s_exact": s})
    nafa_rows.sort(key=lambda r: (-r["s_exact"], r["name"]))
    for r in nafa_rows:
        del r["s_exact"]
    nafot_chart = {"names": [r["name"] for r in nafa_rows],
                   "share": [r["share_v"] for r in nafa_rows],
                   "young": [r["young"] for r in nafa_rows],
                   "nat": r1(nat_share)}

    # Regional councils — largest by young residents.
    cdf = df[df["in_council"]]
    council_rows = []
    for c, sub in cdf.groupby("council", sort=True):
        t, y, s = _pooled(sub)
        council_rows.append({"name": c, "count": int(len(sub)), "young": y, "total": t,
                             "share_v": r1(s), "share": f"{s:.1f}%"})
    n_councils = len(council_rows)
    council_rows.sort(key=lambda r: (-r["young"], r["name"]))
    council_top = council_rows[:TOP_COUNCILS]
    c_hi = sorted(council_rows, key=lambda r: (-r["share_v"], r["name"]))[0] if council_rows else None
    c_lo = sorted(council_rows, key=lambda r: (r["share_v"], r["name"]))[0] if council_rows else None
    councils_chart = {"names": [r["name"] for r in council_top],
                      "young": [r["young"] for r in council_top],
                      "share": [r["share_v"] for r in council_top]}

    # Bureaus.
    bureau_rows = []
    for b, sub in df.groupby("bureau", sort=True):
        t, y, s = _pooled(sub)
        bureau_rows.append({"name": b, "count": int(len(sub)), "young": y, "total": t,
                            "share_v": r1(s), "share": f"{s:.1f}%"})
    n_bureaus = len(bureau_rows)
    bureau_rows.sort(key=lambda r: (-r["young"], r["name"]))
    b_top = bureau_rows[:TOP_BUREAUS]
    b_rest = bureau_rows[TOP_BUREAUS:]
    if b_rest:
        t = sum(r["total"] for r in b_rest)
        y = sum(r["young"] for r in b_rest)
        b_top = b_top + [{"name": f"אחר ({n(len(b_rest))} לשכות)", "count": sum(r["count"] for r in b_rest),
                          "young": y, "total": t, "share_v": r1(y / t * 100 if t else 0),
                          "share": f"{(y / t * 100 if t else 0):.1f}%"}]
    bureaus_chart = {"names": [r["name"] for r in b_top], "young": [r["young"] for r in b_top],
                     "share": [r["share_v"] for r in b_top]}

    # Concentration curve: cumulative share of young residents by locality rank.
    cum_y = by_y["young"].cumsum().tolist()
    ranks = sorted(set([k for k in range(1, 21)] +
                       [int(round(10 ** (e / 20))) for e in range(26, 200)] + [n_loc]))
    ranks = [k for k in ranks if 1 <= k <= n_loc]
    conc_chart = {"x": ranks, "y": [r1(cum_y[k - 1] / nat_young * 100) for k in ranks]}
    by_t = df.sort_values(["total", "code"], ascending=[False, True], kind="stable")
    cum_t = by_t["total"].cumsum().tolist()
    conc_chart["pop"] = [r1(cum_t[k - 1] / nat_total * 100) for k in ranks]
    conc_rows = []
    half = next((i + 1 for i, v in enumerate(cum_y) if v * 2 >= nat_young), n_loc)
    for k in [1, 5, 10, 20, 50, 100, 200, 500]:
        if k <= n_loc:
            conc_rows.append({"k": k, "young": f"{cum_y[k - 1] / nat_young * 100:.1f}%",
                              "pop_share": f"{cum_t[k - 1] / nat_total * 100:.1f}%"})

    # Scatter: size vs share for localities of MIN_POP_SCATTER+ (largest MAX_SCATTER).
    sc = by_t[by_t["total"] >= MIN_POP_SCATTER].head(MAX_SCATTER)
    scatter_series = []
    for d in order:
        sub = sc[sc["district"] == d].sort_values("code", kind="stable")
        if len(sub):
            scatter_series.append({"name": d, "ci": D_IDX[d],
                                   "data": [[int(t), r1(s), nm] for t, s, nm in
                                            zip(sub["total"], sub["share"], sub["name"])]})
    n_scatter = int(len(sc))

    # KPIs.
    kpis = {
        "young": {"value": nat_young, "display": n(nat_young), "tone": "brand"},
        "share": {"value": r1(nat_share), "display": f"{nat_share:.1f}%", "tone": "info"},
        "localities": {"value": n_loc, "display": n(n_loc), "tone": "brand"},
        "median": {"value": r1(med_share), "display": f"{med_share:.1f}%", "tone": "brand"},
    }

    insights = []
    for iid, txt in [
        ("leader", insight_leader(top_rows, nat_young)),
        ("conc", insight_conc(df, nat_total, nat_young)),
        ("district", insight_district(dist_rows)),
        ("high", insight_high(high_rows, len(big))),
        ("low", insight_low(low_rows, nat_share)),
        ("size", insight_size(size_rows)),
        ("council", insight_council(df)),
        ("placeholder", insight_placeholder(ph, nat_total)),
    ]:
        if txt:
            insights.append({"id": iid, "text_he": txt})

    top_d = sorted(dist_rows, key=lambda r: (-r["young"], D_IDX[r["name"]]))[0]
    bad_t = (f" {n(n_bad)} שורות עם ערך חסר או לא תקין הושמטו." if n_bad else "")
    ph_t = (f" שורת ״לא רשום״ ({n(ph['total'])} תושבים ללא ישוב) אינה נכללת." if ph else "")
    top_nafa = nafa_rows[0] if nafa_rows else None
    low_nafa = nafa_rows[-1] if nafa_rows else None
    big_size = max(size_rows, key=lambda r: (r["total"], -r["i"])) if size_rows else None

    labels = {
        "lede": (f"רשות האוכלוסין וההגירה מפרסמת, לכל ישוב במרשם האוכלוסין, את מספר התושבים "
                 f"הרשומים ואת מספר התושבים בגיל 18 עד 34. ברשימה {n(n_loc)} ישובים עם "
                 f"{n(nat_total)} תושבים, ומתוכם {n(nat_young)} צעירים — {pct(nat_share)}. העמוד "
                 f"מראה היכן גרים הצעירים במספרים מוחלטים, היכן הם חלק גדול או קטן מהאוכלוסייה, "
                 f"ואיך השיעור משתנה לפי מחוז, נפה, גודל ישוב ומועצה אזורית.{ph_t}{bad_t}"),
        "young_kpi": "תושבים בגיל 18 עד 34",
        "share_kpi": "שיעור הצעירים מכלל התושבים",
        "localities_kpi": "ישובים ברשימה",
        "median_kpi": f"שיעור הצעירים בישוב החציוני ({n(MIN_POP_DIST)} תושבים ומעלה)",
        "top_note": (f"{n(len(top_rows))} הישובים עם מספר התושבים בגיל 18 עד 34 הגדול ביותר. "
                     f"הקו מציג את שיעור הצעירים מתושבי הישוב."),
        "top_aria": (f"גרף עמודות אופקי: {n(len(top_rows))} הישובים עם מספר הצעירים הגדול ביותר. "
                     + (f"{top_rows[0]['name']} מובילה עם {n(top_rows[0]['young'])}." if top_rows else "")),
        "top_caption": "הישובים עם מספר התושבים בגיל 18 עד 34 הגדול ביותר",
        "high_note": (f"מבין {n(len(big))} הישובים שבהם {n(MIN_POP_RANK)} תושבים ומעלה — כדי "
                      f"שישובים זעירים לא יעוותו את הדירוג."),
        "high_aria": ("גרף עמודות אופקי: הישובים עם שיעור הצעירים הגבוה ביותר. "
                      + (f"{high_rows[0]['name']} מובילה עם {pct(high_rows[0]['share_v'])}." if high_rows else "")),
        "high_caption": "הישובים עם שיעור הצעירים הגבוה ביותר",
        "low_note": (f"אותה קבוצת ישובים ({n(MIN_POP_RANK)} תושבים ומעלה), מהשיעור הנמוך. "
                     f"הקו המקווקו הוא השיעור ברשימה כולה ({pct(nat_share)})."),
        "low_aria": ("גרף עמודות אופקי: הישובים עם שיעור הצעירים הנמוך ביותר. "
                     + (f"ב{low_rows[0]['name']} השיעור הוא {pct(low_rows[0]['share_v'])}." if low_rows else "")),
        "low_caption": "הישובים עם שיעור הצעירים הנמוך ביותר",
        "hist_note": (f"מספר הישובים בכל טווח של שיעור צעירים, ל-{n(len(dist_df))} ישובים שבהם "
                      f"{n(MIN_POP_DIST)} תושבים ומעלה. בישוב החציוני השיעור הוא {pct(med_share)}, "
                      f"ומחצית הישובים נמצאים בין {pct(q1)} ל-{pct(q3)}. העמודה הכהה היא הטווח שבו נמצא "
                      f"השיעור ברשימה כולה ({pct(nat_share)})."),
        "hist_aria": (f"היסטוגרמה: התפלגות שיעור התושבים בגיל 18 עד 34 בין {n(len(dist_df))} ישובים. "
                      f"החציון {pct(med_share)}."),
        "hist_caption": "מספר הישובים לפי טווח שיעור צעירים",
        "size_note": ("שיעור הצעירים המצרפי לפי גודל הישוב (מספר התושבים), לצד מספר הישובים בכל "
                      "קבוצה."
                      + (f" רוב התושבים גרים בישובים של {big_size['label']} תושבים." if big_size and big_size["total"] * 2 > nat_total else "")),
        "size_aria": "גרף עמודות וקו: שיעור הצעירים ומספר הישובים לפי גודל הישוב.",
        "size_caption": "שיעור הצעירים לפי גודל הישוב",
        "districts_note": (f"המחוז נגזר מסמל הנפה. במחוז {top_d['name']} מספר הצעירים הגדול ביותר — "
                           f"{n(top_d['young'])} ({pct(top_d['young'] / nat_young * 100)} מהצעירים "
                           f"ברשימה). העמודות מפצלות את התושבים לבני 18 עד 34 ולשאר; הקו הוא שיעור "
                           f"הצעירים."),
        "districts_aria": (f"גרף עמודות מוערמות וקו: תושבים לפי מחוז ושיעור הצעירים בכל מחוז. "
                           f"מחוז {top_d['name']} מוביל במספר הצעירים."),
        "districts_caption": "תושבים צעירים לפי מחוז",
        "box_note": (f"פיזור שיעור הצעירים בין הישובים שבכל מחוז ({n(MIN_POP_DIST)} תושבים ומעלה): "
                     f"הקופסה מסמנת את מחצית הישובים האמצעית, הקו שבתוכה את החציון, והשפמים את "
                     f"הישוב הנמוך והגבוה."),
        "box_aria": "תרשים קופסה: התפלגות שיעור הצעירים בין הישובים בכל מחוז.",
        "box_caption": "התפלגות שיעור הצעירים בין הישובים לפי מחוז",
        "nafot_note": ((f"{n(len(nafa_rows))} נפות, מהשיעור הגבוה לנמוך. בנפת {top_nafa['name']} "
                        f"השיעור הגבוה ביותר ({pct(top_nafa['share_v'])}), ובנפת {low_nafa['name']} "
                        f"הנמוך ביותר ({pct(low_nafa['share_v'])}). הקו המקווקו הוא השיעור ברשימה "
                        f"כולה.") if nafa_rows else ""),
        "nafot_aria": (f"גרף עמודות אופקי: שיעור הצעירים בכל אחת מ-{n(len(nafa_rows))} הנפות."),
        "nafot_caption": "שיעור הצעירים לפי נפה",
        "councils_note": ((f"{n(len(council_top))} המועצות האזוריות עם מספר הצעירים הגדול ביותר, "
                           f"מתוך {n(n_councils)}. השיעור הגבוה ביותר בין כל המועצות נמצא ב{c_hi['name']} "
                           f"({pct(c_hi['share_v'])}) והנמוך ביותר ב{c_lo['name']} ({pct(c_lo['share_v'])}).")
                          if council_rows else ""),
        "councils_aria": ("גרף עמודות אופקי: המועצות האזוריות עם מספר הצעירים הגדול ביותר."
                          + (f" {council_top[0]['name']} מובילה." if council_top else "")),
        "councils_caption": "המועצות האזוריות עם מספר הצעירים הגדול ביותר",
        "bureaus_note": (f"מספר התושבים בגיל 18 עד 34 בישובים שכל לשכה של רשות האוכלוסין משרתת — "
                         f"{n(TOP_BUREAUS)} הלשכות הגדולות מתוך {n(n_bureaus)}."
                         if b_rest else
                         f"מספר התושבים בגיל 18 עד 34 בישובים שכל אחת מ-{n(n_bureaus)} הלשכות של רשות "
                         f"האוכלוסין משרתת."),
        "bureaus_aria": ("גרף עמודות אופקי: תושבים צעירים לפי לשכת רשות האוכלוסין."
                         + (f" לשכת {bureau_rows[0]['name']} מובילה עם {n(bureau_rows[0]['young'])}." if bureau_rows else "")),
        "bureaus_caption": "תושבים צעירים לפי לשכת רשות האוכלוסין",
        "conc_note": (f"החלק המצטבר מהצעירים (ומכלל התושבים) כשהישובים מדורגים מהגדול לקטן. "
                      f"{n(half)} ישובים בלבד מרכזים מחצית מהתושבים בגיל 18 עד 34. ציר הישובים "
                      f"לוגריתמי."),
        "conc_aria": (f"גרף קו: ריכוז התושבים הצעירים בישובים. {n(half)} ישובים מרכזים מחצית "
                      f"מהצעירים."),
        "conc_caption": "החלק המצטבר מהתושבים לפי מספר הישובים הגדולים",
        "scatter_note": (f"כל נקודה היא ישוב ({n(n_scatter)} הישובים שבהם {n(MIN_POP_SCATTER)} "
                         f"תושבים ומעלה), צבועה לפי מחוז: גודל הישוב (ציר לוגריתמי) מול שיעור "
                         f"הצעירים בו. לחיצה על מחוז במקרא מסתירה אותו."),
        "scatter_aria": (f"תרשים פיזור: גודל הישוב מול שיעור הצעירים, {n(n_scatter)} ישובים."),
    }

    agent_data = {
        "summary_he": (f"מספר התושבים בגיל 18 עד 34 ב-{n(n_loc)} ישובים לפי מרשם האוכלוסין: "
                       f"{n(nat_young)} צעירים, {pct(nat_share)} מהתושבים"
                       + (f"; {top_rows[0]['name']} מובילה עם {n(top_rows[0]['young'])}" if top_rows else "")
                       + f", ופילוח לפי מחוז, נפה, גודל ישוב ומועצה אזורית."),
        "dataset_kind": "rankings",
        "suggested_tags": ["צעירים", "אוכלוסייה", "ישובים", "דמוגרפיה", "מרשם אוכלוסין",
                           "מועצות אזוריות"],
        "related_ids": [
            "00172ee8-4433-4d5d-8fd4-11f0f08ce5c4",
            "3fc54b81-25b3-4ac7-87db-248c3e1602de",
            "d2581732-eca4-4988-b986-df8e791a1d60",
            "785ad9fb-6da6-426d-b5ea-b8e36febbc8a",
        ],
        "spatial_coverage": "ישראל ויהודה והשומרון",
    }

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {
            "top": top_chart,
            "high": ext_chart(high_rows),
            "low": ext_chart(low_rows),
            "nat": r1(nat_share),
            "hist": hist_chart,
            "size": size_chart,
            "districts": districts_chart,
            "box": box_chart,
            "nafot": nafot_chart,
            "councils": councils_chart,
            "bureaus": bureaus_chart,
            "conc": conc_chart,
            "scatter": scatter_series,
        },
        "insights": insights,
        "labels": labels,
        "tables": {
            "top": top_rows,
            "high": high_rows,
            "low": low_rows,
            "hist": hist_rows,
            "size": size_rows,
            "districts": dist_rows,
            "box": box_rows,
            "nafot": nafa_rows,
            "councils": council_top,
            "bureaus": b_top,
            "conc": conc_rows,
        },
        "flags": {"councils": bool(council_top), "scatter": bool(scatter_series),
                  "extremes": len(high_rows) >= 3},
    }
