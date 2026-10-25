"""תיקי פיקוח עם תוצאה תקינה — inspections by the Commission for Equal Rights
of Persons with Disabilities in which no (or only minor) accessibility defects
were found.

One row per inspection file ("מספר תיק פיקוח"); exact duplicate rows and rows
without a file number are dropped. "~" in the source stands for a quote mark.

Sensitivity: the free-text "ישות מפוקחת" sometimes names a private
complainant ("תלונת <name> על ..."), so the page never quotes it — places are
described only by their type and town. "Now" = the latest inspection date in
the data; a calendar year that the data does not reach the end of is labelled
partial and kept out of the trend rules.

Coordinates come in two projections: WGS84 lat/lon and ITM (the "... 1"
columns). A few rows have lat/lon swapped and garbage ITM; the map uses ITM,
whose sanity check (both values ≥ 100,000) drops those rows, and compute
counts mappable rows with the same rule.
"""
import pandas as pd

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
DAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # pandas dayofweek 0=Monday
DAY_ORDER = [6, 0, 1, 2, 3, 4, 5]  # Sunday first
TOP_TYPES = 12
TOP_CITIES = 12
TOP_COMPLAINT_TYPES = 8
ANNUAL = "תוכנית עבודה שנתית"
COMPLAINT = "פניית ציבור"
OTHER_FAMILY = "אחר"
# Rough ITM extent of Israel incl. the Golan and Eilat; mappable points outside
# it are upstream geocoding errors (both projections agree on them).
ITM_N = (370000, 815000)
ITM_E = (120000, 288000)

# Broad family of the inspected place, by keyword in the type label. Order
# matters (first match wins); unknown future types fall to "אחר".
FAMILIES = [
    ("שירות טלפוני ודיגיטלי", ("נתב שיחות", "אתר אינטרנט", "כריזה קולית", "מכונה אוטומ")),
    ("תלונות הפליה ופיקוח מטה", ("הפליה", "אפליה", "במטה", "פיקוח מטה", "ייצוג הולם", "רישוי עסקים", "עיצומים")),
    ("מבני ציבור, דת וקלפיות", ("קלפי", "בית כנסת", "מקווה", "עלמין", "בניין ציבורי", "מבנה ציבורי",
                                "בית שימוש ציבורי")),
    ("תחבורה וחניה", ("תחנת רכבת", "אוטובוס", "נמל", "מעגן", "מזח", "היסעים", "חניון")),
    ("חינוך, השכלה וקהילה", ("מוסד חינוך", "השכלה גבוהה", "קייטנ", "הכשרה", "מועדון קיים", "מתנ",
                             "ספריה", "משפחות אומנה")),
    ("מסחר, אירוח ושירותים", ("מסחר", "מסעדה", "תחנת דלק", "קניון", "דואר", "מלון", "מועדון כושר",
                              "חדר כושר", "קופת חולים")),
    ("בנייני משרדים ומגורים", ("בניין משרדים", "בניין מגורים")),
    ("פנאי, ספורט ושטחים פתוחים", ("משחקים", "שעשועים", "טבע", "גן ציבורי", "חוף", "הנצחה", "ספורט",
                                   "בריכת", "אולם", "מוזיאון", "אירוע", "איצטדיון", "תיאטרון")),
]
FAMILY_ORDER = [f for f, _ in FAMILIES] + [OTHER_FAMILY]


def _int(n):
    return f"{int(n):,}"


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _txt(s):
    return s.str.replace("~", "\"", regex=False).str.replace(r"\s+", " ", regex=True).str.strip()


def _family(t):
    for name, keys in FAMILIES:
        if any(k in t for k in keys):
            return name
    return OTHER_FAMILY


def _building(t):
    if "חדש" in t:
        return "מבנה או מקום חדש"
    if "קיים" in t:
        return "מבנה או מקום קיים"
    return "ללא ציון קיים או חדש"


