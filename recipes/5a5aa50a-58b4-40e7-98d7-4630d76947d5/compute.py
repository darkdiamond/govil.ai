"""יצרני ועסקי מזון בעלי רישיון יצרן — Ministry of Health register of food
business licences (National Food Service).

One row per licence (~5k): holder name, licence type (factory, bakery,
transport, storage, catering, butcher ...), health district, settlement,
recorded licence expiry date, GMP certificate flag + its expiry, and a free-
text product/activity description.

Licence types are folded into five activity groups (production, transport,
storage, catering, retail); an unknown new type falls into a group by keyword,
else "אחר". The free-text product field is classified by keyword into food
categories (multi-label) for production licences only — disclosed on the page.

There is no export / "as of" date in the data, and the clock is banned, so
the page never labels a licence "expired": expiry dates are shown as
recorded (by year, by month-of-year, and as a per-group distribution).

Holder names are businesses (companies, cooperatives, sole traders) and may
be named. Licence numbers, street addresses and holder titles that carry no
letters (a handful of transport licences are titled by a vehicle number) never
reach the page.
"""
import re

import pandas as pd

OTHER = "אחר"
UNKNOWN_CITY = "לא רשום"

G_PROD, G_TRANS, G_STORE, G_CATER, G_RETAIL = "ייצור ואריזה", "הובלה", "אחסנה", "הסעדה", "קמעונאות"
GROUP_ORDER = [G_PROD, G_TRANS, G_STORE, G_CATER, G_RETAIL, OTHER]
GROUP_COLOR = {G_PROD: "#0068f5", G_TRANS: "#0b3668", G_STORE: "#5b9cf8",
               G_CATER: "#8fb8f2", G_RETAIL: "#3d5a80", OTHER: "#adb5bd"}
GROUP_OF = {
    "מפעל מזון/יצור מזון": G_PROD, "מפעל בשר": G_PROD, "מאפיה": G_PROD,
    "קונדיטוריה": G_PROD, "טחנת קמח": G_PROD, "דגנים מעובדים": G_PROD,
    "אריזת מזון": G_PROD, "סימון/הדבקת תוויות": G_PROD,
    "הובלת מזון בטמפ מבוקרת": G_TRANS, "הובלת מזון בטמפ' שאינה מבוקרת": G_TRANS,
    "מחסן מזון בטמפ מבוקרת": G_STORE, "מחסן מזון שאיננו בטמפ מבוקרת": G_STORE,
    "מחסן מזון": G_STORE,
    "הסעדה/קייטרינג": G_CATER, "אולם/גן שמחות אירעים": G_CATER,
    "אטליז בשר": G_RETAIL, "אטליז דגים": G_RETAIL, "מרכול": G_RETAIL,
}
GROUP_KEYWORDS = [(G_TRANS, "הובל"), (G_STORE, "מחסן|אחסנ|קירור"),
                  (G_CATER, "הסעד|קייטר|אולם"), (G_RETAIL, "אטליז|מרכול|חנות"),
                  (G_PROD, "מפעל|יצור|ייצור|מאפ|קונדיטור|אריז|טחנ")]
