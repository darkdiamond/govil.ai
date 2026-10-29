"""עולים חדשים לפי שנים: one row per new immigrant (oleh), Ministry of Aliyah
and Integration, one CSV per year of aliyah (2015 onward).

Each row: year + month of aliyah, age at aliyah, age at the file's export
date (skipped: its meaning shifts with every export), gender, country of
origin, sub-continent, settlement (yeshuv) and district of first residence,
declared occupation.

How the files relate: one file per calendar year, identical layout. Ten of
the files use English column names; the 2024 file uses Hebrew ones (and its
"age today" column is named after an export date). The recipe therefore has
two `by_schema` + `concat` inputs, `main` (English headers) and `heb`
(Hebrew headers), both renamed onto one frame here, so a new yearly file in
either layout flows in with no edit.

If a year ever arrives in two files (a re-upload under the other layout),
only the file with the most rows for that year is kept (disclosed on the
page), so a year is never double counted.

"Now" is the latest year in the data. The latest year is partial when its
last month of aliyah is before December: it is labelled, excluded from the
full-year trend rule, and compared with the same months of the previous
year instead.

Districts: the ministry's district names changed over time (e.g. one name
up to one year and another from the next). The district chart shows the
names as they appear and a computed note lists names that stop or start
mid-series.

People: no names or identifiers exist in the data; everything aggregates.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
             "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MINUS = "−"

HEB_RENAME = {
    "שנת עלייה": "year_aliya", "חודש עלייה": "month_aliya",
    "גיל ביום העלייה": "age", "מגדר": "gender", "ארץ מוצא": "erez_moza",
    "תת יבשת": "subcont", "ישוב": "yeshuv_klita", "מחוז": "machoz",
    "מקצוע": "mikzoa",
}
COLS = list(HEB_RENAME.values())
RES = "_resource_name"

MALE, FEMALE = "זכר", "נקבה"
UNKNOWN = "לא צוין"

# Occupation field: map the non-occupational codes to groups; everything
# else (any new value included) counts as a declared occupation.
OCC_GROUP = {
    "": UNKNOWN, "לא צויין": UNKNOWN, "לא צוין": UNKNOWN, "מקצוע לא מוגדר": UNKNOWN,
    'תלמיד בי"ס יסודי ותכון': "תלמידים", "תלמיד ישיבה": "תלמידים",
    "סטודנט": "סטודנטים",
    "פנסיונר / רנטייר": "פנסיונרים",
    "עקרת בית": "עקרות בית",
}
G_PROF = "בעלי מקצוע מוצהר"
OCC_ORDER = [G_PROF, "תלמידים", "סטודנטים", "פנסיונרים", "עקרות בית", UNKNOWN]

TOP_REGIONS = 6
TOP_COUNTRIES_LINES = 6
TOP_COUNTRIES_BAR = 15
TOP_AGE_COUNTRIES = 12
AGE_COUNTRY_MIN = 500
TOP_CITIES = 15
TOP_PROFS = 15
TOP_DISTRICTS = 6
AGE_BIN = 5
CHILD_AGE = 18
OLD_AGE = 65
AGE_TOP = 85
TREND_FLAT = 0.03
PEAK_RATIO = 1.3
SEASON_MIN_SHARE = 0.095
LEADER_MIN_SHARE = 0.25


def _int(n):
    return f"{int(round(n)):,}"


def _pct(x, digits=1):
    return f"{x * 100:.{digits}f}%"


def _signed_pct(x):
    s = f"{abs(x) * 100:.1f}%"
    return ("+" if x > 0 else MINUS if x < 0 else "") + s


def _rank(counts):
    """Series name->count sorted by count desc, then name asc (total order)."""
    s = counts[counts > 0]
    df = pd.DataFrame({"k": s.index.astype(str), "v": s.values})
    df = df.sort_values(["v", "k"], ascending=[False, True], kind="mergesort")
    return list(zip(df["k"], df["v"].astype(int)))


def _prepare(frames):
    parts = []
    main = frames.get("main")
    if main is not None and len(main):
        parts.append(main[COLS + [RES]].copy())
    heb = frames.get("heb")
    if heb is not None and len(heb):
        parts.append(heb.rename(columns=HEB_RENAME)[COLS + [RES]].copy())
    df = pd.concat(parts, ignore_index=True)
    for c in COLS + [RES]:
        df[c] = df[c].astype(str).str.strip()
    df["year"] = pd.to_numeric(df["year_aliya"], errors="coerce")
    df["month"] = pd.to_numeric(df["month_aliya"], errors="coerce")
    df["age_n"] = pd.to_numeric(df["age"], errors="coerce")
    n_raw = len(df)
    df = df[df["year"].notna() & df["month"].between(1, 12)].copy()
    df["year"] = df["year"].astype(int)
    df["month"] = df["month"].astype(int)
    bad_rows = n_raw - len(df)

    # One file per year: if a year shows up in several files, keep the file
    # with the most rows for it (tie: resource name), drop the rest.
    g = df.groupby(["year", RES]).size().reset_index(name="n")
    g = g.sort_values(["year", "n", RES], ascending=[True, False, True], kind="mergesort")
    keep = g.drop_duplicates("year", keep="first")[["year", RES]]
    before = len(df)
    df = df.merge(keep, on=["year", RES], how="inner")
    dup_rows = before - len(df)
    df.loc[df["age_n"] < 0, "age_n"] = float("nan")
    df.loc[df["age_n"] > 120, "age_n"] = float("nan")
    return df, bad_rows, dup_rows


def _age_bin(a):
    if a >= AGE_TOP:
        return f"{AGE_TOP}+"
    lo = int(a // AGE_BIN) * AGE_BIN
    return f"{lo}-{lo + AGE_BIN - 1}"


def compute(frames):
    df, bad_rows, dup_rows = _prepare(frames)
    total = len(df)
    years = sorted(df["year"].unique().tolist())
    y_first, y_last = years[0], years[-1]
    by_year = df.groupby("year").size().reindex(years).astype(int)
    missing_years = [y for y in range(y_first, y_last + 1) if y not in set(years)]

    last_month = int(df.loc[df["year"] == y_last, "month"].max())
    partial = last_month < 12
    full_years = [y for y in years if not (partial and y == y_last)]

    labels = {}
    insights = []

    # ── yearly ──────────────────────────────────────────────────────────
    labels["years_range"] = f"{y_first}-{y_last}" if y_first != y_last else str(y_first)
    yearly = {"x": [str(y) for y in years], "y": [int(by_year[y]) for y in years],
              "partial": str(y_last) if partial else None,
              "yoy": [("" if i == 0 or years[i] - years[i - 1] != 1 or not by_year[years[i - 1]]
                       or (partial and y == y_last)
                       else _signed_pct((by_year[y] - by_year[years[i - 1]]) / by_year[years[i - 1]]))
                      for i, y in enumerate(years)]}
    peak_year = max(full_years or years, key=lambda y: (by_year[y], -y))
    notes = []
    if partial:
        notes.append(f"השנה {y_last} חלקית: הנתונים בה מגיעים עד {MONTHS_HE[last_month - 1]} ומוצגים בגוון בהיר.")
    if missing_years:
        notes.append("אין קובץ נתונים לשנים: " + ", ".join(str(y) for y in missing_years) + ".")
    if dup_rows:
        notes.append(f"{_int(dup_rows)} רשומות של שנה שהופיעה ביותר מקובץ אחד לא נספרו פעמיים.")
    if bad_rows:
        notes.append(f"{_int(bad_rows)} רשומות ללא שנה או חודש תקינים אינן נכללות.")
    labels["yearly_note"] = (
        f"מספר העולים בכל שנה, {labels['years_range']}. שנת השיא: {peak_year} עם {_int(by_year[peak_year])} עולים. "
        + " ".join(notes)).strip()
    labels["yearly_aria"] = (f"גרף עמודות: עולים חדשים לפי שנת עלייה {labels['years_range']}. "
                             f"שיא ב-{peak_year} עם {_int(by_year[peak_year])} עולים.")

    # ── month × year heatmap ───────────────────────────────────────────
    my = df.groupby(["year", "month"]).size()
    cells = []
    for yi, y in enumerate(years):
        for m in range(1, 13):
            if y == y_last and m > last_month:
                continue
            cells.append([m - 1, yi, int(my.get((y, m), 0))])
    heat = {"x": MONTHS_HE, "y": [str(y) for y in years], "cells": cells,
            "max": int(max(c[2] for c in cells)) if cells else 0}
    full_df = df[df["year"].isin(full_years)]
    by_month = full_df.groupby("month").size().reindex(range(1, 13), fill_value=0)
    m_peak = int(by_month.idxmax()) if by_month.sum() else 1
    m_low = int(by_month.idxmin()) if by_month.sum() else 1
    month_share = by_month / by_month.sum() if by_month.sum() else by_month
    peak_cell = max(cells, key=lambda c: (c[2], -c[1], -c[0])) if cells else [0, 0, 0]
    labels["heat_note"] = (
        f"עולים לפי חודש ושנה. החודש הבולט בשנים המלאות הוא {MONTHS_HE[m_peak - 1]} "
        f"({_pct(month_share[m_peak])} מהעולים), והשקט ביותר {MONTHS_HE[m_low - 1]} ({_pct(month_share[m_low])}). "
        f"החודש העמוס ביותר בכל התקופה: {MONTHS_HE[peak_cell[0]]} {years[peak_cell[1]]} עם {_int(peak_cell[2])} עולים.")
    labels["heat_aria"] = (f"מפת חום: עולים לפי חודש ושנה. השיא ב{MONTHS_HE[peak_cell[0]]} "
                           f"{years[peak_cell[1]]} עם {_int(peak_cell[2])} עולים.")

    # ── regions (sub-continent) mix per year ───────────────────────────
    reg_total = _rank(df.loc[df["subcont"] != "", "subcont"].value_counts())
    top_regs = [k for k, _ in reg_total[:TOP_REGIONS]]
    df["reg"] = df["subcont"].where(df["subcont"].isin(top_regs), "אחר")
    reg_order = top_regs + (["אחר"] if (df["reg"] == "אחר").any() else [])
    ry = df.groupby(["year", "reg"]).size().unstack(fill_value=0).reindex(index=years, columns=reg_order, fill_value=0)
    ry_share = ry.div(ry.sum(axis=1), axis=0).fillna(0)
    regions = {"x": [str(y) for y in years],
               "series": [{"name": r, "data": [round(float(ry_share.loc[y, r]) * 100, 1) for y in years],
                           "counts": [int(ry.loc[y, r]) for y in years]} for r in reg_order]}
    reg_rows = []
    for r in reg_order:
        reg_rows.append({"name": r, "total": int(ry[r].sum()),
                         "first": round(float(ry_share.loc[y_first, r]) * 100, 1),
                         "last": round(float(ry_share.loc[y_last, r]) * 100, 1)})
    lead_reg = reg_order[0]
    labels["first_year"], labels["last_year"] = str(y_first), str(y_last)
    labels["regions_note"] = (
        f"התפלגות העולים לפי אזור מוצא בכל שנה (אחוזים). {lead_reg} היא אזור המוצא הגדול בכל התקופה, "
        f"{_pct(ry[lead_reg].sum() / total)} מהעולים; ב-{y_last} חלקה {_pct(ry_share.loc[y_last, lead_reg])}. "
        + (f"אזורים קטנים מאוחדים תחת \"אחר\"." if "אחר" in reg_order else ""))
    labels["regions_aria"] = (f"גרף עמודות מוערמות: הרכב העולים לפי אזור מוצא בכל שנה. "
                              f"{lead_reg} מובילה עם {_pct(ry[lead_reg].sum() / total)} מהעולים.")

    # ── countries ──────────────────────────────────────────────────────
    ctry_rank = _rank(df.loc[df["erez_moza"] != "", "erez_moza"].value_counts())
    n_countries = len(ctry_rank)
    last_ctry = df.loc[df["year"] == y_last, "erez_moza"].value_counts()
    top_c = ctry_rank[:TOP_COUNTRIES_BAR]
    countries_bar = {"names": [k for k, _ in top_c], "values": [int(v) for _, v in top_c],
                     "shares": [round(v / total * 100, 1) for _, v in top_c],
                     "last": [int(last_ctry.get(k, 0)) for k, _ in top_c]}
    labels["countries_note"] = (
        f"ארצות המוצא הגדולות בכל התקופה, מתוך {_int(n_countries)} ארצות. "
        f"{top_c[0][0]} לבדה: {_int(top_c[0][1])} עולים ({_pct(top_c[0][1] / total)}). "
        f"חמש הארצות הראשונות: {_pct(sum(v for _, v in ctry_rank[:5]) / total)} מכלל העולים.")
    labels["countries_aria"] = (f"גרף עמודות אופקי: {len(top_c)} ארצות המוצא המובילות. "
                                f"{top_c[0][0]} ראשונה עם {_int(top_c[0][1])} עולים.")
    line_c = [k for k, _ in ctry_rank[:TOP_COUNTRIES_LINES]]
    cy = df[df["erez_moza"].isin(line_c)].groupby(["year", "erez_moza"]).size().unstack(fill_value=0) \
        .reindex(index=years, columns=line_c, fill_value=0)
    countries_years = {"x": [str(y) for y in years],
                       "series": [{"name": c, "data": [int(cy.loc[y, c]) for y in years]} for c in line_c],
                       "partial": yearly["partial"]}
    # each line country's own peak year
    peaks = []
    for c in line_c:
        fy = [y for y in full_years] or years
        py = max(fy, key=lambda y: (cy.loc[y, c], -y))
        peaks.append((c, py, int(cy.loc[py, c])))
    labels["cyears_note"] = (
        f"מספר העולים בכל שנה מ-{len(line_c)} ארצות המוצא הגדולות. "
        + " ".join(f"{c}: שיא ב-{py} ({_int(v)})." for c, py, v in peaks[:3]))
    labels["cyears_aria"] = (f"גרף קווים: עולים לפי שנה מ-{len(line_c)} ארצות המוצא המובילות, {labels['years_range']}.")
    countries_years["table"] = [{"year": str(y), "vals": [int(cy.loc[y, c]) for c in line_c]} for y in years]

    # ── age pyramid ────────────────────────────────────────────────────
    ag = df[df["age_n"].notna()].copy()
    ag["bin"] = ag["age_n"].map(_age_bin)
    bins = [f"{lo}-{lo + AGE_BIN - 1}" for lo in range(0, AGE_TOP, AGE_BIN)] + [f"{AGE_TOP}+"]
    pg = ag.groupby(["bin", "gender"]).size().unstack(fill_value=0)
    male = [int(pg.loc[b, MALE]) if (b in pg.index and MALE in pg.columns) else 0 for b in bins]
    female = [int(pg.loc[b, FEMALE]) if (b in pg.index and FEMALE in pg.columns) else 0 for b in bins]
    pyramid = {"bins": bins, "male": male, "female": female}
    med_age = float(ag["age_n"].median())
    big_bin = bins[max(range(len(bins)), key=lambda i: (male[i] + female[i], -i))]
    u18 = float((ag["age_n"] < CHILD_AGE).mean())
    o65 = float((ag["age_n"] >= OLD_AGE).mean())
    labels["pyramid_note"] = (
        f"גיל ביום העלייה לפי מגדר. גיל חציוני: {med_age:.0f}. קבוצת הגיל הגדולה: {big_bin} "
        f"({_int(male[bins.index(big_bin)] + female[bins.index(big_bin)])} עולים). "
        f"{_pct(u18)} עלו לפני גיל {CHILD_AGE} ו-{_pct(o65)} בגיל {OLD_AGE} ומעלה.")
    labels["pyramid_aria"] = (f"פירמידת גילים: עולים לפי קבוצת גיל ומגדר. גיל חציוני {med_age:.0f}, "
                              f"קבוצת הגיל הגדולה {big_bin}.")

    # ── age / gender profile per year ──────────────────────────────────
    gy = df.groupby("year")
    women = df[df["gender"].isin([MALE, FEMALE])].groupby("year")["gender"].apply(lambda s: float((s == FEMALE).mean()))
    med_y = ag.groupby("year")["age_n"].median()
    u18_y = ag.groupby("year")["age_n"].apply(lambda s: float((s < CHILD_AGE).mean()))
    o65_y = ag.groupby("year")["age_n"].apply(lambda s: float((s >= OLD_AGE).mean()))
    profile = {"x": [str(y) for y in years],
               "median": [round(float(med_y.get(y, float("nan"))), 1) for y in years],
               "u18": [round(float(u18_y.get(y, 0)) * 100, 1) for y in years],
               "o65": [round(float(o65_y.get(y, 0)) * 100, 1) for y in years],
               "women": [round(float(women.get(y, 0)) * 100, 1) for y in years]}
    del gy
    my_lo = min(years, key=lambda y: (med_y.get(y, 999), y))
    my_hi = max(years, key=lambda y: (med_y.get(y, -1), -y))
    labels["u18_label"] = f"עד גיל {CHILD_AGE - 1}"
    labels["o65_label"] = f"בני {OLD_AGE} ומעלה"
    labels["profile_note"] = (
        f"גיל חציוני ביום העלייה (קו עבה, ציר ימני) ושיעור הילדים, בני {OLD_AGE} ומעלה והנשים בכל שנה. "
        f"הגיל החציוני נע בין {med_y[my_lo]:.0f} ({my_lo}) ל-{med_y[my_hi]:.0f} ({my_hi}).")
    labels["profile_aria"] = (f"גרף קווים: גיל חציוני ושיעורי ילדים, מבוגרים ונשים בקרב העולים לפי שנה, "
                              f"{labels['years_range']}.")

    # ── median age by country ──────────────────────────────────────────
    ac = ag[ag["erez_moza"] != ""].groupby("erez_moza")["age_n"].agg(["median", "size"])
    ac = ac[ac["size"] >= AGE_COUNTRY_MIN]
    sel = [k for k, _ in ctry_rank if k in ac.index][:TOP_AGE_COUNTRIES]
    acs = ac.loc[sel].reset_index().rename(columns={"erez_moza": "k"})
    acs = acs.sort_values(["median", "size", "k"], ascending=[True, False, True], kind="mergesort")
    age_country = {"names": acs["k"].tolist(), "median": [round(float(v), 1) for v in acs["median"]],
                   "n": [int(v) for v in acs["size"]]}
    if len(acs):
        yc, oc = acs.iloc[0], _oldest(acs)
        labels["agec_note"] = (
            f"גיל חציוני ביום העלייה ב-{len(acs)} ארצות המוצא הגדולות (עם {_int(AGE_COUNTRY_MIN)} עולים לפחות). "
            f"הצעירים ביותר: עולי {yc['k']} (חציון {yc['median']:.0f}); המבוגרים ביותר: עולי {oc['k']} (חציון {oc['median']:.0f}).")
        labels["agec_aria"] = (f"גרף עמודות אופקי: גיל חציוני לפי ארץ מוצא. מ-{yc['median']:.0f} ({yc['k']}) "
                               f"עד {oc['median']:.0f} ({oc['k']}).")
    else:
        labels["agec_note"] = labels["agec_aria"] = "גיל חציוני לפי ארץ מוצא."

    # ── districts per year ─────────────────────────────────────────────
    dmask = df["machoz"] != ""
    d_rank = _rank(df.loc[dmask, "machoz"].value_counts())
    d_names = [k for k, _ in d_rank[:TOP_DISTRICTS]]
    df["dist"] = df["machoz"].where(df["machoz"].isin(d_names), "")
    df.loc[dmask & (df["dist"] == ""), "dist"] = "אחר"
    df.loc[~dmask, "dist"] = UNKNOWN
    d_order = d_names + [x for x in ["אחר", UNKNOWN] if (df["dist"] == x).any()]
    dy = df.groupby(["year", "dist"]).size().unstack(fill_value=0).reindex(index=years, columns=d_order, fill_value=0)
    districts = {"x": [str(y) for y in years],
                 "series": [{"name": d, "data": [int(dy.loc[y, d]) for y in years]} for d in d_order],
                 "table": [{"year": str(y), "vals": [int(dy.loc[y, d]) for d in d_order]} for y in years]}
    # names that stop or start mid-series (renamed districts)
    breaks = []
    for d in d_names:
        ys = [y for y in years if dy.loc[y, d] > 0]
        if not ys or len(years) < 3:
            continue
        if ys[-1] < y_last:
            breaks.append(f"\"{d}\" מופיע עד {ys[-1]}")
        elif ys[0] > y_first:
            breaks.append(f"\"{d}\" מופיע החל מ-{ys[0]}")
    top_d = d_rank[0]
    d_tot = sum(v for _, v in d_rank)
    labels["districts_note"] = (
        f"עולים לפי מחוז הקליטה של משרד העלייה והקליטה בכל שנה. {top_d[0]} קלט {_pct(top_d[1] / d_tot)} מהעולים בתקופה. "
        + (("חלק משמות המחוזות מופיעים רק בחלק מהשנים: " + "; ".join(breaks) + ". לכן ההשוואה בין השנים לפי מחוז אינה רציפה.")
           if breaks else ""))
    labels["districts_aria"] = (f"גרף עמודות מוערמות: עולים לפי מחוז קליטה ושנה. {top_d[0]} הגדול ביותר.")

    # ── cities ─────────────────────────────────────────────────────────
    city_rank = _rank(df.loc[df["yeshuv_klita"] != "", "yeshuv_klita"].value_counts())
    n_cities = len(city_rank)
    last_city = df.loc[df["year"] == y_last, "yeshuv_klita"].value_counts()
    top_ct = city_rank[:TOP_CITIES]
    cities = {"names": [k for k, _ in top_ct], "values": [int(v) for _, v in top_ct],
              "shares": [round(v / total * 100, 1) for _, v in top_ct],
              "last": [int(last_city.get(k, 0)) for k, _ in top_ct]}
    last_city_rank = _rank(last_city[last_city.index != ""])
    labels["cities_note"] = (
        f"היישובים שקלטו הכי הרבה עולים בכל התקופה, מתוך {_int(n_cities)} יישובים. "
        f"{_pct(sum(v for _, v in top_ct) / total)} מהעולים התיישבו ב-{len(top_ct)} היישובים האלה"
        + (f"; ב-{y_last} הוביל היישוב {last_city_rank[0][0]} עם {_int(last_city_rank[0][1])} עולים." if last_city_rank else "."))
    labels["cities_aria"] = (f"גרף עמודות אופקי: {len(top_ct)} היישובים הקולטים המובילים. "
                             f"{top_ct[0][0]} ראשון עם {_int(top_ct[0][1])} עולים.")

    # ── occupation ─────────────────────────────────────────────────────
    df["occ"] = df["mikzoa"].map(OCC_GROUP).fillna(G_PROF)
    og = df["occ"].value_counts()
    occ = [{"name": g, "value": int(og.get(g, 0)), "share": round(og.get(g, 0) / total * 100, 1)}
           for g in OCC_ORDER if og.get(g, 0) > 0]
    prof = df[df["occ"] == G_PROF]
    n_prof = len(prof)
    prof_rank = _rank(prof["mikzoa"].value_counts())
    top_p = prof_rank[:TOP_PROFS]
    professions = {"names": [k for k, _ in top_p], "values": [int(v) for _, v in top_p],
                   "shares": [round(v / n_prof * 100, 1) if n_prof else 0 for _, v in top_p]}
    labels["occ_note"] = (
        f"העיסוק שהוצהר בעת העלייה. {_pct(og.get(G_PROF, 0) / total)} מהעולים ציינו מקצוע; "
        f"השאר תלמידים, סטודנטים, פנסיונרים, עקרות בית או ללא פירוט.")
    labels["occ_aria"] = f"תרשים טבעת: עולים לפי סוג העיסוק בעת העלייה. {_pct(og.get(G_PROF, 0) / total)} עם מקצוע מוצהר."
    if top_p:
        labels["prof_note"] = (
            f"המקצועות הנפוצים בקרב {_int(n_prof)} העולים שציינו מקצוע (תלמידים, סטודנטים, פנסיונרים, עקרות בית ו\"לא צוין\" אינם נכללים). "
            f"{top_p[0][0]} בראש עם {_int(top_p[0][1])} עולים.")
        labels["prof_aria"] = f"גרף עמודות אופקי: {len(top_p)} המקצועות הנפוצים בקרב העולים. {top_p[0][0]} ראשון."
    else:
        labels["prof_note"] = labels["prof_aria"] = "המקצועות הנפוצים בקרב העולים."

    # ── KPIs ───────────────────────────────────────────────────────────
    kpis = {}
    kpis["total"] = {"value": total, "display": _int(total), "tone": "brand"}
    labels["total_kpi"] = f"עולים חדשים, {labels['years_range']}"
    kpis["last"] = {"value": int(by_year[y_last]), "display": _int(by_year[y_last]),
                    "tone": "warn" if partial else "brand"}
    labels["last_kpi"] = (f"עולים ב-{y_last} (עד {MONTHS_HE[last_month - 1]}, שנה חלקית)" if partial
                          else f"עולים ב-{y_last}")
    # change: full year vs previous, or same months vs previous year when partial
    chg = None
    if partial and len(years) >= 2:
        prev = years[-2]
        a = int(((df["year"] == y_last) & (df["month"] <= last_month)).sum())
        b = int(((df["year"] == prev) & (df["month"] <= last_month)).sum())
        if b:
            chg = ((a - b) / b, y_last, prev, a, b, True)
    elif len(full_years) >= 2:
        y1, y0 = full_years[-1], full_years[-2]
        a, b = int(by_year[y1]), int(by_year[y0])
        if b:
            chg = ((a - b) / b, y1, y0, a, b, False)
    if chg:
        r = chg[0]
        tone = "info" if abs(r) < TREND_FLAT else ("ok" if r > 0 else "danger")
        kpis["change"] = {"value": round(r, 4), "display": _signed_pct(r), "tone": tone}
        labels["change_kpi"] = (f"שינוי לעומת {chg[2]} (אותם חודשים)" if chg[5] else f"שינוי ב-{chg[1]} לעומת {chg[2]}")
    kpis["peak"] = {"value": int(by_year[peak_year]), "display": _int(by_year[peak_year]), "tone": "info"}
    labels["peak_kpi"] = f"עולים בשנת השיא ({peak_year})"
    fw = float((df["gender"] == FEMALE).sum() / max(1, df["gender"].isin([MALE, FEMALE]).sum()))
    kpis["women"] = {"value": round(fw, 4), "display": _pct(fw), "tone": "brand"}
    kpis["median_age"] = {"value": med_age, "display": f"{med_age:.0f}", "tone": "brand"}
    kpis["countries"] = {"value": n_countries, "display": _int(n_countries), "tone": "brand"}
    kpis["cities"] = {"value": n_cities, "display": _int(n_cities), "tone": "brand"}

    # ── insights ───────────────────────────────────────────────────────
    def add(i, t):
        if t:
            insights.append({"id": i, "text_he": t})

    def ins_trend():
        if not chg:
            return None
        r, y1, y0, a, b, part = chg
        scope = f"בחודשים ינואר עד {MONTHS_HE[last_month - 1]} {y1}" if part else f"ב-{y1}"
        base = f"באותם חודשים ב-{y0}" if part else f"ב-{y0}"
        if abs(r) < TREND_FLAT:
            return f"{scope} עלו {_int(a)} עולים, כמעט ללא שינוי לעומת {_int(b)} {base}."
        word = "עלייה" if r > 0 else "ירידה"
        return f"{scope} עלו לישראל {_int(a)} עולים, {word} של {abs(r) * 100:.1f}% לעומת {_int(b)} {base}."

    def ins_peak():
        others = [by_year[y] for y in full_years if y != peak_year]
        if len(others) < 2:
            return None
        avg = sum(others) / len(others)
        if by_year[peak_year] < PEAK_RATIO * avg:
            return None
        pk = df[df["year"] == peak_year]["erez_moza"].value_counts()
        pk_rank = _rank(pk[pk.index != ""])
        lead = f" {_pct(pk_rank[0][1] / by_year[peak_year])} מהם מ{pk_rank[0][0]}." if pk_rank else ""
        return (f"שנת השיא היא {peak_year} עם {_int(by_year[peak_year])} עולים, פי {by_year[peak_year] / avg:.1f} "
                f"מהממוצע בשאר השנים המלאות ({_int(avg)}).{lead}")

    def ins_leader():
        k, v = ctry_rank[0]
        sh = v / total
        if sh < LEADER_MIN_SHARE:
            return None
        lr = _rank(last_ctry[last_ctry.index != ""])
        tail = ""
        if lr:
            lk, lv = lr[0]
            part = by_year[y_last]
            if lk == k:
                tail = f" גם ב-{y_last} היא מובילה, עם {_pct(lv / part)} מהעולים."
            else:
                tail = f" ב-{y_last} הובילה דווקא {lk}, עם {_pct(lv / part)} מהעולים."
        return f"{k} היא ארץ המוצא העיקרית: {_int(v)} עולים, {_pct(sh)} מכלל העולים ב-{labels['years_range']}.{tail}"

    def ins_region_shift():
        if len(years) < 3 or y_last == peak_year:
            return None
        west = [r for r in reg_order if r != lead_reg and r != "אחר"][:2]
        if not west:
            return None
        sp = sum(ry_share.loc[peak_year, r] for r in west)
        sl = sum(ry_share.loc[y_last, r] for r in west)
        if abs(sl - sp) < 0.05:
            return None
        word = "עלה" if sl > sp else "ירד"
        return (f"חלקם של עולי {' ו'.join(west)} {word} מ-{_pct(sp)} ב-{peak_year} ל-{_pct(sl)} ב-{y_last}, "
                f"בעוד חלקה של {lead_reg} עבר מ-{_pct(ry_share.loc[peak_year, lead_reg])} ל-{_pct(ry_share.loc[y_last, lead_reg])}.")

    def ins_season():
        if len(full_years) < 3 or month_share[m_peak] < SEASON_MIN_SHARE:
            return None
        return (f"בשנים המלאות {MONTHS_HE[m_peak - 1]} הוא חודש העלייה העמוס ביותר ({_pct(month_share[m_peak])} מהעולים), "
                f"לעומת {_pct(month_share[m_low])} ב{MONTHS_HE[m_low - 1]}, החודש השקט ביותר.")

    def ins_age():
        if len(acs) < 2:
            return None
        yc, oc = acs.iloc[0], _oldest(acs)
        if oc["median"] - yc["median"] < 5:
            return None
        return (f"הגיל החציוני ביום העלייה הוא {med_age:.0f}, אך הוא שונה מאוד בין ארצות המוצא: "
                f"{yc['median']:.0f} בקרב עולי {yc['k']} לעומת {oc['median']:.0f} בקרב עולי {oc['k']}.")

    def ins_cities():
        if len(city_rank) < 5:
            return None
        k, v = city_rank[0]
        s5 = sum(x for _, x in city_rank[:5]) / total
        return (f"{k} קלטה את מספר העולים הגדול ביותר ({_int(v)}, {_pct(v / total)}); "
                f"חמשת היישובים המובילים קלטו יחד {_pct(s5)} מהעולים.")

    def ins_women():
        if abs(fw - 0.5) < 0.01:
            return None
        share = fw if fw > 0.5 else 1 - fw
        old = _old_share(ag, fw > 0.5)
        if old >= share + 0.02:
            tail = f" בקרב בני {OLD_AGE} ומעלה חלקן גבוה יותר: {_pct(old)}."
        elif old <= share - 0.02:
            tail = f" בקרב בני {OLD_AGE} ומעלה חלקן נמוך יותר: {_pct(old)}."
        else:
            tail = ""
        if fw > 0.5:
            return f"נשים הן הרוב בקרב העולים: {_pct(share)}.{tail}"
        return f"גברים הם הרוב בקרב העולים: {_pct(share)}.{tail.replace('חלקן', 'חלקם')}"

    add("trend", ins_trend())
    add("peak", ins_peak())
    add("leader", ins_leader())
    add("region_shift", ins_region_shift())
    add("season", ins_season())
    add("age", ins_age())
    add("cities", ins_cities())
    add("women", ins_women())

    # ── summary / agent_data ───────────────────────────────────────────
    summary = (f"עולים חדשים לפי שנה, ארץ מוצא, גיל, מגדר ויישוב קליטה, {labels['years_range']}: "
               f"{_int(total)} עולים, שיא ב-{peak_year} ({_int(by_year[peak_year])}).")
    labels["lede"] = (
        f"נתוני משרד העלייה והקליטה על {_int(total)} עולים חדשים שעלו לישראל בשנים {labels['years_range']}, "
        f"רשומה לכל עולה: שנה וחודש עלייה, גיל ביום העלייה, מגדר, ארץ מוצא, יישוב ומחוז קליטה ומקצוע. "
        f"העולים הגיעו מ-{_int(n_countries)} ארצות והתיישבו ב-{_int(n_cities)} יישובים; שנת השיא היא {peak_year}."
        + (f" נתוני {y_last} חלקיים (עד {MONTHS_HE[last_month - 1]})." if partial else ""))

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["עלייה", "עולים חדשים", "קליטת עלייה", "הגירה", "דמוגרפיה"],
            "related_ids": [
                "ee6fa2f7-e5c7-4268-9e8a-d23294ddacfe",
                "56da3e15-0111-489e-bad8-f506b121edc7",
                "a7dd6566-0fe5-4cb4-a1db-39043acb4bdc",
                "46242de8-ded9-4b01-ad73-551abae4491d",
                "26526e96-3268-4084-833a-80ec4a34f3d7",
            ],
            "temporal_coverage": f"{y_first}/{y_last}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": {
            "yearly": yearly, "heat": heat, "regions": regions, "countries": countries_bar,
            "cyears": countries_years, "pyramid": pyramid, "profile": profile,
            "agec": age_country, "districts": districts, "cities": cities,
            "occ": occ, "prof": professions,
        },
        "tables": {"regions": reg_rows},
        "insights": insights,
        "labels": labels,
    }


def _old_share(ag, women_majority):
    old = ag[(ag["age_n"] >= OLD_AGE) & ag["gender"].isin([MALE, FEMALE])]
    if not len(old):
        return 0.0
    f = float((old["gender"] == FEMALE).mean())
    return f if women_majority else 1 - f


def _oldest(acs):
    """Highest median age; among ties the country with the most olim."""
    top = acs[acs["median"] == acs["median"].max()]
    top = top.sort_values(["size", "k"], ascending=[False, True], kind="mergesort")
    return top.iloc[0]