def _prepare(df):
    df = df.drop_duplicates()
    lat = pd.to_numeric(df["קואורדינטות  רוחב 1"].str.strip(), errors="coerce")
    lng = pd.to_numeric(df["קואורדינטות אורך 1"].str.strip(), errors="coerce")
    out = pd.DataFrame({
        "file": df["מספר תיק פיקוח"].str.strip(),
        "etype": _txt(df["סוג הישות המפוקחת"]).str.replace(r"\s*V$", "", regex=True).str.strip(),
        "track": _txt(df["מסלול פיקוח"]),
        "date": pd.to_datetime(df["תאריך ושעת פיקוח"].str.strip().str.slice(0, 10),
                               format="%d/%m/%Y", errors="coerce"),
        "city": _txt(df["ישוב"]).str.replace(r"\s*-\s*", "-", regex=True),
        "mappable": (lat >= 100000) & (lng >= 100000),
        "in_israel": lat.between(*ITM_N) & lng.between(*ITM_E),
    })
    out = out[out["file"] != ""].drop_duplicates("file")
    out["family"] = out["etype"].map(_family)
    out["building"] = out["etype"].map(_building)
    return out.sort_values("file", kind="stable").reset_index(drop=True)


def _top(series, n, other):
    vc = series.value_counts().sort_index().sort_values(ascending=False, kind="stable")
    top = vc.head(n)
    rest = int(vc.iloc[n:].sum())
    return list(top.index) + ([other] if rest else []), [int(v) for v in top] + ([rest] if rest else [])


def _rows(names, values, total):
    return [{"name": a, "n": _int(b), "share": f"{b / total * 100:.1f}" if total else "0"}
            for a, b in zip(names, values)]