TYPE_SHORT = {
    "מפעל מזון/יצור מזון": "מפעל מזון", "הובלת מזון בטמפ' שאינה מבוקרת": "הובלה שלא בקירור",
    "הובלת מזון בטמפ מבוקרת": "הובלה בטמפ׳ מבוקרת", "מחסן מזון בטמפ מבוקרת": "מחסן בטמפ׳ מבוקרת",
    "מחסן מזון שאיננו בטמפ מבוקרת": "מחסן שלא בקירור", "הסעדה/קייטרינג": "הסעדה וקייטרינג",
    "אולם/גן שמחות אירעים": "אולם אירועים", "סימון/הדבקת תוויות": "סימון תוויות",
}
PROD_CATS = [
    ("מאפה ולחם", r"מאפ|לחם|לחמ|פית|חלות|בצק|קרקר|מצות|מצה|בייגל|פיצ|קרואס|בריוש"),
    ("עוגות וקונדיטוריה", r"עוג|קונדיטור|קינוח|קצפ|טארט|פחזני"),
    ("פירות, ירקות וקטניות", r"פירות|פרי[ ,.\-]|פרי$|ירק|קטני|תמר|שום|בצל|גזר|פטרי|ריבות|ריבה|שימור|כבוש|נבט|טופו"),
    ("ממרחים, רטבים ושמנים", r"ממרח|רטב|סלט|חומוס|מטבל|טחינה|חומץ|מיונז|שמן|שמנים|זית"),
    ("קפה, פיצוחים ותבלינים", r"קפה|פיצוח|תבלינ|אגוז|בוטנ|שקד|גרעינ|קלי[יה]|חליטות|מלח"),
    ("חלב וגבינות", r"חלב|גבינ|יוגורט|לבנה|לאבנה|חמאה|שמנת|מחלב|קפיר"),
    ("מזון מוכן", r"ארוח|מזון מוכן|מנות|כריכ|פלאפל|קיש|ממולא|כיסונ|לאכילה|ג'חנון|מלאווח|בורקס|מרק|קציצ|סמבוס|לביבות"),
    ("משקאות", r"משקא|משקה|יין|יינות|יקב|בירה|מיץ|מיצים|ליקר|ערק|וודקה|מים|מי שתי|סודה|קומבוצ|סיידר|אלכוהול|מזקק"),
    ("בשר, עוף וביצים", r"בשר|בקר|עוף|עופות|כנף|נקניק|בהמות|כבש|הודו|שניצל|קבב|המבורגר|שווארמה|פסטרמה|ביצ"),
    ("ממתקים וחטיפים", r"שוקולד|ממתק|סוכרי|חטיף|חלוו|מרשמלו|פרלינ"),
    ("דגנים, קמח ופסטה", r"קמח|דגנ|פסטה|אטריות|גרנולה|אורז|פתיתים|קוסקוס|מוזלי|דייס"),
    ("גלידה", r"גליד|ארטיק|סורבה"),
    ("תוספי תזונה", r"תוס[פף]י? ?תזונה|תוספי מזון|ויטמינ|מינרל"),
    ("דבש", r"דבש"),
    ("דגים", r"דגים|דג |דג,|סושי|סלמון|הרינג|טונה"),
]
LEGAL = [("אגודה שיתופית", r'אגודה|אגש"ח|אגש״ח|אגשח|אגש"ת'),
         ("חברה בע״מ", r'בע"מ|בעמ|בע״מ|בע\'\'מ|\bltd\b'),
         ("שותפות", r'שותפות|ש"מ\b'),
         ("עמותה / חל״צ", r'עמותה|ע"ר|חל"צ|חל״צ')]
LEGAL_NONE = "ללא ציון צורה משפטית"
TOP_TYPES = 11
TOP_CITIES = 15
TOP_HOLDERS = 15
LQ_TYPES = 8
HOLD_BUCKETS = [(1, 1, "1"), (2, 2, "2"), (3, 5, "3–5"), (6, 10, "6–10"), (11, None, "11+")]
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
LRI, PDI = "⁦", "⁩"
HAS_LETTER = re.compile(r"[א-תA-Za-z]")


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _group(t):
    if t in GROUP_OF:
        return GROUP_OF[t]
    for g, pat in GROUP_KEYWORDS:
        if re.search(pat, t):
            return g
    return OTHER


def _short(t):
    return TYPE_SHORT.get(t, t) or "לא צוין"


def _legal(title):
    for name, pat in LEGAL:
        if re.search(pat, title, flags=re.I):
            return name
    return LEGAL_NONE


def _holder_key(title):
    t = re.sub(r"\([^)]*\)", " ", title)
    t = re.sub(r'בע"מ|בעמ|בע״מ|בע\'\'מ|אגש"ח|אגשח|אגודה שיתופית( חקלאית)?', " ", t)
    t = re.sub(r"[\s\-–\"'״׳.,()]", "", t)
    return t.replace("י", "").replace("ו", "").lower()


def _date(s):
    return pd.to_datetime(s.str.strip().str[:10], errors="coerce", format="%Y-%m-%d")


def _canon(keys, names):
    """Most frequent display spelling per key (ties by name)."""
    v = (pd.DataFrame({"k": keys, "name": names}).groupby(["k", "name"]).size()
         .reset_index(name="c").sort_values(["k", "c", "name"], ascending=[True, False, True]))
    return v.drop_duplicates("k").set_index("k")["name"]


def _prepare(df):
    out = pd.DataFrame({
        "title": df["title"].str.strip().str.replace(r"\s+", " ", regex=True),
        "type": df["accountType"].str.strip(),
        "district": df["health_district_desc"].str.strip().replace("", "לא צוין"),
        "product": df["ProductActivityFoodType"].str.strip(),
        "gmp": df["gmpstatuscode"].str.strip() == "1",
        "exp": _date(df["expire_date"]),
        "gmp_exp": _date(df["gmp_expire_date"]),
    })
    out["group"] = out["type"].map(_group)
    out["type_s"] = out["type"].map(_short)
    code = df["city_number"].str.strip()
    name = df["city"].str.strip().str.replace(r"\s+", " ", regex=True)
    unknown = (code.isin(["", "0"])) | (name.isin(["", UNKNOWN_CITY]))
    key = code.where(code != "", name)
    canon = _canon(key[~unknown], name[~unknown])
    out["city"] = key.map(canon).where(~unknown, "")
    named = out["title"].map(lambda t: bool(HAS_LETTER.search(t)))
    hk = out["title"].map(_holder_key)
    named &= hk.str.len() >= 2
    out["hkey"] = hk.where(named, "")
    hcanon = _canon(out.loc[named, "hkey"], out.loc[named, "title"])
    out["holder"] = out["hkey"].map(hcanon).where(named, "")
    out["legal"] = out["title"].map(_legal)
    return out


