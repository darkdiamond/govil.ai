"""בודקי שכר מוסמכים: the Ministry of Labor's register of certified payroll
examiners. One row per examiner: first and last name, city of residence,
registration date and registration number.

Searchers come to look up an examiner (by name or city), so the page leads
with the explorer callout, then the register's story: how many joined each
year (a 2019 peak, then a long decline), where they live (a long tail of
small towns behind Jerusalem and Bnei Brak) and how registration comes in
rounds (many examiners share one registration date).

Data quirks handled:
- Registration dates arrive as "YYYY-MM-DD 00:00:00" from an XLSX. In part of
  the rows the day and month look swapped (dates later than the file's
  publication, a round of "4th of the month" dates in one batch), so the page
  aggregates by YEAR only, which a swap never changes. Month-level views and
  the latest date are not shown. A date counts as "unambiguous" when its day
  is above 12; only those decide whether the latest year is still partial.
- Rows with no parseable date stay in the totals and city counts, are left
  out of the yearly views, and the page says how many.
- Names and registration numbers are never aggregated or shown (the explorer
  under the page holds every row).

Growth: a new examiner appends a row. Years flow through (the heatmap keeps
the last HEAT_YEARS years, disclosed), city ranking is top-N, batches use
fixed size buckets.
"""
import pandas as pd
from govlib import fmt, frame

TOP_CITIES = 15
HEAT_CITIES = 8
HEAT_YEARS = 10
BIG_BATCH = 10            # a registration date shared by >= this many examiners
TREND_FLAT = 0.10         # |change| below this between full years reads as stable
MIN_TREND_N = 20         # both compared years need at least this many registrations
PEAK_DROP = 0.30          # latest full year at least this far below the peak year
SHIFT_PTS = 2.0           # share change (percentage points) for the city-shift insight
RECENT_YEARS = 3
OUTLIER_MAX = 2           # a detached year cluster with <= this many rows is a typo date
OUTLIER_GAP = 3           # years this far apart (2+ empty years between) are detached
SUMMARY_MAX = 155
NO_CITY = "לא צוין"

CITY_BUCKETS = [(1, 1, "בודק אחד"), (2, 5, "2-5"), (6, 20, "6-20"), (21, None, "21 ומעלה")]
BATCH_BUCKETS = [(1, 1, "לבד"), (2, 4, "2-4"), (5, 9, "5-9"), (10, 19, "10-19"),
                 (20, None, "20 ומעלה")]


def _n_ex(n):
    return "בודק אחד" if n == 1 else f"{n:,} בודקים"


def _n_city(n):
    return "יישוב אחד" if n == 1 else f"{n:,} יישובים"


def _pre(prefix, text):
    """ב-2019 but ביישוב: a one-letter prefix takes a hyphen before a digit."""
    text = str(text)
    return f"{prefix}-{text}" if text[:1].isdigit() else f"{prefix}{text}"


def _parse_dates(s):
    s = frame.clean_series(s)
    out = pd.to_datetime(s, errors="coerce", format="%Y-%m-%d %H:%M:%S")
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        miss = out.isna() & (s != "")
        if not miss.any():
            break
        out = out.where(~miss, pd.to_datetime(s.where(miss), errors="coerce", format=f))
    return out


def _bucket(v, buckets):
    for lo, hi, label in buckets:
        if v >= lo and (hi is None or v <= hi):
            return label
    return buckets[-1][2]


# ---------------------------------------------------------------- insights

def insight_trend(years, partial_year):
    full = [y for y in years if y["year"] != partial_year]
    if len(full) < 2:
        return None
    a, b = full[-2], full[-1]
    if min(a["n"], b["n"]) < MIN_TREND_N:
        return None
    ch = (b["n"] - a["n"]) / a["n"]
    if abs(ch) < TREND_FLAT:
        s = (f"מספר הנרשמים החדשים יציב: {b['n']:,} {_pre('ב', b['year'])} לעומת "
             f"{a['n']:,} {_pre('ב', a['year'])} ({fmt.signed_pct(ch)})")
    else:
        word = "עלייה" if ch > 0 else "ירידה"
        s = (f"{word} של {fmt.pct(abs(ch))} במספר הנרשמים החדשים: {b['n']:,} "
             f"{_pre('ב', b['year'])} לעומת {a['n']:,} {_pre('ב', a['year'])}")
    if partial_year is not None:
        s += f"; שנת {partial_year} חלקית ואינה נכללת בהשוואה"
    return s + "."


