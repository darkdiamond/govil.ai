"""פנקס העובדים הסוציאליים — the Ministry of Welfare register of social workers.

One row per registered social worker (~49k): surname, first name, registration
number, registration date and settlement of residence. There is no status
column, so every row is a current register entry. "Now" is the latest
registration date in the data (its vintage), never the wall clock; that year
is partial unless the date reaches late December.

Registration numbers are individual identifiers and never reach the page
(only the highest number vs. the row count, in aggregate). Names are used
only in aggregate (most common surnames / first names). Settlement spellings
vary in the source; they are folded on a normalized key and shown under their
most common spelling.
"""
import re

import pandas as pd

UNKNOWN_CITY = {"", "לא רשום", "ללא ישוב"}
TOP_CITIES = 15
TOP_SHIFT = 8
TOP_NAMES = 15
HEAT_YEARS = 12
RECENT_YEARS = 10
MIN_PERIOD = 1000
ZOOM_FROM = 1985
SENIORITY = [(0, 4), (5, 9), (10, 14), (15, 19), (20, 24), (25, 29), (30, 39), (40, None)]
LRI, PDI = "⁦", "⁩"
MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
MONTHS_SHORT = ["ינו׳", "פבר׳", "מרץ", "אפר׳", "מאי", "יוני", "יולי",
                "אוג׳", "ספט׳", "אוק׳", "נוב׳", "דצמ׳"]
# pandas dayofweek: Monday=0 .. Sunday=6 -> Hebrew week order, Sunday first.
DOW_ORDER = [6, 0, 1, 2, 3, 4, 5]
DOW_HE = {6: "ראשון", 0: "שני", 1: "שלישי", 2: "רביעי", 3: "חמישי", 4: "שישי", 5: "שבת"}


def n(v):
    return f"{int(v):,}"


def pct(v, digits=1):
    return f"{LRI}{v:.{digits}f}%{PDI}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def _city_display(s):
    s = re.sub(r"\s+", " ", s.strip())
    return re.sub(r"\s*-\s*", "-", s)


def _city_key(s):
    k = re.sub(r"[\s\-–\"'״׳]", "", s)
    return k.replace("וו", "ו").replace("יי", "י")


def _sorted_counts(s):
    return s.value_counts().sort_index().sort_values(ascending=False, kind="stable")


def _period(year):
    if year < 2000:
        return "עד 1999"
    return f"שנות ה-{year // 10 * 10}"


def _prepare(df):
    out = pd.DataFrame({
        "date": pd.to_datetime(df["תאריך רישום"].str.strip().str[:10], errors="coerce",
                               format="%Y-%m-%d"),
        "first": df["שם-פרטי"].str.strip(),
        "last": df["שם-משפחה"].str.strip(),
        "num": pd.to_numeric(df["מספר רישום"].str.replace(",", "", regex=False),
                             errors="coerce"),
    })
    city = df["ישוב מגורים"].map(_city_display)
    known = ~city.isin(UNKNOWN_CITY)
    key = city.map(_city_key)
    variants = (pd.DataFrame({"key": key[known], "city": city[known]})
                .groupby(["key", "city"]).size().reset_index(name="n")
                .sort_values(["key", "n", "city"], ascending=[True, False, True]))
    canon = variants.drop_duplicates("key").set_index("key")["city"]
    out["city"] = key.map(canon).where(known, "")
    out["year"] = out["date"].dt.year
    return out


def insight_growth(per_year, last_full):
    base = last_full - 10
    if base not in per_year.index or last_full not in per_year.index:
        return None
    a, b = int(per_year[base]), int(per_year[last_full])
    if a < 100 or b < 1.3 * a:
        return None
    return (f"קצב ההצטרפות לפנקס גדל: ב-{last_full} נרשמו {n(b)} עובדים סוציאליים, "
            f"פי {b / a:.1f} מ-{base} ({n(a)}).")