def _groups_present(df):
    present = set(df["group"])
    return [g for g in GROUP_ORDER if g in present]


def _year_frac(ts):
    return ts.dt.year + (ts.dt.dayofyear - 1) / 365.25


# ── insight rules ───────────────────────────────────────────────────────────

def insight_district(dist, total):
    if len(dist) < 3 or total == 0:
        return None
    (a, va), (b, vb) = list(dist.items())[:2]
    if va < 1.2 * vb:
        return None
    return (f"{a} מוביל במספר הרישיונות — {n(va)} ({pct(va / total * 100)} מהמאגר), "
            f"פי {va / vb:.1f} מ{b} שבמקום השני ({n(vb)}).")


def insight_transport(df):
    tr = df[df["group"] == G_TRANS]
    if len(tr) < 100:
        return None
    d = _sorted_counts(tr["district"])
    top, v = d.index[0], int(d.iloc[0])
    share = v / len(tr)
    base = (df["district"] == top).mean()
    if share < 0.35 or share < 1.3 * base:
        return None
    return (f"ענף הובלת המזון מרוכז ב{top}: {n(v)} מתוך {n(len(tr))} רישיונות ההובלה "
            f"({pct(share * 100, 0)}), לעומת {pct(base * 100, 0)} מכלל הרישיונות במאגר.")


def insight_horizon(med):
    if G_TRANS not in med or G_PROD not in med:
        return None
    t, p = med[G_TRANS], med[G_PROD]
    gap = t.year - p.year
    if gap < 3:
        return None
    return (f"רישיונות ההובלה נרשמים לטווח ארוך בהרבה: חציון תאריך התפוגה שלהם הוא בשנת {t.year}, "
            f"לעומת {p.year} ברישיונות הייצור והאריזה — פער של כ-{gap} שנים.")


def insight_gmp(df):
    g = df[df["gmp"]]
    total = len(df)
    if len(g) < 10 or total == 0:
        return None
    by = _sorted_counts(g["type_s"])
    top, v = by.index[0], int(by.iloc[0])
    s = (f"רק ל-{n(len(g))} רישיונות ({pct(len(g) / total * 100)}) נלווית תעודת תנאי ייצור "
         f"נאותים (GMP)")
    if v / len(g) >= 0.5:
        s += f"; {pct(v / len(g) * 100, 0)} מהם בקטגוריה {top}"
    return s + "."


def insight_missing_exp(df):
    miss = df[df["exp"].isna()]
    if len(miss) == 0:
        return None
    by = _sorted_counts(miss["type_s"])
    top, v = by.index[0], int(by.iloc[0])
    s = (f"ל-{n(len(miss))} רישיונות ({pct(len(miss) / len(df) * 100)}) לא רשום תאריך תפוגה")
    if len(miss) >= 20 and v / len(miss) >= 0.4:
        s += f"; {pct(v / len(miss) * 100, 0)} מהם מסוג {top}"
    return s + ". הם אינם נכללים בתרשימי התוקף."


def insight_holders(hold, df):
    named = df[df["holder"] != ""]
    if len(hold) < 5 or len(named) == 0:
        return None
    top, v = hold.index[0], int(hold.iloc[0])
    if v < 5:
        return None
    multi = hold[hold >= 2]
    lic_multi = int(multi.sum())
    top_grp = _sorted_counts(named.loc[named["holder"] == top, "group"])
    g, gv = top_grp.index[0], int(top_grp.iloc[0])
    gtxt = f", {n(gv)} מהם ב{g}" if gv / v >= 0.5 else ""
    return (f"בעל הרישיונות הרב ביותר הוא {top} — {n(v)} רישיונות{gtxt}. "
            f"{n(len(multi))} בעלי רישיון מחזיקים בשניים ומעלה, ויחד הם מחזיקים "
            f"{pct(lic_multi / len(named) * 100, 0)} מהרישיונות.")