def insight_peak(years, partial_year):
    full = [y for y in years if y["year"] != partial_year]
    if len(full) < 3:
        return None
    peak = max(full, key=lambda y: (y["n"], -y["year"]))
    last = full[-1]
    if peak["year"] == last["year"] or peak["n"] == 0:
        return None
    drop = 1 - last["n"] / peak["n"]
    if drop < PEAK_DROP:
        return None
    return (f"שנת השיא ברישום הייתה {peak['year']} עם {_n_ex(peak['n'])} חדשים; "
            f"{_pre('ב', last['year'])} נרשמו {last['n']:,}, {fmt.pct(drop)} פחות מהשיא.")


def insight_partial(years, partial_year):
    if partial_year is None or not years or years[-1]["year"] != partial_year:
        return None
    n = years[-1]["n"]
    return (f"{_pre('ב', partial_year)}, שנה שעדיין לא הסתיימה בנתונים, נרשמו עד כה "
            f"{_n_ex(n)} חדשים.")


def insight_leader(cities, total):
    if len(cities) < 2 or total == 0:
        return None
    a, b = cities[0], cities[1]
    if a["n"] == b["n"]:
        return None
    s = (f"{a['city']} מובילה עם {_n_ex(a['n'])} ({fmt.pct(a['n'] / total)} מהפנקס)")
    if a["n"] >= 1.5 * b["n"]:
        s += f", פי {a['n'] / b['n']:.1f} {_pre('מ', b['city'])} שבמקום השני ({b['n']:,})"
    else:
        s += f", ואחריה {b['city']} ({b['n']:,})"
    return s + "."


def insight_tail(city_counts, total):
    n_c = len(city_counts)
    if n_c < 10 or total == 0:
        return None
    single = int((city_counts == 1).sum())
    top10 = int(city_counts.iloc[:10].sum())
    s = (f"הבודקים מפוזרים {_pre('ב', _n_city(n_c))}: עשרת היישובים הגדולים מרכזים "
         f"{fmt.pct(top10 / total)} מהם")
    if single >= 0.25 * n_c:
        s += (f", ובכ-{fmt.pct(single / n_c, 0)} מהיישובים ({single:,}) "
              "רשום בודק אחד בלבד")
    return s + "."


def insight_batches(batch_share, biggest, total):
    if total == 0 or biggest is None or biggest["n"] < BIG_BATCH:
        return None
    s = (f"הרישום נעשה במחזורים: {fmt.pct(batch_share)} מהבודקים נרשמו בתאריך שבו נרשמו "
         f"{BIG_BATCH:,} בודקים או יותר")
    s += f", והמחזור הגדול ביותר כלל {biggest['n']:,} בודקים ({biggest['when']})"
    return s + "."


def insight_shift(shift):
    if shift is None:
        return None
    up = shift["delta"] > 0
    return (f"משקלה של {shift['city']} בין הנרשמים {'עלה' if up else 'ירד'}: "
            f"{fmt.pct_of(shift['recent'])} מהנרשמים {_pre('ב', shift['recent_span'])} לעומת "
            f"{fmt.pct_of(shift['early'])} {_pre('ב', shift['early_span'])}.")


def _outlier_years(yc):
    """Years of detached clusters too small to be real: split the sorted years
    wherever OUTLIER_GAP or more years separate neighbours; the cluster with
    the most rows (ties: the later one) is the main span, and any other
    cluster holding <= OUTLIER_MAX rows is a typo date (e.g. 2206, 1926).
    A detached cluster with more rows is kept: that is a real gap."""
    ys = sorted(int(y) for y in yc.index)
    if not ys:
        return set()
    clusters, cur = [], [ys[0]]
    for y in ys[1:]:
        if y - cur[-1] >= OUTLIER_GAP:
            clusters.append(cur)
            cur = [y]
        else:
            cur.append(y)
    clusters.append(cur)
    sizes = [int(sum(int(yc[y]) for y in c)) for c in clusters]
    main = max(range(len(clusters)), key=lambda i: (sizes[i], clusters[i][-1]))
    out = set()
    for i, c in enumerate(clusters):
        if i != main and sizes[i] <= OUTLIER_MAX:
            out.update(c)
    return out


