"""קונסולי כבוד של מדינת ישראל — honorary consuls (MFA).

Four files, two genuinely distinct tables, each published in Hebrew and in an
English translation with the same rows:
- `in_il`  — honorary consuls of foreign countries who serve in Israel;
- `abroad` — Israel's own honorary consuls in other countries.
The recipe reads the two Hebrew files (the page is Hebrew).

Grain: a row is a (consul, jurisdiction) entry. The same person can appear on
several rows of one country (one row per district they cover) and can also
represent several countries. The page's consul unit is therefore the distinct
(country, person) pair, person = name without its honorific; its districts are
joined, its appointment date is the earliest valid one.

Honorary consuls are public office holders and may be named (longest-serving
table, multi-country insight). Phone, mobile and e-mail are only COUNTED for
completeness — never printed; the explorer under the page has the rows.

Gender is read from the published honorific only (מר / גברת); academic titles
(דוקטור, פרופסור) and missing honorifics are "לא צוין".

Regions follow the Foreign Ministry's division as used by the sibling pages of
Israel's missions abroad (14f2521f) and foreign missions in Israel (bae5a627).
Country positions on the map are approximate capital coordinates; a country
the table does not know falls into "אחר", is left off the map and disclosed.

Appointment dates before 1948 (one row reads 1923 — evidently a typo) or that
don't parse are excluded from date views, disclosed.
"""
import re

import pandas as pd

LRI, PDI = "⁦", "⁩"
OTHER = "אחר"
NA = "לא צוין"
MIN_YEAR = 1948
TOP_COUNTRIES = 12
TOP_AREAS = 12
TOP_OLDEST = 6
EARLY_BIN = 1995            # appointments before this year share one bucket
BIN = 5
CONTACT_GAP_PP = 20         # completeness gap between the lists worth stating
NONRES_MIN_SHARE = 0.10
RECENT_YEARS = 10

IL, AB = "in_il", "abroad"
DIR_LABEL = {IL: "קונסולי כבוד זרים בישראל", AB: "קונסולי כבוד של ישראל בחו״ל"}

REGION_ORDER = ["אירופה", "אמריקה", "אפריקה", "אסיה", "פאסיפיק"]
_EU, _AM, _AF, _AS, _PA = REGION_ORDER