def insight_products(cat_counts, n_text):
    if len(cat_counts) < 3 or n_text < 100:
        return None
    (a, va), (b, vb) = list(cat_counts.items())[:2]
    if va / n_text < 0.15:
        return None
    return (f"התחום הנפוץ ביותר בתיאורי הפעילות של רישיונות הייצור והאריזה: {a} — {n(va)} "
            f"רישיונות ({pct(va / n_text * 100, 0)} מאלה שתוארה פעילותם), ואחריו {b} ({n(vb)}).")


def insight_month_end(exp):
    if len(exp) < 100:
        return None
    md = exp.dt.month * 100 + exp.dt.day
    dec, jun = int((md == 1231).sum()), int((md == 630).sum())
    share = (dec + jun) / len(exp)
    if share < 0.15:
        return None
    return (f"{pct(share * 100, 0)} מהרישיונות שתאריך תפוגתם רשום פגים ב-31 בדצמבר ({n(dec)}) "
            f"או ב-30 ביוני ({n(jun)}) — מועדי החידוש מרוכזים בסוף השנה ובאמצעה.")


def insight_cities(cities, known, unknown):
    if len(cities) < 10 or known == 0:
        return None
    top10 = cities.head(10).sum() / known
    a, va = cities.index[0], int(cities.iloc[0])
    s = (f"הרישיונות פרושים על פני {n(len(cities))} ישובים; {a} בראש עם {n(va)}, ועשרת הישובים "
         f"המובילים מרכזים {pct(top10 * 100, 0)} מהרישיונות שישובם ידוע")
    if unknown:
        s += f" (ל-{n(unknown)} רישיונות לא צוין ישוב)"
    return s + "."


# ── compute ────────────────────────────────────────────────────────────────