def insight_peak(per_year, last_full):
    full = per_year[per_year.index <= last_full]
    if len(full) < 10 or last_full not in full.index:
        return None
    peak = int(full.idxmax())
    pv, lv = int(full[peak]), int(full[last_full])
    if peak == last_full:
        return f"{last_full} היא שנת השיא ברישום: {n(lv)} עובדים סוציאליים חדשים בפנקס."
    drop = 1 - lv / pv
    if abs(drop) < 0.1:
        return (f"שנת השיא ברישום הייתה {peak} ({n(pv)} נרשמים); ב-{last_full} נרשמו "
                f"{n(lv)} — קרוב לשיא.")
    return (f"שנת השיא ברישום הייתה {peak}, עם {n(pv)} נרשמים; ב-{last_full} נרשמו "
            f"{n(lv)} — {pct(drop * 100, 0)} פחות מהשיא.")


def insight_ytd(df, ref, partial):
    if not partial:
        return None
    y = ref.year
    cur = df[(df["year"] == y) & (df["date"] <= ref)]
    md = (df["date"].dt.month * 100 + df["date"].dt.day) <= (ref.month * 100 + ref.day)
    prev = df[(df["year"] == y - 1) & md]
    if len(prev) < 50:
        return None
    c, p = len(cur), len(prev)
    chg = c / p - 1
    if round(abs(chg) * 100) == 0:
        trend = f"בדומה לתקופה המקבילה ב-{y - 1} ({n(p)})"
    else:
        trend = (f"{pct(abs(chg) * 100, 0)} {'יותר' if chg > 0 else 'פחות'} מבתקופה המקבילה "
                 f"ב-{y - 1} ({n(p)})")
    return f"מתחילת {y} ועד {d_he(ref)} נרשמו {n(c)} עובדים סוציאליים — {trend}."


def insight_season(month_share, y0, y1):
    top = month_share.sort_values(ascending=False, kind="stable").head(3)
    share = float(top.sum())
    if share < 40:
        return None
    months = [MONTHS_HE[int(m) - 1] for m in sorted(top.index)]
    return (f"הרישום מרוכז בסתיו: {months[0]}, {months[1]} ו{months[2]} מרכזים "
            f"{pct(share, 0)} מהרישומים בשנים {y0} עד {y1}, ו{MONTHS_HE[int(top.index[0]) - 1]} לבדו "
            f"{pct(float(top.iloc[0]), 0)}.")


def insight_dow(dow_counts):
    tot = dow_counts.sum()
    if tot < 500:
        return None
    top = dow_counts.sort_values(ascending=False, kind="stable")
    d, v = int(top.index[0]), int(top.iloc[0])
    if v / tot < 0.2:
        return None
    weekend = int(dow_counts.get(4, 0) + dow_counts.get(5, 0))
    wk = weekend / tot * 100
    wk_txt = "פחות מאחוז אחד" if wk < 1 else pct(wk, 0)
    return (f"יום {DOW_HE[d]} הוא יום הרישום הנפוץ ביותר: {pct(v / tot * 100, 0)} מהרישומים; "
            f"בימי שישי ושבת נרשמים רק {wk_txt}.")


def insight_cities(cities, known_total):
    if known_total == 0 or len(cities) < 5:
        return None
    top, v = cities.index[0], int(cities.iloc[0])
    if v / known_total < 0.05:
        return None
    top5 = cities.head(5)
    names = ", ".join(top5.index[1:4]) + " ו" + top5.index[4]
    return (f"{top} מובילה עם {n(v)} עובדים סוציאליים רשומים ({pct(v / known_total * 100)} "
            f"מהרשומים שישובם ידוע); יחד עם {names} מרכזים חמשת הישובים הגדולים "
            f"{pct(top5.sum() / known_total * 100)}.")