# Hebrew country name (as spelled in this dataset, plus common variants)
# -> (MFA region, approx. capital lat, lon).
COUNTRY = {
    # Europe
    "אלבניה": (_EU, 41.33, 19.82), "אנדורה": (_EU, 42.51, 1.52), "אוסטריה": (_EU, 48.21, 16.37),
    "בלארוס": (_EU, 53.90, 27.57), "בלגיה": (_EU, 50.85, 4.35), "בוסניה הרצגובינה": (_EU, 43.86, 18.41),
    "בוסניה והרצגובינה": (_EU, 43.86, 18.41), "בולגריה": (_EU, 42.70, 23.32), "קרואטיה": (_EU, 45.81, 15.98),
    "קפריסין": (_EU, 35.17, 33.36), "צ'כיה": (_EU, 50.08, 14.44), "דנמרק": (_EU, 55.68, 12.57),
    "אסטוניה": (_EU, 59.44, 24.75), "פינלנד": (_EU, 60.17, 24.94), "צרפת": (_EU, 48.86, 2.35),
    "גרמניה": (_EU, 52.52, 13.40), "יוון": (_EU, 37.98, 23.73), "הוותיקן": (_EU, 41.90, 12.45),
    "הכס הקדוש": (_EU, 41.90, 12.45), "הונגריה": (_EU, 47.50, 19.04), "איסלנד": (_EU, 64.15, -21.94),
    "אירלנד": (_EU, 53.35, -6.26), "איטליה": (_EU, 41.90, 12.50), "קוסובו": (_EU, 42.66, 21.17),
    "לטביה": (_EU, 56.95, 24.11), "ליכטנשטיין": (_EU, 47.14, 9.52), "ליטא": (_EU, 54.69, 25.28),
    "לוקסמבורג": (_EU, 49.61, 6.13), "מלטה": (_EU, 35.90, 14.51), "מולדובה": (_EU, 47.01, 28.86),
    "מונקו": (_EU, 43.74, 7.42), "מונטנגרו": (_EU, 42.44, 19.26), "הולנד": (_EU, 52.37, 4.90),
    "מקדוניה הצפונית": (_EU, 42.00, 21.43), "נורבגיה": (_EU, 59.91, 10.75), "פולין": (_EU, 52.23, 21.01),
    "פורטוגל": (_EU, 38.72, -9.14), "רומניה": (_EU, 44.43, 26.10), "רוסיה": (_EU, 55.76, 37.62),
    "סן מרינו": (_EU, 43.94, 12.45), "סרביה": (_EU, 44.79, 20.45), "סלובקיה": (_EU, 48.15, 17.11),
    "סלובניה": (_EU, 46.06, 14.51), "ספרד": (_EU, 40.42, -3.70), "שבדיה": (_EU, 59.33, 18.07),
    "שווייץ": (_EU, 46.95, 7.45), "שוויץ": (_EU, 46.95, 7.45), "תורכיה": (_EU, 39.93, 32.86),
    "טורקיה": (_EU, 39.93, 32.86), "תורכמניסטאן": (_EU, 37.96, 58.33), "טורקמניסטן": (_EU, 37.96, 58.33),
    "אוקראינה": (_EU, 50.45, 30.52), "בריטניה": (_EU, 51.51, -0.13), "קירגיסטאן": (_EU, 42.87, 74.59),
    "קירגיזסטן": (_EU, 42.87, 74.59), "טג'יקיסטאן": (_EU, 38.56, 68.79), "טג'יקיסטן": (_EU, 38.56, 68.79),
    "גיברלטר": (_EU, 36.14, -5.35),
    # America
    "אנטיגואה וברבודה": (_AM, 17.12, -61.85), "ארגנטינה": (_AM, -34.60, -58.38), "איי הבהאמס": (_AM, 25.05, -77.35),
    "בהאמס": (_AM, 25.05, -77.35), "ברבדוס": (_AM, 13.10, -59.62), "בליז": (_AM, 17.25, -88.77),
    "בוליביה": (_AM, -16.50, -68.15), "ברזיל": (_AM, -15.79, -47.88), "קנדה": (_AM, 45.42, -75.70),
    "צ'ילה": (_AM, -33.45, -70.67), "קולומביה": (_AM, 4.71, -74.07), "קוסטה ריקה": (_AM, 9.93, -84.08),
    "קובה": (_AM, 23.11, -82.37), "דומיניקה": (_AM, 15.30, -61.39), "הרפובליקה הדומיניקנית": (_AM, 18.49, -69.93),
    "אקוואדור": (_AM, -0.18, -78.47), "אל סלבדור": (_AM, 13.69, -89.22), "גרנדה": (_AM, 12.06, -61.75),
    "גואטמלה": (_AM, 14.63, -90.51), "גיאנה": (_AM, 6.80, -58.16), "האיטי": (_AM, 18.54, -72.34),
    "הונדורס": (_AM, 14.07, -87.19), "ג'מאיקה": (_AM, 18.02, -76.80), "מכסיקו": (_AM, 19.43, -99.13),
    "מקסיקו": (_AM, 19.43, -99.13), "ניקרגואה": (_AM, 12.11, -86.24), "פנמה": (_AM, 8.98, -79.52),
    "פרגוואי": (_AM, -25.26, -57.58), "פרו": (_AM, -12.05, -77.04), "סט' קיטס ונביס": (_AM, 17.30, -62.72),
    "סט' לוציה": (_AM, 14.01, -60.99), "סט' וינסנט והגרנדינים": (_AM, 13.16, -61.23), "סורינם": (_AM, 5.85, -55.20),
    "טרינידד וטובגו": (_AM, 10.65, -61.51), "ארצות הברית": (_AM, 38.90, -77.04), "אורוגואי": (_AM, -34.90, -56.16),
    "ונצואלה": (_AM, 10.48, -66.90),
    # Africa
    "אנגולה": (_AF, -8.84, 13.23), "בנין": (_AF, 6.50, 2.60), "בוצואנה": (_AF, -24.65, 25.91),
    "בורקינה פסו": (_AF, 12.37, -1.52), "בורונדי": (_AF, -3.38, 29.36), "קמרון": (_AF, 3.85, 11.50),
    "קייפ ורדה": (_AF, 14.93, -23.51), "הרפובליקה המרכז אפריקאית": (_AF, 4.39, 18.56), "צ'אד": (_AF, 12.13, 15.06),
    "קונגו": (_AF, -4.27, 15.28), "הרפובליקה הדמוקרטית של קונגו": (_AF, -4.33, 15.31),
    "חוף השנהב (קוט דיוואר)": (_AF, 6.83, -5.29), "חוף השנהב": (_AF, 6.83, -5.29), "מצרים": (_AF, 30.04, 31.24),
    "גינאה המשוונית": (_AF, 3.75, 8.78), "אסוואטיני": (_AF, -26.31, 31.14), "אתיופיה": (_AF, 9.03, 38.74),
    "גבון": (_AF, 0.42, 9.47), "גמביה": (_AF, 13.45, -16.58), "גאנה": (_AF, 5.60, -0.19),
    "גינאה": (_AF, 9.64, -13.58), "גינאה-ביסאו": (_AF, 11.86, -15.60), "קניה": (_AF, -1.29, 36.82),
    "לסוטו": (_AF, -29.31, 27.48), "ליבריה": (_AF, 6.30, -10.80), "מדגסקר": (_AF, -18.88, 47.51),
    "מלאווי": (_AF, -13.96, 33.79), "מאלי": (_AF, 12.64, -8.00), "מאוריטניה": (_AF, 18.08, -15.98),
    "מאוריציוס": (_AF, -20.16, 57.50), "מרוקו": (_AF, 34.02, -6.84), "מוזמביק": (_AF, -25.97, 32.57),
    "נמיביה": (_AF, -22.56, 17.08), "ניז'ר": (_AF, 13.51, 2.11), "ניגריה": (_AF, 9.08, 7.40),
    "רואנדה": (_AF, -1.95, 30.06), "סאו טומה ופרינסיפה": (_AF, 0.34, 6.73), "סנגל": (_AF, 14.72, -17.47),
    "איי סיישל": (_AF, -4.62, 55.45), "סיישל": (_AF, -4.62, 55.45), "סיירה ליאונה": (_AF, 8.48, -13.23),
    "דרום אפריקה": (_AF, -25.75, 28.19), "דרום סודאן": (_AF, 4.86, 31.57), "סודאן": (_AF, 15.50, 32.56),
    "טוגו": (_AF, 6.13, 1.22), "אוגנדה": (_AF, 0.35, 32.58), "טנזניה": (_AF, -6.16, 35.75),
    "זמביה": (_AF, -15.39, 28.32), "זימבאבווה": (_AF, -17.83, 31.05),
    # Asia
    "ארמניה": (_AS, 40.18, 44.51), "אזרבייג'ן": (_AS, 40.41, 49.87), "בחריין": (_AS, 26.23, 50.59),
    "בהוטן": (_AS, 27.47, 89.64), "קמבודיה": (_AS, 11.56, 104.92), "סין": (_AS, 39.90, 116.41),
    "מזרח טימור": (_AS, -8.56, 125.57), "אריתריאה": (_AS, 15.32, 38.93), "גיאורגיה": (_AS, 41.72, 44.79),
    "גאורגיה": (_AS, 41.72, 44.79), "הודו": (_AS, 28.61, 77.21), "יפן": (_AS, 35.68, 139.69),
    "ירדן": (_AS, 31.95, 35.93), "קזחסטאן": (_AS, 51.17, 71.45), "קזחסטן": (_AS, 51.17, 71.45),
    "קוריאה": (_AS, 37.57, 126.98), "דרום קוריאה": (_AS, 37.57, 126.98), "לאוס": (_AS, 17.98, 102.63),
    "מונגוליה": (_AS, 47.89, 106.91), "מיאנמר": (_AS, 19.76, 96.08), "נפאל": (_AS, 27.72, 85.32),
    "פיליפינים": (_AS, 14.60, 120.98), "הפיליפינים": (_AS, 14.60, 120.98), "קטאר": (_AS, 25.29, 51.53),
    "סינגפור": (_AS, 1.35, 103.82), "סרי לנקה": (_AS, 6.93, 79.86), "טאיוואן": (_AS, 25.03, 121.57),
    "תאילנד": (_AS, 13.76, 100.50), "איחוד האמירויות": (_AS, 24.45, 54.38), "אוזבקיסטאן": (_AS, 41.30, 69.24),
    "אוזבקיסטן": (_AS, 41.30, 69.24), "וייטנאם": (_AS, 21.03, 105.85), "וייטנאם הסוציאליסטית": (_AS, 21.03, 105.85),
    "אינדונזיה": (_AS, -6.21, 106.85), "מלזיה": (_AS, 3.14, 101.69), "המלדיביים": (_AS, 4.18, 73.51),
    # Pacific
    "אוסטרליה": (_PA, -35.28, 149.13), "איי קוק": (_PA, -21.21, -159.78), "פיג'י": (_PA, -18.14, 178.44),
    "קיריבטי": (_PA, 1.45, 173.03), "איי מרשל": (_PA, 7.09, 171.38), "מיקרונזיה": (_PA, 6.92, 158.16),
    "נאורו": (_PA, -0.55, 166.92), "ניו זילנד": (_PA, -41.29, 174.78), "ניואה": (_PA, -19.06, -169.92),
    "פפואה ניו גיני": (_PA, -9.44, 147.18), "פלאו": (_PA, 7.50, 134.62), "סמואה": (_PA, -13.83, -171.76),
    "איי שלמה": (_PA, -9.43, 159.95), "טונגה": (_PA, -21.14, -175.20), "טובלו": (_PA, -8.52, 179.20),
    "ונואטו": (_PA, -17.73, 168.32),
}