def compute(frames):
    df = _prepare(frames["main"])
    total = len(df)
    groups = _groups_present(df)
    gcol = [GROUP_COLOR[g] for g in groups]

    # Groups / types.
    grp_counts = df["group"].value_counts().reindex(groups).fillna(0).astype(int)
    types = _sorted_counts(df["type_s"])
    top_types = list(types.head(TOP_TYPES).index)
    rest = int(types.iloc[TOP_TYPES:].sum()) if len(types) > TOP_TYPES else 0
    type_group = df.drop_duplicates("type_s").set_index("type_s")["group"]
    type_rows = [(t, int(types[t]), type_group[t]) for t in top_types]
    if rest:
        type_rows.append((f"{OTHER} ({n(len(types) - TOP_TYPES)} סוגים)", rest, OTHER))

    # Legal form.
    legal_order = [x for x, _ in LEGAL] + [LEGAL_NONE]
    legal = df["legal"].value_counts().reindex(legal_order).fillna(0).astype(int)
    legal = legal[legal > 0]

    # Districts × group.
    dist = _sorted_counts(df["district"])
    dists = list(dist.index)
    dxg = (df.groupby(["district", "group"]).size().unstack(fill_value=0)
           .reindex(index=dists, columns=groups, fill_value=0))

    # Location quotient: district × top types.
    lq_types = list(types.head(LQ_TYPES).index)
    dxt = (df.groupby(["district", "type_s"]).size().unstack(fill_value=0)
           .reindex(index=dists, columns=lq_types, fill_value=0))
    nat = types.reindex(lq_types) / total
    lq_cells, lq_max = [], 0.0
    for yi, d in enumerate(dists):
        dn = int(dist[d])
        for xi, t in enumerate(lq_types):
            c = int(dxt.loc[d, t])
            lq = round(float((c / dn) / nat[t]), 2) if dn and nat[t] else 0.0
            lq_max = max(lq_max, lq)
            lq_cells.append([xi, yi, lq, c])

    # Settlements.
    known = df[df["city"] != ""]
    cities = _sorted_counts(known["city"])
    top_c = list(cities.head(TOP_CITIES).index)
    cxg = (known[known["city"].isin(top_c)].groupby(["city", "group"]).size()
           .unstack(fill_value=0).reindex(index=top_c, columns=groups, fill_value=0))
    unknown_city = total - len(known)

    # Holders.
    named = df[df["holder"] != ""]
    hold = _sorted_counts(named["holder"])
    top_h = list(hold.head(TOP_HOLDERS).index)
    hxg = (named[named["holder"].isin(top_h)].groupby(["holder", "group"]).size()
           .unstack(fill_value=0).reindex(index=top_h, columns=groups, fill_value=0))
    hb_rows = []
    for lo, hi, lab in HOLD_BUCKETS:
        m = hold >= lo
        if hi is not None:
            m &= hold <= hi
        hb_rows.append((lab, int(m.sum()), int(hold[m].sum())))
    unnamed = total - len(named)

    # Product categories (production group, multi-label).
    prod = df[(df["group"] == G_PROD) & (df["product"] != "")]
    n_text = len(prod)
    cat_hits = {c: prod["product"].str.contains(p, regex=True) for c, p in PROD_CATS}
    cat_counts = pd.Series({c: int(m.sum()) for c, m in cat_hits.items()})
    cat_counts = cat_counts[cat_counts > 0].sort_index().sort_values(ascending=False, kind="stable")
    any_hit = pd.DataFrame(cat_hits).any(axis=1) if cat_hits and n_text else pd.Series(dtype=bool)
    unmatched = int((~any_hit).sum()) if n_text else 0
    prod_all = int((df["group"] == G_PROD).sum())

    # Expiry: by year × group.
    dated = df.dropna(subset=["exp"])
    ey = dated["exp"].dt.year.astype(int)
    yc = ey.value_counts().sort_index()
    cum = yc.cumsum() / max(len(dated), 1)
    first_y = int(cum[cum >= 0.01].index[0]) if len(yc) else 0
    last_y = int(yc.index.max()) if len(yc) else 0
    early = int(yc[yc.index < first_y].sum()) if len(yc) else 0
    years = list(range(first_y, last_y + 1)) if len(yc) else []
    yb = ey.where(ey >= first_y, first_y - 1)
    exg = (dated.assign(y=yb).groupby(["y", "group"]).size().unstack(fill_value=0)
           .reindex(columns=groups, fill_value=0))
    year_keys = ([first_y - 1] if early else []) + years
    exg = exg.reindex(year_keys, fill_value=0)
    year_labels = [(f"לפני {first_y}" if y == first_y - 1 else str(y)) for y in year_keys]

    # Expiry distribution per group (boxplot, decimal years; 5th–95th whiskers).
    box_groups, box_data, box_rows, med = [], [], [], {}
    for g in groups:
        e = dated.loc[dated["group"] == g, "exp"].sort_values()
        if len(e) < 20:
            continue
        yf = _year_frac(e)
        q = [float(yf.quantile(x)) for x in (0.05, 0.25, 0.5, 0.75, 0.95)]
        box_groups.append(g)
        box_data.append([round(v, 2) for v in q])
        mts = e.quantile(0.5)
        med[g] = mts
        box_rows.append({"name": g, "count": n(len(e)),
                         "p25": e.quantile(0.25).strftime("%m/%Y"),
                         "p50": mts.strftime("%m/%Y"),
                         "p75": e.quantile(0.75).strftime("%m/%Y")})

    # Expiry month-of-year.
    mo = dated["exp"].dt.month.value_counts().reindex(range(1, 13), fill_value=0)
    md = dated["exp"].dt.month * 100 + dated["exp"].dt.day
    month_end = {6: int((md == 630).sum()), 12: int((md == 1231).sum())}

    # GMP.
    gmp = df[df["gmp"]]
    gmp_types = _sorted_counts(gmp["type_s"])
    gmp_rows = [(t, int(v), float(v / types[t] * 100)) for t, v in gmp_types.items()]
    ge = gmp["gmp_exp"].dropna()
    gmp_exp_note = ""
    if len(ge) >= 10:
        gmp_exp_note = (f" תאריכי התפוגה הרשומים של תעודות ה-GMP נעים בין {ge.min().year} ל-"
                        f"{ge.max().year}, וחציונם ב{MONTHS_HE[ge.quantile(0.5).month - 1]} "
                        f"{ge.quantile(0.5).year}.")

    charts = {
        "types": {"names": [r[0] for r in type_rows],
                  "values": [{"value": r[1], "itemStyle": {"color": GROUP_COLOR[r[2]]}, "group": r[2]}
                             for r in type_rows]},
        "groups": {"names": groups, "values": [int(grp_counts[g]) for g in groups], "colors": gcol},
        "legal": {"names": list(legal.index), "values": [int(v) for v in legal.values]},
        "districts": {"names": dists,
                      "series": [{"name": g, "color": GROUP_COLOR[g],
                                  "data": [int(dxg.loc[d, g]) for d in dists]} for g in groups]},
        "lq": {"x": lq_types, "y": dists, "cells": lq_cells,
               "max": round(max(lq_max, 2.0), 1)},
        "cities": {"names": top_c,
                   "series": [{"name": g, "color": GROUP_COLOR[g],
                               "data": [int(cxg.loc[c, g]) for c in top_c]} for g in groups]},
        "holders": {"names": top_h,
                    "series": [{"name": g, "color": GROUP_COLOR[g],
                                "data": [int(hxg.loc[h, g]) for h in top_h]} for g in groups]},
        "holdsize": {"names": [r[0] for r in hb_rows],
                     "holders": [r[1] for r in hb_rows], "licences": [r[2] for r in hb_rows]},
        "products": {"names": list(cat_counts.index), "values": [int(v) for v in cat_counts.values]},
        "expiry": {"x": year_labels,
                   "series": [{"name": g, "color": GROUP_COLOR[g],
                               "data": [int(exg.loc[y, g]) for y in year_keys]} for g in groups]},
        "box": {"names": box_groups, "data": box_data},
        "months": {"x": MONTHS_SHORT, "values": [int(v) for v in mo.values]},
        "gmp": {"names": [r[0] for r in gmp_rows], "values": [r[1] for r in gmp_rows],
                "shares": [round(r[2], 1) for r in gmp_rows]},
    }

    rules = [
        ("district", insight_district(dist, total)),
        ("transport", insight_transport(df)),
        ("cities", insight_cities(cities, len(known), unknown_city)),
        ("holders", insight_holders(hold, df)),
        ("products", insight_products(cat_counts, n_text)),
        ("horizon", insight_horizon(med)),
        ("month_end", insight_month_end(dated["exp"])),
        ("gmp", insight_gmp(df)),
        ("missing_exp", insight_missing_exp(df)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    n_gmp = len(gmp)
    n_hold = int(hold.size)
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "holders": {"value": n_hold, "display": n(n_hold), "tone": "brand"},
        "cities": {"value": int(cities.size), "display": n(cities.size), "tone": "brand"},
        "gmp": {"value": n_gmp, "display": n(n_gmp), "tone": "info"},
    }

    top_g = grp_counts.sort_index().sort_values(ascending=False, kind="stable")
    g1, g1v = top_g.index[0], int(top_g.iloc[0])
    lq_top = max(lq_cells, key=lambda c: (c[2], -c[1], -c[0])) if lq_cells else None
    lq_txt = (f" הריכוז הבולט ביותר: {lq_types[lq_top[0]]} ב{dists[lq_top[1]]}, פי {lq_top[2]:.1f} "
              f"מחלקו הארצי." if lq_top and lq_top[2] >= 1.5 else "")
    box_txt = "; ".join(f"{g} — {MONTHS_HE[med[g].month - 1]} {med[g].year}" for g in box_groups)
    labels = {
        "lede": (f"מרשם רישיונות היצרן של שירות המזון הארצי במשרד הבריאות: {n(total)} רישיונות "
                 f"של {n(n_hold)} בעלי רישיון ב-{n(cities.size)} ישובים ובשבעת מחוזות הבריאות"
                 if len(dists) == 7 else
                 f"מרשם רישיונות היצרן של שירות המזון הארצי במשרד הבריאות: {n(total)} רישיונות "
                 f"של {n(n_hold)} בעלי רישיון ב-{n(cities.size)} ישובים וב-{n(len(dists))} מחוזות בריאות")
                + (f". הקבוצה הגדולה היא {g1} ({pct(g1v / total * 100, 0)}), ול-{n(n_gmp)} רישיונות "
                   f"נלווית תעודת GMP. במאגר אין תאריך עדכון, ולכן תאריכי התפוגה מוצגים כפי "
                   f"שנרשמו, בלי לסווג רישיון כבתוקף או כפג."),
        "holders_kpi": "בעלי רישיון (לפי שם העסק)",
        "gmp_kpi": f"רישיונות עם תעודת GMP ({n_gmp / total * 100:.1f}%)",
        "types_note": (f"מספר הרישיונות לפי סוג העסק, צבוע לפי קבוצת הפעילות. "
                       + (f"{n(len(types) - TOP_TYPES)} סוגים קטנים מקובצים תחת „{OTHER}”."
                          if rest else "")),
        "types_aria": (f"תרשים עמודות אופקי: רישיונות לפי סוג עסק — {type_rows[0][0]} בראש עם "
                       f"{n(type_rows[0][1])}."),
        "types_caption": "מספר רישיונות לפי סוג עסק וקבוצת פעילות.",
        "groups_note": "חמשת סוגי הפעילות העיקריים, לאחר קיבוץ סוגי העסק.",
        "groups_aria": f"תרשים טבעת: רישיונות לפי קבוצת פעילות — {g1} {n(g1v)} מתוך {n(total)}.",
        "groups_caption": "מספר ושיעור רישיונות לפי קבוצת פעילות.",
        "legal_note": ("לפי הסיומת בשם בעל הרישיון (בע״מ, אגודה שיתופית וכדומה). שם בלי סיומת "
                       "יכול להיות עוסק יחיד או חברה שהסיומת הושמטה משמה."),
        "legal_aria": (f"תרשים טבעת: רישיונות לפי צורה משפטית של בעל הרישיון — {legal.index[0]} "
                       f"{n(legal.iloc[0])}."),
        "legal_caption": "מספר רישיונות לפי צורה משפטית משוערת.",
        "districts_note": "רישיונות בכל מחוז בריאות, לפי קבוצת הפעילות.",
        "districts_aria": (f"תרשים עמודות אופקי מוערם: רישיונות לפי מחוז בריאות וקבוצת פעילות — "
                           f"{dists[0]} בראש עם {n(dist.iloc[0])}."),
        "districts_caption": "מספר רישיונות לפי מחוז וקבוצת פעילות.",
        "lq_note": (f"מדד ריכוז: חלקו של סוג העסק במחוז חלקי חלקו בכל הארץ, ל-{LQ_TYPES} הסוגים "
                    f"הנפוצים. ערך מעל אחד — הסוג נפוץ במחוז יותר מבממוצע הארצי.{lq_txt}"),
        "lq_aria": (f"מפת חום: מדד ריכוז של {LQ_TYPES} סוגי העסק הנפוצים בכל מחוז בריאות."
                    + lq_txt),
        "lq_caption": "מספר רישיונות ומדד ריכוז לפי מחוז וסוג עסק.",
        "cities_note": (f"{TOP_CITIES} הישובים עם מספר הרישיונות הגדול ביותר, לפי קבוצת פעילות"
                        + (f"; {n(unknown_city)} רישיונות שלא צוין להם ישוב אינם נכללים." if unknown_city else ".")),
        "cities_aria": (f"תרשים עמודות אופקי מוערם: {TOP_CITIES} הישובים המובילים — {top_c[0]} בראש "
                        f"עם {n(cities.iloc[0])} רישיונות."),
        "cities_caption": f"רישיונות לפי ישוב ({TOP_CITIES} המובילים) וקבוצת פעילות.",
        "holders_note": (f"{TOP_HOLDERS} בעלי הרישיונות הרבים ביותר. שמות שנכתבו בכמה אופנים "
                         f"(עם או בלי בע״מ, רווחים, י׳ ו-ו׳) אוחדו"
                         + (f"; {n(unnamed)} רישיונות שבשמם אין אותיות (מספר בלבד) אינם נכללים."
                            if unnamed else ".")),
        "holders_aria": (f"תרשים עמודות אופקי מוערם: {TOP_HOLDERS} בעלי הרישיונות הגדולים — "
                         f"{top_h[0]} בראש עם {n(hold.iloc[0])}."),
        "holders_caption": "מספר רישיונות לבעלי הרישיונות הגדולים, לפי קבוצת פעילות.",
        "holdsize_note": ("כמה בעלי רישיון מחזיקים ברישיון אחד וכמה בכמה רישיונות, ובכמה רישיונות "
                          "בסך הכול מחזיקה כל קבוצה."),
        "holdsize_aria": (f"תרשים עמודות: בעלי רישיון לפי מספר הרישיונות שבידיהם — {n(hb_rows[0][1])} "
                          f"מחזיקים ברישיון אחד, ו-{n(hb_rows[-1][1])} ב-{HOLD_BUCKETS[-1][0]} ומעלה."),
        "holdsize_caption": "בעלי רישיון ומספר רישיונות לפי גודל האחזקה.",
        "products_note": (f"סיווג לפי מילות מפתח בתיאור הפעילות של {n(n_text)} רישיונות ייצור "
                          f"ואריזה (מתוך {n(prod_all)}) שתוארה פעילותם. רישיון יכול להיכלל "
                          f"בכמה תחומים; {n(unmatched)} תיאורים לא סווגו."),
        "products_aria": (f"תרשים עמודות אופקי: תחומי המזון ברישיונות הייצור — "
                          f"{cat_counts.index[0]} בראש עם {n(cat_counts.iloc[0])}."
                          if len(cat_counts) else "תרשים עמודות אופקי: תחומי המזון ברישיונות הייצור."),
        "products_caption": "מספר רישיונות ייצור ואריזה לפי תחום מזון.",
        "expiry_note": (f"שנת התפוגה הרשומה של {n(len(dated))} רישיונות, לפי קבוצת פעילות"
                        + (f"; {n(early)} רישיונות עם תאריך מוקדם מ-{first_y} מקובצים יחד." if early else ".")
                        + f" ל-{n(total - len(dated))} רישיונות לא רשום תאריך תפוגה."),
        "expiry_aria": (f"תרשים עמודות מוערם: רישיונות לפי שנת התפוגה הרשומה, "
                        f"{year_labels[0] if year_labels else ''} עד {last_y}."),
        "expiry_caption": "מספר רישיונות לפי שנת תפוגה וקבוצת פעילות.",
        "box_note": ("פיזור תאריכי התפוגה בכל קבוצה: הקופסה מציינת את הרבעון האמצעי, הקו — את "
                     "החציון, והשפמים — את האחוזונים החמישי והתשעים וחמישה."
                     + (f" חציון: {box_txt}." if box_txt else "")),
        "box_aria": "תרשים קופסה: פיזור תאריכי התפוגה הרשומים לפי קבוצת פעילות." + (f" חציון: {box_txt}." if box_txt else ""),
        "box_caption": "רבעון תחתון, חציון ורבעון עליון של תאריך התפוגה, לפי קבוצה.",
        "months_note": (f"חודש התפוגה הרשום. {n(month_end[12])} רישיונות פגים ב-31 בדצמבר "
                        f"ו-{n(month_end[6])} ב-30 ביוני."),
        "months_aria": (f"תרשים עמודות: רישיונות לפי חודש התפוגה — שיא ב{MONTHS_HE[int(mo.idxmax()) - 1]} "
                        f"עם {n(mo.max())}."),
        "months_caption": "מספר רישיונות לפי חודש התפוגה.",
        "gmp_note": ("תעודת תנאי ייצור נאותים (GMP) לפי סוג העסק, ושיעור בעלי התעודה מכלל "
                     "הרישיונות מאותו סוג." + gmp_exp_note),
        "gmp_aria": (f"תרשים עמודות אופקי: {n(n_gmp)} בעלי תעודת GMP לפי סוג עסק — "
                     f"{gmp_rows[0][0]} בראש עם {n(gmp_rows[0][1])}."
                     if gmp_rows else "תרשים עמודות אופקי: בעלי תעודת GMP לפי סוג עסק."),
        "gmp_caption": "מספר בעלי תעודת GMP ושיעורם לפי סוג עסק.",
    }

    tables = {
        "group_cols": groups,
        "types": [{"name": r[0], "group": r[2], "count": n(r[1]),
                   "share": f"{r[1] / total * 100:.1f}%"} for r in type_rows],
        "groups": [{"name": g, "count": n(grp_counts[g]),
                    "share": f"{grp_counts[g] / total * 100:.1f}%"} for g in groups],
        "legal": [{"name": k, "count": n(v), "share": f"{v / total * 100:.1f}%"}
                  for k, v in legal.items()],
        "districts": [{"name": d, "total": n(dist[d]), "vals": [n(dxg.loc[d, g]) for g in groups]}
                      for d in dists],
        "lq_cols": lq_types,
        "lq": [{"name": d, "vals": [f"{int(dxt.loc[d, t]):,} ({c[2]:.2f})" for t, c in
                                    zip(lq_types, lq_cells[yi * len(lq_types):(yi + 1) * len(lq_types)])]}
               for yi, d in enumerate(dists)],
        "cities": [{"name": c, "total": n(cities[c]), "vals": [n(cxg.loc[c, g]) for g in groups]}
                   for c in top_c],
        "holders": [{"name": h, "total": n(hold[h]), "vals": [n(hxg.loc[h, g]) for g in groups]}
                    for h in top_h],
        "holdsize": [{"name": r[0], "holders": n(r[1]), "licences": n(r[2])} for r in hb_rows],
        "products": [{"name": k, "count": n(v), "share": f"{v / n_text * 100:.1f}%"}
                     for k, v in cat_counts.items()] if n_text else [],
        "expiry": [{"name": lab, "total": n(exg.loc[y].sum()), "vals": [n(exg.loc[y, g]) for g in groups]}
                   for y, lab in zip(year_keys, year_labels)],
        "box": box_rows,
        "months": [{"name": MONTHS_HE[i], "count": n(mo.iloc[i])} for i in range(12)],
        "gmp": [{"name": r[0], "count": n(r[1]), "share": f"{r[2]:.1f}%"} for r in gmp_rows],
    }

    return {
        "agent_data": {
            "summary_he": (f"רישיון יצרן מזון — בדיקת רישיון לפי שם העסק, מספר רישיון או יישוב: {n(n_hold)} יצרני ועסקי "
                           f"מזון, {n(total)} רישיונות, לפי מחוז, תוקף ותעודת GMP."),
            "dataset_kind": "registry",
            "related_ids": ["b87ef422-0355-4490-9506-d502b71e9b10",
                            "9f0ea3dc-2e25-43f0-9b8f-10f53e23c335",
                            "246d949c-a253-4811-8a11-41a137d3d613"],
            "suggested_tags": ["עסקי מזון", "רישוי עסקים", "מפעלי מזון", "שירות המזון",
                               "בטיחות מזון", "הובלת מזון"],
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"has_box": bool(box_groups), "has_gmp": bool(gmp_rows),
                  "has_products": bool(len(cat_counts))},
    }