def insight_shift(shift_names, shift_vals, periods):
    if len(periods) < 2:
        return None
    first, last = periods[1] if len(periods) > 2 else periods[0], periods[-1]
    fi, li = periods.index(first), periods.index(last)
    deltas = [(shift_vals[li][i] - shift_vals[fi][i], nm) for i, nm in enumerate(shift_names)]
    up = max(deltas, key=lambda t: (t[0], t[1]))
    if up[0] < 2:
        return None
    i = shift_names.index(up[1])
    s = (f"{up[1]} הגדילה את חלקה בין הנרשמים החדשים: {pct(shift_vals[li][i])} מהנרשמים ב{last} "
         f"לעומת {pct(shift_vals[fi][i])} ב{first}")
    down = min(deltas, key=lambda t: (t[0], t[1]))
    if down[0] <= -1:
        j = shift_names.index(down[1])
        s += f"; {down[1]} ירדה מ-{pct(shift_vals[fi][j])} ל-{pct(shift_vals[li][j])}"
    return s + "."


def insight_seniority(sen):
    s = sen.dropna()
    if len(s) < 100:
        return None
    return (f"הוותק החציוני בפנקס הוא {int(s.median())} שנים מאז הרישום; "
            f"{pct((s < 10).mean() * 100, 0)} נרשמו בעשור האחרון, ו-{pct((s >= 30).mean() * 100, 0)} "
            f"רשומים בפנקס 30 שנה ומעלה.")


def insight_busiest(df):
    vc = df["date"].value_counts().sort_index().sort_values(ascending=False, kind="stable")
    if len(vc) < 2 or int(vc.iloc[0]) < 100:
        return None
    day, v = vc.index[0], int(vc.iloc[0])
    return (f"היום עם מספר הרישומים הגבוה ביותר בפנקס הוא {d_he(day)}: {n(v)} עובדים "
            f"סוציאליים נרשמו בו ביום.")


def insight_unknown(unknown, total):
    if total == 0 or unknown / total < 0.005:
        return None
    return (f"ל-{n(unknown)} רשומות ({pct(unknown / total * 100)}) אין ישוב מגורים ידוע "
            f"(\"לא רשום\" או ריק); הן אינן נכללות בגרפי הישובים.")


def insight_numbers(df):
    nums = df["num"].dropna()
    if len(nums) < 100:
        return None
    mx, cnt = int(nums.max()), int(nums.nunique())
    gap = mx - cnt
    if gap < 100:
        return None
    return (f"מספרי הרישום מגיעים עד {n(mx)}, אך בקובץ {n(cnt)} רישומים מובחנים — "
            f"{n(gap)} מספרים בטווח אינם מופיעים בפנקס הנוכחי.")


def insight_surname(surnames, total):
    if len(surnames) < 2:
        return None
    (a, va), (b, vb) = list(surnames.items())[:2]
    if va < 1.3 * vb:
        return None
    return (f"שם המשפחה הנפוץ ביותר בפנקס הוא {a} ({n(va)} רשומות, "
            f"{pct(va / total * 100)}), ואחריו {b} ({n(vb)}).")


