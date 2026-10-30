"""שירות המבחן לנוער: referrals, offences and court decisions by district and locality.

The dataset publishes three tables per year as separate CSVs:
  * referrals (הפניות): one row per (district, locality), a column per offence
    group plus a total-referrals column;
  * offences (עבירות): same shape, counting offences (one referral can carry
    several offences, so offences > referrals);
  * court decisions (החלטות בית משפט): a column per decision type.

Both caseload tables match the `caseload` input, decisions the `decisions`
input; each is a `concat` input, so a new yearly file flows in automatically.
The year comes from the file name, the table kind from the total column's
name (fallback: the file name). Column names drift between years (double
spaces, "קנס/ערבות/פיצוי" vs "קנס ערבות פיצוי", יישוב/ישוב/שם יישוב), so names
are normalised before use. District names drift too (חיפה/צפון, צפון, דרם).

Small cells are published as the text "בין 1 ל 10". Every sum is therefore a
range: low = exact values + 1 per suppressed cell, high = exact + 10 per
suppressed cell. Trend and "who leads" rules only speak when the ranges do
not overlap. Files that have no locality column (the 2020 caseload files,
which lost their locality labels) cannot be read reliably and are skipped,
disclosed on the page. Rows with a blank locality are file totals (2019) and
are dropped; numeric "localities" (bare codes) count in totals but not in the
locality ranking.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
RES = "_resource_name"
SUPP_HI = 10
TOP_TOWNS = 15
TOP_DEC_TYPES = 6
INTENSITY_MIN = 200          # min referrals (low bound) for a group's offences-per-referral rate
DISTRICT_SHARE_MIN = 0.25    # top district insight needs at least this share

GROUP_ORDER = ["אלימות", "כלפי הסדר הציבורי", "כלפי רכוש", "שימוש וסחר בסמים",
               "תאונות דרכים ועבירות תעבורה", "עבירות מין", "שאר עבירות"]
GROUP_SHORT = {
    "אלימות": "אלימות",
    "כלפי הסדר הציבורי": "הסדר הציבורי",
    "כלפי רכוש": "רכוש",
    "שימוש וסחר בסמים": "סמים",
    "תאונות דרכים ועבירות תעבורה": "תעבורה",
    "עבירות מין": "עבירות מין",
    "שאר עבירות": "שאר עבירות",
}
DISTRICT_MAP = {"חיפה/צפון": "חיפה וצפון", "צפון": "חיפה וצפון", "חיפה וצפון": "חיפה וצפון",
                "דרם": "דרום"}
DEC_LABEL = {
    "קנס ערבות פיצוי": "קנס, ערבות או פיצוי",
    "דחיית דיון": "דחיית דיון",
    "מאסר על תנאי": "מאסר על תנאי",
    "אחר": "החלטות אחרות",
    "טיפול": "צו טיפול",
}


# ── helpers ──────────────────────────────────────────────────────────────

def n(v):
    return f"{int(round(v)):,}"


def iso(s):
    return f"{LRI}{s}{PDI}"


def pct(v, digits=1):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def rng(lo, hi):
    if lo == hi:
        return iso(n(lo))
    return f"{iso(n(lo))} עד {iso(n(hi))}"


def norm_col(c):
    c = str(c).replace("/", " ")
    return re.sub(r"\s+", " ", c).strip()


def norm_place(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return re.sub(r"\s*-\s*", "-", s)


def norm_district(s):
    s = re.sub(r"\s+", " ", str(s)).strip()
    if not s:
        return "לא צוין"
    return DISTRICT_MAP.get(s, s)


def parse_cells(series):
    """-> (exact values, suppressed flags) for a raw text column."""
    s = series.fillna("").astype(str).str.strip()
    supp = s.str.contains("בין", regex=False)
    v = pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce").fillna(0)
    v = v.where(~supp, 0)
    return v.astype(float), supp.astype(int)


def year_of(name):
    m = re.search(r"(20\d{2})", str(name))
    return int(m.group(1)) if m else None


def split_files(df):
    """Yield (resource_name, frame-with-normalised-columns) per file, sorted by name."""
    if df is None or len(df) == 0:
        return []
    out = []
    for name in sorted(df[RES].unique()):
        part = df[df[RES] == name].drop(columns=[RES])
        part = part.dropna(axis=1, how="all")
        part.columns = [norm_col(c) for c in part.columns]
        part = part.loc[:, ~pd.Index(part.columns).duplicated()]
        out.append((name, part))
    return out


def loc_col(cols):
    for c in cols:
        if "ישוב" in c and "מחוז" not in c:
            return c
    return None


# ── caseload (referrals / offences) ─────────────────────────────────────

def load_caseload(df):
    """-> long frame [year, kind, district, town, valid_town, group, exact, supp]
    plus totals frame [year, kind, district, town, valid_town, exact, supp]; skipped years."""
    longs, tots, skipped = [], [], []
    seen = set()
    for name, part in split_files(df):
        y = year_of(name)
        lc = loc_col(part.columns)
        tot_cols = [c for c in part.columns if c.startswith("סה") or c.startswith("סך")]
        kind = None
        if tot_cols:
            tc = tot_cols[0]
            if "הפניות" in tc:
                kind = "ref"
            elif "עבירות" in tc:
                kind = "off"
        if kind is None:
            if "הפניות" in name:
                kind = "ref"
            elif "עביר" in name:
                kind = "off"
        if y is None or lc is None or "מחוז" not in part.columns or not tot_cols or kind is None:
            if y is not None:
                skipped.append(y)
            continue
        if (y, kind) in seen:      # a duplicate upload of the same table: first by name wins
            continue
        seen.add((y, kind))
        town = part[lc].fillna("").astype(str).map(norm_place)
        keep = (town != "") & ~town.str.startswith("סה")
        part = part[keep]
        town = town[keep]
        dist = part["מחוז"].map(norm_district)
        valid = ~town.str.fullmatch(r"[\d\s]*")
        base = pd.DataFrame({"year": y, "kind": kind, "district": dist.values,
                             "town": town.values, "valid_town": valid.values})
        te, ts = parse_cells(part[tot_cols[0]])
        t = base.copy()
        t["exact"] = te.values
        t["supp"] = ts.values
        tots.append(t)
        for c in part.columns:
            if c in ("מחוז", lc) or c in tot_cols:
                continue
            e, s = parse_cells(part[c])
            g = base.copy()
            g["group"] = c
            g["exact"] = e.values
            g["supp"] = s.values
            longs.append(g)
    cols_l = ["year", "kind", "district", "town", "valid_town", "group", "exact", "supp"]
    cols_t = ["year", "kind", "district", "town", "valid_town", "exact", "supp"]
    L = pd.concat(longs, ignore_index=True) if longs else pd.DataFrame(columns=cols_l)
    T = pd.concat(tots, ignore_index=True) if tots else pd.DataFrame(columns=cols_t)
    return L, T, sorted(set(skipped))


def load_decisions(df):
    longs, seen = [], set()
    for name, part in split_files(df):
        y = year_of(name)
        lc = loc_col(part.columns)
        if y is None or lc is None or "מחוז" not in part.columns or y in seen:
            continue
        seen.add(y)
        town = part[lc].fillna("").astype(str).map(norm_place)
        keep = (town != "") & ~town.str.startswith("סה")
        part = part[keep]
        town = town[keep]
        dist = part["מחוז"].map(norm_district)
        valid = ~town.str.fullmatch(r"[\d\s]*")
        for c in part.columns:
            if c in ("מחוז", lc):
                continue
            e, s = parse_cells(part[c])
            longs.append(pd.DataFrame({"year": y, "district": dist.values, "town": town.values,
                                       "valid_town": valid.values, "type": c,
                                       "exact": e.values, "supp": s.values}))
    cols = ["year", "district", "town", "valid_town", "type", "exact", "supp"]
    return pd.concat(longs, ignore_index=True) if longs else pd.DataFrame(columns=cols)


def agg(df, keys):
    g = df.groupby(keys, sort=True)[["exact", "supp"]].sum().reset_index()
    g["lo"] = g["exact"] + g["supp"]
    g["hi"] = g["exact"] + g["supp"] * SUPP_HI
    return g


def order_groups(groups):
    known = [g for g in GROUP_ORDER if g in groups]
    return known + sorted(g for g in groups if g not in GROUP_ORDER)


def gshort(g):
    return GROUP_SHORT.get(g, g)


def dlabel(t):
    return DEC_LABEL.get(t, t)


# ── main ─────────────────────────────────────────────────────────────────

def compute(frames):
    L, T, skipped_years = load_caseload(frames.get("caseload"))
    D = load_decisions(frames.get("decisions"))

    ref_T = T[T["kind"] == "ref"]
    off_T = T[T["kind"] == "off"]
    ref_L = L[L["kind"] == "ref"]
    off_L = L[L["kind"] == "off"]
    ref_years = sorted(int(y) for y in ref_T["year"].unique())
    off_years = sorted(int(y) for y in off_T["year"].unique())
    dec_years = sorted(int(y) for y in D["year"].unique())
    if not ref_years or not dec_years:
        raise ValueError("no usable referral or decision file")
    Y = ref_years[-1]
    DY = dec_years[-1]
    insights, labels, charts, tables, kpis, flags = [], {}, {}, {}, {}, {}

    # yearly totals
    ry = agg(ref_T, ["year"]).set_index("year")
    oy = agg(off_T, ["year"]).set_index("year") if len(off_T) else None
    years_all = sorted(set(ref_years) | set(off_years))
    yr = {"x": [str(y) for y in years_all], "ref_lo": [], "ref_band": [], "off_lo": [], "off_band": []}
    tables["years"] = []
    for y in years_all:
        r = ry.loc[y] if y in ry.index else None
        o = oy.loc[y] if (oy is not None and y in oy.index) else None
        yr["ref_lo"].append(int(r["lo"]) if r is not None else None)
        yr["ref_band"].append(int(r["hi"] - r["lo"]) if r is not None else None)
        yr["off_lo"].append(int(o["lo"]) if o is not None else None)
        yr["off_band"].append(int(o["hi"] - o["lo"]) if o is not None else None)
        ratio = None
        if r is not None and o is not None and r["exact"] > 0:
            ratio = o["exact"] / r["exact"]
        tables["years"].append({
            "year": str(y),
            "ref": rng(r["lo"], r["hi"]) if r is not None else "",
            "off": rng(o["lo"], o["hi"]) if o is not None else "",
            "ratio": f"{ratio:.2f}" if ratio is not None else "",
        })
    charts["years"] = yr
    supp_years = [str(y) for y in ref_years if ry.loc[y, "supp"] > 0]
    labels["years_note"] = (
        "ההפניות (מקרים שהועברו לשירות) והעבירות שיוחסו בהן, לפי שנה. "
        + (f"בשנים {', '.join(supp_years)} ערכים קטנים פורסמו כ\"בין 1 ל-10\", ולכן כל סכום הוא טווח: "
           "העמודה הכהה היא הערך המינימלי והחלק הבהיר הוא התוספת האפשרית. " if supp_years else "")
        + (f"קובצי ההפניות והעבירות של {', '.join(str(s) for s in skipped_years)} פורסמו ללא שמות יישובים "
           "ולא נכללו." if skipped_years else "")
    ).strip()
    labels["years_aria"] = f"הפניות ועבירות לפי שנה, {years_all[0]} עד {years_all[-1]}"

    r_cur = ry.loc[Y]
    o_cur = oy.loc[Y] if (oy is not None and Y in oy.index) else None

    # trend insight (ranges must not overlap)
    if len(ref_years) >= 2:
        P = ref_years[-2]
        r_prev = ry.loc[P]
        if r_cur["lo"] > r_prev["hi"]:
            ch = r_cur["lo"] / r_prev["hi"] - 1
            insights.append({"id": "trend", "text_he":
                f"מספר ההפניות לשירות המבחן לנוער עלה: {rng(r_cur['lo'], r_cur['hi'])} הפניות ב-{Y}, "
                f"לעומת {rng(r_prev['lo'], r_prev['hi'])} ב-{P}, עלייה של {pct(ch)} לפחות."})
        elif r_cur["hi"] < r_prev["lo"]:
            ch = 1 - r_cur["hi"] / r_prev["lo"]
            insights.append({"id": "trend", "text_he":
                f"מספר ההפניות לשירות המבחן לנוער ירד: {rng(r_cur['lo'], r_cur['hi'])} הפניות ב-{Y}, "
                f"לעומת {rng(r_prev['lo'], r_prev['hi'])} ב-{P}, ירידה של {pct(ch)} לפחות."})
        else:
            insights.append({"id": "trend", "text_he":
                f"ב-{Y} נרשמו {rng(r_cur['lo'], r_cur['hi'])} הפניות לשירות המבחן לנוער, לעומת "
                f"{rng(r_prev['lo'], r_prev['hi'])} ב-{P}. הטווחים חופפים בגלל ערכים חסויים, ולכן "
                "אי אפשר לקבוע מהנתונים שחל שינוי של ממש."})

    # KPIs
    kpis["ref"] = {"value": int(r_cur["lo"]), "display": n(r_cur["lo"]), "tone": "brand"}
    labels["kpi_ref"] = f"הפניות לשירות ב-{Y} (לפחות)"
    if o_cur is not None:
        kpis["off"] = {"value": int(o_cur["lo"]), "display": n(o_cur["lo"]), "tone": "brand"}
        labels["kpi_off"] = f"עבירות שיוחסו בהפניות ב-{Y} (לפחות)"
        ratio = o_cur["exact"] / r_cur["exact"] if r_cur["exact"] else 0
        kpis["ratio"] = {"value": round(ratio, 2), "display": f"{ratio:.2f}", "tone": "info"}
        labels["kpi_ratio"] = f"עבירות להפניה ב-{Y} (ערכים מדויקים)"
    dec_cur = agg(D[D["year"] == DY], ["year"]).iloc[0]
    kpis["dec"] = {"value": int(dec_cur["lo"]), "display": n(dec_cur["lo"]), "tone": "brand"}
    labels["kpi_dec"] = f"החלטות בית משפט ב-{DY} (לפחות)"
    towns_cur = ref_T[(ref_T["year"] == Y) & ref_T["valid_town"] & ((ref_T["exact"] > 0) | (ref_T["supp"] > 0))]
    ntowns = towns_cur["town"].nunique()
    kpis["towns"] = {"value": int(ntowns), "display": n(ntowns), "tone": "brand"}
    labels["kpi_towns"] = f"יישובים שמהם הגיעו הפניות ב-{Y}"
    kpis["years"] = {"value": len(set(years_all) | set(dec_years)),
                     "display": f"{min(min(years_all), min(dec_years))}–{max(max(years_all), max(dec_years))}",
                     "tone": "brand"}
    labels["kpi_years"] = "שנות הנתונים במאגר"

    # referrals by offence group, latest year
    gcur = agg(ref_L[ref_L["year"] == Y], ["group"]).set_index("group")
    groups = order_groups(list(gcur.index))
    gsorted = sorted(groups, key=lambda g: (-gcur.loc[g, "lo"], g))
    gtot_lo = gcur["lo"].sum()
    charts["groups"] = {"names": [gshort(g) for g in gsorted],
                        "lo": [int(gcur.loc[g, "lo"]) for g in gsorted],
                        "band": [int(gcur.loc[g, "hi"] - gcur.loc[g, "lo"]) for g in gsorted]}
    tables["groups"] = [{"name": g, "range": rng(gcur.loc[g, "lo"], gcur.loc[g, "hi"]),
                         "share": pct(gcur.loc[g, "lo"] / gtot_lo) if gtot_lo else ""} for g in gsorted]
    labels["groups_aria"] = f"הפניות לפי קבוצת עבירה ב-{Y}"
    labels["groups_note"] = (f"מספר ההפניות ב-{Y} לפי קבוצת העבירה. הפניה אחת יכולה להיכלל ביותר מקבוצה אחת, "
                             "ולכן סכום הקבוצות גבוה מסך ההפניות. השיעור בטבלה מחושב מסכום הקבוצות.")
    if len(gsorted) >= 2:
        a, b = gsorted[0], gsorted[1]
        if gcur.loc[a, "lo"] > gcur.loc[b, "hi"]:
            insights.append({"id": "lead_group", "text_he":
                f"קבוצת העבירה המובילה בהפניות של {Y} היא {a}: {rng(gcur.loc[a, 'lo'], gcur.loc[a, 'hi'])} "
                f"הפניות, {pct(gcur.loc[a, 'lo'] / gtot_lo)} מסכום הקבוצות, לפני {b} "
                f"({rng(gcur.loc[b, 'lo'], gcur.loc[b, 'hi'])})."})
        else:
            insights.append({"id": "lead_group", "text_he":
                f"שתי קבוצות עבירה מובילות כמעט שוות בהפניות של {Y}: {a} ({rng(gcur.loc[a, 'lo'], gcur.loc[a, 'hi'])}) "
                f"ו{b} ({rng(gcur.loc[b, 'lo'], gcur.loc[b, 'hi'])}). יחד הן {pct((gcur.loc[a, 'lo'] + gcur.loc[b, 'lo']) / gtot_lo)} "
                "מסכום הקבוצות."})

    # mix of groups by year (100% stacked, shares from low bounds)
    gy = agg(ref_L, ["year", "group"])
    all_groups = order_groups(sorted(gy["group"].unique()))
    mix = {"x": [str(y) for y in ref_years], "series": []}
    share_tab = {}
    for g in all_groups:
        vals = []
        for y in ref_years:
            sub = gy[gy["year"] == y]
            tot = sub["lo"].sum()
            row = sub[sub["group"] == g]
            v = round(float(row["lo"].iloc[0] / tot * 100), 1) if (len(row) and tot) else None
            vals.append(v)
        mix["series"].append({"name": gshort(g), "data": vals})
        share_tab[g] = vals
    charts["mix"] = mix
    tables["mix_head"] = [str(y) for y in ref_years]
    tables["mix"] = [{"name": g, "vals": [("" if v is None else f"{v:.1f}%") for v in share_tab[g]]}
                     for g in all_groups]
    labels["mix_aria"] = f"התפלגות ההפניות לפי קבוצת עבירה, {ref_years[0]} עד {ref_years[-1]}"
    labels["mix_note"] = ("שיעור כל קבוצת עבירה מסכום הקבוצות בכל שנה, לפי הערכים המינימליים. "
                          "שינויים חדים בין שנים עשויים לשקף גם שינוי באופן הסיווג.")
    if len(ref_years) >= 3:
        y0 = ref_years[0]
        best = None
        for g in all_groups:
            v0, v1 = share_tab[g][0], share_tab[g][-1]
            if v0 is None or v1 is None:
                continue
            d = v1 - v0
            if best is None or abs(d) > abs(best[1]) or (abs(d) == abs(best[1]) and g < best[0]):
                best = (g, d, v0, v1)
        if best and abs(best[1]) >= 5:
            g, d, v0, v1 = best
            word = "עלה" if d > 0 else "ירד"
            insights.append({"id": "mix_shift", "text_he":
                f"השינוי הבולט בתמהיל ההפניות: חלקה של קבוצת {g} {word} מ-{iso(f'{v0:.1f}%')} ב-{y0} "
                f"ל-{iso(f'{v1:.1f}%')} ב-{Y}, לפי הנתונים כפי שפורסמו (ייתכן שחלק מהשינוי נובע משינוי בסיווג)."})

    # districts, latest year: referrals stacked by group
    dg = agg(ref_L[ref_L["year"] == Y], ["district", "group"])
    dt = agg(ref_T[ref_T["year"] == Y], ["district"]).set_index("district")
    dists = sorted(dt.index, key=lambda d: (-dt.loc[d, "lo"], d))
    dsec = {"names": dists, "series": []}
    for g in groups:
        vals = []
        for d in dists:
            row = dg[(dg["district"] == d) & (dg["group"] == g)]
            vals.append(int(row["lo"].iloc[0]) if len(row) else 0)
        dsec["series"].append({"name": gshort(g), "data": vals})
    charts["districts"] = dsec
    dtot_lo = dt["lo"].sum()
    off_d = agg(off_T[off_T["year"] == Y], ["district"]).set_index("district") if len(off_T) else None
    tables["districts"] = []
    for d in dists:
        sub = dg[dg["district"] == d].sort_values(["lo", "group"], ascending=[False, True])
        tables["districts"].append({
            "name": d, "ref": rng(dt.loc[d, "lo"], dt.loc[d, "hi"]),
            "share": pct(dt.loc[d, "lo"] / dtot_lo) if dtot_lo else "",
            "off": (rng(off_d.loc[d, "lo"], off_d.loc[d, "hi"]) if off_d is not None and d in off_d.index else ""),
            "top": sub["group"].iloc[0] if len(sub) else "",
        })
    labels["districts_aria"] = f"הפניות לפי מחוז וקבוצת עבירה ב-{Y}"
    labels["districts_note"] = (f"הפניות ב-{Y} לפי מחוז השירות, בחלוקה לקבוצות עבירה (ערכים מינימליים). "
                                "מחוז הוא מחוז שירות המבחן שטיפל בהפניה, ויישוב אחד יכול להופיע ביותר ממחוז אחד.")
    if dists and dtot_lo:
        top = dists[0]
        sh = dt.loc[top, "lo"] / dtot_lo
        second_ok = len(dists) < 2 or dt.loc[top, "lo"] > dt.loc[dists[1], "hi"]
        if sh >= DISTRICT_SHARE_MIN and second_ok:
            insights.append({"id": "district", "text_he":
                f"מחוז {top} הוא העמוס ביותר: {pct(sh)} מההפניות ב-{Y} "
                f"({rng(dt.loc[top, 'lo'], dt.loc[top, 'hi'])}), יותר מכל מחוז אחר."})

    # district trend (referrals per district per year)
    dy = agg(ref_T, ["year", "district"])
    dtr = {"x": [str(y) for y in ref_years], "series": []}
    tables["dtrend"] = []
    for d in dists:
        vals = []
        for y in ref_years:
            row = dy[(dy["year"] == y) & (dy["district"] == d)]
            vals.append(int(row["lo"].iloc[0]) if len(row) else None)
        dtr["series"].append({"name": d, "data": vals})
        tables["dtrend"].append({"name": d, "vals": [("" if v is None else n(v)) for v in vals]})
    charts["dtrend"] = dtr
    labels["dtrend_aria"] = f"הפניות לפי מחוז, {ref_years[0]} עד {ref_years[-1]}"
    labels["dtrend_note"] = "מספר ההפניות בכל מחוז לאורך השנים (ערכים מינימליים, מחוזות לפי שמם הנוכחי)."

    # top localities, latest year (summed across districts)
    tw = agg(ref_T[(ref_T["year"] == Y) & ref_T["valid_town"]], ["town"])
    tw = tw.sort_values(["lo", "town"], ascending=[False, True]).reset_index(drop=True)
    two = agg(off_T[(off_T["year"] == Y) & off_T["valid_town"]], ["town"]).set_index("town") if len(off_T) else None
    top_t = tw.head(TOP_TOWNS)
    charts["towns"] = {"names": top_t["town"].tolist(), "ref": [int(v) for v in top_t["lo"]],
                       "off": [int(two.loc[t, "lo"]) if two is not None and t in two.index else None
                               for t in top_t["town"]]}
    tables["towns"] = [{"name": r.town, "ref": rng(r.lo, r.hi),
                        "off": (rng(two.loc[r.town, "lo"], two.loc[r.town, "hi"]) if two is not None and r.town in two.index else "")}
                       for r in top_t.itertuples()]
    labels["towns_aria"] = f"היישובים עם מספר ההפניות הגבוה ביותר ב-{Y}"
    labels["towns_note"] = (f"{len(top_t)} היישובים שמהם הגיעו הכי הרבה הפניות ב-{Y}, עם מספר העבירות שיוחסו בהן. "
                            "יישוב שמופיע בכמה מחוזות מסוכם יחד.")
    all_lo = ref_T[(ref_T["year"] == Y)]["exact"].sum() + ref_T[(ref_T["year"] == Y)]["supp"].sum()
    if len(tw) >= 10 and all_lo:
        t1 = tw.iloc[0]
        sh10 = tw.head(10)["lo"].sum() / all_lo
        insights.append({"id": "towns", "text_he":
            f"היישוב עם מספר ההפניות הגבוה ביותר ב-{Y} הוא {t1.town} ({rng(t1.lo, t1.hi)}). "
            f"עשרת היישובים המובילים מרכזים {pct(sh10)} מההפניות, מתוך {iso(n(ntowns))} יישובים."})

    # offences per referral by group, latest year
    flags["intensity"] = False
    if len(off_L) and Y in off_years:
        og = agg(off_L[off_L["year"] == Y], ["group"]).set_index("group")
        rows = []
        for g in groups:
            if g in og.index and gcur.loc[g, "exact"] >= INTENSITY_MIN:
                rows.append((g, og.loc[g, "exact"] / gcur.loc[g, "exact"]))
        rows.sort(key=lambda r: (-r[1], r[0]))
        if len(rows) >= 3:
            flags["intensity"] = True
            charts["intensity"] = {"names": [gshort(g) for g, _ in rows], "values": [round(v, 2) for _, v in rows]}
            tables["intensity"] = [{"name": g, "val": f"{v:.2f}"} for g, v in rows]
            labels["intensity_aria"] = f"עבירות להפניה לפי קבוצת עבירה ב-{Y}"
            labels["intensity_note"] = (f"כמה עבירות יוחסו בממוצע להפניה אחת בכל קבוצה ב-{Y}, לפי הערכים המדויקים בלבד "
                                        f"(קבוצות עם {iso(n(INTENSITY_MIN))} הפניות לפחות).")
            g0, v0 = rows[0]
            gl, vl = rows[-1]
            if v0 >= 1.3 * vl:
                insights.append({"id": "intensity", "text_he":
                    f"בהפניות על {g0} יוחסו בממוצע {iso(f'{v0:.2f}')} עבירות להפניה ב-{Y}, "
                    f"לעומת {iso(f'{vl:.2f}')} בלבד ב{gl}."})

    # court decisions, latest year
    dcur = agg(D[D["year"] == DY], ["type"])
    dcur = dcur.sort_values(["lo", "type"], ascending=[False, True]).reset_index(drop=True)
    d_tot = dcur["lo"].sum()
    charts["dec"] = {"names": [dlabel(t) for t in dcur["type"]], "lo": [int(v) for v in dcur["lo"]],
                     "band": [int(h - l) for l, h in zip(dcur["lo"], dcur["hi"])]}
    tables["dec"] = [{"name": dlabel(r.type), "range": rng(r.lo, r.hi), "share": pct(r.lo / d_tot) if d_tot else ""}
                     for r in dcur.itertuples()]
    labels["dec_aria"] = f"החלטות בית משפט לפי סוג ב-{DY}"
    labels["dec_note"] = (f"החלטות שהתקבלו בדיונים בבתי המשפט לנוער ב-{DY} לפי סוג ההחלטה. "
                          "נער אחד יכול להיות מעורב בכמה דיונים ובכמה החלטות.")
    if len(dcur) >= 2 and d_tot:
        a, b = dcur.iloc[0], dcur.iloc[1]
        if a.lo > b.hi:
            insights.append({"id": "dec_lead", "text_he":
                f"ההחלטה השכיחה ביותר בבתי המשפט לנוער ב-{DY} היא {dlabel(a.type)}: {rng(a.lo, a.hi)} החלטות, "
                f"{pct(a.lo / d_tot)} מכלל ההחלטות. אחריה {dlabel(b.type)} ({pct(b.lo / d_tot)})."})
    rel = dcur[dcur["type"].isin(["טיפול", "עיכוב הליכים", "ביטול כתב אישום"])]
    pris = dcur[dcur["type"].isin(["מאסר"])]
    if len(pris) and len(rel) and d_tot:
        p_lo = pris["lo"].sum()
        r_lo = rel["lo"].sum()
        insights.append({"id": "dec_custody", "text_he":
            f"החלטות מאסר בפועל היו ב-{DY} {pct(p_lo / d_tot)} מההחלטות ({rng(p_lo, pris['hi'].sum())}). "
            f"החלטות של צו טיפול, עיכוב הליכים או ביטול כתב אישום: {rng(r_lo, rel['hi'].sum())}."})

    # decisions by district, latest year (100% stacked over top types)
    top_types = dcur["type"].head(TOP_DEC_TYPES).tolist()
    ddist = agg(D[D["year"] == DY], ["district", "type"])
    ddt = agg(D[D["year"] == DY], ["district"]).set_index("district")
    ddists = sorted(ddt.index, key=lambda d: (-ddt.loc[d, "lo"], d))
    dd = {"names": ddists, "series": []}
    for t in top_types + ["__other__"]:
        vals = []
        for d in ddists:
            sub = ddist[ddist["district"] == d]
            tot = sub["lo"].sum()
            v = sub[~sub["type"].isin(top_types)]["lo"].sum() if t == "__other__" else sub[sub["type"] == t]["lo"].sum()
            vals.append(round(float(v / tot * 100), 1) if tot else 0)
        dd["series"].append({"name": "סוגים אחרים" if t == "__other__" else dlabel(t), "data": vals})
    charts["dec_dist"] = dd
    tables["dec_dist"] = []
    for d in ddists:
        sub = ddist[ddist["district"] == d].sort_values(["lo", "type"], ascending=[False, True])
        tot = sub["lo"].sum()
        tables["dec_dist"].append({"name": d, "total": rng(ddt.loc[d, "lo"], ddt.loc[d, "hi"]),
                                   "top": dlabel(sub["type"].iloc[0]) if len(sub) else "",
                                   "share": pct(sub["lo"].iloc[0] / tot) if tot else ""})
    labels["dec_dist_aria"] = f"תמהיל החלטות בית המשפט לפי מחוז ב-{DY}"
    labels["dec_dist_note"] = (f"שיעור כל סוג החלטה מסך ההחלטות בכל מחוז ב-{DY} ({len(top_types)} הסוגים "
                               "השכיחים, והשאר יחד). מחושב מהערכים המינימליים.")

    # decisions heat: type x year, as published
    dyt = agg(D, ["year", "type"])
    types_all = sorted(dyt["type"].unique(),
                       key=lambda t: (-dyt[(dyt["type"] == t) & (dyt["year"] == DY)]["lo"].sum(), t))
    heat_cells, hmax = [], 0
    for xi, y in enumerate(dec_years):
        for yi, t in enumerate(types_all):
            row = dyt[(dyt["year"] == y) & (dyt["type"] == t)]
            if len(row):
                v = int(row["lo"].iloc[0])
                heat_cells.append([xi, yi, v])
                hmax = max(hmax, v)
    charts["dec_heat"] = {"x": [str(y) for y in dec_years], "y": [dlabel(t) for t in types_all],
                          "cells": heat_cells, "max": hmax}
    tables["dec_heat_head"] = [str(y) for y in dec_years]
    tables["dec_heat"] = []
    for t in types_all:
        vals = []
        for y in dec_years:
            row = dyt[(dyt["year"] == y) & (dyt["type"] == t)]
            vals.append(n(row["lo"].iloc[0]) if len(row) else "")
        tables["dec_heat"].append({"name": dlabel(t), "vals": vals})
    labels["dec_heat_aria"] = f"החלטות בית משפט לפי סוג ושנה, {dec_years[0]} עד {dec_years[-1]}"
    missing = [dlabel(t) for t in types_all if (dyt["type"] == t).sum() < len(dec_years)]
    labels["dec_heat_note"] = ("מספר ההחלטות מכל סוג בכל שנה, כפי שפורסמו (ערכים מינימליים). "
                               + (f"חלק מהסוגים לא פורסמו בכל השנים ({', '.join(missing)}), ותא ריק פירושו שהסוג לא פורסם. " if missing else "")
                               + "היקפי הסוגים משתנים מאוד בין השנים, ככל הנראה גם בגלל שינויי רישום, ולכן כדאי להשוות בזהירות.")

    # summary / lede
    summary = (f"נתוני שירות המבחן לנוער לפי יישוב ומחוז: הפניות, עבירות והחלטות בתי משפט לנוער. "
               f"ב-{Y} {iso(n(r_cur['lo']))} הפניות לפחות מ-{iso(n(ntowns))} יישובים.")
    lede = (f"הפניות, עבירות והחלטות בתי המשפט לנוער שבטיפול שירות המבחן לנוער, לפי מחוז ויישוב, "
            f"בשנים {min(min(years_all), min(dec_years))} עד {max(max(years_all), max(dec_years))}. "
            f"ב-{Y} הגיעו לשירות {rng(r_cur['lo'], r_cur['hi'])} הפניות מ-{iso(n(ntowns))} יישובים"
            + (f", ויוחסו בהן {rng(o_cur['lo'], o_cur['hi'])} עבירות." if o_cur is not None else ".")
            + " הנתונים מצרפיים, וערכים קטנים פורסמו כטווח \"בין 1 ל-10\" כדי לשמור על פרטיות.")
    labels["lede"] = lede

    t0 = min(min(years_all), min(dec_years))
    t1 = max(max(years_all), max(dec_years))
    agent = {
        "summary_he": summary,
        "dataset_kind": "timeseries",
        "suggested_tags": ["נוער", "עבריינות נוער", "שירות המבחן", "בתי משפט לנוער", "רווחה"],
        "related_ids": ["fae447eb-6f24-45ed-ac48-b890e11daf13", "12ac3fa6-ac57-41d6-8519-17a3435754a7",
                        "ce12ebb6-fbec-4134-80b1-79d068bd96ee", "993ed1f3-0a55-4c31-addc-f15f30ce9790",
                        "edb5f516-28b1-439e-828a-43ec3a3cc82f"],
        "temporal_coverage": f"{t0}/{t1}",
        "spatial_coverage": "ישראל",
    }
    kpi_keys = [k for k in ["ref", "off", "ratio", "dec", "towns", "years"] if k in kpis]
    return {"agent_data": agent, "kpis": kpis, "kpi_keys": kpi_keys, "charts": charts, "tables": tables,
            "insights": insights, "labels": labels, "flags": flags,
            "years": {"ref": Y, "dec": DY}}