def compute(frames):
    df = _prepare(frames["files"])
    n = len(df)
    dated = df[df["date"].notna()]
    anchor = dated["date"].max()
    first = dated["date"].min()
    years = list(range(int(first.year), int(anchor.year) + 1))
    partial = anchor.month < 12
    full_years = [y for y in years if y < anchor.year or not partial]
    yr = dated["date"].dt.year
    per_year = yr.value_counts()

    # Yearly by track + complaint share --------------------------------------
    by_track = pd.crosstab(yr, dated["track"])
    tracks = [t for t in [ANNUAL, COMPLAINT] if t in by_track.columns] + \
        sorted(t for t in by_track.columns if t not in (ANNUAL, COMPLAINT) and t)

    def ycount(track, y):
        return int(by_track[track].get(y, 0)) if track in by_track.columns else 0

    def cshare(y):
        tot = int(per_year.get(y, 0))
        return round(ycount(COMPLAINT, y) / tot * 100, 1) if tot else None

    yearly = {"x": [str(y) for y in years],
              "series": [{"name": t, "data": [ycount(t, y) for y in years]} for t in tracks],
              "share": [cshare(y) for y in years],
              "partial_label": f"{anchor.year} (חלקית)" if partial else ""}
    if partial:
        yearly["x"][-1] = yearly["partial_label"]
    year_rows = [{"year": yearly["x"][i], "n": _int(per_year.get(y, 0)),
                  "c": _int(ycount(COMPLAINT, y)),
                  "share": "" if cshare(y) is None else f"{cshare(y):.1f}"} for i, y in enumerate(years)]

    # Families: totals + mix by year ----------------------------------------
    fam = df["family"].value_counts()
    fam_names = sorted((f for f in FAMILY_ORDER if f in fam.index), key=lambda f: (-int(fam[f]), FAMILY_ORDER.index(f)))
    fam_chart = {"names": fam_names, "values": [int(fam[f]) for f in fam_names]}
    fam_year = pd.crosstab(yr, dated["family"])
    mix = {"x": yearly["x"], "series": [
        {"name": f, "data": [round(float(fam_year[f].get(y, 0)) / int(per_year[y]) * 100, 1)
                             if f in fam_year.columns and per_year.get(y, 0) else 0 for y in years]}
        for f in fam_names]}
    mix_rows = [{"year": yearly["x"][i],
                 "cells": [_int(fam_year[f].get(y, 0)) if f in fam_year.columns else "0" for f in fam_names]}
                for i, y in enumerate(years)]

    # Detailed types, complaint types, buildings, cities ----------------------
    et_names, et_vals = _top(df["etype"], TOP_TYPES, "סוגים אחרים")
    comp = df[df["track"] == COMPLAINT]
    ct_names, ct_vals = _top(comp["etype"], TOP_COMPLAINT_TYPES, "סוגים אחרים")
    bld = df["building"].value_counts()
    bld_names = [b for b in ["מבנה או מקום קיים", "מבנה או מקום חדש", "ללא ציון קיים או חדש"]
                 if b in bld.index]
    bld_chart = {"names": bld_names, "values": [int(bld[b]) for b in bld_names]}
    with_city = df[df["city"] != ""]
    city_names, city_vals = _top(with_city["city"], TOP_CITIES, "יישובים אחרים")

    # Calendar: month × year heatmap + weekday --------------------------------
    ym = dated.groupby([yr, dated["date"].dt.month]).size()
    cells = [[m - 1, yi, int(ym.get((y, m), 0))] for yi, y in enumerate(years) for m in range(1, 13)]
    heat = {"months": MONTHS_HE, "years": yearly["x"], "cells": cells}
    wd = dated["date"].dt.dayofweek.value_counts()
    weekday = {"names": [DAYS_HE[d] for d in DAY_ORDER], "values": [int(wd.get(d, 0)) for d in DAY_ORDER]}

    n_map = int(df["mappable"].sum())
    n_stray = int((df["mappable"] & ~df["in_israel"]).sum())
    n_cities = int(with_city["city"].nunique())
    n_comp = len(comp)

    # Insights ----------------------------------------------------------------
    def ins_latest():
        tail = (f" — {anchor.year} עדיין חלקית במאגר ({_int(per_year.get(anchor.year, 0))} פיקוחים עד כה)"
                if partial else "")
        return (f"הפיקוח האחרון במאגר נערך ב-{d_he(anchor)}; בסך הכול {_int(n)} תיקי פיקוח עם תוצאה תקינה "
                f"מ-{first.year}{tail}.")

    def ins_peak():
        if len(full_years) < 3:
            return None
        peak = max(full_years, key=lambda y: (int(per_year.get(y, 0)), -y))
        last = full_years[-1]
        if peak == last:
            return f"{last} הייתה השנה עם הכי הרבה פיקוחים תקינים ({_int(per_year.get(last, 0))})."
        a, b = int(per_year.get(peak, 0)), int(per_year.get(last, 0))
        return (f"השיא היה ב-{peak} עם {_int(a)} פיקוחים; ב-{last} נרשמו {_int(b)} בלבד "
                f"({_pct(b / a)} מרמת השיא).")

    def ins_trend():
        if len(full_years) < 2:
            return None
        y1, y0 = full_years[-1], full_years[-2]
        a, b = int(per_year.get(y0, 0)), int(per_year.get(y1, 0))
        if a < 10:
            return None
        ch = (b - a) / a
        if abs(ch) < 0.10:
            word = "יציבות" if round(ch * 100) else "ללא שינוי"
            return f"בין {y0} ל-{y1} {word} במספר הפיקוחים: {_int(a)} מול {_int(b)}."
        direction = "עלייה" if ch > 0 else "ירידה"
        return f"ב-{y1} נרשמו {_int(b)} פיקוחים, {direction} של {_pct(abs(ch))} לעומת {y0} ({_int(a)})."

    def ins_track():
        cand = [y for y in full_years if per_year.get(y, 0) >= 20]
        if len(cand) < 2:
            return None
        y0, y1 = cand[0], cand[-1]
        s0, s1 = cshare(y0), cshare(y1)
        if abs(s1 - s0) < 10:
            return (f"{_pct(n_comp / n)} מהפיקוחים נפתחו בעקבות פניית ציבור, והשאר במסגרת תוכנית העבודה "
                    f"השנתית.")
        word = "עלה" if s1 > s0 else "ירד"
        return (f"חלקן של פניות הציבור בפיקוחים {word} מ-{s0:.0f}% ב-{y0} ל-{s1:.0f}% ב-{y1}; "
                f"בסך הכול {_int(n_comp)} פיקוחים ({_pct(n_comp / n)}) נפתחו בעקבות פנייה.")

    def ins_type():
        top = df["etype"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
        if len(top) < 2:
            return None
        t, c = top.index[0], int(top.iloc[0])
        ys = dated[dated["etype"] == t]["date"].dt.year.value_counts().sort_index()
        ys = ys.sort_values(ascending=False, kind="stable")
        tail = ""
        if len(ys) and ys.iloc[0] / c >= 0.8:
            tail = (f" — כולם ב-{int(ys.index[0])}" if int(ys.iloc[0]) == c
                    else f" — {_int(ys.iloc[0])} מהם ב-{int(ys.index[0])}")
        return (f"סוג המקום הנפוץ ביותר: {t} ({_int(c)} פיקוחים{tail}); אחריו {top.index[1]} "
                f"({_int(top.iloc[1])}).")

    def ins_city():
        if len(with_city) < 30 or len(city_names) < 3:
            return None
        top3 = with_city["city"].value_counts().sort_index().sort_values(ascending=False, kind="stable").head(3)
        no_city = df[df["city"] == ""]
        tail = ""
        if len(no_city):
            nf = no_city["family"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
            tail = (f"; ב-{_int(len(no_city))} פיקוחים אין יישוב — רובם בקבוצת {nf.index[0]}"
                    if nf.iloc[0] / len(no_city) >= 0.5 else f"; ב-{_int(len(no_city))} פיקוחים אין יישוב")
        names = ", ".join(f"{c} ({_int(v)})" for c, v in top3.items())
        return f"היישובים עם הכי הרבה פיקוחים תקינים: {names}, מתוך {_int(n_cities)} יישובים{tail}."

    def ins_building():
        new, old = int(bld.get("מבנה או מקום חדש", 0)), int(bld.get("מבנה או מקום קיים", 0))
        if new + old < 30:
            return None
        return (f"{_int(old)} פיקוחים נערכו במבנים ובמקומות קיימים ו-{_int(new)} בחדשים "
                f"({_pct(new / (new + old))} מהמבנים שנבדקו).")

    def ins_month():
        if len(years) < 2:
            return None
        top = ym.sort_index().sort_values(ascending=False, kind="stable")
        (y, m), c = top.index[0], int(top.iloc[0])
        if c < 2 * max(1, float(ym.median())):
            return None
        return (f"החודש העמוס ביותר היה {MONTHS_HE[int(m) - 1]} {int(y)} עם {_int(c)} פיקוחים, "
                f"לעומת חציון של {float(ym.median()):.0f} בחודש שבו נערך פיקוח.")

    rules = [("latest", ins_latest()), ("peak", ins_peak()), ("trend", ins_trend()), ("track", ins_track()),
             ("type", ins_type()), ("city", ins_city()), ("building", ins_building()), ("month", ins_month())]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    return {
        "agent_data": {
            "summary_he": (f"{_int(n)} פיקוחי נגישות של נציבות שוויון זכויות לאנשים עם מוגבלות שבהם לא נמצאו "
                           f"ליקויים או נמצאו ליקויים מעטים, מ-{first.year} ועד {d_he(anchor)}, ב-{_int(n_cities)} "
                           f"יישובים: מה נבדק, איפה, ובעקבות מה."),
            "dataset_kind": "map",
            "suggested_tags": ["נגישות", "אנשים עם מוגבלות", "פיקוח", "שוויון זכויות"],
            "related_ids": ["03bf114c-73cc-452c-a3d1-58520d6dc506", "b5ee9460-87d7-4eb4-868a-58e35bc507b2"],
            "temporal_coverage": f"{first.strftime('%Y-%m-%d')}/{anchor.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": {
            "files": {"value": n, "display": _int(n), "tone": "brand"},
            "cities": {"value": n_cities, "display": _int(n_cities), "tone": "brand"},
            "complaints": {"value": round(n_comp / n * 100, 1), "display": _pct(n_comp / n, 1), "tone": "info"},
            "latest": {"value": anchor.strftime("%Y-%m-%d"),
                       "display": f"{anchor.day}.{anchor.month}.{anchor.year}", "tone": "info"},
        },
        "charts": {"yearly": yearly, "family": fam_chart, "mix": mix,
                   "etype": {"names": et_names, "values": et_vals},
                   "complaint_types": {"names": ct_names, "values": ct_vals},
                   "building": bld_chart, "city": {"names": city_names, "values": city_vals},
                   "heat": heat, "weekday": weekday, "map_center": [31.4, 35.0]},
        "tables": {
            "years": year_rows,
            "family": _rows(fam_names, fam_chart["values"], n),
            "mix_head": fam_names,
            "mix": mix_rows,
            "etype": _rows(et_names, et_vals, n),
            "complaint_types": _rows(ct_names, ct_vals, n_comp),
            "building": _rows(bld_names, bld_chart["values"], n),
            "city": _rows(city_names, city_vals, len(with_city)),
            "weekday": _rows(weekday["names"], weekday["values"], len(dated)),
        },
        "insights": insights,
        "flags": {"map": n_map > 0, "complaints": n_comp >= 5},
        "labels": {
            "lede": (f"{_int(n)} תיקי פיקוח שבהם מפקחי הנציבות בדקו את ביצוע התאמות הנגישות ולא מצאו ליקויים, "
                     f"או מצאו ליקויים מעטים — מ-{d_he(first)} ועד {d_he(anchor)}, ב-{_int(n_cities)} יישובים. "
                     f"התוצאה נכונה ליום הפיקוח ומתייחסת רק למה שנבדק."),
            "yearly_note": (f"פיקוחים לפי שנה ולפי מסלול: תוכנית העבודה השנתית של הנציבות או פניית ציבור. "
                            f"הקו מראה את חלקן של פניות הציבור."
                            + (f" {anchor.year} חלקית — הנתונים עד {d_he(anchor)}." if partial else "")),
            "family_note": "סיווג רחב של סוג המקום שנבדק, לפי שם הסוג במאגר.",
            "mix_note": "חלקה של כל קבוצה מתוך הפיקוחים בכל שנה.",
            "complaint_note": f"{_int(n_comp)} פיקוחים שנפתחו בעקבות פניית ציבור, לפי סוג המקום.",
            "building_note": "לפי ציון \"קיים\" או \"חדש\" בסוג המקום שנבדק; לשירותים, אירועים ותחנות רבות אין ציון כזה.",
            "city_note": f"פיקוחים לפי יישוב המקום שנבדק ({_int(len(with_city))} פיקוחים עם יישוב).",
            "map_note": (f"{_int(n_map)} מתוך {_int(n)} פיקוחים עם קואורדינטות"
                         + (f"; {_int(n_stray)} מהם ממוקמים במאגר מחוץ לישראל — שגיאת מיקום במקור" if n_stray else "")
                         + ". לחיצה על נקודה מציגה את סוג המקום, היישוב ותאריך הפיקוח."),
            "heat_note": "מספר הפיקוחים בכל חודש. גוון כהה יותר = יותר פיקוחים.",
            "yearly_aria": f"עמודות מוערמות וקו: פיקוחים לפי שנה ומסלול, {years[0]} עד {anchor.year}.",
            "family_aria": "עמודות אופקיות: פיקוחים לפי קבוצת סוג המקום.",
            "mix_aria": "עמודות מוערמות: חלק כל קבוצת מקומות מתוך הפיקוחים בכל שנה.",
            "etype_aria": f"עמודות אופקיות: {TOP_TYPES} סוגי המקומות הנפוצים.",
            "complaint_aria": "עמודות אופקיות: פיקוחים בעקבות פניית ציבור לפי סוג המקום.",
            "building_aria": "טבעת: פיקוחים במבנים קיימים, חדשים וללא ציון.",
            "city_aria": f"עמודות אופקיות: {TOP_CITIES} היישובים עם הכי הרבה פיקוחים.",
            "heat_aria": f"מפת חום: פיקוחים לפי חודש ושנה, {years[0]} עד {anchor.year}.",
            "weekday_aria": "עמודות: פיקוחים לפי יום בשבוע.",
            "map_aria": "מפה: מיקומי הפיקוחים עם תוצאה תקינה.",
        },
    }
