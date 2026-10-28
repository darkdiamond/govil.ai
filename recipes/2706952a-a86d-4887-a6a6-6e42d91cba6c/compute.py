"""מפלס כנרת — daily Kinneret level since 1966.

Data: one row per survey date (daily since the 1990s, weekly/fortnightly
before), level in metres below sea level (negative). "Now" is always the
latest survey in the data, never the wall clock.

Thresholds are the Water Authority's operating lines (also quoted in the
dataset notes for the black line). They are policy constants, not data.
"""
import pandas as pd

UPPER_RED = -208.80   # קו אדום עליון
LOWER_RED = -213.00   # קו אדום תחתון
BLACK = -214.87       # קו שחור (המינימום הקבוע בחוק)

MONTHS_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי",
             "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר"]
RECENT_DAYS = 730          # daily-resolution window for the "recent" chart
SEASON_YEARS = 6           # hydrological years overlaid in the seasonal chart
SAME_DAY_TOLERANCE = 10    # days: a year counts for "same date" if measured this close
TABLE_ROWS = 20            # rows in the accessible table fallbacks


LRI, PDI = "⁦", "⁩"   # bidi isolate: keeps "-213.72" intact in RTL text


def m(v):
    """Level (metres, negative) for Hebrew prose."""
    return f"{LRI}{v:.2f}{PDI}"


def cm(delta):
    return f"{abs(delta) * 100:,.0f}"


def d_he(ts):
    return f"{ts.day} ב{MONTHS_HE[ts.month - 1]} {ts.year}"


def hy_label(hy):
    return f"{hy - 1}/{str(hy)[-2:]}"


def _prepare(df):
    out = pd.DataFrame({
        "d": pd.to_datetime(df["Survey_Date"], errors="coerce").dt.normalize(),
        "lvl": pd.to_numeric(df["Kinneret_Level"], errors="coerce"),
    }).dropna()
    # One value per date (stable: if CKAN ever duplicates a date, take the mean).
    out = out.groupby("d", as_index=False)["lvl"].mean().sort_values("d")
    out["hy"] = out["d"].dt.year + (out["d"].dt.month >= 10).astype(int)
    return out.reset_index(drop=True)


def _level_on_or_before(df, when, tolerance_days=SAME_DAY_TOLERANCE):
    s = df[df["d"] <= when]
    if s.empty:
        return None
    row = s.iloc[-1]
    if (when - row["d"]).days > tolerance_days:
        return None
    return row


def _zone(lvl):
    if lvl > UPPER_RED:
        return "above_upper"
    if lvl > LOWER_RED:
        return "between"
    if lvl > BLACK:
        return "below_lower"
    return "below_black"


def _winter_gains(df):
    """Per complete hydrological year: rise from the season's low (before the
    peak) to its peak. Only years with data in all 12 months count."""
    out = []
    for hy, g in df.groupby("hy"):
        if g["d"].dt.month.nunique() < 12:
            continue
        peak_i = g["lvl"].idxmax()
        low = g.loc[:peak_i, "lvl"].min()
        out.append((int(hy), float(g.loc[peak_i, "lvl"] - low)))
    return out


def insight_status(last):
    z, lvl = _zone(last["lvl"]), last["lvl"]
    when = d_he(last["d"])
    if z == "above_upper":
        return (f"נכון ל-{when} המפלס ({m(lvl)} מ') גבוה מהקו האדום העליון "
                f"ב-{cm(lvl - UPPER_RED)} ס״מ — מצב שבו נשקלת פתיחת סכר דגניה.")
    if z == "between":
        return (f"נכון ל-{when} המפלס ({m(lvl)} מ') נמצא בין הקווים האדומים: "
                f"{cm(lvl - LOWER_RED)} ס״מ מעל הקו האדום התחתון ו-{cm(UPPER_RED - lvl)} "
                f"ס״מ מתחת לקו האדום העליון.")
    if z == "below_lower":
        return (f"נכון ל-{when} המפלס ({m(lvl)} מ') נמוך מהקו האדום התחתון "
                f"ב-{cm(LOWER_RED - lvl)} ס״מ, ו-{cm(lvl - BLACK)} ס״מ מעל הקו השחור.")
    return f"נכון ל-{when} המפלס ({m(lvl)} מ') נמצא בקו השחור או מתחתיו — שפל היסטורי."


