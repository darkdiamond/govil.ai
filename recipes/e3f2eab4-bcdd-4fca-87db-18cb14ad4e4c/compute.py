"""כמות כלי רכב חדשים בעלי קוד דגם העולים על הכביש בכל חודש.

One row per (closing month, vehicle type, make code, model code, model name):
how many new vehicles of that model were registered ("closed") that month.
`sgira_month` is YYYYMM; `sug_degem` is P (private), M (commercial) or 3
(two-wheelers). The file grows by one month (~2,000 rows) every month.

Make (brand) and country of manufacture are parsed from `tozeret_nm`, which
is "<brand> <country>" truncated to ~14 characters ("מיצובישי תאילנ",
"קיה ד. קוריאה"). A trailing token is read as a country when it is a prefix
of a known country spelling; otherwise the brand is the whole name and the
country is "לא ידוע" (its share is disclosed on the page).

"Latest" is the latest month in the data. The latest year is partial unless
it reaches December, so year-on-year rules compare the same months
(year to date) and "last 12 months" windows end at the latest month.
"""
import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
UNKNOWN = "לא ידוע"
OTHER = "אחר"

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
TYPE_NAMES = {"P": "פרטי", "M": "מסחרי", "3": "דו־גלגלי"}
TYPE_ORDER = ["P", "M", "3"]

# (canonical name, spellings seen in tozeret_nm; a truncated token matches by prefix)
COUNTRIES = [
    ("יפן", ["יפן"]), ("קוריאה הדרומית", ["קוריאה", "ד.קוריאה"]), ("צ'כיה", ["צ'כיה"]),
    ("טורקיה", ["טורקיה", "תורכיה"]), ("סין", ["סין"]), ("ספרד", ["ספרד"]),
    ("צרפת", ["צרפת"]), ("בריטניה", ["אנגליה", "בריטניה"]), ("סלובקיה", ["סלובקיה"]),
    ("גרמניה", ["גרמניה"]), ("הונגריה", ["הונגריה"]), ("תאילנד", ["תאילנד"]),
    ("ארה״ב", ['ארהב"', "ארה''ב", "ארהב", "ארה״ב"]), ("הודו", ["הודו"]),
    ("מקסיקו", ["מקסיקו"]), ("רומניה", ["רומניה"]), ("איטליה", ["איטליה"]),
    ("בלגיה", ["בלגיה"]), ("פולין", ["פולין"]),
    ("טאיוואן", ["טאיוואן", "טאיוון", "טיוואן", "טיואן"]), ("פורטוגל", ["פורטוגל"]),
    ("קנדה", ["קנדה"]), ("שבדיה", ["שבדיה"]), ("אוסטריה", ["אוסטריה"]),
    ("מרוקו", ["מרוקו"]), ("וייטנאם", ["ויאטנם", "ויטנאם", "וייטנאם"]),
    ("אינדונזיה", ["אינדונזיה"]), ("הולנד", ["הולנד"]), ("סלובניה", ["סלובניה"]),
    ("סרביה", ["סרביה"]), ("פינלנד", ["פינלנד"]), ("ארגנטינה", ["ארגנטינה"]),
    ("דרום אפריקה", ["אפריקה", "ד.אפריקה"]),
]
# Whole-name fixes for makes whose name carries no country token.
NAME_FIX = {"מרוטי סוזוקי": ("סוזוקי", "הודו")}
BRAND_FIX = {"ימאהה": "ימהה", "דאציה": "דאצ'יה"}

TOP_COUNTRIES = 8
TOP_BRANDS = 15
TOP_MODELS = 15
TOP_TWO = 10
BRAND_LINES = 6
COUNTRY_GAP = 5          # years between the two points of the country comparison
SHIFT_PP = 5.0           # min share change (percentage points) for the country insight
SURGE_PP = 15.0          # a gain this large is worded "זינק"
FLAT_PCT = 3.0           # |change| below this is "יציבות"
MIN_GROWER = 2000        # min vehicles in the last 12 months for the fastest-grower rule
MIN_SEASON_YEARS = 3     # full years needed for the seasonality rule
PARTIAL_LOOKBACK = 12    # months the latest month's row count is compared against
PARTIAL_ROWS = 0.35      # latest month below this share of their median rows = partial


