"""Localities and countries in Hebrew, English, Arabic and Russian.

Two lookup tables from the National Digital Agency:
- localities: one row per Israeli locality (symbol number, name in four
  languages, ITM coordinates, straight-line distance to the Lebanon, Gaza
  Strip and Syria borders, in metres);
- countries: one row per country/territory (ISO numeric, alpha-2, alpha-3,
  internet TLD, international calling code, names in four languages).

The page is a lookup page: coverage of each language, how the codes are
built, where the localities lie relative to the borders, and the data
quality issues a lookup user should know about. The border distances are
checked against geography: a locality's distance should agree with its
nearest neighbours' within their spread plus a tolerance; values that
don't are counted and left out of the distance charts (disclosed).
"""
import re

import numpy as np
import pandas as pd
from govlib import fmt, frame

LANGS = ["עברית", "אנגלית", "ערבית", "רוסית"]
BORDERS = [
    ("Distance_From_Lebanon_Border", "lebanon", "גבול לבנון"),
    ("Distance_From_GazaStrip_Border", "gaza", "גבול רצועת עזה"),
    ("Distance_From_Syria_Border", "syria", "גבול סוריה"),
]
# Distance bands, metres (upper bounds, inclusive) and their km labels.
BANDS = [(5000, "עד 5"), (10000, "5-10"), (20000, "10-20"), (40000, "20-40"),
         (100000, "40-100"), (None, "מעל 100")]
NEAR_KM = 5            # "close to the border" threshold for the insight
NEIGHBOURS = 7         # neighbours used for the consistency check
TOLERANCE_M = 10000    # allowed deviation beyond the neighbours' spread
NEAR_N = 8             # rows in each "closest to the border" table
SAMPLE_N = 6
# Well-known rows shown first in the sample tables when present (codes, not
# data values; any missing one is replaced by the next row in code order).
SAMPLE_LOC = ["3000", "5000", "4000", "9000", "7300", "2600"]
SAMPLE_CTY = ["IL", "US", "GB", "FR", "EG", "JO"]
# ITU world numbering zones by the calling code's first digit.
ZONES = {
    "1": "צפון אמריקה והקריביים", "2": "אפריקה", "3": "אירופה", "4": "אירופה",
    "5": "מרכז ודרום אמריקה", "6": "אוקיאניה ודרום-מזרח אסיה",
    "7": "רוסיה וקזחסטן", "8": "מזרח אסיה", "9": "מערב, מרכז ודרום אסיה",
}
SHARED_N = 8
NIQQUD = re.compile("[֑-ׇ]")


def _i(v):
    return fmt.int_he(v)


def _km(m):
    return fmt.num_he(m / 1000.0, 1)


def _filled(s):
    return s != ""


def _localities(df):
    loc = pd.DataFrame({
        "sym": frame.clean_series(df["symbol_number"]),
        "he": frame.clean_series(df["name_in_hebrew"]),
        "en": frame.clean_series(df["name_in_english"]),
        "ar": frame.clean_series(df["name_in_arabic"]),
        "ru": frame.clean_series(df["name_in_russian"]),
        "x": frame.num(df["X"]),
        "y": frame.num(df["Y"]),
    })
    for col, key, _ in BORDERS:
        loc[key] = frame.num(df[col])
    loc["symn"] = pd.to_numeric(loc["sym"], errors="coerce")
    loc = loc[loc["he"] != ""]
    return loc.sort_values(["symn", "sym", "he"], kind="stable").reset_index(drop=True)


def _countries(df):
    c = pd.DataFrame({
        "iso": frame.clean_series(df["International_Code"]),
        "full": frame.clean_series(df["Full_Name"]),
        "en": frame.clean_series(df["Short_Name"]),
        "he": frame.clean_series(df["Hebrew_Name"]),
        "ar": frame.clean_series(df["Arabic_ Name"]),
        "ru_long": frame.clean_series(df["Russian_Long_Name"]),
        "ru": frame.clean_series(df["Russian_short_Name"]),
        "a2": frame.clean_series(df["Alfa_2_Code"]),
        "a3": frame.clean_series(df["Alfa_3_Code"]),
        "tld": frame.clean_series(df["Internet_cc_TLD"]),
        "phone": frame.clean_series(df["Numeric_Code"]),
        "he_raw": df["Hebrew_Name"].astype(str),
    })
    c["ison"] = pd.to_numeric(c["iso"], errors="coerce")
    c = c[(c["he"] != "") | (c["en"] != "")]
    c = c.sort_values(["ison", "iso", "en", "he"], kind="stable").reset_index(drop=True)
    c["base"] = c["phone"].str.extract(r"^(\d+)", expand=False).fillna("")
    return c