def insight_year_change(df, last):
    prev = _level_on_or_before(df, last["d"] - pd.Timedelta(days=365))
    if prev is None:
        return None
    delta = last["lvl"] - prev["lvl"]
    if abs(delta) < 0.05:
        return f"המפלס כמעט לא השתנה בשנה האחרונה (שינוי של {cm(delta)} ס״מ מאז {d_he(prev['d'])})."
    word = "עלה" if delta > 0 else "ירד"
    return f"בשנה האחרונה המפלס {word} ב-{cm(delta)} ס״מ (מ-{m(prev['lvl'])} מ' ב-{d_he(prev['d'])})."


def insight_same_date(df, last):
    """Where today's level ranks among the same calendar date in past years."""
    vals = []
    for y in sorted(df["d"].dt.year.unique()):
        if y >= last["d"].year:
            continue
        try:
            when = last["d"].replace(year=int(y))
        except ValueError:  # 29 Feb
            when = last["d"].replace(year=int(y), day=28)
        row = _level_on_or_before(df, when)
        if row is not None:
            vals.append(row["lvl"])
    if len(vals) < 10:
        return None
    higher = sum(v > last["lvl"] for v in vals)
    share = higher / len(vals)
    if share >= 0.5:
        return (f"המפלס הנוכחי נמוך מהמפלס שנמדד באותו תאריך ב-{higher} מתוך "
                f"{len(vals)} השנים הקודמות שיש להן מדידה ({share * 100:.0f}%).")
    lower = len(vals) - higher
    return (f"המפלס הנוכחי גבוה מהמפלס שנמדד באותו תאריך ב-{lower} מתוך "
            f"{len(vals)} השנים הקודמות שיש להן מדידה ({lower / len(vals) * 100:.0f}%).")


def insight_winter(gains):
    if len(gains) < 5:
        return None
    hy, last_gain = gains[-1]
    avg = sum(g for _, g in gains) / len(gains)
    best_hy, best = max(gains, key=lambda t: (t[1], t[0]))
    rel = "מעל" if last_gain > avg else "מתחת ל"
    return (f"בעונת {hy_label(hy)} עלה המפלס ב-{cm(last_gain)} ס״מ מהשפל לשיא — {rel}ממוצע "
            f"העונות המלאות ({cm(avg)} ס״מ). העלייה הגדולה ביותר נרשמה ב-{hy_label(best_hy)} "
            f"({cm(best)} ס״מ).")


def insight_records(df, last):
    lo = df.loc[df["lvl"].idxmin()]
    hi = df.loc[df["lvl"].idxmax()]
    return (f"השפל הנמוך ביותר במאגר: {m(lo['lvl'])} מ' ({d_he(lo['d'])}); השיא: "
            f"{m(hi['lvl'])} מ' ({d_he(hi['d'])}). המפלס כיום גבוה מהשפל "
            f"ב-{cm(last['lvl'] - lo['lvl'])} ס״מ.")


def insight_below_lower_years(df):
    years = sorted(int(y) for y, g in df.groupby(df["d"].dt.year) if (g["lvl"] <= LOWER_RED).any())
    if not years:
        return "המפלס לא ירד אל מתחת לקו האדום התחתון באף שנה במאגר."
    return (f"המפלס ירד אל מתחת לקו האדום התחתון ב-{len(years)} שנים במאגר, "
            f"האחרונה שבהן {years[-1]}.")