def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def signed_pct_display(v):
    s = f"{abs(v):.1f}%"
    return ("+" + s) if v > 0 else (MINUS + s if v < 0 else s)


def pts(v):
    return f"{LRI}{abs(v):.1f}{PDI} נקודות אחוז"


def _country_of(tok):
    if len(tok) < 2:
        return None
    for name, spellings in COUNTRIES:
        for s in spellings:
            if s.startswith(tok):
                return name
    return None


def parse_make(nm):
    """'מיצובישי תאילנ' -> ('מיצובישי', 'תאילנד')."""
    clean = " ".join(nm.replace("-", " ").replace("_", " ").split())
    if clean in NAME_FIX:
        return NAME_FIX[clean]
    toks = clean.split()
    brand, country = clean, UNKNOWN
    if len(toks) >= 2:
        c = _country_of(toks[-1])
        if c:
            b = toks[:-1]
            while b and b[-1] in ("ד.", "ד"):
                b = b[:-1]
            if b:
                brand, country = " ".join(b), c
    brand = BRAND_FIX.get(brand, brand)
    if brand == "":
        brand = UNKNOWN
    return brand, country


def month_label(ym):
    return f"{MONTHS_HE[int(ym[4:]) - 1]} {ym[:4]}"


def _rank(series):
    """Series name->value to list of (name, value), value desc, name asc."""
    return sorted(((k, float(v)) for k, v in series.items()), key=lambda kv: (-kv[1], kv[0]))


def _prepare(df):
    d = pd.DataFrame({
        "ym": df["sgira_month"].str.strip(),
        "typ": df["sug_degem"].str.strip(),
        "make_cd": df["tozeret_cd"].str.strip(),
        "make_nm": df["tozeret_nm"].str.strip(),
        "model_cd": df["degem_cd"].str.strip(),
        "kinuy": df["kinuy_mishari"].str.strip(),
        "n": pd.to_numeric(df["car_num"].str.replace(",", "", regex=False).str.strip(),
                           errors="coerce"),
    })
    d = d[d["ym"].str.fullmatch(r"(19|20)\d{2}(0[1-9]|1[0-2])") & d["n"].notna() & (d["n"] > 0)].copy()
    d["n"] = d["n"].astype(int)
    d["year"] = d["ym"].str[:4].astype(int)
    d["mon"] = d["ym"].str[4:].astype(int)
    parsed = {nm: parse_make(nm) for nm in sorted(d["make_nm"].unique())}
    d["brand"] = d["make_nm"].map(lambda x: parsed[x][0])
    d["country"] = d["make_nm"].map(lambda x: parsed[x][1])
    d["type_name"] = d["typ"].map(lambda t: TYPE_NAMES.get(t, f"סוג {t}" if t else "לא צוין"))
    return d