def _consistency(loc):
    """Per border, a float Series: 1 where the distance agrees with the
    locality's nearest neighbours, 0 where it doesn't, NaN when it can't be
    judged (no value, no coordinates, too few neighbours with values).
    `loc` has a RangeIndex."""
    out = {key: pd.Series(np.nan, index=loc.index, dtype=float) for _, key, _ in BORDERS}
    has_xy = loc["x"].notna() & loc["y"].notna()
    idx = loc.index[has_xy].to_numpy()
    if len(idx) < 4:
        return out
    xs = loc.loc[idx, "x"].to_numpy(float)
    ys = loc.loc[idx, "y"].to_numpy(float)
    dmat = np.hypot(xs[:, None] - xs[None, :], ys[:, None] - ys[None, :])
    np.fill_diagonal(dmat, np.inf)
    k = min(NEIGHBOURS, len(idx) - 1)
    nn = np.argsort(dmat, axis=1, kind="stable")[:, :k]
    for _, key, _ in BORDERS:
        v = loc.loc[idx, key].to_numpy(float)
        for i in range(len(idx)):
            if np.isnan(v[i]):
                continue
            nb = [j for j in nn[i] if not np.isnan(v[j])]
            if len(nb) < 3:
                continue
            med = float(np.median(v[nb]))
            rad = float(dmat[i, nb].max())
            out[key].iat[int(idx[i])] = 1.0 if abs(v[i] - med) <= rad + TOLERANCE_M else 0.0
    return out


def _band_counts(values):
    counts = []
    lo = -1.0
    for hi, _ in BANDS:
        if hi is None:
            counts.append(int((values > lo).sum()))
        else:
            counts.append(int(((values > lo) & (values <= hi)).sum()))
            lo = float(hi)
    return counts


def _sample(df, key_col, preferred, complete):
    rows = []
    for p in preferred:
        hit = df[(df[key_col] == p) & complete]
        if len(hit):
            rows.append(hit.index[0])
    for i in df.index[complete]:
        if len(rows) >= SAMPLE_N:
            break
        if i not in rows:
            rows.append(i)
    return df.loc[rows[:SAMPLE_N]]


def _first_names(names, n=3):
    return fmt.join_he(sorted(names)[:n])


