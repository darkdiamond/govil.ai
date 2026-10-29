"""מאגר תחנות הדלק (משרד האנרגיה) — registry/statistics page.

One row per licensed fuel station: `station_number` (the ministry's station
number, an identifier), `station_name`, `company` (the fuel company / brand,
or "אחר \\ עצמאי" for independents), `location` (free-text address or road
description), `City` (the locality; filled for under half the rows, mostly
where the station sits in a locality other than the authority's own name),
`authority_name` (local authority) and `telephone` (a contact number; some
are private mobiles, so it is never put on the page).

The page answers "how many fuel stations are there in Israel" and then the
registry's structure: market shares by company and tier, stations per local
authority with the company mix, how many authorities have a single station,
where the stations stand (road/junction, industrial zone, city street, ...)
classified from the free-text location, and where independents are strong.

Growth: the file is a snapshot replaced in place. Company and authority
spellings are normalised by a key that ignores spaces/hyphens, the display
form is the most frequent variant. Category axes are top-N + "אחר"; new
companies/authorities flow through; location classes fall back to
"תיאור כללי".
"""
import re

import pandas as pd

TOP_CO = 10            # companies on the bar chart before "אחר"
TOP_CHAINS = 4         # "the big chains" = this many largest named companies
MID_MIN = 10           # a named company with >= this many stations is "mid-size"
TOP_AUTH = 15          # authorities on the stacked chart
TOP_MIX_CO = 5         # companies kept as series in the stacked charts
IND_MIN_STATIONS = 8   # authority needs this many stations for the independents ranking
TOP_IND = 10
LEADER_GAP = 0.02      # leader must beat #2 by this share to be called a leader
ROAD_GAP = 0.08        # a chain's road share must differ by this from the average

INDEPENDENT = "עצמאי / אחר"
OTHER = "אחר"

LOC_CLASSES = [
    ("כביש / צומת / כניסה ליישוב", re.compile(r"כביש|צומת|מחלף|בכניסה|כניסה ל|כניסה מ|כניסה צפונית|כניסה דרומית|כניסה מזרחית|כניסה מערבית|מעבר גבול")),
    ("אזור תעשייה", re.compile(r'א\.\s*ת|א"ת|א״ת|אזור התעשי|אזור תעשי|איזור תעשי|איזור התעשי|אזה"ת|פארק|ד\. המלאכה|המלאכה')),
    ("מרכז מסחרי", re.compile(r"מרכז מסחרי|מרכז קניות|קניון|סנטר|מ\.מסחרי|מתחם")),
    ("קיבוץ / מושב", re.compile(r"קיבוץ|קבוץ|מושב")),
    ("כתובת ברחוב", re.compile(r"רח'|רח׳|רחוב|שד'|שדרות|דרך |פינת|ככר|כיכר|\d")),
]
LOC_GENERAL = "תיאור כללי (שם יישוב)"


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def clean(s):
    return " ".join(str(s).replace("\xa0", " ").split())


def key_of(s):
    return re.sub(r"[\s\-־–'׳\"״.]", "", s)


def display_map(series):
    """Normalise spelling variants: key ignoring spaces/hyphens/quotes; the
    display form is the most frequent raw variant (ties: alphabetical)."""
    df = pd.DataFrame({"raw": series, "key": series.map(key_of)})
    counts = df.groupby(["key", "raw"]).size().reset_index(name="c")
    counts = counts.sort_values(["key", "c", "raw"], ascending=[True, False, True], kind="mergesort")
    best = counts.drop_duplicates("key").set_index("key")["raw"]
    return df["key"].map(best)


def company_label(s):
    return INDEPENDENT if "עצמאי" in s else s


def loc_class(s):
    for name, rx in LOC_CLASSES:
        if rx.search(s):
            return name
    return LOC_GENERAL