def insight_undated(undated, total, odd_years):
    if undated == 0:
        return None
    head = "לרשומה אחת" if undated == 1 else f"{_pre('ל', f'{undated:,}')} רשומות"
    why = "אין תאריך רישום תקין"
    if odd_years:
        why += (f" או שתאריך הרישום שלהן חריג (שנה מבודדת מחוץ לטווח: "
                f"{', '.join(str(y) for y in odd_years)})")
    return (f"{head} מתוך {total:,} {why}; הן נספרות בסך הכול ובפילוח "
            "היישובים, אך לא בתרשימי השנים ובמחזורי הרישום.")


# ---------------------------------------------------------------- compute

def compute(frames):
    df = frames["main"]
    city = frame.clean_series(df["city"])
    dt = _parse_dates(df["registration_date"])
    d = pd.DataFrame({"city": city.where(city != "", NO_CITY), "dt": dt})
    total = int(len(d))
    dated = d[d["dt"].notna()].copy()
    dated["year"] = dated["dt"].dt.year.astype(int)
    odd = _outlier_years(dated.groupby("year").size())
    odd_years = sorted(odd)
    dated = dated[~dated["year"].isin(odd)]
    undated = total - int(len(dated))

    # ---- years
    yc = dated.groupby("year").size()
    span = list(range(int(yc.index.min()), int(yc.index.max()) + 1)) if len(yc) else []
    dates_per_year = dated.groupby("year")["dt"].nunique()
    years = [{"year": y, "n": int(yc.get(y, 0)), "dates": int(dates_per_year.get(y, 0))}
             for y in span]
    cum = 0
    for y in years:
        cum += y["n"]
        y["cum"] = cum

    # partial latest year: its last unambiguous date (day > 12) is before December 13
    partial_year = None
    if years:
        ly = years[-1]["year"]
        un = dated[(dated["year"] == ly) & (dated["dt"].dt.day > 12)]["dt"]
        last = un.max() if len(un) else dated[dated["year"] == ly]["dt"].max()
        if (last.month, last.day) < (12, 13):
            partial_year = ly

    # ---- cities
    # a blank city is not a place: kept in the totals, left out of every city view
    cc = frame.ranked(d.loc[d["city"] != NO_CITY, "city"])
    no_city = int((d["city"] == NO_CITY).sum())
    cities = [{"city": str(k), "n": int(v)} for k, v in cc.items()]
    n_cities = len(cities)
    top = cities[:TOP_CITIES]
    single = int((cc == 1).sum())

    # city-size buckets: share of cities vs share of examiners
    bucket_rows = []
    for lo, hi, label in CITY_BUCKETS:
        sel = cc[(cc >= lo) & ((cc <= hi) if hi is not None else True)]
        bucket_rows.append({"label": label, "cities": int(len(sel)), "examiners": int(sel.sum())})
    for r in bucket_rows:
        r["city_share"] = round(100 * r["cities"] / n_cities, 1) if n_cities else 0.0
        r["ex_share"] = round(100 * r["examiners"] / total, 1) if total else 0.0

    # ---- heatmap: top cities x last HEAT_YEARS years
    heat_years = span[-HEAT_YEARS:]
    heat_cities = [c["city"] for c in cities[:HEAT_CITIES]]
    ct = dated.groupby(["city", "year"]).size()
    heat_cells, heat_rows = [], []
    for yi, c in enumerate(heat_cities):
        row = []
        for xi, y in enumerate(heat_years):
            v = int(ct.get((c, y), 0))
            heat_cells.append([xi, yi, v])
            row.append(f"{v:,}")
        heat_rows.append([c] + row)
    heat_max = max([c[2] for c in heat_cells], default=0)
    heat_trimmed = len(span) > len(heat_years)

    # ---- registration batches (examiners sharing a registration date)
    per_date = dated.groupby("dt").size()
    size_of = dated["dt"].map(per_date)
    batch_rows = []
    for lo, hi, label in BATCH_BUCKETS:
        m = (size_of >= lo) & ((size_of <= hi) if hi is not None else True)
        batch_rows.append({"label": label, "n": int(m.sum())})
    n_dated = int(len(dated))
    for r in batch_rows:
        r["share"] = round(100 * r["n"] / n_dated, 1) if n_dated else 0.0
    batch_share = float((size_of >= BIG_BATCH).sum()) / n_dated if n_dated else 0.0
    biggest = None
    if len(per_date):
        pdx = per_date.reset_index(name="n").sort_values(["n", "dt"], ascending=[False, True],
                                                         kind="stable")
        b = pdx.iloc[0]
        ts = b["dt"]
        when = fmt.d_he(ts) if ts.day > 12 else f"{_pre('ב', ts.year)}"
        biggest = {"n": int(b["n"]), "when": when}
    n_dates = int(len(per_date))

    # ---- city share shift: recent RECENT_YEARS full years vs earlier years
    shift = None
    full_years = [y["year"] for y in years if y["year"] != partial_year]
    if len(full_years) >= RECENT_YEARS + 2:
        recent = full_years[-RECENT_YEARS:]
        early = [y for y in full_years if y < recent[0]]
        r_df = dated[dated["year"].isin(recent)]
        e_df = dated[dated["year"].isin(early)]
        if len(r_df) and len(e_df):
            rs = r_df["city"].value_counts() / len(r_df) * 100
            es = e_df["city"].value_counts() / len(e_df) * 100
            best = None
            for c in [c["city"] for c in cities[:10]]:
                rv, ev = float(rs.get(c, 0.0)), float(es.get(c, 0.0))
                delta = round(rv - ev, 6)
                key = (abs(delta), c)
                if abs(delta) >= SHIFT_PTS and (best is None or key[0] > best[0] or
                                                (key[0] == best[0] and c < best[1])):
                    best = (abs(delta), c, rv, ev, delta)
            if best:
                shift = {"city": best[1], "recent": best[2], "early": best[3], "delta": best[4],
                         "recent_span": f"{recent[0]}-{recent[-1]}",
                         "early_span": (f"{early[0]}-{early[-1]}" if len(early) > 1
                                        else str(early[0]))}

    rules = [
        ("trend", insight_trend(years, partial_year)),
        ("peak", insight_peak(years, partial_year)),
        ("partial", insight_partial(years, partial_year)),
        ("leader", insight_leader(cities, total)),
        ("tail", insight_tail(cc, total)),
        ("shift", insight_shift(shift)),
        ("batches", insight_batches(batch_share, biggest, total)),
        ("undated", insight_undated(undated, total, odd_years)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # ---- KPIs
    kpis, kl, order = {}, {}, []

    def add(key, value, display, label, tone="brand"):
        kpis[key] = {"value": value, "display": display, "tone": tone}
        kl[key] = label
        order.append(key)

    add("total", total, f"{total:,}", "בודקי שכר רשומים בפנקס")
    add("cities", n_cities, f"{n_cities:,}", "יישובי מגורים")
    full = [y for y in years if y["year"] != partial_year]
    if full:
        last = full[-1]
        tone = "brand"
        if len(full) >= 2 and full[-2]["n"]:
            ch = (last["n"] - full[-2]["n"]) / full[-2]["n"]
            tone = "ok" if ch >= TREND_FLAT else ("warn" if ch <= -TREND_FLAT else "brand")
        add("last_year", last["n"], f"{last['n']:,}", f"נרשמו {_pre('ב', last['year'])}", tone)
        peak = max(full, key=lambda y: (y["n"], -y["year"]))
        add("peak", peak["year"], str(peak["year"]),
            f"שנת השיא ({peak['n']:,} נרשמים)", "info")
    if cities:
        add("top_city", cities[0]["n"], f"{cities[0]['n']:,}",
            f"בודקים {_pre('ב', cities[0]['city'])}, היישוב המוביל")
    add("single", single, f"{single:,}", "יישובים עם בודק אחד בלבד")

    # ---- charts
    year_labels = [str(y["year"]) for y in years]
    chart_years = {
        "labels": year_labels,
        "values": [y["n"] for y in years],
        "dates": [y["dates"] for y in years],
        "partial": [y["year"] == partial_year for y in years],
        "cum": [y["cum"] for y in years],
    }
    tasc = top[::-1]
    chart_cities = {"labels": [c["city"] for c in tasc], "values": [c["n"] for c in tasc],
                    "shares": [round(100 * c["n"] / total, 1) if total else 0 for c in tasc]}
    chart_buckets = {"labels": [r["label"] for r in bucket_rows],
                     "cities": [r["city_share"] for r in bucket_rows],
                     "examiners": [r["ex_share"] for r in bucket_rows],
                     "n_cities": [r["cities"] for r in bucket_rows],
                     "n_examiners": [r["examiners"] for r in bucket_rows]}
    chart_heat = {"years": [str(y) for y in heat_years], "cities": heat_cities[::-1],
                  "cells": [[x, len(heat_cities) - 1 - y, v] for x, y, v in heat_cells],
                  "max": heat_max}
    chart_batches = {"labels": [r["label"] for r in batch_rows],
                     "values": [r["n"] for r in batch_rows],
                     "shares": [r["share"] for r in batch_rows]}

    # ---- text
    first, lastyr = (years[0]["year"], years[-1]["year"]) if years else (None, None)
    since = f" מאז {first}" if first else ""
    summary = (f"איתור בודק שכר מוסמך לפי שם או יישוב: {total:,} בודקי שכר רשומים בפנקס "
               f"של משרד העבודה{since}, {_pre('ב', _n_city(n_cities))}.")
    if len(summary) > SUMMARY_MAX:
        summary = f"איתור בודק שכר מוסמך לפי שם או יישוב: {total:,} בודקים רשומים בפנקס."

    lede = (f"פנקס בודקי השכר המוסמכים של משרד העבודה מונה {_n_ex(total)}"
            + (f" שנרשמו בין {first} ל-{lastyr}" if first and first != lastyr else "")
            + f", המתגוררים {_pre('ב', _n_city(n_cities))}. בודק שכר מוסמך רשאי לערוך "
            "בדיקת שכר ולחתום על דוח בדיקה (ביקורת שכר), שבו נבחן אם המעסיק משלם לעובדיו "
            "את השכר ואת הזכויות על פי חוקי העבודה. כאן אפשר לבדוק אם בודק רשום בפנקס, "
            "ולראות כמה נרשמו בכל שנה והיכן הם מתגוררים.")

    years_lede = ""
    if years:
        pk = max(years, key=lambda y: (y["n"], -y["year"]))
        years_lede = (f"מספר הבודקים שנרשמו בפנקס בכל שנה. השיא {_pre('ב', pk['year'])} "
                      f"({pk['n']:,})")
        if partial_year is not None:
            years_lede += f"; שנת {partial_year} חלקית ומסומנת בצבע אחר"
        years_lede += ". בריחוף מוצג גם מספר תאריכי הרישום השונים באותה שנה."
    cum_lede = (f"גודל הפנקס המצטבר לפי שנת הרישום: מ-{years[0]['cum']:,} בסוף "
                f"{years[0]['year']} עד {years[-1]['cum']:,} כיום. הספירה כוללת רק את "
                "הבודקים המופיעים כיום ברשימה"
                + (", ורק את אלה שיש להם תאריך רישום תקין." if undated else ".") if years else "")
    cities_lede = ""
    if cities:
        shown = int(sum(c["n"] for c in top))
        cities_lede = (f"{len(top):,} היישובים עם מספר הבודקים הגדול ביותר, לפי יישוב המגורים "
                       f"הרשום בפנקס. יחד הם מרכזים {fmt.pct(shown / total)} מהבודקים; "
                       f"השאר מתפזרים בין {_n_city(max(n_cities - len(top), 0))} נוספים."
                       + (f" {_pre('ל', _n_ex(no_city))} לא צוין יישוב." if no_city else ""))
    bucket_lede = ""
    if n_cities:
        b0 = bucket_rows[0]
        bl = bucket_rows[-1]
        bucket_lede = (f"היישובים לפי מספר הבודקים בהם: {fmt.pct_of(b0['city_share'])} מהיישובים "
                       f"מונים בודק אחד בלבד, ואילו {_n_city(bl['cities'])} עם "
                       f"{CITY_BUCKETS[-1][0]:,} בודקים ומעלה מרכזים "
                       f"{fmt.pct_of(bl['ex_share'])} מהבודקים.")
    heat_lede = (f"מספר הנרשמים בכל שנה {_pre('ב', f'{len(heat_cities):,}')} היישובים הגדולים. "
                 + (f"מוצגות {len(heat_years):,} השנים האחרונות. " if heat_trimmed else "")
                 + "תא כהה יותר מציין יותר נרשמים.")
    together = 1 - (batch_rows[0]["share"] / 100) if n_dated else 0.0
    batch_lede = f"בפנקס {n_dates:,} תאריכי רישום שונים {_pre('ל', _n_ex(n_dated))} עם תאריך"
    if together > 0.5:
        batch_lede += f", ו-{fmt.pct(together)} מהבודקים נרשמו יחד עם בודקים נוספים באותו תאריך"
    batch_lede += (f". התרשים מחלק את הבודקים לפי מספר הנרשמים בתאריך שבו נרשמו "
                  f"({fmt.pct(batch_share)} נרשמו בתאריך של {BIG_BATCH:,} נרשמים ומעלה).")

    years_aria = ""
    if years:
        pk = max(years, key=lambda y: (y["n"], -y["year"]))
        years_aria = (f"תרשים עמודות: נרשמים חדשים לפנקס בכל שנה, {first}-{lastyr}. "
                      f"השיא {_pre('ב', pk['year'])} עם {pk['n']:,}.")
    cum_aria = (f"תרשים קו: גודל הפנקס המצטבר לפי שנת רישום, עד {years[-1]['cum']:,} בודקים."
                if years else "")
    cities_aria = (f"תרשים עמודות אופקי: {len(top):,} היישובים המובילים במספר הבודקים. "
                   f"המוביל: {cities[0]['city']} ({cities[0]['n']:,})." if cities else "")
    bucket_aria = (f"תרשים עמודות: שיעור היישובים ושיעור הבודקים לפי גודל היישוב בפנקס. "
                   f"{_n_city(single)} עם בודק אחד בלבד.")
    heat_aria = (f"מפת חום: נרשמים לפי שנה {_pre('ב', f'{len(heat_cities):,}')} היישובים "
                 f"הגדולים. הערך הגבוה בתא אחד: {heat_max:,}.")
    batch_aria = (f"תרשים עמודות: בודקים לפי מספר הנרשמים בתאריך הרישום שלהם. "
                  f"{fmt.pct(batch_share)} נרשמו בתאריך של {BIG_BATCH:,} נרשמים ומעלה.")

    agent_data = {
        "summary_he": summary,
        "dataset_kind": "registry",
        "spatial_coverage": "ישראל",
    }
    if first:
        agent_data["temporal_coverage"] = f"{first}/{lastyr}"

    return {
        "agent_data": agent_data,
        "kpis": kpis,
        "kpi_order": order,
        "charts": {"years": chart_years, "cities": chart_cities, "buckets": chart_buckets,
                   "heat": chart_heat, "batches": chart_batches},
        "insights": insights,
        "tables": {
            "years": [[y["year"], f"{y['n']:,}" + (" (חלקית)" if y["year"] == partial_year else ""),
                       f"{y['dates']:,}", f"{y['cum']:,}"] for y in years],
            "cities": [[c["city"], f"{c['n']:,}", fmt.pct(c["n"] / total)] for c in top],
            "buckets": [[r["label"], f"{r['cities']:,}", fmt.pct_of(r["city_share"]),
                         f"{r['examiners']:,}", fmt.pct_of(r["ex_share"])] for r in bucket_rows],
            "heat_cols": ["יישוב"] + [str(y) for y in heat_years],
            "heat": heat_rows,
            "batches": [[r["label"], f"{r['n']:,}", fmt.pct_of(r["share"])] for r in batch_rows],
        },
        "flags": {"has_years": len(years) >= 2, "has_cities": len(cities) >= 2,
                  "has_buckets": n_cities >= 10, "has_heat": len(heat_cities) >= 3 and
                  len(heat_years) >= 3, "has_batches": n_dated >= 20,
                  "has_undated": undated > 0},
        "labels": {
            **{f"kpi_{k}": v for k, v in kl.items()},
            "lede": lede,
            "years_lede": years_lede, "years_aria": years_aria,
            "years_caption": "נרשמים חדשים, תאריכי רישום ומספר מצטבר לפי שנה.",
            "cum_lede": cum_lede, "cum_aria": cum_aria,
            "cities_lede": cities_lede, "cities_aria": cities_aria,
            "cities_caption": "היישובים המובילים במספר בודקי השכר הרשומים.",
            "bucket_lede": bucket_lede, "bucket_aria": bucket_aria,
            "bucket_caption": "יישובים ובודקים לפי מספר הבודקים ביישוב.",
            "heat_lede": heat_lede, "heat_aria": heat_aria,
            "heat_caption": "נרשמים לפי שנה ביישובים הגדולים.",
            "batch_lede": batch_lede, "batch_aria": batch_aria,
            "batch_caption": "בודקים לפי מספר הנרשמים בתאריך הרישום שלהם.",
            "undated_note": (f"{_n_ex(undated)} ללא תאריך רישום תקין"
                             + (" או עם תאריך חריג" if odd_years else "")
                             + (" אינו נכלל בתרשים." if undated == 1 else " אינם נכללים בתרשים.")
                             if undated else ""),
        },
    }