def compute(frames):
    loc = _localities(frames["localities"])
    cty = _countries(frames["countries"])
    n_loc, n_cty = len(loc), len(cty)

    # ── language coverage ──────────────────────────────────────────────
    loc_fill = {k: int(_filled(loc[k]).sum()) for k in ["he", "en", "ar", "ru"]}
    cty_fill = {k: int(_filled(cty[k]).sum()) for k in ["he", "en", "ar", "ru"]}
    loc_pct = [round(loc_fill[k] / n_loc * 100, 1) if n_loc else 0 for k in ["he", "en", "ar", "ru"]]
    cty_pct = [round(cty_fill[k] / n_cty * 100, 1) if n_cty else 0 for k in ["he", "en", "ar", "ru"]]
    ar_share = loc_fill["ar"] / n_loc if n_loc else 0
    ru_share = loc_fill["ru"] / n_loc if n_loc else 0
    en_share = loc_fill["en"] / n_loc if n_loc else 0
    cty_low = min(zip(["עברית", "אנגלית", "ערבית", "רוסית"], cty_pct), key=lambda t: (t[1], t[0]))
    four_all = int((_filled(loc["en"]) & _filled(loc["ar"]) & _filled(loc["ru"])).sum())

    # ── locality symbols ───────────────────────────────────────────────
    symn = loc["symn"].dropna().astype(int)
    sym_min, sym_max = (int(symn.min()), int(symn.max())) if len(symn) else (0, 0)
    blocks = (symn // 1000).value_counts().sort_index()
    code_labels = [f"{b * 1000}-{b * 1000 + 999}" if b else "1-999" for b in blocks.index]
    code_values = [int(v) for v in blocks.values]
    digits = symn.astype(str).str.len().value_counts().sort_index()
    digit_rows = [[f"{int(k)}", _i(v), fmt.pct(v / len(symn))] for k, v in digits.items()] if len(symn) else []
    top_block = int(blocks.idxmax()) if len(blocks) else 0
    top_block_label = code_labels[list(blocks.index).index(top_block)] if len(blocks) else ""
    sym_unique = loc["sym"].nunique() == n_loc
    tribes = int(loc["he"].str.contains(r"\(\s*שבט\s*\)", regex=True).sum())

    # ── shared transliterations ────────────────────────────────────────
    dup_rows = []
    for lang_key, lang_he in [("en", "אנגלית"), ("ar", "ערבית")]:
        sub = loc[_filled(loc[lang_key])]
        g = sub.groupby(lang_key, sort=True)["he"].apply(lambda s: sorted(s))
        for name, hes in g.items():
            if len(hes) > 1:
                dup_rows.append([name, lang_he, fmt.join_he(hes)])
    dup_en = [r for r in dup_rows if r[1] == "אנגלית"]

    # ── coordinates and border distances ───────────────────────────────
    has_xy = loc["x"].notna() & loc["y"].notna()
    n_xy = int(has_xy.sum())
    cons = _consistency(loc)
    bad_any = pd.Series(False, index=loc.index)
    border_series = []
    border_table = []
    near = {}
    bad_counts = {}
    within = {}
    for col, key, label in BORDERS:
        ok = cons[key] == 1
        bad = cons[key] == 0
        bad_any = bad_any | bad
        bad_counts[key] = int(bad.sum())
        vals = loc.loc[ok, key]
        counts = _band_counts(vals)
        border_series.append({"name": label, "values": counts})
        within[key] = int((vals <= NEAR_KM * 1000).sum())
        nr = loc.loc[ok, ["he", "sym", key]].sort_values([key, "he", "sym"], kind="stable").head(NEAR_N)
        near[key] = {"label": label,
                     "rows": [[r["he"], _km(r[key])] for _, r in nr.iterrows()]}
    for bi, (_, blabel) in enumerate(BANDS):
        border_table.append([blabel] + [_i(s["values"][bi]) for s in border_series])
    n_bad = int(bad_any.sum())

    # fill-down pattern: a flagged value equal to the previous row's value in
    # Hebrew alphabetical order (the order the source file is kept in).
    alpha = loc.sort_values(["he", "sym"], kind="stable")
    same_prev = 0
    flagged = 0
    for _, key, _ in BORDERS:
        prev = alpha[key].shift(1)
        is_bad = (cons[key] == 0).reindex(alpha.index)
        flagged += int(is_bad.sum())
        same_prev += int((is_bad & (alpha[key] == prev)).sum())
    fill_share = same_prev / flagged if flagged else 0

    # ── countries: codes ───────────────────────────────────────────────
    has_phone = cty["base"] != ""
    zone_counts = cty.loc[has_phone, "base"].str[0].value_counts().sort_index()
    zone_labels = [f"{z}: {ZONES.get(z, 'אזור ' + z)}" for z in zone_counts.index]
    zone_values = [int(v) for v in zone_counts.values]
    # Within a shared code, the entries whose whole calling code is the bare
    # prefix (the "main" countries, e.g. +1 for the US and Canada) come first.
    ph = cty[has_phone].assign(sub=(cty["phone"] != cty["base"]).astype(int))
    ph = ph.sort_values(["base", "sub", "he"], kind="stable")
    shared = ph.groupby("base", sort=True)["he"].apply(list)
    shared = shared[shared.map(len) > 1]
    shared_df = pd.DataFrame({"base": shared.index, "n": shared.map(len).values,
                              "names": shared.values})
    shared_df["bn"] = pd.to_numeric(shared_df["base"], errors="coerce")
    shared_df = shared_df.sort_values(["n", "bn", "base"], ascending=[False, True, True], kind="stable")
    shared_top = shared_df.head(SHARED_N)
    n_shared_codes = len(shared_df)
    n_in_shared = int(shared_df["n"].sum()) if len(shared_df) else 0
    sub_codes = int(cty["phone"].str.contains(r"\(", regex=True).sum())

    a2_bad = cty[(cty["a2"] != "") & ~cty["a2"].str.fullmatch(r"[A-Z]{2}")]
    a2_missing = cty[cty["a2"] == ""]
    a3_missing = cty[cty["a3"] == ""]
    tld_missing = cty[cty["tld"] == ""]
    tld_mismatch = cty[(cty["tld"] != "") & cty["a2"].str.fullmatch(r"[A-Z]{2}")
                       & (cty["tld"].str.lower() != "." + cty["a2"].str.lower())]
    phone_missing = cty[~has_phone]
    niqqud = cty[cty["he"].str.contains(NIQQUD)]
    linebreak = cty[cty["he_raw"].str.contains("\n")]
    long_eq = int((cty["full"] == cty["en"]).sum())

    # ── quality table ──────────────────────────────────────────────────
    def names(df, col="he"):
        return _first_names(df[col].tolist())

    quality = []
    loc_nm = "יישובים"
    cty_nm = "מדינות"
    if n_loc - loc_fill["ru"]:
        quality.append([loc_nm, "חסר שם ברוסית", _i(n_loc - loc_fill["ru"]), ""])
    if n_loc - loc_fill["ar"]:
        quality.append([loc_nm, "חסר שם בערבית", _i(n_loc - loc_fill["ar"]), names(loc[~_filled(loc["ar"])])])
    if n_loc - loc_fill["en"]:
        quality.append([loc_nm, "חסר שם באנגלית", _i(n_loc - loc_fill["en"]), names(loc[~_filled(loc["en"])])])
    if n_loc - n_xy:
        quality.append([loc_nm, "חסרות קואורדינטות", _i(n_loc - n_xy), names(loc[~has_xy])])
    for _, key, label in BORDERS:
        if bad_counts[key]:
            quality.append([loc_nm, f"מרחק מ{label} לא עקבי עם המיקום", _i(bad_counts[key]),
                            names(loc[cons[key] == 0])])
    if dup_rows:
        quality.append([loc_nm, "שם זהה ליותר מיישוב אחד", _i(len(dup_rows)),
                        _first_names([r[0] for r in dup_rows])])
    if len(a2_bad):
        quality.append([cty_nm, "קוד אלפא-2 שאינו שתי אותיות", _i(len(a2_bad)),
                        fmt.join_he([f"{h} ({a})" for h, a in zip(a2_bad["he"], a2_bad["a2"])][:3])])
    if len(a2_missing):
        quality.append([cty_nm, "חסר קוד אלפא-2", _i(len(a2_missing)), names(a2_missing)])
    if len(a3_missing):
        quality.append([cty_nm, "חסר קוד אלפא-3", _i(len(a3_missing)), names(a3_missing)])
    if len(tld_missing):
        quality.append([cty_nm, "חסרה סיומת אינטרנט", _i(len(tld_missing)), names(tld_missing)])
    if len(tld_mismatch):
        quality.append([cty_nm, "סיומת אינטרנט שונה מקוד אלפא-2", _i(len(tld_mismatch)), names(tld_mismatch)])
    if len(phone_missing):
        quality.append([cty_nm, "חסרה קידומת טלפון", _i(len(phone_missing)), names(phone_missing)])
    if len(niqqud):
        quality.append([cty_nm, "שם עברי עם סימני ניקוד חלקיים", _i(len(niqqud)), names(niqqud)])
    if len(linebreak):
        quality.append([cty_nm, "שם עברי עם ירידת שורה", _i(len(linebreak)), names(linebreak)])

    # ── samples ────────────────────────────────────────────────────────
    loc_complete = _filled(loc["en"]) & _filled(loc["ar"]) & _filled(loc["ru"])
    s_loc = _sample(loc, "sym", SAMPLE_LOC, loc_complete)
    sample_loc = [[r["he"], r["en"], r["ar"], r["ru"], r["sym"]] for _, r in s_loc.iterrows()]
    cty_complete = _filled(cty["en"]) & _filled(cty["ar"]) & _filled(cty["ru"]) & _filled(cty["a2"])
    s_cty = _sample(cty, "a2", SAMPLE_CTY, cty_complete)
    sample_cty_names = [[r["he"], r["en"], r["ar"], r["ru"]] for _, r in s_cty.iterrows()]
    sample_cty_codes = [[r["he"], r["iso"] or "–", r["a2"] or "–", r["a3"] or "–",
                         ("+" + r["phone"]) if r["phone"] else "–", r["tld"] or "–"]
                        for _, r in s_cty.iterrows()]
    ex = s_cty.iloc[0] if len(s_cty) else None

    # ── insights ───────────────────────────────────────────────────────
    insights = []
    if n_loc and ru_share < ar_share - 0.1:
        insights.append({"id": "coverage", "text_he": (
            f"ל-{fmt.pct(ar_share)} מהיישובים יש שם בערבית ול-{fmt.pct(en_share)} שם באנגלית, "
            f"אבל שם ברוסית מופיע רק ל-{_i(loc_fill['ru'])} יישובים ({fmt.pct(ru_share)}). "
            f"בכל ארבע השפות יחד: {_i(four_all)} יישובים.")})
    elif n_loc:
        insights.append({"id": "coverage", "text_he": (
            f"שמות היישובים כמעט מלאים בכל השפות: ערבית {fmt.pct(ar_share)}, אנגלית {fmt.pct(en_share)} "
            f"ורוסית {fmt.pct(ru_share)}.")})
    if n_bad:
        tail = ""
        if fill_share >= 0.5:
            tail = (f" ב-{fmt.pct(fill_share, 0)} מהמקרים הערך זהה לזה של היישוב הקודם בסדר האלפביתי, "
                    "כנראה ערך שהועתק משורה סמוכה.")
        insights.append({"id": "distance_check", "text_he": (
            f"ב-{_i(n_bad)} יישובים ({fmt.pct(n_bad / n_loc)}) לפחות אחד מהמרחקים מהגבול סוטה ביותר מ-"
            f"{_i(TOLERANCE_M / 1000)} ק״מ מעבר למה שמראים היישובים הסמוכים לו.{tail} "
            "לפני שימוש במרחק כדאי לבדוק אותו מול המיקום.")})
    if any(within.values()):
        insights.append({"id": "near_borders", "text_he": (
            f"עד {NEAR_KM} ק״מ מהגבול (מרחקים עקביים בלבד): {_i(within['lebanon'])} יישובים מגבול לבנון, "
            f"{_i(within['gaza'])} מגבול רצועת עזה {fmt.vav(_i(within['syria']))} מגבול סוריה.")})
    closest = [(near[k]["label"], near[k]["rows"][0]) for _, k, _ in BORDERS if near[k]["rows"]]
    if len(closest) == len(BORDERS):
        insights.append({"id": "closest", "text_he": "היישובים הקרובים ביותר לכל גבול: " + fmt.join_he(
            [f"ל{lbl} {row[0]} ({row[1]} ק״מ)" for lbl, row in closest]) + "."})
    if dup_en:
        r0 = dup_en[0]
        insights.append({"id": "dup_names", "text_he": (
            f"{_i(len(dup_en))} שמות באנגלית משמשים ליותר מיישוב אחד, למשל {r0[0]} עבור {r0[2]}. "
            "בחיפוש לפי שם באנגלית כדאי לוודא את היישוב לפי סמל היישוב.")})
    if tribes:
        insights.append({"id": "tribes", "text_he": (
            f"{_i(tribes)} מהרשומות מסומנות \"(שבט)\" בשם: שבטים הרשומים כיישוב בפני עצמו, עם סמל יישוב משלהם.")})
    if len(shared_df) and int(shared_df.iloc[0]["n"]) >= 3:
        r0 = shared_df.iloc[0]
        insights.append({"id": "shared_code", "text_he": (
            f"קידומת החיוג {r0['base']} משותפת ל-{_i(r0['n'])} מדינות וטריטוריות, ביניהן "
            f"{fmt.join_he(r0['names'][:3])}. בסך הכול {_i(n_in_shared)} רשומות חולקות {_i(n_shared_codes)} קידומות.")})
    if len(a2_bad) or len(tld_mismatch):
        bits = []
        if len(a2_bad):
            r0 = a2_bad.iloc[0]
            bits.append(f"קוד האלפא-2 של {r0['he']} רשום \"{r0['a2']}\" ולא שתי אותיות")
        if len(tld_mismatch):
            bits.append(f"ב-{_i(len(tld_mismatch))} מדינות סיומת האינטרנט אינה תואמת את קוד האלפא-2")
        insights.append({"id": "country_codes", "text_he": "בטבלת המדינות: " + "; ".join(bits) + "."})

    # ── KPIs ───────────────────────────────────────────────────────────
    kpis = {
        "loc": {"value": n_loc, "display": _i(n_loc), "tone": "brand"},
        "cty": {"value": n_cty, "display": _i(n_cty), "tone": "brand"},
        "ar": {"value": round(ar_share, 4), "display": fmt.pct(ar_share),
               "tone": "ok" if ar_share >= 0.95 else "warn"},
        "ru": {"value": round(ru_share, 4), "display": fmt.pct(ru_share),
               "tone": "ok" if ru_share >= 0.9 else ("warn" if ru_share >= 0.1 else "danger")},
        "xy": {"value": n_xy, "display": _i(n_xy), "tone": "brand" if n_xy == n_loc else "info"},
        "bad": {"value": n_bad, "display": _i(n_bad), "tone": "warn" if n_bad else "ok"},
    }

    # ── text ───────────────────────────────────────────────────────────
    summary = (f"שמות {_i(n_loc)} יישובים בישראל בעברית, אנגלית, ערבית ורוסית, עם סמל יישוב, "
               f"קואורדינטות ומרחק מהגבולות, ולצדם {_i(n_cty)} מדינות וטריטוריות עם שמות בארבע השפות, "
               "קודי ISO, סיומת אינטרנט וקידומת טלפון.")
    seo_desc = (f"תרגום שם יישוב או מדינה לאנגלית, ערבית ורוסית, וקודים: סמל יישוב, קוד ISO וקידומת חיוג. "
                f"{_i(n_loc)} יישובים {fmt.vav(_i(n_cty))} מדינות.")
    lede = (f"מאגר עזר דו-חלקי של מערך הדיגיטל הלאומי. החלק הראשון מונה {_i(n_loc)} יישובים, "
            f"לכל אחד סמל יישוב ושם בעברית; שם באנגלית יש ל-{_i(loc_fill['en'])} מהם, בערבית ל-{_i(loc_fill['ar'])} "
            f"וברוסית ל-{_i(loc_fill['ru'])}. "
            f"החלק השני מונה {_i(n_cty)} מדינות וטריטוריות עם שם מלא ומקוצר, שמות בעברית, ערבית ורוסית, "
            "ומערכות הקודים המקובלות: קוד מספרי וקודי אותיות של ISO, סיומת אינטרנט וקידומת חיוג בינלאומית. "
            "המקור מציין שהנתונים אוחדו ממקורות שונים ואינם רשמיים.")

    labels = {
        "lede": lede,
        "kpi_loc": "יישובים ברשימה",
        "kpi_cty": "מדינות וטריטוריות",
        "kpi_ar": "יישובים עם שם בערבית",
        "kpi_ru": "יישובים עם שם ברוסית",
        "kpi_xy": "יישובים עם קואורדינטות",
        "kpi_bad": "יישובים עם מרחק מגבול חשוד",
        "langs_note": (f"אחוז הרשומות שיש בהן שם בכל שפה. ביישובים: ערבית {fmt.pct(ar_share)}, "
                       f"רוסית {fmt.pct(ru_share)}. במדינות הכיסוי הנמוך ביותר הוא ב{cty_low[0]}: {fmt.pct_of(cty_low[1])} "
                       "(באנגלית וברוסית נבדק השם המקוצר)."),
        "langs_aria": (f"גרף עמודות: אחוז הרשומות עם שם בכל שפה, יישובים ומדינות. "
                       f"שם ברוסית יש ל-{fmt.pct(ru_share)} מהיישובים."),
        "sample_loc_note": "כך נראית רשומת יישוב: אותו יישוב בארבע השפות, לצד סמל היישוב.",
        "sample_loc_cap": "דוגמת יישובים בארבע השפות וסמל היישוב",
        "codes_note": (f"סמל היישוב הוא מספר בין {sym_min} ל-{sym_max}"
                       + (", ייחודי לכל יישוב. " if sym_unique else f"; {_i(n_loc - loc['sym'].nunique())} סמלים חוזרים ביותר מרשומה אחת. ")
                       +
                       f"הטווח הנפוץ ביותר הוא {top_block_label}, עם {fmt.pct(blocks.max() / len(symn)) if len(symn) else ''} מהסמלים."),
        "codes_aria": (f"גרף עמודות: מספר היישובים לפי טווח סמל יישוב. הטווח הנפוץ: {top_block_label} "
                       f"עם {_i(int(blocks.max()) if len(blocks) else 0)} יישובים."),
        "digits_cap": "מספר היישובים לפי מספר הספרות בסמל",
        "map_aria": "מפה אינטראקטיבית של היישובים במאגר. גרסה נגישה: ראו את טבלת הנתונים בהמשך העמוד.",
        "map_note": (f"{_i(n_xy)} יישובים עם קואורדינטות (רשת ישראל החדשה), מוצגים במקבצים. "
                     f"לחיצה על נקודה מציגה את השם בארבע השפות ואת סמל היישוב."
                     + (f" {_i(n_loc - n_xy)} יישובים ללא קואורדינטות אינם מוצגים." if n_loc - n_xy else "")),
        "borders_note": (f"מספר היישובים בכל טווח מרחק (ק״מ, קו אווירי) מכל גבול. מוצגים רק מרחקים "
                         f"שעקביים עם מיקום היישוב: {_i(n_bad)} יישובים שבהם מרחק סוטה מהיישובים "
                         f"הסמוכים ביותר מ-{_i(TOLERANCE_M / 1000)} ק״מ אינם נספרים באותו גבול."),
        "borders_aria": (f"גרף עמודות מקובץ: יישובים לפי טווח מרחק מגבולות לבנון, רצועת עזה וסוריה. "
                         f"עד {NEAR_KM} ק״מ: {_i(within['lebanon'])} מגבול לבנון, {_i(within['gaza'])} "
                         f"מגבול הרצועה, {_i(within['syria'])} מגבול סוריה."),
        "near_note": "היישובים עם המרחק הקטן ביותר לכל גבול לפי המאגר (מרחקים עקביים בלבד), בק״מ.",
        "dup_note": ("שמות בתעתיק לאנגלית או לערבית שמופיעים ביותר מרשומה אחת, למשל שבט ויישוב "
                     "באותו שם, או שני שמות עבריים שונים שקיבלו תעתיק זהה. כדאי להבחין ביניהם לפי סמל היישוב."),
        "dup_cap": "שמות בתעתיק המשותפים ליותר מיישוב אחד",
        "zones_note": (f"קידומות החיוג לפי אזור החיוג העולמי (הספרה הראשונה בקידומת). "
                       f"{_i(int(has_phone.sum()))} מתוך {_i(n_cty)} רשומות כוללות קידומת; "
                       f"ב-{_i(sub_codes)} מהן מופיע בסוגריים גם קוד אזור, למשל בטריטוריות שחולקות קידומת עם מדינת האם."),
        "zones_aria": ("גרף עמודות: מדינות וטריטוריות לפי אזור חיוג עולמי. "
                       + (f"האזור הגדול: {zone_labels[int(np.argmax(zone_values))]} עם {_i(max(zone_values))} רשומות."
                          if zone_values else "")),
        "shared_note": (f"{_i(n_shared_codes)} קידומות משותפות ליותר מרשומה אחת, בסך הכול {_i(n_in_shared)} רשומות. "
                        "מעבר עם העכבר על עמודה מציג את הרשומות."),
        "shared_aria": ("גרף עמודות: קידומות החיוג המשותפות ליותר ממדינה אחת. "
                        + (f"קידומת {shared_top.iloc[0]['base']} משותפת ל-{_i(shared_top.iloc[0]['n'])} רשומות."
                           if len(shared_top) else "")),
        "cty_names_note": (f"אותן מדינות בארבע שפות. בטבלה נשמרים גם שם רשמי מלא באנגלית וברוסית; "
                           f"ב-{_i(n_cty - long_eq)} מדינות הוא שונה מהשם המקוצר."),
        "cty_names_cap": "דוגמת מדינות בארבע שפות",
        "cty_codes_note": ("חמש מערכות הקודים שבמאגר"
                           + (f", בדוגמת {ex['he']}: קוד מספרי {ex['iso']}, קוד אלפא-2 {ex['a2']}, "
                              f"קוד אלפא-3 {ex['a3']}, קידומת חיוג {ex['phone']} וסיומת אינטרנט {ex['tld']}."
                              if ex is not None else ".")),
        "cty_codes_cap": "דוגמת מדינות וקודיהן",
        "quality_note": ("בדיקות שחושבו על כל רשומות המאגר. מספר הרשומות בכל בדיקה ועד שלוש דוגמאות. "
                         "מרחק חשוד הוא מרחק שסוטה מחציון שבעת היישובים הקרובים ביותר יותר ממרחקם "
                         f"ועוד {_i(TOLERANCE_M / 1000)} ק״מ."),
        "quality_cap": "בדיקות איכות הנתונים במאגר",
    }

    tables = {
        "langs": [[lg, fmt.pct_of(a), fmt.pct_of(b)] for lg, a, b in zip(LANGS, loc_pct, cty_pct)],
        "sample_loc": sample_loc,
        "digits": digit_rows,
        "codes": [[lbl, _i(v)] for lbl, v in zip(code_labels, code_values)],
        "borders": border_table,
        "near": [near[k] for _, k, _ in BORDERS],
        "dup": dup_rows,
        "zones": [[lbl, _i(v)] for lbl, v in zip(zone_labels, zone_values)],
        "shared": [[r["base"], _i(r["n"]), fmt.join_he(r["names"][:6])] for _, r in shared_top.iterrows()],
        "cty_names": sample_cty_names,
        "cty_codes": sample_cty_codes,
        "quality": quality,
    }

    charts = {
        "langs": {"langs": LANGS, "loc": loc_pct, "cty": cty_pct},
        "codes": {"labels": code_labels, "values": code_values},
        "borders": {"bands": [b for _, b in BANDS], "series": border_series},
        "zones": {"labels": zone_labels, "values": zone_values},
        "shared": {"labels": [f"קידומת {b}" for b in shared_top["base"]],
                   "values": [int(v) for v in shared_top["n"]],
                   "names": [list(v)[:12] for v in shared_top["names"]]},
    }

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "registry",
            "spatial_coverage": "ישראל ומדינות העולם",
            "seo": {
                "title": "תרגום שמות יישובים ומדינות: עברית, אנגלית, ערבית, רוסית",
                "description": seo_desc,
                "name": "שמות יישובים ומדינות בעברית, אנגלית, ערבית ורוסית",
                "alternate_names": [
                    "יישובים ומדינות (עברית, אנגלית, ערבית ורוסית)",
                    "שמות ישובים באנגלית ובערבית",
                    "רשימת מדינות בעברית עם קודי ISO",
                    "קידומות חיוג בינלאומיות לפי מדינה",
                    "סמלי יישובים ומרחק מהגבול",
                ],
            },
        },
        "kpis": kpis,
        "charts": charts,
        "insights": insights,
        "tables": tables,
        "labels": labels,
        "flags": {"map": n_xy > 0, "dup": bool(dup_rows), "shared": bool(len(shared_top)),
                  "quality": bool(quality)},
    }