def compute(frames):
    df = _prepare(frames["register"])
    total = len(df)
    dated = df.dropna(subset=["date"])
    ref = dated["date"].max()
    ref_year = int(ref.year)
    partial = not (ref.month == 12 and ref.day >= 24)
    last_full = ref_year - 1 if partial else ref_year
    first_year = int(dated["year"].min())

    years = list(range(first_year, ref_year + 1))
    per_year = dated.groupby("year").size().reindex(years, fill_value=0)
    per_year.index = per_year.index.astype(int)
    cum = per_year.cumsum()

    # Seasonality + weekday over the last RECENT_YEARS full years.
    y0 = last_full - RECENT_YEARS + 1
    win = dated[(dated["year"] >= y0) & (dated["year"] <= last_full)]
    mshare = (win["date"].dt.month.value_counts(normalize=True) * 100).reindex(range(1, 13), fill_value=0.0)
    mcount = win["date"].dt.month.value_counts().reindex(range(1, 13), fill_value=0)
    dow_counts = dated[dated["year"] >= y0]["date"].dt.dayofweek.value_counts().reindex(range(7), fill_value=0)

    # Heatmap, last HEAT_YEARS years.
    hy = list(range(ref_year - HEAT_YEARS + 1, ref_year + 1))
    hd = dated[dated["year"].isin(hy)]
    hm = hd.groupby([hd["year"].astype(int), hd["date"].dt.month]).size()
    cells = []
    for yi, y in enumerate(hy):
        for m in range(1, 13):
            if y == ref_year and m > ref.month:
                continue
            cells.append([m - 1, yi, int(hm.get((y, m), 0))])

    # Seniority of every registrant, in years since registration.
    sen = (ref_year - df["year"]).where(df["year"].notna())
    sen_rows = []
    for lo, hi in SENIORITY:
        m = sen >= lo
        if hi is not None:
            m &= sen <= hi
        sen_rows.append((f"{lo} ומעלה" if hi is None else (f"עד {hi}" if lo == 0 else f"{lo} עד {hi}"), int(m.sum())))

    # Settlements.
    known = df[df["city"] != ""]
    cities = _sorted_counts(known["city"])
    top_c = list(cities.head(TOP_CITIES).index)
    unknown_city = total - len(known)

    # City mix by registration period.
    kd = known.dropna(subset=["year"]).copy()
    kd["period"] = kd["year"].astype(int).map(_period)
    pcount = kd["period"].value_counts()
    periods = sorted([p for p, c in pcount.items() if c >= MIN_PERIOD],
                     key=lambda p: 0 if p == "עד 1999" else int(p.split("-")[-1]))
    shift_names = list(cities.head(TOP_SHIFT).index)
    shift_vals = []
    for p in periods:
        sub = kd[kd["period"] == p]
        vc = sub["city"].value_counts()
        shift_vals.append([round(float(vc.get(c, 0)) / len(sub) * 100, 1) for c in shift_names])

    surnames = _sorted_counts(df.loc[df["last"] != "", "last"])
    recent_first = df[(df["first"] != "") & (df["year"] >= ref_year - RECENT_YEARS + 1)]
    firsts_recent = _sorted_counts(recent_first["first"])

    charts = {
        "years": {"x": [str(y) for y in years], "y": [int(v) for v in per_year.values],
                  "zoom_from": years.index(ZOOM_FROM) if ZOOM_FROM in years else 0,
                  "partial_last": bool(partial)},
        "cumulative": {"x": [str(y) for y in years], "y": [int(v) for v in cum.values]},
        "season": {"x": MONTHS_SHORT, "y": [round(float(v), 1) for v in mshare.values]},
        "heat": {"x": MONTHS_SHORT, "y": [str(y) for y in hy], "cells": cells,
                 "max": max([c[2] for c in cells] or [1])},
        "dow": {"x": [DOW_HE[d] for d in DOW_ORDER], "y": [int(dow_counts[d]) for d in DOW_ORDER]},
        "seniority": {"names": [k for k, _ in sen_rows], "values": [v for _, v in sen_rows]},
        "cities": {"names": top_c, "values": [int(cities[c]) for c in top_c]},
        "cityshift": {"names": shift_names, "periods": periods,
                      "series": [{"name": p, "data": shift_vals[i]} for i, p in enumerate(periods)]},
        "surnames": {"names": list(surnames.head(TOP_NAMES).index),
                     "values": [int(v) for v in surnames.head(TOP_NAMES).values]},
        "firsts": {"names": list(firsts_recent.head(TOP_NAMES).index),
                   "values": [int(v) for v in firsts_recent.head(TOP_NAMES).values]},
    }

    rules = [
        ("growth", insight_growth(per_year, last_full)),
        ("peak", insight_peak(per_year, last_full)),
        ("ytd", insight_ytd(dated, ref, partial)),
        ("season", insight_season(mshare, y0, last_full)),
        ("dow", insight_dow(dow_counts)),
        ("cities", insight_cities(cities, len(known))),
        ("shift", insight_shift(shift_names, shift_vals, periods)),
        ("seniority", insight_seniority(sen)),
        ("busiest", insight_busiest(dated)),
        ("numbers", insight_numbers(df)),
        ("unknown", insight_unknown(unknown_city, total)),
        ("surname", insight_surname(surnames, total)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    lf = int(per_year.get(last_full, 0))
    lp = int(per_year.get(last_full - 1, 0))
    chg = (lf / lp - 1) if lp else 0
    new_tone = "ok" if chg >= 0.05 else ("warn" if chg <= -0.05 else "brand")
    sv = sen.dropna()
    med = int(sv.median()) if len(sv) else 0
    kpis = {
        "total": {"value": total, "display": n(total), "tone": "brand"},
        "new": {"value": lf, "display": n(lf), "tone": new_tone},
        "median": {"value": med, "display": n(med), "tone": "brand"},
        "cities": {"value": int(cities.size), "display": n(cities.size), "tone": "brand"},
    }
    if not lp or round(abs(chg) * 100) == 0:
        chg_txt = ", ללא שינוי לעומת השנה שקדמה" if lp else ""
    else:
        chg_txt = f", {'עלייה' if chg >= 0 else 'ירידה'} של {abs(chg) * 100:.0f}% לעומת {last_full - 1}"

    partial_note = f" {ref_year} — שנה חלקית, עד {d_he(ref)}." if partial else ""
    top_m = int(mshare.idxmax())
    labels = {
        "lede": (f"פנקס העובדים הסוציאליים של משרד הרווחה והביטחון החברתי: {n(total)} עובדים "
                 f"סוציאליים רשומים מ-{n(cities.size)} ישובים. הרישום המוקדם במאגר הוא מ-{first_year}, "
                 f"והאחרון מ-{d_he(ref)}."),
        "new_kpi": f"נרשמו ב-{last_full}{chg_txt}",
        "median_kpi": "חציון שנות ותק בפנקס",
        "cities_kpi": "ישובי מגורים",
        "years_note": (f"מספר העובדים הסוציאליים שנרשמו בפנקס בכל שנה. ניתן לגלול ולהגדיל את טווח "
                       f"השנים.{partial_note}"),
        "years_aria": (f"גרף עמודות: רישומים חדשים בפנקס בכל שנה מ-{first_year} עד {ref_year}; שיא ב-"
                       f"{int(per_year[per_year.index <= last_full].idxmax())}."),
        "cum_note": f"גודל הפנקס המצטבר: כמה עובדים סוציאליים נרשמו עד כל שנה, מ-{first_year} עד {ref_year}.",
        "cum_aria": f"גרף קו: מספר הרישומים המצטבר בפנקס עד כל שנה, עד {n(total)}.",
        "season_note": (f"חלקו של כל חודש בסך הרישומים בשנים {y0} עד {last_full}. "
                        f"החודש הגבוה ביותר: {MONTHS_HE[top_m - 1]}."),
        "season_aria": f"גרף עמודות: חלק החודש מהרישומים, {y0} עד {last_full}; שיא ב{MONTHS_HE[top_m - 1]}.",
        "season_caption": "שיעור הרישומים לפי חודש קלנדרי.",
        "heat_note": f"מספר הרישומים בכל חודש, {hy[0]} עד {ref_year}.",
        "heat_aria": f"מפת חום: רישומים חדשים לפי חודש ושנה, {hy[0]} עד {ref_year}.",
        "dow_note": f"מספר הרישומים לפי יום בשבוע, {y0} עד {ref_year}.",
        "dow_aria": f"גרף עמודות: רישומים לפי יום בשבוע, {y0} עד {ref_year}.",
        "dow_caption": "מספר רישומים לפי יום בשבוע.",
        "seniority_note": f"שנים מאז הרישום, נכון ל-{ref_year}, בקרב כלל הרשומים בפנקס.",
        "seniority_aria": f"גרף עמודות: רשומים בפנקס לפי ותק, חציון {med} שנים.",
        "seniority_caption": "מספר רשומים לפי קבוצת ותק בשנים.",
        "cities_note": (f"{TOP_CITIES} הישובים עם מספר העובדים הסוציאליים הרשומים הגדול ביותר. "
                        f"איות שמות הישובים במקור אוחד"
                        + (f"; {n(unknown_city)} רשומות ללא ישוב ידוע אינן נכללות." if unknown_city else ".")),
        "cities_aria": (f"גרף עמודות אופקי: {TOP_CITIES} הישובים המובילים — "
                        f"{top_c[0]} בראש עם {n(cities.iloc[0])} רשומים."),
        "cities_caption": f"רשומים לפי ישוב ({TOP_CITIES} המובילים).",
        "shift_note": (f"חלקם של {TOP_SHIFT} הישובים הגדולים מכלל הנרשמים בכל תקופת רישום (באחוזים). "
                       f"ישוב המגורים הוא הרשום בפנקס כיום."),
        "shift_aria": f"גרף עמודות מקובצות: חלק {TOP_SHIFT} הישובים הגדולים בין הנרשמים, לפי תקופת רישום.",
        "shift_caption": "שיעור הנרשמים בכל ישוב, לפי תקופת רישום.",
        "surnames_note": f"{TOP_NAMES} שמות המשפחה הנפוצים בפנקס.",
        "surnames_aria": f"גרף עמודות אופקי: {TOP_NAMES} שמות המשפחה הנפוצים — {surnames.index[0]} בראש.",
        "surnames_caption": "מספר רשומים לפי שם משפחה.",
        "firsts_note": f"{TOP_NAMES} השמות הפרטיים הנפוצים בקרב מי שנרשמו ב-{ref_year - RECENT_YEARS + 1} עד {ref_year}.",
        "firsts_aria": f"גרף עמודות אופקי: {TOP_NAMES} השמות הפרטיים הנפוצים בקרב נרשמים מ-{ref_year - RECENT_YEARS + 1} ואילך.",
        "firsts_caption": "מספר נרשמים לפי שם פרטי.",
    }
    tables = {
        "season": [{"name": MONTHS_HE[i], "count": n(mcount[i + 1]),
                    "share": f"{mshare[i + 1]:.1f}%"} for i in range(12)],
        "dow": [{"name": DOW_HE[d], "count": n(dow_counts[d])} for d in DOW_ORDER],
        "seniority": [{"bucket": k, "count": n(v)} for k, v in sen_rows],
        "cities": [{"name": c, "count": n(cities[c]),
                    "share": f"{cities[c] / len(known) * 100:.1f}%"} for c in top_c],
        "shift": [{"name": nm, "vals": [f"{shift_vals[i][j]:.1f}%" for i in range(len(periods))]}
                  for j, nm in enumerate(shift_names)],
        "shift_cols": periods,
        "surnames": [{"name": k, "count": n(v)} for k, v in surnames.head(TOP_NAMES).items()],
        "firsts": [{"name": k, "count": n(v)} for k, v in firsts_recent.head(TOP_NAMES).items()],
    }

    return {
        "agent_data": {
            "summary_he": (f"פנקס העובדים הסוציאליים: {n(total)} עובדים סוציאליים רשומים, "
                           f"מ-{n(cities.size)} ישובים — תאריכי רישום מ-{first_year} ועד {ref_year}, "
                           f"עונתיות ופיזור גאוגרפי."),
            "dataset_kind": "registry",
            "related_ids": ["fa11b2f3-0796-48f8-ab84-e5540ea2b014", "87d2955a-9b63-406b-8deb-aa75f6a898f0", "56639c97-30ba-4307-a768-9f4b1655c68a"],
            "suggested_tags": ["עובדים סוציאליים", "רישום מקצועי", "רווחה", "כוח אדם",
                               "מרשמים מקצועיים"],
            "temporal_coverage": f"{first_year}/{ref.strftime('%Y-%m-%d')}",
            "spatial_coverage": "ישראל",
        },
        "kpis": kpis,
        "charts": charts,
        "tables": tables,
        "insights": insights,
        "labels": labels,
        "flags": {"has_shift": len(periods) >= 2},
    }