def compute(frames):
    df = _prepare(frames["levels"])
    last = df.iloc[-1]
    first = df.iloc[0]
    gains = _winter_gains(df)

    # Charts ------------------------------------------------------------
    monthly = (df.set_index("d")["lvl"].resample("MS").mean().dropna())
    history = {"x": [d.strftime("%Y-%m") for d in monthly.index],
               "y": [round(float(v), 3) for v in monthly]}

    recent_df = df[df["d"] > last["d"] - pd.Timedelta(days=RECENT_DAYS)]
    recent = {"x": [d.strftime("%Y-%m-%d") for d in recent_df["d"]],
              "y": [round(float(v), 3) for v in recent_df["lvl"]]}

    # Seasonal overlay: weekly level by week of hydrological year.
    df["wk"] = ((df["d"] - pd.to_datetime((df["hy"] - 1).astype(str) + "-10-01")).dt.days // 7).clip(0, 52)
    weekly = df.groupby(["hy", "wk"])["lvl"].mean()
    season_hys = sorted(df["hy"].unique())[-SEASON_YEARS:]
    season = {
        "weeks": list(range(53)),
        "series": [
            {"name": hy_label(int(hy)),
             "data": [round(float(weekly.get((hy, w))), 3) if (hy, w) in weekly.index else None
                      for w in range(53)]}
            for hy in season_hys
        ],
    }
    full_hys = [hy for hy, _ in gains]
    med = (weekly[weekly.index.get_level_values(0).isin(full_hys)]
           .groupby(level=1).median())
    season["median"] = [round(float(med.get(w)), 3) if w in med.index else None for w in range(53)]
    season["median_label"] = (f"חציון {hy_label(full_hys[0])}–{hy_label(full_hys[-1])}"
                              if full_hys else "")

    gains_chart = {"x": [hy_label(hy) for hy, _ in gains],
                   "y": [round(g * 100) for _, g in gains]}

    heat_src = monthly.to_frame("lvl")
    heat_years = sorted({d.year for d in heat_src.index})
    heat = {
        "years": [str(y) for y in heat_years],
        "months": MONTHS_HE,
        "cells": [[heat_years.index(d.year), d.month - 1, round(float(v), 2)]
                  for d, v in heat_src["lvl"].items()],
        "min": round(float(monthly.min()), 2),
        "max": round(float(monthly.max()), 2),
    }

    yearly = df.groupby(df["d"].dt.year)["lvl"].agg(["min", "max", "mean", "count"])
    table_years = [
        {"year": str(int(y)), "min": m(r["min"]), "max": m(r["max"]),
         "mean": m(r["mean"]), "n": f"{int(r['count']):,}"}
        for y, r in yearly.tail(TABLE_ROWS).iterrows()
    ]
    annual = {"x": [str(int(y)) for y in yearly.index],
              "min": [round(float(v), 3) for v in yearly["min"]],
              "max": [round(float(v), 3) for v in yearly["max"]],
              "mean": [round(float(v), 3) for v in yearly["mean"]]}

    # Share of each year's measurements at or below the lower red line.
    # A share, not a day count: measurement frequency changed from
    # weekly/fortnightly to daily in the 1990s.
    below = (df.assign(b=df["lvl"] <= LOWER_RED)
             .groupby(df["d"].dt.year)["b"].mean())
    below_chart = {"x": [str(int(y)) for y in below.index],
                   "y": [round(float(v) * 100, 1) for v in below]}
    table_below = [{"year": str(int(y)), "share": f"{v * 100:.0f}"}
                   for y, v in below.items() if v > 0]

    # Seasonal table: monthly mean per hydrological month for the overlaid
    # seasons + the median of complete seasons (12 rows).
    hy_month_order = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    mm = df.groupby(["hy", df["d"].dt.month])["lvl"].mean()
    med_m = (mm[mm.index.get_level_values(0).isin(full_hys)]
             .groupby(level=1).median())
    season_table = {
        "cols": [hy_label(int(hy)) for hy in season_hys] + ["חציון"],
        "rows": [
            {"month": MONTHS_HE[mo - 1],
             "vals": [(m(mm[(hy, mo)]) if (hy, mo) in mm.index else "—") for hy in season_hys]
                     + [m(med_m[mo]) if mo in med_m.index else "—"]}
            for mo in hy_month_order
        ],
    }
    table_gains = [{"season": hy_label(hy), "gain": f"{g * 100:,.0f}"}
                   for hy, g in gains[-TABLE_ROWS:]]

    # Insights ----------------------------------------------------------
    rules = [
        ("status", insight_status(last)),
        ("year_change", insight_year_change(df, last)),
        ("same_date", insight_same_date(df, last)),
        ("winter", insight_winter(gains)),
        ("below_lower", insight_below_lower_years(df)),
        ("records", insight_records(df, last)),
    ]
    insights = [{"id": i, "text_he": t} for i, t in rules if t]

    # KPIs --------------------------------------------------------------
    d30 = _level_on_or_before(df, last["d"] - pd.Timedelta(days=30))
    d365 = _level_on_or_before(df, last["d"] - pd.Timedelta(days=365))

    def signed_cm(delta):
        # KPI value: bare signed number, U+2212 minus; units live in the label.
        sign = "+" if delta > 0 else "−" if delta < 0 else ""
        return f"{sign}{cm(delta)}"

    def change_tone(delta, warn_at, danger_at):
        # Falling is the bad direction for the lake.
        if delta is None:
            return "brand"
        if delta <= -danger_at:
            return "danger"
        if delta <= -warn_at:
            return "warn"
        if delta >= warn_at:
            return "ok"
        return "brand"

    zone_label = {
        "above_upper": "מעל הקו האדום העליון",
        "between": "בין הקווים האדומים",
        "below_lower": "מתחת לקו האדום התחתון",
        "below_black": "בקו השחור או מתחתיו",
    }[_zone(last["lvl"])]

    zone = _zone(last["lvl"])
    # Level colour follows the operating lines: healthy between them, alarm
    # below the lower red line, notable (flood management) above the upper.
    zone_tone = {"above_upper": "info", "between": "ok",
                 "below_lower": "danger", "below_black": "danger"}[zone]
    d30_delta = None if d30 is None else float(last["lvl"] - d30["lvl"])
    d365_delta = None if d365 is None else float(last["lvl"] - d365["lvl"])
    to_red = float(last["lvl"] - LOWER_RED)
    kpis = {
        "level": {"value": float(last["lvl"]),
                  "display": f"{last['lvl']:.2f}".replace("-", "−"), "tone": zone_tone},
        "as_of": {"value": last["d"].strftime("%Y-%m-%d"), "display": d_he(last["d"])},
        "zone": {"value": zone, "display": zone_label},
        "to_lower_red": {"value": to_red, "display": signed_cm(to_red),
                         "tone": "ok" if to_red >= 0 else "danger"},
        "d30": {"value": d30_delta,
                "display": "—" if d30_delta is None else signed_cm(d30_delta),
                "tone": change_tone(d30_delta, 0.05, 0.25)},
        "d365": {"value": d365_delta,
                 "display": "—" if d365_delta is None else signed_cm(d365_delta),
                 "tone": change_tone(d365_delta, 0.10, 0.50)},
    }
    as_of_num = f"{last['d'].day}.{last['d'].month}.{last['d'].year}"
    kpi_labels = {
        "level": f"מפלס נוכחי, מ' יחסית לפני הים ({as_of_num})",
        "to_lower_red": f"ס״מ ביחס לקו האדום התחתון — {zone_label}",
        "d30": "שינוי בחודש האחרון (ס״מ)",
        "d365": "שינוי בשנה האחרונה (ס״מ)",
    }

    lines = {
        "upper": UPPER_RED, "lower": LOWER_RED, "black": BLACK,
        # Canvas labels: no bidi isolates (some fonts draw them as boxes).
        "upper_label": f"קו אדום עליון {UPPER_RED:.2f}",
        "lower_label": f"קו אדום תחתון {LOWER_RED:.2f}",
        "black_label": f"קו שחור {BLACK:.2f}",
    }

    y0, y1 = int(first["d"].year), int(last["d"].year)
    labels = {
        "lede": (f"מדידות מפלס הכנרת מ-{d_he(first['d'])} ועד {d_he(last['d'])} — "
                 f"{len(df):,} ימי מדידה. המדידה האחרונה: {m(last['lvl'])} מ', {zone_label}."),
        "history_aria": (f"גרף קו: ממוצע חודשי של מפלס הכנרת, {y0} עד {y1}, עם הקווים "
                         f"האדומים והקו השחור."),
        "history_note": (f"ממוצעים חודשיים של {len(df):,} מדידות. עד שנות ה-90 המדידות "
                         f"היו שבועיות או דו-שבועיות; ממוצע חודשי מחליק את ההבדל."),
        "recent_aria": (f"גרף קו: מפלס יומי בשנתיים האחרונות, עד {d_he(last['d'])}."),
        "season_aria": (f"גרף קווים: המפלס לפי שבוע בשנה ההידרולוגית (אוקטובר עד ספטמבר) "
                        f"ב-{len(season_hys)} העונות האחרונות לעומת החציון."),
        "gains_aria": (f"תרשים עמודות: העלייה במפלס מהשפל לשיא בכל אחת מ-{len(gains)} "
                       f"העונות המלאות במאגר."),
        "gains_note": ("עונה = שנה הידרולוגית (אוקטובר–ספטמבר). נכללות רק עונות עם מדידות "
                       "בכל 12 החודשים."),
        "heat_aria": f"מפת חום: ממוצע חודשי של המפלס לפי חודש ושנה, {y0} עד {y1}.",
        "table_caption": f"מפלס מינימלי, מקסימלי וממוצע ב-{len(table_years)} השנים האחרונות.",
        "annual_aria": (f"גרף: טווח המפלס בכל שנה — מינימום, ממוצע ומקסימום — "
                        f"בשנים {y0} עד {y1}."),
        "below_aria": (f"תרשים עמודות: שיעור המדידות בכל שנה שבהן המפלס היה בקו האדום "
                       f"התחתון או מתחתיו, {y0} עד {y1}."),
        "below_caption": (f"השנים שבהן לפחות חלק מהמדידות היו בקו האדום התחתון או מתחתיו "
                          f"({len(table_below)} שנים)."),
        "season_caption": "ממוצע חודשי של המפלס בעונות האחרונות לעומת החציון של העונות המלאות.",
        "gains_caption": f"העלייה במפלס מהשפל לשיא ב-{len(table_gains)} העונות המלאות האחרונות (ס״מ).",
    }

    return {
        "agent_data": {
            "summary_he": (f"מפלס הכנרת היומי מ-{y0} ועד {d_he(last['d'])}: "
                           f"{len(df):,} מדידות. המפלס האחרון, {m(last['lvl'])} מ', "
                           f"{zone_label}."),
            "dataset_kind": "timeseries",
            "related_ids": [
                "ebf0005b-f5fe-4c6c-ab6d-28778167d025",
                "83aba0a3-dc03-48a4-87eb-74af55b0cc5e",
                "e81d14bd-a81d-4de4-b1de-d7a0541ace02",
            ],
            "suggested_tags": ["מפלס מים", "כנרת", "הידרומטריה", "משאבי מים"],
            "temporal_coverage": f"{first['d'].strftime('%Y-%m-%d')}/{last['d'].strftime('%Y-%m-%d')}",
            "spatial_coverage": "כנרת",
        },
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "lines": lines,
        "charts": {
            "history": history,
            "recent": recent,
            "season": season,
            "gains": gains_chart,
            "annual": annual,
            "below": below_chart,
            "heat": heat,
        },
        "tables": {"years": table_years, "below": table_below,
                   "season": season_table, "gains": table_gains},
        "insights": insights,
        "labels": labels,
    }