def _months_between(first, last):
    out = []
    y, m = int(first[:4]), int(first[4:])
    ly, lm = int(last[:4]), int(last[4:])
    while (y, m) <= (ly, lm):
        out.append(f"{y}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _shift(ym, k):
    y, m = int(ym[:4]), int(ym[4:])
    t = y * 12 + (m - 1) - k
    return f"{t // 12}{t % 12 + 1:02d}"


def compute(frames):
    d = _prepare(frames["main"])
    # Upstream publishes complete months only; guard anyway: a latest month with
    # far fewer rows than the months before it is treated as partial and set aside.
    rows_per = d.groupby("ym").size().sort_index()
    partial_note = ""
    if len(rows_per) > PARTIAL_LOOKBACK:
        ref = float(rows_per.iloc[-PARTIAL_LOOKBACK - 1:-1].median())
        last_rows = int(rows_per.iloc[-1])
        if ref > 0 and last_rows < PARTIAL_ROWS * ref:
            dropped = rows_per.index[-1]
            dropped_n = int(d.loc[d["ym"] == dropped, "n"].sum())
            d = d[d["ym"] != dropped].copy()
            partial_note = (f" החודש האחרון בקובץ ({month_label(dropped)}, {n(dropped_n)} כלי רכב) נראה חלקי "
                            f"ולכן אינו נכלל בתרשימים ובהשוואות.")
    total_all = int(d["n"].sum())
    months_present = sorted(d["ym"].unique())
    first_ym, last_ym = months_present[0], months_present[-1]
    months = _months_between(first_ym, last_ym)
    last_year, last_mon = int(last_ym[:4]), int(last_ym[4:])
    first_year = int(first_ym[:4])
    partial_year = last_mon < 12
    full_years = sorted({y for y in d["year"].unique()
                         if d.loc[d["year"] == y, "mon"].nunique() == 12})

    # ---------------------------------------------------------- monthly series
    types_present = [t for t in TYPE_ORDER if t in set(d["typ"])] + \
        sorted(set(d["typ"]) - set(TYPE_ORDER))
    mt = d.groupby(["ym", "typ"])["n"].sum()
    monthly_series = []
    for t in types_present:
        monthly_series.append({
            "name": TYPE_NAMES.get(t, f"סוג {t}" if t else "לא צוין"),
            "data": [int(mt.get((ym, t), 0)) for ym in months],
        })
    month_tot = d.groupby("ym")["n"].sum()
    monthly = {"x": [f"{ym[4:]}/{ym[:4]}" for ym in months], "series": monthly_series}

    latest_month_total = int(month_tot.get(last_ym, 0))
    prev_year_ym = _shift(last_ym, 12)
    prev_year_month_total = int(month_tot.get(prev_year_ym, 0)) if prev_year_ym in month_tot.index else None

    # ---------------------------------------------------------- yearly + YTD
    years = list(range(first_year, last_year + 1))
    yt = d.groupby("year")["n"].sum()
    ytd = d[d["mon"] <= last_mon].groupby("year")["n"].sum()
    yearly = {
        "x": [str(y) for y in years],
        "full": [int(yt.get(y, 0)) if (y in full_years) else None for y in years],
        "partial": [int(yt.get(y, 0)) if (y not in full_years) else None for y in years],
        "ytd": [int(ytd.get(y, 0)) for y in years],
    }
    ytd_label = (f"ינואר עד {MONTHS_HE[last_mon - 1]}" if last_mon > 1 else "ינואר")
    yearly_rows = [{"year": str(y), "total": n(yt.get(y, 0)),
                    "ytd": n(ytd.get(y, 0)),
                    "note": "" if y in full_years else "שנה חלקית"} for y in years]

    ytd_now = int(ytd.get(last_year, 0))
    ytd_prev = int(ytd.get(last_year - 1, 0)) if (last_year - 1) in ytd.index else 0
    ytd_chg = (ytd_now / ytd_prev - 1) * 100 if ytd_prev > 0 else None

    # ---------------------------------------------------------- seasonality heatmap
    ym_tot = d.groupby(["year", "mon"])["n"].sum()
    heat_cells = []
    for yi, y in enumerate(years):
        for mi in range(12):
            v = ym_tot.get((y, mi + 1))
            if v is not None:
                heat_cells.append([mi, yi, int(v)])
    heat = {"x": MONTHS_HE, "y": [str(y) for y in years], "cells": heat_cells,
            "max": max((c[2] for c in heat_cells), default=0)}
    # month index: month total / that year's average month, averaged over full years
    season_idx = None
    if len(full_years) >= MIN_SEASON_YEARS:
        idx = {}
        for mi in range(1, 13):
            vals = [ym_tot.get((y, mi), 0) / (yt.get(y, 0) / 12) for y in full_years if yt.get(y, 0) > 0]
            idx[mi] = sum(vals) / len(vals) if vals else 0.0
        season_idx = idx

    # ---------------------------------------------------------- vehicle type by year
    ty = d.groupby(["year", "typ"])["n"].sum()
    types_year = {"x": [str(y) for y in years], "series": [
        {"name": TYPE_NAMES.get(t, f"סוג {t}" if t else "לא צוין"),
         "data": [int(ty.get((y, t), 0)) for y in years]} for t in types_present]}
    types_rows = []
    for y in years:
        row = {"year": str(y), "vals": [n(ty.get((y, t), 0)) for t in types_present]}
        types_rows.append(row)
    type_headers = [s["name"] for s in types_year["series"]]

    # ---------------------------------------------------------- country of manufacture
    cy = d.groupby(["year", "country"])["n"].sum()
    win12 = set(_shift(last_ym, k) for k in range(12))
    prev12 = set(_shift(last_ym, k) for k in range(12, 24))
    d12 = d[d["ym"].isin(win12)]
    dp12 = d[d["ym"].isin(prev12)]
    c12 = _rank(d12.groupby("country")["n"].sum())
    top_c = [c for c, _ in c12 if c != UNKNOWN][:TOP_COUNTRIES]
    country_series = []
    for c in top_c + [OTHER]:
        data = []
        for y in years:
            tot = yt.get(y, 0)
            if c == OTHER:
                v = tot - sum(cy.get((y, k), 0) for k in top_c)
            else:
                v = cy.get((y, c), 0)
            data.append(round(v / tot * 100, 1) if tot else 0.0)
        country_series.append({"name": c, "data": data})
    country_share = {"x": [str(y) for y in years], "series": country_series}

    def cshare(y, c):
        tot = yt.get(y, 0)
        return cy.get((y, c), 0) / tot * 100 if tot else 0.0

    # comparison year: latest year vs COUNTRY_GAP years earlier (or the first year)
    base_year = max(first_year, last_year - COUNTRY_GAP)
    countries_all = sorted({c for (_, c) in cy.index if c != UNKNOWN})
    comp = sorted(countries_all, key=lambda c: (-(cshare(last_year, c) + cshare(base_year, c)), c))[:10]
    country_cmp = {"names": comp,
                   "base": [round(cshare(base_year, c), 1) for c in comp],
                   "last": [round(cshare(last_year, c), 1) for c in comp],
                   "base_year": str(base_year), "last_year": str(last_year)}
    country_rows = [{"name": c, "base": pct(cshare(base_year, c)), "last": pct(cshare(last_year, c))}
                    for c in comp]
    unknown_share = cshare(last_year, UNKNOWN)

    # ---------------------------------------------------------- brands (last 12 months)
    b12 = d12.groupby("brand")["n"].sum()
    bp12 = dp12.groupby("brand")["n"].sum()
    tot12 = int(d12["n"].sum())
    totp12 = int(dp12["n"].sum())
    rb = _rank(b12)
    top_b = rb[:TOP_BRANDS]
    brands = {"names": [b for b, _ in top_b], "values": [int(v) for _, v in top_b],
              "prev": [int(bp12.get(b, 0)) for b, _ in top_b]}
    brand_rows = []
    for b, v in top_b:
        pv = int(bp12.get(b, 0))
        chg = ("חדש" if pv == 0 else signed_pct_display((v / pv - 1) * 100)) if totp12 else ""
        brand_rows.append({"name": b, "count": n(v), "share": pct(v / tot12 * 100) if tot12 else "",
                           "chg": chg})

    # brand share over years: lines for the top brands of the last 12 months
    by = d.groupby(["year", "brand"])["n"].sum()
    brand_lines = {"x": [str(y) for y in years], "series": [
        {"name": b, "data": [round(by.get((y, b), 0) / yt.get(y, 1) * 100, 1) for y in years]}
        for b, _ in rb[:BRAND_LINES]]}

    # ---------------------------------------------------------- models (private + commercial)
    dm = d12[(d12["typ"].isin(["P", "M"])) & (d12["kinuy"] != "")]
    mg = dm.groupby(["brand", "kinuy"])["n"].sum()
    rm = sorted(((b, k, int(v)) for (b, k), v in mg.items()), key=lambda t: (-t[2], t[0], t[1]))
    top_m = rm[:TOP_MODELS]
    models = {"names": [f"{k} ({b})" for b, k, _ in top_m], "values": [v for _, _, v in top_m]}
    model_rows = [{"model": k, "brand": b, "count": n(v)} for b, k, v in top_m]

    # ---------------------------------------------------------- two-wheelers
    d2 = d12[d12["typ"] == "3"]
    two = None
    two_rows = []
    if len(d2):
        r2 = _rank(d2.groupby("brand")["n"].sum())[:TOP_TWO]
        two = {"names": [b for b, _ in r2], "values": [int(v) for _, v in r2]}
        two_rows = [{"name": b, "count": n(v)} for b, v in r2]
    two_total = int(d2["n"].sum())

    # ---------------------------------------------------------- diversity
    div_brands = d.groupby("year")["brand"].nunique()
    div_models = d.drop_duplicates(["year", "make_cd", "model_cd"]).groupby("year").size()
    diversity = {"x": [str(y) for y in years],
                 "brands": [int(div_brands.get(y, 0)) for y in years],
                 "models": [int(div_models.get(y, 0)) for y in years]}
    diversity_rows = [{"year": str(y), "brands": n(div_brands.get(y, 0)), "models": n(div_models.get(y, 0))}
                      for y in years]

    # ---------------------------------------------------------- insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    def ins_ytd():
        if ytd_chg is None:
            return None
        period = f"{ytd_label} {last_year}" if partial_year else str(last_year)
        prev_p = f"התקופה המקבילה ב־{last_year - 1}" if partial_year else str(last_year - 1)
        if abs(ytd_chg) < FLAT_PCT:
            return (f"ב{period} עלו על הכביש {n(ytd_now)} כלי רכב חדשים, כמעט ללא שינוי לעומת "
                    f"{prev_p} ({n(ytd_prev)}).")
        word = "עלייה" if ytd_chg > 0 else "ירידה"
        return (f"ב{period} עלו על הכביש {n(ytd_now)} כלי רכב חדשים, {word} של {pct(abs(ytd_chg))} "
                f"לעומת {prev_p} ({n(ytd_prev)}).")

    def ins_record():
        if len(full_years) < 3:
            return None
        vals = [(int(yt.get(y, 0)), y) for y in full_years]
        best_v, best_y = max(vals, key=lambda t: (t[0], t[1]))
        latest_full = full_years[-1]
        if best_y == latest_full:
            prev_best = max((t for t in vals if t[1] != best_y), key=lambda t: (t[0], t[1]))
            return (f"{best_y} הייתה שנת השיא בנתונים: {n(best_v)} כלי רכב חדשים, יותר מכל שנה מלאה "
                    f"קודמת מאז {full_years[0]} (השיא הקודם: {n(prev_best[0])} ב־{prev_best[1]}).")
        low_v, low_y = min(vals, key=lambda t: (t[0], t[1]))
        return (f"שנת השיא בנתונים היא {best_y} עם {n(best_v)} כלי רכב חדשים; השנה החלשה ביותר "
                f"מבין השנים המלאות היא {low_y} ({n(low_v)}).")

    def ins_country():
        if last_year - base_year < 2:
            return None
        deltas = sorted(((cshare(last_year, c) - cshare(base_year, c), c) for c in countries_all),
                        key=lambda t: (-t[0], t[1]))
        if not deltas:
            return None
        gain, gc = deltas[0]
        loss, lc = min(deltas, key=lambda t: (t[0], t[1]))
        parts = []
        lbl = f"{last_year} (עד {MONTHS_HE[last_mon - 1]})" if partial_year else str(last_year)
        if gain >= SHIFT_PP:
            verb = "זינק" if gain >= SURGE_PP else "עלה"
            parts.append(f"חלקם של כלי הרכב מתוצרת {gc} {verb} מ־{pct(cshare(base_year, gc))} ב־{base_year} "
                         f"ל־{pct(cshare(last_year, gc))} ב־{lbl}")
        if -loss >= SHIFT_PP and lc != gc:
            parts.append(f"חלקה של {lc} ירד באותה תקופה מ־{pct(cshare(base_year, lc))} "
                         f"ל־{pct(cshare(last_year, lc))}")
        if not parts:
            return None
        return "; ".join(parts) + "."

    def ins_leader():
        if len(rb) < 2 or tot12 == 0:
            return None
        (b1, v1), (b2, v2) = rb[0], rb[1]
        if v1 <= v2:
            return None
        text = (f"{b1} הוא התוצר המוביל ב־12 החודשים האחרונים ({month_label(_shift(last_ym, 11))} עד "
                f"{month_label(last_ym)}): {n(v1)} כלי רכב, {pct(v1 / tot12 * 100)} מכלל הרכב החדש, "
                f"לפני {b2} ({n(v2)}).")
        if totp12:
            rp = _rank(bp12)
            if rp and rp[0][0] != b1:
                text += f" שנה קודם לכן הוביל {rp[0][0]}."
        return text

    def ins_grower():
        if not totp12:
            return None
        cands = []
        for b, v in rb:
            pv = int(bp12.get(b, 0))
            if v >= MIN_GROWER and pv > 0:
                cands.append(((v - pv), b, v, pv))
        if not cands:
            return None
        diff, b, v, pv = max(cands, key=lambda t: (t[0], t[1]))
        if diff <= 0:
            return None
        return (f"הצמיחה הגדולה ביותר במספרים מוחלטים: {b}, מ־{n(pv)} ל־{n(v)} כלי רכב חדשים "
                f"ב־12 החודשים האחרונים לעומת 12 החודשים שקדמו להם.")

    def ins_season():
        if season_idx is None:
            return None
        hi = max(season_idx, key=lambda m: (season_idx[m], -m))
        lo = min(season_idx, key=lambda m: (season_idx[m], m))
        if season_idx[hi] < 1.2 or season_idx[lo] > 0.8:
            return None
        return (f"עונתיות חדה: בממוצע על פני {len(full_years)} שנים מלאות, מספר כלי הרכב החדשים "
                f"ב{MONTHS_HE[hi - 1]} גבוה פי {LRI}{season_idx[hi]:.1f}{PDI} מחודש ממוצע באותה שנה, "
                f"וב{MONTHS_HE[lo - 1]} הוא רק {pct(season_idx[lo] * 100, 0)} מחודש ממוצע.")

    def ins_month():
        if prev_year_month_total in (None, 0):
            return None
        chg = (latest_month_total / prev_year_month_total - 1) * 100
        if abs(chg) < FLAT_PCT:
            return (f"ב{month_label(last_ym)} עלו על הכביש {n(latest_month_total)} כלי רכב חדשים, "
                    f"בדומה ל{month_label(prev_year_ym)} ({n(prev_year_month_total)}).")
        word = "יותר" if chg > 0 else "פחות"
        return (f"ב{month_label(last_ym)} עלו על הכביש {n(latest_month_total)} כלי רכב חדשים, "
                f"{pct(abs(chg))} {word} מאשר ב{month_label(prev_year_ym)} ({n(prev_year_month_total)}).")

    def ins_diversity():
        if len(full_years) < 2:
            return None
        y0, y1 = full_years[0], full_years[-1]
        b0, b1v = int(div_brands.get(y0, 0)), int(div_brands.get(y1, 0))
        if b0 == 0 or b1v < b0 * 1.5:
            return None
        return (f"השוק התפצל: ב־{y1} נרשמו כלי רכב חדשים של {n(b1v)} מותגים שונים, לעומת {n(b0)} "
                f"ב־{y0}.")

    def ins_model():
        if not top_m:
            return None
        b, k, v = top_m[0]
        return (f"הדגם הנפוץ ביותר ב־12 החודשים האחרונים (רכב פרטי ומסחרי) הוא {k} של {b}, "
                f"עם {n(v)} כלי רכב חדשים.")

    add("ytd", ins_ytd())
    add("country_shift", ins_country())
    add("leader", ins_leader())
    add("season", ins_season())
    add("record", ins_record())
    add("grower", ins_grower())
    add("month", ins_month())
    add("diversity", ins_diversity())
    add("model", ins_model())

    # ---------------------------------------------------------- KPIs
    china_ytd = cshare(last_year, "סין")
    kpis = {
        "latest_month": {"value": latest_month_total, "display": n(latest_month_total), "tone": "brand"},
        "ytd": {"value": ytd_now, "display": n(ytd_now), "tone": "brand"},
        "ytd_chg": {"value": round(ytd_chg, 1) if ytd_chg is not None else None,
                    "display": signed_pct_display(ytd_chg) if ytd_chg is not None else "אין נתון",
                    "tone": ("brand" if ytd_chg is None or abs(ytd_chg) < FLAT_PCT
                             else ("ok" if ytd_chg > 0 else "danger"))},
        "last_full": {"value": int(yt.get(full_years[-1], 0)) if full_years else 0,
                      "display": n(yt.get(full_years[-1], 0)) if full_years else "0", "tone": "brand"},
        "china": {"value": round(china_ytd, 1), "display": f"{china_ytd:.1f}%",
                  "tone": "info" if china_ytd >= 10 else "brand"},
        "brands12": {"value": int(len(rb)), "display": n(len(rb)), "tone": "brand"},
    }

    period_lbl = f"{ytd_label} {last_year}" if partial_year else str(last_year)
    labels = {
        "latest_month_kpi": f"כלי רכב חדשים ב{month_label(last_ym)}",
        "ytd_kpi": f"כלי רכב חדשים ב{period_lbl}",
        "ytd_chg_kpi": (f"שינוי לעומת {ytd_label} {last_year - 1}" if partial_year
                        else f"שינוי לעומת {last_year - 1}"),
        "last_full_kpi": (f"כלי רכב חדשים בשנת {full_years[-1]} (שנה מלאה אחרונה)" if full_years
                          else "שנה מלאה אחרונה"),
        "china_kpi": f"שיעור כלי הרכב מתוצרת סין ב{period_lbl}",
        "brands12_kpi": "מותגים שונים ב־12 החודשים האחרונים",
        "lede": (f"כמה כלי רכב חדשים, בעלי קוד דגם, עולים על הכביש בישראל בכל חודש: לפי סוג הרכב, התוצר, "
                 f"ארץ הייצור והדגם. הנתונים מכסים את {month_label(first_ym)} עד {month_label(last_ym)}, "
                 f"{n(total_all)} כלי רכב בסך הכול, ומתעדכנים מדי חודש.{partial_note}"),
        "monthly_note": (f"מספר כלי הרכב החדשים שעלו על הכביש בכל חודש, לפי סוג הרכב. "
                         f"בחודש האחרון ({month_label(last_ym)}): {n(latest_month_total)}. "
                         f"גררו את הפס התחתון כדי להתמקד בתקופה."),
        "monthly_aria": f"כלי רכב חדשים לפי חודש וסוג רכב, {month_label(first_ym)} עד {month_label(last_ym)}",
        "yearly_note": (f"סך כלי הרכב החדשים בכל שנה, ולצדו הסכום ב{ytd_label} בלבד כדי להשוות את השנה החלקית "
                        f"{last_year} לשנים קודמות באותם חודשים." if partial_year else
                        "סך כלי הרכב החדשים בכל שנה קלנדרית."),
        "yearly_aria": f"כלי רכב חדשים לפי שנה, {first_year} עד {last_year}",
        "ytd_col": ytd_label,
        "ytd_series": f"{ytd_label} בלבד",
        "season_note": ("כל משבצת היא חודש אחד; ככל שהצבע כהה יותר, עלו על הכביש יותר כלי רכב. "
                        "כך רואים את קפיצת תחילת השנה ואת השפל בסופה."),
        "season_aria": "מפת חום של כלי רכב חדשים לפי חודש ושנה",
        "types_note": "חלוקת כלי הרכב החדשים בכל שנה לפרטי, מסחרי ודו־גלגלי.",
        "types_aria": "כלי רכב חדשים לפי סוג רכב ושנה",
        "country_note": (f"חלקה של כל ארץ ייצור מכלל כלי הרכב החדשים בכל שנה ({TOP_COUNTRIES} הארצות המובילות "
                         f"ב־12 החודשים האחרונים, והשאר תחת \"אחר\"). ארץ הייצור נגזרת משם התוצר; "
                         f"ב־{last_year} לא זוהתה ארץ עבור {pct(unknown_share)} מכלי הרכב."),
        "country_aria": f"התפלגות כלי רכב חדשים לפי ארץ ייצור ושנה, {first_year} עד {last_year}",
        "country_cmp_note": f"אחוז מכלל כלי הרכב החדשים: {base_year} לעומת {last_year}"
                            + (f" (עד {MONTHS_HE[last_mon - 1]})." if partial_year else "."),
        "country_cmp_aria": f"השוואת חלקן של ארצות הייצור, {base_year} מול {last_year}",
        "brands_note": (f"{TOP_BRANDS} התוצרים (מותגים) עם הכי הרבה כלי רכב חדשים ב־12 החודשים האחרונים "
                        f"({month_label(_shift(last_ym, 11))} עד {month_label(last_ym)}), לצד 12 החודשים "
                        f"שקדמו להם. מותג אחד יכול לכלול כמה מפעלים בארצות שונות."),
        "brands_aria": f"{TOP_BRANDS} התוצרים המובילים ב־12 החודשים האחרונים",
        "brand_now": "12 החודשים האחרונים",
        "brand_prev": "12 החודשים שקדמו להם",
        "brand_lines_note": f"חלקם של {BRAND_LINES} התוצרים המובילים כיום מכלל כלי הרכב החדשים, לאורך השנים.",
        "brand_lines_aria": "נתח שוק שנתי של התוצרים המובילים",
        "models_note": (f"{TOP_MODELS} הדגמים (לפי כינוי מסחרי) עם הכי הרבה כלי רכב חדשים ב־12 החודשים האחרונים, "
                        f"רכב פרטי ומסחרי בלבד: לכלי רכב דו־גלגליים אין כינוי מסחרי במאגר."),
        "models_aria": f"{TOP_MODELS} הדגמים הנפוצים ב־12 החודשים האחרונים",
        "two_note": (f"כלי רכב דו־גלגליים חדשים ב־12 החודשים האחרונים: {n(two_total)} בסך הכול. "
                     f"{TOP_TWO} התוצרים המובילים."),
        "two_aria": f"{TOP_TWO} תוצרי הרכב הדו־גלגלי המובילים ב־12 החודשים האחרונים",
        "diversity_note": "כמה מותגים וכמה קודי דגם שונים קיבלו כלי רכב חדשים בכל שנה.",
        "diversity_aria": "מספר מותגים וקודי דגם שונים לפי שנה",
    }

    summary = (f"כמה כלי רכב חדשים עלו על הכביש בכל חודש, לפי תוצר, דגם וארץ ייצור. "
               f"ב{period_lbl}: {n(ytd_now)} כלי רכב")
    if ytd_chg is not None:
        summary += f", {'עלייה' if ytd_chg >= 0 else 'ירידה'} של {abs(ytd_chg):.1f}% לעומת אשתקד."
    else:
        summary += "."
    tags = ["רכב חדש", "מכירות רכב", "תחבורה", "יבוא רכב", "דגמי רכב"]

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": tags,
            "related_ids": [
                "af997a02-64e6-4c75-a029-3553f14a9ab1",
                "45e317cf-7bb1-4535-b8cf-be5e79ea341f",
                "9db8e799-d2db-4136-bb9c-df255740c810",
                "b37b28ae-d465-482b-b47e-7cc844f45adb",
                "273c5e33-25ab-4980-8522-a2f7ba0bb62d",
            ],
            "temporal_coverage": f"{first_year}/{last_year}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "monthly": monthly,
            "yearly": yearly,
            "heat": heat,
            "types": types_year,
            "country_share": country_share,
            "country_cmp": country_cmp,
            "brands": brands,
            "brand_lines": brand_lines,
            "models": models,
            "two": two,
            "diversity": diversity,
        },
        "tables": {
            "yearly": yearly_rows,
            "types": types_rows,
            "type_headers": type_headers,
            "countries": country_rows,
            "brands": brand_rows,
            "models": model_rows,
            "two": two_rows,
            "diversity": diversity_rows,
        },
        "flags": {"partial_year": partial_year, "two": two is not None,
                  "brand_prev": totp12 > 0},
        "labels": labels,
        "insights": insights,
    }