def join_he(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + items[-1]


def _prepare(df):
    out = pd.DataFrame({
        "num": df["station_number"].map(clean),
        "name": df["station_name"].map(clean),
        "co_raw": df["company"].map(clean),
        "loc": df["location"].map(clean),
        "city": df["City"].map(clean),
        "auth_raw": df["authority_name"].map(clean),
    })
    out = out[(out["auth_raw"] != "") | (out["name"] != "")].copy()
    out["co_raw"] = out["co_raw"].where(out["co_raw"] != "", "לא צוין")
    out["auth_raw"] = out["auth_raw"].where(out["auth_raw"] != "", "לא צוין")
    out["company"] = display_map(out["co_raw"]).map(company_label)
    out["auth"] = display_map(out["auth_raw"])
    out["lclass"] = out["loc"].map(loc_class)
    out["num_n"] = pd.to_numeric(out["num"], errors="coerce")
    out = out.sort_values(["auth", "company", "num_n", "num", "name", "loc"],
                          kind="mergesort", na_position="last").reset_index(drop=True)
    return out


def _ranked(counts):
    """value_counts → list of (name, count) with a total, deterministic order."""
    items = [(k, int(v)) for k, v in counts.items()]
    return sorted(items, key=lambda kv: (-kv[1], kv[0]))


def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    co_rank = _ranked(df["company"].value_counts())
    named = [(k, v) for k, v in co_rank if k != INDEPENDENT]
    n_named = len(named)
    ind = int((df["company"] == INDEPENDENT).sum())
    chains = [k for k, _ in named[:TOP_CHAINS]]
    chain_total = sum(v for _, v in named[:TOP_CHAINS])

    # ---- chart: stations by company (top-N + אחר) -----------------------
    top = co_rank[:TOP_CO]
    rest = co_rank[TOP_CO:]
    c_names = [k for k, _ in top]
    c_vals = [v for _, v in top]
    if rest:
        c_names.append(f"{OTHER} ({n(len(rest))} חברות)")
        c_vals.append(sum(v for _, v in rest))
    chart_co = {"names": c_names, "values": c_vals,
                "shares": [round(v / total * 100, 1) for v in c_vals]}
    tbl_co = [[k, n(v), pct(v / total)] for k, v in zip(c_names, c_vals)]

    # ---- chart: market tiers -------------------------------------------
    mids = [(k, v) for k, v in named[TOP_CHAINS:] if v >= MID_MIN]
    smalls = [(k, v) for k, v in named[TOP_CHAINS:] if v < MID_MIN]
    tiers = [
        (f"{n(len(chains))} הרשתות הגדולות", chain_total),
        (f"חברות בינוניות ({n(len(mids))})", sum(v for _, v in mids)),
        (f"חברות קטנות ({n(len(smalls))})", sum(v for _, v in smalls)),
        ("תחנות עצמאיות / אחר", ind),
    ]
    tiers = [(k, v) for k, v in tiers if v > 0]
    chart_tier = {"items": [{"name": k, "value": v} for k, v in tiers]}
    tbl_tier = [[k, n(v), pct(v / total)] for k, v in tiers]

    # ---- chart: top authorities stacked by company ---------------------
    auth_rank = _ranked(df["auth"].value_counts())
    n_auth = len(auth_rank)
    top_auth = [k for k, _ in auth_rank[:TOP_AUTH]]
    mix_cos = [k for k, _ in co_rank if k != INDEPENDENT][:TOP_MIX_CO]
    grp = df["company"].where(df["company"].isin(mix_cos + [INDEPENDENT]), OTHER)
    ct = pd.crosstab(df["auth"], grp)
    series_names = mix_cos + [x for x in (INDEPENDENT, OTHER) if x in ct.columns]
    ct = ct.reindex(index=top_auth, columns=series_names, fill_value=0)
    chart_auth = {"names": top_auth,
                  "series": [{"name": s, "data": [int(x) for x in ct[s]]} for s in series_names]}
    tbl_auth = [[a] + [n(ct.loc[a, s]) for s in series_names] + [n(ct.loc[a].sum())] for a in top_auth]
    top_auth_total = sum(v for _, v in auth_rank[:TOP_AUTH])

    # ---- chart: authorities by number of stations ----------------------
    per_auth = pd.Series(dict(auth_rank))
    buckets = [("תחנה אחת", 1, 1), ("2", 2, 2), ("3-4", 3, 4), ("5-9", 5, 9),
               ("10-19", 10, 19), ("20 ומעלה", 20, 10 ** 9)]
    b_names, b_auth, b_st = [], [], []
    for lab, lo, hi in buckets:
        sel = per_auth[(per_auth >= lo) & (per_auth <= hi)]
        b_names.append(lab)
        b_auth.append(int(len(sel)))
        b_st.append(int(sel.sum()))
    chart_dist = {"names": b_names, "auth": b_auth, "stations": b_st}
    tbl_dist = [[k, n(a), n(s)] for k, a, s in zip(b_names, b_auth, b_st)]
    singles = b_auth[0]

    # ---- chart: location type ------------------------------------------
    order = [k for k, _ in LOC_CLASSES] + [LOC_GENERAL]
    lc = df["lclass"].value_counts()
    locs = sorted([(k, int(lc[k])) for k in order if k in lc.index],
                  key=lambda kv: (-kv[1], order.index(kv[0])))
    chart_loc = {"names": [k for k, _ in locs], "values": [v for _, v in locs]}
    tbl_loc = [[k, n(v), pct(v / total)] for k, v in locs]

    # ---- chart: location type by company (100% stacked) ----------------
    lco = mix_cos + ([INDEPENDENT] if ind else [])
    sub = df[df["company"].isin(lco)]
    ctl = pd.crosstab(sub["company"], sub["lclass"]).reindex(
        index=lco, columns=chart_loc["names"], fill_value=0)
    loc_series = []
    for lname in chart_loc["names"]:
        cnt = [int(ctl.loc[c, lname]) for c in lco]
        shr = [round(x / max(int(ctl.loc[c].sum()), 1) * 100, 1) for c, x in zip(lco, cnt)]
        loc_series.append({"name": lname, "share": shr, "count": cnt})
    chart_locco = {"names": lco, "series": loc_series}
    tbl_locco = [[c] + [pct(ctl.loc[c, l] / max(int(ctl.loc[c].sum()), 1), 0) for l in chart_loc["names"]]
                 + [n(ctl.loc[c].sum())] for c in lco]

    # ---- chart: independents share by authority ------------------------
    ia = df.groupby("auth").agg(st=("company", "size"),
                                ind=("company", lambda s: int((s == INDEPENDENT).sum())))
    ia = ia[ia["st"] >= IND_MIN_STATIONS].copy()
    ia["share"] = ia["ind"] / ia["st"]
    ia = ia.reset_index().sort_values(["share", "st", "auth"], ascending=[False, False, True],
                                      kind="mergesort")
    ia_top = ia[(ia["ind"] > 0) & (ia["share"] > (ind / total if total else 0))].head(TOP_IND)
    chart_ind = {"names": list(ia_top["auth"]),
                 "share": [round(float(x) * 100, 1) for x in ia_top["share"]],
                 "ind": [int(x) for x in ia_top["ind"]],
                 "st": [int(x) for x in ia_top["st"]],
                 "avg": round(ind / total * 100, 1) if total else 0}
    tbl_ind = [[a, n(i), n(s), pct(sh)] for a, i, s, sh in
               zip(ia_top["auth"], ia_top["ind"], ia_top["st"], ia_top["share"])]

    # ---- localities inside other authorities (City column) --------------
    city_diff = df[(df["city"] != "") & (df["city"].map(key_of) != df["auth"].map(key_of))]
    n_city_diff = len(city_diff)

    # ---- KPIs -----------------------------------------------------------
    chain_share = chain_total / total if total else 0
    ind_share = ind / total if total else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "auth": {"value": n_auth, "display": n(n_auth), "tone": "brand"},
        "chains": {"value": round(chain_share * 100, 1), "display": pct(chain_share, 0),
                   "tone": "warn" if chain_share >= 0.75 else "info"},
        "ind": {"value": round(ind_share * 100, 1), "display": pct(ind_share, 0), "tone": "info"},
    }

    # ---- insights -------------------------------------------------------
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_leader():
        if n_named < 2:
            return None
        (k1, v1), (k2, v2) = named[0], named[1]
        if (v1 - v2) / total < LEADER_GAP:
            return (f"אין חברה דומיננטית אחת: {k1} ({n(v1)} תחנות) ו{k2} ({n(v2)}) "
                    f"מחזיקות נתחים כמעט זהים, {pct(v1 / total)} ו-{pct(v2 / total)} מהתחנות.")
        return (f"{k1} היא חברת הדלק עם מספר התחנות הגדול ביותר: {n(v1)} תחנות "
                f"({pct(v1 / total)}), לפני {k2} עם {n(v2)}.")
    add("leader", ins_leader())

    def ins_chains():
        if len(chains) < TOP_CHAINS:
            return None
        return (f"{n(len(chains))} הרשתות הגדולות ({join_he(chains)}) מפעילות {n(chain_total)} "
                f"מתוך {n(total)} התחנות ({pct(chain_share)}); עוד {n(n_named - len(chains))} "
                f"חברות קטנות יותר ו-{n(ind)} תחנות עצמאיות חולקות את השאר.")
    add("chains", ins_chains())

    def ins_cities():
        if n_auth < 5:
            return None
        k1, v1 = auth_rank[0]
        top5 = sum(v for _, v in auth_rank[:5])
        return (f"ב{k1} יש הכי הרבה תחנות דלק: {n(v1)}. חמש הרשויות המובילות "
                f"({join_he([k for k, _ in auth_rank[:5]])}) מרכזות יחד {n(top5)} תחנות, "
                f"{pct(top5 / total)} מכלל התחנות.")
    add("cities", ins_cities())

    def ins_single():
        if n_auth < 5 or singles == 0:
            return None
        s = (f"ב-{n(singles)} מתוך {n(n_auth)} הרשויות ({pct(singles / n_auth, 0)}) "
             f"יש תחנת דלק אחת בלבד")
        if b_auth[-1] and b_st[-1] / total >= 0.15:
            s += (f", ומנגד {n(b_auth[-1])} רשויות עם {n(buckets[-1][1])} תחנות ומעלה "
                  f"מרכזות {n(b_st[-1])} תחנות ({pct(b_st[-1] / total)})")
        return s + "."
    add("single", ins_single())

    def ins_road():
        if not locs:
            return None
        road_name = LOC_CLASSES[0][0]
        road = int(lc.get(road_name, 0))
        if road == 0:
            return None
        base = road / total
        s = (f"{n(road)} תחנות ({pct(base)}) מתוארות לפי כביש, צומת או כניסה ליישוב, "
             f"ו-{n(int(lc.get('כתובת ברחוב', 0)))} לפי כתובת ברחוב")
        diffs = []
        for c in lco:
            tot_c = int(ctl.loc[c].sum())
            if tot_c < MID_MIN:
                continue
            diffs.append((ctl.loc[c, road_name] / tot_c - base, c))
        diffs.sort(key=lambda t: (-abs(t[0]), t[1]))
        if diffs and abs(diffs[0][0]) >= ROAD_GAP:
            d, c = diffs[0]
            share_c = d + base
            word = "גבוה" if d > 0 else "נמוך"
            s += f". אצל {c} השיעור {word} במיוחד: {pct(share_c)}"
        return s + "."
    add("road", ins_road())

    def ins_ind():
        if ia_top.empty or ind == 0:
            return None
        r = ia_top.iloc[0]
        if r["share"] < 2 * ind_share:
            return None
        return (f"התחנות העצמאיות נפוצות במיוחד ב{r['auth']}: {n(r['ind'])} מתוך {n(r['st'])} "
                f"התחנות ({pct(r['share'])}), לעומת {pct(ind_share)} בכלל הארץ "
                f"(רשויות עם {n(IND_MIN_STATIONS)} תחנות לפחות).")
    add("ind", ins_ind())

    def ins_city():
        if n_city_diff < 10:
            return None
        n_aut = city_diff["auth"].nunique()
        return (f"{n(n_city_diff)} תחנות נמצאות ביישוב ששמו שונה משם הרשות, בעיקר במועצות "
                f"אזוריות ({n(n_aut)} רשויות); חיפוש לפי שם הרשות לבדו עלול לפספס אותן.")
    add("city", ins_city())

    # ---- labels ---------------------------------------------------------
    k1, v1 = auth_rank[0]
    labels = {
        "lede": (f"כמה תחנות דלק יש בישראל? במאגר תחנות הדלק של משרד האנרגיה רשומות "
                 f"{n(total)} תחנות דלק מורשות, ב-{n(n_auth)} רשויות מקומיות, של {n(n_named)} "
                 f"חברות דלק ועוד {n(ind)} תחנות עצמאיות. לכל תחנה מופיעים מספר התחנה, שמה, "
                 f"חברת הדלק, המיקום והרשות המקומית."),
        "twin": ("רוצים לראות את התחנות על מפה? במאגר המקביל, רשימת תחנות הדלק הציבוריות "
                 "כולל מידע גאוגרפי, מופיעות התחנות עם קואורדינטות."),
        "kpi_total": "תחנות דלק מורשות במאגר",
        "kpi_auth": "רשויות מקומיות עם תחנת דלק",
        "kpi_chains": f"מהתחנות שייכות ל-{n(len(chains))} הרשתות הגדולות",
        "kpi_ind": "מהתחנות עצמאיות או ללא חברה מוכרת",
        "co_title": f"תחנות דלק לפי חברה: {join_he(chains)}" + (" ועוד" if n_named > len(chains) or ind else ""),
        "co_note": (f"{named[0][0]} מובילה עם {n(named[0][1])} תחנות. "
                    + (f"מוצגות {n(TOP_CO)} החברות הגדולות; השאר מקובצות תחת \"{OTHER}\"." if rest else "")
                    if named else ""),
        "co_aria": (f"גרף עמודות אופקי: מספר תחנות הדלק לפי חברה. המובילה: {co_rank[0][0]} "
                    f"עם {n(co_rank[0][1])} תחנות." if co_rank else "גרף עמודות: תחנות לפי חברה."),
        "co_cap": "תחנות דלק לפי חברת דלק",
        "tier_note": (f"הרשתות הגדולות: {join_he(chains)}. חברה בינונית: {n(MID_MIN)} תחנות לפחות; "
                      f"חברה קטנה: פחות מכך. התחנות העצמאיות מסומנות במאגר כקטגוריה אחת."),
        "tier_aria": (f"גרף טבעת: חלוקת תחנות הדלק לפי סוג המפעיל. {n(len(chains))} הרשתות הגדולות "
                      f"מחזיקות {pct(chain_share)} מהתחנות."),
        "tier_cap": "תחנות דלק לפי סוג המפעיל",
        "auth_note": (f"{n(TOP_AUTH)} הרשויות עם הכי הרבה תחנות, {n(top_auth_total)} תחנות בסך הכל, "
                      f"בחלוקה לפי חברה. {k1} מובילה עם {n(v1)} תחנות."),
        "auth_aria": (f"גרף עמודות מוערמות: תחנות דלק ב-{n(len(top_auth))} הרשויות המובילות לפי חברה. "
                      f"המובילה: {k1} עם {n(v1)} תחנות."),
        "auth_cap": "תחנות דלק לפי רשות מקומית וחברה",
        "dist_note": (f"כמה רשויות יש בכל קבוצת גודל, וכמה תחנות יש בהן יחד. "
                      f"ב-{n(singles)} רשויות יש תחנה אחת בלבד."),
        "dist_aria": (f"גרף עמודות: מספר הרשויות לפי מספר תחנות הדלק בהן. "
                      f"{n(singles)} רשויות עם תחנה אחת."),
        "dist_cap": "רשויות מקומיות לפי מספר תחנות הדלק",
        "loc_note": ("סיווג לפי תיאור המיקום בנתונים (מילות מפתח כמו כביש, צומת, א.ת., רחוב). "
                     "תיאור שמכיל רק שם יישוב מסווג כתיאור כללי."),
        "loc_aria": (f"גרף עמודות: תחנות דלק לפי סוג המיקום. הנפוץ: {locs[0][0]} עם {n(locs[0][1])} תחנות."
                     if locs else "גרף עמודות: תחנות לפי סוג מיקום."),
        "loc_cap": "תחנות דלק לפי סוג המיקום",
        "locco_note": (f"שיעור כל סוג מיקום מתוך התחנות של כל חברה ({n(len(mix_cos))} החברות הגדולות "
                       f"והתחנות העצמאיות). מעבר עם העכבר מציג גם את המספר."),
        "locco_aria": f"גרף עמודות מוערמות: התפלגות סוגי המיקום של התחנות ב-{n(len(lco))} קבוצות מפעילים.",
        "locco_cap": "סוג המיקום לפי חברת דלק (אחוזים)",
        "ind_note": (f"הרשויות שבהן שיעור התחנות העצמאיות גבוה מהשיעור הארצי (רשויות עם {n(IND_MIN_STATIONS)} תחנות לפחות). "
                     f"הקו האנכי מסמן את השיעור הארצי, {pct(ind_share)}."),
        "ind_aria": (f"גרף עמודות אופקי: רשויות עם השיעור הגבוה ביותר של תחנות עצמאיות. "
                     f"המובילה: {chart_ind['names'][0]} עם {chart_ind['share'][0]}%."
                     if chart_ind["names"] else "גרף עמודות: שיעור תחנות עצמאיות לפי רשות."),
        "ind_cap": "רשויות עם שיעור גבוה של תחנות עצמאיות",
    }

    summary = (f"איתור תחנת דלק לפי שם, חברה, כתובת או רשות. כמה תחנות דלק יש בישראל? "
               f"{n(total)} תחנות מורשות ב-{n(n_auth)} רשויות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "suggested_tags": ["תחנות דלק", "דלק", "חברות דלק", "רשויות מקומיות", "אנרגיה", "תחבורה"],
            "related_ids": ["aa0ce63f-00ad-4814-8a1c-e93f03d827c1",
                            "4dd3bb28-a4ef-4ab5-bb57-fd0bd0b79f8f",
                            "61dc38b6-803e-476e-a1ac-0679c354b2ef",
                            "b2f22645-5068-487b-82d3-78e3490ef49d"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "kpi_order": ["total", "auth", "chains", "ind"],
        "charts": {"co": chart_co, "tier": chart_tier, "auth": chart_auth, "dist": chart_dist,
                   "loc": chart_loc, "locco": chart_locco, "ind": chart_ind},
        "tables": {
            "co": {"head": ["חברה", "תחנות", "שיעור"], "rows": tbl_co},
            "tier": {"head": ["סוג מפעיל", "תחנות", "שיעור"], "rows": tbl_tier},
            "auth": {"head": ["רשות"] + series_names + ["סה״כ"], "rows": tbl_auth},
            "dist": {"head": ["תחנות ברשות", "רשויות", "תחנות"], "rows": tbl_dist},
            "loc": {"head": ["סוג מיקום", "תחנות", "שיעור"], "rows": tbl_loc},
            "locco": {"head": ["חברה"] + chart_loc["names"] + ["תחנות"], "rows": tbl_locco},
            "ind": {"head": ["רשות", "עצמאיות", "כל התחנות", "שיעור"], "rows": tbl_ind},
        },
        "flags": {"ind": len(chart_ind["names"]) >= 3, "twin": True},
        "links": {"twin": "/datasets/aa0ce63f-00ad-4814-8a1c-e93f03d827c1/"},
        "insights": insights,
        "labels": labels,
    }
