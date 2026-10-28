"""תקנות הירושה — בתי הדין הדרוזים (inheritance-order notices, Arabic).

One table, one row per published notice of a request for an inheritance
order: court, file number, applicant name, deceased name, the deceased's
settlement, date of death and the notice's publication date. The source is
in Arabic; the page is Hebrew, so courts and settlements are mapped through
the lookup tables below (unknown values fall into an "other" bucket and are
counted, never printed in Arabic).

Personal-status data: NOTHING about any person is shown — no names of the
deceased or applicants and no file numbers. The page only aggregates by
court, settlement, region, publication month/weekday and the time from death
to notice. File numbers are used internally only to count a file that was
published more than once a single time.

Built to be reusable for the Sharia-courts sibling: dataset-specific facts
live in the COURTS / SETTLEMENTS / REGION tables and the column map.

"Now" is the latest publication date in the data, never the wall clock.
"""
import math

import pandas as pd

LRI, PDI = "⁦", "⁩"
MINUS = "−"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
WEEKDAYS_HE = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]  # pandas 0=Mon
WEEK_ORDER = [6, 0, 1, 2, 3, 4, 5]   # Sunday → Saturday

COL = {
    "court": "court_name",
    "file": "file_number",
    "place": "deaceased_address",
    "death": "deaceased_date",
    "pub": "published_date",
}

OTHER_COURT = "בית דין אחר"
NO_COURT = "לא צוין"
OTHER_PLACE = "יישוב אחר"
OTHER_REGION = "אחר"

# Arabic court name (normalised) → Hebrew short name
COURTS = {
    "عكا": "עכו",
    "بقعاثا": "בוקעאתא",
    "حيفا": "חיפה",
    "الكرمل": "הכרמל",
    "استئناف": "ערעורים",
    "محكمهالاستئناف": "ערעורים",
}

# Arabic settlement (normalised) → (Hebrew name, region, lat, lng)
GALIL, CARMEL, GOLAN = "הגליל", "הכרמל", "רמת הגולן"
SETTLEMENTS = {
    "يركا": ("ירכא", GALIL, 32.955, 35.188),
    "داليهالكرمل": ("דאלית אל-כרמל", CARMEL, 32.693, 35.047),
    "داليه": ("דאלית אל-כרמל", CARMEL, 32.693, 35.047),
    "بيتجن": ("בית ג׳ן", GALIL, 32.963, 35.381),
    "المغار": ("מע׳אר", GALIL, 32.888, 35.408),
    "مغار": ("מע׳אר", GALIL, 32.888, 35.408),
    "عسفيا": ("עספיא", CARMEL, 32.718, 35.065),
    "حرفيش": ("חורפיש", GALIL, 33.017, 35.349),
    "شفاعمرو": ("שפרעם", GALIL, 32.806, 35.170),
    "شفاعمر": ("שפרעם", GALIL, 32.806, 35.170),
    "جولس": ("ג׳ולס", GALIL, 32.946, 35.180),
    "يانوح": ("ינוח", GALIL, 33.022, 35.247),
    "يانوحجث": ("ינוח-ג׳ת", GALIL, 33.016, 35.244),
    "جث": ("ג׳ת (הגליל)", GALIL, 33.010, 35.240),
    "جثالجليل": ("ג׳ת (הגליל)", GALIL, 33.010, 35.240),
    "ابوسنان": ("אבו סנאן", GALIL, 32.958, 35.169),
    "ساجور": ("סאג׳ור", GALIL, 32.943, 35.343),
    "البقيعه": ("פקיעין", GALIL, 32.978, 35.333),
    "بقيعه": ("פקיעין", GALIL, 32.978, 35.333),
    "الرامه": ("ראמה", GALIL, 32.937, 35.367),
    "رامه": ("ראמה", GALIL, 32.937, 35.367),
    "كسري": ("כסרא", GALIL, 32.983, 35.297),
    "كفرسميع": ("כפר סמיע", GALIL, 32.968, 35.302),
    "كسريسميع": ("כסרא-סמיע", GALIL, 32.975, 35.300),
    "عينالاسد": ("עין אל-אסד", GALIL, 32.946, 35.400),
    "كفرياسيف": ("כפר יאסיף", GALIL, 32.954, 35.163),
    "عكا": ("עכו", GALIL, 32.927, 35.082),
    "حيفا": ("חיפה", CARMEL, 32.794, 34.990),
    "مجدلشمس": ("מג׳דל שמס", GOLAN, 33.268, 35.770),
    "بقعاثا": ("בוקעאתא", GOLAN, 33.203, 35.778),
    "عينقنيا": ("עין קנייא", GOLAN, 33.237, 35.740),
    "مسعده": ("מסעדה", GOLAN, 33.233, 35.755),
}
REGION_ORDER = [GALIL, CARMEL, GOLAN, OTHER_REGION]