GENDER_OF = {"מר": "גברים", "גברת": "נשים"}
GENDER_ORDER = ["גברים", "נשים", NA]
HONORIFICS = {"מר", "גברת", "דוקטור", "פרופסור", "ד\"ר", "פרופ'", "אחר"}

NONRES_TOKEN = "נציגות ללא תושבות"
NATIONWIDE = "כל הארץ"
AREA_ALIASES = {"ישראל": NATIONWIDE, "דרום הארץ": "דרום"}
AREA_SPLIT = re.compile(r"\s*,\s*|\s+ו(?=דרום|צפון|מרכז)")

CONTACTS = [("email", "דואר אלקטרוני"), ("phone_number", "טלפון"), ("mobile_phone", "טלפון נייד"),
            ("address", "כתובת"), ("area", "אזור שיפוט")]


def n(v):
    return f"{int(v):,}"


def pct(v, digits=0):
    return f"{LRI}{v * 100:.{digits}f}%{PDI}"


def pct_disp(v, digits=1):
    return f"{v * 100:.{digits}f}%"


def _sorted_counts(s):
    vc = s.value_counts()
    return vc.sort_index().sort_values(ascending=False, kind="stable")


def _join(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " ו" + items[-1]


def _person(name):
    toks = name.split()
    if toks and toks[0] in HONORIFICS and len(toks) > 1:
        toks = toks[1:]
    return " ".join(toks)


def _gender(name):
    toks = name.split()
    return GENDER_OF.get(toks[0], NA) if toks else NA


def _areas_il(text):
    out = []
    for t in AREA_SPLIT.split(text):
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        t = AREA_ALIASES.get(t, t)
        if t not in out:
            out.append(t)
    return out


def _consuls(df):
    """One row per distinct (country, person)."""
    r = pd.DataFrame({c: df[c].astype(str).str.strip() for c in
                      ["country", "name", "honorary_consul_title", "area", "email",
                       "phone_number", "mobile_phone", "address", "appointment_date"]})
    r["name"] = r["name"].str.replace(r"\s+", " ", regex=True)
    r = r[(r["country"] != "") & (r["name"] != "")].copy()
    n_rows = len(r)
    r["person"] = r["name"].map(_person)
    r["date"] = pd.to_datetime(r["appointment_date"], format="%d-%m-%Y", errors="coerce")
    r.loc[r["date"].dt.year < MIN_YEAR, "date"] = pd.NaT
    r["title"] = r["honorary_consul_title"].replace("", NA)
    r = r.sort_values(["country", "person", "name", "area", "appointment_date", "title",
                       "email", "phone_number", "mobile_phone", "address"], kind="stable")
    g = r.groupby(["country", "person"], sort=True)

    def first_nonempty(s):
        v = [x for x in s if x]
        return v[0] if v else ""

    def mode(s):
        return _sorted_counts(s).index[0]

    c = pd.DataFrame({
        "name": g["name"].agg(mode),
        "title": g["title"].agg(mode),
        "date": g["date"].min(),
        "areas": g["area"].agg(lambda s: [a for a in dict.fromkeys(s) if a]),
        "n_rows": g.size(),
    })
    for col, _ in CONTACTS:
        if col != "area":
            c[col] = g[col].agg(first_nonempty)
    c["area"] = c["areas"].map(lambda a: " · ".join(a))
    c = c.reset_index()
    c["gender"] = c["name"].map(_gender)
    c["region"] = c["country"].map(lambda k: COUNTRY[k][0] if k in COUNTRY else OTHER)
    c["year"] = c["date"].dt.year
    return c, n_rows


def compute(frames):
    cons = {}
    raw = {}
    for k in (IL, AB):
        cons[k], raw[k] = _consuls(frames[k])
    il, ab = cons[IL], cons[AB]
    n_il, n_ab = len(il), len(ab)
    c_il = set(il["country"])
    c_ab = set(ab["country"])
    both = sorted(c_il & c_ab)
    only_il = sorted(c_il - c_ab)
    only_ab = sorted(c_ab - c_il)
    all_c = sorted(c_il | c_ab)
    unknown = [c for c in all_c if c not in COUNTRY]

    cnt_il = il["country"].value_counts()
    cnt_ab = ab["country"].value_counts()

    # ---- KPIs ------------------------------------------------------------
    kpis = {
        "in_il": {"value": n_il, "display": n(n_il), "tone": "brand"},
        "il_countries": {"value": len(c_il), "display": n(len(c_il)), "tone": "brand"},
        "abroad": {"value": n_ab, "display": n(n_ab), "tone": "brand"},
        "ab_countries": {"value": len(c_ab), "display": n(len(c_ab)), "tone": "brand"},
        "both": {"value": len(both), "display": n(len(both)), "tone": "info"},
    }

    # ---- map -------------------------------------------------------------
    pts = []
    for c in all_c:
        if c not in COUNTRY:
            continue
        _, lat, lon = COUNTRY[c]
        if lon < -150:   # far-Pacific islands: keep them beside the rest of Oceania
            lon += 360
        a, b = int(cnt_il.get(c, 0)), int(cnt_ab.get(c, 0))
        kind = "both" if a and b else ("il" if a else "ab")
        pts.append([lat, lon, c, a, b, kind])
    map_data = {"points": pts}

    # ---- regions ------------------------------------------------------------
    regions = [r for r in REGION_ORDER + [OTHER]
               if (il["region"] == r).any() or (ab["region"] == r).any()]
    reg_il = [int((il["region"] == r).sum()) for r in regions]
    reg_ab = [int((ab["region"] == r).sum()) for r in regions]
    reg_cil = [int(il.loc[il["region"] == r, "country"].nunique()) for r in regions]
    reg_cab = [int(ab.loc[ab["region"] == r, "country"].nunique()) for r in regions]
    regions_chart = {"x": regions, "il": reg_il, "ab": reg_ab}
    regions_table = [{"region": r, "il": n(a), "cil": n(ca), "ab": n(b), "cab": n(cb)}
                     for r, a, ca, b, cb in zip(regions, reg_il, reg_cil, reg_ab, reg_cab)]

    # ---- overlap by region -----------------------------------------------------
    reg_of = {c: (COUNTRY[c][0] if c in COUNTRY else OTHER) for c in all_c}
    ov_both = [sum(1 for c in both if reg_of[c] == r) for r in regions]
    ov_il = [sum(1 for c in only_il if reg_of[c] == r) for r in regions]
    ov_ab = [sum(1 for c in only_ab if reg_of[c] == r) for r in regions]
    overlap_chart = {"x": regions, "both": ov_both, "il": ov_il, "ab": ov_ab}
    overlap_table = [{"region": r, "both": n(a), "il": n(b), "ab": n(c),
                      "names": ", ".join(x for x in both if reg_of[x] == r)}
                     for r, a, b, c in zip(regions, ov_both, ov_il, ov_ab)]

    # ---- top countries ------------------------------------------------------
    def top(cons_df, cnt):
        order = sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))
        multi = [(c, v) for c, v in order if v > 1]
        shown = multi[:TOP_COUNTRIES]
        areas = cons_df.groupby("country")["areas"].agg(lambda s: sorted({a for lst in s for a in lst}))
        chart = {"names": [c for c, _ in shown], "values": [int(v) for _, v in shown]}
        table = [{"country": c, "count": n(v), "areas": " · ".join(areas.get(c, [])) or NA} for c, v in shown]
        return chart, table, order, len(multi)

    top_ab_chart, top_ab_table, order_ab, n_multi_ab = top(ab, cnt_ab)
    top_il_chart, top_il_table, order_il, n_multi_il = top(il, cnt_il)

    # ---- areas in Israel ------------------------------------------------------
    il["tokens"] = il["areas"].map(lambda lst: [t for a in lst for t in _areas_il(a)])
    il["nonres"] = il["tokens"].map(lambda t: NONRES_TOKEN in t)
    tok = pd.Series([t for lst in il["tokens"] for t in dict.fromkeys(lst) if t != NONRES_TOKEN], dtype=object)
    tok_counts = _sorted_counts(tok) if len(tok) else pd.Series(dtype=int)
    tok_top = tok_counts.head(TOP_AREAS)
    tok_rest = int(tok_counts.iloc[TOP_AREAS:].sum()) if len(tok_counts) > TOP_AREAS else 0
    area_names = list(tok_top.index) + ([OTHER] if tok_rest else [])
    area_vals = [int(v) for v in tok_top.values] + ([tok_rest] if tok_rest else [])
    no_area = int((il["tokens"].map(lambda t: len([x for x in t if x != NONRES_TOKEN]) == 0)).sum())
    areas_chart = {"names": area_names, "values": area_vals}
    areas_table = [{"area": a, "count": n(v)} for a, v in zip(area_names, area_vals)]
    if no_area:
        areas_table.append({"area": "אזור לא צוין", "count": n(no_area)})
    n_nonres = int(il["nonres"].sum())
    nonres_countries = int(il.loc[il["nonres"], "country"].nunique())
    kpis["nonres"] = {"value": n_nonres, "display": n(n_nonres),
                      "tone": "info" if n_il and n_nonres / n_il >= NONRES_MIN_SHARE else "brand"}

    # ---- appointment periods -----------------------------------------------------
    years = pd.concat([il["year"], ab["year"]]).dropna()
    max_year = int(years.max()) if len(years) else None
    min_year = int(years.min()) if len(years) else None
    bins = []
    if max_year is not None:
        start = EARLY_BIN if min_year < EARLY_BIN else (min_year // BIN) * BIN
        if min_year < EARLY_BIN:
            bins.append((None, EARLY_BIN - 1, f"לפני {EARLY_BIN}"))
        y = start
        while y <= max_year:
            hi = min(y + BIN - 1, max_year)
            bins.append((y, hi, f"{y}" if hi == y else f"{y} עד {hi}"))
            y += BIN

    def bin_counts(df):
        out = []
        for lo, hi, _ in bins:
            m = df["year"].le(hi)
            if lo is not None:
                m &= df["year"].ge(lo)
            out.append(int(m.sum()))
        return out

    yr_il, yr_ab = bin_counts(il), bin_counts(ab)
    partial_last = bool(bins) and bins[-1][1] - (bins[-1][0] or 0) + 1 < BIN
    years_chart = {"x": [b[2] for b in bins], "il": yr_il, "ab": yr_ab}
    years_table = [{"period": b[2], "il": n(a), "ab": n(c)} for b, a, c in zip(bins, yr_il, yr_ab)]
    undated = {k: int(cons[k]["year"].isna().sum()) for k in (IL, AB)}

    # ---- oldest appointments ---------------------------------------------------
    def oldest(df, side):
        d = df[df["date"].notna()].sort_values(["date", "country", "person"], kind="stable").head(TOP_OLDEST)
        return [{"name": r.name, "country": r.country, "title": r.title, "year": str(int(r.year)), "side": side}
                for r in d.itertuples()]

    oldest_il, oldest_ab = oldest(il, IL), oldest(ab, AB)

    # ---- titles & gender -----------------------------------------------------------
    titles = list(_sorted_counts(pd.concat([il["title"], ab["title"]])).index)
    titles = [t for t in titles if t != NA] + ([NA] if NA in titles else [])
    t_il = il["title"].value_counts()
    t_ab = ab["title"].value_counts()
    titles_chart = {"names": titles, "il": [int(t_il.get(t, 0)) for t in titles],
                    "ab": [int(t_ab.get(t, 0)) for t in titles]}
    titles_table = [{"title": t, "il": n(t_il.get(t, 0)), "ab": n(t_ab.get(t, 0))} for t in titles]

    g_il = il["gender"].value_counts()
    g_ab = ab["gender"].value_counts()
    genders = [x for x in GENDER_ORDER if g_il.get(x, 0) or g_ab.get(x, 0)]
    dirs = [DIR_LABEL[IL], DIR_LABEL[AB]]
    gender_series = []
    for x in genders:
        counts = [int(g_il.get(x, 0)), int(g_ab.get(x, 0))]
        shares = [round(counts[0] / n_il * 100, 1) if n_il else 0, round(counts[1] / n_ab * 100, 1) if n_ab else 0]
        gender_series.append({"name": x, "data": shares, "counts": counts})
    gender_chart = {"x": dirs, "series": gender_series}
    gender_table = [{"gender": x, "il": n(g_il.get(x, 0)), "il_share": pct_disp(g_il.get(x, 0) / n_il if n_il else 0),
                     "ab": n(g_ab.get(x, 0)), "ab_share": pct_disp(g_ab.get(x, 0) / n_ab if n_ab else 0)}
                    for x in genders]
    w_il = g_il.get("נשים", 0) / n_il if n_il else 0
    w_ab = g_ab.get("נשים", 0) / n_ab if n_ab else 0

    # ---- contact completeness ------------------------------------------------------
    cc_names, cc_il, cc_ab, cc_il_n, cc_ab_n = [], [], [], [], []
    for col, lbl in CONTACTS:
        a = int((il[col] != "").sum())
        b = int((ab[col] != "").sum())
        cc_names.append(lbl)
        cc_il_n.append(a)
        cc_ab_n.append(b)
        cc_il.append(round(a / n_il * 100, 1) if n_il else 0)
        cc_ab.append(round(b / n_ab * 100, 1) if n_ab else 0)
    contacts_chart = {"names": cc_names, "il": cc_il, "ab": cc_ab, "il_n": cc_il_n, "ab_n": cc_ab_n}
    contacts_table = [{"field": f, "il": n(a), "il_share": pct_disp(x / 100), "ab": n(b), "ab_share": pct_disp(y / 100)}
                      for f, a, x, b, y in zip(cc_names, cc_il_n, cc_il, cc_ab_n, cc_ab)]

    # ---- multi-country persons ----------------------------------------------------------
    def multi_persons(df):
        pc = df.groupby("person")["country"].agg(lambda s: sorted(set(s)))
        pc = pc[pc.map(len) > 1]
        names = df.drop_duplicates("person").set_index("person")["name"]
        return [(names[p], lst) for p, lst in sorted(pc.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

    mp_il = multi_persons(il)

    # ---- insights --------------------------------------------------------------------
    insights = []

    if n_il and n_ab:
        ratio = n_il / n_ab
        if ratio >= 1.15:
            cmp_ = f"פי {LRI}{ratio:.1f}{PDI} ממספר הקונסולים שמייצגים את ישראל בחו״ל ({n(n_ab)}, ב-{n(len(c_ab))} מדינות)"
        elif ratio <= 1 / 1.15:
            cmp_ = f"פחות ממספר הקונסולים שמייצגים את ישראל בחו״ל ({n(n_ab)}, ב-{n(len(c_ab))} מדינות)"
        else:
            cmp_ = f"קרוב למספר הקונסולים שמייצגים את ישראל בחו״ל ({n(n_ab)}, ב-{n(len(c_ab))} מדינות)"
        insights.append({"id": "scale", "text_he": (
            f"בישראל משרתים {n(n_il)} קונסולי כבוד של {n(len(c_il))} מדינות זרות — {cmp_}.")})

    if len(all_c) >= 10 and len(both) >= 3:
        insights.append({"id": "both", "text_he": (
            f"{'רק ' if len(both) / len(all_c) < 0.5 else ''}ב-{n(len(both))} מתוך {n(len(all_c))} המדינות שבמאגר "
            f"({pct(len(both) / len(all_c))}) הייצוג דו-כיווני: יש להן קונסול כבוד בישראל ולישראל יש קונסול כבוד אצלן. "
            f"{n(len(only_il))} מדינות מיוצגות רק בישראל ו-{n(len(only_ab))} רק בכיוון ההפוך.")})

    if n_il and n_nonres / n_il >= NONRES_MIN_SHARE:
        insights.append({"id": "nonres", "text_he": (
            f"{n(n_nonres)} מקונסולי הכבוד בישראל ({pct(n_nonres / n_il)}), של {n(nonres_countries)} מדינות, "
            f"מסומנים „{NONRES_TOKEN}” — הם מייצגים מדינה שאין לה שגרירות היושבת בישראל.")})

    local = tok_counts[tok_counts.index != NATIONWIDE] if len(tok_counts) else tok_counts
    if len(local) >= 2 and local.iloc[0] > local.iloc[1]:
        a0, a1 = local.index[0], local.index[1]
        nw = int(tok_counts.get(NATIONWIDE, 0))
        nw_txt = f" {n(nw)} קונסולים נוספים אחראים לכל הארץ." if nw else ""
        insights.append({"id": "areas", "text_he": (
            f"מבין אזורי השיפוט בישראל, {a0} משורתת בידי מספר קונסולי הכבוד הגדול ביותר — {n(local.iloc[0])} "
            f"({pct(local.iloc[0] / n_il)}), לפני {a1} עם {n(local.iloc[1])} (קונסול יכול לשרת כמה אזורים).{nw_txt}")})

    if order_ab and order_ab[0][1] >= 3:
        mx = order_ab[0][1]
        leaders = [c for c, v in order_ab if v == mx]
        lead_txt = (f"ב{leaders[0]} פועלים" if len(leaders) == 1 else f"ב{_join(leaders)} פועלים בכל אחת")
        insights.append({"id": "abroad_top", "text_he": (
            f"{lead_txt} {n(mx)} קונסולי כבוד ישראליים — הפריסה הצפופה ביותר בחו״ל. "
            f"{n(n_multi_ab)} מדינות מארחות יותר מקונסול כבוד ישראלי אחד.")})

    if mp_il:
        shown = mp_il[:3]
        parts = [f"{nm} ({_join(lst)})" for nm, lst in shown]
        more = f" ועוד {n(len(mp_il) - len(shown))}" if len(mp_il) > len(shown) else ""
        insights.append({"id": "multi_person", "text_he": (
            f"{n(len(mp_il))} קונסולי כבוד בישראל מייצגים יותר ממדינה אחת: " + "; ".join(parts) + f"{more}.")})

    if max_year is not None:
        since = max_year - RECENT_YEARS + 1
        dated = pd.concat([il["year"], ab["year"]]).dropna()
        rec = int((dated >= since).sum())
        if len(dated) >= 20:
            o = (oldest_il[:1] + oldest_ab[:1])
            o.sort(key=lambda r: (int(r["year"]), r["country"]))
            txt = (f"{n(rec)} מתוך {n(len(dated))} הקונסולים שמועד מינויים ידוע ({pct(rec / len(dated))}) מונו "
                   f"מ-{since} ואילך.")
            if o:
                r0 = o[0]
                whom = r0["country"] if r0["side"] == IL else "ישראל ב" + r0["country"]
                txt += f" הוותיק ברשימה הוא {r0['name']}, {r0['title']} של {whom}, שמונה ב-{r0['year']}."
            insights.append({"id": "tenure", "text_he": txt})

    if n_il >= 20 and n_ab >= 20:
        insights.append({"id": "gender", "text_he": (
            f"לפי התואר שפורסם, נשים הן {pct(w_il)} מקונסולי הכבוד בישראל ו-{pct(w_ab)} מקונסולי הכבוד של ישראל בחו״ל.")})

    em_i = [c for c, _ in CONTACTS].index("email")
    if n_il >= 20 and n_ab >= 20 and abs(cc_il[em_i] - cc_ab[em_i]) >= CONTACT_GAP_PP:
        hi_side, lo_side = ("בישראל", "בחו״ל") if cc_il[em_i] > cc_ab[em_i] else ("בחו״ל", "בישראל")
        hi_v, lo_v = max(cc_il[em_i], cc_ab[em_i]), min(cc_il[em_i], cc_ab[em_i])
        insights.append({"id": "contacts", "text_he": (
            f"כתובת דואר אלקטרוני מופיעה אצל {pct(hi_v / 100)} מקונסולי הכבוד {hi_side}, "
            f"לעומת {pct(lo_v / 100)} בלבד {lo_side}.")})

    # ---- labels ------------------------------------------------------------------------
    excl_date = undated[IL] + undated[AB]
    labels = {
        "lede": (f"משרד החוץ מפרסם שתי רשימות של קונסולי כבוד: {n(n_il)} קונסולים המייצגים {n(len(c_il))} "
                 f"מדינות זרות בישראל, ו-{n(n_ab)} קונסולים המייצגים את ישראל ב-{n(len(c_ab))} מדינות. "
                 f"קונסול כבוד אינו דיפלומט מקצועי אלא תושב המקום שמונה לייצג מדינה — לרוב בעיר שאין בה "
                 f"שגרירות או קונסוליה. לכל קונסול מופיעים התואר, אזור השיפוט, מועד המינוי ודרכי ההתקשרות."),
        "in_il_kpi": "קונסולי כבוד זרים בישראל",
        "il_countries_kpi": "מדינות המיוצגות בישראל בקונסול כבוד",
        "abroad_kpi": "קונסולי כבוד של ישראל בחו״ל",
        "ab_countries_kpi": "מדינות שבהן לישראל קונסול כבוד",
        "both_kpi": "מדינות עם ייצוג בשני הכיוונים",
        "nonres_kpi": "קונסולים בישראל של מדינה ללא שגרירות יושבת",
        "map_note": (f"כל עיגול הוא מדינה (במיקום בירתה), וגודלו לפי מספר הקונסולים. כחול: יש לה קונסול כבוד "
                     f"בישראל בלבד; תכלת: לישראל יש קונסול כבוד אצלה בלבד; כחול כהה: ייצוג בשני הכיוונים "
                     f"({n(len(both))} מדינות).") + (
                     f" {n(len(unknown))} מדינות לא מוקמו על המפה: {_join(unknown)}." if unknown else ""),
        "map_aria": "מפת עולם: מדינות עם קונסולי כבוד בישראל ומדינות שבהן לישראל קונסולי כבוד.",
        "regions_note": (f"מספר הקונסולים בכל אזור, לפי חלוקת האזורים של משרד החוץ: קונסולים זרים בישראל לפי "
                         f"אזור המדינה שהם מייצגים, וקונסולים ישראליים לפי אזור המדינה שבה הם פועלים."),
        "regions_aria": "גרף עמודות: קונסולי כבוד לפי אזור, בישראל ובחו״ל.",
        "regions_caption": "קונסולי כבוד ומדינות לפי אזור.",
        "overlap_note": (f"לכל מדינה במאגר: האם יש לה קונסול כבוד בישראל, האם לישראל יש קונסול כבוד אצלה, או "
                         f"שניהם. {n(len(both))} מדינות מיוצגות בשני הכיוונים."),
        "overlap_aria": "גרף עמודות מוערמות: מדינות לפי אזור וכיוון הייצוג.",
        "overlap_caption": "מדינות לפי אזור וכיוון הייצוג.",
        "top_ab_note": (f"מדינות שבהן פועל יותר מקונסול כבוד ישראלי אחד. "
                        f"{n(n_multi_ab)} מדינות כאלה" +
                        (f"; מוצגות {n(TOP_COUNTRIES)}." if n_multi_ab > TOP_COUNTRIES else ".") +
                        " אזורי השיפוט בטבלה."),
        "top_ab_aria": "גרף עמודות אופקי: מדינות עם כמה קונסולי כבוד ישראליים.",
        "top_ab_caption": "מדינות עם יותר מקונסול כבוד ישראלי אחד ואזורי השיפוט.",
        "top_il_note": (f"מדינות שמינו יותר מקונסול כבוד אחד בישראל. "
                        f"{n(n_multi_il)} מדינות כאלה" +
                        (f"; מוצגות {n(TOP_COUNTRIES)}." if n_multi_il > TOP_COUNTRIES else ".")),
        "top_il_aria": "גרף עמודות אופקי: מדינות עם כמה קונסולי כבוד בישראל.",
        "top_il_caption": "מדינות עם יותר מקונסול כבוד אחד בישראל ואזורי השיפוט.",
        "areas_note": (f"אזור השיפוט של קונסולי הכבוד בישראל כפי שפורסם — עיר או מחוז. קונסול שאחראי לכמה "
                       f"אזורים נספר בכל אחד מהם; „{NATIONWIDE}” מציין שיפוט על כל ישראל. "
                       f"{n(n_nonres)} קונסולים מסומנים גם „{NONRES_TOKEN}”."),
        "areas_aria": "גרף עמודות אופקי: קונסולי כבוד בישראל לפי אזור שיפוט.",
        "areas_caption": "קונסולי כבוד בישראל לפי אזור שיפוט.",
        "years_note": ("מועד המינוי של הקונסולים המכהנים כיום, בתקופות של חמש שנים. הרשימה כוללת רק את "
                       "המכהנים, ולכן תקופות מוקדמות מיוצגות רק בידי מי שעדיין בתפקיד." +
                       (f" התקופה האחרונה ({bins[-1][2]}) חלקית." if partial_last else "") +
                       (f" ל-{n(excl_date)} קונסולים אין מועד מינוי תקין." if excl_date else "")),
        "years_aria": "גרף עמודות: קונסולי כבוד מכהנים לפי תקופת מינוי, בישראל ובחו״ל.",
        "years_caption": "קונסולי כבוד מכהנים לפי תקופת מינוי.",
        "oldest_note": "הקונסולים שמכהנים זמן רב ביותר, לפי מועד המינוי שפורסם.",
        "oldest_il_caption": "קונסולי הכבוד הוותיקים בישראל.",
        "oldest_ab_caption": "קונסולי הכבוד הוותיקים של ישראל בחו״ל.",
        "titles_note": (f"רוב הקונסולים נושאים את התואר „{titles[0]}”. „קונסול כללי של כבוד” הוא דרגה בכירה יותר, "
                        f"ו„סגן קונסול כבוד” או „סוכן קונסולרי” זוטרות ממנה.") if titles else "",
        "titles_aria": "גרף עמודות אופקי: קונסולי כבוד לפי תואר, בישראל ובחו״ל.",
        "titles_caption": "קונסולי כבוד לפי תואר.",
        "gender_note": ("לפי התואר שלפני השם (מר / גברת). תואר אקדמי או היעדר תואר נספרים כלא צוין."),
        "gender_aria": "גרף עמודות מוערמות מנורמל: קונסולי כבוד לפי מגדר, בישראל ובחו״ל.",
        "gender_caption": "קונסולי כבוד לפי מגדר.",
        "contacts_note": ("שיעור הקונסולים שעבורם מפורסם כל פרט קשר. העמוד מציג רק את השיעורים; "
                          "הפרטים עצמם מופיעים בטבלת הנתונים שבתחתית העמוד."),
        "contacts_aria": "גרף עמודות אופקי: שיעור קונסולי הכבוד שפורסם עבורם כל פרט קשר.",
        "contacts_caption": "פרטי קשר שמפורסמים לקונסולי הכבוד.",
        "dir_il": DIR_LABEL[IL],
        "dir_ab": DIR_LABEL[AB],
    }

    temporal = f"{min_year}/{max_year}" if max_year is not None else None
    agent_data = {
        "summary_he": (f"{n(n_il)} קונסולי כבוד של {n(len(c_il))} מדינות זרות בישראל ו-{n(n_ab)} קונסולי כבוד של "
                       f"ישראל ב-{n(len(c_ab))} מדינות: מפת עולם, ייצוג דו-כיווני, אזורי שיפוט, מועדי מינוי, "
                       f"תארים, מגדר ושלמות פרטי הקשר."),
        "dataset_kind": "registry",
        "suggested_tags": ["קונסולי כבוד", "משרד החוץ", "קונסוליות", "דיפלומטיה", "יחסים בינלאומיים"],
        "related_ids": ["14f2521f-819a-4ea4-87e8-6811d43e4495", "bae5a627-f1bd-4da7-8b08-664cf626df47",
                        "0093a1b8-918b-42b7-b268-e35e22616de1", "4eaa3676-34ea-4c88-8980-dd64cba86411"],
        "spatial_coverage": "עולם",
    }
    if temporal:
        agent_data["temporal_coverage"] = temporal

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "charts": {"map": map_data, "regions": regions_chart, "overlap": overlap_chart,
                   "top_ab": top_ab_chart, "top_il": top_il_chart, "areas": areas_chart,
                   "years": years_chart, "titles": titles_chart, "gender": gender_chart,
                   "contacts": contacts_chart},
        "tables": {"regions": regions_table, "overlap": overlap_table, "top_ab": top_ab_table,
                   "top_il": top_il_table, "areas": areas_table, "years": years_table,
                   "oldest_il": oldest_il, "oldest_ab": oldest_ab, "titles": titles_table,
                   "gender": gender_table, "contacts": contacts_table},
        "flags": {"has_map": bool(pts), "has_top_ab": bool(top_ab_table), "has_top_il": bool(top_il_table),
                  "has_years": bool(bins), "has_oldest": bool(oldest_il or oldest_ab)},
        "insights": insights,
        "labels": labels,
    }