TOP_PLACES = 15
DEATH_YEARS = 10          # individual death years shown; older grouped
MIN_LAG_N = 50
MIN_YEAR_LAG_N = 40       # files per publication year for the lag-mix chart
SEASON_MIN_N = 300

LAG_BUCKETS = [  # (upper bound in days, inclusive, label)
    (30, "עד חודש"),
    (91, "חודש עד שלושה"),
    (182, "שלושה עד שישה חודשים"),
    (365, "חצי שנה עד שנה"),
    (730, "שנה עד שנתיים"),
    (1826, "שנתיים עד חמש שנים"),
    (3652, "חמש עד עשר שנים"),
    (None, "יותר מעשר שנים"),
]
LAG_GROUPS = [(365, "עד שנה"), (1826, "שנה עד חמש שנים"), (None, "יותר מחמש שנים")]


# ---------------------------------------------------------------- helpers
def n(v):
    return f"{int(round(v)):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_dot(ts):
    return f"{ts.day:02d}.{ts.month:02d}.{ts.year}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def norm_ar(s):
    s = str(s).strip()
    for a in "أإآٱ":
        s = s.replace(a, "ا")
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ـ", "")
    return "".join(ch for ch in s if ch not in " -_.'\"،")


def court_he(raw):
    k = norm_ar(raw)
    if not k:
        return NO_COURT
    return COURTS.get(k, OTHER_COURT)


def place_info(raw):
    k = norm_ar(raw)
    hit = SETTLEMENTS.get(k)
    if hit is None and k.startswith("قريه"):
        hit = SETTLEMENTS.get(k[4:])
    return hit


def parse_dates(s):
    u = pd.Series(sorted(s.unique()))
    a = pd.to_datetime(u.str.strip(), format="%d/%m/%Y", errors="coerce")
    b = pd.to_datetime(u.str.strip(), format="%d.%m.%Y", errors="coerce")
    return s.map(dict(zip(u, a.fillna(b))))


def lag_label(days, buckets):
    for ub, lab in buckets:
        if ub is None or days <= ub:
            return lab
    return buckets[-1][1]


def signed_pct(v):
    r = round(v, 1)
    if r == 0:
        return "0%"
    return f"+{r:.1f}%" if r > 0 else f"{MINUS}{abs(r):.1f}%"


def court_phrase(c):
    if c in (NO_COURT, OTHER_COURT):
        return c
    return f"בית הדין ב{c}"


# ---------------------------------------------------------------- compute
def compute(frames):
    raw = frames["main"].copy()
    n_rows_raw = len(raw)
    keep = [COL[k] for k in ("court", "file", "place", "death", "pub")]
    raw = raw.drop_duplicates()
    for c in keep:
        raw[c] = raw[c].astype(str).str.strip()
    n_exact_dups = n_rows_raw - len(raw)

    df = pd.DataFrame({
        "court": raw[COL["court"]].map(court_he),
        "file": raw[COL["file"]],
        "place_raw": raw[COL["place"]],
        "pub": parse_dates(raw[COL["pub"]]),
        "death": parse_dates(raw[COL["death"]]),
    })
    info = df["place_raw"].map(place_info)
    df["place"] = info.map(lambda t: t[0] if t else OTHER_PLACE)
    df["region"] = info.map(lambda t: t[1] if t else OTHER_REGION)

    n_bad_pub = int(df["pub"].isna().sum())
    df = df[df["pub"].notna()].copy()
    total = len(df)
    df = df.sort_values(["pub", "court", "file", "place", "death"],
                        kind="mergesort", na_position="last").reset_index(drop=True)

    last = df["pub"].max()
    first = df["pub"].min()
    last_year = int(last.year)

    # ----------------------------------------------- unique files (estates)
    has_file = df["file"] != ""
    keyed = df[has_file].drop_duplicates(["court", "file"], keep="first")
    files = pd.concat([keyed, df[~has_file]]).sort_values(
        ["pub", "court", "file", "place", "death"], kind="mergesort",
        na_position="last").reset_index(drop=True)
    n_files = len(files)
    n_republished = int(df[has_file].duplicated(["court", "file"], keep="first").sum())

    # ----------------------------------------------- courts
    court_counts = df["court"].value_counts()
    courts = sorted(court_counts.index, key=lambda c: (-court_counts[c], c))
    named_courts = [c for c in courts if c not in (NO_COURT, OTHER_COURT)]

    # ----------------------------------------------- monthly publications
    months = pd.period_range(first.to_period("M"), last.to_period("M"), freq="M")
    df["ym"] = df["pub"].dt.to_period("M")
    m_ct = df.groupby(["ym", "court"]).size()
    month_labels = [f"{MONTHS_SHORT[p.month - 1]} {p.year}" for p in months]
    monthly_series = []
    for c in courts:
        monthly_series.append({"name": c,
                               "data": [int(m_ct.get((p, c), 0)) for p in months]})
    m_tot = df.groupby("ym").size().reindex(months, fill_value=0)
    full_months = m_tot.iloc[1:-1] if len(m_tot) > 2 else m_tot
    peak_p = max(full_months.index, key=lambda p: (int(full_months[p]), -p.ordinal))
    peak_v = int(full_months[peak_p])
    med_month = float(full_months.median())
    zoom_start = month_labels[max(0, len(month_labels) - 24)]

    # ----------------------------------------------- yearly publications
    df["y"] = df["pub"].dt.year
    years = list(range(int(first.year), last_year + 1))
    y_ct = df.groupby(["y", "court"]).size()
    y_tot = df.groupby("y").size()
    year_partial = not (last.month == 12 and last.day >= 24)
    year_labels = []
    for y in years:
        lab = str(y)
        if y == last_year and year_partial:
            lab = f"{y} (עד {d_dot(last)[:5]})"
        year_labels.append(lab)
    years_chart = {
        "x": year_labels,
        "series": [{"name": c,
                    "data": [int(y_ct.get((y, c), 0)) for y in years]} for c in courts],
    }
    years_table = [{"year": year_labels[i],
                    "cells": [n(y_ct.get((y, c), 0)) for c in courts],
                    "total": n(y_tot.get(y, 0))} for i, y in enumerate(years)]

    # same-period comparison
    def upto(ts_series, y):
        return ((ts_series.dt.year == y) &
                ((ts_series.dt.month < last.month) |
                 ((ts_series.dt.month == last.month) & (ts_series.dt.day <= last.day))))
    ytd = int(upto(df["pub"], last_year).sum())
    prev_ytd = int(upto(df["pub"], last_year - 1).sum())
    ytd_chg = (ytd - prev_ytd) / prev_ytd * 100 if prev_ytd >= 20 else None

    # ----------------------------------------------- weekday / batches
    wd = df["pub"].dt.dayofweek.value_counts()
    batches = df.groupby("pub").size()
    n_batches = len(batches)
    wd_dates = pd.Series(batches.index).dt.dayofweek.value_counts()
    weekday_chart = {"x": [WEEKDAYS_HE[i] for i in WEEK_ORDER],
                     "y": [int(wd.get(i, 0)) for i in WEEK_ORDER]}
    weekday_table = [{"day": WEEKDAYS_HE[i], "notices": n(wd.get(i, 0)),
                      "dates": n(wd_dates.get(i, 0))} for i in WEEK_ORDER]
    top_wd = max(range(7), key=lambda i: (int(wd.get(i, 0)), -i))
    top_wd_share = int(wd.get(top_wd, 0)) / total if total else 0
    batch_med = float(batches.median())
    batch_max = int(batches.max())

    # ----------------------------------------------- settlements / regions
    p_ct = files["place"].value_counts()
    known_places = [p for p in p_ct.index if p != OTHER_PLACE]
    known_places.sort(key=lambda p: (-int(p_ct[p]), p))
    n_other_place = int(p_ct.get(OTHER_PLACE, 0))
    region_of = {}
    coords = {}
    for v in SETTLEMENTS.values():
        region_of[v[0]] = v[1]
        coords[v[0]] = (v[2], v[3])
    place_court = (files.groupby(["place", "court"]).size().reset_index(name="k")
                   .sort_values(["place", "k", "court"], ascending=[True, False, True],
                                kind="mergesort").drop_duplicates("place"))
    main_court = dict(zip(place_court["place"], place_court["court"]))

    top = known_places[:TOP_PLACES]
    rest = int(sum(int(p_ct[p]) for p in known_places[TOP_PLACES:])) + n_other_place
    regions_present = [r for r in REGION_ORDER if r in set(files["region"])]
    place_rows = list(reversed(top))  # bottom→top for horizontal bar
    places_chart = {"y": (["שאר היישובים"] if rest else []) + place_rows, "series": []}
    for r in regions_present:
        if r == OTHER_REGION:
            continue
        data = []
        if rest:
            data.append(0)
        for p in place_rows:
            data.append(int(p_ct[p]) if region_of.get(p) == r else 0)
        places_chart["series"].append({"name": r, "data": data})
    if rest:
        places_chart["series"].append({"name": "שאר היישובים",
                                       "data": [rest] + [0] * len(place_rows)})
    places_table = [{"place": p, "region": region_of.get(p, OTHER_REGION),
                     "court": court_phrase(main_court.get(p, NO_COURT)),
                     "files": n(p_ct[p]),
                     "share": pct(int(p_ct[p]) / n_files * 100)} for p in top]
    if rest:
        places_table.append({"place": "שאר היישובים", "region": "—", "court": "—",
                             "files": n(rest), "share": pct(rest / n_files * 100)})

    r_ct = files["region"].value_counts()
    r_places = files[files["place"] != OTHER_PLACE].groupby("region")["place"].nunique()
    region_court = (files.groupby(["region", "court"]).size().reset_index(name="k")
                    .sort_values(["region", "k", "court"], ascending=[True, False, True],
                                 kind="mergesort").drop_duplicates("region"))
    r_main_court = dict(zip(region_court["region"], region_court["court"]))
    regions_table = [{"region": r, "places": n(r_places.get(r, 0)),
                      "files": n(r_ct.get(r, 0)),
                      "share": pct(int(r_ct.get(r, 0)) / n_files * 100),
                      "court": court_phrase(r_main_court.get(r, NO_COURT))}
                     for r in regions_present]

    map_points = []
    for p in sorted(known_places, key=lambda p: (-int(p_ct[p]), p)):
        if p in coords:
            la, ln = coords[p]
            map_points.append([la, ln, int(p_ct[p]), p, region_of.get(p, OTHER_REGION),
                               court_phrase(main_court.get(p, NO_COURT))])
    n_places = len(known_places)

    # ----------------------------------------------- lag death → notice
    lagdf = files[files["death"].notna()].copy()
    lagdf["lag"] = (lagdf["pub"] - lagdf["death"]).dt.days
    n_neg = int((lagdf["lag"] < 0).sum())
    n_bad_death = int(files["death"].isna().sum())
    lagdf = lagdf[lagdf["lag"] >= 0].copy()
    n_lag = len(lagdf)
    lagdf["b"] = lagdf["lag"].map(lambda d: lag_label(d, LAG_BUCKETS))
    b_ct = lagdf["b"].value_counts()
    lag_chart = {"x": [lab for _, lab in LAG_BUCKETS],
                 "y": [int(b_ct.get(lab, 0)) for _, lab in LAG_BUCKETS]}
    lag_table = [{"bucket": lab, "files": n(b_ct.get(lab, 0)),
                  "share": pct(int(b_ct.get(lab, 0)) / n_lag * 100 if n_lag else 0)}
                 for _, lab in LAG_BUCKETS]
    lag_med_days = float(lagdf["lag"].median()) if n_lag else None
    lag_med_months = lag_med_days / 30.4375 if lag_med_days is not None else None
    within_year = int((lagdf["lag"] <= 365).sum())
    over10 = int((lagdf["lag"] > 3652).sum())

    # lag mix per publication year
    lagdf["y"] = lagdf["pub"].dt.year
    lagdf["g"] = lagdf["lag"].map(lambda d: lag_label(d, LAG_GROUPS))
    ly = lagdf.groupby("y").size()
    lag_years = [y for y in years if int(ly.get(y, 0)) >= MIN_YEAR_LAG_N]
    g_ct = lagdf.groupby(["y", "g"]).size()
    y_med = lagdf.groupby("y")["lag"].median()
    lag_year_chart = {
        "x": [year_labels[years.index(y)] for y in lag_years],
        "series": [{"name": lab,
                    "data": [round(int(g_ct.get((y, lab), 0)) / int(ly[y]) * 100, 1)
                             for y in lag_years]} for _, lab in LAG_GROUPS],
    }
    lag_year_table = [{"year": year_labels[years.index(y)], "files": n(ly[y]),
                       "cells": [pct(int(g_ct.get((y, lab), 0)) / int(ly[y]) * 100)
                                 for _, lab in LAG_GROUPS],
                       "median": f"{float(y_med[y]) / 30.4375:.1f}"} for y in lag_years]

    # ----------------------------------------------- year of death
    dy = files["death"].dropna()
    dy = dy[dy <= last]
    max_dy = int(dy.dt.year.max()) if len(dy) else last_year
    cut = max_dy - DEATH_YEARS + 1
    dyc = dy.dt.year.value_counts()
    older = int(dyc[dyc.index < cut].sum())
    death_x, death_y = [], []
    if older:
        death_x.append(f"לפני {cut}")
        death_y.append(older)
    for y in range(cut, max_dy + 1):
        death_x.append(str(y))
        death_y.append(int(dyc.get(y, 0)))
    oldest_year = int(dy.dt.year.min()) if len(dy) else None
    recent_years = [y for y in range(cut, max_dy + 1)]
    top_dy = (max(recent_years, key=lambda y: (int(dyc.get(y, 0)), -y))
              if recent_years and len(dy) else None)
    death_table = [{"year": death_x[i], "files": n(death_y[i])} for i in range(len(death_x))]

    # ----------------------------------------------- month of death (seasonality)
    ds = files["death"].dropna()
    ds = ds[ds <= last]
    placeholder = (ds.dt.month == 1) & (ds.dt.day == 1)
    n_placeholder = int(placeholder.sum())
    ds = ds[~placeholder]
    n_season = len(ds)
    mc = ds.dt.month.value_counts()
    winter_months = [12, 1, 2]
    season_chart = {"x": MONTHS_HE, "y": [int(mc.get(m, 0)) for m in range(1, 13)],
                    "winter": [m in winter_months for m in range(1, 13)]}
    season_table = [{"month": MONTHS_HE[m - 1], "files": n(mc.get(m, 0))} for m in range(1, 13)]
    winter = int(sum(int(mc.get(m, 0)) for m in winter_months))
    winter_share = winter / n_season if n_season else 0
    summer = int(sum(int(mc.get(m, 0)) for m in (6, 7, 8)))
    summer_share = summer / n_season if n_season else 0

    # ================================================= insights
    insights = []

    def add(iid, text):
        if text:
            insights.append({"id": iid, "text_he": text})

    # 1. which court carries the load
    def ins_court():
        if not named_courts or total < 50:
            return None
        lead = named_courts[0]
        share = court_counts[lead] / total
        if share < 0.6:
            return None
        txt = (f"{court_phrase(lead)} פרסם {n(court_counts[lead])} מתוך {n(total)} ההודעות "
               f"({pct(share * 100)}).")
        if len(named_courts) > 1:
            sec = named_courts[1]
            sec_files = files[files["court"] == sec]
            if len(sec_files):
                rc = sec_files["region"].value_counts()
                top_r = sorted(rc.index, key=lambda r: (-int(rc[r]), r))[0]
                r_share = int(rc[top_r]) / len(sec_files)
                tail = ""
                if top_r != OTHER_REGION and r_share >= 0.8:
                    tail = f", ו־{pct(r_share * 100, 0)} מהתיקים שלו הם של נפטרים מיישובי {top_r}"
                txt += f" {court_phrase(sec)} פרסם {n(court_counts[sec])}{tail}."
        return txt
    add("court_lead", ins_court())

    # 2. settlement concentration
    def ins_places():
        if len(known_places) < 3 or n_files < 50:
            return None
        t3 = known_places[:3]
        s3 = sum(int(p_ct[p]) for p in t3)
        if s3 / n_files < 0.25:
            return None
        return (f"בראש רשימת היישובים: {t3[0]}, עם {n(p_ct[t3[0]])} תיקי עזבון ({pct(p_ct[t3[0]] / n_files * 100)}); "
                f"יחד עם {t3[1]} ו{t3[2]} — שלושת היישובים מרכזים {pct(s3 / n_files * 100)} "
                f"מכלל {n(n_files)} התיקים, מתוך {n(n_places)} יישובים שמופיעים במאגר.")
    add("places", ins_places())

    # 3. time from death to notice
    def ins_lag():
        if n_lag < MIN_LAG_N:
            return None
        txt = (f"החציון בין הפטירה לפרסום ההודעה הוא {lag_med_months:.1f} חודשים, "
               f"ו־{pct(within_year / n_lag * 100, 0)} מהבקשות פורסמו בתוך שנה מהפטירה.")
        if over10 / n_lag >= 0.1:
            txt += (f" מנגד, {pct(over10 / n_lag * 100, 0)} ({n(over10)} תיקים) נוגעים לפטירות "
                    f"שאירעו יותר מעשר שנים לפני הפרסום — עזבונות ישנים שמוסדרים באיחור רב.")
        return txt
    add("lag", ins_lag())

    # 4. same-period comparison
    def ins_ytd():
        if ytd_chg is None:
            return None
        period = f"מתחילת {last_year} ועד {d_he(last)}"
        if abs(ytd_chg) < 10:
            trend = (f"דומה לתקופה המקבילה ב־{last_year - 1} ({n(prev_ytd)}"
                     + (", ללא שינוי" if round(ytd_chg, 1) == 0 else f", {LRI}{signed_pct(ytd_chg)}{PDI}")
                     + ")")
        elif ytd_chg > 0:
            trend = (f"עלייה של {pct(ytd_chg, 0)} לעומת התקופה המקבילה ב־{last_year - 1} "
                     f"({n(prev_ytd)})")
        else:
            trend = (f"ירידה של {pct(abs(ytd_chg), 0)} לעומת התקופה המקבילה ב־{last_year - 1} "
                     f"({n(prev_ytd)})")
        return f"{period} פורסמו {n(ytd)} הודעות — {trend}."
    add("ytd", ins_ytd())

    # 5. publication rhythm
    def ins_weekday():
        if total < 50 or top_wd_share < 0.5:
            return None
        return (f"ההודעות מתפרסמות במקבצים: {n(n_batches)} מועדי פרסום, "
                f"בחציון {batch_med:.0f} הודעות בכל מועד. {pct(top_wd_share * 100, 0)} מההודעות "
                f"פורסמו ביום {WEEKDAYS_HE[top_wd]}.")
    add("weekday", ins_weekday())

    # 6. winter deaths
    def ins_winter():
        if n_season < SEASON_MIN_N:
            return None
        thr = 0.25 + 2.5 * math.sqrt(0.25 * 0.75 / n_season)
        if winter_share < thr:
            return None
        return (f"{pct(winter_share * 100, 0)} מהפטירות שתאריכן ידוע אירעו בחודשי החורף "
                f"(דצמבר עד פברואר), לעומת {pct(summer_share * 100, 0)} בחודשי הקיץ "
                f"(יוני עד אוגוסט) — יותר מהרבע הצפוי בפיזור אחיד על פני השנה.")
    add("winter", ins_winter())

    # 7. busiest month
    def ins_peak():
        if len(full_months) < 6 or med_month <= 0 or peak_v < 1.3 * med_month:
            return None
        return (f"החודש העמוס ביותר היה {MONTHS_HE[peak_p.month - 1]} {peak_p.year} עם "
                f"{n(peak_v)} הודעות, לעומת חציון של {med_month:.0f} הודעות בחודש "
                f"(ללא החודש הראשון והאחרון, שאינם מלאים).")
    add("peak", ins_peak())

    # ================================================= KPIs
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "ytd": {"value": ytd, "display": n(ytd), "tone": "brand"},
        "ytd_change": {
            "value": None if ytd_chg is None else round(ytd_chg, 1),
            "display": "—" if ytd_chg is None else signed_pct(ytd_chg),
            "tone": "brand" if ytd_chg is None or abs(ytd_chg) < 10 else "info",
        },
        "lag": {"value": None if lag_med_months is None else round(lag_med_months, 1),
                "display": "—" if lag_med_months is None else f"{lag_med_months:.1f}",
                "tone": "info"},
        "old": {"value": round(over10 / n_lag * 100, 1) if n_lag else None,
                "display": f"{over10 / n_lag * 100:.1f}%" if n_lag else "—",
                "tone": "warn" if n_lag and over10 / n_lag >= 0.2 else "brand"},
        "places": {"value": n_places, "display": n(n_places), "tone": "brand"},
    }

    # ================================================= labels
    span = f"מ־{d_he(first)} עד {d_he(last)}"
    lead_txt = ""
    if named_courts:
        lead_txt = (f" {court_phrase(named_courts[0])} מפרסם {pct(court_counts[named_courts[0]] / total * 100, 0)} "
                    f"מההודעות.")
    dups_txt = ""
    if n_republished:
        dups_txt = (f"{n(n_republished)} תיקים פורסמו יותר מפעם אחת; בניתוח לפי יישוב ולפי מועד "
                    f"הפטירה כל תיק נספר פעם אחת ({n(n_files)} תיקים).")
    if n_exact_dups:
        dups_txt += f" {n(n_exact_dups)} שורות כפולות זהות הוסרו."
    if n_bad_pub:
        dups_txt += f" {n(n_bad_pub)} שורות ללא תאריך פרסום תקין לא נכללו."

    regions_list = [r for r in regions_present if r != OTHER_REGION]
    def in_(r):
        return r[1:] if r.startswith("ה") else r
    if len(regions_list) > 1:
        regions_phrase = ("ב" + ", ב".join(in_(r) for r in regions_list[:-1])
                          + " וב" + in_(regions_list[-1]))
    elif regions_list:
        regions_phrase = "ב" + in_(regions_list[0])
    else:
        regions_phrase = ""
    lede = (f"הודעות שמפרסמים בתי הדין הדתיים הדרוזיים על בקשות לצו ירושה, כדי שמי שמתנגד "
            f"יוכל להגיש התנגדות. במאגר {n(total)} הודעות שפורסמו {span}, על עזבונות של נפטרים "
            f"מ־{n(n_places)} יישובים {regions_phrase}.{lead_txt} העמוד מציג נתונים מצרפיים בלבד — "
            f"ללא שמות הנפטרים, היורשים או המבקשים וללא מספרי תיקים.")

    lm = last.to_period("M")
    monthly_note = (f"מספר ההודעות שפורסמו בכל חודש, לפי בית הדין. בחציון {med_month:.0f} הודעות "
                    f"בחודש; החודש האחרון ({MONTHS_HE[lm.month - 1]} {lm.year}) כולל פרסומים עד "
                    f"{d_he(last)}.")
    years_note = (f"הודעות לפי שנת פרסום ובית דין."
                  + (f" {last_year} חלקית — עד {d_he(last)}: {n(ytd)} הודעות, לעומת {n(prev_ytd)} "
                     f"בתקופה המקבילה אשתקד." if year_partial and prev_ytd else ""))
    weekday_note = (f"באיזה יום בשבוע מתפרסמות ההודעות. {n(n_batches)} מועדי פרסום; "
                    f"בחציון {batch_med:.0f} הודעות במועד, ובמועד הגדול ביותר {n(batch_max)}.")
    map_note = (f"כל עיגול הוא יישוב מגוריו של הנפטר; גודלו לפי מספר התיקים."
                + (f" {n(n_other_place)} תיקים מיישובים שלא זוהו אינם מוצגים במפה."
                   if n_other_place else ""))
    places_note = (f"תיקי עזבון לפי יישוב המגורים של הנפטר ({n(TOP_PLACES)} המובילים), "
                   f"בצבע לפי אזור.")
    lag_note = (f"הזמן שחלף מיום הפטירה ועד פרסום ההודעה, ב־{n(n_lag)} תיקים שבהם שני התאריכים תקינים"
                + (f"; {n(n_bad_death)} תיקים בלי תאריך פטירה תקין" if n_bad_death else "")
                + (f" ו־{n(n_neg)} שבהם תאריך הפטירה מאוחר מהפרסום (שגיאת הקלדה) לא נכללו"
                   if n_neg else (" לא נכללו" if n_bad_death else ""))
                + ".")
    lag_year_note = (f"חלוקת הבקשות לפי הזמן מהפטירה, בכל שנת פרסום (שנים עם לפחות "
                     f"{n(MIN_YEAR_LAG_N)} תיקים), באחוזים.")
    death_note = (f"שנת הפטירה של הנפטרים שעזבונם נדון; השנים שלפני {cut} מקובצות"
                  + (f" (הוותיקה ביותר: {oldest_year})" if oldest_year and older else "")
                  + ".")
    season_note = (f"חודש הפטירה, ב־{n(n_season)} תיקים עם תאריך פטירה מלא"
                   + (f" (ללא {n(n_placeholder)} תאריכים של הראשון בינואר, שנראים כתאריך משוער)"
                      if n_placeholder else "")
                   + ". חודשי החורף מודגשים.")

    lead_c = named_courts[0] if named_courts else NO_COURT
    lead_every_year = all(int(y_ct.get((y, lead_c), 0)) >= max(int(y_ct.get((y, c), 0)) for c in courts)
                          for y in years)
    labels = {
        "lede": lede,
        "dups": dups_txt.strip(),
        "ytd_kpi": f"הודעות ב־{last_year} (עד {d_dot(last)})",
        "ytd_change_kpi": f"שינוי לעומת התקופה המקבילה ב־{last_year - 1}",
        "monthly_note": monthly_note,
        "monthly_aria": (f"גרף עמודות מוערמות: הודעות ירושה לפי חודש ובית דין. "
                         f"שיא ב{MONTHS_HE[peak_p.month - 1]} {peak_p.year} עם {n(peak_v)} הודעות."),
        "years_note": years_note,
        "years_aria": (f"גרף עמודות: הודעות לפי שנה ובית דין. {court_phrase(lead_c)} מוביל"
                       + (" בכל השנים." if lead_every_year else " בסך הכול.")),
        "years_caption": "הודעות לפי שנה ובית דין",
        "weekday_note": weekday_note,
        "weekday_aria": (f"גרף עמודות: הודעות לפי יום בשבוע. יום {WEEKDAYS_HE[top_wd]} מוביל עם "
                         f"{pct(top_wd_share * 100, 0)} מההודעות."),
        "weekday_caption": "הודעות ומועדי פרסום לפי יום בשבוע",
        "map_note": map_note,
        "map_aria": "מפה אינטראקטיבית של יישובי הנפטרים לפי מספר תיקי העזבון. גרסה נגישה: ראו טבלה למטה.",
        "regions_caption": "תיקי עזבון לפי אזור",
        "places_note": places_note,
        "places_aria": (f"גרף עמודות אופקי: תיקי עזבון לפי יישוב. "
                        + (f"בראש: {known_places[0]} עם {n(p_ct[known_places[0]])} תיקים."
                           if known_places else "")),
        "places_caption": "תיקי עזבון לפי יישוב",
        "lag_note": lag_note,
        "lag_aria": (f"היסטוגרמה: הזמן מהפטירה ועד פרסום ההודעה. החציון "
                     f"{'—' if lag_med_months is None else f'{lag_med_months:.1f}'} חודשים."),
        "lag_caption": "תיקים לפי הזמן מהפטירה ועד הפרסום",
        "lag_year_note": lag_year_note,
        "lag_year_aria": "גרף עמודות מוערמות באחוזים: חלוקת הבקשות לפי הזמן מהפטירה בכל שנת פרסום.",
        "lag_year_caption": "הזמן מהפטירה לפי שנת פרסום",
        "death_note": death_note,
        "death_aria": (f"גרף עמודות: תיקי עזבון לפי שנת הפטירה. "
                       + (f"השנה הבולטת: {top_dy} עם {n(dyc.get(top_dy, 0))} תיקים; "
                          f"{n(older)} תיקים על פטירות לפני {cut}." if top_dy else "")),
        "death_caption": "תיקים לפי שנת הפטירה",
        "season_note": season_note,
        "season_aria": (f"גרף עמודות: פטירות לפי חודש. {pct(winter_share * 100, 0)} בחודשי החורף."),
        "season_caption": "פטירות לפי חודש",
        "lag_median_kpi": "חציון חודשים מהפטירה ועד ההודעה",
        "old_kpi": "בקשות על פטירות של יותר מעשר שנים",
        "places_kpi": "יישובים במאגר",
        "notice_count": "הודעות במאגר",
    }

    summary = (f"{n(total)} הודעות על בקשות לצו ירושה שפרסמו בתי הדין הדרוזיים בין "
               f"{first.year} ל־{last.year}, על עזבונות מ־{n(n_places)} יישובים"
               + (f"; החציון בין הפטירה להודעה הוא {lag_med_months:.1f} חודשים" if lag_med_months else "")
               + ". נתונים מצרפיים בלבד, ללא שמות.")

    return {
        "agent_data": {
            "summary_he": summary,
            "dataset_kind": "timeseries",
            "suggested_tags": ["ירושה", "צווי ירושה", "בתי הדין הדרוזים", "העדה הדרוזית",
                               "משפט אישי", "משרד המשפטים"],
            "related_ids": ["00044967-eda3-4942-b87c-a796b5768526",
                            "7368d9de-e3ea-43e9-9e7d-03ffffe79b5f",
                            "cdf9391c-e51d-48d7-aacc-2dade6e63c09"],
            "temporal_coverage": f"{first.year}/{last.year}",
            "spatial_coverage": f"יישובים דרוזיים {regions_phrase}".strip(),
        },
        "kpis": kpis,
        "charts": {
            "monthly": {"x": month_labels, "series": monthly_series, "zoom_start": zoom_start},
            "years": years_chart,
            "weekday": weekday_chart,
            "map": {"points": map_points},
            "places": places_chart,
            "lag": lag_chart,
            "lag_year": lag_year_chart,
            "death": {"x": death_x, "y": death_y},
            "season": season_chart,
        },
        "tables": {
            "courts": [court_phrase(c) for c in courts],
            "years": years_table,
            "weekday": weekday_table,
            "regions": regions_table,
            "places": places_table,
            "lag": lag_table,
            "lag_groups": [lab for _, lab in LAG_GROUPS],
            "lag_year": lag_year_table,
            "death": death_table,
            "season": season_table,
        },
        "flags": {
            "map": len(map_points) >= 3,
            "lag_year": len(lag_years) >= 2,
            "season": n_season >= SEASON_MIN_N,
        },
        "insights": insights,
        "labels": labels,
    }
